
"""Connect browser queue mode to atomic note/job creation."""

from pathlib import Path

path = Path("memory_assistant/web.py")
source = path.read_text(encoding="utf-8")

import_anchor = "from .jobs import create_job, init_jobs"

old_block = """                if queue_enabled:
                    init_jobs()

                note_id = add_note(value)

                if queue_enabled:
                    job_id = create_job(
                        note_id=note_id,
                        idempotency_key=f"extract-note-{note_id}",
                    )
"""

new_block = """                if queue_enabled:
                    note_id, job_id = add_queued_note(value)
                else:
                    note_id = add_note(value)

                if queue_enabled:
"""

if source.count(import_anchor) != 1:
    raise SystemExit(
        "Expected jobs import not found. No changes made."
    )

if source.count(old_block) != 1:
    raise SystemExit(
        "Expected browser queue block not found. "
        "No changes made."
    )

source = source.replace(
    import_anchor,
    import_anchor
    + "\nfrom .queued_notes import add_queued_note",
    1,
)

source = source.replace(old_block, new_block, 1)

compile(source, str(path), "exec")
path.write_text(source, encoding="utf-8")

print("Atomic browser queue patch applied.")

