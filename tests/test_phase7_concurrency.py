"""Phase 7: concurrent job claiming and SQLite locking."""

import concurrent.futures
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from memory_assistant import storage
from memory_assistant.jobs import (
    claim_job,
    complete_job,
    create_job,
    get_job,
    init_jobs,
)


class ConcurrencyTests(unittest.TestCase):

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

    def tearDown(self):
        self.db_patch.stop()
        self.tempdir.cleanup()

    def create_test_job(self):
        note_id = storage.add_note(
            "My fictional meeting is at 9 AM."
        )
        return create_job(note_id)

    def test_only_one_worker_claims_single_job(self):
        job_id = self.create_test_job()

        worker_count = 5
        barrier = threading.Barrier(worker_count)

        def attempt_claim(_):
            barrier.wait(timeout=5)
            return claim_job()

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=worker_count
        ) as executor:
            results = list(
                executor.map(
                    attempt_claim,
                    range(worker_count),
                )
            )

        claimed = [
            result for result in results
            if result is not None
        ]

        self.assertEqual(len(claimed), 1)
        self.assertEqual(claimed[0]["id"], job_id)
        self.assertEqual(claimed[0]["attempts"], 1)

        job = get_job(job_id)
        self.assertEqual(job["status"], "running")
        self.assertEqual(job["attempts"], 1)

    def test_multiple_jobs_are_claimed_once_each(self):
        job_ids = {
            self.create_test_job()
            for _ in range(5)
        }

        worker_count = 5
        barrier = threading.Barrier(worker_count)

        def attempt_claim(_):
            barrier.wait(timeout=5)
            return claim_job()

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=worker_count
        ) as executor:
            results = list(
                executor.map(
                    attempt_claim,
                    range(worker_count),
                )
            )

        claimed_ids = [
            result["id"]
            for result in results
            if result is not None
        ]

        self.assertEqual(len(claimed_ids), 5)
        self.assertEqual(len(set(claimed_ids)), 5)
        self.assertEqual(set(claimed_ids), job_ids)

        for job_id in job_ids:
            self.assertEqual(
                get_job(job_id)["attempts"],
                1,
            )

    def test_completed_job_cannot_be_claimed_again(self):
        job_id = self.create_test_job()

        claimed = claim_job()
        self.assertIsNotNone(claimed)

        self.assertTrue(
            complete_job(
                job_id,
                claimed["lease_token"],
            )
        )

        self.assertIsNone(claim_job())

        job = get_job(job_id)
        self.assertEqual(job["status"], "succeeded")
        self.assertEqual(job["attempts"], 1)


if __name__ == "__main__":
    unittest.main()
