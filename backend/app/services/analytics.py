"""Performance feedback loop math (brief sections 36-38, campaign-pipeline.md's
"feeds back into strategy" arrow). Deliberately simple and inspectable — this is
manually-entered performance data (no ad-platform API integration exists), so the
math stays honest about what it can claim: a plain engagement rate, not a
fabricated "virality score" or anything dressed up as more precise than it is.

`average_engagement_rate_for_strategy_type` is what closes the loop: the Autopilot
orchestrator's `_select_underused_strategy_type` (services/orchestrator.py) uses it
as a tie-breaker among equally-underused Strategy Library types, so a type that has
actually performed well for this brand gets a nudge over one that hasn't — without
letting performance override the underused-count-first rule that keeps one family
from dominating every campaign just because it converts well (see
docs/architecture.md section 5a).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from ..models import Campaign, CampaignStrategyType, PerformanceMetric, Publication


def engagement_rate(metric: PerformanceMetric) -> float | None:
    """(likes + comments + shares + saves) / reach, falling back to impressions as
    the denominator when reach wasn't recorded. Returns None when neither
    denominator is available — a metric snapshot with no reach/impressions can't
    produce a rate, and treating that as 0 would understate it rather than just
    admitting it's not computable.
    """
    denom = metric.reach or metric.impressions
    if not denom:
        return None
    numerator = metric.likes + metric.comments + metric.shares + metric.saves
    return numerator / denom


def _metrics_query(db: Session, *, brand_id: str, since: datetime | None = None):
    q = (
        db.query(PerformanceMetric)
        .join(Publication, Publication.id == PerformanceMetric.publication_id)
        .join(Campaign, Campaign.id == Publication.campaign_id)
        .filter(Campaign.brand_id == brand_id)
    )
    if since is not None:
        q = q.filter(PerformanceMetric.recorded_at >= since)
    return q


def average_engagement_rate_for_strategy_type(db: Session, *, brand_id: str, strategy_type_id: str) -> float:
    """0.0 when there's no computable data yet for this type — a brand-new or
    never-measured type simply doesn't get a performance nudge, it isn't
    penalized relative to one with a poor recorded rate. Scoped to one brand:
    a strategy type performing well for a different brand in this workspace
    shouldn't bias this brand's selection.
    """
    metrics = (
        db.query(PerformanceMetric)
        .join(Publication, Publication.id == PerformanceMetric.publication_id)
        .join(Campaign, Campaign.id == Publication.campaign_id)
        .filter(Campaign.brand_id == brand_id, Campaign.strategy_type_id == strategy_type_id)
        .all()
    )
    rates = [r for r in (engagement_rate(m) for m in metrics) if r is not None]
    return sum(rates) / len(rates) if rates else 0.0


def performance_summary(db: Session, *, brand_id: str, days: int = 90) -> dict:
    """Aggregate totals + a per-strategy-type breakdown for the Analytics page.
    Everything here is a straight sum/average over rows the user actually entered
    (or a connector wrote, once one exists) — nothing modeled or predicted.
    """
    since = datetime.now(timezone.utc) - timedelta(days=days) if days else None
    metrics = _metrics_query(db, brand_id=brand_id, since=since).all()

    totals = {
        "impressions": sum(m.impressions for m in metrics),
        "reach": sum(m.reach for m in metrics),
        "likes": sum(m.likes for m in metrics),
        "comments": sum(m.comments for m in metrics),
        "shares": sum(m.shares for m in metrics),
        "saves": sum(m.saves for m in metrics),
        "clicks": sum(m.clicks for m in metrics),
        "leads": sum(m.leads for m in metrics),
        "bookings": sum(m.bookings for m in metrics),
        "sales": sum(m.sales for m in metrics),
        "revenue": sum(m.revenue for m in metrics),
        "publications_with_data": len({m.publication_id for m in metrics}),
    }

    # Per-strategy-type breakdown: which archetypes are actually performing for
    # this brand, not just which ones get chosen most.
    by_type: dict[str, list[PerformanceMetric]] = {}
    type_rows = (
        db.query(PerformanceMetric, Campaign.strategy_type_id)
        .join(Publication, Publication.id == PerformanceMetric.publication_id)
        .join(Campaign, Campaign.id == Publication.campaign_id)
        .filter(Campaign.brand_id == brand_id)
    )
    if since is not None:
        type_rows = type_rows.filter(PerformanceMetric.recorded_at >= since)
    type_rows = type_rows.all()  # materialized once, reused below for campaign_scores too
    for metric, strategy_type_id in type_rows:
        if not strategy_type_id:
            continue
        by_type.setdefault(strategy_type_id, []).append(metric)

    strategy_ids = list(by_type.keys())
    names = {}
    if strategy_ids:
        for st in db.query(CampaignStrategyType).filter(CampaignStrategyType.id.in_(strategy_ids)).all():
            names[st.id] = st.name

    strategy_breakdown = []
    for stype_id, type_metrics in by_type.items():
        rates = [r for r in (engagement_rate(m) for m in type_metrics) if r is not None]
        strategy_breakdown.append(
            {
                "strategy_type_id": stype_id,
                "strategy_type_name": names.get(stype_id, "Unknown"),
                "campaigns_measured": len({m.publication_id for m in type_metrics}),
                "avg_engagement_rate": round(sum(rates) / len(rates), 4) if rates else None,
                "total_revenue": sum(m.revenue for m in type_metrics),
                "total_sales": sum(m.sales for m in type_metrics),
            }
        )
    strategy_breakdown.sort(key=lambda r: (r["avg_engagement_rate"] is None, -(r["avg_engagement_rate"] or 0)))

    # Top campaigns by revenue, falling back to engagement rate when nothing sold.
    campaign_scores: dict[str, dict] = {}
    for metric, _ in type_rows:
        pub = db.get(Publication, metric.publication_id)
        if pub is None:
            continue
        entry = campaign_scores.setdefault(
            pub.campaign_id, {"revenue": 0.0, "sales": 0, "rates": []},
        )
        entry["revenue"] += metric.revenue
        entry["sales"] += metric.sales
        rate = engagement_rate(metric)
        if rate is not None:
            entry["rates"].append(rate)

    top_campaigns = []
    if campaign_scores:
        campaigns = db.query(Campaign).filter(Campaign.id.in_(campaign_scores.keys())).all()
        campaigns_by_id = {c.id: c for c in campaigns}
        ranked = sorted(
            campaign_scores.items(),
            key=lambda item: (item[1]["revenue"], sum(item[1]["rates"])),
            reverse=True,
        )
        for campaign_id, scores in ranked[:5]:
            c = campaigns_by_id.get(campaign_id)
            if c is None:
                continue
            top_campaigns.append(
                {
                    "campaign_id": c.id,
                    "display_id": c.display_id,
                    "angle": c.angle,
                    "revenue": scores["revenue"],
                    "sales": scores["sales"],
                    "avg_engagement_rate": round(sum(scores["rates"]) / len(scores["rates"]), 4)
                    if scores["rates"]
                    else None,
                }
            )

    return {"window_days": days, "totals": totals, "by_strategy_type": strategy_breakdown, "top_campaigns": top_campaigns}
