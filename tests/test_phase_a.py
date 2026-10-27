"""Synthetic offline regressions for the normal durable save path."""
import contextlib
import importlib
import io
import os
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from memory_assistant import storage
from memory_assistant.ai import process_note
from memory_assistant.forget import forget_fact, prepare_forget_schema
from memory_assistant.gemini import GeminiError
from memory_assistant.jobs import get_job
from memory_assistant.note_processing import processing_status, reprocess_note
from memory_assistant.pipeline import pending_facts, prepare_schema
from memory_assistant.providers import MockProvider
from memory_assistant.queued_notes import add_queued_note
from memory_assistant.retrieval import ask
from memory_assistant.updates import resolve_update
from memory_assistant.worker import process_next_job


class PhaseATests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        p = patch.object(storage, 'DB_PATH', Path(self.temp.name) / 'test.db')
        p.start()
        self.addCleanup(p.stop)
        self.env = patch.dict(os.environ, {'MEMORY_PROVIDER': 'mock'}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        storage.init_db()
        prepare_schema()
        prepare_forget_schema()

    def save(self, text='Fictional yoga at 7 AM'):
        return add_queued_note(text)

    def available(self, job_id):
        with storage.get_connection() as conn:
            conn.execute("UPDATE processing_jobs SET available_at='2000-01-01' WHERE id=?", (job_id,))

    def test_wrong_time_and_unknown_input(self):
        provider = MockProvider()
        self.assertEqual(provider.extract('Fictional yoga at 7 AM')[0]['value'], '7 AM')
        for text in ('yoga at 8 AM', 'yoga tomorrow', 'yoga moved to 11 AM', 'yoga at 7 AM or 9 AM', 'unmatched input'):
            self.assertEqual(provider.extract(text), [], text)

    def test_current_answer_changes_only_after_approval(self):
        old, _ = self.save()
        process_next_job()
        new, _ = self.save('Fictional yoga at 9 AM')
        process_next_job()
        proposal = pending_facts()[0]
        self.assertEqual(proposal['old_statements'], ['Fictional yoga at 7 AM'])
        self.assertIn('7 AM', ask('yoga', MockProvider())['answer'])
        # Database reopen is implicit in every call; proposal survives it.
        resolve_update(proposal['approval_id'], 'approved')
        result = ask('yoga', MockProvider())
        self.assertIn('9 AM', result['answer'])
        self.assertEqual([s['note_id'] for s in result['sources']], [new])
        self.assertEqual(storage.list_facts()[0]['status'], 'superseded')

    def test_stale_proposal_cannot_replace_changed_current(self):
        self.save(); process_next_job()
        second, _ = self.save('Fictional yoga at 9 AM'); process_next_job()
        self.save('Different fictional yoga at 9 AM'); process_next_job()
        first, stale = pending_facts()
        resolve_update(first['approval_id'], 'approved')
        with self.assertRaisesRegex(ValueError, 'changed'):
            resolve_update(stale['approval_id'], 'approved')

    def test_missing_key_is_saved_failed_and_reprocessable(self):
        note, job = self.save()
        with patch.dict(os.environ, {'MEMORY_PROVIDER': 'gemini'}, clear=True):
            result = process_next_job()
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['last_error_code'], 'CONFIGURATION')
        self.assertEqual(processing_status(note)['state'], 'failed')
        self.assertEqual(reprocess_note(note), job)
        self.assertEqual(process_next_job()['status'], 'succeeded')
        self.assertEqual(len(storage.list_notes()), 1)

    def test_timeout_retries_twice_then_succeeds_without_duplicates(self):
        note, job = self.save()
        provider = MockProvider()
        original = provider.extract
        with patch.object(provider, 'extract', side_effect=[TimeoutError('private text'), TimeoutError('private text'), original('Fictional yoga at 7 AM')]):
            for attempt in (1, 2):
                result = process_next_job(provider=provider)
                self.assertEqual(result['attempts'], attempt)
                self.assertEqual(result['status'], 'queued')
                self.assertEqual(result['last_error_code'], 'TIMEOUT')
                self.assertNotIn('private text', result['last_error_message'])
                self.assertIsNone(process_next_job(provider=provider))
                self.available(job)
            self.assertEqual(process_next_job(provider=provider)['status'], 'succeeded')
        self.assertEqual(len(storage.list_facts()), 1)
        reprocess_note(note)
        process_next_job()
        self.assertEqual(len(storage.list_facts()), 1)

    def test_empty_extraction_has_readable_failed_status(self):
        note, job = self.save('Unmatched fictional sentence')
        self.assertEqual(process_next_job()['last_error_code'], 'EMPTY_EXTRACTION')
        self.assertEqual(processing_status(note)['state'], 'failed')
        self.assertEqual(storage.list_facts(), [])

    def test_bad_second_fact_rolls_back_first(self):
        note, job = self.save()
        provider = MockProvider()
        facts = provider.extract('Fictional yoga at 7 AM') + [{'subject': 'broken'}]
        with patch.object(provider, 'extract', return_value=facts):
            self.assertEqual(process_next_job(provider=provider)['status'], 'failed')
        self.assertEqual(storage.list_facts(), [])
        reprocess_note(note)
        process_next_job()
        self.assertEqual(len(storage.list_facts()), 1)

    def test_forget_removes_jobs_and_traces_and_prevents_resave(self):
        note, job = self.save(); process_next_job()
        forget_fact(storage.list_facts()[0]['id'])
        self.assertIsNone(get_job(job))
        with storage.get_connection() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM processing_traces').fetchone()[0], 0)
        with self.assertRaises(ValueError):
            self.save()
        with self.assertRaises(ValueError):
            reprocess_note(note)

    def test_cli_add_does_not_call_provider_and_shows_status(self):
        # Do not read any local .env file during tests.
        with patch('memory_assistant.config.load_env'):
            cli = importlib.import_module('memory_assistant.__main__')
        output = io.StringIO()
        with contextlib.redirect_stdout(output), patch('sys.argv', ['memory_assistant', 'add', 'Fictional yoga at 7 AM']), patch('memory_assistant.ai.get_provider', side_effect=AssertionError('must not run')):
            cli.main()
        self.assertIn('Processing job queued', output.getvalue())
        self.assertEqual(len(storage.list_notes()), 1)
        self.assertEqual(processing_status(1)['state'], 'pending')
        process_next_job()
        self.assertEqual(processing_status(1)['state'], 'done')


    def test_transient_failure_stops_after_three_attempts(self):
        note, job = self.save()
        provider = MockProvider()
        with patch.object(provider, 'extract', side_effect=TimeoutError()):
            for attempt in range(3):
                self.available(job)
                result = process_next_job(provider=provider)
            self.assertEqual(result['status'], 'failed')
            self.assertEqual(result['attempts'], 3)
            self.assertIsNone(process_next_job(provider=provider))
        self.assertEqual(storage.list_facts(), [])

    def test_processing_state_and_user_scoped_reprocess(self):
        from memory_assistant.jobs import claim_job
        note, job = self.save()
        claim_job()
        self.assertEqual(processing_status(note)['state'], 'processing')
        with self.assertRaises(ValueError):
            reprocess_note(note)
        with self.assertRaises(ValueError):
            reprocess_note(note, user_id=999)

    def test_rate_limit_and_schema_are_classified(self):
        from memory_assistant.processing_errors import classify_error
        try:
            try:
                raise urllib.error.HTTPError('https://example.invalid', 429, 'limited', {}, None)
            except urllib.error.HTTPError as cause:
                raise GeminiError('safe wrapper') from cause
        except GeminiError as error:
            self.assertEqual(classify_error(error)[0::2], ('RATE_LIMIT', True))
        self.assertEqual(classify_error(GeminiError('Invalid extracted fact.'))[0::2], ('BAD_SCHEMA', False))
