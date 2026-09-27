"""Build 4 (HUMAN APPROVAL + PLATFORM/LANGUAGE FEEDBACK LEARNING) — the
required minimum test coverage named by the spec's own "BUILD 4 TESTS" list
PLUS the "BUILD 3 CARRY-FORWARD REQUIREMENTS" section's own numbered test
list (10 items). Each test's docstring names which item(s) it covers.

 BUILD 4 TESTS:
  1. Feedback persists.
  2. Platform is recorded.
  3. Language is recorded.
  4. PT-BR feedback is selectively retrievable.
  5. English feedback is selectively retrievable.
  6. Platform-specific feedback is selective.
  7. Positive examples work.
  8. Negative patterns work.
  9. Novelty remains functional.

 CARRY-FORWARD REQUIREMENT 10's OWN TEST LIST:
  1. Feedback on one platform/language variant does not mutate sibling variants.
  2. Human review status and QA status are independent.
  3. Revision preserves prior reviewed version/history.
  4. Owner feedback references the exact reviewed asset/version.
  5. Feedback selector has a bounded result count.
  6. Feedback never mutates VerifiedProductFacts.
  7. Approved examples influence generation without being copied verbatim.
  8. Script/storyboard feedback remains distinct from rendered-asset feedback.
  9. Historical QA evidence remains unchanged after later human review.
 10. All existing 281 tests remain green — verified by the full suite, not here.

Most tests below build a campaign + `PlatformCampaignVariant` row(s) directly
(no full Strategy->Copy->Visuals pipeline run) since `record_review_feedback`/
`select_feedback_examples` operate on already-persisted state — same "fast,
fully deterministic unit test" discipline `test_build3_qa_engine.py` uses for
its own Part A/D tests. The one exception (`test_revision_preserves_...`)
needs a genuinely rendered variant, since it exercises `apply_requested_
revision`'s reuse of Build 3's real render pipeline.
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


import json
import uuid

import pytest
from PIL import Image

from app.data.feedback_reasons import FEEDBACK_REASON_CODES
from app.models import (
    Brand, Campaign, CampaignOutput, Category, PlatformCampaignVariant, Product, ReviewFeedback,
    VerifiedProductFact,
)
from app.schemas.ai import CampaignCopy, CampaignStrategy, CampaignStrategyCandidates, CarouselPlan, CreativeBrief, \
    ResearchInsightItem, ResearchResult, SlidePlan
from app.schemas.creative_director import MasterCampaignConcept, PlatformAdaptation, VideoConcept
from app.schemas.qa import RevisedCopy
from app.services.creative.renderer import PlaywrightRenderer
from app.services.feedback_selector import format_feedback_for_prompt, select_feedback_examples
from app.services.orchestrator import AutopilotConfig, get_platform_campaign_variants, run_copy_stage, run_strategy_stage, run_visuals_stage
from app.services.review_engine import apply_requested_revision, record_review_feedback


# ---------------------------------------------------------------------------
# Shared fixtures/helpers (duplicated rather than imported across test files —
# this codebase's own stated convention, see test_build3_qa_engine.py).
# ---------------------------------------------------------------------------

@pytest.fixture()
async def variant_renderer():
    renderer = PlaywrightRenderer()
    yield renderer
    await renderer.close()


def _make_review_test_campaign(session, tmp_path):
    """One brand/category, a campaign targeting two platforms x two languages,
    and two already-"rendered" `PlatformCampaignVariant` rows (instagram/pt-BR,
    instagram/en) with distinct QA state — enough for every feedback-recording
    and selector test below without needing a real pipeline run.
    """
    from app.services.seed import seed_strategy_library
    seed_strategy_library(session)

    brand = Brand(name="Hanna", slug=f"hanna-{uuid.uuid4().hex[:8]}", colors={"primary": "#f2ede3"}, campaign_rules={"verified_operational_strategy_keys": list(_LEGACY_VERIFIED_OPERATIONAL_STRATEGY_KEYS)})
    session.add(brand)
    session.commit()
    category = Category(brand_id=brand.id, name="Skincare", slug="skincare")
    session.add(category)
    session.commit()
    campaign = Campaign(
        display_id=f"HANNA-SKIN-{uuid.uuid4().hex[:8]}", brand_id=brand.id, category_id=category.id,
        objective="awareness", status="REVIEW", languages=["pt-BR", "en"],
        target_platforms=["instagram", "pinterest"],
    )
    session.add(campaign)
    session.commit()

    img_path = tmp_path / "slide.png"
    Image.new("RGB", (1080, 1080), (10, 50, 200)).save(img_path)

    v_ig_ptbr = PlatformCampaignVariant(
        campaign_id=campaign.id, target_platform="instagram", language="pt-BR", content_type="feed_post",
        render_format_key="instagram_square", status="RENDERED", slide_asset_paths=[str(img_path)],
        qa_status="PASS", qa_scores={"overall": 90}, qa_attempts=1, qa_evidence_paths=["evidence-1.json"],
        qa_versions={"qa_prompt_version": "1.0.0"},
    )
    v_ig_en = PlatformCampaignVariant(
        campaign_id=campaign.id, target_platform="instagram", language="en", content_type="feed_post",
        render_format_key="instagram_square", status="RENDERED", slide_asset_paths=[str(img_path)],
        qa_status="PASS", qa_scores={"overall": 88}, qa_attempts=1,
    )
    session.add_all([v_ig_ptbr, v_ig_en])
    session.commit()
    return brand, category, campaign, v_ig_ptbr, v_ig_en


# ---------------------------------------------------------------------------
# BUILD 4 TESTS 1-3: feedback persists, with platform + language recorded.
# ---------------------------------------------------------------------------

def test_feedback_persists_with_platform_and_language(temp_db, tmp_path):
    session = temp_db.SessionLocal()
    brand, category, campaign, v_ig_ptbr, v_ig_en = _make_review_test_campaign(session, tmp_path)

    fb = record_review_feedback(
        session, campaign=campaign, variant=v_ig_ptbr, level="PLATFORM_VARIANT", action="REJECT",
        reason_code="too_much_text", reason_text="Way too much copy on slide 1.",
    )
    assert fb.id is not None
    assert fb.platform == "instagram"
    assert fb.language == "pt-BR"

    reloaded = session.query(ReviewFeedback).filter(ReviewFeedback.id == fb.id).one()
    assert reloaded.platform == "instagram"
    assert reloaded.language == "pt-BR"
    assert reloaded.reason_code == "too_much_text"
    assert reloaded.reason_text == "Way too much copy on slide 1."
    session.close()


def test_campaign_level_feedback_has_no_platform_or_language(temp_db, tmp_path):
    """A `level="CAMPAIGN"` action spans every platform/language at once, so
    it deliberately records neither — never a fabricated single value.
    """
    session = temp_db.SessionLocal()
    brand, category, campaign, v_ig_ptbr, v_ig_en = _make_review_test_campaign(session, tmp_path)

    fb = record_review_feedback(session, campaign=campaign, variant=None, level="CAMPAIGN", action="APPROVE")
    assert fb.platform == ""
    assert fb.language == ""
    session.refresh(campaign)
    assert campaign.human_review_status == "APPROVED"
    session.close()


# ---------------------------------------------------------------------------
# Carry-forward test 1: feedback on one variant never mutates a sibling.
# ---------------------------------------------------------------------------

def test_feedback_on_one_variant_does_not_mutate_sibling_variants(temp_db, tmp_path):
    session = temp_db.SessionLocal()
    brand, category, campaign, v_ig_ptbr, v_ig_en = _make_review_test_campaign(session, tmp_path)

    record_review_feedback(
        session, campaign=campaign, variant=v_ig_ptbr, level="PLATFORM_VARIANT", action="REJECT",
        reason_code="too_much_text",
    )
    session.refresh(v_ig_ptbr)
    session.refresh(v_ig_en)
    session.refresh(campaign)
    assert v_ig_ptbr.human_review_status == "REJECTED"
    assert v_ig_en.human_review_status == "PENDING"  # untouched sibling
    assert campaign.human_review_status == "PENDING"  # untouched parent — level was PLATFORM_VARIANT, not CAMPAIGN

    # And the ONE ReviewFeedback row that exists references only v_ig_ptbr.
    rows = session.query(ReviewFeedback).filter(ReviewFeedback.campaign_id == campaign.id).all()
    assert len(rows) == 1
    assert rows[0].platform_campaign_variant_id == v_ig_ptbr.id
    session.close()


# ---------------------------------------------------------------------------
# Carry-forward test 2: human_review_status and qa_status are independent —
# a variant can honestly be QA_PASS + OWNER_REJECTED.
# ---------------------------------------------------------------------------

def test_human_review_status_independent_of_qa_status(temp_db, tmp_path):
    session = temp_db.SessionLocal()
    brand, category, campaign, v_ig_ptbr, v_ig_en = _make_review_test_campaign(session, tmp_path)
    assert v_ig_ptbr.qa_status == "PASS"

    record_review_feedback(
        session, campaign=campaign, variant=v_ig_ptbr, level="PLATFORM_VARIANT", action="REJECT",
        reason_code="boring_concept",
    )
    session.refresh(v_ig_ptbr)
    assert v_ig_ptbr.qa_status == "PASS"  # untouched — QA_PASS + OWNER_REJECTED is a valid, real state
    assert v_ig_ptbr.human_review_status == "REJECTED"
    session.close()


# ---------------------------------------------------------------------------
# Carry-forward tests 4 + 9: feedback references the EXACT reviewed asset/
# version, and that snapshot stays frozen even after a later QA rerun
# mutates the live variant row (never made ambiguous by history).
# ---------------------------------------------------------------------------

def test_owner_feedback_references_exact_reviewed_asset_and_qa_version(temp_db, tmp_path):
    session = temp_db.SessionLocal()
    brand, category, campaign, v_ig_ptbr, v_ig_en = _make_review_test_campaign(session, tmp_path)

    fb = record_review_feedback(
        session, campaign=campaign, variant=v_ig_ptbr, level="PLATFORM_VARIANT", action="REJECT",
        reason_code="wrong_colors",
    )
    assert fb.reviewed_slide_asset_paths == v_ig_ptbr.slide_asset_paths
    assert fb.reviewed_qa_status == "PASS"
    assert fb.reviewed_qa_scores == {"overall": 90}
    assert fb.reviewed_qa_attempts == 1
    assert fb.reviewed_qa_evidence_paths == ["evidence-1.json"]

    # A later QA rerun mutates the LIVE variant row in place (exactly what
    # Build 3's own revision mechanism already does)...
    v_ig_ptbr.qa_status = "NEEDS_REVIEW"
    v_ig_ptbr.qa_scores = {"overall": 40}
    v_ig_ptbr.qa_attempts = 2
    session.commit()

    # ...but the historical feedback's own frozen snapshot never changes —
    # carry-forward requirement 9: "historical QA evidence remains unchanged
    # after later human review" (and, symmetrically here, after a later QA
    # rerun too — nothing about reviewing something rewrites the past).
    reloaded_fb = session.get(ReviewFeedback, fb.id)
    assert reloaded_fb.reviewed_qa_status == "PASS"
    assert reloaded_fb.reviewed_qa_scores == {"overall": 90}
    assert reloaded_fb.reviewed_qa_attempts == 1
    session.close()


def test_approve_and_reject_never_mutate_qa_state(temp_db, tmp_path):
    """Carry-forward requirement 9 (API-level phrasing): a plain APPROVE/
    REJECT action must leave `qa_status`/`qa_scores`/`qa_attempts`/evidence
    exactly as they were — only `apply_requested_revision` (a REAL re-render)
    is ever allowed to change them.
    """
    session = temp_db.SessionLocal()
    brand, category, campaign, v_ig_ptbr, v_ig_en = _make_review_test_campaign(session, tmp_path)
    original_scores = dict(v_ig_ptbr.qa_scores)
    original_attempts = v_ig_ptbr.qa_attempts
    original_evidence = list(v_ig_ptbr.qa_evidence_paths)

    record_review_feedback(session, campaign=campaign, variant=v_ig_ptbr, level="PLATFORM_VARIANT", action="APPROVE")
    session.refresh(v_ig_ptbr)
    assert v_ig_ptbr.qa_scores == original_scores
    assert v_ig_ptbr.qa_attempts == original_attempts
    assert v_ig_ptbr.qa_evidence_paths == original_evidence
    assert v_ig_ptbr.qa_status == "PASS"
    session.close()


# ---------------------------------------------------------------------------
# Carry-forward test 6: feedback never becomes a VerifiedProductFact.
# ---------------------------------------------------------------------------

def test_feedback_never_mutates_verified_product_facts(temp_db, tmp_path):
    session = temp_db.SessionLocal()
    brand, category, campaign, v_ig_ptbr, v_ig_en = _make_review_test_campaign(session, tmp_path)
    product = Product(brand_id=brand.id, category_id=category.id, name="Rice Serum", slug="rice-serum")
    session.add(product)
    session.commit()
    fact = VerifiedProductFact(product_id=product.id, verified_description="Contains rice bran extract.")
    session.add(fact)
    session.commit()
    campaign.product_id = product.id
    session.commit()

    record_review_feedback(
        session, campaign=campaign, variant=v_ig_ptbr, level="PLATFORM_VARIANT", action="REJECT",
        reason_code="inaccurate_claim",
        reason_text="This copy claims it cures acne — that's not a verified fact, never use it again.",
    )

    facts_after = session.query(VerifiedProductFact).filter(VerifiedProductFact.product_id == product.id).all()
    assert len(facts_after) == 1
    assert facts_after[0].verified_description == "Contains rice bran extract."  # untouched
    assert "cures acne" not in facts_after[0].verified_description
    session.close()


# ---------------------------------------------------------------------------
# Carry-forward test 8 + Build 4's own "video-concept feedback must remain
# format-aware": script-only feedback uses script field refs, never a
# rendered-slide ref, and is rejected if it tries to.
# ---------------------------------------------------------------------------

def test_script_only_variant_feedback_stays_distinct_from_rendered_asset_feedback(temp_db, tmp_path):
    session = temp_db.SessionLocal()
    brand, category, campaign, v_ig_ptbr, v_ig_en = _make_review_test_campaign(session, tmp_path)
    v_tiktok = PlatformCampaignVariant(
        campaign_id=campaign.id, target_platform="tiktok", language="pt-BR", content_type="short_video",
        render_format_key="", status="SCRIPT_ONLY", slide_asset_paths=[],
        video_concept=VideoConcept(hook="Day in the life", script="Open, routine, result.").model_dump(),
    )
    session.add(v_tiktok)
    session.commit()

    # A script-field reference is valid for a script-only variant...
    fb = record_review_feedback(
        session, campaign=campaign, variant=v_tiktok, level="ASSET", asset_ref="hook", action="REQUEST_REVISION",
        reason_code="content_unsuitable_for_tiktok",
    )
    assert fb.asset_ref == "hook"
    assert fb.reviewed_video_concept["hook"] == "Day in the life"
    assert fb.reviewed_slide_asset_paths == []  # never implies a rendered file exists

    # ...but a rendered-slide-style reference is rejected outright for a
    # script-only variant — the API must never expose a control implying a
    # rendered video file exists (carry-forward requirement 8).
    with pytest.raises(ValueError, match="script-only"):
        record_review_feedback(
            session, campaign=campaign, variant=v_tiktok, level="ASSET", asset_ref="slide-1", action="REJECT",
        )
    session.close()


async def test_script_only_revision_updates_only_the_video_concept(temp_db, tmp_path):
    """`apply_requested_revision` on a SCRIPT_ONLY variant only ever revises
    the structured script (`qa_engine.revise_video_concept`) — never attempts
    a render, and `slide_asset_paths` stays empty throughout.
    """
    session = temp_db.SessionLocal()
    brand, category, campaign, v_ig_ptbr, v_ig_en = _make_review_test_campaign(session, tmp_path)
    v_tiktok = PlatformCampaignVariant(
        campaign_id=campaign.id, target_platform="tiktok", language="pt-BR", content_type="short_video",
        render_format_key="", status="SCRIPT_ONLY", slide_asset_paths=[],
        video_concept=VideoConcept(hook="Day in the life", script="Open, routine, result.").model_dump(),
    )
    session.add(v_tiktok)
    session.commit()

    fb = record_review_feedback(
        session, campaign=campaign, variant=v_tiktok, level="ASSET", asset_ref="hook", action="REQUEST_REVISION",
        reason_code="content_unsuitable_for_tiktok",
    )
    config = AutopilotConfig(
        campaign_model="gpt-5.1", research_model="gpt-5.1", trend_ttl_hours=24, category_ttl_hours=168,
        too_similar_threshold=75, acceptable_threshold=45, output_root=tmp_path / "output",
    )
    renderer = PlaywrightRenderer()
    try:
        updated = await apply_requested_revision(
            session, campaign=campaign, variant=v_tiktok, feedback=fb, config=config, renderer=renderer,
            ai_provider=None,  # no AI provider available -> keeps the previous script unchanged, never fabricated
        )
    finally:
        await renderer.close()
    assert updated.slide_asset_paths == []
    assert updated.status == "SCRIPT_ONLY"
    assert updated.human_review_status == "PENDING"  # reset for a fresh owner look
    session.close()


# ---------------------------------------------------------------------------
# BUILD 4 TESTS 4-6: selective, bounded retrieval — the spec's own worked
# example ("repeated Instagram PT-BR 'Too much text' must NOT blindly affect
# Pinterest English").
# ---------------------------------------------------------------------------

def test_feedback_selector_is_selective_by_platform_and_language(temp_db, tmp_path):
    session = temp_db.SessionLocal()
    brand, category, campaign, v_ig_ptbr, v_ig_en = _make_review_test_campaign(session, tmp_path)
    v_pin_en = PlatformCampaignVariant(
        campaign_id=campaign.id, target_platform="pinterest", language="en", content_type="pin",
        render_format_key="pinterest_pin", status="RENDERED", slide_asset_paths=[],
    )
    session.add(v_pin_en)
    session.commit()

    record_review_feedback(
        session, campaign=campaign, variant=v_ig_ptbr, level="PLATFORM_VARIANT", action="REJECT",
        reason_code="too_much_text",
    )
    record_review_feedback(
        session, campaign=campaign, variant=v_ig_en, level="PLATFORM_VARIANT", action="REJECT",
        reason_code="cta_weak",
    )

    # Test 4: PT-BR feedback is selectively retrievable...
    ptbr_selection = select_feedback_examples(session, brand_id=brand.id, platform="instagram", language="pt-BR")
    assert any(fb.reason_code == "too_much_text" for fb in ptbr_selection.negative)
    assert all(fb.language != "en" for fb in ptbr_selection.negative)

    # Test 5: ...and English feedback is independently, selectively retrievable.
    en_selection = select_feedback_examples(session, brand_id=brand.id, platform="instagram", language="en")
    assert any(fb.reason_code == "cta_weak" for fb in en_selection.negative)
    assert all(fb.language != "pt-BR" for fb in en_selection.negative)

    # Test 6 + the spec's own worked example: Pinterest/English must NOT see
    # feedback scoped to a different platform (Instagram).
    pinterest_selection = select_feedback_examples(session, brand_id=brand.id, platform="pinterest", language="en")
    assert pinterest_selection.negative == []
    session.close()


# ---------------------------------------------------------------------------
# BUILD 4 TEST 8 + carry-forward test 6's negative-example half: negative
# patterns are retrievable and correctly characterized.
# ---------------------------------------------------------------------------

def test_negative_patterns_work(temp_db, tmp_path):
    session = temp_db.SessionLocal()
    brand, category, campaign, v_ig_ptbr, v_ig_en = _make_review_test_campaign(session, tmp_path)
    record_review_feedback(
        session, campaign=campaign, variant=v_ig_ptbr, level="PLATFORM_VARIANT", action="REJECT",
        reason_code="too_much_text",
    )
    selection = select_feedback_examples(session, brand_id=brand.id, platform="instagram", language="pt-BR")
    assert len(selection.negative) == 1
    prompt_text = format_feedback_for_prompt(selection)
    assert "Too much text" in prompt_text
    assert "REJECTED" in prompt_text or "revise" in prompt_text.lower() or "flagged" in prompt_text.lower()
    session.close()


# ---------------------------------------------------------------------------
# BUILD 4 TEST 7 + carry-forward test 7: positive examples work AND never
# leak the reviewed variant's literal headline/body text into the prompt.
# ---------------------------------------------------------------------------

def test_positive_examples_work_without_verbatim_text(temp_db, tmp_path):
    session = temp_db.SessionLocal()
    brand, category, campaign, v_ig_ptbr, v_ig_en = _make_review_test_campaign(session, tmp_path)

    # Persist a distinctive real copy stage JSON so the review's snapshot
    # actually captures literal text — the test then proves that text never
    # reaches the formatted prompt string.
    distinctive_headline = "Unlock Your Radiant Glow Ritual Today"
    copy_path = tmp_path / "copy.json"
    copy_path.write_text(json.dumps({
        "primary_language": "pt-BR",
        "languages": {"pt-BR": {"headline": distinctive_headline, "body": "Secret body copy.", "cta": "Shop now"}},
    }))
    session.add(CampaignOutput(campaign_id=campaign.id, kind="copy", file_path=str(copy_path)))
    session.commit()

    record_review_feedback(session, campaign=campaign, variant=v_ig_ptbr, level="PLATFORM_VARIANT", action="APPROVE")

    selection = select_feedback_examples(session, brand_id=brand.id, platform="instagram", language="pt-BR")
    assert len(selection.positive) == 1
    assert selection.positive[0].reviewed_copy_snapshot["headline"] == distinctive_headline  # captured...

    prompt_text = format_feedback_for_prompt(selection)
    assert "instagram/pt-BR" in prompt_text
    assert distinctive_headline not in prompt_text  # ...but never reproduced into the grounding text (no cloning)
    assert "Secret body copy." not in prompt_text
    session.close()


# ---------------------------------------------------------------------------
# Carry-forward test 5: the selector's result count is bounded.
# ---------------------------------------------------------------------------

def test_feedback_selector_result_count_is_bounded(temp_db, tmp_path):
    session = temp_db.SessionLocal()
    brand, category, campaign, v_ig_ptbr, v_ig_en = _make_review_test_campaign(session, tmp_path)
    reasons = [c for c in FEEDBACK_REASON_CODES if c != "other"][:8]
    for code in reasons:
        record_review_feedback(
            session, campaign=campaign, variant=v_ig_ptbr, level="PLATFORM_VARIANT", action="REJECT",
            reason_code=code,
        )
    assert len(reasons) > 3  # sanity: more candidates exist than the limit below

    selection = select_feedback_examples(session, brand_id=brand.id, platform="instagram", language="pt-BR", limit=3)
    assert len(selection.negative) <= 3
    session.close()


# ---------------------------------------------------------------------------
# BUILD 4 TEST 9: novelty stays functional with feedback rows present — Build
# 4 never touches CampaignFingerprint/_compute_novelty/too_similar_threshold.
# ---------------------------------------------------------------------------

class _NoveltyFakeProvider:
    """Deliberately reproduces the exact same strategy candidate every call,
    so a second `run_strategy_stage` for a fresh campaign is a genuine repeat
    of the first — the same shape `test_orchestrator.py::
    test_all_candidates_rejected_as_exact_repeats` already exercises, just
    with `ReviewFeedback` rows present in the database this time.
    """

    async def generate_structured(self, *, system, user, schema, model):
        if schema is CampaignStrategyCandidates:
            return CampaignStrategyCandidates(candidates=[
                CampaignStrategy(
                    objective="awareness", audience="A", funnel_stage="tofu", insight="Same insight",
                    angle="Same angle", key_message="Same message", reason_this_should_work="reason",
                )
            ])
        raise AssertionError(f"Unexpected schema requested: {schema}")

    async def research(self, query, *, model):
        return ResearchResult(insights=[])


def _config(tmp_path, **overrides):
    return AutopilotConfig(
        campaign_model="gpt-5.1", research_model="gpt-5.1", trend_ttl_hours=24, category_ttl_hours=168,
        too_similar_threshold=75, acceptable_threshold=45, output_root=tmp_path / "output", **overrides,
    )


async def test_novelty_remains_functional_with_feedback_present(temp_db, tmp_path):
    from datetime import datetime, timezone
    from app.models import Asset, CampaignFingerprint
    from app.services.fingerprint import text_hash

    session = temp_db.SessionLocal()
    brand, category, campaign, v_ig_ptbr, v_ig_en = _make_review_test_campaign(session, tmp_path)
    img_path = tmp_path / "novelty-asset.jpg"
    Image.new("RGB", (800, 800), (30, 60, 90)).save(img_path)
    session.add(Asset(
        brand_id=brand.id, category_id=category.id, absolute_path=str(img_path),
        relative_path="skincare/novelty-asset.jpg", filename="novelty-asset.jpg", extension=".jpg",
        sha256="novelty-sha", width=800, height=800,
    ))
    session.commit()

    # Real ReviewFeedback rows on file for this brand — proving their mere
    # presence changes nothing about novelty detection.
    record_review_feedback(session, campaign=campaign, variant=v_ig_ptbr, level="PLATFORM_VARIANT", action="APPROVE")
    record_review_feedback(
        session, campaign=campaign, variant=v_ig_en, level="PLATFORM_VARIANT", action="REJECT",
        reason_code="too_similar_to_previous_campaign",
    )

    fp_hash = text_hash("Same angle", "Same message", "Same insight")
    session.add(CampaignFingerprint(
        campaign_id=campaign.id, text_hash=fp_hash, angle="Same angle",
        promise_summary="Same angle Same message Same insight", objective="awareness", format="instagram_square",
        asset_sha256_list=[], computed_at=datetime.now(timezone.utc),
    ))
    session.commit()

    new_campaign = Campaign(
        display_id=f"HANNA-SKIN-{uuid.uuid4().hex[:8]}", brand_id=brand.id, category_id=category.id,
        objective="awareness", status="IDEA", languages=["pt-BR"], target_platforms=["instagram"],
    )
    session.add(new_campaign)
    session.commit()

    provider = _NoveltyFakeProvider()
    with pytest.raises(ValueError, match="too similar"):
        await run_strategy_stage(
            session, campaign_id=new_campaign.id, ai_provider=provider, research_provider=provider,
            config=_config(tmp_path),
        )
    session.close()


# ---------------------------------------------------------------------------
# Carry-forward test 3: REQUEST_REVISION creates lineage, never overwrites
# history — a full-pipeline integration test since it exercises
# `apply_requested_revision`'s reuse of Build 3's real render pipeline.
# ---------------------------------------------------------------------------

def _make_brand_category_assets(session, tmp_path, *, num_assets=2):
    from app.services.seed import seed_strategy_library
    seed_strategy_library(session)

    from app.models import Asset

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


class _RevisionFakeProvider:
    """Minimal fake covering only what a Strategy->Copy->Visuals run plus a
    single targeted COPY revision needs — leaner than test_build3's
    `FakeQAProvider` since this test never runs `run_qa_stage` itself.
    """

    def __init__(self):
        self.copy_revision_calls = 0

    async def generate_structured(self, *, system, user, schema, model):
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
        if schema is RevisedCopy:
            self.copy_revision_calls += 1
            return RevisedCopy(headline="Shorter, punchier headline", body="Trimmed body copy.", cta="Shop now")
        raise AssertionError(f"Unexpected schema requested: {schema}")

    async def research(self, query, *, model):
        return ResearchResult(insights=[
            ResearchInsightItem(
                statement="Multi-step skincare routines are trending in Brazil.", confidence=0.8,
                freshness="this_quarter", category="trend", recommended_implication="Emphasize routine-building.",
                source_urls=["https://example.com/trend-report"],
            )
        ])


async def test_revision_preserves_reviewed_history_and_lineage(temp_db, tmp_path, variant_renderer):
    """Carry-forward requirement 3: a REQUEST_REVISION action never destroys
    the reviewed version — the feedback row's OWN snapshot keeps the
    pre-revision asset paths forever, even after the live variant is
    re-rendered to a NEW set of asset paths; a later feedback action on the
    same variant auto-links back to the REQUEST_REVISION it answers.
    """
    session = temp_db.SessionLocal()
    provider = _RevisionFakeProvider()
    config = _config(tmp_path, qa_max_retries=0)
    brand, category = _make_brand_category_assets(session, tmp_path)
    campaign = Campaign(
        display_id=f"HANNA-SKIN-{uuid.uuid4().hex[:8]}", brand_id=brand.id, category_id=category.id,
        objective="awareness", status="IDEA", languages=["pt-BR"], target_platforms=["instagram"],
    )
    session.add(campaign)
    session.commit()
    campaign_id = campaign.id

    await run_strategy_stage(
        session, campaign_id=campaign_id, ai_provider=provider, research_provider=provider, config=config,
    )
    await run_copy_stage(session, campaign_id=campaign_id, ai_provider=provider, config=config)
    await run_visuals_stage(session, campaign_id=campaign_id, renderer=variant_renderer, config=config)

    variants = get_platform_campaign_variants(session, campaign_id)
    variant = next(v for v in variants if v.target_platform == "instagram" and v.language == "pt-BR")
    assert variant.status == "RENDERED"
    original_asset_paths = list(variant.slide_asset_paths)

    campaign = session.get(Campaign, campaign_id)
    feedback = record_review_feedback(
        session, campaign=campaign, variant=variant, level="PLATFORM_VARIANT", action="REQUEST_REVISION",
        reason_code="too_much_text", reason_text="Trim the body copy.",
    )
    assert feedback.reviewed_slide_asset_paths == original_asset_paths

    revised_variant = await apply_requested_revision(
        session, campaign=campaign, variant=variant, feedback=feedback, config=config, renderer=variant_renderer,
        ai_provider=provider,
    )
    assert provider.copy_revision_calls == 1
    assert revised_variant.slide_asset_paths  # a real new render happened
    assert revised_variant.slide_asset_paths != original_asset_paths  # different output path (new attempt tag)
    assert revised_variant.human_review_status == "PENDING"  # reset for a fresh owner look

    # The ORIGINAL feedback's own frozen snapshot is untouched by the revision
    # that came after it — lineage preserved, history never overwritten.
    session.refresh(feedback)
    assert feedback.reviewed_slide_asset_paths == original_asset_paths

    # A follow-up APPROVE on the now-revised variant auto-links back to the
    # REQUEST_REVISION it's answering.
    approval = record_review_feedback(
        session, campaign=campaign, variant=revised_variant, level="PLATFORM_VARIANT", action="APPROVE",
    )
    assert approval.revision_of_feedback_id == feedback.id
    session.close()
