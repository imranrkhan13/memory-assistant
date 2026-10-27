
"""Phase 6 tests for Gemini response handling."""

import json
import unittest
from unittest.mock import patch

from memory_assistant.gemini import (
    GeminiError,
    GeminiProvider,
)



class FakeResponse:
    def __init__(self, data):
        self.data = json.dumps(data).encode("utf-8")

    def read(self):
        return self.data

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False



class GeminiTests(unittest.TestCase):
    def setUp(self):
        self.provider = GeminiProvider(
            api_key="fictional-test-key",
            model="gemini-test",
        )

    def fake_api(self, result):
        return {
            "candidates": [{
                "finishReason": "STOP",
                "content": {
                    "parts": [{
                        "text": json.dumps(result)
                    }]
                },
            }]
        }

    def test_missing_api_key(self):
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(GeminiError):
                GeminiProvider()

    def test_invalid_model_name(self):
        with self.assertRaises(GeminiError):
            GeminiProvider(
                api_key="test",
                model="../invalid",
            )

    @patch("urllib.request.urlopen")
    def test_extract_facts(self, mocked_open):
        mocked_open.return_value = FakeResponse(
            self.fake_api({
                "facts": [{
                    "subject": "yoga_batch",
                    "value": "9 AM",
                    "statement": "My yoga batch is at 9 AM.",
                    "confidence": 0.95,
                }]
            })
        )

        result = self.provider.extract(
            "My yoga batch is at 9 AM."
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["value"], "9 AM")

    @patch("urllib.request.urlopen")
    def test_empty_extraction(self, mocked_open):
        mocked_open.return_value = FakeResponse(
            self.fake_api({"facts": []})
        )

        self.assertEqual(
            self.provider.extract("Hello"),
            [],
        )

    @patch("urllib.request.urlopen")
    def test_reject_invalid_confidence(self, mocked_open):
        mocked_open.return_value = FakeResponse(
            self.fake_api({
                "facts": [{
                    "subject": "yoga",
                    "value": "9 AM",
                    "statement": "Yoga at 9 AM.",
                    "confidence": 5,
                }]
            })
        )

        with self.assertRaises(GeminiError):
            self.provider.extract("Yoga at 9 AM")

    @patch("urllib.request.urlopen")
    def test_answer_with_citation(self, mocked_open):
        mocked_open.return_value = FakeResponse(
            self.fake_api({
                "claims": [{
                    "statement": "Yoga is at 9 AM.",
                    "note_id": 4,
                }]
            })
        )

        result = self.provider.answer(
            "When is yoga?",
            [{
                "note_id": 4,
                "raw_text": "Yoga is at 9 AM.",
            }],
        )

        self.assertEqual(
            result["claims"][0]["note_id"],
            4,
        )

    @patch("urllib.request.urlopen")
    def test_invalid_claim_rejected(self, mocked_open):
        mocked_open.return_value = FakeResponse(
            self.fake_api({
                "claims": [{
                    "statement": "Invented answer",
                    "note_id": "fake",
                }]
            })
        )

        with self.assertRaises(GeminiError):
            self.provider.answer("Question", [])

    @patch("urllib.request.urlopen")
    def test_api_key_in_header(self, mocked_open):
        mocked_open.return_value = FakeResponse(
            self.fake_api({"facts": []})
        )

        self.provider.extract("Test note")

        request = mocked_open.call_args.args[0]

        self.assertEqual(
            request.get_header("X-goog-api-key"),
            "fictional-test-key",
        )

        self.assertNotIn(
            "fictional-test-key",
            request.full_url,
        )


if __name__ == "__main__":
    unittest.main()
