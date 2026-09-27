"""Tests for research orchestration (services/research/openai_research.py) and its
API endpoint. A FakeResearchProvider stands in for OpenAIProvider throughout — these
tests never need a network call or an API key, which is the point: the caching and
no-fake-research logic is pure application code, independently testable.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.models import Brand, Category, ResearchRun
from app.schemas.ai import ResearchInsightItem, ResearchQuery, ResearchResult
from app.services.research.openai_research import (
    build_research_query,
    find_fresh_research_run,
    run_research,
)


class FakeResearchProvider:
    """Implements the ResearchProvider protocol with canned, controllable results
    and a call counter so tests can assert whether the cache was actually hit.
    """

    def __init__(self, result: ResearchResult | None = None):
        self.call_count = 0
        self.result = result or ResearchResult(
            insights=[
                ResearchInsightItem(
                    statement="Skincare routines with 5+ steps are trending on Brazilian TikTok this quarter.",
                    confidence=0.8,
                    freshness="this_quarter",
                    category="trend",
                    recommended_implication="Highlight routine-building in copy.",
                    source_urls=["https://example.com/trend-report"],
                ),
                ResearchInsightItem(
                    statement="An uncited claim the model should not have made up.",
                    confidence=0.9,
                    freshness="this_quarter",
                    category="trend",
                    recommended_implication="This should never be persisted.",
                    source_urls=[],
                ),
            ]
        )

    async def research(self, query: ResearchQuery, *, model: str) -> ResearchResult:
        self.call_count += 1
        return self.result


def _query() -> ResearchQuery:
    return build_research_query(
        brand_name="Hanna",
        category_name="Skincare",
        geography="Brazil",
        audience="Japanese beauty enthusiasts",
        objective="awareness",
    )


def test_build_research_query_maps_fields():
    q = build_research_query(
        brand_name="Hanna",
        category_name="Skincare",
        product_name="Serum X",
        geography="Brazil",
        audience="beauty enthusiasts",
        objective="sale",
        language="en",
    )
    assert q.brand_name == "Hanna"
    assert q.category == "Skincare"
    assert q.product == "Serum X"
    assert q.language == "en"


async def test_run_research_persists_only_cited_insights(temp_db):
    session = temp_db.SessionLocal()
    brand = Brand(name="Hanna", slug="hanna")
    session.add(brand)
    session.commit()

    provider = FakeResearchProvider()
    run, was_cached = await run_research(
        session,
        provider=provider,
        query=_query(),
        brand_id=brand.id,
        model="gpt-5.1",
        trend_ttl_hours=24,
        category_ttl_hours=168,
    )

    assert was_cached is False
    assert provider.call_count == 1
    assert len(run.insights) == 1, "the uncited insight must be dropped, not persisted"
    assert run.insights[0].statement.startswith("Skincare routines")
    assert len(run.sources) == 1
    assert run.sources[0].url == "https://example.com/trend-report"
    assert run.insights[0].source_ids == [run.sources[0].id]
    session.close()


async def test_run_research_dedupes_repeated_source_urls(temp_db):
    session = temp_db.SessionLocal()
    brand = Brand(name="Hanna", slug="hanna")
    session.add(brand)
    session.commit()

    shared_url = "https://example.com/shared"
    result = ResearchResult(
        insights=[
            ResearchInsightItem(
                statement="First insight citing the shared source.",
                confidence=0.7,
                freshness="this_month",
                category="trend",
                recommended_implication="",
                source_urls=[shared_url],
            ),
            ResearchInsightItem(
                statement="Second insight citing the same shared source.",
                confidence=0.6,
                freshness="this_month",
                category="trend",
                recommended_implication="",
                source_urls=[shared_url],
            ),
        ]
    )
    provider = FakeResearchProvider(result=result)
    run, _ = await run_research(
        session, provider=provider, query=_query(), brand_id=brand.id,
        model="gpt-5.1", trend_ttl_hours=24, category_ttl_hours=168,
    )

    assert len(run.sources) == 1, "the same URL cited twice should create one ResearchSource, not two"
    assert len(run.insights) == 2
    session.close()


async def test_run_research_cache_hit_does_not_call_provider_again(temp_db):
    session = temp_db.SessionLocal()
    brand = Brand(name="Hanna", slug="hanna")
    session.add(brand)
    session.commit()

    provider = FakeResearchProvider()
    run1, cached1 = await run_research(
        session, provider=provider, query=_query(), brand_id=brand.id,
        model="gpt-5.1", trend_ttl_hours=24, category_ttl_hours=168,
    )
    run2, cached2 = await run_research(
        session, provider=provider, query=_query(), brand_id=brand.id,
        model="gpt-5.1", trend_ttl_hours=24, category_ttl_hours=168,
    )

    assert cached1 is False
    assert cached2 is True
    assert run1.id == run2.id
    assert provider.call_count == 1, "a fresh cache hit must not re-call the provider"
    session.close()


async def test_run_research_force_refresh_bypasses_cache(temp_db):
    session = temp_db.SessionLocal()
    brand = Brand(name="Hanna", slug="hanna")
    session.add(brand)
    session.commit()

    provider = FakeResearchProvider()
    run1, _ = await run_research(
        session, provider=provider, query=_query(), brand_id=brand.id,
        model="gpt-5.1", trend_ttl_hours=24, category_ttl_hours=168,
    )
    run2, cached2 = await run_research(
        session, provider=provider, query=_query(), brand_id=brand.id,
        model="gpt-5.1", trend_ttl_hours=24, category_ttl_hours=168, force_refresh=True,
    )

    assert cached2 is False
    assert provider.call_count == 2
    assert run2.id != run1.id
    session.close()


async def test_expired_research_run_is_not_reused(temp_db):
    session = temp_db.SessionLocal()
    brand = Brand(name="Hanna", slug="hanna")
    session.add(brand)
    session.commit()

    provider = FakeResearchProvider()
    run1, _ = await run_research(
        session, provider=provider, query=_query(), brand_id=brand.id,
        model="gpt-5.1", trend_ttl_hours=24, category_ttl_hours=168,
    )
    # Force it into the past to simulate TTL having elapsed.
    stored = session.get(ResearchRun, run1.id)
    stored.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
    session.commit()

    assert find_fresh_research_run(session, brand_id=brand.id, category_id=None, product_id=None) is None

    run2, cached2 = await run_research(
        session, provider=provider, query=_query(), brand_id=brand.id,
        model="gpt-5.1", trend_ttl_hours=24, category_ttl_hours=168,
    )
    assert cached2 is False
    assert provider.call_count == 2
    session.close()


async def test_different_category_scope_does_not_share_cache(temp_db):
    session = temp_db.SessionLocal()
    brand = Brand(name="Hanna", slug="hanna")
    session.add(brand)
    session.commit()
    cat_a = Category(brand_id=brand.id, name="Skincare", slug="skincare")
    cat_b = Category(brand_id=brand.id, name="Snacks", slug="snacks")
    session.add_all([cat_a, cat_b])
    session.commit()

    provider = FakeResearchProvider()
    await run_research(
        session, provider=provider, query=_query(), brand_id=brand.id, category_id=cat_a.id,
        model="gpt-5.1", trend_ttl_hours=24, category_ttl_hours=168,
    )
    await run_research(
        session, provider=provider, query=_query(), brand_id=brand.id, category_id=cat_b.id,
        model="gpt-5.1", trend_ttl_hours=24, category_ttl_hours=168,
    )

    assert provider.call_count == 2, "a different category is a different scope and must not hit the other's cache"
    session.close()


# --------------------------------------------------------------------------------
# API endpoint
# --------------------------------------------------------------------------------


def test_trigger_research_requires_openai_configured(temp_db):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        r = client.post("/api/brands", json={"name": "Hanna", "slug": "hanna"})
        brand_id = r.json()["id"]

        r = client.post("/api/research/run", json={"brand_id": brand_id})
        assert r.status_code == 400
        assert "OpenAI" in r.json()["detail"]


def test_trigger_research_end_to_end_with_fake_provider(temp_db, monkeypatch):
    from fastapi.testclient import TestClient

    from app import api as api_package  # noqa: F401  (ensure package import order)
    from app.api import research as research_module
    from app.main import app

    fake = FakeResearchProvider()
    monkeypatch.setattr(research_module, "openai_provider_from_effective_settings", lambda effective: fake)

    with TestClient(app) as client:
        r = client.post("/api/brands", json={"name": "Hanna", "slug": "hanna"})
        brand_id = r.json()["id"]
        client.patch("/api/settings", json={"openai_api_key": "sk-test"})

        r = client.post("/api/research/run", json={"brand_id": brand_id, "objective": "awareness"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["was_cached"] is False
        assert body["insight_count"] == 1
        assert body["source_count"] == 1

        r = client.get(f"/api/research/runs/{body['id']}")
        assert r.status_code == 200
        detail = r.json()
        assert len(detail["insights"]) == 1
        assert detail["sources"][0]["url"] == "https://example.com/trend-report"

        # Second call within the TTL window should be a cache hit.
        r = client.post("/api/research/run", json={"brand_id": brand_id})
        assert r.status_code == 200
        assert r.json()["was_cached"] is True
        assert fake.call_count == 1

        r = client.get("/api/research/runs", params={"brand_id": brand_id})
        assert r.status_code == 200
        assert len(r.json()) == 1


def test_get_research_run_404_for_unknown_id(temp_db):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        r = client.get("/api/research/runs/does-not-exist")
        assert r.status_code == 404
