"""Hosted demo mode: per-visitor isolated fictional workspaces.

Enable with MEMORY_DEMO=1. Every visitor receives a signed session
cookie tied to their own SQLite workspace under MEMORY_DEMO_DIR
(default: ./demo_data). Workspaces are seeded with fictional sample
memories, expire after MEMORY_DEMO_TTL_HOURS (default 24), and can be
reset by their owner without touching any other visitor's data.

Demo workspaces never contain real personal notes: they start from the
same canned fictional examples used by the offline test suite.
"""

import hashlib
import hmac
import os
import secrets
import shutil
import threading
import time
from collections import deque
from pathlib import Path

from . import storage
from .jobs import init_jobs
from .pipeline import prepare_schema
from .forget import prepare_forget_schema

SESSION_COOKIE = "memory_demo_session"
DEFAULT_TTL_HOURS = 24
MAX_SESSIONS = 200
ADD_LIMIT_PER_HOUR = 15
ASK_LIMIT_PER_HOUR = 60

# Random per server start. A restart invalidates session cookies;
# ephemeral hosting loses the workspace files then anyway.
_SECRET = secrets.token_urlsafe(32)

_sessions_lock = threading.Lock()
_workers_lock = threading.Lock()
_workers = {}
_worker_stops = {}
_rate_lock = threading.Lock()
_rate_buckets = {}

SEED_NOTES = [
    "I selected the 9 AM yoga batch because evening traffic is bad.",
    "My sample library book is due on November 3.",
]

MOCK_EXAMPLES = [
    "My yoga batch moved to 7 AM.",
    "My fictional mixer warranty receipt is in the August 12 email.",
]

GEMINI_EXAMPLES = [
    "My dentist appointment is on Friday at 4 PM.",
    "I moved my dentist appointment to Monday at 10 AM.",
]


def enabled():
    return os.environ.get("MEMORY_DEMO", "").strip() == "1"


def demo_dir():
    return Path(
        os.environ.get(
            "MEMORY_DEMO_DIR",
            str(storage.BASE_DIR / "demo_data"),
        )
    )


def ttl_seconds():
    hours = int(
        os.environ.get("MEMORY_DEMO_TTL_HOURS", DEFAULT_TTL_HOURS)
    )
    return hours * 3600


def _sign(session_id):
    return hmac.new(
        _SECRET.encode(), session_id.encode(), hashlib.sha256
    ).hexdigest()


def new_session():
    session_id = secrets.token_urlsafe(16)
    return session_id, session_id + "." + _sign(session_id)


def verify_session(cookie_value):
    """Return the session id for a valid signed cookie, else None."""
    if not cookie_value or "." not in cookie_value:
        return None
    session_id, signature = cookie_value.rsplit(".", 1)
    if not session_id or not signature:
        return None
    if hmac.compare_digest(signature, _sign(session_id)):
        return session_id
    return None


def session_db_path(session_id):
    return demo_dir() / session_id / "memory.db"


def _seed_workspace():
    """Insert fictional sample notes and process them synchronously.

    Goes through the normal queued-job pipeline with the offline
    MockProvider, so seeding works without any API key, never sends
    content anywhere, and leaves proper processing checkpoints.
    """
    from .providers import MockProvider
    from .queued_notes import add_queued_note
    from .worker import process_pending_jobs

    for text in SEED_NOTES:
        try:
            add_queued_note(text)
        except ValueError:
            pass
    try:
        process_pending_jobs(provider=MockProvider(), limit=10)
    except Exception:
        # Seeding is best-effort; the visitor can still add notes.
        pass


def ensure_workspace(session_id):
    """Create and seed the visitor's workspace if needed."""
    db_path = session_db_path(session_id)
    if db_path.is_file():
        try:
            os.utime(db_path.parent, None)
        except OSError:
            pass
        return db_path

    with _sessions_lock:
        if db_path.is_file():
            return db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        storage.set_current_db_path(db_path)
        try:
            storage.init_db()
            init_jobs()
            prepare_schema()
            prepare_forget_schema()
            _seed_workspace()
        finally:
            storage.clear_current_db_path()
    return db_path


def reset_workspace(session_id):
    """Delete only this visitor's workspace; it re-seeds on next use."""
    with _workers_lock:
        worker = _workers.pop(session_id, None)
        stop = _worker_stops.pop(session_id, None)
    if stop is not None:
        stop.set()
    if worker is not None and worker.is_alive():
        # Let an in-flight extraction finish before deleting its DB.
        worker.join(timeout=15)
    with _sessions_lock:
        shutil.rmtree(
            session_db_path(session_id).parent, ignore_errors=True
        )
    with _rate_lock:
        _rate_buckets.pop(session_id, None)
    return ensure_workspace(session_id)


DEFAULT_GLOBAL_GEMINI_LIMIT = 200


def global_gemini_limit():
    """Shared Gemini call budget across all demo visitors."""
    return int(
        os.environ.get(
            "MEMORY_GEMINI_GLOBAL_CAP",
            DEFAULT_GLOBAL_GEMINI_LIMIT,
        )
    )


def _global_usage_path():
    return demo_dir() / "global_gemini_usage.txt"


def _read_global_usage(path):
    """Counter value, or None when the file is unreadable/corrupt.

    A missing file means zero calls: the counter lives on ephemeral
    demo storage, so a cold start or redeploy resets the budget.
    Anything else wrong with the file fails closed (treated as
    exhausted) rather than resetting the budget.
    """
    try:
        text = path.read_text().strip()
    except FileNotFoundError:
        return 0
    except OSError:
        return None
    try:
        value = int(text)
    except ValueError:
        return None
    if value < 0:
        return None
    return value


def gemini_calls_used():
    """Best-effort counter read for display/tests; corrupt reads as full."""
    used = _read_global_usage(_global_usage_path())
    if used is None:
        return global_gemini_limit()
    return used


def try_reserve_gemini_call():
    """Atomically reserve one shared Gemini call; False when exhausted.

    The counter increments under one lock BEFORE the request is sent,
    so concurrent worker/request threads cannot both pass the check,
    and failed requests and retries count against the budget too. The
    counter never exceeds the cap. Fails closed when the counter file
    cannot be read or written.
    """
    with _rate_lock:
        path = _global_usage_path()
        used = _read_global_usage(path)
        if used is None:
            return False
        limit = global_gemini_limit()
        if used >= limit:
            return False
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(str(min(used + 1, limit)))
        except OSError:
            return False
        return True


def check_rate_limit(session_id, kind):
    """True if the action is allowed; False when over the hourly cap."""
    limits = {
        "add": ADD_LIMIT_PER_HOUR,
        "ask": ASK_LIMIT_PER_HOUR,
    }
    limit = limits[kind]
    now = time.monotonic()
    with _rate_lock:
        buckets = _rate_buckets.setdefault(
            session_id, {"add": deque(), "ask": deque()}
        )
        queue = buckets[kind]
        while queue and now - queue[0] > 3600:
            queue.popleft()
        if len(queue) >= limit:
            return False
        queue.append(now)
        return True


def ensure_worker(session_id):
    """Start a per-session extraction worker thread if none runs."""
    with _workers_lock:
        existing = _workers.get(session_id)
        if existing is not None and existing.is_alive():
            return
        stop = threading.Event()
        thread = threading.Thread(
            target=_worker_loop,
            args=(session_id, stop),
            daemon=True,
        )
        _workers[session_id] = thread
        _worker_stops[session_id] = stop
        thread.start()


def _worker_loop(session_id, stop):
    from .worker import process_pending_jobs

    db_path = session_db_path(session_id)
    storage.set_current_db_path(db_path)
    try:
        idle_rounds = 0
        while idle_rounds < 5 and not stop.is_set():
            if not db_path.parent.is_dir():
                break
            processed = process_pending_jobs(limit=20)
            if processed:
                idle_rounds = 0
            else:
                idle_rounds += 1
                stop.wait(2)
    except Exception:
        pass
    finally:
        storage.clear_current_db_path()
        with _workers_lock:
            _workers.pop(session_id, None)
            _worker_stops.pop(session_id, None)


def _active_session_ids():
    with _workers_lock:
        return {
            sid
            for sid, thread in _workers.items()
            if thread.is_alive()
        }


def _prune_rate_buckets(keep):
    with _rate_lock:
        for sid in list(_rate_buckets):
            if sid not in keep:
                _rate_buckets.pop(sid, None)


def sweep_expired():
    """Remove expired workspaces and cap the total session count.

    A workspace with a running extraction worker is never removed.
    """
    root = demo_dir()
    if not root.is_dir():
        return 0

    active = _active_session_ids()
    cutoff = time.time() - ttl_seconds()
    removed = 0
    candidates = []
    for child in root.iterdir():
        if not child.is_dir():
            continue
        if child.name in active:
            candidates.append((time.time(), child))
            continue
        try:
            mtime = child.stat().st_mtime
        except OSError:
            continue
        if mtime < cutoff:
            shutil.rmtree(child, ignore_errors=True)
            removed += 1
        else:
            candidates.append((mtime, child))

    if len(candidates) > MAX_SESSIONS:
        candidates.sort()
        excess = len(candidates) - MAX_SESSIONS
        for _, child in candidates:
            if excess <= 0:
                break
            if child.name in active:
                continue
            shutil.rmtree(child, ignore_errors=True)
            removed += 1
            excess -= 1

    surviving = {child.name for child in root.iterdir() if child.is_dir()}
    _prune_rate_buckets(surviving)
    return removed


def start_sweeper():
    """Hourly background retention sweep (daemon thread)."""
    def loop():
        while True:
            time.sleep(3600)
            try:
                sweep_expired()
            except Exception:
                pass

    thread = threading.Thread(target=loop, daemon=True)
    thread.start()
    return thread
