"""Tests for browser job dashboard and retry actions."""

import tempfile
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
from memory_assistant.web import render_jobs


class JobsWebTests(unittest.TestCase):

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
            "My fictional meeting is tomorrow."
        )

        self.job_id = create_job(self.note_id)

    def tearDown(self):
        self.db_patch.stop()
        self.tempdir.cleanup()

    def test_dashboard_displays_queued_job(self):
        page = render_jobs()

        self.assertIn("Processing Jobs", page)
        self.assertIn("QUEUED", page)
        self.assertIn(self.job_id, page)

    def test_running_job_is_visible(self):
        claimed = claim_job()
        self.assertIsNotNone(claimed)

        page = render_jobs()

        self.assertIn("RUNNING", page)
        self.assertNotIn('action="/jobs/retry"', page)

    def test_succeeded_job_has_no_retry_button(self):
        claimed = claim_job()

        self.assertTrue(
            complete_job(
                self.job_id,
                claimed["lease_token"],
            )
        )

        page = render_jobs()

        self.assertIn("SUCCEEDED", page)
        self.assertNotIn('action="/jobs/retry"', page)

    def test_failed_job_with_attempts_remaining_has_retry(self):
        with storage.get_connection() as conn:
            conn.execute(
                """
                UPDATE processing_jobs
                SET status = 'failed',
                    attempts = 1,
                    max_attempts = 3,
                    last_error_code = 'TEST_FAILURE'
                WHERE id = ?
                """,
                (self.job_id,),
            )

        page = render_jobs()

        self.assertIn("FAILED", page)
        self.assertIn("TEST_FAILURE", page)
        self.assertIn('action="/jobs/retry"', page)

    def test_exhausted_job_has_no_retry_button(self):
        with storage.get_connection() as conn:
            conn.execute(
                """
                UPDATE processing_jobs
                SET status = 'failed',
                    attempts = 3,
                    max_attempts = 3
                WHERE id = ?
                """,
                (self.job_id,),
            )

        page = render_jobs()

        self.assertIn("Retry limit reached", page)
        self.assertNotIn('action="/jobs/retry"', page)

    def test_retry_job_requeues_failed_job(self):
        from memory_assistant.jobs import retry_job

        with storage.get_connection() as conn:
            conn.execute(
                """
                UPDATE processing_jobs
                SET status = 'failed',
                    attempts = 1
                WHERE id = ?
                """,
                (self.job_id,),
            )

        self.assertTrue(retry_job(self.job_id))

        job = get_job(self.job_id)

        self.assertEqual(job["status"], "queued")
        self.assertEqual(job["attempts"], 1)


if __name__ == "__main__":
    unittest.main()
