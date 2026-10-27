"""A model-free dev runner: ingest history, retrieve, then read scoring labels."""
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import subprocess
import sqlite3
import tempfile
import time

from .dataset import (BENCHMARK_DIR, DATASET_PATH, MANIFEST_PATH, ROOT, QUESTION_TYPES,
                      history_from_record, iter_records, query_from_record,
                      read_manifest, sha256_file, verify_dataset)
from .index import BenchmarkIndex, INDEX_VERSION
from .metrics import METRIC_VERSION, session_metrics


def percentile(values, fraction):
    if not values:
        return None
    return sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)]


def summarize(results):
    """Fail closed: failures remain in the eligible denominator, scored as zero."""
    eligible = [row for row in results if not row['abstention']]
    scored = [row for row in eligible if row['status'] == 'scored']
    metrics = {name: sum(row.get('metrics', {}).get(name, 0.0) for row in eligible) / len(eligible) if eligible else None
               for name in ('recall_all@10', 'ndcg_any@10')}
    return {
        'selected': len(results), 'eligible': len(eligible), 'scored': len(scored),
        'failed': sum(row['status'] == 'failed' for row in results),
        'skipped_abstentions': sum(row['status'] == 'skipped_abstention' for row in results),
        'failure_policy': 'Failed eligible questions score zero; abstentions are excluded.',
        'metrics': metrics,
        'perfect_recall_questions': sum(row['metrics']['recall_all@10'] == 1 for row in scored),
        'retrieval_ms': {'samples': len(scored),
                         'p50': percentile([row['retrieval_ms'] for row in scored], 0.50),
                         'p95': percentile([row['retrieval_ms'] for row in scored], 0.95)},
        'misses': [{'question_id': row['question_id'], 'missing_session_ids': row['missing_session_ids']}
                   for row in scored if row['missing_session_ids']],
        'failures': [{'question_id': row['question_id'], 'error_code': row['error_code']}
                     for row in results if row['status'] == 'failed'],
    }


def code_provenance():
    def git(*args):
        return subprocess.check_output(['git', *args], cwd=ROOT, text=True, stderr=subprocess.DEVNULL).strip()
    try:
        return {'commit': git('rev-parse', 'HEAD'), 'working_tree_dirty': bool(git('status', '--porcelain'))}
    except (OSError, subprocess.CalledProcessError):
        return {'commit': None, 'working_tree_dirty': None}


def run_keyword(dataset_path=DATASET_PATH, manifest_path=MANIFEST_PATH,
                index_path=BENCHMARK_DIR / 'local' / 'keyword.sqlite3', subset='dev'):
    if subset != 'dev':
        raise ValueError('Heldout is reserved for the later frozen final comparison; only dev runs are enabled.')
    manifest = read_manifest(manifest_path)
    verify_dataset(dataset_path, manifest)
    split = manifest['split']
    selected = split['dev']
    heldout = split['heldout']
    if not selected or len(selected) != len(set(selected)) or len(heldout) != len(set(heldout)) or set(selected) & set(heldout):
        raise ValueError('Invalid, empty or overlapping benchmark split.')
    selected_set = set(selected)
    metadata = {
        **code_provenance(),
        'created_at_utc': datetime.now(timezone.utc).isoformat(),
        'dataset': manifest['dataset'],
        'manifest_sha256': sha256_file(manifest_path),
        'split_version': split['version'], 'split_seed': split['seed'], 'subset': subset,
        'subset_ids_sha256': hashlib.sha256(json.dumps(sorted(selected), separators=(',', ':')).encode()).hexdigest(),
        'official_metrics': manifest['official_metrics'],
        'method': 'keyword', 'index_version': INDEX_VERSION, 'metric_version': METRIC_VERSION,
        'configuration': {
            'chunking': 'one raw turn per chunk; all roles; all duplicate session occurrences preserved',
            'ranking': 'product tokens and exact token-overlap count; ascending chunk ID breaks ties',
            'session_aggregation': 'first occurrence per session ID in the ranked positive-score turns',
            'top_k_sessions': 10, 'zero_score_fill': False,
            'timestamp_scoring': False, 'question_date_scoring': False,
            'extraction': False, 'approval': False, 'answer_generation': False,
        },
        'provider_mode': 'none; retrieval only', 'model': None,
        'embedding_version': None, 'prompt_version': None, 'model_calls': 0,
        'python': platform.python_version(), 'platform': platform.platform(),
        'source_sha256': {str(path.relative_to(ROOT)): sha256_file(path) for path in (
            ROOT / 'memory_assistant' / 'retrieval.py',
            Path(__file__).with_name('index.py'), Path(__file__).with_name('metrics.py'),
            Path(__file__).with_name('dataset.py'), Path(__file__),
        )},
    }
    started = time.perf_counter()
    index = BenchmarkIndex(index_path)
    results = []
    seen = set()
    try:
        for record in iter_records(dataset_path):
            question_id = record.get('question_id')
            if not isinstance(question_id, str) or question_id in seen:
                raise ValueError('Invalid or duplicate dataset question ID.')
            seen.add(question_id)
            if question_id not in selected_set:
                continue
            abstention = '_abs' in question_id
            kind = record.get('question_type')
            row = {'question_id': question_id, 'question_type': kind if kind in QUESTION_TYPES else 'unknown',
                   'abstention': abstention}
            item_started = time.perf_counter()
            try:
                # Ingestion has no access to the evaluation query or reference fields.
                history = history_from_record(record)
                row['indexed_turns'] = index.ingest(history)
                row['session_occurrences'] = len(history.sessions)
                corpus_ids = index.corpus_session_ids(question_id)
                row['unique_sessions'] = len(corpus_ids)
                row['index_ms'] = (time.perf_counter() - item_started) * 1000
                if abstention:
                    row.update(status='skipped_abstention', skip_reason='Official retrieval exclusion: _abs ID.')
                else:
                    query = query_from_record(record)
                    ranked, elapsed = index.keyword_search(question_id, query.question, limit=10)
                    retrieved_ids = [item['session_id'] for item in ranked]
                    # Labels cross only into scoring, after retrieval has completed.
                    row.update(status='scored', retrieval_ms=elapsed, ranked_sessions=ranked,
                               expected_session_ids=list(query.evidence_session_ids),
                               missing_session_ids=sorted(set(query.evidence_session_ids) - set(retrieved_ids)),
                               metrics=session_metrics(retrieved_ids, query.evidence_session_ids, corpus_ids, k=10))
            except (ValueError, KeyError, TypeError, sqlite3.Error) as error:
                row.update(status='failed', error_code=type(error).__name__)
            row['total_ms'] = (time.perf_counter() - item_started) * 1000
            results.append(row)
    finally:
        index.close()
    for question_id in sorted(selected_set - seen):
        results.append({'question_id': question_id, 'question_type': 'unknown',
                        'abstention': '_abs' in question_id, 'status': 'failed',
                        'error_code': 'MISSING_QUESTION'})
    results.sort(key=lambda row: row['question_id'])
    grouped = defaultdict(list)
    for row in results:
        grouped[row['question_type']].append(row)
    metadata['elapsed_ms'] = (time.perf_counter() - started) * 1000
    return {'schema_version': 1, 'metadata': metadata, 'summary': summarize(results),
            'by_question_type': {kind: summarize(rows) for kind, rows in sorted(grouped.items())},
            'questions': results}


def write_report(report, output):
    """Publish a complete JSON file atomically; never overwrite an earlier run."""
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=output.parent, delete=False) as target:
            temporary = Path(target.name)
            json.dump(report, target, indent=2, allow_nan=False)
            target.write('\n')
        os.link(temporary, output)  # Atomic and fails if output already exists.
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)
    return output
