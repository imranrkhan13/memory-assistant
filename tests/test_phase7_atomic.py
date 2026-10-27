
"""Tests for atomic fact persistence and job completion."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from memory_assistant import storage
from memory_assistant.ai import process_note
from memory_assistant.jobs import (
    claim_job,
    create_job,
    get_job,
    init_jobs,
)
from memory_assistant.pipeline import prepare_schema


class FixedProvider:
    name = "atomic-test"

    def extract(self, text):
        return [{
            "subject": "appointment",
            "value": "9 AM",
            "statement": "My fictional appointment is at 9 AM.",
            "confidence": 0.99,
        }]


class AtomicPersistenceTests(unittest.TestCase):

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

    def tearDown(self):
        self.db_patch.stop()
        self.tempdir.cleanup()

    def test_fact_and_job_complete_together(self):
        process_note(
            self.note_id,
            provider=FixedProvider(),
            job_id=self.job_id,
            lease_token=self.job["lease_token"],
        )

        with storage.get_connection() as conn:
            fact_count = conn.execute(
                "SELECT COUNT(*) FROM facts WHERE note_id = ?",
                (self.note_id,),
            ).fetchone()[0]

        self.assertEqual(fact_count, 1)
        self.assertEqual(
            get_job(self.job_id)["status"],
            "succeeded",
        )

    def test_expired_lease_rolls_back(self):
        with storage.get_connection() as conn:
            conn.execute(
                """
                UPDATE processing_jobs
                SET lease_until = ?
                WHERE id = ?
                """,
                ("2000-01-01T00:00:00+00:00", self.job_id),
            )

        with self.assertRaises(RuntimeError):
            process_note(
                self.note_id,
                provider=FixedProvider(),
                job_id=self.job_id,
                lease_token=self.job["lease_token"],
            )

        with storage.get_connection() as conn:
            fact_count = conn.execute(
                "SELECT COUNT(*) FROM facts WHERE note_id = ?",
                (self.note_id,),
            ).fetchone()[0]

        self.assertEqual(fact_count, 0)
        self.assertEqual(
            get_job(self.job_id)["status"],
            "running",
        )


if __name__ == "__main__":
    unittest.main()

