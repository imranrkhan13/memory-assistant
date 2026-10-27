
"""Phase 6 integration tests."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from memory_assistant import storage
from memory_assistant.ai import (
    get_provider,
    process_note,
    answer_question,
)
from memory_assistant.gemini import GeminiProvider
from memory_assistant.providers import MockProvider
from memory_assistant.pipeline import prepare_schema
from memory_assistant.forget import prepare_forget_schema


class AIIntegrationTests(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(
            storage,
            "DB_PATH",
            Path(self.temp.name) / "test.db",
        )
        self.db_patch.start()

        storage.init_db()
        prepare_schema()
        prepare_forget_schema()

    def tearDown(self):
        self.db_patch.stop()
        self.temp.cleanup()

    def test_default_mock(self):
        with patch.dict(
            "os.environ",
            {"MEMORY_PROVIDER": "mock"},
        ):
            self.assertIsInstance(
                get_provider(),
                MockProvider,
            )

    def test_unknown_provider_rejected(self):
        with patch.dict(
            "os.environ",
            {"MEMORY_PROVIDER": "invalid"},
        ):
            with self.assertRaises(ValueError):
                get_provider()

    def test_gemini_provider_selection(self):
        with patch.dict(
            "os.environ",
            {
                "MEMORY_PROVIDER": "gemini",
                "GEMINI_API_KEY": "fictional-key",
            },
        ):
            self.assertIsInstance(
                get_provider(),
                GeminiProvider,
            )

    def test_gemini_fact_requires_approval(self):
        note_id = storage.add_note(
            "My imaginary gym class starts at 6 AM."
        )

        provider = GeminiProvider(
            api_key="fictional-key",
        )

        with patch.object(
            provider,
            "extract",
            return_value=[{
                "subject": "gym_class",
                "value": "6 AM",
                "statement":
                    "My imaginary gym class starts at 6 AM.",
                "confidence": 0.99,
            }],
        ):
            results = process_note(
                note_id,
                provider=provider,
            )

        self.assertEqual(results[0][0], "pending")

        facts = storage.list_facts()

        self.assertEqual(facts[0]["status"], "pending")

    def test_mock_answer_still_works(self):
        result = answer_question(
            "Where is my fictional passport?",
            provider=MockProvider(),
        )

        self.assertEqual(
            result["answer"],
            "I don't know",
        )


if __name__ == "__main__":
    unittest.main()
