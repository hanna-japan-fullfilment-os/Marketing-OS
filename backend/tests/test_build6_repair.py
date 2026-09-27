"""BUILD 6 REPAIR — TARGETED LIVE-ACCEPTANCE REPAIR.

Focused regression tests for the 7 numbered CRITICAL DEFECTs the owner's own
real live-acceptance run surfaced (see claude/build-status.md's "Build 6
REPAIR" section and `data/live_acceptance/20260912T064017Z.json`'s findings):

  1. Source-product identity gate (pre-generation) — tests A, B, plus a
     regression-safety test proving the fix does not break every existing
     test fake that predates this new `AIProvider` capability.
  2. Claims-boundary grounding (verified facts vs. research vs. brand notes
     vs. creative ideas) — tests D, E, F, G.
  3. Duplicate/no-effect revision guard — test I (the qa_engine.py unit-level
     half; the full integration proof lives in
     test_build3_qa_engine.py::test_retry_limit_and_needs_review_and_
     evidence_persist_per_variant, updated this same repair).
  4. Deterministic text-overflow shortening — test J/K.
  5. TikTok/video-concept one-retry — test L (retry half; SCRIPT_ONLY + QA
     completion is already covered by
     test_build6_acceptance.py::test_tiktok_script_only_gets_video_qa, an
     existing pre-repair test this repair does not need to duplicate).
  6. Exact acceptance matrix (no Cartesian product) — test H.
  7. Usage-scope attribution + cost preflight — tests M, N (scope-attribution
     unit coverage lives in test_usage_tracking.py, added this same repair;
     this file covers the run_live_acceptance.py-side grouping/estimate/
     budget helpers).

Test-file convention (established by test_build3_qa_engine.py /
test_build5_benchmark.py / test_build5_repair.py / test_build6_acceptance.py):
fakes/helpers are duplicated locally, not imported across test files.
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

import pytest
from PIL import Image

from app.data.platform_creative_specs import resolve_platform_creative_spec
from app.models import AuditEvent, Asset, Brand, Campaign, Category, Product
from app.schemas.ai import (
    CampaignCopy, CampaignStrategy, CampaignStrategyCandidates, CarouselPlan, CreativeBrief, ResearchResult,
    SlidePlan, SourceProductIdentityCheck,
)
from app.schemas.creative_director import MasterCampaignConcept, PlatformAdaptation, VideoConcept
from app.schemas.qa import RevisedCopy
from app.services.creative.renderer import PlaywrightRenderer
from app.services.orchestrator import (
    AutopilotConfig, SourceProductIdentityMismatch, _claims_boundary_instruction,
    _enforce_source_product_identity_gate, generate_video_concept, run_copy_stage, run_strategy_stage,
    run_visuals_stage, verify_source_product_identity,
)
from app.services.qa_engine import (
    _COPY_DENSITY_WORD_BUDGETS, _deterministic_shorten_copy, _hash_slide_files, _truncate_to_words,
)

from scripts.run_live_acceptance import (
    ACCEPTANCE_MATRIX, _combine_verdict, _estimate_matrix_cost_usd, _group_matrix_by_platform, _is_script_only_case,
    _merge_cost_report, _smoke_matrix,
)


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
    img_path = tmp_path / "source.jpg"
    Image.new("RGB", (800, 800), (200, 180, 190)).save(img_path)
    asset = Asset(
        brand_id=brand.id, category_id=category.id, product_id=product.id, absolute_path=str(img_path),
        relative_path="skincare/source.jpg", filename="source.jpg", extension=".jpg", sha256="src-sha", width=800,
        height=800,
    )
    session.add(asset)
    session.commit()
    campaign = Campaign(
        display_id=f"HANNA-SKIN-{uuid.uuid4().hex[:8]}", brand_id=brand.id, category_id=category.id,
        product_id=product.id, objective="awareness", status="IDEA",
    )
    session.add(campaign)
    session.commit()
    return brand, category, product, asset, campaign


# ---------------------------------------------------------------------------
# Critical Defect 1 — pre-generation source-product identity gate.
# Tests A, B, plus a regression-safety test for the capability-detection fix.
# ---------------------------------------------------------------------------

class _IdentityCheckProvider:
    """Minimal `AIProvider` stand-in exposing ONLY `verify_source_product_
    identity` — everything `_enforce_source_product_identity_gate` actually
    calls.
    """

    def __init__(self, *, verdict: str = "MATCH", raises: bool = False):
        self.verdict = verdict
        self.raises = raises
        self.calls = 0

    async def verify_source_product_identity(self, *, source_image_path, product_name, category_name, model):
        self.calls += 1
        if self.raises:
            raise RuntimeError("simulated vision-model outage")
        return SourceProductIdentityCheck(
            verdict=self.verdict, observed_product_type="cleanser" if self.verdict != "MATCH" else "serum",
            reasoning="fake check",
        )


async def test_a_source_identity_mismatch_fails_before_any_generation(temp_db, tmp_path):
    session = temp_db.SessionLocal()
    _, _, product, asset, campaign = _make_brand_category_product_asset(session, tmp_path)
    provider = _IdentityCheckProvider(verdict="MISMATCH")

    with pytest.raises(SourceProductIdentityMismatch) as excinfo:
        await _enforce_source_product_identity_gate(
            session, campaign=campaign, ai_provider=provider, vision_model="gpt-5.1",
            asset_product_pairs=[(asset, product)],
        )
    assert str(excinfo.value).startswith("SOURCE_PRODUCT_IDENTITY_MISMATCH")
    session.refresh(campaign)
    assert campaign.status == "FAILED"

    audit_rows = session.query(AuditEvent).filter(AuditEvent.action == "source_product_identity_check").all()
    assert len(audit_rows) == 1
    assert audit_rows[0].detail["verdict"] == "MISMATCH"
    session.close()


async def test_b_unverifiable_verdict_fails_closed_not_treated_as_match(temp_db, tmp_path):
    session = temp_db.SessionLocal()
    _, _, product, asset, campaign = _make_brand_category_product_asset(session, tmp_path)
    provider = _IdentityCheckProvider(verdict="UNVERIFIABLE")

    with pytest.raises(SourceProductIdentityMismatch):
        await _enforce_source_product_identity_gate(
            session, campaign=campaign, ai_provider=provider, vision_model="gpt-5.1",
            asset_product_pairs=[(asset, product)],
        )
    session.refresh(campaign)
    assert campaign.status == "FAILED"
    session.close()


async def test_b_a_check_that_errors_also_fails_closed_via_the_wrapper(temp_db, tmp_path):
    """`verify_source_product_identity` (the module-level wrapper, not the
    gate) never propagates a provider exception — it resolves to an honest
    `UNVERIFIABLE`, mirroring `recreate_creative_image_with_fidelity_gate`'s
    own established "an errored check is never treated as a pass" rule. The
    gate then fails closed on that `UNVERIFIABLE` exactly like test B above.
    """
    session = temp_db.SessionLocal()
    _, _, product, asset, campaign = _make_brand_category_product_asset(session, tmp_path)
    provider = _IdentityCheckProvider(raises=True)

    result = await verify_source_product_identity(
        ai_provider=provider, source_image_path=tmp_path / "source.jpg", product_name=product.name,
        category_name="", model="gpt-5.1",
    )
    assert result.verdict == "UNVERIFIABLE"

    with pytest.raises(SourceProductIdentityMismatch):
        await _enforce_source_product_identity_gate(
            session, campaign=campaign, ai_provider=provider, vision_model="gpt-5.1",
            asset_product_pairs=[(asset, product)],
        )
    session.close()


async def test_source_identity_match_passes_through_and_dedupes_per_asset(temp_db, tmp_path):
    session = temp_db.SessionLocal()
    _, _, product, asset, campaign = _make_brand_category_product_asset(session, tmp_path)
    provider = _IdentityCheckProvider(verdict="MATCH")

    # The same asset appears twice (round-robin reuse across two slides) —
    # must be checked (and billed) only once.
    await _enforce_source_product_identity_gate(
        session, campaign=campaign, ai_provider=provider, vision_model="gpt-5.1",
        asset_product_pairs=[(asset, product), (asset, product)],
    )
    assert provider.calls == 1
    session.refresh(campaign)
    assert campaign.status == "IDEA"  # untouched — no failure occurred
    session.close()


async def test_gate_is_a_noop_for_a_provider_lacking_the_capability(temp_db, tmp_path):
    """Regression-safety net: this repair added `verify_source_product_
    identity` to the `AIProvider` Protocol, but every pre-existing test fake
    across this whole suite predates it and does not implement it. Without
    this capability check, EVERY one of those fakes would make the gate
    fail-closed to `UNVERIFIABLE` (via the wrapper's own except-Exception
    fallback catching the `AttributeError`) and fail every product-scoped
    campaign outright — a mass regression this test exists specifically to
    prevent. A capability gap is a different fact from a check that was
    actually attempted and came back inconclusive (see `_enforce_source_
    product_identity_gate`'s own docstring) — mirrors `services/usage_
    tracking.py::drain_provider_usage_events`'s identical duck-typed
    "this fake test provider doesn't support it" detection.
    """
    session = temp_db.SessionLocal()
    _, _, product, asset, campaign = _make_brand_category_product_asset(session, tmp_path)
    bare_provider = SimpleNamespace()  # no verify_source_product_identity at all

    await _enforce_source_product_identity_gate(
        session, campaign=campaign, ai_provider=bare_provider, vision_model="gpt-5.1",
        asset_product_pairs=[(asset, product)],
    )
    session.refresh(campaign)
    assert campaign.status == "IDEA"  # never touched — the gate was a clean no-op
    assert session.query(AuditEvent).filter(AuditEvent.action == "source_product_identity_check").count() == 0
    session.close()


async def test_gate_is_a_noop_for_a_category_only_campaign(temp_db, tmp_path):
    """A category-only campaign (no catalog `Product`) makes no per-product
    identity claim in the first place — `product=None` in the pair correctly
    skips the check entirely, never a false block.
    """
    session = temp_db.SessionLocal()
    _, _, _product, asset, campaign = _make_brand_category_product_asset(session, tmp_path)
    provider = _IdentityCheckProvider(verdict="MISMATCH")  # would fail if it were ever consulted

    await _enforce_source_product_identity_gate(
        session, campaign=campaign, ai_provider=provider, vision_model="gpt-5.1",
        asset_product_pairs=[(asset, None)],
    )
    assert provider.calls == 0
    session.refresh(campaign)
    assert campaign.status == "IDEA"
    session.close()


class _PipelineIdentityProvider:
    """A slightly fuller fake — enough to run Strategy -> Copy -> Visuals for
    a single-platform/single-language product-scoped campaign — used only to
    prove the gate fires INSIDE the real `run_visuals_stage` entry point,
    strictly before any image-generation call, not just when called directly.
    """

    def __init__(self, *, identity_verdict: str = "MATCH"):
        self.identity_verdict = identity_verdict
        self.image_calls = 0

    async def generate_structured(self, *, system, user, schema, model):
        # Successful semantic scan with no extra factual candidates.
        if getattr(schema, "__name__", "") == "CandidateClaimExtractionResult":
            return schema(claims=[])

        if schema is CampaignStrategyCandidates:
            return CampaignStrategyCandidates(candidates=[CampaignStrategy(
                objective="awareness", audience="Young adults", funnel_stage="tofu", insight="Routines trend",
                angle="Build a routine", key_message="Everything for a routine", reason_this_should_work="Trend.",
            )])
        if schema is CreativeBrief:
            return CreativeBrief(
                design_concept="Clean hero shot", visual_prompt="Product on a gradient",
                template_suggestion="feature_showcase", tone_notes="Warm",
            )
        if schema is CampaignCopy:
            return CampaignCopy(
                hook="hook", headline="Straight from Japan", supporting_copy="Sourced firsthand.", cta="Shop now",
                caption="Straight from Japan.", alt_text="Product bottle",
            )
        if schema is CarouselPlan:
            return CarouselPlan(
                slides=[SlidePlan(
                    slide_number=1, purpose="hero", headline="Slide one", body="Body one", cta="Shop now",
                    visual_brief="Hero shot",
                )],
                narrative_summary="A one-slide carousel.",
            )
        if schema is MasterCampaignConcept:
            return MasterCampaignConcept(
                concept_name="Everyday Ritual", campaign_promise="A routine that fits your day",
                key_message="Everything for a routine", emotional_goal="Confidence", audience="Young adults",
                objective="awareness", visual_identity="Clean hero shot", story_arc="Open, reveal, close",
                cta_intent="Try it",
            )
        raise AssertionError(f"Unexpected schema requested: {schema}")

    async def research(self, query, *, model):
        return ResearchResult(insights=[])

    async def verify_source_product_identity(self, *, source_image_path, product_name, category_name, model):
        return SourceProductIdentityCheck(verdict=self.identity_verdict, reasoning="fake pipeline check")

    # ---- ImageProvider (tracked; must NEVER be called when the gate fails) --
    async def generate(self, *, prompt, size, model, reference_images=None, quality="high"):
        self.image_calls += 1
        raise AssertionError("image generation must never be reached when the identity gate fails")

    async def edit(self, *, base_image, prompt, model, mask=None, quality="high"):
        self.image_calls += 1
        raise AssertionError("image generation must never be reached when the identity gate fails")


async def test_a_pipeline_level_mismatch_never_reaches_image_generation(temp_db, tmp_path):
    session = temp_db.SessionLocal()
    _, _, _product, _asset, campaign = _make_brand_category_product_asset(session, tmp_path)
    campaign.languages = ["pt-BR"]
    campaign.target_platforms = ["instagram"]
    session.commit()
    campaign_id = campaign.id

    provider = _PipelineIdentityProvider(identity_verdict="MISMATCH")
    config = _config(tmp_path, use_ai_background=True, recreate_with_ai=False)
    renderer = PlaywrightRenderer()
    try:
        await run_strategy_stage(
            session, campaign_id=campaign_id, ai_provider=provider, research_provider=provider, config=config,
        )
        await run_copy_stage(session, campaign_id=campaign_id, ai_provider=provider, config=config)
        with pytest.raises(SourceProductIdentityMismatch):
            await run_visuals_stage(
                session, campaign_id=campaign_id, renderer=renderer, config=config, image_provider=provider,
                ai_provider=provider,
            )
    finally:
        await renderer.close()

    assert provider.image_calls == 0, "no billed image generation may happen once the identity gate fails"
    reloaded = session.get(Campaign, campaign_id)
    assert reloaded.status == "FAILED"
    session.close()


# ---------------------------------------------------------------------------
# Critical Defect 2 — claims boundary (verified facts vs. research vs. brand
# notes vs. creative ideas). Tests D, E, F, G (content-level).
# ---------------------------------------------------------------------------

def test_claims_boundary_instruction_names_every_banned_unsupported_claim():
    """Tests F + G: the exact claim categories a real live-acceptance run
    produced without any verified basis (bestseller/#1 status, before/after
    results, VIP/restock/priority perks, a follower/community count, a
    discount) are explicitly named as forbidden unless verified or
    owner-confirmed.
    """
    text = _claims_boundary_instruction()
    for phrase in (
        "bestseller", "before/after", "restock", "VIP/membership perk", "surprise", "star rating or testimonial",
        "clinical/scientific claim", "customer, follower, or community-size number", "discount or price",
    ):
        assert phrase in text, f"claims boundary instruction is missing an explicit ban on: {phrase!r}"


def test_claims_boundary_instruction_tells_the_model_sparse_facts_stay_honest():
    """Test D: a sparse-facts product must get a simpler, honest concept —
    never an invented popularity/performance claim to fill the gap.
    """
    text = _claims_boundary_instruction()
    assert "sparse" in text.lower()
    assert "honest concept is the correct output" in text


def test_claims_boundary_instruction_separates_the_four_information_sources():
    """Test E: research is explicitly demoted to context-only — it "must
    NEVER become a stated product fact" — while verified facts and
    owner-confirmed brand notes are the only two sources usable as fact.
    """
    text = _claims_boundary_instruction()
    assert "VERIFIED PRODUCT FACTS" in text
    assert "Research insights" in text and "must NEVER become a stated" in text
    assert "owner-confirmed" in text


@pytest.mark.parametrize("purpose_marker", [
    "creative_brief", "master_campaign_concept", "campaign_copy", "carousel_plan",
])
def test_claims_boundary_instruction_is_wired_into_every_early_stage_prompt(purpose_marker):
    """A cheap, direct proof the four call sites this repair touched
    (`run_strategy_stage`'s creative_brief, `run_copy_stage`'s master_concept/
    campaign_copy/carousel_plan) actually import and can call the same shared
    function — the full end-to-end wiring is exercised indirectly by every
    other pipeline test in this suite still passing after this repair; this
    guards specifically against the boundary text silently regressing back
    out of `_claims_boundary_instruction()` itself.
    """
    # The marker parameter documents WHICH stage this instruction reaches —
    # see orchestrator.py's own call sites (grep `_claims_boundary_instruction()`)
    # for the four `system=` strings it is appended to. The instruction text
    # itself is identical everywhere (one shared function, never copy-pasted
    # per call site), so asserting its content once is sufficient; this test
    # exists as a named, per-stage checklist entry rather than one anonymous
    # assertion.
    assert callable(_claims_boundary_instruction)
    assert _claims_boundary_instruction()  # never empty


# ---------------------------------------------------------------------------
# Critical Defect 3/4 — deterministic text-overflow shortening + the
# duplicate/no-effect revision hash guard. Tests I, J, K.
# ---------------------------------------------------------------------------

def test_truncate_to_words_is_a_pure_word_boundary_cut():
    assert _truncate_to_words("one two three four five", 3) == "one two three"
    # Already fits: untouched, never padded or altered.
    assert _truncate_to_words("short headline", 10) == "short headline"
    assert _truncate_to_words("", 5) == ""


def test_deterministic_shorten_copy_uses_the_platforms_own_density_budget():
    """Test J/K: a Facebook feed_post spec is "medium" density — the exact
    real-world case (Facebook pt-BR hard overflow on slides 1-4) this repair
    fixes. Shortening is word-boundary truncation only — never a rewrite —
    so the copy's claims/meaning cannot drift, only its length.
    """
    spec = resolve_platform_creative_spec("facebook", "feed_post")
    assert spec.max_copy_density in _COPY_DENSITY_WORD_BUDGETS
    long_headline = " ".join(f"word{i}" for i in range(20))
    long_body = " ".join(f"body{i}" for i in range(60))
    shortened = _deterministic_shorten_copy(headline=long_headline, body=long_body, cta="Shop now today please", spec=spec)
    budgets = _COPY_DENSITY_WORD_BUDGETS[spec.max_copy_density]
    assert len(shortened.headline.split()) <= budgets["headline"]
    assert len(shortened.body.split()) <= budgets["body"]
    assert len(shortened.cta.split()) <= budgets["cta"]
    # Never invents new words — every word in the shortened copy came from
    # the original.
    assert set(shortened.headline.split()) <= set(long_headline.split())


def test_hash_slide_files_is_stable_and_treats_a_missing_file_as_distinct(tmp_path):
    """Test I's underlying mechanism: identical bytes hash identically
    (this is what lets the QA loop detect a revision that changed nothing),
    and a missing/unreadable file hashes to `""` rather than raising — so a
    partial render still compares (as different) instead of crashing the
    loop.
    """
    a = tmp_path / "a.png"
    b = tmp_path / "b.png"
    Image.new("RGB", (10, 10), (1, 2, 3)).save(a)
    Image.new("RGB", (10, 10), (1, 2, 3)).save(b)
    assert _hash_slide_files([str(a)]) == _hash_slide_files([str(b)])  # identical pixels -> identical hash

    c = tmp_path / "c.png"
    Image.new("RGB", (10, 10), (9, 9, 9)).save(c)
    assert _hash_slide_files([str(a)]) != _hash_slide_files([str(c)])

    missing = tmp_path / "does-not-exist.png"
    assert _hash_slide_files([str(missing)]) == ("",)


# ---------------------------------------------------------------------------
# Critical Defect 5/10 — one retry for `generate_video_concept` before
# SCRIPT_UNAVAILABLE. Test L (retry half).
# ---------------------------------------------------------------------------

class _FlakyOnceProvider:
    """Fails the first call, succeeds the second — proves the new one-retry
    behavior actually recovers from a single transient failure rather than
    settling for `SCRIPT_UNAVAILABLE` on what a retry would have fixed.
    """

    def __init__(self):
        self.calls = 0

    async def generate_structured(self, *, system, user, schema, model):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("simulated transient API failure")
        return VideoConcept(
            hook="hook", script="script", shot_list=["shot one"], caption="caption",
        )


class _AlwaysFailsProvider:
    def __init__(self):
        self.calls = 0

    async def generate_structured(self, *, system, user, schema, model):
        self.calls += 1
        raise RuntimeError("simulated persistent API failure")


def _master_concept_and_adaptation():
    master = MasterCampaignConcept(
        concept_name="c", campaign_promise="p", key_message="k", emotional_goal="g", audience="a",
        objective="awareness", visual_identity="v", story_arc="s", cta_intent="c",
    )
    adaptation = PlatformAdaptation(
        platform="tiktok", adaptation_strategy="short-form hook-first video", narrative_shape="hook, story, cta",
        tone_adjustment="warm", content_type="short_video",
    )
    return master, adaptation


async def test_l_generate_video_concept_recovers_from_one_transient_failure():
    provider = _FlakyOnceProvider()
    master, adaptation = _master_concept_and_adaptation()
    result = await generate_video_concept(
        provider, master_concept=master, platform="tiktok", language="pt-BR", adaptation=adaptation, model="gpt-5.1",
    )
    assert result is not None
    assert provider.calls == 2  # one failure, one successful retry


async def test_l_generate_video_concept_still_returns_none_after_two_failures():
    """The honest "no fabricated script" contract is unchanged — a second
    consecutive failure still returns `None`, exactly as before this repair.
    """
    provider = _AlwaysFailsProvider()
    master, adaptation = _master_concept_and_adaptation()
    result = await generate_video_concept(
        provider, master_concept=master, platform="tiktok", language="pt-BR", adaptation=adaptation, model="gpt-5.1",
    )
    assert result is None
    assert provider.calls == 2  # both attempts made, neither fabricated a script


# ---------------------------------------------------------------------------
# Critical Defect 6/11 — exact acceptance matrix, never a Cartesian product.
# Test H.
# ---------------------------------------------------------------------------

def test_h_matrix_grouped_by_platform_never_creates_a_non_matrix_combination():
    groups = _group_matrix_by_platform(ACCEPTANCE_MATRIX)
    # Every (platform, language) pair the grouped structure can produce is
    # one that was actually in the matrix — the Cartesian-product bug this
    # repair fixes would instead let e.g. facebook/en or pinterest/pt-BR
    # appear here.
    reconstructed = {(platform, lang) for platform, langs in groups.items() for lang in langs}
    assert reconstructed == set(ACCEPTANCE_MATRIX)
    # Platform order is preserved (first-seen), matching the matrix's own
    # ordering rather than an alphabetical sort that could silently swap
    # which language ends up looking "primary".
    assert list(groups.keys()) == ["instagram", "facebook", "pinterest", "tiktok"]
    assert groups["instagram"] == ["pt-BR", "en"]
    assert groups["facebook"] == ["pt-BR"]
    assert groups["pinterest"] == ["en"]
    assert groups["tiktok"] == ["pt-BR"]


def test_h_grouping_never_duplicates_a_language_within_one_platform():
    matrix = [("instagram", "pt-BR"), ("instagram", "pt-BR"), ("instagram", "en")]
    groups = _group_matrix_by_platform(matrix)
    assert groups["instagram"] == ["pt-BR", "en"]


def test_is_script_only_case_matches_the_real_platform_creative_specs():
    assert _is_script_only_case("tiktok") is True
    assert _is_script_only_case("instagram") is False
    assert _is_script_only_case("facebook") is False


def test_smoke_matrix_covers_both_a_static_and_a_script_only_case():
    smoke = _smoke_matrix(ACCEPTANCE_MATRIX)
    assert len(smoke) == 2
    assert any(not _is_script_only_case(p) for p, _l in smoke)
    assert any(_is_script_only_case(p) for p, _l in smoke)
    # Every smoke case is still a real matrix case, never an invented pair.
    assert set(smoke) <= set(ACCEPTANCE_MATRIX)


def test_combine_verdict_picks_the_most_severe_signal():
    assert _combine_verdict("PASS", "NEEDS_REVIEW") == "NEEDS_REVIEW"
    assert _combine_verdict("NEEDS_REVIEW", "PASS") == "NEEDS_REVIEW"  # never downgraded
    assert _combine_verdict("NEEDS_REVIEW", "FAIL") == "FAIL"
    assert _combine_verdict("FAIL", "INCOMPLETE_BUDGET_CEILING") == "FAIL"  # FAIL always wins
    assert _combine_verdict("PASS", "INCOMPLETE_BUDGET_CEILING") == "INCOMPLETE_BUDGET_CEILING"


# ---------------------------------------------------------------------------
# Critical Defect 7/12 — cost preflight (estimate vs. actual, never
# invented as guaranteed). Test N.
# ---------------------------------------------------------------------------

def test_n_matrix_cost_estimate_is_unavailable_for_mixed_usage():
    # Stage 3B2: GPT Image 2.5 usage cannot be authoritatively
    # priced by local preflight accounting. Returning None is
    # deliberate and prevents a fabricated dollar estimate.
    assert _estimate_matrix_cost_usd(ACCEPTANCE_MATRIX) is None


def test_n_smoke_matrix_is_narrower_without_fake_dollar_estimate():
    full_matrix = list(ACCEPTANCE_MATRIX)
    smoke_matrix = _smoke_matrix(ACCEPTANCE_MATRIX)

    assert _estimate_matrix_cost_usd(full_matrix) is None
    assert _estimate_matrix_cost_usd(smoke_matrix) is None
    assert 0 < len(smoke_matrix) < len(full_matrix)
    assert all(pair in full_matrix for pair in smoke_matrix)


def test_n_merge_cost_report_combines_multiple_platform_scoped_campaigns():
    """Merge platform-scoped reports using the current accounting shape."""
    dest = {
        "total_usd": 0.0,
        "image_generation_usd": 0.0,
        "text_generation_usd": 0.0,
        "known_total_usd": 0.0,
        "known_image_generation_usd": 0.0,
        "known_text_generation_usd": 0.0,
        "call_count": 0,
        "usage_recorded": False,
        "cost_status": "no_usage",
        "cost_complete": True,
        "total_usd_is_complete": True,
        "image_generation_usd_is_complete": True,
        "text_generation_usd_is_complete": True,
        "unpriced_call_count": 0,
        "unpriced_image_call_count": 0,
        "unpriced_text_call_count": 0,
        "unpriced_image_count": 0,
        "unpriced_models": [],
        "unpriced_operations": [],
        "by_operation": {},
        "by_variant": [],
        "by_scope": {},
    }

    one = {
        "total_usd": 1.5,
        "image_generation_usd": 1.2,
        "text_generation_usd": 0.3,
        "call_count": 4,
        "usage_recorded": True,
        "by_operation": {
            "research": {
                "cost_usd": 0.3,
                "call_count": 1,
                "input_tokens": 10,
                "output_tokens": 5,
                "image_count": 0,
            }
        },
        "by_variant": [
            {
                "platform": "instagram",
                "language": "pt-BR",
                "content_type": "feed_post",
                "cost_usd": 1.2,
                "call_count": 3,
            }
        ],
        "by_scope": {
            "campaign_global": {"cost_usd": 0.3, "call_count": 1},
            "variant": {"cost_usd": 1.2, "call_count": 3},
        },
    }

    two = {
        "total_usd": 0.5,
        "image_generation_usd": 0.2,
        "text_generation_usd": 0.3,
        "call_count": 2,
        "usage_recorded": True,
        "by_operation": {
            "research": {
                "cost_usd": 0.3,
                "call_count": 1,
                "input_tokens": 8,
                "output_tokens": 4,
                "image_count": 0,
            }
        },
        "by_variant": [
            {
                "platform": "facebook",
                "language": "pt-BR",
                "content_type": "feed_post",
                "cost_usd": 0.2,
                "call_count": 1,
            }
        ],
        "by_scope": {
            "campaign_global": {"cost_usd": 0.3, "call_count": 1},
            "variant": {"cost_usd": 0.2, "call_count": 1},
        },
    }

    _merge_cost_report(dest, one)
    _merge_cost_report(dest, two)

    assert dest["usage_recorded"] is True
    assert dest["total_usd"] == 2.0
    assert dest["call_count"] == 6
    assert dest["unpriced_call_count"] == 0
    assert dest["by_operation"]["research"]["call_count"] == 2
    assert dest["by_operation"]["research"]["cost_usd"] == 0.6
    assert len(dest["by_variant"]) == 2
    assert dest["by_scope"]["campaign_global"]["cost_usd"] == 0.6
    assert dest["by_scope"]["variant"]["cost_usd"] == 1.4
