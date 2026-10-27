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

Stage 0 completion: `python3 -m unittest discover -s tests` passed **112 tests in 2.407 seconds**, 0 failures/errors/skips. Commit `b9870b7` froze the adapter and split before any retrieval scores were computed.

## Stage 1: reproducible keyword baseline

Run from the repository root:

```sh
python3 -m memory_assistant.benchmark download
python3 -m memory_assistant.benchmark run --method keyword --subset dev
```

The first command downloads only the pinned public cleaned S release and verifies its exact bytes. If it already exists, it is verified without a download. The run command performs no network or model calls, loads no `.env`, and uses no product notes/database. It rechecks the dataset hash before ingestion. Raw downloads and the rebuildable benchmark SQLite index stay under the git-ignored `benchmarks/longmemeval/local/` directory. Removing that dedicated benchmark index and rerunning rebuilds it from the dataset.

Each raw turn is one chunk, including user and assistant turns. Raw timestamps are retained but never scored. Tokenization and exact overlap count are shared with the product retriever; ties follow ascending insertion/chunk ID. There is no BM25, stemming, query expansion, recency boost, semantic model or zero-score padding. Sessions are ranked by the first occurrence of their ID in the ranked turns; repeated session IDs collapse to one session result. Search stops at ten distinct positive-score sessions.

The metric port uses the pinned official `evaluate_retrieval`/`ndcg` session formulas over this unique-session ranking and the full unique-session corpus. It does not implement the upstream `evaluate_retrieval_turn2session` path, which can retain repeated session labels while extending its effective cutoff. Therefore these are official session metric formulas on our explicitly documented turn-to-session adapter, not a reproduction of every upstream retrieval protocol or a score comparable to vendor headlines.

Official DCG discounts ranks as `1, 1/log2(2), 1/log2(3), ...`; the first two ranks consequently have equal discount. Using a common rank-plus-one nDCG library would change the result. Abstention questions are indexed but never searched/scored. Questions without full evidence in the top ten are listed with their missing IDs. Runtime/schema failures are listed separately and remain in the eligible denominator with zero credit; the output always reports selected, eligible, scored, failed and skipped counts. Latency reports cover retrieval only, with indexing and total time recorded separately.

JSON results include per-question rankings, source/session IDs, scores, evidence misses, metric values and timings. They include no raw turns, reference answers or generated answers. Provenance records the code commit/dirty state, source digests, dataset revision/hash, manifest and split hashes, method/configuration, metric version, runtime and UTC date. A completed output file is published atomically and cannot be overwritten. Heldout execution is disabled in this stage; enabling it later requires an intentional code change after methods are frozen.

Verification commands:

```sh
python3 -m unittest discover -s tests -p test_benchmark_runner.py
python3 scripts/verify_longmemeval_metrics.py
python3 -m unittest discover -s tests
git diff --check
```

The runner's twelve synthetic tests passed in 0.114 seconds. The full suite passed **124 tests in 2.470 seconds**, 0 failures/errors/skips. Tests run offline without needing the large dataset or NumPy. The optional one-time metric audit used the already installed NumPy 2.1.2 to execute the unmodified pinned official source: **2,000 comparisons, 0 failures, maximum absolute nDCG difference `1.11e-16`**. For that audit only, the removed NumPy 1.x `asfarray` API was restored with its equivalent float-array conversion. No dependency was installed or added to the application.

No dev score is claimed in this implementation commit. The measured run and its limits will be recorded separately against this frozen code.

## First measured run: keyword dev v1

Code was frozen at `3bfda872211549520b6bf2c98a0a4b2140ce8897`; the runner recorded a **clean working tree**. No retrieval changes were made after seeing the scores.

Exact command:

```sh
python3 -m memory_assistant.benchmark run --method keyword --subset dev --output benchmarks/longmemeval/results/keyword-dev-v1.json
```

Actual output:

```text
Provider: none (retrieval only); model calls: 0
Selected: 40; eligible: 38; scored: 38; failed: 0; skipped abstentions: 2
recall_all@10: 0.789474
ndcg_any@10: 0.761281
Retrieval latency (ms): {'samples': 38, 'p50': 3.978125052526593, 'p95': 4.863040987402201}
Questions with missed evidence:
  3fdac837: answer_419d21d5_1
  57f827a0: answer_1bde8d3b
  830ce83f: answer_0b1a0942_2
  92a0aa75: answer_6cb8f792_1
  eeda8a6d: answer_3e5fea0e_2
  gpt4_731e37d7: answer_826d51da_2
  gpt4_f2262a51: answer_55a6940c_1, answer_55a6940c_2, answer_55a6940c_3
  gpt4_fa19884d: answer_ff201787_1
Results: benchmarks/longmemeval/results/keyword-dev-v1.json
```

| Method | Eligible | All evidence in top 10 | recall_all@10 | Mean ndcg_any@10 | Failed | Excluded abstentions |
|---|---:|---:|---:|---:|---:|---:|
| Keyword, raw turns → unique sessions | 38 | 30 | 0.789474 | 0.761281 | 0 | 2 |

The dedicated local index contains 19,748 turns across 1,906 session occurrences for these forty dev questions. Indexing the two abstention histories does not give them a retrieval score. Session IDs and timestamps are metadata only; neither is tokenized or used to boost rankings. The recorded processing time was 2,184 ms, including streaming, indexing and retrieval, but excluding initial hash verification and report writing. Retrieval-only p50/p95 used 38 samples. These timings are one local run, not a throughput or scale claim.

| Type | Eligible | All evidence in top 10 | Mean ndcg_any@10 |
|---|---:|---:|---:|
| knowledge-update | 6 | 5 | 0.827556 |
| multi-session | 10 | 5 | 0.547107 |
| single-session-assistant | 5 | 5 | 1.000000 |
| single-session-preference | 2 | 1 | 0.193426 |
| single-session-user | 5 | 5 | 1.000000 |
| temporal-reasoning | 10 | 9 | 0.810542 |

These type groups are small and do not establish general quality differences. In particular, 5/5 on a subgroup is not proof of perfect retrieval. [Machine-readable run with provenance and per-question results](../benchmarks/longmemeval/results/keyword-dev-v1.json).

## Proven, partial, missing

- **Proven:** pinned bytes, frozen/disjoint stratified splits, isolation and leakage-boundary regressions, 124 passing offline tests, official-source metric conformance, and this single dev run with its full denominators and miss list. Model calls: **0**; no service charges. Stage 0 and Stage 1 are complete for the documented adapter.
- **Partial:** this reuses the product's keyword scoring over raw benchmark turns, bypassing extraction and approval. It does not measure whether the product extracts useful facts. Session ranking is our documented adapter, not a reproduction of all upstream configurations. Latency excludes indexing unless explicitly marked as total processing time. Public benchmark text remains only in the local download/index; committed results contain IDs and metrics, not raw conversations.
- **Missing:** semantic/hybrid comparison, answer generation and correctness labels, claim-support assessment, answer traces and failure diagnoses, heldout evaluation, versioned API and second client. No real-model quality, vendor score equivalence, production scale or hiring outcome is claimed. Product approval/Forget/crash-recovery tests remain separate from benchmark scores.

The sixty heldout questions have not been retrieved/scored. Stop after Stage 1 for owner review before Stage 2. Nothing is pushed by this benchmark task.

Final diff audit: `git diff --check origin/main..HEAD` reports two EOF blank-line warnings, both in the unmodified pinned official metric reference files. They are retained to preserve their recorded SHA-256 digests. The authored changes pass the working-tree diff check; the warnings do not indicate a test or benchmark failure.
