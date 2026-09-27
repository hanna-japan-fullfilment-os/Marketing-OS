"""BUILD 6 — PRODUCTION INTEGRATION + MULTI-PLATFORM HANNA ACCEPTANCE.

Covers the carry-forward spec's numbered requirements, run against the REAL
Strategy -> Copy -> Visuals -> QA -> Review pipeline (never a mocked-out
shortcut), grounded in Hanna's own real, canonical brand/product identity —
see `claude/hanna-gpt-system/01-company-and-service-profile.md` and
`.../02-canonical-product-catalog.md` in the Project docs, which is where
"Hanna From Japan" and "Melano CC Essence" (canonical ID HANNA-PROD-000006)
below come from, rather than an invented placeholder brand/product.

IMPORTANT HONESTY NOTE (read before trusting "LIVE" language anywhere in this
file or the Build 6 completion packet): this whole backend has never made a
real OpenAI network call from inside this development sandbox — there is no
`OPENAI_API_KEY` configured here, and this app is explicitly designed
(`.env.example`'s Windows `SOURCE_ASSET_ROOT`) to run on the OWNER's own PC
against the owner's own key. Every test in this file (and every test in this
whole suite, 324 pre-existing plus these) uses a deterministic FAKE provider,
exactly like `tests/test_build5_repair.py::_FullProvider` and every other
test file in this project. What these tests actually prove is architecture
correctness: the real pipeline code (not a shortcut, not a mock of
`run_strategy_stage`/`run_copy_stage`/`run_visuals_stage`/`run_qa_stage`
themselves) genuinely produces the traceability, reuse, cost-capture, and
review behavior Build 6 asks for, end to end. A genuinely LIVE run (real
OpenAI calls, real cost, real image quality judged by a human) can only
happen on the owner's own machine with their own key — see
`docs/marketing-os-creative-quality-handoff.md` for the runnable script this
build adds for exactly that purpose.

Test-file convention (established by test_build3_qa_engine.py /
test_build5_benchmark.py / test_build5_repair.py): fakes/helpers are
duplicated locally, not imported across test files.
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

from app.data.platform_creative_specs import resolve_platform_creative_spec
from app.models import AIUsage, Asset, Brand, Campaign, Category, Product, ReviewFeedback
from app.schemas.ai import (
    CampaignCopy, CampaignStrategy, CampaignStrategyCandidates, CarouselPlan, CreativeBrief, ProductFidelityCheck,
    ResearchInsightItem, ResearchResult, SlidePlan,
)
from app.schemas.creative_director import CreativeDirection, MasterCampaignConcept, PlatformAdaptation, VideoConcept
from app.schemas.product_facts import VerifiedProductFactsOut
from app.schemas.qa import CreativeCritiqueResult, LanguageQAResult, RevisedCopy, VideoQAResult
from app.services.benchmark_engine import build_creative_system_snapshot
from app.services.creative.renderer import PlaywrightRenderer
from app.services.orchestrator import AutopilotConfig, _resolve_image_model_and_quality, get_platform_campaign_variants, \
    run_copy_stage, run_strategy_stage, run_visuals_stage
from app.services.product_facts import resolve_verified_product_facts
from app.services.qa_engine import run_qa_stage
from app.services.review_engine import apply_requested_revision, record_review_feedback
from app.services.usage_tracking import build_campaign_cost_report


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


def _make_hanna_brand_and_product(session, tmp_path, *, num_assets=2):
    """Real Hanna identity, not an invented placeholder: brand voice/promise
    from `claude/hanna-gpt-system/01-company-and-service-profile.md`, product
    from the canonical catalog's HANNA-PROD-000006 (Melano CC Essence,
    Skincare, campaign-drafting eligible).
    """
    from app.services.seed import seed_strategy_library
    seed_strategy_library(session)

    brand = Brand(
        name="Hanna From Japan", slug=f"hanna-from-japan-{uuid.uuid4().hex[:8]}",
        voice="A real person in Japan helping Brazilians buy authentic Japanese products safely, with "
        "personalized, honest guidance — never a faceless forwarding service.",
        target_countries=["Brazil"], target_audiences=["Brazilians interested in Japanese skincare"],
        preferred_ctas=["Saiba mais", "Fale com a Hanna"],
        disallowed_terms=["cura", "garantido", "milagroso"],
        campaign_rules={"verified_operational_strategy_keys": list(_LEGACY_VERIFIED_OPERATIONAL_STRATEGY_KEYS)},
    )
    session.add(brand)
    session.commit()
    category = Category(brand_id=brand.id, name="Skincare", slug="skincare")
    session.add(category)
    session.commit()
    product = Product(
        brand_id=brand.id, category_id=category.id, name="Melano CC Essence", slug="melano-cc-essence",
        notes="Canonical catalog HANNA-PROD-000006 — identity/category/eligibility only; no formulation "
        "facts asserted here (see the catalog's own rule: do not infer ingredients/claims from the name).",
    )
    session.add(product)
    session.commit()
    for i in range(num_assets):
        img_path = tmp_path / f"melano-{i}.jpg"
        Image.new("RGB", (800, 800), (230, 200 - i * 10, 210)).save(img_path)
        session.add(Asset(
            brand_id=brand.id, category_id=category.id, product_id=product.id, absolute_path=str(img_path),
            relative_path=f"skincare/melano-{i}.jpg", filename=f"melano-{i}.jpg", extension=".jpg",
            sha256=f"melano-sha-{i}", width=800, height=800,
        ))
    session.commit()
    return brand, category, product


class _HannaProvider:
    """Combined AIProvider + ResearchProvider + ImageProvider for the Build 6
    acceptance suite. Returns THE SAME `CreativeDirection` regardless of
    platform/language (mirroring `_FullProvider`'s own design) — this is what
    makes the same-platform pt-BR/en scene-reuse assertion (item 5) exercise
    the REAL cache-matching logic in `_render_additional_platform_variants`
    rather than a contrived shortcut: two independently-requested AI
    generations that happen to describe the identical scene really do share
    one `_scene_signature`.

    `fail_language_for` (platform, language) forces exactly one variant's
    `run_language_qa` result to hard-fail on its first attempt — this is what
    lets a test prove a single failing variant never corrupts its siblings
    (item 3) and that a real failure is reported honestly, never silently
    hidden (item 10).

    `report_usage` makes this provider ALSO implement `drain_usage_events()`,
    returning realistic-shaped (but simulated — see this file's module
    docstring) usage events, so item 6's plumbing (call site ->
    `record_stage_usage` -> `AIUsage` row -> `build_campaign_cost_report`)
    can be proven end to end without a real network call.
    """

    def __init__(self, *, fail_language_for: tuple[str, str] | None = None, report_usage: bool = False):
        self.fail_language_for = fail_language_for
        self._language_attempts: dict[tuple[str, str], int] = {}
        self.report_usage = report_usage
        self._events: list[dict] = []
        self.creative_direction_calls: list[tuple[str, str]] = []
        self.video_concept_calls: list[tuple[str, str]] = []

    def _maybe_report(self, *, model: str, kind: str, count: int = 1) -> None:
        if not self.report_usage:
            return
        if kind == "text":
            self._events.append({
                "provider": "openai", "model": model, "input_tokens": 850, "output_tokens": 320,
                "image_count": 0, "estimated_cost_usd": 0.0042,
            })
        else:
            self._events.append({
                "provider": "openai", "model": model, "input_tokens": 0, "output_tokens": 0,
                "image_count": count, "estimated_cost_usd": 0.042 * count,
            })

    def drain_usage_events(self) -> list[dict]:
        events, self._events = self._events, []
        return events

    async def generate_structured(self, *, system, user, schema, model):
        # Successful semantic scan with no extra factual candidates.
        if getattr(schema, "__name__", "") == "CandidateClaimExtractionResult":
            return schema(claims=[])

        self._maybe_report(model=model, kind="text")
        if schema is CampaignStrategyCandidates:
            return CampaignStrategyCandidates(candidates=[
                CampaignStrategy(
                    objective="awareness", audience="Brazilians interested in Japanese skincare",
                    funnel_stage="tofu", insight="Multi-step Japanese skincare routines are trending in Brazil.",
                    angle="Discover your Japanese skincare routine", key_message="Authentic Japanese skincare, "
                    "sourced firsthand and shipped safely to Brazil.", reason_this_should_work="Rides real,"
                    " cited interest in J-beauty while leaning on Hanna's personal-shopper trust story.",
                )
            ])
        if schema is CreativeBrief:
            return CreativeBrief(
                design_concept="Clean hero shot on a soft studio backdrop", visual_prompt="Product bottle on a "
                "warm gradient, no invented claims on-screen", template_suggestion="feature_showcase",
                tone_notes="Warm, trustworthy, personal",
            )
        if schema is CampaignCopy:
            return CampaignCopy(
                hook="Descubra o skincare japonês", headline="Direto do Japão para você", supporting_copy=(
                    "A Hanna compra pessoalmente no Japão e envia com cuidado para o Brasil."
                ),
                cta="Fale com a Hanna", caption="Direto do Japão para você.", hashtags=["#skincarejapones"],
                alt_text="Melano CC Essence bottle on a soft studio backdrop",
            )
        if schema is CarouselPlan:
            return CarouselPlan(
                slides=[SlidePlan(
                    slide_number=1, purpose="hero", headline="Direto do Japão", body="Comprado pessoalmente.",
                    cta="Fale com a Hanna", visual_brief="Hero shot of the essence bottle",
                )],
                narrative_summary="A one-slide hero carousel.",
            )
        if schema is MasterCampaignConcept:
            return MasterCampaignConcept(
                concept_name="Authentic Japan, Delivered Personally", campaign_promise="Real Japanese skincare,"
                " bought with care", key_message="Authentic Japanese skincare, sourced firsthand.",
                emotional_goal="Trust", audience="Brazilians interested in Japanese skincare", objective="awareness",
                visual_identity="Soft studio backdrop, warm light, product front and center",
                story_arc="Open on the product, reveal the sourcing story, close on the CTA",
                cta_intent="Talk to Hanna",
            )
        if schema is PlatformAdaptation:
            return PlatformAdaptation(
                platform="instagram", adaptation_strategy="single hero image with a personal, trust-forward"
                " caption", narrative_shape="Open, reveal, close", tone_adjustment="warm", content_type="feed_post",
            )
        if schema is VideoConcept:
            self.video_concept_calls.append((system[:0] or "video", "call"))
            return VideoConcept(
                hook="Você sabia que dá pra comprar skincare japonês de verdade?", script=(
                    "A Hanna mora no Japão e compra pessoalmente cada produto antes de enviar para o Brasil."
                ),
                shot_list=["Hanna segurando o produto", "Close no rótulo", "Embalagem pronta para envio"],
                timing="0-3s hook, 4-12s story, 13-15s CTA", visual_direction="Handheld, natural light",
                on_screen_text=["Direto do Japão", "Fale com a Hanna"], caption="Direto do Japão para você.",
                cover_creative_brief="Hanna holding the product, soft daylight",
            )
        if schema is LanguageQAResult:
            # `run_language_qa` (services/qa_engine.py) always builds its
            # `user` string as "Declared language: {language}. Platform:
            # {platform}. ..." — parsed here rather than needing a test-only
            # hook threaded through the real `run_qa_stage` entry point.
            language = user.split("Declared language: ", 1)[1].split(".", 1)[0].strip()
            platform = user.split("Platform: ", 1)[1].split(".", 1)[0].strip()
            return self._language_qa_result(platform=platform, language=language)
        if schema is RevisedCopy:
            return RevisedCopy(headline="Revised headline", body="Revised, more natural body copy.", cta="Shop now")
        if schema is VideoQAResult:
            return VideoQAResult(
                hook_strength=85, script_coherence=88, shot_list_completeness=82, timing_score=80,
                on_screen_text_suitability=84, platform_fit=86, language_naturalness=90, factual_accuracy=90,
                brand_alignment=85, cta_effectiveness=83, hard_fails=[], issues=[],
            )
        if schema is CreativeDirection:
            return CreativeDirection(
                concept_name="Authentic Japan, Delivered Personally",
                background_concept="Soft warm studio backdrop with a folded linen texture",
                lighting="Soft diffused morning light", mood="Calm, trustworthy",
                scene_generation_prompt="Soft warm studio backdrop, folded linen, no text, no logos, no products"
                " other than the one supplied.",
            )
        raise AssertionError(f"Unexpected schema requested: {schema}")

    def _language_qa_result(self, *, platform: str, language: str) -> LanguageQAResult:
        key = (platform, language)
        if self.fail_language_for is not None and key == self.fail_language_for:
            attempts = self._language_attempts.get(key, 0) + 1
            self._language_attempts[key] = attempts
            if attempts == 1:
                return LanguageQAResult(language_naturalness=30, hard_fails=["Unnatural, machine-translated wording."])
        return LanguageQAResult(language_naturalness=92, hard_fails=[])

    async def critique_creative(self, *, image_paths, source_image_path, context, model):
        self._maybe_report(model=model, kind="text")
        return CreativeCritiqueResult(
            overall_quality=88, brand_alignment=85, product_fidelity=85, composition=86,
            carousel_consistency=85, professional_ad_quality=85, platform_fit=87, language_naturalness=88,
            hard_fails=[], rationale="Clean, on-brand studio shot with the real product intact.",
        )

    async def vision_describe(self, *, image_path, prompt, model):
        return ""

    async def research(self, query, *, model):
        self._maybe_report(model=model, kind="text")
        return ResearchResult(insights=[
            ResearchInsightItem(
                statement="Multi-step Japanese ('J-beauty') skincare routines are a growing interest among"
                " Brazilian skincare shoppers.", confidence=0.75, freshness="this_quarter", category="trend",
                recommended_implication="Frame the product as one step in an authentic Japanese routine.",
                source_urls=["https://example.com/j-beauty-brazil-trend-report"],
            )
        ])

    async def discover_opportunities(self, query, *, model):
        raise NotImplementedError

    async def detect_product_zone(self, *, image_path, model):
        raise NotImplementedError

    async def check_product_fidelity(self, *, source_image_path, generated_image_path, model):
        return ProductFidelityCheck(overall_verdict="PASS", reasoning="Matches the real source photo.")

    async def analyze_visual_style(self, *, image_paths, brand_name, model):
        raise NotImplementedError

    # ---- ImageProvider ----------------------------------------------------
    async def generate(self, *, prompt, size, model, reference_images=None, quality="high"):
        self._maybe_report(model=model, kind="image")
        buf = io.BytesIO()
        Image.new("RGB", (64, 64), (220, 200, 210)).save(buf, format="PNG")
        return buf.getvalue()

    async def edit(self, *, base_image, prompt, model, mask=None, quality="high"):
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Item 2 — real Hanna product facts, provenance, and no invented claims.
# ---------------------------------------------------------------------------

def test_verified_product_facts_use_real_hanna_data_with_provenance_and_no_fabrication(temp_db, tmp_path):
    from app.models import VerifiedProductFact

    session = temp_db.SessionLocal()
    brand, category, product = _make_hanna_brand_and_product(session, tmp_path)

    # Only what the canonical catalog itself allows to be stated: identity,
    # category, and country of origin (Japan) — deliberately NO ingredients,
    # benefits, usage, price, or availability, per the catalog's own explicit
    # rule ("Do not infer ingredients, vitamin content, claims... from the
    # name alone"). This is what "no research insight silently becomes a
    # product fact" looks like in practice: real identity in, invented
    # formulation left honestly blank.
    fact = VerifiedProductFact(
        product_id=product.id,
        verified_country_of_origin="Japan",
        source_asset_ids=[],
        source_references=[
            "Hanna canonical product catalog, HANNA-PROD-000006, baseline 2026-08-09 "
            "(claude/hanna-gpt-system/02-canonical-product-catalog.md)",
        ],
        confidence=0.5,  # identity confirmed; formulation/claims unconfirmed — never a falsely reassuring 1.0
        provenance="owner_provided",
    )
    session.add(fact)
    session.commit()

    resolved: VerifiedProductFactsOut = resolve_verified_product_facts(session, product)

    assert resolved.verified_country_of_origin == "Japan"
    assert resolved.provenance == "owner_provided"
    assert resolved.source_references, "provenance must not be empty for a real, owner-confirmed fact"
    # Every field the catalog explicitly forbids inventing is genuinely absent,
    # not filled with a guess:
    assert resolved.verified_ingredients == []
    assert resolved.verified_benefits == []
    assert resolved.verified_usage == ""
    assert resolved.verified_price == ""
    assert resolved.verified_claims == []
    # ...and is reported as MISSING (so a caller/prompt knows to omit it),
    # never silently treated as "nothing to say" — this is exactly the "report
    # the missing field rather than fabricating it" instruction.
    assert "verified_ingredients" in resolved.missing_information
    assert "verified_benefits" in resolved.missing_information
    session.close()


# ---------------------------------------------------------------------------
# Items 1, 3, 5, 9, 10 — cross-platform + bilingual campaign, one shared
# MasterCampaignConcept, real CreativeDirection AI path, scene reuse, live
# traceability, and an honestly-reported failing variant.
# ---------------------------------------------------------------------------

async def test_cross_platform_bilingual_campaign_variants_are_independent_and_traceable(
    temp_db, tmp_path, variant_renderer,
):
    session = temp_db.SessionLocal()
    brand, category, product = _make_hanna_brand_and_product(session, tmp_path)
    campaign = Campaign(
        display_id=f"HANNA-SKIN-{uuid.uuid4().hex[:8]}", brand_id=brand.id, category_id=category.id,
        product_id=product.id, objective="awareness", status="IDEA",
        languages=["pt-BR", "en"], target_platforms=["instagram", "facebook"],
    )
    session.add(campaign)
    session.commit()
    campaign_id = campaign.id

    # Facebook/en is the one variant this run forces to fail language QA on
    # its first attempt — proving item 3's "one failing variant does not
    # incorrectly fail or overwrite sibling variants" against REAL sibling
    # variants, not a contrived stand-in.
    provider = _HannaProvider(fail_language_for=("facebook", "en"), report_usage=True)
    config = _config(tmp_path, use_ai_background=True, recreate_with_ai=False, qa_max_retries=1, qa_best_of_n=1)

    await run_strategy_stage(
        session, campaign_id=campaign_id, ai_provider=provider, research_provider=provider, config=config,
    )
    await run_copy_stage(session, campaign_id=campaign_id, ai_provider=provider, config=config)
    await run_visuals_stage(
        session, campaign_id=campaign_id, renderer=variant_renderer, config=config, image_provider=provider,
        ai_provider=provider,
    )

    variants = get_platform_campaign_variants(session, campaign_id)
    combos = {(v.target_platform, v.language) for v in variants}
    assert combos == {("instagram", "pt-BR"), ("instagram", "en"), ("facebook", "pt-BR"), ("facebook", "en")}
    assert all(v.status == "RENDERED" for v in variants), "every static combo should have rendered"

    by_combo = {(v.target_platform, v.language): v for v in variants}
    # Item 1: CreativeDirection's real AI-generation path fires for every
    # NON-primary combo (primary = instagram/pt-BR, per Build 5 repair's own
    # documented architectural discovery that the primary combo never sets
    # creative_direction) — never a fabricated/empty dict for those three.
    primary_direction = by_combo[
        ("instagram", "pt-BR")
    ].creative_direction

    assert primary_direction
    assert primary_direction.get(
        "scene_generation_prompt"
    )
    assert (
        "headline/body/CTA copy rendered by the AI"
        in primary_direction.get(
            "prohibited_elements",
            [],
        )
    )
    for combo in [("instagram", "en"), ("facebook", "pt-BR"), ("facebook", "en")]:
        assert by_combo[combo].creative_direction, f"{combo} should have AI-generated CreativeDirection on file"

    # Item 5: Facebook/en's scene should REUSE Facebook/pt-BR's — same
    # platform, identical `_scene_signature` (this fake returns the same
    # CreativeDirection regardless of language), never a second paid
    # generation just because the language changed.
    assert by_combo[("facebook", "en")].shared_scene_source, (
        "facebook/en should have reused facebook/pt-BR's already-generated scene"
    )
    assert by_combo[("facebook", "pt-BR")].shared_scene_source == "", (
        "facebook/pt-BR is the one that generated the scene facebook/en reused"
    )

    # Item 6 (usage capture wiring, exercised here since this is already a
    # real multi-stage pipeline run): every stage's real generation call
    # produced an `AIUsage` row, attributed with real operation/platform/
    # language, and the cost report aggregates them.
    usage_rows = session.query(AIUsage).filter(AIUsage.campaign_id == campaign_id).all()
    assert usage_rows, "no AIUsage rows were recorded despite a provider reporting usage"
    operations = {r.operation for r in usage_rows}
    assert {"research", "strategy", "campaign_copy", "scene_generation", "platform_adaptation"} <= operations
    report = build_campaign_cost_report(session, campaign_id)
    assert report["usage_recorded"] is True
    assert report["total_usd"] > 0
    assert report["by_operation"]
    assert report["by_variant"]

    # Now QA every variant independently (item 3's own QA requirement + item
    # 10's "do not hide a real failure").
    await run_qa_stage(
        session, campaign_id=campaign_id, renderer=variant_renderer, config=config, image_provider=provider,
        ai_provider=provider,
    )
    session.commit()
    variants = get_platform_campaign_variants(session, campaign_id)
    by_combo = {(v.target_platform, v.language): v for v in variants}

    # Sibling variants were completely unaffected by facebook/en's forced
    # first-attempt failure — each has its OWN independent qa_status/qa_scores.
    for combo in [("instagram", "pt-BR"), ("instagram", "en"), ("facebook", "pt-BR")]:
        assert by_combo[combo].qa_status == "PASS", f"{combo} should have passed QA independently"
    # facebook/en genuinely failed attempt 1 then recovered via a real targeted
    # copy revision (qa_max_retries=1 gives it exactly one more try) — this
    # must show up as real evidence, not be silently smoothed over.
    fb_en = by_combo[("facebook", "en")]
    assert fb_en.qa_attempts >= 2, "facebook/en should have needed a real retry, not passed on the first try"
    assert len(fb_en.qa_evidence_paths) >= 2, "both the failing and the recovered attempt's evidence must be kept"
    # The honest, non-hidden outcome: it is reported for what actually
    # happened. This run's revision is expected to recover it (item 10 is
    # about never MISREPORTING an outcome, not about every retry succeeding —
    # a NEEDS_REVIEW would be equally acceptable and must never be silently
    # promoted to PASS without a genuinely passing rescore).
    assert fb_en.qa_status in ("PASS", "NEEDS_REVIEW")
    if fb_en.qa_status == "PASS":
        assert not fb_en.qa_hard_fails
    else:
        assert fb_en.qa_hard_fails, "a NEEDS_REVIEW variant must carry its real hard-fail reasons, never a bare status"

    # Item 9: live prompt + creative-system traceability, verified as
    # POPULATED EVIDENCE from this real (non-benchmark) pipeline run — not a
    # bare assertion that the database columns exist. `build_creative_system_
    # snapshot` needs no BenchmarkRun; it reads back the real AuditEvent
    # usage trail this actual run just wrote.
    snapshot = build_creative_system_snapshot(
        session, campaign_id=campaign_id, platform="facebook", language="en", content_type="feed_post",
        quality_mode=config.quality_mode,
    )
    pv = snapshot["prompt_versions"]
    # `platform_adaptation`/`creative_direction`/`scene_generation` are
    # recorded per-TARGET-platform (see their own `record_prompt_usage` call
    # sites in services/orchestrator.py), so they show up when queried with
    # facebook/en specifically.
    for purpose in ("platform_adaptation", "creative_direction", "scene_generation"):
        assert purpose in pv and pv[purpose] not in ("", "unknown", None), (
            f"{purpose} version should be traceable from this real run's own usage trail"
        )
    # `master_campaign_concept`/`campaign_copy` are campaign-wide/per-LANGUAGE
    # concepts generated once and held constant across every platform (see
    # `run_copy_stage`'s own docstring) — `record_prompt_usage` tags them with
    # the PRIMARY platform they happened to run under, not every platform
    # that later reuses them, so tracing them back needs the primary
    # platform/language, not facebook/en specifically. Still real, populated
    # evidence from this exact run — never "unknown"/absent.
    primary_snapshot = build_creative_system_snapshot(
        session, campaign_id=campaign_id, platform="instagram", language="pt-BR", content_type="feed_post",
        quality_mode=config.quality_mode,
    )
    primary_pv = primary_snapshot["prompt_versions"]
    for purpose in ("master_campaign_concept", "campaign_copy"):
        assert purpose in primary_pv and primary_pv[purpose] not in ("", "unknown", None), (
            f"{purpose} version should be traceable from this real run's own usage trail"
        )
    assert snapshot["verified_product_facts_resolver_version"]
    assert snapshot["renderer_version"]
    assert snapshot["template_version"]
    assert snapshot["qa_rubric_version"]
    assert snapshot["platform"] == "facebook" and snapshot["language"] == "en"

    session.close()



# ---------------------------------------------------------------------------
# Item 4 — a video-oriented platform is represented honestly: script/
# storyboard/cover only, QA judges the right dimensions, never a claim of
# rendered-video fidelity.
# ---------------------------------------------------------------------------

async def test_video_platform_is_represented_as_script_never_as_rendered_video(temp_db, tmp_path, variant_renderer):
    session = temp_db.SessionLocal()
    brand, category, product = _make_hanna_brand_and_product(session, tmp_path)
    campaign = Campaign(
        display_id=f"HANNA-SKIN-{uuid.uuid4().hex[:8]}", brand_id=brand.id, category_id=category.id,
        product_id=product.id, objective="awareness", status="IDEA",
        languages=["pt-BR"], target_platforms=["instagram", "tiktok"],
    )
    session.add(campaign)
    session.commit()
    campaign_id = campaign.id

    provider = _HannaProvider()
    config = _config(tmp_path, use_ai_background=True)
    await run_strategy_stage(
        session, campaign_id=campaign_id, ai_provider=provider, research_provider=provider, config=config,
    )
    await run_copy_stage(session, campaign_id=campaign_id, ai_provider=provider, config=config)
    await run_visuals_stage(
        session, campaign_id=campaign_id, renderer=variant_renderer, config=config, image_provider=provider,
        ai_provider=provider,
    )

    variants = get_platform_campaign_variants(session, campaign_id)
    tiktok_variant = next(v for v in variants if v.target_platform == "tiktok")
    spec = resolve_platform_creative_spec("tiktok", tiktok_variant.content_type)
    assert spec.supports_static is False, "tiktok's default content type must be a script-only, video-oriented one"

    assert tiktok_variant.status == "SCRIPT_ONLY"
    assert tiktok_variant.render_format_key == ""
    assert tiktok_variant.slide_asset_paths == []
    assert tiktok_variant.video_concept, "a script-only variant must have a real VideoConcept on file"
    assert tiktok_variant.video_concept["is_rendered_video"] is False
    assert tiktok_variant.video_concept["hook"] and tiktok_variant.video_concept["script"]
    assert tiktok_variant.video_concept["shot_list"]

    await run_qa_stage(
        session, campaign_id=campaign_id, renderer=variant_renderer, config=config, image_provider=provider,
        ai_provider=provider,
    )
    session.commit()
    session.refresh(tiktok_variant)

    video_scores = tiktok_variant.qa_scores["video"]
    for dimension in (
        "hook_strength", "script_coherence", "shot_list_completeness", "timing_score",
        "on_screen_text_suitability", "platform_fit", "language_naturalness", "cta_effectiveness",
    ):
        assert dimension in video_scores
    # Never a rendered-video fidelity claim: no technical (static-image) QA
    # block, and no fabricated video-motion/rendered-fidelity score field.
    assert tiktok_variant.qa_scores.get("technical") is None
    assert "video_fidelity" not in video_scores and "motion_quality" not in video_scores
    session.close()


# ---------------------------------------------------------------------------
# Item 7 — DRAFT / STANDARD / PREMIUM quality modes behave materially
# differently (configuration-level, per the spec's own explicit allowance).
# ---------------------------------------------------------------------------

def test_quality_modes_resolve_to_materially_different_configuration(tmp_path):
    draft = _config(tmp_path, quality_mode="draft", image_model="gpt-image-1", draft_image_model="gpt-image-1-mini")
    standard = _config(tmp_path, quality_mode="standard", image_model="gpt-image-1")
    premium = _config(
        tmp_path, quality_mode="premium", image_model="gpt-image-1", premium_image_model="gpt-image-1-hd",
        qa_best_of_n=2, qa_max_retries=3,
    )

    assert _resolve_image_model_and_quality(draft) == ("gpt-image-1-mini", "low")
    assert _resolve_image_model_and_quality(standard) == ("gpt-image-1", "high")
    assert _resolve_image_model_and_quality(premium) == ("gpt-image-1-hd", "high")

    # DRAFT never does unnecessary candidate generation — a plain default
    # config's own best-of-n stays at the pre-Build-2 single-candidate value.
    assert draft.qa_best_of_n == 1
    # PREMIUM's "may use stricter QA or additional candidate/revision
    # behavior where implemented" is a caller-configured knob on this exact
    # same AutopilotConfig (`qa_best_of_n`/`qa_max_retries`), not an automatic
    # side effect of `quality_mode="premium"` alone — documented honestly in
    # docs/marketing-os-creative-quality-handoff.md rather than claiming an
    # automatic linkage this codebase doesn't actually have.
    assert premium.qa_best_of_n > standard.qa_best_of_n
    assert premium.qa_max_retries > standard.qa_max_retries


# ---------------------------------------------------------------------------
# Item 8 — human review end to end: generation -> QA -> human review ->
# REQUEST_REVISION -> targeted revision -> QA rerun -> APPROVE, with full
# history intact.
# ---------------------------------------------------------------------------

async def test_human_review_end_to_end_preserves_full_history(temp_db, tmp_path, variant_renderer):
    session = temp_db.SessionLocal()
    brand, category, product = _make_hanna_brand_and_product(session, tmp_path)
    campaign = Campaign(
        display_id=f"HANNA-SKIN-{uuid.uuid4().hex[:8]}", brand_id=brand.id, category_id=category.id,
        product_id=product.id, objective="awareness", status="IDEA",
        languages=["pt-BR"], target_platforms=["instagram"],
    )
    session.add(campaign)
    session.commit()
    campaign_id = campaign.id

    provider = _HannaProvider()
    config = _config(tmp_path, qa_max_retries=0)  # QA passes clean; the human is the one asking for a revision here
    await run_strategy_stage(
        session, campaign_id=campaign_id, ai_provider=provider, research_provider=provider, config=config,
    )
    await run_copy_stage(session, campaign_id=campaign_id, ai_provider=provider, config=config)
    await run_visuals_stage(
        session, campaign_id=campaign_id, renderer=variant_renderer, config=config, image_provider=provider,
        ai_provider=provider,
    )
    await run_qa_stage(
        session, campaign_id=campaign_id, renderer=variant_renderer, config=config, image_provider=provider,
        ai_provider=provider,
    )
    session.commit()

    variant = get_platform_campaign_variants(session, campaign_id)[0]
    assert variant.qa_status == "PASS"
    original_qa_overall = variant.qa_scores["overall"]
    campaign = session.get(Campaign, campaign_id)

    # The owner's OWN separate review verdict — a genuinely different concept
    # from `qa_status` above (Build 4 carry-forward requirement 4): a QA PASS
    # can still get a human REQUEST_REVISION.
    request_feedback = record_review_feedback(
        session, campaign=campaign, variant=variant, level="PLATFORM_VARIANT", action="REQUEST_REVISION",
        reason_code="unnatural_portuguese", reason_text="The copy reads a bit stiff — make it warmer.",
    )
    session.commit()
    assert variant.human_review_status == "REVISION_REQUESTED"

    revised_variant = await apply_requested_revision(
        session, campaign=campaign, variant=variant, feedback=request_feedback, config=config,
        renderer=variant_renderer, image_provider=provider, ai_provider=provider,
    )
    session.commit()
    assert revised_variant.human_review_status == "PENDING", "a revision awaits a fresh owner look, never auto-approved"

    # QA rerun on the revised asset.
    await run_qa_stage(
        session, campaign_id=campaign_id, renderer=variant_renderer, config=config, image_provider=provider,
        ai_provider=provider,
    )
    session.commit()
    session.refresh(revised_variant)
    new_qa_overall = revised_variant.qa_scores["overall"]

    approve_feedback = record_review_feedback(
        session, campaign=campaign, variant=revised_variant, level="PLATFORM_VARIANT", action="APPROVE",
    )
    session.commit()
    assert revised_variant.human_review_status == "APPROVED"

    # The system can answer every question item 8 names:
    history = (
        session.query(ReviewFeedback)
        .filter(ReviewFeedback.platform_campaign_variant_id == variant.id)
        .order_by(ReviewFeedback.created_at.asc())
        .all()
    )
    assert [h.action for h in history] == ["REQUEST_REVISION", "APPROVE"]
    assert history[0].reason_text == "The copy reads a bit stiff — make it warmer."  # why revision was requested
    assert approve_feedback.revision_of_feedback_id == request_feedback.id  # lineage: this approval answers that request
    assert original_qa_overall is not None and new_qa_overall is not None  # old QA score / new QA score both on file
    assert len(revised_variant.qa_evidence_paths) >= 2  # what changed is inspectable at every attempt
    session.close()
