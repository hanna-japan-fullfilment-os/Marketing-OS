"""BUILD 5 FINAL REPAIR — PROMPT + CREATIVE SYSTEM TRACEABILITY.

Covers the repair spec's own numbered TEST REQUIREMENTS list:

 1. Scene-generation recipe version registration.
 2. Scene-generation version usage recording.
 3. Immutable scene-generation version in a BenchmarkRun.
 4. Complete creative-system snapshot.
 5. Renderer version identity.
 6. Template/layout version identity.
 7. Model-role snapshot remains immutable.
 8. Later configuration changes do not alter old benchmark runs.
 9. QA/owner agreement classification.
10. False-positive and false-negative QA disagreement reporting.

Plus REPAIR 1 test item 5 ("dynamic CreativeDirection content still works
normally") and REPAIR 4 ("the effective revision mechanism is explicit in
BenchmarkRun traceability").

Test-file convention (established by test_build3_qa_engine.py /
test_build5_benchmark.py): fakes/helpers are duplicated locally, not
imported across test files.
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
from dataclasses import replace

import pytest
from PIL import Image

from app.models import (
    Asset, AuditEvent, Brand, Campaign, Category, PlatformCampaignVariant,
)
from app.schemas.ai import (
    CampaignCopy, CampaignStrategy, CampaignStrategyCandidates, CarouselPlan, CreativeBrief, ProductFidelityCheck,
    ResearchInsightItem, ResearchResult, SlidePlan,
)
from app.schemas.creative_director import CreativeDirection, MasterCampaignConcept, PlatformAdaptation
from app.schemas.qa import CreativeCritiqueResult, LanguageQAResult, RevisedCopy
from app.services.benchmark_engine import build_creative_system_snapshot, curate_benchmark_case, run_benchmark_case
from app.services.creative.renderer import RENDERER_VERSION, PlaywrightRenderer
from app.services.creative.templates import TEMPLATE_REGISTRY_VERSION
from app.services.orchestrator import AutopilotConfig, get_platform_campaign_variants, run_copy_stage, \
    run_strategy_stage, run_visuals_stage
from app.services.product_facts import VERIFIED_PRODUCT_FACTS_RESOLVER_VERSION
from app.services.prompt_registry import PROMPT_VERSIONS
from app.services.qa_engine import QA_RUBRIC_VERSION
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


class _FullProvider:
    """A combined AIProvider + ImageProvider stand-in covering every schema the
    full Strategy -> Copy -> Visuals -> QA pipeline can request, PLUS
    `ImageProvider.generate` (for scene-generation coverage) and
    `check_product_fidelity` (for the full-recreation path). `language_fails_
    for_n_calls` (same knob as test_build3_qa_engine.py's FakeQAProvider) lets
    a test trigger exactly one targeted-copy-revision round.
    """

    def __init__(self, *, language_fails_for_n_calls: int = 0):
        self.language_fails_for_n_calls = language_fails_for_n_calls
        self.language_qa_calls = 0
        self.image_calls: list[dict] = []

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
            self.language_qa_calls += 1
            still_failing = self.language_qa_calls <= self.language_fails_for_n_calls
            fails = ["Mixed pt-BR/English wording."] if still_failing else []
            return LanguageQAResult(language_naturalness=90 if not fails else 30, hard_fails=fails)
        if schema is RevisedCopy:
            return RevisedCopy(headline="Revised headline", body="Revised body copy.", cta="Shop now")
        if schema is CreativeDirection:
            if "REVISING the visual direction" in system:
                return CreativeDirection(
                    concept_name="Everyday Ritual", background_concept="Revised calm studio backdrop",
                    lighting="Soft revised light", mood="Calm",
                    scene_generation_prompt="Revised calm studio backdrop, no text, no logos, no products.",
                )
            return CreativeDirection(
                concept_name="Everyday Ritual", background_concept="Soft warm gradient studio backdrop",
                lighting="Soft morning light", mood="Warm",
                scene_generation_prompt="Soft warm gradient studio backdrop, no text, no logos, no products.",
            )
        raise AssertionError(f"Unexpected schema requested: {schema}")

    async def critique_creative(self, *, image_paths, source_image_path, context, model):
        return CreativeCritiqueResult(
            overall_quality=90, brand_alignment=85, product_fidelity=85, composition=88,
            carousel_consistency=85, professional_ad_quality=85, platform_fit=88, language_naturalness=88,
            hard_fails=[], rationale="fake critique",
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

    async def detect_product_zone(self, *, image_path, model):
        raise NotImplementedError

    async def check_product_fidelity(self, *, source_image_path, generated_image_path, model):
        return ProductFidelityCheck(overall_verdict="PASS", reasoning="Matches.")

    # --- ImageProvider ----------------------------------------------------
    async def generate(self, *, prompt, size, model, reference_images=None, quality="high"):
        self.image_calls.append({"prompt": prompt, "size": size, "reference_images": reference_images})
        buf = io.BytesIO()
        Image.new("RGB", (64, 64), (200, 100, 50)).save(buf, format="PNG")
        return buf.getvalue()

    async def edit(self, *, base_image, prompt, model, mask=None, quality="high"):
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Repair test 1: scene-generation recipe version registration.
# ---------------------------------------------------------------------------

def test_scene_generation_prompt_is_registered():
    spec = PROMPT_VERSIONS["scene_generation"]
    assert spec.version == "1.1.0"
    assert "generate_ai_background" in spec.file_path or "recreate_creative_image" in spec.file_path
    # Deliberately language-independent — never scoped to a specific language
    # the way video_concept is scoped to specific platforms.
    assert spec.language_applicability == []



# ---------------------------------------------------------------------------
# Repair test 2: scene-generation version usage recording, at the real
# pipeline call sites (background-only path).
# ---------------------------------------------------------------------------

async def test_scene_generation_usage_is_recorded_when_ai_background_runs(temp_db, tmp_path, variant_renderer):
    session = temp_db.SessionLocal()
    brand, category = _make_brand_category_assets(session, tmp_path)
    campaign = Campaign(
        display_id=f"HANNA-SKIN-{uuid.uuid4().hex[:8]}", brand_id=brand.id, category_id=category.id,
        objective="awareness", status="IDEA", languages=["pt-BR"], target_platforms=["instagram"],
    )
    session.add(campaign)
    session.commit()
    campaign_id = campaign.id

    provider = _FullProvider()
    config = _config(tmp_path, use_ai_background=True, qa_max_retries=0)
    await run_strategy_stage(
        session, campaign_id=campaign_id, ai_provider=provider, research_provider=provider, config=config,
    )
    await run_copy_stage(session, campaign_id=campaign_id, ai_provider=provider, config=config)
    await run_visuals_stage(
        session, campaign_id=campaign_id, renderer=variant_renderer, config=config, image_provider=provider,
    )

    assert provider.image_calls  # the AI background call genuinely happened
    rows = (
        session.query(AuditEvent)
        .filter(AuditEvent.entity_type == "campaign_prompt_usage", AuditEvent.entity_id == campaign_id,
                AuditEvent.action == "scene_generation")
        .all()
    )
    assert rows, "no scene_generation usage was recorded despite a real AI background call"
    assert rows[0].detail["version"] == PROMPT_VERSIONS["scene_generation"].version
    assert rows[0].detail["language"] == ""  # language-independent, per the recipe's own docstring
    assert rows[0].detail["mode"] == "background_only"  # the `extra` dict merges straight into `detail`
    session.close()


# ---------------------------------------------------------------------------
# Repair tests 3/4: a BenchmarkRun preserves the scene-generation version,
# and a later registry bump never retroactively changes an old run.
# ---------------------------------------------------------------------------

async def test_benchmark_run_preserves_scene_generation_version(temp_db, tmp_path, variant_renderer):
    session = temp_db.SessionLocal()
    brand, category = _make_brand_category_assets(session, tmp_path)
    case = curate_benchmark_case(
        session, brand_id=brand.id, category_id=category.id, platform="instagram", content_type="feed_post",
        language="pt-BR", objective="awareness",
    )
    provider = _FullProvider()
    config = _config(tmp_path, use_ai_background=True, qa_max_retries=0)

    run = await run_benchmark_case(
        session, case=case, config=config, mode="MOCK", renderer=variant_renderer, ai_provider=provider,
        image_provider=provider,
    )
    assert provider.image_calls  # the recipe genuinely ran during this benchmark
    snapshot = run.creative_system_snapshot
    assert snapshot["prompt_versions"]["scene_generation"] == PROMPT_VERSIONS["scene_generation"].version
    session.close()


async def test_old_benchmark_run_scene_generation_version_is_immutable_after_registry_bump(
    temp_db, tmp_path, variant_renderer, monkeypatch,
):
    session = temp_db.SessionLocal()
    brand, category = _make_brand_category_assets(session, tmp_path)
    case = curate_benchmark_case(
        session, brand_id=brand.id, category_id=category.id, platform="instagram", content_type="feed_post",
        language="pt-BR", objective="awareness",
    )
    provider = _FullProvider()
    config = _config(tmp_path, use_ai_background=True, qa_max_retries=0)
    run = await run_benchmark_case(
        session, case=case, config=config, mode="MOCK", renderer=variant_renderer, ai_provider=provider,
        image_provider=provider,
    )
    recorded_version = run.creative_system_snapshot["prompt_versions"]["scene_generation"]
    assert recorded_version == "1.1.0"

    # Simulate a later scene-generation RECIPE version bump — a real prompt-
    # registry change, exactly like `test_old_benchmark_run_retains_version_
    # identity_after_prompt_change` already proves for `campaign_copy`.
    monkeypatch.setitem(
        PROMPT_VERSIONS, "scene_generation", replace(PROMPT_VERSIONS["scene_generation"], version="9.9.9"),
    )
    assert PROMPT_VERSIONS["scene_generation"].version == "9.9.9"  # the live registry did change

    session.refresh(run)
    assert run.creative_system_snapshot["prompt_versions"]["scene_generation"] == "1.1.0"  # old run untouched
    session.close()




# ---------------------------------------------------------------------------
# Repair test 4 (complete creative-system snapshot) / 5-6 (renderer + template
# version identity).
# ---------------------------------------------------------------------------

async def test_creative_system_snapshot_includes_every_version_identity(temp_db, tmp_path, variant_renderer):
    session = temp_db.SessionLocal()
    brand, category = _make_brand_category_assets(session, tmp_path)
    case = curate_benchmark_case(
        session, brand_id=brand.id, category_id=category.id, platform="instagram", content_type="feed_post",
        language="pt-BR", objective="awareness",
    )
    provider = _FullProvider()
    config = _config(tmp_path, qa_max_retries=0)  # no image generation this time — a plain, no-AI-image run

    run = await run_benchmark_case(
        session, case=case, config=config, mode="MOCK", renderer=variant_renderer, ai_provider=provider,
    )
    snapshot = run.creative_system_snapshot
    assert snapshot["verified_product_facts_resolver_version"] == VERIFIED_PRODUCT_FACTS_RESOLVER_VERSION
    assert snapshot["renderer_version"] == RENDERER_VERSION
    assert snapshot["template_version"] == TEMPLATE_REGISTRY_VERSION
    assert snapshot["qa_rubric_version"] == QA_RUBRIC_VERSION
    assert snapshot["platform"] == "instagram"
    assert snapshot["language"] == "pt-BR"
    assert snapshot["quality_mode"] == config.quality_mode
    # A future engineer can read WHICH generation system produced this run
    # from this one field alone — including the real per-purpose prompt
    # versions actually used, not just the top-level identities above.
    assert snapshot["prompt_versions"]["campaign_copy"] == PROMPT_VERSIONS["campaign_copy"].version
    assert snapshot["prompt_versions"]["master_campaign_concept"] == PROMPT_VERSIONS["master_campaign_concept"].version
    session.close()


def test_build_creative_system_snapshot_does_not_duplicate_model_role_snapshot(temp_db, tmp_path):
    """Repair 2's own "do not unnecessarily duplicate large blobs" — the
    snapshot builder's own return shape never includes a `model_role_*` key,
    since `BenchmarkRun.model_role_snapshot` already answers that question as
    its own column.
    """
    session = temp_db.SessionLocal()
    brand, category = _make_brand_category_assets(session, tmp_path)
    campaign = Campaign(
        display_id=f"HANNA-SKIN-{uuid.uuid4().hex[:8]}", brand_id=brand.id, category_id=category.id,
        objective="awareness", status="IDEA", languages=["pt-BR"], target_platforms=["instagram"],
    )
    session.add(campaign)
    session.commit()

    snapshot = build_creative_system_snapshot(
        session, campaign_id=campaign.id, platform="instagram", language="pt-BR", content_type="feed_post",
        quality_mode="standard",
    )
    assert not any(key.startswith("model_role") for key in snapshot)
    session.close()


# ---------------------------------------------------------------------------
# Repair 4: the effective revision mechanism is explicit in BenchmarkRun
# traceability — a targeted copy revision's own prompt version shows up
# distinctly, never silently folded into/overwriting the original purpose.
# ---------------------------------------------------------------------------

async def test_revision_purpose_is_traced_in_the_benchmark_runs_snapshot(temp_db, tmp_path, variant_renderer):
    session = temp_db.SessionLocal()
    brand, category = _make_brand_category_assets(session, tmp_path)
    case = curate_benchmark_case(
        session, brand_id=brand.id, category_id=category.id, platform="instagram", content_type="feed_post",
        language="pt-BR", objective="awareness",
    )
    # The first language-QA attempt fails, triggering exactly one targeted
    # copy revision before the second attempt passes.
    provider = _FullProvider(language_fails_for_n_calls=1)
    config = _config(tmp_path, qa_max_retries=1)

    run = await run_benchmark_case(
        session, case=case, config=config, mode="MOCK", renderer=variant_renderer, ai_provider=provider,
    )
    assert run.qa_status == "PASS"  # passed on the second attempt, after revision
    prompt_versions = run.creative_system_snapshot["prompt_versions"]
    # The revision purpose is its OWN distinct key — never collapsed into or
    # overwriting "campaign_copy"'s own original-generation version.
    assert "targeted_copy_revision" in prompt_versions
    assert "campaign_copy" in prompt_versions
    assert prompt_versions["targeted_copy_revision"] == PROMPT_VERSIONS["targeted_copy_revision"].version
    session.close()


# ---------------------------------------------------------------------------
# Repair 1 test item 5: dynamic CreativeDirection content still works
# normally — this repair's new record_prompt_usage calls around scene
# generation must not have broken the actual mechanism that produces it.
# ---------------------------------------------------------------------------

async def test_dynamic_creative_direction_content_is_unaffected(temp_db, tmp_path, variant_renderer):
    """`CreativeDirection` is only ever AI-generated on the ADDITIONAL-variant
    path (`_render_additional_platform_variants`) — a benchmark campaign is
    always single-platform/single-language by design (Part H), so this needs
    a real multi-language campaign (same shape as
    test_build2_platform_variants.py's own multi-variant fixtures) to
    actually exercise it, not `run_benchmark_case`.
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

    provider = _FullProvider()
    config = _config(tmp_path, use_ai_background=True, qa_max_retries=0)
    await run_strategy_stage(
        session, campaign_id=campaign_id, ai_provider=provider, research_provider=provider, config=config,
    )
    await run_copy_stage(session, campaign_id=campaign_id, ai_provider=provider, config=config)
    await run_visuals_stage(
        session, campaign_id=campaign_id, renderer=variant_renderer, config=config, image_provider=provider,
        ai_provider=provider,
    )

    variants = get_platform_campaign_variants(session, campaign_id)
    # "en" is the non-primary language here — its CreativeDirection is
    # genuinely AI-generated (never shared with pt-BR's), per Build 2 Part H.
    variant = next(v for v in variants if v.target_platform == "instagram" and v.language == "en")
    assert variant.creative_direction.get("background_concept") == "Soft warm gradient studio backdrop"
    assert variant.creative_direction.get("mood") == "Warm"

    # The scene-generation recipe also ran for this additional-variant slide —
    # this repair's new recording didn't disturb the actual generation.
    rows = (
        session.query(AuditEvent)
        .filter(AuditEvent.entity_type == "campaign_prompt_usage", AuditEvent.entity_id == campaign_id,
                AuditEvent.action == "scene_generation")
        .all()
    )
    assert rows
    session.close()


# ---------------------------------------------------------------------------
# Repair 5: owner/QA agreement — explicit case counts for all four
# QA-status x owner-decision combinations (extends the existing coverage in
# test_build5_benchmark.py rather than rewriting it).
# ---------------------------------------------------------------------------

def test_owner_agreement_report_exposes_all_four_classification_counts(temp_db, tmp_path):
    from app.services.benchmark_engine import compute_owner_agreement_report

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

    c, v = _variant("PASS")  # QA_PASS + OWNER_APPROVED -> agreement
    record_review_feedback(session, campaign=c, variant=v, level="PLATFORM_VARIANT", action="APPROVE")
    c, v = _variant("FAIL")  # QA_FAIL + OWNER_REJECTED -> agreement
    record_review_feedback(session, campaign=c, variant=v, level="PLATFORM_VARIANT", action="REJECT")
    c, v = _variant("PASS")  # QA_PASS + OWNER_REJECTED -> false positive
    record_review_feedback(session, campaign=c, variant=v, level="PLATFORM_VARIANT", action="REJECT")
    c, v = _variant("NEEDS_REVIEW")  # QA_FAIL/NEEDS_REVIEW + OWNER_APPROVED -> false negative
    record_review_feedback(session, campaign=c, variant=v, level="PLATFORM_VARIANT", action="APPROVE")

    report = compute_owner_agreement_report(session, brand_id=brand.id)
    assert report["owner_approved"] == 2
    assert report["owner_rejected"] == 2
    assert report["qa_pass"] == 2
    assert report["qa_fail_or_needs_review"] == 2
    assert report["agreement_count"] == 2
    assert report["false_positive_creative_pass"] == 1
    assert report["false_negative_creative_fail"] == 1
    assert report["disagreement_count"] == 2
    assert "never a statistically meaningful" in report["caveat"]
    session.close()


# ---------------------------------------------------------------------------
# Repair 3: renderer / template version identity exist and are simple,
# maintainable string constants (not a giant new framework).
# ---------------------------------------------------------------------------

def test_renderer_and_template_registry_versions_are_simple_constants():
    assert isinstance(RENDERER_VERSION, str) and RENDERER_VERSION
    assert isinstance(TEMPLATE_REGISTRY_VERSION, str) and TEMPLATE_REGISTRY_VERSION
    assert isinstance(VERIFIED_PRODUCT_FACTS_RESOLVER_VERSION, str) and VERIFIED_PRODUCT_FACTS_RESOLVER_VERSION
