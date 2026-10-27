"""Synthetic-only checks for the benchmark data boundary and namespaces."""
import copy
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from memory_assistant.benchmark.dataset import (
    History, Session, Turn, history_from_record, iter_records,
    query_from_record, read_manifest, sha256_file, verify_dataset,
)
from memory_assistant.benchmark.index import BenchmarkIndex
from memory_assistant.benchmark.splits import build_splits


def sample_record(question_id='question-a'):
    return {
        'question_id': question_id, 'question_type': 'knowledge-update',
        'question': 'QUERY_CANARY', 'answer': 'REFERENCE_CANARY',
        'question_date': 'QUERY_DATE_CANARY',
        'haystack_session_ids': ['shared-id', 'session-b'],
        'haystack_dates': ['2025/01/01 08:00', '2025/02/01 08:00'],
        'haystack_sessions': [
            [{'role': 'user', 'content': 'Fictional Atlas prototype uses SQLite.', 'has_answer': True},
             {'role': 'assistant', 'content': 'Keep fictional local tests separate.', 'has_answer': False}],
            [{'role': 'user', 'content': 'Fictional Atlas deployment uses Postgres.', 'has_answer': True}],
        ],
        'answer_session_ids': ['session-b'],
    }


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.index = BenchmarkIndex(self.root / 'index.sqlite3')
        self.addCleanup(self.index.close)

    def snapshot(self):
        return {name: [tuple(row) for row in self.index.connection.execute(f'SELECT * FROM {name} ORDER BY 1,2')]
                for name in ('benchmark_sessions', 'benchmark_chunks')}

    def test_labels_reference_question_and_query_date_never_enter_index(self):
        record = sample_record()
        self.index.ingest(history_from_record(record))
        first = self.snapshot()
        changed = copy.deepcopy(record)
        changed.update(question='ANOTHER_QUERY', answer='ANOTHER_REFERENCE', question_date='ANOTHER_DATE', answer_session_ids=['shared-id'])
        for session in changed['haystack_sessions']:
            for turn in session:
                turn['has_answer'] = not turn['has_answer']
                turn['unexpected_label'] = 'LABEL_CANARY'
        self.index.ingest(history_from_record(changed))
        self.assertEqual(self.snapshot(), first)
        stored = json.dumps(first)
        for canary in ('QUERY_CANARY', 'REFERENCE_CANARY', 'QUERY_DATE_CANARY', 'has_answer', 'LABEL_CANARY', 'answer_session_ids'):
            self.assertNotIn(canary, stored)
        with self.assertRaises(TypeError):
            self.index.ingest(record)

    def test_colliding_session_ids_are_isolated_in_both_directions(self):
        first = sample_record()
        second = sample_record('question-b')
        second['haystack_sessions'][0][0]['content'] = 'Fictional Neptune uses Redis.'
        self.index.ingest(history_from_record(first))
        self.index.ingest(history_from_record(second))
        self.assertEqual(self.index.keyword_search('question-a', 'Neptune Redis')[0], [])
        self.assertEqual(self.index.keyword_search('question-b', 'SQLite')[0], [])
        self.assertEqual(self.index.keyword_search('unknown-question', 'Atlas')[0], [])
        self.assertEqual(self.index.keyword_search('question-b', 'Redis')[0][0]['session_id'], 'shared-id')

    def test_both_roles_and_raw_timestamps_are_preserved_without_inference(self):
        record = sample_record()
        self.index.ingest(history_from_record(record))
        self.assertEqual(self.index.keyword_search('question-a', 'local tests')[0][0]['turn_ordinal'], 1)
        dates = [row[0] for row in self.index.connection.execute('SELECT timestamp FROM benchmark_sessions ORDER BY session_ordinal')]
        self.assertEqual(dates, record['haystack_dates'])

    def test_reingest_replaces_chunks_and_is_atomic(self):
        self.index.ingest(history_from_record(sample_record()))
        before = self.snapshot()
        duplicate = Session('same', 'unknown', (Turn('user', 'fictional text'),))
        with self.assertRaises(sqlite3.IntegrityError):
            self.index.ingest(History('question-a', (duplicate, Session(None, 'unknown', ()))))
        self.assertEqual(self.snapshot(), before)
        self.index.ingest(History('question-a', (Session('replacement', '', (Turn('user', 'new fictional text'),)),)))
        self.assertEqual(self.index.corpus_session_ids('question-a'), ['replacement'])
        self.assertEqual(self.index.keyword_search('question-a', 'SQLite')[0], [])

    def test_refuses_product_database(self):
        path = self.root / 'product.sqlite3'
        with sqlite3.connect(path) as connection:
            connection.execute('CREATE TABLE notes (id INTEGER)')
        with self.assertRaisesRegex(ValueError, 'dedicated'):
            BenchmarkIndex(path)

    def test_adapter_rejects_misalignment_and_preserves_duplicate_occurrences(self):
        record = sample_record()
        record['haystack_dates'].pop()
        with self.assertRaises(ValueError):
            history_from_record(record)
        record = sample_record()
        record['haystack_session_ids'] = ['same', 'same']
        history = history_from_record(record)
        self.index.ingest(history)
        self.assertEqual(len(history.sessions), 2)
        self.assertEqual(self.index.corpus_session_ids('question-a'), ['same'])
        self.assertEqual(self.index.connection.execute('SELECT COUNT(*) FROM benchmark_sessions').fetchone()[0], 2)

    def test_query_validates_evidence_without_using_reference_answers(self):
        record = sample_record()
        query = query_from_record(record)
        record['answer'] = {'unexpected': 'REFERENCE_CANARY'}
        self.assertEqual(query_from_record(record), query)
        record['answer_session_ids'] = ['outside-corpus']
        with self.assertRaises(ValueError):
            query_from_record(record)

    def test_streaming_parser_handles_chunk_boundaries_and_escaped_text(self):
        path = self.root / 'sample.json'
        records = [{'text': 'Fictional [brackets], \\"quotes\\" and café'}, sample_record()]
        path.write_text(json.dumps(records), encoding='utf-8')
        for block_size in (1, 2, 3, 31):
            self.assertEqual(list(iter_records(path, block_size)), records)

    def test_streaming_parser_rejects_corrupt_arrays(self):
        path = self.root / 'bad.json'
        for content in ('{}', '[{},]', '[{}', '[{} {}]', '[{}] extra', '[1]', '[{"unfinished":'):
            path.write_text(content)
            with self.assertRaises(ValueError, msg=content):
                list(iter_records(path, block_size=2))

    def test_sha_verification_rejects_different_bytes_and_missing_data(self):
        path = self.root / 'dataset.json'
        path.write_text('[]')
        manifest = {'dataset': {'size_bytes': 2, 'sha256': sha256_file(path)}}
        verify_dataset(path, manifest)
        path.write_text('{}')
        with self.assertRaises(ValueError):
            verify_dataset(path, manifest)
        with self.assertRaises(ValueError):
            verify_dataset(self.root / 'missing.json', manifest)

    def test_splits_are_deterministic_disjoint_and_stratified(self):
        metadata = [(f'{kind}-{number}', kind, number % 10 == 0) for kind in ('a', 'b', 'c', 'd', 'e', 'f') for number in range(100)]
        split = build_splits(metadata, 'fixed-seed')
        self.assertEqual(split, build_splits(list(reversed(metadata)), 'fixed-seed'))
        self.assertEqual(len(split['dev']), 40)
        self.assertEqual(len(split['heldout']), 60)
        self.assertFalse(set(split['dev']) & set(split['heldout']))
        self.assertTrue(all(split['dev_counts_by_type'].values()))
        self.assertTrue(all(split['heldout_counts_by_type'].values()))
        with self.assertRaises(ValueError):
            build_splits(metadata + [metadata[0]], 'fixed-seed')

    def test_committed_manifest_has_frozen_split_and_pinned_upstream(self):
        manifest = read_manifest()
        split = manifest['split']
        self.assertEqual(len(split['dev']), 40)
        self.assertEqual(len(split['heldout']), 60)
        self.assertEqual(len(set(split['dev'] + split['heldout'])), 100)
        self.assertEqual(len(manifest['dataset']['revision']), 40)
        self.assertEqual(len(manifest['dataset']['sha256']), 64)
        self.assertEqual(manifest['dataset']['filename'], 'longmemeval_s_cleaned.json')
        upstream = Path(__file__).resolve().parents[1] / 'benchmarks' / 'longmemeval' / 'upstream'
        for source, digest in manifest['official_metrics']['files'].items():
            self.assertEqual(sha256_file(upstream / Path(source).name), digest)
