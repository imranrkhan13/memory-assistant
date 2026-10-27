
"""Safely add opt-in Phase 7 queue support to the browser.

Run:
    python3 phase7_web_patch.py
"""

from pathlib import Path

path = Path("memory_assistant/web.py")

if not path.is_file():
    raise SystemExit(
        "Run this script from the memory-assistant project directory."
    )

source = path.read_text(encoding="utf-8")

old_import = """from .gemini import GeminiError"""

new_import = """from .gemini import GeminiError
from .jobs import create_job, init_jobs
"""

old_processing = """                note_id = add_note(value)

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
"""

new_processing = """                # Phase 7 queue mode is opt-in while the existing
                # synchronous browser tests remain supported.
                queue_enabled = (
                    os.environ.get("MEMORY_JOBS_ASYNC", "0") == "1"
                )

                if queue_enabled:
                    init_jobs()

                note_id = add_note(value)

                if queue_enabled:
                    job_id = create_job(
                        note_id=note_id,
                        idempotency_key=f"extract-note-{note_id}",
                    )
                    print(
                        f"Note #{note_id} queued as job {job_id}",
                        flush=True,
                    )
                else:
                    try:
                        process_note(note_id)
                    except (GeminiError, ValueError) as error:
                        print(
                            f"Extraction for note #{note_id} failed: "
                            f"{type(error).__name__}",
                            flush=True,
                        )

                destination = "/notes"
"""

if new_processing in source:
    print("Phase 7 browser integration already applied.")
    raise SystemExit(0)

if source.count(old_import) != 1:
    raise SystemExit(
        "Import location does not match. No changes made."
    )

if source.count(old_processing) != 1:
    raise SystemExit(
        "Add Note handler does not match. No changes made."
    )

source = source.replace(old_import, new_import, 1)
source = source.replace(old_processing, new_processing, 1)

path.write_text(source, encoding="utf-8")

print("Phase 7 browser integration applied successfully.")

