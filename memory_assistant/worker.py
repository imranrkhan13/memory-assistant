
"""Phase 7 processing worker.

Processes existing SQLite jobs using the current memory extraction
pipeline. Does not require any third-party packages.
"""

import time
from .job_heartbeat import JobHeartbeat
from .ai import process_note
from .jobs import (
    add_trace,
    claim_job,
    complete_job,
    fail_job,
    get_job,
    init_jobs,
    recover_expired_jobs,
    retry_job,
)
from .storage import DEFAULT_USER_ID, get_connection


def process_next_job(user_id=DEFAULT_USER_ID, provider=None):
    """Process one queued job and return its final state."""

    init_jobs()
    recover_expired_jobs()

    job = claim_job(user_id=user_id)

    if job is None:
        return None

    job_id = job["id"]
    note_id = job["note_id"]
    token = job["lease_token"]

    started = time.monotonic()

    try:
        # Check that the source note still exists.
        with get_connection() as conn:
            note = conn.execute(
                """
                SELECT id FROM notes
                WHERE id = ? AND user_id = ?
                """,
                (note_id, user_id),
            ).fetchone()

        if note is None:
            raise ValueError("Source note no longer exists")

        # Existing pipeline handles extraction, fact persistence,
        # conflict detection and approval creation.
        with JobHeartbeat(
            job_id=job_id,
            lease_token=token,
            interval_seconds=30,
            lease_seconds=120,
        ) as heartbeat:
            results = process_note(
                note_id,
                provider=provider,
                user_id=user_id,
                job_id=job_id,
                lease_token=token,
            )

        if heartbeat.lost_lease:
            raise RuntimeError(
                "Worker lost its job lease during processing"
            )

        # Fact persistence and job completion are committed
        # together by the extraction pipeline.
        completed = get_job(job_id, user_id=user_id)

        if completed is None or completed["status"] != "succeeded":
            raise RuntimeError(
                "Atomic job completion was not confirmed"
            )

        duration_ms = int(
            (time.monotonic() - started) * 1000
        )

        add_trace(
            job_id=job_id,
            operation="extract_note",
            status="succeeded",
            duration_ms=duration_ms,
        )

        return get_job(job_id, user_id=user_id)

    except Exception as error:
        # Avoid recording raw provider error messages because
        # they may contain sensitive request information.
        error_code = type(error).__name__

        fail_job(
            job_id,
            token,
            error_code=error_code,
            error_message="Note processing failed",
        )

        duration_ms = int(
            (time.monotonic() - started) * 1000
        )

        add_trace(
            job_id=job_id,
            operation="extract_note",
            status="failed",
            duration_ms=duration_ms,
            error_code=error_code,
        )

        return get_job(job_id, user_id=user_id)


def process_pending_jobs(
    user_id=DEFAULT_USER_ID,
    provider=None,
    limit=20,
):
    """Process up to limit queued jobs."""

    if not isinstance(limit, int) or not 1 <= limit <= 500:
        raise ValueError("limit must be between 1 and 500")

    processed = []

    for _ in range(limit):
        result = process_next_job(
            user_id=user_id,
            provider=provider,
        )

        if result is None:
            break

        processed.append(result)

    return processed


def retry_failed_job(job_id, user_id=DEFAULT_USER_ID):
    """Requeue a failed job when attempts remain."""

    init_jobs()

    if not retry_job(job_id, user_id=user_id):
        raise ValueError(
            "Job not found, not failed, or retry limit reached"
        )

    return get_job(job_id, user_id=user_id)

