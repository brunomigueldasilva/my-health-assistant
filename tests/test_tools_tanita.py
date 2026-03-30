"""
Tests for tools/tanita_tools.py

Covers private helpers (_safe_float, _safe_int, _parse_date, _parse_csv,
_insert_rows), the public sync/history tools, and all 9 educational tools.
ChromaDB and Playwright are never touched — SQLite is redirected to a temp file.
"""

import sqlite3
from unittest.mock import patch
import pytest

from tools.tanita_tools import (
    _safe_float,
    _safe_int,
    _parse_date,
    _parse_csv,
    _insert_rows,
    get_body_composition_history,
    sync_tanita_measurements,
    get_weight_measurement_info,
    get_body_water_info,
    get_body_fat_info,
    get_bmi_info,
    get_visceral_fat_info,
    get_muscle_mass_info,
    get_bone_mass_info,
    get_bmr_info,
    get_metabolic_age_info,
)

# ── Sample CSV content ────────────────────────────────────────────────────────

COMMA_CSV = (
    "Date,Weight (kg),BMI,Body Fat (%),Visc Fat,Muscle Mass (kg),"
    "Bone Mass (kg),BMR (kcal),Metab Age,Body Water (%)\n"
    "19/06/2019 09:20,75.5,23.4,18.2,7,32.1,2.8,1750,30,58.3\n"
)

SEMICOLON_CSV = (
    "Date;Weight (kg);BMI;Body Fat (%)\n"
    "19/06/2019 09:20;75,5;23,4;18,2\n"
)

MULTI_ROW_CSV = (
    "Date,Weight (kg)\n"
    "19/06/2019 09:20,75.5\n"
    "20/06/2019 09:20,75.3\n"
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_tanita_db(tmp_path, monkeypatch):
    """Redirect tanita SQLITE_DB to a temp file and pre-create weight_history."""
    db_path = tmp_path / "test_tanita.db"
    monkeypatch.setattr("tools.tanita_tools.SQLITE_DB", db_path)
    # weight_history must exist before _get_db() tries to create the unique index on it
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """CREATE TABLE IF NOT EXISTS weight_history (
               id          INTEGER PRIMARY KEY AUTOINCREMENT,
               user_id     TEXT NOT NULL,
               weight_kg   REAL,
               recorded_at TEXT NOT NULL,
               UNIQUE(user_id, recorded_at)
           )"""
    )
    conn.commit()
    conn.close()
    return db_path


@pytest.fixture
def mem_db():
    """In-memory SQLite with body_composition_history + weight_history tables."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE body_composition_history (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id         TEXT    NOT NULL,
            measured_at     TEXT    NOT NULL,
            weight_kg       REAL,
            bmi             REAL,
            body_fat_pct    REAL,
            visceral_fat    REAL,
            muscle_mass_kg  REAL,
            muscle_quality  REAL,
            bone_mass_kg    REAL,
            bmr_kcal        REAL,
            metabolic_age   INTEGER,
            body_water_pct  REAL,
            physique_rating INTEGER,
            UNIQUE(user_id, measured_at)
        );
        CREATE TABLE weight_history (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     TEXT NOT NULL,
            weight_kg   REAL,
            recorded_at TEXT NOT NULL,
            UNIQUE(user_id, recorded_at)
        );
        """
    )
    conn.commit()
    yield conn
    conn.close()


# ── _safe_float ───────────────────────────────────────────────────────────────

class TestSafeFloat:
    def test_normal_float(self):
        assert _safe_float("3.14") == pytest.approx(3.14)

    def test_comma_decimal_separator(self):
        assert _safe_float("1,5") == pytest.approx(1.5)

    def test_integer_string(self):
        assert _safe_float("42") == pytest.approx(42.0)

    def test_empty_string_returns_none(self):
        assert _safe_float("") is None

    def test_invalid_string_returns_none(self):
        assert _safe_float("abc") is None

    def test_none_value_returns_none(self):
        assert _safe_float(None) is None

    def test_whitespace_stripped(self):
        assert _safe_float("  2.5  ") == pytest.approx(2.5)


# ── _safe_int ─────────────────────────────────────────────────────────────────

class TestSafeInt:
    def test_integer_string(self):
        assert _safe_int("25") == 25

    def test_float_string_truncated(self):
        assert _safe_int("25.9") == 25

    def test_comma_decimal_separator(self):
        assert _safe_int("3,0") == 3

    def test_empty_string_returns_none(self):
        assert _safe_int("") is None

    def test_invalid_string_returns_none(self):
        assert _safe_int("xyz") is None

    def test_none_value_returns_none(self):
        assert _safe_int(None) is None


# ── _parse_date ───────────────────────────────────────────────────────────────

class TestParseDate:
    def test_dd_mm_yyyy_hh_mm(self):
        assert _parse_date("19/06/2019 09:20") == "2019-06-19 09:20:00"

    def test_dd_mm_yyyy_hh_mm_ss(self):
        assert _parse_date("19/06/2019 09:20:30") == "2019-06-19 09:20:30"

    def test_iso_datetime(self):
        assert _parse_date("2024-01-15 08:30:00") == "2024-01-15 08:30:00"

    def test_iso_datetime_T_separator(self):
        assert _parse_date("2024-01-15T08:30:00") == "2024-01-15 08:30:00"

    def test_dd_mm_yyyy_dash_separator(self):
        assert _parse_date("15-01-2024 08:30") == "2024-01-15 08:30:00"

    def test_mm_dd_yyyy(self):
        assert _parse_date("01/15/2024 08:30") == "2024-01-15 08:30:00"

    def test_unknown_format_returned_as_is(self):
        assert _parse_date("2024.01.15") == "2024.01.15"

    def test_strips_whitespace(self):
        assert _parse_date("  19/06/2019 09:20  ") == "2019-06-19 09:20:00"


# ── _parse_csv ────────────────────────────────────────────────────────────────

class TestParseCsv:
    def test_comma_delimited(self):
        rows = _parse_csv(COMMA_CSV, "user1")
        assert len(rows) == 1
        row = rows[0]
        assert row["user_id"] == "user1"
        assert row["measured_at"] == "2019-06-19 09:20:00"
        assert row["weight_kg"] == pytest.approx(75.5)
        assert row["bmi"] == pytest.approx(23.4)
        assert row["body_fat_pct"] == pytest.approx(18.2)
        assert row["metabolic_age"] == 30
        assert row["body_water_pct"] == pytest.approx(58.3)

    def test_semicolon_delimited(self):
        rows = _parse_csv(SEMICOLON_CSV, "user2")
        assert len(rows) == 1
        assert rows[0]["weight_kg"] == pytest.approx(75.5)
        assert rows[0]["bmi"] == pytest.approx(23.4)

    def test_rows_without_date_are_skipped(self):
        csv_no_date = "Weight (kg),BMI\n75.5,23.4\n"
        rows = _parse_csv(csv_no_date, "user1")
        assert rows == []

    def test_empty_csv_returns_empty_list(self):
        rows = _parse_csv("", "user1")
        assert rows == []

    def test_multiple_rows_parsed(self):
        rows = _parse_csv(MULTI_ROW_CSV, "user1")
        assert len(rows) == 2

    def test_integer_columns_converted(self):
        csv = "Date,Metab Age,Physique Rating\n19/06/2019 09:20,30,5\n"
        rows = _parse_csv(csv, "user1")
        assert rows[0]["metabolic_age"] == 30
        assert rows[0]["physique_rating"] == 5

    def test_user_id_injected_in_every_row(self):
        rows = _parse_csv(MULTI_ROW_CSV, "u42")
        assert all(r["user_id"] == "u42" for r in rows)


# ── _insert_rows ──────────────────────────────────────────────────────────────

class TestInsertRows:
    def test_inserts_single_row(self, mem_db):
        rows = [{"user_id": "u1", "measured_at": "2024-01-01 08:00:00", "weight_kg": 75.0}]
        inserted, skipped = _insert_rows(mem_db, rows)
        assert inserted == 1
        assert skipped == 0

    def test_skips_duplicate(self, mem_db):
        rows = [{"user_id": "u1", "measured_at": "2024-01-01 08:00:00", "weight_kg": 75.0}]
        _insert_rows(mem_db, rows)
        inserted, skipped = _insert_rows(mem_db, rows)
        assert inserted == 0
        assert skipped == 1

    def test_mirrors_weight_to_weight_history(self, mem_db):
        rows = [{"user_id": "u1", "measured_at": "2024-01-01 08:00:00", "weight_kg": 75.0}]
        _insert_rows(mem_db, rows)
        wh = mem_db.execute(
            "SELECT * FROM weight_history WHERE user_id='u1'"
        ).fetchall()
        assert len(wh) == 1
        assert wh[0]["weight_kg"] == pytest.approx(75.0)

    def test_no_weight_mirror_when_weight_absent(self, mem_db):
        rows = [{"user_id": "u1", "measured_at": "2024-01-01 08:00:00", "bmi": 23.0}]
        _insert_rows(mem_db, rows)
        wh = mem_db.execute(
            "SELECT * FROM weight_history WHERE user_id='u1'"
        ).fetchall()
        assert len(wh) == 0

    def test_mixed_new_and_duplicate_rows(self, mem_db):
        row_a = {"user_id": "u1", "measured_at": "2024-01-01 08:00:00", "weight_kg": 75.0}
        row_b = {"user_id": "u1", "measured_at": "2024-01-02 08:00:00", "weight_kg": 74.8}
        _insert_rows(mem_db, [row_a])
        inserted, skipped = _insert_rows(mem_db, [row_a, row_b])
        assert inserted == 1
        assert skipped == 1


# ── get_body_composition_history ──────────────────────────────────────────────

class TestGetBodyCompositionHistory:
    def test_no_data_returns_fallback(self, tmp_tanita_db):
        result = get_body_composition_history("unknown_user")
        assert "Sem dados" in result
        assert "/tanita" in result

    def test_returns_formatted_metrics(self, tmp_tanita_db):
        from tools.tanita_tools import _get_db
        conn = _get_db()
        conn.execute(
            """INSERT INTO body_composition_history
               (user_id, measured_at, weight_kg, bmi, body_fat_pct, visceral_fat,
                muscle_mass_kg, bone_mass_kg, bmr_kcal, metabolic_age, body_water_pct)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            ("u1", "2024-01-15 08:30:00", 75.5, 23.4, 18.2, 7, 32.1, 2.8, 1750, 30, 58.3),
        )
        conn.commit()
        conn.close()

        result = get_body_composition_history("u1")
        assert "2024-01-15 08:30" in result
        assert "75.50 kg" in result
        assert "23.4" in result
        assert "18.2%" in result
        assert "1750" in result
        assert "30 anos" in result

    def test_weight_trend_shown_for_multiple_entries(self, tmp_tanita_db):
        from tools.tanita_tools import _get_db
        conn = _get_db()
        conn.executemany(
            "INSERT INTO body_composition_history (user_id, measured_at, weight_kg) VALUES (?,?,?)",
            [
                ("u2", "2024-01-01 08:00:00", 80.0),
                ("u2", "2024-01-15 08:00:00", 78.0),
            ],
        )
        conn.commit()
        conn.close()

        result = get_body_composition_history("u2")
        assert "Variação de peso" in result

    def test_limit_restricts_number_of_entries(self, tmp_tanita_db):
        from tools.tanita_tools import _get_db
        conn = _get_db()
        for i in range(15):
            conn.execute(
                "INSERT INTO body_composition_history (user_id, measured_at, weight_kg) VALUES (?,?,?)",
                ("u3", f"2024-01-{i + 1:02d} 08:00:00", 75.0 + i * 0.1),
            )
        conn.commit()
        conn.close()

        result = get_body_composition_history("u3", limit=5)
        assert "últimas 5 medições" in result

    def test_limit_capped_at_50(self, tmp_tanita_db):
        """Requesting more than 50 should silently cap at 50."""
        result = get_body_composition_history("nobody", limit=200)
        # No crash, returns fallback (no data)
        assert "Sem dados" in result


# ── sync_tanita_measurements ──────────────────────────────────────────────────

class TestSyncTanitaMeasurements:
    def test_missing_credentials_returns_error(self, monkeypatch):
        monkeypatch.setattr("tools.tanita_tools.USER_TANITA", "")
        monkeypatch.setattr("tools.tanita_tools.PASS_TANITA", "")
        result = sync_tanita_measurements("user1")
        assert "❌" in result
        assert "USER_TANITA" in result

    def test_playwright_exception_returns_error(self, monkeypatch, tmp_tanita_db):
        monkeypatch.setattr("tools.tanita_tools.USER_TANITA", "user@test.com")
        monkeypatch.setattr("tools.tanita_tools.PASS_TANITA", "secret")
        with patch(
            "tools.tanita_tools._download_csv_via_playwright",
            side_effect=RuntimeError("Network error"),
        ):
            result = sync_tanita_measurements("user1")
        assert "❌" in result
        assert "Network error" in result

    def test_empty_csv_returns_warning(self, monkeypatch, tmp_tanita_db):
        monkeypatch.setattr("tools.tanita_tools.USER_TANITA", "user@test.com")
        monkeypatch.setattr("tools.tanita_tools.PASS_TANITA", "secret")
        with patch(
            "tools.tanita_tools._download_csv_via_playwright", return_value=""
        ):
            result = sync_tanita_measurements("user1")
        assert "⚠️" in result
        assert "CSV" in result

    def test_successful_sync_reports_inserted_count(self, monkeypatch, tmp_tanita_db):
        monkeypatch.setattr("tools.tanita_tools.USER_TANITA", "user@test.com")
        monkeypatch.setattr("tools.tanita_tools.PASS_TANITA", "secret")
        with patch(
            "tools.tanita_tools._download_csv_via_playwright", return_value=COMMA_CSV
        ):
            result = sync_tanita_measurements("user1")
        assert "✅" in result
        assert "1 nova(s) medição(ões)" in result

    def test_second_sync_reports_duplicates_skipped(self, monkeypatch, tmp_tanita_db):
        monkeypatch.setattr("tools.tanita_tools.USER_TANITA", "user@test.com")
        monkeypatch.setattr("tools.tanita_tools.PASS_TANITA", "secret")
        with patch(
            "tools.tanita_tools._download_csv_via_playwright", return_value=COMMA_CSV
        ):
            sync_tanita_measurements("user1")
            result = sync_tanita_measurements("user1")
        assert "0 nova(s)" in result
        assert "1 duplicado(s)" in result

    def test_user_id_coerced_to_string(self, monkeypatch, tmp_tanita_db):
        """Integer user_id should not raise."""
        monkeypatch.setattr("tools.tanita_tools.USER_TANITA", "user@test.com")
        monkeypatch.setattr("tools.tanita_tools.PASS_TANITA", "secret")
        with patch(
            "tools.tanita_tools._download_csv_via_playwright", return_value=COMMA_CSV
        ):
            result = sync_tanita_measurements(12345)
        assert "✅" in result


# ── Educational tools ─────────────────────────────────────────────────────────

class TestEducationalTools:
    def test_weight_measurement_info(self):
        r = get_weight_measurement_info()
        assert "⚖️" in r
        assert "Peso Corporal" in r

    def test_body_water_info_includes_ranges(self):
        r = get_body_water_info()
        assert "💧" in r
        assert "Água Corporal" in r
        assert "Feminino" in r
        assert "Masculino" in r

    def test_body_fat_info_includes_healthy_ranges(self):
        r = get_body_fat_info()
        assert "🫀" in r
        assert "Gordura Corporal" in r
        assert "20" in r   # 20–35 % female range

    def test_bmi_info(self):
        r = get_bmi_info()
        assert "📐" in r
        assert "IMC" in r

    def test_visceral_fat_info(self):
        r = get_visceral_fat_info()
        assert "🔴" in r
        assert "Gordura Visceral" in r

    def test_muscle_mass_info(self):
        r = get_muscle_mass_info()
        assert "💪" in r
        assert "Massa Muscular" in r

    def test_bone_mass_info(self):
        r = get_bone_mass_info()
        assert "🦴" in r
        assert "Massa Óssea" in r

    def test_bmr_info_includes_warning(self):
        r = get_bmr_info()
        assert "🔥" in r
        assert "Taxa Metabólica Basal" in r
        assert "⚠️" in r

    def test_metabolic_age_info(self):
        r = get_metabolic_age_info()
        assert "🕐" in r
        assert "Idade Metabólica" in r
