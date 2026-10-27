
"""Provider interface and deterministic SAMPLE MockProvider."""
import re
import json
from abc import ABC, abstractmethod
from pathlib import Path

FIXTURE_PATH = (
    Path(__file__).resolve().parent.parent
    / "fixtures"
    / "mock_facts.json"
)


class Provider(ABC):

    @abstractmethod
    def extract(self, text):
        """Return structured candidate facts."""

    @abstractmethod
    def answer(self, question, context):
        """Return structured source-linked claims."""


class MockProvider(Provider):
    name = "SAMPLE MockProvider"

    def __init__(self, fixture_path=FIXTURE_PATH):
        with open(fixture_path, encoding="utf-8") as file:
            self.cases = json.load(file)["cases"]

    def extract(self, text):
        yoga = re.search(
            r"\b(?:7|9)\s*(?:AM|a\.m\.)\b",
            text,
            re.IGNORECASE,
        )

        if re.search(r"\byoga\b", text, re.I) and yoga and len(re.findall(r"\b\d+\s*(?:am|pm)\b", text, re.I)) == 1:
            hour = yoga.group(0)
            hour = "7 AM" if hour.startswith("7") else "9 AM"

            return [{
                "statement": text.strip(),
                "subject": "yoga_batch",
                "value": hour,
                "confidence": 0.99,
            }]
        if re.search(r"\byoga\b", text, re.I) and re.search(r"\d", text):
            return []
        cases = sorted(
            self.cases,
            key=lambda case: len(case["contains"]),
            reverse=True,
        )

        for case in cases:
            # Exact fixture aliases remain available for offline demonstrations.
            # Longer notes must contain the fixture value explicitly.
            if (text.strip().lower() == case["contains"].lower() or
                (case["contains"].lower() in text.lower() and
                 all(fact["value"].lower() in text.lower()
                     for fact in case["facts"]))):
                return [
                    {**fact, "statement": text.strip()}
                    for fact in case["facts"]
                ]

        if "mixer warranty" in text.lower():
            return [{"statement": text.strip(), "subject": "mixer_receipt",
                     "value": text.strip(), "confidence": 0.65}]
        return []

    def answer(self, question, context):
        """Return source text directly; no real language reasoning."""
        if not context:
            return {"claims": []}

        source = context[0]

        return {
            "claims": [
                {
                    "statement": source["raw_text"],
                    "note_id": source["note_id"],
                }
            ]
        }
