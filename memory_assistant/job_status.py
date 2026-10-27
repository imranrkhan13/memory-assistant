
"""Phase 7 processing job status dashboard.

Usage:
    python3 -m memory_assistant.job_status
    python3 -m memory_assistant.job_status --limit 20
"""

import argparse

from .jobs import init_jobs
from .storage import DEFAULT_USER_ID, get_connection, init_db


def get_summary(user_id=DEFAULT_USER_ID, limit=10):
    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")

    init_db()
    init_jobs()

    conn = get_connection()

    try:
        counts = {
            "queued": 0,
            "running": 0,
            "succeeded": 0,
            "failed": 0,
            "cancelled": 0,
        }

        rows = conn.execute(
            """
            SELECT status, COUNT(*) AS total
            FROM processing_jobs
            WHERE user_id = ?
            GROUP BY status
            """,
            (user_id,),
        ).fetchall()

        for row in rows:
            counts[row["status"]] = row["total"]

        recent = conn.execute(
            """
            SELECT
                id,
                note_id,
                status,
                attempts,
                max_attempts,
                checkpoint,
                created_at,
                completed_at,
                last_error_code
            FROM processing_jobs
            WHERE user_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (user_id, limit),
        ).fetchall()

        return counts, [dict(row) for row in recent]

    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(
        description="Memory Assistant processing status"
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Number of recent jobs to display",
    )

    args = parser.parse_args()

    counts, recent = get_summary(limit=args.limit)

    print("\nMEMORY ASSISTANT - PROCESSING STATUS")
    print("=" * 42)

    for status in (
        "queued",
        "running",
        "succeeded",
        "failed",
        "cancelled",
    ):
        print(f"{status.capitalize():12} {counts[status]}")

    print("\nRECENT JOBS")
    print("-" * 42)

    if not recent:
        print("No processing jobs found.")
        return

    for job in recent:
        print(
            f"Note #{job['note_id']} | "
            f"{job['status'].upper()} | "
            f"Attempts {job['attempts']}/"
            f"{job['max_attempts']}"
        )

        print(f"  Job ID: {job['id']}")
        print(f"  Checkpoint: {job['checkpoint']}")

        if job["last_error_code"]:
            print(
                f"  Error: {job['last_error_code']}"
            )

        print()


if __name__ == "__main__":
    main()

