"""Build 5 (GOLDEN BENCHMARK + PROMPT REGISTRY + MULTI-PLATFORM REGRESSION) —
the required minimum coverage named by the spec's own "BUILD 5 TESTS" list,
plus the BUILD 4 CARRY-FORWARD REQUIREMENTS section's own numbered test list
(items 3-10; items 1-2, completing feedback grounding, are covered by
`test_build4_completion.py`).

 BUILD 5 TESTS:
  1. Prompt registry works.
  2. Platform adapter prompt is versioned.
  3. Benchmark cases include platform.
  4. Benchmark cases include locale.
  5. PT-BR regression detected independently.
  6. English regression detected independently.
  7. Instagram regression detected.
  8. Pinterest/TikTok cases can use distinct evaluation expectations.
  9. Offline mode uses no paid API.
 10. Reports include platform/language.

 CARRY-FORWARD REQUIREMENTS 3-10 (own numbered test list, items not already
 covered elsewhere):
  5. Benchmark cases reference the exact reviewed historical version when
     derived from feedback.
  6. QA and owner-review ground truth remain separate.
  7. Owner/QA disagreement can be reported.
  8. Benchmark membership is explicit rather than automatic.
  9. Video benchmarks do not pretend rendered-video evidence exists.
 10. Old benchmark runs retain version identity after prompt/config changes.
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

from app.data.benchmark_scoring import compute_platform_weighted_score, weights_for
from app.models import (
    Asset, Brand, BenchmarkCase, BenchmarkRun, Campaign, Category, PlatformCampaignVariant, Product,
)
from app.schemas.ai import (
    CampaignCopy, CampaignStrategy, CampaignStrategyCandidates, CarouselPlan, CreativeBrief, ResearchInsightItem,
    ResearchResult, SlidePlan,
)
from app.schemas.creative_director import MasterCampaignConcept, PlatformAdaptation, VideoConcept
from app.schemas.qa import CreativeCritiqueResult, LanguageQAResult, VideoQAResult
from app.services.benchmark_engine import (
    build_regression_report, compare_runs, compute_owner_agreement_report, curate_benchmark_case, run_benchmark_case,
)
from app.services.creative.renderer import PlaywrightRenderer
from app.services.orchestrator import AutopilotConfig
from app.services.prompt_registry import PROMPT_VERSIONS, ensure_prompt_versions_seeded
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


# ---------------------------------------------------------------------------
# Part A / BUILD 5 TESTS 1-2: prompt registry.
# ---------------------------------------------------------------------------

def test_prompt_registry_has_platform_and_language_applicability(temp_db, tmp_path):
    """Test 1 (prompt registry works) + test 2 (platform adapter prompt is
    versioned) + Part A's own "platform applicability, language
    applicability, version, active status" requirement.
    """
    session = temp_db.SessionLocal()
    ensure_prompt_versions_seeded(session)

    from app.models import PromptVersion
    rows = {row.purpose: row for row in session.query(PromptVersion).all()}

    assert "platform_adaptation" in rows
    assert rows["platform_adaptation"].version  # versioned, not blank
    assert rows["platform_adaptation"].active is True

    # video_concept is structurally TikTok/YouTube-Shorts-only — the registry
    # says so explicitly rather than claiming universal applicability.
    assert rows["video_concept"].platform_applicability == ["tiktok", "youtube_shorts"]
    assert rows["campaign_copy"].platform_applicability == []  # [] == "every platform"

    # In-memory spec matches what got persisted (same source of truth).
    assert PROMPT_VERSIONS["video_concept"].platform_applicability == ["tiktok", "youtube_shorts"]
    session.close()


# ---------------------------------------------------------------------------
# Part B / BUILD 5 TESTS 3-4: benchmark case identity.
# ---------------------------------------------------------------------------

def test_benchmark_case_includes_platform_and_locale(temp_db, tmp_path):
    session = temp_db.SessionLocal()
    brand, category = _make_brand_category_assets(session, tmp_path)

    case = curate_benchmark_case(
        session, brand_id=brand.id, category_id=category.id, platform="pinterest", content_type="pin",
        language="en", objective="awareness", name="Pinterest EN golden case",
    )
    assert case.platform == "pinterest"
    assert case.language == "en"
    # Instagram/pt-BR and Instagram/en are separate cases even for "the same"
    # underlying idea (Part H) — proven structurally: nothing forces them to
    # share a row, and each case's own id is independent.
    case2 = curate_benchmark_case(
        session, brand_id=brand.id, category_id=category.id, platform="instagram", content_type="feed_post",
        language="pt-BR", objective="awareness",
    )
    case3 = curate_benchmark_case(
        session, brand_id=brand.id, category_id=category.id, platform="instagram", content_type="feed_post",
        language="en", objective="awareness",
    )
    assert case2.id != case3.id
    assert case2.language != case3.language
    session.close()


# ---------------------------------------------------------------------------
# Carry-forward test 8 (BUILD 5's own Part G): explicit membership only.
# ---------------------------------------------------------------------------

def test_benchmark_case_membership_is_explicit_not_automatic(temp_db, tmp_path):
    """A flood of ordinary APPROVE/REJECT review actions must never, by
    itself, create a `BenchmarkCase` row — curation is always a separate,
    deliberate call.
    """
    session = temp_db.SessionLocal()
    brand, category = _make_brand_category_assets(session, tmp_path)

    for action in ("APPROVE", "REJECT", "APPROVE", "REJECT", "REJECT"):
        campaign = Campaign(
            display_id=f"HANNA-SKIN-{uuid.uuid4().hex[:8]}", brand_id=brand.id, category_id=category.id,
            objective="awareness", status="REVIEW", languages=["pt-BR"], target_platforms=["instagram"],
        )
        session.add(campaign)
        session.commit()
        variant = PlatformCampaignVariant(
            campaign_id=campaign.id, target_platform="instagram", language="pt-BR", content_type="feed_post",
            status="RENDERED", slide_asset_paths=["slide.png"], qa_status="PASS",
        )
        session.add(variant)
        session.commit()
        record_review_feedback(session, campaign=campaign, variant=variant, level="PLATFORM_VARIANT", action=action)

    assert session.query(BenchmarkCase).count() == 0  # zero, despite five review actions

    # Only an explicit curate_benchmark_case call ever creates one.
    curate_benchmark_case(
        session, brand_id=brand.id, category_id=category.id, platform="instagram", content_type="feed_post",
        language="pt-BR",
    )
    assert session.query(BenchmarkCase).count() == 1
    session.close()


# ---------------------------------------------------------------------------
# Carry-forward test 5: a case derived from feedback preserves the exact
# reviewed snapshot, without ever mutating the ReviewFeedback row.
# ---------------------------------------------------------------------------

def test_benchmark_case_derived_from_feedback_preserves_immutable_snapshot(temp_db, tmp_path):
    session = temp_db.SessionLocal()
    brand, category = _make_brand_category_assets(session, tmp_path)
    campaign = Campaign(
        display_id=f"HANNA-SKIN-{uuid.uuid4().hex[:8]}", brand_id=brand.id, category_id=category.id,
        objective="awareness", status="REVIEW", languages=["pt-BR"], target_platforms=["instagram"],
    )
    session.add(campaign)
    session.commit()
    variant = PlatformCampaignVariant(
        campaign_id=campaign.id, target_platform="instagram", language="pt-BR", content_type="feed_post",
        status="RENDERED", slide_asset_paths=["golden-slide.png"], qa_status="PASS", qa_scores={"overall": 91},
    )
    session.add(variant)
    session.commit()

    feedback = record_review_feedback(
        session, campaign=campaign, variant=variant, level="PLATFORM_VARIANT", action="APPROVE",
    )
    feedback_version_before = feedback.updated_at

    case = curate_benchmark_case(
        session, brand_id=brand.id, category_id=category.id, platform="instagram", content_type="feed_post",
        language="pt-BR", source_feedback_id=feedback.id, name="Approved golden case",
    )
    assert case.owner_rating == "APPROVED"
    assert case.baseline_output_snapshot["slide_asset_paths"] == ["golden-slide.png"]
    assert case.baseline_output_snapshot["qa_status"] == "PASS"
    assert case.source_feedback_id == feedback.id

    # The ReviewFeedback row itself is untouched by curation.
    session.refresh(feedback)
    assert feedback.updated_at == feedback_version_before
    assert feedback.reviewed_slide_asset_paths == ["golden-slide.png"]

    # Deleting the source feedback row (SET NULL, never CASCADE) leaves the
    # case's own frozen snapshot fully intact — proving it was copied, never
    # a live join.
    session.delete(feedback)
    session.commit()
    session.refresh(case)
    assert case.source_feedback_id is None
    assert case.owner_rating == "APPROVED"
    assert case.baseline_output_snapshot["slide_asset_paths"] == ["golden-slide.png"]
    session.close()


# ---------------------------------------------------------------------------
# Carry-forward test 6: QA status and human review status stay separate on a
# BenchmarkRun (never collapsed into one ground truth).
# ---------------------------------------------------------------------------

def test_benchmark_run_keeps_qa_status_and_human_review_status_separate(temp_db, tmp_path):
    session = temp_db.SessionLocal()
    brand, category = _make_brand_category_assets(session, tmp_path)
    case = curate_benchmark_case(
        session, brand_id=brand.id, category_id=category.id, platform="instagram", content_type="feed_post",
        language="pt-BR",
    )
    run = BenchmarkRun(
        benchmark_case_id=case.id, mode="MOCK", platform="instagram", language="pt-BR",
        qa_status="PASS", human_review_status="REJECTED",  # a real QA_PASS + OWNER_REJECTED combination
        qa_scores={"overall": 88}, weighted_score=88.0,
    )
    session.add(run)
    session.commit()
    session.refresh(run)
    assert run.qa_status == "PASS"
    assert run.human_review_status == "REJECTED"  # never collapsed/overwritten by the qa_status write
    session.close()


# ---------------------------------------------------------------------------
# Carry-forward test 7 / spec's owner-agreement metrics.
# ---------------------------------------------------------------------------

def test_owner_agreement_report_surfaces_false_positive_and_negative(temp_db, tmp_path):
    session = temp_db.SessionLocal()
    brand, category = _make_brand_category_assets(session, tmp_path)

    def _variant(qa_status):
        campaign = Campaign(
            display_id=f"HANNA-SKIN-{uuid.uuid4().hex[:8]}", brand_id=brand.id, category_id=category.id,
            objective="awareness", status="REVIEW", languages=["pt-BR"], target_platforms=["instagram"],
        )
        session.add(campaign)
        session.commit()
        v = PlatformCampaignVariant(
            campaign_id=campaign.id, target_platform="instagram", language="pt-BR", content_type="feed_post",
            status="RENDERED", slide_asset_paths=["s.png"], qa_status=qa_status,
        )
        session.add(v)
        session.commit()
        return campaign, v

    # QA PASS + owner REJECTED -> false positive creative pass.
    c, v = _variant("PASS")
    record_review_feedback(session, campaign=c, variant=v, level="PLATFORM_VARIANT", action="REJECT")
    # QA NEEDS_REVIEW + owner APPROVED -> false negative creative fail.
    c, v = _variant("NEEDS_REVIEW")
    record_review_feedback(session, campaign=c, variant=v, level="PLATFORM_VARIANT", action="APPROVE")
    # Two genuine agreements.
    c, v = _variant("PASS")
    record_review_feedback(session, campaign=c, variant=v, level="PLATFORM_VARIANT", action="APPROVE")
    c, v = _variant("FAIL")
    record_review_feedback(session, campaign=c, variant=v, level="PLATFORM_VARIANT", action="REJECT")

    report = compute_owner_agreement_report(session, brand_id=brand.id)
    assert report["false_positive_creative_pass"] == 1
    assert report["false_negative_creative_fail"] == 1
    assert report["agreement_count"] == 2
    assert report["total_with_known_qa_status"] == 4
    assert "never a statistically meaningful" in report["caveat"]
    session.close()


# ---------------------------------------------------------------------------
# BUILD 5 TESTS 5-7, 10 + Part E/G: regression reporting, grouped by platform
# AND independently by language.
# ---------------------------------------------------------------------------

def _bare_run(session, case, *, platform, language, score, qa_status="PASS", prompt_versions=None):
    run = BenchmarkRun(
        benchmark_case_id=case.id, mode="MOCK", platform=platform, language=language, qa_status=qa_status,
        weighted_score=score, prompt_versions_snapshot=prompt_versions or {"campaign_copy": "1.0.0"},
    )
    session.add(run)
    session.commit()
    session.refresh(run)
    return run


def test_regression_report_tracks_platform_and_language_independently(temp_db, tmp_path):
    """Tests 5, 6, 7, 10 (reports include platform/language): an Instagram
    regression must show up under `by_platform["instagram"]`; a PT-BR
    regression and an EN improvement (or vice versa) on the SAME platform
    must both surface independently under `by_language`, never one hiding
    the other inside an averaged score.
    """
    session = temp_db.SessionLocal()
    brand, category = _make_brand_category_assets(session, tmp_path)
    ig_ptbr_case = curate_benchmark_case(
        session, brand_id=brand.id, category_id=category.id, platform="instagram", content_type="feed_post",
        language="pt-BR",
    )
    ig_en_case = curate_benchmark_case(
        session, brand_id=brand.id, category_id=category.id, platform="instagram", content_type="feed_post",
        language="en",
    )

    # PT-BR regresses (90 -> 70); EN improves (70 -> 90) — on the SAME platform.
    ptbr_baseline = _bare_run(session, ig_ptbr_case, platform="instagram", language="pt-BR", score=90.0)
    ptbr_candidate = _bare_run(session, ig_ptbr_case, platform="instagram", language="pt-BR", score=70.0)
    en_baseline = _bare_run(session, ig_en_case, platform="instagram", language="en", score=70.0)
    en_candidate = _bare_run(session, ig_en_case, platform="instagram", language="en", score=90.0)

    comparisons = [compare_runs(ptbr_baseline, ptbr_candidate), compare_runs(en_baseline, en_candidate)]
    report = build_regression_report(comparisons)

    assert report["comparisons"][0]["platform"] == "instagram"
    assert report["comparisons"][0]["language"] == "pt-BR"
    assert len(report["regressions"]) == 1
    assert len(report["improvements"]) == 1

    # Grouped by platform: instagram has BOTH a regression and an improvement
    # inside it — never averaged into one net-neutral instagram number.
    assert report["by_platform"]["instagram"]["count"] == 2
    assert len(report["by_platform"]["instagram"]["regressions"]) == 1
    assert len(report["by_platform"]["instagram"]["improvements"]) == 1

    # Grouped by language independently: pt-BR shows ONLY the regression,
    # en shows ONLY the improvement — one language's result never hides the
    # other's.
    assert len(report["by_language"]["pt-BR"]["regressions"]) == 1
    assert len(report["by_language"]["pt-BR"]["improvements"]) == 0
    assert len(report["by_language"]["en"]["regressions"]) == 0
    assert len(report["by_language"]["en"]["improvements"]) == 1
    session.close()


def test_old_benchmark_run_retains_version_identity_after_prompt_change(temp_db, tmp_path):
    """Carry-forward test 10 / Part F: a `BenchmarkRun`'s own frozen `prompt_
    versions_snapshot` never changes just because the LIVE prompt registry
    later bumps a version — old runs stay auditable against what they
    actually used.
    """
    session = temp_db.SessionLocal()
    brand, category = _make_brand_category_assets(session, tmp_path)
    case = curate_benchmark_case(
        session, brand_id=brand.id, category_id=category.id, platform="instagram", content_type="feed_post",
        language="pt-BR",
    )
    old_run = _bare_run(
        session, case, platform="instagram", language="pt-BR", score=85.0,
        prompt_versions={"campaign_copy": "1.0.0", "creative_direction": "1.0.0"},
    )
    old_snapshot = dict(old_run.prompt_versions_snapshot)

    # Simulate a later prompt-text change bumping the live registry version —
    # the OLD run's own frozen snapshot must not move.
    import dataclasses
    bumped_spec = dataclasses.replace(PROMPT_VERSIONS["campaign_copy"], version="2.0.0")
    original_spec = PROMPT_VERSIONS["campaign_copy"]
    PROMPT_VERSIONS["campaign_copy"] = bumped_spec
    try:
        ensure_prompt_versions_seeded(session)
        session.refresh(old_run)
        assert old_run.prompt_versions_snapshot == old_snapshot  # unchanged
        assert old_run.prompt_versions_snapshot["campaign_copy"] == "1.0.0"  # still the version it actually used

        from app.models import PromptVersion
        live_row = session.query(PromptVersion).filter_by(purpose="campaign_copy").one()
        assert live_row.version == "2.0.0"  # the LIVE registry did move
    finally:
        PROMPT_VERSIONS["campaign_copy"] = original_spec
        ensure_prompt_versions_seeded(session)
    session.close()


# ---------------------------------------------------------------------------
# BUILD 5 TEST 8: Pinterest/TikTok use distinct, documented evaluation
# expectations (Part D).
# ---------------------------------------------------------------------------

def test_pinterest_and_instagram_use_distinct_documented_weights():
    pinterest_weights = weights_for("pinterest", is_video=False)
    instagram_weights = weights_for("instagram", is_video=False)
    assert pinterest_weights != instagram_weights
    assert pinterest_weights["composition"] > instagram_weights.get("composition", 0)

    same_scorecard = {
        "overall": 80,
        "creative": CreativeCritiqueResult(
            overall_quality=80, composition=95, originality=95, platform_fit=95, carousel_consistency=40,
            professional_ad_quality=40,
        ).model_dump(),
    }
    pinterest_result = compute_platform_weighted_score("pinterest", same_scorecard)
    instagram_result = compute_platform_weighted_score("instagram", same_scorecard)
    # The SAME raw scorecard scores differently per platform's own weighting
    # — Pinterest rewards this (high composition/originality) scorecard more
    # than Instagram does (which weights carousel_consistency/professional_
    # ad_quality, both deliberately left low here).
    assert pinterest_result["weighted_score"] > instagram_result["weighted_score"]


def test_tiktok_video_weights_never_claim_rendered_video_evidence():
    """Carry-forward test 9: a video benchmark's own weight table only ever
    references `VideoQAResult`'s real dimensions (script/hook/shot-list/
    timing text judgments) — never a "visual quality"/"motion quality"/
    "product fidelity" dimension implying an actual rendered video exists,
    since this app renders none (`VideoConcept.is_rendered_video` is always
    `False`).
    """
    tiktok_weights = weights_for("tiktok", is_video=True)
    forbidden_terms = ("visual_quality", "motion_quality", "video_product_fidelity", "video_visual")
    for dim in tiktok_weights:
        assert not any(term in dim for term in forbidden_terms), dim
    assert "hook_strength" in tiktok_weights  # the real, honest dimension that DOES exist

    video_scorecard = {"video": VideoQAResult(hook_strength=95, script_coherence=90).model_dump()}
    result = compute_platform_weighted_score("tiktok", video_scorecard)
    assert result["weighted_score"] is not None
    assert "hook_strength" in result["dimensions_scored"]
    assert not any(term in dim for dim in result["weights_used"] for term in forbidden_terms)


# ---------------------------------------------------------------------------
# BUILD 5 TEST 9: OFFLINE mode makes no paid API call.
# ---------------------------------------------------------------------------

class _RaisingProvider:
    """Every method raises — used to PROVE `OFFLINE` mode never touches
    whatever provider object a caller happens to pass in, rather than merely
    hoping it stays unused because the test never gave it real credentials.
    """

    async def generate_structured(self, **kwargs):
        raise AssertionError("OFFLINE mode must never call generate_structured.")

    async def research(self, query, *, model):
        raise AssertionError("OFFLINE mode must never call research.")

    async def critique_creative(self, **kwargs):
        raise AssertionError("OFFLINE mode must never call critique_creative.")

    async def vision_describe(self, **kwargs):
        raise AssertionError("OFFLINE mode must never call vision_describe.")


async def test_offline_mode_never_calls_the_ai_provider(temp_db, tmp_path, variant_renderer):
    session = temp_db.SessionLocal()
    brand, category = _make_brand_category_assets(session, tmp_path)
    case = curate_benchmark_case(
        session, brand_id=brand.id, category_id=category.id, platform="instagram", content_type="feed_post",
        language="pt-BR",
    )
    config = _config(tmp_path)

    run = await run_benchmark_case(
        session, case=case, config=config, mode="OFFLINE", renderer=variant_renderer,
        ai_provider=_RaisingProvider(),  # would raise immediately if OFFLINE ever used it
    )
    assert run.mode == "OFFLINE"
    assert run.cost_breakdown["usage_recorded"] is False  # honestly zero, never fabricated
    session.close()


# ---------------------------------------------------------------------------
# End-to-end: MOCK mode runs the real pipeline and produces a fully scored,
# version-traceable run — proving `run_benchmark_case`/`compare_runs` work
# together on genuine pipeline output, not just hand-built rows.
# ---------------------------------------------------------------------------

class _ScoredFakeProvider:
    def __init__(self, *, creative_score: int = 90, hard_fails: list[str] | None = None):
        self.creative_score = creative_score
        self.hard_fails = hard_fails or []

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
        if schema is LanguageQAResult:
            return LanguageQAResult(language_naturalness=92, hard_fails=[])
        raise AssertionError(f"Unexpected schema requested: {schema}")

    async def critique_creative(self, *, image_paths, source_image_path, context, model):
        return CreativeCritiqueResult(
            overall_quality=self.creative_score, brand_alignment=85, product_fidelity=85, composition=88,
            carousel_consistency=85, professional_ad_quality=85, platform_fit=88, language_naturalness=88,
            hard_fails=list(self.hard_fails), rationale="fake critique",
        )

    async def vision_describe(self, *, image_path, prompt, model):
        return ""

    async def research(self, query, *, model):
        return ResearchResult(insights=[
            ResearchInsightItem(
                statement="Multi-step skincare routines are trending in Brazil.", confidence=0.8,
                freshness="this_quarter", category="trend", recommended_implication="Emphasize routine-building.",
                source_urls=["https://example.com/trend-report"],
            )
        ])


async def test_mock_mode_runs_real_pipeline_and_produces_scored_versioned_run(temp_db, tmp_path, variant_renderer):
    session = temp_db.SessionLocal()
    brand, category = _make_brand_category_assets(session, tmp_path)
    case = curate_benchmark_case(
        session, brand_id=brand.id, category_id=category.id, platform="instagram", content_type="feed_post",
        language="pt-BR", objective="awareness",
    )
    config = _config(tmp_path, qa_max_retries=0)
    provider = _ScoredFakeProvider(creative_score=91)

    run = await run_benchmark_case(
        session, case=case, config=config, mode="MOCK", renderer=variant_renderer, ai_provider=provider,
        is_baseline=True,
    )
    assert run.mode == "MOCK"
    assert run.platform == "instagram" and run.language == "pt-BR"
    assert run.qa_status == "PASS"
    assert run.weighted_score is not None
    assert run.prompt_versions_snapshot  # real prompt-version traceability, not empty
    assert run.model_role_snapshot["copy_model"]  # real model-role snapshot, not empty
    assert run.is_baseline is True
    assert run.human_review_status == "PENDING"  # no owner review has happened yet — never inferred from qa_status

    # A second, worse run compares as a real regression against the baseline.
    worse_provider = _ScoredFakeProvider(creative_score=40, hard_fails=["pasted-on product"])
    candidate = await run_benchmark_case(
        session, case=case, config=config, mode="MOCK", renderer=variant_renderer, ai_provider=worse_provider,
    )
    comparison = compare_runs(run, candidate)
    assert comparison["regression"] is True
    assert comparison["platform"] == "instagram"
    assert comparison["language"] == "pt-BR"
    assert "pasted-on product" in comparison["new_hard_failures"]
    session.close()


# ---------------------------------------------------------------------------
# API wiring smoke test — the service layer above is what's actually
# exercised in depth; this just proves `api/benchmarks.py` is wired up
# correctly end to end (curate -> run (OFFLINE, background job) -> fetch).
# ---------------------------------------------------------------------------

def _client():
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)


def _wait_for_job(client, job_id: str, *, timeout: float = 15.0) -> dict:
    import time
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


def test_benchmark_api_curate_run_offline_and_fetch(temp_db, tmp_path):
    session = temp_db.SessionLocal()
    brand, category = _make_brand_category_assets(session, tmp_path)
    brand_id, category_id = brand.id, category.id
    session.close()

    with _client() as client:
        r = client.patch("/api/settings", json={"output_root": str(tmp_path / "output")})
        assert r.status_code == 200

        r = client.get("/api/benchmarks/prompt-registry")
        assert r.status_code == 200
        assert any(p["purpose"] == "campaign_copy" for p in r.json()["prompts"])

        r = client.post("/api/benchmarks/cases", json={
            "brand_id": brand_id, "category_id": category_id, "platform": "instagram",
            "content_type": "feed_post", "language": "pt-BR", "name": "API golden case",
        })
        assert r.status_code == 201, r.text
        case_id = r.json()["id"]
        assert r.json()["platform"] == "instagram"
        assert r.json()["language"] == "pt-BR"

        r = client.get("/api/benchmarks/cases", params={"brand_id": brand_id})
        assert r.status_code == 200
        assert len(r.json()["cases"]) == 1

        r = client.post(f"/api/benchmarks/cases/{case_id}/runs", json={"mode": "OFFLINE", "is_baseline": True})
        assert r.status_code == 201, r.text
        job = _wait_for_job(client, r.json()["job_id"])
        assert job["status"] == "COMPLETED", job

        r = client.get(f"/api/benchmarks/cases/{case_id}/runs")
        assert r.status_code == 200
        runs = r.json()["runs"]
        assert len(runs) == 1
        assert runs[0]["mode"] == "OFFLINE"
        assert runs[0]["is_baseline"] is True

        r = client.get("/api/benchmarks/owner-agreement", params={"brand_id": brand_id})
        assert r.status_code == 200
        assert "caveat" in r.json()
