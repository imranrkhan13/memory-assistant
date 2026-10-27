
"""SAMPLE fact extraction and approval workflow."""

import sqlite3

from .providers import MockProvider
from .storage import (
    DEFAULT_USER_ID,
    check_secrets,
    get_connection,
    utc_now,
)

THRESHOLD = 0.85


def prepare_schema():
    """Add Phase 2 metadata to the existing database."""
    with get_connection() as conn:
        columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(facts)")
        }

        if "subject" not in columns:
            conn.execute(
                "ALTER TABLE facts ADD COLUMN subject TEXT"
            )

        if "value" not in columns:
            conn.execute(
                "ALTER TABLE facts ADD COLUMN value TEXT"
            )

        if "provider" not in columns:
            conn.execute(
                "ALTER TABLE facts ADD COLUMN provider TEXT"
            )


def extract_note(note_id, provider=None, user_id=DEFAULT_USER_ID):
    provider = provider or MockProvider()

    with get_connection() as conn:
        note = conn.execute(
            "SELECT raw_text FROM notes WHERE id=? AND user_id=?",
            (note_id, user_id),
        ).fetchone()

    if note is None:
        raise ValueError("Note not found.")

    if check_secrets(note["raw_text"]):
        raise ValueError("Secret-like content blocked.")

    candidates = provider.extract(note["raw_text"])
    results = []

    with get_connection() as conn:
        for fact in candidates:
            subject = fact["subject"]
            value = fact["value"]
            confidence = float(fact["confidence"])

            if not 0 <= confidence <= 1:
                raise ValueError("Invalid confidence.")

            conflict = conn.execute(
                """
                SELECT id FROM facts
                WHERE user_id=? AND subject=?
                AND status='active' AND value<>?
                LIMIT 1
                """,
                (user_id, subject, value),
            ).fetchone()

            existing = conn.execute(
                """
                SELECT id FROM facts
                WHERE user_id=? AND note_id=? AND subject=?
                LIMIT 1
                """,
                (user_id, note_id, subject),
            ).fetchone()

            if existing:
                results.append(("already_processed", existing["id"]))
                continue

            pending = confidence < THRESHOLD or conflict is not None
            status = "pending" if pending else "active"

            cursor = conn.execute(
                """
                INSERT INTO facts (
                    user_id, note_id, statement, status,
                    confidence, created_at, subject, value, provider
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id, note_id, fact["statement"], status,
                    confidence, utc_now(), subject, value,
                    provider.name,
                ),
            )

            fact_id = cursor.lastrowid

            if pending:
                reason = (
                    "conflict"
                    if conflict
                    else "low_confidence"
                )
                conn.execute(
                    """
                    INSERT INTO approvals (
                        user_id, fact_id, status, reason, created_at
                    )
                    VALUES (?, ?, 'pending', ?, ?)
                    """,
                    (user_id, fact_id, reason, utc_now()),
                )

            conn.execute(
                """
                INSERT INTO audit_log (
                    user_id, action, entity_type, entity_id, created_at
                )
                VALUES (?, ?, 'fact', ?, ?)
                """,
                (
                    user_id,
                    "propose" if pending else "activate",
                    fact_id,
                    utc_now(),
                ),
            )

            results.append((status, fact_id))

    return results


def pending_facts(user_id=DEFAULT_USER_ID):
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT a.id AS approval_id, f.id AS fact_id,
                   f.statement, a.reason
            FROM approvals a
            JOIN facts f ON f.id=a.fact_id
                         AND f.user_id=a.user_id
            WHERE a.user_id=? AND a.status='pending'
            ORDER BY a.id
            """,
            (user_id,),
        ).fetchall()
        return [dict(row) for row in rows]


def resolve_fact(approval_id, decision, edited_statement=None,
                 user_id=DEFAULT_USER_ID):
    if decision not in ("approved", "rejected"):
        raise ValueError("Invalid decision.")

    if edited_statement is not None:
        if not edited_statement.strip() or check_secrets(edited_statement):
            raise ValueError("Invalid or secret-like edit.")

    with get_connection() as conn:
        approval = conn.execute(
            """
            SELECT a.fact_id, f.subject, f.value
            FROM approvals a
            JOIN facts f ON f.id=a.fact_id
                         AND f.user_id=a.user_id
            WHERE a.id=? AND a.user_id=? AND a.status='pending'
            """,
            (approval_id, user_id),
        ).fetchone()

        if approval is None:
            raise ValueError("Pending approval not found.")

        if decision == "approved":
            # Conflicting facts remain pending until Phase 4
            # implements atomic superseding.
            conflict = conn.execute(
                """
                SELECT id FROM facts
                WHERE user_id=? AND subject=?
                  AND status='active' AND value<>?
                LIMIT 1
                """,
                (
                    user_id,
                    approval["subject"],
                    approval["value"],
                ),
            ).fetchone()

            if conflict:
                raise ValueError(
                    "Conflicting update requires Phase 4 superseding."
                )

        if edited_statement is not None:
            conn.execute(
                "UPDATE facts SET statement=? WHERE id=? AND user_id=?",
                (edited_statement, approval["fact_id"], user_id),
            )

        conn.execute(
            """
            UPDATE facts SET status=?
            WHERE id=? AND user_id=?
            """,
            (
                "active" if decision == "approved" else "superseded",
                approval["fact_id"],
                user_id,
            ),
        )

        conn.execute(
            """
            UPDATE approvals SET status=?, resolved_at=?
            WHERE id=? AND user_id=?
            """,
            (decision, utc_now(), approval_id, user_id),
        )

        conn.execute(
            """
            INSERT INTO audit_log (
                user_id, action, entity_type, entity_id, created_at
            )
            VALUES (?, ?, 'fact', ?, ?)
            """,
            (
                user_id, decision, approval["fact_id"], utc_now()
            ),
        )
