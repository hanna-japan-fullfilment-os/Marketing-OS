"""Research endpoints. Listing is read-only over persisted research runs.
`POST /run` is real, live research orchestration (brief section 5-6): it calls
`ResearchProvider.research()` (grounded in real web search, via
`services/research/openai_research.py`) and persists cited insights only — an
insight the model returns with no source URL is dropped, never fabricated into a
`research_insights` row. TTL caching means a repeat call for the same brand/
category/product within the configured window returns the cached run instead of
re-billing a new research call.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Brand, Category, Product, ResearchRun
from ..services import settings_store
from ..services.ai.openai_provider import OpenAIProvider, openai_provider_from_effective_settings
from ..services.research.openai_research import (
    build_research_query, derive_geography_and_audience, run_research,
)

router = APIRouter(prefix="/api/research", tags=["research"])


class RunResearchRequest(BaseModel):
    brand_id: str
    category_id: str | None = None
    product_id: str | None = None
    objective: str = "awareness"
    geography: str | None = None
    audience: str | None = None
    ttl_kind: str = "trend"  # trend | category
    force_refresh: bool = False


@router.get("/runs")
def list_research_runs(brand_id: str, db: Session = Depends(get_db)):
    runs = db.query(ResearchRun).filter(ResearchRun.brand_id == brand_id).order_by(ResearchRun.created_at.desc()).all()
    return [
        {
            "id": r.id,
            "category_id": r.category_id,
            "ttl_kind": r.ttl_kind,
            "created_at": r.created_at,
            "expires_at": r.expires_at,
            "insight_count": len(r.insights),
            "source_count": len(r.sources),
        }
        for r in runs
    ]


@router.get("/runs/{run_id}")
def get_research_run(run_id: str, db: Session = Depends(get_db)):
    run = db.get(ResearchRun, run_id)
    if run is None:
        raise HTTPException(404, "Research run not found.")
    return {
        "id": run.id,
        "category_id": run.category_id,
        "ttl_kind": run.ttl_kind,
        "created_at": run.created_at,
        "expires_at": run.expires_at,
        "insights": [
            {
                "statement": i.statement,
                "confidence": i.confidence,
                "freshness": i.freshness,
                "category": i.category,
                "recommended_implication": i.recommended_implication,
                "source_ids": i.source_ids,
            }
            for i in run.insights
        ],
        "sources": [
            {"id": s.id, "url": s.url, "title": s.source_title, "publisher": s.publisher}
            for s in run.sources
        ],
    }


@router.post("/run")
async def trigger_research(payload: RunResearchRequest, db: Session = Depends(get_db)):
    brand = db.get(Brand, payload.brand_id)
    if brand is None:
        raise HTTPException(404, "Brand not found.")

    category = None
    if payload.category_id:
        category = db.get(Category, payload.category_id)
        if category is None:
            raise HTTPException(404, "Category not found.")

    product = None
    if payload.product_id:
        product = db.get(Product, payload.product_id)
        if product is None:
            raise HTTPException(404, "Product not found.")

    effective = settings_store.get_effective_settings(db)
    api_key = effective.get("openai_api_key")
    if not api_key:
        raise HTTPException(400, "OpenAI API key is not configured. Set it in Settings first.")

    geography, audience = derive_geography_and_audience(
        brand_target_countries=brand.target_countries,
        brand_target_audiences=brand.target_audiences,
        category_name=category.name if category is not None else None,
        geography_override=payload.geography,
        audience_override=payload.audience,
    )
    language = brand.language_rules.get("primary") if isinstance(brand.language_rules, dict) else None

    query = build_research_query(
        brand_name=brand.name,
        category_name=category.name if category is not None else "general",
        product_name=product.name if product is not None else None,
        geography=geography,
        audience=audience,
        objective=payload.objective,
        language=language or "pt-BR",
    )

    provider = openai_provider_from_effective_settings(effective)
    try:
        run, was_cached = await run_research(
            db,
            provider=provider,
            query=query,
            brand_id=brand.id,
            category_id=payload.category_id,
            product_id=payload.product_id,
            model=effective.get("openai_research_model"),
            ttl_kind=payload.ttl_kind,
            trend_ttl_hours=effective.get("trend_research_ttl_hours"),
            category_ttl_hours=effective.get("category_research_ttl_hours"),
            force_refresh=payload.force_refresh,
        )
    except RuntimeError as exc:
        raise HTTPException(400, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(502, f"Research call did not return a usable structured result: {exc}") from exc

    return {
        "id": run.id,
        "was_cached": was_cached,
        "ttl_kind": run.ttl_kind,
        "created_at": run.created_at,
        "expires_at": run.expires_at,
        "insight_count": len(run.insights),
        "source_count": len(run.sources),
    }
