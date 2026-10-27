
"""Atomic note and processing-job creation for Phase 7."""

import sqlite3
import uuid

from .jobs import init_jobs
from .storage import (
    DEFAULT_USER_ID,
    check_secrets,
    get_connection,
    init_db,
    utc_now,
)


def add_queued_note(text, user_id=DEFAULT_USER_ID):
    """Save a note and its processing job in one transaction.

    Returns:
        (note_id, job_id)

    If any database operation fails, neither the note nor
    its job is committed.
    """
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Note cannot be empty.")

    if len(text) > 10000:
        raise ValueError("Note exceeds 10,000 characters.")

    detected = check_secrets(text)

    if detected:
        raise ValueError(
            "Potential secret detected. Note was not saved."
        )

    # Schema setup happens before the atomic transaction.
    init_db()
    init_jobs()

    job_id = str(uuid.uuid4())
    timestamp = utc_now()

    conn = get_connection()

    try:
        conn.execute("BEGIN IMMEDIATE")

        user = conn.execute(
            "SELECT id FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()

        if user is None:
            raise ValueError("User does not exist.")

        cursor = conn.execute(
            """
            INSERT INTO notes (
                user_id, raw_text, created_at
            )
            VALUES (?, ?, ?)
            """,
            (user_id, text, timestamp),
        )

        note_id = cursor.lastrowid

        conn.execute(
            """
            INSERT INTO audit_log (
                user_id,
                action,
                entity_type,
                entity_id,
                created_at
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                user_id,
                "create",
                "note",
                note_id,
                timestamp,
            ),
        )

        conn.execute(
            """
            INSERT INTO processing_jobs (
                id,
                user_id,
                note_id,
                job_type,
                status,
                attempts,
                max_attempts,
                checkpoint,
                idempotency_key,
                available_at,
                created_at
            )
            VALUES (
                ?, ?, ?, 'extract', 'queued',
                0, 3, 'note_saved', ?, ?, ?
            )
            """,
            (
                job_id,
                user_id,
                note_id,
                f"extract-note-{note_id}",
                timestamp,
                timestamp,
            ),
        )

        conn.commit()

        return note_id, job_id

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()

