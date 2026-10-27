
"""Tests for atomic note and job creation."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from memory_assistant import storage
from memory_assistant.jobs import init_jobs
from memory_assistant.queued_notes import add_queued_note


class QueuedNoteTests(unittest.TestCase):

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

    def count(self, table):
        with storage.get_connection() as conn:
            return conn.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone()[0]

    def test_note_and_job_created(self):
        note_id, job_id = add_queued_note(
            "My fictional appointment is at 9 AM."
        )

        with storage.get_connection() as conn:
            note = conn.execute(
                "SELECT * FROM notes WHERE id = ?",
                (note_id,),
            ).fetchone()

            job = conn.execute(
                "SELECT * FROM processing_jobs WHERE id = ?",
                (job_id,),
            ).fetchone()

        self.assertIsNotNone(note)
        self.assertIsNotNone(job)
        self.assertEqual(job["note_id"], note_id)
        self.assertEqual(job["status"], "queued")

    def test_invalid_note_creates_nothing(self):
        with self.assertRaises(ValueError):
            add_queued_note("")

        self.assertEqual(self.count("notes"), 0)
        self.assertEqual(self.count("processing_jobs"), 0)

    def test_invalid_user_creates_nothing(self):
        with self.assertRaises(ValueError):
            add_queued_note(
                "A fictional test note.",
                user_id=99999,
            )

        self.assertEqual(self.count("notes"), 0)
        self.assertEqual(self.count("processing_jobs"), 0)

    def test_secret_rejected(self):
        with self.assertRaises(ValueError):
            add_queued_note(
                "My password is secret123"
            )

        self.assertEqual(self.count("notes"), 0)
        self.assertEqual(self.count("processing_jobs"), 0)


if __name__ == "__main__":
    unittest.main()

