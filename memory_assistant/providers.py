
"""Provider interface and deterministic SAMPLE MockProvider."""

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
        cases = sorted(
            self.cases,
            key=lambda case: len(case["contains"]),
            reverse=True,
        )

        for case in cases:
            if case["contains"].lower() in text.lower():
                return [
                    dict(fact)
                    for fact in case["facts"]
                ]

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
