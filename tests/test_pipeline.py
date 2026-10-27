
"""Phase 2 tests using SAMPLE MockProvider."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from memory_assistant import storage
from memory_assistant.pipeline import (
    extract_note,
    pending_facts,
    prepare_schema,
    resolve_fact,
)


class PipelineTests(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "test.db"
        self.patch = patch.object(storage, "DB_PATH", self.db_path)
        self.patch.start()
        storage.init_db()
        prepare_schema()

    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    def test_messy_sentence_extraction(self):
        note_id = storage.add_note(
            "Well, I picked yoga at 9am because traffic is bad."
        )
        results = extract_note(note_id)
        self.assertEqual(results[0][0], "active")

    def test_low_confidence_pending(self):
        note_id = storage.add_note(
            "My fictional mixer warranty receipt is in an email."
        )
        extract_note(note_id)
        self.assertEqual(len(pending_facts()), 1)

    def test_approve(self):
        note_id = storage.add_note("mixer warranty")
        extract_note(note_id)
        approval_id = pending_facts()[0]["approval_id"]
        resolve_fact(approval_id, "approved")
        self.assertEqual(storage.list_facts()[0]["status"], "active")

    def test_reject(self):
        note_id = storage.add_note("mixer warranty")
        extract_note(note_id)
        approval_id = pending_facts()[0]["approval_id"]
        resolve_fact(approval_id, "rejected")
        self.assertNotEqual(
            storage.list_facts()[0]["status"],
            "active",
        )

    def test_conflict_requires_later_phase(self):
        first = storage.add_note("yoga")
        extract_note(first)

        second = storage.add_note("yoga moved")
        extract_note(second)

        self.assertEqual(len(pending_facts()), 1)

        approval_id = pending_facts()[0]["approval_id"]

        with self.assertRaises(ValueError):
            resolve_fact(approval_id, "approved")


if __name__ == "__main__":
    unittest.main()
