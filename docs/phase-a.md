# Phase A evidence — 27 October 2026

Scope: Phase A only. Provider mode: offline mock/stubs, synthetic data, temporary SQLite databases. Actual live Gemini requests: **0**. No dependencies added, paid services used, push, PR, deployment or account action performed.

## Starting point

HEAD was `59abf1b`, matching the handoff. Seven files already had uncommitted edits: `__main__.py`, `pipeline.py`, `providers.py`, `retrieval.py`, `updates.py`, `web.py` and `tests/test_web.py`. Their intent was reviewed and reconciled, not blindly overwritten. In particular, the duplicate browser save was removed and upload-ID ordering was replaced by explicit approval baselines. Retrieval keeps its original score/ID ordering; correct current answers come from approved state transitions, not recency ranking.

A clean source snapshot was produced without modifying the working tree:

```sh
git archive HEAD -o /tmp/memory-head-baseline.tar
mkdir -p /tmp/memory-head-baseline
tar -xf /tmp/memory-head-baseline.tar -C /tmp/memory-head-baseline
# working directory /tmp/memory-head-baseline:
python3 -m unittest discover -s tests
```

Actual clean-HEAD output:

```text
Ran 88 tests in 2.153s
OK
```

The initial working-tree run reached 88 tests but failed with one failure (`queued` vs `pending` in a changed test) and one error (Forget foreign key failure). An earlier sandboxed run stopped at 77 tests because the sandbox blocked binding a local HTTP socket. Subsequent full runs used permission to bind the temporary HTTP test server.

## What changed

- CLI/browser save through one atomic note-plus-job queue by default. A save does not invoke a provider or claim extraction completed.
- Notes/CLI expose durable job-derived extraction state, safe error text and explicit reprocessing. A manual reprocess resets the bounded attempt cycle, keeps the same job ID, and preserves fact and approval decisions. Existing extraction metadata migrations use the project's additive schema setup.
- Mock matching no longer maps arbitrary yoga text to a 9 AM fixture. Explicit times must be unambiguous and supported. Legacy exact SAMPLE aliases remain; unsupported input creates no facts.
- Failures are classified without retaining raw exception content. Timeouts, connection errors, rate limits and server errors are transient; configuration/schema/empty-extraction errors need review. Automatic retries are bounded and delayed.
- Facts and job success remain one transaction. Partial extraction writes roll back. Retried/reprocessed notes retain a single fact per source/subject.
- Proposals retain the active fact IDs they were created against, display old/new statements, and recheck that baseline under a write lock during approval. Approval, not upload order, changes the current answer. Legacy proposals without a baseline require explicit reprocessing.
- Forget deletes associated jobs and metadata traces before the source, within the same transaction. The deleted lease prevents paused workers from committing results.
- Worker entry points initialize extraction schema and read the same configuration as the regular CLI.

## Verification

Commands actually run:

```sh
python3 -m unittest discover -s tests -p test_phase_a.py
python3 -m unittest discover -s tests
git diff --check
```

The focused run at that point passed its first 10 new tests in 0.177 seconds. Two additional tests were then added for retry exhaustion and visible processing/user-scoped reprocessing. Final full-suite output:

```text
Ran 100 tests in 2.294s
OK
```

Denominator: **100 tests**, 0 failures, 0 errors, 0 skipped. Twelve Phase A tests cover wrong/unknown/ambiguous times; answers before and after human approval; stale proposals; missing key plus recovery; two timeout retries and repeated reprocessing; empty extraction; partial-write rollback; Forget with jobs/traces; CLI save without provider execution; retry exhaustion; processing state and ownership; rate-limit/schema classification. Existing crash, lease, concurrency, source, approval and privacy tests also pass. No answer-quality success percentage is claimed.

A temporary local preview used only three fictional notes. Installed Chrome rendered Notes, Approvals and Jobs at 1280 and 390 pixels; six screenshots were captured and visually inspected, with no horizontal overflow. The first browser attempt failed because the bundled Chromium binary was absent; installed Chrome was then used. The owner subsequently asked to focus on the product rather than UI polish.

## Partial and missing

- Proven: the offline logic and HTTP integration suite described above. Mock tests do not establish real-model extraction/answer quality.
- Partial: mock extraction deliberately recognizes only limited fixtures. Subjects encode scope today; there is no general entity/time/scope model, so ambiguous real-world updates remain a limitation. Approval baselines compare fact IDs, not the full versioned API contract planned for Phase C.
- Partial: reprocessing retains existing extracted facts; it does not reconcile changed provider output against already extracted subjects. Legacy notes without checkpoints show pending instead of inventing a successful processing history.
- Missing: live Gemini validation, semantic retrieval/evaluations, API/second client and the later reliability/demo work (Phases B–E). No new guarantee about physical erasure of SQLite pages/backups or semantic claim support is made.
- Operational choice: the worker remains a separate process. Start it as documented in README; otherwise work remains queued. Explicit reprocessing can start another bounded cycle after configuration is fixed.

Stop here for owner review before Phase B.
