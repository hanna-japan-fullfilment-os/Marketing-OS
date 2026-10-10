"""Autopilot orchestrator (brief section 18, campaign-pipeline.md's numbered steps).

This is what makes `POST /api/campaigns/{id}/generate` real: it ties together the
pieces that already exist and are independently tested — research orchestration
(`services/research/openai_research.py`), fingerprinting (`services/fingerprint.py`),
and the creative pipeline (`services/creative/pipeline.py`) — into the actual
research → strategy → copy → creative sequence.

As of the Campaign Builder advanced-mode round, that sequence is three independently
callable stages rather than one monolithic function:

- `run_strategy_stage` (steps 1-9): research → strategy candidates → novelty filter.
  Ends at `BRIEF_READY`. Needs an OpenAI key (research + one AI call).
- `run_copy_stage` (steps 10-12): creative brief → copy → carousel plan, reading the
  strategy stage's persisted output back rather than re-deriving it (so it can run
  standalone, in a later request, without re-running research). Ends at
  `COPY_READY`. Needs an OpenAI key.
- `run_visuals_stage` (steps 13-15): renders every planned slide from the copy
  stage's persisted carousel plan. Ends at `REVIEW`. Needs **no** OpenAI key at all —
  it only reads back already-generated text and composites your real photos, same as
  the manual per-slide `/slides/render` endpoint.

Each stage persists its output as a JSON file under `OUTPUT_ROOT/.../<campaign>/
brief/{strategy,copy,creative}.json` (mirroring how `qa_report`s are already stored —
see `_save_stage_json`/`_load_stage_json`), tracked via a `CampaignOutput` row per
kind. That's what lets a later stage run in a completely different HTTP request (or
even a different day) and pick up exactly where the prior one left off — this is the
actual mechanism behind the advanced-mode "Generate Strategy Only / Copy Only /
Visuals Only" UI on Campaign Detail (see `docs/campaign-pipeline.md`).

`run_autopilot` is the "Everything" mode: it simply calls the three stages back to
back in one call, unchanged in effect from before this split — every existing test
of the full pipeline still exercises the same end-to-end behavior.

Deliberately DB-row-in, DB-row-out but otherwise plain: each stage takes a `Session`
and a `campaign_id`, plus already-constructed `AIProvider`/`ResearchProvider`
instances and an `AutopilotConfig` of plain values, so it's testable end to end
against a fake provider (see tests/test_orchestrator.py) without a real OpenAI key or
network call.

Runs as a fire-and-forget background task from the API layer (via
`services/jobs.run_job_in_background`) rather than blocking the caller's HTTP
request — a real run does real research + several AI calls + Playwright renders,
easily tens of seconds, long enough that the frontend polls `GET /api/jobs/{id}`
(see `progress`/`JobContext`) instead of a request sitting open the whole time.
This module itself is unaware of which way it's invoked either way — it just
awaits a `Session` and reports progress through the `ProgressReporter` it's given
— so tests can still call these functions directly and await them inline.
"""
from __future__ import annotations

import io
import json
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Protocol

from PIL import Image
from sqlalchemy.orm import Session

from ..data.platform_capabilities import PLATFORM_CAPABILITIES
from ..data.platform_creative_specs import (
    default_content_type_for_platform, resolve_platform_creative_spec,
)
from ..models import (
    Asset, AuditEvent, Brand, BrandAsset, Campaign, CampaignAsset, CampaignFingerprint,
    CampaignOutput, CampaignSlide, CampaignStrategyType, Category, PlatformCampaignVariant, Product,
    ResearchInsight,
)
from ..schemas.ai import (
    CampaignCopy, CampaignStrategy, CampaignStrategyCandidates, CarouselPlan, CreativeBrief,
    ProductFidelityCheck, ProductZoneDetection, SourceProductIdentityCheck,
)
from ..schemas.ai import SlidePlan  # BUILD6R_PREMIUM_HERO_NO_CAROUSEL_CALL_V2
from ..schemas.creative_director import (
    CreativeDirection, MasterCampaignConcept, PlatformAdaptation, VideoConcept,
)
from .ai.base import AIProvider, ImageProvider, ResearchProvider
from .analytics import average_engagement_rate_for_strategy_type
from .creative.brand_style import resolve_brand_style
from .creative.pipeline import (
    SlideCreativeInput,
    build_qa_report_path,
    build_slide_output_path,
    build_variant_qa_report_path,
    build_variant_slide_output_path,
    prepare_masked_scene_edit_inputs,
    render_slide,
)
from .creative.renderer import PlaywrightRenderer
from .creative.templates import Feature, get_platform_format
from .feedback_selector import format_feedback_for_prompt, select_feedback_examples
from .product_facts import format_verified_facts_for_prompt, resolve_verified_product_facts
from .prompt_registry import record_prompt_usage
from .usage_tracking import record_stage_usage
from .fingerprint import NOVELTY_FRESH, NOVELTY_SIMILAR_BUT_ACCEPTABLE, classify_novelty, text_hash
from .research.openai_research import build_research_query, derive_geography_and_audience, run_research


class ProgressReporter(Protocol):
    def set_progress(self, progress: int, step: str) -> None: ...


class _NullProgress:
    def set_progress(self, progress: int, step: str) -> None:
        pass


class _ScaledProgress:
    """Rescales a stage's own 0-100 progress into a sub-range of an outer
    ProgressReporter, so `run_autopilot` (which runs all three stages back to back)
    can still report one continuous 0-100 progress bar across all of them, while
    each stage function reports its own honest 0-100 when run standalone.
    """

    def __init__(self, inner: ProgressReporter, start: int, end: int):
        self._inner = inner
        self._start = start
        self._end = end

    def set_progress(self, progress: int, step: str) -> None:
        scaled = self._start + (self._end - self._start) * (progress / 100)
        self._inner.set_progress(round(scaled), step)


@dataclass
class AutopilotConfig:
    campaign_model: str
    research_model: str
    trend_ttl_hours: int
    category_ttl_hours: int
    too_similar_threshold: int
    acceptable_threshold: int
    output_root: Path
    platform_key: str = "instagram_square"
    # Round 17: "feature_showcase" (richer layout matching the user's own
    # reference ads) is now the default — see services/creative/templates.py.
    # "premium_product_hero" is still registered and selectable.
    template_id: str = "feature_showcase"
    max_slides: int = 4

    # BUILD6R_PREMIUM_HERO_NO_CAROUSEL_CALL_V2
    # False by default so all normal campaigns keep the existing
    # carousel planner. Only the governed premium-hero runner opts in.
    hero_only: bool = False
    image_model: str = "gpt-image-2.5-sunburst-2026-09-08"
    use_ai_background: bool = False
    vision_model: str = "gpt-5.1"
    detect_product_zone: bool = False
    recreate_with_ai: bool = False

    # Stage 3D bounded integrated-scene editing. Defaults OFF so all
    # existing normal production/API behavior remains unchanged.
    use_masked_scene_edit: bool = False
    require_masked_scene_edit_success: bool = False

    # --- Build 2, Part D: model role routing --------------------------------
    # Each defaults to whatever the pre-Build-2 call site it replaces already
    # used, so a config built with only the fields above (every pre-Build-2
    # test, and any deployment that hasn't touched Settings) gets byte-for-byte
    # the same models as before. `api/campaigns.py::_build_autopilot_config` is
    # what actually wires these to Settings for a real request.
    strategy_model: str = ""  # falls back to campaign_model when unset, see __post_init__
    copy_model: str = ""  # falls back to campaign_model when unset
    platform_adapter_model: str = ""  # falls back to campaign_model when unset
    creative_director_model: str = ""  # falls back to campaign_model when unset
    draft_image_model: str = ""  # falls back to image_model when unset
    premium_image_model: str = ""  # falls back to image_model when unset
    creative_qa_model: str = ""  # falls back to vision_model when unset
    revision_model: str = ""  # falls back to image_model when unset

    # --- Build 2, Part K: quality modes -------------------------------------
    # "draft" | "standard" | "premium" — picks which image-model role (above)
    # and which Images API `quality` tier `_resolve_image_model_and_quality`
    # uses for every AI-generated background/recreation call this run makes.
    # "standard" (the default) behaves exactly as every pre-Build-2 run always
    # did: `image_model` at `quality="high"`.
    quality_mode: str = "standard"

    # Build 2 (the core carry-forward requirement): whether `run_visuals_stage`
    # also renders an independent `PlatformCampaignVariant` for every selected
    # (target_platform x language) combination beyond the primary one — see
    # `_render_additional_platform_variants`. Defaults to True; the only reason
    # to ever pass False is a test that wants to isolate the legacy
    # single-variant render path.
    render_platform_variants: bool = True

    # --- Build 3: Platform + Language Aware Multimodal QA -------------------
    # `enable_qa_stage` is opt-in and defaults False — `run_qa_stage` (new,
    # `services/qa_engine.py`) is an independently callable stage (mirroring
    # Build 1's Strategy/Copy/Visuals split), never auto-invoked from
    # `run_autopilot` by default. This is a deliberate "opt-in flag beats
    # changing a default" choice (this project's own established rule, see
    # `claude/build-status.md`'s "Key architectural decisions"): every
    # existing Build 1/2 test that passes a fake AIProvider not implementing
    # `critique_creative` would otherwise break the moment QA silently ran
    # underneath `run_autopilot`.
    enable_qa_stage: bool = False
    # Part H: overall_quality (or the video-QA equivalent) at/above this,
    # with no hard fail present, is a PASS with no revision needed.
    # Stage 3D: premium acceptance may require the AI scene to
    # succeed instead of silently accepting deterministic fallback.
    # False preserves normal production behavior.
    require_ai_background_success: bool = False
    qa_pass_threshold: int = 60
    # Part H: "retry exhaustion -> NEEDS_REVIEW" — how many targeted-revision
    # rounds a failing variant gets before settling there.
    qa_max_retries: int = 2
    # Part G ("optional platform-specific candidate generation"): how many
    # independent candidates a targeted creative-direction revision generates
    # per attempt, keeping whichever scores best. 1 (the default) is exactly
    # the pre-Best-of-N single-candidate behavior.
    qa_best_of_n: int = 1

    # --- Build 4: Human Approval + Platform/Language Feedback Learning ------
    # Carry-forward requirement 5's "configurable or deterministic maximum
    # number of feedback examples injected into generation" — caps how many
    # positive and how many negative `ReviewFeedback` examples
    # `feedback_selector.select_feedback_examples` returns per call. Unlike
    # `enable_qa_stage` above, this needs no opt-in flag: an empty
    # `review_feedback` table (every pre-Build-4 database, and every existing
    # test) makes `format_feedback_for_prompt` return `""`, so every prompt
    # this wires into stays byte-for-byte identical until real feedback
    # exists — see `services/feedback_selector.py`'s module docstring.
    feedback_examples_limit: int = 5

    # BUILD6R_PREMIUM_HERO_TRUE_SCOPE_V1
    # Explicit acceptance-mode cost/scope boundary. Defaults OFF so
    # normal campaigns continue to generate their CarouselPlan.
    skip_carousel_plan: bool = False

    def __post_init__(self) -> None:
        self.strategy_model = self.strategy_model or self.campaign_model
        self.copy_model = self.copy_model or self.campaign_model
        self.platform_adapter_model = self.platform_adapter_model or self.campaign_model
        self.creative_director_model = self.creative_director_model or self.campaign_model
        self.draft_image_model = self.draft_image_model or self.image_model
        self.premium_image_model = self.premium_image_model or self.image_model
        self.creative_qa_model = self.creative_qa_model or self.vision_model
        self.revision_model = self.revision_model or self.image_model


_AI_BACKGROUND_SIZES = ("1024x1024", "1024x1536", "1536x1024")

# Build 6 repair (visual quality defects) — a mobile-first hierarchy note
# appended to every full-recreation prompt. Deliberately prompt-level only,
# never a frontend/template redesign (out of scope for this repair): a real
# live-acceptance review found excessive copy density, tiny microcopy, a
# generic dark footer bar, and a barely-visible logo across several
# real-run creatives.
_mobile_hierarchy_instruction = (
    " This will be viewed primarily on a phone screen at small size: prioritize ONE clear message per "
    "slide, a large and highly legible headline, much shorter supporting copy than you'd use for print, "
    "deliberate negative space rather than filling every inch, and a brand mark that reads as genuinely "
    "integrated into the composition (proper scale and placement) rather than a small logo pasted in a "
    "corner. Avoid a large generic bottom bar of dense footer text — keep any secondary copy minimal and "
    "purposeful."
)


def _resolve_image_model_and_quality(
    config: AutopilotConfig,
) -> tuple[str, str]:
    """Resolve the active image role without breaking legacy image models."""
    if config.quality_mode == "draft":
        return (
            config.draft_image_model,
            "low",
        )

    if config.quality_mode == "premium":
        model = (
            config.premium_image_model
        )

        quality = (
            "xhigh"
            if model.startswith(
                "gpt-image-2.5-"
            )
            else "high"
        )

        return (
            model,
            quality,
        )

    return (
        config.image_model,
        "high",
    )


def _nearest_ai_image_size(
    width: int,
    height: int,
    *,
    model: str = "",
) -> str:
    """Select an image API size while preserving legacy-model compatibility."""
    ratio = (
        width
        / height
    )

    if (
        model.startswith(
            "gpt-image-2.5-"
        )
        and abs(
            ratio
            - 0.8
        )
        <= 0.02
    ):
        return (
            "1088x1360"
        )

    if ratio > 1.15:
        return (
            "1536x1024"
        )

    if ratio < 0.87:
        return (
            "1024x1536"
        )

    return (
        "1024x1024"
    )


def _resolve_inspiration_paths(
    db: Session, brand_id: str, *, category_id: str | None = None, limit: int = 2
) -> list[Path]:
    """Real, user-uploaded example ads/posts/carousels (`BrandAsset kind=
    'inspiration'` — see `POST /api/brands/{id}/assets`) used as creative-direction
    reference when recreating a photo for a campaign (see
    `recreate_creative_image` below) — separate from `visual_reference`, which
    describes the brand's *own* look rather than outside inspiration the user found.
    Category-scoped examples (this campaign's own category) are preferred and fill
    the limit first; brand-wide ones (`category_id IS NULL`) top up any remaining
    slots. Only files that actually exist on disk are returned.
    """
    query = db.query(BrandAsset).filter(BrandAsset.brand_id == brand_id, BrandAsset.kind == "inspiration")
    scoped: list[BrandAsset] = []
    if category_id:
        scoped = query.filter(BrandAsset.category_id == category_id).order_by(BrandAsset.created_at.desc()).all()
    remaining = max(0, limit - len(scoped))
    brand_wide: list[BrandAsset] = []
    if remaining:
        brand_wide = (
            query.filter(BrandAsset.category_id.is_(None)).order_by(BrandAsset.created_at.desc()).limit(remaining).all()
        )
    combined = (scoped + brand_wide)[:limit]
    return [p for p in (Path(a.file_path) for a in combined) if p.exists()]


def _resolve_visual_reference_paths(db: Session, brand_id: str, *, limit: int = 3) -> list[Path]:
    """Real, user-uploaded example photos for this brand (BrandAsset kind=
    'visual_reference' — see POST /api/brands/{id}/assets), used as a live style
    reference for AI-generated backgrounds. Never fabricated: only files that
    actually exist on disk are returned, same immutability discipline as every
    other real-file lookup in this module.
    """
    assets = (
        db.query(BrandAsset)
        .filter(BrandAsset.brand_id == brand_id, BrandAsset.kind == "visual_reference")
        .order_by(BrandAsset.created_at.desc())
        .limit(limit)
        .all()
    )
    return [p for p in (Path(a.file_path) for a in assets) if p.exists()]


def _brand_creative_instructions_block(brand: Brand) -> str:
    """Round 20: the brand's own free-text `creative_instructions` (see that
    field's docstring on the `Brand` model), formatted as a clearly-labeled block
    so it reads as the brand's own standing direction rather than blending
    anonymously into the rest of a prompt. Empty string (not a placeholder
    sentence) when the brand hasn't set one, so every prompt that includes this
    is byte-for-byte unchanged for a brand that never fills it in.

    This is deliberately called from every AI call this app makes on a brand's
    behalf — strategy candidates, the creative brief, campaign copy, and the
    image-recreation/background prompts (via `_brand_style_prompt_notes` below)
    — because a brand's own custom-GPT-style prompt (tone rules, formatting
    conventions, non-negotiables) is exactly the kind of thing that should apply
    everywhere, not to just one stage. Not a substitute for the structured
    fields (`voice`/`visual_style`/`preferred_ctas`/`disallowed_terms`/
    `forbidden_styles`) below it — this is the free-text complement to those,
    for whatever doesn't fit a single structured field.
    """
    if not brand.creative_instructions or not brand.creative_instructions.strip():
        return ""
    return f"Brand's own standing creative instructions (follow these): {brand.creative_instructions.strip()}"


def _brand_style_prompt_notes(brand: Brand) -> str:
    """Turns the brand's own text-configured style fields into a short prompt
    fragment, so an AI-generated background is grounded in the brand's actual
    configured voice/visual_style/colors rather than generic marketing imagery.
    """
    parts: list[str] = []
    instructions = _brand_creative_instructions_block(brand)
    if instructions:
        parts.append(instructions)
    if brand.voice:
        parts.append(f"Brand voice: {brand.voice}.")
    if isinstance(brand.visual_style, dict) and brand.visual_style:
        descriptors = ", ".join(str(v) for v in brand.visual_style.values() if v)
        if descriptors:
            parts.append(f"Visual style: {descriptors}.")
    colors = resolve_brand_colors(brand)
    if colors:
        parts.append(f"Brand colors: {', '.join(colors)}.")
    if isinstance(brand.forbidden_styles, list) and brand.forbidden_styles:
        parts.append(f"Avoid: {', '.join(str(s) for s in brand.forbidden_styles)}.")
    return " ".join(parts)


def _language_style_rules(language: str) -> str:
    """Build 1 (Part F): concrete, locale-specific copywriting rules folded into
    every per-language `CampaignCopy`/`CarouselPlan` call in `run_copy_stage`, so
    two languages read as independently native writing rather than one language
    translated into the other. Each rule set names the specific failure modes to
    avoid (not just "write naturally"), since that's what actually steers a
    structured-output call away from generic AI phrasing.
    """
    if language == "pt-BR":
        return (
            "Write in natural, contemporary Brazilian Portuguese — the way a Brazilian social-media "
            "marketer actually writes, not a formal or corporate register. Avoid Portugal-specific "
            "vocabulary and conjugations (no 'tu', no 'está a fazer' — use 'você' and 'está fazendo'), "
            "avoid overly formal business Portuguese, avoid sentence structures that read like a literal "
            "translation from English, avoid generic AI-sounding phrases ('Descubra o poder de...', "
            "'Transforme sua rotina', 'Eleve sua...'), and avoid excessive hype or bureaucratic "
            "vocabulary. Write like a real person talking to a friend, not an ad script."
        )
    if language == "en":
        return (
            "Write in natural marketing English appropriate to the target audience. Avoid sentence "
            "structures that read like a Portuguese (or any other language's) sentence translated "
            "word-for-word, avoid unnatural idioms, avoid generic AI-sounding filler phrases ('Discover "
            "the power of...', 'Elevate your routine', 'Unlock your...'), and avoid unnecessary "
            "exaggeration. Write like a real marketer writing for this specific audience, not a template."
        )
    # SUPPORTED_LANGUAGES only ever contains pt-BR/en today (data/platform_
    # capabilities.py), so this branch isn't reachable via the validated API —
    # kept as an honest fallback rather than raising, in case that list grows.
    return (
        f"Write in natural, idiomatic {language}, the way a native speaker actually writes marketing "
        "copy in this language — never a literal translation from another language."
    )


def _claims_boundary_instruction() -> str:
    """Build 6 repair, Critical Defect 2 — a strong, explicit boundary between
    the four distinct kinds of information a copy/concept prompt is ever
    handed, appended to every AI call in this stage that could otherwise
    state an unsupported claim as fact. A real live-acceptance run produced
    unsupported claims (bestseller/"#1" status, before/after results, VIP/
    restock/priority perks, a customer/follower count, a discount) despite
    `VerifiedProductFacts` being deliberately sparse for that product — the
    four-way separation between verified facts, research context, owner-
    confirmed brand notes, and the model's own creative ideas already existed
    in this prompt's INPUTS (Build 1's own distinct "VERIFIED PRODUCT FACTS"
    vs. research-insights blocks — see `format_verified_facts_for_prompt`/
    `_format_research_insights_for_prompt`), but nothing told the model those
    categories carry different evidentiary weight; this closes that gap. Kept
    as one shared function (not copy-pasted per call site) so tightening this
    boundary later never means finding and editing four separate strings.
    """
    return (
        (("CLAIMS BOUNDARY (read carefully — this overrides any temptation to write punchier copy): "
        "(1) VERIFIED PRODUCT FACTS, when given above, are the ONLY facts you may state as true about "
        "this specific product. (2) Research insights, when given, are market/trend CONTEXT ONLY — they "
        "may shape your angle, tone, or which pain point you lead with, but must NEVER become a stated "
        "product fact, a specific number, or a claim that the product itself does something, unless that "
        "exact claim also appears in VERIFIED PRODUCT FACTS. (3) Brand voice/disclaimers/preferred CTAs "
        "given are owner-confirmed and may be used as given — never invent an additional brand program, "
        "perk, or policy beyond what's stated. (4) Never state or imply, unless it explicitly appears in "
        "VERIFIED PRODUCT FACTS or the owner-confirmed brand notes above: bestseller/rank/#1/most-popular "
        "status; a specific customer, follower, or community-size number; a before/after or transformation "
        "result; a restock, early-access, or priority-shipping promise; a VIP/membership perk; a surprise "
        "gift or bonus; a discount or price; a star rating or testimonial; or a clinical/scientific claim. "
        "When the given facts are sparse, build the concept around what IS actually known (the product's "
        "real name, category, and any verified facts) rather than inventing popularity or performance "
        "claims to fill the gap — a simpler, honest concept is the correct output; an exciting but "
        "unsupported one is not. "
        "CULTURAL/MARKET CONTEXT HARD STOP: Research or trend context may inspire creative direction, "
        "but it must not become a factual claim about cultural norms, common consumer behavior or prevalence, "
        "pharmacy presence or shelf prevalence, product availability, national usage habits, or Hanna Japan's "
        "curation/market role unless that exact fact is present in VERIFIED PRODUCT FACTS or explicit "
        "owner-confirmed brand facts." + " Build 6R V3.23 SEMANTIC BOUNDARY: Never invent evaluative product positioning such as advanced/avancado, superior, innovative, premium, or equivalent quality positioning unless that exact assertion is explicitly supported by VERIFIED PRODUCT FACTS. Research, trends, strategy, audience, funnel, planning, creative briefs, and other AI-generated context never provide product-fact evidence. If exosome or stem-lineage information is mentioned and the VERIFIED PRODUCT FACTS carry a no-stem-cell qualification, keep that qualification in the SAME generated textual field; never rely on another field for that safety qualification. Funnel stage and similar planning concepts are campaign metadata, not product facts." + " Build 6R V3.26 COMPARATIVE BOUNDARY: Never invent rhetorical comparisons, comparative hooks, superiority framing, or implied relative quality merely to make copy more engaging. Phrases equivalent to 'not all X are equal', 'X nao e tudo igual', 'better than ordinary X', 'more advanced', 'superior to', 'different from other X', or similar comparative/superlative framing are prohibited unless VERIFIED PRODUCT FACTS explicitly support every compared subject, comparison dimension, and asserted relation. If no verified comparison exists, use neutral descriptive wording. Research, trends, strategy, creative direction, owner photos, and other AI-generated or contextual material never create comparison evidence."))
    )


def _sparse_fact_grounding_instruction() -> str:
    """Universal fail-closed grounding for sparse product facts."""
    return (
        " SPARSE-FACT GROUNDING - AUTHORITATIVE: "
        "VERIFIED PRODUCT FACTS are the complete factual evidence boundary "
        "for product-specific claims. Empty, blank, omitted, or unknown "
        "fields mean UNKNOWN and are never permission to infer the missing "
        "information. A product name, model name, category, or free-text "
        "product note is identity/context only. Words inside those fields "
        "do not prove ingredients, materials, percentages, functions, "
        "effects, benefits, performance, usage, safety, availability, "
        "popularity, or results. "
        "Research, trends, competitor examples, inspiration assets, prior "
        "campaigns, strategy text, creative briefs, campaign copy, and other "
        "AI-generated upstream outputs are creative context only. They are "
        "NEVER factual evidence about the product unless the same fact is "
        "explicitly present in VERIFIED PRODUCT FACTS. "
        "This rule applies to every output field, including "
        "product_category_context, campaign_promise, key_message, story_arc, "
        "story_beats, visual_identity, hero_treatment, "
        "proof_or_demo_strategy, purpose, eyebrow, headline, body, CTA, "
        "badge_text, intro, features, callouts, bottom_features, "
        "trust_badges, and visual_brief. "
        "Do not state or imply ingredients, percentages, efficacy, health, "
        "beauty, safety, performance, durability, transformations, outcomes, "
        "rankings, popularity, scarcity, price, availability, certification, "
        "usage instructions, comparisons, or results unless explicitly "
        "supported by VERIFIED PRODUCT FACTS or, for brand/logistics policy "
        "only, explicit owner-confirmed brand facts. "
        "A visual idea is also a claim when it depicts or strongly implies "
        "an unsupported fact. visual_brief must never use before/after, "
        "transformation, clinical proof, ingredient symbolism, result "
        "comparison, or outcome imagery as a workaround for a claim that "
        "would be forbidden in text. "
        "When facts are sparse, STAY SPARSE. Use verified identity, verified "
        "provenance, authentic source-product fidelity, brand styling, "
        "composition, lighting, atmosphere, materials, and non-claim "
        "storytelling. Leave unsupported factual details neutral or blank "
        "rather than guessing. "
        # BUILD6R_UNVERIFIED_CLAIM_PROMPT_HARDENING_V1
        " ORIGIN/PROVENANCE HARD STOP: Country of origin, manufacturing country, made-in, "
        "imported-from, or wording such as 'Japanese product', 'produto japones', 'pouch japones', "
        "'japones' or 'japonesa' is a factual origin claim. Use it ONLY when country of origin is "
        "explicitly populated in VERIFIED PRODUCT FACTS. Brand identity, store identity, retailer "
        "location, target market, campaign geography, packaging language, manufacturer website "
        "language, source URL, research, or J-beauty context do NOT establish country of origin. "
        "THIRD-PARTY AUTHORITY HARD STOP: Never say or imply that guides, experts, editors, "
        "communities, reviews, rankings, trends, creators, or other third parties recommend, endorse, "
        "rank, cite, prefer, or validate this specific product unless that exact product-specific "
        "endorsement is explicitly present in VERIFIED PRODUCT FACTS. Research can inspire creative "
        "direction only and is never endorsement evidence. Do not turn a research discussion of "
        "hydration or another benefit into a claim that this product is recommended for that benefit. "
        "QUALITATIVE QUANTITY/INTENSITY HARD STOP: Exact verified counts and amounts may be stated, "
        "but do not inflate them with subjective quantity or potency language such as 'muita formula', "
        "'a lot of formula', 'loaded with', 'packed with', 'generous amount', 'abundant', 'powerful', "
        "'potent', 'concentrated', 'intense', or similar wording unless that qualitative statement is "
        "itself explicitly verified. If the evidence says 150 mL and 7 sheets, say 150 mL and 7 sheets; "
        "do not convert those numbers into an unverified judgment about how much formula there is. "
        "PARAPHRASE DISCIPLINE: Natural translation and grammatical paraphrase are allowed only when "
        "they preserve the same factual atoms. Never add an origin modifier, benefit/effect, endorsement, "
        "comparison, popularity signal, quantity judgment, performance adjective, efficacy implication, "
        "or other new factual modifier while paraphrasing a verified fact. "
        # BUILD6R_STAGE3D_SHARED_ANTI_INFERENCE_HARDENING_V2
        " TEMPORAL/ROUTINE INFERENCE HARD STOP: A verified package count, amount, permitted time of day, "
        "or existence of multiple units does NOT establish frequency, cadence, duration, consecutive use, "
        "continuous use, daily use, a multi-day routine, or how many days the product should accompany a "
        "consumer. Never infer wording such as 'continuous use', 'uso cont\u00ednuo', 'several days', "
        "'v\u00e1rios dias', 'alguns dias de cuidado seguido', 'sequence', or 'sequ\u00eancia' unless that specific "
        "temporal/routine fact is explicitly verified. A statement that something may be used morning or "
        "evening describes permitted timing only; it does not establish daily, consecutive, continuous, "
        "or multi-day use. "
        "PACKAGE PURPOSE/ORGANIZATION HARD STOP: Packaging facts describe only what is verified about the "
        "package. Multiple units in one pouch do NOT prove that the format was designed, created, planned, "
        "organized, optimized, or intended for continuous use, convenience, routine building, several days, "
        "storage improvement, or comparison with separate sachets. Do not transform package structure into "
        "an invented purpose or consumer benefit. "
        "PURCHASE-BEHAVIOR INFERENCE HARD STOP: Never infer how the customer otherwise buys, stores, forgets, "
        "organizes, or uses products. Do not invent contrasts such as buying one sheet at a time, impulse "
        "purchases, loose purchases, random purchases, sachets lost in a drawer, or a package replacing those "
        "behaviors unless VERIFIED PRODUCT FACTS explicitly establish that comparison. "
        "SUBJECTIVE QUALITY/COMFORT INFERENCE HARD STOP: A verified product or material name does not prove "
        "comfort, softness, luxury, premium quality, craftsmanship, sensory superiority, or that something "
        "is 'well made'. Do not turn a manufacturer feature name into phrases such as 'comfortable touch', "
        "'toque confort\u00e1vel', 'bem feita', 'premium feel', or another subjective quality judgment unless "
        "the same quality or sensory statement is itself verified. "
        "USAGE MODIFIER INFERENCE HARD STOP: Usage instructions must preserve the verified action, sequence, "
        "timing, and modifiers exactly in meaning. Never add 'gently', 'softly', 'firmly', 'lightly', massage, "
        "extra pressure, a leave-on duration, frequency, cadence, or another manner-of-use modifier unless "
        "that modifier is explicitly present in VERIFIED PRODUCT FACTS. For example, a verified instruction "
        "to 'press' does not authorize 'press gently' or 'pressionando suavemente'. "
    )


def _platform_requirements_note(target_platforms: list[str]) -> str:
    """Build 1 (Part C): turns `campaign.target_platforms` into real, platform-
    specific copywriting guidance (from `data/platform_capabilities.py`'s
    `copy_notes`) folded into the copy/carousel-plan prompts — so "write for
    TikTok" means something concrete instead of copy that silently assumes
    Instagram regardless of what was actually selected. An unrecognized key
    (shouldn't happen — validated at the API layer, see
    `data/platform_capabilities.py::validate_target_platforms`) is skipped
    rather than raising, since this is prompt-building, not validation.
    """
    lines = []
    for key in target_platforms:
        cap = PLATFORM_CAPABILITIES.get(key)
        if cap is None:
            continue
        lines.append(f"- {cap.label} ({', '.join(cap.content_types)}): {cap.copy_notes}")
    if not lines:
        return ""
    return (
        "This campaign targets the following real platform(s) — write copy that actually fits their "
        "real conventions below, not generic copy reused everywhere:\n" + "\n".join(lines)
    )


def _format_research_insights_for_prompt(db: Session, research_run_id: str | None) -> str:
    """Build 1 (Part E): this campaign's own persisted research — generated back
    in `run_strategy_stage` but, before this, never read again after that —
    formatted for the copy/carousel-plan prompts. Highest-confidence insights
    first, capped at 6 so the prompt doesn't balloon on a research run with many
    insights. Returns "" (never a placeholder sentence) when there's no research
    run yet or it produced no insights, same "byte-for-byte unchanged when
    there's nothing to add" discipline as `_brand_creative_instructions_block`.
    """
    if not research_run_id:
        return ""
    insights = (
        db.query(ResearchInsight)
        .filter(ResearchInsight.research_run_id == research_run_id)
        .order_by(ResearchInsight.confidence.desc())
        .limit(6)
        .all()
    )
    if not insights:
        return ""
    lines = [
        "Relevant research insights for this campaign (use these to ground and sharpen the copy — "
        "don't just restate them verbatim):"
    ]
    for ins in insights:
        implication = f" Implication: {ins.recommended_implication}." if ins.recommended_implication else ""
        lines.append(f"- {ins.statement}{implication} (confidence: {ins.confidence:.2f})")
    return "\n".join(lines)


def _stage_language_variant(data: dict | None, language: str | None) -> dict | None:
    """Reads back one language's variant from a `copy`/`creative` stage JSON blob
    (Build 1's nested `{"primary_language": ..., "languages": {"<lang>": {...}}}`
    shape — see `run_copy_stage`), while staying compatible with the flat shape a
    campaign generated before Build 1 persisted (the whole dict IS the one
    variant, from when a campaign could only ever have a single language) — so a
    pre-Build-1 campaign's already-generated copy still reads back correctly
    rather than erroring or silently returning nothing.

    `language=None` (or a language that isn't actually in `data["languages"]`,
    which shouldn't happen but is handled rather than raising) resolves to the
    stored primary language, falling back to whichever variant happens to be
    first if even that's missing.
    """
    if not data:
        return None
    if "languages" not in data:
        return data  # pre-Build-1 flat shape
    variants = data["languages"]
    if not variants:
        return None
    target = language or data.get("primary_language")
    if target in variants:
        return variants[target]
    return next(iter(variants.values()))


async def generate_ai_background(
    db: Session,
    *,
    image_provider: ImageProvider,
    brand: Brand,
    model: str,
    width: int,
    height: int,
    visual_brief: str = "",
    quality: str = "high",
    creative_direction: CreativeDirection | None = None,
) -> Image.Image | None:
    """Best-effort AI-generated scene background — the brief's documented
    `SlideCreativeInput.generated_background` hook, finally wired up. Shared by
    `run_visuals_stage` (one call per planned slide) and the manual per-slide
    `/slides/render` endpoint, so both paths use the same prompt-building and the
    same brand visual-reference photos as style guidance.

    Build 2 (Part J — the Hybrid Renderer's SCENE-generation step): the AI is
    asked for scene/surface/atmosphere/environment/lighting only, exactly as
    before — this docstring and the prompt below now spell out, by name, every
    element Part J says must never be asked of the AI here: the exact product
    label, the brand logo, the headline/body/CTA copy, a price or discount
    graphic, or any legal/disclaimer text. All of those stay real HTML/CSS
    (`services/creative/templates.py`) or the real, untouched product photo
    (`services/creative/compositor.py::composite_product`) — never pixels this
    call generates. `creative_direction` (Build 2, Part G), when given, folds
    that variant's own `background_concept`/`lighting`/`mood`/`palette`/
    `scene_generation_prompt` into the prompt instead of just `visual_brief`;
    omitted (the pre-Build-2 call shape), this behaves exactly as before.

    Returns `None` on ANY failure (bad key, rate limit, network error, malformed
    image bytes) rather than raising — an AI-generated background is a nice-to-have
    layered on top of a pipeline that has always worked with a deterministic
    gradient, so a failure here must never take down a slide render that would
    otherwise have succeeded. Callers fall back to `make_background(...)` when this
    returns `None`.
    """
    try:
        reference_paths = _resolve_visual_reference_paths(db, brand.id, limit=3)
        style_notes = _brand_style_prompt_notes(brand)
        direction_note = ""
        if creative_direction is not None:
            direction_note = (
                f" Product/category context: {creative_direction.product_category_context}. "
                f"Campaign archetype: {creative_direction.campaign_archetype}. "
                f"Archetype reasoning: {creative_direction.archetype_reasoning}. "
                f"Visual story system: {creative_direction.visual_story_system}. "
                f"Hero treatment: {creative_direction.hero_treatment}. "
                f"Proof/demo strategy: {creative_direction.proof_or_demo_strategy}. "
                f"Scene concept: {creative_direction.background_concept or creative_direction.visual_style}. "
                f"Composition: {creative_direction.composition}. "
                f"Product position: {creative_direction.product_position}. "
                f"Product scale: {creative_direction.product_scale}. "
                f"Lighting: {creative_direction.lighting}. "
                f"Mood: {creative_direction.mood}. "
                f"Depth: {creative_direction.depth}. "
                f"Texture: {creative_direction.texture}. "
                f"{creative_direction.scene_generation_prompt}"
            ).strip()
        prompt = (
            f"A premium product-marketing background scene for the brand '{brand.name}'. "
            f"{style_notes} {visual_brief}{direction_note} "
            "No text of any kind, no exact product label or packaging text, no brand logo, no "
            "headline/body/CTA copy, no price or discount graphic, no legal or disclaimer text, no "
            "people, no product in frame — just an evocative background scene (surface, atmosphere, "
            "environment, lighting); the real product photo and all copy/logo/legal text are added "
            "separately afterward as real, unaltered elements."
        ).strip()
        size = _nearest_ai_image_size(width, height, model=model)
        image_bytes = await image_provider.generate(
            prompt=prompt, size=size, model=model, reference_images=reference_paths or None, quality=quality,
        )
        return Image.open(io.BytesIO(image_bytes)).convert("RGB")
    except Exception:  # noqa: BLE001 - best-effort; caller falls back to the gradient
        return None


class SourceProductIdentityMismatch(ValueError):
    """Build 6 repair, Critical Defect 1: raised by `_enforce_source_product_
    identity_gate` when a real source photo cannot be CONFIRMED to depict the
    catalog product this campaign/slide claims it does — before any billed AI
    image generation happens. Both an explicit `MISMATCH` and an
    `UNVERIFIABLE` verdict raise this (never silently treated as a pass, per
    the repair's own explicit "UNVERIFIABLE must not be silently treated as
    MATCH" instruction) — the message always starts with the literal string
    `SOURCE_PRODUCT_IDENTITY_MISMATCH` so a caller/log can grep for this
    specific, actionable failure mode.
    """


async def verify_source_product_identity(
    *, ai_provider: AIProvider, source_image_path: Path, product_name: str, category_name: str, model: str,
) -> SourceProductIdentityCheck:
    """Best-effort wrapper around `AIProvider.verify_source_product_identity`
    — fail-CLOSED (an `UNVERIFIABLE` verdict, never a `MATCH`) on any provider
    exception, mirroring `recreate_creative_image_with_fidelity_gate`'s own
    "an unverifiable check is never treated as a pass" discipline.
    """
    try:
        return await ai_provider.verify_source_product_identity(
            source_image_path=source_image_path, product_name=product_name, category_name=category_name,
            model=model,
        )
    except Exception as exc:  # noqa: BLE001 - fail-closed: an errored check is never treated as a pass
        return SourceProductIdentityCheck(
            verdict="UNVERIFIABLE", reasoning=f"Identity check could not be completed (provider error: {exc})."
        )


async def _enforce_source_product_identity_gate(
    db: Session, *, campaign: Campaign, ai_provider: AIProvider | None, vision_model: str,
    asset_product_pairs: list[tuple[Asset, Product]],
) -> None:
    """Build 6 repair, Critical Defect 1 — a PRE-GENERATION gate: before this
    run does ANY billed AI image generation (full recreation or an AI-
    generated scene/background), confirm that every distinct real source
    photo about to be used actually depicts the catalog product this
    campaign/slide claims it does. Runs once per distinct asset (never
    re-billed for a photo reused/round-robined across several slides in the
    same run).

    Deliberately narrow: skipped entirely (never a false block, never extra
    cost) when there's no catalog product to check against at all (a
    category-only campaign makes no per-product identity claim in the first
    place — `product` is `None` in the pair), when no `ai_provider` is
    available at all, or when the given provider simply doesn't implement
    this vision check (`verify_source_product_identity` is absent/not
    callable — the same duck-typed "this test/legacy provider doesn't
    support this capability" detection `services/usage_tracking.py::
    drain_provider_usage_events` already uses for exactly this reason:
    a capability gap is a different fact from a check that ran and came back
    inconclusive). That distinction matters: fail-closed on `UNVERIFIABLE`
    is for a check that was actually ATTEMPTED and couldn't confirm a match
    — not for a provider that never had this ability in the first place,
    which would otherwise make every non-vision-capable provider fail every
    product-scoped campaign outright. The real `OpenAIProvider` always
    implements this, so production behavior is unaffected.

    Raises `SourceProductIdentityMismatch` — which callers treat as a HARD
    FAIL of the whole run, never a soft `NEEDS_REVIEW` — the moment any
    checked asset comes back anything other than a confirmed `MATCH`, before
    proceeding to generate a single image.
    """
    if ai_provider is None or not callable(getattr(ai_provider, "verify_source_product_identity", None)):
        return
    checked: dict[str, SourceProductIdentityCheck] = {}
    for asset, product in asset_product_pairs:
        if product is None or asset.id in checked:
            continue
        source_path = Path(asset.absolute_path)
        if not source_path.exists():
            continue  # a missing file is handled (skipped) by the render loop itself, not this gate
        check = await verify_source_product_identity(
            ai_provider=ai_provider, source_image_path=source_path, product_name=product.name,
            category_name="", model=vision_model,
        )
        checked[asset.id] = check
        _audit(
            db, campaign.id, "source_product_identity_check",
            {
                "asset_id": asset.id, "product_id": product.id, "product_name": product.name,
                "verdict": check.verdict, "observed_product_type": check.observed_product_type,
                "observed_label_text": check.observed_label_text, "reasoning": check.reasoning,
            },
        )
        if check.verdict != "MATCH":
            campaign.status = "FAILED"
            db.commit()
            raise SourceProductIdentityMismatch(
                f"SOURCE_PRODUCT_IDENTITY_MISMATCH: the source photo for asset {asset.id} "
                f"({source_path.name!r}) could not be confirmed to depict the catalog product "
                f"'{product.name}' (verdict={check.verdict}). {check.reasoning or ''}".strip()
                + " Fix this asset's product tagging, or replace/re-tag the source photo, before "
                "generating visuals for this campaign."
            )
    db.commit()



def _masked_scene_model_and_quality(
    config: AutopilotConfig,
) -> tuple[str, str]:
    """Mirror the established image-model roles for the new edit path."""
    mode = (
        config.quality_mode
        or "standard"
    ).strip().lower()

    if mode == "draft":
        return (
            config.draft_image_model
            or config.image_model,
            "low",
        )

    if mode == "premium":
        return (
            config.premium_image_model
            or config.image_model,
            "high",
        )

    return (
        config.image_model,
        "high",
    )


async def generate_masked_product_scene(
    *,
    image_provider: ImageProvider,
    creative_input: SlideCreativeInput,
    config: AutopilotConfig,
) -> Image.Image | None:
    """Make exactly one masked Images edit around deterministic product pixels.

    BUILD6R_SINGLE_MASKED_SCENE_EDIT_V2

    This function deliberately has no generate() fallback and no retry.
    It returns only the edited scene. render_slide performs the final
    deterministic approved-product overlay afterward.
    """
    try:
        prepared = (
            prepare_masked_scene_edit_inputs(
                creative_input
            )
        )

        model, quality = (
            _masked_scene_model_and_quality(
                config
            )
        )

        direction_bits = [
            creative_input.hero_treatment,
            creative_input.visual_style,
            creative_input.mood,
            creative_input.negative_space,
            creative_input.typography_direction,
        ]

        direction = "; ".join(
            value.strip()
            for value in direction_bits
            if isinstance(
                value,
                str,
            )
            and value.strip()
        )

        colors = ", ".join(
            creative_input.brand_colors
            or []
        )

        prompt = (
            "Create a premium professionally art-directed commercial "
            "environment around the exact already-positioned product in "
            "the input image. Preserve the product position, scale, "
            "silhouette, proportions, packaging colors, logo, label "
            "structure and visible packaging text. Do not redesign, "
            "replace, translate, repaint, blur, soften or regenerate the "
            "product. Use only the surrounding editable region for "
            "integrated lighting, realistic contact shadow, reflective "
            "interaction, surface depth, atmosphere and premium editorial "
            "art direction. The result should feel like one intentional "
            "campaign photograph, not a product pasted on a generic "
            "gradient. Do not add headlines, CTA text, prices, discounts, "
            "invented claims, legal copy, extra logos, people or hands. "
            "Marketing typography and the real brand logo are rendered "
            "afterward by deterministic HTML/CSS. "
            f"Brand palette guidance: {colors}. "
            f"Creative direction: {direction}."
        ).strip()

        with tempfile.TemporaryDirectory(
            prefix="marketing-os-masked-scene-"
        ) as temporary_directory:

            root = Path(
                temporary_directory
            )

            base_path = (
                root
                / "base.png"
            )

            mask_path = (
                root
                / "mask.png"
            )

            prepared.base_image.save(
                base_path,
                format="PNG",
            )

            prepared.mask_image.save(
                mask_path,
                format="PNG",
            )

            with Image.open(
                base_path
            ) as base_check:
                base_size = base_check.size
                base_format = base_check.format

            with Image.open(
                mask_path
            ) as mask_check:
                mask_size = mask_check.size
                mask_format = mask_check.format
                mask_has_alpha = (
                    "A"
                    in mask_check.getbands()
                )

            if (
                base_size
                != mask_size
                or base_format
                != mask_format
                or not mask_has_alpha
            ):
                raise RuntimeError(
                    "Masked edit base/mask contract failed."
                )

            # EXACTLY ONE provider image call in this function.
            image_bytes = (
                await image_provider.edit(
                    base_image=base_path,
                    mask=mask_path,
                    prompt=prompt,
                    model=model,
                    quality=quality,
                )
            )

        with Image.open(
            io.BytesIO(
                image_bytes
            )
        ) as opened:
            edited_scene = opened.convert(
                "RGB"
            ).copy()

        if (
            edited_scene.size
            != prepared.base_image.size
        ):
            raise RuntimeError(
                "Masked edit returned a different canvas size."
            )

        return edited_scene

    except Exception:
        # Caller enforces fail-closed behavior when this mode is required.
        # There is intentionally no second image call here.
        return None



def _record_masked_scene_usage(
    db: Session,
    *,
    campaign_id: str,
    image_provider: ImageProvider,
    platform: str,
    content_type: str = "",
) -> None:
    """Drain the one successful masked image-edit event at its real callsite.

    BUILD6R_MASKED_SCENE_USAGE_ACCOUNTING_V1

    This remains outside generate_masked_product_scene itself so the
    low-level generation helper has no campaign/DB concerns. It is invoked
    immediately after the successful edit bridge and before rendering.
    """
    record_prompt_usage(
        db,
        campaign_id=campaign_id,
        purpose="scene_generation",
        language="",
        platform=platform,
        extra={
            "mode": "masked_scene_edit",
            "image_edit_calls": 1,
            "image_generate_calls": 0,
        },
    )

    record_stage_usage(
        db,
        campaign_id=campaign_id,
        operation="scene_generation",
        providers=[
            image_provider
        ],
        platform=platform,
        language="",
        content_type=content_type,
    )


async def _apply_masked_scene_edit_if_enabled(
    *,
    config: AutopilotConfig,
    image_provider: ImageProvider | None,
    creative_input: SlideCreativeInput,
) -> bool:
    """Bridge one masked scene into the existing deterministic renderer."""
    if (
        config.require_masked_scene_edit_success
        and not config.use_masked_scene_edit
    ):
        raise RuntimeError(
            "Masked-scene success is required while masked-scene "
            "editing is disabled."
        )

    if not config.use_masked_scene_edit:
        return False

    if config.use_ai_background:
        raise RuntimeError(
            "Masked scene edit and background generation are mutually "
            "exclusive for one slide."
        )

    if config.recreate_with_ai:
        raise RuntimeError(
            "Masked scene edit cannot be combined with full AI "
            "product recreation."
        )

    if image_provider is None:
        if config.require_masked_scene_edit_success:
            raise RuntimeError(
                "Masked scene edit requires an ImageProvider."
            )

        return False

    edited_scene = (
        await generate_masked_product_scene(
            image_provider=image_provider,
            creative_input=creative_input,
            config=config,
        )
    )

    if edited_scene is None:
        if config.require_masked_scene_edit_success:
            raise RuntimeError(
                "Required masked scene edit failed. No second image "
                "call and no background-generation fallback are allowed."
            )

        return False

    # The AI output is treated only as the scene/background. render_slide
    # now performs the one final deterministic approved-product overlay.
    creative_input.generated_background = (
        edited_scene
    )

    creative_input.masked_scene_background = (
        True
    )

    return True


async def recreate_creative_image(
    db: Session,
    *,
    image_provider: ImageProvider,
    brand: Brand,
    category_id: str | None,
    source_image_path: Path,
    model: str,
    width: int,
    height: int,
    angle: str = "",
    main_promise: str = "",
    visual_brief: str = "",
    headline: str = "",
    body: str = "",
    cta: str = "",
    eyebrow: str = "",
    visual_master_path: Path | None = None,
    creative_direction: CreativeDirection | None = None,
    correction_note: str = "",
    quality: str = "high",
) -> Image.Image | None:
    """Best-effort **full** AI recreation of a real source photo — the direct
    answer to "the app should recreate my photo so it fits the campaign, not just
    paste a bit of text on it." Unlike `generate_ai_background` (which generates
    only an empty backdrop and pastes the untouched product on top, see that
    function's docstring), this hands the real product photo itself — plus, when
    uploaded, the user's own inspiration examples (`_resolve_inspiration_paths`) —
    to the image model as reference images on an Images **edit** call
    (`ImageProvider.generate(..., reference_images=[...])` routes there whenever
    reference images are given, see `OpenAIProvider.generate`), so the model
    reimagines the product's scene, lighting, composition and mood together as one
    new image rather than compositing pieces deterministically.

    As of round 18, the prompt asks for the specific commercial production level
    the user's own uploaded design-profile doc (`HSC-PROD-001 — High-Impact
    Product Carousel`) describes: a professionally art-directed advertising
    photograph with real foreground/midground/background depth, polished
    lighting, shadows, reflections, and glow/material detail — not a flat
    editorial card or generic template. This function alone never decides a
    recreation is *safe to ship*, though — see
    `recreate_creative_image_with_fidelity_gate` below, the caller almost every
    part of this app should actually use; this function is the raw generation
    step it wraps.

    `visual_master_path`, when given, is passed as one more reference image (the
    "Campaign Visual Master" concept from the user's uploaded design-profile doc):
    a prior slide in the *same* carousel that already rendered successfully and
    passed its own fidelity check. The model is told to match that slide's
    lighting/palette/material/typography/finish so a multi-slide carousel reads as
    one consistent, art-directed campaign — without copying its exact composition.

    `correction_note`, when given, is appended as a direct correction from a
    failed fidelity check on a prior attempt for this same slide (see
    `recreate_creative_image_with_fidelity_gate`'s one retry) — naming exactly
    which product aspects didn't match so the regeneration has a concrete target
    instead of repeating the same mistake.

    As of round 16, when any of `headline`/`body`/`cta`/`eyebrow` is passed, the
    model is asked to design the marketing text directly into the graphic — bold
    typography, badges, countdown-style callouts, whatever fits the brand — matched
    to the look of the user's own inspiration examples, with an explicit instruction
    to keep it legible (real contrast/backing behind the text, not text floating
    over busy detail). This was a deliberate reversal from the original "no text in
    the AI image, ever" rule this function shipped with: real inspiration ads users
    upload almost always bake dramatic text into the graphic itself, and asking the
    model to leave text out entirely produced two competing, uncoordinated text
    layers when this app's own HTML/CSS headline/body/CTA was then drawn on top of
    an image the model had *also* added its own text to despite being told not to
    (image models are unreliable about obeying "no text" instructions, especially
    when shown text-heavy reference images). The caller is responsible for *not*
    also passing this same text into `SlideCreativeInput`'s eyebrow/headline/body/
    cta fields when this call succeeds — see `run_visuals_stage` and the manual
    `/slides/render` endpoint — so the two layers never compete: either the AI
    designs the whole graphic (text included), or (when no text was passed here, or
    this call fails) this app's own HTML/CSS layer draws it, never both. The brand
    logo is a separate exception either way — always added afterward as real HTML/
    CSS, never left to the model, per the brief's section 65 rule against
    AI-generated logos. The "N/total" slide-number marker is the same — always
    added afterward as real HTML/CSS (see `templates.py::_slide_marker_html`),
    never left to the model.

    The prompt explicitly asks the model to keep the actual product (packaging,
    shape, label, color) accurate to the reference photo rather than inventing a
    different product — this is a restyling of the scene around a real product,
    not a hallucinated substitute for it. Inspiration examples are framed as style/
    mood/format/typography references to draw from, not something to reproduce
    verbatim (their own text/logos/people should not be copied in).

    Returns `None` on ANY failure (bad key, rate limit, malformed image bytes)
    rather than raising, mirroring `generate_ai_background`'s failure handling —
    the caller falls back to the deterministic gradient-plus-paste pipeline that
    has always worked, so a bad response here never takes down a render that would
    otherwise have succeeded.
    """
    try:
        inspiration_paths = _resolve_inspiration_paths(db, brand.id, category_id=category_id, limit=2)
        style_notes = _brand_style_prompt_notes(brand)
        campaign_notes = " ".join(part for part in (angle, main_promise, visual_brief) if part)

        deterministic_text_ownership_note = (
            " DETERMINISTIC TEXT OWNERSHIP: create the visual scene, photography, "
            "environment, lighting, materials and composition only. Do not ADD any "
            "campaign eyebrow, advertising headline, body copy, CTA, promotional badge, "
            "price graphic, discount graphic, floating words, decorative marketing text "
            "or campaign logo. Those exact elements are rendered afterward by the "
            "deterministic HTML/CSS composition layer. Preserve authentic typography, "
            "logos and label text physically printed on the real source product/package "
            "as part of product fidelity; never erase, translate, rewrite, redesign or "
            "invent the real packaging."
        )

        creative_direction_note = ""

        if creative_direction is not None:
            creative_direction_note = (
                " CAMPAIGN-SPECIFIC ART DIRECTION ? this is authoritative. "
                "Do not replace it with a generic product-ad aesthetic. "
                f"Product/category context: {creative_direction.product_category_context!r}. "
                f"Campaign archetype: {creative_direction.campaign_archetype!r}. "
                f"Archetype reasoning: {creative_direction.archetype_reasoning!r}. "
                f"Visual story system: {creative_direction.visual_story_system!r}. "
                f"Hero treatment: {creative_direction.hero_treatment!r}. "
                f"Proof/demo strategy: {creative_direction.proof_or_demo_strategy!r}. "
                f"Visual style: {creative_direction.visual_style!r}. "
                f"Mood: {creative_direction.mood!r}. "
                f"Composition: {creative_direction.composition!r}. "
                f"Product position: {creative_direction.product_position!r}. "
                f"Product scale: {creative_direction.product_scale!r}. "
                f"Background: {creative_direction.background_concept!r}. "
                f"Lighting: {creative_direction.lighting!r}. "
                f"Depth: {creative_direction.depth!r}. "
                f"Texture: {creative_direction.texture!r}. "
                f"Palette: {creative_direction.palette!r}. "
                f"Negative space: {creative_direction.negative_space!r}. "
                f"Scene instruction: {creative_direction.scene_generation_prompt!r}. "
                "Do not automatically convert unrelated products into "
                "black/gold, cyber, neon, nightclub, pedestal or cosmetics advertising."
            )

        reference_images = [source_image_path, *inspiration_paths]
        master_note = ""
        if visual_master_path is not None and visual_master_path.exists():
            reference_images.append(visual_master_path)
            master_note = (
                " One more reference image follows the product/inspiration photos: an earlier, "
                "already-approved slide from this SAME carousel campaign. Match its lighting "
                "language, color palette, material treatment, typography system, and overall "
                "photographic/commercial finish so this slide clearly belongs to the same "
                "art-directed campaign world — but do not duplicate its exact composition; create "
                "a new, distinct shot that happens to share its visual system."
            )
        inspiration_note = (
            " Draw creative-direction inspiration (mood, composition, format, and typography style) from "
            "the additional reference image(s) that follow the product photo, without copying their exact "
            "text, logos, or people."
            if inspiration_paths
            else ""
        )
        text_parts = [
            f"Eyebrow/kicker text: {eyebrow!r}." if eyebrow else "",
            f"Headline: {headline!r}." if headline else "",
            f"Supporting text: {body!r}." if body else "",
            f"Call to action: {cta!r}." if cta else "",
        ]
        text_note = " ".join(p for p in text_parts if p)
        if text_note:
            text_instruction = (
                " Design this exact marketing text directly into the graphic as bold, on-brand "
                f"typography — {text_note} Give the text (and any badges/callouts you add) proper "
                "contrast and a real backing — a solid or gradient panel, a scrim, a shape behind "
                "it — so every word stays fully legible against the photo, never floating "
                "unsupported over busy detail. Keep the text accurate to what's given above; do not "
                "invent additional slogans or numbers beyond it."
            )
            logo_instruction = " Do not render any logo — the real brand logo is added separately afterward."
        else:
            text_instruction = ""
            logo_instruction = (
                " Do not render any text, words, captions, or logos anywhere in the image — those are "
                "added separately afterward."
            )
        correction_instruction = (
            f" CRITICAL CORRECTION from a prior attempt at this same slide: {correction_note} Fix this "
            "exactly — the product's real packaging, shape, label, logo, text, closure, and color must "
            "all be unmistakably accurate to the reference product photo. If you cannot render it "
            "accurately, keep the product region closer to a direct, lightly restyled photo of the "
            "actual reference rather than a stylized reinterpretation."
            if correction_note
            else ""
        )
        # Round 20: a baseline claims-safety instruction, added after comparing this
        # app's output against several of the user's own custom GPTs — some of
        # which explicitly forbid an image model from inventing exactly this list
        # of unverifiable claim graphics (matching this app's own existing
        # anti-fabrication discipline elsewhere: real stock counts only, never
        # simulated FOMO numbers, real before/afters only). Applies unconditionally
        # — with or without baked-in text — since an image model can add a graphic
        # badge/callout on its own even when not asked to render any text at all.
        claims_safety_instruction = (
            " Do not invent or render any scarcity/low-stock badge or counter, a countdown timer or "
            "date, a price or discount graphic, a review-star rating or testimonial quote, a "
            "bestseller/No.1/rank badge, a clinical or safety-certification seal, a before/after result, "
            "a competitor-comparison graphic, fast-delivery imagery, a VIP/membership badge, a restock/"
            "early-access/priority-shipping graphic, a 'surprise gift' or bonus callout, or a customer/"
            "follower-count badge — none of these are verified for this specific product/campaign, so "
            "none should appear unless explicitly requested above."
        )
        prompt = (
            "Recreate this exact real product as a premium, professionally art-directed commercial "
            f"marketing photograph for the brand '{brand.name}' — the production level of a finished "
            "advertising campaign, not a simple editorial post, brand-book page, or generic social "
            "template. Give it clear foreground/midground/background depth, dimensional composition, "
            "and polished lighting with real shadows, reflections, and glow or material detail where "
            "appropriate (glass, liquid, metal, or packaging sheen), so the product itself reads as a "
            "dramatic hero object in the frame. The product's own authentic packaging colors may drive "
            "the scene's palette when that creates stronger commercial impact — do not force a "
            "generic or unrelated color scheme onto it.\n\n"
            "Keep the product itself — its packaging, shape, label, logo, visible text, cap/pump/"
            "dropper or other closure, and colors — completely accurate and recognizable to the "
            "reference photo; this is a restyling of the scene AROUND a real, unaltered product, never "
            "a redesigned, generic, or fictional lookalike standing in for it. When in doubt between a "
            "bolder reinterpretation and product accuracy, always choose accuracy.\n\n"
            f"{style_notes} {campaign_notes}{creative_direction_note}{deterministic_text_ownership_note}{inspiration_note}{master_note}"
            f"{text_instruction}{logo_instruction}{correction_instruction}{claims_safety_instruction}"
            f"{_mobile_hierarchy_instruction}"
        ).strip()
        size = _nearest_ai_image_size(width, height, model=model)
        image_bytes = await image_provider.generate(
            prompt=prompt, size=size, model=model, reference_images=reference_images, quality=quality,
        )
        return Image.open(io.BytesIO(image_bytes)).convert("RGB")
    except Exception:  # noqa: BLE001 - best-effort; caller falls back to the deterministic pipeline
        return None


@dataclass
class RecreationOutcome:
    """Result of `recreate_creative_image_with_fidelity_gate` — never just an
    `Image.Image | None`, because a caller (`run_visuals_stage`) needs to know
    *whether the image was actually verified* to decide if it's safe to use as a
    `visual_master_path` reference for later slides in the same carousel, and the
    QA record needs `fidelity_notes` for a human reviewer even when the gate
    ultimately fell back to the deterministic pipeline.
    """

    image: Image.Image | None
    verified: bool = False
    attempts: int = 0
    fidelity_notes: str = ""


def _mismatched_aspects_note(check: ProductFidelityCheck) -> str:
    """Turns a failed/uncertain ProductFidelityCheck into a short, concrete
    correction note naming exactly which aspects didn't match — fed back into
    `recreate_creative_image`'s `correction_note` on the one retry, rather than
    just re-asking with the same prompt and hoping for a different result.
    """
    aspect_labels = {
        "package_shape": "package shape",
        "proportions": "proportions",
        "brand_logo": "brand/logo",
        "label_structure": "label structure",
        "visible_text": "visible text on the package",
        "cap_or_closure": "cap/pump/dropper or other closure",
        "color": "color",
        "distinctive_marks": "distinctive marks",
    }
    bad = [
        label
        for field_name, label in aspect_labels.items()
        if getattr(check, field_name) == "mismatch"
    ]
    parts = []
    if bad:
        parts.append(f"The following did not match the real product: {', '.join(bad)}.")
    if check.reasoning:
        parts.append(check.reasoning)
    return " ".join(parts) or "The product in the recreated image did not clearly match the real reference photo."


async def recreate_creative_image_with_fidelity_gate(
    db: Session,
    *,
    image_provider: ImageProvider,
    ai_provider: AIProvider,
    brand: Brand,
    category_id: str | None,
    source_image_path: Path,
    model: str,
    vision_model: str,
    width: int,
    height: int,
    angle: str = "",
    main_promise: str = "",
    visual_brief: str = "",
    headline: str = "",
    body: str = "",
    cta: str = "",
    eyebrow: str = "",
    visual_master_path: Path | None = None,
    creative_direction: CreativeDirection | None = None,
    quality: str = "high",
    revision_model: str = "",
) -> RecreationOutcome:
    """The round-18 answer to the round-17 problem: rather than leaving full AI
    recreation off by default forever because it's unreliable, verify each
    attempt against the real source product photo the same way the user's own
    uploaded GPT-based review system does (their content-and-creative-review
    rubric's "H. Product fidelity" check — "Fail if the creative replaces the
    real product with a fictional lookalike or redesign") and never trust a
    generation that doesn't clearly pass it.

    Flow: generate once via `recreate_creative_image`; if that fails outright,
    stop (no image to verify). Otherwise run `AIProvider.check_product_fidelity`
    against it. A `PASS` verdict returns the image as verified. Anything else — an
    explicit `FAIL`, or the check itself failing/erroring (treated the same way,
    fail-closed, per the user's own uploaded rule "a blocker is better than
    invented content") — triggers exactly ONE retry with a corrective prompt
    naming the specific mismatched aspects. If the retry isn't a verified PASS
    either, this gives up and returns `image=None` so the caller falls back to
    the deterministic pipeline — a slide with the wrong product, or an
    unverifiable one, is never shipped silently.

    This never raises — every failure mode (generation failure, check failure,
    check exception) resolves to a `RecreationOutcome`, matching every other
    best-effort AI hook in this module.
    """
    attempts = 0
    correction_note = ""
    last_notes = ""

    for attempt_number in (1, 2):
        attempts = attempt_number
        # Build 2 (Part D): the one corrective retry (attempt 2) routes through
        # `revision_model` when one was given — e.g. a stronger/differently
        # tuned model for a correction pass — falling back to the same `model`
        # attempt 1 used when `revision_model` is unset, so a caller that never
        # passes it behaves exactly as before this parameter existed.
        attempt_model = model if attempt_number == 1 else (revision_model or model)
        candidate = await recreate_creative_image(
            db, image_provider=image_provider, brand=brand, category_id=category_id,
            source_image_path=source_image_path, model=attempt_model, width=width, height=height,
            angle=angle, main_promise=main_promise, visual_brief=visual_brief,
            headline=headline, body=body, cta=cta, eyebrow=eyebrow,
            visual_master_path=visual_master_path,
            creative_direction=creative_direction,
            correction_note=correction_note,
            quality=quality,
        )
        if candidate is None:
            return RecreationOutcome(
                image=None, verified=False, attempts=attempts,
                fidelity_notes=last_notes or "Image generation failed.",
            )

        tmp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp_file:
                candidate.save(tmp_file, format="PNG")
                tmp_path = Path(tmp_file.name)
            check: ProductFidelityCheck | None = None
            try:
                check = await ai_provider.check_product_fidelity(
                    source_image_path=source_image_path, generated_image_path=tmp_path, model=vision_model,
                )
            except Exception:  # noqa: BLE001 - fail-closed: an unverifiable check is never treated as a pass
                check = None
        finally:
            if tmp_path is not None:
                tmp_path.unlink(missing_ok=True)

        if check is not None and check.overall_verdict == "PASS":
            return RecreationOutcome(image=candidate, verified=True, attempts=attempts, fidelity_notes=check.reasoning)

        last_notes = (
            _mismatched_aspects_note(check) if check is not None
            else "Product fidelity check could not be completed (provider error) — treated as not verified."
        )
        correction_note = last_notes

    return RecreationOutcome(image=None, verified=False, attempts=attempts, fidelity_notes=last_notes)


async def detect_product_zone(
    *, ai_provider: AIProvider, image_path: Path, model: str
) -> ProductZoneDetection | None:
    """Best-effort per-photo product-zone detection (opt-in, mirrors
    `generate_ai_background`'s failure handling above): a vision-model call that
    looks at one real source photo and returns the tight crop box around the
    actual product plus which edge it's anchored to (see `ProductZoneDetection`),
    so `services/creative/pipeline.py::render_slide` can fill the template's
    product zone with just the product instead of assuming every uploaded photo
    happens to already be framed the way the template's one fixed layout expects.

    Returns `None` on ANY failure (bad key, rate limit, malformed response) rather
    than raising — this is a refinement layered on a pipeline that has always
    worked with the template's default full-frame placement, so a photo that can't
    be analyzed still renders fine; it just doesn't get this per-photo refinement.
    """
    try:
        return await ai_provider.detect_product_zone(image_path=image_path, model=model)
    except Exception:  # noqa: BLE001 - best-effort; caller falls back to the template's fixed zone
        return None


def resolve_brand_colors(brand: Brand) -> list[str] | None:
    """Shared with the manual per-slide render endpoint (api/campaigns.py) so both
    paths derive the creative pipeline's background gradient the same way.
    """
    if isinstance(brand.colors, dict) and brand.colors:
        colors = [v for v in brand.colors.values() if isinstance(v, str) and v.strip()]
        return colors or None
    return None


def resolve_brand_logo_path(db: Session, brand_id: str) -> Path | None:
    logo_asset = db.query(BrandAsset).filter(BrandAsset.brand_id == brand_id, BrandAsset.kind == "logo").first()
    if logo_asset is None:
        return None
    candidate = Path(logo_asset.file_path)
    return candidate if candidate.exists() else None


def _audit(db: Session, campaign_id: str, action: str, detail: dict) -> None:
    db.add(AuditEvent(entity_type="campaign", entity_id=campaign_id, action=action, detail=detail))


def _load_campaign_context(db: Session, campaign_id: str) -> tuple[Campaign, Brand, Category | None, Product | None]:
    """Shared by all three stages: load and validate the campaign/brand/category/
    product rows a stage needs, without any status guard — each stage applies its
    own guard appropriate to what it depends on (see each function's docstring).
    """
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise ValueError(f"Campaign {campaign_id} not found.")
    brand = db.get(Brand, campaign.brand_id)
    if brand is None:
        raise ValueError("Brand not found for this campaign.")
    category = db.get(Category, campaign.category_id) if campaign.category_id else None
    product = db.get(Product, campaign.product_id) if campaign.product_id else None
    return campaign, brand, category, product


def _brief_json_path(
    config: AutopilotConfig, *, brand_slug: str, category_slug: str, campaign_display_id: str,
    year: int, month: int, name: str,
) -> Path:
    """Same deterministic folder scheme as slide/QA outputs (README.md /
    architecture.md), under a `brief/` subfolder: OUTPUT_ROOT/<brand>/<category>/
    <year>/<year-month>/<campaign>/brief/<name>.json.
    """
    return (
        config.output_root / brand_slug / category_slug / f"{year:04d}" / f"{year:04d}-{month:02d}"
        / campaign_display_id / "brief" / f"{name}.json"
    )


def _save_stage_json(
    db: Session, *, campaign: Campaign, brand_slug: str, category_slug: str, config: AutopilotConfig,
    kind: str, data: dict,
) -> Path:
    """Persists one stage's structured output to disk and tracks it as a
    `CampaignOutput` row of that `kind` — this is what lets a later stage (possibly
    in a different request) read the data back via `_load_stage_json`. Replaces any
    prior row/file of the same kind for this campaign rather than accumulating
    versions, matching the same "a retry doesn't leave stale duplicates" discipline
    already used for slide/QA outputs.
    """
    now = datetime.now(timezone.utc)
    path = _brief_json_path(
        config, brand_slug=brand_slug, category_slug=category_slug, campaign_display_id=campaign.display_id,
        year=now.year, month=now.month, name=kind,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))
    db.query(CampaignOutput).filter(CampaignOutput.campaign_id == campaign.id, CampaignOutput.kind == kind).delete()
    db.add(CampaignOutput(campaign_id=campaign.id, kind=kind, file_path=str(path)))
    return path


def _load_stage_json(db: Session, campaign_id: str, kind: str) -> dict | None:
    """Reads back a prior stage's output. Returns None (never raises) when nothing
    was persisted yet, or the file has since gone missing/corrupt — callers turn
    that into a clear "run the prior stage first" ValueError rather than a confusing
    file-system error.
    """
    row = (
        db.query(CampaignOutput)
        .filter(CampaignOutput.campaign_id == campaign_id, CampaignOutput.kind == kind)
        .order_by(CampaignOutput.created_at.desc())
        .first()
    )
    if row is None or not row.file_path:
        return None
    path = Path(row.file_path)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def get_campaign_copy(db: Session, campaign_id: str, language: str | None = None) -> CampaignCopy | None:
    """Public read-only accessor for the Copy stage's persisted output, for callers
    outside this module that need the real caption/hashtags a campaign already has —
    e.g. the auto-publish endpoint (`app/api/campaigns.py`), which defaults a Meta
    post's caption to whatever Copy generated rather than re-deriving or fabricating
    one. Deliberately public (no leading underscore) unlike `_load_stage_json`, which
    stays private/untyped since only this module's own stages call it directly.

    Build 1: `language` selects which of a multi-language campaign's independent
    `CampaignCopy` variants to return (see `run_copy_stage`'s new per-language
    persistence shape and `_stage_language_variant`) — `None` (the default, and
    what every existing caller still passes) returns the campaign's primary
    language, so this stays backward compatible for both pre-Build-1 persisted
    campaigns (flat shape) and every existing call site.
    """
    data = _load_stage_json(db, campaign_id, "copy")
    variant = _stage_language_variant(data, language)
    return CampaignCopy(**variant) if variant else None


def check_copy_stage_prerequisite(db: Session, campaign_id: str) -> None:
    """Raises the same `ValueError` `run_copy_stage` raises if Strategy hasn't run
    yet for this campaign — split out (deliberately public, unlike
    `_load_stage_json`) so `POST /api/campaigns/{id}/generate/copy` can check this
    synchronously, before queuing the background job, and 400 immediately with a
    clear message instead of only discovering the same problem once the job runs
    and fails asynchronously (see api/campaigns.py's module docstring for why the
    job itself runs in the background). `run_copy_stage` still calls this too, so
    a caller that invokes it directly (tests, `run_autopilot`) gets the same guard.
    """
    if _load_stage_json(db, campaign_id, "strategy") is None:
        raise ValueError(
            "Run the Strategy stage for this campaign before generating copy — no accepted strategy "
            "is on file yet."
        )


def check_visuals_stage_prerequisite(db: Session, campaign_id: str) -> None:
    """Same idea as `check_copy_stage_prerequisite`, for `/generate/visuals` and
    `run_visuals_stage`.
    """
    copy_data = _load_stage_json(db, campaign_id, "copy")
    creative_data = _load_stage_json(db, campaign_id, "creative")
    if copy_data is None or creative_data is None:
        raise ValueError(
            "Run the Copy stage for this campaign before generating visuals — no campaign copy or "
            "carousel plan is on file yet."
        )


def _slide_plan_to_dict(slide) -> dict:
    """Handles both a real `SlidePlan` (has `.model_dump()`) and the plain
    `SlidePlanFallback` object used when the model returns an empty slide list.
    """
    if hasattr(slide, "model_dump"):
        return slide.model_dump()
    return {
        "slide_number": getattr(slide, "slide_number", 0),
        "purpose": slide.purpose,
        "eyebrow": slide.eyebrow,
        "headline": slide.headline,
        "body": slide.body,
        "cta": slide.cta,
        "visual_brief": slide.visual_brief,
        "badge_text": getattr(slide, "badge_text", ""),
        "intro": getattr(slide, "intro", ""),
        "features": getattr(slide, "features", []),
        "callout_label": getattr(slide, "callout_label", ""),
        "callout_value": getattr(slide, "callout_value", ""),
        "bottom_features": getattr(slide, "bottom_features", []),
        "trust_badges": getattr(slide, "trust_badges", []),
    }


def _select_candidate_assets(
    db: Session, *, brand_id: str, category_id: str | None, product_id: str | None, limit: int
) -> list[Asset]:
    """Return canonical non-reconstructed source assets only.

    Strategy, factual source resolution, and QA authority continue to use this
    selector so an AI-derived product master can never silently become its own
    factual authority.
    """
    from .product_asset_selection import select_source_assets

    return select_source_assets(
        db,
        brand_id=brand_id,
        category_id=category_id,
        product_id=product_id,
        limit=limit,
    )


def _select_render_assets(
    db: Session, *, brand_id: str, category_id: str | None, product_id: str | None, limit: int
) -> list[Asset]:
    """Prefer an approved product master, with canonical-source fallback."""
    from .product_asset_selection import select_render_assets

    return select_render_assets(
        db,
        brand_id=brand_id,
        category_id=category_id,
        product_id=product_id,
        limit=limit,
    )


def _strategy_type_fact_hard_fails(
    *,
    brand: Brand,
    verified,
    strategy_type: CampaignStrategyType,
) -> list[str]:
    """Evaluate Strategy Library factual framing against canonical evidence."""

    if verified is None:
        return []

    from .claims_audit import (
        audit_text_fields,
        format_claims_hard_fails,
    )

    fields = {
        "strategy_type.name":
            str(
                getattr(
                    strategy_type,
                    "name",
                    "",
                )
                or ""
            ),

        "strategy_type.objective":
            str(
                getattr(
                    strategy_type,
                    "objective",
                    "",
                )
                or ""
            ),

        "strategy_type.example":
            str(
                getattr(
                    strategy_type,
                    "example",
                    "",
                )
                or ""
            ),

        "strategy_type.trigger_description":
            str(
                getattr(
                    strategy_type,
                    "trigger_description",
                    "",
                )
                or ""
            ),

        "strategy_type.audience":
            str(
                getattr(
                    strategy_type,
                    "audience",
                    "",
                )
                or ""
            ),

        "strategy_type.notes":
            str(
                getattr(
                    strategy_type,
                    "notes",
                    "",
                )
                or ""
            ),
    }

    result = audit_text_fields(
        fields=fields,
        verified=verified,
        brand=brand,
    )

    return list(
        dict.fromkeys(
            format_claims_hard_fails(
                result
            )
        )
    )



# Build 6R ? universal deterministic Strategy Library applicability gate.
#
# Every Strategy Library type represents a real campaign approach with an
# applicability condition. Product facts establish product truth; they do
# not establish that a campaign trigger, offer, customer state, inventory
# condition, competitor event, schedule, partnership, promotion, or manual
# business decision currently exists.
#
# Existing Brand.campaign_rules provides the owner-controlled contract:
#
#   verified_operational_strategy_keys: list[str]
#
# A Strategy Library key is eligible only when explicitly listed there.
#
# This field controls strategy applicability only. It is NOT product-claim
# evidence and is never inferred from research, prior Campaign rows, model
# output, performance history, or the Strategy Library description itself.
_STRATEGY_OPERATIONAL_EVIDENCE_RULE_KEY = (
    "verified_operational_strategy_keys"
)


def _strategy_type_operational_hard_fails(
    *,
    brand: Brand | None,
    strategy_type: CampaignStrategyType,
) -> list[str]:

    strategy_key = str(
        getattr(
            strategy_type,
            "key",
            "",
        )
        or ""
    ).strip()


    if not strategy_key:

        return [
            (
                "[strategy_operational_evidence] "
                "strategy_type.key is missing."
            )
        ]


    rules = (
        getattr(
            brand,
            "campaign_rules",
            None,
        )
        if brand is not None
        else None
    )


    if not isinstance(
        rules,
        dict,
    ):

        rules = {}


    approved = rules.get(
        _STRATEGY_OPERATIONAL_EVIDENCE_RULE_KEY,
        [],
    )


    if not isinstance(
        approved,
        list,
    ):

        approved = []


    approved_keys = {
        str(value).strip()
        for value in approved
        if str(value).strip()
    }


    if strategy_key in approved_keys:

        return []


    return [
        (
            "[strategy_operational_evidence] "
            f"strategy_type.key {strategy_key!r} has no "
            "verified applicability evidence in "
            "brand.campaign_rules."
            f"{_STRATEGY_OPERATIONAL_EVIDENCE_RULE_KEY}"
        )
    ]


def _select_underused_strategy_type(
    db: Session,
    *,
    brand_id: str,
    category_id: str | None,
    brand: Brand | None = None,
    verified_product_facts=None,
) -> CampaignStrategyType | None:
    """Pick the least-used fact-compatible active strategy.

    Existing usage rotation and performance tie-breaking are preserved.
    """

    types = (
        db.query(
            CampaignStrategyType
        )
        .filter(
            CampaignStrategyType
            .is_active
            .is_(
                True
            )
        )
        .all()
    )

    if not types:
        return None


    if (
        brand is not None
        and verified_product_facts is not None
    ):
        candidate_types = [
            strategy_type
            for strategy_type in types
            if not _strategy_type_fact_hard_fails(
                brand=brand,
                verified=verified_product_facts,
                strategy_type=strategy_type,
            )
        ]
    else:
        candidate_types = types


    # Build 6R operational-prerequisite filter.
    if brand is not None:
        candidate_types = [
            strategy_type
            for strategy_type in candidate_types
            if not _strategy_type_operational_hard_fails(
                brand=brand,
                strategy_type=strategy_type,
            )
        ]


    if not candidate_types:
        return None


    usage_q = (
        db.query(
            Campaign.strategy_type_id
        )
        .filter(
            Campaign.brand_id
            == brand_id,
            Campaign.strategy_type_id
            .isnot(
                None
            ),
        )
    )


    if category_id:
        usage_q = usage_q.filter(
            Campaign.category_id
            == category_id
        )


    usage_counts: dict[str, int] = {}


    for (
        strategy_type_id,
    ) in usage_q.all():

        usage_counts[
            strategy_type_id
        ] = (
            usage_counts.get(
                strategy_type_id,
                0,
            )
            + 1
        )


    return min(
        candidate_types,
        key=lambda strategy_type: (
            usage_counts.get(
                strategy_type.id,
                0,
            ),

            -average_engagement_rate_for_strategy_type(
                db,
                brand_id=brand_id,
                strategy_type_id=strategy_type.id,
            ),

            strategy_type.family_id,
            strategy_type.name,
        ),
    )



def _recent_fingerprints(
    db: Session, *, brand_id: str, category_id: str | None, exclude_campaign_id: str
) -> list[dict]:
    q = (
        db.query(CampaignFingerprint)
        .join(Campaign, Campaign.id == CampaignFingerprint.campaign_id)
        .filter(Campaign.brand_id == brand_id, Campaign.id != exclude_campaign_id)
    )
    if category_id:
        q = q.filter(Campaign.category_id == category_id)
    return [
        {"campaign_id": fp.campaign_id, "text_hash": fp.text_hash, "summary": fp.promise_summary}
        for fp in q.all()
    ]


class PreVisualClaimGroundingError(RuntimeError):
    """Raised when generated campaign material contains a factual
    marketing claim that canonical evidence does not support.

    This gate is deterministic and performs no network call. It exists
    specifically to stop unsupported copy before any paid vision/image
    work begins.
    """


def _collect_previsual_claim_text_fields(
    value,
    *,
    prefix: str,
    fields: dict[str, str],
) -> None:
    """Flatten generated campaign structures into auditable text fields."""

    if value is None:
        return

    if isinstance(value, str):
        text = value.strip()

        if text:
            fields[prefix] = text

        return

    if isinstance(value, dict):
        for key, child in value.items():
            # `must_avoid` is internal negative guidance, not an assertion
            # that the campaign makes. Auditing its contents as claims would
            # falsely reject a concept merely for saying, for example, that
            # an unsupported ranking claim must NOT be used.
            if str(key) == "must_avoid":
                continue

            child_prefix = (
                f"{prefix}.{key}"
                if prefix
                else str(key)
            )

            _collect_previsual_claim_text_fields(
                child,
                prefix=child_prefix,
                fields=fields,
            )

        return

    if isinstance(
        value,
        (
            list,
            tuple,
        ),
    ):
        for index, child in enumerate(
            value,
            start=1,
        ):
            _collect_previsual_claim_text_fields(
                child,
                prefix=(
                    f"{prefix}[{index}]"
                ),
                fields=fields,
            )


def _enforce_previsual_claim_grounding_gate(
    db: Session,
    *,
    campaign: Campaign,
    brand: Brand,
    product,
    phase: str,
    structures: dict,
) -> list[str]:
    """Fail before vision/image generation when product claims are unsupported.

    Deep-dive product campaigns are checked against canonical
    VerifiedProductFacts plus owner-confirmed brand facts using the
    existing deterministic claims engine.

    Multi-product/category discovery is deliberately left to its existing
    per-product grounding path for now; treating several products as if
    they shared one VerifiedProductFacts record would be incorrect.
    """

    if product is None:
        return []

    from .claims_audit import (
        audit_text_fields,
        format_claims_hard_fails,
    )

    fields: dict[str, str] = {}

    for root_name, value in structures.items():
        _collect_previsual_claim_text_fields(
            value,
            prefix=root_name,
            fields=fields,
        )

    verified = (
        resolve_verified_product_facts(
            db,
            product,
        )
    )

    result = audit_text_fields(
        fields=fields,
        verified=verified,
        brand=brand,
    )

    # One phrase may occur repeatedly inside the same generated field.
    # Preserve the first evidence record, but do not emit the exact same
    # hard-fail message multiple times.
    hard_fails = list(
        dict.fromkeys(
            format_claims_hard_fails(
                result
            )
        )
    )

    if not hard_fails:
        return []

    campaign.status = "FAILED"

    _audit(
        db,
        campaign.id,
        "previsual_claim_grounding_failed",
        {
            "phase": phase,
            "field_count": len(fields),
            "hard_fail_count": len(hard_fails),
            "hard_fails": hard_fails,
        },
    )

    db.commit()

    shown = hard_fails[:8]

    summary = " | ".join(
        shown
    )

    if len(hard_fails) > len(shown):
        summary += (
            f" | ... and "
            f"{len(hard_fails) - len(shown)} "
            "additional unsupported claim(s)"
        )

    raise PreVisualClaimGroundingError(
        "PREVISUAL_UNSUPPORTED_CLAIM: "
        + summary
    )

# =====================================================================
# BUILD6R_STRATEGY_COMPATIBILITY_EARLY_PREFLIGHT_V4
# =====================================================================


_BUILD6R_CREATIVE_BRIEF_NEUTRALIZABLE_CLAIM_CATEGORIES = frozenset(
    {
        "ranking_bestseller",
        "ranking_or_bestseller",
    }
)


_BUILD6R_CREATIVE_BRIEF_FIELDS = (
    "design_concept",
    "visual_prompt",
    "template_suggestion",
    "tone_notes",
)


_BUILD6R_NEUTRAL_DESIGN_CONCEPT = (
    "Premium product hero with balanced negative space "
    "and restrained brand-compatible styling"
)


_BUILD6R_NEUTRAL_TEMPLATE_SUGGESTION = (
    "premium_product_hero"
)


_BUILD6R_NEUTRAL_TONE_NOTES = (
    "Warm, restrained and editorial"
)


def _unsupported_claim_findings(
    result,
):
    return [
        finding
        for finding
        in getattr(
            result,
            "findings",
            [],
        )
        if str(
            getattr(
                finding,
                "evidence_status",
                "",
            )
        ).upper()
        == "UNSUPPORTED"
    ]


def _neutralize_creative_brief_ranking_only(
    db: Session,
    *,
    campaign: Campaign,
    brand: Brand,
    product,
    creative_brief: CreativeBrief,
) -> CreativeBrief:
    """Recover only cross-field ranking/bestseller CreativeBrief drift.

    This is deliberately NOT a general claim sanitizer.

    Every CreativeBrief free-text field is audited independently with the
    existing deterministic canonical claims engine.

    Recovery is allowed only when every unsupported finding across the entire
    CreativeBrief is exclusively a ranking/bestseller category.

    Clean fields are preserved unchanged. Contaminated fields are replaced
    with fixed claim-neutral creative language. No provider/model/network/
    research/image/regeneration boundary exists in this function.

    The caller must still execute the complete existing canonical grounding
    gate on the repaired CreativeBrief immediately afterward.
    """

    if product is None:

        return creative_brief

    from .claims_audit import (
        audit_text_fields,
    )

    verified = (
        resolve_verified_product_facts(
            db,
            product,
        )
    )

    original_fields = {
        "design_concept":
            creative_brief.design_concept,

        "visual_prompt":
            creative_brief.visual_prompt,

        "template_suggestion":
            creative_brief.template_suggestion,

        "tone_notes":
            creative_brief.tone_notes,
    }

    unsupported_by_field = {}

    for field_name in (
        _BUILD6R_CREATIVE_BRIEF_FIELDS
    ):

        result = audit_text_fields(
            fields={
                (
                    "creative_brief."
                    + field_name
                ):
                    original_fields[
                        field_name
                    ],
            },
            verified=verified,
            brand=brand,
        )

        unsupported = (
            _unsupported_claim_findings(
                result
            )
        )

        if unsupported:

            unsupported_by_field[
                field_name
            ] = unsupported


    if not unsupported_by_field:

        return creative_brief


    all_categories = {
        str(
            getattr(
                finding,
                "claim_category",
                "",
            )
        )
        for findings
        in unsupported_by_field.values()
        for finding
        in findings
    }


    if (
        not all_categories
        or not all_categories.issubset(
            _BUILD6R_CREATIVE_BRIEF_NEUTRALIZABLE_CLAIM_CATEGORIES
        )
    ):

        # Mixed or non-ranking unsupported claims remain untouched so the
        # existing full canonical gate fails closed exactly as before.
        return creative_brief


    contaminated_fields = set(
        unsupported_by_field
    )

    updates = {}


    if (
        "design_concept"
        in contaminated_fields
    ):

        updates[
            "design_concept"
        ] = (
            _BUILD6R_NEUTRAL_DESIGN_CONCEPT
        )


    repaired_design_concept = str(
        updates.get(
            "design_concept",
            creative_brief.design_concept,
        )
        or _BUILD6R_NEUTRAL_DESIGN_CONCEPT
    ).strip()


    if (
        "template_suggestion"
        in contaminated_fields
    ):

        updates[
            "template_suggestion"
        ] = (
            _BUILD6R_NEUTRAL_TEMPLATE_SUGGESTION
        )


    if (
        "tone_notes"
        in contaminated_fields
    ):

        updates[
            "tone_notes"
        ] = (
            _BUILD6R_NEUTRAL_TONE_NOTES
        )


    if (
        "visual_prompt"
        in contaminated_fields
    ):

        updates[
            "visual_prompt"
        ] = (
            repaired_design_concept
            + ". "
            + "Use a claim-neutral product composition derived only from this "
              "creative direction. Keep the product as the clear visual focus. "
              "Use neutral lighting, spacing, background, scale and "
              "brand-compatible styling. Do not add badges, rankings, awards, "
              "endorsements, popularity signals, numerical claims, results, "
              "prices, discounts, scarcity, availability claims, "
              "certifications or other factual assertions."
        )


    repaired = (
        creative_brief.model_copy(
            update=updates
        )
    )


    categories_by_field = {
        field_name:
            sorted(
                {
                    str(
                        getattr(
                            finding,
                            "claim_category",
                            "",
                        )
                    )
                    for finding
                    in findings
                }
            )
        for (
            field_name,
            findings,
        )
        in unsupported_by_field.items()
    }


    _audit(
        db,
        campaign.id,
        "creative_brief_ranking_fields_locally_neutralized",
        {
            "repair":
                "creative_brief_cross_field_ranking_bestseller_only",

            "neutralized_fields":
                sorted(
                    contaminated_fields
                ),

            "claim_categories":
                sorted(
                    all_categories
                ),

            "claim_categories_by_field":
                categories_by_field,

            "replacement_mode":
                "deterministic_claim_neutral_local_fallbacks",

            "provider_calls":
                0,

            "model_calls":
                0,

            "network_calls":
                0,

            "research_calls":
                0,

            "image_calls":
                0,

            "full_grounding_gate_required_after_repair":
                True,
        },
    )


    return repaired



# =====================================================================
# BUILD6R_CREATIVEBRIEF_BEFORE_AFTER_ONLY_RECOVERY_V1
#
# Separate bounded local recovery for CreativeBrief drift whose complete
# unsupported-finding set is exclusively the existing deterministic
# `transformation_results` category.
#
# This does NOT broaden ranking/bestseller recovery and is NOT a general
# sanitizer. Mixed categories remain untouched and fail closed at the
# unchanged canonical grounding gate.
# =====================================================================

_BUILD6R_CREATIVE_BRIEF_BEFORE_AFTER_ONLY_CATEGORIES = frozenset(
    {
        "transformation_results",
    }
)


_BUILD6R_NEUTRAL_BEFORE_AFTER_VISUAL_PROMPT = (
    "Premium product hero on a clean brand-compatible background with "
    "balanced negative space. Keep the product as the clear visual focus. "
    "Use neutral lighting, spacing, scale and restrained decorative styling."
)


def _neutralize_creative_brief_before_after_only(
    db: Session,
    *,
    campaign: Campaign,
    brand: Brand,
    product,
    creative_brief: CreativeBrief,
) -> CreativeBrief:
    """Recover only transformation-results CreativeBrief drift locally.

    Eligibility is intentionally strict:

    - every CreativeBrief free-text field is audited independently;
    - there must be at least one unsupported finding;
    - every unsupported finding across all four fields must have the exact
      deterministic category `transformation_results`;
    - any mixed or different category returns the original object unchanged;
    - only contaminated fields are replaced;
    - no provider/model/network/research/image/regeneration call exists here;
    - the caller must still execute the unchanged full canonical grounding
      gate immediately afterward.
    """

    if product is None:

        return creative_brief

    from .claims_audit import (
        audit_text_fields,
    )

    verified = (
        resolve_verified_product_facts(
            db,
            product,
        )
    )

    original_fields = {
        "design_concept":
            creative_brief.design_concept,

        "visual_prompt":
            creative_brief.visual_prompt,

        "template_suggestion":
            creative_brief.template_suggestion,

        "tone_notes":
            creative_brief.tone_notes,
    }

    unsupported_by_field = {}

    for field_name in (
        _BUILD6R_CREATIVE_BRIEF_FIELDS
    ):

        result = audit_text_fields(
            fields={
                (
                    "creative_brief."
                    + field_name
                ):
                    original_fields[
                        field_name
                    ],
            },
            verified=verified,
            brand=brand,
        )

        unsupported = (
            _unsupported_claim_findings(
                result
            )
        )

        if unsupported:

            unsupported_by_field[
                field_name
            ] = unsupported


    if not unsupported_by_field:

        return creative_brief


    all_categories = {
        str(
            getattr(
                finding,
                "claim_category",
                "",
            )
        )
        for findings
        in unsupported_by_field.values()
        for finding
        in findings
    }


    if (
        not all_categories
        or not all_categories.issubset(
            _BUILD6R_CREATIVE_BRIEF_BEFORE_AFTER_ONLY_CATEGORIES
        )
    ):

        return creative_brief


    contaminated_fields = set(
        unsupported_by_field
    )

    updates = {}


    if (
        "design_concept"
        in contaminated_fields
    ):

        updates[
            "design_concept"
        ] = (
            _BUILD6R_NEUTRAL_DESIGN_CONCEPT
        )


    if (
        "visual_prompt"
        in contaminated_fields
    ):

        updates[
            "visual_prompt"
        ] = (
            _BUILD6R_NEUTRAL_BEFORE_AFTER_VISUAL_PROMPT
        )


    if (
        "template_suggestion"
        in contaminated_fields
    ):

        updates[
            "template_suggestion"
        ] = (
            _BUILD6R_NEUTRAL_TEMPLATE_SUGGESTION
        )


    if (
        "tone_notes"
        in contaminated_fields
    ):

        updates[
            "tone_notes"
        ] = (
            _BUILD6R_NEUTRAL_TONE_NOTES
        )


    repaired = (
        creative_brief.model_copy(
            update=updates
        )
    )


    categories_by_field = {
        field_name:
            sorted(
                {
                    str(
                        getattr(
                            finding,
                            "claim_category",
                            "",
                        )
                    )
                    for finding
                    in findings
                }
            )
        for (
            field_name,
            findings,
        )
        in unsupported_by_field.items()
    }


    _audit(
        db,
        campaign.id,
        "creative_brief_before_after_fields_locally_neutralized",
        {
            "repair":
                "creative_brief_before_after_transformation_results_only",

            "neutralized_fields":
                sorted(
                    contaminated_fields
                ),

            "claim_categories":
                sorted(
                    all_categories
                ),

            "claim_categories_by_field":
                categories_by_field,

            "replacement_mode":
                "deterministic_claim_neutral_local_fallbacks",

            "provider_calls":
                0,

            "model_calls":
                0,

            "network_calls":
                0,

            "research_calls":
                0,

            "image_calls":
                0,

            "full_grounding_gate_required_after_repair":
                True,
        },
    )


    return repaired


def _enforce_generated_claim_grounding_gate(
    db: Session,
    *,
    campaign: Campaign,
    brand: Brand,
    product,
    phase: str,
    root_name: str,
    value,
) -> list[str]:
    """Apply the existing deterministic canonical claims gate immediately.

    This deliberately performs no semantic AI extraction and creates no
    additional model/API cost.
    """

    payload = (
        value.model_dump()
        if hasattr(
            value,
            "model_dump",
        )
        else value
    )

    return _enforce_previsual_claim_grounding_gate(
        db,
        campaign=campaign,
        brand=brand,
        product=product,
        phase=phase,
        structures={
            root_name:
                payload,
        },
    )


async def _enforce_previsual_semantic_claim_grounding_gate(
    db: Session,
    *,
    campaign: Campaign,
    brand: Brand,
    product,
    phase: str,
    structures: dict,
    ai_provider,
    model: str,
    language: str,
    platform: str,
) -> list[str]:
    """Run deterministic plus semantic claim grounding before visuals.

    The existing deterministic gate remains the first zero-cost line of
    defense. For a real product campaign with an AI provider, this then
    reuses claims_audit's AI candidate extraction and its deterministic
    evidence evaluator.

    The semantic extraction is fail-closed. If the extraction itself does
    not complete, image generation must not proceed.
    """
    deterministic = _enforce_previsual_claim_grounding_gate(
        db,
        campaign=campaign,
        brand=brand,
        product=product,
        phase=phase,
        structures=structures,
    )

    if (
        product is None
        or ai_provider is None
    ):
        return deterministic

    from .claims_audit import (
        CLAIM_AUDIT_VERSION,
        audit_text_fields,
        augment_with_ai_extraction,
        format_claims_hard_fails,
    )

    fields: dict[str, str] = {}

    for root_name, value in structures.items():
        _collect_previsual_claim_text_fields(
            value,
            prefix=root_name,
            fields=fields,
        )

    if not fields:
        return deterministic

    verified = resolve_verified_product_facts(
        db,
        product,
    )

    semantic_seed = audit_text_fields(
        fields=fields,
        verified=verified,
        brand=brand,
    )

    semantic_result = await augment_with_ai_extraction(
        ai_provider,
        fields=fields,
        verified=verified,
        brand=brand,
        model=model,
        existing=semantic_seed,
    )

    record_prompt_usage(
        db,
        campaign_id=campaign.id,
        purpose="claims_audit_extraction",
        language=language,
        platform=platform,
        extra={
            "rubric_version": CLAIM_AUDIT_VERSION,
            "model_role": "creative_qa_model",
            "phase": phase,
            "previsual": True,
        },
    )

    record_stage_usage(
        db,
        campaign_id=campaign.id,
        operation="claims_audit_extraction",
        providers=[
            ai_provider
        ],
        platform=platform,
        language=language,
        content_type="",
        scope="campaign_global",
    )

    if semantic_result is semantic_seed:
        campaign.status = "FAILED"

        _audit(
            db,
            campaign.id,
            "previsual_semantic_claim_audit_unavailable",
            {
                "phase": phase,
                "field_count": len(
                    fields
                ),
            },
        )

        db.commit()

        raise PreVisualClaimGroundingError(
            "PREVISUAL_CLAIM_AUDIT_UNAVAILABLE: "
            "semantic claim extraction did not complete; "
            "visual generation is blocked."
        )

    hard_fails = list(
        dict.fromkeys(
            format_claims_hard_fails(
                semantic_result
            )
        )
    )

    if not hard_fails:
        return deterministic

    campaign.status = "FAILED"

    _audit(
        db,
        campaign.id,
        "previsual_semantic_claim_grounding_failed",
        {
            "phase": phase,
            "field_count": len(
                fields
            ),
            "hard_fail_count": len(
                hard_fails
            ),
            "hard_fails": hard_fails,
        },
    )

    db.commit()

    shown = hard_fails[:8]

    summary = " | ".join(
        shown
    )

    if len(
        hard_fails
    ) > len(
        shown
    ):
        summary += (
            " | ... and "
            + str(
                len(
                    hard_fails
                )
                - len(
                    shown
                )
            )
            + " additional unsupported claim(s)"
        )

    raise PreVisualClaimGroundingError(
        "PREVISUAL_UNSUPPORTED_CLAIM: "
        + summary
    )



async def run_strategy_stage(
    db: Session,
    *,
    campaign_id: str,
    ai_provider: AIProvider,
    research_provider: ResearchProvider,
    config: AutopilotConfig,
    progress: ProgressReporter | None = None,
) -> Campaign:
    """Advanced-mode stage 1 of 3 (brief section 18 steps 1-9): pick candidate
    photos, lock a Strategy Library type, research current trends, generate 2-3
    strategy candidates, and reject anything too similar to a past campaign in the
    same category. Ends at `BRIEF_READY` (or `FAILED`). Persists the accepted
    strategy as a `CampaignOutput(kind="strategy")` JSON so `run_copy_stage` can
    read it back later without re-deriving or re-researching anything.

    Guard: campaign must be `IDEA` or `FAILED` — same as the full pipeline, since
    re-running strategy selection on a campaign that already has copy/visuals
    committed to a different angle would leave those artifacts orphaned.
    """
    progress = progress or _NullProgress()
    campaign, brand, category, product = _load_campaign_context(db, campaign_id)
    if campaign.status not in ("IDEA", "FAILED"):
        raise ValueError(
            f"Campaign must be in IDEA or FAILED status to run the Strategy stage (currently {campaign.status})."
        )

    progress.set_progress(5, "Loading candidate photos")
    _audit(db, campaign.id, "autopilot.started", {})
    db.commit()

    candidate_assets = _select_candidate_assets(
        db, brand_id=brand.id, category_id=campaign.category_id, product_id=campaign.product_id,
        limit=max(4, config.max_slides * 2),
    )
    if not candidate_assets:
        campaign.status = "FAILED"
        db.commit()
        raise ValueError(
            "No active photos found for this category — scan your library or add photos before running Autopilot."
        )

    verified_product_facts = resolve_verified_product_facts(db, product) if product is not None else None

    strategy_type = db.get(CampaignStrategyType, campaign.strategy_type_id) if campaign.strategy_type_id else None

    preserve_preselected_strategy_angle = bool(
        strategy_type is not None
        and campaign.angle
    )

    if (
        strategy_type is not None
        and verified_product_facts is not None
    ):
        strategy_type_hard_fails = (
            _strategy_type_fact_hard_fails(
                brand=brand,
                verified=verified_product_facts,
                strategy_type=strategy_type,
            )
        )

        if strategy_type_hard_fails:
            campaign.status = "FAILED"

            _audit(
                db,
                campaign.id,
                "strategy_type_claim_grounding_failed",
                {
                    "strategy_type_id":
                        strategy_type.id,

                    "strategy_type_key":
                        getattr(
                            strategy_type,
                            "key",
                            "",
                        ),

                    "strategy_type_name":
                        strategy_type.name,

                    "hard_fail_count":
                        len(
                            strategy_type_hard_fails
                        ),

                    "hard_fails":
                        strategy_type_hard_fails,
                },
            )

            db.commit()

            raise PreVisualClaimGroundingError(
                "PREVISUAL_UNSUPPORTED_CLAIM: "
                + " | ".join(
                    strategy_type_hard_fails[
                        :8
                    ]
                )
            )


    if strategy_type is not None:

        operational_hard_fails = (
            _strategy_type_operational_hard_fails(
                brand=brand,
                strategy_type=strategy_type,
            )
        )


        if operational_hard_fails:

            campaign.status = "FAILED"

            _audit(
                db,
                campaign.id,
                "strategy_type_operational_evidence_failed",
                {
                    "strategy_type_id":
                        strategy_type.id,

                    "strategy_type_key":
                        getattr(
                            strategy_type,
                            "key",
                            "",
                        ),

                    "strategy_type_name":
                        strategy_type.name,

                    "campaign_rules_key":
                        _STRATEGY_OPERATIONAL_EVIDENCE_RULE_KEY,

                    "hard_fail_count":
                        len(
                            operational_hard_fails
                        ),

                    "hard_fails":
                        operational_hard_fails,
                },
            )

            db.commit()

            raise PreVisualClaimGroundingError(
                "PREVISUAL_UNSUPPORTED_OPERATIONAL_STRATEGY: "
                + " | ".join(
                    operational_hard_fails[:8]
                )
            )


    if strategy_type is None:
        progress.set_progress(
            10,
            "Selecting an underused campaign strategy",
        )

        strategy_type = _select_underused_strategy_type(
            db,
            brand_id=brand.id,
            category_id=campaign.category_id,
            brand=brand,
            verified_product_facts=verified_product_facts,
        )

        if strategy_type is not None:
            campaign.strategy_type_id = strategy_type.id
            db.commit()


    if strategy_type is None:

        campaign.status = "FAILED"

        _audit(
            db,
            campaign.id,
            "strategy_type_operational_evidence_missing",
            {
                "campaign_rules_key":
                    _STRATEGY_OPERATIONAL_EVIDENCE_RULE_KEY,

                "reason":
                    "no_fact_compatible_owner_verified_strategy",
            },
        )

        db.commit()

        raise PreVisualClaimGroundingError(
            "PREVISUAL_NO_VERIFIED_OPERATIONAL_STRATEGY: "
            "No fact-compatible Strategy Library type has explicit "
            "applicability approval in "
            "brand.campaign_rules."
            f"{_STRATEGY_OPERATIONAL_EVIDENCE_RULE_KEY}"
        )


    campaign.status = "RESEARCHING"
    db.commit()
    progress.set_progress(20, "Researching current trends and context")

    geography, audience = derive_geography_and_audience(
        brand_target_countries=brand.target_countries,
        brand_target_audiences=brand.target_audiences,
        category_name=category.name if category else None,
    )
    query = build_research_query(
        brand_name=brand.name,
        category_name=category.name if category else "general",
        product_name=product.name if product else None,
        geography=geography,
        audience=audience,
        objective=campaign.objective,
        language=(brand.language_rules.get("primary") if isinstance(brand.language_rules, dict) else None) or "pt-BR",
    )
    research_run, was_cached = await run_research(
        db, provider=research_provider, query=query, brand_id=brand.id, category_id=campaign.category_id,
        product_id=campaign.product_id, model=config.research_model, trend_ttl_hours=config.trend_ttl_hours,
        category_ttl_hours=config.category_ttl_hours,
    )
    campaign.research_run_id = research_run.id
    db.commit()
    _audit(db, campaign.id, "autopilot.research_ready", {"research_run_id": research_run.id, "cached": was_cached})
    db.commit()
    if not was_cached:
        # Build 6 carry-forward requirement 6 ("research cost") — never record
        # usage for a cache hit; `run_research` made no real call then, same
        # "only a real generation earns a usage row" rule scene_generation's
        # cache-miss-only recording already follows (services/orchestrator.py's
        # Build 5 repair call sites).
        record_stage_usage(
            db, campaign_id=campaign.id, operation="research", providers=[research_provider],
            scope="campaign_global",
        )

    progress.set_progress(45, "Generating strategy candidates")
    insights_text = "\n".join(
        f"- {i.statement} (confidence {i.confidence:.0%})" for i in research_run.insights
    ) or "No cited research insights were available for this scope — reason from brand rules and the stated objective only."
    strategy_type_context = (
        f"{strategy_type.name} — {strategy_type.objective}. Psychology levers: "
        f"{', '.join(strategy_type.psychology) if strategy_type.psychology else 'unspecified'}."
        if strategy_type is not None
        else campaign.angle or "unspecified — propose an angle that fits the objective."
    )
    brand_instructions_note = _brand_creative_instructions_block(brand)

    # Stage 3D repair: Strategy must operate inside the same canonical
    # product-fact boundary as downstream Copy/Creative stages.
    verified_facts_note = ""
    if verified_product_facts is not None:
        verified_facts_note = format_verified_facts_for_prompt(
            verified_product_facts
        )

    strategy_result: CampaignStrategyCandidates = await ai_provider.generate_structured(
        system=(
            ("You are a senior direct-response marketing strategist. Research may inform audience "
            "tension, cultural context, timing, and creative direction, but it is NEVER factual "
            "evidence about this specific product. Product-specific claims must remain inside "
            "VERIFIED PRODUCT FACTS. This applies to every candidate field, including objective, "
            "audience, funnel_stage, insight, angle, key_message, reason_this_should_work, and "
            "research_basis. If research contains an ingredient, benefit, result, popularity, "
            "scarcity, availability, efficacy, ranking, or other product claim that is not also "
            "present in VERIFIED PRODUCT FACTS, do not repeat or imply it as true about the product. "
            "Use such research only as internal creative context or omit it. "
            + _claims_boundary_instruction()
            + _sparse_fact_grounding_instruction()) + _build6r_v36_strategy_generation_grounding_instruction()
            + _build6r_v39_field_specific_strategy_generation_contract()
        ),
        user=(
            f"Brand: {brand.name}. Voice: {brand.voice or 'not specified'}.\n"
            f"{brand_instructions_note + chr(10) if brand_instructions_note else ''}"
            f"Category: {category.name if category else 'general'}."
            f"{f' Product: {product.name}.' if product else ''}\n"
            f"Chosen campaign strategy: {strategy_type_context}\n"
            f"Objective: {campaign.objective}. Audience: {audience}. Geography: {geography}.\n"
            f"{verified_facts_note + chr(10) if verified_facts_note else ''}"
            f"Research insights ? CREATIVE CONTEXT ONLY, never product-fact evidence:\n"
            f"{insights_text}\n\n"
            "Propose 2-3 genuinely different strategy candidates (a distinct angle/hook direction "
            "each). Use research only to choose creative direction; it is not factual evidence. "
            "RESEARCH-TO-FACT HARD STOP: do not turn research into claims about cultural norms, common "
            "consumer behavior or prevalence, pharmacy presence, shelf prevalence, product availability, "
            "national usage habits, or Hanna Japan brand-role claims. Any such factual statement must be "
            "present in verified product facts or explicit owner-confirmed brand facts above."
            ' V3.6 FINAL STRATEGY INSTRUCTION: Research may shape creative direction only, never factual grounding. Every factual clause must be supported by VERIFIED PRODUCT FACTS or explicit owner-confirmed brand facts. Do not infer cultural, origin, retail, market, consumer-behavior, popularity, or brand-role claims from research, geography, category, retailer/store identity, or strategy metadata. If an angle would require such an unsupported premise, rewrite it using verified product atoms plus non-factual creative framing.'
        ),
        schema=CampaignStrategyCandidates,
        model=config.strategy_model,
    )
    record_stage_usage(
        db, campaign_id=campaign.id, operation="strategy", providers=[ai_provider], scope="campaign_global",
    )
    if not strategy_result.candidates:
        campaign.status = "FAILED"
        db.commit()
        raise ValueError("The model did not return any strategy candidates.")

    progress.set_progress(80, "Checking candidates against campaign history")
    prior_fingerprints = _recent_fingerprints(
        db, brand_id=brand.id, category_id=campaign.category_id, exclude_campaign_id=campaign.id
    )
    (
        grounded_strategy_candidates,
        grounding_rejections,
    ) = _build6r_v38_filter_grounded_strategy_candidates(
        strategy_result.candidates,
        verified_product_facts,
    )

    if grounding_rejections:
        grounding_hard_fails = [
            failure
            for _index, failures in grounding_rejections
            for failure in failures
        ]
        _audit(
            db,
            campaign.id,
            "autopilot.strategy_candidates_grounding_filtered",
            {
                "candidate_count": len(strategy_result.candidates),
                "grounding_rejected_candidate_count": len(
                    grounding_rejections
                ),
                "grounded_candidate_count": len(
                    grounded_strategy_candidates
                ),
                "hard_fail_count": len(grounding_hard_fails),
                "hard_fails": grounding_hard_fails[:8],
                "zero_cost_candidate_filter": True,
            },
        )
        db.commit()

    if not grounded_strategy_candidates:
        deterministic_fallback = (
            _build6r_v310_deterministic_canonical_strategy_fallback(
                strategy_result.candidates,
                verified_product_facts,
            )
        )
        (
            fallback_grounded_candidates,
            fallback_rejections,
        ) = _build6r_v38_filter_grounded_strategy_candidates(
            [deterministic_fallback],
            verified_product_facts,
        )
        fallback_hard_fails = [
            failure
            for _index, failures in fallback_rejections
            for failure in failures
        ]

        _audit(
            db,
            campaign.id,
            "autopilot.strategy_deterministic_fallback",
            {
                "trigger": "all_model_candidates_unsupported",
                "candidate_count": 1,
                "grounded_candidate_count": len(
                    fallback_grounded_candidates
                ),
                "hard_fail_count": len(fallback_hard_fails),
                "hard_fails": fallback_hard_fails[:8],
                "zero_cost_fallback": True,
                "extra_model_calls": 0,
            },
        )
        db.commit()

        if fallback_grounded_candidates:
            grounded_strategy_candidates = fallback_grounded_candidates
        else:
            campaign.status = "FAILED"
            db.commit()

            raise PreVisualClaimGroundingError(
                "PREVISUAL_ALL_STRATEGY_CANDIDATES_UNSUPPORTED: "
                + " | ".join(
                    (grounding_hard_fails + fallback_hard_fails)[:8]
                )
            )

    accepted = None
    accepted_novelty = None
    for candidate in grounded_strategy_candidates:
        summary = f"{candidate.angle} {candidate.key_message} {candidate.insight}"
        candidate_hash = text_hash(candidate.angle, candidate.key_message, candidate.insight)
        novelty = classify_novelty(
            candidate_text_hash=candidate_hash,
            candidate_summary=summary,
            prior_fingerprints=prior_fingerprints,
            too_similar_threshold=config.too_similar_threshold,
            acceptable_threshold=config.acceptable_threshold,
        )
        is_acceptable = novelty.classification in (NOVELTY_FRESH, NOVELTY_SIMILAR_BUT_ACCEPTABLE)
        is_better = accepted is None or (
            novelty.classification == NOVELTY_FRESH and accepted_novelty.classification != NOVELTY_FRESH
        )
        if is_acceptable and is_better:
            accepted, accepted_novelty = candidate, novelty

    if accepted is None:
        campaign.status = "FAILED"
        db.commit()
        _audit(db, campaign.id, "autopilot.all_candidates_rejected", {"candidate_count": len(strategy_result.candidates)})
        db.commit()
        raise ValueError(
            f"All {len(strategy_result.candidates)} strategy candidates were too similar to prior "
            "campaigns in this category. Try a different strategy type from the Strategy Library, or "
            "wait until more campaign history exists to compare against."
        )

    if verified_product_facts is not None:
        _build6r_v35_enforce_strategy_containment(
            db,
            campaign=campaign,
            accepted=accepted,
            verified=verified_product_facts,
        )

    _enforce_generated_claim_grounding_gate(
        db,
        campaign=campaign,
        brand=brand,
        product=product,
        phase="strategy_candidate",
        root_name="strategy",
        value=accepted,
    )

    campaign.audience = accepted.audience
    campaign.funnel_stage = accepted.funnel_stage

    if not preserve_preselected_strategy_angle:
        campaign.angle = accepted.angle

    campaign.main_promise = accepted.key_message
    campaign.status = "BRIEF_READY"
    db.commit()

    category_slug = category.slug if category else "general"
    _save_stage_json(
        db, campaign=campaign, brand_slug=brand.slug, category_slug=category_slug, config=config,
        kind="strategy", data={"strategy": accepted.model_dump(), "novelty": accepted_novelty.classification},
    )
    db.commit()
    _audit(db, campaign.id, "autopilot.strategy_selected", {"angle": accepted.angle, "novelty": accepted_novelty.classification})
    db.commit()
    db.refresh(campaign)
    progress.set_progress(100, "Strategy ready")
    return campaign


async def run_copy_stage(
    db: Session,
    *,
    campaign_id: str,
    ai_provider: AIProvider,
    config: AutopilotConfig,
    progress: ProgressReporter | None = None,
) -> Campaign:
    """Advanced-mode stage 2 of 3 (brief section 18 steps 10-12): creative brief →
    campaign copy → carousel plan, grounded in the strategy `run_strategy_stage`
    already accepted (read back from its persisted `CampaignOutput(kind=
    "strategy")` JSON — this stage never re-derives or re-researches anything, so
    it can run standalone, in a later request, from whichever process ran Strategy).
    Ends at `COPY_READY`. Writes `campaign.hook`/`cta` (from the primary language's
    variant) and persists `copy`/`creative` JSON for `run_visuals_stage` to
    consume — touches no photos and renders nothing.

    Guard: requires a persisted strategy output to exist — not a specific campaign
    status — so Copy can be re-run later (e.g. to try different copy) even after
    Visuals has already run, without needing to reset the whole campaign.

    Slide count: when `campaign.target_slide_count` is set, the carousel planner is
    told to plan *exactly* that many slides instead of "up to" `config.max_slides`
    on its own judgment — see the field's docstring on `Campaign` for why the
    default (unset) behavior stays as-is. This is a strong instruction to the model
    via the same structured-output call as everything else in this pipeline, not a
    hard guarantee — like every other AI-authored count in this app, a genuinely
    unusual request can still come back short.

    Build 1 (Parts B/C/E/F/I) rewrite — what changed and why:

    - **Languages** (Part B/F): `campaign.languages` (falling back to the legacy
      `campaign.language` for a pre-Build-1 campaign) drives a real loop — every
      language gets its own independent `CampaignCopy` + `CarouselPlan` call, each
      with that language's own native-writing rules (`_language_style_rules`),
      never one generated then translated into the other. The **creative brief**
      stays a single call per campaign — it's the "master campaign concept"
      (visual/design direction), not per-language text, matching the "one
      campaign idea, multiple executions" architecture.
    - **Platforms** (Part C): `campaign.target_platforms` (falling back to
      `["instagram"]`) is turned into real copywriting guidance
      (`_platform_requirements_note`, sourced from `data/platform_capabilities.py`)
      folded into every copy/carousel-plan call — Instagram is no longer assumed.
    - **Product facts** (Part A/E): a single-product ("deep-dive") campaign's
      `VerifiedProductFacts` (never invented — see `services/product_facts.py`)
      now reach this prompt; a discovery campaign's facts stay per-product,
      grounded per-slide the same way they always were (that carousel's own
      product-info lines below).
    - **Research** (Part E): this campaign's own persisted `ResearchInsight` rows
      (via `campaign.research_run_id`) now reach this prompt — previously
      generated back in the Strategy stage and never read again after that.
    - **Strategy** (Part E): `funnel_stage`/`insight`/`reason_this_should_work`
      now reach this prompt, not just `angle`/`key_message`/`audience`/
      `objective`.
    - **Brand** (Part E): `disclaimers`/`target_audiences`/`target_countries` now
      reach this prompt, alongside the existing `voice`/`preferred_ctas`/
      `disallowed_terms`/`creative_instructions`. `campaign_rules` (the round-1
      JSON field Part E's prose also names) is deliberately NOT resurrected —
      `creative_instructions` is its round-20 replacement and is already wired
      in; see docs/campaign-pipeline.md's Build 1 section.
    - **Prompt versioning** (Part I): every `campaign_copy`/`carousel_plan` call
      is now logged via `record_prompt_usage` (see `services/prompt_registry.py`)
      with its purpose, version, language, and platform.

    Persistence shape changed accordingly: both `copy` and `creative` stage JSON
    are now `{"primary_language": ..., "languages": {"<lang>": {...}, ...}}`
    (plus a top-level `creative_brief` on `creative`, shared across languages) —
    see `_stage_language_variant`. `get_campaign_copy` and `run_visuals_stage`
    both read this back via that same helper, which also transparently handles
    the old flat shape from a campaign generated before Build 1.

    Scoping note (documented, not an oversight): only the **primary** language
    (`languages[0]`) is rendered into actual slide images by `run_visuals_stage`
    in Build 1 — every other selected language's copy/carousel-plan is generated
    and persisted in full, but full multi-language *visual* rendering (baking
    each language's own text into its own set of slide images) is out of scope
    for this build. See the Build 1 completion packet's REMAINING_BLOCKERS.
    """
    progress = progress or _NullProgress()
    campaign, brand, category, product = _load_campaign_context(db, campaign_id)

    check_copy_stage_prerequisite(db, campaign.id)
    strategy_data = _load_stage_json(db, campaign.id, "strategy")
    accepted = CampaignStrategy(**strategy_data["strategy"])
    brand_instructions_note = _brand_creative_instructions_block(brand)

    languages = list(campaign.languages) if campaign.languages else [campaign.language or "pt-BR"]
    primary_language = languages[0]
    target_platforms = list(campaign.target_platforms) if campaign.target_platforms else ["instagram"]
    primary_platform = target_platforms[0] if target_platforms else None
    platform_note = _platform_requirements_note(target_platforms)

    verified_facts_note = ""
    if product is not None:
        verified_facts_note = format_verified_facts_for_prompt(resolve_verified_product_facts(db, product))

    # Build 6R: category is context for creative reasoning, never
    # permission to manufacture category-typical claims.
    category_context_note = (
        f"PRODUCT/CATEGORY CONTEXT: "
        f"category={category.name if category else 'general'}; "
        f"product={product.name if product else 'category/discovery campaign'}. "
        "Use category only to choose communication structure, "
        "demonstration style, visual environment, information hierarchy "
        "and buying-decision story. Never infer unsupported facts from it."
    )

    from ..data.campaign_archetypes import (
        format_campaign_archetypes_for_prompt,
    )

    campaign_archetypes_note = (
        format_campaign_archetypes_for_prompt()
    )

    research_note = _format_research_insights_for_prompt(db, campaign.research_run_id)

    strategy_note = (
        f"Funnel stage: {accepted.funnel_stage}. Core insight this campaign is built on: "
        f"{accepted.insight!r}. Why this should work: {accepted.reason_this_should_work!r}."
    )

    brand_note_parts = [f"Brand: {brand.name}."]
    if brand.target_audiences:
        brand_note_parts.append(f"Brand's usual target audiences: {', '.join(brand.target_audiences)}.")
    if brand.target_countries:
        brand_note_parts.append(f"Brand's target countries: {', '.join(brand.target_countries)}.")
    if brand.disclaimers:
        brand_note_parts.append(
            "Brand disclaimers that must be honored (do not contradict them; they render separately on "
            f"the creative, do not repeat them verbatim in the caption unless natural to do so): "
            f"{'; '.join(brand.disclaimers)}."
        )
    brand_note = " ".join(brand_note_parts)

    progress.set_progress(10, "Writing the creative brief")
    creative_brief: CreativeBrief = await ai_provider.generate_structured(
        system=(
            ("You are a creative director translating a marketing strategy into a concrete creative brief. "
            f"{_claims_boundary_instruction()}") + _sparse_fact_grounding_instruction()
        ),
        user=(
            f"Strategy angle: {accepted.angle!r}. Key message: {accepted.key_message!r}. "
            f"Reasoning: {accepted.reason_this_should_work!r}. Brand visual style: "
            f"{brand.visual_style or 'not specified'}."
            f"{chr(10) + category_context_note}"
            f"{chr(10) + verified_facts_note if verified_facts_note else ''}"
            f"{chr(10) + brand_instructions_note if brand_instructions_note else ''}"
        ),
        schema=CreativeBrief,
        model=config.creative_director_model,
    )
    record_stage_usage(
        db, campaign_id=campaign.id, operation="creative_brief", providers=[ai_provider], scope="campaign_global",
    )

    # Build 6R narrow recovery. Only ranking/bestseller drift
    # confined to visual_prompt can be neutralized locally.
    creative_brief = (
        _neutralize_creative_brief_ranking_only(
            db,
            campaign=campaign,
            brand=brand,
            product=product,
            creative_brief=creative_brief,
        )
    )

    # Existing canonical gate remains the final authority.
    # Build 6R bounded recovery for transformation-results-only
    # CreativeBrief drift. Mixed categories remain fail-closed.
    creative_brief = (
        _neutralize_creative_brief_before_after_only(
            db,
            campaign=campaign,
            brand=brand,
            product=product,
            creative_brief=creative_brief,
        )
    )

    # The existing complete canonical grounding gate remains final.
    _enforce_generated_claim_grounding_gate(
        db,
        campaign=campaign,
        brand=brand,
        product=product,
        phase="creative_brief",
        root_name="creative_brief",
        value=creative_brief,
    )

    # Build 2, Part E: the ONE master campaign concept, generated once and held
    # constant across every platform/language adaptation `_render_additional_
    # platform_variants` (run_visuals_stage) produces later — never
    # regenerated per platform or per language, per Part E's own requirement
    # ("This should remain consistent across selected platforms"). Persisted
    # alongside copy/creative below so a later, standalone Visuals-only run
    # (a different request, possibly a different day) can read it back.
    progress.set_progress(15, "Defining the master campaign concept")
    master_concept: MasterCampaignConcept = await ai_provider.generate_structured(
        system=(
            ("You are a senior creative director defining the ONE consistent campaign concept that will "
                "later be adapted for several different social platforms and, separately, translated into "
                "one or more languages ? the concept itself remains platform- and language-agnostic. "
                "Before defining its visual world, choose exactly ONE primary campaign_archetype from the "
                "UNIVERSAL catalog below. An archetype is a COMMUNICATION STRUCTURE, not a product category. "
                "This system must work equally for cosmetics, umbrellas, electronics, wellness devices, "
                "household goods, automotive items, kitchen products, food, fashion, collectibles and future "
                "categories. Never default every product to the same luxury studio, pedestal, neon, black-gold "
                "or generic social-ad aesthetic. The PRODUCT and its VERIFIED buying decision must determine "
                "the creative direction. Populate product_category_context, campaign_archetype, "
                "archetype_reasoning, visual_story_system, hero_treatment, proof_or_demo_strategy and "
                "story_beats. "
                f"{campaign_archetypes_note} "
                "Describe the master campaign idea rather than platform-specific execution or wording. "
                f"{_claims_boundary_instruction()}") + _sparse_fact_grounding_instruction()
        ),
        user=(
            f"Strategy angle: {accepted.angle!r}. Key message: {accepted.key_message!r}. Audience: "
            f"{accepted.audience!r}. Objective: {accepted.objective!r}. Reasoning: "
            f"{accepted.reason_this_should_work!r}. Creative brief design concept: "
            f"{creative_brief.design_concept!r}. Brand visual style: {brand.visual_style or 'not specified'}."
            f"{chr(10) + category_context_note}"
            f"{chr(10) + brand_instructions_note if brand_instructions_note else ''}"
            # Build 6 repair (Critical Defect 2/4): the master concept is where a
            # campaign's core promise gets set — it must see the same verified-
            # facts/research grounding campaign_copy gets, not just the strategy
            # angle, or it can set a promise the copy stage then has no verified
            # basis to honor.
            f"{chr(10) + verified_facts_note if verified_facts_note else ''}"
            f"{chr(10) + research_note if research_note else ''}"
        ),
        schema=MasterCampaignConcept,
        model=config.creative_director_model,
    )
    record_prompt_usage(
        db, campaign_id=campaign.id, purpose="master_campaign_concept", language=primary_language,
        platform=primary_platform,
    )
    record_stage_usage(
        db, campaign_id=campaign.id, operation="master_campaign_concept", providers=[ai_provider],
        platform=primary_platform, language=primary_language, scope="campaign_global",
    )

    # Round 19: which of the two carousel structures this campaign uses follows
    # what's already picked on the campaign — see get_campaign's structure_mode
    # (api/campaigns.py) for the identical rule applied to the read side. A
    # category-only campaign with no discovery products picked yet keeps the
    # original single-concept planning below untouched. Resolved once, outside
    # the per-language loop, since it depends only on the campaign's own setup.
    discovery_products = list(campaign.discovery_products)
    is_discovery = campaign.product_id is None and len(discovery_products) > 0
    target_slide_count = campaign.target_slide_count

    campaign_copy_by_language: dict[str, CampaignCopy] = {}
    carousel_plan_by_language: dict[str, CarouselPlan] = {}
    planned_slides_by_language: dict[str, list] = {}

    for idx, language in enumerate(languages):
        language_note = _language_style_rules(language)
        step = 20 + round(50 * idx / len(languages))

        # Build 4: selective, bounded feedback grounding (carry-forward
        # requirement 5) — "" for a brand with no `review_feedback` history
        # yet, so this is byte-for-byte a no-op until real feedback exists.
        feedback_note = format_feedback_for_prompt(select_feedback_examples(
            db, brand_id=brand.id, platform=primary_platform or "", language=language,
            category_id=campaign.category_id, product_id=campaign.product_id, objective=campaign.objective,
            content_type=campaign.content_type, limit=config.feedback_examples_limit,
        ))

        progress.set_progress(step, f"Writing campaign copy ({language})")
        campaign_copy: CampaignCopy = await ai_provider.generate_structured(
            system=(
                ("You are a native-level direct-response copywriter. Write this response ENTIRELY and "
                "naturally in the language specified below — this is one of possibly several independent "
                "language versions of the same campaign idea, and each must read as if it were written by "
                "a native speaker from scratch, never as a translation of another language's copy. "
                f"{language_note} {_claims_boundary_instruction()}") + _sparse_fact_grounding_instruction()
            ),
            user=(
                f"Language: {language}. Angle: {accepted.angle}. Key message: {accepted.key_message}. "
                f"Audience: {accepted.audience}. Objective: {accepted.objective}. {strategy_note} "
                f"{brand_note} Brand voice: {brand.voice or 'not specified'}. Brand preferred CTAs: "
                f"{brand.preferred_ctas or 'none specified'}. Brand disallowed terms: "
                f"{brand.disallowed_terms or 'none'}."
                f"{chr(10) + verified_facts_note if verified_facts_note else ''}"
                f"{chr(10) + research_note if research_note else ''}"
                f"{chr(10) + platform_note if platform_note else ''}"
                f"{chr(10) + brand_instructions_note if brand_instructions_note else ''}"
                f"{chr(10) + feedback_note if feedback_note else ''}"
            ),
            schema=CampaignCopy,
            model=config.copy_model,
        )
        campaign_copy_by_language[language] = campaign_copy
        record_prompt_usage(
            db, campaign_id=campaign.id, purpose="campaign_copy", language=language, platform=primary_platform,
        )
        record_stage_usage(
            db, campaign_id=campaign.id, operation="campaign_copy", providers=[ai_provider],
            platform=primary_platform, language=language, scope="campaign_global",
        )

        # BUILD6R_PREMIUM_HERO_TRUE_SCOPE_V1
        # A premium-hero acceptance run is one hero, not a carousel.
        # Reuse the already-generated campaign copy as one deterministic
        # fallback slide and bypass CarouselPlan AI generation entirely.
        #
        # This branch intentionally performs NO carousel_plan prompt call,
        # NO carousel_plan stage accounting, and NO second planning model
        # request. The normal carousel path immediately below is untouched.
        if config.skip_carousel_plan:
            progress.set_progress(
                step + 10,
                f"Using deterministic hero plan ({language})",
            )

            planned_slides_by_language[language] = [
                SlidePlanFallback(
                    headline=campaign_copy.headline,
                    body=campaign_copy.supporting_copy,
                    cta=campaign_copy.cta,
                )
            ]

            continue

        # BUILD6R_PREMIUM_HERO_NO_CAROUSEL_CALL_V2
        # Premium hero mode creates the ONE downstream slide deterministically
        # from the already-grounded CampaignCopy. No carousel-planning model
        # request is made in this branch.
        if config.hero_only:
            progress.set_progress(
                step + 10,
                f"Preparing the premium hero ({language})",
            )

            carousel_plan = CarouselPlan(
                slides=[
                    SlidePlan(
                        slide_number=1,
                        purpose="hero",
                        headline=campaign_copy.headline,
                        body=campaign_copy.supporting_copy,
                        cta=campaign_copy.cta,
                        visual_brief=(
                            creative_brief.design_concept
                            or campaign_copy.alt_text
                            or "Product hero"
                        ),
                    )
                ],
                narrative_summary=(
                    "Premium hero-only deterministic single-slide plan."
                ),
            )

            effective_max_slides = 1

        else:
            progress.set_progress(step + 10, f"Planning the carousel ({language})")
            if is_discovery:
                # Build 6 repair (Critical Defect 2/6): a discovery slide previously
                # had ZERO verified-facts grounding of its own (only the product's
                # free-text `notes`), so a sparse/unverified product had nothing to
                # anchor the model except its own name — the exact "solve sparse
                # facts by inventing benefits" failure mode this repair fixes.
                # Each product line now carries its OWN missing_information note,
                # so the model is told, per product, what it does NOT yet know.
                product_lines = "\n\n".join(
                    (
                        f"{i + 1}. PRODUCT IDENTITY (identity only, not factual evidence): {dp.product.name}\n"
                        + format_verified_facts_for_prompt(
                            resolve_verified_product_facts(
                                db,
                                dp.product,
                            )
                        )
                        + (
                            "\nUNVERIFIED PRODUCT NOTES "
                            "(context only; never factual evidence): "
                            + dp.product.notes
                            if dp.product.notes
                            else ""
                        )
                    )
                    for i, dp in enumerate(
                        discovery_products
                    )
                )
                carousel_plan: CarouselPlan = await ai_provider.generate_structured(
                    system=(
                        (
                        "You are a social media content planner and direct-response copywriter planning a "
                        "MULTI-PRODUCT DISCOVERY carousel. A fixed ordered list of products is given below. "
                        "Plan EXACTLY one slide per product in the SAME order. Never combine products, skip a "
                        "product, or invent an extra product. Each slide must remain inside THAT product's own "
                        "VERIFIED PRODUCT FACTS boundary. Product identity, category, free-text notes, research, "
                        "strategy, and earlier AI output are not substitutes for verified facts. "
                        "Optional sections such as badge_text, intro, features, callouts, bottom_features, and "
                        "trust_badges must be blank whenever their factual basis is not explicitly verified. "
                        "A badge, ingredient, result, statistic, logistics statement, authenticity statement, "
                        "ranking, review claim, scarcity claim, comparison, or outcome may appear only when its "
                        "specific factual basis is present in that product's VERIFIED PRODUCT FACTS or, for "
                        "brand/logistics policy only, explicit owner-confirmed brand facts. "
                        "Each visual_brief describes composition and subject only; it must not depict or imply an "
                        "unsupported benefit, ingredient, transformation, before/after result, clinical proof, or "
                        "performance outcome. "
                        f"{language_note} {_claims_boundary_instruction()}"
                    ) + _sparse_fact_grounding_instruction()
                    ),
                    user=(
                        f"Language: {language}. Overall campaign hook: {campaign_copy.hook}. Overall theme/"
                        f"headline: {campaign_copy.headline}. CTA: {campaign_copy.cta}. Design concept: "
                        f"{creative_brief.design_concept}.\n\nProducts to feature, in this exact order (plan "
                        f"exactly {len(discovery_products)} slide(s), one per product, same order):\n"
                        f"{product_lines}\n\nEach slide needs a visual_brief describing what photo/subject that "
                        "slide needs."
                        f"{chr(10) + platform_note if platform_note else ''}"
                        f"{chr(10) + brand_instructions_note if brand_instructions_note else ''}"
                        f"{chr(10) + feedback_note if feedback_note else ''}"
                    ),
                    schema=CarouselPlan,
                    model=config.copy_model,
                )
                effective_max_slides = len(discovery_products)
            else:
                slide_count_instruction = (
                    f"Plan exactly {target_slide_count} slide(s), no more and no fewer — this carousel length "
                    "was chosen deliberately."
                    if target_slide_count
                    else f"Plan up to {config.max_slides} slide(s), using your judgment for how many the "
                    "concept actually needs — a strong single hero image is fine if the concept doesn't need a "
                    "full carousel."
                )
                carousel_plan = await ai_provider.generate_structured(
                    system=(
                        (
                        "You are a social media content planner and direct-response copywriter. Plan a short "
                        "carousel that delivers the campaign across slides. All optional factual sections must "
                        "remain inside VERIFIED PRODUCT FACTS. Product identity, category, free-text product notes, "
                        "research, strategy, creative briefs, and earlier AI-generated copy are creative context "
                        "only and are never product-fact evidence. "
                        "Use badge_text, intro, features, callouts, bottom_features, or trust_badges only when the "
                        "specific factual basis is explicitly verified. Otherwise leave the field blank. "
                        "Never invent or infer ingredients, percentages, benefits, effects, results, rankings, "
                        "reviews, customer counts, scarcity, price, availability, certification, logistics, "
                        "authenticity, comparisons, or transformations. "
                        "Each visual_brief describes composition and subject only; it must not depict or imply "
                        "before/after, transformation, ingredient action, clinical proof, result comparison, or "
                        "any other unsupported outcome. "
                        f"{language_note} {_claims_boundary_instruction()}"
                    ) + _sparse_fact_grounding_instruction()
                    ),
                    user=(
                        f"Language: {language}. Hook: {campaign_copy.hook}. Headline: {campaign_copy.headline}. "
                        f"Supporting copy: {campaign_copy.supporting_copy}. CTA: {campaign_copy.cta}. Design "
                        f"concept: {creative_brief.design_concept}. Product: "
                        f"{product.name if product else 'not specified'}. Product notes: "
                        f"{(product.notes if product and product.notes else 'not specified')}. "
                        f"{slide_count_instruction} Each slide needs a visual_brief describing what photo/subject "
                        "that slide needs."
                        f"{chr(10) + verified_facts_note if verified_facts_note else ''}"
                        f"{chr(10) + platform_note if platform_note else ''}"
                        f"{chr(10) + brand_instructions_note if brand_instructions_note else ''}"
                        f"{chr(10) + feedback_note if feedback_note else ''}"
                    ),
                    schema=CarouselPlan,
                    model=config.copy_model,
                )
                effective_max_slides = target_slide_count or config.max_slides

        planned_slides = carousel_plan.slides[:effective_max_slides] or [
            SlidePlanFallback(
                headline=campaign_copy.headline, body=campaign_copy.supporting_copy, cta=campaign_copy.cta
            )
        ]
        carousel_plan_by_language[language] = carousel_plan
        planned_slides_by_language[language] = planned_slides
        if not config.hero_only:
            record_prompt_usage(
                db, campaign_id=campaign.id, purpose="carousel_plan", language=language, platform=primary_platform,
            )
            record_stage_usage(
                db, campaign_id=campaign.id, operation="carousel_plan", providers=[ai_provider],
                platform=primary_platform, language=language, scope="campaign_global",
            )

    # Build 6R pre-visual grounding gate:
    # all text-model work for this stage is complete, but no unsupported
    # generated material may be persisted as COPY_READY or proceed toward
    # any billed vision/image generation.
    await _enforce_previsual_semantic_claim_grounding_gate(
        db,
        campaign=campaign,
        brand=brand,
        product=product,
        phase="copy_stage",
        structures={
            "campaign": {
                "angle": campaign.angle or "",
                "main_promise": campaign.main_promise or "",
            },
            "strategy": accepted.model_dump(),
            "master_concept": master_concept.model_dump(),
            "copy": {
                language: campaign_copy.model_dump()
                for language, campaign_copy
                in campaign_copy_by_language.items()
            },
            "creative": {
                "creative_brief": creative_brief.model_dump(),
                "languages": {
                    language: {
                        "carousel_plan": {
                            "slides": [
                                _slide_plan_to_dict(slide)
                                for slide in planned_slides_by_language[
                                    language
                                ]
                            ],
                            "narrative_summary": (
                                carousel_plan_by_language[
                                    language
                                ].narrative_summary
                            ),
                        }
                    }
                    for language in languages
                },
            },
        },
        platform=primary_platform or "",
        language=primary_language,
        model=config.creative_qa_model,
        ai_provider=ai_provider,
    )

    primary_copy = campaign_copy_by_language[primary_language]
    campaign.hook = primary_copy.hook
    campaign.cta = primary_copy.cta
    db.commit()

    category_slug = category.slug if category else "general"
    # Build 2, Part E: persisted once per campaign, read back by
    # `_render_additional_platform_variants` (run_visuals_stage) so every
    # platform adaptation and creative direction it generates stays grounded
    # in this SAME concept rather than re-deriving (and potentially drifting
    # from) a new one per variant.
    _save_stage_json(
        db, campaign=campaign, brand_slug=brand.slug, category_slug=category_slug, config=config,
        kind="master_concept", data=master_concept.model_dump(),
    )
    _save_stage_json(
        db, campaign=campaign, brand_slug=brand.slug, category_slug=category_slug, config=config,
        kind="copy",
        data={
            "primary_language": primary_language,
            "languages": {lang: cc.model_dump() for lang, cc in campaign_copy_by_language.items()},
        },
    )
    _save_stage_json(
        db, campaign=campaign, brand_slug=brand.slug, category_slug=category_slug, config=config,
        kind="creative",
        data={
            "primary_language": primary_language,
            # Shared across every language — the design/visual direction is ONE
            # campaign idea, not per-language text. See this function's docstring.
            "creative_brief": creative_brief.model_dump(),
            "languages": {
                lang: {
                    "carousel_plan": {
                        "slides": [_slide_plan_to_dict(s) for s in planned_slides_by_language[lang]],
                        "narrative_summary": carousel_plan_by_language[lang].narrative_summary,
                    }
                }
                for lang in languages
            },
        },
    )
    if campaign.status in ("BRIEF_READY", "FAILED"):
        campaign.status = "COPY_READY"
    db.commit()
    _audit(db, campaign.id, "autopilot.copy_ready", {
        "slide_count_planned": len(planned_slides_by_language[primary_language]),
        "languages": languages,
        "target_platforms": target_platforms,
    })
    db.commit()
    db.refresh(campaign)
    progress.set_progress(100, "Copy ready")
    return campaign



async def run_visuals_stage(
    db: Session,
    *,
    campaign_id: str,
    renderer: PlaywrightRenderer,
    config: AutopilotConfig,
    progress: ProgressReporter | None = None,
    image_provider: ImageProvider | None = None,
    ai_provider: AIProvider | None = None,
) -> Campaign:
    """Advanced-mode stage 3 of 3 (brief section 18 steps 13-15): render every
    planned slide from the Copy stage's persisted carousel plan through the
    existing creative pipeline, then persist a `CampaignFingerprint` for future
    novelty checks. Ends at `REVIEW`. Needs **no** OpenAI key by default — it only
    reads back already-generated copy/carousel JSON and composites your real
    photos, same as the manual per-slide `/slides/render` endpoint.

    Pass `image_provider` (and, to actually verify the result, `ai_provider` too)
    + set `config.recreate_with_ai=True` to have each slide's entire image —
    product included, not just the backdrop — come from
    `recreate_creative_image_with_fidelity_gate(...)` (round 18): a full AI
    recreation, style-guided by the brand's own uploaded inspiration examples and,
    from the second slide on, by the campaign's own already-verified "visual
    master" slide, then checked against the real source photo via `AIProvider.
    check_product_fidelity` before it's trusted — a `FAIL` (or an unverifiable
    check) triggers one corrective retry, and if that still isn't a verified
    `PASS` this falls back exactly as if recreation were off for that slide. When
    `ai_provider` is `None`, recreation is skipped entirely rather than risk
    shipping an unverified image (fail-closed) — pass both providers together to
    actually use this path. When a verified recreation succeeds it takes priority
    over `use_ai_background`/`detect_product_zone` below for that slide (there's
    no background or product-zone left to compute once the whole image is
    recreated).

    Pass `image_provider` + set `config.use_ai_background=True` to have each
    slide's background come from `generate_ai_background(...)` (an AI-generated
    scene, style-guided by the brand's uploaded visual-reference photos) instead of
    the deterministic gradient — this is one thing that makes Visuals need an
    OpenAI key; the no-key path is unchanged when this stays off (the default).

    Pass `ai_provider` + set `config.detect_product_zone=True` to have each slide's
    product placement come from `detect_product_zone(...)` (a vision-model call per
    photo, see that function's docstring) instead of the template's one fixed
    layout — the other thing that makes Visuals need an OpenAI key when opted into
    standalone.

    Guard: requires persisted `copy` and `creative` outputs to exist (i.e.
    `run_copy_stage` has run) — not a specific campaign status, so Visuals can be
    re-run later (e.g. to re-render after adding new photos) without resetting
    anything else.
    """
    # BUILD6R_IMMUTABLE_PRODUCT_LAYER_RUN_VISUALS_GUARD
    # Full AI recreation changes product/package pixels.
    # Product campaigns must generate only the scene/background
    # and composite the authentic source product afterward.
    if config.recreate_with_ai:
        raise RuntimeError(
            "Full AI product recreation is prohibited by the "
            "immutable-product-layer contract. Use "
            "use_ai_background=True and recreate_with_ai=False so "
            "the authentic source product is composited after scene generation."
        )

    progress = progress or _NullProgress()
    campaign, brand, category, product = _load_campaign_context(db, campaign_id)

    # Round 20: a campaign can pick its own platform/format (see `Campaign.
    # platform_key`'s docstring) — that always wins when set. NULL (every
    # campaign before this field existed, and any new one that hasn't picked one)
    # falls back to `config.platform_key`'s own default, exactly as before this
    # existed. Every former `config.platform_key` reference below now reads this
    # local instead, so the whole render (output path, AI recreation/background
    # canvas size, the deterministic template render, and the persisted QA/output
    # records) agrees on one platform for the whole run.
    effective_platform_key = campaign.platform_key or config.platform_key

    check_visuals_stage_prerequisite(db, campaign.id)
    copy_data_raw = _load_stage_json(db, campaign.id, "copy")
    creative_data_raw = _load_stage_json(db, campaign.id, "creative")
    strategy_data = _load_stage_json(db, campaign.id, "strategy")
    insight = (strategy_data or {}).get("strategy", {}).get("insight", "")
    # Build 1: only the primary language actually renders slide images in this
    # build (see run_copy_stage's docstring "Scoping note") — resolve it the same
    # way run_copy_stage picked it, falling back to the campaign's own current
    # languages/language if the persisted JSON predates that (shouldn't happen
    # for a campaign whose Copy stage already ran, but stays safe either way).
    primary_language = (
        (copy_data_raw or {}).get("primary_language")
        or (list(campaign.languages) if campaign.languages else [campaign.language or "pt-BR"])[0]
    )
    copy_data = _stage_language_variant(copy_data_raw, primary_language) or {}
    creative_variant = _stage_language_variant(creative_data_raw, primary_language) or {}
    campaign_cta = copy_data.get("cta") or campaign.cta
    campaign_headline = copy_data.get("headline", "")
    planned_slides = [SimpleNamespace(**s) for s in creative_variant["carousel_plan"]["slides"]]
    # Build 2 (the core carry-forward requirement from Build 1's own documented
    # limitation): every selected language, and every selected target
    # platform, not just the primary of each — used below by
    # `_render_additional_platform_variants` to render one independent
    # `PlatformCampaignVariant` per combination beyond the primary one, which
    # the loop right below this still renders exactly as it always has.
    languages = list(campaign.languages) if campaign.languages else [campaign.language or "pt-BR"]
    target_platforms = list(campaign.target_platforms) if campaign.target_platforms else ["instagram"]
    primary_platform = target_platforms[0] if target_platforms else "instagram"

    # Build 6R defense-in-depth: reject unsupported persisted
    # campaign/copy/creative claims before even the source-product identity
    # vision call, platform adaptation, CreativeDirection, or image generation.
    _enforce_previsual_claim_grounding_gate(
        db,
        campaign=campaign,
        brand=brand,
        product=product,
        phase="visuals_stage",
        structures={
            "campaign": {
                "angle": campaign.angle or "",
                "hook": campaign.hook or "",
                "main_promise": campaign.main_promise or "",
                "cta": campaign.cta or "",
            },
            "strategy": strategy_data or {},
            "master_concept": (
                _load_stage_json(
                    db,
                    campaign.id,
                    "master_concept",
                )
                or {}
            ),
            "copy": copy_data_raw or {},
            "creative": creative_data_raw or {},
        },
    )

    progress.set_progress(5, "Loading candidate photos")
    # Round 19: same structure-mode rule as run_copy_stage and get_campaign — a
    # specific Product means deep-dive, a category-only campaign with at least
    # one hand-picked discovery product means discovery, and a category-only
    # campaign with none picked yet keeps today's original behavior untouched.
    discovery_products = list(campaign.discovery_products)
    is_discovery = campaign.product_id is None and len(discovery_products) > 0

    if is_discovery:
        # One slide per hand-picked product, in the order they were picked — this
        # is NOT round-robin: each slide must show a DIFFERENT specific product,
        # never cycle back through one already used. A picked product with no
        # active photo on file simply doesn't get a slide (best-effort, same "a
        # moved/deleted source file shouldn't fail the whole run" philosophy as
        # the rest of this loop) rather than failing the whole run over one gap.
        slide_assets: list[Asset] = []
        slides: list[SimpleNamespace] = []
        # Build 6 repair (Critical Defect 1): paired alongside slide_assets so
        # the pre-generation identity gate below can check each discovery
        # slide's own asset against ITS OWN picked product — never the
        # deep-dive campaign's single `product` (there isn't one here).
        asset_product_pairs: list[tuple[Asset, Product | None]] = []
        for idx, dp in enumerate(discovery_products):
            if idx >= len(planned_slides):
                break  # the model planned fewer slides than products were picked
            per_product = _select_render_assets(
                db, brand_id=brand.id, category_id=None, product_id=dp.product_id, limit=1,
            )
            asset = per_product[0] if per_product else None
            if asset is None or not Path(asset.absolute_path).exists():
                continue
            slide_assets.append(asset)
            slides.append(planned_slides[idx])
            asset_product_pairs.append((asset, db.get(Product, dp.product_id)))
        if not slide_assets:
            campaign.status = "FAILED"
            db.commit()
            raise ValueError(
                "None of this discovery campaign's picked products have an active photo on file — "
                "scan your library, add a photo for at least one picked product, or pick different "
                "products before generating visuals."
            )
    else:
        # Sized off the plan actually persisted by run_copy_stage (which already honors
        # campaign.target_slide_count), not config.max_slides alone — a custom slide
        # count larger than the default cap should still get enough DISTINCT candidate
        # photos to cover every planned slide when that many actually exist. When
        # fewer photos exist than planned slides, the loop below round-robins through
        # whatever this returns rather than truncating the carousel (see the Round 18
        # fix comment just below) — this `limit` only controls how many distinct
        # photos get a chance to be used, never how many slides get rendered.
        candidate_assets = _select_render_assets(
            db, brand_id=brand.id, category_id=campaign.category_id, product_id=campaign.product_id,
            limit=max(4, len(planned_slides) * 2, config.max_slides * 2),
        )
        if not candidate_assets:
            campaign.status = "FAILED"
            db.commit()
            raise ValueError(
                "No active photos found for this category — scan your library or add photos before "
                "generating visuals."
            )

        # Round 18 fix: a carousel is NOT capped to however many distinct source
        # photos happen to be on file for this product/category — a user with just
        # one product photo, asking for a 6-slide carousel "like these reference
        # slides" (each a different AI-recreated composition of the SAME real
        # product, per `recreate_with_ai`/the visual-master mechanism above), must
        # still get all 6 slides, not silently just 1. Every planned slide is kept;
        # `candidate_assets` is cycled (round-robin via modulo) when there are
        # fewer photos than planned slides, rather than truncating the carousel
        # down to the photo count. With recreate_with_ai on, reusing one photo
        # across slides is exactly the intended workflow (six different recreated
        # compositions of one real product); with it off, slides reusing the same
        # photo still differ by their own headline/body/cta, same as any ordinary
        # multi-slide carousel built from one hero shot.
        slides = planned_slides
        slide_assets = [candidate_assets[(i - 1) % len(candidate_assets)] for i in range(1, len(slides) + 1)]
        # Build 6 repair (Critical Defect 1): every slide here shares the SAME
        # deep-dive `product` (resolved by `_load_campaign_context` above) —
        # `None` for a category-only campaign, which correctly makes the gate
        # below a no-op (a category-only campaign makes no per-product claim).
        asset_product_pairs = [(asset, product) for asset in slide_assets]

    # Build 6 repair (Critical Defect 1) — a PRE-GENERATION source-product
    # identity gate: before ANY billed AI image generation below (full
    # recreation or an AI-generated scene/background), confirm every distinct
    # real source photo about to be used actually depicts the catalog product
    # it's claimed to be. Raises (failing this whole run, never a silent
    # NEEDS_REVIEW) on a MISMATCH or an UNVERIFIABLE verdict — see
    # `_enforce_source_product_identity_gate`'s own docstring for exactly why
    # UNVERIFIABLE is never treated as a pass. A no-op (zero extra cost, zero
    # risk) when no `ai_provider` is available or no slide has a catalog
    # product to check against in the first place.
    await _enforce_source_product_identity_gate(
        db, campaign=campaign, ai_provider=ai_provider, vision_model=config.creative_qa_model,
        asset_product_pairs=asset_product_pairs,
    )

    campaign.status = "GENERATING"
    # Clear any slides/QA outputs from a previous run so a retry never accumulates
    # duplicates alongside the fresh render.
    db.query(CampaignSlide).filter(CampaignSlide.campaign_id == campaign.id).delete()
    db.query(CampaignOutput).filter(
        CampaignOutput.campaign_id == campaign.id, CampaignOutput.kind == "qa_report"
    ).delete()
    db.commit()
    progress.set_progress(15, "Rendering creative")

    brand_colors = resolve_brand_colors(brand)
    logo_path = resolve_brand_logo_path(db, brand.id)
    # Build 1 (Part G/H): the one canonical brand-style structure — accent/text
    # color and font now actually come from brand data (previously always the
    # hardcoded SlideCreativeInput/TemplateContext defaults, at every call site,
    # confirmed via audit) and its disclaimer_text is what fills the new
    # deterministic disclaimer field below (Part H's one genuinely-missing
    # element — `brand.disclaimers` existed but was never rendered).
    brand_style = resolve_brand_style(db, brand, logo_path=logo_path)
    category_slug = category.slug if category else "general"
    now = datetime.now(timezone.utc)
    rendered_asset_ids: list[str] = []
    # Build 2, Part K: which image-model role + Images API quality tier this
    # whole run uses for every AI-generated background/recreation call it
    # makes — resolved once (quality mode is a per-run setting, not per-slide).
    quality_image_model, quality_tier = _resolve_image_model_and_quality(config)

    # Build 6R-B1 critical repair:
    # the primary platform/language previously bypassed PlatformAdaptation
    # and CreativeDirection even though secondary variants used them.
    master_concept_data = _load_stage_json(
        db,
        campaign.id,
        "master_concept",
    )

    master_concept = (
        MasterCampaignConcept(**master_concept_data)
        if master_concept_data
        else None
    )

    primary_content_type = (
        default_content_type_for_platform(
            primary_platform,
            slide_count=len(slides),
        )
        or "carousel"
    )

    primary_platform_feedback_note = (
        format_feedback_for_prompt(
            select_feedback_examples(
                db,
                brand_id=brand.id,
                platform=primary_platform,
                language="",
                category_id=campaign.category_id,
                product_id=campaign.product_id,
                objective=campaign.objective,
                content_type=primary_content_type,
                limit=config.feedback_examples_limit,
            )
        )
    )

    verified_facts_note = (
        format_verified_facts_for_prompt(
            resolve_verified_product_facts(db, product)
        )
        if product is not None
        else ""
    )
    primary_adaptation = await _resolve_platform_adaptation(
        ai_provider,
        master_concept=master_concept,
        platform=primary_platform,
        content_type=primary_content_type,
        model=config.platform_adapter_model,
        feedback_note=primary_platform_feedback_note,
    verified_facts_note=verified_facts_note)
    _enforce_previsual_claim_grounding_gate(
        db,
        campaign=campaign,
        brand=brand,
        product=product,
        phase=f"platform_adaptation:{primary_platform}",
        structures={"platform_adaptation": primary_adaptation.model_dump()},
    )

    if ai_provider is not None:
        record_prompt_usage(
            db,
            campaign_id=campaign.id,
            purpose="platform_adaptation",
            language="",
            platform=primary_platform,
        )

        record_stage_usage(
            db,
            campaign_id=campaign.id,
            operation="platform_adaptation",
            providers=[ai_provider],
            platform=primary_platform,
            content_type=primary_content_type,
        )

    primary_direction_feedback_note = (
        format_feedback_for_prompt(
            select_feedback_examples(
                db,
                brand_id=brand.id,
                platform=primary_platform,
                language=primary_language,
                category_id=campaign.category_id,
                product_id=campaign.product_id,
                objective=campaign.objective,
                content_type=primary_content_type,
                limit=config.feedback_examples_limit,
            )
        )
    )

    # Round 18 "Campaign Visual Master" (see recreate_creative_image's docstring):
    # once a slide's full AI recreation is generated AND passes the product-
    # fidelity gate, its rendered PNG becomes an extra style reference for later
    # slides' recreation calls, so a multi-slide carousel reads as one
    # consistent, art-directed campaign world rather than unrelated images.
    # Stays None whenever recreation is off, unverified, or unavailable — later
    # slides then just don't get this extra reference, nothing else changes.
    visual_master_path: Path | None = None
    # Build 2: tracked so the primary (first platform x first language) combo
    # gets its own `PlatformCampaignVariant` row too, for a uniform "every
    # combination is a variant" view — reusing these already-rendered paths
    # rather than rendering the primary combo a second time.
    primary_slide_paths: list[str] = []
    primary_qa_paths: list[str] = []
    # Build 3 carry-forward fix (requirement 1): every AI-generated background
    # this primary-combo loop produces, keyed by slide index — handed to
    # `_render_additional_platform_variants` so a non-primary LANGUAGE of this
    # SAME primary platform can reuse it instead of paying for a redundant
    # regeneration. Before this fix, `_render_additional_platform_variants`
    # only ever shared a background among the languages IT rendered, never
    # with the one language this loop itself already rendered — so e.g.
    # Instagram+en (non-primary) always regenerated Instagram's slide-1
    # background from scratch even though Instagram+pt-BR (primary) had just
    # generated the exact same scene right here.
    primary_generated_backgrounds: dict[int, Image.Image] = {}
    primary_creative_directions: dict[int, CreativeDirection] = {}

    for i, slide in enumerate(slides, start=1):
        asset = slide_assets[i - 1]
        source_path = Path(asset.absolute_path)
        if not source_path.exists():
            continue  # a moved/deleted source file shouldn't fail the whole run

        output_path = build_slide_output_path(
            output_root=config.output_root, brand_slug=brand.slug, category_slug=category_slug,
            campaign_display_id=campaign.display_id, year=now.year, month=now.month,
            platform_key=effective_platform_key, slide_number=i,
        )
        qa_report_path = build_qa_report_path(
            output_root=config.output_root, brand_slug=brand.slug, category_slug=category_slug,
            campaign_display_id=campaign.display_id, year=now.year, month=now.month, slide_number=i,
        )
        slide_eyebrow = getattr(slide, "eyebrow", "")
        slide_headline = slide.headline
        slide_body = getattr(slide, "body", "")
        slide_cta = getattr(slide, "cta", "") or campaign_cta

        primary_fallback_direction = (
            _deterministic_creative_direction(
                master_concept=master_concept,
                adaptation=primary_adaptation,
                platform=primary_platform,
                language=primary_language,
                content_type=primary_content_type,
                slide_role=getattr(
                    slide,
                    "purpose",
                    "",
                ),
                brand_style=brand_style,
            )
        )

        primary_creative_direction = (
            await _generate_creative_direction(
                ai_provider,
                master_concept=master_concept,
                adaptation=primary_adaptation,
                platform=primary_platform,
                language=primary_language,
                content_type=primary_content_type,
                slide=slide,
                model=config.creative_director_model,
                fallback=primary_fallback_direction,
                feedback_note=primary_direction_feedback_note,
            verified_facts_note=verified_facts_note)
        )
        _enforce_previsual_claim_grounding_gate(
            db,
            campaign=campaign,
            brand=brand,
            product=product,
            phase=f"creative_direction:{primary_platform}:{primary_language}:slide-{i}",
            structures={"creative_direction": {
                key: item
                for key, item in primary_creative_direction.model_dump().items()
                if key not in {"prohibited_elements", "negative_constraints"}
            }},
        )

        primary_creative_directions[i] = (
            primary_creative_direction
        )

        if ai_provider is not None:
            record_prompt_usage(
                db,
                campaign_id=campaign.id,
                purpose="creative_direction",
                language=primary_language,
                platform=primary_platform,
            )

            record_stage_usage(
                db,
                campaign_id=campaign.id,
                operation="creative_direction",
                providers=[ai_provider],
                platform=primary_platform,
                language=primary_language,
                content_type=primary_content_type,
            )

        recreated_image = None
        fidelity_outcome: RecreationOutcome | None = None
        if config.recreate_with_ai and image_provider is not None:
            fmt = get_platform_format(effective_platform_key)
            if ai_provider is not None:
                # The verified path (round 18): generate, check against the real
                # source photo, retry once if needed, fall back to None (the
                # deterministic pipeline below) rather than trust an unverified
                # image — see recreate_creative_image_with_fidelity_gate.
                fidelity_outcome = await recreate_creative_image_with_fidelity_gate(
                    db, image_provider=image_provider, ai_provider=ai_provider, brand=brand,
                    category_id=campaign.category_id, source_image_path=source_path,
                    model=quality_image_model, vision_model=config.creative_qa_model,
                    width=fmt.width, height=fmt.height,
                    angle=campaign.angle or "", main_promise=campaign.main_promise or "",
                    visual_brief=getattr(slide, "visual_brief", ""),
                    eyebrow="", headline="", body="", cta="",
                    visual_master_path=visual_master_path,
                    creative_direction=primary_creative_direction,
                    quality=quality_tier,
                    revision_model=config.revision_model,
                )
                recreated_image = fidelity_outcome.image
                if recreated_image is not None:
                    # Build 5 repair (Part 1): record which scene-generation RECIPE
                    # version actually produced this image — language="" since a
                    # scene never varies by copy language (same reasoning as
                    # platform_adaptation above).
                    record_prompt_usage(
                        db, campaign_id=campaign.id, purpose="scene_generation", language="",
                        platform=primary_platform,
                        extra={"mode": "full_recreation", "verified": fidelity_outcome.verified},
                    )
                    record_stage_usage(
                        db, campaign_id=campaign.id, operation="scene_generation", providers=[image_provider],
                        platform=primary_platform,
                    )
            else:
                # No AI provider on hand to verify product fidelity against the real
                # photo — this is exactly the unverified-recreation failure mode
                # round 17 turned off by default. Fail closed: skip recreation
                # entirely rather than ship an unverifiable image, and fall through
                # to the deterministic pipeline below.
                fidelity_outcome = RecreationOutcome(
                    image=None, verified=False, attempts=0,
                    fidelity_notes="No AI provider available to verify product fidelity — recreation skipped.",
                )

        generated_background = None
        zone_detection = None
        if recreated_image is None:
            # Full recreation already produced the whole image when it succeeds —
            # these two are irrelevant then; only run them as the fallback path
            # (recreation off, or it failed and returned None).
            if config.use_ai_background and image_provider is not None:
                fmt = get_platform_format(effective_platform_key)
                generated_background = await generate_ai_background(
                    db, image_provider=image_provider, brand=brand, model=quality_image_model,
                    width=fmt.width, height=fmt.height, visual_brief=getattr(slide, "visual_brief", ""),
                    quality=quality_tier,
                    creative_direction=primary_creative_direction,
                )
                if generated_background is not None:
                    primary_generated_backgrounds[i] = generated_background
                    record_prompt_usage(
                        db, campaign_id=campaign.id, purpose="scene_generation", language="",
                        platform=primary_platform, extra={"mode": "background_only"},
                    )
                    record_stage_usage(
                        db, campaign_id=campaign.id, operation="scene_generation", providers=[image_provider],
                        platform=primary_platform,
                    )

            if (
                config.require_ai_background_success
                and config.use_ai_background
                and generated_background is None
            ):
                raise RuntimeError(
                    "Premium hero acceptance requires a successful "
                    "AI-generated background; deterministic gradient "
                    "fallback is not accepted."
                )

            if config.detect_product_zone and ai_provider is not None:
                zone_detection = await detect_product_zone(
                    ai_provider=ai_provider, image_path=source_path, model=config.vision_model,
                )

        # When recreation succeeded, the marketing text was baked directly into the
        # image (see recreate_creative_image's docstring) — pass empty text here so
        # this app's own HTML/CSS layer doesn't draw a second, competing copy of it
        # on top. The real text is still stored on the CampaignSlide DB row below
        # either way, for the record and for editability if the slide is re-rendered
        # without recreation later.
        text_baked_in = False  # Build 6R-C1: deterministic renderer owns campaign text
        slide_features = [
            Feature(icon=f.get("icon", ""), title=f.get("title", ""), subtitle=f.get("subtitle", ""))
            for f in (getattr(slide, "features", None) or [])
        ]
        creative_input = SlideCreativeInput(
            source_image_path=source_path, template_id=config.template_id, platform_key=effective_platform_key,
            eyebrow="" if text_baked_in else slide_eyebrow,
            headline="" if text_baked_in else slide_headline,
            body="" if text_baked_in else slide_body,
            cta="" if text_baked_in else slide_cta,
            brand_colors=brand_colors, logo_path=logo_path,
            accent_color=brand_style.accent_color, text_color=brand_style.text_color,
            font_family=brand_style.primary_font,
            generated_background=generated_background, product_zone_detection=zone_detection,
            recreated_image=recreated_image,
            # Round 17 feature_showcase fields — also suppressed when the AI baked
            # its own text into a recreated image, same reasoning as eyebrow/etc
            # above (never draw two competing text layers).
            badge_text="" if text_baked_in else getattr(slide, "badge_text", ""),
            intro="" if text_baked_in else getattr(slide, "intro", ""),
            features=[] if text_baked_in else slide_features,
            callout_label="" if text_baked_in else getattr(slide, "callout_label", ""),
            callout_value="" if text_baked_in else getattr(slide, "callout_value", ""),
            bottom_features=[] if text_baked_in else list(getattr(slide, "bottom_features", None) or []),
            trust_badges=[] if text_baked_in else list(getattr(slide, "trust_badges", None) or []),
            # Build 1 (Part H): deterministic disclaimer text, never baked into an
            # AI-recreated image (same never-two-competing-text-layers rule as
            # every other text field above).
            disclaimer="" if text_baked_in else brand_style.disclaimer_text,
            slide_number=i, total_slides=len(slides),
            campaign_archetype=(
                primary_creative_direction.campaign_archetype
            ),
            slide_role=getattr(
                slide,
                "purpose",
                "",
            ),
                             direction_palette=list(primary_creative_direction.palette or brand_style.palette or []),
                             secondary_font_family=brand_style.secondary_font,
                             typography_direction=primary_creative_direction.typography_direction,
                             headline_emphasis=primary_creative_direction.headline_emphasis,
                             cta_treatment=primary_creative_direction.cta_treatment,
                             hero_treatment=primary_creative_direction.hero_treatment,
                             visual_style=primary_creative_direction.visual_style,
                             mood=primary_creative_direction.mood,
                             negative_space=primary_creative_direction.negative_space,
        )
        masked_scene_applied = await _apply_masked_scene_edit_if_enabled(
            config=config,
            image_provider=image_provider,
            creative_input=creative_input,
        )

        if masked_scene_applied:
            _record_masked_scene_usage(
                db,
                campaign_id=campaign.id,
                image_provider=image_provider,
                platform=primary_platform,
                content_type=primary_content_type,
            )
        result = await render_slide(creative_input, output_path=output_path, renderer=renderer)
        from .creative.pipeline import persist_render_context as _persist_render_context
        _persist_render_context(
            slide_output_path=result.output_path,
            creative_direction=primary_creative_direction.model_dump(),
            visual_base=(recreated_image if recreated_image is not None else generated_background),
            visual_base_kind=(
                "recreated_image"
                if recreated_image is not None
                else "generated_background"
                if generated_background is not None
                else "none"
            ),
            product_zone_detection=zone_detection,
            slide_role=getattr(slide, "purpose", ""),
        )

        if fidelity_outcome is not None and fidelity_outcome.image is not None and fidelity_outcome.verified:
            # This slide is now the strongest available visual-consistency
            # reference for the rest of the carousel (see recreate_creative_
            # image's docstring on visual_master_path) — only ever a slide that
            # actually passed the fidelity gate, never an unverified one.
            visual_master_path = result.output_path

        qa_report_path.parent.mkdir(parents=True, exist_ok=True)
        qa_dict = result.qa.to_dict()
        if fidelity_outcome is not None:
            # Mirrors the user's own uploaded creative-handoff contract's
            # PRODUCT_FIDELITY_CHECK field — kept in the QA record (not the
            # CreativeQAResult dataclass itself, which stays pipeline.py's
            # DB-agnostic mechanical checks) so a human reviewer can see exactly
            # what happened even when the gate fell back to the deterministic
            # pipeline.
            qa_dict["product_fidelity"] = {
                "attempted": True,
                "verified": fidelity_outcome.verified,
                "used_recreated_image": recreated_image is not None,
                "attempts": fidelity_outcome.attempts,
                "notes": fidelity_outcome.fidelity_notes,
            }
        qa_report_path.write_text(json.dumps(qa_dict, indent=2))

        db.add(
            CampaignSlide(
                campaign_id=campaign.id, slide_number=i, purpose=getattr(slide, "purpose", ""),
                eyebrow=slide_eyebrow, headline=slide_headline, body=slide_body,
                cta=slide_cta, visual_brief=getattr(slide, "visual_brief", ""),
                source_asset_id=asset.id, template_id=config.template_id,
                rendered_asset_path=str(result.output_path),
            )
        )
        if not any(ca.asset_id == asset.id for ca in campaign.assets):
            db.add(CampaignAsset(campaign_id=campaign.id, asset_id=asset.id, role="source"))
        db.add(
            CampaignOutput(
                campaign_id=campaign.id, kind="qa_report", platform=effective_platform_key,
                file_path=str(qa_report_path),
            )
        )
        asset.times_used = (asset.times_used or 0) + 1
        asset.last_used_at = now
        rendered_asset_ids.append(asset.sha256)
        primary_slide_paths.append(str(result.output_path))
        primary_qa_paths.append(str(qa_report_path))
        db.commit()
        progress.set_progress(15 + round(75 * i / len(slides)), f"Rendered slide {i} of {len(slides)}")

    existing_fp = db.query(CampaignFingerprint).filter(CampaignFingerprint.campaign_id == campaign.id).one_or_none()
    fp_fields = dict(
        text_hash=text_hash(campaign.angle, campaign.main_promise, campaign_headline),
        angle=campaign.angle,
        promise_summary=f"{campaign.angle} {campaign.main_promise} {insight}".strip(),
        objective=campaign.objective,
        format=effective_platform_key,
        asset_sha256_list=rendered_asset_ids,
        computed_at=now,
    )
    if existing_fp is not None:
        for key, value in fp_fields.items():
            setattr(existing_fp, key, value)
    else:
        db.add(CampaignFingerprint(campaign_id=campaign.id, **fp_fields))

    campaign.status = "REVIEW"
    db.commit()

    # Build 2: every OTHER selected (target_platform x language) combination
    # beyond the primary one just rendered above — see this function's own
    # docstring update and `_render_additional_platform_variants`. Best-effort
    # per variant (never lets one variant's failure fail the whole Visuals
    # stage, which has already succeeded for the primary combo by this point);
    # `config.render_platform_variants=False` (never the default) skips this
    # entirely, for a caller that wants to isolate the legacy single-variant
    # path.
    variants_rendered = 0
    if config.render_platform_variants:
        progress.set_progress(92, "Rendering additional platform/language variants")
        master_concept_data = _load_stage_json(db, campaign.id, "master_concept")
        variants_rendered = await _render_additional_platform_variants(
            db, campaign=campaign, brand=brand,
            category_slug=category_slug, languages=languages, target_platforms=target_platforms,
            primary_language=primary_language, primary_platform=primary_platform,
            effective_platform_key=effective_platform_key,
            copy_data_raw=copy_data_raw, creative_data_raw=creative_data_raw,
            master_concept_data=master_concept_data,
            discovery_products=discovery_products, is_discovery=is_discovery,
            brand_colors=brand_colors, logo_path=logo_path, brand_style=brand_style,
            config=config, renderer=renderer, image_provider=image_provider, ai_provider=ai_provider,
            quality_image_model=quality_image_model, quality_tier=quality_tier,
            primary_slide_paths=primary_slide_paths, primary_qa_paths=primary_qa_paths,
            primary_generated_backgrounds=primary_generated_backgrounds,
            now=now,
            primary_adaptation=primary_adaptation,
            primary_creative_directions=primary_creative_directions,
        product=product, verified_facts_note=verified_facts_note)

    db.refresh(campaign)
    progress.set_progress(100, "Ready for review")
    _audit(
        db, campaign.id, "autopilot.completed",
        {"slides_rendered": len(rendered_asset_ids), "additional_variants_rendered": variants_rendered},
    )
    db.commit()
    return campaign



# ---------------------------------------------------------------------------
# Build 2 — Platform Adapter + Creative Director + Hybrid Visual Engine.
# ---------------------------------------------------------------------------

# Part F fallback: how the master concept adapts to each platform when no
# `ai_provider` is on hand to generate a richer `PlatformAdaptation` — the
# same real, specific strategies the user's own spec named by example, kept
# here as the honest deterministic default rather than a generic placeholder.
_DEFAULT_ADAPTATION_STRATEGY: dict[str, str] = {
    "instagram": "visual storytelling carousel — one idea per slide, consistent visual system",
    "facebook": "slightly fuller promotional context than Instagram, conversational tone",
    "tiktok": "hook + script + shot progression — spoken-language, native/organic tone",
    "youtube_shorts": "hook + script + shot progression, with a searchable, keyword-bearing title",
    "pinterest": "vertical discovery creative — evergreen, search-optimized, no urgency language",
    "linkedin": "professional/educational framing, even for a consumer product",
    "x": "short, concise execution — a single sharp visual and line",
}


async def _resolve_platform_adaptation(
    ai_provider: AIProvider | None, *, master_concept: MasterCampaignConcept | None, platform: str,
    content_type: str, model: str, feedback_note: str = "",
verified_facts_note: str = "") -> PlatformAdaptation:
    """Part F. AI-optional, mirroring every other AI hook in this module: with
    no provider (the default no-key Visuals-only path), falls back to the
    real, platform-specific strategy note above rather than a generic one —
    never fabricated marketing claims, just a structural default. With a
    provider, asks it to adapt the master concept concretely — "do not simply
    resize the same creative" is the literal instruction given.

    Build 4 carry-forward requirement 1: `feedback_note` is deliberately
    PLATFORM-ONLY (the caller resolves it with `language=""`) since a
    `PlatformAdaptation` is generated once per platform and shared across
    every language that platform targets (see this function's own callers in
    `_render_additional_platform_variants`) — language-specific feedback has
    no single language to attach to here and belongs instead in the
    per-language `_generate_creative_direction`/`generate_video_concept`
    calls, which already receive their own language-scoped `feedback_note`.
    """
    fallback_strategy = _DEFAULT_ADAPTATION_STRATEGY.get(platform, "adapt the concept to this platform's real format")
    if ai_provider is None or master_concept is None:
        return PlatformAdaptation(
            platform=platform, adaptation_strategy=fallback_strategy,
            narrative_shape=(master_concept.story_arc if master_concept else ""),
            tone_adjustment="", content_type=content_type,
            reasoning="Deterministic fallback — no AI provider available for platform adaptation.",
        )
    cap = PLATFORM_CAPABILITIES.get(platform)
    try:
        return await ai_provider.generate_structured(
            system=(
                (("You are a platform adapter for a marketing creative director. Given ONE master campaign "
                "concept, decide how it should be re-shaped for a SPECIFIC platform's real conventions — "
                "do not simply describe resizing the same creative; describe how the STORY changes shape "
                f"for this platform (e.g. {fallback_strategy}).") + "\n" + _claims_boundary_instruction() + _sparse_fact_grounding_instruction())
            ),
            user=(
                ((f"Master concept: {master_concept.concept_name!r} — {master_concept.campaign_promise!r}. Key "
                f"message: {master_concept.key_message!r}. Story arc: {master_concept.story_arc!r}. "
                f"Product/category context: {master_concept.product_category_context!r}. "
                f"Campaign archetype: {master_concept.campaign_archetype!r}. "
                f"Visual story system: {master_concept.visual_story_system!r}. "
                f"Hero treatment: {master_concept.hero_treatment!r}. "
                f"Proof/demo strategy: {master_concept.proof_or_demo_strategy!r}. "
                f"Visual identity: {master_concept.visual_identity!r}. Target platform: {platform} "
                f"({cap.label if cap else platform}). Content type: {content_type}."
                f"{' Platform notes: ' + cap.copy_notes if cap else ''}"
                f"{chr(10) + feedback_note if feedback_note else ''}") + (("\n" + verified_facts_note) if verified_facts_note else ""))
            ),
            schema=PlatformAdaptation,
            model=model,
        )
    except Exception:  # noqa: BLE001 - best-effort, mirrors every other AI hook here
        return PlatformAdaptation(
            platform=platform, adaptation_strategy=fallback_strategy, narrative_shape=master_concept.story_arc,
            tone_adjustment="", content_type=content_type,
            reasoning="Deterministic fallback — platform adaptation call failed.",
        )


def _deterministic_creative_direction(
    *,
    master_concept: MasterCampaignConcept | None,
    adaptation: PlatformAdaptation,
    platform: str,
    language: str,
    content_type: str,
    slide_role: str,
    brand_style,
) -> CreativeDirection:
    """Grounded fallback for one concrete slide direction.

    Build 6R-B1 preserves the master campaign archetype even without
    an AI creative-director result.
    """
    return CreativeDirection(
        concept_name=(
            master_concept.concept_name
            if master_concept
            else ""
        ),
        platform=platform,
        content_type=content_type,
        language=language,
        campaign_visual_identity=(
            master_concept.visual_identity
            if master_concept
            else ""
        ),
        product_category_context=(
            master_concept.product_category_context
            if master_concept
            else ""
        ),
        campaign_archetype=(
            master_concept.campaign_archetype
            if master_concept
            else ""
        ),
        archetype_reasoning=(
            master_concept.archetype_reasoning
            if master_concept
            else ""
        ),
        visual_story_system=(
            master_concept.visual_story_system
            if master_concept
            else ""
        ),
        hero_treatment=(
            master_concept.hero_treatment
            if master_concept
            else ""
        ),
        proof_or_demo_strategy=(
            master_concept.proof_or_demo_strategy
            if master_concept
            else ""
        ),
        rationale=(
            "Deterministic fallback ? no AI provider available. "
            f"Platform adaptation: {adaptation.adaptation_strategy}"
        ),
        emotional_goal=(
            master_concept.emotional_goal
            if master_concept
            else ""
        ),
        palette=list(
            brand_style.palette or []
        ),
        typography_direction=(
            f"Brand primary font: "
            f"{brand_style.primary_font}."
        ),
        slide_role=slide_role,
        continuity_notes=(
            adaptation.narrative_shape
        ),
        scene_generation_prompt="",
    )


async def _generate_creative_direction(
    ai_provider: AIProvider | None,
    *,
    master_concept: MasterCampaignConcept | None,
    adaptation: PlatformAdaptation,
    platform: str,
    language: str,
    content_type: str,
    slide,
    model: str,
    fallback: CreativeDirection,
    feedback_note: str = "",
verified_facts_note: str = "") -> CreativeDirection:
    """Resolve one concrete product-aware slide direction."""

    if ai_provider is None or master_concept is None:
        return fallback

    try:
        return await ai_provider.generate_structured(
            system=(
                (("You are a senior advertising creative director defining one "
                "concrete marketing slide. Ground every decision in the supplied "
                "master campaign and platform adaptation. Never invent factual "
                "product claims, rankings, certifications, testimonials, prices, "
                "promotions, scarcity signals or before/after results. "
                "Execute the selected campaign_archetype and visual_story_system. "
                "The PRODUCT and its verified buying decision determine the "
                "creative direction; a template never determines the product. "
                "Do not automatically use black/gold luxury, neon, cyber, "
                "nightclub, pedestal, cosmetics, clinical or minimalist styling "
                "for unrelated categories. Lifestyle utility should feel useful "
                "in real life. Technical performance should communicate only "
                "verified technical value. Feature demo should make actual "
                "features understandable. Premium discovery may use editorial "
                "storytelling. Product identity must remain faithful.") + "\n" + _claims_boundary_instruction() + _sparse_fact_grounding_instruction())
            ),
            user=(
                ((f"Master concept: {master_concept.concept_name!r} ? "
                f"{master_concept.campaign_promise!r}. "
                f"Product/category context: "
                f"{master_concept.product_category_context!r}. "
                f"Campaign archetype: "
                f"{master_concept.campaign_archetype!r}. "
                f"Archetype reasoning: "
                f"{master_concept.archetype_reasoning!r}. "
                f"Visual story system: "
                f"{master_concept.visual_story_system!r}. "
                f"Hero treatment: "
                f"{master_concept.hero_treatment!r}. "
                f"Proof/demo strategy: "
                f"{master_concept.proof_or_demo_strategy!r}. "
                f"Campaign visual identity: "
                f"{master_concept.visual_identity!r}. "
                f"Platform: {platform}. "
                f"Platform adaptation: "
                f"{adaptation.adaptation_strategy!r} "
                f"({adaptation.narrative_shape!r}). "
                f"Language: {language}. "
                f"Content type: {content_type}. "
                f"Slide role: "
                f"{getattr(slide, 'purpose', '') or 'not specified'}. "
                f"Headline: "
                f"{getattr(slide, 'headline', '')!r}. "
                f"Visual brief: "
                f"{getattr(slide, 'visual_brief', '')!r}."
                f"{chr(10) + feedback_note if feedback_note else ''}") + (("\n" + verified_facts_note) if verified_facts_note else ""))
            ),
            schema=CreativeDirection,
            model=model,
        )

    except Exception:  # noqa: BLE001
        return fallback


async def generate_video_concept(
    ai_provider: AIProvider | None, *, master_concept: MasterCampaignConcept | None, platform: str, language: str,
    adaptation: PlatformAdaptation, model: str, feedback_note: str = "",
) -> VideoConcept | None:
    """Part L: the structured hook/script/shot-list output for a video-oriented
    content type (TikTok/YouTube Shorts) — this app has no video-rendering
    capability, so this is never a stand-in for an actual video file (see
    `VideoConcept.is_rendered_video`, always `False`). Returns `None` (never a
    fabricated script) when there's no AI provider or the master concept isn't
    available yet — the caller records `PlatformCampaignVariant.status=
    "SCRIPT_UNAVAILABLE"` for that case rather than inventing content.

    Build 4 carry-forward requirement 1: `feedback_note` is resolved by the
    caller per (platform, language) — e.g. repeated "weak hook" feedback on
    TikTok/pt-BR should ground future TikTok/pt-BR script generation, never
    bleed into an unrelated platform/language — using the same selective,
    bounded `select_feedback_examples` mechanism every other stage uses.
    Still characterization-only (never the rejected script's literal text),
    per carry-forward requirement 2.
    """
    if ai_provider is None or master_concept is None:
        return None
    cap = PLATFORM_CAPABILITIES.get(platform)
    # Build 6 repair (Critical Defect 5/10): one retry before giving up, mirroring
    # `recreate_creative_image_with_fidelity_gate`'s own established one-retry
    # pattern — a live-acceptance run found TikTok/pt-BR settled for
    # `SCRIPT_UNAVAILABLE` (and therefore `qa_status=PENDING`, since there was
    # never a script to QA) on what a single transient API failure can easily
    # cause. This does not change the honest "no fabricated script" contract:
    # a second failure still returns `None` exactly as before, and the caller
    # still records `SCRIPT_UNAVAILABLE` for that case.
    for _attempt_number in (1, 2):
        try:
            return await ai_provider.generate_structured(
                system=(
                    "You are a short-form video creative director writing a structured hook/script/shot-list "
                    "for a real production team to film — NOT a description of a video that already exists. "
                    "Ground every beat in the master concept given; never invent a marketing claim not already "
                    f"present in it. {_claims_boundary_instruction()}"
                ),
                user=(
                    f"Master concept: {master_concept.concept_name!r} — {master_concept.campaign_promise!r}. Key "
                    f"message: {master_concept.key_message!r}. Platform: {platform} "
                    f"({cap.label if cap else platform}). Language: {language}. Adaptation strategy: "
                    f"{adaptation.adaptation_strategy!r}.{' Platform notes: ' + cap.copy_notes if cap else ''}"
                    f"{chr(10) + feedback_note if feedback_note else ''}"
                ),
                schema=VideoConcept,
                model=model,
            )
        except Exception:  # noqa: BLE001 - best-effort, mirrors every other AI hook here
            continue
    return None


def _scene_signature(direction: CreativeDirection) -> tuple:
    """Build 3 carry-forward requirement 1/4: the scene-relevant subset of a
    `CreativeDirection` — everything that actually shapes the AI-generated
    background/scene image itself (never the per-language typography/copy
    fields, which are deliberately excluded so a genuine typography-only
    difference between two languages never blocks scene reuse). Two
    directions with the same signature are describing the same visual scene,
    so the background generated for one is safe to reuse for the other
    (requirement 1); a genuinely different signature means the AI provider
    decided this language/platform needs different imagery, so the scene must
    be generated fresh rather than force-reused (requirement 4).

    Two languages that never consult an AI provider at all always match:
    `_deterministic_creative_direction` (the no-AI fallback) builds every one
    of these fields from language-independent inputs (master concept, brand
    style), so two different languages' fallback directions are identical by
    construction. `_render_additional_platform_variants` uses that same
    guarantee to seed the primary platform's cache from `run_visuals_stage`'s
    own plain, direction-less background generation — it computes what
    `_deterministic_creative_direction` WOULD have produced for the primary
    combination and tags the already-generated image with that signature,
    since a direction-less generation is exactly equivalent to the
    deterministic one. `_EMPTY_SCENE_SIGNATURE` (an all-empty tuple) is the
    specific case of that when the brand has no configured palette.
    """
    return (
        direction.background_concept, direction.visual_style, direction.mood, direction.composition,
        direction.product_position, direction.product_scale, direction.lighting, direction.depth,
        direction.texture, tuple(direction.palette), direction.scene_generation_prompt,
    )


_EMPTY_SCENE_SIGNATURE = _scene_signature(CreativeDirection())


async def _render_additional_platform_variants(
    db: Session,
    *,
    campaign: Campaign,
    brand: Brand,
    category_slug: str,
    languages: list[str],
    target_platforms: list[str],
    primary_language: str,
    primary_platform: str,
    effective_platform_key: str,
    copy_data_raw: dict | None,
    creative_data_raw: dict | None,
    master_concept_data: dict | None,
    discovery_products: list,
    is_discovery: bool,
    brand_colors: list[str] | None,
    logo_path: Path | None,
    brand_style,
    config: AutopilotConfig,
    renderer: PlaywrightRenderer,
    image_provider: ImageProvider | None,
    ai_provider: AIProvider | None,
    quality_image_model: str,
    quality_tier: str,
    primary_slide_paths: list[str],
    primary_qa_paths: list[str],
    primary_generated_backgrounds: dict[int, object],
    now: datetime,
    primary_adaptation: PlatformAdaptation | None = None,
    primary_creative_directions: dict[int, CreativeDirection] | None = None,
product=None, verified_facts_note: str = "") -> int:
    """Build 2's core deliverable: for every (target_platform x language)
    combination `campaign` targets, create an independently reviewable
    `PlatformCampaignVariant`. The primary combination (`primary_platform`,
    `primary_language`) was already rendered by `run_visuals_stage`'s own loop
    above (unchanged, so every pre-Build-2 test/behavior stays byte-for-byte
    identical) — it just gets a `PlatformCampaignVariant` row here referencing
    those already-rendered paths, never re-rendered.

    Cost discipline ("do not regenerate expensive visual assets unnecessarily
    just because the language changes"): an AI-generated background
    (`config.use_ai_background`) is generated ONCE per (platform, slide index,
    scene signature) and reused across that platform's other targeted
    languages — the background/scene is language-independent; only the
    deterministic HTML/CSS text layer differs per language, per this build's
    own architecture (shared scene -> shared product composite -> separate
    per-language typography). Full AI recreation (`config.recreate_with_ai`)
    CANNOT be shared this way and isn't — the marketing text bakes directly
    into those pixels (see `recreate_creative_image`'s docstring), so each
    language genuinely needs its own recreation call; this is a real cost
    difference between the two modes, not an oversight.

    Build 3 carry-forward fix: the primary combination's own background
    generations (`primary_generated_backgrounds`, captured by
    `run_visuals_stage`'s own loop) seed the primary platform's cache here too
    — a non-primary LANGUAGE of the SAME primary platform (e.g. Instagram+en
    when Instagram+pt-BR is primary) now reuses that already-generated scene
    instead of paying for a second, redundant AI call, closing the one gap
    the original Build 2 cost-discipline design left. Reuse is gated on a
    "scene signature" (`_scene_signature`) derived from each language's own
    `CreativeDirection` — the scene-relevant fields only (background concept,
    visual style, mood, composition, lighting, etc.), never the per-language
    typography/copy fields. Two directions with an identical signature really
    are describing the same scene (including the common case where no AI
    provider is running at all, so every language's deterministic fallback
    direction is identical by construction — see `_deterministic_creative_
    direction`'s docstring); a direction whose signature genuinely differs
    (an AI provider deciding this language/platform needs a different scene)
    is never force-reused — it gets its own fresh generation, cached
    separately under its own signature for any later language that matches
    IT instead.

    Never raises: one variant's failure (a missing photo, a renderer error) is
    recorded on that variant's own row (`status="FAILED"`, `notes`) rather
    than failing the whole Visuals stage, which has already succeeded for the
    primary combination by the time this runs.

    Returns how many variants ended up with a real rendered/script result
    (`status` in `{"RENDERED", "SCRIPT_ONLY"}`), for the caller's audit log.
    """
    # Retry-safe: clear this campaign's variants from a prior run before
    # regenerating, same discipline as the CampaignSlide/qa_report clearing in
    # run_visuals_stage's own main loop.
    db.query(PlatformCampaignVariant).filter(PlatformCampaignVariant.campaign_id == campaign.id).delete()
    db.commit()

    master_concept = MasterCampaignConcept(**master_concept_data) if master_concept_data else None
    rendered_count = 0
    # Reused across a platform's targeted languages — see this function's own
    # cost-discipline paragraph above. Keyed by slide index (scoped per
    # platform by virtue of being reset at the top of each platform's loop);
    # each slide index maps to a LIST of (scene_signature, image) pairs, not a
    # single image — a platform/slide can end up with more than one distinct
    # scene cached when different languages' CreativeDirections genuinely
    # disagree on what the scene should look like (see `_scene_signature`).
    background_cache: dict[int, list[tuple[tuple, object]]] = {}

    for platform in target_platforms:
        background_cache = {}
        primary_creative_variant = _stage_language_variant(creative_data_raw, primary_language) or {}
        primary_slide_count = len(primary_creative_variant.get("carousel_plan", {}).get("slides", []))
        content_type = default_content_type_for_platform(platform, slide_count=primary_slide_count)
        if content_type is None:
            for language in languages:
                db.add(PlatformCampaignVariant(
                    campaign_id=campaign.id, target_platform=platform, language=language,
                    content_type="unknown", status="SKIPPED_UNSUPPORTED",
                    notes="No known content type for this platform in the Build 2 creative-spec catalog.",
                ))
            db.commit()
            continue
        spec = resolve_platform_creative_spec(platform, content_type)
        # Build 4 carry-forward requirement 1: platform-only (language="")
        # since `adaptation` below is shared across every language this
        # platform targets — see `_resolve_platform_adaptation`'s docstring.
                # Build 6R-B2:
        # `run_visuals_stage` already resolved the primary platform's
        # PlatformAdaptation before rendering its primary slides.
        # Reuse that exact object here instead of paying for and potentially
        # receiving a different second adaptation for the same platform.
        if (
            platform == primary_platform
            and primary_adaptation is not None
        ):
            adaptation = primary_adaptation
        else:
            platform_feedback_note = (
                format_feedback_for_prompt(
                    select_feedback_examples(
                        db,
                        brand_id=brand.id,
                        platform=platform,
                        language="",
                        category_id=campaign.category_id,
                        product_id=campaign.product_id,
                        objective=campaign.objective,
                        content_type=content_type,
                        limit=config.feedback_examples_limit,
                    )
                )
            )

            adaptation = await _resolve_platform_adaptation(
                ai_provider,
                master_concept=master_concept,
                platform=platform,
                content_type=content_type,
                model=config.platform_adapter_model,
                feedback_note=platform_feedback_note,
            verified_facts_note=verified_facts_note)
            _enforce_previsual_claim_grounding_gate(
                db,
                campaign=campaign,
                brand=brand,
                product=product,
                phase=f"platform_adaptation:{platform}",
                structures={"platform_adaptation": adaptation.model_dump()},
            )

            if ai_provider is not None:
                record_prompt_usage(
                    db,
                    campaign_id=campaign.id,
                    purpose="platform_adaptation",
                    language="",
                    platform=platform,
                )

                record_stage_usage(
                    db,
                    campaign_id=campaign.id,
                    operation="platform_adaptation",
                    providers=[ai_provider],
                    platform=platform,
                    content_type=content_type,
                )

        if platform == primary_platform:
            # Build 3 carry-forward fix: prime this platform's cache with
            # whatever `run_visuals_stage`'s own primary-combo loop already
            # generated. Tagged with the signature the DETERMINISTIC fallback
            # direction produces for this platform (never a bare empty
            # tuple) — that's the honest equivalent of "no creative direction
            # was consulted", since it's built only from language-independent
            # inputs (master concept, brand style) the same way for every
            # language, matching `_deterministic_creative_direction`'s own
            # per-language-identical-output guarantee. A non-primary language
            # only reuses this when ITS OWN resolved direction (AI-authored or
            # the same deterministic fallback) lands on that exact signature
            # too — see `_scene_signature`'s docstring.
                        # Build 6R-B2:
            # primary backgrounds now have real per-slide CreativeDirections.
            # Cache each scene under the actual direction that produced it,
            # never a fabricated generic fallback signature.
            background_cache = {
                idx: [
                    (
                        _scene_signature(
                            (
                                primary_creative_directions
                                or {}
                            ).get(idx)
                            or _deterministic_creative_direction(
                                master_concept=master_concept,
                                adaptation=adaptation,
                                platform=platform,
                                language=primary_language,
                                content_type=content_type,
                                slide_role="",
                                brand_style=brand_style,
                            )
                        ),
                        image,
                    )
                ]
                for idx, image in (
                    primary_generated_backgrounds
                    or {}
                ).items()
                if image is not None
            }

        for language in languages:
            if platform == primary_platform and language == primary_language:
                # Already rendered above by run_visuals_stage's own loop — just
                # record the variant row for a uniform "every combination has a
                # variant" view; never re-rendered.
                db.add(PlatformCampaignVariant(
                    campaign_id=campaign.id, target_platform=platform, language=language,
                    content_type=content_type, render_format_key=effective_platform_key,
                    status="RENDERED" if primary_slide_paths else "FAILED",
                    slide_asset_paths=list(primary_slide_paths), copy_language=language,
                    qa_report_paths=list(primary_qa_paths),
                    creative_direction=(
                        primary_creative_directions[
                            max(primary_creative_directions)
                        ].model_dump()
                        if (
                            primary_slide_paths
                            and primary_creative_directions
                        )
                        else {}
                    ),
                    notes="" if primary_slide_paths else "The primary render produced no slides.",
                ))
                db.commit()
                if primary_slide_paths:
                    rendered_count += 1
                continue

            if not spec.supports_static:
                # Part L: a video-oriented content type — structured script
                # only, never a rendered video file. Build 4 carry-forward
                # requirement 1: per (platform, language) feedback grounding,
                # same selective/bounded mechanism as every other stage —
                # e.g. repeated "weak hook" feedback on TikTok/pt-BR grounds
                # future TikTok/pt-BR script generation without touching an
                # unrelated platform or language.
                video_feedback_note = format_feedback_for_prompt(select_feedback_examples(
                    db, brand_id=brand.id, platform=platform, language=language,
                    category_id=campaign.category_id, product_id=campaign.product_id,
                    objective=campaign.objective, content_type=content_type,
                    limit=config.feedback_examples_limit,
                ))
                video_concept = await generate_video_concept(
                    ai_provider, master_concept=master_concept, platform=platform, language=language,
                    adaptation=adaptation, model=config.platform_adapter_model,
                    feedback_note=video_feedback_note,
                )
                if ai_provider is not None:
                    record_prompt_usage(db, campaign_id=campaign.id, purpose="video_concept", language=language, platform=platform)
                    record_stage_usage(
                        db, campaign_id=campaign.id, operation="video_concept", providers=[ai_provider],
                        platform=platform, language=language, content_type=content_type,
                    )
                db.add(PlatformCampaignVariant(
                    campaign_id=campaign.id, target_platform=platform, language=language,
                    content_type=content_type, render_format_key="",
                    status="SCRIPT_ONLY" if video_concept is not None else "SCRIPT_UNAVAILABLE",
                    slide_asset_paths=[], copy_language=language,
                    video_concept=video_concept.model_dump() if video_concept is not None else None,
                    notes="" if video_concept is not None else "No AI provider available to write the script.",
                ))
                db.commit()
                if video_concept is not None:
                    rendered_count += 1
                continue

            try:
                copy_variant = _stage_language_variant(copy_data_raw, language) or {}
                creative_variant = _stage_language_variant(creative_data_raw, language) or {}
                planned_slides = [
                    SimpleNamespace(**s) for s in creative_variant.get("carousel_plan", {}).get("slides", [])
                ]
                if not spec.supports_carousel:
                    planned_slides = planned_slides[: max(1, spec.recommended_slide_count)]
                if not planned_slides:
                    db.add(PlatformCampaignVariant(
                        campaign_id=campaign.id, target_platform=platform, language=language,
                        content_type=content_type, render_format_key=spec.render_format_key,
                        status="FAILED", notes="No planned slides on file for this language.",
                    ))
                    db.commit()
                    continue

                if is_discovery:
                    slide_assets: list[Asset] = []
                    slides: list = []
                    for idx, dp in enumerate(discovery_products):
                        if idx >= len(planned_slides):
                            break
                        per_product = _select_render_assets(
                            db, brand_id=brand.id, category_id=None, product_id=dp.product_id, limit=1,
                        )
                        asset = per_product[0] if per_product else None
                        if asset is None or not Path(asset.absolute_path).exists():
                            continue
                        slide_assets.append(asset)
                        slides.append(planned_slides[idx])
                else:
                    candidate_assets = _select_render_assets(
                        db, brand_id=brand.id, category_id=campaign.category_id, product_id=campaign.product_id,
                        limit=max(4, len(planned_slides) * 2),
                    )
                    slides = planned_slides
                    slide_assets = (
                        [candidate_assets[(i - 1) % len(candidate_assets)] for i in range(1, len(slides) + 1)]
                        if candidate_assets else []
                    )

                if not slide_assets:
                    db.add(PlatformCampaignVariant(
                        campaign_id=campaign.id, target_platform=platform, language=language,
                        content_type=content_type, render_format_key=spec.render_format_key,
                        status="FAILED", notes="No candidate photos available for this platform/language.",
                    ))
                    db.commit()
                    continue

                render_format_key = spec.render_format_key or effective_platform_key
                fmt = get_platform_format(render_format_key)
                campaign_cta = copy_variant.get("cta") or campaign.cta
                slide_paths: list[str] = []
                qa_paths: list[str] = []
                shared_source_parts: list[str] = []
                last_direction = CreativeDirection(platform=platform, language=language, content_type=content_type)

                # Build 4: same selective, bounded feedback grounding as
                # `run_copy_stage` above — computed once per (platform,
                # language), not once per slide, since it doesn't vary by
                # slide. "" (a byte-for-byte no-op) for a brand with no
                # `review_feedback` history yet.
                feedback_note = format_feedback_for_prompt(select_feedback_examples(
                    db, brand_id=brand.id, platform=platform, language=language, category_id=campaign.category_id,
                    product_id=campaign.product_id, objective=campaign.objective, content_type=content_type,
                    limit=config.feedback_examples_limit,
                ))

                for idx, slide in enumerate(slides, start=1):
                    asset = slide_assets[idx - 1]
                    source_path = Path(asset.absolute_path)
                    if not source_path.exists():
                        continue

                    fallback_direction = _deterministic_creative_direction(
                        master_concept=master_concept, adaptation=adaptation, platform=platform,
                        language=language, content_type=content_type, slide_role=getattr(slide, "purpose", ""),
                        brand_style=brand_style,
                    )
                    creative_direction = await _generate_creative_direction(
                        ai_provider, master_concept=master_concept, adaptation=adaptation, platform=platform,
                        language=language, content_type=content_type, slide=slide,
                        model=config.creative_director_model, fallback=fallback_direction,
                        feedback_note=feedback_note,
                    verified_facts_note=verified_facts_note)
                    _enforce_previsual_claim_grounding_gate(
                        db,
                        campaign=campaign,
                        brand=brand,
                        product=product,
                        phase=f"creative_direction:{platform}:{language}:slide-{idx}",
                        structures={"creative_direction": {
                            key: item
                            for key, item in creative_direction.model_dump().items()
                            if key not in {"prohibited_elements", "negative_constraints"}
                        }},
                    )
                    if ai_provider is not None:
                        record_prompt_usage(
                            db, campaign_id=campaign.id, purpose="creative_direction", language=language,
                            platform=platform,
                        )
                        record_stage_usage(
                            db, campaign_id=campaign.id, operation="creative_direction", providers=[ai_provider],
                            platform=platform, language=language, content_type=content_type,
                        )
                    last_direction = creative_direction

                    generated_background = None
                    if config.use_ai_background and image_provider is not None:
                        signature = _scene_signature(creative_direction)
                        cached_match = next(
                            (img for sig, img in background_cache.get(idx, []) if sig == signature), None,
                        )
                        if cached_match is not None:
                            generated_background = cached_match
                            shared_source_parts.append(f"{platform}:slide-{idx}")
                        else:
                            generated_background = await generate_ai_background(
                                db, image_provider=image_provider, brand=brand, model=quality_image_model,
                                width=fmt.width, height=fmt.height, visual_brief=getattr(slide, "visual_brief", ""),
                                quality=quality_tier, creative_direction=creative_direction,
                            )
                            if generated_background is not None:
                                background_cache.setdefault(idx, []).append((signature, generated_background))
                                record_prompt_usage(
                                    db, campaign_id=campaign.id, purpose="scene_generation", language="",
                                    platform=platform, extra={"mode": "background_only"},
                                )
                                record_stage_usage(
                                    db, campaign_id=campaign.id, operation="scene_generation",
                                    providers=[image_provider], platform=platform, content_type=content_type,
                                )

                    recreated_image = None
                    if config.recreate_with_ai and image_provider is not None and ai_provider is not None:
                        # Cannot be shared across languages — see this function's
                        # own docstring on why full recreation's cost can't be
                        # cached the way the background above is.
                        outcome = await recreate_creative_image_with_fidelity_gate(
                            db, image_provider=image_provider, ai_provider=ai_provider, brand=brand,
                            category_id=campaign.category_id, source_image_path=source_path,
                            model=quality_image_model, vision_model=config.creative_qa_model,
                            width=fmt.width, height=fmt.height, angle=campaign.angle or "",
                            main_promise=campaign.main_promise or "",
                            visual_brief=getattr(slide, "visual_brief", ""),
                            eyebrow="", headline="",
                            body="", cta="",
                            creative_direction=creative_direction,
                            quality=quality_tier,
                            revision_model=config.revision_model,
                        )
                        recreated_image = outcome.image
                        if recreated_image is not None:
                            record_prompt_usage(
                                db, campaign_id=campaign.id, purpose="scene_generation", language="",
                                platform=platform, extra={"mode": "full_recreation", "verified": outcome.verified},
                            )
                            record_stage_usage(
                                db, campaign_id=campaign.id, operation="scene_generation",
                                providers=[image_provider], platform=platform, content_type=content_type,
                            )

                    text_baked_in = False  # Build 6R-C1: deterministic renderer owns campaign text
                    output_path = build_variant_slide_output_path(
                        output_root=config.output_root, brand_slug=brand.slug, category_slug=category_slug,
                        campaign_display_id=campaign.display_id, year=now.year, month=now.month,
                        platform_key=render_format_key, language=language, slide_number=idx,
                    )
                    slide_features = [
                        Feature(icon=f.get("icon", ""), title=f.get("title", ""), subtitle=f.get("subtitle", ""))
                        for f in (getattr(slide, "features", None) or [])
                    ]
                    creative_input = SlideCreativeInput(
                        source_image_path=source_path, template_id=config.template_id,
                        platform_key=render_format_key,
                        eyebrow="" if text_baked_in else getattr(slide, "eyebrow", ""),
                        headline="" if text_baked_in else slide.headline,
                        body="" if text_baked_in else getattr(slide, "body", ""),
                        cta="" if text_baked_in else (getattr(slide, "cta", "") or campaign_cta),
                        brand_colors=brand_colors, logo_path=logo_path,
                        accent_color=brand_style.accent_color, text_color=brand_style.text_color,
                        font_family=brand_style.primary_font,
                        generated_background=generated_background, recreated_image=recreated_image,
                        badge_text="" if text_baked_in else getattr(slide, "badge_text", ""),
                        intro="" if text_baked_in else getattr(slide, "intro", ""),
                        features=[] if text_baked_in else slide_features,
                        callout_label="" if text_baked_in else getattr(slide, "callout_label", ""),
                        callout_value="" if text_baked_in else getattr(slide, "callout_value", ""),
                        bottom_features=[] if text_baked_in else list(getattr(slide, "bottom_features", None) or []),
                        trust_badges=[] if text_baked_in else list(getattr(slide, "trust_badges", None) or []),
                        disclaimer="" if text_baked_in else brand_style.disclaimer_text,
                        slide_number=idx, total_slides=len(slides),
                        campaign_archetype=(
                            creative_direction.campaign_archetype
                        ),
                        slide_role=getattr(
                            slide,
                            "purpose",
                            "",
                        ),
                                         direction_palette=list(creative_direction.palette or brand_style.palette or []),
                                         secondary_font_family=brand_style.secondary_font,
                                         typography_direction=creative_direction.typography_direction,
                                         headline_emphasis=creative_direction.headline_emphasis,
                                         cta_treatment=creative_direction.cta_treatment,
                                         hero_treatment=creative_direction.hero_treatment,
                                         visual_style=creative_direction.visual_style,
                                         mood=creative_direction.mood,
                                         negative_space=creative_direction.negative_space,
                    )
                    masked_scene_applied = await _apply_masked_scene_edit_if_enabled(
                        config=config,
                        image_provider=image_provider,
                        creative_input=creative_input,
                    )

                    if masked_scene_applied:
                        _record_masked_scene_usage(
                            db,
                            campaign_id=campaign.id,
                            image_provider=image_provider,
                            platform=platform,
                            content_type=content_type,
                        )
                    result = await render_slide(creative_input, output_path=output_path, renderer=renderer)
                    from .creative.pipeline import persist_render_context as _persist_render_context
                    _persist_render_context(
                        slide_output_path=result.output_path,
                        creative_direction=creative_direction.model_dump(),
                        visual_base=(recreated_image if recreated_image is not None else generated_background),
                        visual_base_kind=(
                            "recreated_image"
                            if recreated_image is not None
                            else "generated_background"
                            if generated_background is not None
                            else "none"
                        ),
                        product_zone_detection=None,
                        slide_role=getattr(slide, "purpose", ""),
                    )
                    slide_paths.append(str(result.output_path))
                    qa_path = build_variant_qa_report_path(
                        output_root=config.output_root, brand_slug=brand.slug, category_slug=category_slug,
                        campaign_display_id=campaign.display_id, year=now.year, month=now.month,
                        platform_key=render_format_key, language=language, slide_number=idx,
                    )
                    qa_path.parent.mkdir(parents=True, exist_ok=True)
                    qa_path.write_text(json.dumps(result.qa.to_dict(), indent=2))
                    qa_paths.append(str(qa_path))

                db.add(PlatformCampaignVariant(
                    campaign_id=campaign.id, target_platform=platform, language=language,
                    content_type=content_type, render_format_key=render_format_key,
                    status="RENDERED" if slide_paths else "FAILED",
                    slide_asset_paths=slide_paths, copy_language=language,
                    creative_direction=last_direction.model_dump() if slide_paths else {},
                    qa_report_paths=qa_paths, shared_scene_source=",".join(shared_source_parts),
                    notes="" if slide_paths else "No slide in this variant had a readable source photo.",
                ))
                db.commit()
                if slide_paths:
                    rendered_count += 1
            except Exception as exc:  # noqa: BLE001 - one variant's failure must never fail the whole Visuals stage
                db.rollback()
                db.add(PlatformCampaignVariant(
                    campaign_id=campaign.id, target_platform=platform, language=language,
                    content_type=content_type, render_format_key=spec.render_format_key,
                    status="FAILED", notes=f"{type(exc).__name__}: {exc}"[:500],
                ))
                db.commit()

    return rendered_count


def get_platform_campaign_variants(db: Session, campaign_id: str) -> list[PlatformCampaignVariant]:
    """Public read-only accessor (mirrors `get_campaign_copy`'s naming/visibility
    convention) for every `PlatformCampaignVariant` a campaign has — used by
    `GET /api/campaigns/{id}/variants`.
    """
    return (
        db.query(PlatformCampaignVariant)
        .filter(PlatformCampaignVariant.campaign_id == campaign_id)
        .order_by(PlatformCampaignVariant.target_platform, PlatformCampaignVariant.language)
        .all()
    )


async def run_autopilot(
    db: Session,
    *,
    campaign_id: str,
    ai_provider: AIProvider,
    research_provider: ResearchProvider,
    renderer: PlaywrightRenderer,
    config: AutopilotConfig,
    progress: ProgressReporter | None = None,
    image_provider: ImageProvider | None = None,
) -> Campaign:
    """"Everything" mode: runs Strategy, then Copy, then Visuals back to back — the
    original one-click "Run Autopilot" behavior, now implemented as the three
    advanced-mode stages above run in sequence rather than one monolithic function.
    Behavior is unchanged from before the split (same end-to-end result, same
    failure points, same audit trail); only the internals were decomposed so each
    stage can also run standalone via `POST /api/campaigns/{id}/generate/
    {strategy,copy,visuals}` for the Campaign Builder advanced-mode UI.

    `image_provider` is passed straight through to `run_visuals_stage` — see that
    function's docstring for `config.recreate_with_ai`/`config.use_ai_background`.
    Leaving it `None` (the default) keeps every existing caller's behavior
    byte-for-byte unchanged.

    `ai_provider` (already required above for research/strategy/copy) is also
    passed straight through to `run_visuals_stage` for `config.detect_product_zone`
    — Autopilot always has this provider on hand, so opting into per-photo zone
    detection here costs nothing extra to wire up.
    """
    progress = progress or _NullProgress()
    await run_strategy_stage(
        db, campaign_id=campaign_id, ai_provider=ai_provider, research_provider=research_provider,
        config=config, progress=_ScaledProgress(progress, 0, 45),
    )
    await run_copy_stage(
        db, campaign_id=campaign_id, ai_provider=ai_provider, config=config,
        progress=_ScaledProgress(progress, 45, 65),
    )
    return await run_visuals_stage(
        db, campaign_id=campaign_id, renderer=renderer, config=config,
        progress=_ScaledProgress(progress, 65, 100), image_provider=image_provider,
        ai_provider=ai_provider,
    )


class SlidePlanFallback:
    """Used only if the model returns an empty slide list despite being asked for
    at least one — keeps the pipeline from crashing on that edge case by falling
    back to a single hero slide built from the campaign copy directly.
    """

    def __init__(self, *, headline: str, body: str, cta: str):
        self.purpose = "hero"
        self.eyebrow = ""
        self.headline = headline
        self.body = body
        self.cta = cta
        self.visual_brief = "Hero product shot"
# =====================================================================
# BUILD6R_STRATEGY_GENERATION_CONTAINMENT_V3_5
#
# Zero-cost deterministic containment helpers. The V3.5 runtime inserts one
# call to _build6r_v35_enforce_strategy_containment inside the existing
# run_strategy_stage immediately before the sealed strategy-candidate
# grounding/persistence boundary. It deliberately does NOT redefine
# run_strategy_stage.
# =====================================================================


def _build6r_v35_strategy_value_strings(
    value,
    path="strategy",
):
    items = []

    if isinstance(value, str):
        items.append(
            (path, value)
        )
        return items

    if isinstance(value, dict):
        for key, child in value.items():
            items.extend(
                _build6r_v35_strategy_value_strings(
                    child,
                    path + "." + str(key),
                )
            )
        return items

    if isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            items.extend(
                _build6r_v35_strategy_value_strings(
                    child,
                    path + "[" + str(index) + "]",
                )
            )

    return items


def _build6r_v35_strategy_containment_failures(
    strategy_payload,
    verified,
):
    from . import claims_audit as _build6r_v35_claims_audit

    inspect_suffixes = (
        ".angle",
        ".key_message",
        ".reason_this_should_work",
        ".insight",
    )

    failures = []

    for path, text in _build6r_v35_strategy_value_strings(
        strategy_payload
    ):
        if not (
            path.endswith(inspect_suffixes)
            or ".research_basis[" in path
        ):
            continue

        if _build6r_v35_claims_audit._build6r_v35_strategy_product_fact_violation(
            text,
            verified,
        ):
            failures.append(
                path + ": " + text
            )

    return failures


def _build6r_v35_enforce_strategy_containment(
    db,
    *,
    campaign,
    accepted,
    verified,
):
    strategy_payload = (
        accepted.model_dump()
        if hasattr(accepted, "model_dump")
        else accepted
    )

    failures = _build6r_v37_strategy_containment_failures(
        strategy_payload,
        verified,
    )

    if not failures:
        return []

    campaign.status = "FAILED"

    _audit(
        db,
        campaign.id,
        "strategy_candidate_claim_grounding_failed",
        {
            "phase": "post_strategy_pre_copy",
            "hard_fail_count": len(failures),
            "hard_fails": failures,
            "zero_cost_containment": True,
        },
    )

    db.commit()

    raise PreVisualClaimGroundingError(
        "PREVISUAL_UNSUPPORTED_STRATEGY_CLAIM: "
        + " | ".join(
            failures[:8]
        )
    )
# =====================================================================
# BUILD6R_STRATEGY_GENERATION_GROUNDING_V3_6
#
# Prompt-only prevention layer. V3.5 deterministic containment remains the
# fail-closed backstop. This helper adds no provider/network path.
# =====================================================================


def _build6r_v36_strategy_generation_grounding_instruction() -> str:
    return (
        " STRATEGY-GENERATION GROUNDING HARD STOP: "
        "Before writing any strategy candidate, separate creative context from factual assertions. "
        "Research, trends, audience hypotheses, geography, category, retailer/store identity, "
        "strategy-library metadata, and cultural observations may influence creative direction only; "
        "they are not evidence for product origin, retail presence, pharmacy presence, market prevalence, "
        "consumer behavior, cultural norms, popularity, brand-role claims, or product-specific effects. "
        "Do not say or imply that a product is Japanese, from Japan, representative of Japanese routines, "
        "seen on Japanese shelves, sold in Japanese pharmacies, commonly encountered in a market, "
        "viewed a certain way by many people, or associated with a consumer behavior unless that exact "
        "claim is explicitly verified. "
        "Do not turn research phrasing such as 'people see', 'people do not know', 'curiosity around "
        "Japanese routines', or similar audience/cultural observations into a factual premise. "
        "research_basis may describe research only as creative context; it must not convert research into "
        "product-fact evidence or an asserted cultural, retail, market, consumer-behavior, or brand-role fact. "
        "MIXED-FIELD HARD STOP: every factual clause inside insight, angle, key_message, "
        "reason_this_should_work, and research_basis must be independently supported. If one clause is "
        "unsupported, rewrite the whole field using only verified identity, package, ingredient, free-from, "
        "material, and usage atoms plus non-factual creative framing. Never preserve an unsupported premise "
        "merely because other clauses in the same field are verified. "
    )
# =====================================================================
# BUILD6R_FIELD_AWARE_STRATEGY_SEMANTICS_V3_7
#
# Field-aware deterministic evidence isolation. The sealed V3.5 canonical
# product-fact validator remains unchanged and is reused for actual product
# assertions. Research context and non-factual rationale are not automatically
# treated as product facts, while consumer/market/provenance/product assertions
# remain fail-closed.
# =====================================================================


def _build6r_v37_normalized_strategy_text(text):
    from . import claims_audit as _build6r_v37_claims_audit

    return _build6r_v37_claims_audit._build6r_semantic_normalize(
        text
    )


def _build6r_v37_explicit_research_context_allowed(
    path,
    text,
):
    if ".research_basis[" not in str(path):
        return False

    normalized = _build6r_v37_normalized_strategy_text(
        text
    )

    if not normalized:
        return False

    research_markers = (
        "mencoes a",
        "mencoes de",
        "conteudos de skincare",
        "conteudos sobre skincare",
        "pesquisa indica",
        "pesquisas indicam",
        "dados indicam",
        "observacoes de pesquisa",
        "research indicates",
        "research mentions",
        "trend data",
    )

    if not any(
        marker in normalized
        for marker in research_markers
    ):
        return False

    direct_product_attribution = (
        "lululun",
        "hydra ex",
        "este produto",
        "esse produto",
        "o produto",
        "esta mascara",
        "essa mascara",
        "a mascara",
        "a formula",
        "o pouch",
        "7 sheets",
        "7 folhas",
        "150 ml",
        "melty feel sheet",
    )

    return not any(
        marker in normalized
        for marker in direct_product_attribution
    )


def _build6r_v37_unscoped_context_violation(
    path,
    text,
):
    normalized = _build6r_v37_normalized_strategy_text(
        text
    )

    if not normalized:
        return False

    provenance_markers = (
        "no rotulo",
        "do rotulo",
        "pelo rotulo",
        "listado no rotulo",
        "listados no rotulo",
        "escrito no rotulo",
        "na propria embalagem",
        "na embalagem",
        "da embalagem",
        "escrito na embalagem",
        "o que esta escrito na propria embalagem",
    )

    consumer_market_markers = (
        "muita gente",
        "todo mundo",
        "consumidores",
        "clientes costumam",
        "pessoas costumam",
        "quem busca informacao",
        "quem busca informacao objetiva",
        "trava quando",
        "desperta curiosidade",
        "gera curiosidade",
        "podem gerar curiosidade",
        "reforca autoridade",
        "reforca confianca",
        "atende quem",
    )

    origin_retail_popularity_markers = (
        "sheet mask japonesa",
        "mascara japonesa",
        "produto japones",
        "do japao",
        "no japao",
        "prateleiras japonesas",
        "farmacias japonesas",
        "bestseller",
        "mais vendido",
        "viral",
        "popularidade",
        "uso frequente",
    )

    return any(
        marker in normalized
        for marker in (
            provenance_markers
            + consumer_market_markers
            + origin_retail_popularity_markers
        )
    )


def _build6r_v37_strategy_field_violation(
    path,
    text,
    verified,
):
    from . import claims_audit as _build6r_v37_claims_audit

    if not str(text or "").strip():
        return False

    if _build6r_v37_explicit_research_context_allowed(
        path,
        text,
    ):
        return False

    if _build6r_v37_unscoped_context_violation(
        path,
        text,
    ):
        return True

    return _build6r_v37_claims_audit._build6r_v35_strategy_product_fact_violation(
        text,
        verified,
    )


def _build6r_v37_strategy_containment_failures(
    strategy_payload,
    verified,
):
    inspect_suffixes = (
        ".angle",
        ".key_message",
        ".reason_this_should_work",
        ".insight",
    )

    failures = []

    for path, text in _build6r_v35_strategy_value_strings(
        strategy_payload
    ):
        if not (
            path.endswith(inspect_suffixes)
            or ".research_basis[" in path
        ):
            continue

        if _build6r_v37_strategy_field_violation(
            path,
            text,
            verified,
        ):
            failures.append(
                path + ": " + text
            )

    return failures
# =====================================================================
# BUILD6R_GROUNDING_AWARE_STRATEGY_CANDIDATE_FILTER_V3_8
#
# Reuse sealed V3.7 field-aware containment semantics to filter
# unsupported already-generated candidates before the existing novelty
# ranking loop. No model, research, image, network, database, or provider
# call occurs here.
# =====================================================================


def _build6r_v38_filter_grounded_strategy_candidates(
    candidates,
    verified,
):
    grounded_candidates = []
    grounding_rejections = []

    for index, candidate in enumerate(candidates):
        payload = (
            candidate.model_dump()
            if hasattr(candidate, "model_dump")
            else candidate
        )

        failures = _build6r_v37_strategy_containment_failures(
            payload,
            verified,
        )

        if failures:
            grounding_rejections.append(
                (index, tuple(failures))
            )
            continue

        grounded_candidates.append(candidate)

    return grounded_candidates, grounding_rejections
# =====================================================================
# BUILD6R_FIELD_SPECIFIC_STRATEGY_GENERATION_CONTRACT_V3_9
#
# Prompt-only hardening for the existing single strategy generation call.
# This helper performs no model, network, database, image, or provider work.
# Validation remains owned by sealed V3.5-V3.8 runtime gates.
# =====================================================================


def _build6r_v39_field_specific_strategy_generation_contract() -> str:
    return (
        "\n\nFIELD-SPECIFIC STRATEGY OUTPUT CONTRACT (MANDATORY): "
        "Apply these rules independently to every candidate before emitting JSON. "

        "INSIGHT FIELD: Treat insight as a non-factual creative premise, not an empirical "
        "claim about consumers, beginners, audiences, markets, categories, culture, or geography. "
        "Do not say or imply 'many people', 'people often', 'beginners often', 'consumers think', "
        "'the audience sees', 'the market shows', or equivalent consumer behavior or market behavior. "
        "Research about people or markets may stay only in research_basis as explicitly external "
        "context; do not convert it into a declarative insight. "

        "ANGLE FIELD: Describe only the creative treatment or content structure. Do not turn the "
        "angle into a new product fact, benefit, provenance claim, manufacturer communication claim, "
        "market claim, retailer/shelf claim, cultural claim, or interpretation of what the product "
        "format supposedly means. Do not claim 'the label says', 'the package says', 'the manufacturer "
        "focuses on', 'LuLuLun materials emphasize', or similar provenance unless that exact proposition "
        "is present in VERIFIED PRODUCT FACTS. "

        "KEY_MESSAGE FIELD: Every factual product atom must be directly supported by VERIFIED PRODUCT "
        "FACTS and must preserve the verified meaning. Do not add interpretive product assertions. "
        "Verified ingredients, size, free-from facts, usage, or sheet description do not by themselves "
        "show, prove, demonstrate, imply, or establish that the product is more technical, carefully "
        "designed, structured, suitable, effective, premium, easier, better, or otherwise superior. "
        "Do not simplify or rename a technical ingredient into a different factual claim. "

        "REASON_THIS_SHOULD_WORK FIELD: State only hypothetical creative rationale or design intent. "
        "Use language such as 'designed to explain', 'intended to organize', or 'could make the verified "
        "facts easier to scan'. Do not assert actual audience reaction, consumer response, authority, "
        "trust, credibility, curiosity, conversion, understanding, or perception as a fact or expected "
        "outcome. Do not state that the public or audience will think, feel, understand, trust, or see "
        "the product differently. "

        "RESEARCH_BASIS FIELD: Research is explicitly external creative context only and is never "
        "product evidence. If populated, phrase each item as 'External research context: ...'. "
        "Do not assert facts about this product, its manufacturer communication, LuLuLun materials, "
        "package/label wording, Japanese shelves, retailer presence, popularity, efficacy, provenance, "
        "or availability unless the exact product proposition is independently present in VERIFIED "
        "PRODUCT FACTS. If a research statement cannot be kept clearly external, omit it. "

        "CONSERVATIVE FALLBACK CANDIDATE: Among the 2-3 candidates, at least one candidate MUST be a "
        "conservative fallback candidate. Its insight must be a neutral non-factual creative premise; "
        "its angle must be a simple educational or visual treatment; its key_message must use only "
        "canonical VERIFIED PRODUCT FACTS without interpretation; its reason_this_should_work must be "
        "hypothetical creative intent only; and its research_basis should be empty unless an explicitly "
        "external research-context item is genuinely necessary. The fallback must remain useful even "
        "if every market, consumer, cultural, retailer, popularity, and provenance assumption is removed. "

        "FINAL SELF-CHECK: Before emitting the candidates, inspect every sentence and factual clause. "
        "If a clause is not supported by canonical VERIFIED PRODUCT FACTS, is not clearly non-factual "
        "creative rationale, and is not explicitly external research context in research_basis, rewrite "
        "or delete it. Never use research_basis to justify a product claim. Never trade grounding for "
        "punchier copy. "
    )
# =====================================================================
# BUILD6R_DETERMINISTIC_CANONICAL_STRATEGY_FALLBACK_V3_10
#
# Zero-cost local fallback used only when every model-generated strategy
# candidate is rejected by the sealed V3.8 grounding filter.
#
# V3.10 repair v2 deliberately does NOT inject raw canonical fact strings
# into strategy fields. Canonical source presence is required, but the
# strategy itself stays non-factual/generic so it cannot mutate or
# re-phrase verified product facts before downstream grounded generation.
# The fallback is then revalidated by the same sealed V3.8/V3.7 path.
# =====================================================================


def _build6r_v310_deterministic_canonical_strategy_fallback(
    candidates,
    verified,
):
    if not candidates:
        raise PreVisualClaimGroundingError(
            "PREVISUAL_DETERMINISTIC_FALLBACK_NO_TEMPLATE_CANDIDATE"
        )

    if verified is None:
        raise PreVisualClaimGroundingError(
            "PREVISUAL_DETERMINISTIC_FALLBACK_NO_SAFE_CANONICAL_FACTS"
        )

    canonical_values = [
        getattr(verified, "verified_description", ""),
        getattr(verified, "verified_usage", ""),
        getattr(verified, "verified_size", ""),
        getattr(verified, "verified_variant", ""),
        getattr(verified, "verified_features", []),
        getattr(verified, "verified_claims", []),
        getattr(verified, "verified_ingredients", []),
    ]

    def contains_text(value):
        if isinstance(value, (list, tuple)):
            return any(
                str(item or "").strip()
                for item in value
            )

        return bool(str(value or "").strip())

    if not any(
        contains_text(value)
        for value in canonical_values
    ):
        raise PreVisualClaimGroundingError(
            "PREVISUAL_DETERMINISTIC_FALLBACK_NO_SAFE_CANONICAL_FACTS"
        )

    updates = {
        "insight": (
            "Organizar a narrativa visual usando apenas informacoes verificadas."
        ),
        "angle": (
            "Tratamento visual educativo e simples, sem adicionar alegacoes "
            "alem do que foi verificado."
        ),
        "key_message": (
            "Apresentar somente informacoes verificadas do produto, "
            "sem extrapolacao."
        ),
        "reason_this_should_work": (
            "Estrutura criada para manter a comunicacao clara e limitada "
            "ao que foi verificado."
        ),
        "research_basis": [],
    }

    template = candidates[0]

    if hasattr(template, "model_copy"):
        return template.model_copy(update=updates)

    if hasattr(template, "copy"):
        try:
            return template.copy(update=updates)
        except TypeError:
            pass

    if hasattr(template, "model_dump"):
        payload = template.model_dump()
    elif hasattr(template, "dict"):
        payload = template.dict()
    else:
        payload = dict(vars(template))

    payload.update(updates)
    return type(template)(**payload)
