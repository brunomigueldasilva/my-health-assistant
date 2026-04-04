"""
Per-user credential store — encrypted at rest with Fernet (AES-128-CBC + HMAC).

Credentials are stored in the existing user_profiles.db SQLite database,
in a table `user_credentials(user_id, service, username_enc, password_enc)`.

The encryption key is a single SECRET_KEY stored in .env:
  SECRET_KEY=<base64-url-safe 32-byte key>

Generate a new key once with:
  python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

Usage:
    from tools.credential_store import set_credential, get_credential, delete_credential

    set_credential("123456", "tanita", "user@example.com", "mypassword")
    username, password = get_credential("123456", "tanita")
    delete_credential("123456", "tanita")
"""

import logging
import sqlite3
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

from config import SQLITE_DB, SECRET_KEY

logger = logging.getLogger(__name__)


# ── Fernet cipher ──────────────────────────────────────────────────────────────

def _cipher() -> Fernet:
    if not SECRET_KEY:
        raise RuntimeError(
            "SECRET_KEY is not set in .env.\n"
            "Generate one with:\n"
            "  python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"\n"
            "Then add SECRET_KEY=<value> to your .env file."
        )
    return Fernet(SECRET_KEY.encode() if isinstance(SECRET_KEY, str) else SECRET_KEY)


def _enc(value: str) -> bytes:
    return _cipher().encrypt(value.encode())


def _dec(token: bytes) -> str:
    try:
        return _cipher().decrypt(token).decode()
    except InvalidToken as e:
        raise ValueError("Falha ao desencriptar — chave incorrecta ou dados corrompidos.") from e


# ── DB helpers ─────────────────────────────────────────────────────────────────

def _get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(SQLITE_DB))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS user_credentials (
            user_id      TEXT NOT NULL,
            service      TEXT NOT NULL,
            username_enc BLOB NOT NULL,
            password_enc BLOB NOT NULL,
            updated_at   TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (user_id, service)
        )"""
    )
    conn.commit()
    return conn


# ── Public API ─────────────────────────────────────────────────────────────────

def set_credential(user_id: str, service: str, username: str, password: str) -> None:
    """
    Store (or update) the username/password for *service* and *user_id*.

    Args:
        user_id:  The user this credential belongs to.
        service:  Service identifier, e.g. "tanita" or "garmin".
        username: Plain-text username / e-mail.
        password: Plain-text password.
    """
    user_id = str(user_id)
    conn = _get_db()
    conn.execute(
        """INSERT INTO user_credentials (user_id, service, username_enc, password_enc, updated_at)
           VALUES (?, ?, ?, ?, datetime('now'))
           ON CONFLICT(user_id, service) DO UPDATE SET
               username_enc = excluded.username_enc,
               password_enc = excluded.password_enc,
               updated_at   = excluded.updated_at""",
        (user_id, service, _enc(username), _enc(password)),
    )
    conn.commit()
    conn.close()
    logger.info("Credential stored for user=%s service=%s", user_id, service)


def get_credential(user_id: str, service: str) -> Optional[tuple[str, str]]:
    """
    Retrieve the (username, password) for *service* and *user_id*.

    Returns:
        (username, password) tuple, or None if not found.
    """
    user_id = str(user_id)
    conn = _get_db()
    row = conn.execute(
        "SELECT username_enc, password_enc FROM user_credentials WHERE user_id=? AND service=?",
        (user_id, service),
    ).fetchone()
    conn.close()

    if row is None:
        return None

    return _dec(row["username_enc"]), _dec(row["password_enc"])


def delete_credential(user_id: str, service: str) -> bool:
    """
    Remove the stored credential for *service* and *user_id*.

    Returns:
        True if a row was deleted, False if it didn't exist.
    """
    user_id = str(user_id)
    conn = _get_db()
    cur = conn.execute(
        "DELETE FROM user_credentials WHERE user_id=? AND service=?",
        (user_id, service),
    )
    conn.commit()
    conn.close()
    deleted = cur.rowcount > 0
    if deleted:
        logger.info("Credential deleted for user=%s service=%s", user_id, service)
    return deleted


def list_services(user_id: str) -> list[str]:
    """Return the list of service names that have credentials stored for *user_id*."""
    user_id = str(user_id)
    conn = _get_db()
    rows = conn.execute(
        "SELECT service FROM user_credentials WHERE user_id=? ORDER BY service",
        (user_id,),
    ).fetchall()
    conn.close()
    return [r["service"] for r in rows]
