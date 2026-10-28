"""Hosted demo mode tests: per-visitor isolation, reset, rate limits,
retention sweep, and session-cookie signing. All offline (mock provider).
"""

import http.cookiejar
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlencode
from urllib.request import (
    HTTPCookieProcessor,
    Request,
    build_opener,
)

from memory_assistant import demo, storage
from memory_assistant.web import create_server


def make_opener(jar):
    return build_opener(HTTPCookieProcessor(jar))


class DemoModeTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.env_patch = patch.dict(
            "os.environ",
            {
                "MEMORY_PROVIDER": "mock",
                "MEMORY_DEMO": "1",
                "MEMORY_DEMO_TTL_HOURS": "24",
            },
        )
        cls.env_patch.start()

        cls.temp = tempfile.TemporaryDirectory()
        cls.demo_dir = Path(cls.temp.name) / "demo_data"
        cls.dir_patch = patch.dict(
            "os.environ", {"MEMORY_DEMO_DIR": str(cls.demo_dir)}
        )
        cls.dir_patch.start()

        cls.default_db = Path(cls.temp.name) / "default.db"
        cls.db_patch = patch.object(
            storage, "DB_PATH", cls.default_db
        )
        cls.db_patch.start()

        cls.server = create_server(port=0)
        cls.port = cls.server.server_port
        cls.base = f"http://127.0.0.1:{cls.port}"
        cls.thread = threading.Thread(
            target=cls.server.serve_forever, daemon=True
        )
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)
        cls.db_patch.stop()
        cls.dir_patch.stop()
        cls.env_patch.stop()
        cls.temp.cleanup()

    def setUp(self):
        self.jar = http.cookiejar.CookieJar()
        self.opener = make_opener(self.jar)

    def get(self, path):
        return self.opener.open(self.base + path, timeout=10).read().decode()

    def post(self, path, fields):
        data = urlencode(fields).encode()
        request = Request(self.base + path, data=data)
        return self.opener.open(request, timeout=10)

    def csrf(self):
        page = self.get("/notes")
        marker = 'name="csrf" value="'
        return page.split(marker)[1].split('"')[0]

    def session_cookie(self):
        for cookie in self.jar:
            if cookie.name == demo.SESSION_COOKIE:
                return cookie.value
        return None

    def test_session_cookie_assigned_and_seeded(self):
        page = self.get("/")
        self.assertIn("Interactive demo workspace", page)
        self.assertIn("Reset my demo workspace", page)
        self.assertIsNotNone(self.session_cookie())
        # Seeded fictional memories are visible immediately.
        self.assertIn("Saved notes: <strong>2</strong>", page)
        self.assertIn("Active facts: <strong>2</strong>", page)

    def test_default_database_not_created(self):
        self.get("/")
        self.assertFalse(self.default_db.exists())

    def test_tampered_cookie_gets_fresh_session(self):
        self.get("/")
        first = self.session_cookie()
        self.assertIsNotNone(first)
        self.jar.clear()
        request = Request(
            self.base + "/",
            headers={"Cookie": demo.SESSION_COOKIE + "=forged.bad"},
        )
        self.opener.open(request, timeout=10).read()
        second = self.session_cookie()
        self.assertIsNotNone(second)
        self.assertNotEqual(first, second)

    def test_visitors_are_isolated(self):
        token = self.csrf()
        marker = "My zebrawood shelf arrived on Tuesday."
        self.post("/add", {"csrf": token, "text": marker}).read()

        other_jar = http.cookiejar.CookieJar()
        other = make_opener(other_jar)
        other_page = other.open(
            self.base + "/notes", timeout=10
        ).read().decode()
        self.assertNotIn("zebrawood", other_page)
        self.assertIn("zebrawood", self.get("/notes"))

        token = self.csrf()
        self.post(
            "/add",
            {"csrf": token, "text": "My yoga batch moved to 7 AM."},
        ).read()
        time.sleep(6)
        approvals = self.get("/approvals")
        self.assertIn("7 AM", approvals)
        other_approvals = other.open(
            self.base + "/approvals", timeout=10
        ).read().decode()
        self.assertIn("No pending approvals", other_approvals)

    def test_reset_only_affects_own_workspace(self):
        token = self.csrf()
        marker = "My zebrawood shelf arrived on Tuesday."
        self.post("/add", {"csrf": token, "text": marker}).read()
        self.assertIn("zebrawood", self.get("/notes"))

        other_jar = http.cookiejar.CookieJar()
        other = make_opener(other_jar)
        other.open(self.base + "/", timeout=10).read()

        self.post("/demo/reset", {"csrf": token}).read()
        page = self.get("/notes")
        self.assertNotIn("zebrawood", page)
        # Seed data is back after reset.
        self.assertIn("9 AM yoga", page)

        other_notes = other.open(
            self.base + "/notes", timeout=10
        ).read().decode()
        self.assertIn("9 AM yoga", other_notes)

    def test_add_rate_limit(self):
        token = self.csrf()
        with patch.object(demo, "ADD_LIMIT_PER_HOUR", 3):
            for i in range(3):
                self.post(
                    "/add",
                    {"csrf": token, "text": f"Library book note {i}"},
                ).read()
            with self.assertRaises(Exception) as ctx:
                self.post(
                    "/add",
                    {"csrf": token, "text": "Library book overflow"},
                )
            self.assertIn("400", str(ctx.exception))

    def test_ask_rate_limit(self):
        self.get("/")
        with patch.object(demo, "ASK_LIMIT_PER_HOUR", 2):
            self.get("/ask?q=yoga")
            self.get("/ask?q=yoga")
            page = None
            try:
                self.get("/ask?q=yoga")
            except Exception as exc:
                page = str(exc)
            self.assertIn("429", page)

    def test_retention_sweep_removes_expired(self):
        self.get("/")
        stale = self.demo_dir / "stale-session"
        stale.mkdir(parents=True)
        (stale / "memory.db").write_bytes(b"")
        old = time.time() - 25 * 3600
        os.utime(stale, (old, old))
        removed = demo.sweep_expired()
        self.assertGreaterEqual(removed, 1)
        self.assertFalse(stale.exists())
        # The current visitor's workspace survives.
        self.assertTrue(self.get("/notes").find("9 AM yoga") > -1)

    def test_reset_right_after_add_is_fast(self):
        token = self.csrf()
        self.post(
            "/add",
            {"csrf": token, "text": "My yoga batch moved to 7 AM."},
        ).read()
        start = time.monotonic()
        self.post("/demo/reset", {"csrf": token}).read()
        elapsed = time.monotonic() - start
        self.assertLess(elapsed, 12)
        self.assertIn("9 AM yoga", self.get("/notes"))

    def test_sweep_keeps_workspace_with_active_worker(self):
        token = self.csrf()
        self.post(
            "/add",
            {"csrf": token, "text": "My yoga batch moved to 7 AM."},
        ).read()
        sid = self.session_cookie().split(".")[0]
        # Force the workspace to look expired; the worker is running.
        target = self.demo_dir / sid
        old = time.time() - 25 * 3600
        os.utime(target, (old, old))
        demo.sweep_expired()
        self.assertTrue(target.exists())

    def test_concurrent_visitors_stay_isolated(self):
        jars = [http.cookiejar.CookieJar() for _ in range(2)]
        openers = [make_opener(jar) for jar in jars]
        markers = ["zebrawood-one", "zebrawood-two"]
        errors = []

        def work(index):
            try:
                page = openers[index].open(
                    self.base + "/notes", timeout=10
                ).read().decode()
                token = page.split('name="csrf" value="')[1].split('"')[0]
                data = urlencode(
                    {"csrf": token, "text": markers[index]}
                ).encode()
                openers[index].open(
                    Request(self.base + "/add", data=data), timeout=10
                ).read()
            except Exception as exc:  # pragma: no cover
                errors.append(exc)

        threads = [
            threading.Thread(target=work, args=(i,)) for i in range(2)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=20)
        self.assertEqual(errors, [])

        for index, opener in enumerate(openers):
            page = opener.open(
                self.base + "/notes", timeout=10
            ).read().decode()
            self.assertIn(markers[index], page)
            self.assertNotIn(markers[1 - index], page)

    def test_demo_reset_path_requires_post(self):
        try:
            self.get("/demo/reset")
            self.fail("GET /demo/reset should not exist")
        except Exception as exc:
            self.assertIn("404", str(exc))

    def test_arbitrary_host_header_accepted_in_demo(self):
        request = Request(
            self.base + "/",
            headers={"Host": "memory-demo.onrender.com"},
        )
        body = self.opener.open(request, timeout=10).read().decode()
        self.assertIn("Interactive demo workspace", body)


if __name__ == "__main__":
    unittest.main()
