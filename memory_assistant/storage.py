
"""Local SQLite storage for Personal Memory Assistant."""

import re
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "memory.db"
DEFAULT_USER_ID = 1

SECRET_PATTERNS = [
    (
        "password",
        re.compile(
            r"\b(?:password|passwd|pwd)\s*(?:is|:|=)\s*\S+",
            re.IGNORECASE,
        ),
    ),
    (
        "PIN",
        re.compile(
            r"\b(?:pin|mpin|upi\s*pin)\s*(?:is|:|=)\s*\d{4,8}\b",
            re.IGNORECASE,
        ),
    ),
    (
        "OTP",
        re.compile(
            r"\b(?:otp|verification\s*code|one.time\s*password)"
            r"\s*(?:is|:|=)\s*\d{4,8}\b",
            re.IGNORECASE,
        ),
    ),
    (
        "card number",
        re.compile(r"\b(?:\d[ -]?){12,18}\d\b"),
    ),
]


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def check_secrets(text):
    """Best-effort check; not a guarantee of secret detection."""
    return [
        name
        for name, pattern in SECRET_PATTERNS
        if pattern.search(text)
    ]


_thread_state = threading.local()


def set_current_db_path(path):
    """Point the current thread at a different database file.

    Used by hosted demo mode so each visitor session works against
    its own isolated SQLite file. Normal local use never calls this.
    """
    _thread_state.db_path = str(path)


def clear_current_db_path():
    """Remove the per-thread database override, if any."""
    _thread_state.db_path = None


def _current_db_path():
    override = getattr(_thread_state, "db_path", None)
    return override if override else DB_PATH


def get_connection():
    connection = sqlite3.connect(_current_db_path())
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def init_db():
    """Create the database schema if it does not exist."""
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                raw_text TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS facts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                note_id INTEGER NOT NULL,
                statement TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN (
                        'pending', 'active', 'superseded'
                    )),
                confidence REAL NOT NULL
                    CHECK (confidence BETWEEN 0 AND 1),
                superseded_by INTEGER,
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (note_id) REFERENCES notes(id),
                FOREIGN KEY (superseded_by) REFERENCES facts(id)
            );

            CREATE TABLE IF NOT EXISTS approvals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                fact_id INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN (
                        'pending', 'approved', 'rejected'
                    )),
                reason TEXT NOT NULL,
                created_at TEXT NOT NULL,
                resolved_at TEXT,
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (fact_id) REFERENCES facts(id)
            );

            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                action TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                entity_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            );

            CREATE INDEX IF NOT EXISTS idx_notes_user
                ON notes(user_id);

            CREATE INDEX IF NOT EXISTS idx_facts_user_status
                ON facts(user_id, status);

            CREATE INDEX IF NOT EXISTS idx_approvals_user_status
                ON approvals(user_id, status);
        """)

        conn.execute(
            "INSERT OR IGNORE INTO users (id, name) VALUES (?, ?)",
            (DEFAULT_USER_ID, "Local User"),
        )


def add_note(text, user_id=DEFAULT_USER_ID):
    """Validate and save an exact note with audit metadata."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Note cannot be empty.")

    detected = check_secrets(text)
    if detected:
        raise ValueError(
            "Potential secret detected ("
            + ", ".join(detected)
            + "). Note was not saved."
        )

    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO notes (user_id, raw_text, created_at)
            VALUES (?, ?, ?)
            """,
            (user_id, text, utc_now()),
        )
        note_id = cursor.lastrowid

        conn.execute(
            """
            INSERT INTO audit_log
                (user_id, action, entity_type, entity_id, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, "create", "note", note_id, utc_now()),
        )

    return note_id


def list_notes(user_id=DEFAULT_USER_ID):
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, raw_text, created_at
            FROM notes
            WHERE user_id = ?
            ORDER BY id
            """,
            (user_id,),
        ).fetchall()
        return [dict(row) for row in rows]


def list_facts(user_id=DEFAULT_USER_ID):
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, note_id, statement, status,
                   confidence, created_at
            FROM facts
            WHERE user_id = ?
            ORDER BY id
            """,
            (user_id,),
        ).fetchall()
        return [dict(row) for row in rows]


def list_audit_log(user_id=DEFAULT_USER_ID):
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, action, entity_type, entity_id, created_at
            FROM audit_log
            WHERE user_id = ?
            ORDER BY id
            """,
            (user_id,),
        ).fetchall()
        return [dict(row) for row in rows]
