"""Note-level status and explicit reprocessing over the durable job queue."""
import uuid
from .jobs import init_jobs, now
from .storage import DEFAULT_USER_ID, get_connection


def processing_status(note_id, user_id=DEFAULT_USER_ID):
    init_jobs()
    with get_connection() as conn:
        job = conn.execute("SELECT * FROM processing_jobs WHERE note_id=? AND user_id=? ORDER BY created_at DESC LIMIT 1", (note_id, user_id)).fetchone()
        if job:
            result = dict(job)
            result["state"] = {"queued": "failed" if job["last_error_code"] else "pending", "running": "processing", "succeeded": "done", "failed": "failed", "cancelled": "failed"}[job["status"]]
            return result
        # Legacy notes do not claim completed extraction without a checkpoint.
        return {"state": "pending", "id": None, "last_error_message": "No processing checkpoint; reprocess this note.", "last_error_code": None}


def reprocess_note(note_id, user_id=DEFAULT_USER_ID):
    """Start a new bounded attempt cycle, retaining the same job and fact IDs."""
    init_jobs()
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        if not conn.execute("SELECT 1 FROM notes WHERE id=? AND user_id=?", (note_id, user_id)).fetchone():
            raise ValueError("Note not found.")
        job = conn.execute("SELECT * FROM processing_jobs WHERE note_id=? AND user_id=? ORDER BY created_at DESC LIMIT 1", (note_id, user_id)).fetchone()
        if job and job["status"] in ("queued", "running"):
            raise ValueError("Note already has queued or running work.")
        # Refresh stale pending proposals against exactly the current facts.
        # Approved/rejected facts remain untouched and are never reactivated.
        import json
        for fact in conn.execute("SELECT id, subject FROM facts WHERE note_id=? AND user_id=? AND status='pending'", (note_id, user_id)).fetchall():
            expected = [row["id"] for row in conn.execute("SELECT id FROM facts WHERE subject=? AND user_id=? AND status='active' ORDER BY id", (fact["subject"], user_id))]
            conn.execute("UPDATE approvals SET expected_active_ids=? WHERE fact_id=? AND user_id=? AND status='pending'", (json.dumps(expected), fact["id"], user_id))
        if job:
            conn.execute("UPDATE processing_jobs SET status='queued', attempts=0, checkpoint='note_saved', available_at=?, completed_at=NULL, last_error_code=NULL, last_error_message=NULL, lease_token=NULL, lease_until=NULL WHERE id=?", (now(), job["id"]))
            return job["id"]
        job_id = str(uuid.uuid4())
        conn.execute("INSERT INTO processing_jobs(id,user_id,note_id,idempotency_key,available_at,created_at) VALUES(?,?,?,?,?,?)", (job_id,user_id,note_id,f"extract-note-{note_id}",now(),now()))
        return job_id
