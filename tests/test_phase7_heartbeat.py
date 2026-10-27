"""Tests for heartbeat renewal and completion behavior."""

import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from memory_assistant import storage
from memory_assistant.job_heartbeat import JobHeartbeat
from memory_assistant.jobs import (
    claim_job,
    complete_job,
    create_job,
    get_job,
    init_jobs,
    owns_job_lease,
)


class HeartbeatTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()

        self.db_patch = patch.object(
            storage,
            "DB_PATH",
            Path(self.tempdir.name) / "test.db",
        )
        self.db_patch.start()

        storage.init_db()
        init_jobs()

        note_id = storage.add_note(
            "My fictional appointment is tomorrow."
        )

        self.job_id = create_job(note_id)
        self.job = claim_job()

    def tearDown(self):
        self.db_patch.stop()
        self.tempdir.cleanup()

    def test_heartbeat_renews_active_lease(self):
        with storage.get_connection() as conn:
            conn.execute(
                """
                UPDATE processing_jobs
                SET lease_until = ?
                WHERE id = ?
                """,
                (
                    "2099-01-01T00:00:00+00:00",
                    self.job_id,
                ),
            )

        with JobHeartbeat(
            self.job_id,
            self.job["lease_token"],
            interval_seconds=0.02,
            lease_seconds=120,
        ) as heartbeat:
            time.sleep(0.08)

        self.assertFalse(heartbeat.lost_lease)
        self.assertTrue(
            owns_job_lease(
                self.job_id,
                self.job["lease_token"],
            )
        )

    def test_completed_job_is_not_reported_lost(self):
        with JobHeartbeat(
            self.job_id,
            self.job["lease_token"],
            interval_seconds=0.02,
            lease_seconds=120,
        ) as heartbeat:
            self.assertTrue(
                complete_job(
                    self.job_id,
                    self.job["lease_token"],
                )
            )
            time.sleep(0.08)

        self.assertFalse(heartbeat.lost_lease)
        self.assertEqual(
            get_job(self.job_id)["status"],
            "succeeded",
        )

    def test_cancelled_job_reports_lost_lease(self):
        with JobHeartbeat(
            self.job_id,
            self.job["lease_token"],
            interval_seconds=0.02,
            lease_seconds=120,
        ) as heartbeat:
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

            time.sleep(0.08)

        self.assertTrue(heartbeat.lost_lease)


if __name__ == "__main__":
    unittest.main()
