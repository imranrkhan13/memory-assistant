
"""Phase 3 retrieval and grounding tests."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from memory_assistant import storage
from memory_assistant.pipeline import (
    extract_note,
    prepare_schema,
)
from memory_assistant.providers import MockProvider
from memory_assistant.retrieval import (
    UNKNOWN,
    ask,
    retrieve,
    select_context,
    validate_answer,
)


class RetrievalTests(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "test.db"

        self.patch = patch.object(
            storage, "DB_PATH", self.db_path
        )
        self.patch.start()

        storage.init_db()
        prepare_schema()

        self.provider = MockProvider()

    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    def add_active_yoga(self):
        note_id = storage.add_note(
            "I selected the 9 AM yoga batch because evening traffic is bad."
        )
        extract_note(note_id)
        return note_id

    def test_retrieves_active_fact(self):
        self.add_active_yoga()
        matches = retrieve("Why yoga?")
        self.assertEqual(len(matches), 1)

    def test_answer_has_source(self):
        note_id = self.add_active_yoga()
        result = ask("Why yoga?", self.provider)

        self.assertNotEqual(result["answer"], UNKNOWN)
        self.assertEqual(
            result["sources"][0]["note_id"],
            note_id,
        )

    def test_unrelated_question_unknown(self):
        self.add_active_yoga()
        result = ask(
            "Where is my fictional passport?",
            self.provider,
        )
        self.assertEqual(result["answer"], UNKNOWN)

    def test_invented_citation_rejected(self):
        note_id = self.add_active_yoga()
        matches = retrieve("yoga")

        response = {
            "claims": [
                {
                    "statement": "I selected yoga.",
                    "note_id": 999999,
                }
            ]
        }

        valid, reason = validate_answer(
            response, matches
        )

        self.assertFalse(valid)
        self.assertEqual(
            reason, "Invented or missing citation"
        )

    def test_unsupported_claim_rejected(self):
        self.add_active_yoga()
        matches = retrieve("yoga")

        response = {
            "claims": [
                {
                    "statement": "I selected yoga on Mars.",
                    "note_id": matches[0]["note_id"],
                }
            ]
        }

        valid, reason = validate_answer(
            response, matches
        )

        self.assertFalse(valid)
        self.assertEqual(
            reason, "Unsupported claim"
        )

    def test_missing_citations_rejected(self):
        self.add_active_yoga()
        matches = retrieve("yoga")

        valid, reason = validate_answer(
            {"claims": []}, matches
        )

        self.assertFalse(valid)

    def test_context_budget(self):
        self.add_active_yoga()
        matches = retrieve("yoga")

        context = select_context(matches, budget=1)

        self.assertEqual(context["selected"], [])
        self.assertEqual(len(context["dropped"]), 1)

    def test_pending_fact_not_retrieved(self):
        note_id = storage.add_note("mixer warranty")
        extract_note(note_id)

        matches = retrieve("mixer warranty")

        self.assertEqual(matches, [])


if __name__ == "__main__":
    unittest.main()
