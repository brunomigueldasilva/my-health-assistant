"""
Tanita Tools — sync body composition data from MyTanita scale portal.

Automates login to mytanita.eu, downloads the measurements CSV,
parses all body composition fields, and stores them without duplicates.
"""

import csv
import io
import logging
import os
import sqlite3
from datetime import datetime
from typing import Optional

from config import SQLITE_DB
from xai import xai_tool

logger = logging.getLogger(__name__)

TANITA_LOGIN_URL = "https://mytanita.eu/en/user/login"
USER_TANITA = os.getenv("USER_TANITA", "")
PASS_TANITA = os.getenv("PASS_TANITA", "")

# Map CSV column headers to DB column names.
# Multiple variants handle regional/version differences in the export.
_COLUMN_MAP: dict[str, str] = {
    # Date variants
    "Date": "measured_at",
    "date": "measured_at",
    "Date/Time": "measured_at",
    # Weight
    "Weight (kg)": "weight_kg",
    "Weight": "weight_kg",
    # BMI
    "BMI": "bmi",
    # Body Fat
    "Body Fat (%)": "body_fat_pct",
    "Body Fat": "body_fat_pct",
    "Fat Mass (%)": "body_fat_pct",
    # Visceral Fat
    "Visc Fat": "visceral_fat",
    "Visceral Fat": "visceral_fat",
    "Visceral Fat Rating": "visceral_fat",
    # Muscle Mass
    "Muscle Mass (kg)": "muscle_mass_kg",
    "Muscle Mass": "muscle_mass_kg",
    # Muscle Quality
    "Muscle Quality": "muscle_quality",
    "Muscle Quality Score": "muscle_quality",
    # Bone Mass
    "Bone Mass (kg)": "bone_mass_kg",
    "Bone Mass": "bone_mass_kg",
    # BMR
    "BMR (kcal)": "bmr_kcal",
    "BMR": "bmr_kcal",
    "Basal Metabolic Rate": "bmr_kcal",
    # Metabolic Age
    "Metab Age": "metabolic_age",
    "Metabolic Age": "metabolic_age",
    # Body Water
    "Body Water (%)": "body_water_pct",
    "Body Water": "body_water_pct",
    "Total Body Water (%)": "body_water_pct",
    # Physique Rating
    "Physique Rating": "physique_rating",
}

# Numeric DB columns (used for safe float/int conversion)
_FLOAT_COLS = {
    "weight_kg", "bmi", "body_fat_pct", "visceral_fat",
    "muscle_mass_kg", "muscle_quality", "bone_mass_kg",
    "bmr_kcal", "body_water_pct",
}
_INT_COLS = {"metabolic_age", "physique_rating"}


def _get_db() -> sqlite3.Connection:
    """Return a SQLite connection with the body_composition_history table ensured."""
    conn = sqlite3.connect(str(SQLITE_DB))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS body_composition_history (
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
        )"""
    )
    # Unique index on weight_history so Tanita re-syncs don't create duplicates
    conn.execute(
        """CREATE UNIQUE INDEX IF NOT EXISTS idx_weight_history_unique
           ON weight_history (user_id, recorded_at)"""
    )
    conn.commit()
    return conn


def _parse_date(raw: str) -> str:
    """Normalise MyTanita date strings to ISO-8601 (YYYY-MM-DD HH:MM:SS)."""
    raw = raw.strip()
    for fmt in (
        "%d/%m/%Y %H:%M",   # 19/06/2019 09:20  (most common)
        "%d/%m/%Y %H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%d-%m-%Y %H:%M",
        "%m/%d/%Y %H:%M",
    ):
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
    # Fallback: return as-is so we don't silently discard rows
    return raw


def _safe_float(value: str) -> Optional[float]:
    try:
        return float(value.replace(",", ".").strip())
    except (ValueError, AttributeError):
        return None


def _safe_int(value: str) -> Optional[int]:
    try:
        return int(float(value.replace(",", ".").strip()))
    except (ValueError, AttributeError):
        return None


def _screenshot_path(step: str) -> str:
    """Return a temp path for a debug screenshot."""
    import tempfile
    return os.path.join(tempfile.gettempdir(), f"tanita_debug_{step}.png")


def _download_csv_via_playwright(headless: bool = True) -> str:
    """
    Open a Chromium browser, log in to MyTanita, navigate to
    My Measurements → Import/Export, and return the downloaded CSV as a string.

    Set headless=False to watch the browser (useful for debugging).
    """
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

    if not USER_TANITA or not PASS_TANITA:
        raise ValueError("USER_TANITA and PASS_TANITA must be set in .env")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)
        ctx = browser.new_context(
            accept_downloads=True,
            viewport={"width": 1280, "height": 800},
        )
        page = ctx.new_page()

        try:
            # ── 1. Login ──────────────────────────────────────────────
            logger.info("Tanita: navigating to %s", TANITA_LOGIN_URL)
            page.goto(TANITA_LOGIN_URL, wait_until="domcontentloaded", timeout=30_000)
            page.wait_for_load_state("networkidle", timeout=15_000)

            # MyTanita uses Symfony (_username / _password) or standard email/password
            email_filled = False
            for sel in (
                'input[name="_username"]',
                'input[type="email"]',
                'input[name="email"]',
                '#email',
                'input[id*="email" i]',
                'input[placeholder*="mail" i]',
            ):
                if page.locator(sel).count() > 0:
                    page.fill(sel, USER_TANITA)
                    email_filled = True
                    logger.info("Tanita: filled email using selector '%s'", sel)
                    break

            if not email_filled:
                page.screenshot(path=_screenshot_path("login_no_email"))
                raise RuntimeError(
                    f"Login form not found at {page.url}. "
                    f"Screenshot saved to {_screenshot_path('login_no_email')}"
                )

            for sel in (
                'input[name="_password"]',
                'input[type="password"]',
                'input[name="password"]',
                '#password',
                'input[id*="password" i]',
            ):
                if page.locator(sel).count() > 0:
                    page.fill(sel, PASS_TANITA)
                    break

            # Submit — press Enter or click the submit button
            submitted = False
            for sel in (
                'button[type="submit"]',
                'input[type="submit"]',
                'button:has-text("Login")',
                'button:has-text("Sign in")',
                'button:has-text("Entrar")',
                '.login-btn',
                'form button',
            ):
                if page.locator(sel).count() > 0:
                    page.click(sel)
                    submitted = True
                    break

            if not submitted:
                page.keyboard.press("Enter")

            page.wait_for_load_state("networkidle", timeout=20_000)
            logger.info("Tanita: after login, URL=%s", page.url)

            # Detect failed login (still on login page or error message visible)
            if "login" in page.url.lower():
                page.screenshot(path=_screenshot_path("login_failed"))
                raise RuntimeError(
                    f"Login failed — still on login page ({page.url}). "
                    "Check USER_TANITA / PASS_TANITA credentials in .env. "
                    f"Debug screenshot: {_screenshot_path('login_failed')}"
                )

            # ── 2. Navigate to My Measurements ────────────────────────
            meas_url = TANITA_LOGIN_URL.replace("/user/login", "/user/measurements")
            navigated = False

            # First try: direct URL navigation (most reliable)
            try:
                page.goto(meas_url, wait_until="networkidle", timeout=20_000)
                navigated = True
                logger.info("Tanita: navigated directly to measurements page")
            except Exception:
                pass

            # Second try: click nav link
            if not navigated or "measurement" not in page.url.lower():
                for sel in (
                    'a[href*="measurement"]',
                    'a:has-text("My Measurements")',
                    'a:has-text("Measurements")',
                    'a:has-text("Medições")',
                    'nav a:nth-child(2)',
                ):
                    try:
                        if page.locator(sel).count() > 0:
                            page.click(sel)
                            page.wait_for_load_state("networkidle", timeout=15_000)
                            navigated = True
                            break
                    except PWTimeout:
                        continue

            logger.info("Tanita: measurements page URL=%s", page.url)

            # ── 3. Open Import/Export modal, then click "Export list as CSV" ──
            # The MyTanita measurements page has a two-step flow:
            #   Step A — click the "Import/Export" button → opens a modal/panel
            #   Step B — inside the modal, click "Export list as CSV" → triggers download
            page.screenshot(path=_screenshot_path("before_export"))
            logger.info("Tanita: screenshot before export saved to %s",
                        _screenshot_path("before_export"))

            # Step A: open the modal
            modal_opened = False
            for sel in (
                'a:has-text("Import/Export")',
                'button:has-text("Import/Export")',
                'a:has-text("IMPORT/EXPORT")',
                'button:has-text("IMPORT/EXPORT")',
                '*[class*="import"i]',
            ):
                loc = page.locator(sel)
                if loc.count() > 0:
                    loc.first.click()
                    logger.info("Tanita: clicked modal trigger with '%s'", sel)
                    modal_opened = True
                    break

            if not modal_opened:
                page.screenshot(path=_screenshot_path("modal_trigger_not_found"))
                links = page.locator("a, button").all_text_contents()
                raise RuntimeError(
                    "Import/Export button not found on the measurements page.\n"
                    f"Page URL: {page.url}\n"
                    f"Visible elements: {links[:20]}\n"
                    f"Debug screenshot: {_screenshot_path('modal_trigger_not_found')}"
                )

            # Step B: wait for "Export list as CSV" to become VISIBLE, then click it.
            # The modal has a CSS animation — we must wait for the link to be interactable,
            # not just present in the DOM.
            export_csv_sel = 'text=Export list as CSV'
            try:
                page.wait_for_selector(
                    export_csv_sel,
                    state="visible",
                    timeout=8_000,
                )
            except PWTimeout:
                # Fallback: try alternative text (localised or slightly different)
                export_csv_sel = None
                for fallback in (
                    'text=Export',
                    'a[href*="csv"]',
                    'a[href*="export"]',
                ):
                    try:
                        page.wait_for_selector(fallback, state="visible", timeout=3_000)
                        export_csv_sel = fallback
                        break
                    except PWTimeout:
                        continue

            page.screenshot(path=_screenshot_path("after_modal_open"))
            logger.info("Tanita: modal open, export selector resolved to '%s'", export_csv_sel)

            if export_csv_sel is None:
                page.screenshot(path=_screenshot_path("csv_click_failed"))
                links = page.locator("a, button").all_text_contents()
                raise RuntimeError(
                    "Modal opened but 'Export list as CSV' link never became visible.\n"
                    f"Page URL: {page.url}\n"
                    f"Visible elements: {links[:20]}\n"
                    f"Debug screenshot: {_screenshot_path('csv_click_failed')}"
                )

            # Download timeout is generous — the server may take a few seconds to generate CSV
            csv_content = None
            try:
                with page.expect_download(timeout=90_000) as dl_info:
                    page.click(export_csv_sel)
                download = dl_info.value
                dl_path = download.path()
                with open(dl_path, "r", encoding="utf-8-sig") as f:
                    csv_content = f.read()
                logger.info("Tanita: CSV downloaded (%d bytes)", len(csv_content))
            except Exception as exc:
                page.screenshot(path=_screenshot_path("csv_click_failed"))
                raise RuntimeError(
                    f"Click on '{export_csv_sel}' did not trigger a download: {exc}\n"
                    f"Debug screenshot: {_screenshot_path('csv_click_failed')}"
                ) from exc

        finally:
            browser.close()

        return csv_content


def _parse_csv(csv_content: str, user_id: str) -> list[dict]:
    """
    Parse the MyTanita CSV and return a list of row dicts ready for DB insertion.
    Handles both comma and semicolon delimiters (European locale exports).
    """
    # Detect delimiter
    first_line = csv_content.splitlines()[0] if csv_content.strip() else ""
    delimiter = ";" if first_line.count(";") > first_line.count(",") else ","

    reader = csv.DictReader(io.StringIO(csv_content), delimiter=delimiter)
    rows = []
    for raw_row in reader:
        record: dict = {"user_id": user_id}
        for csv_col, db_col in _COLUMN_MAP.items():
            raw_val = raw_row.get(csv_col, "").strip()
            if not raw_val:
                continue
            if db_col == "measured_at":
                record[db_col] = _parse_date(raw_val)
            elif db_col in _FLOAT_COLS:
                record[db_col] = _safe_float(raw_val)
            elif db_col in _INT_COLS:
                record[db_col] = _safe_int(raw_val)
        if "measured_at" in record:
            rows.append(record)
    return rows


def _insert_rows(conn: sqlite3.Connection, rows: list[dict]) -> tuple[int, int]:
    """
    Insert rows using INSERT OR IGNORE to skip duplicates.
    Also mirrors weight_kg into weight_history so the existing weight chart
    reflects all Tanita measurements.
    Returns (inserted_count, skipped_count).
    """
    inserted = 0
    skipped = 0
    for row in rows:
        cols = list(row.keys())
        placeholders = ", ".join("?" * len(cols))
        sql = (
            f"INSERT OR IGNORE INTO body_composition_history "
            f"({', '.join(cols)}) VALUES ({placeholders})"
        )
        cur = conn.execute(sql, [row[c] for c in cols])
        if cur.rowcount:
            inserted += 1
            # Mirror weight into weight_history for the dashboard chart
            if row.get("weight_kg") is not None:
                conn.execute(
                    """INSERT OR IGNORE INTO weight_history (user_id, weight_kg, recorded_at)
                       VALUES (?, ?, ?)""",
                    (row["user_id"], row["weight_kg"], row["measured_at"]),
                )
        else:
            skipped += 1
    conn.commit()
    return inserted, skipped


# ─────────────────────────────────────────────────────────────────────────────
# Public tools
# ─────────────────────────────────────────────────────────────────────────────

@xai_tool
def sync_tanita_measurements(user_id: str | int) -> str:
    """
    Sync body composition measurements from MyTanita scale portal.

    Logs in to mytanita.eu using the credentials in .env (USER_TANITA /
    PASS_TANITA), downloads the full CSV export from My Measurements →
    Import/Export, parses all body composition fields, and stores them in
    the local database.  Duplicate entries (same user + timestamp) are
    automatically skipped.

    Args:
        user_id: Telegram user ID

    Returns:
        Summary of how many new measurements were imported
    """
    user_id = str(user_id)

    if not USER_TANITA or not PASS_TANITA:
        return (
            "❌ Credenciais MyTanita não configuradas.\n"
            "Adiciona USER_TANITA e PASS_TANITA ao ficheiro .env."
        )

    try:
        csv_content = _download_csv_via_playwright()
    except Exception as exc:
        logger.error("Tanita download failed: %s", exc, exc_info=True)
        return f"❌ Erro ao aceder ao MyTanita: {exc}"

    rows = _parse_csv(csv_content, user_id)
    if not rows:
        return (
            "⚠️ O ficheiro CSV foi descarregado mas não continha dados reconhecíveis. "
            "Verifica o formato da exportação."
        )

    conn = _get_db()
    inserted, skipped = _insert_rows(conn, rows)

    # Backfill weight_history from body_composition_history so the dashboard
    # weight chart reflects all Tanita records, even ones imported previously.
    cur = conn.execute(
        """INSERT OR IGNORE INTO weight_history (user_id, weight_kg, recorded_at)
           SELECT user_id, weight_kg, measured_at
           FROM body_composition_history
           WHERE user_id = ? AND weight_kg IS NOT NULL""",
        (user_id,),
    )
    weight_synced = cur.rowcount
    conn.commit()
    conn.close()

    return (
        f"✅ Sincronização MyTanita concluída!\n"
        f"  • {inserted} nova(s) medição(ões) importada(s)\n"
        f"  • {skipped} duplicado(s) ignorado(s)\n"
        f"  • {weight_synced} peso(s) adicionado(s) ao gráfico\n"
        f"  • Total no CSV: {len(rows)} registos"
    )


@xai_tool
def get_body_composition_history(
    user_id: str | int,
    limit: int = 10,
) -> str:
    """
    Retrieve the user's body composition history from Tanita measurements.

    Shows the most recent entries with all tracked metrics:
    weight, BMI, body fat, visceral fat, muscle mass, bone mass,
    BMR, metabolic age, body water, and physique rating.

    Args:
        user_id: Telegram user ID
        limit: Number of recent entries to show (default 10, max 50)

    Returns:
        Formatted body composition history
    """
    user_id = str(user_id)
    limit = min(int(limit), 50)

    conn = _get_db()
    rows = conn.execute(
        """SELECT measured_at, weight_kg, bmi, body_fat_pct, visceral_fat,
                  muscle_mass_kg, muscle_quality, bone_mass_kg,
                  bmr_kcal, metabolic_age, body_water_pct, physique_rating
           FROM body_composition_history
           WHERE user_id = ?
           ORDER BY measured_at DESC
           LIMIT ?""",
        (user_id, limit),
    ).fetchall()
    conn.close()

    if not rows:
        return (
            "📊 Sem dados de composição corporal.\n"
            "Usa /tanita para sincronizar medições do MyTanita."
        )

    lines = [f"📊 Composição corporal — últimas {len(rows)} medições:\n"]
    for r in rows:
        date_str = r["measured_at"][:16]
        lines.append(f"📅 {date_str}")
        if r["weight_kg"] is not None:
            lines.append(f"  ⚖️  Peso: {r['weight_kg']:.2f} kg")
        if r["bmi"] is not None:
            lines.append(f"  📐 IMC: {r['bmi']:.1f}")
        if r["body_fat_pct"] is not None:
            lines.append(f"  🫀 Gordura corporal: {r['body_fat_pct']:.1f}%")
        if r["visceral_fat"] is not None:
            lines.append(f"  🔴 Gordura visceral: {r['visceral_fat']:.1f}")
        if r["muscle_mass_kg"] is not None:
            lines.append(f"  💪 Massa muscular: {r['muscle_mass_kg']:.2f} kg")
        if r["muscle_quality"] is not None:
            lines.append(f"  ⭐ Qualidade muscular: {r['muscle_quality']:.0f}")
        if r["bone_mass_kg"] is not None:
            lines.append(f"  🦴 Massa óssea: {r['bone_mass_kg']:.2f} kg")
        if r["bmr_kcal"] is not None:
            lines.append(f"  🔥 TMB: {r['bmr_kcal']:.0f} kcal")
        if r["metabolic_age"] is not None:
            lines.append(f"  🕐 Idade metabólica: {r['metabolic_age']} anos")
        if r["body_water_pct"] is not None:
            lines.append(f"  💧 Água corporal: {r['body_water_pct']:.1f}%")
        if r["physique_rating"] is not None:
            lines.append(f"  🏅 Avaliação física: {r['physique_rating']}")
        lines.append("")

    # Trend summary (first vs last available weight)
    weights = [r["weight_kg"] for r in rows if r["weight_kg"] is not None]
    if len(weights) >= 2:
        diff = weights[0] - weights[-1]
        icon = "⬇️" if diff < 0 else "⬆️" if diff > 0 else "➡️"
        lines.append(f"{icon} Variação de peso (período): {diff:+.2f} kg")

    return "\n".join(lines)


@xai_tool
def get_weight_measurement_info() -> str:
    """
    Return educational context about what body weight means and its limitations
    as a standalone health metric.

    Use this when the user asks about their weight, wants to understand what
    weight measures, or needs context on why body composition matters beyond
    just weight.

    Returns:
        Educational text explaining what weight is and its limitations
    """
    return (
        "⚖️ O que é o Peso Corporal?\n\n"
        "O peso é a massa total do teu corpo em kg/libras. Esta medição inclui "
        "todos os elementos do corpo — ossos, sangue, órgãos, músculos e gordura.\n\n"
        "O teu peso é determinado por vários fatores, incluindo componentes hereditários, "
        "anomalias hormonais, exercício, dieta e estilo de vida. Estar abaixo ou acima "
        "do peso pode impactar significativamente o teu bem-estar físico e psicológico.\n\n"
        "⚠️ Limitação importante: o peso sozinho não indica quanto é músculo e quanto é "
        "gordura. Uma análise completa da saúde só é possível com uma avaliação da "
        "composição corporal que inclua outras métricas além do peso (ex: % gordura, "
        "massa muscular, gordura visceral, água corporal).\n\n"
        "💡 Para uma visão completa, usa /tanita para sincronizar os dados da balança "
        "Tanita com todas as métricas de composição corporal."
    )


@xai_tool
def get_body_water_info() -> str:
    """
    Return educational context about body water percentage and its health relevance.
    Use when the user asks about hydration, body water, or TBW%.

    Returns:
        Educational text about body water
    """
    return (
        "💧 Água Corporal (TBW%)\n\n"
        "A água corporal é uma parte essencial para se manter saudável. Mais de metade do corpo "
        "é constituído por água. Regula a temperatura corporal e ajuda a eliminar resíduos. "
        "Perdes água continuamente através da urina, suor e respiração, por isso é importante "
        "repô-la regularmente.\n\n"
        "A quantidade de líquido necessário por dia varia de pessoa para pessoa e é influenciada "
        "pelas condições climáticas e pelo nível de atividade física. Estar bem hidratado ajuda "
        "a concentração, o desempenho desportivo e o bem-estar geral.\n\n"
        "Os especialistas recomendam pelo menos dois litros de líquido por dia, de preferência "
        "água ou outras bebidas de baixas calorias. Se estás a treinar, aumenta a ingestão de "
        "líquidos para garantir o máximo desempenho.\n\n"
        "📊 Valores médios de TBW% para uma pessoa saudável:\n"
        "  • Feminino: 45 a 60%\n"
        "  • Masculino: 50 a 65%"
    )


@xai_tool
def get_body_fat_info() -> str:
    """
    Return educational context about body fat percentage and healthy ranges.
    Use when the user asks about body fat, fat percentage, or physique rating.

    Returns:
        Educational text about body fat percentage
    """
    return (
        "🫀 Gordura Corporal (%)\n\n"
        "A percentagem de gordura corporal é a proporção do teu peso total que consiste em tecido "
        "gordo. O teu corpo precisa de uma certa quantidade de gordura essencial para manter as "
        "funções vitais e reprodutivas — a gordura também envolve e protege os órgãos internos.\n\n"
        "À medida que o teu nível de atividade muda, o equilíbrio entre gordura corporal e massa "
        "muscular altera-se gradualmente, afetando o teu físico geral. Uma percentagem elevada de "
        "gordura corporal aumenta o risco de doenças cardiovasculares, diabetes tipo 2 e outras "
        "condições metabólicas.\n\n"
        "A avaliação do físico fornecida pelo monitor de composição corporal dá-te uma ideia do "
        "tipo de físico que tens com base no equilíbrio entre gordura e massa muscular.\n\n"
        "📊 Valores saudáveis típicos:\n"
        "  • Feminino: 20–35%\n"
        "  • Masculino: 8–24%"
    )


@xai_tool
def get_bmi_info() -> str:
    """
    Return educational context about BMI and its limitations.
    Use when the user asks about BMI, body mass index, or weight classification.

    Returns:
        Educational text about BMI
    """
    return (
        "📐 IMC (Índice de Massa Corporal / BMI)\n\n"
        "O teu IMC pode ser calculado dividindo o teu peso (em quilogramas) pelo quadrado da tua "
        "altura (em metros). O IMC é um bom indicador geral para estudos populacionais, mas tem "
        "uma limitação séria quando avaliado a nível individual — não distingue entre massa "
        "muscular e gordura."
    )


@xai_tool
def get_visceral_fat_info() -> str:
    """
    Return educational context about visceral fat and its health risks.
    Use when the user asks about visceral fat, abdominal fat, or metabolic risk.

    Returns:
        Educational text about visceral fat
    """
    return (
        "🔴 Gordura Visceral\n\n"
        "A gordura visceral está localizada no interior da região abdominal, envolvendo e "
        "protegendo os órgãos vitais. Mesmo que o teu peso e gordura corporal se mantenham "
        "constantes, à medida que envelheces a distribuição de gordura muda e tende a acumular-se "
        "na zona abdominal.\n\n"
        "Manter um nível saudável de gordura visceral reduz diretamente o risco de certas doenças "
        "como doenças cardíacas, pressão arterial elevada e pode atrasar o aparecimento de "
        "diabetes tipo 2.\n\n"
        "Monitorizar a gordura visceral com um monitor de composição corporal ajuda a acompanhar "
        "potenciais problemas e a testar a eficácia da tua dieta ou treino."
    )


@xai_tool
def get_muscle_mass_info() -> str:
    """
    Return educational context about muscle mass and its role in metabolism.
    Use when the user asks about muscle mass, lean mass, or muscle building.

    Returns:
        Educational text about muscle mass
    """
    return (
        "💪 Massa Muscular\n\n"
        "A massa muscular inclui os músculos esqueléticos, músculos lisos como os músculos "
        "cardíacos e digestivos, e a água contida nestes músculos. Os músculos funcionam como "
        "um motor no consumo de energia.\n\n"
        "À medida que a tua massa muscular aumenta, a taxa a que queimas energia (calorias) "
        "aumenta, o que acelera a tua taxa metabólica basal (TMB) e ajuda a reduzir o excesso "
        "de gordura corporal e a perder peso de forma saudável.\n\n"
        "Se estás a treinar intensamente, a tua massa muscular vai aumentar e pode também "
        "aumentar o teu peso total — por isso é importante monitorizar regularmente para ver "
        "o impacto do teu programa de treino na massa muscular."
    )


@xai_tool
def get_bone_mass_info() -> str:
    """
    Return educational context about bone mass and bone health.
    Use when the user asks about bone mass, bone density, or osteoporosis risk.

    Returns:
        Educational text about bone mass
    """
    return (
        "🦴 Massa Óssea\n\n"
        "O peso previsto do mineral ósseo no teu corpo. Embora a tua massa óssea seja improvável "
        "de sofrer alterações notáveis a curto prazo, é importante manter ossos saudáveis através "
        "de uma dieta equilibrada rica em cálcio e com bastante exercício de suporte de peso.\n\n"
        "Deves acompanhar a tua massa óssea ao longo do tempo e estar atento a quaisquer "
        "alterações a longo prazo."
    )


@xai_tool
def get_bmr_info() -> str:
    """
    Return educational context about basal metabolic rate (BMR) and calorie management.
    Use when the user asks about BMR, metabolism, or calorie needs.

    Returns:
        Educational text about BMR
    """
    return (
        "🔥 Taxa Metabólica Basal (TMB / BMR)\n\n"
        "Aumentar a massa muscular acelera a tua taxa metabólica basal (TMB). Uma pessoa com uma "
        "TMB elevada queima mais calorias em repouso do que uma pessoa com uma TMB baixa. Cerca "
        "de 70% das calorias consumidas diariamente são usadas para o metabolismo basal.\n\n"
        "Aumentar a tua massa muscular ajuda a elevar a TMB, o que aumenta o número de calorias "
        "que queimas e ajuda a diminuir os níveis de gordura corporal. A tua medição de TMB pode "
        "ser usada como linha de base mínima para um programa de dieta — calorias adicionais "
        "podem ser incluídas dependendo do teu nível de atividade.\n\n"
        "Quanto mais ativo fores, mais calorias queimas e mais músculo constróis, por isso "
        "precisas de garantir que consomes calorias suficientes para manter o corpo em forma e "
        "saudável. À medida que as pessoas envelhecem, o metabolismo muda: o metabolismo basal "
        "aumenta à medida que uma criança cresce e atinge o pico por volta dos 16 ou 17 anos, "
        "após o qual tipicamente começa a diminuir.\n\n"
        "⚠️ Uma TMB baixa torna mais difícil perder gordura corporal e peso geral."
    )


@xai_tool
def get_metabolic_age_info() -> str:
    """
    Return educational context about metabolic age and how to improve it.
    Use when the user asks about metabolic age or wants to understand their metabolism.

    Returns:
        Educational text about metabolic age
    """
    return (
        "🕐 Idade Metabólica\n\n"
        "A idade metabólica compara a tua TMB com a média para o teu grupo etário. É calculada "
        "comparando a tua taxa metabólica basal (TMB) com a TMB média do teu grupo etário "
        "cronológico.\n\n"
        "Se a tua idade metabólica for superior à tua idade real, é uma indicação de que precisas "
        "de melhorar a tua taxa metabólica. O exercício aumentado irá construir tecido muscular "
        "saudável, o que por sua vez irá melhorar a tua idade metabólica.\n\n"
        "💡 Mantém-te no caminho certo monitorando regularmente."
    )


TANITA_TOOLS = [
    sync_tanita_measurements,
    get_body_composition_history,
    get_weight_measurement_info,
    get_body_water_info,
    get_body_fat_info,
    get_bmi_info,
    get_visceral_fat_info,
    get_muscle_mass_info,
    get_bone_mass_info,
    get_bmr_info,
    get_metabolic_age_info,
]
