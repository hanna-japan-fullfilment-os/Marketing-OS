"""Research orchestration (brief sections 5-6, campaign-pipeline.md step 6).

Wraps `ResearchProvider.research()` with TTL-based caching against `research_runs` so
the same brand/category/product scope isn't re-researched (and re-billed) on every
campaign — see `TREND_RESEARCH_TTL_HOURS`/`CATEGORY_RESEARCH_TTL_HOURS` in config.

The brief's "no fake research" rule is enforced structurally, not by convention: an
insight the provider returns with zero `source_urls` is dropped before it's ever
persisted (see `_persist_result`). A `ResearchRun` is still recorded even when every
insight gets filtered out — the caller sees "we asked, nothing came back cited"
rather than the run silently not existing, which would look like the feature never
ran at all.

DB-agnostic where it matters: `build_research_query` takes plain strings so the API
layer decides how to derive geography/audience/objective from a Brand row, rather
than this module reaching into ORM relationships itself.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from ...models import ResearchInsight, ResearchRun, ResearchSource
from ...schemas.ai import ResearchQuery, ResearchResult
from ..ai.base import ResearchProvider


def derive_geography_and_audience(
    *,
    brand_target_countries: list[str] | None,
    brand_target_audiences: list[str] | None,
    category_name: str | None,
    geography_override: str | None = None,
    audience_override: str | None = None,
) -> tuple[str, str]:
    """Shared default-derivation logic used by both the manual research trigger
    (api/research.py) and the Autopilot orchestrator, so the two don't drift.
    """
    geography = geography_override or (
        ", ".join(brand_target_countries) if brand_target_countries else "unspecified"
    )
    audience = audience_override or (
        ", ".join(brand_target_audiences)
        if brand_target_audiences
        else (category_name if category_name else "general audience")
    )
    return geography, audience


def build_research_query(
    *,
    brand_name: str,
    category_name: str,
    product_name: str | None = None,
    geography: str,
    audience: str,
    objective: str,
    language: str = "pt-BR",
) -> ResearchQuery:
    return ResearchQuery(
        brand_name=brand_name,
        category=category_name,
        product=product_name,
        geography=geography,
        audience=audience,
        objective=objective,
        language=language,
    )


def find_fresh_research_run(
    db: Session, *, brand_id: str, category_id: str | None, product_id: str | None
) -> ResearchRun | None:
    """The most recent non-expired run for this exact scope. Category/product must
    match exactly (None means brand-wide) — a wrong-scope cache hit silently reusing
    research from a different category would be worse than a fresh (billed) call.
    """
    now = datetime.now(timezone.utc)
    return (
        db.query(ResearchRun)
        .filter(
            ResearchRun.brand_id == brand_id,
            ResearchRun.category_id == category_id,
            ResearchRun.product_id == product_id,
        )
        .filter((ResearchRun.expires_at.is_(None)) | (ResearchRun.expires_at > now))
        .order_by(ResearchRun.created_at.desc())
        .first()
    )


def _ttl_for(ttl_kind: str, *, trend_ttl_hours: int, category_ttl_hours: int) -> timedelta:
    hours = trend_ttl_hours if ttl_kind == "trend" else category_ttl_hours
    return timedelta(hours=hours)


def _persist_result(
    db: Session,
    *,
    result: ResearchResult,
    brand_id: str,
    category_id: str | None,
    product_id: str | None,
    query: ResearchQuery,
    ttl_kind: str,
    trend_ttl_hours: int,
    category_ttl_hours: int,
) -> ResearchRun:
    now = datetime.now(timezone.utc)
    run = ResearchRun(
        brand_id=brand_id,
        category_id=category_id,
        product_id=product_id,
        query_context=query.model_dump(),
        ttl_kind=ttl_kind,
        expires_at=now + _ttl_for(ttl_kind, trend_ttl_hours=trend_ttl_hours, category_ttl_hours=category_ttl_hours),
    )
    db.add(run)
    db.flush()  # need run.id before attaching sources/insights

    source_id_by_url: dict[str, str] = {}
    for insight in result.insights:
        for url in insight.source_urls:
            if url in source_id_by_url:
                continue
            source = ResearchSource(
                research_run_id=run.id,
                url=url,
                query=query.category,
                retrieved_at=now,
            )
            db.add(source)
            db.flush()
            source_id_by_url[url] = source.id

    for insight in result.insights:
        if not insight.source_urls:
            # No citation trail — this is exactly the "fabricated statistic" the
            # brief prohibits, so it never becomes a persisted ResearchInsight.
            continue
        db.add(
            ResearchInsight(
                research_run_id=run.id,
                statement=insight.statement,
                source_ids=[source_id_by_url[u] for u in insight.source_urls if u in source_id_by_url],
                confidence=insight.confidence,
                freshness=insight.freshness,
                category=insight.category,
                recommended_implication=insight.recommended_implication,
            )
        )

    db.commit()
    db.refresh(run)
    return run


async def run_research(
    db: Session,
    *,
    provider: ResearchProvider,
    query: ResearchQuery,
    brand_id: str,
    category_id: str | None = None,
    product_id: str | None = None,
    model: str,
    ttl_kind: str = "trend",
    trend_ttl_hours: int,
    category_ttl_hours: int,
    force_refresh: bool = False,
) -> tuple[ResearchRun, bool]:
    """Returns (run, was_cached). Checks the cache first unless `force_refresh` is
    set; on a cache miss, calls the provider exactly once and persists the result
    (with uncited insights filtered out, per module docstring).
    """
    if not force_refresh:
        cached = find_fresh_research_run(db, brand_id=brand_id, category_id=category_id, product_id=product_id)
        if cached is not None:
            return cached, True

    result = await provider.research(query, model=model)
    run = _persist_result(
        db,
        result=result,
        brand_id=brand_id,
        category_id=category_id,
        product_id=product_id,
        query=query,
        ttl_kind=ttl_kind,
        trend_ttl_hours=trend_ttl_hours,
        category_ttl_hours=category_ttl_hours,
    )
    return run, False
