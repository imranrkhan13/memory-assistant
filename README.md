# Personal Memory Assistant

A private, local-first AI memory assistant built with **Python 3, SQLite, and Google Gemini**.

The application allows users to save notes, extract important facts, approve memories, and ask questions about previously saved information.

It uses a simplified **Retrieval-Augmented Generation (RAG)** architecture. Python searches the local SQLite database for relevant approved facts, and Gemini generates answers using the retrieved information.

## Project Status

| Phase | Feature | Status |
|---|---|---|
| Phase 0 | CLI setup | Completed |
| Phase 1 | SQLite storage | Completed |
| Phase 2 | SAMPLE fact extraction and approvals | Completed |
| Phase 3 | SQL retrieval and source-linked answers | Completed |
| Phase 4 | Memory updates and forgetting | Completed |
| Phase 5 | Local browser application | Completed |
| Phase 6 | Google Gemini integration | Completed |
| Phase 7 | Traces and checkpoints | Planned |

**Current testing:** 48 automated tests passed during Phase 6 testing. Live Gemini extraction and source-linked question answering have also been verified.

## Requirements

- Python 3.12 or compatible Python 3
- SQLite (included with Python)
- No third-party Python dependencies
- Gemini API key for real AI functionality
- Internet connection when using Gemini

The application uses Python's standard library for its HTTP server, database access, JSON handling, and Gemini API requests.

## Setup

Run the following command from the project root:

```bash
python3 -m memory_assistant init
```

### Configure Gemini

Create a `.env` file in the project root:

```dotenv
MEMORY_PROVIDER=gemini
GEMINI_API_KEY=your_gemini_api_key
GEMINI_MODEL=gemini-3.5-flash-lite
```

The application includes a configuration loader for reading the `.env` file.

To use the offline SAMPLE provider instead:

```dotenv
MEMORY_PROVIDER=mock
```

Never commit your actual API key to Git.

## Start the Browser Application

Run:

```bash
python3 -m memory_assistant serve
```

Open:

http://127.0.0.1:8765

The application runs on localhost and is not intended for public deployment.

### Browser Features

- **Dashboard:** Overview of saved notes, active facts, and pending approvals.
- **Notes:** Add and view notes.
- **Facts:** View active and inactive facts and forget saved information.
- **Approvals:** Approve, edit, or reject extracted facts.
- **Ask Memory:** Ask questions about approved memories.
- **History:** View memory updates and superseded facts.
- **Audit:** View recorded memory operations.

## CLI Commands

```bash
python3 -m memory_assistant hello

python3 -m memory_assistant init

python3 -m memory_assistant add "I selected the 9 AM yoga batch"

python3 -m memory_assistant notes

python3 -m memory_assistant facts

python3 -m memory_assistant pending

python3 -m memory_assistant approve 1

python3 -m memory_assistant edit 1 "Corrected statement"

python3 -m memory_assistant reject 1

python3 -m memory_assistant ask "Why did I select morning yoga?"

python3 -m memory_assistant audit

python3 -m memory_assistant serve
```

Approval commands take approval IDs, not fact IDs.

## Architecture

The application separates memory storage, information retrieval, and AI processing.

| File | Responsibility |
|---|---|
| `storage.py` | SQLite persistence and database operations |
| `providers.py` | SAMPLE MockProvider |
| `pipeline.py` | Fact extraction and approval workflow |
| `retrieval.py` | SQL retrieval, keyword ranking, context selection, and answer validation |
| `updates.py` | Memory updates and fact history |
| `forget.py` | Forgetting facts and related source information |
| `web.py` | Local browser application and HTTP routes |
| `gemini.py` | Gemini REST API integration |
| `ai.py` | Provider selection and AI operations |
| `config.py` | Environment configuration loading |
| `__main__.py` | Command-line interface |
| `fixtures/mock_facts.json` | SAMPLE extraction fixtures |
| `tests/` | Automated unittest coverage |

### How the Memory System Works

**1. Save a note**

The user enters:

> My fictional swimming class starts on October 28, 2026, at 7 AM.

Python saves the original note in SQLite.

**2. Extract facts**

Gemini analyzes the note and may extract:

- Swimming class date: October 28, 2026
- Swimming class time: 7 AM

**3. Review memories**

Gemini-generated facts require user approval before becoming active.

The user can approve, edit, or reject extracted information.

**4. Ask a question**

The user asks:

> When is my swimming class?

**5. Retrieve information**

Python searches SQLite for relevant active facts and retrieves their source notes.

**6. Generate and validate the answer**

Gemini receives the question and relevant source information.

Python validates the generated claims against their cited notes before displaying the answer.

## SQLite Database

SQLite is a relational database with tables, columns, rows, primary keys, and SQL queries.

The application stores information in tables including:

- `users`
- `notes`
- `facts`
- `approvals`
- `audit_log`

SQLite runs locally without requiring a separate database server.

### Why SQLite?

- Simple setup
- No separate database service
- Fast local queries
- Persistent storage
- Supports structured data and SQL
- Suitable for local applications and prototypes

## Retrieval and RAG

The application currently uses **SQL retrieval with keyword-overlap ranking**.

### Retrieval Process

1. Load active facts belonging to the current user.
2. Rank facts according to keyword overlap with the question.
3. Select relevant information within a context character budget.
4. Retrieve the associated source notes.
5. Send the selected context and question to the provider.
6. Validate the answer and its citations.

Pending and superseded facts are excluded from question answering.

The context budget limits how much source information is sent to Gemini.

If no relevant information is found, the application returns:

```text
I don't know
```

### Is Embedding Search Implemented?

**No.**

The current application does not generate or store embeddings.

It does not perform vector similarity search.

The current implementation is a simplified RAG system based on SQL and keyword matching.

Embedding-based semantic search is a possible future enhancement.

## Google Gemini Integration

Gemini is used for two main operations.

### Fact Extraction

Gemini converts natural-language notes into structured candidate facts containing:

- Subject
- Value
- Statement
- Confidence

Gemini-generated facts require human approval.

### Question Answering

Gemini receives the user's question and relevant source notes retrieved by Python.

It generates structured claims containing source note references.

The application validates those claims before displaying an answer.

### Provider Selection

Set:

```dotenv
MEMORY_PROVIDER=gemini
```

For real Gemini API requests.

Or:

```dotenv
MEMORY_PROVIDER=mock
```

For SAMPLE testing without Gemini API calls.

**Gemini does not directly connect to SQLite.** Python handles database access and sends relevant context to the model.

## Memory Updates and Forgetting

### Updates

The application supports memory correction and fact history.

When an approved update replaces an existing fact, the previous fact can be marked as superseded.

Superseded facts are not used for current question answering.

### Forgetting

Users can delete a fact and its associated source note through the browser interface.

The application also maintains protection against accidentally reintroducing an exact previously forgotten note.

## Grounding and Validation

The application includes source-linked answer validation.

- Answers without required citations are rejected.
- Invented source note IDs are rejected.
- Unsupported claims are rejected by a rough lexical support check.
- Responses can include source note IDs, timestamps, and original note text.
- Answers are restricted to relevant active memories.

### Limitations

The lexical support check is not a complete factual verification system.

It can reject valid paraphrases and may accept incorrect statements that reuse words from a source.

The system should not be considered fully hallucination-proof.

## Security and Privacy

The application is designed for local development.

Current protections include:

- Localhost-only HTTP binding
- Host validation
- CSRF tokens for browser forms
- Origin checking
- Security-related HTTP headers
- Input validation
- Best-effort secret detection
- Human approval of Gemini-generated memories

### Important Limitations

- The SQLite database is not encrypted.
- The application has no user authentication.
- Gemini requests send selected information to Google's API.
- Secret detection is best effort, not guaranteed.
- The application is not suitable for storing passwords, PINs, OTPs, API keys, or other sensitive secrets.
- It is not intended to provide medical, legal, or financial advice.
- It does not automatically send emails, messages, or social media posts.
- It should not be exposed directly to the public internet.

Use fictional information during development and testing.

## Testing

Run the complete test suite:

```bash
python3 -m unittest discover -s tests -v
```

Run AI integration tests:

```bash
python3 -m unittest tests.test_ai -v
```

Tests use isolated temporary SQLite databases.

The most recently confirmed Phase 6 test run passed **48 tests**.

### Live Testing Completed

- Local browser application starts successfully.
- Notes can be saved to SQLite.
- Gemini API configuration works.
- Gemini can extract structured facts from notes.
- Extracted facts can be reviewed and approved.
- Active facts can be retrieved.
- Gemini can answer questions using saved source notes.
- Source-linked answer validation works for tested cases.

## Current Limitations

1. Retrieval uses keyword matching rather than semantic embeddings.
2. Previously saved notes are not automatically reprocessed when switching AI providers.
3. Relative dates such as "tomorrow" are not reliably normalized using the note creation date.
4. The interface does not yet clearly display extraction failures for each note.
5. Gemini API calls require an internet connection.
6. The application is intended for local development, not production hosting.

## Future Roadmap

### Phase 7 — Traces and Checkpoints

Planned improvements:

- Trace the complete note-processing workflow.
- Record extraction and retrieval stages.
- Track provider errors and processing results.
- Add checkpoints for troubleshooting.
- Improve visibility into failed operations.

### Future Enhancements

- SQLite FTS5 full-text search
- Embedding-based semantic search
- Hybrid keyword and semantic retrieval
- Reprocess existing notes
- Better relative-date handling
- Extraction status indicators
- Reduced Gemini API usage through direct-answer retrieval
- Stronger authentication and encryption before handling sensitive data

## Summary

The Personal Memory Assistant combines:

**SQLite for storage + Python for retrieval and application logic + Gemini for AI understanding and answer generation.**

The result is a local-first memory application that can save information, extract facts, require human approval, retrieve relevant memories, and generate source-linked answers.

It is a working foundation for a more advanced personal AI memory system.