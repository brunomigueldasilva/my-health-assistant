"""
Tests for tools/profile_tools.py

Uses tmp_db fixture to redirect SQLite to a temporary path,
and mock_kb_profile to avoid ChromaDB initialisation.
"""

import json
import pytest
from tools.profile_tools import (
    update_user_profile,
    get_user_profile,
    get_weight_history,
    add_allergy,
    add_food_preference,
    add_health_goal,
    export_user_data,
    delete_all_user_data,
)


# ── update_user_profile ───────────────────────────────────────────────────────

class TestUpdateUserProfile:

    def test_creates_new_profile(self, tmp_db, mock_kb_profile):
        result = update_user_profile(
            user_id="1001", name="Ana", birth_date="1996-03-30", gender="female",
            height_cm=165.0, weight_kg=60.0, activity_level="moderate",
            goal="lose_weight",
        )
        assert "✅" in result
        assert "nome" in result
        assert "peso" in result

    def test_updates_existing_profile_partial_fields(self, tmp_db, mock_kb_profile):
        update_user_profile(user_id="1002", name="Bruno", birth_date="1998-03-30", weight_kg=75.0)
        result = update_user_profile(user_id="1002", weight_kg=74.0)
        assert "✅" in result
        assert "peso" in result
        # Fields not passed should not appear in confirmation
        assert "nome" not in result

    def test_weight_logged_on_update(self, tmp_db, mock_kb_profile):
        update_user_profile(user_id="1003", weight_kg=80.0)
        update_user_profile(user_id="1003", weight_kg=79.5)
        history = get_weight_history("1003")
        assert "80.0 kg" in history
        assert "79.5 kg" in history

    def test_returns_updated_field_names_in_portuguese(self, tmp_db, mock_kb_profile):
        result = update_user_profile(
            user_id="1004", birth_date="2001-03-30", height_cm=178.0, activity_level="active"
        )
        assert "data nasc." in result
        assert "altura" in result
        assert "atividade" in result


# ── get_user_profile ──────────────────────────────────────────────────────────

class TestGetUserProfile:

    def test_returns_profile_for_existing_user(self, tmp_db, mock_kb_profile):
        from datetime import date
        birth_date = "1991-03-30"
        bd = date(1991, 3, 30)
        today = date.today()
        expected_age = today.year - bd.year - ((today.month, today.day) < (bd.month, bd.day))
        update_user_profile(
            user_id="2001", name="Carlos", birth_date=birth_date, gender="male",
            height_cm=180.0, weight_kg=82.0, activity_level="active",
            goal="gain_muscle",
        )
        result = get_user_profile("2001")
        assert "Carlos" in result
        assert str(expected_age) in result
        assert "82.0 kg" in result

    def test_returns_warning_for_unknown_user(self, tmp_db, mock_kb_profile):
        result = get_user_profile("user_that_does_not_exist")
        assert "⚠️" in result
        assert "Perfil não configurado" in result

    def test_includes_preferences_section(self, tmp_db, mock_kb_profile):
        mock_kb_profile.get_user_profile_summary.return_value = "Gosta de: frango"
        update_user_profile(user_id="2002", name="Diana")
        result = get_user_profile("2002")
        assert "Preferências" in result
        assert "frango" in result


# ── get_weight_history ────────────────────────────────────────────────────────

class TestGetWeightHistory:

    def test_returns_no_history_message_when_empty(self, tmp_db, mock_kb_profile):
        result = get_weight_history("9999")
        assert "Sem histórico" in result

    def test_returns_all_logged_weights(self, tmp_db, mock_kb_profile):
        update_user_profile(user_id="3001", weight_kg=85.0)
        update_user_profile(user_id="3001", weight_kg=84.0)
        update_user_profile(user_id="3001", weight_kg=83.5)
        result = get_weight_history("3001")
        assert "85.0 kg" in result
        assert "84.0 kg" in result
        assert "83.5 kg" in result

    def test_shows_weight_variation_when_multiple_entries(self, tmp_db, mock_kb_profile):
        update_user_profile(user_id="3002", weight_kg=90.0)
        update_user_profile(user_id="3002", weight_kg=88.0)
        result = get_weight_history("3002")
        assert "Variação:" in result

    def test_variation_icon_down_when_weight_decreased(self, tmp_db, mock_kb_profile):
        update_user_profile(user_id="3003", weight_kg=80.0)
        update_user_profile(user_id="3003", weight_kg=78.0)
        result = get_weight_history("3003")
        assert "⬇️" in result

    def test_variation_icon_up_when_weight_increased(self, tmp_db, mock_kb_profile):
        update_user_profile(user_id="3004", weight_kg=70.0)
        update_user_profile(user_id="3004", weight_kg=72.0)
        result = get_weight_history("3004")
        assert "⬆️" in result


# ── add_allergy ───────────────────────────────────────────────────────────────

class TestAddAllergy:

    def test_registers_allergy_in_chromadb(self, tmp_db, mock_kb_profile):
        result = add_allergy("8001", "lactose")
        assert "⚠️" in result
        assert "lactose" in result
        mock_kb_profile.add_preference.assert_called_once()
        call_args = mock_kb_profile.add_preference.call_args
        assert call_args[0][0] == "8001"
        assert call_args[0][1] == "allergies"
        assert call_args[0][2] == "lactose"

    def test_metadata_type_is_allergy(self, tmp_db, mock_kb_profile):
        add_allergy("8002", "glúten")
        call_args = mock_kb_profile.add_preference.call_args
        metadata = call_args[0][3]
        assert metadata["type"] == "allergy"
        assert "created" in metadata

    def test_user_id_coerced_to_string(self, tmp_db, mock_kb_profile):
        add_allergy(8003, "amendoim")
        call_args = mock_kb_profile.add_preference.call_args
        assert call_args[0][0] == "8003"


# ── add_food_preference ───────────────────────────────────────────────────────

class TestAddFoodPreference:

    def test_like_records_positive_sentiment(self, tmp_db, mock_kb_profile):
        result = add_food_preference("4001", "frango", likes=True)
        assert "👍" in result
        assert "frango" in result
        mock_kb_profile.add_preference.assert_called_once()
        call_kwargs = mock_kb_profile.add_preference.call_args
        assert call_kwargs[0][1] == "food_likes"

    def test_dislike_records_negative_sentiment(self, tmp_db, mock_kb_profile):
        result = add_food_preference("4002", "beterraba", likes=False)
        assert "👎" in result
        assert "beterraba" in result
        call_kwargs = mock_kb_profile.add_preference.call_args
        assert call_kwargs[0][1] == "food_dislikes"


# ── add_health_goal ───────────────────────────────────────────────────────────

class TestAddHealthGoal:

    def test_records_goal_in_chromadb_and_sqlite(self, tmp_db, mock_kb_profile):
        update_user_profile(user_id="5001", name="Eva")
        result = add_health_goal("5001", "perder 5kg em 3 meses")
        assert "🎯" in result
        assert "perder 5kg" in result
        mock_kb_profile.add_preference.assert_called_once()


# ── export_user_data (GDPR Art. 20) ──────────────────────────────────────────

class TestExportUserData:

    def test_export_contains_required_gdpr_fields(self, tmp_db, mock_kb_profile):
        update_user_profile(
            user_id="6001", name="Fábio", birth_date="1986-03-30",
            weight_kg=90.0, goal="maintain",
        )
        raw = export_user_data("6001")
        data = json.loads(raw)
        assert "export_date" in data
        assert "gdpr_basis" in data
        assert "profile" in data
        assert "weight_history" in data
        assert "preferences" in data

    def test_export_includes_weight_history(self, tmp_db, mock_kb_profile):
        update_user_profile(user_id="6002", weight_kg=75.0)
        update_user_profile(user_id="6002", weight_kg=74.0)
        raw = export_user_data("6002")
        data = json.loads(raw)
        weights = [e["weight_kg"] for e in data["weight_history"]]
        assert 75.0 in weights
        assert 74.0 in weights

    def test_export_unknown_user_returns_empty_profile(self, tmp_db, mock_kb_profile):
        raw = export_user_data("user_never_created")
        data = json.loads(raw)
        assert data["profile"] == {}


# ── delete_all_user_data (GDPR Art. 17) ──────────────────────────────────────

class TestDeleteAllUserData:

    def test_deletes_profile_and_weight_history(self, tmp_db, mock_kb_profile):
        update_user_profile(user_id="7001", name="Gina", weight_kg=65.0)
        delete_all_user_data("7001")
        # Profile should be gone
        profile = get_user_profile("7001")
        assert "⚠️" in profile
        # Weight history should be empty
        history = get_weight_history("7001")
        assert "Sem histórico" in history

    def test_returns_confirmation_message(self, tmp_db, mock_kb_profile):
        update_user_profile(user_id="7002", name="Hugo")
        result = delete_all_user_data("7002")
        assert "✅" in result
        assert "eliminados permanentemente" in result
        assert "RGPD Art. 17" in result

    def test_deletes_chromadb_preferences(self, tmp_db, mock_kb_profile):
        mock_kb_profile.preferences.get.return_value = {
            "ids": ["pref-1", "pref-2"],
            "documents": ["frango", "arroz"],
        }
        update_user_profile(user_id="7003", name="Inês")
        delete_all_user_data("7003")
        mock_kb_profile.preferences.delete.assert_called()
        # Verify the correct IDs were passed to delete
        delete_calls = mock_kb_profile.preferences.delete.call_args_list
        deleted_ids = [c.kwargs["ids"] for c in delete_calls if c.kwargs.get("ids")]
        assert ["pref-1", "pref-2"] in deleted_ids
