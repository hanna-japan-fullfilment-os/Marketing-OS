"""Tests for the Autopilot orchestrator (services/orchestrator.py) — the piece that
makes `POST /api/campaigns/{id}/generate` real. A FakeAutopilotProvider implements
both AIProvider and ResearchProvider so the full research -> strategy -> novelty
filter -> copy -> carousel -> creative-render sequence runs end to end against real
application code (DB, fingerprinting, the Playwright creative pipeline) with zero
network calls or API key.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest
from PIL import Image

from app.models import (
    Asset, AuditEvent, Brand, BrandAsset, Campaign, CampaignDiscoveryProduct, CampaignFingerprint,
    CampaignOutput, CampaignSlide, CampaignStrategyFamily, CampaignStrategyType, Category, Product,
    PromptVersion, VerifiedProductFact,
)
from app.schemas.ai import (
    CampaignCopy, CampaignStrategy, CampaignStrategyCandidates, CarouselPlan,
    CreativeBrief, ProductFidelityCheck, ProductZoneDetection, ResearchInsightItem, ResearchResult,
    SlideFeature, SlidePlan,
)
from app.schemas.creative_director import (
    CreativeDirection, MasterCampaignConcept, PlatformAdaptation, VideoConcept,
)
from app.services.creative.brand_style import resolve_brand_style
from app.services.creative.renderer import PlaywrightRenderer
from app.services.creative.templates import TemplateContext, get_template
from app.services.fingerprint import text_hash
from app.services.orchestrator import (
    AutopilotConfig, RecreationOutcome, get_campaign_copy, recreate_creative_image,
    recreate_creative_image_with_fidelity_gate, run_autopilot, run_copy_stage, run_strategy_stage,
    run_visuals_stage,
)
from app.services.prompt_registry import PROMPT_VERSIONS, ensure_prompt_versions_seeded


class FakeAutopilotProvider:
    """Implements AIProvider.generate_structured (dispatching on the requested
    schema type) and ResearchProvider.research with controllable, canned results.
    """

    def __init__(
        self,
        *,
        strategy_candidates: CampaignStrategyCandidates | None = None,
        creative_brief: CreativeBrief | None = None,
        campaign_copy: CampaignCopy | None = None,
        carousel_plan: CarouselPlan | None = None,
        master_concept: MasterCampaignConcept | None = None,
        platform_adaptation: PlatformAdaptation | None = None,
        creative_direction: CreativeDirection | None = None,
        video_concept: VideoConcept | None = None,
        research_result: ResearchResult | None = None,
        zone_detection: ProductZoneDetection | None = None,
        zone_detection_raises: bool = False,
        fidelity_checks: list[ProductFidelityCheck] | None = None,
        fidelity_raises: bool = False,
    ):
        self.schema_calls: list[type] = []
        self.user_prompts: list[str] = []  # parallel to schema_calls — the `user` text of each call
        # Build 1: parallel to schema_calls/user_prompts — lets a test assert on
        # the `system` text too (e.g. `_language_style_rules`'s pt-BR/en rules,
        # which `run_copy_stage` embeds in `system` for CampaignCopy).
        self.system_prompts: list[str] = []
        self.research_calls = 0
        self.zone_detection_calls: list[dict] = []
        self._zone_detection_raises = zone_detection_raises
        self._zone_detection = zone_detection or ProductZoneDetection(
            crop_left=0.1, crop_top=0.1, crop_width=0.7, crop_height=0.7, anchor="bottom",
        )
        # Round 18: controllable results for AIProvider.check_product_fidelity — a
        # list consumed one verdict per call (so a test can script "FAIL then
        # PASS" for the one-retry path), defaulting to an endless PASS when unset
        # so every existing recreate_with_ai test that doesn't care about
        # fidelity still gets a verified image on the first attempt.
        self.fidelity_calls: list[dict] = []
        self._fidelity_raises = fidelity_raises
        self._fidelity_checks = list(fidelity_checks) if fidelity_checks else None
        self._default_fidelity_check = ProductFidelityCheck(
            package_shape="match", proportions="match", brand_logo="match", label_structure="match",
            visible_text="match", cap_or_closure="match", color="match", distinctive_marks="match",
            overall_verdict="PASS", reasoning="Product matches the reference photo.",
        )
        self._strategy_candidates = strategy_candidates or CampaignStrategyCandidates(
            candidates=[
                CampaignStrategy(
                    objective="awareness",
                    audience="Young adults in Brazil interested in J-beauty",
                    funnel_stage="tofu",
                    insight="Multi-step routines are trending",
                    angle="Build your routine",
                    key_message="Everything you need for a 5-step routine",
                    reason_this_should_work="Rides the current trend with a real product fit.",
                ),
                CampaignStrategy(
                    objective="awareness",
                    audience="Young adults in Brazil interested in J-beauty",
                    funnel_stage="tofu",
                    insight="Scarcity drives urgency",
                    angle="Limited restock",
                    key_message="Back in stock for a limited time",
                    reason_this_should_work="Creates urgency distinct from the routine angle.",
                ),
            ]
        )
        self._creative_brief = creative_brief or CreativeBrief(
            design_concept="Clean hero shot on a warm gradient",
            visual_prompt="Product centered on a soft brand-colored gradient",
            template_suggestion="premium_product_hero",
            tone_notes="Warm, aspirational, not pushy",
        )
        self._campaign_copy = campaign_copy or CampaignCopy(
            hook="Your skin deserves this",
            headline="Straight from Japan",
            supporting_copy="Sourced firsthand, shipped to Brazil.",
            cta="Shop now",
            caption="Straight from Japan, made for your routine.",
            hashtags=["#skincare", "#jbeauty"],
            alt_text="Product bottle on a gradient background",
        )
        self._carousel_plan = carousel_plan or CarouselPlan(
            slides=[
                SlidePlan(
                    slide_number=1, purpose="hero", eyebrow="New", headline="Slide one headline",
                    body="Slide one body", cta="Shop now", visual_brief="Hero product shot",
                ),
                SlidePlan(
                    slide_number=2, purpose="benefit", eyebrow="", headline="Slide two headline",
                    body="Slide two body", cta="Shop now", visual_brief="Detail shot",
                ),
            ],
            narrative_summary="A two-slide hero + benefit carousel.",
        )
        # Build 2: canned results for the new Creative Director schemas
        # requested from `run_copy_stage` (MasterCampaignConcept) and
        # `_render_additional_platform_variants` (PlatformAdaptation,
        # CreativeDirection, VideoConcept) — same dispatch-on-schema pattern
        # as every fake above, so every test that runs the full pipeline with
        # an AI provider gets a real (fake) structured response instead of
        # tripping the "unexpected schema" assertion below.
        self._master_concept = master_concept or MasterCampaignConcept(
            concept_name="Everyday Ritual",
            campaign_promise="A simple routine that actually fits your day",
            key_message="Everything you need for a 5-step routine",
            emotional_goal="Confidence in a simple daily ritual",
            audience="Young adults in Brazil interested in J-beauty",
            objective="awareness",
            visual_identity="Clean hero shot on a warm gradient",
            story_arc="Open on the product, reveal the routine, close on the result",
            cta_intent="Encourage trying the routine",
        )
        self._platform_adaptation = platform_adaptation or PlatformAdaptation(
            platform="instagram",
            adaptation_strategy="visual storytelling carousel — one idea per slide",
            narrative_shape="Open on the product, reveal the routine, close on the result",
            tone_adjustment="warm, aspirational",
            content_type="carousel",
            reasoning="Fake canned adaptation for tests.",
        )
        self._creative_direction = creative_direction or CreativeDirection(
            concept_name="Everyday Ritual",
            platform="instagram",
            content_type="carousel",
            language="pt-BR",
            campaign_visual_identity="Clean hero shot on a warm gradient",
            rationale="Fake canned creative direction for tests.",
            emotional_goal="Confidence in a simple daily ritual",
            visual_style="Clean, warm, aspirational",
            mood="Calm confidence",
            composition="Product centered, generous negative space",
            product_position="center",
            product_scale="large",
            background_concept="Soft warm gradient studio backdrop",
            lighting="Soft diffused daylight",
            palette=["#F5E6D8", "#B8895A"],
            typography_direction="Clean sans-serif, generous spacing",
            headline_emphasis="Short, confident headline",
            cta_treatment="Solid button, high contrast",
            slide_role="hero",
            scene_generation_prompt="Soft warm gradient studio backdrop, no text, no logos, no products.",
        )
        self._video_concept = video_concept or VideoConcept(
            hook="Your 5-step routine starts here",
            script="Open on the product. Walk through the 5 steps. Close on the result.",
            shot_list=["Product hero shot", "Routine steps in sequence", "Final result close-up"],
            timing="0-3s hook, 3-12s routine, 12-15s close",
            visual_direction="Warm, natural light, handheld feel",
            on_screen_text=["Step 1", "Step 2", "Step 3"],
            caption="Everything you need for a 5-step routine.",
            cover_creative_brief="Product hero shot on a warm gradient",
        )
        self._research_result = research_result or ResearchResult(
            insights=[
                ResearchInsightItem(
                    statement="Multi-step skincare routines are trending on Brazilian social media.",
                    confidence=0.8,
                    freshness="this_quarter",
                    category="trend",
                    recommended_implication="Emphasize routine-building in copy.",
                    source_urls=["https://example.com/trend-report"],
                )
            ]
        )

    async def generate_structured(self, *, system: str, user: str, schema, model: str):
        self.schema_calls.append(schema)
        self.user_prompts.append(user)
        self.system_prompts.append(system)
        if schema is CampaignStrategyCandidates:
            return self._strategy_candidates
        if schema is CreativeBrief:
            return self._creative_brief
        if schema is CampaignCopy:
            return self._campaign_copy
        if schema is CarouselPlan:
            return self._carousel_plan
        if schema is MasterCampaignConcept:
            return self._master_concept
        if schema is PlatformAdaptation:
            return self._platform_adaptation
        if schema is CreativeDirection:
            return self._creative_direction
        if schema is VideoConcept:
            return self._video_concept
        raise AssertionError(f"Unexpected schema requested from FakeAutopilotProvider: {schema}")

    async def vision_describe(self, *, image_path, prompt, model: str) -> str:
        return ""

    async def detect_product_zone(self, *, image_path, model: str) -> ProductZoneDetection:
        self.zone_detection_calls.append({"image_path": image_path, "model": model})
        if self._zone_detection_raises:
            raise RuntimeError("simulated vision API failure")
        return self._zone_detection

    async def research(self, query, *, model: str) -> ResearchResult:
        self.research_calls += 1
        return self._research_result

    async def check_product_fidelity(self, *, source_image_path, generated_image_path, model: str) -> ProductFidelityCheck:
        self.fidelity_calls.append(
            {"source_image_path": source_image_path, "generated_image_path": generated_image_path, "model": model}
        )
        if self._fidelity_raises:
            raise RuntimeError("simulated fidelity-check API failure")
        if self._fidelity_checks:
            # Consumed one per call; the last entry repeats once exhausted, so a
            # test can script exactly the sequence it cares about (e.g.
            # [FAIL, PASS] for "retry succeeds") without needing to know exactly
            # how many calls will happen.
            index = min(len(self.fidelity_calls) - 1, len(self._fidelity_checks) - 1)
            return self._fidelity_checks[index]
        return self._default_fidelity_check


def _make_brand_and_assets(session, tmp_path, *, num_assets=3):
    # The production application seeds the canonical Strategy Library at
    # startup. temp_db intentionally creates schema only, so this shared
    # orchestrator fixture must reproduce that canonical runtime prerequisite.
    from app.services.seed import seed_strategy_library

    seed_strategy_library(session)

    brand = Brand(
        name="Hanna",
        slug="hanna",
        colors={
            "primary": "#f2ede3",
            "secondary": "#d8c9ad",
        },
        campaign_rules={
            "verified_operational_strategy_keys": [
                "educational_campaign",
            ],
        },
    )
    session.add(brand)
    session.commit()
    category = Category(brand_id=brand.id, name="Skincare", slug="skincare")
    session.add(category)
    session.commit()

    assets = []
    for i in range(num_assets):
        img_path = tmp_path / f"asset-{i}.jpg"
        Image.new("RGB", (800, 800), (10 + i * 20, 50, 200)).save(img_path)
        asset = Asset(
            brand_id=brand.id,
            category_id=category.id,
            absolute_path=str(img_path),
            relative_path=f"skincare/asset-{i}.jpg",
            filename=f"asset-{i}.jpg",
            extension=".jpg",
            sha256=f"sha-{i}",
            width=800,
            height=800,
        )
        session.add(asset)
        assets.append(asset)
    session.commit()
    return brand, category, assets


def _make_discovery_products(session, brand, category, tmp_path, names: list[str]) -> list[Product]:
    """Round 19 test building block: one Product + one of its own active Asset per
    given name, all in the same category — a real, hand-pickable discovery-mode
    catalog, distinct from `_make_brand_and_assets`'s single-product photo pool.
    """
    products = []
    for i, name in enumerate(names):
        product = Product(brand_id=brand.id, category_id=category.id, name=name, slug=name.lower().replace(" ", "-"))
        session.add(product)
        session.commit()
        img_path = tmp_path / f"discovery-{i}.jpg"
        Image.new("RGB", (800, 800), (10 + i * 30, 40, 180)).save(img_path)
        asset = Asset(
            brand_id=brand.id, category_id=category.id, product_id=product.id,
            absolute_path=str(img_path), relative_path=f"skincare/{name.lower()}/discovery-{i}.jpg",
            filename=f"discovery-{i}.jpg", extension=".jpg", sha256=f"disc-sha-{i}",
            width=800, height=800,
        )
        session.add(asset)
        products.append(product)
    session.commit()
    return products


def _set_discovery_products(session, campaign, products: list[Product]) -> None:
    for i, product in enumerate(products):
        session.add(CampaignDiscoveryProduct(campaign_id=campaign.id, product_id=product.id, sort_order=i))
    session.commit()


def _make_campaign(session, brand, category, *, status="IDEA", strategy_type_id=None):
    campaign = Campaign(
        display_id=f"HANNA-SKIN-{uuid.uuid4().hex[:8]}",
        brand_id=brand.id,
        category_id=category.id,
        objective="awareness",
        status=status,
        strategy_type_id=strategy_type_id,
    )
    session.add(campaign)
    session.commit()
    return campaign


def _config(tmp_path):
    return AutopilotConfig(
        campaign_model="gpt-5.1",
        research_model="gpt-5.1",
        trend_ttl_hours=24,
        category_ttl_hours=168,
        too_similar_threshold=75,
        acceptable_threshold=45,
        output_root=tmp_path / "output",
    )


@pytest.fixture()
async def shared_renderer():
    renderer = PlaywrightRenderer()
    yield renderer
    await renderer.close()


async def test_run_autopilot_happy_path_reaches_review(temp_db, tmp_path, shared_renderer):
    session = temp_db.SessionLocal()
    brand, category, assets = _make_brand_and_assets(session, tmp_path)
    campaign = _make_campaign(session, brand, category)
    provider = FakeAutopilotProvider()

    result = await run_autopilot(
        session,
        campaign_id=campaign.id,
        ai_provider=provider,
        research_provider=provider,
        renderer=shared_renderer,
        config=_config(tmp_path),
    )

    assert result.status == "REVIEW"
    assert result.hook == "Your skin deserves this"
    assert result.cta == "Shop now"
    assert result.research_run_id is not None
    assert provider.research_calls == 1

    from pathlib import Path

    slides = (
        session.query(CampaignSlide)
        .filter(CampaignSlide.campaign_id == campaign.id)
        .order_by(CampaignSlide.slide_number)
        .all()
    )
    assert len(slides) == 2
    for slide in slides:
        assert slide.rendered_asset_path
        assert Path(slide.rendered_asset_path).exists()

    fingerprint = session.query(CampaignFingerprint).filter(CampaignFingerprint.campaign_id == campaign.id).one()
    assert fingerprint.angle == "Build your routine"
    assert len(fingerprint.asset_sha256_list) == 2
    session.close()


async def test_no_candidate_assets_fails_and_marks_campaign_failed(temp_db, tmp_path, shared_renderer):
    session = temp_db.SessionLocal()
    brand = Brand(name="Hanna", slug="hanna")
    session.add(brand)
    session.commit()
    category = Category(brand_id=brand.id, name="Skincare", slug="skincare")
    session.add(category)
    session.commit()
    campaign = _make_campaign(session, brand, category)
    provider = FakeAutopilotProvider()

    with pytest.raises(ValueError, match="No active photos"):
        await run_autopilot(
            session,
            campaign_id=campaign.id,
            ai_provider=provider,
            research_provider=provider,
            renderer=shared_renderer,
            config=_config(tmp_path),
        )

    session.refresh(campaign)
    assert campaign.status == "FAILED"
    session.close()


async def test_campaign_status_guard_rejects_wrong_status(temp_db, tmp_path, shared_renderer):
    session = temp_db.SessionLocal()
    brand, category, assets = _make_brand_and_assets(session, tmp_path)
    campaign = _make_campaign(session, brand, category, status="REVIEW")
    provider = FakeAutopilotProvider()

    with pytest.raises(ValueError, match="IDEA or FAILED"):
        await run_autopilot(
            session,
            campaign_id=campaign.id,
            ai_provider=provider,
            research_provider=provider,
            renderer=shared_renderer,
            config=_config(tmp_path),
        )
    session.close()


async def test_all_candidates_rejected_as_exact_repeats(temp_db, tmp_path, shared_renderer):
    session = temp_db.SessionLocal()
    brand, category, assets = _make_brand_and_assets(session, tmp_path)

    prior_campaign = _make_campaign(session, brand, category, status="REVIEW")
    fp_hash = text_hash("Same angle", "Same message", "Same insight")
    session.add(
        CampaignFingerprint(
            campaign_id=prior_campaign.id,
            text_hash=fp_hash,
            angle="Same angle",
            promise_summary="Same angle Same message Same insight",
            objective="awareness",
            format="instagram_square",
            asset_sha256_list=[],
            computed_at=datetime.now(timezone.utc),
        )
    )
    session.commit()

    campaign = _make_campaign(session, brand, category)
    duplicate_candidates = CampaignStrategyCandidates(
        candidates=[
            CampaignStrategy(
                objective="awareness", audience="A", funnel_stage="tofu",
                insight="Same insight", angle="Same angle", key_message="Same message",
                reason_this_should_work="reason",
            )
        ]
    )
    provider = FakeAutopilotProvider(strategy_candidates=duplicate_candidates)

    with pytest.raises(ValueError, match="too similar"):
        await run_autopilot(
            session,
            campaign_id=campaign.id,
            ai_provider=provider,
            research_provider=provider,
            renderer=shared_renderer,
            config=_config(tmp_path),
        )

    session.refresh(campaign)
    assert campaign.status == "FAILED"
    session.close()


async def test_retry_after_failed_does_not_duplicate_slide_rows(temp_db, tmp_path, shared_renderer):
    session = temp_db.SessionLocal()
    brand, category, assets = _make_brand_and_assets(session, tmp_path)
    campaign = _make_campaign(session, brand, category)
    provider = FakeAutopilotProvider()
    config = _config(tmp_path)

    def _slide_count() -> int:
        return (
            session.query(CampaignSlide)
            .filter(CampaignSlide.campaign_id == campaign.id)
            .count()
        )

    await run_autopilot(
        session, campaign_id=campaign.id, ai_provider=provider, research_provider=provider,
        renderer=shared_renderer, config=config,
    )
    first_slide_count = _slide_count()
    assert first_slide_count == 2

    session.refresh(campaign)
    campaign.status = "FAILED"
    session.commit()

    await run_autopilot(
        session, campaign_id=campaign.id, ai_provider=provider, research_provider=provider,
        renderer=shared_renderer, config=config,
    )
    assert _slide_count() == first_slide_count
    # Research was cached the second time around (same brand/category scope, fresh TTL).
    assert provider.research_calls == 1
    session.close()


async def test_existing_strategy_type_is_not_overridden(temp_db, tmp_path, shared_renderer):
    session = temp_db.SessionLocal()
    brand, category, assets = _make_brand_and_assets(session, tmp_path)

    # _make_brand_and_assets has already seeded the canonical Strategy
    # Library. Reuse the real seeded strategy instead of inserting a
    # duplicate key, and explicitly verify its applicability.
    chosen_type = (
        session.query(CampaignStrategyType)
        .filter(
            CampaignStrategyType.key
            == "guerrilla_marketing"
        )
        .one()
    )

    # Keep a second eligible alternative so this test still proves that a
    # valid explicitly preselected strategy is preserved rather than replaced.
    alternative_type = (
        session.query(CampaignStrategyType)
        .filter(
            CampaignStrategyType.key
            == "educational_campaign"
        )
        .one()
    )

    brand.campaign_rules = {
        "verified_operational_strategy_keys": [
            chosen_type.key,
            alternative_type.key,
        ],
    }
    session.commit()

    campaign = _make_campaign(session, brand, category, strategy_type_id=chosen_type.id)
    campaign.angle = chosen_type.name
    session.commit()

    provider = FakeAutopilotProvider()
    result = await run_autopilot(
        session, campaign_id=campaign.id, ai_provider=provider, research_provider=provider,
        renderer=shared_renderer, config=_config(tmp_path),
    )

    assert result.strategy_type_id == chosen_type.id
    assert result.angle == "Guerrilla Marketing"
    session.close()


# --------------------------------------------------------------------------------
# Campaign Builder advanced mode: the same pipeline, run as three separate stages
# (services/orchestrator.py's run_strategy_stage/run_copy_stage/run_visuals_stage).
# --------------------------------------------------------------------------------


async def test_strategy_stage_alone_reaches_brief_ready_and_persists_output(temp_db, tmp_path):
    session = temp_db.SessionLocal()
    brand, category, assets = _make_brand_and_assets(session, tmp_path)
    campaign = _make_campaign(session, brand, category)
    provider = FakeAutopilotProvider()

    result = await run_strategy_stage(
        session, campaign_id=campaign.id, ai_provider=provider, research_provider=provider,
        config=_config(tmp_path),
    )

    assert result.status == "BRIEF_READY"
    assert result.angle == "Build your routine"
    assert result.main_promise == "Everything you need for a 5-step routine"
    # No copy or visuals should exist yet — this stage stops before either.
    assert result.hook == ""
    assert len(result.slides) == 0

    strategy_output = (
        session.query(CampaignOutput)
        .filter(CampaignOutput.campaign_id == campaign.id, CampaignOutput.kind == "strategy")
        .one()
    )
    assert Path(strategy_output.file_path).exists()
    session.close()


async def test_copy_stage_requires_strategy_output_first(temp_db, tmp_path):
    session = temp_db.SessionLocal()
    brand, category, assets = _make_brand_and_assets(session, tmp_path)
    campaign = _make_campaign(session, brand, category)
    provider = FakeAutopilotProvider()

    with pytest.raises(ValueError, match="Run the Strategy stage"):
        await run_copy_stage(session, campaign_id=campaign.id, ai_provider=provider, config=_config(tmp_path))
    session.close()


async def test_visuals_stage_requires_copy_output_first(temp_db, tmp_path, shared_renderer):
    session = temp_db.SessionLocal()
    brand, category, assets = _make_brand_and_assets(session, tmp_path)
    campaign = _make_campaign(session, brand, category)

    with pytest.raises(ValueError, match="Run the Copy stage"):
        await run_visuals_stage(session, campaign_id=campaign.id, renderer=shared_renderer, config=_config(tmp_path))
    session.close()


async def test_three_stages_run_separately_reach_review_like_full_autopilot(temp_db, tmp_path, shared_renderer):
    """The actual Campaign Builder advanced-mode flow: Strategy, then Copy, then
    Visuals, called one at a time (as three separate HTTP requests would) rather
    than via run_autopilot — each stage reads back the prior stage's persisted
    output instead of being handed it directly.
    """
    session = temp_db.SessionLocal()
    brand, category, assets = _make_brand_and_assets(session, tmp_path)
    campaign = _make_campaign(session, brand, category)
    provider = FakeAutopilotProvider()
    config = _config(tmp_path)

    strategy_result = await run_strategy_stage(
        session, campaign_id=campaign.id, ai_provider=provider, research_provider=provider, config=config,
    )
    assert strategy_result.status == "BRIEF_READY"

    copy_result = await run_copy_stage(session, campaign_id=campaign.id, ai_provider=provider, config=config)
    assert copy_result.status == "COPY_READY"
    assert copy_result.hook == "Your skin deserves this"
    assert copy_result.cta == "Shop now"

    visuals_result = await run_visuals_stage(
        session, campaign_id=campaign.id, renderer=shared_renderer, config=config,
    )
    assert visuals_result.status == "REVIEW"
    assert len(visuals_result.slides) == 2
    for slide in visuals_result.slides:
        assert slide.rendered_asset_path
        assert Path(slide.rendered_asset_path).exists()

    fingerprint = session.query(CampaignFingerprint).filter(CampaignFingerprint.campaign_id == campaign.id).one()
    assert fingerprint.angle == "Build your routine"
    assert provider.research_calls == 1
    session.close()


async def test_copy_stage_can_rerun_without_moving_status_backward(temp_db, tmp_path, shared_renderer):
    """Regenerating copy on a campaign that's already past COPY_READY (e.g. already
    in REVIEW after Visuals ran) shouldn't silently revert its status — only a
    campaign still at BRIEF_READY/FAILED should advance to COPY_READY.
    """
    session = temp_db.SessionLocal()
    brand, category, assets = _make_brand_and_assets(session, tmp_path)
    campaign = _make_campaign(session, brand, category)
    provider = FakeAutopilotProvider()
    config = _config(tmp_path)

    await run_strategy_stage(
        session, campaign_id=campaign.id, ai_provider=provider, research_provider=provider, config=config,
    )
    await run_copy_stage(session, campaign_id=campaign.id, ai_provider=provider, config=config)
    await run_visuals_stage(session, campaign_id=campaign.id, renderer=shared_renderer, config=config)

    session.refresh(campaign)
    assert campaign.status == "REVIEW"

    # Regenerate copy again now that the campaign has already reached REVIEW.
    result = await run_copy_stage(session, campaign_id=campaign.id, ai_provider=provider, config=config)
    assert result.status == "REVIEW"  # unchanged, not reverted to COPY_READY
    session.close()


class FakeImageProvider:
    """Minimal ImageProvider stand-in for testing `generate_ai_background` / the
    `use_ai_background` wiring in `run_visuals_stage` — records every call so tests
    can assert the brand's visual-reference photos and prompt actually reached it,
    without a real OpenAI key or network call. Returns real (small) PNG bytes on
    success, since `generate_ai_background` opens the result with `PIL.Image.open`.
    """

    def __init__(self, *, raises: bool = False):
        self.calls: list[dict] = []
        self._raises = raises

    async def generate(self, *, prompt, size, model, reference_images=None, quality="high"):
        self.calls.append({"prompt": prompt, "size": size, "model": model, "reference_images": reference_images})
        if self._raises:
            raise RuntimeError("simulated image API failure")
        import io
        buf = io.BytesIO()
        Image.new("RGB", (64, 64), (200, 100, 50)).save(buf, format="PNG")
        return buf.getvalue()

    async def edit(self, *, base_image, prompt, model, mask=None, quality="high"):
        raise NotImplementedError


async def test_visuals_stage_uses_ai_background_when_enabled(temp_db, tmp_path, shared_renderer):
    """`use_ai_background=True` + an `image_provider` should route each slide's
    background through `generate_ai_background` (and therefore the fake image
    provider) instead of the deterministic gradient, and should hand it the
    brand's uploaded visual-reference photo as a style reference.
    """
    session = temp_db.SessionLocal()
    brand, category, assets = _make_brand_and_assets(session, tmp_path)
    ref_path = tmp_path / "reference.jpg"
    Image.new("RGB", (400, 400), (240, 230, 210)).save(ref_path)
    session.add(BrandAsset(brand_id=brand.id, kind="visual_reference", file_path=str(ref_path)))
    session.commit()

    campaign = _make_campaign(session, brand, category)
    provider = FakeAutopilotProvider()
    base_config = _config(tmp_path)

    await run_strategy_stage(
        session, campaign_id=campaign.id, ai_provider=provider, research_provider=provider, config=base_config,
    )
    await run_copy_stage(session, campaign_id=campaign.id, ai_provider=provider, config=base_config)

    image_provider = FakeImageProvider()
    ai_config = replace(base_config, use_ai_background=True)
    result = await run_visuals_stage(
        session, campaign_id=campaign.id, renderer=shared_renderer, config=ai_config,
        image_provider=image_provider,
    )

    assert result.status == "REVIEW"
    assert len(image_provider.calls) == 2  # one per rendered slide
    call = image_provider.calls[0]
    assert brand.name in call["prompt"]
    assert call["reference_images"] == [ref_path]
    session.close()


async def test_visuals_stage_falls_back_to_gradient_when_ai_background_fails(temp_db, tmp_path, shared_renderer):
    """An AI-generated background is a nice-to-have layered on a pipeline that has
    always worked with a deterministic gradient — a failure generating it (bad key,
    rate limit, whatever) must never take down a render that would otherwise have
    succeeded.
    """
    session = temp_db.SessionLocal()
    brand, category, assets = _make_brand_and_assets(session, tmp_path)
    campaign = _make_campaign(session, brand, category)
    provider = FakeAutopilotProvider()
    base_config = _config(tmp_path)

    await run_strategy_stage(
        session, campaign_id=campaign.id, ai_provider=provider, research_provider=provider, config=base_config,
    )
    await run_copy_stage(session, campaign_id=campaign.id, ai_provider=provider, config=base_config)

    failing_image_provider = FakeImageProvider(raises=True)
    ai_config = replace(base_config, use_ai_background=True)
    result = await run_visuals_stage(
        session, campaign_id=campaign.id, renderer=shared_renderer, config=ai_config,
        image_provider=failing_image_provider,
    )

    assert result.status == "REVIEW"
    assert len(result.slides) == 2
    for slide in result.slides:
        assert Path(slide.rendered_asset_path).exists()
    assert len(failing_image_provider.calls) == 2  # it was tried for every slide, just failed each time
    session.close()


async def test_visuals_stage_rejects_recreate_with_ai_when_enabled(
    temp_db, tmp_path, shared_renderer
):
    """Full AI product recreation is no longer a supported visuals mode."""

    session = temp_db.SessionLocal()

    image_provider = FakeImageProvider()
    provider = FakeAutopilotProvider()

    config = replace(
        _config(tmp_path),
        recreate_with_ai=True,
        use_ai_background=True,
    )

    caught = None

    try:
        await run_visuals_stage(
            session,
            campaign_id="immutable-product-contract",
            renderer=shared_renderer,
            config=config,
            image_provider=image_provider,
            ai_provider=provider,
        )
    except RuntimeError as exc:
        caught = exc
    finally:
        session.close()

    assert caught is not None

    assert (
        "Full AI product recreation is prohibited"
        in str(caught)
    )

    assert image_provider.calls == []
    assert provider.fidelity_calls == []



async def test_visuals_stage_does_not_fallback_from_prohibited_full_recreation(
    temp_db, tmp_path, shared_renderer
):
    """A prohibited rendering architecture is rejected, not treated as an
    optional enhancement whose generation failure should silently fall back.
    """

    session = temp_db.SessionLocal()

    image_provider = FakeImageProvider(
        raises=True
    )

    provider = FakeAutopilotProvider()

    config = replace(
        _config(tmp_path),
        recreate_with_ai=True,
    )

    caught = None

    try:
        await run_visuals_stage(
            session,
            campaign_id="immutable-product-contract",
            renderer=shared_renderer,
            config=config,
            image_provider=image_provider,
            ai_provider=provider,
        )
    except RuntimeError as exc:
        caught = exc
    finally:
        session.close()

    assert caught is not None

    assert (
        "immutable-product-layer contract"
        in str(caught)
    )

    assert image_provider.calls == []
    assert provider.fidelity_calls == []



async def test_recreate_creative_image_includes_inspiration_reference_photos(temp_db, tmp_path):
    """A direct unit test of `recreate_creative_image` (not the full stage): the
    real source photo is always the first reference image, category-scoped
    inspiration examples are preferred over brand-wide ones, and the prompt names
    the brand and the campaign's own angle/promise rather than being generic.
    """
    session = temp_db.SessionLocal()
    brand, category, assets = _make_brand_and_assets(session, tmp_path, num_assets=1)

    scoped_path = tmp_path / "inspiration-scoped.jpg"
    Image.new("RGB", (300, 300), (10, 10, 10)).save(scoped_path)
    session.add(BrandAsset(brand_id=brand.id, kind="inspiration", category_id=category.id, file_path=str(scoped_path)))

    brand_wide_path = tmp_path / "inspiration-brand-wide.jpg"
    Image.new("RGB", (300, 300), (20, 20, 20)).save(brand_wide_path)
    session.add(BrandAsset(brand_id=brand.id, kind="inspiration", category_id=None, file_path=str(brand_wide_path)))
    session.commit()

    image_provider = FakeImageProvider()
    result = await recreate_creative_image(
        session, image_provider=image_provider, brand=brand, category_id=category.id,
        source_image_path=Path(assets[0].absolute_path), model="gpt-image-1", width=1080, height=1080,
        angle="Build your routine", main_promise="Everything for a 5-step routine",
    )

    assert result is not None
    assert len(image_provider.calls) == 1
    call = image_provider.calls[0]
    assert call["reference_images"][0] == Path(assets[0].absolute_path)
    assert scoped_path in call["reference_images"]
    assert brand.name in call["prompt"]
    assert "Build your routine" in call["prompt"]
    session.close()


async def test_recreate_creative_image_returns_none_on_failure(temp_db, tmp_path):
    session = temp_db.SessionLocal()
    brand, category, assets = _make_brand_and_assets(session, tmp_path, num_assets=1)
    failing_image_provider = FakeImageProvider(raises=True)

    result = await recreate_creative_image(
        session, image_provider=failing_image_provider, brand=brand, category_id=category.id,
        source_image_path=Path(assets[0].absolute_path), model="gpt-image-1", width=1080, height=1080,
    )

    assert result is None
    session.close()


async def test_visuals_stage_uses_gradient_by_default(temp_db, tmp_path, shared_renderer):
    """The no-key, gradient-background behavior documented since the Campaign
    Builder advanced-mode round must stay the default — use_ai_background defaults
    to False and no image_provider is required.
    """
    session = temp_db.SessionLocal()
    brand, category, assets = _make_brand_and_assets(session, tmp_path)
    campaign = _make_campaign(session, brand, category)
    provider = FakeAutopilotProvider()
    config = _config(tmp_path)
    assert config.use_ai_background is False

    await run_strategy_stage(
        session, campaign_id=campaign.id, ai_provider=provider, research_provider=provider, config=config,
    )
    await run_copy_stage(session, campaign_id=campaign.id, ai_provider=provider, config=config)
    result = await run_visuals_stage(session, campaign_id=campaign.id, renderer=shared_renderer, config=config)

    assert result.status == "REVIEW"
    session.close()


async def test_visuals_stage_defaults_to_feature_showcase_and_renders_its_fields(temp_db, tmp_path, shared_renderer):
    """Round 17: `feature_showcase` (badge/intro/feature-list/callout/bottom-strip/
    CTA-bar — see services/creative/templates.py) is now the default template, and
    a carousel plan carrying those fields (as `run_copy_stage`'s prompt now asks
    the model for) must actually reach the render — not just the plain eyebrow/
    headline/body/cta a plainer plan would produce. Also confirms the richer
    fields round-trip through the persisted `creative` stage JSON (see
    `_slide_plan_to_dict`), which is what makes a later re-render without
    re-running Copy still see them.
    """
    session = temp_db.SessionLocal()
    brand, category, assets = _make_brand_and_assets(session, tmp_path)
    campaign = _make_campaign(session, brand, category)
    plan = CarouselPlan(
        slides=[
            SlidePlan(
                slide_number=1, purpose="hero", eyebrow="New", headline="Slide one headline",
                body="Slide one body", cta="Shop now", visual_brief="Hero product shot",
                badge_text="Best Seller", intro="Loved across Brazil.",
                features=[
                    SlideFeature(icon="\U0001F4A7", title="Deep hydration", subtitle="24h moisture"),
                    SlideFeature(icon="\U0001F343", title="Natural", subtitle="No parabens"),
                ],
                callout_label="Key ingredient", callout_value="Niacinamide 10%",
                bottom_features=["Ships nationwide"], trust_badges=["Guaranteed"],
            ),
            SlidePlan(
                slide_number=2, purpose="benefit", headline="Slide two headline",
                body="Slide two body", cta="Shop now", visual_brief="Detail shot",
            ),
        ],
        narrative_summary="A two-slide carousel.",
    )
    provider = FakeAutopilotProvider(carousel_plan=plan)
    config = _config(tmp_path)
    assert config.template_id == "feature_showcase"

    await run_strategy_stage(
        session, campaign_id=campaign.id, ai_provider=provider, research_provider=provider, config=config,
    )
    await run_copy_stage(session, campaign_id=campaign.id, ai_provider=provider, config=config)
    result = await run_visuals_stage(session, campaign_id=campaign.id, renderer=shared_renderer, config=config)

    assert result.status == "REVIEW"
    assert len(result.slides) == 2
    for slide in result.slides:
        assert Path(slide.rendered_asset_path).exists()

    creative_output = (
        session.query(CampaignOutput)
        .filter(CampaignOutput.campaign_id == campaign.id, CampaignOutput.kind == "creative")
        .one()
    )
    creative_data = json.loads(Path(creative_output.file_path).read_text())
    # Build 1: creative JSON is now nested per language (see run_copy_stage) —
    # read back the primary language's variant.
    primary_variant = creative_data["languages"][creative_data["primary_language"]]
    slide_one = primary_variant["carousel_plan"]["slides"][0]
    assert slide_one["badge_text"] == "Best Seller"
    assert slide_one["callout_value"] == "Niacinamide 10%"
    assert slide_one["features"][0]["title"] == "Deep hydration"
    assert slide_one["bottom_features"] == ["Ships nationwide"]
    session.close()


async def test_visuals_stage_uses_product_zone_detection_when_enabled(temp_db, tmp_path, shared_renderer):
    """`detect_product_zone=True` + an `ai_provider` should call
    `AIProvider.detect_product_zone` once per rendered slide (via
    `services/orchestrator.py::detect_product_zone`) instead of relying purely on
    the template's one fixed layout.
    """
    session = temp_db.SessionLocal()
    brand, category, assets = _make_brand_and_assets(session, tmp_path)
    campaign = _make_campaign(session, brand, category)
    provider = FakeAutopilotProvider()
    base_config = _config(tmp_path)

    await run_strategy_stage(
        session, campaign_id=campaign.id, ai_provider=provider, research_provider=provider, config=base_config,
    )
    await run_copy_stage(session, campaign_id=campaign.id, ai_provider=provider, config=base_config)

    zone_config = replace(base_config, detect_product_zone=True, vision_model="gpt-5.1")
    result = await run_visuals_stage(
        session, campaign_id=campaign.id, renderer=shared_renderer, config=zone_config, ai_provider=provider,
    )

    assert result.status == "REVIEW"
    assert len(provider.zone_detection_calls) == 2  # one per rendered slide
    assert provider.zone_detection_calls[0]["model"] == "gpt-5.1"
    session.close()


async def test_visuals_stage_falls_back_to_template_zone_when_detection_fails(temp_db, tmp_path, shared_renderer):
    """A per-photo zone detection is a refinement layered on a pipeline that has
    always worked with the template's fixed layout — a failure detecting it (bad
    key, rate limit, malformed response) must never take down a render that would
    otherwise have succeeded.
    """
    session = temp_db.SessionLocal()
    brand, category, assets = _make_brand_and_assets(session, tmp_path)
    campaign = _make_campaign(session, brand, category)
    provider = FakeAutopilotProvider(zone_detection_raises=True)
    base_config = _config(tmp_path)

    await run_strategy_stage(
        session, campaign_id=campaign.id, ai_provider=provider, research_provider=provider, config=base_config,
    )
    await run_copy_stage(session, campaign_id=campaign.id, ai_provider=provider, config=base_config)

    zone_config = replace(base_config, detect_product_zone=True)
    result = await run_visuals_stage(
        session, campaign_id=campaign.id, renderer=shared_renderer, config=zone_config, ai_provider=provider,
    )

    assert result.status == "REVIEW"
    assert len(result.slides) == 2
    for slide in result.slides:
        assert Path(slide.rendered_asset_path).exists()
    assert len(provider.zone_detection_calls) == 2  # it was tried for every slide, just failed each time
    session.close()


async def test_visuals_stage_skips_detection_by_default(temp_db, tmp_path, shared_renderer):
    """The template-fixed-layout behavior that predates this feature must stay the
    default — detect_product_zone defaults to False and no ai_provider is required.
    """
    session = temp_db.SessionLocal()
    brand, category, assets = _make_brand_and_assets(session, tmp_path)
    campaign = _make_campaign(session, brand, category)
    provider = FakeAutopilotProvider()
    config = _config(tmp_path)
    assert config.detect_product_zone is False

    await run_strategy_stage(
        session, campaign_id=campaign.id, ai_provider=provider, research_provider=provider, config=config,
    )
    await run_copy_stage(session, campaign_id=campaign.id, ai_provider=provider, config=config)
    result = await run_visuals_stage(session, campaign_id=campaign.id, renderer=shared_renderer, config=config)

    assert result.status == "REVIEW"
    assert provider.zone_detection_calls == []
    session.close()


# --------------------------------------------------------------------------------
# Round 16: AI-baked-in marketing text + custom carousel length
# (campaign.target_slide_count / recreate_creative_image's headline/body/cta/eyebrow).
# --------------------------------------------------------------------------------


async def test_recreate_creative_image_bakes_text_in_with_legibility_instruction(temp_db, tmp_path):
    """When headline/body/cta/eyebrow are passed, the prompt sent to the image
    provider must contain the exact text (so the model doesn't invent its own copy),
    the legibility/backing instruction, and a "no logo" instruction — but must NOT
    contain the old blanket "do not render any text" instruction, since that's
    exactly what round 16 reverses for this case.
    """
    session = temp_db.SessionLocal()
    brand, category, assets = _make_brand_and_assets(session, tmp_path, num_assets=1)
    image_provider = FakeImageProvider()

    result = await recreate_creative_image(
        session, image_provider=image_provider, brand=brand, category_id=category.id,
        source_image_path=Path(assets[0].absolute_path), model="gpt-image-1", width=1080, height=1080,
        eyebrow="New", headline="Maximum results in 7 days", body="Feel the difference fast", cta="Shop now",
    )

    assert result is not None
    call = image_provider.calls[0]
    prompt = call["prompt"]
    assert "Maximum results in 7 days" in prompt
    assert "Feel the difference fast" in prompt
    assert "Shop now" in prompt
    assert "New" in prompt
    assert "proper" in prompt and "backing" in prompt  # legibility instruction
    assert "Do not render any logo" in prompt
    assert "Do not render any text, words, captions, or logos" not in prompt
    session.close()


async def test_recreate_creative_image_omits_text_when_none_given(temp_db, tmp_path):
    """The original behavior (no headline/body/cta/eyebrow passed) must be
    unchanged: the prompt still tells the model to leave text and logos out
    entirely, for the case where the app's own HTML/CSS layer will draw them.
    """
    session = temp_db.SessionLocal()
    brand, category, assets = _make_brand_and_assets(session, tmp_path, num_assets=1)
    image_provider = FakeImageProvider()

    result = await recreate_creative_image(
        session, image_provider=image_provider, brand=brand, category_id=category.id,
        source_image_path=Path(assets[0].absolute_path), model="gpt-image-1", width=1080, height=1080,
    )

    assert result is not None
    prompt = image_provider.calls[0]["prompt"]
    assert "Do not render any text, words, captions, or logos" in prompt
    assert "Do not render any logo — the real brand logo is added separately" not in prompt
    session.close()


async def test_visuals_stage_never_bakes_text_into_ai_recreated_product_pixels(
    temp_db, tmp_path, shared_renderer
):
    """Marketing text must not be baked into a full AI recreation because
    full AI product recreation itself is prohibited.
    """

    session = temp_db.SessionLocal()

    image_provider = FakeImageProvider()
    provider = FakeAutopilotProvider()

    config = replace(
        _config(tmp_path),
        recreate_with_ai=True,
    )

    caught = None

    try:
        await run_visuals_stage(
            session,
            campaign_id="immutable-product-contract",
            renderer=shared_renderer,
            config=config,
            image_provider=image_provider,
            ai_provider=provider,
        )
    except RuntimeError as exc:
        caught = exc
    finally:
        session.close()

    assert caught is not None

    assert (
        "Full AI product recreation is prohibited"
        in str(caught)
    )

    assert image_provider.calls == []




# --------------------------------------------------------------------------------
# Round 18: product-fidelity gate around full AI recreation, cross-slide "visual
# master" consistency, and the "N/total" slide-number marker.
# --------------------------------------------------------------------------------


async def test_visuals_stage_rejects_recreation_even_without_ai_provider(
    temp_db, tmp_path, shared_renderer
):
    """The immutable-product rule is architectural and does not depend on
    whether a fidelity-check provider is available.
    """

    session = temp_db.SessionLocal()

    image_provider = FakeImageProvider()

    config = replace(
        _config(tmp_path),
        recreate_with_ai=True,
    )

    caught = None

    try:
        await run_visuals_stage(
            session,
            campaign_id="immutable-product-contract",
            renderer=shared_renderer,
            config=config,
            image_provider=image_provider,
        )
    except RuntimeError as exc:
        caught = exc
    finally:
        session.close()

    assert caught is not None

    assert (
        "Full AI product recreation is prohibited"
        in str(caught)
    )

    assert image_provider.calls == []



async def test_fidelity_gate_returns_verified_image_on_first_pass(temp_db, tmp_path):
    """Direct unit test of the gate: a PASS on the first attempt returns the
    image already marked verified, with no retry.
    """
    session = temp_db.SessionLocal()
    brand, category, assets = _make_brand_and_assets(session, tmp_path, num_assets=1)
    provider = FakeAutopilotProvider()
    image_provider = FakeImageProvider()

    outcome = await recreate_creative_image_with_fidelity_gate(
        session, image_provider=image_provider, ai_provider=provider, brand=brand, category_id=category.id,
        source_image_path=Path(assets[0].absolute_path), model="gpt-image-1", vision_model="gpt-5.1",
        width=1080, height=1080,
    )

    assert isinstance(outcome, RecreationOutcome)
    assert outcome.image is not None
    assert outcome.verified is True
    assert outcome.attempts == 1
    assert len(image_provider.calls) == 1
    assert len(provider.fidelity_calls) == 1
    session.close()


async def test_fidelity_gate_retries_once_then_succeeds(temp_db, tmp_path):
    """A FAIL on the first attempt must trigger exactly one corrective retry —
    and the retry's prompt must name what didn't match, per `recreate_creative_
    image`'s `correction_note` — rather than silently giving up or retrying
    forever.
    """
    session = temp_db.SessionLocal()
    brand, category, assets = _make_brand_and_assets(session, tmp_path, num_assets=1)
    failed_check = ProductFidelityCheck(
        brand_logo="mismatch", overall_verdict="FAIL", reasoning="Logo shape looked different.",
    )
    passed_check = ProductFidelityCheck(overall_verdict="PASS", reasoning="Matches now.")
    provider = FakeAutopilotProvider(fidelity_checks=[failed_check, passed_check])
    image_provider = FakeImageProvider()

    outcome = await recreate_creative_image_with_fidelity_gate(
        session, image_provider=image_provider, ai_provider=provider, brand=brand, category_id=category.id,
        source_image_path=Path(assets[0].absolute_path), model="gpt-image-1", vision_model="gpt-5.1",
        width=1080, height=1080,
    )

    assert outcome.image is not None
    assert outcome.verified is True
    assert outcome.attempts == 2
    assert len(image_provider.calls) == 2
    assert "brand/logo" in image_provider.calls[1]["prompt"]  # the retry's corrective prompt
    assert "CRITICAL CORRECTION" in image_provider.calls[1]["prompt"]
    assert "CRITICAL CORRECTION" not in image_provider.calls[0]["prompt"]  # not on the first attempt
    session.close()


async def test_fidelity_gate_falls_back_after_persistent_failure(temp_db, tmp_path):
    """A recreation that still doesn't pass after the one retry must give up —
    `image=None` — rather than ship an unverified product image; the caller
    (`run_visuals_stage`) falls back to the deterministic pipeline for that
    slide.
    """
    session = temp_db.SessionLocal()
    brand, category, assets = _make_brand_and_assets(session, tmp_path, num_assets=1)
    always_fails = ProductFidelityCheck(overall_verdict="FAIL", reasoning="Still wrong.")
    provider = FakeAutopilotProvider(fidelity_checks=[always_fails])
    image_provider = FakeImageProvider()

    outcome = await recreate_creative_image_with_fidelity_gate(
        session, image_provider=image_provider, ai_provider=provider, brand=brand, category_id=category.id,
        source_image_path=Path(assets[0].absolute_path), model="gpt-image-1", vision_model="gpt-5.1",
        width=1080, height=1080,
    )

    assert outcome.image is None
    assert outcome.verified is False
    assert outcome.attempts == 2
    assert len(image_provider.calls) == 2  # the original attempt plus one retry, never more
    session.close()


async def test_fidelity_gate_treats_check_error_as_not_verified(temp_db, tmp_path):
    """A fidelity check that errors (bad key, rate limit, malformed response) must
    be treated exactly like a FAIL — fail-closed — never like an implicit PASS.
    """
    session = temp_db.SessionLocal()
    brand, category, assets = _make_brand_and_assets(session, tmp_path, num_assets=1)
    provider = FakeAutopilotProvider(fidelity_raises=True)
    image_provider = FakeImageProvider()

    outcome = await recreate_creative_image_with_fidelity_gate(
        session, image_provider=image_provider, ai_provider=provider, brand=brand, category_id=category.id,
        source_image_path=Path(assets[0].absolute_path), model="gpt-image-1", vision_model="gpt-5.1",
        width=1080, height=1080,
    )

    assert outcome.image is None
    assert outcome.verified is False
    assert outcome.attempts == 2  # still retried once, since a check error isn't distinguished from a FAIL
    session.close()


async def test_visuals_stage_does_not_use_prior_slide_as_full_recreation_master(
    temp_db, tmp_path, shared_renderer
):
    """Carousel continuity must not be implemented by feeding a previously
    rendered slide into a full product-recreation edit path.
    """

    session = temp_db.SessionLocal()

    image_provider = FakeImageProvider()
    provider = FakeAutopilotProvider()

    config = replace(
        _config(tmp_path),
        recreate_with_ai=True,
    )

    caught = None

    try:
        await run_visuals_stage(
            session,
            campaign_id="immutable-product-contract",
            renderer=shared_renderer,
            config=config,
            image_provider=image_provider,
            ai_provider=provider,
        )
    except RuntimeError as exc:
        caught = exc
    finally:
        session.close()

    assert caught is not None

    assert (
        "Full AI product recreation is prohibited"
        in str(caught)
    )

    assert image_provider.calls == []
    assert provider.fidelity_calls == []



async def test_visuals_stage_renders_all_planned_slides_even_with_one_source_photo(
    temp_db, tmp_path, shared_renderer
):
    """Round 18 bug fix: the carousel must NOT be truncated down to however many
    distinct source photos exist for the product/category. A user with just one
    uploaded product photo, asking for a 6-slide carousel, must still get all 6
    rendered slides — round-robining (reusing) that one photo across every slide
    — rather than silently collapsing to a single slide. This is the exact
    real-world bug report: "it only added text to the picture I already gave"
    when 6 slides were expected.
    """
    session = temp_db.SessionLocal()
    brand, category, assets = _make_brand_and_assets(session, tmp_path, num_assets=1)
    campaign = _make_campaign(session, brand, category)
    campaign.target_slide_count = 6
    session.commit()

    six_slide_plan = CarouselPlan(
        slides=[
            SlidePlan(
                slide_number=i, purpose="hero", eyebrow="", headline=f"Headline {i}",
                body=f"Body {i}", cta="Shop now", visual_brief="Product shot",
            )
            for i in range(1, 7)
        ],
        narrative_summary="A six-slide plan built from a single source photo.",
    )
    provider = FakeAutopilotProvider(carousel_plan=six_slide_plan)
    config = _config(tmp_path)

    await run_strategy_stage(
        session, campaign_id=campaign.id, ai_provider=provider, research_provider=provider, config=config,
    )
    await run_copy_stage(session, campaign_id=campaign.id, ai_provider=provider, config=config)
    result = await run_visuals_stage(session, campaign_id=campaign.id, renderer=shared_renderer, config=config)

    assert len(result.slides) == 6
    assert [s.headline for s in sorted(result.slides, key=lambda s: s.slide_number)] == [
        f"Headline {i}" for i in range(1, 7)
    ]
    # The single asset was reused (round-robined) across every slide, not just slide 1.
    assert all(s.source_asset_id == assets[0].id for s in result.slides)
    session.refresh(assets[0])
    # Bookkeeping: reused 6 times in this one run, so times_used reflects 6 real usages.
    assert assets[0].times_used == 6
    session.close()


async def test_visuals_stage_uses_the_campaigns_own_platform_key_when_set(temp_db, tmp_path, shared_renderer):
    """Round 20: a campaign that picked its own platform/format must render at
    THAT platform's dimensions, not AutopilotConfig's default
    ("instagram_square", 1080x1080) — the whole point of letting a campaign pick
    a real social platform up front so its slides come out the right size.
    """
    from PIL import Image

    session = temp_db.SessionLocal()
    brand, category, _assets = _make_brand_and_assets(session, tmp_path, num_assets=1)
    campaign = _make_campaign(session, brand, category)
    campaign.platform_key = "instagram_portrait"  # 1080x1350 — deliberately NOT the config default
    session.commit()

    one_slide_plan = CarouselPlan(
        slides=[
            SlidePlan(
                slide_number=1, purpose="hero", eyebrow="", headline="Headline",
                body="Body", cta="Shop now", visual_brief="Product shot",
            )
        ],
        narrative_summary="A one-slide plan to check platform sizing.",
    )
    provider = FakeAutopilotProvider(carousel_plan=one_slide_plan)
    config = _config(tmp_path)
    assert config.platform_key == "instagram_square"  # the default this test proves gets overridden

    await run_strategy_stage(
        session, campaign_id=campaign.id, ai_provider=provider, research_provider=provider, config=config,
    )
    await run_copy_stage(session, campaign_id=campaign.id, ai_provider=provider, config=config)
    result = await run_visuals_stage(session, campaign_id=campaign.id, renderer=shared_renderer, config=config)

    assert len(result.slides) == 1
    rendered_path = result.slides[0].rendered_asset_path
    with Image.open(rendered_path) as img:
        assert img.size == (1080, 1350)  # instagram_portrait, not config's 1080x1080 default
    session.close()


async def test_visuals_stage_falls_back_to_config_platform_key_when_campaign_has_none(
    temp_db, tmp_path, shared_renderer
):
    """The other half of the same behavior: a campaign with no platform_key of its
    own (every campaign created before round 20, or one that hasn't picked one)
    must render at exactly AutopilotConfig's default, unchanged from before this
    field existed.
    """
    from PIL import Image

    session = temp_db.SessionLocal()
    brand, category, _assets = _make_brand_and_assets(session, tmp_path, num_assets=1)
    campaign = _make_campaign(session, brand, category)
    assert campaign.platform_key is None
    session.commit()

    one_slide_plan = CarouselPlan(
        slides=[
            SlidePlan(
                slide_number=1, purpose="hero", eyebrow="", headline="Headline",
                body="Body", cta="Shop now", visual_brief="Product shot",
            )
        ],
        narrative_summary="A one-slide plan to check the fallback default.",
    )
    provider = FakeAutopilotProvider(carousel_plan=one_slide_plan)
    config = _config(tmp_path)

    await run_strategy_stage(
        session, campaign_id=campaign.id, ai_provider=provider, research_provider=provider, config=config,
    )
    await run_copy_stage(session, campaign_id=campaign.id, ai_provider=provider, config=config)
    result = await run_visuals_stage(session, campaign_id=campaign.id, renderer=shared_renderer, config=config)

    rendered_path = result.slides[0].rendered_asset_path
    with Image.open(rendered_path) as img:
        assert img.size == (1080, 1080)  # config's own "instagram_square" default, untouched
    session.close()


def test_brand_creative_instructions_block_is_empty_for_a_brand_that_never_set_one():
    from app.services.orchestrator import _brand_creative_instructions_block
    from app.models import Brand

    assert _brand_creative_instructions_block(Brand(name="Hanna", slug="hanna")) == ""
    assert _brand_creative_instructions_block(Brand(name="Hanna", slug="hanna", creative_instructions="   ")) == ""


def test_brand_creative_instructions_block_labels_and_includes_the_brands_own_text():
    from app.services.orchestrator import _brand_creative_instructions_block
    from app.models import Brand

    brand = Brand(name="Hanna", slug="hanna", creative_instructions="Never show the cap off the bottle.")
    note = _brand_creative_instructions_block(brand)
    assert "Never show the cap off the bottle." in note
    assert "standing creative instructions" in note  # labeled, not blended in unmarked


async def test_copy_stage_prompt_includes_the_brands_creative_instructions_when_set(temp_db, tmp_path):
    """The whole point of round 20's `creative_instructions` field: it must
    actually reach the AI call, not just exist in the database unread — checked
    directly on the fake provider's captured prompt, the same way round 19's
    discovery-ordering test checks the copy-stage prompt.
    """
    session = temp_db.SessionLocal()
    brand, category, _assets = _make_brand_and_assets(session, tmp_path, num_assets=1)
    brand.creative_instructions = "Always write the CTA in all caps."
    session.commit()
    campaign = _make_campaign(session, brand, category)
    session.commit()

    provider = FakeAutopilotProvider()
    config = _config(tmp_path)
    await run_strategy_stage(
        session, campaign_id=campaign.id, ai_provider=provider, research_provider=provider, config=config,
    )
    await run_copy_stage(session, campaign_id=campaign.id, ai_provider=provider, config=config)

    all_prompts = " ".join(provider.user_prompts)
    assert "Always write the CTA in all caps." in all_prompts
    assert "standing creative instructions" in all_prompts
    session.close()


# --- Round 19: multi-product "discovery" carousels -------------------------------
# The other campaign shape the user described (verbatim): "discoveries campaigns
# that should use many different products and each product should be one slide,
# while other campaigns it should [be] one product and transform into a 20 slide
# carrousel[]". Deep-dive (one product, many slides) is everything above; these
# tests cover discovery (many products, one slide each) — active only when
# `Campaign.product_id` is unset AND at least one product has been hand-picked via
# `CampaignDiscoveryProduct` (see api/campaigns.py's PUT /discovery-products).

async def test_copy_stage_plans_one_slide_per_discovery_product_in_order(temp_db, tmp_path):
    session = temp_db.SessionLocal()
    brand, category, _base_assets = _make_brand_and_assets(session, tmp_path, num_assets=0)
    products = _make_discovery_products(session, brand, category, tmp_path, ["Cleanser", "Toner", "Serum"])
    campaign = _make_campaign(session, brand, category)  # no product_id -> category-only
    _set_discovery_products(session, campaign, products)

    three_slide_plan = CarouselPlan(
        slides=[
            SlidePlan(
                slide_number=i, purpose="hero", eyebrow="", headline=f"Headline {i}",
                body=f"Body {i}", cta="Shop now", visual_brief="Product shot",
            )
            for i in range(1, 4)
        ],
        narrative_summary="One slide per featured product.",
    )
    provider = FakeAutopilotProvider(carousel_plan=three_slide_plan)
    config = _config(tmp_path)

    await run_strategy_stage(
        session, campaign_id=campaign.id, ai_provider=provider, research_provider=provider, config=config,
    )
    await run_copy_stage(session, campaign_id=campaign.id, ai_provider=provider, config=config)

    carousel_prompts = [
        prompt for schema, prompt in zip(provider.schema_calls, provider.user_prompts) if schema is CarouselPlan
    ]
    assert len(carousel_prompts) == 1
    prompt = carousel_prompts[0]
    # All three product names appear, in the picked order.
    assert prompt.index("Cleanser") < prompt.index("Toner") < prompt.index("Serum")
    assert "plan exactly 3 slide(s), one per product" in prompt
    # The deep-dive single-product instruction language must NOT leak into a
    # discovery prompt — these are genuinely different planning modes.
    assert "Plan up to" not in prompt
    assert "Plan exactly 3 slide(s), no more and no fewer" not in prompt

    creative_output = (
        session.query(CampaignOutput)
        .filter(CampaignOutput.campaign_id == campaign.id, CampaignOutput.kind == "creative")
        .one()
    )
    creative_data = json.loads(Path(creative_output.file_path).read_text())
    primary_variant = creative_data["languages"][creative_data["primary_language"]]
    assert len(primary_variant["carousel_plan"]["slides"]) == 3
    session.close()


async def test_visuals_stage_renders_one_slide_per_discovery_product_not_round_robin(temp_db, tmp_path, shared_renderer):
    """The core discovery-mode guarantee: each slide shows a DIFFERENT hand-picked
    product's own photo, in pick order — never round-robin/reuse like deep-dive
    mode, even though both modes share the same rendering loop.
    """
    session = temp_db.SessionLocal()
    brand, category, _base_assets = _make_brand_and_assets(session, tmp_path, num_assets=0)
    products = _make_discovery_products(session, brand, category, tmp_path, ["Cleanser", "Toner", "Serum"])
    campaign = _make_campaign(session, brand, category)
    _set_discovery_products(session, campaign, products)

    three_slide_plan = CarouselPlan(
        slides=[
            SlidePlan(
                slide_number=i, purpose="hero", eyebrow="", headline=f"Headline {i}",
                body=f"Body {i}", cta="Shop now", visual_brief="Product shot",
            )
            for i in range(1, 4)
        ],
        narrative_summary="One slide per featured product.",
    )
    provider = FakeAutopilotProvider(carousel_plan=three_slide_plan)
    config = _config(tmp_path)

    await run_strategy_stage(
        session, campaign_id=campaign.id, ai_provider=provider, research_provider=provider, config=config,
    )
    await run_copy_stage(session, campaign_id=campaign.id, ai_provider=provider, config=config)
    result = await run_visuals_stage(session, campaign_id=campaign.id, renderer=shared_renderer, config=config)

    assert result.status == "REVIEW"
    slides = sorted(result.slides, key=lambda s: s.slide_number)
    assert [s.headline for s in slides] == ["Headline 1", "Headline 2", "Headline 3"]
    # Each slide's source photo is that same-index product's OWN asset, in pick
    # order — a real cross-product distinctness check, not just "some asset".
    product_asset_ids = {
        p.id: session.query(Asset).filter(Asset.product_id == p.id).one().id for p in products
    }
    assert [s.source_asset_id for s in slides] == [product_asset_ids[p.id] for p in products]
    session.close()


async def test_visuals_stage_discovery_mode_skips_a_picked_product_with_no_active_photo(
    temp_db, tmp_path, shared_renderer
):
    """A hand-picked product that currently has no active photo simply loses its
    slide (best-effort, matching the rest of this loop's "a moved/deleted source
    file shouldn't fail the whole run" philosophy) rather than failing the run —
    the remaining picked products still render correctly, still in order.
    """
    session = temp_db.SessionLocal()
    brand, category, _base_assets = _make_brand_and_assets(session, tmp_path, num_assets=0)
    products = _make_discovery_products(session, brand, category, tmp_path, ["Cleanser", "Toner", "Serum"])
    # Deactivate Toner's only photo — Toner was picked but now has nothing to render.
    toner_asset = session.query(Asset).filter(Asset.product_id == products[1].id).one()
    toner_asset.is_active = False
    session.commit()

    campaign = _make_campaign(session, brand, category)
    _set_discovery_products(session, campaign, products)

    three_slide_plan = CarouselPlan(
        slides=[
            SlidePlan(
                slide_number=i, purpose="hero", eyebrow="", headline=f"Headline {i}",
                body=f"Body {i}", cta="Shop now", visual_brief="Product shot",
            )
            for i in range(1, 4)
        ],
        narrative_summary="One slide per featured product.",
    )
    provider = FakeAutopilotProvider(carousel_plan=three_slide_plan)
    config = _config(tmp_path)

    await run_strategy_stage(
        session, campaign_id=campaign.id, ai_provider=provider, research_provider=provider, config=config,
    )
    await run_copy_stage(session, campaign_id=campaign.id, ai_provider=provider, config=config)
    result = await run_visuals_stage(session, campaign_id=campaign.id, renderer=shared_renderer, config=config)

    slides = sorted(result.slides, key=lambda s: s.slide_number)
    assert [s.headline for s in slides] == ["Headline 1", "Headline 3"]  # Toner's slide is missing
    cleanser_asset_id = session.query(Asset).filter(Asset.product_id == products[0].id).one().id
    serum_asset_id = session.query(Asset).filter(Asset.product_id == products[2].id).one().id
    assert [s.source_asset_id for s in slides] == [cleanser_asset_id, serum_asset_id]
    session.close()


async def test_visuals_stage_discovery_mode_fails_when_no_picked_product_has_a_photo(
    temp_db, tmp_path, shared_renderer
):
    session = temp_db.SessionLocal()
    # One generic, unrelated-to-any-product photo in the category so the earlier
    # Strategy-stage candidate-photo check (category-wide, unaware of discovery
    # picks) still passes — this test is specifically about the Visuals-stage
    # discovery guard, which is narrower: none of the PICKED products have a photo,
    # even though the category itself isn't empty.
    brand, category, _base_assets = _make_brand_and_assets(session, tmp_path, num_assets=1)
    products = _make_discovery_products(session, brand, category, tmp_path, ["Cleanser"])
    session.query(Asset).filter(Asset.product_id == products[0].id).one().is_active = False
    session.commit()

    campaign = _make_campaign(session, brand, category)
    _set_discovery_products(session, campaign, products)

    provider = FakeAutopilotProvider()
    config = _config(tmp_path)
    await run_strategy_stage(
        session, campaign_id=campaign.id, ai_provider=provider, research_provider=provider, config=config,
    )
    await run_copy_stage(session, campaign_id=campaign.id, ai_provider=provider, config=config)

    with pytest.raises(ValueError, match="discovery"):
        await run_visuals_stage(session, campaign_id=campaign.id, renderer=shared_renderer, config=config)

    session.refresh(campaign)
    assert campaign.status == "FAILED"
    session.close()


async def test_copy_stage_honors_target_slide_count_in_prompt(temp_db, tmp_path):
    """When the campaign has an explicit `target_slide_count`, the carousel-planning
    prompt must ask for exactly that many slides rather than the default "up to
    config.max_slides, use your judgment" instruction.
    """
    session = temp_db.SessionLocal()
    brand, category, assets = _make_brand_and_assets(session, tmp_path)
    campaign = _make_campaign(session, brand, category)
    campaign.target_slide_count = 3
    session.commit()
    provider = FakeAutopilotProvider()
    config = _config(tmp_path)

    await run_strategy_stage(
        session, campaign_id=campaign.id, ai_provider=provider, research_provider=provider, config=config,
    )
    await run_copy_stage(session, campaign_id=campaign.id, ai_provider=provider, config=config)

    carousel_prompts = [
        prompt for schema, prompt in zip(provider.schema_calls, provider.user_prompts) if schema is CarouselPlan
    ]
    assert len(carousel_prompts) == 1
    assert "Plan exactly 3 slide(s)" in carousel_prompts[0]
    assert "up to" not in carousel_prompts[0]
    session.close()


async def test_copy_stage_defaults_to_up_to_max_slides_prompt_when_unset(temp_db, tmp_path):
    """The unset (None) default must keep the original "up to config.max_slides,
    use your judgment" instruction — round 16 must not change behavior for
    campaigns that don't opt into a fixed carousel length.
    """
    session = temp_db.SessionLocal()
    brand, category, assets = _make_brand_and_assets(session, tmp_path)
    campaign = _make_campaign(session, brand, category)
    assert campaign.target_slide_count is None
    provider = FakeAutopilotProvider()
    config = _config(tmp_path)

    await run_strategy_stage(
        session, campaign_id=campaign.id, ai_provider=provider, research_provider=provider, config=config,
    )
    await run_copy_stage(session, campaign_id=campaign.id, ai_provider=provider, config=config)

    carousel_prompts = [
        prompt for schema, prompt in zip(provider.schema_calls, provider.user_prompts) if schema is CarouselPlan
    ]
    assert len(carousel_prompts) == 1
    assert f"Plan up to {config.max_slides} slide(s)" in carousel_prompts[0]
    assert "Plan exactly" not in carousel_prompts[0]
    session.close()


async def test_copy_stage_slices_planned_slides_to_target_slide_count(temp_db, tmp_path, shared_renderer):
    """`target_slide_count` must actually constrain how many of the model's planned
    slides get used, even when the model's (fake, canned) response returns more
    slides than requested — the effective cap is `target_slide_count`, not
    `config.max_slides`, whenever it's set. `run_copy_stage` itself doesn't create
    `CampaignSlide` rows (that's the Visuals stage's job), so this runs Visuals too
    and checks the count that actually got rendered.
    """
    session = temp_db.SessionLocal()
    brand, category, assets = _make_brand_and_assets(session, tmp_path)
    campaign = _make_campaign(session, brand, category)
    campaign.target_slide_count = 1
    session.commit()

    four_slide_plan = CarouselPlan(
        slides=[
            SlidePlan(
                slide_number=i, purpose="hero", eyebrow="", headline=f"Headline {i}",
                body=f"Body {i}", cta="Shop now", visual_brief="Product shot",
            )
            for i in range(1, 5)
        ],
        narrative_summary="A four-slide plan the model returned despite being asked for one.",
    )
    provider = FakeAutopilotProvider(carousel_plan=four_slide_plan)
    config = _config(tmp_path)

    await run_strategy_stage(
        session, campaign_id=campaign.id, ai_provider=provider, research_provider=provider, config=config,
    )
    await run_copy_stage(session, campaign_id=campaign.id, ai_provider=provider, config=config)
    result = await run_visuals_stage(session, campaign_id=campaign.id, renderer=shared_renderer, config=config)

    assert len(result.slides) == 1
    assert result.slides[0].headline == "Headline 1"
    session.close()


# --------------------------------------------------------------------------------
# Build 1 ("Verified Product Facts + Campaign Foundation") — orchestrator-level
# grounding tests. API-layer tests (VerifiedProductFacts endpoints, campaign
# languages/target_platforms fields, the platform-capabilities endpoint) live in
# tests/test_build1_product_facts_and_platform_api.py instead.
# --------------------------------------------------------------------------------


def _copy_calls(provider: FakeAutopilotProvider) -> list[tuple[str, str]]:
    """(system, user) pairs for every CampaignCopy call the provider received, in
    order — the common lookup every grounding test below needs.
    """
    return [
        (system, user)
        for schema, system, user in zip(provider.schema_calls, provider.system_prompts, provider.user_prompts)
        if schema is CampaignCopy
    ]


async def test_copy_stage_generates_independent_copy_per_selected_language(temp_db, tmp_path):
    """Test 6: both pt-BR and en can be selected together, and each gets its own
    independent CampaignCopy + CarouselPlan call (not one call reused/translated)
    — asserted on call count and on each call's own `Language: <code>` marker,
    per FakeAutopilotProvider's documented "same canned object per schema"
    limitation (see its docstring) — this test checks *how many times* and *with
    what prompt* the provider was called, not what it returned.
    """
    session = temp_db.SessionLocal()
    brand, category, assets = _make_brand_and_assets(session, tmp_path)
    campaign = _make_campaign(session, brand, category)
    campaign.languages = ["pt-BR", "en"]
    session.commit()
    provider = FakeAutopilotProvider()
    config = _config(tmp_path)

    await run_strategy_stage(
        session, campaign_id=campaign.id, ai_provider=provider, research_provider=provider, config=config,
    )
    await run_copy_stage(session, campaign_id=campaign.id, ai_provider=provider, config=config)

    copy_calls = _copy_calls(provider)
    assert len(copy_calls) == 2
    carousel_calls = [s for s in provider.schema_calls if s is CarouselPlan]
    assert len(carousel_calls) == 2
    assert any("Language: pt-BR" in user for _, user in copy_calls)
    assert any("Language: en" in user for _, user in copy_calls)

    copy_data = json.loads(
        Path(
            session.query(CampaignOutput)
            .filter(CampaignOutput.campaign_id == campaign.id, CampaignOutput.kind == "copy")
            .one()
            .file_path
        ).read_text()
    )
    assert set(copy_data["languages"].keys()) == {"pt-BR", "en"}
    assert copy_data["primary_language"] == "pt-BR"
    session.close()


async def test_copy_stage_grounds_copy_in_brand_voice(temp_db, tmp_path):
    """Test 11: the brand's own `voice` field reaches the CampaignCopy prompt."""
    session = temp_db.SessionLocal()
    brand, category, assets = _make_brand_and_assets(session, tmp_path)
    brand.voice = "Warm, confident, like a trusted older sister explaining her routine."
    session.commit()
    campaign = _make_campaign(session, brand, category)
    provider = FakeAutopilotProvider()
    config = _config(tmp_path)

    await run_strategy_stage(
        session, campaign_id=campaign.id, ai_provider=provider, research_provider=provider, config=config,
    )
    await run_copy_stage(session, campaign_id=campaign.id, ai_provider=provider, config=config)

    copy_calls = _copy_calls(provider)
    assert len(copy_calls) == 1
    assert "trusted older sister" in copy_calls[0][1]
    session.close()


async def test_copy_stage_grounds_copy_in_verified_product_facts(temp_db, tmp_path, monkeypatch):
    """Test 12: a single-product campaign's real `VerifiedProductFacts` (never
    invented) reach the CampaignCopy prompt, via `services/product_facts.py`.
    """
    from app.services import orchestrator as _orch_test_module

    async def _vpffacts_test_semantic_gate(
        db,
        *,
        campaign,
        brand,
        product,
        phase,
        structures,
        **_ignored,
    ):
        # This legacy test verifies VerifiedProductFacts propagation
        # into CampaignCopy. Semantic extraction has dedicated Build 6R
        # tests, so retain the deterministic grounding gate here without
        # requiring FakeAutopilotProvider to implement semantic auditing.
        return _orch_test_module._enforce_previsual_claim_grounding_gate(
            db,
            campaign=campaign,
            brand=brand,
            product=product,
            phase=phase,
            structures=structures,
        )

    monkeypatch.setattr(
        _orch_test_module,
        "_enforce_previsual_semantic_claim_grounding_gate",
        _vpffacts_test_semantic_gate,
    )

    session = temp_db.SessionLocal()
    brand, category, assets = _make_brand_and_assets(session, tmp_path)
    product = Product(brand_id=brand.id, category_id=category.id, name="Rice Serum", slug="rice-serum")
    session.add(product)
    session.commit()
    session.add(VerifiedProductFact(
        product_id=product.id,
        verified_ingredients=["Rice bran extract", "Hyaluronic acid"],
        verified_size="30ml",
        provenance="owner_provided",
    ))
    img_path = tmp_path / "rice-serum.jpg"
    Image.new("RGB", (800, 800), (200, 200, 150)).save(img_path)
    session.add(Asset(
        brand_id=brand.id, category_id=category.id, product_id=product.id, absolute_path=str(img_path),
        relative_path="skincare/rice-serum/rice-serum.jpg", filename="rice-serum.jpg", extension=".jpg",
        sha256="sha-rice-serum", width=800, height=800,
    ))
    session.commit()
    campaign = Campaign(
        display_id="HANNA-SKIN-VPF001", brand_id=brand.id, category_id=category.id, product_id=product.id,
        objective="awareness", status="IDEA",
    )
    session.add(campaign)
    session.commit()

    provider = FakeAutopilotProvider()
    config = _config(tmp_path)
    await run_strategy_stage(
        session, campaign_id=campaign.id, ai_provider=provider, research_provider=provider, config=config,
    )
    await run_copy_stage(session, campaign_id=campaign.id, ai_provider=provider, config=config)

    copy_calls = _copy_calls(provider)
    assert "Rice bran extract" in copy_calls[0][1]
    assert "30ml" in copy_calls[0][1]
    session.close()


async def test_copy_stage_grounds_copy_in_research_insights(temp_db, tmp_path):
    """Test 13: this campaign's own persisted research (from the Strategy stage)
    reaches the CampaignCopy prompt — previously generated and then never read
    again after Strategy.
    """
    session = temp_db.SessionLocal()
    brand, category, assets = _make_brand_and_assets(session, tmp_path)
    campaign = _make_campaign(session, brand, category)
    provider = FakeAutopilotProvider()
    config = _config(tmp_path)

    await run_strategy_stage(
        session, campaign_id=campaign.id, ai_provider=provider, research_provider=provider, config=config,
    )
    await run_copy_stage(session, campaign_id=campaign.id, ai_provider=provider, config=config)

    copy_calls = _copy_calls(provider)
    assert "Multi-step skincare routines are trending on Brazilian social media." in copy_calls[0][1]
    session.close()


async def test_copy_stage_grounds_copy_in_target_platform(temp_db, tmp_path):
    """Test 14: `campaign.target_platforms` reaches the CampaignCopy prompt as
    real platform-specific guidance, not a generic/Instagram-assumed note.
    """
    session = temp_db.SessionLocal()
    brand, category, assets = _make_brand_and_assets(session, tmp_path)
    campaign = _make_campaign(session, brand, category)
    campaign.target_platforms = ["tiktok"]
    session.commit()
    provider = FakeAutopilotProvider()
    config = _config(tmp_path)

    await run_strategy_stage(
        session, campaign_id=campaign.id, ai_provider=provider, research_provider=provider, config=config,
    )
    await run_copy_stage(session, campaign_id=campaign.id, ai_provider=provider, config=config)

    copy_calls = _copy_calls(provider)
    assert "TikTok" in copy_calls[0][1]
    assert "Spoken-language" in copy_calls[0][1]
    assert "Instagram" not in copy_calls[0][1]
    session.close()


async def test_copy_stage_grounds_copy_in_selected_language(temp_db, tmp_path):
    """Test 15: `campaign.languages` reaches the CampaignCopy prompt as an
    explicit `Language: <code>` marker.
    """
    session = temp_db.SessionLocal()
    brand, category, assets = _make_brand_and_assets(session, tmp_path)
    campaign = _make_campaign(session, brand, category)
    campaign.languages = ["en"]
    session.commit()
    provider = FakeAutopilotProvider()
    config = _config(tmp_path)

    await run_strategy_stage(
        session, campaign_id=campaign.id, ai_provider=provider, research_provider=provider, config=config,
    )
    await run_copy_stage(session, campaign_id=campaign.id, ai_provider=provider, config=config)

    copy_calls = _copy_calls(provider)
    assert "Language: en" in copy_calls[0][1]
    session.close()


async def test_copy_stage_applies_pt_br_native_language_rules(temp_db, tmp_path):
    """Test 16: a pt-BR campaign's CampaignCopy call carries the concrete
    Brazilian-Portuguese-native instructions (Part F), not a generic "write
    naturally" note.
    """
    session = temp_db.SessionLocal()
    brand, category, assets = _make_brand_and_assets(session, tmp_path)
    campaign = _make_campaign(session, brand, category)
    campaign.languages = ["pt-BR"]
    session.commit()
    provider = FakeAutopilotProvider()
    config = _config(tmp_path)

    await run_strategy_stage(
        session, campaign_id=campaign.id, ai_provider=provider, research_provider=provider, config=config,
    )
    await run_copy_stage(session, campaign_id=campaign.id, ai_provider=provider, config=config)

    copy_calls = _copy_calls(provider)
    system_text = copy_calls[0][0]
    assert "Avoid Portugal-specific vocabulary" in system_text
    assert "Descubra o poder de" in system_text  # named generic-AI-phrase example to avoid
    session.close()


async def test_copy_stage_applies_english_native_language_rules(temp_db, tmp_path):
    """Test 17: an en campaign's CampaignCopy call carries the concrete natural-
    English instructions (Part F), distinct from the pt-BR rule set.
    """
    session = temp_db.SessionLocal()
    brand, category, assets = _make_brand_and_assets(session, tmp_path)
    campaign = _make_campaign(session, brand, category)
    campaign.languages = ["en"]
    session.commit()
    provider = FakeAutopilotProvider()
    config = _config(tmp_path)

    await run_strategy_stage(
        session, campaign_id=campaign.id, ai_provider=provider, research_provider=provider, config=config,
    )
    await run_copy_stage(session, campaign_id=campaign.id, ai_provider=provider, config=config)

    copy_calls = _copy_calls(provider)
    system_text = copy_calls[0][0]
    assert "sentence structures that read like a Portuguese" in system_text
    assert "Discover the power of" in system_text  # named generic-AI-phrase example to avoid
    assert "Avoid Portugal-specific vocabulary" not in system_text
    session.close()


def test_brand_style_resolver_maps_named_and_positional_colors(temp_db, tmp_path):
    """Test 18: `resolve_brand_style` maps a brand's free-form `colors` dict by
    recognized key name, falls back to positional order when no key matches,
    and falls back to the app's own defaults when no colors are set at all —
    plus folds in `disclaimers` as one joined string.
    """
    session = temp_db.SessionLocal()

    named = Brand(
        name="Hanna Named", slug="hanna-named",
        colors={"accent": "#111111", "primary": "#222222", "secondary": "#333333"},
        disclaimers=["Results may vary.", "Consult a dermatologist before use."],
    )
    session.add(named)
    session.commit()
    style = resolve_brand_style(session, named)
    assert style.accent_color == "#111111"
    assert style.primary_color == "#222222"
    assert style.secondary_color == "#333333"
    assert style.disclaimer_text == "Results may vary. · Consult a dermatologist before use."
    assert style.background_preference == "brand_colors"

    positional = Brand(name="Hanna Positional", slug="hanna-positional", colors={"swatch_1": "#444444", "swatch_2": "#555555"})
    session.add(positional)
    session.commit()
    style2 = resolve_brand_style(session, positional)
    assert style2.accent_color == "#444444"  # no recognized key -> first color by position
    assert style2.secondary_color == "#555555"

    empty = Brand(name="Hanna Empty", slug="hanna-empty")
    session.add(empty)
    session.commit()
    style3 = resolve_brand_style(session, empty)
    from app.services.creative.brand_style import DEFAULT_ACCENT_COLOR, DEFAULT_TEXT_COLOR
    assert style3.accent_color == DEFAULT_ACCENT_COLOR
    assert style3.text_color == DEFAULT_TEXT_COLOR
    assert style3.background_preference == "default"
    assert style3.disclaimer_text == ""
    session.close()


def test_deterministic_disclaimer_renders_as_real_text():
    """Test 19: deterministic typography (Part H) — a disclaimer string is
    rendered as real HTML text by both templates, never left out or baked into
    an image, and skipped entirely when empty (existing no-disclaimer slides are
    byte-for-byte unaffected).
    """
    ctx_with = TemplateContext(
        width=1080, height=1080, composited_image_data_uri="data:image/png;base64,AA==",
        headline="Glow starts here", disclaimer="Results may vary. Individual results differ.",
    )
    feature_html = get_template("feature_showcase").build_html(ctx_with)
    assert "Results may vary. Individual results differ." in feature_html
    assert "disclaimer" in feature_html

    hero_html = get_template("premium_product_hero").build_html(ctx_with)
    assert "Results may vary. Individual results differ." in hero_html

    ctx_without = TemplateContext(
        width=1080, height=1080, composited_image_data_uri="data:image/png;base64,AA==", headline="Glow starts here",
    )
    feature_html_without = get_template("feature_showcase").build_html(ctx_without)
    assert "Results may vary" not in feature_html_without


async def test_prompt_versions_seeded_and_usage_recorded_per_language(temp_db, tmp_path):
    """Test 20: Part I's prompt-versioning infrastructure is real — versions are
    seeded into `PromptVersion`, and every actual CampaignCopy/CarouselPlan call
    a real campaign run makes is logged (purpose, version, language, platform)
    via `record_prompt_usage`. Build 2 extends the same registry/logging to its
    own new `run_copy_stage` Creative Director call — `master_campaign_concept`,
    generated once per campaign and logged against the campaign's primary
    language even though the concept itself is language-agnostic (see
    `MasterCampaignConcept`'s own docstring). The other three Build 2 prompt
    purposes (`platform_adaptation`/`creative_direction`/`video_concept`, all
    logged from `_render_additional_platform_variants` in `run_visuals_stage`)
    are covered separately by `tests/test_build2_platform_variants.py`, not
    duplicated here.
    """
    session = temp_db.SessionLocal()
    ensure_prompt_versions_seeded(session)
    versions = {row.purpose: row for row in session.query(PromptVersion).all()}
    assert versions["campaign_copy"].version == PROMPT_VERSIONS["campaign_copy"].version
    assert versions["carousel_plan"].version == PROMPT_VERSIONS["carousel_plan"].version
    assert versions["campaign_copy"].variables  # traceability: real variable names, not empty

    brand, category, assets = _make_brand_and_assets(session, tmp_path)
    campaign = _make_campaign(session, brand, category)
    campaign.languages = ["pt-BR", "en"]
    campaign.target_platforms = ["facebook"]
    session.commit()
    provider = FakeAutopilotProvider()
    config = _config(tmp_path)

    await run_strategy_stage(
        session, campaign_id=campaign.id, ai_provider=provider, research_provider=provider, config=config,
    )
    await run_copy_stage(session, campaign_id=campaign.id, ai_provider=provider, config=config)

    events = (
        session.query(AuditEvent)
        .filter(AuditEvent.entity_type == "campaign_prompt_usage", AuditEvent.entity_id == campaign.id)
        .all()
    )
    seen = {(e.action, e.detail["language"], e.detail["platform"]) for e in events}
    assert seen == {
        ("campaign_copy", "pt-BR", "facebook"), ("campaign_copy", "en", "facebook"),
        ("carousel_plan", "pt-BR", "facebook"), ("carousel_plan", "en", "facebook"),
        ("master_campaign_concept", "pt-BR", "facebook"),
    }
    assert all(e.detail["version"] == PROMPT_VERSIONS[e.action].version for e in events)
    session.close()


async def test_get_campaign_copy_returns_requested_language_variant(temp_db, tmp_path):
    """`get_campaign_copy`'s new `language` parameter (used by, among others, the
    publish endpoint) resolves to the right per-language variant, defaulting to
    the campaign's primary language when unspecified.
    """
    session = temp_db.SessionLocal()
    brand, category, assets = _make_brand_and_assets(session, tmp_path)
    campaign = _make_campaign(session, brand, category)
    campaign.languages = ["pt-BR", "en"]
    session.commit()
    provider = FakeAutopilotProvider()
    config = _config(tmp_path)

    await run_strategy_stage(
        session, campaign_id=campaign.id, ai_provider=provider, research_provider=provider, config=config,
    )
    await run_copy_stage(session, campaign_id=campaign.id, ai_provider=provider, config=config)

    default_copy = get_campaign_copy(session, campaign.id)
    pt_copy = get_campaign_copy(session, campaign.id, language="pt-BR")
    en_copy = get_campaign_copy(session, campaign.id, language="en")
    assert default_copy is not None and pt_copy is not None and en_copy is not None
    assert default_copy.hook == pt_copy.hook  # pt-BR is the primary (first-selected) language
    assert en_copy.hook == pt_copy.hook  # FakeAutopilotProvider returns the same canned object either way — a real
    # provider would differ; this asserts the *plumbing* reads the right slot, not that content differs (see
    # test_copy_stage_generates_independent_copy_per_selected_language for the "actually called twice" assertion).
    session.close()
