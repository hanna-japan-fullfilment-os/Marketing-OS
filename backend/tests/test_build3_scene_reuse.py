"""Build 3 (MARKETING OS — PLATFORM + LANGUAGE AWARE MULTIMODAL QA) carry-forward
requirement 1: verifying and correcting Build 2's language-variant scene reuse.

Build 2's own cost-discipline design (`_render_additional_platform_variants`'s
`background_cache`) already shared an AI-generated background across a
platform's *non-primary* languages, but never with the *primary* language —
which `run_visuals_stage`'s own separate legacy loop renders. A non-primary
language of the PRIMARY platform (e.g. Instagram+en when Instagram+pt-BR is
primary) always regenerated its background from scratch, even when nothing
about the scene should differ. `services/orchestrator.py::_scene_signature`
plus the primary-cache-seeding block in `_render_additional_platform_variants`
close that gap while never reusing a scene a CreativeDirection genuinely says
should differ (requirement 4) and never crossing platform boundaries
(requirement 5).

Reuses `test_build2_platform_variants.py`'s fakes/helpers rather than
redefining them, since this module is testing a correction to exactly that
build's own machinery.
"""
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


import io
import uuid

import pytest
from PIL import Image

from app.models import Asset, Brand, Campaign, Category
from app.schemas.ai import (
    CampaignCopy, CampaignStrategy, CampaignStrategyCandidates, CarouselPlan, CreativeBrief, ProductFidelityCheck,
    ResearchInsightItem, ResearchResult, SlidePlan,
)
from app.schemas.creative_director import CreativeDirection, MasterCampaignConcept, PlatformAdaptation, VideoConcept
from app.services.creative.renderer import PlaywrightRenderer
from app.services.orchestrator import (
    AutopilotConfig, get_platform_campaign_variants, run_autopilot, run_copy_stage, run_strategy_stage,
    run_visuals_stage,
)


@pytest.fixture()
async def variant_renderer():
    renderer = PlaywrightRenderer()
    yield renderer
    await renderer.close()


def _make_brand_category_assets(session, tmp_path, *, num_assets=3):
    """Duplicated from `test_build2_platform_variants.py` rather than
    imported — this codebase's own stated convention (see that module's
    docstring) is to keep each test file's fakes/helpers local, since
    `tests/` isn't a package and cross-file imports don't resolve cleanly.
    """
    from app.services.seed import seed_strategy_library
    seed_strategy_library(session)

    brand = Brand(name="Hanna", slug=f"hanna-{uuid.uuid4().hex[:8]}", colors={"primary": "#f2ede3"}, campaign_rules={"verified_operational_strategy_keys": list(_LEGACY_VERIFIED_OPERATIONAL_STRATEGY_KEYS)})
    session.add(brand)
    session.commit()
    category = Category(brand_id=brand.id, name="Skincare", slug="skincare")
    session.add(category)
    session.commit()
    for i in range(num_assets):
        img_path = tmp_path / f"asset-{i}.jpg"
        Image.new("RGB", (800, 800), (10 + i * 20, 50, 200)).save(img_path)
        session.add(Asset(
            brand_id=brand.id, category_id=category.id, absolute_path=str(img_path),
            relative_path=f"skincare/asset-{i}.jpg", filename=f"asset-{i}.jpg", extension=".jpg",
            sha256=f"sha-{i}", width=800, height=800,
        ))
    session.commit()
    return brand, category


class FakeMultiVariantProvider:
    """AIProvider + ResearchProvider stand-in covering every schema the full
    Strategy -> Copy -> Visuals -> multi-variant pipeline can request.
    Duplicated from `test_build2_platform_variants.py` — see that class's own
    docstring; kept local per this codebase's test-file convention.
    """

    def __init__(self):
        self.research_calls = 0
        self.creative_direction_calls: list[dict] = []

    async def generate_structured(self, *, system, user, schema, model):
        if schema is CampaignStrategyCandidates:
            return CampaignStrategyCandidates(
                candidates=[
                    CampaignStrategy(
                        objective="awareness", audience="Young adults in Brazil", funnel_stage="tofu",
                        insight="Routines are trending", angle="Build your routine",
                        key_message="Everything for a 5-step routine", reason_this_should_work="Rides the trend.",
                    )
                ]
            )
        if schema is CreativeBrief:
            return CreativeBrief(
                design_concept="Clean hero shot", visual_prompt="Product on a gradient",
                template_suggestion="feature_showcase", tone_notes="Warm",
            )
        if schema is CampaignCopy:
            return CampaignCopy(
                hook="Your skin deserves this", headline="Straight from Japan",
                supporting_copy="Sourced firsthand.", cta="Shop now", caption="Straight from Japan.",
                hashtags=["#skincare"], alt_text="Product bottle on a gradient background",
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
                concept_name="Everyday Ritual", campaign_promise="A routine that fits your day",
                key_message="Everything for a 5-step routine", emotional_goal="Confidence",
                audience="Young adults in Brazil", objective="awareness",
                visual_identity="Clean hero shot on a warm gradient",
                story_arc="Open on product, reveal routine, close on result", cta_intent="Try the routine",
            )
        if schema is PlatformAdaptation:
            return PlatformAdaptation(
                platform="instagram", adaptation_strategy="visual storytelling carousel",
                narrative_shape="Open, reveal, close", tone_adjustment="warm", content_type="carousel",
            )
        if schema is CreativeDirection:
            self.creative_direction_calls.append({"user": user})
            return CreativeDirection(
                concept_name="Everyday Ritual", background_concept="Soft warm gradient studio backdrop",
                scene_generation_prompt="Soft warm gradient studio backdrop, no text, no logos, no products.",
            )
        if schema is VideoConcept:
            return VideoConcept(
                hook="Your 5-step routine starts here", script="Open, walk through, close.",
                shot_list=["Hero shot", "Routine steps", "Result"], caption="Everything you need.",
            )
        raise AssertionError(f"Unexpected schema requested: {schema}")

    async def vision_describe(self, *, image_path, prompt, model):
        return ""

    async def research(self, query, *, model):
        self.research_calls += 1
        return ResearchResult(
            insights=[
                ResearchInsightItem(
                    statement="Multi-step skincare routines are trending in Brazil.", confidence=0.8,
                    freshness="this_quarter", category="trend",
                    recommended_implication="Emphasize routine-building.",
                    source_urls=["https://example.com/trend-report"],
                )
            ]
        )

    async def detect_product_zone(self, *, image_path, model):
        raise NotImplementedError

    async def check_product_fidelity(self, *, source_image_path, generated_image_path, model):
        return ProductFidelityCheck(overall_verdict="PASS", reasoning="Matches.")


class _FakeImageProvider:
    """Counts real generation calls — every existing Build 2 background-sharing
    test uses this exact shape; duplicated here rather than imported since
    `test_build2_platform_variants.py` defines it locally inside its own test
    function, not at module scope.
    """

    def __init__(self):
        self.calls = 0

    async def generate(self, *, prompt, size, model, reference_images=None, quality="high"):
        self.calls += 1
        buf = io.BytesIO()
        Image.new("RGB", (64, 64), (200, 100, 50)).save(buf, format="PNG")
        return buf.getvalue()

    async def edit(self, *, base_image, prompt, model, mask=None, quality="high"):
        raise NotImplementedError


class _LanguageDivergentDirectionProvider(FakeMultiVariantProvider):
    """Same canned responses as `FakeMultiVariantProvider` for every schema
    EXCEPT `CreativeDirection`, where it reads the real prompt text (same
    technique Build 2's own EN/PT-BR-typography-differs test uses) and
    returns a GENUINELY different scene per language — the exact situation
    requirement 4 says must never be force-shared.
    """

    async def generate_structured(self, *, system, user, schema, model):
        if schema is CreativeDirection:
            self.creative_direction_calls.append({"user": user})
            if "Language: en." in user:
                return CreativeDirection(
                    concept_name="Everyday Ritual", background_concept="Bright beach morning light",
                    scene_generation_prompt="Bright beach morning light, airy, no text, no logos, no products.",
                )
            return CreativeDirection(
                concept_name="Everyday Ritual", background_concept="Soft warm gradient studio backdrop",
                scene_generation_prompt="Soft warm gradient studio backdrop, no text, no logos, no products.",
            )
        return await super().generate_structured(system=system, user=user, schema=schema, model=model)


def _config(tmp_path, **overrides):
    return AutopilotConfig(
        campaign_model="gpt-5.1", research_model="gpt-5.1", trend_ttl_hours=24, category_ttl_hours=168,
        too_similar_threshold=75, acceptable_threshold=45, output_root=tmp_path / "output",
        use_ai_background=True, **overrides,
    )


async def test_primary_and_non_primary_language_of_same_platform_share_a_scene(
    temp_db, tmp_path, variant_renderer,
):
    """Requirements 1 + 2 + 3: with no AI provider consulted for creative
    direction (this app's documented no-key Visuals path — every language's
    `CreativeDirection` is `_deterministic_creative_direction`'s own
    fallback, identical by construction regardless of language), the
    non-primary "en" language of the PRIMARY platform now reuses the exact
    background the primary "pt-BR" combination already generated (1), each
    language still gets its own independently rendered file (2), and each
    variant still carries its own distinct language/copy tagging (3) despite
    sharing the underlying scene.
    """
    session = temp_db.SessionLocal()
    brand, category = _make_brand_category_assets(session, tmp_path)
    campaign = Campaign(
        display_id=f"HANNA-SKIN-{uuid.uuid4().hex[:8]}", brand_id=brand.id, category_id=category.id,
        objective="awareness", status="IDEA", languages=["pt-BR", "en"], target_platforms=["instagram"],
    )
    session.add(campaign)
    session.commit()
    campaign_id = campaign.id

    provider = FakeMultiVariantProvider()
    image_provider = _FakeImageProvider()
    config = _config(tmp_path)
    await run_strategy_stage(
        session, campaign_id=campaign_id, ai_provider=provider, research_provider=provider, config=config,
    )
    await run_copy_stage(session, campaign_id=campaign_id, ai_provider=provider, config=config)
    # No ai_provider passed here — the documented no-key Visuals-only path.
    await run_visuals_stage(
        session, campaign_id=campaign_id, renderer=variant_renderer, config=config, image_provider=image_provider,
    )

    variants = get_platform_campaign_variants(session, campaign_id)
    pt_variant = next(v for v in variants if v.target_platform == "instagram" and v.language == "pt-BR")
    en_variant = next(v for v in variants if v.target_platform == "instagram" and v.language == "en")
    assert pt_variant.status == "RENDERED" and en_variant.status == "RENDERED"

    # Requirement 1: reused, not regenerated.
    assert en_variant.shared_scene_source != ""
    assert all(part.startswith("instagram:slide-") for part in en_variant.shared_scene_source.split(","))
    assert image_provider.calls == len(pt_variant.slide_asset_paths)  # never a second pass for "en"

    # Requirement 2: still two independently rendered files, not one shared asset.
    assert set(en_variant.slide_asset_paths).isdisjoint(set(pt_variant.slide_asset_paths))
    for p in en_variant.slide_asset_paths:
        assert p  # a real path was produced, not an empty/placeholder entry

    # Requirement 3: language-specific tagging stays separate even though the
    # scene pixels are shared.
    assert en_variant.copy_language == "en" and pt_variant.copy_language == "pt-BR"
    assert en_variant.creative_direction.get("language") == "en"
    session.close()


async def test_creative_direction_requiring_different_imagery_is_not_shared(
    temp_db, tmp_path, variant_renderer,
):
    """Requirement 4: two non-primary languages of the SAME non-primary
    platform, whose AI-authored `CreativeDirection`s genuinely disagree on
    the scene, must each get their own background — never force-shared just
    because they're the same platform and slide index. Isolated from the
    primary-combo nuance by using Pinterest, which is never the primary
    platform here (Instagram is).
    """
    session = temp_db.SessionLocal()
    brand, category = _make_brand_category_assets(session, tmp_path)
    campaign = Campaign(
        display_id=f"HANNA-SKIN-{uuid.uuid4().hex[:8]}", brand_id=brand.id, category_id=category.id,
        objective="awareness", status="IDEA", languages=["pt-BR", "en"],
        target_platforms=["instagram", "pinterest"],
    )
    session.add(campaign)
    session.commit()
    campaign_id = campaign.id

    provider = _LanguageDivergentDirectionProvider()
    image_provider = _FakeImageProvider()
    config = _config(tmp_path)
    await run_autopilot(
        session, campaign_id=campaign_id, ai_provider=provider, research_provider=provider,
        image_provider=image_provider, renderer=variant_renderer, config=config,
    )

    variants = get_platform_campaign_variants(session, campaign_id)
    pinterest_variants = [v for v in variants if v.target_platform == "pinterest"]
    assert len(pinterest_variants) == 2
    assert all(v.status == "RENDERED" for v in pinterest_variants)
    # Neither shares with the other — their CreativeDirections genuinely disagree.
    assert all(v.shared_scene_source == "" for v in pinterest_variants)
    session.close()


async def test_scene_reuse_never_crosses_platform_boundaries(temp_db, tmp_path, variant_renderer):
    """Requirement 5: the background cache is reset at the top of every
    platform's own loop iteration inside `_render_additional_platform_
    variants` — a `shared_scene_source` value must always name the SAME
    platform the variant itself belongs to, never a different one, even
    across three platforms sharing two languages with identical AI-returned
    directions. (Cross-campaign isolation holds by construction — the cache
    is a local variable scoped to one `_render_additional_platform_variants`
    call, i.e. one campaign's one Visuals run; there is no module- or
    class-level cache for a second campaign to ever observe.)
    """
    session = temp_db.SessionLocal()
    brand, category = _make_brand_category_assets(session, tmp_path)
    campaign = Campaign(
        display_id=f"HANNA-SKIN-{uuid.uuid4().hex[:8]}", brand_id=brand.id, category_id=category.id,
        objective="awareness", status="IDEA", languages=["pt-BR", "en"],
        target_platforms=["instagram", "facebook", "pinterest"],
    )
    session.add(campaign)
    session.commit()
    campaign_id = campaign.id

    provider = FakeMultiVariantProvider()
    image_provider = _FakeImageProvider()
    config = _config(tmp_path)
    await run_autopilot(
        session, campaign_id=campaign_id, ai_provider=provider, research_provider=provider,
        image_provider=image_provider, renderer=variant_renderer, config=config,
    )

    variants = get_platform_campaign_variants(session, campaign_id)
    assert any(v.shared_scene_source for v in variants)  # the test is non-vacuous
    for v in variants:
        for part in (v.shared_scene_source.split(",") if v.shared_scene_source else []):
            assert part.startswith(f"{v.target_platform}:"), (
                f"{v.target_platform}/{v.language} claims a shared scene from {part!r} — "
                "must never reference a different platform."
            )
    session.close()
