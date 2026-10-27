
"""Phase 5: local browser HTTP integration tests.

Tests browser functionality with the Phase 7 queued note-processing flow.
"""

import http.cookiejar
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import (
    HTTPCookieProcessor,
    Request,
    build_opener,
)

from memory_assistant import storage
from memory_assistant.web import create_server
from memory_assistant.worker import process_pending_jobs


class WebTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.provider_patch = patch.dict(
            "os.environ",
            {"MEMORY_PROVIDER": "mock"},
        )
        cls.provider_patch.start()

        cls.temp = tempfile.TemporaryDirectory()
        cls.db_path = Path(cls.temp.name) / "test.db"

        cls.db_patch = patch.object(
            storage,
            "DB_PATH",
            cls.db_path,
        )
        cls.db_patch.start()

        cls.server = create_server(port=0)
        cls.port = cls.server.server_port
        cls.base = f"http://127.0.0.1:{cls.port}"

        cls.thread = threading.Thread(
            target=cls.server.serve_forever,
            daemon=True,
        )
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

        cls.db_patch.stop()
        cls.temp.cleanup()
        cls.provider_patch.stop()

    def setUp(self):
        self.cookies = http.cookiejar.CookieJar()
        self.client = build_opener(
            HTTPCookieProcessor(self.cookies)
        )

        # This is an isolated temporary test database.
        # Delete dependent records before deleting notes.
        with storage.get_connection() as conn:
            conn.execute("DELETE FROM approvals")
            conn.execute("DELETE FROM processing_traces")
            conn.execute("DELETE FROM processing_jobs")
            conn.execute("DELETE FROM facts")
            conn.execute("DELETE FROM notes")
            conn.execute("DELETE FROM audit_log")
            conn.execute("DELETE FROM forgotten_fingerprints")

    def get(self, path="/"):
        with self.client.open(self.base + path) as response:
            return (
                response.status,
                response.read().decode("utf-8"),
            )

    def post(self, path, data, include_csrf=True):
        fields = dict(data)

        if include_csrf:
            self.get("/")

            token = next(
                cookie.value
                for cookie in self.cookies
                if cookie.name == "memory_csrf"
            )

            fields["csrf"] = token

        body = urlencode(fields).encode("utf-8")

        request = Request(
            self.base + path,
            data=body,
            method="POST",
            headers={
                "Content-Type":
                    "application/x-www-form-urlencoded",
                "Origin": self.base,
            },
        )

        with self.client.open(request) as response:
            return (
                response.status,
                response.read().decode("utf-8"),
                response.geturl(),
            )

    def run_queued_jobs(self):
        """Process queued notes before checking extracted facts."""
        process_pending_jobs()

    def test_dashboard_loads(self):
        status, body = self.get("/")

        self.assertEqual(status, 200)
        self.assertIn("Personal Memory Assistant", body)
        self.assertIn("Dashboard", body)

    def test_navigation_pages_load(self):
        for path in (
            "/notes",
            "/jobs",
            "/facts",
            "/approvals",
            "/ask",
            "/history",
            "/audit",
        ):
            with self.subTest(path=path):
                status, _ = self.get(path)
                self.assertEqual(status, 200)

    def test_add_note_through_browser(self):
        status, body, url = self.post(
            "/add",
            {
                "text":
                    "I selected the 9 AM yoga batch "
                    "because evening traffic is bad."
            },
        )

        self.assertEqual(status, 200)
        self.assertTrue(url.endswith("/notes"))
        self.assertIn("9 AM yoga batch", body)

        # Browser saving is asynchronous.
        # A fact should not exist until the worker runs.
        self.assertEqual(len(storage.list_facts()), 0)

        with storage.get_connection() as conn:
            jobs = conn.execute(
                """
                SELECT id, note_id, status
                FROM processing_jobs
                ORDER BY created_at DESC
                """
            ).fetchall()

        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["status"], "queued")

        self.run_queued_jobs()

        facts = storage.list_facts()

        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0]["status"], "active")

        with storage.get_connection() as conn:
            job = conn.execute(
                """
                SELECT status
                FROM processing_jobs
                WHERE id = ?
                """,
                (jobs[0]["id"],),
            ).fetchone()

        self.assertEqual(job["status"], "succeeded")

    def test_approval_through_browser(self):
        self.post("/add", {"text": "mixer warranty"})

        # Extract pending fact through the worker.
        self.run_queued_jobs()

        with storage.get_connection() as conn:
            approval = conn.execute(
                """
                SELECT id
                FROM approvals
                WHERE status = 'pending'
                LIMIT 1
                """
            ).fetchone()

        self.assertIsNotNone(approval)

        self.post(
            "/approve",
            {"approval_id": str(approval["id"])},
        )

        facts = storage.list_facts()

        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0]["status"], "active")

    def test_ask_displays_source(self):
        self.post(
            "/add",
            {
                "text":
                    "I selected the 9 AM yoga batch "
                    "because evening traffic is bad."
            },
        )

        self.run_queued_jobs()

        status, body = self.get("/ask?q=Why+yoga%3F")

        self.assertEqual(status, 200)
        self.assertIn("Source note #", body)
        self.assertIn("9 AM yoga batch", body)

    def test_unrelated_question_unknown(self):
        self.post("/add", {"text": "mixer warranty"})

        self.run_queued_jobs()

        status, body = self.get(
            "/ask?q=Where+is+my+fictional+passport%3F"
        )

        self.assertEqual(status, 200)
        self.assertIn("I don&#x27;t know", body)

    def test_csrf_required(self):
        self.get("/")

        with self.assertRaises(HTTPError) as caught:
            self.post(
                "/add",
                {"text": "yoga"},
                include_csrf=False,
            )

        self.assertEqual(caught.exception.code, 403)
        self.assertEqual(storage.list_notes(), [])

    def test_secret_rejected(self):
        with self.assertRaises(HTTPError) as caught:
            self.post(
                "/add",
                {"text": "My test OTP is 123456"},
            )

        self.assertEqual(caught.exception.code, 400)
        self.assertEqual(storage.list_notes(), [])

    def test_forget_through_browser(self):
        self.post(
            "/add",
            {
                "text":
                    "I selected the 9 AM yoga batch "
                    "because evening traffic is bad."
            },
        )

        self.run_queued_jobs()

        facts = storage.list_facts()
        self.assertEqual(len(facts), 1)

        fact_id = facts[0]["id"]

        self.post(
            "/forget",
            {
                "fact_id": str(fact_id),
                "confirm": "yes",
            },
        )

        self.assertEqual(storage.list_facts(), [])
        self.assertEqual(storage.list_notes(), [])

    def test_html_escaping(self):
        self.post(
            "/add",
            {"text": "<script>alert(1)</script>"},
        )

        status, body = self.get("/notes")

        self.assertEqual(status, 200)
        self.assertNotIn(
            "<script>alert(1)</script>",
            body,
        )
        self.assertIn(
            "&lt;script&gt;",
            body,
        )

    def test_invalid_host_rejected(self):
        request = Request(
            self.base + "/",
            headers={"Host": "evil.example"},
        )

        with self.assertRaises(HTTPError) as caught:
            self.client.open(request)

        self.assertEqual(caught.exception.code, 400)


if __name__ == "__main__":
    unittest.main()
