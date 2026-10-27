
"""Tests for Phase 7 worker lease ownership and renewal."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from memory_assistant import storage
from memory_assistant.jobs import (
    claim_job,
    create_job,
    init_jobs,
    owns_job_lease,
    renew_job_lease,
)


class Phase7LeaseTests(unittest.TestCase):

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

        note_id = storage.add_note(
            "My fictional library book is due on November 3."
        )

        self.job_id = create_job(note_id)
        self.job = claim_job()

    def tearDown(self):
        self.db_patch.stop()
        self.tempdir.cleanup()

    def test_valid_lease_is_owned(self):
        self.assertTrue(
            owns_job_lease(
                self.job_id,
                self.job["lease_token"],
            )
        )

    def test_invalid_token_is_rejected(self):
        self.assertFalse(
            owns_job_lease(
                self.job_id,
                "wrong-token",
            )
        )

    def test_valid_lease_can_be_renewed(self):
        self.assertTrue(
            renew_job_lease(
                self.job_id,
                self.job["lease_token"],
                lease_seconds=300,
            )
        )

        self.assertTrue(
            owns_job_lease(
                self.job_id,
                self.job["lease_token"],
            )
        )

    def test_invalid_token_cannot_renew(self):
        self.assertFalse(
            renew_job_lease(
                self.job_id,
                "wrong-token",
            )
        )

    def test_expired_lease_cannot_be_renewed(self):
        from memory_assistant.storage import get_connection

        with get_connection() as conn:
            conn.execute(
                """
                UPDATE processing_jobs
                SET lease_until = ?
                WHERE id = ?
                """,
                ("2000-01-01T00:00:00+00:00", self.job_id),
            )

        self.assertFalse(
            owns_job_lease(
                self.job_id,
                self.job["lease_token"],
            )
        )

        self.assertFalse(
            renew_job_lease(
                self.job_id,
                self.job["lease_token"],
            )
        )


if __name__ == "__main__":
    unittest.main()

