from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Job

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("")
def list_jobs(status: str | None = None, limit: int = 50, db: Session = Depends(get_db)):
    q = db.query(Job)
    if status:
        q = q.filter(Job.status == status)
    jobs = q.order_by(Job.created_at.desc()).limit(limit).all()
    return [
        {
            "id": j.id, "type": j.type, "status": j.status, "progress": j.progress,
            "step": j.step, "error": j.error, "created_at": j.created_at,
        }
        for j in jobs
    ]


@router.get("/{job_id}")
def get_job(job_id: str, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "Job not found.")
    return {
        "id": job.id, "type": job.type, "status": job.status, "progress": job.progress,
        "step": job.step, "error": job.error, "attempts": job.attempts,
        "started_at": job.started_at, "completed_at": job.completed_at,
    }
