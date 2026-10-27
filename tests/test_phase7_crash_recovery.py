"""Phase 7: crash recovery, retry exhaustion, and job idempotency."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from memory_assistant import storage
from memory_assistant.jobs import (
    claim_job,
    create_job,
    get_job,
    init_jobs,
    recover_expired_jobs,
)
from memory_assistant.pipeline import prepare_schema
from memory_assistant.worker import process_next_job


EXPIRED = "2000-01-01T00:00:00+00:00"


class FixedProvider:
    name = "crash-recovery-test"

    def extract(self, text):
        return [{
            "subject": "fictional_appointment",
            "value": "9 AM",
            "statement": "My fictional appointment is at 9 AM.",
            "confidence": 0.99,
        }]


class CrashRecoveryTests(unittest.TestCase):

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(
            storage,
            "DB_PATH",
            Path(self.tempdir.name) / "test.db",
        )
        self.db_patch.start()

        storage.init_db()
        prepare_schema()
        init_jobs()

        self.note_id = storage.add_note(
            "My fictional appointment is at 9 AM."
        )

        self.job_id = create_job(
            self.note_id,
            max_attempts=3,
        )

    def tearDown(self):
        self.db_patch.stop()
        self.tempdir.cleanup()

    def expire_job(self):
        with storage.get_connection() as conn:
            conn.execute(
                """
                UPDATE processing_jobs
                SET lease_until = ?
                WHERE id = ?
                """,
                (EXPIRED, self.job_id),
            )

    def make_available(self):
        with storage.get_connection() as conn:
            conn.execute(
                """
                UPDATE processing_jobs
                SET available_at = ?
                WHERE id = ?
                  AND status = 'queued'
                """,
                (EXPIRED, self.job_id),
            )

    def fact_count(self):
        with storage.get_connection() as conn:
            return conn.execute(
                """
                SELECT COUNT(*)
                FROM facts
                WHERE note_id = ?
                """,
                (self.note_id,),
            ).fetchone()[0]

    def test_expired_running_job_is_recovered(self):
        first = claim_job()
        self.assertIsNotNone(first)

        self.expire_job()

        recovered = recover_expired_jobs()
        self.assertEqual(recovered, 1)

        job = get_job(self.job_id)

        self.assertEqual(job["status"], "queued")
        self.assertIsNone(job["lease_token"])
        self.assertIsNone(job["lease_until"])
        self.assertEqual(job["attempts"], 1)

    def test_recovered_job_can_succeed(self):
        first = claim_job()
        self.assertIsNotNone(first)

        self.expire_job()
        self.assertEqual(recover_expired_jobs(), 1)

        # This also accommodates delayed retry scheduling.
        self.make_available()

        result = process_next_job(
            provider=FixedProvider()
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["attempts"], 2)
        self.assertEqual(self.fact_count(), 1)

    def test_retry_exhaustion_marks_job_failed(self):
        for attempt in range(1, 4):
            claimed = claim_job()
            self.assertIsNotNone(claimed)
            self.assertEqual(claimed["attempts"], attempt)

            self.expire_job()
            self.assertEqual(recover_expired_jobs(), 1)

            current = get_job(self.job_id)

            if attempt < 3:
                self.assertEqual(current["status"], "queued")
                self.make_available()
            else:
                self.assertEqual(current["status"], "failed")

        self.assertIsNone(claim_job())
        self.assertEqual(self.fact_count(), 0)

    def test_completed_job_is_not_recovered_twice(self):
        result = process_next_job(
            provider=FixedProvider()
        )

        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(self.fact_count(), 1)

        self.assertEqual(recover_expired_jobs(), 0)

        second = process_next_job(
            provider=FixedProvider()
        )

        self.assertIsNone(second)
        self.assertEqual(self.fact_count(), 1)

        final = get_job(self.job_id)
        self.assertEqual(final["status"], "succeeded")
        self.assertEqual(final["attempts"], 1)


if __name__ == "__main__":
    unittest.main()
