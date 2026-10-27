
"""Continuous background worker for Personal Memory Assistant.
Examples:
    python3 -m memory_assistant.job_daemon
    python3 -m memory_assistant.job_daemon --interval 2
    python3 -m memory_assistant.job_daemon --once
"""
import argparse
import signal
import time

from .jobs import init_jobs
from .storage import init_db
from .worker import process_next_job


def main():
    from .config import load_env
    load_env()
    from .pipeline import prepare_schema
    init_db()
    prepare_schema()
    parser = argparse.ArgumentParser(
        description="Personal Memory Assistant background worker"
    )

    parser.add_argument(
        "--interval",
        type=float,
        default=2.0,
        help="Seconds between checks when the queue is empty",
    )

    parser.add_argument(
        "--once",
        action="store_true",
        help="Process one job and exit",
    )

    args = parser.parse_args()

    if not 0.2 <= args.interval <= 300:
        parser.error("--interval must be between 0.2 and 300")

    init_db()
    init_jobs()

    stopping = False

    def stop_handler(signum, frame):
        nonlocal stopping
        stopping = True
        print("\nStopping worker after current operation...", flush=True)

    signal.signal(signal.SIGINT, stop_handler)
    signal.signal(signal.SIGTERM, stop_handler)

    print("Memory Assistant background worker started.", flush=True)

    while not stopping:
        try:
            job = process_next_job()

            if job is not None:
                print(
                    f"Job {job['id']} | "
                    f"Note #{job['note_id']} | "
                    f"Status: {job['status']}",
                    flush=True,
                )

            if args.once:
                break

            if job is None:
                time.sleep(args.interval)

        except Exception as error:
            # Avoid printing sensitive provider error details.
            print(
                f"Worker error: {type(error).__name__}",
                flush=True,
            )

            if args.once:
                raise

            time.sleep(args.interval)

    print("Memory Assistant background worker stopped.", flush=True)


if __name__ == "__main__":
    main()

