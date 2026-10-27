"""Metric and pipeline regressions, with small fictional histories only."""
import copy
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from memory_assistant import storage
from memory_assistant.benchmark.dataset import history_from_record, sha256_file
from memory_assistant.benchmark.index import BenchmarkIndex
from memory_assistant.benchmark.metrics import dcg, session_metrics
from memory_assistant.benchmark.runner import run_keyword, summarize, write_report
from memory_assistant.retrieval import retrieve


def fixture(question_id, question='Where is fictional Postgres used?'):
    return {
        'question_id': question_id, 'question_type': 'knowledge-update',
        'question': question, 'answer': 'REFERENCE_NOT_FOR_INDEX',
        'haystack_session_ids': ['shared', 'new_scope'],
        'haystack_dates': ['', 'unknown'],
        'haystack_sessions': [[{'role': 'user', 'content': 'Fictional SQLite for local tests.', 'has_answer': False}],
                              [{'role': 'assistant', 'content': 'Fictional Postgres for shared deployment.', 'has_answer': True}]],
        'answer_session_ids': ['new_scope'],
    }


class MetricTests(unittest.TestCase):
    def test_official_discount_convention_and_late_evidence(self):
        self.assertEqual(dcg([0, 1], 10), 1.0)
        self.assertAlmostEqual(dcg([0, 0, 1], 10), 1 / math.log2(3))
        self.assertEqual(dcg([], 10), 0.0)
        result = session_metrics(['a', 'b', 'c'], ['c'], ['a', 'b', 'c'], 10)
        self.assertEqual(result['recall_all@10'], 1.0)
        self.assertAlmostEqual(result['ndcg_any@10'], 1 / math.log2(3))

    def test_all_evidence_required_including_at_cutoff(self):
        corpus = [str(number) for number in range(12)]
        result = session_metrics(corpus, ['0', '10'], corpus, 10)
        self.assertEqual(result['recall_all@10'], 0.0)
        self.assertEqual(result['ndcg_any@10'], 0.5)
        self.assertEqual(session_metrics(['10', '0'], ['0', '10'], corpus, 10)['recall_all@10'], 1.0)

    def test_partial_rankings_do_not_reduce_ideal_denominator(self):
        result = session_metrics(['a'], ['a', 'b'], ['a', 'b', 'c'])
        self.assertEqual(result['recall_all@10'], 0.0)
        self.assertEqual(result['ndcg_any@10'], 0.5)
        self.assertEqual(session_metrics([], ['a'], ['a'])['ndcg_any@10'], 0.0)

    def test_duplicate_or_outside_ids_and_unscorable_cases_are_rejected(self):
        for ranking, correct, corpus in [(['a', 'a'], ['a'], ['a']), (['b'], ['a'], ['a']), ([], [], ['a']), ([], ['b'], ['a'])]:
            with self.assertRaises(ValueError):
                session_metrics(ranking, correct, corpus)

    def test_failed_items_stay_in_denominator_and_abs_are_excluded(self):
        summary = summarize([
            {'question_id': 'pass', 'abstention': False, 'status': 'scored', 'metrics': {'recall_all@10': 1.0, 'ndcg_any@10': 1.0}, 'retrieval_ms': 2.0, 'missing_session_ids': []},
            {'question_id': 'failed', 'abstention': False, 'status': 'failed', 'error_code': 'BAD_DATA'},
            {'question_id': 'skip_abs', 'abstention': True, 'status': 'skipped_abstention'},
        ])
        self.assertEqual((summary['selected'], summary['eligible'], summary['failed'], summary['skipped_abstentions']), (3, 2, 1, 1))
        self.assertEqual(summary['metrics']['recall_all@10'], 0.5)
        self.assertEqual(summary['retrieval_ms']['samples'], 1)


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def dataset(self, records, dev, heldout=()):
        path = self.root / 'synthetic.json'
        path.write_text(json.dumps(records))
        manifest = {
            'dataset': {'filename': path.name, 'sha256': sha256_file(path), 'size_bytes': path.stat().st_size, 'revision': 'fictional-fixture'},
            'split': {'version': 'synthetic', 'seed': 'synthetic', 'dev': list(dev), 'heldout': list(heldout)},
            'official_metrics': {'revision': 'synthetic-tests'},
        }
        manifest_path = self.root / 'manifest.json'
        manifest_path.write_text(json.dumps(manifest))
        return path, manifest_path

    def run_fixture(self, path, manifest):
        return run_keyword(path, manifest, self.root / 'index.sqlite3')

    def test_end_to_end_is_model_free_and_only_indexes_dev(self):
        record = fixture('dev')
        path, manifest = self.dataset([record, fixture('heldout')], ['dev'], ['heldout'])
        with patch('memory_assistant.ai.get_provider', side_effect=AssertionError('no model')), patch.object(storage, 'get_connection', side_effect=AssertionError('no product database')):
            report = self.run_fixture(path, manifest)
        self.assertEqual(report['summary']['metrics']['recall_all@10'], 1.0)
        self.assertEqual(report['metadata']['model_calls'], 0)
        self.assertEqual(report['summary']['eligible'], 1)
        index = BenchmarkIndex(self.root / 'index.sqlite3')
        self.addCleanup(index.close)
        self.assertEqual(index.corpus_session_ids('heldout'), [])
        self.assertEqual(index.keyword_search('dev', 'REFERENCE_NOT_FOR_INDEX')[0], [])

    def test_bad_or_missing_questions_fail_without_dropping_denominator(self):
        bad = fixture('bad')
        bad['haystack_dates'] = []
        path, manifest = self.dataset([fixture('good'), fixture('skip_abs'), bad], ['good', 'skip_abs', 'bad', 'missing'])
        report = self.run_fixture(path, manifest)
        summary = report['summary']
        self.assertEqual((summary['selected'], summary['eligible'], summary['scored'], summary['failed'], summary['skipped_abstentions']), (4, 3, 1, 2, 1))
        self.assertAlmostEqual(summary['metrics']['recall_all@10'], 1 / 3)
        self.assertEqual({row['question_id'] for row in summary['failures']}, {'bad', 'missing'})

    def test_reference_and_turn_label_changes_cannot_change_retrieval(self):
        original = fixture('dev')
        path, manifest = self.dataset([original], ['dev'])
        first = self.run_fixture(path, manifest)
        changed = copy.deepcopy(original)
        changed['answer'] = 'OTHER_REFERENCE'
        changed['answer_session_ids'] = ['shared']
        for session in changed['haystack_sessions']:
            for turn in session:
                turn['has_answer'] = not turn['has_answer']
        path, manifest = self.dataset([changed], ['dev'])
        second = self.run_fixture(path, manifest)
        self.assertEqual(first['questions'][0]['ranked_sessions'], second['questions'][0]['ranked_sessions'])
        self.assertEqual(second['questions'][0]['missing_session_ids'], ['shared'])

    def test_overlapping_split_and_heldout_execution_are_rejected(self):
        path, manifest = self.dataset([fixture('dev')], ['dev'], ['dev'])
        with self.assertRaisesRegex(ValueError, 'overlapping'):
            self.run_fixture(path, manifest)
        with self.assertRaisesRegex(ValueError, 'reserved'):
            run_keyword(path, manifest, self.root / 'index.sqlite3', subset='heldout')

    def test_atomic_report_refuses_overwriting_existing_result(self):
        output = self.root / 'results' / 'result.json'
        write_report({'proof': 1}, output)
        with self.assertRaises(FileExistsError):
            write_report({'proof': 2}, output)
        self.assertEqual(json.loads(output.read_text()), {'proof': 1})
        self.assertEqual(list(output.parent.iterdir()), [output])

    def test_keyword_ranking_matches_product_on_equivalent_raw_sources(self):
        record = fixture('dev', 'Fictional local deployment')
        with patch.object(storage, 'DB_PATH', self.root / 'product.sqlite3'):
            storage.init_db()
            for session in record['haystack_sessions']:
                text = session[0]['content']
                note = storage.add_note(text)
                with storage.get_connection() as connection:
                    connection.execute("INSERT INTO facts(user_id,note_id,statement,status,confidence,created_at) VALUES(1,?,?,'active',1,'synthetic')", (note, text))
            expected = retrieve(record['question'])
        index = BenchmarkIndex(self.root / 'parity.sqlite3')
        self.addCleanup(index.close)
        index.ingest(history_from_record(record))
        actual, _ = index.keyword_search('dev', record['question'])
        self.assertEqual([row['score'] for row in actual], [row['score'] for row in expected])
        self.assertEqual([row['chunk_id'] for row in actual], [row['fact_id'] for row in expected])

    def test_session_collapse_uses_first_ranked_turn_without_id_parsing(self):
        record = fixture('dev', 'Fictional Postgres deployment')
        record['haystack_sessions'][1].append({'role': 'user', 'content': 'Fictional Postgres'})
        index = BenchmarkIndex(self.root / 'collapse.sqlite3')
        self.addCleanup(index.close)
        index.ingest(history_from_record(record))
        ranked, _ = index.keyword_search('dev', record['question'])
        self.assertEqual([row['session_id'] for row in ranked], ['new_scope'])
        self.assertEqual(ranked[0]['chunk_id'], 2)
