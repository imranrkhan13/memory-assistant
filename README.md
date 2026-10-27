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
| Phase 7 | Durable extraction jobs, leases, retries and metadata traces | Implemented foundation |
| Phase A | Correctness and normal durable save path | Offline tests passing |
| Retrieval benchmark Stages 0–1 | Pinned LongMemEval adapter and keyword runner | Implemented; measured report linked below |
| Later stages | Semantic comparison, answer evaluation, traces, API and second client | Not started |

**Current testing (27 October 2026):** 124 automated tests passed using offline logic, mock/stub providers and temporary databases. No live Gemini calls were made in Phase A; real-model extraction and answer quality remain unconfirmed. See [Phase A evidence](docs/phase-a.md).

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

The application binds to `127.0.0.1`; the `localhost` Host header is rejected. It is not intended for public deployment.

Saving queues extraction by default in both the CLI and browser. `MEMORY_JOBS_ASYNC` is no longer required. Start the worker in a second terminal:

```bash
MEMORY_PROVIDER=mock python3 -m memory_assistant.job_daemon
```

For a single batch instead:

```bash
MEMORY_PROVIDER=mock python3 -m memory_assistant.job_cli run
```

The worker is deliberately a separate process. Without it, saves remain safely queued. It reads the same environment/`.env` configuration as the browser and CLI. Mock mode is offline; only use Gemini when you have confirmed free quota. No paid fallback is implemented.

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

python3 -m memory_assistant reprocess 1

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

Python saves the original note and a durable extraction job in one SQLite transaction. A successful save means extraction is pending, not completed.

**2. Extract facts**

The worker uses the configured provider to analyze the note and may extract:

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

The Phase A run passed **100 tests** (0 failures, 0 errors), including 12 new regressions. These are offline logic checks, not real-model quality measurements.

### Phase A behavior

- Each note displays `pending`, `processing`, `done`, or `failed` in Notes and the CLI. Status comes from durable SQLite job records. Legacy notes without a processing checkpoint display pending and can be reprocessed.
- `done` means extraction committed; proposed facts can still require approval.
- Missing configuration, invalid schemas and empty extraction stop with a readable failure. Provider timeouts, HTTP 429 and HTTP 5xx retry automatically, at most three attempts per cycle (5 then 10 seconds before the remaining attempts; the backoff implementation caps at 300 seconds).
- After fixing a failure, use **Reprocess note** or `python3 -m memory_assistant reprocess NOTE_ID`. This explicitly starts another bounded attempt cycle. Existing facts and decisions are retained; reprocessing does not reactivate rejected or superseded facts. Reprocessing does not revise already extracted facts when changing providers.
- Conflicts show old and proposed statements. Human approval atomically supersedes current facts, after checking that those facts still match the proposal. A stale or legacy proposal must be reprocessed and reviewed again. Upload order never determines which decision wins.
- Forget removes the source's jobs and processing traces in the same transaction as its facts and approvals, so a worker cannot restore the forgotten source.
- Mock mode recognizes a few synthetic fixtures, not arbitrary language. Explicit yoga times support only unambiguous 7 AM/9 AM notes. Exact legacy fixture aliases (`yoga`, `yoga moved`, `library book`, `mixer warranty`) remain SAMPLE demonstrations; other unmatched notes create no facts and report empty extraction. No mock result establishes real-model quality.

No live Gemini extraction or answering was verified in Phase A. Previous README live-provider claims have been removed because this run did not reproduce them.

## Current Limitations

1. Retrieval uses keyword matching rather than semantic embeddings.
2. Reprocessing is explicit; changing providers does not replace already extracted facts.
3. Relative dates such as "tomorrow" are not reliably normalized using the note creation date.
4. A retrieval-only benchmark runner exists; semantic comparisons, answer quality evaluation, a versioned service API and a second API client are still missing.
5. Gemini API calls require an internet connection.
6. The application is intended for local development, not production hosting.

## Future Roadmap

### Retrieval evaluation: Stages 0–1

A separate model-free adapter measures keyword evidence retrieval on the public cleaned LongMemEval S dataset. It bypasses extraction/approval deliberately and never indexes reference answers, questions or evidence labels.

```bash
python3 -m memory_assistant.benchmark download
python3 -m memory_assistant.benchmark run --method keyword --subset dev
```

The 277 MB download is pinned by revision and SHA-256 and stays outside Git. The split is frozen at 40 dev and 60 reserved heldout questions. Runs write versioned JSON results with `recall_all@10`, `ndcg_any@10`, misses, failures, denominator and latency. The benchmark never calls a model or reads your notes or `.env`. [Methodology, commands and evidence](docs/benchmark-stages-0-1.md).

Next, compare free local semantic and hybrid retrieval on the same dev questions, after checking hardware and licence constraints. Heldout execution stays disabled until methods are frozen. Retrieval scores and answer accuracy are separate measurements.

Later phases cover a versioned API, a second client, richer answer traces and a reproducible demonstration. Current traces contain extraction metadata only.

### Future Enhancements

- SQLite FTS5 full-text search
- Embedding-based semantic search
- Hybrid keyword and semantic retrieval
- Better relative-date handling
- Reduced Gemini API usage through direct-answer retrieval
- Stronger authentication and encryption before handling sensitive data

## Summary

The Personal Memory Assistant combines:

**SQLite for storage + Python for retrieval and application logic + Gemini for AI understanding and answer generation.**

The result is a local-first memory application that can save information, extract facts, require human approval, retrieve relevant memories, and generate source-linked answers.

It is a working foundation for a more advanced personal AI memory system.