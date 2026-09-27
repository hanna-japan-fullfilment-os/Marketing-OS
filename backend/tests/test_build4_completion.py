"""Build 4 carry-forward requirement 1 (Build 5 spec's own "BUILD 4
CARRY-FORWARD REQUIREMENTS" section) — COMPLETE FEEDBACK GROUNDING ACROSS
CREATIVE PLANNING.

Build 4 itself (see `test_build4_review_engine.py`) already wired selective,
bounded owner-feedback grounding into `CampaignCopy` and `_generate_
creative_direction`. Two gaps remained before "every relevant planning
stage" was true:

1. `CarouselPlan` (both the discovery and non-discovery branches of
   `run_copy_stage`) computed a `feedback_note` but never appended it to
   either prompt.
2. `_resolve_platform_adaptation` and `generate_video_concept` never received
   a `feedback_note` parameter at all — a TikTok/pt-BR "weak hook" pattern
   had no way to reach future TikTok/pt-BR video-concept generation, and a
   platform-wide adaptation note had no way to reach `_resolve_platform_
   adaptation`.

This file proves all three are now grounded, using the SAME selective/
bounded `select_feedback_examples` mechanism (never a new one), and that the
platform/language exclusion discipline (`test_feedback_selector_is_
selective_by_platform_and_language` in `test_build4_review_engine.py`) holds
for these three newly-wired call sites too — matching this build's own
worked examples:

  - "If Instagram/pt-BR carousel feedback says 'too much text', that
    feedback may influence future matching Instagram/pt-BR carousel
    planning but should not automatically affect Pinterest/en."
  - "If multiple TikTok/pt-BR concepts were rejected because the hook was
    weak, future TikTok/pt-BR video-concept generation should be able to
    receive that relevant pattern" — without leaking into an unrelated
    platform.

Also proves (requirement 2) that none of these three newly-wired prompts
ever carries a rejected/approved variant's literal copy text — only the
existing characterization-only `format_feedback_for_prompt` output.

Feedback is attached to a variant on a SEPARATE, earlier "history" campaign
for the same brand — `select_feedback_examples` filters by `brand_id` alone
(never `campaign_id`), so this is the realistic shape: a brand's past
campaigns teaching a brand-new one, the same pattern `test_build4_review_
engine.py::test_novelty_remains_functional_with_feedback_present` already
uses.
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


import uuid

import pytest
from PIL import Image

from app.models import Asset, Brand, Campaign, Category, PlatformCampaignVariant
from app.schemas.ai import (
    CampaignCopy, CampaignStrategy, CampaignStrategyCandidates, CarouselPlan, CreativeBrief, ResearchInsightItem,
    ResearchResult, SlidePlan,
)
from app.schemas.creative_director import MasterCampaignConcept, PlatformAdaptation, VideoConcept
from app.services.creative.renderer import PlaywrightRenderer
from app.services.orchestrator import AutopilotConfig, run_copy_stage, run_strategy_stage, run_visuals_stage
from app.services.review_engine import record_review_feedback


@pytest.fixture()
async def variant_renderer():
    renderer = PlaywrightRenderer()
    yield renderer
    await renderer.close()


def _config(tmp_path, **overrides):
    return AutopilotConfig(
        campaign_model="gpt-5.1", research_model="gpt-5.1", trend_ttl_hours=24, category_ttl_hours=168,
        too_similar_threshold=75, acceptable_threshold=45, output_root=tmp_path / "output", **overrides,
    )


def _make_brand_category_assets(session, tmp_path, *, num_assets=2):
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


def _record_history_feedback(session, brand, category, *, platform, language, reason_code="", reason_text=""):
    """A minimal earlier "history" campaign + variant, purely to give
    `record_review_feedback` something to snapshot/attach to — mirrors
    `test_build4_review_engine.py::test_novelty_remains_functional_with_
    feedback_present`'s own "feedback on file for this brand" setup.
    """
    history_campaign = Campaign(
        display_id=f"HANNA-HIST-{uuid.uuid4().hex[:8]}", brand_id=brand.id, category_id=category.id,
        objective="awareness", status="REVIEW", languages=[language], target_platforms=[platform],
    )
    session.add(history_campaign)
    session.commit()
    variant = PlatformCampaignVariant(
        campaign_id=history_campaign.id, target_platform=platform, language=language,
        content_type="feed_post", status="RENDERED", slide_asset_paths=["history-slide.png"],
    )
    session.add(variant)
    session.commit()
    return record_review_feedback(
        session, campaign=history_campaign, variant=variant, level="PLATFORM_VARIANT",
        action="REQUEST_REVISION", reason_code=reason_code, reason_text=reason_text,
    )


class _CapturingProvider:
    """Records every `(schema, user)` pair, dispatching on schema like every
    other fake `AIProvider` in this codebase — canned values copied from
    `test_orchestrator.py::FakeAutopilotProvider` / `test_build4_review_
    engine.py::_RevisionFakeProvider` (this codebase's own stated convention
    is to duplicate rather than cross-import test fixtures).
    """

    def __init__(self):
        self.schema_calls: list[type] = []
        self.user_prompts: list[str] = []

    async def generate_structured(self, *, system, user, schema, model):
        self.schema_calls.append(schema)
        self.user_prompts.append(user)
        if schema is CampaignStrategyCandidates:
            return CampaignStrategyCandidates(candidates=[
                CampaignStrategy(
                    objective="awareness", audience="Young adults in Brazil", funnel_stage="tofu",
                    insight="Routines are trending", angle="Build your routine",
                    key_message="Everything for a 5-step routine", reason_this_should_work="Rides the trend.",
                )
            ])
        if schema is CreativeBrief:
            return CreativeBrief(
                design_concept="Clean hero shot", visual_prompt="Product on a gradient",
                template_suggestion="feature_showcase", tone_notes="Warm",
            )
        if schema is CampaignCopy:
            return CampaignCopy(
                hook="Your skin deserves this", headline="Straight from Japan", supporting_copy="Sourced firsthand.",
                cta="Shop now", caption="Straight from Japan.", hashtags=["#skincare"],
                alt_text="Product bottle on a gradient background",
            )
        if schema is CarouselPlan:
            return CarouselPlan(
                slides=[SlidePlan(slide_number=1, purpose="hero", headline="Slide one", body="Body one",
                                   cta="Shop now", visual_brief="Hero shot")],
                narrative_summary="A one-slide carousel.",
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
                narrative_shape="Open, reveal, close", tone_adjustment="warm", content_type="feed_post",
            )
        if schema is VideoConcept:
            return VideoConcept(
                hook="Your 5-step routine starts here", script="Open on the product. Close on the result.",
                shot_list=["Product hero shot", "Result close-up"], timing="0-3s hook, 3-15s close",
                visual_direction="Warm, natural light", on_screen_text=["Step 1"],
                caption="Everything for a 5-step routine.", cover_creative_brief="Product hero shot",
            )
        raise AssertionError(f"Unexpected schema requested: {schema}")

    async def research(self, query, *, model):
        return ResearchResult(insights=[
            ResearchInsightItem(
                statement="Multi-step skincare routines are trending in Brazil.", confidence=0.8,
                freshness="this_quarter", category="trend", recommended_implication="Emphasize routine-building.",
                source_urls=["https://example.com/trend-report"],
            )
        ])


def _prompts_for(provider: _CapturingProvider, schema: type) -> list[str]:
    return [user for s, user in zip(provider.schema_calls, provider.user_prompts) if s is schema]


# ---------------------------------------------------------------------------
# Gap 1: CarouselPlan.
# ---------------------------------------------------------------------------

async def test_carousel_plan_receives_matching_platform_language_feedback(temp_db, tmp_path):
    """Instagram/pt-BR carousel feedback reaches a NEW campaign's Instagram/
    pt-BR carousel planning, but not its Instagram/en carousel planning —
    the spec's own worked example, now proven for `CarouselPlan` specifically
    (previously only proven for `CampaignCopy`/`CreativeDirection`).
    """
    session = temp_db.SessionLocal()
    brand, category = _make_brand_category_assets(session, tmp_path)
    feedback = _record_history_feedback(
        session, brand, category, platform="instagram", language="pt-BR", reason_code="too_much_text",
    )
    assert feedback.id  # sanity: the history row really persisted

    campaign = Campaign(
        display_id=f"HANNA-SKIN-{uuid.uuid4().hex[:8]}", brand_id=brand.id, category_id=category.id,
        objective="awareness", status="IDEA", languages=["pt-BR", "en"], target_platforms=["instagram"],
    )
    session.add(campaign)
    session.commit()

    provider = _CapturingProvider()
    config = _config(tmp_path)
    await run_strategy_stage(
        session, campaign_id=campaign.id, ai_provider=provider, research_provider=provider, config=config,
    )
    await run_copy_stage(session, campaign_id=campaign.id, ai_provider=provider, config=config)

    carousel_prompts = _prompts_for(provider, CarouselPlan)
    assert len(carousel_prompts) == 2  # one per language, in `languages` order: pt-BR then en
    ptbr_prompt, en_prompt = carousel_prompts

    assert "Too much text" in ptbr_prompt  # the reason's display label
    assert "REJECTED or asked to revise" in ptbr_prompt
    assert "Too much text" not in en_prompt  # never bleeds into the other language

    # Requirement 2: characterization only, never the history variant's own
    # literal rendered copy.
    assert "history-slide.png" not in ptbr_prompt
    session.close()


async def test_carousel_plan_does_not_leak_cross_platform_feedback(temp_db, tmp_path):
    """Pinterest/en feedback must not blindly affect Instagram/pt-BR carousel
    planning — the platform side of the same worked example.
    """
    session = temp_db.SessionLocal()
    brand, category = _make_brand_category_assets(session, tmp_path)
    _record_history_feedback(
        session, brand, category, platform="pinterest", language="en", reason_code="too_generic",
    )

    campaign = Campaign(
        display_id=f"HANNA-SKIN-{uuid.uuid4().hex[:8]}", brand_id=brand.id, category_id=category.id,
        objective="awareness", status="IDEA", languages=["pt-BR"], target_platforms=["instagram"],
    )
    session.add(campaign)
    session.commit()

    provider = _CapturingProvider()
    config = _config(tmp_path)
    await run_strategy_stage(
        session, campaign_id=campaign.id, ai_provider=provider, research_provider=provider, config=config,
    )
    await run_copy_stage(session, campaign_id=campaign.id, ai_provider=provider, config=config)

    carousel_prompts = _prompts_for(provider, CarouselPlan)
    assert len(carousel_prompts) == 1
    assert "Too generic" not in carousel_prompts[0]
    session.close()


# ---------------------------------------------------------------------------
# Gap 2a: `generate_video_concept`.
# ---------------------------------------------------------------------------

async def test_video_concept_receives_matching_platform_language_feedback(temp_db, tmp_path, variant_renderer):
    """TikTok/pt-BR 'weak hook' feedback reaches a new campaign's TikTok/pt-BR
    video-concept generation, but a Pinterest/pt-BR feedback row for the SAME
    language does not — proving the platform side of the filter for this
    call site specifically.
    """
    session = temp_db.SessionLocal()
    brand, category = _make_brand_category_assets(session, tmp_path)
    _record_history_feedback(
        session, brand, category, platform="tiktok", language="pt-BR",
        reason_text="The hook felt weak and generic — needs a stronger opening line.",
    )
    _record_history_feedback(
        session, brand, category, platform="pinterest", language="pt-BR", reason_code="too_generic",
    )

    campaign = Campaign(
        display_id=f"HANNA-SKIN-{uuid.uuid4().hex[:8]}", brand_id=brand.id, category_id=category.id,
        objective="awareness", status="IDEA", languages=["pt-BR"], target_platforms=["instagram", "tiktok"],
    )
    session.add(campaign)
    session.commit()
    campaign_id = campaign.id

    provider = _CapturingProvider()
    config = _config(tmp_path)
    await run_strategy_stage(
        session, campaign_id=campaign_id, ai_provider=provider, research_provider=provider, config=config,
    )
    await run_copy_stage(session, campaign_id=campaign_id, ai_provider=provider, config=config)
    await run_visuals_stage(
        session, campaign_id=campaign_id, renderer=variant_renderer, config=config, ai_provider=provider,
    )

    video_prompts = _prompts_for(provider, VideoConcept)
    assert len(video_prompts) == 1  # exactly the tiktok/pt-BR combination
    assert "hook felt weak" in video_prompts[0].lower()
    assert "Too generic" not in video_prompts[0]  # the pinterest-scoped row never leaks in
    session.close()


async def test_video_concept_does_not_leak_cross_platform_feedback(temp_db, tmp_path, variant_renderer):
    """A TikTok-scoped feedback row must not reach a different video-oriented
    platform's (YouTube Shorts) script generation for the same language.
    """
    session = temp_db.SessionLocal()
    brand, category = _make_brand_category_assets(session, tmp_path)
    _record_history_feedback(
        session, brand, category, platform="tiktok", language="pt-BR",
        reason_text="The hook felt weak and generic.",
    )

    campaign = Campaign(
        display_id=f"HANNA-SKIN-{uuid.uuid4().hex[:8]}", brand_id=brand.id, category_id=category.id,
        objective="awareness", status="IDEA", languages=["pt-BR"],
        target_platforms=["instagram", "youtube_shorts"],
    )
    session.add(campaign)
    session.commit()
    campaign_id = campaign.id

    provider = _CapturingProvider()
    config = _config(tmp_path)
    await run_strategy_stage(
        session, campaign_id=campaign_id, ai_provider=provider, research_provider=provider, config=config,
    )
    await run_copy_stage(session, campaign_id=campaign_id, ai_provider=provider, config=config)
    await run_visuals_stage(
        session, campaign_id=campaign_id, renderer=variant_renderer, config=config, ai_provider=provider,
    )

    video_prompts = _prompts_for(provider, VideoConcept)
    assert len(video_prompts) == 1  # exactly the youtube_shorts/pt-BR combination
    assert "hook felt weak" not in video_prompts[0].lower()
    session.close()


# ---------------------------------------------------------------------------
# Gap 2b: `_resolve_platform_adaptation`.
# ---------------------------------------------------------------------------

async def test_platform_adaptation_receives_platform_scoped_feedback_shared_across_languages(
    temp_db, tmp_path, variant_renderer,
):
    """A Pinterest-scoped feedback row reaches Pinterest's `PlatformAdaptation`
    call (shared across every language that platform targets — Pinterest
    adaptation is computed ONCE per platform, never per language, see
    `_render_additional_platform_variants`'s docstring), but never reaches
    Instagram's own `PlatformAdaptation` call.
    """
    session = temp_db.SessionLocal()
    brand, category = _make_brand_category_assets(session, tmp_path)
    _record_history_feedback(
        session, brand, category, platform="pinterest", language="en",
        reason_code="pinterest_creative_too_horizontal",
    )

    campaign = Campaign(
        display_id=f"HANNA-SKIN-{uuid.uuid4().hex[:8]}", brand_id=brand.id, category_id=category.id,
        objective="awareness", status="IDEA", languages=["pt-BR", "en"],
        target_platforms=["instagram", "pinterest"],
    )
    session.add(campaign)
    session.commit()
    campaign_id = campaign.id

    provider = _CapturingProvider()
    config = _config(tmp_path)
    await run_strategy_stage(
        session, campaign_id=campaign_id, ai_provider=provider, research_provider=provider, config=config,
    )
    await run_copy_stage(session, campaign_id=campaign_id, ai_provider=provider, config=config)
    await run_visuals_stage(
        session, campaign_id=campaign_id, renderer=variant_renderer, config=config, ai_provider=provider,
    )

    adaptation_prompts = _prompts_for(provider, PlatformAdaptation)
    # One call per target platform (order follows `target_platforms`),
    # shared across both targeted languages — never one call per language.
    assert len(adaptation_prompts) == 2
    instagram_prompt, pinterest_prompt = adaptation_prompts

    assert "Pinterest creative too horizontal" in pinterest_prompt  # the feedback's own display label
    assert "Pinterest creative too horizontal" not in instagram_prompt  # never leaks cross-platform
    session.close()
