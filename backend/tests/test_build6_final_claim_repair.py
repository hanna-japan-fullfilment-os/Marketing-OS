"""BUILD 6 — FINAL TARGETED REPAIR: UNSUPPORTED CLAIM ENFORCEMENT ONLY.

Focused tests for the real, code-enforced unsupported-claim gate this repair
adds (`app/services/claims_audit.py`), wired into `services/qa_engine.py`'s
`run_qa_stage` and read back (never recomputed) by `scripts/run_live_
acceptance.py`. See `services/claims_audit.py`'s own module docstring for the
full defect this replaces: the pre-repair `_check_unsupported_claims` only
ever checked `brand.disallowed_terms` and was handed rendered FILE PATHS
instead of real copy, so `unsupported_claim_flags == []` on every real case.

Tests A-J are fast, fully deterministic unit tests directly against
`claims_audit.py`'s own functions (no DB, no renderer, no AI provider) — the
always-on layer-1 pattern detector this repair's fail-closed guarantee
actually rests on. Test K is a full-pipeline integration test (Strategy ->
Copy -> Visuals -> `run_qa_stage`, mirroring `test_build3_qa_engine.py`'s own
established pattern) proving an unsupported claim reaching real generated
copy is a genuine hard fail that blocks `PASS` end-to-end. Item L from the
spec ("all existing tests remain green") is verified by running the full
backend suite alongside this file, not a dedicated test function here.

Test-file convention (established by test_build3_qa_engine.py /
test_build6_repair.py): fakes/helpers are duplicated locally, not imported
across test files.
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
from types import SimpleNamespace

from PIL import Image

from app.models import Asset, Brand, Campaign, Category, Product, VerifiedProductFact
from app.schemas.ai import CampaignCopy, CampaignStrategy, CampaignStrategyCandidates, CarouselPlan, CreativeBrief, ResearchInsightItem, ResearchResult, SlidePlan
from app.schemas.claims_audit import CandidateClaimExtractionResult
from app.schemas.creative_director import CreativeDirection, MasterCampaignConcept, PlatformAdaptation, VideoConcept
from app.schemas.product_facts import VerifiedProductFactsOut
from app.schemas.qa import CreativeCritiqueResult, LanguageQAResult, RevisedCopy, VideoQAResult
from app.services.claims_audit import audit_text_fields, collect_carousel_slide_fields, collect_video_concept_fields
from app.services.creative.renderer import PlaywrightRenderer
from app.services.orchestrator import AutopilotConfig, get_platform_campaign_variants, run_copy_stage, run_strategy_stage, run_visuals_stage
from app.services.qa_engine import run_qa_stage


def _verified(**overrides) -> VerifiedProductFactsOut:
    """A minimal, honestly-sparse `VerifiedProductFactsOut` — every field
    empty/zero except what a test explicitly overrides, matching the real
    Hanna fixture the spec names (Melano CC Essence: only country_of_origin
    confirmed).
    """
    base = dict(
        product_id="p1", product_name="Melano CC Essence", category="Skincare", brand_name="Hanna Japan",
        owner_notes="", verified_description="", verified_ingredients=[], verified_features=[],
        verified_benefits=[], verified_usage="", verified_size="", verified_variant="", verified_price="",
        verified_availability="", verified_country_of_origin="Japan", verified_claims=[], prohibited_claims=[],
        source_asset_ids=[], source_references=[], confidence=0.4, missing_information=[], provenance="owner",
    )
    base.update(overrides)
    return VerifiedProductFactsOut(**base)


class _FakeBrand:
    """A plain stand-in for the ORM `Brand` — `audit_text_fields`/
    `_brand_evidence_text` only ever touch these attributes.
    """

    def __init__(
        self, *, voice="", disclaimers=None, preferred_ctas=None, disallowed_terms=None, target_audiences=None,
        target_countries=None, creative_instructions="",
    ):
        self.voice = voice
        self.disclaimers = disclaimers or []
        self.preferred_ctas = preferred_ctas or []
        self.disallowed_terms = disallowed_terms or []
        self.target_audiences = target_audiences or []
        self.target_countries = target_countries or []
        self.creative_instructions = creative_instructions


# ---------------------------------------------------------------------------
# Tests A-E: each REQUIREMENT-3 claim category the deterministic layer 1
# detector must catch, run through the real evidence-comparison pipeline.
# ---------------------------------------------------------------------------

def test_a_unsupported_benefit_claim_caught():
    verified = _verified()  # no verified_benefits on file at all
    result = audit_text_fields({"copy.supporting_copy": "Reduces acne marks overnight."}, verified, _FakeBrand())
    assert not result.passed
    assert any(f.claim_category == "product_benefit" and f.evidence_status == "UNSUPPORTED" for f in result.findings)


def test_b_bestseller_ranking_claim_caught():
    verified = _verified()
    result = audit_text_fields({"copy.headline": "The #1 serum in Japan"}, verified, _FakeBrand())
    assert not result.passed
    assert any(f.claim_category == "ranking_bestseller" for f in result.unsupported_findings)


def test_c_numerical_social_proof_caught():
    verified = _verified()
    result = audit_text_fields(
        {"copy.supporting_copy": "Loved by 10,000 customers across Brazil."}, verified, _FakeBrand(),
    )
    assert not result.passed
    assert any(f.claim_category == "social_proof_count" for f in result.unsupported_findings)


def test_d_vip_restock_gift_claims_caught():
    verified = _verified()
    fields = {
        "carousel.slide_1.badge_text": "VIP members get early access",
        "carousel.slide_2.callout_value": "Free surprise gift with every order",
        "carousel.slide_3.callout_label": "Restock guarantee for loyal shoppers",
    }
    result = audit_text_fields(fields, verified, _FakeBrand())
    categories = {f.claim_category for f in result.unsupported_findings}
    assert "vip_member_perks" in categories
    assert "early_priority_access" in categories
    assert "restock_promise" in categories
    assert "free_gift" in categories
    assert not result.passed


def test_e_unverified_ingredient_and_percentage_caught():
    verified = _verified()  # verified_ingredients is empty — nothing confirmed
    result = audit_text_fields(
        {"copy.supporting_copy": "Formulated with retinol for a 20% brighter glow."}, verified, _FakeBrand(),
    )
    categories = {f.claim_category for f in result.unsupported_findings}
    assert "percentage_or_ingredient" in categories
    assert not result.passed


# ---------------------------------------------------------------------------
# Tests F-H: the "must not over-flag" side of the same gate — real evidence
# (class A/B) is honored, and safe creative language passes untouched even
# with sparse facts on file (REQUIREMENT 6's own sparse-fixture scenario).
# ---------------------------------------------------------------------------

def test_f_actually_verified_claim_allowed():
    verified = _verified(verified_ingredients=["vitamin c"], verified_benefits=["brightens skin tone"])
    result = audit_text_fields(
        {"copy.supporting_copy": "Formulated with vitamin C to help brighten skin tone."}, verified, _FakeBrand(),
    )
    assert result.passed
    assert all(f.evidence_status == "SUPPORTED" for f in result.findings)


def test_g_owner_confirmed_business_fact_allowed():
    brand = _FakeBrand(creative_instructions="We proudly offer a free shipping guarantee to Brazil on all orders.")
    result = audit_text_fields(
        {"copy.supporting_copy": "We proudly offer a free shipping guarantee to Brazil."}, _verified(), brand,
    )
    assert result.passed
    assert result.findings and result.findings[0].allowed_source == "owner_confirmed_brand_facts"


def test_h_neutral_creative_language_with_sparse_facts_allowed():
    # Only country_of_origin is verified — the real Hanna/Melano CC fixture
    # this repair's spec names. Generic, non-factual creative copy must still
    # pass cleanly rather than the gate being a brittle "flag everything"
    # blacklist.
    verified = _verified(confidence=0.2, missing_information=["verified_benefits", "verified_ingredients"])
    fields = {
        "copy.hook": "Your everyday glow, made simple.",
        "copy.headline": "Brighten your routine",
        "copy.supporting_copy": "A little ritual from Japan, made for every day.",
        "copy.cta": "Shop now",
    }
    result = audit_text_fields(fields, verified, _FakeBrand())
    assert result.passed
    assert result.findings == []


# ---------------------------------------------------------------------------
# Tests I-J: REQUIREMENT 1's carousel and VideoConcept field coverage.
# ---------------------------------------------------------------------------

def test_i_carousel_badge_callout_bottom_feature_claims_inspected():
    slides = [
        SimpleNamespace(
            slide_number=1, badge_text="#1 bestseller", callout_label="Why it works", callout_value="Clinically proven results",
            bottom_features=["Free gift with every order"], trust_badges=["VIP members only"],
            features=[{"title": "Reduces wrinkles", "subtitle": "Visible in days"}],
            eyebrow="", headline="", body="", intro="",
        ),
    ]
    fields = collect_carousel_slide_fields(slides)
    assert fields["carousel.slide_1.badge_text"] == "#1 bestseller"
    assert fields["carousel.slide_1.callout_value"] == "Clinically proven results"
    assert "Free gift" in fields["carousel.slide_1.bottom_features"]
    assert "VIP members only" in fields["carousel.slide_1.trust_badges"]
    assert fields["carousel.slide_1.feature_0.title"] == "Reduces wrinkles"

    result = audit_text_fields(fields, _verified(), _FakeBrand())
    categories = {f.claim_category for f in result.unsupported_findings}
    assert "ranking_bestseller" in categories
    assert "clinical_scientific" in categories
    assert "free_gift" in categories
    assert "vip_member_perks" in categories
    assert "product_benefit" in categories  # "Reduces wrinkles" feature title
    assert not result.passed


def test_j_video_concept_on_screen_and_script_claims_inspected():
    video_concept = {
        "hook": "Everyone's talking about this",
        "script": "This #1 serum already has 50,000 customers.",
        "on_screen_text": ["VIP early access starts today", "Free gift while supplies last"],
        "caption": "Straight from Japan.",
        "shot_list": ["Hero shot"], "timing": "15s", "visual_direction": "warm studio light",
    }
    fields = collect_video_concept_fields(video_concept)
    assert "video_concept.script" in fields
    assert "video_concept.on_screen_text" in fields
    assert "video_concept.shot_list" not in fields  # production directive, not visible text

    result = audit_text_fields(fields, _verified(), _FakeBrand())
    categories = {f.claim_category for f in result.unsupported_findings}
    assert "ranking_bestseller" in categories
    assert "social_proof_count" in categories
    assert "early_priority_access" in categories
    assert "free_gift" in categories or "availability_scarcity" in categories
    assert not result.passed


# ---------------------------------------------------------------------------
# Test K: full pipeline — an unsupported claim reaching real generated copy
# is a genuine hard fail and prevents PASS end-to-end.
# ---------------------------------------------------------------------------

class _FakeClaimQAProvider:
    """Mirrors `test_build3_qa_engine.py::FakeQAProvider` (this codebase's own
    established full-pipeline fake) but returns copy carrying a deliberately
    UNSUPPORTED claim, so this test exercises the real `run_qa_stage" ->
    `services/claims_audit.py` wiring rather than re-testing `claims_audit.py`
    in isolation again.
    """

    def __init__(self):
        self.claims_extraction_calls = 0

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
                hook="Your skin deserves this", headline="The #1 serum in Japan",
                supporting_copy="Loved by 10,000 customers across Brazil.", cta="Shop now",
                caption="Straight from Japan.", hashtags=["#skincare"],
                alt_text="Product bottle on a gradient background",
            )
        if schema is CarouselPlan:
            return CarouselPlan(
                slides=[
                    SlidePlan(slide_number=1, purpose="hero", headline="Slide one", body="Body one",
                              cta="Shop now", visual_brief="Hero shot"),
                ],
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
        if schema is LanguageQAResult:
            return LanguageQAResult(language_naturalness=95, hard_fails=[])
        if schema is RevisedCopy:
            return RevisedCopy(headline="Revised headline", body="Revised body copy.", cta="Shop now")
        if schema is VideoQAResult:
            return VideoQAResult(
                hook_strength=90, script_coherence=90, shot_list_completeness=90, timing_score=90,
                on_screen_text_suitability=90, platform_fit=90, language_naturalness=90, factual_accuracy=90,
                brand_alignment=90, cta_effectiveness=90,
            )
        if schema is CreativeDirection:
            return CreativeDirection(
                concept_name="Everyday Ritual", background_concept="Soft warm gradient studio backdrop",
                scene_generation_prompt="Soft warm gradient studio backdrop, no text, no logos, no products.",
            )
        if schema is VideoConcept:
            return VideoConcept(
                hook="Your 5-step routine starts here", script="Open, walk through, close.",
                shot_list=["Hero shot", "Routine steps", "Result"], caption="Everything you need.",
            )
        if schema is CandidateClaimExtractionResult:
            self.claims_extraction_calls += 1
            return CandidateClaimExtractionResult(claims=[])
        raise AssertionError(f"Unexpected schema requested: {schema}")

    async def critique_creative(self, *, image_paths, source_image_path, context, model):
        return CreativeCritiqueResult(
            overall_quality=92, brand_alignment=85, product_fidelity=85, product_prominence=85, composition=85,
            typography=85, readability=85, color_harmony=85, hierarchy=85, clutter=85, copy_visual_fit=85,
            cta_visibility=85, mobile_readability=85, originality=85, professional_ad_quality=85,
            carousel_consistency=85, platform_fit=88, language_naturalness=88, hard_fails=[], rationale="fake",
        )

    async def vision_describe(self, *, image_path, prompt, model):
        return ""

    async def research(self, query, *, model):
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
        from app.schemas.ai import ProductFidelityCheck
        return ProductFidelityCheck(overall_verdict="PASS", reasoning="Matches.")


def _config(tmp_path, **overrides):
    return AutopilotConfig(
        campaign_model="gpt-5.1", research_model="gpt-5.1", trend_ttl_hours=24, category_ttl_hours=168,
        too_similar_threshold=75, acceptable_threshold=45, output_root=tmp_path / "output", **overrides,
    )


def _make_brand_category_product_asset(session, tmp_path):
    from app.services.seed import seed_strategy_library
    seed_strategy_library(session)

    brand = Brand(name="Hanna", slug=f"hanna-{uuid.uuid4().hex[:8]}", colors={"primary": "#f2ede3"}, campaign_rules={"verified_operational_strategy_keys": list(_LEGACY_VERIFIED_OPERATIONAL_STRATEGY_KEYS)})
    session.add(brand)
    session.commit()
    category = Category(brand_id=brand.id, name="Skincare", slug="skincare")
    session.add(category)
    session.commit()
    product = Product(brand_id=brand.id, category_id=category.id, name="Melano CC Essence", slug="melano-cc-essence")
    session.add(product)
    session.commit()
    # Sparse-but-real VerifiedProductFact row — only country_of_origin
    # confirmed, matching the exact fixture REQUIREMENT 6 names.
    session.add(VerifiedProductFact(product_id=product.id, verified_country_of_origin="Japan", confidence=0.4))
    session.commit()
    img_path = tmp_path / "source.jpg"
    Image.new("RGB", (800, 800), (200, 180, 190)).save(img_path)
    asset = Asset(
        brand_id=brand.id, category_id=category.id, product_id=product.id, absolute_path=str(img_path),
        relative_path="skincare/source.jpg", filename="source.jpg", extension=".jpg", sha256="src-sha", width=800,
        height=800,
    )
    session.add(asset)
    session.commit()
    return brand, category, product


async def test_k_unsupported_claim_prevents_pass(
    temp_db,
    tmp_path,
):
    import pytest
    """BUILD 6R strengthened REQUIREMENT 5:

    Unsupported factual claims must now fail CLOSED during Copy, before
    Visuals, image generation, vision QA, or a PlatformCampaignVariant can
    ever be produced.

    The fake provider deliberately emits both an unsupported ranking claim
    ("#1") and unsupported numerical social proof ("10,000 customers").
    With sparse VerifiedProductFacts, `run_copy_stage` must raise the
    deterministic pre-visual grounding error and leave the campaign FAILED.
    """

    from app.services.orchestrator import (
        PreVisualClaimGroundingError,
    )

    session = temp_db.SessionLocal()
    renderer = PlaywrightRenderer()

    try:
        provider = _FakeClaimQAProvider()

        config = _config(
            tmp_path,
            qa_max_retries=0,
            enable_qa_stage=True,
        )

        (
            brand,
            category,
            product,
        ) = _make_brand_category_product_asset(
            session,
            tmp_path,
        )

        campaign = Campaign(
            display_id=(
                f"HANNA-SKIN-"
                f"{uuid.uuid4().hex[:8]}"
            ),
            brand_id=brand.id,
            category_id=category.id,
            product_id=product.id,
            objective="awareness",
            status="IDEA",
            languages=["pt-BR"],
            target_platforms=["instagram"],
        )

        session.add(
            campaign
        )

        session.commit()

        campaign_id = campaign.id

        await run_strategy_stage(
            session,
            campaign_id=campaign_id,
            ai_provider=provider,
            research_provider=provider,
            config=config,
        )

        with pytest.raises(
            PreVisualClaimGroundingError,
            match="PREVISUAL_UNSUPPORTED_CLAIM",
        ) as exc_info:
            await run_copy_stage(
                session,
                campaign_id=campaign_id,
                ai_provider=provider,
                config=config,
            )

        error_text = str(
            exc_info.value
        )

        assert (
            "UNSUPPORTED_CLAIM:"
            in error_text
        )

        assert (
            "#1"
            in error_text
            or "10,000 customers"
            in error_text
        )

        session.expire_all()

        persisted = session.get(
            Campaign,
            campaign_id,
        )

        assert persisted is not None
        assert persisted.status == "FAILED"

        # Critical Build 6R contract:
        # the old test used to continue into Visuals and expect NEEDS_REVIEW.
        # It must no longer do so. Reaching this point proves Copy itself
        # terminated the run before render/visual QA.
        assert persisted.status != "COPY_READY"
        assert persisted.status != "GENERATING"
        assert persisted.status != "REVIEW"

    finally:
        try:
            await renderer.close()
        except Exception:
            pass

        session.close()


