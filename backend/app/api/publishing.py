"""Publications + performance metrics (brief sections 36-38, Phase 9).

A `Publication` is a manual record of "this campaign went out somewhere" — created
from Campaign Detail via `POST /api/campaigns/{id}/publications` (see api/campaigns.py
for that entry point and its status guard). This module owns the publication as its
own resource once it exists: listing across a brand, updating its status/URL, and
attaching real performance numbers you typed in after checking the platform's own
insights.

Nothing here estimates, predicts, or infers a number. `PerformanceMetric` rows are
either typed in by hand (`source="manual"`, the only path that exists today) or, in a
future connector, written by a real platform-API sync — never fabricated. The math
that turns these rows into rates/summaries lives in `services/analytics.py`; this
module is pure CRUD plus the one piece of business logic already established by the
campaigns endpoint: marking a publication "published" moves its campaign to
`PUBLISHED` too, so campaign status always reflects the most-advanced known reality.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Campaign, PerformanceMetric, Publication
from ..services import settings_store
from ..services.publishing.meta_provider import MetaPublishingProvider

router = APIRouter(prefix="/api/publications", tags=["publishing"])

_SYNCABLE_PROVIDERS = {"facebook_page", "instagram"}


def _publication_out(pub: Publication) -> dict:
    return {
        "id": pub.id,
        "campaign_id": pub.campaign_id,
        "provider": pub.provider,
        "external_post_id": pub.external_post_id,
        "url": pub.url,
        "status": pub.status,
        "published_at": pub.published_at,
        "created_at": pub.created_at,
    }


def _metric_out(m: PerformanceMetric) -> dict:
    return {
        "id": m.id,
        "publication_id": m.publication_id,
        "impressions": m.impressions,
        "reach": m.reach,
        "likes": m.likes,
        "comments": m.comments,
        "shares": m.shares,
        "saves": m.saves,
        "clicks": m.clicks,
        "leads": m.leads,
        "bookings": m.bookings,
        "sales": m.sales,
        "revenue": m.revenue,
        "recorded_at": m.recorded_at,
        "source": m.source,
    }


@router.get("")
def list_publications(
    brand_id: str, status: str | None = None, provider: str | None = None, db: Session = Depends(get_db)
):
    q = (
        db.query(Publication)
        .join(Campaign, Campaign.id == Publication.campaign_id)
        .filter(Campaign.brand_id == brand_id)
    )
    if status:
        q = q.filter(Publication.status == status)
    if provider:
        q = q.filter(Publication.provider == provider)
    rows = q.order_by(Publication.created_at.desc()).all()
    return [_publication_out(p) for p in rows]


class UpdatePublicationRequest(BaseModel):
    status: str | None = None
    url: str | None = None
    external_post_id: str | None = None
    published_at: datetime | None = None


@router.patch("/{publication_id}")
def update_publication(publication_id: str, payload: UpdatePublicationRequest, db: Session = Depends(get_db)):
    pub = db.get(Publication, publication_id)
    if pub is None:
        raise HTTPException(404, "Publication not found.")

    if payload.url is not None:
        pub.url = payload.url
    if payload.external_post_id is not None:
        pub.external_post_id = payload.external_post_id
    if payload.published_at is not None:
        pub.published_at = payload.published_at
    if payload.status is not None:
        pub.status = payload.status
        if payload.status == "published":
            if pub.published_at is None:
                pub.published_at = datetime.now(timezone.utc)
            campaign = db.get(Campaign, pub.campaign_id)
            if campaign is not None:
                campaign.status = "PUBLISHED"

    db.commit()
    db.refresh(pub)
    return _publication_out(pub)


class AddMetricRequest(BaseModel):
    impressions: int = 0
    reach: int = 0
    likes: int = 0
    comments: int = 0
    shares: int = 0
    saves: int = 0
    clicks: int = 0
    leads: int = 0
    bookings: int = 0
    sales: int = 0
    revenue: float = 0.0
    recorded_at: datetime | None = None


@router.get("/{publication_id}/metrics")
def list_metrics(publication_id: str, db: Session = Depends(get_db)):
    pub = db.get(Publication, publication_id)
    if pub is None:
        raise HTTPException(404, "Publication not found.")
    rows = (
        db.query(PerformanceMetric)
        .filter(PerformanceMetric.publication_id == publication_id)
        .order_by(PerformanceMetric.created_at.desc())
        .all()
    )
    return [_metric_out(m) for m in rows]


@router.post("/{publication_id}/metrics", status_code=201)
def add_metric(publication_id: str, payload: AddMetricRequest, db: Session = Depends(get_db)):
    pub = db.get(Publication, publication_id)
    if pub is None:
        raise HTTPException(404, "Publication not found.")

    metric = PerformanceMetric(
        publication_id=publication_id,
        impressions=payload.impressions,
        reach=payload.reach,
        likes=payload.likes,
        comments=payload.comments,
        shares=payload.shares,
        saves=payload.saves,
        clicks=payload.clicks,
        leads=payload.leads,
        bookings=payload.bookings,
        sales=payload.sales,
        revenue=payload.revenue,
        recorded_at=payload.recorded_at or datetime.now(timezone.utc),
        source="manual",
    )
    db.add(metric)
    db.commit()
    db.refresh(metric)
    return _metric_out(metric)


@router.post("/{publication_id}/metrics/sync", status_code=201)
async def sync_metrics_from_meta(publication_id: str, db: Session = Depends(get_db)):
    """Pulls real engagement numbers for this publication from Meta's Graph API
    (sections 36-38's automated counterpart to `add_metric` above) instead of the
    user checking the platform's own insights and typing them in. Only works for a
    publication that was either auto-published by this app (`POST /api/campaigns/
    {id}/publish`, which always sets `external_post_id`) or logged by hand with a
    real `external_post_id` filled in — there's no post to sync numbers for
    otherwise. See `MetaPublishingProvider.fetch_metrics` for exactly which
    numbers this can and can't retrieve, and why some (impressions/reach on
    Facebook, for instance) are best-effort.
    """
    pub = db.get(Publication, publication_id)
    if pub is None:
        raise HTTPException(404, "Publication not found.")
    if pub.provider not in _SYNCABLE_PROVIDERS:
        raise HTTPException(
            400, f"Can't sync metrics for provider '{pub.provider}' — only facebook_page and instagram support this.",
        )
    if not pub.external_post_id:
        raise HTTPException(
            400, "This publication has no external_post_id on file — nothing to sync numbers for.",
        )

    effective = settings_store.get_effective_settings(db)
    access_token = effective.get("facebook_page_access_token")
    if not access_token:
        raise HTTPException(400, "Facebook Page access token is not configured. Set it in Settings first.")

    provider = MetaPublishingProvider(access_token)
    result = await provider.fetch_metrics(provider=pub.provider, external_post_id=pub.external_post_id)
    if not result.success:
        raise HTTPException(502, result.error or "Metrics sync failed for an unknown reason.")

    metric = PerformanceMetric(
        publication_id=publication_id,
        impressions=result.metrics.get("impressions", 0),
        reach=result.metrics.get("reach", 0),
        likes=result.metrics.get("likes", 0),
        comments=result.metrics.get("comments", 0),
        shares=result.metrics.get("shares", 0),
        saves=result.metrics.get("saves", 0),
        recorded_at=datetime.now(timezone.utc),
        source="meta_sync",
    )
    db.add(metric)
    db.commit()
    db.refresh(metric)
    return _metric_out(metric)
