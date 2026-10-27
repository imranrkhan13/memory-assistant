"""Add a local Processing Jobs dashboard and CSRF-protected retry."""

from pathlib import Path

path = Path("memory_assistant/web.py")
source = path.read_text(encoding="utf-8")


def replace_once(old, new):
    global source
    count = source.count(old)

    if count != 1:
        raise RuntimeError(
            f"Expected one matching section, found {count}. "
            "No changes made."
        )

    source = source.replace(old, new, 1)


# Import existing job operations.
replace_once(
    "from .gemini import GeminiError",
    "from .gemini import GeminiError\n"
    "from .jobs import list_jobs, retry_job, init_jobs",
)

# Ensure job tables exist when the web server starts.
replace_once(
    "def initialize():\n    init_db()",
    "def initialize():\n    init_db()\n    init_jobs()",
)

# Add navigation link.
replace_once(
    "'<a href=\"/notes\">Notes</a>'",
    "'<a href=\"/notes\">Notes</a>'\n"
    "        '<a href=\"/jobs\">Jobs</a>'",
)

# Insert a new rendering function before the HTTP handler.
marker = "class MemoryHandler(BaseHTTPRequestHandler):"

render_jobs = '''
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


'''

replace_once(marker, render_jobs + marker)

# Register GET /jobs.
replace_once(
    '        elif path == "/notes":\n'
    '            title, body = "Notes", render_notes()',
    '        elif path == "/notes":\n'
    '            title, body = "Notes", render_notes()\n'
    '        elif path == "/jobs":\n'
    '            title, body = "Processing Jobs", render_jobs()',
)

# Add POST /jobs/retry to the existing allowlist.
replace_once(
    '"/add", "/approve", "/reject", "/edit", "/forget"',
    '"/add", "/approve", "/reject", "/edit", '
    '"/forget", "/jobs/retry"',
)

# Handle retry after existing Origin and CSRF checks.
replace_once(
    '            if path == "/add":',
    '''            if path == "/jobs/retry":
                job_id = fields.get("job_id", [""])[0]

                if not job_id or len(job_id) > 100:
                    raise ValueError("Invalid job ID.")

                if not retry_job(job_id):
                    raise ValueError(
                        "Job cannot be retried. It may be "
                        "completed, running, or out of attempts."
                    )

                destination = "/jobs"

            elif path == "/add":''',
)

# Validate before writing.
compile(source, str(path), "exec")
path.write_text(source, encoding="utf-8")

print("Processing Jobs dashboard installed successfully.")
