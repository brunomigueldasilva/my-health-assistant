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


def _get_db():
    """Return SQLite connection, ensuring tables exist."""
    conn = sqlite3.connect(str(SQLITE_DB))
    conn.row_factory = sqlite3.Row
    conn.execute(
        """CREATE TABLE IF NOT EXISTS user_profiles (
            user_id TEXT PRIMARY KEY,
            name TEXT,
            age INTEGER,
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

    return (
        f"👤 Perfil de {row['name'] or 'Utilizador'}:\n"
        f"  • Idade: {row['age'] or '?'} anos\n"
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
    age: Optional[int] = None,
    gender: Optional[str] = None,
    height_cm: Optional[float] = None,
    weight_kg: Optional[float] = None,
    activity_level: Optional[str] = None,
    goal: Optional[str] = None,
) -> str:
    """
    Update user profile. Only provided fields are updated.

    Args:
        user_id: Telegram user ID (string or integer)
        name: User's name
        age: Age in years
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
               (user_id, name, age, gender, height_cm, weight_kg,
                activity_level, goal, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, name, age, gender, height_cm, weight_kg,
             activity_level, goal, now, now),
        )
        # Seed default preferences for the new user
        try:
            from knowledge.seed_data import seed_user_preferences
            seed_user_preferences(user_id)
        except Exception as exc:
            logger.warning("Could not seed preferences for %s: %s", user_id, exc)
    else:
        updates, params = [], []
        for field, value in [
            ("name", name), ("age", age), ("gender", gender),
            ("height_cm", height_cm), ("weight_kg", weight_kg),
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
            "INSERT INTO weight_history (user_id, weight_kg, recorded_at) VALUES (?, ?, ?)",
            (user_id, weight_kg, now),
        )

    conn.commit()
    conn.close()

    updated = [
        label for label, v in [
            ("nome", name), ("idade", age), ("género", gender),
            ("altura", height_cm), ("peso", weight_kg),
            ("atividade", activity_level), ("objetivo", goal),
        ] if v is not None
    ]
    return f"✅ Perfil atualizado: {', '.join(updated)}"


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
def get_weight_history(user_id: str | int) -> str:
    """
    Get the user's weight tracking history.

    Args:
        user_id: Telegram user ID

    Returns:
        Weight history with dates and trend
    """
    user_id = str(user_id)
    conn = _get_db()
    rows = conn.execute(
        """SELECT weight_kg, recorded_at FROM weight_history
           WHERE user_id = ? ORDER BY recorded_at DESC LIMIT 20""",
        (user_id,),
    ).fetchall()
    conn.close()

    if not rows:
        return "📊 Sem histórico de peso. Usa /peso <kg> para registar."

    lines = ["📊 Histórico de peso:\n"]
    for row in rows:
        lines.append(f"  {row['recorded_at'][:10]}: {row['weight_kg']} kg")

    if len(rows) >= 2:
        diff = rows[0]["weight_kg"] - rows[-1]["weight_kg"]
        icon = "⬇️" if diff < 0 else "⬆️" if diff > 0 else "➡️"
        lines.append(f"\n{icon} Variação: {diff:+.1f} kg")

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
    add_food_preference,
    add_health_goal,
    get_weight_history,
    export_user_data,
    delete_all_user_data,
]
