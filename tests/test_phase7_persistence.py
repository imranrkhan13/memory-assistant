
"""Phase 7 tests for lease-protected fact persistence."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from memory_assistant import storage
from memory_assistant.ai import process_note
from memory_assistant.pipeline import prepare_schema
from memory_assistant.jobs import (
    claim_job,
    complete_job,
    create_job,
    get_job,
    init_jobs,
)


class TestProvider:
    name = "phase7-test"

    def extract(self, text):
        return [
            {
                "subject": "test_appointment",
                "value": "9 AM",
                "statement": "My fictional appointment is at 9 AM.",
                "confidence": 0.99,
            }
        ]


class Phase7PersistenceTests(unittest.TestCase):

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

        self.job_id = create_job(self.note_id)
        self.job = claim_job()

        self.provider = TestProvider()

    def tearDown(self):
        self.db_patch.stop()
        self.tempdir.cleanup()

    def fact_count(self):
        with storage.get_connection() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS total
                FROM facts
                WHERE note_id = ?
                """,
                (self.note_id,),
            ).fetchone()

        return row["total"]

    def expire_lease(self):
        with storage.get_connection() as conn:
            conn.execute(
                """
                UPDATE processing_jobs
                SET lease_until = ?
                WHERE id = ?
                """,
                (
                    "2000-01-01T00:00:00+00:00",
                    self.job_id,
                ),
            )

    def test_valid_lease_saves_fact(self):
        result = process_note(
            self.note_id,
            provider=self.provider,
            job_id=self.job_id,
            lease_token=self.job["lease_token"],
        )

        self.assertEqual(self.fact_count(), 1)
        self.assertEqual(len(result), 1)

    def test_expired_lease_does_not_save_fact(self):
        self.expire_lease()

        with self.assertRaises(RuntimeError):
            process_note(
                self.note_id,
                provider=self.provider,
                job_id=self.job_id,
                lease_token=self.job["lease_token"],
            )

        self.assertEqual(self.fact_count(), 0)

    def test_invalid_token_does_not_save_fact(self):
        with self.assertRaises(RuntimeError):
            process_note(
                self.note_id,
                provider=self.provider,
                job_id=self.job_id,
                lease_token="invalid-token",
            )

        self.assertEqual(self.fact_count(), 0)

    def test_completed_job_cannot_save_again(self):
        self.assertTrue(
            complete_job(
                self.job_id,
                self.job["lease_token"],
            )
        )

        self.assertEqual(
            get_job(self.job_id)["status"],
            "succeeded",
        )

        with self.assertRaises(RuntimeError):
            process_note(
                self.note_id,
                provider=self.provider,
                job_id=self.job_id,
                lease_token=self.job["lease_token"],
            )

        self.assertEqual(self.fact_count(), 0)


if __name__ == "__main__":
    unittest.main()

