
"""Terminal commands for Phase 7 processing jobs.

Run with:
    python3 -m memory_assistant.job_cli list
    python3 -m memory_assistant.job_cli run
    python3 -m memory_assistant.job_cli retry JOB_ID
"""

import argparse
import json

from .jobs import (
    create_job,
    get_job,
    init_jobs,
    list_jobs,
    recover_expired_jobs,
)
from .storage import DEFAULT_USER_ID, get_connection, init_db
from .worker import process_pending_jobs, retry_failed_job


def print_json(value):
    print(json.dumps(value, indent=2, default=str))


def main():
    from .config import load_env
    load_env()
    from .pipeline import prepare_schema
    init_db()
    prepare_schema()
    parser = argparse.ArgumentParser(
        description="Personal Memory Assistant - Phase 7 Jobs"
    )

    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
    )

    list_parser = subparsers.add_parser(
        "list",
        help="Show processing jobs",
    )
    list_parser.add_argument(
        "--status",
        choices=[
            "queued",
            "running",
            "succeeded",
            "failed",
            "cancelled",
        ],
    )

    run_parser = subparsers.add_parser(
        "run",
        help="Process queued jobs",
    )
    run_parser.add_argument(
        "--limit",
        type=int,
        default=10,
    )

    retry_parser = subparsers.add_parser(
        "retry",
        help="Retry a failed job",
    )
    retry_parser.add_argument("job_id")

    show_parser = subparsers.add_parser(
        "show",
        help="Show one job",
    )
    show_parser.add_argument("job_id")

    enqueue_parser = subparsers.add_parser(
        "enqueue",
        help="Queue an existing note",
    )
    enqueue_parser.add_argument(
        "note_id",
        type=int,
    )

    subparsers.add_parser(
        "recover",
        help="Recover expired jobs",
    )

    args = parser.parse_args()

    init_db()
    init_jobs()

    if args.command == "list":
        print_json(
            list_jobs(
                user_id=DEFAULT_USER_ID,
                status=args.status,
            )
        )

    elif args.command == "show":
        job = get_job(
            args.job_id,
            user_id=DEFAULT_USER_ID,
        )

        if job is None:
            parser.error("Job not found")

        print_json(job)

    elif args.command == "enqueue":
        with get_connection() as conn:
            note = conn.execute(
                """
                SELECT id FROM notes
                WHERE id = ? AND user_id = ?
                """,
                (args.note_id, DEFAULT_USER_ID),
            ).fetchone()

        if note is None:
            parser.error("Note not found")

        # One job per note, avoiding accidental duplicate extraction.
        with get_connection() as conn:
            existing = conn.execute(
                """
                SELECT id FROM processing_jobs
                WHERE note_id = ?
                  AND user_id = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (args.note_id, DEFAULT_USER_ID),
            ).fetchone()

        if existing:
            parser.error(
                "This note already has a processing job. "
                "Use show or retry instead."
            )

        job_id = create_job(
            note_id=args.note_id,
            user_id=DEFAULT_USER_ID,
            idempotency_key=f"extract-note-{args.note_id}",
        )

        print_json(
            get_job(job_id, user_id=DEFAULT_USER_ID)
        )

    elif args.command == "run":
        results = process_pending_jobs(
            user_id=DEFAULT_USER_ID,
            limit=args.limit,
        )

        print_json({
            "processed": len(results),
            "jobs": results,
        })

    elif args.command == "retry":
        job = retry_failed_job(
            args.job_id,
            user_id=DEFAULT_USER_ID,
        )
        print_json(job)

    elif args.command == "recover":
        count = recover_expired_jobs()
        print_json({
            "recovered": count,
        })


if __name__ == "__main__":
    main()

