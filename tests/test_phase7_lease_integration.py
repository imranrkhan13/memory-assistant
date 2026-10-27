"""Integration tests for lease renewal and cancellation."""

import tempfile
import threading
import time
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from memory_assistant import storage
from memory_assistant.ai import process_note
from memory_assistant.job_heartbeat import JobHeartbeat
from memory_assistant.jobs import (
    claim_job,
    create_job,
    get_job,
    init_jobs,
)
from memory_assistant.pipeline import prepare_schema


class ControlledProvider:
    name = "controlled-test"

    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()

    def extract(self, text):
        self.started.set()

        if not self.release.wait(timeout=5):
            raise TimeoutError("Test provider was not released")

        return [{
            "subject": "appointment",
            "value": "9 AM",
            "statement": "My fictional appointment is at 9 AM.",
            "confidence": 0.99,
        }]


class LeaseIntegrationTests(unittest.TestCase):

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(
            storage,
            "DB_PATH",
            Path(self.tempdir.name) / "test.db",
        )
        self.db_patch.start()

        storage.init_db()
        prepare_schema()
        init_jobs()

        self.note_id = storage.add_note(
            "My fictional appointment is at 9 AM."
        )
        self.job_id = create_job(self.note_id)

    def tearDown(self):
        self.db_patch.stop()
        self.tempdir.cleanup()

    def lease_until(self):
        with storage.get_connection() as conn:
            row = conn.execute(
                """
                SELECT lease_until
                FROM processing_jobs
                WHERE id = ?
                """,
                (self.job_id,),
            ).fetchone()

        return row["lease_until"]

    def fact_count(self):
        with storage.get_connection() as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM facts WHERE note_id = ?",
                (self.note_id,),
            ).fetchone()[0]

    def test_heartbeat_actually_extends_expiry(self):
        job = claim_job(lease_seconds=2)
        before = datetime.fromisoformat(self.lease_until())

        with JobHeartbeat(
            self.job_id,
            job["lease_token"],
            interval_seconds=0.02,
            lease_seconds=120,
        ) as heartbeat:
            time.sleep(0.12)
            after = datetime.fromisoformat(self.lease_until())

        self.assertGreater(after, before)
        self.assertFalse(heartbeat.lost_lease)

    def test_cancel_during_extraction_saves_no_facts(self):
        job = claim_job()
        provider = ControlledProvider()
        errors = []

        def run_extraction():
            try:
                process_note(
                    self.note_id,
                    provider=provider,
                    job_id=self.job_id,
                    lease_token=job["lease_token"],
                )
            except Exception as error:
                errors.append(error)

        thread = threading.Thread(target=run_extraction)
        thread.start()

        try:
            self.assertTrue(provider.started.wait(timeout=2))

            with storage.get_connection() as conn:
                conn.execute(
                    """
                    UPDATE processing_jobs
                    SET status = 'cancelled',
                        lease_token = NULL,
                        lease_until = NULL
                    WHERE id = ?
                    """,
                    (self.job_id,),
                )
        finally:
            provider.release.set()
            thread.join(timeout=5)

        self.assertFalse(thread.is_alive())
        self.assertEqual(self.fact_count(), 0)
        self.assertEqual(
            get_job(self.job_id)["status"],
            "cancelled",
        )
        self.assertTrue(
            any(isinstance(error, RuntimeError) for error in errors)
        )

    def test_expiry_during_extraction_saves_no_facts(self):
        job = claim_job()
        provider = ControlledProvider()
        errors = []

        def run_extraction():
            try:
                process_note(
                    self.note_id,
                    provider=provider,
                    job_id=self.job_id,
                    lease_token=job["lease_token"],
                )
            except Exception as error:
                errors.append(error)

        thread = threading.Thread(target=run_extraction)
        thread.start()

        try:
            self.assertTrue(provider.started.wait(timeout=2))

            with storage.get_connection() as conn:
                conn.execute(
                    """
                    UPDATE processing_jobs
                    SET lease_until = ?
                    WHERE id = ?
                    """,
                    (
                        "2000-01-01T00:00:00+00:00",
                        self.job_id,
                    ),
                )
        finally:
            provider.release.set()
            thread.join(timeout=5)

        self.assertFalse(thread.is_alive())
        self.assertEqual(self.fact_count(), 0)
        self.assertTrue(
            any(isinstance(error, RuntimeError) for error in errors)
        )


if __name__ == "__main__":
    unittest.main()
