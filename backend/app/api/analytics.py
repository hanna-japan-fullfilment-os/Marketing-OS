"""Dashboard/analytics summary — real counts from the DB. No manufactured metrics."""
from __future__ import annotations

import calendar as calendar_module
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Asset, Campaign, Opportunity, Publication
from ..services.analytics import performance_summary

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


@router.get("/dashboard")
def dashboard_summary(brand_id: str, db: Session = Depends(get_db)):
    thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)

    campaigns_this_month = (
        db.query(func.count(Campaign.id))
        .filter(Campaign.brand_id == brand_id, Campaign.created_at >= thirty_days_ago)
        .scalar()
    )
    waiting_for_review = (
        db.query(func.count(Campaign.id))
        .filter(Campaign.brand_id == brand_id, Campaign.status == "REVIEW")
        .scalar()
    )
    published = (
        db.query(func.count(Campaign.id))
        .filter(Campaign.brand_id == brand_id, Campaign.status == "PUBLISHED")
        .scalar()
    )
    unused_assets = (
        db.query(func.count(Asset.id))
        .filter(Asset.brand_id == brand_id, Asset.times_used == 0, Asset.is_active.is_(True))
        .scalar()
    )
    total_assets = db.query(func.count(Asset.id)).filter(Asset.brand_id == brand_id).scalar()
    opportunities_discovered = (
        db.query(func.count(Opportunity.id)).filter(Opportunity.brand_id == brand_id).scalar()
    )

    return {
        "campaigns_this_month": campaigns_this_month or 0,
        "waiting_for_review": waiting_for_review or 0,
        "published": published or 0,
        "source_assets_unused": unused_assets or 0,
        "source_assets_total": total_assets or 0,
        "opportunities_discovered": opportunities_discovered or 0,
    }


@router.get("/performance")
def performance(brand_id: str, days: int = 90, db: Session = Depends(get_db)):
    """The feedback-loop summary (brief sections 36-38): totals, a per-strategy-type
    breakdown, and top campaigns — all real sums/averages over manually-entered
    `PerformanceMetric` rows (see services/analytics.py's module docstring for why
    this stays a plain engagement rate rather than any fabricated composite score).
    """
    return performance_summary(db, brand_id=brand_id, days=days)


@router.get("/calendar")
def calendar_month(brand_id: str, year: int, month: int, db: Session = Depends(get_db)):
    """Campaigns with a publication scheduled/published in the given month, grouped
    by day. Deliberately a list-grouped-by-date rather than a calendar-grid widget —
    the useful question here is "what went out when", not a visual month grid.
    """
    if not 1 <= month <= 12:
        raise HTTPException(400, "month must be between 1 and 12.")

    days_in_month = calendar_module.monthrange(year, month)[1]
    range_start = datetime(year, month, 1, tzinfo=timezone.utc)
    range_end = datetime(year, month, days_in_month, 23, 59, 59, tzinfo=timezone.utc)

    rows = (
        db.query(Publication, Campaign)
        .join(Campaign, Campaign.id == Publication.campaign_id)
        .filter(
            Campaign.brand_id == brand_id,
            Publication.published_at.isnot(None),
            Publication.published_at >= range_start,
            Publication.published_at <= range_end,
        )
        .order_by(Publication.published_at.asc())
        .all()
    )

    by_day: dict[str, list[dict]] = {}
    for pub, campaign in rows:
        day_key = pub.published_at.date().isoformat()
        by_day.setdefault(day_key, []).append(
            {
                "publication_id": pub.id,
                "campaign_id": campaign.id,
                "display_id": campaign.display_id,
                "angle": campaign.angle,
                "provider": pub.provider,
                "url": pub.url,
                "published_at": pub.published_at,
            }
        )

    return {
        "year": year,
        "month": month,
        "days": [{"date": day, "publications": entries} for day, entries in sorted(by_day.items())],
    }
