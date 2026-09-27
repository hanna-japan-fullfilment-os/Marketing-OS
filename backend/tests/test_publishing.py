"""Tests for Phase 9's publication + performance metric endpoints
(api/campaigns.py's `/publications` sub-resource, api/publishing.py's own resource,
and api/analytics.py's `/performance` + `/calendar`) plus services/analytics.py's
aggregation math directly.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone


def _client(temp_db):
    from fastapi.testclient import TestClient

    from app.main import app

    return TestClient(app)


def _make_brand_category_campaign(session, *, status="APPROVED", strategy_type_id=None):
    from app.models import Brand, Campaign, Category

    brand = Brand(name="Hanna", slug="hanna")
    session.add(brand)
    session.commit()
    category = Category(brand_id=brand.id, name="Skincare", slug="skincare")
    session.add(category)
    session.commit()
    campaign = Campaign(
        display_id="HANNA-SKIN-000010", brand_id=brand.id, category_id=category.id,
        objective="awareness", status=status, strategy_type_id=strategy_type_id,
        angle="Build your routine",
    )
    session.add(campaign)
    session.commit()
    return brand, category, campaign


def test_create_publication_requires_approved_campaign(temp_db):
    session = temp_db.SessionLocal()
    _, _, campaign = _make_brand_category_campaign(session, status="IDEA")
    campaign_id = campaign.id
    session.close()

    with _client(temp_db) as client:
        r = client.post(f"/api/campaigns/{campaign_id}/publications", json={"provider": "manual"})
        assert r.status_code == 400
        assert "approved" in r.json()["detail"].lower()


def test_create_and_list_publications(temp_db):
    session = temp_db.SessionLocal()
    _, _, campaign = _make_brand_category_campaign(session, status="APPROVED")
    campaign_id = campaign.id
    session.close()

    with _client(temp_db) as client:
        r = client.post(
            f"/api/campaigns/{campaign_id}/publications",
            json={"provider": "facebook_page", "url": "https://facebook.com/post/123", "status": "draft"},
        )
        assert r.status_code == 201
        body = r.json()
        assert body["status"] == "draft"
        assert body["provider"] == "facebook_page"

        r = client.get(f"/api/campaigns/{campaign_id}/publications")
        assert r.status_code == 200
        assert len(r.json()) == 1


def test_publishing_status_transition_bumps_campaign_and_sets_published_at(temp_db):
    from app.models import Campaign

    session = temp_db.SessionLocal()
    _, _, campaign = _make_brand_category_campaign(session, status="APPROVED")
    campaign_id = campaign.id
    session.close()

    with _client(temp_db) as client:
        r = client.post(
            f"/api/campaigns/{campaign_id}/publications",
            json={"provider": "instagram", "status": "draft"},
        )
        pub_id = r.json()["id"]

        r = client.patch(f"/api/publications/{pub_id}", json={"status": "published"})
        assert r.status_code == 200
        assert r.json()["status"] == "published"
        assert r.json()["published_at"] is not None

    session = temp_db.SessionLocal()
    refreshed = session.get(Campaign, campaign_id)
    assert refreshed.status == "PUBLISHED"
    session.close()


def test_add_and_list_metrics(temp_db):
    session = temp_db.SessionLocal()
    _, _, campaign = _make_brand_category_campaign(session, status="APPROVED")
    campaign_id = campaign.id
    session.close()

    with _client(temp_db) as client:
        r = client.post(f"/api/campaigns/{campaign_id}/publications", json={"provider": "manual"})
        pub_id = r.json()["id"]

        r = client.post(
            f"/api/publications/{pub_id}/metrics",
            json={"impressions": 1000, "reach": 800, "likes": 40, "comments": 5, "shares": 2, "saves": 3, "revenue": 120.5, "sales": 2},
        )
        assert r.status_code == 201
        assert r.json()["source"] == "manual"

        r = client.get(f"/api/publications/{pub_id}/metrics")
        assert r.status_code == 200
        assert len(r.json()) == 1
        assert r.json()[0]["revenue"] == 120.5


def test_sync_metrics_requires_syncable_provider_and_external_post_id(temp_db):
    session = temp_db.SessionLocal()
    _, _, campaign = _make_brand_category_campaign(session, status="APPROVED")
    campaign_id = campaign.id
    session.close()

    with _client(temp_db) as client:
        r = client.post(f"/api/campaigns/{campaign_id}/publications", json={"provider": "manual"})
        manual_pub_id = r.json()["id"]
        r = client.post(f"/api/publications/{manual_pub_id}/metrics/sync")
        assert r.status_code == 400
        assert "facebook_page and instagram" in r.json()["detail"]

        r = client.post(
            f"/api/campaigns/{campaign_id}/publications",
            json={"provider": "facebook_page", "status": "published"},
        )
        fb_pub_id = r.json()["id"]
        r = client.post(f"/api/publications/{fb_pub_id}/metrics/sync")
        assert r.status_code == 400
        assert "external_post_id" in r.json()["detail"]

        client.patch(f"/api/publications/{fb_pub_id}", json={"external_post_id": "123_456"})
        r = client.post(f"/api/publications/{fb_pub_id}/metrics/sync")
        assert r.status_code == 400
        assert "access token" in r.json()["detail"].lower()


def test_sync_metrics_from_meta_creates_a_metric_with_source_meta_sync(temp_db, monkeypatch):
    from app.api import publishing as publishing_module
    from app.services.ai.base import MetricsFetchResult

    class _FakePublisher:
        def __init__(self, access_token, api_version=None):
            self.access_token = access_token

        async def fetch_metrics(self, *, provider, external_post_id):
            assert provider == "facebook_page"
            assert external_post_id == "123_456"
            return MetricsFetchResult(success=True, metrics={"likes": 42, "reach": 500})

    monkeypatch.setattr(publishing_module, "MetaPublishingProvider", _FakePublisher)

    session = temp_db.SessionLocal()
    _, _, campaign = _make_brand_category_campaign(session, status="APPROVED")
    campaign_id = campaign.id
    session.close()

    with _client(temp_db) as client:
        client.patch("/api/settings", json={"facebook_page_access_token": "page-token"})
        r = client.post(
            f"/api/campaigns/{campaign_id}/publications",
            json={"provider": "facebook_page", "external_post_id": "123_456", "status": "published"},
        )
        pub_id = r.json()["id"]

        r = client.post(f"/api/publications/{pub_id}/metrics/sync")
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["source"] == "meta_sync"
        assert body["likes"] == 42
        assert body["reach"] == 500
        assert body["comments"] == 0  # not returned by the fake — defaulted, never fabricated as "found"


def test_sync_metrics_upstream_failure_is_surfaced_and_nothing_recorded(temp_db, monkeypatch):
    from app.api import publishing as publishing_module
    from app.services.ai.base import MetricsFetchResult

    class _FailingPublisher:
        def __init__(self, access_token, api_version=None):
            pass

        async def fetch_metrics(self, *, provider, external_post_id):
            return MetricsFetchResult(success=False, error="Invalid OAuth access token.")

    monkeypatch.setattr(publishing_module, "MetaPublishingProvider", _FailingPublisher)

    session = temp_db.SessionLocal()
    _, _, campaign = _make_brand_category_campaign(session, status="APPROVED")
    campaign_id = campaign.id
    session.close()

    with _client(temp_db) as client:
        client.patch("/api/settings", json={"facebook_page_access_token": "bad-token"})
        r = client.post(
            f"/api/campaigns/{campaign_id}/publications",
            json={"provider": "facebook_page", "external_post_id": "123_456", "status": "published"},
        )
        pub_id = r.json()["id"]

        r = client.post(f"/api/publications/{pub_id}/metrics/sync")
        assert r.status_code == 502
        assert r.json()["detail"] == "Invalid OAuth access token."

        r = client.get(f"/api/publications/{pub_id}/metrics")
        assert r.json() == []


def test_list_publications_filters_by_brand_status_and_provider(temp_db):
    session = temp_db.SessionLocal()
    brand, category, campaign = _make_brand_category_campaign(session, status="APPROVED")
    brand_id = brand.id
    campaign_id = campaign.id
    session.close()

    with _client(temp_db) as client:
        client.post(f"/api/campaigns/{campaign_id}/publications", json={"provider": "facebook_page", "status": "draft"})
        client.post(f"/api/campaigns/{campaign_id}/publications", json={"provider": "instagram", "status": "published"})

        r = client.get("/api/publications", params={"brand_id": brand_id})
        assert len(r.json()) == 2

        r = client.get("/api/publications", params={"brand_id": brand_id, "provider": "instagram"})
        assert len(r.json()) == 1
        assert r.json()[0]["provider"] == "instagram"

        r = client.get("/api/publications", params={"brand_id": brand_id, "status": "draft"})
        assert len(r.json()) == 1
        assert r.json()[0]["status"] == "draft"


def test_engagement_rate_math_and_denominator_fallback():
    from app.models import PerformanceMetric
    from app.services.analytics import engagement_rate

    m = PerformanceMetric(publication_id="x", reach=200, likes=10, comments=5, shares=3, saves=2)
    assert engagement_rate(m) == (10 + 5 + 3 + 2) / 200

    m_no_reach = PerformanceMetric(publication_id="x", impressions=500, likes=10, comments=0, shares=0, saves=0)
    assert engagement_rate(m_no_reach) == 10 / 500

    m_no_denominator = PerformanceMetric(publication_id="x", likes=10)
    assert engagement_rate(m_no_denominator) is None


def test_performance_summary_aggregates_totals_and_top_campaigns(temp_db):
    from app.models import PerformanceMetric, Publication
    from app.services.analytics import performance_summary

    session = temp_db.SessionLocal()
    brand, category, campaign = _make_brand_category_campaign(session, status="PUBLISHED")

    pub = Publication(campaign_id=campaign.id, provider="facebook_page", status="published")
    session.add(pub)
    session.commit()

    metric = PerformanceMetric(
        publication_id=pub.id, reach=1000, likes=50, comments=10, shares=5, saves=5,
        revenue=299.99, sales=3, recorded_at=datetime.now(timezone.utc),
    )
    session.add(metric)
    session.commit()

    summary = performance_summary(session, brand_id=brand.id, days=90)
    assert summary["totals"]["reach"] == 1000
    assert summary["totals"]["revenue"] == 299.99
    assert summary["totals"]["publications_with_data"] == 1
    assert len(summary["top_campaigns"]) == 1
    assert summary["top_campaigns"][0]["campaign_id"] == campaign.id
    session.close()


def test_calendar_endpoint_groups_publications_by_day(temp_db):
    from app.models import Publication

    session = temp_db.SessionLocal()
    brand, category, campaign = _make_brand_category_campaign(session, status="PUBLISHED")
    brand_id = brand.id
    published_at = datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc)
    pub = Publication(
        campaign_id=campaign.id, provider="facebook_page", status="published", published_at=published_at,
    )
    session.add(pub)
    session.commit()
    session.close()

    with _client(temp_db) as client:
        r = client.get("/api/analytics/calendar", params={"brand_id": brand_id, "year": 2026, "month": 6})
        assert r.status_code == 200
        body = r.json()
        assert body["days"][0]["date"] == "2026-06-15"
        assert body["days"][0]["publications"][0]["campaign_id"] == campaign.id

        # A different month has nothing.
        r = client.get("/api/analytics/calendar", params={"brand_id": brand_id, "year": 2026, "month": 7})
        assert r.json()["days"] == []


def test_average_engagement_rate_for_strategy_type_feeds_orchestrator_tiebreak(temp_db):
    """Direct unit test of the Phase 9 feedback loop: _select_underused_strategy_type
    picks the type with the higher recorded engagement rate when usage counts tie.
    """
    from app.models import (
        Campaign, CampaignStrategyFamily, CampaignStrategyType, PerformanceMetric, Publication,
    )
    from app.services.orchestrator import _select_underused_strategy_type

    session = temp_db.SessionLocal()
    brand, category, _unused = _make_brand_category_campaign(session, status="IDEA")

    family = CampaignStrategyFamily(key="ACQUIRE", name="Acquire")
    session.add(family)
    session.commit()
    type_a = CampaignStrategyType(key="type_a", name="Type A", family_id=family.id, objective="o", psychology=[])
    type_b = CampaignStrategyType(key="type_b", name="Type B", family_id=family.id, objective="o", psychology=[])
    session.add_all([type_a, type_b])
    session.commit()

    # Equal usage count (one campaign each) so the tie-break is what decides.
    camp_a = Campaign(
        display_id="HANNA-A-1", brand_id=brand.id, category_id=category.id, status="PUBLISHED",
        strategy_type_id=type_a.id,
    )
    camp_b = Campaign(
        display_id="HANNA-B-1", brand_id=brand.id, category_id=category.id, status="PUBLISHED",
        strategy_type_id=type_b.id,
    )
    session.add_all([camp_a, camp_b])
    session.commit()

    pub_a = Publication(campaign_id=camp_a.id, provider="facebook_page", status="published")
    pub_b = Publication(campaign_id=camp_b.id, provider="facebook_page", status="published")
    session.add_all([pub_a, pub_b])
    session.commit()

    # Type A performs much better than Type B.
    session.add(PerformanceMetric(publication_id=pub_a.id, reach=100, likes=80, comments=0, shares=0, saves=0))
    session.add(PerformanceMetric(publication_id=pub_b.id, reach=100, likes=1, comments=0, shares=0, saves=0))
    session.commit()

    selected = _select_underused_strategy_type(session, brand_id=brand.id, category_id=category.id)
    assert selected.id == type_a.id
    session.close()
