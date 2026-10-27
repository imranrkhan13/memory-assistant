"""Test recovery after a real worker process is killed."""

import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from memory_assistant import storage
from memory_assistant.jobs import (
    create_job,
    get_job,
    init_jobs,
    recover_expired_jobs,
)
from memory_assistant.pipeline import prepare_schema
from memory_assistant.worker import process_next_job


class FixedProvider:
    name = "process-crash-test"

    def extract(self, text):
        return [{
            "subject": "fictional_appointment",
            "value": "9 AM",
            "statement": "My fictional appointment is at 9 AM.",
            "confidence": 0.99,
        }]


class ProcessCrashTests(unittest.TestCase):

    def test_killed_worker_job_can_be_recovered(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "crash_test.db"
            ready_file = Path(directory) / "worker_ready"

            with patch.object(storage, "DB_PATH", db_path):
                storage.init_db()
                prepare_schema()
                init_jobs()

                note_id = storage.add_note(
                    "My fictional appointment is at 9 AM."
                )
                job_id = create_job(note_id)

                child_code = """
import sys
import time
from pathlib import Path

from memory_assistant import storage
from memory_assistant.jobs import claim_job

storage.DB_PATH = Path(sys.argv[1])
ready_file = Path(sys.argv[2])

job = claim_job(lease_seconds=120)
if job is None:
    sys.exit(2)

ready_file.write_text(job["id"])
time.sleep(300)
"""

                process = subprocess.Popen(
                    [
                        sys.executable,
                        "-c",
                        child_code,
                        str(db_path),
                        str(ready_file),
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    cwd=str(Path(__file__).resolve().parent.parent),
                )

                try:
                    deadline = time.monotonic() + 10

                    while not ready_file.exists():
                        if process.poll() is not None:
                            stderr = process.stderr.read().decode(
                                errors="replace"
                            )
                            self.fail(
                                f"Worker exited before claiming: {stderr}"
                            )

                        if time.monotonic() >= deadline:
                            self.fail("Worker did not claim job in time")

                        time.sleep(0.02)

                    self.assertEqual(
                        ready_file.read_text(),
                        job_id,
                    )

                    self.assertEqual(
                        get_job(job_id)["status"],
                        "running",
                    )

                    # Simulate a real abrupt worker crash.
                    process.kill()
                    process.wait(timeout=5)

                    # The killed process cannot release its lease.
                    self.assertEqual(
                        get_job(job_id)["status"],
                        "running",
                    )

                    # Simulate the passage of the 120-second
                    # lease without making the test wait.
                    with storage.get_connection() as conn:
                        conn.execute(
                            """
                            UPDATE processing_jobs
                            SET lease_until = ?
                            WHERE id = ?
                            """,
                            (
                                "2000-01-01T00:00:00+00:00",
                                job_id,
                            ),
                        )

                    recovered = recover_expired_jobs()
                    self.assertEqual(recovered, 1)

                    self.assertEqual(
                        get_job(job_id)["status"],
                        "queued",
                    )

                    # Make the recovered job immediately
                    # eligible, including implementations
                    # with delayed retry scheduling.
                    with storage.get_connection() as conn:
                        conn.execute(
                            """
                            UPDATE processing_jobs
                            SET available_at = ?
                            WHERE id = ?
                              AND status = 'queued'
                            """,
                            (
                                "2000-01-01T00:00:00+00:00",
                                job_id,
                            ),
                        )

                    result = process_next_job(
                        provider=FixedProvider()
                    )

                    self.assertIsNotNone(result)
                    self.assertEqual(
                        result["status"],
                        "succeeded",
                    )
                    self.assertEqual(
                        result["attempts"],
                        2,
                    )

                    with storage.get_connection() as conn:
                        count = conn.execute(
                            """
                            SELECT COUNT(*)
                            FROM facts
                            WHERE note_id = ?
                            """,
                            (note_id,),
                        ).fetchone()[0]

                    self.assertEqual(count, 1)

                finally:
                    if process.poll() is None:
                        process.kill()
                        process.wait(timeout=5)

                    if process.stderr:
                        process.stderr.close()


if __name__ == "__main__":
    unittest.main()
