
"""Phase 5: localhost-only browser interface.

Standard library only. SAMPLE MockProvider.
Not intended for public deployment.
"""
import os
import html
import hmac
import secrets
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode, urlsplit
from . import demo
from .ai import (
    get_provider,
    process_note,
    answer_question,
)
from .gemini import GeminiError
from .jobs import list_jobs, retry_job, init_jobs
from .jobs import create_job, init_jobs
from .queued_notes import add_queued_note
from .note_processing import processing_status, reprocess_note

from .storage import (
    add_note,
    clear_current_db_path,
    init_db,
    set_current_db_path,
    list_audit_log,
    list_facts,
    list_notes,
)
from .pipeline import (
    extract_note,
    pending_facts,
    prepare_schema,
)
from .providers import MockProvider
from .retrieval import ask
from .updates import fact_history, resolve_update
from .forget import (
    forget_fact,
    is_forgotten,
    prepare_forget_schema,
)

HOST = "127.0.0.1"
PORT = 8765
MAX_BODY = 20_000

# Random token generated on each server start.
# This is local-development CSRF protection, not login.
CSRF_TOKEN = secrets.token_urlsafe(32)

CSS = """
:root {
    color-scheme: light;
    font-family: system-ui, -apple-system, sans-serif;
    background: #f5f7fb;
    color: #182235;
}
* { box-sizing: border-box; }
body { margin: 0; }
header {
    background: #14233c;
    color: white;
    padding: 20px max(24px, calc((100% - 1050px)/2));
}
header h1 { margin: 0 0 5px; font-size: 24px; }
header p { margin: 0; opacity: .8; }
nav {
    background: white;
    border-bottom: 1px solid #dde3ee;
    padding: 12px 24px;
    display: flex;
    justify-content: center;
    flex-wrap: wrap;
    gap: 14px;
}
nav a { color: #264a82; text-decoration: none; font-weight: 600; }
main { max-width: 1050px; margin: 26px auto; padding: 0 18px; }
section {
    background: white;
    border: 1px solid #e0e5ef;
    border-radius: 12px;
    padding: 22px;
    margin-bottom: 18px;
}
h2 { margin-top: 0; font-size: 20px; }
h3 { margin-bottom: 6px; }
p { line-height: 1.55; overflow-wrap: anywhere; }
small, .muted { color: #607087; }
textarea, input {
    width: 100%;
    padding: 11px;
    border: 1px solid #bac5d6;
    border-radius: 7px;
    font: inherit;
    margin: 8px 0 12px;
}
textarea { min-height: 95px; resize: vertical; }
button {
    background: #2459b5;
    color: white;
    border: 0;
    border-radius: 7px;
    padding: 10px 16px;
    cursor: pointer;
    font: inherit;
}
button.danger { background: #ad3030; }
button.secondary { background: #475569; }
.inline { display: inline-block; margin: 4px 8px 4px 0; }
.item { border-top: 1px solid #e4e9f1; padding: 15px 0; }
.item:first-of-type { border-top: 0; }
.notice {
    border-left: 4px solid #2459b5;
    background: #edf4ff;
    padding: 12px;
    border-radius: 5px;
    margin-bottom: 18px;
}
.warning {
    background: #fff3e8;
    border-left: 4px solid #d97706;
    padding: 12px;
    margin-bottom: 18px;
}
.answer {
    background: #f0f6ff;
    padding: 16px;
    border-radius: 8px;
    white-space: pre-wrap;
}
code { overflow-wrap: anywhere; }
"""


def esc(value):
    """HTML-escape all database and user-provided text."""
    return html.escape(str(value), quote=True)


def initialize():
    init_db()
    init_jobs()
    prepare_schema()
    prepare_forget_schema()


def hidden_csrf():
    return (
        '<input type="hidden" name="csrf" value="'
        + esc(CSRF_TOKEN)
        + '">'
    )


def form(action, fields, button, danger=False):
    style = ' class="danger"' if danger else ""
    return (
        '<form method="post" action="' + esc(action) + '">'
        + hidden_csrf()
        + fields
        + '<button' + style + '>'
        + esc(button)
        + '</button></form>'
    )


def layout(title, body):
    nav = (
        '<nav>'
        '<a href="/">Dashboard</a>'
        '<a href="/notes">Notes</a>'
        '<a href="/jobs">Jobs</a>'
        '<a href="/facts">Facts</a>'
        '<a href="/approvals">Approvals</a>'
        '<a href="/ask">Ask Memory</a>'
        '<a href="/history">History</a>'
        '<a href="/audit">Audit</a>'
        '</nav>'
    )

    if demo.enabled():
        provider = os.environ.get("MEMORY_PROVIDER", "mock")
        ttl = os.environ.get(
            "MEMORY_DEMO_TTL_HOURS", str(demo.DEFAULT_TTL_HOURS)
        )
        if provider == "gemini":
            guidance = (
                "Interactive demo. Type your own fictional notes; "
                "answers come from a live AI model. Please do not "
                "enter real personal information."
            )
        else:
            guidance = (
                "Interactive demo with offline sample extraction. "
                "Use the example notes below the add form; this "
                "deployment runs without the live AI model, so "
                "free-typed notes are not understood yet."
            )
        banner = (
            '<div class="warning">'
            + esc(
                guidance
                + " Your workspace is tied to a cookie in this "
                "browser and stored on the demo server, separate "
                "from other visitors; it is not saved in your "
                "browser. It holds only fictional sample data and "
                "is kept for about "
                + ttl
                + " hours. "
            )
            + form("/demo/reset", "", "Reset my demo workspace")
            + "</div>"
        )
        header_note = "Interactive demo workspace"
    else:
        banner = (
            '<div class="warning">'
            "Development mode. Use fictional data only. "
            "No login or database encryption is implemented."
            "</div>"
        )
        header_note = "Private local workspace"

    return (
        '<!doctype html><html lang="en"><head>'
        '<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>" + esc(title) + " - Memory Assistant</title>"
        "<style>" + CSS + "</style></head><body>"
        "<header><h1>Personal Memory Assistant</h1>"
        "<p>" + header_note + " · Provider: "
        + esc(os.environ.get("MEMORY_PROVIDER", "mock"))
        + "</p></header>"
        + nav
        + "<main>"
        + banner
        + body
        + "</main></body></html>"
    )


def render_dashboard():
    notes = list_notes()
    facts = list_facts()
    approvals = pending_facts()

    active = sum(
        1 for fact in facts if fact["status"] == "active"
    )

    return (
        '<section><h2>Dashboard</h2>'
        '<p>Saved notes: <strong>' + str(len(notes)) + '</strong></p>'
        '<p>Active facts: <strong>' + str(active) + '</strong></p>'
        '<p>Pending approvals: <strong>'
        + str(len(approvals)) + '</strong></p>'
        '<p class="muted">'
        + esc(
            "Each visitor gets a separate fictional demo workspace."
            if demo.enabled()
            else "All information stays in your local SQLite "
            "database. No Gemini requests yet."
        )
        + "</p>"
        '</section>'
        + render_add_form()
    )


def render_add_form():
    examples = ""
    if demo.enabled():
        provider = os.environ.get("MEMORY_PROVIDER", "mock")
        texts = (
            demo.GEMINI_EXAMPLES
            if provider == "gemini"
            else demo.MOCK_EXAMPLES
        )
        buttons = "".join(
            form(
                "/add",
                '<input type="hidden" name="text" value="'
                + esc(text)
                + '">',
                "Try: " + text,
            )
            for text in texts
        )
        examples = (
            '<p class="muted">Example notes to try:</p>' + buttons
        )
    return (
        '<section><h2>Add a note</h2>'
        + form(
            "/add",
            '<label for="note">Your note</label>'
            '<textarea id="note" name="text" '
            'maxlength="10000" required '
            'placeholder="Use a fictional SAMPLE note"></textarea>',
            "Save note",
        )
        + examples
        + '</section>'
    )


def render_notes():
    result = render_add_form()
    result += '<section><h2>Saved notes</h2>'

    notes = list_notes()

    if not notes:
        result += '<p>No notes available.</p>'

    for note in notes:
        status = processing_status(note["id"])
        result += (
            '<div class="item"><strong>Note #'
            + str(note["id"]) + '</strong>'
            + '<p>' + esc(note["raw_text"]) + '</p>'
            + '<p>Extraction: <strong>' + esc(status["state"]) + '</strong></p>'
            + '<p>' + esc(status.get("last_error_message") or "") + '</p>'
            + (form("/notes/reprocess", '<input type="hidden" name="note_id" value="' + str(note["id"]) + '">', "Reprocess note") if status["state"] in ("done", "failed", "pending") and status.get("status") not in ("queued", "running") else "")
            + '<small>' + esc(note["created_at"]) + '</small>'
            + '</div>'
        )

    return result + '</section>'


def render_facts():
    result = '<section><h2>Facts</h2>'
    result += (
        '<p class="muted">Only active facts are used '
        'for question answering.</p>'
    )

    facts = list_facts()

    if not facts:
        result += '<p>No facts available.</p>'

    for fact in facts:
        fact_id = int(fact["id"])

        result += (
            '<div class="item"><strong>Fact #'
            + str(fact_id) + '</strong>'
            + '<p>' + esc(fact["statement"]) + '</p>'
            + '<p>Status: <strong>'
            + esc(fact["status"]) + '</strong></p>'
        )

        result += form(
            "/forget",
            '<input type="hidden" name="fact_id" value="'
            + str(fact_id) + '">'
            '<label><input type="checkbox" name="confirm" '
            'value="yes" required '
            'style="width:auto"> '
            'Delete this fact and its source note</label>',
            "Forget fact",
            danger=True,
        )

        result += '</div>'

    return result + '</section>'


def render_approvals():
    result = '<section><h2>Pending approvals</h2>'
    approvals = pending_facts()

    if not approvals:
        result += '<p>No pending approvals.</p>'

    for approval in approvals:
        approval_id = int(approval["approval_id"])

        hidden_id = (
            '<input type="hidden" name="approval_id" value="'
            + str(approval_id) + '">'
        )

        result += (
            '<div class="item"><strong>Approval #'
            + str(approval_id) + '</strong>'
            + '<p>Old: ' + esc('; '.join(approval['old_statements']) or 'No active fact') + '</p>'
            + '<p>Proposed: ' + esc(approval["statement"]) + '</p>'
            + '<small>Reason: '
            + esc(approval["reason"]) + '</small>'
        )

        result += form(
            "/approve",
            hidden_id,
            "Approve",
        )

        result += form(
            "/reject",
            hidden_id,
            "Reject",
            danger=True,
        )

        result += form(
            "/edit",
            hidden_id
            + '<label>Corrected statement</label>'
            + '<textarea name="statement" required '
            + 'maxlength="10000"></textarea>',
            "Edit and approve",
        )

        result += '</div>'

    return result + '</section>'


def render_ask(question=""):
    result = (
        '<section><h2>Ask your memory</h2>'
        '<form method="get" action="/ask">'
        '<label for="question">Question</label>'
        '<input id="question" name="q" required '
        'maxlength="1000" value="' + esc(question) + '">'
        '<button>Ask</button></form></section>'
    )

    if not question:
        return result

    try:
        response = answer_question(question)
    except (GeminiError, ValueError) as error:
        return (
            result
            + '<section><h2>AI request failed</h2><p>'
            + esc(error)
            + '</p></section>'
        )

    result += (
        '<section><h2>Memory answer</h2>'
        '<div class="answer">'
        + esc(response["answer"])
        + '</div><p class="muted">Validation: '
        + esc(response["validation"])
        + '</p>'
    )

    for source in response["sources"]:
        result += (
            '<div class="item"><strong>Source note #'
            + str(source["note_id"]) + '</strong>'
            + '<p>' + esc(source["text"]) + '</p>'
            + '<small>' + esc(source["date"]) + '</small>'
            + '</div>'
        )

    context = response["context"]

    result += (
        '<p class="muted">Context: '
        + str(context["characters"])
        + '/' + str(context["budget"])
        + ' characters</p></section>'
    )

    return result


def render_history(subject=""):
    result = (
        '<section><h2>Fact history</h2>'
        '<form method="get" action="/history">'
        '<label>Subject key</label>'
        '<input name="subject" maxlength="200" '
        'value="' + esc(subject) + '" '
        'placeholder="e.g. yoga_batch" required>'
        '<button>Show history</button></form>'
    )

    if subject:
        history = fact_history(subject)

        if not history:
            result += '<p>No history found.</p>'

        for fact in history:
            result += (
                '<div class="item"><strong>Fact #'
                + str(fact["id"]) + '</strong>'
                + '<p>' + esc(fact["statement"]) + '</p>'
                + '<p>Status: ' + esc(fact["status"]) + '</p>'
                + '<p>Superseded by: '
                + esc(fact["superseded_by"]) + '</p>'
                + '<small>Source note #'
                + str(fact["note_id"]) + '</small>'
                + '</div>'
            )

    return result + '</section>'


def render_audit():
    result = '<section><h2>Audit log</h2>'
    events = list_audit_log()

    if not events:
        result += '<p>No audit entries.</p>'

    for event in events:
        result += (
            '<div class="item">'
            + esc(event["action"])
            + ' · ' + esc(event["entity_type"])
            + ' #' + str(event["entity_id"])
            + '</div>'
        )

    return result + '</section>'



def render_jobs():
    """Show recent jobs and permitted manual retry actions."""
    jobs = list_jobs(limit=100)

    counts = {
        "queued": 0,
        "running": 0,
        "succeeded": 0,
        "failed": 0,
        "cancelled": 0,
    }

    for job in jobs:
        status = job["status"]
        if status in counts:
            counts[status] += 1

    result = (
        '<section><h2>Processing Jobs</h2>'
        '<p class="muted">Showing the 100 most recent jobs. '
        'Refresh to see updates. Retries are processed by '
        'the background worker.</p>'
        '<p>'
        + " · ".join(
            esc(label.title()) + ": <strong>"
            + str(counts[label]) + "</strong>"
            for label in counts
        )
        + '</p></section>'
        '<section><h2>Recent jobs</h2>'
    )

    if not jobs:
        result += '<p>No processing jobs yet.</p>'

    for job in jobs:
        status = str(job["status"])
        attempts = int(job["attempts"])
        max_attempts = int(job["max_attempts"])

        result += (
            '<div class="item">'
            '<h3>Note #' + esc(job["note_id"]) + '</h3>'
            '<p>Status: <strong>' + esc(status.upper())
            + '</strong></p>'
            '<p>Attempts: ' + str(attempts)
            + ' / ' + str(max_attempts) + '</p>'
            '<p>Checkpoint: '
            + esc(job["checkpoint"] or "-") + '</p>'
            '<p>Created: '
            + esc(job["created_at"] or "-") + '</p>'
            '<p>Available at: '
            + esc(job["available_at"] or "-") + '</p>'
            '<p>Completed: '
            + esc(job["completed_at"] or "-") + '</p>'
            '<p>Error code: '
            + esc(job["last_error_code"] or "-") + '</p>'
            '<small>Job ID: ' + esc(job["id"]) + '</small>'
        )

        # Do not display raw exception messages. They could
        # contain sensitive provider or application details.
        if status == "failed" and attempts < max_attempts:
            result += form(
                "/jobs/retry",
                '<input type="hidden" name="job_id" value="'
                + esc(job["id"]) + '">',
                "Retry job",
            )
        elif status == "failed":
            result += (
                '<p class="muted">Retry limit reached. '
                'No further attempts are available.</p>'
            )

        result += '</div>'

    return result + '</section>'


class MemoryHandler(BaseHTTPRequestHandler):
    """Minimal localhost HTTP handler."""

    def log_message(self, format, *args):
        # Avoid logging full URLs containing questions.
        pass

    def _valid_host(self):
        if demo.enabled():
            # Public demo: the deployed hostname is not known in
            # advance. POST origins are still checked against Host.
            return True
        host = self.headers.get("Host", "")
        return host == f"{HOST}:{self.server.server_port}"

    def _send_html(self, status, body, set_cookie=False):
        content = body.encode("utf-8")

        self.send_response(status)
        self.send_header(
            "Content-Type", "text/html; charset=utf-8"
        )
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'none'; style-src 'unsafe-inline'; "
            "form-action 'self'; base-uri 'none'; "
            "frame-ancestors 'none'",
        )

        if set_cookie:
            self.send_header(
                "Set-Cookie",
                "memory_csrf=" + CSRF_TOKEN
                + "; Path=/; HttpOnly; SameSite=Strict",
            )

        self._send_pending_session_cookie()

        self.end_headers()
        self.wfile.write(content)

    def _send_pending_session_cookie(self):
        pending = getattr(self, "_pending_session_cookie", None)
        if not pending:
            return
        cookie = (
            demo.SESSION_COOKIE + "=" + pending
            + "; Path=/; HttpOnly; SameSite=Lax"
        )
        if self.headers.get("X-Forwarded-Proto") == "https":
            cookie += "; Secure"
        self.send_header("Set-Cookie", cookie)
        self._pending_session_cookie = None

    def _error(self, status, message):
        self._send_html(
            status,
            layout("Error", (
                '<section><h2>Request error</h2><p>'
                + esc(message)
                + '</p><a href="/">Return home</a></section>'
            )),
        )

    def _redirect(self, location):
        self.send_response(303)
        self.send_header("Location", location)
        self.send_header("Cache-Control", "no-store")
        self._send_pending_session_cookie()
        self.end_headers()

    def _begin_demo_session(self):
        # Resolve or create the visitor session and bind its
        # database for this request thread. Returns the session id
        # in demo mode, None otherwise.
        if not demo.enabled():
            return None
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
            value = cookie[demo.SESSION_COOKIE].value
        except (KeyError, ValueError):
            value = ""
        session_id = demo.verify_session(value)
        if session_id is None:
            session_id, signed = demo.new_session()
            self._pending_session_cookie = signed
        db_path = demo.ensure_workspace(session_id)
        set_current_db_path(db_path)
        return session_id

    def _end_demo_session(self):
        if demo.enabled():
            clear_current_db_path()

    def do_GET(self):
        if not self._valid_host():
            self._error(400, "Invalid Host header.")
            return

        session_id = self._begin_demo_session()
        try:
            self._do_get(session_id)
        finally:
            self._end_demo_session()

    def _do_get(self, session_id):
        parsed = urlsplit(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        if path == "/":
            title, body = "Dashboard", render_dashboard()
        elif path == "/notes":
            title, body = "Notes", render_notes()
        elif path == "/jobs":
            title, body = "Processing Jobs", render_jobs()
        elif path == "/facts":
            title, body = "Facts", render_facts()
        elif path == "/approvals":
            title, body = "Approvals", render_approvals()
        elif path == "/ask":
            question = query.get("q", [""])[0][:1000]
            if (
                question
                and session_id
                and not demo.check_rate_limit(session_id, "ask")
            ):
                self._error(
                    429,
                    "Hourly question limit reached for this demo "
                    "workspace. It resets within an hour.",
                )
                return
            title = "Ask Memory"
            body = render_ask(question)
        elif path == "/history":
            title = "History"
            body = render_history(
                query.get("subject", [""])[0][:200]
            )
        elif path == "/audit":
            title, body = "Audit", render_audit()
        else:
            self._error(404, "Page not found.")
            return

        self._send_html(
            200,
            layout(title, body),
            set_cookie=True,
        )

    def _read_form(self):
        if self.headers.get("Content-Type", "").split(";")[0].strip() != (
            "application/x-www-form-urlencoded"
        ):
            raise ValueError("Unsupported form content type.")

        length = int(self.headers.get("Content-Length", "0"))

        if length <= 0 or length > MAX_BODY:
            raise ValueError("Invalid request size.")

        body = self.rfile.read(length).decode("utf-8")
        return parse_qs(body, keep_blank_values=True)

    def _check_csrf(self, fields):
        cookie = SimpleCookie()

        try:
            cookie.load(self.headers.get("Cookie", ""))
            supplied_cookie = cookie["memory_csrf"].value
        except (KeyError, ValueError):
            return False

        supplied_form = fields.get("csrf", [""])[0]

        return (
            hmac.compare_digest(supplied_cookie, CSRF_TOKEN)
            and hmac.compare_digest(supplied_form, CSRF_TOKEN)
        )

    def do_POST(self):
        if not self._valid_host():
            self._error(400, "Invalid Host header.")
            return

        origin = self.headers.get("Origin")

        if origin is not None:
            if demo.enabled():
                origin_host = urlsplit(origin).netloc
                if origin_host != self.headers.get("Host", ""):
                    self._error(403, "Invalid request origin.")
                    return
            else:
                expected_origin = (
                    f"http://{HOST}:{self.server.server_port}"
                )
                if origin != expected_origin:
                    self._error(403, "Invalid request origin.")
                    return

        session_id = self._begin_demo_session()
        try:
            self._do_post_actions(session_id)
        finally:
            self._end_demo_session()

    def _do_post_actions(self, session_id):
        path = urlsplit(self.path).path
        if path not in {
            "/add", "/approve", "/reject", "/edit", "/forget",
            "/jobs/retry", "/notes/reprocess", "/demo/reset",
        }:
            self._error(404, "Unknown action.")
            return
        try:
            fields = self._read_form()

            if not self._check_csrf(fields):
                self._error(403, "Invalid CSRF token.")
                return

            if path == "/notes/reprocess":
                reprocess_note(int(fields.get("note_id", ["0"])[0]))
                destination = "/notes"

            elif path == "/jobs/retry":
                job_id = fields.get("job_id", [""])[0]

                if not job_id or len(job_id) > 100:
                    raise ValueError("Invalid job ID.")

                if not retry_job(job_id):
                    raise ValueError(
                        "Job cannot be retried. It may be "
                        "completed, running, or out of attempts."
                    )

                destination = "/jobs"

            elif path == "/demo/reset":
                if session_id:
                    demo.reset_workspace(session_id)
                destination = "/"

            elif path == "/add":
                value = fields.get("text", [""])[0].strip()

                if not value or len(value) > 10000:
                    raise ValueError("Invalid note length.")

                if session_id and not demo.check_rate_limit(
                    session_id, "add"
                ):
                    raise ValueError(
                        "Hourly note limit reached for this demo "
                        "workspace. It resets within an hour."
                    )

                if is_forgotten(value):
                    raise ValueError(
                        "This exact note was previously forgotten."
                    )

                note_id, job_id = add_queued_note(value)

                if session_id:
                    demo.ensure_worker(session_id)

                print(
                    f"Note #{note_id} queued as job {job_id}",
                    flush=True,
                )

                destination = "/notes"

            elif path in {"/approve", "/reject", "/edit"}:
                approval_id = int(
                    fields.get("approval_id", ["0"])[0]
                )

                if path == "/reject":
                    resolve_update(approval_id, "rejected")
                elif path == "/edit":
                    statement = fields.get("statement", [""])[0]

                    if len(statement) > 10000:
                        raise ValueError("Edited statement too long.")

                    resolve_update(
                        approval_id,
                        "approved",
                        edited_statement=statement,
                    )
                else:
                    resolve_update(approval_id, "approved")

                destination = "/approvals"

            else:
                if fields.get("confirm", [""])[0] != "yes":
                    raise ValueError("Confirm forgetting first.")

                fact_id = int(
                    fields.get("fact_id", ["0"])[0]
                )
                forget_fact(fact_id)
                destination = "/facts"

            self._redirect(destination)

        except (ValueError, UnicodeDecodeError) as error:
            self._error(400, str(error))


def create_server(host=None, port=None):
    """Create the HTTP server.

    Local mode binds 127.0.0.1 only. Demo mode (MEMORY_DEMO=1) may
    bind another interface through MEMORY_HOST so a hosting provider
    can expose it, and reads the port from the PORT environment
    variable when set.
    """
    if host is None:
        host = os.environ.get("MEMORY_HOST", HOST)
    if port is None:
        port = int(os.environ.get("PORT", PORT))

    if host != HOST and not demo.enabled():
        raise ValueError(
            "Only 127.0.0.1 is allowed outside demo mode."
        )

    if demo.enabled():
        demo.sweep_expired()
    else:
        initialize()

    return ThreadingHTTPServer(
        (host, port),
        MemoryHandler,
    )


def serve(host=None, port=None):
    server = create_server(host=host, port=port)

    bound_host, bound_port = server.server_address[:2]
    print(
        f"Personal Memory Assistant running at "
        f"http://{bound_host}:{bound_port}",
        flush=True,
    )
    if demo.enabled():
        demo.start_sweeper()
        print(
            "Demo mode: per-visitor isolated fictional workspaces.",
            flush=True,
        )
    else:
        print("SAMPLE mode. Press Ctrl+C to stop.", flush=True)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
    finally:
        server.server_close()
