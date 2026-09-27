"""services/jobs.py — round 14 regression coverage.

The scenario this guards against: a campaign in a mid-stage status
(RESEARCHING/GENERATING, set by run_strategy_stage/run_visuals_stage right
before doing real work) hits a genuinely unexpected exception — a network
blip, an OpenAI/Playwright error, anything the orchestrator didn't already
anticipate with its own explicit `campaign.status = "FAILED"` branch. Before
this round, `_execute_job` correctly marked the `Job` row FAILED but never
touched the `Campaign` row, so the campaign stayed stuck showing
RESEARCHING/GENERATING forever with no way to retry (the big "Run Autopilot"
button's guard only re-enables on IDEA/FAILED). These tests exercise the
fix directly against `run_job`/`_execute_job`, without needing a real
Autopilot run to reach the failure.
"""
from __future__ import annotations

import pytest

from app.models import Brand, Campaign, Job
from app.services.jobs import run_job


async def _boom(_ctx) -> None:
    raise RuntimeError("a genuinely unexpected failure, not one the stage anticipated")


def _make_campaign(session, *, status: str) -> Campaign:
    brand = Brand(name="Hanna", slug="hanna")
    session.add(brand)
    session.commit()
    campaign = Campaign(display_id="HANNA-SKIN-000099", brand_id=brand.id, status=status)
    session.add(campaign)
    session.commit()
    return campaign


async def test_unexpected_job_failure_unsticks_a_generating_campaign(temp_db):
    session = temp_db.SessionLocal()
    campaign = _make_campaign(session, status="GENERATING")
    job = Job(type="autopilot_campaign", campaign_id=campaign.id, status="QUEUED")
    session.add(job)
    session.commit()
    job_id, campaign_id = job.id, campaign.id
    session.close()

    with pytest.raises(RuntimeError):
        await run_job(job_id, _boom)

    session = temp_db.SessionLocal()
    refreshed_job = session.get(Job, job_id)
    refreshed_campaign = session.get(Campaign, campaign_id)
    assert refreshed_job.status == "FAILED"
    assert "genuinely unexpected failure" in refreshed_job.error
    assert refreshed_campaign.status == "FAILED"
    session.close()


async def test_unexpected_job_failure_unsticks_a_researching_campaign(temp_db):
    session = temp_db.SessionLocal()
    campaign = _make_campaign(session, status="RESEARCHING")
    job = Job(type="strategy_stage", campaign_id=campaign.id, status="QUEUED")
    session.add(job)
    session.commit()
    job_id, campaign_id = job.id, campaign.id
    session.close()

    with pytest.raises(RuntimeError):
        await run_job(job_id, _boom)

    session = temp_db.SessionLocal()
    assert session.get(Campaign, campaign_id).status == "FAILED"
    session.close()


async def test_unexpected_job_failure_leaves_a_stable_campaign_status_alone(temp_db):
    """A campaign sitting in a stable, resumable status (e.g. BRIEF_READY, between
    Strategy and Copy) is never one the orchestrator set mid-stage — an unrelated
    job failure shouldn't rewrite it to FAILED out from under the user.
    """
    session = temp_db.SessionLocal()
    campaign = _make_campaign(session, status="BRIEF_READY")
    job = Job(type="copy_stage", campaign_id=campaign.id, status="QUEUED")
    session.add(job)
    session.commit()
    job_id, campaign_id = job.id, campaign.id
    session.close()

    with pytest.raises(RuntimeError):
        await run_job(job_id, _boom)

    session = temp_db.SessionLocal()
    assert session.get(Campaign, campaign_id).status == "BRIEF_READY"
    session.close()


async def test_unexpected_job_failure_with_no_campaign_id_does_not_crash(temp_db):
    """Not every job is campaign-scoped (Job.campaign_id is nullable) — the
    backstop must be a no-op, not an error, when there's no campaign to update.
    """
    session = temp_db.SessionLocal()
    job = Job(type="misc", campaign_id=None, status="QUEUED")
    session.add(job)
    session.commit()
    job_id = job.id
    session.close()

    with pytest.raises(RuntimeError):
        await run_job(job_id, _boom)

    session = temp_db.SessionLocal()
    assert session.get(Job, job_id).status == "FAILED"
    session.close()
