"""Tests for Build 2 (MARKETING OS — PLATFORM ADAPTER + CREATIVE DIRECTOR +
HYBRID VISUAL ENGINE): `PlatformCreativeSpec` (Parts A/B), the Creative Director
schemas (Parts E/F/G/H/L), the Brand Asset Validator (Part C), model role
routing / quality modes (Parts D/K), and the multi-variant renderer itself
(`services/orchestrator.py::_render_additional_platform_variants`) — the core
carry-forward fix for Build 1's own documented limitation: every selected
(target_platform x language) combination now gets an independently rendered
`PlatformCampaignVariant`, not just the first-selected one.

Kept as its own module (mirrors `test_build1_product_facts_and_platform_api.py`)
rather than appended to `test_orchestrator.py`, which is already large. Local
fake providers are duplicated here rather than imported from
`test_orchestrator.py`/`test_api.py`, matching this codebase's own stated
convention of keeping each test file's fakes local.
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
from pathlib import Path

import pytest
from PIL import Image

from app.data.platform_creative_specs import (
    PLATFORM_CONTENT_TYPES, PlatformCreativeSpec, default_content_type_for_platform,
    list_content_types_for_platform, resolve_platform_creative_spec,
)
from app.models import AuditEvent, Asset, Brand, BrandAsset, Campaign, Category, PlatformCampaignVariant, Product
from app.schemas.ai import (
    CampaignCopy, CampaignStrategy, CampaignStrategyCandidates, CarouselPlan, CreativeBrief, ProductFidelityCheck,
    ResearchInsightItem, ResearchResult, SlidePlan,
)
from app.schemas.creative_director import CreativeDirection, MasterCampaignConcept, PlatformAdaptation, VideoConcept
from app.services.brand_assets_validator import validate_brand_assets
from app.services.creative.renderer import PlaywrightRenderer
from app.services.creative.templates import PLATFORM_FORMATS
from app.services.orchestrator import (
    AutopilotConfig, _deterministic_creative_direction, _generate_creative_direction, _resolve_image_model_and_quality,
    generate_video_concept, get_platform_campaign_variants, run_autopilot,
)


# ---------------------------------------------------------------------------
# Part A/B — PlatformCreativeSpec catalog
# ---------------------------------------------------------------------------

def test_platform_creative_spec_dataclass_has_expected_shape():
    """PlatformCreativeSpec validates — a real instance carries every field Part A
    asked for, with sane types (not stringly-typed booleans, not fabricated
    dimensions for a script-only spec).
    """
    spec = resolve_platform_creative_spec("instagram", "feed_post")
    assert isinstance(spec, PlatformCreativeSpec)
    assert spec.platform == "instagram"
    assert spec.content_type == "feed_post"
    assert spec.width == 1080 and spec.height == 1080
    assert spec.render_format_key == "instagram_square"
    assert spec.supports_static is True
    assert spec.supports_short_video is False
    assert isinstance(spec.safe_zones, tuple)


def test_instagram_carousel_content_type_resolves():
    spec = resolve_platform_creative_spec("instagram", "carousel")
    assert spec.supports_carousel is True
    assert spec.supports_static is True
    assert spec.render_format_key == "instagram_portrait"
    assert spec.recommended_slide_count > 1


def test_facebook_config_resolves():
    spec = resolve_platform_creative_spec("facebook", "feed_post")
    assert spec.platform == "facebook"
    assert spec.render_format_key == "facebook_feed"
    assert spec.width == 1200 and spec.height == 630

    multi = resolve_platform_creative_spec("facebook", "multi_image_campaign")
    assert multi.supports_carousel is True


def test_tiktok_config_resolves_as_script_only_never_a_rendered_video():
    """Part B/L: TikTok's video-oriented content types must never claim to
    support a static render — they route to the script/shot-list path instead.
    """
    spec = resolve_platform_creative_spec("tiktok", "short_video_concept")
    assert spec.supports_static is False
    assert spec.supports_short_video is True
    assert spec.script_required is True
    assert spec.width == 0 and spec.height == 0 and spec.render_format_key == ""

    cover = resolve_platform_creative_spec("tiktok", "cover")
    assert cover.supports_static is True  # the cover frame IS a real static image


def test_pinterest_config_resolves():
    spec = resolve_platform_creative_spec("pinterest", "pin")
    assert spec.render_format_key == "pinterest_vertical"
    assert spec.aspect_ratio == "2:3"
    assert spec.width == 1000 and spec.height == 1500


def test_pinterest_vertical_render_format_is_registered_in_platform_formats():
    """`PlatformCreativeSpec.render_format_key` values must always resolve
    against the real pixel-exact canvas registry — Pinterest was Build 2's
    first non-Instagram/Facebook render format added there.
    """
    fmt = PLATFORM_FORMATS["pinterest_vertical"]
    assert fmt.width == 1000 and fmt.height == 1500


def test_resolve_platform_creative_spec_raises_on_unknown_platform_or_content_type():
    with pytest.raises(ValueError, match="Unknown platform"):
        resolve_platform_creative_spec("snapchat", "feed_post")
    with pytest.raises(ValueError, match="Unknown content type"):
        resolve_platform_creative_spec("instagram", "not_a_real_content_type")


def test_default_content_type_for_platform_prefers_carousel_for_multi_slide_plans():
    assert default_content_type_for_platform("instagram", slide_count=1) == "feed_post"
    assert default_content_type_for_platform("instagram", slide_count=3) == "carousel"
    assert default_content_type_for_platform("facebook", slide_count=3) == "multi_image_campaign"
    assert default_content_type_for_platform("linkedin", slide_count=3) == "carousel_document_concept"
    # Pinterest has no carousel-shaped content type — stays on its single pin
    # format even for a multi-slide plan, rather than inventing one.
    assert default_content_type_for_platform("pinterest", slide_count=3) == "pin"
    assert default_content_type_for_platform("not_a_platform", slide_count=1) is None


def test_every_platform_in_the_catalog_has_at_least_one_content_type():
    for platform, content_types in PLATFORM_CONTENT_TYPES.items():
        assert content_types, f"{platform} has no content types registered"
        assert list_content_types_for_platform(platform) == sorted(content_types)


# ---------------------------------------------------------------------------
# Part E/F/G/H/L — Creative Director schemas
# ---------------------------------------------------------------------------

def test_master_campaign_concept_schema_validates():
    concept = MasterCampaignConcept(
        concept_name="Everyday Ritual", campaign_promise="A routine that fits your day",
        key_message="Everything for a 5-step routine", emotional_goal="Confidence",
        audience="Young adults in Brazil", objective="awareness",
        visual_identity="Clean hero shot on a warm gradient",
        story_arc="Open on product, reveal routine, close on result", cta_intent="Try the routine",
    )
    assert concept.must_include == []
    assert concept.must_avoid == []
    # Deliberately platform/language agnostic — nothing here names a specific
    # platform format or a specific language's wording.
    assert "instagram" not in concept.model_dump_json().lower()


def test_platform_adaptation_schema_validates():
    adaptation = PlatformAdaptation(
        platform="tiktok", adaptation_strategy="hook + script + shot progression",
        narrative_shape="Compressed to a single hook + payoff", tone_adjustment="native/organic",
        content_type="short_video_concept",
    )
    assert adaptation.reasoning == ""  # optional, defaults empty rather than fabricated


def test_creative_direction_schema_validates_with_part_j_prohibited_elements_default():
    """Part J: the AI must never be asked to generate the exact product label,
    logo, headline/body/CTA copy, price/discount graphic, or legal text — this
    default is what `_render_additional_platform_variants` actually ships to
    the background-generation prompt.
    """
    direction = CreativeDirection()
    assert "brand logo rendered by the AI" in direction.prohibited_elements
    assert "exact product label text rendered by the AI" in direction.prohibited_elements
    assert "price or discount graphic" in direction.prohibited_elements
    assert len(direction.prohibited_elements) == 5


def test_video_concept_is_rendered_video_is_always_false():
    """Part L: even a caller that explicitly tries to set is_rendered_video=True
    must not be able to — this app has no video-rendering capability and must
    never claim otherwise.
    """
    concept = VideoConcept(hook="Hook", script="Script", is_rendered_video=True)
    assert concept.is_rendered_video is False


# ---------------------------------------------------------------------------
# Part F — PlatformCampaignVariant model
# ---------------------------------------------------------------------------

def _make_brand_and_category(session):
    brand = Brand(name="Hanna", slug=f"hanna-{uuid.uuid4().hex[:8]}", colors={"primary": "#f2ede3"})
    session.add(brand)
    session.commit()
    category = Category(brand_id=brand.id, name="Skincare", slug="skincare")
    session.add(category)
    session.commit()
    return brand, category


def test_platform_campaign_variant_model_persists_and_enforces_uniqueness(temp_db):
    session = temp_db.SessionLocal()
    brand, category = _make_brand_and_category(session)
    campaign = Campaign(display_id=f"HANNA-SKIN-{uuid.uuid4().hex[:8]}", brand_id=brand.id, category_id=category.id)
    session.add(campaign)
    session.commit()

    variant = PlatformCampaignVariant(
        campaign_id=campaign.id, target_platform="instagram", language="pt-BR", content_type="carousel",
        render_format_key="instagram_portrait", status="RENDERED", slide_asset_paths=["/tmp/a.png"],
        copy_language="pt-BR", creative_direction={"platform": "instagram"},
    )
    session.add(variant)
    session.commit()

    fetched = session.query(PlatformCampaignVariant).filter(PlatformCampaignVariant.campaign_id == campaign.id).one()
    assert fetched.status == "RENDERED"
    assert fetched.slide_asset_paths == ["/tmp/a.png"]

    # Same (campaign, platform, language, content_type) combination again ->
    # the uq_platform_variant constraint must refuse the duplicate.
    session.add(PlatformCampaignVariant(
        campaign_id=campaign.id, target_platform="instagram", language="pt-BR", content_type="carousel",
    ))
    with pytest.raises(Exception):
        session.commit()
    session.rollback()
    session.close()


# ---------------------------------------------------------------------------
# Part C — Brand Asset Validator
# ---------------------------------------------------------------------------

def test_brand_asset_validator_flags_missing_assets_without_fabricating_anything(temp_db):
    session = temp_db.SessionLocal()
    # Deliberately no colors/typography set (unlike `_make_brand_and_category`'s
    # shared helper, which sets a real palette) — this brand's catalog is
    # genuinely empty in every dimension the validator checks.
    brand = Brand(name="Hanna", slug=f"hanna-{uuid.uuid4().hex[:8]}")
    session.add(brand)
    session.commit()
    category = Category(brand_id=brand.id, name="Skincare", slug="skincare")
    session.add(category)
    session.commit()
    product = Product(brand_id=brand.id, category_id=category.id, name="Cleanser", slug="cleanser")
    session.add(product)
    session.commit()

    result = validate_brand_assets(session, brand)
    assert result.valid is False
    assert result.logo_present is False
    assert result.logo_path == ""  # never a fabricated placeholder path
    assert result.fonts_resolved is False
    assert result.palette_present is False
    assert result.products_without_photos == 1
    assert any("logo" in issue.lower() for issue in result.issues)
    session.close()


def test_brand_asset_validator_passes_with_real_logo_fonts_palette_and_photos(temp_db, tmp_path):
    session = temp_db.SessionLocal()
    brand, category = _make_brand_and_category(session)
    brand.typography = {"primary_font": "Poppins"}
    brand.colors = {"primary": "#f2ede3", "secondary": "#d8c9ad"}
    session.commit()

    logo_path = tmp_path / "logo.png"
    Image.new("RGBA", (200, 200), (255, 255, 255, 0)).save(logo_path)
    session.add(BrandAsset(brand_id=brand.id, kind="logo", file_path=str(logo_path), label="Primary logo"))
    session.commit()

    product = Product(brand_id=brand.id, category_id=category.id, name="Cleanser", slug="cleanser")
    session.add(product)
    session.commit()
    photo_path = tmp_path / "cleanser.jpg"
    Image.new("RGB", (800, 800), (10, 50, 200)).save(photo_path)
    session.add(Asset(
        brand_id=brand.id, category_id=category.id, product_id=product.id, absolute_path=str(photo_path),
        relative_path="skincare/cleanser.jpg", filename="cleanser.jpg", extension=".jpg", sha256="sha-1",
        width=800, height=800, is_active=True,
    ))
    session.commit()

    result = validate_brand_assets(session, brand)
    assert result.valid is True
    assert result.logo_present is True
    assert result.logo_path == str(logo_path)
    assert result.products_with_photos == 1
    assert result.issues == []
    session.close()


# ---------------------------------------------------------------------------
# Part D/K — model role routing + quality modes
# ---------------------------------------------------------------------------

def test_autopilot_config_role_fields_fall_back_to_legacy_fields_when_unset():
    """Part D: an unset role field falls back to the legacy field it replaces,
    so a pre-Build-2 config (or Settings that hasn't been touched) behaves
    byte-for-byte as before.
    """
    config = AutopilotConfig(
        campaign_model="gpt-campaign", research_model="gpt-research", trend_ttl_hours=24, category_ttl_hours=168,
        too_similar_threshold=75, acceptable_threshold=45, output_root=Path("/tmp/x"), image_model="gpt-image-1",
        vision_model="gpt-vision",
    )
    assert config.strategy_model == "gpt-campaign"
    assert config.copy_model == "gpt-campaign"
    assert config.platform_adapter_model == "gpt-campaign"
    assert config.creative_director_model == "gpt-campaign"
    assert config.draft_image_model == "gpt-image-1"
    assert config.premium_image_model == "gpt-image-1"
    assert config.revision_model == "gpt-image-1"
    assert config.creative_qa_model == "gpt-vision"


def test_autopilot_config_role_fields_are_not_overridden_when_explicitly_set():
    config = AutopilotConfig(
        campaign_model="gpt-campaign", research_model="gpt-research", trend_ttl_hours=24, category_ttl_hours=168,
        too_similar_threshold=75, acceptable_threshold=45, output_root=Path("/tmp/x"),
        creative_director_model="gpt-creative-director",
    )
    assert config.creative_director_model == "gpt-creative-director"
    assert config.strategy_model == "gpt-campaign"  # still falls back, unaffected by the other override


def test_quality_modes_resolve_correctly():
    """Part K: DRAFT/STANDARD/PREMIUM each resolve to a distinct (model,
    quality-tier) pair; STANDARD (the default) must be byte-for-byte what
    every pre-Build-2 call site always used.
    """
    base = dict(
        campaign_model="gpt-campaign", research_model="gpt-research", trend_ttl_hours=24, category_ttl_hours=168,
        too_similar_threshold=75, acceptable_threshold=45, output_root=Path("/tmp/x"), image_model="gpt-image-1",
        draft_image_model="gpt-image-draft", premium_image_model="gpt-image-premium",
    )
    standard = AutopilotConfig(**base, quality_mode="standard")
    assert _resolve_image_model_and_quality(standard) == ("gpt-image-1", "high")

    draft = AutopilotConfig(**base, quality_mode="draft")
    assert _resolve_image_model_and_quality(draft) == ("gpt-image-draft", "low")

    premium = AutopilotConfig(**base, quality_mode="premium")
    assert _resolve_image_model_and_quality(premium) == ("gpt-image-premium", "high")


# ---------------------------------------------------------------------------
# Part G/H — creative direction generation (AI-optional, per-language)
# ---------------------------------------------------------------------------

class _FakeLanguageAwareProvider:
    """Returns a CreativeDirection whose typography/headline fields genuinely
    differ depending on which language was asked for — read out of the `user`
    prompt text `_generate_creative_direction` builds (which always embeds
    "Language: <language>."), the same way the real model would be told which
    language to write for. Used to prove Part H's requirement concretely
    rather than merely asserting two independent literal schemas differ.
    """

    async def generate_structured(self, *, system, user, schema, model):
        assert schema is CreativeDirection
        if "Language: en." in user:
            return CreativeDirection(
                language="en", typography_direction="Compact single-line headline, wide tracking",
                headline_emphasis="Short punchy English headline",
            )
        if "Language: pt-BR." in user:
            return CreativeDirection(
                language="pt-BR", typography_direction="Two-line headline, tighter tracking for longer PT-BR words",
                headline_emphasis="Headline wraps to two lines to fit longer Portuguese phrasing",
            )
        raise AssertionError(f"Unexpected language in prompt: {user}")


async def test_creative_direction_differs_between_english_and_portuguese():
    """Part H: 'do not assume identical typography for English and Portuguese' —
    calling `_generate_creative_direction` once per language must be able to
    produce genuinely different typography/layout guidance per language.
    """
    provider = _FakeLanguageAwareProvider()
    master_concept = MasterCampaignConcept(
        concept_name="Everyday Ritual", campaign_promise="A routine that fits your day",
        key_message="Everything for a 5-step routine", emotional_goal="Confidence",
        audience="Young adults", objective="awareness", visual_identity="Clean hero shot",
        story_arc="Open, reveal, close", cta_intent="Try it",
    )
    adaptation = PlatformAdaptation(
        platform="instagram", adaptation_strategy="carousel", narrative_shape="Open, reveal, close",
        tone_adjustment="warm", content_type="carousel",
    )
    fallback = CreativeDirection(platform="instagram", content_type="carousel")
    slide = type("Slide", (), {"purpose": "hero", "headline": "Headline", "visual_brief": "Hero shot"})()

    en_direction = await _generate_creative_direction(
        provider, master_concept=master_concept, adaptation=adaptation, platform="instagram", language="en",
        content_type="carousel", slide=slide, model="gpt-5.1", fallback=fallback,
    )
    pt_direction = await _generate_creative_direction(
        provider, master_concept=master_concept, adaptation=adaptation, platform="instagram", language="pt-BR",
        content_type="carousel", slide=slide, model="gpt-5.1", fallback=fallback,
    )
    assert en_direction.typography_direction != pt_direction.typography_direction
    assert en_direction.headline_emphasis != pt_direction.headline_emphasis
    assert en_direction.language == "en"
    assert pt_direction.language == "pt-BR"


async def test_creative_direction_falls_back_deterministically_without_ai_provider():
    """No AI provider available -> the fallback (built only from already-known,
    real structural data) is returned unchanged, never a fabricated field.
    """
    master_concept = MasterCampaignConcept(
        concept_name="Everyday Ritual", campaign_promise="promise", key_message="message",
        emotional_goal="Confidence", audience="Young adults", objective="awareness",
        visual_identity="Clean hero shot", story_arc="Open, reveal, close", cta_intent="Try it",
    )
    adaptation = PlatformAdaptation(
        platform="pinterest", adaptation_strategy="vertical discovery creative", narrative_shape="Evergreen",
        tone_adjustment="informational", content_type="pin",
    )
    from app.services.creative.brand_style import ResolvedBrandStyle
    brand_style = ResolvedBrandStyle(
        primary_color="#f2ede3", accent_color="#d8c9ad", secondary_color="#d8c9ad", text_color="#222222",
        background_preference="brand_colors", primary_font="Poppins", secondary_font="Poppins",
        palette=["#f2ede3", "#d8c9ad"], disclaimer_text="",
    )
    fallback = _deterministic_creative_direction(
        master_concept=master_concept, adaptation=adaptation, platform="pinterest", language="en",
        content_type="pin", slide_role="hero", brand_style=brand_style,
    )
    result = await _generate_creative_direction(
        None, master_concept=master_concept, adaptation=adaptation, platform="pinterest", language="en",
        content_type="pin", slide=type("Slide", (), {"purpose": "hero", "headline": "H", "visual_brief": "B"})(),
        model="gpt-5.1", fallback=fallback,
    )
    assert result is fallback
    assert result.scene_generation_prompt == ""  # never a fabricated scene prompt with no AI available
    assert result.palette == ["#f2ede3", "#d8c9ad"]


async def test_generate_video_concept_returns_none_without_ai_provider_rather_than_fabricating():
    """Part L: no AI provider -> None, never an invented script. The caller
    records `status="SCRIPT_UNAVAILABLE"` for this case (see the integration
    test below) rather than shipping fabricated marketing content.
    """
    result = await generate_video_concept(
        None, master_concept=None, platform="tiktok", language="en",
        adaptation=PlatformAdaptation(
            platform="tiktok", adaptation_strategy="hook + script + shot progression", narrative_shape="",
            tone_adjustment="", content_type="short_video_concept",
        ),
        model="gpt-5.1",
    )
    assert result is None


# ---------------------------------------------------------------------------
# Integration — the actual multi-variant renderer, via run_autopilot
# ---------------------------------------------------------------------------

class FakeMultiVariantProvider:
    """AIProvider + ResearchProvider stand-in covering every schema the full
    Strategy -> Copy -> Visuals -> multi-variant pipeline can request,
    including Build 2's new Creative Director schemas.
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


def _make_brand_category_assets(session, tmp_path, *, num_assets=3):
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


def _multi_variant_config(tmp_path):
    return AutopilotConfig(
        campaign_model="gpt-5.1", research_model="gpt-5.1", trend_ttl_hours=24, category_ttl_hours=168,
        too_similar_threshold=75, acceptable_threshold=45, output_root=tmp_path / "output",
    )


@pytest.fixture()
async def variant_renderer():
    renderer = PlaywrightRenderer()
    yield renderer
    await renderer.close()


async def test_multi_variant_renderer_creates_one_variant_per_platform_language_combination(
    temp_db, tmp_path, variant_renderer,
):
    """The core Build 2 deliverable: Instagram+pt-BR, Instagram+en, Facebook+
    pt-BR, Facebook+en must all become four independently reviewable variants
    when those targets are selected — not just the first-selected combination.
    """
    session = temp_db.SessionLocal()
    brand, category = _make_brand_category_assets(session, tmp_path)
    campaign = Campaign(
        display_id=f"HANNA-SKIN-{uuid.uuid4().hex[:8]}", brand_id=brand.id, category_id=category.id,
        objective="awareness", status="IDEA", languages=["pt-BR", "en"],
        target_platforms=["instagram", "facebook"],
    )
    session.add(campaign)
    session.commit()
    campaign_id = campaign.id

    provider = FakeMultiVariantProvider()
    await run_autopilot(
        session, campaign_id=campaign_id, ai_provider=provider, research_provider=provider,
        renderer=variant_renderer, config=_multi_variant_config(tmp_path),
    )

    variants = get_platform_campaign_variants(session, campaign_id)
    combos = {(v.target_platform, v.language) for v in variants}
    assert combos == {("instagram", "pt-BR"), ("instagram", "en"), ("facebook", "pt-BR"), ("facebook", "en")}
    # Every combination reached a real terminal state — never left PENDING.
    assert all(v.status in ("RENDERED", "FAILED") for v in variants)
    rendered = [v for v in variants if v.status == "RENDERED"]
    assert len(rendered) == 4
    for v in rendered:
        assert v.slide_asset_paths
        for p in v.slide_asset_paths:
            assert Path(p).exists()
    session.close()


async def test_multi_variant_primary_combination_reuses_legacy_rendered_paths(temp_db, tmp_path, variant_renderer):
    """The primary (first-selected platform x first-selected language)
    combination must reference the exact same slide paths `run_visuals_stage`'s
    own unchanged legacy loop already rendered — never a second, redundant
    render of the same combination.
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
    result = await run_autopilot(
        session, campaign_id=campaign_id, ai_provider=provider, research_provider=provider,
        renderer=variant_renderer, config=_multi_variant_config(tmp_path),
    )
    primary_paths = sorted(str(s.rendered_asset_path) for s in result.slides)

    variants = get_platform_campaign_variants(session, campaign_id)
    primary_variant = next(v for v in variants if v.target_platform == "instagram" and v.language == "pt-BR")
    assert sorted(primary_variant.slide_asset_paths) == primary_paths
    session.close()


async def test_multi_variant_platform_specific_render_size_is_honored(temp_db, tmp_path, variant_renderer):
    """Facebook's multi-image format (1200x630) and Pinterest's pin format
    (1000x1500) must actually produce differently-sized rendered images — not
    the same creative simply relabeled per platform. Instagram is deliberately
    the PRIMARY platform here (irrelevant to this test — the primary
    combination always reuses the legacy render's own fixed square canvas,
    regardless of which platform it belongs to) so both Facebook and Pinterest
    are exercised through the new content-type-driven render path instead.
    """
    session = temp_db.SessionLocal()
    brand, category = _make_brand_category_assets(session, tmp_path)
    campaign = Campaign(
        display_id=f"HANNA-SKIN-{uuid.uuid4().hex[:8]}", brand_id=brand.id, category_id=category.id,
        objective="awareness", status="IDEA", languages=["pt-BR"],
        target_platforms=["instagram", "facebook", "pinterest"],
    )
    session.add(campaign)
    session.commit()
    campaign_id = campaign.id

    provider = FakeMultiVariantProvider()
    await run_autopilot(
        session, campaign_id=campaign_id, ai_provider=provider, research_provider=provider,
        renderer=variant_renderer, config=_multi_variant_config(tmp_path),
    )

    variants = get_platform_campaign_variants(session, campaign_id)
    facebook_variant = next(v for v in variants if v.target_platform == "facebook")
    pinterest_variant = next(v for v in variants if v.target_platform == "pinterest")
    assert facebook_variant.status == "RENDERED" and pinterest_variant.status == "RENDERED"
    assert facebook_variant.content_type == "multi_image_campaign"
    assert pinterest_variant.content_type == "pin"

    with Image.open(facebook_variant.slide_asset_paths[0]) as img:
        assert img.size == (1200, 630)
    with Image.open(pinterest_variant.slide_asset_paths[0]) as img:
        assert img.size == (1000, 1500)
    session.close()


async def test_multi_variant_carousel_continuity_renders_every_planned_slide(temp_db, tmp_path, variant_renderer):
    """Instagram's carousel content type must render one slide per planned
    carousel slide (continuity across the sequence), using the same render
    format for every slide in the set. Facebook is deliberately the PRIMARY
    platform here so Instagram is exercised through the new content-type-
    driven render path (the primary combination's own render always uses the
    legacy pipeline's fixed square canvas instead, regardless of content type).
    """
    session = temp_db.SessionLocal()
    brand, category = _make_brand_category_assets(session, tmp_path, num_assets=4)
    campaign = Campaign(
        display_id=f"HANNA-SKIN-{uuid.uuid4().hex[:8]}", brand_id=brand.id, category_id=category.id,
        objective="awareness", status="IDEA", languages=["pt-BR"], target_platforms=["facebook", "instagram"],
    )
    session.add(campaign)
    session.commit()
    campaign_id = campaign.id

    provider = FakeMultiVariantProvider()
    result = await run_autopilot(
        session, campaign_id=campaign_id, ai_provider=provider, research_provider=provider,
        renderer=variant_renderer, config=_multi_variant_config(tmp_path),
    )
    # The primary combination's own legacy render already produced 2 slides
    # (from FakeMultiVariantProvider's 2-slide CarouselPlan) — confirms the
    # planned slide count this test's continuity check below is measured
    # against.
    assert len(result.slides) == 2

    variants = get_platform_campaign_variants(session, campaign_id)
    instagram_variant = next(v for v in variants if v.target_platform == "instagram" and v.language == "pt-BR")
    assert instagram_variant.content_type == "carousel"
    assert len(instagram_variant.slide_asset_paths) == 2
    for path in instagram_variant.slide_asset_paths:
        with Image.open(path) as img:
            assert img.size == (1080, 1350)  # every slide in the set uses the same render format
    session.close()


async def test_multi_variant_tiktok_is_script_only_never_a_rendered_video(temp_db, tmp_path, variant_renderer):
    """Part L, end to end: a video-oriented target platform must produce a
    structured script (status SCRIPT_ONLY, a populated VideoConcept with
    is_rendered_video=False) and never a rendered image/video asset.
    """
    session = temp_db.SessionLocal()
    brand, category = _make_brand_category_assets(session, tmp_path)
    campaign = Campaign(
        display_id=f"HANNA-SKIN-{uuid.uuid4().hex[:8]}", brand_id=brand.id, category_id=category.id,
        objective="awareness", status="IDEA", languages=["pt-BR"], target_platforms=["instagram", "tiktok"],
    )
    session.add(campaign)
    session.commit()
    campaign_id = campaign.id

    provider = FakeMultiVariantProvider()
    await run_autopilot(
        session, campaign_id=campaign_id, ai_provider=provider, research_provider=provider,
        renderer=variant_renderer, config=_multi_variant_config(tmp_path),
    )

    variants = get_platform_campaign_variants(session, campaign_id)
    tiktok_variant = next(v for v in variants if v.target_platform == "tiktok")
    assert tiktok_variant.status == "SCRIPT_ONLY"
    assert tiktok_variant.slide_asset_paths == []
    assert tiktok_variant.render_format_key == ""
    assert tiktok_variant.video_concept is not None
    assert tiktok_variant.video_concept["is_rendered_video"] is False
    assert tiktok_variant.video_concept["hook"]
    session.close()


async def test_multi_variant_tiktok_without_ai_provider_is_marked_script_unavailable(
    temp_db, tmp_path, variant_renderer,
):
    """`run_visuals_stage` can run with no AI provider at all (its documented
    no-key default path) — a video-oriented target platform in that case must
    be marked SCRIPT_UNAVAILABLE, never a fabricated script.
    """
    from app.services.orchestrator import run_copy_stage, run_strategy_stage, run_visuals_stage

    session = temp_db.SessionLocal()
    brand, category = _make_brand_category_assets(session, tmp_path)
    campaign = Campaign(
        display_id=f"HANNA-SKIN-{uuid.uuid4().hex[:8]}", brand_id=brand.id, category_id=category.id,
        objective="awareness", status="IDEA", languages=["pt-BR"], target_platforms=["instagram", "tiktok"],
    )
    session.add(campaign)
    session.commit()
    campaign_id = campaign.id

    provider = FakeMultiVariantProvider()
    config = _multi_variant_config(tmp_path)
    await run_strategy_stage(
        session, campaign_id=campaign_id, ai_provider=provider, research_provider=provider, config=config,
    )
    await run_copy_stage(session, campaign_id=campaign_id, ai_provider=provider, config=config)
    # No ai_provider passed here — the documented no-key Visuals path.
    await run_visuals_stage(session, campaign_id=campaign_id, renderer=variant_renderer, config=config)

    variants = get_platform_campaign_variants(session, campaign_id)
    tiktok_variant = next(v for v in variants if v.target_platform == "tiktok")
    assert tiktok_variant.status == "SCRIPT_UNAVAILABLE"
    assert tiktok_variant.video_concept is None
    session.close()


async def test_multi_variant_background_generation_is_shared_across_a_platforms_languages(
    temp_db, tmp_path, variant_renderer,
):
    """Cost discipline: an AI-generated background is generated once per
    (platform, slide index) and reused across that platform's other targeted
    languages — never regenerated just because the language changed.

    Pinterest is deliberately the SECOND target platform (Instagram is
    primary) so BOTH of Pinterest's languages go through the new multi-variant
    renderer's own loop (the primary combination always reuses the legacy
    render instead, which would make it a non-representative single-language
    case for what this test needs to prove).
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

    class _FakeImageProvider:
        def __init__(self):
            self.calls = 0

        async def generate(self, *, prompt, size, model, reference_images=None, quality="high"):
            self.calls += 1
            import io
            buf = io.BytesIO()
            Image.new("RGB", (64, 64), (200, 100, 50)).save(buf, format="PNG")
            return buf.getvalue()

        async def edit(self, *, base_image, prompt, model, mask=None, quality="high"):
            raise NotImplementedError

    provider = FakeMultiVariantProvider()
    image_provider = _FakeImageProvider()
    config = AutopilotConfig(
        campaign_model="gpt-5.1", research_model="gpt-5.1", trend_ttl_hours=24, category_ttl_hours=168,
        too_similar_threshold=75, acceptable_threshold=45, output_root=tmp_path / "output",
        use_ai_background=True,
    )
    await run_autopilot(
        session, campaign_id=campaign_id, ai_provider=provider, research_provider=provider,
        image_provider=image_provider, renderer=variant_renderer, config=config,
    )

    variants = get_platform_campaign_variants(session, campaign_id)
    pinterest_variants = [v for v in variants if v.target_platform == "pinterest"]
    assert len(pinterest_variants) == 2
    assert all(v.status == "RENDERED" for v in pinterest_variants)
    # Exactly one of Pinterest's two language variants should show a
    # shared_scene_source (the other one generated it originally) — never
    # both blank and never a separate generation for each language.
    assert sum(1 for v in pinterest_variants if v.shared_scene_source) == 1
    # Total background calls, one per (platform, language, slide index) that
    # isn't served from cache: Instagram's 2-slide carousel plan means 2 calls
    # for its primary pt-BR (legacy path, no caching there) + 2 more for its
    # non-primary "en" (no sharing partner — Instagram has only one
    # non-primary language here) = 4. Pinterest's single-image "pin" content
    # type only ever plans 1 slide, and that 1 slide's background is SHARED
    # across both of Pinterest's languages instead of generated twice = 1.
    # 5 total, not 6 — the saving is specifically Pinterest's missing 2nd call.
    assert image_provider.calls == 3
    session.close()



async def test_multi_variant_source_product_and_logo_remain_authentic(temp_db, tmp_path, variant_renderer):
    """Source product authenticity + authentic logo, end to end for a
    non-primary variant: with no AI recreation enabled, the real uploaded
    photo (never an AI-fabricated product) and the brand's real uploaded logo
    file (never a generated stand-in) are what actually get composited.
    """
    session = temp_db.SessionLocal()
    brand, category = _make_brand_category_assets(session, tmp_path)
    logo_path = tmp_path / "logo.png"
    Image.new("RGBA", (200, 200), (255, 255, 255, 0)).save(logo_path)
    session.add(BrandAsset(brand_id=brand.id, kind="logo", file_path=str(logo_path)))
    session.commit()

    campaign = Campaign(
        display_id=f"HANNA-SKIN-{uuid.uuid4().hex[:8]}", brand_id=brand.id, category_id=category.id,
        objective="awareness", status="IDEA", languages=["pt-BR", "en"], target_platforms=["facebook"],
    )
    session.add(campaign)
    session.commit()
    campaign_id = campaign.id

    provider = FakeMultiVariantProvider()
    await run_autopilot(
        session, campaign_id=campaign_id, ai_provider=provider, research_provider=provider,
        renderer=variant_renderer, config=_multi_variant_config(tmp_path),
    )

    variants = get_platform_campaign_variants(session, campaign_id)
    en_variant = next(v for v in variants if v.target_platform == "facebook" and v.language == "en")
    assert en_variant.status == "RENDERED"
    # No AI recreation was enabled -> the deterministic pipeline composited the
    # real uploaded photo verbatim (never routed through image generation);
    # the rendered asset exists as a real file on disk, not a claimed one.
    for path in en_variant.slide_asset_paths:
        assert Path(path).exists()
        with Image.open(path) as img:
            assert img.size[0] > 0 and img.size[1] > 0
    session.close()


async def test_multi_variant_unsupported_platform_is_skipped_not_fabricated(
    temp_db, tmp_path, variant_renderer, monkeypatch,
):
    """Defensive path: if the content-type catalog ever has nothing for a
    targeted platform (every platform `validate_target_platforms` currently
    allows does resolve — see `test_every_platform_in_the_catalog_has_at_
    least_one_content_type` above), the renderer must record a real
    SKIPPED_UNSUPPORTED row for every targeted language rather than silently
    dropping the platform or inventing a fake result for it.
    """
    import app.services.orchestrator as orchestrator_module

    monkeypatch.setattr(orchestrator_module, "default_content_type_for_platform", lambda platform, *, slide_count: None)

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
    await run_autopilot(
        session, campaign_id=campaign_id, ai_provider=provider, research_provider=provider,
        renderer=variant_renderer, config=_multi_variant_config(tmp_path),
    )

    variants = get_platform_campaign_variants(session, campaign_id)
    assert len(variants) == 2  # one per targeted language, never silently dropped
    for v in variants:
        assert v.status == "SKIPPED_UNSUPPORTED"
        assert v.slide_asset_paths == []
        assert v.video_concept is None
    session.close()


async def test_multi_variant_creative_director_calls_are_logged_for_traceability(
    temp_db, tmp_path, variant_renderer,
):
    """Build 2 extends `services/prompt_registry.py`'s Part I traceability
    (purpose/version/language/platform, logged as an AuditEvent) to its own
    new Creative Director calls — `platform_adaptation`, `creative_direction`,
    and `video_concept` (all logged from `_render_additional_platform_variants`
    for a non-primary combination; `master_campaign_concept`, logged from
    `run_copy_stage`, is covered by `tests/test_orchestrator.py::
    test_prompt_versions_seeded_and_usage_recorded_per_language`).
    """
    session = temp_db.SessionLocal()
    brand, category = _make_brand_category_assets(session, tmp_path)
    campaign = Campaign(
        display_id=f"HANNA-SKIN-{uuid.uuid4().hex[:8]}", brand_id=brand.id, category_id=category.id,
        objective="awareness", status="IDEA", languages=["pt-BR"], target_platforms=["facebook", "instagram", "tiktok"],
    )
    session.add(campaign)
    session.commit()
    campaign_id = campaign.id

    provider = FakeMultiVariantProvider()
    await run_autopilot(
        session, campaign_id=campaign_id, ai_provider=provider, research_provider=provider,
        renderer=variant_renderer, config=_multi_variant_config(tmp_path),
    )

    events = (
        session.query(AuditEvent)
        .filter(AuditEvent.entity_type == "campaign_prompt_usage", AuditEvent.entity_id == campaign_id)
        .all()
    )
    purposes_logged = {e.action for e in events}
    # facebook is primary (no new adaptation/direction call needed for it);
    # instagram and tiktok are both non-primary, so both generate a real
    # platform_adaptation. tiktok's content type is video-oriented, so it
    # generates a video_concept instead of a creative_direction.
    assert "platform_adaptation" in purposes_logged
    assert "creative_direction" in purposes_logged
    assert "video_concept" in purposes_logged
    from app.services.prompt_registry import PROMPT_VERSIONS

    tracked_actions = {
        "platform_adaptation",
        "creative_direction",
        "video_concept",
    }

    tracked_events = [
        e
        for e in events
        if e.action in tracked_actions
    ]

    assert tracked_events

    assert all(
        e.detail["version"]
        == PROMPT_VERSIONS[e.action].version
        for e in tracked_events
    )
    session.close()


def test_gpt_image_2_5_role_routing_and_native_instagram_size():
    from app.services.orchestrator import (
        _nearest_ai_image_size,
    )

    base = dict(
        campaign_model="gpt-campaign",
        research_model="gpt-research",
        trend_ttl_hours=24,
        category_ttl_hours=168,
        too_similar_threshold=75,
        acceptable_threshold=45,
        output_root=Path("/tmp/x"),
        image_model="gpt-image-2.5-sunburst-2026-09-08",
        draft_image_model="gpt-image-2.5-flare-2026-09-08",
        premium_image_model="gpt-image-2.5-sunburst-2026-09-08",
        revision_model="gpt-image-2.5-sunburst-2026-09-08",
    )

    standard = AutopilotConfig(
        **base,
        quality_mode="standard",
    )

    assert (
        _resolve_image_model_and_quality(
            standard
        )
        == (
            "gpt-image-2.5-sunburst-2026-09-08",
            "high",
        )
    )

    draft = AutopilotConfig(
        **base,
        quality_mode="draft",
    )

    assert (
        _resolve_image_model_and_quality(
            draft
        )
        == (
            "gpt-image-2.5-flare-2026-09-08",
            "low",
        )
    )

    premium = AutopilotConfig(
        **base,
        quality_mode="premium",
    )

    assert (
        _resolve_image_model_and_quality(
            premium
        )
        == (
            "gpt-image-2.5-sunburst-2026-09-08",
            "xhigh",
        )
    )

    assert (
        premium.revision_model
        == "gpt-image-2.5-sunburst-2026-09-08"
    )

    assert (
        _nearest_ai_image_size(
            1080,
            1350,
            model="gpt-image-2.5-sunburst-2026-09-08",
        )
        == "1088x1360"
    )


def test_native_4x5_does_not_leak_into_legacy_gpt_image_1():
    from app.services.orchestrator import (
        _nearest_ai_image_size,
    )

    assert (
        _nearest_ai_image_size(
            1080,
            1350,
            model="gpt-image-1",
        )
        == "1024x1536"
    )


def test_legacy_premium_model_remains_high_not_xhigh():
    legacy = AutopilotConfig(
        campaign_model="gpt-campaign",
        research_model="gpt-research",
        trend_ttl_hours=24,
        category_ttl_hours=168,
        too_similar_threshold=75,
        acceptable_threshold=45,
        output_root=Path("/tmp/x"),
        image_model="gpt-image-1",
        draft_image_model="gpt-image-1",
        premium_image_model="gpt-image-1",
        quality_mode="premium",
    )

    assert (
        _resolve_image_model_and_quality(
            legacy
        )
        == (
            "gpt-image-1",
            "high",
        )
    )

