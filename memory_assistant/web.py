
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
from .ai import (
    get_provider,
    process_note,
    answer_question,
)
from .gemini import GeminiError
from .storage import (
    add_note,
    init_db,
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
        '<a href="/facts">Facts</a>'
        '<a href="/approvals">Approvals</a>'
        '<a href="/ask">Ask Memory</a>'
        '<a href="/history">History</a>'
        '<a href="/audit">Audit</a>'
        '</nav>'
    )
    return (
        '<!doctype html><html lang="en"><head>'
        '<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>' + esc(title) + ' — Memory Assistant</title>'
        '<style>' + CSS + '</style></head><body>'
        '<header><h1>Personal Memory Assistant</h1>'
        '<p>Private local workspace · Provider: '
        + esc(os.environ.get("MEMORY_PROVIDER", "mock"))
        + '</p></header>'
        + nav
        + '<main>'
        + '<div class="warning">'
        'Development mode. Use fictional data only. '
        'No login or database encryption is implemented.'
        '</div>'
        + body
        + '</main></body></html>'
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
        '<p class="muted">All information stays in your '
        'local SQLite database. No Gemini requests yet.</p>'
        '</section>'
        + render_add_form()
    )


def render_add_form():
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
        + '</section>'
    )


def render_notes():
    result = render_add_form()
    result += '<section><h2>Saved notes</h2>'

    notes = list_notes()

    if not notes:
        result += '<p>No notes available.</p>'

    for note in notes:
        result += (
            '<div class="item"><strong>Note #'
            + str(note["id"]) + '</strong>'
            + '<p>' + esc(note["raw_text"]) + '</p>'
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
            + '<p>' + esc(approval["statement"]) + '</p>'
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
        '<section><h2>MEMORy answer</h2>'
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


class MemoryHandler(BaseHTTPRequestHandler):
    """Minimal localhost HTTP handler."""

    def log_message(self, format, *args):
        # Avoid logging full URLs containing questions.
        pass

    def _valid_host(self):
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

        self.end_headers()
        self.wfile.write(content)

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
        self.end_headers()

    def do_GET(self):
        if not self._valid_host():
            self._error(400, "Invalid Host header.")
            return

        parsed = urlsplit(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        if path == "/":
            title, body = "Dashboard", render_dashboard()
        elif path == "/notes":
            title, body = "Notes", render_notes()
        elif path == "/facts":
            title, body = "Facts", render_facts()
        elif path == "/approvals":
            title, body = "Approvals", render_approvals()
        elif path == "/ask":
            title = "Ask Memory"
            body = render_ask(query.get("q", [""])[0][:1000])
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
        expected_origin = f"http://{HOST}:{self.server.server_port}"

        if origin is not None and origin != expected_origin:
            self._error(403, "Invalid request origin.")
            return
        path = urlsplit(self.path).path
        if path not in {
            "/add", "/approve", "/reject", "/edit", "/forget"
        }:
            self._error(404, "Unknown action.")
            return
        try:
            fields = self._read_form()

            if not self._check_csrf(fields):
                self._error(403, "Invalid CSRF token.")
                return

            if path == "/add":
                value = fields.get("text", [""])[0].strip()

                if not value or len(value) > 10000:
                    raise ValueError("Invalid note length.")

                if is_forgotten(value):
                    raise ValueError(
                        "This exact note was previously forgotten."
                    )

                note_id = add_note(value)

                try:
                    process_note(note_id)
                except (GeminiError, ValueError) as error:
                    # Note remains saved for a later retry.
                    # No facts are activated when extraction fails.
                    print(
                        f"Extraction for note #{note_id} failed: {error}",
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


def create_server(host=HOST, port=PORT):
    """Create the local development server."""
    if host != HOST:
        raise ValueError("Only 127.0.0.1 is allowed.")

    initialize()

    return ThreadingHTTPServer(
        (host, port),
        MemoryHandler,
    )


def serve(port=PORT):
    server = create_server(port=port)

    print(
        f"Personal Memory Assistant running at "
        f"http://{HOST}:{server.server_port}",
        flush=True,
    )
    print("SAMPLE mode. Press Ctrl+C to stop.", flush=True)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
    finally:
        server.server_close()
