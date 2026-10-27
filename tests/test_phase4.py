
"""Phase 4 tests: updates, history, Forget and retrieval regression."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from memory_assistant import storage
from memory_assistant.pipeline import (
    extract_note,
    pending_facts,
    prepare_schema,
)
from memory_assistant.providers import MockProvider
from memory_assistant.retrieval import UNKNOWN, ask, retrieve
from memory_assistant.updates import (
    fact_history,
    resolve_update,
)
from memory_assistant.forget import (
    forget_fact,
    is_forgotten,
    prepare_forget_schema,
)


class Phase4Tests(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "test.db"

        self.db_patch = patch.object(
            storage, "DB_PATH", self.db_path
        )
        self.db_patch.start()

        storage.init_db()
        prepare_schema()
        prepare_forget_schema()

        self.provider = MockProvider()

    def tearDown(self):
        self.db_patch.stop()
        self.temp.cleanup()

    def add_yoga(self):
        note_id = storage.add_note(
            "I selected the 9 AM yoga batch because evening traffic is bad."
        )
        extract_note(note_id)
        return note_id

    def add_yoga_update(self):
        note_id = storage.add_note("yoga moved")
        extract_note(note_id)
        return note_id

    def test_approve_conflict_supersedes_old_fact(self):
        self.add_yoga()
        self.add_yoga_update()

        approvals = pending_facts()
        self.assertEqual(len(approvals), 1)

        resolve_update(
            approvals[0]["approval_id"],
            "approved",
        )

        history = fact_history("yoga_batch")

        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]["status"], "superseded")
        self.assertEqual(history[1]["status"], "active")
        self.assertEqual(
            history[0]["superseded_by"],
            history[1]["id"],
        )

    def test_rejected_update_preserves_old_fact(self):
        self.add_yoga()
        self.add_yoga_update()

        approval_id = pending_facts()[0]["approval_id"]

        resolve_update(approval_id, "rejected")

        history = fact_history("yoga_batch")

        self.assertEqual(history[0]["status"], "active")
        self.assertEqual(history[1]["status"], "superseded")

    def test_edited_approval(self):
        note_id = storage.add_note("mixer warranty")
        extract_note(note_id)

        approval_id = pending_facts()[0]["approval_id"]

        resolve_update(
            approval_id,
            "approved",
            edited_statement="mixer warranty",
        )

        with storage.get_connection() as conn:
            row = conn.execute(
                "SELECT statement, status FROM facts LIMIT 1"
            ).fetchone()

        self.assertEqual(row["statement"], "mixer warranty")
        self.assertEqual(row["status"], "active")

    def test_approval_cannot_be_reused(self):
        note_id = storage.add_note("mixer warranty")
        extract_note(note_id)

        approval_id = pending_facts()[0]["approval_id"]

        resolve_update(approval_id, "approved")

        with self.assertRaises(ValueError):
            resolve_update(approval_id, "approved")

    def test_forget_removes_source_and_fact(self):
        note_id = self.add_yoga()

        facts = storage.list_facts()
        fact_id = facts[0]["id"]

        result = forget_fact(fact_id)

        self.assertEqual(result["removed_note_id"], note_id)
        self.assertEqual(result["removed_facts"], 1)

        self.assertEqual(storage.list_notes(), [])
        self.assertEqual(storage.list_facts(), [])
        self.assertEqual(fact_history("yoga_batch"), [])

    def test_forgotten_text_fingerprint(self):
        text = (
            "I selected the 9 AM yoga batch "
            "because evening traffic is bad."
        )

        self.add_yoga()

        fact_id = storage.list_facts()[0]["id"]

        forget_fact(fact_id)

        self.assertTrue(is_forgotten(text))
        self.assertFalse(is_forgotten("Different fictional note"))

    def test_forgotten_fact_not_retrieved(self):
        self.add_yoga()

        fact_id = storage.list_facts()[0]["id"]

        forget_fact(fact_id)

        result = ask("Why yoga?", self.provider)

        self.assertEqual(result["answer"], UNKNOWN)
        self.assertEqual(result["sources"], [])

    def test_passport_regression(self):
        note_id = storage.add_note("mixer warranty")
        extract_note(note_id)

        approval_id = pending_facts()[0]["approval_id"]
        resolve_update(approval_id, "approved")

        result = ask(
            "Where is my fictional passport?",
            self.provider,
        )

        self.assertEqual(result["answer"], UNKNOWN)
        self.assertEqual(result["sources"], [])

    def test_superseded_fact_not_retrieved(self):
        self.add_yoga()
        self.add_yoga_update()

        approval_id = pending_facts()[0]["approval_id"]
        resolve_update(approval_id, "approved")

        matches = retrieve("yoga")

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["raw_text"], "yoga moved")

    def test_forget_clears_pending_approval(self):
        note_id = storage.add_note("mixer warranty")
        extract_note(note_id)

        self.assertEqual(len(pending_facts()), 1)

        fact_id = storage.list_facts()[0]["id"]

        forget_fact(fact_id)

        self.assertEqual(pending_facts(), [])

    def test_forget_is_user_scoped(self):
        self.add_yoga()
        fact_id = storage.list_facts()[0]["id"]

        with self.assertRaises(ValueError):
            forget_fact(fact_id, user_id=999)

        self.assertEqual(len(storage.list_facts()), 1)


if __name__ == "__main__":
    unittest.main()
