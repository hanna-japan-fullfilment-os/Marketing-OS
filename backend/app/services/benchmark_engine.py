"""Build 5 — GOLDEN BENCHMARK + PROMPT REGISTRY + MULTI-PLATFORM REGRESSION.

Deliberately reuses 100% of the existing, already-tested pipeline
(`orchestrator.run_strategy_stage` / `run_copy_stage` / `run_visuals_stage`
and `qa_engine.run_qa_stage`) rather than building a second, parallel
generation path for benchmarking — a benchmark run IS a real (throwaway)
campaign run, just against a fixed, curated `BenchmarkCase` instead of a
brand-new idea, with every version/cost/score fact it produces frozen onto
one `BenchmarkRun` row afterward.

Four responsibilities, matching the spec's own Parts:

- `curate_benchmark_case` (Part B / carry-forward requirement 7) — the ONLY
  way a `BenchmarkCase` row is ever created. Never automatic from a plain
  APPROVE/REJECT action; optionally derived from one specific `ReviewFeedback`
  row (`source_feedback_id`), copying its immutable snapshot rather than
  joining to it live.
- `run_benchmark_case` (Part C/F) — executes the real pipeline under one of
  four `BENCHMARK_TEST_MODES` and freezes a `BenchmarkRun`. `OFFLINE` uses a
  built-in zero-network stand-in provider (`_OfflineProvider`) rather than a
  bare `None`, since Strategy/Copy generation in this codebase always
  requires a real `ai_provider.generate_structured` call — only Visuals/QA
  are AI-optional by construction.
- `compare_runs` / `build_regression_report` (Part E/G) — diff two runs, and
  roll many comparisons up by platform AND independently by language, so one
  language's improvement never hides another's regression.
- `compute_owner_agreement_report` (carry-forward requirement 5) — reads
  `ReviewFeedback.reviewed_qa_status` (the frozen snapshot, never today's
  live `qa_status`) against `ReviewFeedback.action` to surface QA/owner
  calibration gaps as plain counts, never a fabricated accuracy percentage.
"""
from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import replace

from sqlalchemy.orm import Session

from ..data.benchmark_scoring import compute_platform_weighted_score
from ..models import (
    BenchmarkCase, BenchmarkRun, BENCHMARK_CASE_STATUSES, BENCHMARK_TEST_MODES, Campaign,
    CampaignFingerprint, PlatformCampaignVariant, Product, ReviewFeedback,
)
from ..schemas.ai import CampaignCopy, CampaignStrategy, CampaignStrategyCandidates, CarouselPlan, CreativeBrief, \
    ResearchResult, SlidePlan
from ..schemas.creative_director import MasterCampaignConcept, PlatformAdaptation
from ..schemas.product_facts import VerifiedProductFactsOut
from ..schemas.qa import CreativeCritiqueResult, LanguageQAResult
from .ai.base import AIProvider, ImageProvider
from .creative.renderer import RENDERER_VERSION, PlaywrightRenderer
from .creative.templates import TEMPLATE_REGISTRY_VERSION
from .feedback_selector import snapshot_prompt_versions
from .orchestrator import AutopilotConfig, get_platform_campaign_variants, run_copy_stage, run_strategy_stage, \
    run_visuals_stage
from .product_facts import VERIFIED_PRODUCT_FACTS_RESOLVER_VERSION, resolve_verified_product_facts
from .qa_engine import QA_RUBRIC_VERSION, run_qa_stage
from .usage_tracking import build_campaign_cost_report

TEST_MODES = BENCHMARK_TEST_MODES
CASE_STATUSES = BENCHMARK_CASE_STATUSES


class _OfflineProvider:
    """`BENCHMARK_TEST_MODES == "OFFLINE"`'s own zero-network stand-in.

    Only `run_visuals_stage`/`qa_engine.run_qa_stage` are genuinely AI-
    optional by construction in this codebase (a `None` `ai_provider` falls
    back to deterministic output — see their own docstrings). `run_strategy_
    stage`/`run_copy_stage` are NOT: both unconditionally call `ai_provider.
    generate_structured(...)` for `CampaignStrategyCandidates`/`CreativeBrief`
    /`CampaignCopy`/`CarouselPlan`/`MasterCampaignConcept` with no fallback
    path, so `OFFLINE` mode cannot simply pass `None` through without
    crashing. This class is what makes `OFFLINE` genuinely free instead:
    every method is pure Python, makes no network call of any kind, and
    returns simple, honest, non-fabricated structured values built only from
    generic scaffolding — never a marketing claim, statistic, or fact this
    app doesn't actually have.
    """

    async def generate_structured(self, *, system, user, schema, model):
        if schema is CampaignStrategyCandidates:
            return CampaignStrategyCandidates(candidates=[
                CampaignStrategy(
                    objective="awareness", audience="General audience", funnel_stage="tofu",
                    insight="No AI research available in OFFLINE mode.", angle="Baseline angle",
                    key_message="Baseline key message", reason_this_should_work="OFFLINE deterministic baseline.",
                )
            ])
        if schema is CreativeBrief:
            return CreativeBrief(
                design_concept="Baseline product hero shot", visual_prompt="Product on a plain background",
                template_suggestion="feature_showcase", tone_notes="Neutral",
            )
        if schema is CampaignCopy:
            return CampaignCopy(
                hook="", headline="Baseline headline", supporting_copy="", cta="Learn more", caption="",
                hashtags=[], alt_text="Product photo",
            )
        if schema is CarouselPlan:
            return CarouselPlan(
                slides=[SlidePlan(slide_number=1, purpose="hero", headline="Baseline headline", body="",
                                   cta="Learn more", visual_brief="Product hero shot")],
                narrative_summary="OFFLINE deterministic single-slide baseline.",
            )
        if schema is MasterCampaignConcept:
            return MasterCampaignConcept(
                concept_name="Baseline concept", campaign_promise="", key_message="Baseline key message",
                emotional_goal="", audience="General audience", objective="awareness", visual_identity="",
                story_arc="", cta_intent="",
            )
        if schema is PlatformAdaptation:
            return PlatformAdaptation(
                platform="", adaptation_strategy="OFFLINE deterministic baseline — no platform adaptation call made.",
                narrative_shape="", tone_adjustment="", content_type="",
            )
        if schema is LanguageQAResult:
            return LanguageQAResult(language_naturalness=0, hard_fails=[], notes="OFFLINE mode — not AI-scored.")
        raise AssertionError(f"_OfflineProvider was asked for an unexpected schema: {schema}")

    async def research(self, query, *, model):
        return ResearchResult(insights=[])

    async def critique_creative(self, *, image_paths, source_image_path, context, model):
        return CreativeCritiqueResult(rationale="OFFLINE mode — not AI-scored.")

    async def vision_describe(self, *, image_path, prompt, model):
        return ""

    async def analyze_visual_style(self, *, image_paths, brand_name, model):
        raise NotImplementedError("_OfflineProvider does not support visual-style analysis.")

    async def detect_product_zone(self, *, image_path, model):
        raise NotImplementedError("OFFLINE mode never enables detect_product_zone.")

    async def check_product_fidelity(self, *, source_image_path, generated_image_path, model):
        raise NotImplementedError("OFFLINE mode never enables recreate_with_ai.")

# Every named model-role field this app resolves per run (Build 2, Part D) —
# frozen onto `BenchmarkRun.model_role_snapshot` (Part F: "model-role
# configuration" is one of the things a benchmark run must snapshot).
_MODEL_ROLE_FIELDS = (
    "strategy_model", "copy_model", "platform_adapter_model", "creative_director_model", "draft_image_model",
    "premium_image_model", "creative_qa_model", "revision_model",
)


def build_creative_system_snapshot(
    db: Session, *, campaign_id: str, platform: str, language: str, content_type: str, quality_mode: str,
) -> dict:
    """Build 5 repair (Part 2) — the COMPLETE, immutable creative-system
    identity for one `BenchmarkRun`, answering "what exact generation system
    produced run X?" from ONE frozen field, never from today's live,
    possibly-since-changed configuration.

    Combines `snapshot_prompt_versions` (Build 1/3/4's existing best-effort
    read-back of every `AuditEvent(entity_type="campaign_prompt_usage")` row
    for this campaign — already covers VerifiedProductFacts-adjacent copy/
    strategy prompts, `master_campaign_concept`, `platform_adaptation`,
    `creative_direction`, `video_concept`, the new `scene_generation` recipe
    (repair Part 1), every QA-critique purpose, AND, critically, whichever
    TARGETED REVISION purpose actually fired for this run — e.g.
    `targeted_copy_revision` shows up as its own key alongside `campaign_copy`
    the moment a revision happens, never silently folded into or overwriting
    the original purpose's version, per repair Part 4) with the version
    identities that mechanism doesn't cover on its own: the Verified Product
    Facts resolver, the renderer, and the template/layout system — plus this
    run's own platform/language/content_type/quality_mode identity.

    Deliberately does NOT duplicate `model_role_snapshot` (its own
    `BenchmarkRun` column already answers "which model per role") — repair
    Part 2's own "do not unnecessarily duplicate large blobs" instruction.
    """
    prompt_versions = snapshot_prompt_versions(db, campaign_id=campaign_id, platform=platform, language=language)
    return {
        "prompt_versions": prompt_versions,
        "verified_product_facts_resolver_version": VERIFIED_PRODUCT_FACTS_RESOLVER_VERSION,
        "renderer_version": RENDERER_VERSION,
        "template_version": TEMPLATE_REGISTRY_VERSION,
        "qa_rubric_version": QA_RUBRIC_VERSION,
        "platform": platform,
        "language": language,
        "content_type": content_type,
        "quality_mode": quality_mode,
    }


def curate_benchmark_case(
    db: Session, *, brand_id: str, platform: str, content_type: str, language: str, objective: str = "",
    audience: str = "", product_id: str | None = None, category_id: str | None = None,
    source_asset_paths: list[str] | None = None, expected_truths: list[str] | None = None,
    prohibited_claims: list[str] | None = None, expected_creative_characteristics: list[str] | None = None,
    name: str = "", notes: str = "", status: str = "ACTIVE", source_feedback_id: str | None = None,
) -> BenchmarkCase:
    """Part B + carry-forward requirement 7's own "provide controlled
    curation/designation of benchmark examples" — this is the ONE function
    in this codebase that ever inserts a `BenchmarkCase` row; nothing here is
    ever triggered automatically by a `ReviewFeedback` write.

    When `source_feedback_id` is given, `owner_rating` and `baseline_output_
    snapshot` are copied from that feedback row's own immutable `reviewed_*`
    snapshot (never a live join, never a mutation of the feedback row itself
    — carry-forward requirement 3's own discipline, applied here too).
    """
    if status not in CASE_STATUSES:
        raise ValueError(f"status must be one of {CASE_STATUSES}, got {status!r}.")

    verified_facts_snapshot: dict = {}
    if product_id:
        product = db.get(Product, product_id)
        if product is not None:
            facts: VerifiedProductFactsOut = resolve_verified_product_facts(db, product)
            verified_facts_snapshot = facts.model_dump()

    owner_rating = ""
    baseline_output_snapshot: dict = {}
    if source_feedback_id:
        feedback = db.get(ReviewFeedback, source_feedback_id)
        if feedback is not None:
            owner_rating = {"APPROVE": "APPROVED", "REJECT": "REJECTED", "REQUEST_REVISION": "REVISION_REQUESTED"}.get(
                feedback.action, ""
            )
            baseline_output_snapshot = {
                "slide_asset_paths": list(feedback.reviewed_slide_asset_paths or []),
                "video_concept": dict(feedback.reviewed_video_concept) if feedback.reviewed_video_concept else None,
                "copy_snapshot": dict(feedback.reviewed_copy_snapshot or {}),
                "creative_direction": dict(feedback.reviewed_creative_direction or {}),
                "qa_status": feedback.reviewed_qa_status,
                "qa_scores": dict(feedback.reviewed_qa_scores) if feedback.reviewed_qa_scores else None,
                "prompt_versions": dict(feedback.reviewed_prompt_versions or {}),
            }

    case = BenchmarkCase(
        name=name, notes=notes, status=status, brand_id=brand_id, product_id=product_id, category_id=category_id,
        platform=platform, content_type=content_type, language=language, objective=objective, audience=audience,
        source_asset_paths=list(source_asset_paths or []), verified_product_facts_snapshot=verified_facts_snapshot,
        expected_truths=list(expected_truths or []), prohibited_claims=list(prohibited_claims or []),
        expected_creative_characteristics=list(expected_creative_characteristics or []),
        baseline_output_snapshot=baseline_output_snapshot, owner_rating=owner_rating,
        source_feedback_id=source_feedback_id,
    )
    db.add(case)
    db.commit()
    db.refresh(case)
    return case


def _smoke_config(config: AutopilotConfig) -> AutopilotConfig:
    """LOW_COST_SMOKE's own cost-limiting overrides — a real provider is
    still used (so this isn't free), but every expensive knob this app has
    (AI background generation, full AI recreation, multi-slide carousels, QA
    retries) is turned off/down, keeping the call count small. `render_
    platform_variants` deliberately stays `True` (never disabled) — a
    benchmark case always targets exactly one platform and one language, so
    `_render_additional_platform_variants` costs exactly one extra cheap
    `PlatformAdaptation` text call here, and it's the only code path that
    actually creates the `PlatformCampaignVariant` row this run needs to
    score at all (disabling it would leave nothing for QA to evaluate).
    """
    return replace(
        config, use_ai_background=False, recreate_with_ai=False, detect_product_zone=False, max_slides=1,
        qa_max_retries=0, qa_best_of_n=1,
    )


def _cost_breakdown_for_campaign(db: Session, campaign_id: str | None) -> dict:
    """Part 10 — "where usage information is available." `AIUsage` rows are
    written by `services/ai/openai_provider.py` per real API call (Build 6
    finally wires this up end to end — see `services/usage_tracking.py` for
    the full mechanism); this is honestly `{totals: 0, ...}` when none exist
    yet for this campaign (e.g. every OFFLINE run, or a campaign run entirely
    with fake/test providers) rather than a fabricated estimate — never claim
    a cost this app didn't actually record.

    Kept as a thin wrapper (rather than inlining) so every pre-existing
    reference to this exact name in this file, `app/api/benchmarks.py`, and
    `tests/test_build5_benchmark.py` keeps working unchanged — the real body
    now lives in `services/usage_tracking.py::build_campaign_cost_report`,
    extended with the per-operation/per-variant breakdown carry-forward
    requirement 6 asks for, rather than duplicated here.
    """
    return build_campaign_cost_report(db, campaign_id)


async def run_benchmark_case(
    db: Session, *, case: BenchmarkCase, config: AutopilotConfig, mode: str, renderer: PlaywrightRenderer,
    ai_provider: AIProvider | None = None, research_provider=None, image_provider: ImageProvider | None = None,
    is_baseline: bool = False,
) -> BenchmarkRun:
    """Part C/F: runs the real pipeline (Strategy -> Copy -> Visuals -> QA)
    against `case`'s own fixed identity, under one of `TEST_MODES`, and
    freezes the result onto a new `BenchmarkRun`.

    - `OFFLINE` — ALWAYS uses the internal `_OfflineProvider` (see that
      class's own docstring for why a bare `None` would crash `run_strategy_
      stage`/`run_copy_stage`), ignoring whatever `ai_provider`/`research_
      provider`/`image_provider` the caller passed — a genuinely zero-
      network, zero-cost run every time, Build 5 test 9's own requirement.
    - `MOCK` — the caller's own fake provider(s) (a test's canned responses),
      used exactly as given; never forced to `None`.
    - `LOW_COST_SMOKE` — a real provider, `config` narrowed by `_smoke_
      config` to the cheapest possible real run (one slide, no AI images,
      no retries).
    - `LIVE_FULL` — a real provider, `config` used exactly as given.
    """
    if mode not in TEST_MODES:
        raise ValueError(f"mode must be one of {TEST_MODES}, got {mode!r}.")

    if mode == "OFFLINE":
        offline = _OfflineProvider()
        ai_provider = offline
        research_provider = offline
        image_provider = None
    elif mode == "MOCK":
        if ai_provider is None:
            raise ValueError("MOCK mode requires a caller-supplied fake ai_provider.")
        research_provider = research_provider or ai_provider
    else:  # LOW_COST_SMOKE | LIVE_FULL
        if ai_provider is None:
            raise ValueError(f"{mode} mode requires a real ai_provider.")
        research_provider = research_provider or ai_provider
        if mode == "LOW_COST_SMOKE":
            config = _smoke_config(config)

    campaign = Campaign(
        display_id=f"BENCH-{case.id[:8]}-{uuid.uuid4().hex[:8]}", brand_id=case.brand_id,
        category_id=case.category_id, product_id=case.product_id, objective=case.objective or "awareness",
        status="IDEA", languages=[case.language], target_platforms=[case.platform],
    )
    db.add(campaign)
    db.commit()

    await run_strategy_stage(
        db, campaign_id=campaign.id, ai_provider=ai_provider, research_provider=research_provider, config=config,
    )
    await run_copy_stage(db, campaign_id=campaign.id, ai_provider=ai_provider, config=config)
    await run_visuals_stage(
        db, campaign_id=campaign.id, renderer=renderer, config=config, image_provider=image_provider,
        ai_provider=ai_provider,
    )
    # A benchmark case is deliberately RE-RUN against the same fixed inputs
    # over and over (that's the whole point of a regression comparison) —
    # `run_visuals_stage` persists a `CampaignFingerprint` for real campaigns
    # so the Strategy stage's novelty guard can reject a genuinely repeated
    # idea; that guard would otherwise reject every second-and-later
    # benchmark run of the SAME case as an "exact repeat" of its own prior
    # run. A benchmark's own throwaway campaigns were never real marketing
    # history, so their fingerprints are cleaned up immediately here rather
    # than left to poison novelty checking for this case's next run (or any
    # other case sharing its category).
    db.query(CampaignFingerprint).filter(CampaignFingerprint.campaign_id == campaign.id).delete()
    db.commit()
    # QA always runs for a benchmark (regardless of `config.enable_qa_stage`,
    # which only governs whether a REAL campaign's `run_autopilot` calls it
    # automatically) — a benchmark run with no scorecard would have nothing
    # for `compute_platform_weighted_score` to score.
    await run_qa_stage(
        db, campaign_id=campaign.id, renderer=renderer, config=config, image_provider=image_provider,
        ai_provider=ai_provider,
    )

    variants = get_platform_campaign_variants(db, campaign.id)
    variant = next(
        (v for v in variants if v.target_platform == case.platform and v.language == case.language), None,
    )

    qa_scores = dict(variant.qa_scores) if variant and variant.qa_scores else {}
    weighted = compute_platform_weighted_score(case.platform, qa_scores)
    prompt_versions = snapshot_prompt_versions(db, campaign_id=campaign.id, platform=case.platform, language=case.language)
    model_role_snapshot = {field: getattr(config, field) for field in _MODEL_ROLE_FIELDS}
    creative_system_snapshot = build_creative_system_snapshot(
        db, campaign_id=campaign.id, platform=case.platform, language=case.language,
        content_type=(variant.content_type if variant else case.content_type), quality_mode=config.quality_mode,
    )

    run = BenchmarkRun(
        benchmark_case_id=case.id, mode=mode, platform=case.platform, language=case.language,
        campaign_id=campaign.id, variant_id=variant.id if variant else None,
        prompt_versions_snapshot=prompt_versions, model_role_snapshot=model_role_snapshot,
        creative_system_snapshot=creative_system_snapshot,
        qa_status=(variant.qa_status if variant else ""), human_review_status=(variant.human_review_status if variant else ""),
        qa_scores=qa_scores, hard_fails=list(variant.qa_hard_fails or []) if variant else [],
        weighted_score=weighted["weighted_score"], weights_used=weighted["weights_used"],
        cost_breakdown=_cost_breakdown_for_campaign(db, campaign.id), is_baseline=is_baseline,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def compare_runs(baseline: BenchmarkRun, candidate: BenchmarkRun) -> dict:
    """Part E/G: a pairwise diff, read entirely from each run's own frozen
    columns — never a live re-query of either run's campaign/variant, so a
    later prompt/model change can never silently reinterpret an old
    comparison (Part F's own requirement, applied to comparisons too).
    """
    b_score, c_score = baseline.weighted_score, candidate.weighted_score
    delta = (c_score - b_score) if (b_score is not None and c_score is not None) else None
    baseline_fails = set(baseline.hard_fails or [])
    candidate_fails = set(candidate.hard_fails or [])
    return {
        "benchmark_case_id": candidate.benchmark_case_id,
        "platform": candidate.platform,
        "language": candidate.language,
        "baseline_run_id": baseline.id,
        "candidate_run_id": candidate.id,
        "baseline_score": b_score,
        "candidate_score": c_score,
        "delta": round(delta, 2) if delta is not None else None,
        "baseline_qa_status": baseline.qa_status,
        "candidate_qa_status": candidate.qa_status,
        "baseline_human_review_status": baseline.human_review_status,
        "candidate_human_review_status": candidate.human_review_status,
        "hard_failures": sorted(candidate_fails),
        "new_hard_failures": sorted(candidate_fails - baseline_fails),
        "resolved_hard_failures": sorted(baseline_fails - candidate_fails),
        "regression": delta is not None and delta < 0,
        "improvement": delta is not None and delta > 0,
        "baseline_cost": baseline.cost_breakdown,
        "candidate_cost": candidate.cost_breakdown,
    }


def build_regression_report(comparisons: list[dict]) -> dict:
    """Part E/G's own reporting shape: rolled up overall, AND independently
    by platform AND by language, so "PT-BR improved" can never hide "English
    regressed" (or vice versa) inside one averaged number.
    """
    by_platform: dict[str, list[dict]] = defaultdict(list)
    by_language: dict[str, list[dict]] = defaultdict(list)
    for c in comparisons:
        by_platform[c["platform"]].append(c)
        by_language[c["language"]].append(c)

    def _bucket(rows: list[dict]) -> dict:
        return {
            "count": len(rows),
            "regressions": [r for r in rows if r["regression"]],
            "improvements": [r for r in rows if r["improvement"]],
            "new_hard_failures": [r for r in rows if r["new_hard_failures"]],
        }

    return {
        "comparisons": comparisons,
        "regressions": [c for c in comparisons if c["regression"]],
        "improvements": [c for c in comparisons if c["improvement"]],
        "by_platform": {platform: _bucket(rows) for platform, rows in by_platform.items()},
        "by_language": {language: _bucket(rows) for language, rows in by_language.items()},
    }


_OWNER_AGREEMENT_CAVEAT = (
    "Descriptive counts only, from whatever benchmark/review history currently exists — never a statistically "
    "meaningful accuracy percentage. The goal is surfacing where automated QA and the owner's own judgment "
    "disagree, not manufacturing an AI-quality score."
)


def compute_owner_agreement_report(db: Session, *, brand_id: str | None = None) -> dict:
    """Carry-forward requirement 5 — "add reporting that can help evaluate
    whether Creative QA agrees with owner decisions", explicitly never
    claiming statistical significance (requirement 5's own caveat, always
    included regardless of sample size).

    Reads `ReviewFeedback.reviewed_qa_status` — the frozen snapshot of what
    QA said AT REVIEW TIME — never `PlatformCampaignVariant.qa_status`'s
    live, possibly-since-changed value (carry-forward requirement 3's own
    "never evaluate historical owner decisions against whatever the campaign
    happens to look like today").
    """
    query = db.query(ReviewFeedback).filter(ReviewFeedback.action.in_(("APPROVE", "REJECT")))
    if brand_id:
        query = query.filter(ReviewFeedback.brand_id == brand_id)
    rows = query.all()
    judged = [r for r in rows if r.reviewed_qa_status in ("PASS", "FAIL", "NEEDS_REVIEW")]

    agreement = 0
    false_positive_creative_pass = 0  # QA PASS but owner REJECTED
    false_negative_creative_fail = 0  # QA FAIL/NEEDS_REVIEW but owner APPROVED
    for row in judged:
        owner_approved = row.action == "APPROVE"
        qa_pass = row.reviewed_qa_status == "PASS"
        if qa_pass == owner_approved:
            agreement += 1
        elif qa_pass and not owner_approved:
            false_positive_creative_pass += 1
        else:
            false_negative_creative_fail += 1

    return {
        "total_feedback_considered": len(rows),
        "total_with_known_qa_status": len(judged),
        "owner_approved": sum(1 for r in judged if r.action == "APPROVE"),
        "owner_rejected": sum(1 for r in judged if r.action == "REJECT"),
        "qa_pass": sum(1 for r in judged if r.reviewed_qa_status == "PASS"),
        "qa_fail_or_needs_review": sum(1 for r in judged if r.reviewed_qa_status != "PASS"),
        "agreement_count": agreement,
        "disagreement_count": len(judged) - agreement,
        "false_positive_creative_pass": false_positive_creative_pass,
        "false_negative_creative_fail": false_negative_creative_fail,
        "agreement_rate": round(agreement / len(judged), 3) if judged else None,
        "caveat": _OWNER_AGREEMENT_CAVEAT,
    }
