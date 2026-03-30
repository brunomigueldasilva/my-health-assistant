"""
Profile Tools — manage user preferences, goals, and health data.
Tool docstrings in English for LLM reliability.
"""

import logging
import sqlite3
from datetime import datetime
from typing import Optional

from config import SQLITE_DB
from knowledge import get_knowledge_base
from xai import xai_tool

logger = logging.getLogger(__name__)


def _age_from_birth_date(birth_date: Optional[str]) -> Optional[int]:
    """Compute current age in years from an ISO date string (YYYY-MM-DD)."""
    if not birth_date:
        return None
    try:
        from datetime import date
        bd = datetime.strptime(birth_date[:10], "%Y-%m-%d").date()
        today = date.today()
        return today.year - bd.year - ((today.month, today.day) < (bd.month, bd.day))
    except Exception:
        return None


def _get_db():
    """Return SQLite connection, ensuring tables exist."""
    conn = sqlite3.connect(str(SQLITE_DB))
    conn.row_factory = sqlite3.Row
    # WAL mode allows concurrent reads during writes (prevents Gradio UI lockout
    # while long Tanita syncs are running).
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS user_profiles (
            user_id TEXT PRIMARY KEY,
            name TEXT,
            birth_date TEXT,
            gender TEXT,
            height_cm REAL,
            weight_kg REAL,
            activity_level TEXT DEFAULT 'moderado',
            goal TEXT,
            created_at TEXT,
            updated_at TEXT
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS weight_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            weight_kg REAL,
            recorded_at TEXT
        )"""
    )
    conn.execute(
        """CREATE UNIQUE INDEX IF NOT EXISTS idx_weight_history_unique
           ON weight_history (user_id, recorded_at)"""
    )
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
    conn.commit()
    return conn


@xai_tool
def get_user_profile(user_id: str | int) -> str:
    """
    Get the complete user profile including dietary preferences.

    Args:
        user_id: Telegram user ID

    Returns:
        Full profile with personal data and food preferences
    """
    user_id = str(user_id)
    conn = _get_db()
    row = conn.execute(
        "SELECT * FROM user_profiles WHERE user_id = ?", (user_id,)
    ).fetchone()
    conn.close()

    kb = get_knowledge_base()
    prefs = kb.get_user_profile_summary(user_id)

    if not row:
        prefs_default = kb.get_user_profile_summary("default")
        return (
            f"⚠️ Perfil não configurado para user_id={user_id}.\n\n"
            f"Preferências (default):\n{prefs_default}\n\n"
            f"💡 Usa /perfil para configurar."
        )

    age = _age_from_birth_date(row["birth_date"])
    bd = row["birth_date"] or ""
    age_label = f"{age} anos (nasc. {bd})" if age and bd else (f"{age} anos" if age else "?")
    return (
        f"👤 Perfil de {row['name'] or 'Utilizador'}:\n"
        f"  • Idade: {age_label}\n"
        f"  • Género: {row['gender'] or '?'}\n"
        f"  • Altura: {row['height_cm'] or '?'} cm\n"
        f"  • Peso: {row['weight_kg'] or '?'} kg\n"
        f"  • Atividade: {row['activity_level'] or '?'}\n"
        f"  • Objetivo: {row['goal'] or 'Não definido'}\n\n"
        f"🍽️ Preferências:\n{prefs}"
    )


@xai_tool
def update_user_profile(
    user_id: str | int,
    name: Optional[str] = None,
    birth_date: Optional[str] = None,
    gender: Optional[str] = None,
    height_cm: Optional[float] = None,
    weight_kg: Optional[float] = None,
    activity_level: Optional[str] = None,
    goal: Optional[str] = None,
) -> str:
    """
    Update user profile. Only provided fields are updated.
    Age is never stored — it is always computed from birth_date at runtime.

    Args:
        user_id: App user ID (string or integer)
        name: User's name
        birth_date: Date of birth in ISO format YYYY-MM-DD
        gender: "male" or "female"
        height_cm: Height in centimeters
        weight_kg: Weight in kilograms
        activity_level: "sedentary", "light", "moderate", "active", "very_active"
        goal: Health goal (e.g. "lose visceral fat", "gain muscle", "maintain weight")

    Returns:
        Confirmation of update
    """
    user_id = str(user_id)
    conn = _get_db()
    now = datetime.now().isoformat()

    existing = conn.execute(
        "SELECT * FROM user_profiles WHERE user_id = ?", (user_id,)
    ).fetchone()

    if not existing:
        conn.execute(
            """INSERT INTO user_profiles
               (user_id, name, birth_date, gender, height_cm, weight_kg,
                activity_level, goal, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, name, birth_date, gender, height_cm, weight_kg,
             activity_level, goal, now, now),
        )
        try:
            from knowledge.seed_data import seed_user_preferences
            seed_user_preferences(user_id)
        except Exception as exc:
            logger.warning("Could not seed preferences for %s: %s", user_id, exc)
    else:
        updates, params = [], []
        for field, value in [
            ("name", name), ("birth_date", birth_date),
            ("gender", gender), ("height_cm", height_cm), ("weight_kg", weight_kg),
            ("activity_level", activity_level), ("goal", goal),
        ]:
            if value is not None:
                updates.append(f"{field} = ?")
                params.append(value)
        if updates:
            updates.append("updated_at = ?")
            params.extend([now, user_id])
            conn.execute(
                f"UPDATE user_profiles SET {', '.join(updates)} WHERE user_id = ?",
                params,
            )

    if weight_kg is not None:
        conn.execute(
            "INSERT OR IGNORE INTO weight_history (user_id, weight_kg, recorded_at) VALUES (?, ?, ?)",
            (user_id, weight_kg, now),
        )

    conn.commit()
    conn.close()

    updated = [
        label for label, v in [
            ("nome", name), ("data nasc.", birth_date), ("género", gender),
            ("altura", height_cm), ("peso", weight_kg),
            ("atividade", activity_level), ("objetivo", goal),
        ] if v is not None
    ]
    return f"✅ Perfil atualizado: {', '.join(updated)}"


@xai_tool
def add_allergy(user_id: str | int, allergy: str) -> str:
    """
    Add an allergy or food intolerance for the user.

    Args:
        user_id: Telegram user ID
        allergy: Allergy or intolerance name (e.g. "glúten", "lactose")

    Returns:
        Confirmation message
    """
    user_id = str(user_id)
    kb = get_knowledge_base()
    kb.add_preference(
        user_id, "allergies", allergy,
        {"type": "allergy", "created": datetime.now().isoformat()},
    )
    return f"⚠️ Alergia/intolerância registada: **{allergy}**"


@xai_tool
def add_food_preference(user_id: str | int, food: str, likes: bool) -> str:
    """
    Add a food preference for the user.

    Args:
        user_id: Telegram user ID
        food: Food name
        likes: True if user likes it, False if user dislikes it

    Returns:
        Confirmation message
    """
    user_id = str(user_id)
    kb = get_knowledge_base()
    category = "food_likes" if likes else "food_dislikes"
    kb.add_preference(
        user_id, category, food,
        {"sentiment": "positive" if likes else "negative"},
    )
    emoji = "👍" if likes else "👎"
    action = "gosta de" if likes else "não gosta de"
    return f"{emoji} Registado: {action} **{food}**"


@xai_tool
def add_health_goal(user_id: str | int, goal: str) -> str:
    """
    Add a health or fitness goal for the user.

    Args:
        user_id: Telegram user ID
        goal: Goal description (e.g. "lose 5kg in 3 months", "reduce visceral fat")

    Returns:
        Confirmation message
    """
    user_id = str(user_id)
    kb = get_knowledge_base()
    kb.add_preference(
        user_id, "goals", goal,
        {"type": "health_goal", "created": datetime.now().isoformat()},
    )
    conn = _get_db()
    conn.execute(
        "UPDATE user_profiles SET goal = ?, updated_at = ? WHERE user_id = ?",
        (goal, datetime.now().isoformat(), user_id),
    )
    conn.commit()
    conn.close()
    return f"🎯 Objetivo registado: **{goal}**"


@xai_tool
def get_weight_history(user_id: str | int, limit: int = 30) -> str:
    """
    Get the user's weight tracking history.

    Args:
        user_id: Telegram user ID
        limit: Number of recent entries to return (default 30, max 1000).
            Use limit=1000 when the user asks about long-term trends, the
            oldest/first record, or history spanning months or years.

    Returns:
        Weight history with dates and trend. The first line always shows
        the total number of records and the full date range, regardless
        of the limit, so the LLM knows the complete history available.
    """
    user_id = str(user_id)
    limit = min(int(limit), 1000)
    conn = _get_db()

    stats = conn.execute(
        """SELECT COUNT(*) as total,
                  MIN(recorded_at) as first_date,
                  MAX(recorded_at) as last_date
           FROM weight_history WHERE user_id = ?""",
        (user_id,),
    ).fetchone()
    total = stats["total"] if stats else 0
    first_date = stats["first_date"][:10] if stats and stats["first_date"] else None
    last_date = stats["last_date"][:10] if stats and stats["last_date"] else None

    rows = conn.execute(
        """SELECT weight_kg, recorded_at FROM weight_history
           WHERE user_id = ? ORDER BY recorded_at DESC LIMIT ?""",
        (user_id, limit),
    ).fetchall()
    conn.close()

    if not rows:
        return "📊 Sem histórico de peso. Usa /peso <kg> para registar."

    lines = [
        f"📈 Histórico total: {total} registos (de {first_date} a {last_date}). "
        f"A mostrar: {len(rows)} mais recentes (limit={limit}).\n",
        "📊 Histórico de peso:\n",
    ]
    for row in rows:
        lines.append(f"  {row['recorded_at'][:10]}: {row['weight_kg']} kg")

    if len(rows) >= 2:
        diff = rows[0]["weight_kg"] - rows[-1]["weight_kg"]
        icon = "⬇️" if diff < 0 else "⬆️" if diff > 0 else "➡️"
        lines.append(f"\n{icon} Variação no período mostrado: {diff:+.1f} kg")

    return "\n".join(lines)


@xai_tool
def export_user_data(user_id: str | int) -> str:
    """
    Export all personal data for a user in a portable format.
    Implements GDPR Article 20 — Right to Data Portability.

    Args:
        user_id: User ID

    Returns:
        JSON string containing all user data (profile, weight history, preferences)
    """
    import json
    user_id = str(user_id)
    conn = _get_db()
    profile_row = conn.execute(
        "SELECT * FROM user_profiles WHERE user_id = ?", (user_id,)
    ).fetchone()
    history_rows = conn.execute(
        "SELECT weight_kg, recorded_at FROM weight_history WHERE user_id = ? ORDER BY recorded_at",
        (user_id,),
    ).fetchall()
    conn.close()

    kb = get_knowledge_base()
    preferences: dict[str, list[str]] = {}
    for cat in ("food_likes", "food_dislikes", "allergies", "goals", "restrictions", "health_data"):
        try:
            data = kb.preferences.get(
                where={"$and": [{"user_id": user_id}, {"category": cat}]}
            )
            preferences[cat] = data.get("documents", []) if data else []
        except Exception:
            preferences[cat] = []

    export = {
        "export_date": datetime.now().isoformat(),
        "gdpr_basis": "Art. 20 — Right to Data Portability",
        "user_id": user_id,
        "profile": dict(profile_row) if profile_row else {},
        "weight_history": [
            {"weight_kg": r["weight_kg"], "recorded_at": r["recorded_at"]}
            for r in history_rows
        ],
        "preferences": preferences,
    }
    logger.info("GDPR export requested for user %s", user_id)
    return json.dumps(export, ensure_ascii=False, indent=2)


@xai_tool
def delete_all_user_data(user_id: str | int) -> str:
    """
    Permanently delete all personal data for a user.
    Implements GDPR Article 17 — Right to Erasure ("Right to be Forgotten").

    Args:
        user_id: User ID

    Returns:
        Confirmation of permanent deletion
    """
    user_id = str(user_id)
    conn = _get_db()
    conn.execute("DELETE FROM user_profiles WHERE user_id = ?", (user_id,))
    conn.execute("DELETE FROM weight_history WHERE user_id = ?", (user_id,))
    conn.execute("DELETE FROM body_composition_history WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

    kb = get_knowledge_base()
    deleted_prefs = 0
    for cat in ("food_likes", "food_dislikes", "allergies", "goals", "restrictions", "health_data"):
        try:
            data = kb.preferences.get(
                where={"$and": [{"user_id": user_id}, {"category": cat}]}
            )
            if data and data.get("ids"):
                kb.preferences.delete(ids=data["ids"])
                deleted_prefs += len(data["ids"])
        except Exception as exc:
            logger.warning("Could not delete ChromaDB prefs for %s/%s: %s", user_id, cat, exc)

    logger.info(
        "GDPR erasure completed for user %s — %d preference entries removed",
        user_id, deleted_prefs,
    )
    return (
        f"✅ Todos os dados do utilizador {user_id} foram eliminados permanentemente "
        f"({deleted_prefs} preferências removidas). "
        "Esta acção é irreversível (RGPD Art. 17)."
    )


PROFILE_TOOLS = [
    get_user_profile,
    update_user_profile,
    add_allergy,
    add_food_preference,
    add_health_goal,
    get_weight_history,
    export_user_data,
    delete_all_user_data,
]
