"""Minimal DB-backed job runner (brief section 30). One FastAPI process, no external
queue — appropriate for a single local user. Long operations (research, campaign
generation) create a `Job` row; `run_job` awaits it synchronously (the caller's HTTP
request returns once it's done — useful for a short job, or a test that wants the
result inline), while `run_job_in_background` schedules it as a fire-and-forget
`asyncio.create_task` and returns immediately, letting the caller's HTTP response go
back right away and the frontend poll `GET /api/jobs/{id}` for progress instead of
the request blocking for the run's duration. All four `POST /api/campaigns/{id}/
generate*` endpoints (api/campaigns.py) use `run_job_in_background` — a real
Autopilot run does real research + several AI calls + Playwright renders, easily
tens of seconds, which is long enough that a blocked request stops looking like a
reasonable trade-off once there's a frontend that can poll instead.

Looks up `SessionLocal` via the `db` module object (not a copied name) so tests that
monkeypatch `app.db.SessionLocal` for an isolated test database are respected here
too — a `from ..db import SessionLocal` binding would freeze to whichever engine
existed the first time this module was imported (see app/main.py's lifespan for the
same fix, applied for the same reason).
"""
from __future__ import annotations

import asyncio
import traceback
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from .. import db as db_module
from ..models import Campaign, Job

JobFn = Callable[["JobContext"], Awaitable[None]]

# Campaign statuses the orchestrator only ever sets *mid*-stage, immediately
# before doing the actual (AI/render) work — never a status a campaign is
# meant to sit in between requests. `run_strategy_stage` sets RESEARCHING
# right before its research + AI calls; `run_visuals_stage` sets GENERATING
# right before its render loop. Each stage already sets `campaign.status =
# "FAILED"` itself for the specific failure cases it anticipates (no
# candidate photos, no strategy candidates returned, everything rejected as
# too similar) — but an *unanticipated* exception (a network blip, an
# OpenAI/Playwright error) raised from inside one of those windows would
# otherwise leave the campaign stuck showing RESEARCHING/GENERATING forever,
# with the big "Run Autopilot" button disabled (its guard only re-enables on
# IDEA/FAILED) even though `Job.status` correctly says FAILED. See below.
_STUCK_IF_JOB_FAILS = frozenset({"RESEARCHING", "GENERATING"})


class JobContext:
    """Passed into a job function so it can report progress without holding a
    long-lived DB session across awaits.
    """

    def __init__(self, job_id: str):
        self.job_id = job_id

    def _with_session(self, fn: Callable[[Session, Job], None]) -> None:
        db = db_module.SessionLocal()
        try:
            job = db.get(Job, self.job_id)
            if job is None:
                return
            fn(db, job)
            db.commit()
        finally:
            db.close()

    def set_progress(self, progress: int, step: str) -> None:
        def _update(db: Session, job: Job) -> None:
            job.progress = max(0, min(100, progress))
            job.step = step

        self._with_session(_update)


def create_job(db: Session, *, type_: str, campaign_id: str | None = None, metadata: dict | None = None) -> Job:
    job = Job(type=type_, campaign_id=campaign_id, status="QUEUED", job_metadata=metadata or {})
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


async def _execute_job(job_id: str, fn: JobFn) -> None:
    db = db_module.SessionLocal()
    try:
        job = db.get(Job, job_id)
        if job is None:
            return
        job.status = "RUNNING"
        job.started_at = datetime.now(timezone.utc)
        job.attempts += 1
        db.commit()
    finally:
        db.close()

    ctx = JobContext(job_id)
    exc_to_reraise: BaseException | None = None
    db2 = db_module.SessionLocal()
    try:
        job = db2.get(Job, job_id)
        try:
            await fn(ctx)
            if job is not None:
                job.status = "COMPLETED"
                job.progress = 100
                job.completed_at = datetime.now(timezone.utc)
        except Exception as exc:  # noqa: BLE001 - job failure is data, not a crash
            if job is not None:
                # Prefer the exception's own message (usually a clear, actionable
                # ValueError from the orchestrator) over a raw traceback dump.
                job.error = str(exc) or traceback.format_exc(limit=5)
                job.status = "FAILED"
                job.completed_at = datetime.now(timezone.utc)
                # An anticipated failure inside a stage (e.g. "no candidate
                # photos") already sets campaign.status = "FAILED" itself
                # before raising. This is the backstop for everything else —
                # any exception this job function didn't specifically handle —
                # so a genuinely unexpected failure never leaves the campaign
                # stuck showing an in-progress status with no way to retry.
                # See _STUCK_IF_JOB_FAILS's docstring above for why only these
                # two statuses qualify.
                if job.campaign_id is not None:
                    campaign = db2.get(Campaign, job.campaign_id)
                    if campaign is not None and campaign.status in _STUCK_IF_JOB_FAILS:
                        campaign.status = "FAILED"
            exc_to_reraise = exc
        db2.commit()
    finally:
        db2.close()

    if exc_to_reraise is not None:
        raise exc_to_reraise


async def run_job(job_id: str, fn: JobFn) -> None:
    """Await this directly to run the job synchronously in the current coroutine —
    e.g. from a request handler that wants to return the final result once the job
    finishes. Re-raises the job function's exception after recording it on the Job
    row, so the caller can translate it into an HTTP error.
    """
    await _execute_job(job_id, fn)


def run_job_in_background(job_id: str, fn: JobFn) -> None:
    """Fire-and-forget: schedules the job on the running event loop and returns
    immediately, for a job type whose caller wants to poll GET /api/jobs/{id}
    instead of waiting on the request.
    """
    asyncio.create_task(_execute_job(job_id, fn))
