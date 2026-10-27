"""Durable SQLite-backed processing jobs for Personal Memory Assistant.

Phase 7 foundation. Does not automatically modify existing note extraction.
"""
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from .storage import get_connection
SAFE_ERROR_MESSAGES = {
    "No facts extracted; review the note or provider.",
    "Provider HTTP failure; check configuration or quota.",
    "Provider connection failed or timed out.",
    "Configure the Gemini key and model, then reprocess.",
    "Provider returned invalid or unusable data; review provider configuration.",
    "Invalid configuration or extraction data; review and reprocess.",
    "Processing interrupted; retry scheduled.",
}

def now():
    return datetime.now(timezone.utc).isoformat()

def init_jobs():
    """Create job and trace tables without removing existing data."""
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS processing_jobs (
                id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                note_id INTEGER NOT NULL,
                job_type TEXT NOT NULL DEFAULT 'extract',
                status TEXT NOT NULL DEFAULT 'queued'
                    CHECK (status IN (
                        'queued', 'running', 'succeeded',
                        'failed', 'cancelled'
                    )),
                attempts INTEGER NOT NULL DEFAULT 0,
                max_attempts INTEGER NOT NULL DEFAULT 3,
                checkpoint TEXT NOT NULL DEFAULT 'note_saved',
                idempotency_key TEXT UNIQUE,
                lease_token TEXT,
                lease_until TEXT,
                available_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                started_at TEXT,
                completed_at TEXT,
                last_error_code TEXT,
                last_error_message TEXT,
                FOREIGN KEY (note_id) REFERENCES notes(id)
            );

            CREATE INDEX IF NOT EXISTS idx_jobs_status
            ON processing_jobs(status, available_at);

            CREATE INDEX IF NOT EXISTS idx_jobs_note
            ON processing_jobs(note_id);

            CREATE TABLE IF NOT EXISTS processing_traces (
                id TEXT PRIMARY KEY,
                job_id TEXT NOT NULL,
                operation TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                duration_ms INTEGER,
                error_code TEXT,
                extracted_count INTEGER DEFAULT 0,
                saved_count INTEGER DEFAULT 0,
                FOREIGN KEY (job_id)
                    REFERENCES processing_jobs(id)
                    ON DELETE CASCADE
            );
        """)


def create_job(
    note_id,
    user_id=1,
    job_type="extract",
    idempotency_key=None,
    max_attempts=3,
):
    """Create a queued processing job."""
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")

    init_jobs()

    job_id = str(uuid.uuid4())
    timestamp = now()

    with get_connection() as conn:
        if idempotency_key:
            existing = conn.execute(
                """
                SELECT id FROM processing_jobs
                WHERE idempotency_key = ?
                """,
                (idempotency_key,),
            ).fetchone()

            if existing:
                return existing["id"]

        conn.execute(
            """
            INSERT INTO processing_jobs (
                id, user_id, note_id, job_type, status,
                max_attempts, idempotency_key,
                available_at, created_at
            )
            VALUES (?, ?, ?, ?, 'queued', ?, ?, ?, ?)
            """,
            (
                job_id,
                user_id,
                note_id,
                job_type,
                max_attempts,
                idempotency_key,
                timestamp,
                timestamp,
            ),
        )

    return job_id


def get_job(job_id, user_id=1):
    """Read a job belonging to the given user."""
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT * FROM processing_jobs
            WHERE id = ? AND user_id = ?
            """,
            (job_id, user_id),
        ).fetchone()

        return dict(row) if row else None


def list_jobs(user_id=1, status=None, limit=100):
    """List jobs for a user."""
    limit = max(1, min(int(limit), 500))

    with get_connection() as conn:
        if status:
            rows = conn.execute(
                """
                SELECT * FROM processing_jobs
                WHERE user_id = ? AND status = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (user_id, status, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT * FROM processing_jobs
                WHERE user_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()

    return [dict(row) for row in rows]


def claim_job(user_id=1, lease_seconds=120):
    """Atomically claim one available job."""
    init_jobs()

    timestamp = now()
    lease_until = (
        datetime.now(timezone.utc)
        + timedelta(seconds=lease_seconds)
    ).isoformat()
    token = str(uuid.uuid4())

    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")

        row = conn.execute(
            """
            SELECT id FROM processing_jobs
            WHERE user_id = ?
              AND status = 'queued'
              AND available_at <= ?
              AND attempts < max_attempts
            ORDER BY created_at ASC
            LIMIT 1
            """,
            (user_id, timestamp),
        ).fetchone()

        if not row:
            return None

        conn.execute(
            """
            UPDATE processing_jobs
            SET status = 'running',
                attempts = attempts + 1,
                started_at = ?,
                lease_token = ?,
                lease_until = ?,
                checkpoint = 'extraction_started'
            WHERE id = ? AND status = 'queued'
            """,
            (timestamp, token, lease_until, row["id"]),
        )

        job = conn.execute(
            "SELECT * FROM processing_jobs WHERE id = ?",
            (row["id"],),
        ).fetchone()

    return dict(job)


def complete_job(job_id, lease_token):
    """Mark a job successful only if the caller owns its lease."""
    with get_connection() as conn:
        cursor = conn.execute(
            """
            UPDATE processing_jobs
            SET status = 'succeeded',
                checkpoint = 'processing_completed',
                completed_at = ?,
                lease_token = NULL,
                lease_until = NULL,
                last_error_code = NULL,
                last_error_message = NULL
            WHERE id = ?
              AND status = 'running'
              AND lease_token = ?
              AND lease_until > ?
            """,
            (now(), job_id, lease_token, now()),
        )

        return cursor.rowcount == 1



def fail_job(
    job_id,
    lease_token,
    error_code="PROCESSING_ERROR",
    error_message="Processing failed",
    transient=True,
):
    """Retry a failed attempt or permanently fail after max attempts.

    Delays: 5 seconds, 10 seconds, 20 seconds, ...
    Only the worker holding the current lease can update the job.
    """
    timestamp = now()
    safe_code = str(error_code)[:80]
    # Caller supplies only a fixed, content-free classification.
    safe_message = error_message if error_message in SAFE_ERROR_MESSAGES else "Note processing failed"

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

        can_retry = transient and row["attempts"] < row["max_attempts"]

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


def retry_job(job_id, user_id=1):
    """Manually requeue a failed job if attempts remain."""
    with get_connection() as conn:
        cursor = conn.execute(
            """
            UPDATE processing_jobs
            SET status = 'queued',
                available_at = ?,
                completed_at = NULL,
                last_error_code = NULL,
                last_error_message = NULL,
                lease_token = NULL,
                lease_until = NULL
            WHERE id = ?
              AND user_id = ?
              AND status = 'failed'
              AND attempts < max_attempts
            """,
            (now(), job_id, user_id),
        )

        return cursor.rowcount == 1


def recover_expired_jobs():
    """Recover jobs whose processing leases have expired."""
    timestamp = now()

    with get_connection() as conn:
        cursor = conn.execute(
            """
            UPDATE processing_jobs
            SET status = CASE
                    WHEN attempts < max_attempts
                    THEN 'queued'
                    ELSE 'failed'
                END,
                available_at = ?,
                lease_token = NULL,
                lease_until = NULL,
                last_error_code = 'LEASE_EXPIRED',
                last_error_message = 'Processing was interrupted'
            WHERE status = 'running'
              AND lease_until <= ?
            """,
            (timestamp, timestamp),
        )

        return cursor.rowcount


def cancel_note_jobs(note_id, user_id=1):
    """Cancel pending jobs for a note, including running jobs."""
    with get_connection() as conn:
        cursor = conn.execute(
            """
            UPDATE processing_jobs
            SET status = 'cancelled',
                completed_at = ?,
                lease_token = NULL,
                lease_until = NULL
            WHERE note_id = ?
              AND user_id = ?
              AND status IN ('queued', 'running', 'failed')
            """,
            (now(), note_id, user_id),
        )

        return cursor.rowcount


def add_trace(
    job_id,
    operation,
    status,
    duration_ms=None,
    error_code=None,
    extracted_count=0,
    saved_count=0,
):
    """Record processing metadata, not note or prompt content."""
    trace_id = str(uuid.uuid4())

    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO processing_traces (
                id, job_id, operation, status,
                created_at, duration_ms, error_code,
                extracted_count, saved_count
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                trace_id,
                job_id,
                operation,
                status,
                now(),
                duration_ms,
                error_code,
                extracted_count,
                saved_count,
            ),
        )

    return trace_id


def owns_job_lease(job_id, lease_token):
    """Return True only when the current lease is still valid."""
    if not job_id or not lease_token:
        return False

    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT 1
            FROM processing_jobs
            WHERE id = ?
              AND status = 'running'
              AND lease_token = ?
              AND lease_until > ?
            """,
            (job_id, lease_token, now()),
        ).fetchone()

    return row is not None


def renew_job_lease(job_id, lease_token, lease_seconds=120):
    """Extend a valid lease without allowing expired workers to renew."""
    if not isinstance(lease_seconds, int) or not 1 <= lease_seconds <= 3600:
        raise ValueError("lease_seconds must be between 1 and 3600")

    if not job_id or not lease_token:
        return False

    current_time = datetime.now(timezone.utc)
    new_expiry = (
        current_time + timedelta(seconds=lease_seconds)
    ).isoformat()

    with get_connection() as conn:
        cursor = conn.execute(
            """
            UPDATE processing_jobs
            SET lease_until = ?
            WHERE id = ?
              AND status = 'running'
              AND lease_token = ?
              AND lease_until > ?
            """,
            (
                new_expiry,
                job_id,
                lease_token,
                current_time.isoformat(),
            ),
        )

        return cursor.rowcount == 1
