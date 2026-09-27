"""Opportunity discovery + manual community workflow (brief section 46,
campaign-pipeline.md Phase 8).

`POST /discover` is real: it calls `ResearchProvider.discover_opportunities()`
(web-search-grounded, via `services/opportunities.py`) and persists only
communities the model could back with a source URL — an unverifiable "Facebook
Group" name is dropped, never shown as if it were a real, checkable place to post.

Auto-posting into a Group the brand doesn't administer isn't something Meta's
Graph API allows any third-party app to do (see README.md) — so this module's job
ends at "here's a real, verified place, and a draft post for it", with the human
doing the actual posting. `PATCH /{id}` tracks that manual workflow (joined/
favorite/blocked/notes) so discovery doesn't re-suggest the same group forever.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Brand, Category, Opportunity
from ..services import settings_store
from ..services.ai.openai_provider import OpenAIProvider, openai_provider_from_effective_settings
from ..services.opportunities import build_opportunity_query, run_opportunity_discovery
from ..services.research.openai_research import derive_geography_and_audience

router = APIRouter(prefix="/api/opportunities", tags=["opportunities"])


def _opportunity_out(o: Opportunity) -> dict:
    return {
        "id": o.id,
        "platform": o.platform,
        "name": o.name,
        "url": o.url,
        "description": o.description,
        "audience": o.audience,
        "category_id": o.category_id,
        "country": o.country,
        "language": o.language,
        "estimated_relevance": o.estimated_relevance,
        "audience_size": o.audience_size,
        "promo_allowed": o.promo_allowed,
        "posting_rules": o.posting_rules,
        "recommended_content_style": o.recommended_content_style,
        "notes": o.notes,
        "source": o.source,
        "status": o.status,
        "joined_status": o.joined_status,
        "favorite": o.favorite,
        "blocked": o.blocked,
        "discovered_at": o.discovered_at,
        "last_checked_at": o.last_checked_at,
        "last_posted_at": o.last_posted_at,
    }


@router.get("")
def list_opportunities(brand_id: str, status: str | None = None, db: Session = Depends(get_db)):
    q = db.query(Opportunity).filter(Opportunity.brand_id == brand_id, Opportunity.blocked.is_(False))
    if status:
        q = q.filter(Opportunity.status == status)
    rows = q.order_by(Opportunity.estimated_relevance.desc()).all()
    return [_opportunity_out(o) for o in rows]


class DiscoverOpportunitiesRequest(BaseModel):
    brand_id: str
    category_id: str | None = None
    objective: str = "community_reach"
    geography: str | None = None
    audience: str | None = None


@router.post("/discover")
async def discover_opportunities(payload: DiscoverOpportunitiesRequest, db: Session = Depends(get_db)):
    brand = db.get(Brand, payload.brand_id)
    if brand is None:
        raise HTTPException(404, "Brand not found.")

    category = None
    if payload.category_id:
        category = db.get(Category, payload.category_id)
        if category is None:
            raise HTTPException(404, "Category not found.")

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

    query = build_opportunity_query(
        brand_name=brand.name,
        category_name=category.name if category is not None else "general",
        geography=geography,
        audience=audience,
        objective=payload.objective,
        language=language or "pt-BR",
    )

    provider = openai_provider_from_effective_settings(effective)
    try:
        outcome = await run_opportunity_discovery(
            db,
            provider=provider,
            query=query,
            brand_id=brand.id,
            category_id=payload.category_id,
            model=effective.get("openai_research_model"),
        )
    except RuntimeError as exc:
        raise HTTPException(400, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(502, f"Opportunity discovery did not return a usable result: {exc}") from exc

    return {
        "created": len(outcome.created),
        "updated": len(outcome.updated),
        "dropped_uncited": outcome.dropped_uncited,
        "opportunities": [_opportunity_out(o) for o in [*outcome.created, *outcome.updated]],
    }


class UpdateOpportunityRequest(BaseModel):
    joined_status: str | None = None  # not_joined | requested | joined | rejected
    favorite: bool | None = None
    blocked: bool | None = None
    notes: str | None = None
    status: str | None = None  # DISCOVERED | ACTIVE | ARCHIVED


@router.patch("/{opportunity_id}")
def update_opportunity(opportunity_id: str, payload: UpdateOpportunityRequest, db: Session = Depends(get_db)):
    opp = db.get(Opportunity, opportunity_id)
    if opp is None:
        raise HTTPException(404, "Opportunity not found.")
    if payload.joined_status is not None:
        opp.joined_status = payload.joined_status
    if payload.favorite is not None:
        opp.favorite = payload.favorite
    if payload.blocked is not None:
        opp.blocked = payload.blocked
    if payload.notes is not None:
        opp.notes = payload.notes
    if payload.status is not None:
        opp.status = payload.status
    db.commit()
    db.refresh(opp)
    return _opportunity_out(opp)

