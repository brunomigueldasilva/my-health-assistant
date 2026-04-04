"""
Shared utilities for the Gradio interface.

Used by all tab modules and the main gradio_app entry point.
"""

import re
import sqlite3
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import SQLITE_DB

# ── Agent team (lazy init) ───────────────────────────────
_team = None
_user_sessions: dict[str, str] = {}


def _get_team():
    global _team
    if _team is None:
        from agents.coordinator import create_health_team
        _team = create_health_team()
    return _team


def _get_session(uid: str) -> str:
    if uid not in _user_sessions:
        _user_sessions[uid] = f"ui_{uid}"
    return _user_sessions[uid]


def _reset_session(uid: str) -> str:
    _user_sessions[uid] = f"ui_{uid}_{uuid.uuid4().hex[:6]}"
    return _user_sessions[uid]


_METADATA_RE = re.compile(
    r"\[Data de hoje:[^\]]*\]\s*\[ID do utilizador:[^\]]*\]\s*\n?",
)


def _sanitize_reply(text: str) -> str:
    """Strip routing metadata and replace raw API errors with user-friendly messages."""
    text = _METADATA_RE.sub("", text).lstrip()
    t = text.lower()
    if "429" in t or "too many requests" in t or "resource_exhausted" in t or "quota" in t:
        return "De momento estou com muitos pedidos em simultâneo. Por favor, aguarda uns segundos e tenta novamente. 🙏"
    if "bound method" in t or "clientresponse" in t or "exception" in t or "traceback" in t:
        return "Ocorreu um problema ao processar o teu pedido. Por favor, tenta novamente. 🙏"
    return text


def _extract_text(response) -> str:
    if response is None:
        return ""
    if hasattr(response, "content"):
        if isinstance(response.content, str):
            return response.content
        if isinstance(response.content, list):
            parts = []
            for item in response.content:
                if hasattr(item, "text"):
                    parts.append(item.text)
                elif isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict) and "text" in item:
                    parts.append(item["text"])
            return "\n".join(parts)
    if hasattr(response, "messages"):
        for msg in reversed(response.messages):
            if hasattr(msg, "content") and msg.role == "assistant":
                return msg.content
    return str(response)


def _db_conn(path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def list_users():
    """Returns the list of registered users for the dropdown."""
    try:
        conn = _db_conn(SQLITE_DB)
        rows = conn.execute(
            "SELECT user_id, name FROM user_profiles ORDER BY name IS NULL, name, user_id"
        ).fetchall()
        conn.close()
        choices = []
        for r in rows:
            label = f"{r['name']} ({r['user_id']})" if r["name"] else str(r["user_id"])
            choices.append((label, r["user_id"]))
        return choices
    except Exception:
        return []


def check_user_status(uid) -> str:
    uid = (uid or "").strip()
    if not uid:
        return ""
    try:
        conn = _db_conn(SQLITE_DB)
        row = conn.execute(
            "SELECT name FROM user_profiles WHERE user_id = ?", (uid,)
        ).fetchone()
        conn.close()
        if row:
            name = row["name"] or uid
            return f"✅ **{name}**"
        return "🆕 Utilizador novo — preenche o teu perfil!"
    except Exception:
        return ""
