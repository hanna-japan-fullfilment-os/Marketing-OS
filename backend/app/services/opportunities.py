"""Opportunity discovery (brief section 46, campaign-pipeline.md Phase 8) — finding
real places to post (Facebook Groups, subreddits, forums, Discord servers) rather
than the app pretending it can auto-post into a Group it doesn't administer (Meta's
Graph API structurally doesn't allow that for third-party apps — see README.md).

Mirrors `services/research/openai_research.py`'s "no fake research" discipline: a
recommendation the model can't back with at least one `source_urls` entry is dropped
before it's ever persisted as an `Opportunity` row, never shown as if it were a real,
verified community.

Deliberately upserts rather than always inserting: re-running discovery for the same
brand/category scope should refresh what's already known (relevance score, posting
rules, last_checked_at) rather than accumulating duplicate rows for the same group —
the same "don't repeat yourself" principle the brief applies to campaigns applies
here to the communities themselves.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from ..models import Opportunity
from ..schemas.ai import OpportunityDiscoveryResult, ResearchQuery
from .ai.base import ResearchProvider


def build_opportunity_query(
    *,
    brand_name: str,
    category_name: str,
    product_name: str | None = None,
    geography: str,
    audience: str,
    objective: str = "community_reach",
    language: str = "pt-BR",
) -> ResearchQuery:
    """Reuses ResearchQuery as-is (brand/category/product/geography/audience/
    objective/language) rather than a parallel schema — the discovery prompt just
    interprets those same fields for "where does this audience gather" instead of
    "what's trending", so a second near-identical schema would add nothing.
    """
    return ResearchQuery(
        brand_name=brand_name,
        category=category_name,
        product=product_name,
        geography=geography,
        audience=audience,
        objective=objective,
        language=language,
    )


@dataclass
class OpportunityDiscoveryOutcome:
    created: list[Opportunity]
    updated: list[Opportunity]
    dropped_uncited: int


def _find_existing(db: Session, *, brand_id: str, platform: str, name: str) -> Opportunity | None:
    """Matches on (brand_id, platform, name) case-insensitively — the model has no
    unique constraint for this (a user might legitimately rename/annotate a row), so
    matching is done here rather than relying on the DB to reject a duplicate insert.
    """
    normalized = name.strip().lower()
    candidates = (
        db.query(Opportunity)
        .filter(Opportunity.brand_id == brand_id, Opportunity.platform == platform)
        .all()
    )
    for c in candidates:
        if c.name.strip().lower() == normalized:
            return c
    return None


async def run_opportunity_discovery(
    db: Session,
    *,
    provider: ResearchProvider,
    query: ResearchQuery,
    brand_id: str,
    category_id: str | None,
    model: str,
) -> OpportunityDiscoveryOutcome:
    result: OpportunityDiscoveryResult = await provider.discover_opportunities(query, model=model)
    now = datetime.now(timezone.utc)

    created: list[Opportunity] = []
    updated: list[Opportunity] = []
    dropped = 0

    for rec in result.recommendations:
        if not rec.source_urls:
            # No verifiable source — exactly the "invented Facebook Group" failure
            # mode the brief prohibits, so this recommendation is never persisted.
            dropped += 1
            continue

        existing = _find_existing(db, brand_id=brand_id, platform=rec.platform, name=rec.name)
        source_note = "; ".join(rec.source_urls)
        if existing is not None:
            existing.url = rec.url or existing.url
            existing.audience = query.audience
            existing.category_id = category_id or existing.category_id
            existing.country = rec.country or existing.country
            existing.language = rec.language or existing.language
            existing.estimated_relevance = rec.estimated_relevance
            existing.audience_size = rec.audience_size if rec.audience_size is not None else existing.audience_size
            existing.promo_allowed = rec.promo_allowed if rec.promo_allowed is not None else existing.promo_allowed
            existing.posting_rules = rec.posting_rules or existing.posting_rules
            existing.recommended_content_style = rec.recommended_content_style
            existing.notes = rec.rationale
            existing.source = source_note
            existing.last_checked_at = now
            updated.append(existing)
        else:
            opp = Opportunity(
                brand_id=brand_id,
                platform=rec.platform,
                name=rec.name,
                url=rec.url,
                description=rec.rationale,
                audience=query.audience,
                category_id=category_id,
                country=rec.country,
                language=rec.language,
                estimated_relevance=rec.estimated_relevance,
                audience_size=rec.audience_size,
                promo_allowed=rec.promo_allowed,
                posting_rules=rec.posting_rules,
                recommended_content_style=rec.recommended_content_style,
                notes=rec.rationale,
                source=source_note,
                discovered_at=now,
                last_checked_at=now,
                status="DISCOVERED",
            )
            db.add(opp)
            created.append(opp)

    db.commit()
    for opp in created:
        db.refresh(opp)
    return OpportunityDiscoveryOutcome(created=created, updated=updated, dropped_uncited=dropped)
