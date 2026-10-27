
# Personal Memory Assistant

A private, local-first memory assistant using Python 3
and SQLite.

## Status

- Phase 0: CLI setup verified
- Phase 1: SQLite storage implemented
- Phase 2: SAMPLE fact extraction and approvals verified
- Phase 3: SQL retrieval and source-linked SAMPLE answers
- Phase 4-7: Not implemented

## Requirements

- Python 3.12 or compatible Python 3
- No third-party dependencies

## Setup

Run from the project root:

    python3 -m memory_assistant init

## CLI Commands

    python3 -m memory_assistant hello
    python3 -m memory_assistant add "yoga"
    python3 -m memory_assistant notes
    python3 -m memory_assistant facts
    python3 -m memory_assistant pending
    python3 -m memory_assistant approve 1
    python3 -m memory_assistant edit 1 "Edited statement"
    python3 -m memory_assistant reject 1
    python3 -m memory_assistant ask "Why yoga?"
    python3 -m memory_assistant audit

Approval commands take approval IDs, not fact IDs.

## Architecture

- storage.py: SQLite persistence
- providers.py: Provider interface and SAMPLE MockProvider
- pipeline.py: Extraction and approvals
- retrieval.py: SQL retrieval, context selection, grounding
- __main__.py: CLI
- fixtures/mock_facts.json: SAMPLE extraction fixtures
- tests/: unittest coverage

## Retrieval

Retrieval uses SQL to load active facts for the current
user, then ranks them by keyword overlap with the question.

Pending and superseded facts are excluded.

The context budget limits the number of characters
passed to the provider.

The response includes source note IDs, dates, and text.

If no relevant facts are found, the answer is exactly:

    I don't know

## Grounding Limitations

Answers without citations are rejected.

Invented note IDs are rejected.

Claims containing words not found in their cited source
are rejected.

This lexical support check is rough and cannot establish
whether a claim is semantically true.

It can reject valid paraphrases and may accept false
claims made from words present in the source.

The SAMPLE MockProvider returns source text rather
than performing real language understanding.

The mock is not evidence that real AI works.

Real Gemini integration is planned for Phase 6.

## Safety and Privacy

The database is local but is not encrypted.

Secret detection is best effort, not a guarantee.
Never enter real passwords, PINs, OTPs, card numbers,
API keys, or other secrets.

The application must not provide medical, legal, or
financial advice.

It does not send messages, emails, or posts.

No network calls are implemented in Phase 3.

## Tests

Run:

    python3 -m unittest discover -s tests -v

Tests use isolated temporary SQLite databases.

## Roadmap

- Phase 0: Setup
- Phase 1: Storage
- Phase 2: Extraction and approval
- Phase 3: Retrieval and grounded answers
- Phase 4: Updates and Forget
- Phase 5: Browser app
- Phase 6: Gemini
- Phase 7: Traces and checkpoints
