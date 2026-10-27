# LongMemEval stages 0–1

This is retrieval-only evaluation of public benchmark histories. It deliberately bypasses product extraction, fact approval and answering. It measures evidence retrieval, not product safety, answer correctness or a job qualification score. No paid services or model calls are used.

## Stage 0: pinned adapter and frozen split

The starting branch is fetched `origin/main` at `8e2d01a`, which contains Phase A. Before benchmark changes, `python3 -m unittest discover -s tests` passed 100 tests in 2.333 seconds.

The manifest pins the cleaned S dataset to Hugging Face revision `98d7416c24c778c2fee6e6f3006e7a073259d48f`, 277,383,467 bytes, SHA-256 `d6f21ea9d60a0d56f34a05b609c79c88a451d2ae03597821ea3d5a9678c3a442`. The public download matched both size and digest. The raw file stays git-ignored; it is not copied into product memory or committed.

The 500 question records contain 23,867 session occurrences and 246,750 turns. A streaming validation projected all histories successfully. The first validator incorrectly assumed unique session IDs per question and failed on the real release. Inspection found 13 duplicate occurrences with different timestamps or turn contents. The revised index preserves every occurrence under its own ordinal; it never overwrites one copy with another. Session-level scoring collapses equal session labels to one ID. A synthetic regression covers this behavior.

Forty dev and sixty heldout IDs were selected before any retrieval scores were computed. The committed deterministic procedure groups by question type and abstention marker, allocates proportionally by largest remainders, and orders each group by SHA-256 of a fixed seed and question ID. It uses no reference answer, query wording or evidence labels to select questions. The heldout questions are reserved for a later final run.

| Type | Dev | Heldout |
|---|---:|---:|
| knowledge-update | 7 | 9 |
| multi-session | 11 | 15 |
| single-session-assistant | 5 | 7 |
| single-session-preference | 2 | 4 |
| single-session-user | 5 | 9 |
| temporal-reasoning | 10 | 16 |
| Total | 40 | 60 |

Dev includes 2 abstentions and heldout includes 4. They remain in the split but are excluded from retrieval scoring, following the official reporting script. The complete release contains 30 abstentions. Metadata and schema validation do not constitute running the heldout benchmark.

The ingestion interface accepts only a `History` projection: namespace ID, raw session IDs, raw timestamps and allowlisted role/content turns. It strips all other fields, including turn labels. The question is supplied only to retrieval; `answer`, `has_answer` and `answer_session_ids` never enter the index. Queries with colliding session/chunk IDs in different question namespaces cannot see one another. The SQLite index is dedicated to this benchmark and refuses databases with product tables.

Stage 0 adds twelve synthetic unittest cases covering these boundaries, corrupt/truncated inputs, hash verification, atomic reingestion, duplicate occurrences and split stability. Tests require neither the download nor network access.

Sources: [official release and format](https://github.com/xiaowu0162/LongMemEval/tree/9e0b455f4ef0e2ab8f2e582289761153549043fc), [cleaned dataset and MIT licence](https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/tree/98d7416c24c778c2fee6e6f3006e7a073259d48f), [official metric functions](https://github.com/xiaowu0162/LongMemEval/blob/9e0b455f4ef0e2ab8f2e582289761153549043fc/src/retrieval/eval_utils.py), [official reporting exclusions](https://github.com/xiaowu0162/LongMemEval/blob/9e0b455f4ef0e2ab8f2e582289761153549043fc/src/evaluation/print_retrieval_metrics.py).
