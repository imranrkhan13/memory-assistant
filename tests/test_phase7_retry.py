
"""Test Phase 7 automatic retry behavior."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from memory_assistant import storage
from memory_assistant.jobs import (
    claim_job,
    create_job,
    fail_job,
    get_job,
    init_jobs,
)


class Phase7RetryTests(unittest.TestCase):

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()

        self.db_patch = patch.object(
            storage,
            "DB_PATH",
            Path(self.tempdir.name) / "test.db",
        )
        self.db_patch.start()

        storage.init_db()
        init_jobs()

        self.note_id = storage.add_note(
            "My fictional library book is due on November 3."
        )

    def tearDown(self):
        self.db_patch.stop()
        self.tempdir.cleanup()

    def test_failure_schedules_retry(self):
        job_id = create_job(
            self.note_id,
            max_attempts=3,
        )

        job = claim_job()
        self.assertIsNotNone(job)

        updated = fail_job(
            job_id,
            job["lease_token"],
            error_code="TEST_FAILURE",
        )

        self.assertTrue(updated)

        result = get_job(job_id)

        self.assertEqual(result["status"], "queued")
        self.assertEqual(result["attempts"], 1)
        self.assertEqual(
            result["checkpoint"],
            "retry_scheduled",
        )

        # The retry is delayed, so it cannot be claimed immediately.
        self.assertIsNone(claim_job())

    def test_final_attempt_stays_failed(self):
        job_id = create_job(
            self.note_id,
            max_attempts=1,
        )

        job = claim_job()

        fail_job(
            job_id,
            job["lease_token"],
            error_code="TEST_FAILURE",
        )

        result = get_job(job_id)

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["attempts"], 1)
        self.assertEqual(result["checkpoint"], "failed")

    def test_old_lease_cannot_fail_job(self):
        job_id = create_job(self.note_id)
        job = claim_job()

        updated = fail_job(
            job_id,
            "incorrect-lease-token",
        )

        self.assertFalse(updated)
        self.assertEqual(
            get_job(job_id)["status"],
            "running",
        )


if __name__ == "__main__":
    unittest.main()

