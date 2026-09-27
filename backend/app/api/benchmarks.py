"""Build 5 — GOLDEN BENCHMARK + PROMPT REGISTRY + MULTI-PLATFORM REGRESSION.

Deliberately thin: every real decision (curation, scoring, comparison) lives
in `services/benchmark_engine.py`/`data/benchmark_scoring.py` — this module
only validates request shape, resolves the API-level concerns (OpenAI key,
output root, background jobs) `api/campaigns.py` already established, and
serializes rows to plain dicts.

`POST /cases/{id}/runs` only accepts `OFFLINE` / `LOW_COST_SMOKE` /
`LIVE_FULL` over HTTP — `MOCK` mode exists purely for direct-Python test
callers that hand in a fake provider object, which has no meaning as a JSON
request body.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import db as db_module
from ..db import get_db
from ..models import BenchmarkCase, BenchmarkRun, BENCHMARK_CASE_STATUSES
from ..services import settings_store
from ..services.ai.openai_provider import OpenAIProvider, openai_provider_from_effective_settings
from ..services.benchmark_engine import (
    build_regression_report, compare_runs, compute_owner_agreement_report, curate_benchmark_case, run_benchmark_case,
)
from ..services.creative.renderer import get_renderer
from ..services.jobs import create_job, run_job_in_background
from ..services.prompt_registry import PROMPT_VERSIONS
from .campaigns import _build_autopilot_config

router = APIRouter(prefix="/api/benchmarks", tags=["benchmarks"])

_HTTP_MODES = ("OFFLINE", "LOW_COST_SMOKE", "LIVE_FULL")


def _case_out(case: BenchmarkCase) -> dict:
    return {
        "id": case.id, "name": case.name, "notes": case.notes, "status": case.status,
        "brand_id": case.brand_id, "product_id": case.product_id, "category_id": case.category_id,
        "platform": case.platform, "content_type": case.content_type, "language": case.language,
        "objective": case.objective, "audience": case.audience,
        "source_asset_paths": case.source_asset_paths, "expected_truths": case.expected_truths,
        "prohibited_claims": case.prohibited_claims,
        "expected_creative_characteristics": case.expected_creative_characteristics,
        "owner_rating": case.owner_rating, "source_feedback_id": case.source_feedback_id,
        "created_at": case.created_at.isoformat() if case.created_at else None,
    }


def _run_out(run: BenchmarkRun) -> dict:
    return {
        "id": run.id, "benchmark_case_id": run.benchmark_case_id, "mode": run.mode,
        "platform": run.platform, "language": run.language, "campaign_id": run.campaign_id,
        "variant_id": run.variant_id, "prompt_versions_snapshot": run.prompt_versions_snapshot,
        "model_role_snapshot": run.model_role_snapshot,
        # Build 5 repair (Part 2): the complete creative-system identity —
        # answers "what exact generation system produced this run?" on its own,
        # without a reader having to cross-reference live/mutable config.
        "creative_system_snapshot": run.creative_system_snapshot,
        "qa_status": run.qa_status,
        "human_review_status": run.human_review_status, "qa_scores": run.qa_scores,
        "hard_fails": run.hard_fails, "weighted_score": run.weighted_score, "weights_used": run.weights_used,
        "cost_breakdown": run.cost_breakdown, "is_baseline": run.is_baseline,
        "created_at": run.created_at.isoformat() if run.created_at else None,
    }


class CurateCaseRequest(BaseModel):
    brand_id: str
    platform: str
    content_type: str = ""
    language: str
    objective: str = ""
    audience: str = ""
    product_id: str | None = None
    category_id: str | None = None
    source_asset_paths: list[str] = []
    expected_truths: list[str] = []
    prohibited_claims: list[str] = []
    expected_creative_characteristics: list[str] = []
    name: str = ""
    notes: str = ""
    status: str = "ACTIVE"
    source_feedback_id: str | None = None


@router.post("/cases", status_code=201)
def create_benchmark_case(payload: CurateCaseRequest, db: Session = Depends(get_db)):
    if payload.status not in BENCHMARK_CASE_STATUSES:
        raise HTTPException(400, f"status must be one of {BENCHMARK_CASE_STATUSES}.")
    case = curate_benchmark_case(db, **payload.model_dump())
    return _case_out(case)


@router.get("/cases")
def list_benchmark_cases(
    brand_id: str | None = None, platform: str | None = None, language: str | None = None,
    status: str | None = None, db: Session = Depends(get_db),
):
    query = db.query(BenchmarkCase)
    if brand_id:
        query = query.filter(BenchmarkCase.brand_id == brand_id)
    if platform:
        query = query.filter(BenchmarkCase.platform == platform)
    if language:
        query = query.filter(BenchmarkCase.language == language)
    if status:
        query = query.filter(BenchmarkCase.status == status)
    cases = query.order_by(BenchmarkCase.created_at.desc()).all()
    return {"cases": [_case_out(c) for c in cases]}


@router.get("/cases/{case_id}")
def get_benchmark_case(case_id: str, db: Session = Depends(get_db)):
    case = db.get(BenchmarkCase, case_id)
    if case is None:
        raise HTTPException(404, "Benchmark case not found.")
    return _case_out(case)


class RunCaseRequest(BaseModel):
    mode: str = "OFFLINE"
    is_baseline: bool = False


@router.post("/cases/{case_id}/runs", status_code=201)
async def run_case_endpoint(case_id: str, payload: RunCaseRequest, db: Session = Depends(get_db)):
    case = db.get(BenchmarkCase, case_id)
    if case is None:
        raise HTTPException(404, "Benchmark case not found.")
    if payload.mode not in _HTTP_MODES:
        raise HTTPException(400, f"mode must be one of {_HTTP_MODES} over the API (MOCK is test-only).")

    effective = settings_store.get_effective_settings(db)
    output_root = effective.get("output_root")
    if not output_root:
        raise HTTPException(400, "OUTPUT_ROOT is not configured. Set it in Settings first.")
    config = _build_autopilot_config(effective, output_root)

    provider = None
    if payload.mode in ("LOW_COST_SMOKE", "LIVE_FULL"):
        api_key = effective.get("openai_api_key")
        if not api_key:
            raise HTTPException(400, "OpenAI API key is not configured. Set it in Settings first.")
        provider = openai_provider_from_effective_settings(effective)

    job = create_job(db, type_="benchmark_run", campaign_id=None, metadata={"benchmark_case_id": case.id})

    async def _job_fn(ctx) -> None:
        session = db_module.SessionLocal()
        try:
            fresh_case = session.get(BenchmarkCase, case.id)
            await run_benchmark_case(
                session, case=fresh_case, config=config, mode=payload.mode, renderer=get_renderer(),
                ai_provider=provider, research_provider=provider, image_provider=provider,
                is_baseline=payload.is_baseline,
            )
        finally:
            session.close()

    run_job_in_background(job.id, _job_fn)
    return {"job_id": job.id, "job_status": job.status}


@router.get("/cases/{case_id}/runs")
def list_case_runs(case_id: str, db: Session = Depends(get_db)):
    runs = (
        db.query(BenchmarkRun).filter(BenchmarkRun.benchmark_case_id == case_id)
        .order_by(BenchmarkRun.created_at.desc()).all()
    )
    return {"runs": [_run_out(r) for r in runs]}


@router.get("/runs/{run_id}")
def get_run(run_id: str, db: Session = Depends(get_db)):
    run = db.get(BenchmarkRun, run_id)
    if run is None:
        raise HTTPException(404, "Benchmark run not found.")
    return _run_out(run)


class CompareRunsRequest(BaseModel):
    baseline_run_id: str
    candidate_run_id: str


@router.post("/compare")
def compare_runs_endpoint(payload: CompareRunsRequest, db: Session = Depends(get_db)):
    baseline = db.get(BenchmarkRun, payload.baseline_run_id)
    candidate = db.get(BenchmarkRun, payload.candidate_run_id)
    if baseline is None or candidate is None:
        raise HTTPException(404, "One or both benchmark runs not found.")
    return compare_runs(baseline, candidate)


class RegressionReportRequest(BaseModel):
    pairs: list[CompareRunsRequest]


@router.post("/regression-report")
def regression_report_endpoint(payload: RegressionReportRequest, db: Session = Depends(get_db)):
    comparisons = []
    for pair in payload.pairs:
        baseline = db.get(BenchmarkRun, pair.baseline_run_id)
        candidate = db.get(BenchmarkRun, pair.candidate_run_id)
        if baseline is None or candidate is None:
            raise HTTPException(404, f"Run not found for pair {pair.model_dump()}.")
        comparisons.append(compare_runs(baseline, candidate))
    return build_regression_report(comparisons)


@router.get("/owner-agreement")
def owner_agreement_endpoint(brand_id: str | None = None, db: Session = Depends(get_db)):
    return compute_owner_agreement_report(db, brand_id=brand_id)


@router.get("/prompt-registry")
def prompt_registry_endpoint():
    """Part A: the registry's own current state, for a frontend to display —
    never a live DB read of `PromptVersion` (which only exists so a real
    campaign's `AuditEvent` trail can reference a stored id); the source of
    truth for "what's registered" is this module's own `PROMPT_VERSIONS`
    dict, seeded into the DB on every startup.
    """
    return {
        "prompts": [
            {
                "purpose": spec.purpose, "version": spec.version, "file_path": spec.file_path,
                "variables": spec.variables, "change_notes": spec.change_notes,
                "platform_applicability": spec.platform_applicability or ["all"],
                "language_applicability": spec.language_applicability or ["all"],
                "active": spec.active,
            }
            for spec in PROMPT_VERSIONS.values()
        ]
    }
