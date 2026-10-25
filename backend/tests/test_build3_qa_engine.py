"""Build 3 (MARKETING OS — PLATFORM + LANGUAGE AWARE MULTIMODAL QA) — the
required minimum test coverage named by the spec's own "BUILD 3 TESTS" list:

 1. Platform fit is scored.
 2. Language naturalness is scored.
 3. PT-BR/English mixing fails.
 4. Wrong platform aspect ratio fails.
 5. Technically valid ugly creative can fail.
 6. Wrong product hard fails.
 7. Targeted language revision works.
 8. Targeted platform revision works.
 9. Retry limit works.
10. NEEDS_REVIEW persists per variant.
11. QA evidence stored per platform/language variant.

Two kinds of tests here: fast, fully deterministic unit tests against the
Part A/D functions directly (no renderer, no AI) for the purely mechanical
properties (3's deterministic half, 4), and full-pipeline integration tests
(Strategy -> Copy -> Visuals -> `run_qa_stage`) using a controllable fake
`AIProvider` for everything that genuinely needs a rendered variant and an
AI critic (1, 2, 3's AI half, 5, 6, 7, 8, 9, 10, 11).

Every integration test uses a single-slide carousel plan (see
`FakeQAProvider.generate_structured`'s `CarouselPlan` override) and a single
platform/language so the primary variant's actual rendered dimensions
(`AutopilotConfig.platform_key`'s default "instagram_square", 1080x1080)
always agree with `default_content_type_for_platform`'s "feed_post"
resolution for a 1-slide plan — sidestepping an unrelated pre-existing
Build 2 nuance (a multi-slide primary-platform render uses
`effective_platform_key`, which need not match the carousel content type
`_render_additional_platform_variants` would separately resolve) that has
nothing to do with what these tests are actually verifying.
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

from app.data.platform_creative_specs import resolve_platform_creative_spec
from app.models import Asset, Brand, Campaign, Category, PlatformCampaignVariant
from app.schemas.ai import (
    CampaignCopy, CampaignStrategy, CampaignStrategyCandidates, CarouselPlan, CreativeBrief, ProductFidelityCheck,
    ResearchInsightItem, ResearchResult, SlidePlan,
)
from app.schemas.creative_director import CreativeDirection, MasterCampaignConcept, PlatformAdaptation, VideoConcept
from app.schemas.qa import CreativeCritiqueResult, LanguageQAResult, RevisedCopy, VideoQAResult
from app.services.creative.renderer import PlaywrightRenderer
from app.services.orchestrator import AutopilotConfig, get_platform_campaign_variants, run_copy_stage, run_strategy_stage, run_visuals_stage
from app.services.qa_engine import detect_identical_copy_across_languages, detect_platform_hard_fails, run_qa_stage, run_technical_qa


@pytest.fixture()
async def variant_renderer():
    renderer = PlaywrightRenderer()
    yield renderer
    await renderer.close()


def _make_brand_category_assets(session, tmp_path, *, num_assets=2):
    """Duplicated rather than imported — this codebase's own stated
    convention (see test_build2_platform_variants.py's docstring) is to keep
    each test file's fakes/helpers local.
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


class FakeQAProvider:
    """AIProvider stand-in covering every schema the full Strategy -> Copy ->
    Visuals -> QA pipeline can request, PLUS Build 3's own new schemas
    (`LanguageQAResult`, `RevisedCopy`, `VideoQAResult`) and `critique_creative`
    (Part B). Every QA-relevant response is controllable via constructor
    flags so one fake can drive every scenario below without needing a
    dozen near-identical subclasses.

    Returns a single-slide `CarouselPlan` (unlike `test_build2_platform_
    variants.py`'s own two-slide fake) — see this module's own docstring for
    why that matters for these particular tests.
    """

    def __init__(
        self, *,
        creative_score: int = 90,
        creative_hard_fails: list[str] | None = None,
        language_naturalness: int = 90,
        language_hard_fails: list[str] | None = None,
        language_fails_for_n_calls: int = 0,
    ):
        self.creative_score = creative_score
        self.creative_hard_fails = creative_hard_fails or []
        self.language_naturalness = language_naturalness
        self.language_hard_fails = language_hard_fails or []
        # How many of the FIRST `run_language_qa` calls should still report
        # `language_hard_fails` — used by the targeted-language-revision test
        # to simulate "the first attempt is broken, the revised copy is fine".
        self.language_fails_for_n_calls = language_fails_for_n_calls

        self.language_qa_calls = 0
        self.critique_calls = 0
        self.copy_revision_calls = 0
        self.creative_direction_revision_calls = 0
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
            self.language_qa_calls += 1
            still_failing = self.language_qa_calls <= self.language_fails_for_n_calls
            fails = list(self.language_hard_fails) if still_failing else []
            return LanguageQAResult(
                language_naturalness=self.language_naturalness if not fails else 30, hard_fails=fails,
            )
        if schema is RevisedCopy:
            self.copy_revision_calls += 1
            return RevisedCopy(headline="Revised headline", body="Revised body copy.", cta="Shop now")
        if schema is VideoQAResult:
            return VideoQAResult(
                hook_strength=90, script_coherence=90, shot_list_completeness=90, timing_score=90,
                on_screen_text_suitability=90, platform_fit=90, language_naturalness=90, factual_accuracy=90,
                brand_alignment=90, cta_effectiveness=90,
            )
        if schema is CreativeDirection:
            self.creative_direction_calls.append({"user": user})
            if "REVISING the visual direction" in system:
                self.creative_direction_revision_calls += 1
                return CreativeDirection(
                    concept_name="Everyday Ritual", background_concept="Revised calm studio backdrop",
                    scene_generation_prompt="Revised calm studio backdrop, no text, no logos, no products.",
                )
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

    async def critique_creative(self, *, image_paths, source_image_path, context, model):
        self.critique_calls += 1
        return CreativeCritiqueResult(
            overall_quality=self.creative_score, brand_alignment=85, product_fidelity=85, product_prominence=85,
            composition=85, typography=85, readability=85, color_harmony=85, hierarchy=85, clutter=85,
            copy_visual_fit=85, cta_visibility=85, mobile_readability=85, originality=85,
            professional_ad_quality=85, carousel_consistency=85, platform_fit=88, language_naturalness=88,
            hard_fails=list(self.creative_hard_fails), rationale="fake critique",
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
        return ProductFidelityCheck(overall_verdict="PASS", reasoning="Matches.")


def _config(tmp_path, **overrides):
    return AutopilotConfig(
        campaign_model="gpt-5.1", research_model="gpt-5.1", trend_ttl_hours=24, category_ttl_hours=168,
        too_similar_threshold=75, acceptable_threshold=45, output_root=tmp_path / "output", **overrides,
    )


async def _build_single_variant_campaign(session, tmp_path, variant_renderer, config, provider):
    """Shared setup for every integration test below: one brand/category/
    asset pool, a single-platform single-language campaign, run through
    Strategy -> Copy -> Visuals (no `image_provider`/`ai_provider` needed for
    Visuals itself — deterministic gradient rendering, fastest and simplest),
    returning the campaign id and its one `PlatformCampaignVariant`.
    """
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
    return campaign_id, variant


# ---------------------------------------------------------------------------
# Fast, fully deterministic unit tests (no renderer, no AI) — tests 3 (the
# deterministic half) and 4.
# ---------------------------------------------------------------------------

def test_wrong_platform_aspect_ratio_fails(tmp_path):
    """Test 4: a rendered slide whose actual PNG dimensions don't match its
    own `PlatformCreativeSpec` is a platform hard fail — purely mechanical,
    no AI or renderer needed.
    """
    spec = resolve_platform_creative_spec("instagram", "feed_post")  # 1080x1080
    bad_path = tmp_path / "wrong-size.png"
    Image.new("RGB", (500, 500), (200, 100, 50)).save(bad_path)
    variant = PlatformCampaignVariant(
        campaign_id="c1", target_platform="instagram", language="pt-BR", content_type="feed_post",
        render_format_key="instagram_square", status="RENDERED", slide_asset_paths=[str(bad_path)],
        qa_report_paths=[],  # not committed to a session, so the column's DB-side default never applies
    )
    fails = detect_platform_hard_fails(variant, spec)
    assert any("aspect" in f or "px" in f for f in fails)

    technical = run_technical_qa(variant, spec)
    assert technical.passed is False
    assert any("1080x1080" in issue for issue in technical.issues)


def test_pt_br_en_mixing_fails_deterministic_identical_copy_check():
    """Test 3 (deterministic half): the same non-trivial copy text appearing
    byte-identical across two declared languages is a real, checkable
    "likely untranslated" signal with no AI involved at all.
    """
    fails = detect_identical_copy_across_languages(
        "A rotina perfeita para sua pele todos os dias.",
        {"en": "A rotina perfeita para sua pele todos os dias.", "pt-BR": "irrelevant"},
        this_language="pt-BR",
    )
    assert any("untranslated" in f for f in fails)

    # A short, generic phrase legitimately shared across languages must NOT
    # be flagged — this is the min-length guard's whole purpose.
    assert detect_identical_copy_across_languages("Buy now", {"en": "Buy now"}, this_language="pt-BR") == []


# ---------------------------------------------------------------------------
# Full-pipeline integration tests.
# ---------------------------------------------------------------------------

async def test_platform_fit_and_language_naturalness_are_scored(temp_db, tmp_path, variant_renderer):
    """Tests 1 + 2: a passing variant's persisted `qa_scores` carries a real
    `platform_fit` score (Part B) and a real `language_naturalness` score
    (Part C), not fabricated/omitted values.
    """
    session = temp_db.SessionLocal()
    provider = FakeQAProvider(creative_score=92, language_naturalness=95)
    config = _config(tmp_path, qa_max_retries=0)
    campaign_id, variant = await _build_single_variant_campaign(session, tmp_path, variant_renderer, config, provider)

    await run_qa_stage(session, campaign_id=campaign_id, renderer=variant_renderer, config=config, ai_provider=provider)

    session.refresh(variant)
    assert variant.qa_status == "PASS"
    assert variant.qa_scores["creative"]["platform_fit"] == 88
    assert variant.qa_scores["language"]["language_naturalness"] == 95
    session.close()


async def test_technically_valid_ugly_creative_can_fail(temp_db, tmp_path, variant_renderer):
    """Test 5: a low `overall_quality` score with NO hard fails at all (the
    render is technically fine — right dimensions, valid file, on-brand
    copy) must still fail to PASS once below `qa_pass_threshold`.
    """
    session = temp_db.SessionLocal()
    provider = FakeQAProvider(creative_score=20)  # below the default threshold (60), no hard fails
    config = _config(tmp_path, qa_max_retries=0)  # single attempt — isolate the threshold-only failure
    campaign_id, variant = await _build_single_variant_campaign(session, tmp_path, variant_renderer, config, provider)

    await run_qa_stage(session, campaign_id=campaign_id, renderer=variant_renderer, config=config, ai_provider=provider)

    session.refresh(variant)
    assert variant.qa_status == "NEEDS_REVIEW"
    assert variant.qa_scores["technical"]["passed"] is True  # technically valid...
    assert variant.qa_hard_fails == []  # ...and no hard fail either — pure threshold failure
    session.close()


async def test_wrong_product_hard_fails(temp_db, tmp_path, variant_renderer):
    """Test 6: the creative critic naming a wrong-product defect is a hard
    fail that keeps the variant from passing regardless of `overall_quality`.
    """
    session = temp_db.SessionLocal()
    provider = FakeQAProvider(
        creative_score=95, creative_hard_fails=["wrong product: a different bottle shape than the source photo"],
    )
    config = _config(tmp_path, qa_max_retries=0)
    campaign_id, variant = await _build_single_variant_campaign(session, tmp_path, variant_renderer, config, provider)

    await run_qa_stage(session, campaign_id=campaign_id, renderer=variant_renderer, config=config, ai_provider=provider)

    session.refresh(variant)
    assert variant.qa_status == "NEEDS_REVIEW"
    assert any("wrong product" in f for f in variant.qa_hard_fails)
    session.close()


async def test_targeted_language_revision_works(temp_db, tmp_path, variant_renderer):
    """Test 7: a language hard-fail on attempt 1 triggers ONLY a targeted
    copy revision (never a creative-direction revision) for this one variant,
    and once the (simulated) revised copy reads clean, the variant passes on
    the very next attempt.
    """
    session = temp_db.SessionLocal()
    provider = FakeQAProvider(
        creative_score=90, language_hard_fails=["language_hard_fail: mixes Portuguese and English mid-sentence"],
        language_fails_for_n_calls=1,  # only the FIRST run_language_qa call reports the failure
    )
    config = _config(tmp_path, qa_max_retries=1)  # attempt 1 (fails) + one targeted revision attempt
    campaign_id, variant = await _build_single_variant_campaign(session, tmp_path, variant_renderer, config, provider)

    await run_qa_stage(session, campaign_id=campaign_id, renderer=variant_renderer, config=config, ai_provider=provider)

    session.refresh(variant)
    assert variant.qa_status == "PASS"
    assert variant.qa_attempts == 2
    assert provider.copy_revision_calls == 1
    assert provider.creative_direction_revision_calls == 0  # never touched the scene for a language-only issue
    session.close()


async def test_targeted_platform_revision_works(temp_db, tmp_path, variant_renderer):
    """Test 8: a platform/technical hard fail (here, a corrupted rendered
    file with the wrong dimensions) triggers a bare RE-RENDER of this one
    variant — never a copy or creative-direction change — and the re-render
    fixes the dimensions, so the variant passes on the next attempt.
    """
    session = temp_db.SessionLocal()
    provider = FakeQAProvider(creative_score=90)
    config = _config(tmp_path, qa_max_retries=1)
    campaign_id, variant = await _build_single_variant_campaign(session, tmp_path, variant_renderer, config, provider)

    # Corrupt the already-rendered slide to the wrong dimensions, simulating
    # the "Pinterest aspect problem" scenario Part E names by example.
    bad_path = variant.slide_asset_paths[0]
    Image.new("RGB", (400, 400), (0, 0, 0)).save(bad_path)

    await run_qa_stage(session, campaign_id=campaign_id, renderer=variant_renderer, config=config, ai_provider=provider)

    session.refresh(variant)
    assert variant.qa_status == "PASS"
    assert provider.copy_revision_calls == 0
    assert provider.creative_direction_revision_calls == 0
    with Image.open(variant.slide_asset_paths[0]) as img:
        assert img.size == (1080, 1080)  # re-rendered back to the correct instagram_square dimensions
    session.close()


async def test_retry_limit_and_needs_review_and_evidence_persist_per_variant(temp_db, tmp_path, variant_renderer):
    """Tests 9 + 10 + 11, updated for the Build 6 repair's duplicate-revision
    guard (Critical Defect 3): a persistent creative hard fail with no
    `image_provider` available means every creative-direction revision this
    scenario triggers can never produce a new AI-generated background, so
    once two consecutive revision attempts land on the exact same rendered
    bytes (the first revision's own re-render vs. the next one — the initial
    pre-QA render and a QA revision render aren't necessarily identical to
    each other, but two revisions in a row through the same, otherwise
    unchanged inputs are), the loop stops itself right there
    (`REVISION_NO_EFFECT`) rather than blindly exhausting all
    `qa_max_retries` attempts re-paying for renders that were never going to
    change anything further. This is the same real defect the owner's own
    live-acceptance review found (a manual SHA256 dedup showing 27 of 54
    rendered PNGs were wasted duplicate revision rounds) — settles at
    NEEDS_REVIEW, attached to THIS variant row and still there after a fresh
    read from the database, well short of the full 3-attempt retry budget,
    with real QA-evidence JSON files on disk for every attempt that actually
    ran.
    """
    session = temp_db.SessionLocal()
    provider = FakeQAProvider(
        creative_score=95, creative_hard_fails=["wrong product: persists across every retry"],
    )
    config = _config(tmp_path, qa_max_retries=2)  # up to 3 attempts allowed, but no image_provider to make a
    # creative-direction revision ever actually change the rendered pixels.
    campaign_id, variant = await _build_single_variant_campaign(session, tmp_path, variant_renderer, config, provider)
    variant_id = variant.id

    await run_qa_stage(session, campaign_id=campaign_id, renderer=variant_renderer, config=config, ai_provider=provider)

    session.refresh(variant)
    assert variant.qa_status == "NEEDS_REVIEW"
    assert "REVISION_NO_EFFECT" in variant.qa_notes
    # Stops well short of exhausting all 3 allowed attempts — the whole point
    # of this repair — rather than the pre-repair behavior of always running
    # every one of qa_max_retries + 1 attempts.
    assert variant.qa_attempts < 3
    assert len(variant.qa_evidence_paths) == variant.qa_attempts
    from pathlib import Path
    for p in variant.qa_evidence_paths:
        assert Path(p).exists()

    # Re-fetch from a fresh query (not just the in-memory ORM object) to
    # confirm this genuinely persisted to the database, per-variant.
    attempts_at_stop = variant.qa_attempts
    session.close()
    session2 = temp_db.SessionLocal()
    reloaded = session2.get(PlatformCampaignVariant, variant_id)
    assert reloaded.qa_status == "NEEDS_REVIEW"
    assert reloaded.qa_attempts == attempts_at_stop
    session2.close()


@pytest.mark.parametrize("change", [
    {"reference_fidelity": 60}, {"unintended_duplicate_product": True},
    {"background_has_product": True}, {"reference_id": "wrong"},
    {"reference_sha256": "changed"}, {"reference_fidelity": None},
    {"background_has_product": None}, {"unintended_duplicate_product": None},
])
def test_high_generic_score_cannot_mask_reference_failure(change):
    from app.schemas.qa import CreativeCritiqueResult
    from app.services.qa_engine import reference_qa_hard_fails
    from types import SimpleNamespace
    target = SimpleNamespace(reference_id="owner", sha256="a" * 64, minimum_fidelity=85)
    values = dict(overall_quality=99, reference_id="owner", reference_sha256="a" * 64,
                  reference_fidelity=95, background_has_product=False, unintended_duplicate_product=False)
    values.update(change)
    assert reference_qa_hard_fails(CreativeCritiqueResult(**values), target)


def test_correct_target_and_background_only_are_structurally_acceptable():
    from app.schemas.qa import CreativeCritiqueResult
    from app.services.qa_engine import reference_qa_hard_fails
    from types import SimpleNamespace
    target = SimpleNamespace(reference_id="owner", sha256="a" * 64, minimum_fidelity=85)
    result = CreativeCritiqueResult(overall_quality=95, reference_id="owner", reference_sha256="a" * 64,
        reference_fidelity=90, background_has_product=False, unintended_duplicate_product=False)
    assert reference_qa_hard_fails(result, target) == []
    assert reference_qa_hard_fails(None, target)


@pytest.mark.parametrize("fault", [None, "low_slide", "missing", "duplicate", "foreign", "stale",
                                  "wrong_target", "background", "second_product", "incoherent", "unknown_coherence"])
def test_prepared_reference_results_require_every_slide_and_coherence(fault):
    from types import SimpleNamespace
    from app.schemas.qa import CreativeCritiqueResult
    from app.services.qa_engine import reference_qa_hard_fails
    target = SimpleNamespace(reference_id="owner", sha256="a" * 64, minimum_fidelity=85)
    manifest = [{"slide_id": str(i), "contract_sha256": str(i) * 64,
                 "reference_target": dict(reference_id="owner", sha256="a" * 64, minimum_fidelity=85)}
                for i in (1, 2)]
    results = [dict(slide_id=m["slide_id"], contract_sha256=m["contract_sha256"],
                   reference_id="owner", reference_sha256="a" * 64, reference_fidelity=95,
                   background_has_product=False, unintended_duplicate_product=False) for m in manifest]
    values = dict(overall_quality=99, reference_id="owner", reference_sha256="a" * 64,
                  reference_fidelity=99, background_has_product=False, unintended_duplicate_product=False,
                  campaign_reference_coherent=True)
    if fault == "low_slide": results[1]["reference_fidelity"] = 84
    if fault == "missing": results.pop()
    if fault == "duplicate": results[1] = dict(results[0])
    if fault == "foreign": results[1]["slide_id"] = "foreign"
    if fault == "stale": results[1]["contract_sha256"] = "changed"
    if fault == "wrong_target": results[1]["reference_id"] = "other"
    if fault == "background": results[1]["background_has_product"] = True
    if fault == "second_product": results[1]["unintended_duplicate_product"] = True
    if fault == "incoherent": values["campaign_reference_coherent"] = False
    if fault == "unknown_coherence": values["campaign_reference_coherent"] = None
    creative = CreativeCritiqueResult(**values, slide_reference_results=results)
    assert bool(reference_qa_hard_fails(creative, target, manifest)) == (fault is not None)


@pytest.mark.parametrize("failure", ["paint_coherence", "individual_fidelity", "reference_identity", "unprepared_paint"])
def test_high_generic_score_cannot_override_paint_campaign_contract(failure):
    from types import SimpleNamespace
    from app.schemas.qa import CreativeCritiqueResult
    from app.services.qa_engine import reference_qa_hard_fails
    target = SimpleNamespace(reference_id="owner", sha256="a" * 64, minimum_fidelity=85)
    manifest = [dict(slide_id="paint-slide", contract_sha256="b" * 64,
        reference_target=dict(reference_id="owner", sha256="a" * 64, minimum_fidelity=85))]
    result = dict(slide_id="paint-slide", contract_sha256="b" * 64, reference_id="owner",
        reference_sha256="a" * 64, reference_fidelity=99, background_has_product=False,
        unintended_duplicate_product=False)
    if failure == "individual_fidelity": result["reference_fidelity"] = 84
    if failure == "reference_identity": result["reference_id"] = "other"
    if failure == "unprepared_paint": result["contract_sha256"] = "c" * 64
    values = dict(overall_quality=100, reference_id="owner", reference_sha256="a" * 64,
        reference_fidelity=99, background_has_product=False, unintended_duplicate_product=False,
        campaign_reference_coherent=failure != "paint_coherence", slide_reference_results=[result])
    assert reference_qa_hard_fails(CreativeCritiqueResult(**values), target, manifest)


def _physical_mark_qa_fixture():
    from app.schemas.qa import AuthenticPackageMarkPermission, PackageMarkSlideContext, CreativeCritiqueResult
    from app.services.qa_engine import _provenance_hash
    permission = AuthenticPackageMarkPermission.model_validate(dict(version=1, status="APPROVED", authority="OWNER",
        approved_at="2026-01-01T00:00:00Z", campaign_id="campaign", brand_id="brand", product_id="product",
        source_asset_id="source", render_asset_id="master", source_sha256="a"*64, render_sha256="b"*64,
        owner_decision_sha256="c"*64, use="PHYSICAL_PACKAGE_DEPICTION_ONLY",
        allowed_marks=[dict(mark_id="seal", kind="award", visible_text=["Real seal"])]) )
    context = PackageMarkSlideContext(slide_id="slide", contract_sha256="d"*64,
        permission_sha256=_provenance_hash(permission.model_dump(mode="json")), permission=permission,
        render_asset_id="master", render_sha256="b"*64, render_path="master.bin",
        source_asset_id="source", source_sha256="a"*64, source_path="source.bin",
        background_path="background.bin", background_sha256="e"*64, final_path="final.bin", final_sha256="f"*64)
    result = {k:getattr(context,k) for k in ["slide_id", "contract_sha256", "permission_sha256", "render_asset_id", "render_sha256", "source_asset_id", "source_sha256"]}
    result.update(marks=[dict(mark_id="seal", origin="AUTHORIZED_PRODUCT_LAYER", matches_authorized_asset=True)],
        generated_award_or_ranking_content=False, renderer_added_award_or_ranking_content=False,
        unsupported_promotional_award_content=False, assessment_complete=True)
    return context, result


@pytest.mark.parametrize("fault", [None, "no_permission", "generated_badge", "generated_ranking", "renderer_added",
    "unsupported_award_copy", "unsupported_ranking_copy", "other_mark", "unmatched", "unknown", "missing",
    "duplicate", "foreign", "stale_permission", "stale_plan", "wrong_asset", "wrong_source", "incomplete", "duplicate_mark"])
def test_package_mark_qa_decision_table_and_high_score_guard(fault):
    from app.schemas.qa import CreativeCritiqueResult
    from app.services.qa_engine import package_mark_hard_fails
    context, result = _physical_mark_qa_fixture()
    if fault in {"generated_badge", "generated_ranking"}:
        result["generated_award_or_ranking_content"] = True
        result["marks"][0]["origin"] = "GENERATED_BACKGROUND"
    if fault == "renderer_added":
        result["renderer_added_award_or_ranking_content"] = True
        result["marks"][0]["origin"] = "RENDERER_ADDED"
    if fault in {"unsupported_award_copy", "unsupported_ranking_copy"}: result["unsupported_promotional_award_content"] = True
    if fault == "other_mark": result["marks"][0]["mark_id"] = "unapproved"
    if fault == "unmatched": result["marks"][0]["matches_authorized_asset"] = False
    if fault == "unknown": result["marks"][0]["origin"] = "UNKNOWN"
    if fault == "stale_permission": result["permission_sha256"] = "0"*64
    if fault == "stale_plan": result["contract_sha256"] = "0"*64
    if fault == "wrong_asset": result["render_asset_id"] = "other"
    if fault == "wrong_source": result["source_sha256"] = "0"*64
    if fault == "incomplete": result["assessment_complete"] = False
    if fault == "foreign": result["slide_id"] = "other"
    if fault == "duplicate_mark": result["marks"] *= 2
    results = [] if fault == "missing" else [result, result] if fault == "duplicate" else [result]
    creative = CreativeCritiqueResult(overall_quality=100, package_mark_results=results)
    assert bool(package_mark_hard_fails(creative, None if fault == "no_permission" else [context])) == (fault is not None)


def test_permission_does_not_suppress_unrelated_failures_or_create_claims():
    from app.schemas.qa import CreativeCritiqueResult, TechnicalQAResult
    from app.services.qa_engine import _creative_overall_and_fails, package_mark_hard_fails
    context, result = _physical_mark_qa_fixture()
    creative = CreativeCritiqueResult(overall_quality=100, package_mark_results=[result], hard_fails=["unsupported promotional claim"])
    assert not package_mark_hard_fails(creative, [context])
    assert _creative_overall_and_fails(TechnicalQAResult(passed=True), [], [], creative)[1] == ["unsupported promotional claim"]
    assert "claim_id" not in type(context.permission).model_fields
    assert not package_mark_hard_fails(CreativeCritiqueResult())  # Legacy parsing grants no exception.


async def test_package_mark_context_uses_same_single_vision_request(tmp_path, monkeypatch):
    from pathlib import Path
    import hashlib
    from types import SimpleNamespace
    from app.services.ai import openai_provider as module
    from app.schemas.qa import CreativeCritiqueResult
    context, result = _physical_mark_qa_fixture()
    updates = {}
    for prefix in ["source", "render", "background", "final"]:
        path = tmp_path / (prefix + ".bin"); path.write_bytes(prefix.encode())
        updates[prefix + "_path"] = str(path)
        updates[prefix + "_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    permission = context.permission.model_copy(update={"source_sha256":updates["source_sha256"], "render_sha256":updates["render_sha256"]})
    from app.services.qa_engine import _provenance_hash
    updates.update(permission=permission, permission_sha256=_provenance_hash(permission.model_dump(mode="json")))
    context = context.model_copy(update=updates)
    calls = []
    class FakeResponses:
        async def parse(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(output_parsed=CreativeCritiqueResult(), usage=None)
    client = SimpleNamespace(responses=FakeResponses())
    provider = module.OpenAIProvider("sk-fake-offline")
    monkeypatch.setattr(provider, "_require_client", lambda: client)
    monkeypatch.setattr(module, "_openai_image_data_uri", lambda p: "fixture:" + str(p))
    await provider.critique_creative(image_paths=[Path(context.final_path)], source_image_path=None,
        context="factual campaign", model="fake", package_mark_context=[context])
    assert len(calls) == 1
    content = calls[0]["input"][0]["content"]
    assert sum(x["type"] == "input_image" for x in content) == 4
    text = str(content)
    assert "EXACT APPROVED RENDER ASSET" in text and "PHYSICAL_PACKAGE_DEPICTION_ONLY" in text
    Path(context.render_path).write_bytes(b"changed")
    with pytest.raises(ValueError, match="pixels changed"):
        await provider.critique_creative(image_paths=[Path(context.final_path)], source_image_path=None,
            context="factual campaign", model="fake", package_mark_context=[context])
    assert len(calls) == 1
