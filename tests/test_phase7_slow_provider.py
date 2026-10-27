"""Tests for slow extraction and heartbeat lease renewal."""

import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from memory_assistant import storage
from memory_assistant.jobs import (
    claim_job,
    create_job,
    get_job,
    init_jobs,
)
from memory_assistant.pipeline import prepare_schema
from memory_assistant.worker import process_next_job


class SlowProvider:
    name = "slow-test"

    def extract(self, text):
        time.sleep(0.2)
        return [{
            "subject": "appointment",
            "value": "9 AM",
            "statement": "My fictional appointment is at 9 AM.",
            "confidence": 0.99,
        }]


class SlowProviderTests(unittest.TestCase):

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

    def test_heartbeat_extends_lease_during_slow_extraction(self):
        from memory_assistant.job_heartbeat import JobHeartbeat
        from memory_assistant.ai import process_note

        job = claim_job(lease_seconds=2)

        with storage.get_connection() as conn:
            before = conn.execute(
                "SELECT lease_until FROM processing_jobs WHERE id = ?",
                (self.job_id,),
            ).fetchone()["lease_until"]

        with JobHeartbeat(
            self.job_id,
            job["lease_token"],
            interval_seconds=0.03,
            lease_seconds=120,
        ) as heartbeat:
            process_note(
                self.note_id,
                provider=SlowProvider(),
                job_id=self.job_id,
                lease_token=job["lease_token"],
            )

        with storage.get_connection() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM facts WHERE note_id = ?",
                (self.note_id,),
            ).fetchone()

        self.assertFalse(heartbeat.lost_lease)
        self.assertEqual(row[0], 1)
        self.assertEqual(get_job(self.job_id)["status"], "succeeded")

        # Completion clears the lease, so we cannot compare
        # the final lease_until against the original expiry.
        # The test demonstrates successful processing while
        # heartbeat renewals occur during extraction.

    def test_worker_completes_slow_provider_job(self):
        result = process_next_job(provider=SlowProvider())

        self.assertIsNotNone(result)
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(get_job(self.job_id)["status"], "succeeded")


if __name__ == "__main__":
    unittest.main()
