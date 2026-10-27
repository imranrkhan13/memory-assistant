
"""Phase 7: protect fact persistence with SQLite job leases.

Updates pipeline.py, ai.py and worker.py.
Refuses to modify files when expected source sections differ.
"""

from pathlib import Path


def replace_once(source, old, new, filename):
    count = source.count(old)
    if count != 1:
        raise RuntimeError(
            f"{filename}: expected one matching section, found {count}. "
            "No files have been modified."
        )
    return source.replace(old, new, 1)


base = Path("memory_assistant")

pipeline_path = base / "pipeline.py"
ai_path = base / "ai.py"
worker_path = base / "worker.py"

pipeline = pipeline_path.read_text(encoding="utf-8")
ai = ai_path.read_text(encoding="utf-8")
worker = worker_path.read_text(encoding="utf-8")

pipeline = replace_once(
    pipeline,
    "def extract_note(note_id, provider=None, user_id=DEFAULT_USER_ID):",
    """def extract_note(
    note_id,
    provider=None,
    user_id=DEFAULT_USER_ID,
    job_id=None,
    lease_token=None,
):""",
    "pipeline.py",
)

pipeline = replace_once(
    pipeline,
    """    with get_connection() as conn:
        for fact in candidates:""",
    """    with get_connection() as conn:
        # Acquire SQLite's write lock before validating the lease.
        # The lock remains held until all facts are committed or
        # the transaction is rolled back.
        if job_id is not None:
            if not lease_token:
                raise ValueError("Missing worker lease token")

            conn.execute("BEGIN IMMEDIATE")

            valid_lease = conn.execute(
                \"""
                SELECT 1
                FROM processing_jobs
                WHERE id = ?
                  AND user_id = ?
                  AND note_id = ?
                  AND status = 'running'
                  AND lease_token = ?
                  AND lease_until > ?
                \""",
                (
                    job_id,
                    user_id,
                    note_id,
                    lease_token,
                    utc_now(),
                ),
            ).fetchone()

            if valid_lease is None:
                raise RuntimeError(
                    "Worker lease expired or ownership lost"
                )

        for fact in candidates:""",
    "pipeline.py",
)

ai = replace_once(
    ai,
    """def process_note(
    note_id,
    provider=None,
    user_id=DEFAULT_USER_ID,
):""",
    """def process_note(
    note_id,
    provider=None,
    user_id=DEFAULT_USER_ID,
    job_id=None,
    lease_token=None,
):""",
    "ai.py",
)

# Both provider branches must pass the lease to the pipeline.
old_call = """        return extract_note(
            note_id,
            provider=ReviewProvider(),
            user_id=user_id,
        )"""

new_call = """        return extract_note(
            note_id,
            provider=ReviewProvider(),
            user_id=user_id,
            job_id=job_id,
            lease_token=lease_token,
        )"""

ai = replace_once(
    ai, old_call, new_call, "ai.py"
)

ai = replace_once(
    ai,
    """    return extract_note(
        note_id,
        provider=provider,
        user_id=user_id,
    )""",
    """    return extract_note(
        note_id,
        provider=provider,
        user_id=user_id,
        job_id=job_id,
        lease_token=lease_token,
    )""",
    "ai.py",
)

worker = replace_once(
    worker,
    """        results = process_note(
            note_id,
            provider=provider,
            user_id=user_id,
        )""",
    """        results = process_note(
            note_id,
            provider=provider,
            user_id=user_id,
            job_id=job_id,
            lease_token=token,
        )""",
    "worker.py",
)

# Validate all three files before writing anything.
for filename, content in (
    ("pipeline.py", pipeline),
    ("ai.py", ai),
    ("worker.py", worker),
):
    compile(content, str(base / filename), "exec")

pipeline_path.write_text(pipeline, encoding="utf-8")
ai_path.write_text(ai, encoding="utf-8")
worker_path.write_text(worker, encoding="utf-8")

print("Phase 7 lease-safe persistence patch applied.")

