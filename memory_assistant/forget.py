
"""Phase 4: forget application-managed SQLite records."""

import hashlib

from .storage import (
    DEFAULT_USER_ID,
    get_connection,
    utc_now,
)


def fingerprint(text):
    """Hash exact text without storing its plaintext."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def prepare_forget_schema():
    """Create exact-text forgetting markers."""
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS forgotten_fingerprints (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                fingerprint TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(user_id, fingerprint),
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
            """
        )


def is_forgotten(text, user_id=DEFAULT_USER_ID):
    """Check whether this exact text has been forgotten."""
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT id
            FROM forgotten_fingerprints
            WHERE user_id = ?
              AND fingerprint = ?
            """,
            (user_id, fingerprint(text)),
        ).fetchone()

    return row is not None


def forget_fact(fact_id, user_id=DEFAULT_USER_ID):
    """Delete a fact's source note and associated records.

    Deletion is logical removal from the live SQLite database.
    It does not guarantee physical erasure of database pages,
    WAL files, backups or operating-system snapshots.
    """
    with get_connection() as conn:
        target = conn.execute(
            """
            SELECT f.id, f.note_id, f.statement, n.raw_text
            FROM facts f
            JOIN notes n
              ON n.id = f.note_id
             AND n.user_id = f.user_id
            WHERE f.id = ?
              AND f.user_id = ?
            """,
            (fact_id, user_id),
        ).fetchone()

        if target is None:
            raise ValueError("Fact not found.")

        note_id = target["note_id"]

        related = conn.execute(
            """
            SELECT id, statement
            FROM facts
            WHERE user_id = ? AND note_id = ?
            """,
            (user_id, note_id),
        ).fetchall()

        related_ids = [row["id"] for row in related]

        # Remember exact original strings without retaining plaintext.
        texts = [target["raw_text"]]
        texts.extend(row["statement"] for row in related)

        for value in set(texts):
            conn.execute(
                """
                INSERT OR IGNORE INTO forgotten_fingerprints (
                    user_id, fingerprint, created_at
                )
                VALUES (?, ?, ?)
                """,
                (user_id, fingerprint(value), utc_now()),
            )

        # Remove references pointing to facts being deleted.
        for related_id in related_ids:
            conn.execute(
                """
                UPDATE facts
                SET superseded_by = NULL
                WHERE user_id = ?
                  AND superseded_by = ?
                """,
                (user_id, related_id),
            )

        # Delete approval rows first to satisfy foreign keys.
        conn.execute(
            """
            DELETE FROM approvals
            WHERE user_id = ?
              AND fact_id IN (
                  SELECT id FROM facts
                  WHERE user_id = ? AND note_id = ?
              )
            """,
            (user_id, user_id, note_id),
        )

        # Remove historical audit entries for these records.
        conn.execute(
            """
            DELETE FROM audit_log
            WHERE user_id = ?
              AND entity_type = 'note'
              AND entity_id = ?
            """,
            (user_id, note_id),
        )

        for related_id in related_ids:
            conn.execute(
                """
                DELETE FROM audit_log
                WHERE user_id = ?
                  AND entity_type = 'fact'
                  AND entity_id = ?
                """,
                (user_id, related_id),
            )

        conn.execute(
            """
            DELETE FROM facts
            WHERE user_id = ? AND note_id = ?
            """,
            (user_id, note_id),
        )

        conn.execute(
            """
            DELETE FROM notes
            WHERE user_id = ? AND id = ?
            """,
            (user_id, note_id),
        )

        # Metadata-only audit: no original text.
        conn.execute(
            """
            INSERT INTO audit_log (
                user_id, action, entity_type,
                entity_id, created_at
            )
            VALUES (?, 'forget', 'fact', ?, ?)
            """,
            (user_id, fact_id, utc_now()),
        )

    return {
        "forgotten_fact_id": fact_id,
        "removed_note_id": note_id,
        "removed_facts": len(related_ids),
    }
