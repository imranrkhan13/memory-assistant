
"""Phase 7: atomically save extracted facts and complete their job."""

from pathlib import Path

base = Path("memory_assistant")
pipeline_path = base / "pipeline.py"
worker_path = base / "worker.py"

pipeline = pipeline_path.read_text(encoding="utf-8")
worker = worker_path.read_text(encoding="utf-8")


def replace_once(source, old, new, filename):
    count = source.count(old)
    if count != 1:
        raise RuntimeError(
            f"{filename}: expected one match, found {count}. "
            "No files modified."
        )
    return source.replace(old, new, 1)


# The existing pipeline already validates the lease after
# acquiring BEGIN IMMEDIATE. Add completion to that transaction.
old_pipeline_end = """            results.append((status, fact_id))

    return results
"""

new_pipeline_end = """            results.append((status, fact_id))

        if job_id is not None:
            cursor = conn.execute(
                \"""
                UPDATE processing_jobs
                SET status = 'succeeded',
                    checkpoint = 'processing_completed',
                    completed_at = ?,
                    lease_token = NULL,
                    lease_until = NULL,
                    last_error_code = NULL,
                    last_error_message = NULL
                WHERE id = ?
                  AND user_id = ?
                  AND note_id = ?
                  AND status = 'running'
                  AND lease_token = ?
                  AND lease_until > ?
                \""",
                (
                    utc_now(),
                    job_id,
                    user_id,
                    note_id,
                    lease_token,
                    utc_now(),
                ),
            )

            if cursor.rowcount != 1:
                raise RuntimeError(
                    "Job lease lost before atomic completion"
                )

    return results
"""

pipeline = replace_once(
    pipeline,
    old_pipeline_end,
    new_pipeline_end,
    "pipeline.py",
)

# The pipeline now completes the job itself. The worker must
# not try to complete it a second time.
old_worker = """        # Do not mark success if the job was cancelled,
        # expired or claimed by another worker.
        success = complete_job(job_id, token)

        if not success:
            raise RuntimeError(
                "Job lease lost before completion"
            )
"""

new_worker = """        # Fact persistence and job completion are committed
        # together by the extraction pipeline.
        completed = get_job(job_id, user_id=user_id)

        if completed is None or completed["status"] != "succeeded":
            raise RuntimeError(
                "Atomic job completion was not confirmed"
            )
"""

worker = replace_once(
    worker,
    old_worker,
    new_worker,
    "worker.py",
)

# Validate before writing either file.
compile(pipeline, str(pipeline_path), "exec")
compile(worker, str(worker_path), "exec")

pipeline_path.write_text(pipeline, encoding="utf-8")
worker_path.write_text(worker, encoding="utf-8")

print("Atomic persistence patch applied successfully.")

