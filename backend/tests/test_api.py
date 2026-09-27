from __future__ import annotations

_LEGACY_VERIFIED_OPERATIONAL_STRATEGY_KEYS = (
    "abandoned_cart_campaign",
    "ambassador_campaign",
    "anti_ad",
    "before_after_campaign",
    "behind_the_scenes",
    "bundle_campaign",
    "community_challenges",
    "competitor_comparison",
    "competitor_counterattack",
    "contest_campaign",
    "countdown_campaign",
    "counter_marketing",
    "cross_sell_campaign",
    "cultural_campaign",
    "customer_appreciation",
    "customer_voting",
    "discovery_campaign",
    "early_access",
    "educational_campaign",
    "event_campaign",
    "flash_sale",
    "fomo_campaign",
    "founder_campaign",
    "gamification_campaign",
    "giveaway",
    "guerrilla_marketing",
    "influencer",
    "interactive_campaign",
    "japan_experience",
    "launch_campaign",
    "limited_edition_campaign",
    "localization_campaign",
    "loyalty_campaign",
    "meme_campaign",
    "micro_influencer",
    "mystery_campaign",
    "newsjacking",
    "paid_ads",
    "personalization_campaign",
    "personalized_offers",
    "price_attack",
    "price_match_response",
    "problem_solution_campaign",
    "product_drop",
    "product_selection",
    "quiz_campaign",
    "reactivation_campaign",
    "referral",
    "restock_campaign",
    "scarcity_campaign",
    "secret_drop",
    "share_of_voice_defense",
    "shock_curiosity_campaign",
    "social_proof_campaign",
    "storytelling_campaign",
    "subscription_campaign",
    "transparency_campaign",
    "trend_jacking",
    "ugc_campaign",
    "upsell_campaign",
    "value_bundle_defense",
    "vip_campaign",
    "viral_campaign",
    "win_back_campaign",
)


import time
from pathlib import Path


def _client(temp_db):
    from fastapi.testclient import TestClient

    from app.main import app

    return TestClient(app)


def _wait_for_job(client, job_id: str, *, timeout: float = 10.0) -> dict:
    """Polls `GET /api/jobs/{job_id}` until it reaches a terminal status.

    All four `/api/campaigns/{id}/generate*` endpoints now run their pipeline via
    `run_job_in_background` (services/jobs.py) and return `{job_id, job_status}`
    immediately rather than blocking until the run finishes (see api/campaigns.py's
    module docstring) — so any test that used to read the finished campaign state
    straight off the POST response now has to wait for the background task first,
    the same way the real frontend polls. The fake providers these tests use do no
    real network I/O, so completion is normally near-instant; the timeout is just a
    safety net against a genuine regression hanging the test suite.
    """
    deadline = time.time() + timeout
    data = {"status": "QUEUED"}
    while time.time() < deadline:
        r = client.get(f"/api/jobs/{job_id}")
        assert r.status_code == 200, r.text
        data = r.json()
        if data["status"] in ("COMPLETED", "FAILED"):
            return data
        time.sleep(0.02)
    raise AssertionError(f"Job {job_id} did not reach a terminal status within {timeout}s: {data}")


def test_brand_crud_and_settings_roundtrip(temp_db):
    with _client(temp_db) as client:
        r = client.post("/api/brands", json={"name": "Hanna", "slug": "hanna"})
        assert r.status_code == 201
        brand_id = r.json()["id"]

        r = client.get("/api/brands")
        assert r.status_code == 200
        assert len(r.json()) == 1

        r = client.patch("/api/settings", json={"source_asset_root": "/tmp/x"})
        assert r.status_code == 200
        assert r.json()["source_asset_root"] == "/tmp/x"

        # API key must never be echoed back.
        client.patch("/api/settings", json={"openai_api_key": "sk-secret"})
        r = client.get("/api/settings")
        assert "sk-secret" not in r.text
        assert r.json()["openai_configured"] is True

        r = client.get("/api/analytics/dashboard", params={"brand_id": brand_id})
        assert r.status_code == 200
        assert r.json()["source_assets_total"] == 0


def test_duplicate_brand_slug_rejected(temp_db):
    with _client(temp_db) as client:
        client.post("/api/brands", json={"name": "Hanna", "slug": "hanna"})
        r = client.post("/api/brands", json={"name": "Hanna Again", "slug": "hanna"})
        assert r.status_code == 409


def test_campaign_generate_endpoint_404s_for_unknown_campaign(temp_db):
    with _client(temp_db) as client:
        r = client.post("/api/campaigns/does-not-exist/generate")
        assert r.status_code == 404


def test_campaign_generate_endpoint_requires_openai_configured(temp_db, tmp_path):
    from app.models import Brand, Campaign

    with _client(temp_db) as client:
        client.patch("/api/settings", json={"output_root": str(tmp_path / "generated")})
        session = temp_db.SessionLocal()
        brand = Brand(name="Hanna", slug="hanna")
        session.add(brand)
        session.commit()
        campaign = Campaign(display_id="HANNA-SKIN-000002", brand_id=brand.id, status="IDEA")
        session.add(campaign)
        session.commit()
        campaign_id = campaign.id
        session.close()

        r = client.post(f"/api/campaigns/{campaign_id}/generate")
        assert r.status_code == 400
        assert "OpenAI" in r.json()["detail"]


def test_campaign_generate_endpoint_end_to_end_with_fake_provider(temp_db, tmp_path, monkeypatch):
    from PIL import Image

    from app.models import Asset, Brand, Campaign, Category
    from app.api import campaigns as campaigns_module
    from app.schemas.ai import (
        CampaignCopy, CampaignStrategy, CampaignStrategyCandidates, CarouselPlan,
        CreativeBrief, ResearchInsightItem, ResearchResult, SlidePlan,
    )
    from app.schemas.creative_director import (
        CreativeDirection, MasterCampaignConcept, PlatformAdaptation, VideoConcept,
    )

    class _FakeProvider:
        """Minimal local stand-in for AIProvider + ResearchProvider — a slimmer
        cousin of tests/test_orchestrator.py's FakeAutopilotProvider, kept local so
        this file doesn't depend on test-module cross-imports.
        """

        def __init__(self):
            self.research_calls = 0

        async def generate_structured(self, *, system, user, schema, model):
            if schema is CampaignStrategyCandidates:
                return CampaignStrategyCandidates(
                    candidates=[
                        CampaignStrategy(
                            objective="awareness", audience="Young adults in Brazil",
                            funnel_stage="tofu", insight="Routines are trending",
                            angle="Build your routine", key_message="Everything for a 5-step routine",
                            reason_this_should_work="Rides the current trend.",
                        )
                    ]
                )
            if schema is CreativeBrief:
                return CreativeBrief(
                    design_concept="Clean hero shot", visual_prompt="Product on a gradient",
                    template_suggestion="premium_product_hero", tone_notes="Warm",
                )
            if schema is CampaignCopy:
                return CampaignCopy(
                    hook="Your skin deserves this", headline="Straight from Japan",
                    supporting_copy="Sourced firsthand, shipped to Brazil.", cta="Shop now",
                    caption="Straight from Japan.", hashtags=["#skincare"],
                    alt_text="Product bottle on a gradient background",
                )
            if schema is CarouselPlan:
                return CarouselPlan(
                    slides=[
                        SlidePlan(slide_number=1, purpose="hero", headline="Slide one", body="Body one",
                                  cta="Shop now", visual_brief="Hero shot"),
                        SlidePlan(slide_number=2, purpose="benefit", headline="Slide two", body="Body two",
                                  cta="Shop now", visual_brief="Detail shot"),
                    ],
                    narrative_summary="A two-slide carousel.",
                )
            if schema is MasterCampaignConcept:
                return MasterCampaignConcept(
                    concept_name="Everyday Ritual",
                    campaign_promise="A simple routine that actually fits your day",
                    key_message="Everything you need for a 5-step routine",
                    emotional_goal="Confidence in a simple daily ritual",
                    audience="Young adults in Brazil",
                    objective="awareness",
                    visual_identity="Clean hero shot on a warm gradient",
                    story_arc="Open on the product, reveal the routine, close on the result",
                    cta_intent="Encourage trying the routine",
                )
            if schema is PlatformAdaptation:
                return PlatformAdaptation(
                    platform="instagram",
                    adaptation_strategy="visual storytelling carousel — one idea per slide",
                    narrative_shape="Open on the product, reveal the routine, close on the result",
                    tone_adjustment="warm, aspirational",
                    content_type="carousel",
                    reasoning="Fake canned adaptation for tests.",
                )
            if schema is CreativeDirection:
                return CreativeDirection(
                    concept_name="Everyday Ritual", platform="instagram", content_type="carousel",
                    language="pt-BR", campaign_visual_identity="Clean hero shot on a warm gradient",
                    rationale="Fake canned creative direction for tests.",
                    background_concept="Soft warm gradient studio backdrop",
                    scene_generation_prompt="Soft warm gradient studio backdrop, no text, no logos, no products.",
                )
            if schema is VideoConcept:
                return VideoConcept(
                    hook="Your 5-step routine starts here",
                    script="Open on the product. Walk through the 5 steps. Close on the result.",
                    shot_list=["Product hero shot", "Routine steps in sequence", "Final result close-up"],
                    caption="Everything you need for a 5-step routine.",
                )
            raise AssertionError(f"Unexpected schema: {schema}")

        async def vision_describe(self, *, image_path, prompt, model):
            return ""

        async def research(self, query, *, model):
            self.research_calls += 1
            return ResearchResult(
                insights=[
                    ResearchInsightItem(
                        statement="Multi-step skincare routines are trending in Brazil.",
                        confidence=0.8, freshness="this_quarter", category="trend",
                        recommended_implication="Emphasize routine-building.",
                        source_urls=["https://example.com/trend-report"],
                    )
                ]
            )

    output_root = tmp_path / "generated"
    fake = _FakeProvider()
    monkeypatch.setattr(campaigns_module, "openai_provider_from_effective_settings", lambda api_key: fake)

    with _client(temp_db) as client:
        client.patch("/api/settings", json={"output_root": str(output_root), "openai_api_key": "sk-test"})

        session = temp_db.SessionLocal()
        brand = Brand(name="Hanna", slug="hanna", colors={"primary": "#f2ede3", "secondary": "#d8c9ad"}, campaign_rules={"verified_operational_strategy_keys": list(_LEGACY_VERIFIED_OPERATIONAL_STRATEGY_KEYS)})
        session.add(brand)
        session.commit()
        category = Category(brand_id=brand.id, name="Skincare", slug="skincare")
        session.add(category)
        session.commit()
        campaign = Campaign(
            display_id="HANNA-SKIN-000003", brand_id=brand.id, category_id=category.id, status="IDEA",
        )
        session.add(campaign)
        session.commit()
        for i in range(3):
            img_path = tmp_path / f"asset-{i}.jpg"
            Image.new("RGB", (800, 800), (10 + i * 20, 50, 200)).save(img_path)
            session.add(
                Asset(
                    brand_id=brand.id, category_id=category.id, absolute_path=str(img_path),
                    relative_path=f"skincare/asset-{i}.jpg", filename=f"asset-{i}.jpg",
                    extension=".jpg", sha256=f"sha-{i}", width=800, height=800,
                )
            )
        session.commit()
        campaign_id = campaign.id
        session.close()

        r = client.post(f"/api/campaigns/{campaign_id}/generate")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["job_status"] == "QUEUED"  # returns immediately, before the run finishes
        job = _wait_for_job(client, body["job_id"])
        assert job["status"] == "COMPLETED", job

        r = client.get(f"/api/campaigns/{campaign_id}")
        assert r.status_code == 200
        detail = r.json()
        assert detail["status"] == "REVIEW"
        assert len(detail["slides"]) == 2

        # Re-running while not IDEA/FAILED is rejected rather than silently re-generating.
        r = client.post(f"/api/campaigns/{campaign_id}/generate")
        assert r.status_code == 400


def test_campaign_generate_endpoint_recreates_images_with_verified_fidelity_when_opted_in(
    temp_db, tmp_path, monkeypatch
):
    """`recreate_with_ai` history on `POST /generate` (the main "Run Autopilot"
    flow) — see that endpoint's own docstring for the full story: true in rounds
    15-16, false in round 17 (full AI recreation proved unreliable against real
    campaigns), true again in round 18 (paired with a fidelity gate — every
    recreation is checked against the real source product photo via
    `AIProvider.check_product_fidelity` before it's trusted), and **false again**
    as of Build 1 (Part D) — full recreation, still passing through the same
    fidelity gate, is now an explicit opt-in rather than the everyday default;
    see docs/campaign-pipeline.md's Build 1 section. This test now exercises the
    explicit-opt-in path directly (`recreate_with_ai=true`): it MUST reach the
    image provider's `generate()` AND the fidelity check (the safety net is
    actually wired up), and a verified PASS must be what lets the recreated image
    through. `test_campaign_generate_endpoint_end_to_end_with_fake_provider`
    (elsewhere in this file) is the regression test for the new false-by-default
    behavior. Explicit opt-out and the retry/fallback paths are covered at the
    service layer by test_orchestrator.py's dedicated fidelity-gate tests.
    """
    from PIL import Image

    from app.models import Asset, Brand, Campaign, Category
    from app.api import campaigns as campaigns_module
    from app.schemas.ai import (
        CampaignCopy, CampaignStrategy, CampaignStrategyCandidates, CarouselPlan,
        CreativeBrief, ProductFidelityCheck, ResearchInsightItem, ResearchResult, SlidePlan,
    )
    from app.schemas.creative_director import (
        CreativeDirection, MasterCampaignConcept, PlatformAdaptation, VideoConcept,
    )

    class _FakeProviderWithImages:
        """Same shape as `test_campaign_generate_endpoint_end_to_end_with_fake_provider`'s
        `_FakeProvider`, plus a real `ImageProvider.generate` implementation and a
        `check_product_fidelity` that always PASSes, so this test can assert the
        round-18 default (`recreate_with_ai=True`) actually reaches both.
        """

        def __init__(self):
            self.research_calls = 0
            self.image_calls: list[dict] = []
            self.fidelity_calls: list[dict] = []

        async def generate_structured(self, *, system, user, schema, model):
            if schema is CampaignStrategyCandidates:
                return CampaignStrategyCandidates(
                    candidates=[
                        CampaignStrategy(
                            objective="awareness", audience="Young adults in Brazil",
                            funnel_stage="tofu", insight="Routines are trending",
                            angle="Build your routine", key_message="Everything for a 5-step routine",
                            reason_this_should_work="Rides the current trend.",
                        )
                    ]
                )
            if schema is CreativeBrief:
                return CreativeBrief(
                    design_concept="Clean hero shot", visual_prompt="Product on a gradient",
                    template_suggestion="premium_product_hero", tone_notes="Warm",
                )
            if schema is CampaignCopy:
                return CampaignCopy(
                    hook="Your skin deserves this", headline="Straight from Japan",
                    supporting_copy="Sourced firsthand, shipped to Brazil.", cta="Shop now",
                    caption="Straight from Japan.", hashtags=["#skincare"],
                    alt_text="Product bottle on a gradient background",
                )
            if schema is CarouselPlan:
                return CarouselPlan(
                    slides=[
                        SlidePlan(slide_number=1, purpose="hero", headline="Slide one", body="Body one",
                                  cta="Shop now", visual_brief="Hero shot"),
                        SlidePlan(slide_number=2, purpose="benefit", headline="Slide two", body="Body two",
                                  cta="Shop now", visual_brief="Detail shot"),
                    ],
                    narrative_summary="A two-slide carousel.",
                )
            if schema is MasterCampaignConcept:
                return MasterCampaignConcept(
                    concept_name="Everyday Ritual",
                    campaign_promise="A simple routine that actually fits your day",
                    key_message="Everything you need for a 5-step routine",
                    emotional_goal="Confidence in a simple daily ritual",
                    audience="Young adults in Brazil",
                    objective="awareness",
                    visual_identity="Clean hero shot on a warm gradient",
                    story_arc="Open on the product, reveal the routine, close on the result",
                    cta_intent="Encourage trying the routine",
                )
            if schema is PlatformAdaptation:
                return PlatformAdaptation(
                    platform="instagram",
                    adaptation_strategy="visual storytelling carousel — one idea per slide",
                    narrative_shape="Open on the product, reveal the routine, close on the result",
                    tone_adjustment="warm, aspirational",
                    content_type="carousel",
                    reasoning="Fake canned adaptation for tests.",
                )
            if schema is CreativeDirection:
                return CreativeDirection(
                    concept_name="Everyday Ritual", platform="instagram", content_type="carousel",
                    language="pt-BR", campaign_visual_identity="Clean hero shot on a warm gradient",
                    rationale="Fake canned creative direction for tests.",
                    background_concept="Soft warm gradient studio backdrop",
                    scene_generation_prompt="Soft warm gradient studio backdrop, no text, no logos, no products.",
                )
            if schema is VideoConcept:
                return VideoConcept(
                    hook="Your 5-step routine starts here",
                    script="Open on the product. Walk through the 5 steps. Close on the result.",
                    shot_list=["Product hero shot", "Routine steps in sequence", "Final result close-up"],
                    caption="Everything you need for a 5-step routine.",
                )
            raise AssertionError(f"Unexpected schema: {schema}")

        async def vision_describe(self, *, image_path, prompt, model):
            return ""

        async def research(self, query, *, model):
            self.research_calls += 1
            return ResearchResult(
                insights=[
                    ResearchInsightItem(
                        statement="Multi-step skincare routines are trending in Brazil.",
                        confidence=0.8, freshness="this_quarter", category="trend",
                        recommended_implication="Emphasize routine-building.",
                        source_urls=["https://example.com/trend-report"],
                    )
                ]
            )

        async def generate(self, *, prompt, size, model, reference_images=None, quality="high"):
            self.image_calls.append({"prompt": prompt, "reference_images": reference_images})
            import io
            buf = io.BytesIO()
            Image.new("RGB", (64, 64), (5, 5, 5)).save(buf, format="PNG")
            return buf.getvalue()

        async def check_product_fidelity(self, *, source_image_path, generated_image_path, model):
            self.fidelity_calls.append(
                {"source_image_path": source_image_path, "generated_image_path": generated_image_path}
            )
            return ProductFidelityCheck(overall_verdict="PASS", reasoning="Matches the reference photo.")

    output_root = tmp_path / "generated"
    fake = _FakeProviderWithImages()
    monkeypatch.setattr(campaigns_module, "openai_provider_from_effective_settings", lambda api_key: fake)

    with _client(temp_db) as client:
        client.patch("/api/settings", json={"output_root": str(output_root), "openai_api_key": "sk-test"})

        session = temp_db.SessionLocal()
        brand = Brand(name="Hanna", slug="hanna", colors={"primary": "#f2ede3", "secondary": "#d8c9ad"})
        session.add(brand)
        session.commit()
        category = Category(brand_id=brand.id, name="Skincare", slug="skincare")
        session.add(category)
        session.commit()
        campaign = Campaign(
            display_id="HANNA-SKIN-000004", brand_id=brand.id, category_id=category.id, status="IDEA",
        )
        session.add(campaign)
        session.commit()
        asset_paths = []
        for i in range(3):
            img_path = tmp_path / f"asset-{i}.jpg"
            Image.new("RGB", (800, 800), (10 + i * 20, 50, 200)).save(img_path)
            asset_paths.append(img_path)
            session.add(
                Asset(
                    brand_id=brand.id, category_id=category.id, absolute_path=str(img_path),
                    relative_path=f"skincare/asset-{i}.jpg", filename=f"asset-{i}.jpg",
                    extension=".jpg", sha256=f"sha-{i}", width=800, height=800,
                )
            )
        session.commit()
        campaign_id = campaign.id
        session.close()

        # Build 1: recreate_with_ai now defaults to false, so this test opts in
        # explicitly to exercise the fidelity-gated recreation path.
        # Build 6R immutable-product-layer contract.
        # The old API flag may still be supplied for compatibility,
        # but full AI recreation of authentic product/package pixels
        # must fail before any image-generation or fidelity call.
        r = client.post(
            f"/api/campaigns/{campaign_id}/generate?recreate_with_ai=true"
        )
        assert r.status_code == 200, r.text
        job = _wait_for_job(
            client,
            r.json()["job_id"],
        )

        assert job["status"] == "FAILED", job
        assert fake.image_calls == [], fake.image_calls
        assert fake.fidelity_calls == [], fake.fidelity_calls


def test_delete_campaign_removes_record_files_and_cascades(temp_db, tmp_path):
    """DELETE /api/campaigns/{id} removes the campaign row, cascades (via DB-level
    ondelete=CASCADE — see models/campaign.py, models/opportunity.py,
    models/publishing.py) to its slides/outputs/fingerprint/publications/
    opportunity-drafts, cleans up its own Job history (not a real foreign key —
    see models/platform.py), and best-effort deletes the real files those rows
    pointed at — without touching an Opportunity itself, which isn't scoped to one
    campaign.
    """
    from datetime import datetime, timezone

    from app.models import (
        Brand, Campaign, CampaignFingerprint, CampaignOpportunity, CampaignOutput,
        CampaignSlide, Job, Opportunity, Publication,
    )

    with _client(temp_db) as client:
        session = temp_db.SessionLocal()
        brand = Brand(name="Hanna", slug="hanna")
        session.add(brand)
        session.commit()
        campaign = Campaign(display_id="HANNA-SKIN-000010", brand_id=brand.id, status="PUBLISHED")
        session.add(campaign)
        session.commit()
        campaign_id = campaign.id

        # Real files this campaign "owns" on disk, referenced by DB rows exactly the
        # way the render pipeline / stage-json persistence normally would.
        slide_path = tmp_path / "slide-01.png"
        slide_path.write_bytes(b"fake-png-bytes")
        bg_path = tmp_path / "bg-01.png"
        bg_path.write_bytes(b"fake-bg-bytes")
        output_path = tmp_path / "copy.json"
        output_path.write_text("{}")

        session.add(CampaignSlide(
            campaign_id=campaign.id, slide_number=1, headline="Hi",
            rendered_asset_path=str(slide_path), generated_background_path=str(bg_path),
        ))
        session.add(CampaignOutput(campaign_id=campaign.id, kind="copy", file_path=str(output_path)))
        session.add(CampaignFingerprint(
            campaign_id=campaign.id, text_hash="abc", computed_at=datetime.now(timezone.utc),
        ))
        session.add(Publication(campaign_id=campaign.id, provider="facebook_page", status="published"))
        opportunity = Opportunity(brand_id=brand.id, platform="facebook_group", name="Test Group")
        session.add(opportunity)
        session.commit()
        session.add(CampaignOpportunity(campaign_id=campaign.id, opportunity_id=opportunity.id))
        session.add(Job(type="autopilot_campaign", campaign_id=campaign.id, status="COMPLETED"))
        session.commit()
        opportunity_id = opportunity.id
        session.close()

        assert slide_path.exists() and bg_path.exists() and output_path.exists()

        r = client.delete(f"/api/campaigns/{campaign_id}")
        assert r.status_code == 204, r.text

        assert not slide_path.exists()
        assert not bg_path.exists()
        assert not output_path.exists()

        r = client.get(f"/api/campaigns/{campaign_id}")
        assert r.status_code == 404

        session = temp_db.SessionLocal()
        assert session.query(CampaignSlide).filter(CampaignSlide.campaign_id == campaign_id).count() == 0
        assert session.query(CampaignOutput).filter(CampaignOutput.campaign_id == campaign_id).count() == 0
        assert session.query(CampaignFingerprint).filter(CampaignFingerprint.campaign_id == campaign_id).count() == 0
        assert session.query(Publication).filter(Publication.campaign_id == campaign_id).count() == 0
        assert session.query(CampaignOpportunity).filter(CampaignOpportunity.campaign_id == campaign_id).count() == 0
        assert session.query(Job).filter(Job.campaign_id == campaign_id).count() == 0
        # The opportunity itself isn't campaign-scoped and must survive.
        assert session.get(Opportunity, opportunity_id) is not None
        session.close()


def test_delete_campaign_404s_for_unknown_campaign(temp_db):
    with _client(temp_db) as client:
        r = client.delete("/api/campaigns/does-not-exist")
        assert r.status_code == 404


def test_delete_campaign_refused_while_job_active(temp_db):
    """Deleting a campaign with a QUEUED/RUNNING background job would otherwise let
    that job fail confusingly trying to write to a campaign that no longer exists
    — refused with a clear 409 instead, and the campaign is left untouched.
    """
    from app.models import Brand, Campaign, Job

    with _client(temp_db) as client:
        session = temp_db.SessionLocal()
        brand = Brand(name="Hanna", slug="hanna")
        session.add(brand)
        session.commit()
        campaign = Campaign(display_id="HANNA-SKIN-000011", brand_id=brand.id, status="GENERATING")
        session.add(campaign)
        session.commit()
        campaign_id = campaign.id
        session.add(Job(type="autopilot_campaign", campaign_id=campaign.id, status="RUNNING"))
        session.commit()
        session.close()

        r = client.delete(f"/api/campaigns/{campaign_id}")
        assert r.status_code == 409

        r = client.get(f"/api/campaigns/{campaign_id}")
        assert r.status_code == 200


def test_campaign_builder_advanced_mode_stage_endpoints(temp_db, tmp_path, monkeypatch):
    """The Campaign Builder advanced mode: /generate/strategy, /generate/copy, and
    /generate/visuals called as three separate HTTP requests, plus the guard that
    each stage 400s with a clear message if the prior one hasn't run yet.
    """
    from PIL import Image

    from app.models import Asset, Brand, Campaign, Category
    from app.api import campaigns as campaigns_module
    from app.schemas.ai import (
        CampaignCopy, CampaignStrategy, CampaignStrategyCandidates, CarouselPlan,
        CreativeBrief, ResearchInsightItem, ResearchResult, SlidePlan,
    )
    from app.schemas.creative_director import (
        CreativeDirection, MasterCampaignConcept, PlatformAdaptation, VideoConcept,
    )

    class _FakeProvider:
        def __init__(self):
            self.research_calls = 0

        async def generate_structured(self, *, system, user, schema, model):
            if schema is CampaignStrategyCandidates:
                return CampaignStrategyCandidates(
                    candidates=[
                        CampaignStrategy(
                            objective="awareness", audience="Young adults in Brazil",
                            funnel_stage="tofu", insight="Routines are trending",
                            angle="Build your routine", key_message="Everything for a 5-step routine",
                            reason_this_should_work="Rides the current trend.",
                        )
                    ]
                )
            if schema is CreativeBrief:
                return CreativeBrief(
                    design_concept="Clean hero shot", visual_prompt="Product on a gradient",
                    template_suggestion="premium_product_hero", tone_notes="Warm",
                )
            if schema is CampaignCopy:
                return CampaignCopy(
                    hook="Your skin deserves this", headline="Straight from Japan",
                    supporting_copy="Sourced firsthand, shipped to Brazil.", cta="Shop now",
                    caption="Straight from Japan.", hashtags=["#skincare"],
                    alt_text="Product bottle on a gradient background",
                )
            if schema is CarouselPlan:
                return CarouselPlan(
                    slides=[
                        SlidePlan(slide_number=1, purpose="hero", headline="Slide one", body="Body one",
                                  cta="Shop now", visual_brief="Hero shot"),
                        SlidePlan(slide_number=2, purpose="benefit", headline="Slide two", body="Body two",
                                  cta="Shop now", visual_brief="Detail shot"),
                    ],
                    narrative_summary="A two-slide carousel.",
                )
            if schema is MasterCampaignConcept:
                return MasterCampaignConcept(
                    concept_name="Everyday Ritual",
                    campaign_promise="A simple routine that actually fits your day",
                    key_message="Everything you need for a 5-step routine",
                    emotional_goal="Confidence in a simple daily ritual",
                    audience="Young adults in Brazil",
                    objective="awareness",
                    visual_identity="Clean hero shot on a warm gradient",
                    story_arc="Open on the product, reveal the routine, close on the result",
                    cta_intent="Encourage trying the routine",
                )
            if schema is PlatformAdaptation:
                return PlatformAdaptation(
                    platform="instagram",
                    adaptation_strategy="visual storytelling carousel — one idea per slide",
                    narrative_shape="Open on the product, reveal the routine, close on the result",
                    tone_adjustment="warm, aspirational",
                    content_type="carousel",
                    reasoning="Fake canned adaptation for tests.",
                )
            if schema is CreativeDirection:
                return CreativeDirection(
                    concept_name="Everyday Ritual", platform="instagram", content_type="carousel",
                    language="pt-BR", campaign_visual_identity="Clean hero shot on a warm gradient",
                    rationale="Fake canned creative direction for tests.",
                    background_concept="Soft warm gradient studio backdrop",
                    scene_generation_prompt="Soft warm gradient studio backdrop, no text, no logos, no products.",
                )
            if schema is VideoConcept:
                return VideoConcept(
                    hook="Your 5-step routine starts here",
                    script="Open on the product. Walk through the 5 steps. Close on the result.",
                    shot_list=["Product hero shot", "Routine steps in sequence", "Final result close-up"],
                    caption="Everything you need for a 5-step routine.",
                )
            raise AssertionError(f"Unexpected schema: {schema}")

        async def vision_describe(self, *, image_path, prompt, model):
            return ""

        async def research(self, query, *, model):
            self.research_calls += 1
            return ResearchResult(
                insights=[
                    ResearchInsightItem(
                        statement="Multi-step skincare routines are trending in Brazil.",
                        confidence=0.8, freshness="this_quarter", category="trend",
                        recommended_implication="Emphasize routine-building.",
                        source_urls=["https://example.com/trend-report"],
                    )
                ]
            )

    output_root = tmp_path / "generated"
    fake = _FakeProvider()
    monkeypatch.setattr(campaigns_module, "openai_provider_from_effective_settings", lambda api_key: fake)

    with _client(temp_db) as client:
        client.patch("/api/settings", json={"output_root": str(output_root), "openai_api_key": "sk-test"})

        session = temp_db.SessionLocal()
        brand = Brand(name="Hanna", slug="hanna", colors={"primary": "#f2ede3", "secondary": "#d8c9ad"}, campaign_rules={"verified_operational_strategy_keys": list(_LEGACY_VERIFIED_OPERATIONAL_STRATEGY_KEYS)})
        session.add(brand)
        session.commit()
        category = Category(brand_id=brand.id, name="Skincare", slug="skincare")
        session.add(category)
        session.commit()
        campaign = Campaign(
            display_id="HANNA-SKIN-000004", brand_id=brand.id, category_id=category.id, status="IDEA",
        )
        session.add(campaign)
        session.commit()
        for i in range(3):
            img_path = tmp_path / f"adv-asset-{i}.jpg"
            Image.new("RGB", (800, 800), (10 + i * 20, 50, 200)).save(img_path)
            session.add(
                Asset(
                    brand_id=brand.id, category_id=category.id, absolute_path=str(img_path),
                    relative_path=f"skincare/adv-asset-{i}.jpg", filename=f"adv-asset-{i}.jpg",
                    extension=".jpg", sha256=f"adv-sha-{i}", width=800, height=800,
                )
            )
        session.commit()
        campaign_id = campaign.id
        session.close()

        # Copy/Visuals both refuse to run before their prerequisite stage.
        r = client.post(f"/api/campaigns/{campaign_id}/generate/copy")
        assert r.status_code == 400
        assert "Strategy" in r.json()["detail"]
        r = client.post(f"/api/campaigns/{campaign_id}/generate/visuals")
        assert r.status_code == 400
        assert "Copy" in r.json()["detail"]

        r = client.post(f"/api/campaigns/{campaign_id}/generate/strategy")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["job_status"] == "QUEUED"  # returns immediately, before the run finishes
        job = _wait_for_job(client, body["job_id"])
        assert job["status"] == "COMPLETED", job

        detail = client.get(f"/api/campaigns/{campaign_id}").json()
        assert detail["status"] == "BRIEF_READY"
        # Angle may come from an auto-selected seeded Strategy Library type rather
        # than the fake candidate's angle (a real strategy_type_id takes precedence
        # over the AI-proposed angle — see run_strategy_stage) — just confirm one
        # was actually set, and that copy hasn't run yet.
        assert detail["angle"]
        assert detail["hook"] == ""  # copy hasn't run yet

        # Visuals still refuses — Copy hasn't run yet, even though Strategy has.
        r = client.post(f"/api/campaigns/{campaign_id}/generate/visuals")
        assert r.status_code == 400
        assert "Copy" in r.json()["detail"]

        r = client.post(f"/api/campaigns/{campaign_id}/generate/copy")
        assert r.status_code == 200, r.text
        job = _wait_for_job(client, r.json()["job_id"])
        assert job["status"] == "COMPLETED", job

        detail = client.get(f"/api/campaigns/{campaign_id}").json()
        assert detail["status"] == "COPY_READY"
        assert detail["hook"] == "Your skin deserves this"
        assert len(detail["slides"]) == 0  # nothing rendered yet

        # Visuals needs no OpenAI key at all — remove it and confirm it still works.
        client.patch("/api/settings", json={"openai_api_key": ""})
        r = client.post(f"/api/campaigns/{campaign_id}/generate/visuals")
        assert r.status_code == 200, r.text
        job = _wait_for_job(client, r.json()["job_id"])
        assert job["status"] == "COMPLETED", job

        detail = client.get(f"/api/campaigns/{campaign_id}").json()
        assert detail["status"] == "REVIEW"
        assert len(detail["slides"]) == 2
        assert fake.research_calls == 1


def test_create_campaign_from_strategy_library_type(temp_db):
    with _client(temp_db) as client:
        r = client.post("/api/brands", json={"name": "Hanna", "slug": "hanna"})
        brand_id = r.json()["id"]
        r = client.post("/api/categories", json={"brand_id": brand_id, "name": "Skincare", "slug": "skincare"})
        category_id = r.json()["id"]

        r = client.post(
            "/api/campaigns",
            json={"brand_id": brand_id, "category_id": category_id, "strategy_type_key": "flash_sale"},
        )
        assert r.status_code == 201
        body = r.json()
        assert body["status"] == "IDEA"
        assert body["display_id"].startswith("HANNA-SKINC-")

        r = client.get("/api/campaigns", params={"brand_id": brand_id})
        assert r.status_code == 200
        assert r.json()[0]["strategy_type_name"] == "Flash Sale"


def test_create_campaign_rejects_unknown_strategy_key(temp_db):
    with _client(temp_db) as client:
        r = client.post("/api/brands", json={"name": "Hanna", "slug": "hanna"})
        brand_id = r.json()["id"]
        r = client.post("/api/campaigns", json={"brand_id": brand_id, "strategy_type_key": "not-a-real-type"})
        assert r.status_code == 404


def test_campaign_approve_requires_review_status(temp_db):
    from app.models import Brand, Campaign

    with _client(temp_db) as client:
        session = temp_db.SessionLocal()
        brand = Brand(name="Hanna", slug="hanna")
        session.add(brand)
        session.commit()
        campaign = Campaign(display_id="HANNA-SKIN-000001", brand_id=brand.id, status="IDEA")
        session.add(campaign)
        session.commit()
        campaign_id = campaign.id
        session.close()

        r = client.post(f"/api/campaigns/{campaign_id}/approve")
        assert r.status_code == 400

        session = temp_db.SessionLocal()
        c = session.get(Campaign, campaign_id)
        c.status = "REVIEW"
        session.commit()
        session.close()

        r = client.post(f"/api/campaigns/{campaign_id}/approve")
        assert r.status_code == 200
        assert r.json()["status"] == "APPROVED"


def test_update_campaign_sets_and_clears_target_slide_count(temp_db):
    """Round 16: `PATCH /api/campaigns/{id}` lets the user set an exact carousel
    length on the campaign itself, editable any time, and clear it back to null
    (letting Autopilot's carousel planner use its own judgment again) — the
    `CampaignUpdate` schema uses `model_fields_set` so an explicit `null` clears the
    field rather than being indistinguishable from "not provided".
    """
    from app.models import Brand, Campaign

    with _client(temp_db) as client:
        session = temp_db.SessionLocal()
        brand = Brand(name="Hanna", slug="hanna")
        session.add(brand)
        session.commit()
        campaign = Campaign(display_id="HANNA-SKIN-000003", brand_id=brand.id, status="IDEA")
        session.add(campaign)
        session.commit()
        campaign_id = campaign.id
        session.close()

        r = client.get(f"/api/campaigns/{campaign_id}")
        assert r.status_code == 200
        assert r.json()["target_slide_count"] is None

        r = client.patch(f"/api/campaigns/{campaign_id}", json={"target_slide_count": 4})
        assert r.status_code == 200
        assert r.json()["target_slide_count"] == 4

        r = client.get(f"/api/campaigns/{campaign_id}")
        assert r.json()["target_slide_count"] == 4

        r = client.patch(f"/api/campaigns/{campaign_id}", json={"target_slide_count": None})
        assert r.status_code == 200
        assert r.json()["target_slide_count"] is None

        r = client.get(f"/api/campaigns/{campaign_id}")
        assert r.json()["target_slide_count"] is None


def test_update_campaign_rejects_out_of_range_slide_count(temp_db):
    from app.models import Brand, Campaign

    with _client(temp_db) as client:
        session = temp_db.SessionLocal()
        brand = Brand(name="Hanna", slug="hanna")
        session.add(brand)
        session.commit()
        campaign = Campaign(display_id="HANNA-SKIN-000004", brand_id=brand.id, status="IDEA")
        session.add(campaign)
        session.commit()
        campaign_id = campaign.id
        session.close()

        r = client.patch(f"/api/campaigns/{campaign_id}", json={"target_slide_count": 0})
        assert r.status_code == 400

        # Round 19: the cap was raised from 10 to 20 (real request: a single-product
        # deep-dive campaign transformed into up to a 20-slide carousel).
        r = client.patch(f"/api/campaigns/{campaign_id}", json={"target_slide_count": 21})
        assert r.status_code == 400

        r = client.get(f"/api/campaigns/{campaign_id}")
        assert r.json()["target_slide_count"] is None  # rejected writes must not have applied


def test_update_campaign_accepts_the_new_round_19_slide_count_ceiling(temp_db):
    """20 must be accepted (the new ceiling) and set correctly — a separate
    campaign/test from the rejection test above so its assertions don't collide.
    """
    from app.models import Brand, Campaign

    with _client(temp_db) as client:
        session = temp_db.SessionLocal()
        brand = Brand(name="Hanna", slug="hanna")
        session.add(brand)
        session.commit()
        campaign = Campaign(display_id="HANNA-SKIN-000005", brand_id=brand.id, status="IDEA")
        session.add(campaign)
        session.commit()
        campaign_id = campaign.id
        session.close()

        r = client.patch(f"/api/campaigns/{campaign_id}", json={"target_slide_count": 20})
        assert r.status_code == 200
        assert r.json()["target_slide_count"] == 20

        r = client.get(f"/api/campaigns/{campaign_id}")
        assert r.json()["target_slide_count"] == 20


def test_update_campaign_404s_for_unknown_campaign(temp_db):
    with _client(temp_db) as client:
        r = client.patch("/api/campaigns/does-not-exist", json={"target_slide_count": 3})
        assert r.status_code == 404


# --- Round 20: campaign-level platform_key (pick a real social platform up front) -


def test_create_campaign_accepts_a_valid_platform_key_and_get_reports_it(temp_db):
    from app.models import Brand

    with _client(temp_db) as client:
        session = temp_db.SessionLocal()
        brand = Brand(name="Hanna", slug="hanna")
        session.add(brand)
        session.commit()
        brand_id = brand.id
        session.close()

        r = client.post("/api/campaigns", json={"brand_id": brand_id, "platform_key": "instagram_portrait"})
        assert r.status_code == 201
        campaign_id = r.json()["id"]

        r = client.get(f"/api/campaigns/{campaign_id}")
        assert r.json()["platform_key"] == "instagram_portrait"


def test_create_campaign_rejects_an_unknown_platform_key(temp_db):
    from app.models import Brand

    with _client(temp_db) as client:
        session = temp_db.SessionLocal()
        brand = Brand(name="Hanna", slug="hanna")
        session.add(brand)
        session.commit()
        brand_id = brand.id
        session.close()

        r = client.post("/api/campaigns", json={"brand_id": brand_id, "platform_key": "tiktok_vertical_9x16"})
        assert r.status_code == 400


def test_create_campaign_without_platform_key_leaves_it_null(temp_db):
    """No platform_key given (every campaign created before round 20, and any new
    one that hasn't picked one) must leave the column NULL — behaves exactly as
    before this field existed, falling back to AutopilotConfig.platform_key's own
    default at render time (see run_visuals_stage's effective_platform_key).
    """
    from app.models import Brand

    with _client(temp_db) as client:
        session = temp_db.SessionLocal()
        brand = Brand(name="Hanna", slug="hanna")
        session.add(brand)
        session.commit()
        brand_id = brand.id
        session.close()

        r = client.post("/api/campaigns", json={"brand_id": brand_id})
        assert r.status_code == 201
        campaign_id = r.json()["id"]

        r = client.get(f"/api/campaigns/{campaign_id}")
        assert r.json()["platform_key"] is None


def test_update_campaign_platform_key_round_trips_and_rejects_unknown_value(temp_db):
    from app.models import Brand, Campaign

    with _client(temp_db) as client:
        session = temp_db.SessionLocal()
        brand = Brand(name="Hanna", slug="hanna")
        session.add(brand)
        session.commit()
        campaign = Campaign(display_id="HANNA-SKIN-000006", brand_id=brand.id, status="IDEA")
        session.add(campaign)
        session.commit()
        campaign_id = campaign.id
        session.close()

        r = client.patch(f"/api/campaigns/{campaign_id}", json={"platform_key": "instagram_story"})
        assert r.status_code == 200
        assert r.json()["platform_key"] == "instagram_story"

        r = client.patch(f"/api/campaigns/{campaign_id}", json={"platform_key": "not_a_real_platform"})
        assert r.status_code == 400

        # The rejected write must not have applied — still the last valid value.
        r = client.get(f"/api/campaigns/{campaign_id}")
        assert r.json()["platform_key"] == "instagram_story"

        # Explicit null clears it back to the render-time default.
        r = client.patch(f"/api/campaigns/{campaign_id}", json={"platform_key": None})
        assert r.status_code == 200
        assert r.json()["platform_key"] is None


def test_update_campaign_can_set_target_slide_count_and_platform_key_independently(temp_db):
    """Sending only one field must not clobber the other — the PATCH endpoint
    checks `model_fields_set` per field rather than treating a missing key as an
    implicit `null`.
    """
    from app.models import Brand, Campaign

    with _client(temp_db) as client:
        session = temp_db.SessionLocal()
        brand = Brand(name="Hanna", slug="hanna")
        session.add(brand)
        session.commit()
        campaign = Campaign(display_id="HANNA-SKIN-000007", brand_id=brand.id, status="IDEA")
        session.add(campaign)
        session.commit()
        campaign_id = campaign.id
        session.close()

        r = client.patch(f"/api/campaigns/{campaign_id}", json={"target_slide_count": 5})
        assert r.status_code == 200
        r = client.patch(f"/api/campaigns/{campaign_id}", json={"platform_key": "facebook_feed"})
        assert r.status_code == 200

        r = client.get(f"/api/campaigns/{campaign_id}")
        body = r.json()
        assert body["target_slide_count"] == 5
        assert body["platform_key"] == "facebook_feed"


def test_strategy_library_types_expose_product_scope(temp_db):
    """Round 20: every one of the 64 seeded types must carry a real product_scope
    value — surfaced read-only in the API so the frontend can show it, not used to
    gate anything.
    """
    with _client(temp_db) as client:
        r = client.get("/api/strategy-library")
        assert r.status_code == 200
        families = r.json()
        all_types = [t for family in families for t in family["types"]]
        assert len(all_types) == 64
        for t in all_types:
            assert t["product_scope"] in ("single", "multi", "either")


def test_brand_creative_instructions_round_trips_through_update(temp_db):
    from app.models import Brand

    with _client(temp_db) as client:
        session = temp_db.SessionLocal()
        brand = Brand(name="Hanna", slug="hanna")
        session.add(brand)
        session.commit()
        brand_id = brand.id
        session.close()

        r = client.get(f"/api/brands/{brand_id}")
        assert r.json()["creative_instructions"] == ""  # default, every pre-round-20 brand

        r = client.patch(
            f"/api/brands/{brand_id}",
            json={"creative_instructions": "Always show the product label facing forward."},
        )
        assert r.status_code == 200
        assert r.json()["creative_instructions"] == "Always show the product label facing forward."

        r = client.get(f"/api/brands/{brand_id}")
        assert r.json()["creative_instructions"] == "Always show the product label facing forward."


# --- Round 19: discovery-products endpoint + structure_mode on GET ---------------

def _make_brand_category_and_products(session, n=2):
    from app.models import Brand, Category, Product

    brand = Brand(name="Hanna", slug="hanna")
    session.add(brand)
    session.commit()
    category = Category(brand_id=brand.id, name="Skincare", slug="skincare")
    session.add(category)
    session.commit()
    products = []
    for i in range(n):
        product = Product(brand_id=brand.id, category_id=category.id, name=f"Product {i}", slug=f"product-{i}")
        session.add(product)
        products.append(product)
    session.commit()
    return brand, category, products


def test_get_campaign_reports_deep_dive_structure_mode_when_product_is_set(temp_db):
    from app.models import Campaign

    session = temp_db.SessionLocal()
    brand, category, products = _make_brand_category_and_products(session, n=1)
    campaign = Campaign(
        display_id="HANNA-SKIN-000010", brand_id=brand.id, category_id=category.id, product_id=products[0].id,
        status="IDEA",
    )
    session.add(campaign)
    session.commit()
    campaign_id = campaign.id
    session.close()

    with _client(temp_db) as client:
        r = client.get(f"/api/campaigns/{campaign_id}")
        assert r.status_code == 200
        data = r.json()
        assert data["structure_mode"] == "deep_dive"
        assert data["product_id"] == products[0].id
        assert data["product_name"] == "Product 0"
        assert data["discovery_products"] == []


def test_set_discovery_products_replaces_list_and_get_campaign_reports_discovery_mode(temp_db):
    from app.models import Campaign

    session = temp_db.SessionLocal()
    brand, category, products = _make_brand_category_and_products(session, n=2)
    campaign = Campaign(
        display_id="HANNA-SKIN-000011", brand_id=brand.id, category_id=category.id, status="IDEA",
    )
    session.add(campaign)
    session.commit()
    campaign_id = campaign.id
    p0_id, p1_id = products[0].id, products[1].id
    session.close()

    with _client(temp_db) as client:
        # A category-only campaign with nothing picked yet is still deep_dive
        # (today's original single-photo-pool behavior, untouched).
        r = client.get(f"/api/campaigns/{campaign_id}")
        assert r.json()["structure_mode"] == "deep_dive"
        assert r.json()["discovery_products"] == []

        # Pick order is deliberately reversed from creation order to prove order
        # is driven by the payload, not by product id/creation order.
        r = client.put(f"/api/campaigns/{campaign_id}/discovery-products", json={"product_ids": [p1_id, p0_id]})
        assert r.status_code == 200
        assert [dp["product_id"] for dp in r.json()["discovery_products"]] == [p1_id, p0_id]

        r = client.get(f"/api/campaigns/{campaign_id}")
        data = r.json()
        assert data["structure_mode"] == "discovery"
        assert [dp["product_id"] for dp in data["discovery_products"]] == [p1_id, p0_id]
        assert [dp["name"] for dp in data["discovery_products"]] == ["Product 1", "Product 0"]

        # Replacing wholesale with an empty list clears it back to deep_dive.
        r = client.put(f"/api/campaigns/{campaign_id}/discovery-products", json={"product_ids": []})
        assert r.status_code == 200
        assert r.json()["discovery_products"] == []
        r = client.get(f"/api/campaigns/{campaign_id}")
        assert r.json()["structure_mode"] == "deep_dive"


def test_set_discovery_products_rejects_when_campaign_has_a_product_id(temp_db):
    from app.models import Campaign

    session = temp_db.SessionLocal()
    brand, category, products = _make_brand_category_and_products(session, n=1)
    campaign = Campaign(
        display_id="HANNA-SKIN-000012", brand_id=brand.id, category_id=category.id, product_id=products[0].id,
        status="IDEA",
    )
    session.add(campaign)
    session.commit()
    campaign_id = campaign.id
    product_id = products[0].id
    session.close()

    with _client(temp_db) as client:
        r = client.put(f"/api/campaigns/{campaign_id}/discovery-products", json={"product_ids": [product_id]})
        assert r.status_code == 400
        assert "deep-dive" in r.json()["detail"].lower() or "single product" in r.json()["detail"].lower()


def test_set_discovery_products_rejects_duplicate_ids(temp_db):
    from app.models import Campaign

    session = temp_db.SessionLocal()
    brand, category, products = _make_brand_category_and_products(session, n=1)
    campaign = Campaign(display_id="HANNA-SKIN-000013", brand_id=brand.id, category_id=category.id, status="IDEA")
    session.add(campaign)
    session.commit()
    campaign_id = campaign.id
    product_id = products[0].id
    session.close()

    with _client(temp_db) as client:
        r = client.put(
            f"/api/campaigns/{campaign_id}/discovery-products", json={"product_ids": [product_id, product_id]}
        )
        assert r.status_code == 400


def test_set_discovery_products_rejects_unknown_product(temp_db):
    from app.models import Campaign

    session = temp_db.SessionLocal()
    brand, category, _products = _make_brand_category_and_products(session, n=0)
    campaign = Campaign(display_id="HANNA-SKIN-000014", brand_id=brand.id, category_id=category.id, status="IDEA")
    session.add(campaign)
    session.commit()
    campaign_id = campaign.id
    session.close()

    with _client(temp_db) as client:
        r = client.put(
            f"/api/campaigns/{campaign_id}/discovery-products", json={"product_ids": ["does-not-exist"]}
        )
        assert r.status_code == 404


def test_set_discovery_products_rejects_more_than_20(temp_db):
    from app.models import Campaign

    session = temp_db.SessionLocal()
    brand, category, products = _make_brand_category_and_products(session, n=21)
    campaign = Campaign(display_id="HANNA-SKIN-000015", brand_id=brand.id, category_id=category.id, status="IDEA")
    session.add(campaign)
    session.commit()
    campaign_id = campaign.id
    product_ids = [p.id for p in products]
    session.close()

    with _client(temp_db) as client:
        r = client.put(f"/api/campaigns/{campaign_id}/discovery-products", json={"product_ids": product_ids})
        assert r.status_code == 400


def test_creative_templates_endpoint_lists_real_registry(temp_db):
    with _client(temp_db) as client:
        r = client.get("/api/campaigns/creative/templates")
        assert r.status_code == 200
        body = r.json()
        assert any(t["id"] == "premium_product_hero" for t in body["templates"])
        assert any(f["key"] == "instagram_square" for f in body["platform_formats"])


def test_asset_image_endpoint_serves_a_resized_preview(temp_db, tmp_path):
    from PIL import Image

    from app.models import Asset, Brand

    photo_path = tmp_path / "hero.jpg"
    Image.new("RGB", (1200, 1200), (100, 150, 200)).save(photo_path)

    with _client(temp_db) as client:
        session = temp_db.SessionLocal()
        brand = Brand(name="Hanna", slug="hanna")
        session.add(brand)
        session.commit()
        asset = Asset(
            brand_id=brand.id,
            absolute_path=str(photo_path),
            relative_path="hero.jpg",
            filename="hero.jpg",
            extension=".jpg",
            sha256="x",
            width=1200,
            height=1200,
        )
        session.add(asset)
        session.commit()
        asset_id = asset.id
        session.close()

        r = client.get(f"/api/assets/{asset_id}/image", params={"max_size": 300})
        assert r.status_code == 200
        assert r.headers["content-type"] == "image/jpeg"

        import io

        from PIL import Image as PILImage

        with PILImage.open(io.BytesIO(r.content)) as img:
            assert max(img.size) <= 300


def test_render_campaign_slide_end_to_end(temp_db, tmp_path):
    from PIL import Image

    from app.models import Asset, Brand, Campaign, Category

    source_photo = tmp_path / "product.jpg"
    Image.new("RGB", (900, 900), (180, 90, 40)).save(source_photo)
    output_root = tmp_path / "generated"

    with _client(temp_db) as client:
        r = client.patch("/api/settings", json={"output_root": str(output_root)})
        assert r.status_code == 200

        session = temp_db.SessionLocal()
        brand = Brand(name="Hanna", slug="hanna", colors={"primary": "#f2ede3", "secondary": "#d8c9ad"})
        session.add(brand)
        session.commit()
        category = Category(brand_id=brand.id, name="Skincare", slug="skincare")
        session.add(category)
        session.commit()
        campaign = Campaign(display_id="HANNA-SKINC-000001", brand_id=brand.id, category_id=category.id, status="IDEA")
        session.add(campaign)
        session.commit()
        asset = Asset(
            brand_id=brand.id,
            category_id=category.id,
            absolute_path=str(source_photo),
            relative_path="skincare/product.jpg",
            filename="product.jpg",
            extension=".jpg",
            sha256="x",
            width=900,
            height=900,
        )
        session.add(asset)
        session.commit()
        brand_id, campaign_id, asset_id = brand.id, campaign.id, asset.id
        session.close()

        r = client.post(
            f"/api/campaigns/{campaign_id}/slides/render",
            json={
                "asset_id": asset_id,
                "slide_number": 1,
                "headline": "Your new skincare favorite",
                "eyebrow": "Direct from Japan",
                "body": "Sourced firsthand, shipped to Brazil.",
                "cta": "Shop the drop",
            },
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["width"] == 1080 and body["height"] == 1080
        assert body["qa"]["passed"] is True, body["qa"]
        rendered_path = Path(body["rendered_asset_path"])
        assert rendered_path.exists()
        assert rendered_path.is_relative_to(output_root)

        r = client.get(body["image_url"])
        assert r.status_code == 200
        assert r.headers["content-type"] == "image/png"

        r = client.get(f"/api/campaigns/{campaign_id}")
        assert r.status_code == 200
        slides = r.json()["slides"]
        assert len(slides) == 1
        assert slides[0]["headline"] == "Your new skincare favorite"

        r = client.get(f"/api/assets/{asset_id}")
        assert r.json()["times_used"] == 1


def test_render_campaign_slide_with_ai_background(temp_db, tmp_path, monkeypatch):
    """`use_ai_background=true` on the manual per-slide endpoint should require an
    OpenAI key and route the background through `generate_ai_background` (and
    therefore the fake provider) rather than the deterministic gradient — same
    property the Campaign Builder advanced-mode Visuals stage has, exposed here too
    since this is the endpoint that stage itself is built on.
    """
    import io

    from PIL import Image

    from app.api import campaigns as campaigns_module
    from app.models import Asset, Brand, Campaign, Category

    source_photo = tmp_path / "product.jpg"
    Image.new("RGB", (900, 900), (180, 90, 40)).save(source_photo)
    output_root = tmp_path / "generated"

    class _FakeImageProvider:
        def __init__(self, api_key):
            self.api_key = api_key
            self.calls = []

        async def generate(self, *, prompt, size, model, reference_images=None, quality="high"):
            self.calls.append({"prompt": prompt, "size": size, "reference_images": reference_images})
            buf = io.BytesIO()
            Image.new("RGB", (64, 64), (10, 20, 30)).save(buf, format="PNG")
            return buf.getvalue()

    fake_instances: list[_FakeImageProvider] = []

    def _make_fake(api_key):
        instance = _FakeImageProvider(api_key)
        fake_instances.append(instance)
        return instance

    monkeypatch.setattr(campaigns_module, "openai_provider_from_effective_settings", _make_fake)

    with _client(temp_db) as client:
        client.patch("/api/settings", json={"output_root": str(output_root)})

        session = temp_db.SessionLocal()
        brand = Brand(name="Hanna", slug="hanna")
        session.add(brand)
        session.commit()
        category = Category(brand_id=brand.id, name="Skincare", slug="skincare")
        session.add(category)
        session.commit()
        campaign = Campaign(display_id="HANNA-SKINC-000002", brand_id=brand.id, category_id=category.id, status="IDEA")
        session.add(campaign)
        session.commit()
        asset = Asset(
            brand_id=brand.id, category_id=category.id, absolute_path=str(source_photo),
            relative_path="skincare/product.jpg", filename="product.jpg", extension=".jpg", sha256="x",
            width=900, height=900,
        )
        session.add(asset)
        session.commit()
        campaign_id, asset_id = campaign.id, asset.id
        session.close()

        # Without a key, the flag is rejected up front rather than silently ignored.
        r = client.post(
            f"/api/campaigns/{campaign_id}/slides/render",
            json={"asset_id": asset_id, "headline": "Hero", "use_ai_background": True},
        )
        assert r.status_code == 400
        assert "OpenAI API key" in r.json()["detail"]

        client.patch("/api/settings", json={"openai_api_key": "sk-test"})
        r = client.post(
            f"/api/campaigns/{campaign_id}/slides/render",
            json={"asset_id": asset_id, "headline": "Hero", "use_ai_background": True},
        )
        assert r.status_code == 200, r.text
        assert len(fake_instances) == 1
        assert len(fake_instances[0].calls) == 1


def test_render_campaign_slide_with_product_zone_detection(temp_db, tmp_path, monkeypatch):
    """`detect_product_zone=true` on the manual per-slide endpoint should require an
    OpenAI key and route the placement through `services/orchestrator.py::
    detect_product_zone` (and therefore the fake provider) rather than only the
    template's fixed layout — same property the Campaign Builder advanced-mode
    Visuals stage has, exposed here too since this is the endpoint that stage
    itself is built on.
    """
    from PIL import Image

    from app.api import campaigns as campaigns_module
    from app.models import Asset, Brand, Campaign, Category
    from app.schemas.ai import ProductZoneDetection

    source_photo = tmp_path / "product.jpg"
    Image.new("RGB", (900, 900), (180, 90, 40)).save(source_photo)
    output_root = tmp_path / "generated"

    class _FakeAIProvider:
        def __init__(self, api_key):
            self.api_key = api_key
            self.calls = []

        async def detect_product_zone(self, *, image_path, model):
            self.calls.append({"image_path": image_path, "model": model})
            return ProductZoneDetection(
                crop_left=0.1, crop_top=0.1, crop_width=0.6, crop_height=0.6, anchor="bottom",
            )

    fake_instances: list[_FakeAIProvider] = []

    def _make_fake(api_key):
        instance = _FakeAIProvider(api_key)
        fake_instances.append(instance)
        return instance

    monkeypatch.setattr(campaigns_module, "openai_provider_from_effective_settings", _make_fake)

    with _client(temp_db) as client:
        client.patch("/api/settings", json={"output_root": str(output_root)})

        session = temp_db.SessionLocal()
        brand = Brand(name="Hanna", slug="hanna")
        session.add(brand)
        session.commit()
        category = Category(brand_id=brand.id, name="Skincare", slug="skincare")
        session.add(category)
        session.commit()
        campaign = Campaign(display_id="HANNA-SKINC-000003", brand_id=brand.id, category_id=category.id, status="IDEA")
        session.add(campaign)
        session.commit()
        asset = Asset(
            brand_id=brand.id, category_id=category.id, absolute_path=str(source_photo),
            relative_path="skincare/product.jpg", filename="product.jpg", extension=".jpg", sha256="x",
            width=900, height=900,
        )
        session.add(asset)
        session.commit()
        campaign_id, asset_id = campaign.id, asset.id
        session.close()

        # Without a key, the flag is rejected up front rather than silently ignored.
        r = client.post(
            f"/api/campaigns/{campaign_id}/slides/render",
            json={"asset_id": asset_id, "headline": "Hero", "detect_product_zone": True},
        )
        assert r.status_code == 400
        assert "OpenAI API key" in r.json()["detail"]

        client.patch("/api/settings", json={"openai_api_key": "sk-test"})
        r = client.post(
            f"/api/campaigns/{campaign_id}/slides/render",
            json={"asset_id": asset_id, "headline": "Hero", "detect_product_zone": True},
        )
        assert r.status_code == 200, r.text
        assert len(fake_instances) == 1
        assert len(fake_instances[0].calls) == 1


def test_render_campaign_slide_requires_output_root_configured(temp_db, tmp_path):
    from PIL import Image

    from app.models import Asset, Brand, Campaign

    source_photo = tmp_path / "product.jpg"
    Image.new("RGB", (500, 500), (10, 10, 10)).save(source_photo)

    with _client(temp_db) as client:
        session = temp_db.SessionLocal()
        brand = Brand(name="Hanna", slug="hanna")
        session.add(brand)
        session.commit()
        campaign = Campaign(display_id="HANNA-GEN-000001", brand_id=brand.id, status="IDEA")
        session.add(campaign)
        session.commit()
        asset = Asset(
            brand_id=brand.id,
            absolute_path=str(source_photo),
            relative_path="product.jpg",
            filename="product.jpg",
            extension=".jpg",
            sha256="x",
        )
        session.add(asset)
        session.commit()
        campaign_id, asset_id = campaign.id, asset.id
        session.close()

        r = client.post(
            f"/api/campaigns/{campaign_id}/slides/render",
            json={"asset_id": asset_id, "headline": "No output root set"},
        )
        assert r.status_code == 400
        assert "OUTPUT_ROOT" in r.json()["detail"]


def test_render_campaign_slide_rejects_asset_from_a_different_brand(temp_db, tmp_path):
    from PIL import Image

    from app.models import Asset, Brand, Campaign

    source_photo = tmp_path / "product.jpg"
    Image.new("RGB", (500, 500), (10, 10, 10)).save(source_photo)

    with _client(temp_db) as client:
        client.patch("/api/settings", json={"output_root": str(tmp_path / "generated")})

        session = temp_db.SessionLocal()
        brand_a = Brand(name="Hanna", slug="hanna")
        brand_b = Brand(name="Other", slug="other")
        session.add_all([brand_a, brand_b])
        session.commit()
        campaign = Campaign(display_id="HANNA-GEN-000002", brand_id=brand_a.id, status="IDEA")
        session.add(campaign)
        session.commit()
        asset = Asset(
            brand_id=brand_b.id,
            absolute_path=str(source_photo),
            relative_path="product.jpg",
            filename="product.jpg",
            extension=".jpg",
            sha256="x",
        )
        session.add(asset)
        session.commit()
        campaign_id, asset_id = campaign.id, asset.id
        session.close()

        r = client.post(
            f"/api/campaigns/{campaign_id}/slides/render",
            json={"asset_id": asset_id, "headline": "Wrong brand asset"},
        )
        assert r.status_code == 404


def test_brand_asset_upload_list_image_and_delete(temp_db, tmp_path):
    """Brand assets (logo/font/visual_reference) had a DB model since round 1 but
    zero endpoints — a brand's logo has never once made it into a rendered creative
    in this app because there was no way to upload one. This is the round that
    closes that gap, so it's worth testing thoroughly: upload writes a real file
    under OUTPUT_ROOT and a BrandAsset row, list/image/delete all work over the
    file that was actually written, and delete removes both the row and the file.
    """
    with _client(temp_db) as client:
        output_root = tmp_path / "generated"
        client.patch("/api/settings", json={"output_root": str(output_root)})

        r = client.post("/api/brands", json={"name": "Hanna", "slug": "hanna"})
        brand_id = r.json()["id"]

        r = client.post(
            f"/api/brands/{brand_id}/assets",
            data={"kind": "logo", "label": "Primary logo"},
            files={"file": ("logo.png", b"fake-png-bytes", "image/png")},
        )
        assert r.status_code == 201, r.text
        asset = r.json()
        assert asset["kind"] == "logo"
        assert asset["label"] == "Primary logo"
        asset_id = asset["id"]

        # The file was actually written under OUTPUT_ROOT, not just recorded in the DB.
        written = list((output_root / "_brand_assets" / "hanna" / "logo").glob("*.png"))
        assert len(written) == 1
        assert written[0].read_bytes() == b"fake-png-bytes"

        r = client.get(f"/api/brands/{brand_id}/assets")
        assert r.status_code == 200
        assert len(r.json()) == 1

        r = client.get(f"/api/brands/{brand_id}/assets", params={"kind": "visual_reference"})
        assert r.json() == []

        r = client.delete(f"/api/brands/{brand_id}/assets/{asset_id}")
        assert r.status_code == 204
        assert written[0].exists() is False  # file removed alongside the row

        r = client.get(f"/api/brands/{brand_id}/assets")
        assert r.json() == []


def test_inspiration_brand_asset_can_be_scoped_to_a_category(temp_db, tmp_path):
    """Round 15: `kind='inspiration'` (a real ad/post/carousel the user wants
    campaigns to draw creative direction from) plus an optional `category_id` that
    scopes it to one category instead of the whole brand. Covers: the kind is
    accepted, category_id round-trips, listing filters by it, an unknown/foreign
    category_id is rejected, and a brand-wide (no category_id) upload still works.
    """
    with _client(temp_db) as client:
        output_root = tmp_path / "generated"
        client.patch("/api/settings", json={"output_root": str(output_root)})

        r = client.post("/api/brands", json={"name": "Hanna", "slug": "hanna"})
        brand_id = r.json()["id"]
        r = client.post("/api/categories", json={"brand_id": brand_id, "name": "Skincare", "slug": "skincare"})
        category_id = r.json()["id"]

        # Category-scoped inspiration example.
        r = client.post(
            f"/api/brands/{brand_id}/assets",
            data={"kind": "inspiration", "category_id": category_id, "label": "Competitor carousel ad"},
            files={"file": ("ad.png", b"fake-ad-bytes", "image/png")},
        )
        assert r.status_code == 201, r.text
        scoped_asset = r.json()
        assert scoped_asset["kind"] == "inspiration"
        assert scoped_asset["category_id"] == category_id

        # Brand-wide inspiration example (no category_id).
        r = client.post(
            f"/api/brands/{brand_id}/assets",
            data={"kind": "inspiration"},
            files={"file": ("post.png", b"fake-post-bytes", "image/png")},
        )
        assert r.status_code == 201, r.text
        assert r.json()["category_id"] is None

        r = client.get(f"/api/brands/{brand_id}/assets", params={"kind": "inspiration"})
        assert r.status_code == 200
        assert len(r.json()) == 2

        r = client.get(f"/api/brands/{brand_id}/assets", params={"kind": "inspiration", "category_id": category_id})
        assert r.status_code == 200
        assert [a["id"] for a in r.json()] == [scoped_asset["id"]]

        # A category_id from a different (or nonexistent) brand is rejected.
        r = client.post(
            f"/api/brands/{brand_id}/assets",
            data={"kind": "inspiration", "category_id": "not-a-real-category"},
            files={"file": ("bad.png", b"bytes", "image/png")},
        )
        assert r.status_code == 404


def test_brand_asset_upload_rejects_unknown_kind(temp_db, tmp_path):
    with _client(temp_db) as client:
        client.patch("/api/settings", json={"output_root": str(tmp_path / "generated")})
        r = client.post("/api/brands", json={"name": "Hanna", "slug": "hanna"})
        brand_id = r.json()["id"]
        r = client.post(
            f"/api/brands/{brand_id}/assets",
            data={"kind": "mood_board"},
            files={"file": ("x.png", b"bytes", "image/png")},
        )
        assert r.status_code == 400


def test_analyze_visual_style_requires_reference_photo_and_key(temp_db, tmp_path):
    with _client(temp_db) as client:
        client.patch("/api/settings", json={"output_root": str(tmp_path / "generated")})
        r = client.post("/api/brands", json={"name": "Hanna", "slug": "hanna"})
        brand_id = r.json()["id"]

        # No OpenAI key configured yet.
        r = client.post(f"/api/brands/{brand_id}/visual-style/analyze")
        assert r.status_code == 400
        assert "OpenAI API key" in r.json()["detail"]

        client.patch("/api/settings", json={"openai_api_key": "sk-test"})
        # Key is set but no visual_reference photo has been uploaded yet.
        r = client.post(f"/api/brands/{brand_id}/visual-style/analyze")
        assert r.status_code == 400
        assert "Upload at least one visual-reference photo" in r.json()["detail"]


def test_analyze_visual_style_returns_ai_proposal_without_touching_the_brand(temp_db, tmp_path, monkeypatch):
    """The analysis is a proposal only — it must never write to the brand itself;
    applying it is a separate, human-driven `PATCH /api/brands/{id}` call.
    """
    from app.api import brands as brands_module
    from app.schemas.ai import BrandVisualStyleAnalysis

    expected = BrandVisualStyleAnalysis(
        summary="Warm, editorial J-beauty flat-lays on neutral backgrounds.",
        dominant_colors=["#f5e6d3", "#2b2b2b"],
        typography_mood="clean minimalist sans-serif",
        photography_style="soft natural light, flat-lay",
        visual_style_descriptors=["minimal", "warm neutrals", "editorial"],
        voice_suggestion="warm, expert, unhurried",
    )

    class _FakeProvider:
        def __init__(self):
            self.calls = []

        async def analyze_visual_style(self, *, image_paths, brand_name, model):
            self.calls.append((tuple(image_paths), brand_name, model))
            return expected

    fake = _FakeProvider()
    monkeypatch.setattr(brands_module, "openai_provider_from_effective_settings", lambda api_key: fake)

    with _client(temp_db) as client:
        client.patch(
            "/api/settings",
            json={"output_root": str(tmp_path / "generated"), "openai_api_key": "sk-test"},
        )
        r = client.post("/api/brands", json={"name": "Hanna", "slug": "hanna"})
        brand_id = r.json()["id"]
        original_voice = r.json()["voice"]

        client.post(
            f"/api/brands/{brand_id}/assets",
            data={"kind": "visual_reference"},
            files={"file": ("ref.png", b"fake-photo-bytes", "image/png")},
        )

        r = client.post(f"/api/brands/{brand_id}/visual-style/analyze")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["summary"] == expected.summary
        assert body["dominant_colors"] == expected.dominant_colors
        assert len(fake.calls) == 1
        assert fake.calls[0][1] == "Hanna"

        # Nothing was written to the brand by the analysis call itself.
        r = client.get(f"/api/brands/{brand_id}")
        assert r.json()["voice"] == original_voice
        assert r.json()["colors"] == {}


def _rendered_campaign(temp_db, tmp_path, client, *, display_id: str) -> tuple[str, int]:
    """Shared setup for the auto-publish tests below: a brand, a rendered slide, and
    the campaign approved and ready to log/auto-publish a real post against. Returns
    (campaign_id, slide_number).
    """
    from PIL import Image

    from app.models import Asset, Brand, Campaign, Category

    source_photo = tmp_path / f"{display_id}.jpg"
    Image.new("RGB", (900, 900), (180, 90, 40)).save(source_photo)
    client.patch("/api/settings", json={"output_root": str(tmp_path / "generated")})

    session = temp_db.SessionLocal()
    brand = Brand(name="Hanna", slug="hanna")
    session.add(brand)
    session.commit()
    category = Category(brand_id=brand.id, name="Skincare", slug="skincare")
    session.add(category)
    session.commit()
    campaign = Campaign(
        display_id=display_id, brand_id=brand.id, category_id=category.id, status="IDEA",
        angle="New drop, direct from Japan",
    )
    session.add(campaign)
    session.commit()
    asset = Asset(
        brand_id=brand.id, category_id=category.id, absolute_path=str(source_photo),
        relative_path="skincare/product.jpg", filename="product.jpg", extension=".jpg", sha256="x",
        width=900, height=900,
    )
    session.add(asset)
    session.commit()
    campaign_id, asset_id = campaign.id, asset.id
    session.close()

    r = client.post(
        f"/api/campaigns/{campaign_id}/slides/render",
        json={"asset_id": asset_id, "headline": "New drop", "cta": "Shop now"},
    )
    assert r.status_code == 200, r.text

    session = temp_db.SessionLocal()
    c = session.get(Campaign, campaign_id)
    c.status = "REVIEW"
    session.commit()
    session.close()
    r = client.post(f"/api/campaigns/{campaign_id}/approve")
    assert r.status_code == 200, r.text

    return campaign_id, 1


def test_auto_publish_requires_approval_and_configured_credentials(temp_db, tmp_path):
    with _client(temp_db) as client:
        campaign_id, slide_number = _rendered_campaign(temp_db, tmp_path, client, display_id="HANNA-SKIN-P00001")

        from app.models import Campaign

        session = temp_db.SessionLocal()
        c = session.get(Campaign, campaign_id)
        c.status = "IDEA"
        session.commit()
        session.close()

        r = client.post(f"/api/campaigns/{campaign_id}/publish", json={"provider": "facebook_page"})
        assert r.status_code == 400
        assert "approved" in r.json()["detail"].lower()

        session = temp_db.SessionLocal()
        c = session.get(Campaign, campaign_id)
        c.status = "APPROVED"
        session.commit()
        session.close()

        # No access token configured yet.
        r = client.post(f"/api/campaigns/{campaign_id}/publish", json={"provider": "facebook_page"})
        assert r.status_code == 400
        assert "access token" in r.json()["detail"].lower()

        # Token configured, but no Page ID yet.
        client.patch("/api/settings", json={"facebook_page_access_token": "page-token"})
        r = client.post(f"/api/campaigns/{campaign_id}/publish", json={"provider": "facebook_page"})
        assert r.status_code == 400
        assert "page id" in r.json()["detail"].lower()

        # An unrendered slide number is rejected even once credentials are set.
        client.patch("/api/settings", json={"facebook_page_id": "999888777"})
        r = client.post(
            f"/api/campaigns/{campaign_id}/publish",
            json={"provider": "facebook_page", "slide_number": 2},
        )
        assert r.status_code == 400
        assert "not been rendered" in r.json()["detail"].lower()


def test_auto_publish_facebook_success_creates_publication_and_bumps_status(temp_db, tmp_path, monkeypatch):
    from app.api import campaigns as campaigns_module
    from app.services.ai.base import PublishResult

    class _FakePublisher:
        def __init__(self, access_token, api_version=None):
            self.access_token = access_token
            self.calls = []

        async def publish(self, *, target, assets, copy):
            self.calls.append({"target": target, "assets": assets, "copy": copy})
            return PublishResult(success=True, external_post_id="999888777_555", url="https://www.facebook.com/999888777_555")

    fake_instances: list[_FakePublisher] = []

    def _make_fake(access_token, api_version=None):
        instance = _FakePublisher(access_token, api_version)
        fake_instances.append(instance)
        return instance

    monkeypatch.setattr(campaigns_module, "MetaPublishingProvider", _make_fake)

    with _client(temp_db) as client:
        campaign_id, slide_number = _rendered_campaign(temp_db, tmp_path, client, display_id="HANNA-SKIN-P00002")
        client.patch(
            "/api/settings",
            json={"facebook_page_access_token": "page-token", "facebook_page_id": "999888777"},
        )

        r = client.post(f"/api/campaigns/{campaign_id}/publish", json={"provider": "facebook_page"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["provider"] == "facebook_page"
        assert body["external_post_id"] == "999888777_555"
        assert body["status"] == "published"
        assert len(fake_instances) == 1 and len(fake_instances[0].calls) == 1
        call = fake_instances[0].calls[0]
        assert call["target"].external_id == "999888777"
        assert call["copy"].caption  # defaulted from the rendered slide's headline/cta, not empty

        r = client.get(f"/api/campaigns/{campaign_id}")
        assert r.json()["status"] == "PUBLISHED"
        r = client.get(f"/api/campaigns/{campaign_id}/publications")
        assert len(r.json()) == 1
        assert r.json()[0]["url"] == "https://www.facebook.com/999888777_555"


def test_auto_publish_upstream_failure_is_surfaced_and_nothing_is_recorded(temp_db, tmp_path, monkeypatch):
    """A failed post attempt is not something that happened: no Publication row, and
    the campaign status is left alone rather than being bumped to PUBLISHED.
    """
    from app.api import campaigns as campaigns_module
    from app.services.ai.base import PublishResult

    class _FailingPublisher:
        def __init__(self, access_token, api_version=None):
            pass

        async def publish(self, *, target, assets, copy):
            return PublishResult(success=False, error="Invalid OAuth access token.")

    monkeypatch.setattr(campaigns_module, "MetaPublishingProvider", _FailingPublisher)

    with _client(temp_db) as client:
        campaign_id, _ = _rendered_campaign(temp_db, tmp_path, client, display_id="HANNA-SKIN-P00003")
        client.patch(
            "/api/settings",
            json={"facebook_page_access_token": "bad-token", "facebook_page_id": "999888777"},
        )

        r = client.post(f"/api/campaigns/{campaign_id}/publish", json={"provider": "facebook_page"})
        assert r.status_code == 502
        assert r.json()["detail"] == "Invalid OAuth access token."

        r = client.get(f"/api/campaigns/{campaign_id}")
        assert r.json()["status"] == "APPROVED"
        r = client.get(f"/api/campaigns/{campaign_id}/publications")
        assert r.json() == []


def test_auto_publish_instagram_without_public_base_url_fails_with_real_provider(temp_db, tmp_path):
    """Uses the real `MetaPublishingProvider` (no monkeypatch) — its Instagram branch
    fails before making any network call when no public image URL is configured, so
    this is safe to run against the concrete implementation directly.
    """
    with _client(temp_db) as client:
        campaign_id, _ = _rendered_campaign(temp_db, tmp_path, client, display_id="HANNA-SKIN-P00004")
        client.patch(
            "/api/settings",
            json={
                "facebook_page_access_token": "page-token",
                "instagram_business_account_id": "ig-123",
            },
        )

        r = client.post(f"/api/campaigns/{campaign_id}/publish", json={"provider": "instagram"})
        assert r.status_code == 502
        assert "public url" in r.json()["detail"].lower()

        r = client.get(f"/api/campaigns/{campaign_id}")
        assert r.json()["status"] == "APPROVED"
