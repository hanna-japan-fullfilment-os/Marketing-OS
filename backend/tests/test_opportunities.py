"""Tests for opportunity discovery (services/opportunities.py) and its API +
manual campaign-community workflow (brief section 46). A FakeOpportunityProvider
implements the ResearchProvider Protocol's `discover_opportunities` the same way
FakeResearchProvider stands in for `research` — no network call or API key needed
to verify the "drop anything uncited" / upsert-not-duplicate logic.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.models import Brand, Campaign, CampaignOpportunity, Category, Opportunity
from app.schemas.ai import OpportunityDiscoveryResult, OpportunityRecommendation, ResearchQuery
from app.services.opportunities import build_opportunity_query, run_opportunity_discovery


class FakeOpportunityProvider:
    def __init__(self, result: OpportunityDiscoveryResult | None = None):
        self.call_count = 0
        self.result = result or OpportunityDiscoveryResult(
            recommendations=[
                OpportunityRecommendation(
                    platform="facebook_group",
                    name="J-Beauty Brasil Lovers",
                    url="https://facebook.com/groups/jbeautybrasil",
                    rationale="Active community of Brazilian J-beauty enthusiasts.",
                    estimated_relevance=0.9,
                    recommended_content_style="Casual, routine-focused posts, not ads.",
                    country="Brazil",
                    language="pt-BR",
                    audience_size=15000,
                    promo_allowed=False,
                    posting_rules="No direct selling; share routines/results instead.",
                    source_urls=["https://facebook.com/groups/jbeautybrasil"],
                ),
                OpportunityRecommendation(
                    platform="facebook_group",
                    name="An invented group the model made up",
                    rationale="This should never be persisted.",
                    estimated_relevance=0.95,
                    recommended_content_style="N/A",
                    source_urls=[],
                ),
            ]
        )

    async def research(self, query, *, model: str):
        raise AssertionError("research() should not be called by opportunity discovery")

    async def discover_opportunities(self, query: ResearchQuery, *, model: str) -> OpportunityDiscoveryResult:
        self.call_count += 1
        return self.result


def _query() -> ResearchQuery:
    return build_opportunity_query(
        brand_name="Hanna", category_name="Skincare", geography="Brazil", audience="J-beauty enthusiasts",
    )


async def test_run_opportunity_discovery_drops_uncited_recommendations(temp_db):
    session = temp_db.SessionLocal()
    brand = Brand(name="Hanna", slug="hanna")
    session.add(brand)
    session.commit()

    provider = FakeOpportunityProvider()
    outcome = await run_opportunity_discovery(
        session, provider=provider, query=_query(), brand_id=brand.id, category_id=None, model="gpt-5.1",
    )

    assert outcome.dropped_uncited == 1
    assert len(outcome.created) == 1
    assert outcome.created[0].name == "J-Beauty Brasil Lovers"
    assert outcome.created[0].source == "https://facebook.com/groups/jbeautybrasil"

    all_opps = session.query(Opportunity).filter(Opportunity.brand_id == brand.id).all()
    assert len(all_opps) == 1, "the uncited recommendation must never be persisted"
    session.close()


async def test_run_opportunity_discovery_upserts_by_platform_and_name(temp_db):
    session = temp_db.SessionLocal()
    brand = Brand(name="Hanna", slug="hanna")
    session.add(brand)
    session.commit()

    provider = FakeOpportunityProvider()
    await run_opportunity_discovery(
        session, provider=provider, query=_query(), brand_id=brand.id, category_id=None, model="gpt-5.1",
    )

    updated_result = OpportunityDiscoveryResult(
        recommendations=[
            OpportunityRecommendation(
                platform="facebook_group",
                name="J-Beauty Brasil Lovers",  # same group, refreshed relevance
                url="https://facebook.com/groups/jbeautybrasil",
                rationale="Still active, even bigger now.",
                estimated_relevance=0.6,
                recommended_content_style="Still casual.",
                source_urls=["https://facebook.com/groups/jbeautybrasil"],
            )
        ]
    )
    provider2 = FakeOpportunityProvider(result=updated_result)
    outcome2 = await run_opportunity_discovery(
        session, provider=provider2, query=_query(), brand_id=brand.id, category_id=None, model="gpt-5.1",
    )

    assert len(outcome2.created) == 0
    assert len(outcome2.updated) == 1
    assert outcome2.updated[0].estimated_relevance == 0.6

    all_opps = session.query(Opportunity).filter(Opportunity.brand_id == brand.id).all()
    assert len(all_opps) == 1, "re-discovering the same group must update it, not duplicate it"
    session.close()


# --------------------------------------------------------------------------------
# API endpoints
# --------------------------------------------------------------------------------


def test_discover_endpoint_requires_openai_configured(temp_db):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        r = client.post("/api/brands", json={"name": "Hanna", "slug": "hanna"})
        brand_id = r.json()["id"]

        r = client.post("/api/opportunities/discover", json={"brand_id": brand_id})
        assert r.status_code == 400
        assert "OpenAI" in r.json()["detail"]


def test_discover_endpoint_end_to_end_with_fake_provider(temp_db, monkeypatch):
    from fastapi.testclient import TestClient

    from app.api import opportunities as opportunities_module
    from app.main import app

    fake = FakeOpportunityProvider()
    monkeypatch.setattr(opportunities_module, "openai_provider_from_effective_settings", lambda effective: fake)

    with TestClient(app) as client:
        r = client.post("/api/brands", json={"name": "Hanna", "slug": "hanna"})
        brand_id = r.json()["id"]
        client.patch("/api/settings", json={"openai_api_key": "sk-test"})

        r = client.post("/api/opportunities/discover", json={"brand_id": brand_id})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["created"] == 1
        assert body["dropped_uncited"] == 1

        r = client.get("/api/opportunities", params={"brand_id": brand_id})
        assert r.status_code == 200
        listed = r.json()
        assert len(listed) == 1
        assert listed[0]["name"] == "J-Beauty Brasil Lovers"
        opp_id = listed[0]["id"]

        r = client.patch(f"/api/opportunities/{opp_id}", json={"favorite": True, "joined_status": "joined"})
        assert r.status_code == 200
        assert r.json()["favorite"] is True
        assert r.json()["joined_status"] == "joined"

        r = client.patch(f"/api/opportunities/{opp_id}", json={"blocked": True})
        assert r.status_code == 200
        r = client.get("/api/opportunities", params={"brand_id": brand_id})
        assert r.json() == [], "a blocked opportunity must not be listed"


def test_attach_opportunity_to_campaign_and_mark_posted(temp_db):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        session = temp_db.SessionLocal()
        brand = Brand(name="Hanna", slug="hanna")
        session.add(brand)
        session.commit()
        category = Category(brand_id=brand.id, name="Skincare", slug="skincare")
        session.add(category)
        session.commit()
        campaign = Campaign(
            display_id="HANNA-SKIN-000099", brand_id=brand.id, category_id=category.id, status="REVIEW",
            hook="Your skin deserves this", main_promise="Everything for a 5-step routine", cta="Shop now",
        )
        session.add(campaign)
        session.commit()
        opportunity = Opportunity(
            brand_id=brand.id, platform="facebook_group", name="J-Beauty Brasil Lovers",
            url="https://facebook.com/groups/jbeautybrasil", promo_allowed=False,
            posting_rules="No direct selling.", estimated_relevance=0.9,
            discovered_at=datetime.now(timezone.utc),
        )
        session.add(opportunity)
        session.commit()
        campaign_id, opportunity_id = campaign.id, opportunity.id
        session.close()

        r = client.post(f"/api/campaigns/{campaign_id}/opportunities", json={"opportunity_id": opportunity_id})
        assert r.status_code == 201, r.text
        body = r.json()
        assert "Your skin deserves this" in body["community_post_text"]
        assert "doesn't allow direct promotion" in body["community_post_text"]
        assert body["posted"] is False
        co_id = body["id"]

        r = client.get(f"/api/campaigns/{campaign_id}/opportunities")
        assert r.status_code == 200
        assert len(r.json()) == 1

        r = client.patch(
            f"/api/campaigns/{campaign_id}/opportunities/{co_id}",
            json={"posted": True, "community_post_text": "Edited draft I actually posted"},
        )
        assert r.status_code == 200
        assert r.json()["posted"] is True
        assert r.json()["posted_at"] is not None
        assert r.json()["community_post_text"] == "Edited draft I actually posted"

        session = temp_db.SessionLocal()
        co = session.get(CampaignOpportunity, co_id)
        opp = session.get(Opportunity, opportunity_id)
        assert co.posted is True
        assert opp.last_posted_at is not None
        session.close()
