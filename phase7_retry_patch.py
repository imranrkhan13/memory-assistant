
"""Add automatic retry/backoff to the Phase 7 job system."""

from pathlib import Path

path = Path("memory_assistant/jobs.py")
source = path.read_text(encoding="utf-8")

start = source.index("\ndef fail_job(")
end = source.index("\ndef retry_job(", start)

replacement = '''

def fail_job(
    job_id,
    lease_token,
    error_code="PROCESSING_ERROR",
    error_message="Processing failed",
):
    """Retry a failed attempt or permanently fail after max attempts.

    Delays: 5 seconds, 10 seconds, 20 seconds, ...
    Only the worker holding the current lease can update the job.
    """
    timestamp = now()
    safe_code = str(error_code)[:80]
    safe_message = "Note processing failed"

    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")

        row = conn.execute(
            """
            SELECT attempts, max_attempts
            FROM processing_jobs
            WHERE id = ?
              AND status = 'running'
              AND lease_token = ?
            """,
            (job_id, lease_token),
        ).fetchone()

        if row is None:
            return False

        can_retry = row["attempts"] < row["max_attempts"]

        if can_retry:
            delay = min(
                300,
                5 * (2 ** min(row["attempts"] - 1, 6)),
            )
            next_attempt = (
                datetime.now(timezone.utc)
                + timedelta(seconds=delay)
            ).isoformat()

            status = "queued"
            completed_at = None
        else:
            next_attempt = timestamp
            status = "failed"
            completed_at = timestamp

        cursor = conn.execute(
            """
            UPDATE processing_jobs
            SET status = ?,
                available_at = ?,
                completed_at = ?,
                checkpoint = ?,
                lease_token = NULL,
                lease_until = NULL,
                last_error_code = ?,
                last_error_message = ?
            WHERE id = ?
              AND status = 'running'
              AND lease_token = ?
            """,
            (
                status,
                next_attempt,
                completed_at,
                "retry_scheduled" if can_retry else "failed",
                safe_code,
                safe_message,
                job_id,
                lease_token,
            ),
        )

        return cursor.rowcount == 1

'''

source = source[:start] + replacement + source[end:]

path.write_text(source, encoding="utf-8")
print("Automatic retry patch applied.")

