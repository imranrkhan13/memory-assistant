
"""Phase 4: atomic approval, superseding and fact history."""
from .storage import (
    DEFAULT_USER_ID,
    get_connection,
    utc_now,
    check_secrets,
)

def _audit(conn, user_id, action, entity_type, entity_id):
    conn.execute(
        """
        INSERT INTO audit_log (user_id, action, entity_type, entity_id, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (user_id, action, entity_type, entity_id, utc_now()),
    )


def resolve_update(
    approval_id,
    decision,
    edited_statement=None,
    user_id=DEFAULT_USER_ID,
):
    """Approve or reject a pending fact.
    On approval, supersede conflicting active facts atomically.
    """
    if decision not in ("approved", "rejected"):
        raise ValueError("Decision must be approved or rejected.")

    if edited_statement is not None:
        if (
            not edited_statement.strip()
            or check_secrets(edited_statement)
        ):
            raise ValueError(
                "Invalid or secret-like edited statement."
            )

    with get_connection() as conn:
        approval = conn.execute(
            """
            SELECT a.fact_id, f.subject, f.value, f.statement
            FROM approvals a
            JOIN facts f
              ON f.id = a.fact_id
             AND f.user_id = a.user_id
            WHERE a.id = ?
              AND a.user_id = ?
              AND a.status = 'pending'
              AND f.status = 'pending'
            """,
            (approval_id, user_id),).fetchone()

        if approval is None:
            raise ValueError("Pending approval not found.")
        fact_id = approval["fact_id"]
        if decision == "approved":
            if edited_statement is not None:
                conn.execute(
                    """
                    UPDATE facts
                    SET statement = ?
                    WHERE id = ? AND user_id = ?
                    """,
                    (
                        edited_statement.strip(),
                        fact_id,
                        user_id,
                    ),
                )

            old_facts = conn.execute(
                """
                SELECT id
                FROM facts
                WHERE user_id = ?
                  AND subject = ?
                  AND status = 'active'
                  AND id <> ?
                """,
                (user_id, approval["subject"], fact_id),
            ).fetchall()

            for old in old_facts:
                conn.execute(
                    """
                    UPDATE facts
                    SET status = 'superseded',
                        superseded_by = ?
                    WHERE id = ? AND user_id = ?
                    """,
                    (fact_id, old["id"], user_id),
                )

                _audit(
                    conn,
                    user_id,
                    "supersede",
                    "fact",
                    old["id"],
                )

            conn.execute(
                """
                UPDATE facts
                SET status = 'active'
                WHERE id = ? AND user_id = ?
                """,
                (fact_id, user_id),
            )

        else:
            # Existing schema does not have a rejected fact status.
            conn.execute(
                """
                UPDATE facts
                SET status = 'superseded'
                WHERE id = ? AND user_id = ?
                """,
                (fact_id, user_id),
            )

        conn.execute(
            """
            UPDATE approvals
            SET status = ?, resolved_at = ?
            WHERE id = ? AND user_id = ?
            """,
            (
                decision,
                utc_now(),
                approval_id,
                user_id,
            ),
        )

        _audit(
            conn,
            user_id,
            decision,
            "fact",
            fact_id,
        )

        return {
            "fact_id": fact_id,
            "decision": decision,
        }


def fact_history(subject, user_id=DEFAULT_USER_ID):
    """Return all fact versions for a subject."""
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                f.id,
                f.subject,
                f.value,
                f.statement,
                f.status,
                f.superseded_by,
                f.note_id,
                n.created_at
            FROM facts f
            JOIN notes n
              ON n.id = f.note_id
             AND n.user_id = f.user_id
            WHERE f.user_id = ?
              AND f.subject = ?
            ORDER BY f.id
            """,
            (user_id, subject),
        ).fetchall()

    return [dict(row) for row in rows]
