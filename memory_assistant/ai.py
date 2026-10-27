
"""Phase 6: provider selection and memory AI operations."""

import os

from .gemini import GeminiProvider
from .providers import MockProvider
from .pipeline import extract_note
from .storage import (
    DEFAULT_USER_ID,
    get_connection,
    check_secrets,
)
from .retrieval import ask


def get_provider():
    mode = os.environ.get(
        "MEMORY_PROVIDER", "mock"
    ).strip().lower()

    if mode == "mock":
        return MockProvider()

    if mode == "gemini":
        return GeminiProvider()

    raise ValueError(
        "MEMORY_PROVIDER must be mock or gemini."
    )


def process_note(
    note_id,
    provider=None,
    user_id=DEFAULT_USER_ID,
):
    """Extract candidate facts from a saved note."""

    provider = provider or get_provider()

    # Gemini-generated facts require human approval.
    # The current pipeline auto-activates high-confidence facts,
    # so clamp confidence before persistence.
    if isinstance(provider, GeminiProvider):

        class ReviewProvider:
            name = provider.name

            def extract(self, text):
                candidates = provider.extract(text)

                safe_candidates = []

                for candidate in candidates:
                    statement = candidate["statement"]
                    value = candidate["value"]

                    if (
                        check_secrets(statement)
                        or check_secrets(value)
                    ):
                        continue

                    safe_candidates.append({
                        **candidate,
                        "confidence": min(
                            candidate["confidence"], 0.84
                        ),
                    })

                return safe_candidates

        return extract_note(
            note_id,
            provider=ReviewProvider(),
            user_id=user_id,
        )

    return extract_note(
        note_id,
        provider=provider,
        user_id=user_id,
    )


def answer_question(
    question,
    provider=None,
    user_id=DEFAULT_USER_ID,
):
    """Answer using active facts and source validation."""

    provider = provider or get_provider()

    # Preserve Phase 3 behavior and its source validator.
    return ask(
        question,
        provider=provider,
        user_id=user_id,
    )
