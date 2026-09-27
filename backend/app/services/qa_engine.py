"""Build 3 — MARKETING OS: PLATFORM + LANGUAGE AWARE MULTIMODAL QA.

Evaluates every already-rendered `PlatformCampaignVariant` (Build 2) for
visual quality, brand quality, product fidelity, language quality, and
platform fit, then applies ONE targeted, minimal revision when something
fails — never a blind full-campaign regeneration. New module (not appended to
the already-large `services/orchestrator.py`) — imports one-directionally
FROM `orchestrator.py` (renderer/background/creative-direction/candidate-
asset helpers), never the reverse, so there is no import cycle and Build 1/2's
own tested code paths stay completely untouched by this build.

Four QA surfaces (`schemas/qa.py` has the full contract for each):

- Part A, `run_technical_qa` — purely deterministic: dimensions, valid file,
  aspect ratio, safe zones, text overflow, logo presence, export correctness,
  platform format correctness. No AI, always runs.
- Part B, `run_creative_qa` — the multimodal structured critic (`AIProvider.
  critique_creative`), scored across every visual/brand/product/copy-fit
  dimension the spec named. AI-optional: `None` with no `ai_provider`, never
  a fabricated scorecard.
- Part C, `run_language_qa` (AI) + `detect_identical_copy_across_languages`
  (deterministic) — language hard-fails on the real copy text a variant uses.
- Carry-forward requirement 3 + Part L, `run_video_qa` — format-appropriate
  QA for a script-only, video-oriented variant; never static-image visual QA
  applied to a video concept, and never a claim of video-visual fidelity
  since no video file is ever rendered.

Part D (`detect_platform_hard_fails`) is deterministic, reusing the same
`PlatformCreativeSpec` Build 2 already resolves per variant.

`run_qa_stage` is the orchestration entry point — an independently callable
stage (mirrors Build 1's Strategy/Copy/Visuals split), gated behind
`AutopilotConfig.enable_qa_stage` (default `False`, never auto-wired into
`run_autopilot`) so no existing Build 1/2 test is affected by this build at
all unless it explicitly opts in.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from PIL import Image
from sqlalchemy.orm import Session

from .ai.base import AIProvider, ImageProvider
from .claims_audit import (
    CLAIM_AUDIT_VERSION, audit_text_fields, augment_with_ai_extraction, collect_campaign_copy_fields,
    collect_carousel_slide_fields, collect_video_concept_fields, format_claims_hard_fails,
)
from .creative.brand_style import resolve_brand_style
from .creative.pipeline import (
    SlideCreativeInput, build_variant_qa_report_path, build_variant_slide_output_path, render_slide,
)
from .creative.qa import CreativeQAResult as MechanicalQAResult
from .creative.renderer import PlaywrightRenderer
from .creative.templates import Feature, get_platform_format
from .product_facts import format_verified_facts_for_prompt, resolve_verified_product_facts
from .prompt_registry import record_prompt_usage
from .usage_tracking import record_stage_usage
from ..data.platform_creative_specs import PlatformCreativeSpec, resolve_platform_creative_spec
from ..models import Campaign, PlatformCampaignVariant, Product
from ..schemas.creative_director import CreativeDirection, MasterCampaignConcept, PlatformAdaptation, VideoConcept
from ..schemas.qa import CreativeCritiqueResult, LanguageQAResult, RevisedCopy, TechnicalQAResult, VideoQAResult
from .orchestrator import (
    AutopilotConfig, _audit, _claims_boundary_instruction, _deterministic_creative_direction, _enforce_previsual_claim_grounding_gate, _sparse_fact_grounding_instruction,
    _load_campaign_context, _load_stage_json, _resolve_image_model_and_quality, _resolve_platform_adaptation,
    _select_candidate_assets, _stage_language_variant, generate_ai_background, get_platform_campaign_variants,
    resolve_brand_colors, resolve_brand_logo_path,
)

QA_PROMPT_VERSION = "1.0.0"
QA_RUBRIC_VERSION = "1.0.0"
REVISION_PROMPT_VERSION = "1.0.0"

# Anything at or above this many characters is long enough that two languages
# matching exactly is implausible coincidence rather than a short, generic
# phrase (e.g. "Shop now") both languages might legitimately share.
_IDENTICAL_TEXT_MIN_LENGTH = 8


# ---------------------------------------------------------------------------
# Part A — Technical QA (deterministic, no AI).
# ---------------------------------------------------------------------------

def run_technical_qa(variant: PlatformCampaignVariant, spec: PlatformCreativeSpec) -> TechnicalQAResult:
    """Dimensions, valid file, aspect ratio, safe zones, text overflow, logo
    presence, export correctness, platform format correctness — for the
    variant's rendered slide(s) as a whole. Reuses the per-slide mechanical
    `CreativeQAResult` reports `services/creative/qa.py` already wrote at
    render time (`variant.qa_report_paths`) for the text-overflow/logo checks
    rather than re-deriving them, and adds the platform-structural checks
    Build 2 never had a reason to make (slide-count-vs-carousel-support,
    cover-required, exact dimensions against the variant's OWN spec).
    """
    issues: list[str] = []
    checks: dict[str, bool] = {}

    if not variant.slide_asset_paths:
        checks["has_rendered_assets"] = False
        issues.append("No rendered slide assets to check.")
        return TechnicalQAResult(passed=False, issues=issues, checks=checks)
    checks["has_rendered_assets"] = True

    for i, p in enumerate(variant.slide_asset_paths, start=1):
        path = Path(p)
        if not path.exists():
            checks[f"slide_{i}_file_exists"] = False
            issues.append(f"Slide {i} asset file is missing: {p}")
            continue
        try:
            with Image.open(path) as img:
                img.load()
                actual_size = img.size
                actual_format = img.format
        except Exception as exc:  # noqa: BLE001 - report as a QA issue, never crash the QA pass
            checks[f"slide_{i}_valid_image"] = False
            issues.append(f"Slide {i} could not be read back as a valid image: {exc}")
            continue
        checks[f"slide_{i}_valid_image"] = True
        checks[f"slide_{i}_format_png"] = actual_format == "PNG"
        if actual_format != "PNG":
            issues.append(f"Slide {i} expected PNG output, got {actual_format}.")
        if spec.width and spec.height:
            dims_ok = actual_size == (spec.width, spec.height)
            checks[f"slide_{i}_platform_format_correct"] = dims_ok
            if not dims_ok:
                issues.append(
                    f"Slide {i} is {actual_size[0]}x{actual_size[1]}px, expected "
                    f"{spec.width}x{spec.height}px for {spec.platform}/{spec.content_type}."
                )

    slide_count = len(variant.slide_asset_paths)
    if not spec.supports_carousel and slide_count > 1:
        checks["slide_count_within_platform_support"] = False
        issues.append(
            f"{spec.platform} content type {spec.content_type!r} does not support a carousel, but "
            f"{slide_count} slides were rendered — exceeds this platform's constraints."
        )
    else:
        checks["slide_count_within_platform_support"] = True

    checks["cover_present"] = not spec.cover_required or slide_count >= 1
    if spec.cover_required and slide_count < 1:
        issues.append("A cover frame is required for this content type but none was rendered.")

    for i, qp in enumerate(variant.qa_report_paths or [], start=1):
        qpath = Path(qp)
        if not qpath.exists():
            continue
        try:
            data = json.loads(qpath.read_text())
        except Exception:  # noqa: BLE001 - a corrupt/missing evidence file is a QA gap, not a crash
            continue
        if not data.get("passed", True):
            checks[f"slide_{i}_mechanical_qa"] = False
            issues.extend(f"Slide {i}: {issue}" for issue in data.get("issues", []))
        else:
            checks[f"slide_{i}_mechanical_qa"] = True

    return TechnicalQAResult(passed=len(issues) == 0, issues=issues, checks=checks)


# ---------------------------------------------------------------------------
# Part D — platform hard fails (deterministic).
# ---------------------------------------------------------------------------

def detect_platform_hard_fails(variant: PlatformCampaignVariant, spec: PlatformCreativeSpec) -> list[str]:
    """Wrong aspect ratio, wrong content type, unsafe crop (caught via exact-
    dimensions above), TikTok output incorrectly represented as a generated
    video, required cover missing, carousel exceeds platform constraints.
    Deterministic and always run — these are structural facts about the
    variant's own render vs. its own `PlatformCreativeSpec`, not a judgment
    call an AI needs to make.
    """
    fails: list[str] = []
    if not spec.supports_static:
        if variant.slide_asset_paths:
            fails.append(
                "platform_hard_fail: a video-oriented content type was incorrectly rendered as a static image."
            )
        if variant.video_concept and variant.video_concept.get("is_rendered_video"):
            fails.append(
                "platform_hard_fail: short-video output incorrectly represented as a generated video file."
            )
        return fails

    for i, p in enumerate(variant.slide_asset_paths, start=1):
        path = Path(p)
        if not path.exists():
            fails.append(f"platform_hard_fail: slide {i} asset is missing — content is unusable on this platform.")
            continue
        if spec.width and spec.height:
            try:
                with Image.open(path) as img:
                    if img.size != (spec.width, spec.height):
                        fails.append(
                            f"platform_hard_fail: slide {i} is {img.size[0]}x{img.size[1]}px, wrong aspect "
                            f"ratio/size for {spec.platform}."
                        )
            except Exception:  # noqa: BLE001 - unreadable file is itself a hard fail, not a crash
                fails.append(f"platform_hard_fail: slide {i} is unreadable — content is unusable on this platform.")

    slide_count = len(variant.slide_asset_paths)
    if not spec.supports_carousel and slide_count > 1:
        fails.append("platform_hard_fail: carousel exceeds platform constraints (platform does not support carousel).")
    if spec.cover_required and slide_count < 1:
        fails.append("platform_hard_fail: required cover missing.")
    return fails


# ---------------------------------------------------------------------------
# Part C — language QA (deterministic identical-text check + AI critique).
# ---------------------------------------------------------------------------

def detect_identical_copy_across_languages(
    this_text: str, sibling_texts: dict[str, str], *, this_language: str,
) -> list[str]:
    """Deterministic, AI-independent signal for "untranslated text remains":
    if this variant's copy is byte-identical to another targeted language's
    copy for the same slide, that's a real, checkable fact — not a judgment
    call — regardless of whether an AI provider is available to say so. Skips
    short strings (a CTA like "Shop now" can legitimately be identical across
    languages without meaning anything went untranslated).
    """
    fails: list[str] = []
    stripped = (this_text or "").strip()
    if len(stripped) < _IDENTICAL_TEXT_MIN_LENGTH:
        return fails
    for language, text in sibling_texts.items():
        if language == this_language:
            continue
        if (text or "").strip() == stripped:
            fails.append(
                f"language_hard_fail: copy is byte-identical to the {language} variant — likely untranslated."
            )
    return fails


async def run_language_qa(
    ai_provider: AIProvider | None, *, headline: str, body: str, cta: str, language: str, platform: str, model: str,
) -> LanguageQAResult | None:
    """AI-optional judgment of the real copy text a variant uses, against the
    spec's own six hard-fail conditions. Returns `None` (never a fabricated
    score) when no provider is available — the caller still has the
    deterministic identical-text check above regardless.
    """
    if ai_provider is None:
        return None
    try:
        return await ai_provider.generate_structured(
            system=(
                "You are a bilingual (Portuguese/English) copy editor reviewing marketing text for a "
                "specific declared language. Hard-fail (in `hard_fails`, one entry per issue, be specific) "
                "when: the text is not actually written in the declared language; it looks untranslated "
                "(placeholder or source-language text left in); it accidentally mixes Portuguese and English "
                "mid-sentence; its grammar is broken badly enough to damage meaning; it reads as an obvious "
                "literal/machine translation rather than natural phrasing; or it contains spelling corruption. "
                "Score `language_naturalness` 0-100 (100 = reads as if written natively by a skilled copywriter "
                "in this language)."
            ),
            user=(
                f"Declared language: {language}. Platform: {platform}. Headline: {headline!r}. Body: {body!r}. "
                f"CTA: {cta!r}."
            ),
            schema=LanguageQAResult,
            model=model,
        )
    except Exception:  # noqa: BLE001 - best-effort, mirrors every other AI hook in this codebase
        return None


# ---------------------------------------------------------------------------
# Part B — the multimodal creative critic.
# ---------------------------------------------------------------------------

def _build_creative_context(
    *, master_concept: MasterCampaignConcept | None, adaptation: PlatformAdaptation | None,
    creative_direction: CreativeDirection | None, headline: str, body: str, cta: str, language: str,
    platform: str, content_type: str, slide_count: int, verified_facts_text: str, brand_requirements_text: str,
) -> str:
    """Assembles Part B's full input list into one plain-text bundle — every
    piece named by the spec (VerifiedProductFacts, brand requirements,
    MasterCampaignConcept, PlatformCampaignVariant fields, CampaignCopy,
    CreativeDirection, locale, platform, carousel context), never invented
    here — each value is either real persisted data or an honest "not
    available" note.
    """
    lines = [
        f"Platform: {platform}. Content type: {content_type}. Locale: {language}.",
        f"Carousel context: {slide_count} slide(s) in this variant.",
    ]
    if master_concept is not None:
        lines.append(
            f"Master campaign concept: {master_concept.concept_name!r} — {master_concept.campaign_promise!r}. "
            f"Key message: {master_concept.key_message!r}. Must include: {master_concept.must_include}. "
            f"Must avoid: {master_concept.must_avoid}."
        )
    if adaptation is not None:
        lines.append(f"Platform adaptation strategy: {adaptation.adaptation_strategy!r}.")
    if creative_direction is not None:
        lines.append(
            f"Creative direction: visual_style={creative_direction.visual_style!r} "
            f"mood={creative_direction.mood!r} composition={creative_direction.composition!r} "
            f"prohibited_elements={creative_direction.prohibited_elements}."
        )
    lines.append(f"On-slide copy — headline: {headline!r}. body: {body!r}. cta: {cta!r}.")
    lines.append(f"Verified product facts: {verified_facts_text or 'none on file'}")
    lines.append(f"Brand requirements: {brand_requirements_text or 'none on file'}")
    return "\n".join(lines)


async def run_creative_qa(
    ai_provider: AIProvider | None, *, image_paths: list[Path], source_image_path: Path | None, context: str,
    model: str,
) -> CreativeCritiqueResult | None:
    """AI-optional wrapper around `AIProvider.critique_creative` — `None`
    (never a fabricated scorecard) with no provider or on a failed call.
    """
    if ai_provider is None or not image_paths:
        return None
    try:
        return await ai_provider.critique_creative(
            image_paths=image_paths, source_image_path=source_image_path, context=context, model=model,
        )
    except Exception:  # noqa: BLE001 - best-effort, mirrors every other AI hook in this codebase
        return None


# ---------------------------------------------------------------------------
# Carry-forward requirement 3 + Part L — video-oriented (format-appropriate) QA.
# ---------------------------------------------------------------------------

async def run_video_qa(
    ai_provider: AIProvider | None, *, video_concept: VideoConcept, platform: str, language: str,
    master_concept: MasterCampaignConcept | None, model: str, cover_image_path: Path | None = None,
) -> VideoQAResult | None:
    """Format-appropriate QA for a script-only variant — judges the
    structured hook/script/shot-list/timing/on-screen-text text itself, never
    applies static-image visual QA to it, and never claims video-visual
    fidelity since this app renders no video file. `cover_image_path` is
    accepted for forward-compatibility (Part L's "cover_creative_quality when
    a cover image exists") but this app's architecture never produces one
    yet, so the caller always passes `None` today — `cover_creative_quality`
    then stays honestly unset rather than scored against nothing.
    """
    if ai_provider is None:
        return None
    try:
        return await ai_provider.generate_structured(
            system=(
                "You are reviewing a SHORT-FORM VIDEO CONCEPT — a structured hook/script/shot-list/on-screen-"
                "text/caption written for a human production team to film. You are NOT reviewing a rendered "
                "video file (none exists) — never claim to judge visual fidelity, footage quality, or actual "
                "on-screen visuals; judge only the text itself: does the hook grab attention, is the script "
                "coherent, is the shot list complete enough to film from, is the timing realistic, is the "
                "on-screen text suitable, does it fit the platform and read naturally in the declared language, "
                "is it factually grounded in the campaign context given (no invented claims), does it stay on "
                "brand, and is the CTA effective. Score every dimension 0-100."
            ),
            user=(
                f"Platform: {platform}. Language: {language}. Hook: {video_concept.hook!r}. Script: "
                f"{video_concept.script!r}. Shot list: {video_concept.shot_list}. Timing: "
                f"{video_concept.timing!r}. On-screen text: {video_concept.on_screen_text}. Caption: "
                f"{video_concept.caption!r}."
                + (
                    f" Master concept: {master_concept.concept_name!r} — {master_concept.campaign_promise!r}."
                    if master_concept is not None else ""
                )
            ),
            schema=VideoQAResult,
            model=model,
        )
    except Exception:  # noqa: BLE001 - best-effort, mirrors every other AI hook in this codebase
        return None


# ---------------------------------------------------------------------------
# Part E — targeted revision. Each function fixes ONE variant's ONE thing —
# never a blind full-campaign regeneration, and never touches the shared
# CampaignOutput rows another platform/language reads from.
# ---------------------------------------------------------------------------

async def revise_copy_for_variant(
    ai_provider: AIProvider | None, *, headline: str, body: str, cta: str, issues: list[str], language: str,
    platform: str, model: str,
verified_facts_note: str = "") -> RevisedCopy | None:
    """"English headline too long -> revise English copy only" / "Portuguese
    copy unnatural -> revise PT-BR copy only" (Part E's own examples). Text-
    only and cheap — never touches the AI-generated scene. `None` (never a
    fabricated rewrite) with no AI provider; the caller then has nothing
    better to fall back to than leaving the copy unchanged.
    """
    if ai_provider is None:
        return None
    try:
        return await ai_provider.generate_structured(
            system=(
                (("You are revising ONLY this one platform+language variant's marketing copy to fix specific "
                "QA issues named below — never invent a new claim, statistic, or product detail not already "
                "present in the current copy. Keep the same core message and CTA intent; fix only what the "
                "issues name (e.g. shorten an overlong headline, fix unnatural phrasing, remove mixed-language "
                f"text). {_claims_boundary_instruction()}") + _sparse_fact_grounding_instruction())
            ),
            user=(
                ((f"Current headline: {headline!r}. Current body: {body!r}. Current CTA: {cta!r}. Language: "
                f"{language}. Platform: {platform}. Issues to fix: {issues}.") + (("\n" + verified_facts_note) if verified_facts_note else ""))
            ),
            schema=RevisedCopy,
            model=model,
        )
    except Exception:  # noqa: BLE001 - best-effort, mirrors every other AI hook in this codebase
        return None


async def revise_creative_direction_for_variant(
    ai_provider: AIProvider | None,
    *,
    previous_direction: CreativeDirection,
    issues: list[str],
    master_concept: MasterCampaignConcept | None,
    adaptation: PlatformAdaptation,
    platform: str,
    language: str,
    content_type: str,
    slide_role: str,
    model: str,
    fallback: CreativeDirection,
verified_facts_note: str = "") -> CreativeDirection:
    """Revise one variant without abandoning its master creative strategy.

    Build 6R-B2 treats product/category context, campaign archetype and
    visual-story system as continuity constraints during QA repair.
    """

    if (
        ai_provider is None
        or master_concept is None
    ):
        return fallback

    try:
        return await ai_provider.generate_structured(
            system=(
                ((("You are revising the visual direction for ONE marketing "
                "slide to fix specific QA issues. Preserve the SAME master "
                "campaign idea, product/category context, campaign archetype "
                "and visual story system. Do not invent a new campaign. "
                "Do not fix weak visual execution by collapsing the slide "
                "into generic luxury, black/gold, neon, cyber, nightclub, "
                "pedestal, clinical or cosmetics styling. Preserve real "
                "product identity and do not invent factual claims.") + _sparse_fact_grounding_instruction() + " " + _claims_boundary_instruction()))
            ),
            user=(
                ((f"Previous visual style: "
                f"{previous_direction.visual_style!r}. "
                f"Previous mood: "
                f"{previous_direction.mood!r}. "
                f"Previous composition: "
                f"{previous_direction.composition!r}. "
                f"Previous background: "
                f"{previous_direction.background_concept!r}. "
                f"Issues to fix: {issues}. "
                f"Master concept: "
                f"{master_concept.concept_name!r} ? "
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
                f"{adaptation.adaptation_strategy!r}. "
                f"Language: {language}. "
                f"Content type: {content_type}. "
                f"Slide role: "
                f"{slide_role or 'not specified'}.") + (("\n" + verified_facts_note) if verified_facts_note else ""))
            ),
            schema=CreativeDirection,
            model=model,
        )

    except Exception:  # noqa: BLE001
        return fallback


async def revise_video_concept(
    ai_provider: AIProvider | None, *, previous: VideoConcept, issues: list[str],
    master_concept: MasterCampaignConcept | None, platform: str, language: str, adaptation: PlatformAdaptation,
    model: str,
) -> VideoConcept | None:
    """Video-concept counterpart to the two revisions above — fixes the
    structured script in response to specific QA issues without inventing a
    new concept. `None` (keep the previous script unchanged) with no AI
    provider or a failed call.
    """
    if ai_provider is None:
        return None
    try:
        return await ai_provider.generate_structured(
            system=(
                "You are REVISING a short-form video concept (hook/script/shot-list/on-screen-text/caption) "
                "to fix specific QA issues named below, staying grounded in the same master campaign concept "
                "and platform adaptation strategy — do not invent a new concept, fix only what the issues name. "
                f"{_claims_boundary_instruction()}"
            ),
            user=(
                f"Previous hook: {previous.hook!r}. Previous script: {previous.script!r}. Issues to fix: "
                f"{issues}. Platform: {platform}. Language: {language}. Adaptation strategy: "
                f"{adaptation.adaptation_strategy!r}."
                + (
                    f" Master concept: {master_concept.concept_name!r} — {master_concept.campaign_promise!r}."
                    if master_concept is not None else ""
                )
            ),
            schema=VideoConcept,
            model=model,
        )
    except Exception:  # noqa: BLE001 - best-effort, mirrors every other AI hook in this codebase
        return None


def _planned_slides_for_variant(creative_data_raw: dict | None, language: str, spec: PlatformCreativeSpec) -> list:
    creative_variant = _stage_language_variant(creative_data_raw, language) or {}
    planned = [SimpleNamespace(**s) for s in creative_variant.get("carousel_plan", {}).get("slides", [])]
    if not spec.supports_carousel:
        planned = planned[: max(1, spec.recommended_slide_count)]
    return planned


def _slide_assets_for_variant(
    db: Session, *, campaign: Campaign, brand, is_discovery: bool, discovery_products: list, planned_slides: list,
) -> list:
    from .product_asset_selection import select_render_assets as _select_render_assets

    if is_discovery:
        assets = []
        for idx, dp in enumerate(discovery_products):
            if idx >= len(planned_slides):
                break
            per_product = _select_render_assets(
                db, brand_id=brand.id, category_id=None, product_id=dp.product_id, limit=1,
            )
            asset = per_product[0] if per_product else None
            if asset is not None and Path(asset.absolute_path).exists():
                assets.append(asset)
        return assets
    candidate_assets = _select_render_assets(
        db, brand_id=brand.id, category_id=campaign.category_id, product_id=campaign.product_id,
        limit=max(4, len(planned_slides) * 2),
    )
    if not candidate_assets:
        return []
    return [candidate_assets[(i - 1) % len(candidate_assets)] for i in range(1, len(planned_slides) + 1)]


async def _regenerate_variant_render(
    db: Session, *, variant: PlatformCampaignVariant, campaign: Campaign, brand, category_slug: str,
    config: AutopilotConfig, renderer: PlaywrightRenderer, image_provider: ImageProvider | None,
    quality_image_model: str, quality_tier: str, spec: PlatformCreativeSpec, creative_data_raw: dict | None,
    discovery_products: list, is_discovery: bool, brand_colors, logo_path, brand_style,
    creative_direction: CreativeDirection | None, copy_override: RevisedCopy | None, now: datetime,
    regenerate_visual_base: bool = False,
) -> tuple[list[str], list[str]]:
    """Re-render one variant without silently losing its visual identity.

    Copy/language/overflow/platform retries reuse each slide's persisted
    text-free visual base, CreativeDirection and ProductZoneDetection.

    Only a genuine creative-direction revision may explicitly request a new
    visual base by setting regenerate_visual_base=True.
    """
    from .creative.pipeline import (
        load_render_context,
        load_render_visual_base,
        persist_render_context,
    )
    from ..schemas.ai import ProductZoneDetection

    language = variant.language

    planned_slides = _planned_slides_for_variant(
        creative_data_raw,
        language,
        spec,
    )

    if not planned_slides:
        return [], []

    slide_assets = _slide_assets_for_variant(
        db,
        campaign=campaign,
        brand=brand,
        is_discovery=is_discovery,
        discovery_products=discovery_products,
        planned_slides=planned_slides,
    )

    if not slide_assets:
        return [], []

    render_format_key = (
        spec.render_format_key
        or config.platform_key
    )

    fmt = get_platform_format(
        render_format_key
    )

    copy_variant = (
        _stage_language_variant(
            _load_stage_json(
                db,
                campaign.id,
                "copy",
            ),
            language,
        )
        or {}
    )

    campaign_cta = (
        copy_variant.get(
            "cta"
        )
        or campaign.cta
    )

    if (
        regenerate_visual_base
        and creative_direction is None
    ):
        raise RuntimeError(
            "Visual-base regeneration requires "
            "a CreativeDirection."
        )

    fresh_generated_background = None

    if (
        regenerate_visual_base
        and creative_direction is not None
        and config.use_ai_background
        and image_provider is not None
    ):
        fresh_generated_background = await generate_ai_background(
            db,
            image_provider=image_provider,
            brand=brand,
            model=quality_image_model,
            width=fmt.width,
            height=fmt.height,
            visual_brief=getattr(
                planned_slides[0],
                "visual_brief",
                "",
            ),
            quality=quality_tier,
            creative_direction=creative_direction,
        )

        if fresh_generated_background is None:
            raise RuntimeError(
                "Creative-direction revision requested "
                "a fresh AI background but generation failed."
            )

    variant_direction = None

    if (
        isinstance(
            variant.creative_direction,
            dict,
        )
        and variant.creative_direction
    ):
        variant_direction = CreativeDirection(
            **variant.creative_direction
        )

    slide_paths: list[str] = []
    qa_paths: list[str] = []

    attempt_tag = (
        "revision-"
        + uuid.uuid4().hex[:8]
    )

    for idx, slide in enumerate(
        planned_slides,
        start=1,
    ):
        if idx > len(
            slide_assets
        ):
            break

        asset = slide_assets[
            idx - 1
        ]

        source_path = Path(
            asset.absolute_path
        )

        if not source_path.exists():
            continue

        current_paths = list(
            variant.slide_asset_paths
            or []
        )

        existing_slide_path = (
            Path(
                current_paths[
                    idx - 1
                ]
            )
            if idx <= len(
                current_paths
            )
            else None
        )

        render_context = (
            load_render_context(
                existing_slide_path
            )
            if existing_slide_path is not None
            else None
        )

        if (
            not regenerate_visual_base
            and existing_slide_path is not None
            and render_context is None
            and (
                config.use_ai_background
                or config.recreate_with_ai
                or config.detect_product_zone
            )
        ):
            raise RuntimeError(
                "Render context is missing for an AI-touched "
                "variant; refusing to degrade the QA rerender."
            )

        context_direction = None
        zone_detection = None

        if render_context is not None:
            direction_payload = render_context.get(
                "creative_direction"
            )

            if direction_payload:
                if not isinstance(
                    direction_payload,
                    dict,
                ):
                    raise RuntimeError(
                        "Persisted CreativeDirection is invalid."
                    )

                context_direction = CreativeDirection(
                    **direction_payload
                )

            zone_payload = render_context.get(
                "product_zone_detection"
            )

            if zone_payload is not None:
                if not isinstance(
                    zone_payload,
                    dict,
                ):
                    raise RuntimeError(
                        "Persisted ProductZoneDetection is invalid."
                    )

                zone_detection = ProductZoneDetection(
                    **zone_payload
                )

        generated_background = None
        recreated_image = None
        visual_base_kind = "none"

        if regenerate_visual_base:
            effective_direction = (
                creative_direction
                or context_direction
                or variant_direction
            )

            generated_background = (
                fresh_generated_background
            )

            if generated_background is not None:
                visual_base_kind = (
                    "generated_background"
                )

        else:
            effective_direction = (
                context_direction
                or creative_direction
                or variant_direction
            )

            if existing_slide_path is not None:
                (
                    persisted_base,
                    persisted_kind,
                    _,
                ) = load_render_visual_base(
                    existing_slide_path
                )

                if (
                    persisted_kind
                    == "generated_background"
                ):
                    generated_background = (
                        persisted_base
                    )

                    visual_base_kind = (
                        persisted_kind
                    )

                elif (
                    persisted_kind
                    == "recreated_image"
                ):
                    recreated_image = (
                        persisted_base
                    )

                    visual_base_kind = (
                        persisted_kind
                    )

        headline = slide.headline

        body = getattr(
            slide,
            "body",
            "",
        )

        cta = (
            getattr(
                slide,
                "cta",
                "",
            )
            or campaign_cta
        )

        if (
            copy_override is not None
            and idx == 1
        ):
            headline = (
                copy_override.headline
            )

            body = (
                copy_override.body
            )

            cta = (
                copy_override.cta
            )

        slide_features = [
            Feature(
                icon=f.get(
                    "icon",
                    "",
                ),
                title=f.get(
                    "title",
                    "",
                ),
                subtitle=f.get(
                    "subtitle",
                    "",
                ),
            )
            for f in (
                getattr(
                    slide,
                    "features",
                    None,
                )
                or []
            )
        ]

        direction_palette = (
            list(
                effective_direction.palette
                or brand_style.palette
                or []
            )
            if effective_direction is not None
            else list(
                brand_style.palette
                or []
            )
        )

        creative_input = SlideCreativeInput(
            source_image_path=source_path,
            template_id=config.template_id,
            platform_key=render_format_key,
            eyebrow=getattr(
                slide,
                "eyebrow",
                "",
            ),
            headline=headline,
            body=body,
            cta=cta,
            brand_colors=brand_colors,
            logo_path=logo_path,
            accent_color=brand_style.accent_color,
            text_color=brand_style.text_color,
            font_family=brand_style.primary_font,
            generated_background=generated_background,
            product_zone_detection=zone_detection,
            recreated_image=recreated_image,
            badge_text=getattr(
                slide,
                "badge_text",
                "",
            ),
            intro=getattr(
                slide,
                "intro",
                "",
            ),
            features=slide_features,
            callout_label=getattr(
                slide,
                "callout_label",
                "",
            ),
            callout_value=getattr(
                slide,
                "callout_value",
                "",
            ),
            bottom_features=list(
                getattr(
                    slide,
                    "bottom_features",
                    None,
                )
                or []
            ),
            trust_badges=list(
                getattr(
                    slide,
                    "trust_badges",
                    None,
                )
                or []
            ),
            disclaimer=brand_style.disclaimer_text,
            slide_number=idx,
            total_slides=len(
                planned_slides
            ),
            campaign_archetype=(
                effective_direction.campaign_archetype
                if effective_direction is not None
                else ""
            ),
            slide_role=getattr(
                slide,
                "purpose",
                "",
            ),
            direction_palette=direction_palette,
            secondary_font_family=brand_style.secondary_font,
            typography_direction=(
                effective_direction.typography_direction
                if effective_direction is not None
                else ""
            ),
            headline_emphasis=(
                effective_direction.headline_emphasis
                if effective_direction is not None
                else ""
            ),
            cta_treatment=(
                effective_direction.cta_treatment
                if effective_direction is not None
                else ""
            ),
            hero_treatment=(
                effective_direction.hero_treatment
                if effective_direction is not None
                else ""
            ),
            visual_style=(
                effective_direction.visual_style
                if effective_direction is not None
                else ""
            ),
            mood=(
                effective_direction.mood
                if effective_direction is not None
                else ""
            ),
            negative_space=(
                effective_direction.negative_space
                if effective_direction is not None
                else ""
            ),
        )

        output_path = build_variant_slide_output_path(
            output_root=config.output_root,
            brand_slug=brand.slug,
            category_slug=category_slug,
            campaign_display_id=campaign.display_id,
            year=now.year,
            month=now.month,
            platform_key=(
                f"{render_format_key}__{attempt_tag}"
            ),
            language=language,
            slide_number=idx,
        )

        result = await render_slide(
            creative_input,
            output_path=output_path,
            renderer=renderer,
        )

        persist_render_context(
            slide_output_path=result.output_path,
            creative_direction=(
                effective_direction.model_dump()
                if effective_direction is not None
                else {}
            ),
            visual_base=(
                recreated_image
                if recreated_image is not None
                else generated_background
            ),
            visual_base_kind=visual_base_kind,
            product_zone_detection=zone_detection,
            slide_role=getattr(
                slide,
                "purpose",
                "",
            ),
        )

        slide_paths.append(
            str(
                result.output_path
            )
        )

        qa_path = build_variant_qa_report_path(
            output_root=config.output_root,
            brand_slug=brand.slug,
            category_slug=category_slug,
            campaign_display_id=campaign.display_id,
            year=now.year,
            month=now.month,
            platform_key=(
                f"{render_format_key}__{attempt_tag}"
            ),
            language=language,
            slide_number=idx,
        )

        qa_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        qa_path.write_text(
            json.dumps(
                result.qa.to_dict(),
                indent=2,
            )
        )

        qa_paths.append(
            str(
                qa_path
            )
        )

    return slide_paths, qa_paths


async def _regenerate_with_best_of_n(
    db: Session, *, variant: PlatformCampaignVariant, campaign: Campaign, brand, category_slug: str,
    config: AutopilotConfig, renderer: PlaywrightRenderer, image_provider: ImageProvider | None,
    ai_provider: AIProvider | None, quality_image_model: str, quality_tier: str, spec: PlatformCreativeSpec,
    creative_data_raw: dict | None, discovery_products: list, is_discovery: bool, brand_colors, logo_path,
    brand_style, creative_direction: CreativeDirection | None, copy_override: RevisedCopy | None, now: datetime,
    scoring_context: str,
) -> tuple[list[str], list[str]]:
    """Render creative-direction candidates and keep the best candidate only."""
    from .creative.pipeline import (
        build_render_context_path,
        build_render_visual_base_path,
    )

    n = (
        max(
            1,
            config.qa_best_of_n,
        )
        if creative_direction is not None
        else 1
    )

    candidates: list[
        tuple[
            list[str],
            list[str],
            CreativeCritiqueResult | None,
        ]
    ] = []

    for _ in range(
        n
    ):
        paths, qa_paths = await _regenerate_variant_render(
            db,
            variant=variant,
            campaign=campaign,
            brand=brand,
            category_slug=category_slug,
            config=config,
            renderer=renderer,
            image_provider=image_provider,
            quality_image_model=quality_image_model,
            quality_tier=quality_tier,
            spec=spec,
            creative_data_raw=creative_data_raw,
            discovery_products=discovery_products,
            is_discovery=is_discovery,
            brand_colors=brand_colors,
            logo_path=logo_path,
            brand_style=brand_style,
            creative_direction=creative_direction,
            copy_override=copy_override,
            now=now,
            regenerate_visual_base=True,
        )

        if not paths:
            continue

        score = None

        if (
            ai_provider is not None
            and n > 1
        ):
            score = await run_creative_qa(
                ai_provider,
                image_paths=[
                    Path(
                        path
                    )
                    for path in paths
                ],
                source_image_path=None,
                context=scoring_context,
                model=config.creative_qa_model,
            )

        candidates.append(
            (
                paths,
                qa_paths,
                score,
            )
        )

    if not candidates:
        return [], []

    scored = [
        candidate
        for candidate in candidates
        if candidate[2] is not None
    ]

    best = (
        max(
            scored,
            key=lambda candidate:
            candidate[2].overall_quality,
        )
        if scored
        else candidates[0]
    )

    for paths, qa_paths, _ in candidates:
        if paths is best[0]:
            continue

        for path_value in paths:
            slide_path = Path(
                path_value
            )

            slide_path.unlink(
                missing_ok=True
            )

            build_render_context_path(
                slide_path
            ).unlink(
                missing_ok=True
            )

            build_render_visual_base_path(
                slide_path
            ).unlink(
                missing_ok=True
            )

        for qa_path_value in qa_paths:
            Path(
                qa_path_value
            ).unlink(
                missing_ok=True
            )

    return best[0], best[1]


def _write_qa_evidence(
    config: AutopilotConfig, *, campaign: Campaign, variant: PlatformCampaignVariant, attempt: int, payload: dict,
) -> Path:
    """Test 11 / Part F: "QA evidence stored per platform/language variant" —
    one JSON file per attempt, never overwritten, so a human reviewer can see
    exactly what every retry round found.
    """
    path = (
        config.output_root / "qa_evidence" / campaign.display_id / variant.target_platform / variant.language
        / f"attempt-{attempt:02d}.json"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str))
    return path


def _hash_slide_files(paths: list[str]) -> tuple[str, ...]:
    """SHA256 of each rendered slide's actual bytes, in file order — the exact
    same signal the owner's own live-acceptance review used (a manual SHA256
    dedup across the zip) to discover that 27 of 54 rendered PNGs were
    byte-for-byte duplicates produced by "successful" revision rounds that
    changed nothing (Build 6 repair, Critical Defect 3). Comparing this
    tuple before and after a revision attempt is what lets the QA loop below
    tell a revision that genuinely changed the artifact from one that just
    re-spent a render (or an AI call) to reproduce the same pixels. A missing/
    unreadable file hashes to "" rather than raising, so a partial/failed
    render still compares (as different, since "" != a real hash) instead of
    crashing the QA loop.
    """
    hashes: list[str] = []
    for p in paths:
        try:
            hashes.append(hashlib.sha256(Path(p).read_bytes()).hexdigest())
        except OSError:
            hashes.append("")
    return tuple(hashes)


# Build 6 repair (Critical Defect 4/9): per-density word budgets used to fix a
# text-overflow hard fail WITHOUT any AI call or scene regeneration. Text
# overflow (`services/creative/qa.py`'s "Text content overflowed its safe-
# margin box" check) is a purely mechanical fact about rendered DOM
# measurements, not a creative judgment — so the fix is mechanical too:
# shorten the copy to fit the platform's own already-known
# `PlatformCreativeSpec.max_copy_density`, then re-render with the SAME
# `creative_direction=None` and the SAME source assets. This is deliberately
# NOT a rewrite/paraphrase (which would need an AI call and could drift the
# meaning) — pure word-boundary truncation, so nothing new is invented and
# the copy's claims are unchanged, only its length. Matches Requirement 8's
# "route deterministic problems deterministically... do not immediately
# regenerate expensive AI backgrounds/scenes."
_COPY_DENSITY_WORD_BUDGETS: dict[str, dict[str, int]] = {
    "low": {"headline": 6, "body": 14, "cta": 4},
    "medium": {"headline": 9, "body": 22, "cta": 5},
    "high": {"headline": 12, "body": 32, "cta": 6},
}


def _truncate_to_words(text: str, max_words: int) -> str:
    """Word-boundary truncation only — never a paraphrase. A no-op when the
    text already fits, so a genuinely short overflow cause (e.g. a single
    very long unbroken word, or a template/density mismatch) is left honestly
    unresolved for the QA loop to keep surfacing rather than silently
    "fixed" by cutting words that were never the actual problem.
    """
    text = (text or "").strip()
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]).rstrip(",.;:-")


def _deterministic_shorten_copy(
    *, headline: str, body: str, cta: str, spec: PlatformCreativeSpec,
) -> RevisedCopy:
    """Mechanical, no-AI copy shortening keyed off the platform's own
    already-known copy-density budget. Used as the FIRST response to a
    detected text-overflow hard fail, ahead of a bare re-render or any
    creative-direction/scene regeneration — see the text_overflow_issue
    branch in `_qa_one_static_variant`.
    """
    budgets = _COPY_DENSITY_WORD_BUDGETS.get(spec.max_copy_density, _COPY_DENSITY_WORD_BUDGETS["medium"])
    return RevisedCopy(
        headline=_truncate_to_words(headline, budgets["headline"]),
        body=_truncate_to_words(body, budgets["body"]),
        cta=_truncate_to_words(cta, budgets["cta"]),
    )


def _creative_overall_and_fails(
    technical: TechnicalQAResult, platform_fails: list[str], language_fails: list[str],
    creative: CreativeCritiqueResult | None,
) -> tuple[int, list[str]]:
    hard_fails = list(platform_fails) + list(language_fails)
    if not technical.passed:
        hard_fails.append(f"technical_hard_fail: {'; '.join(technical.issues) or 'technical QA failed'}")
    if creative is not None:
        hard_fails.extend(creative.hard_fails)
        overall = creative.overall_quality
    else:
        # No AI provider available to score creative quality — never fabricate
        # a number. A variant with no hard fails at all still needs a human
        # look before PASS, so this deliberately scores below any sane
        # threshold rather than defaulting to a false "0 is bad, passes
        # anyway" middle ground.
        overall = 0
    return overall, hard_fails


def _video_overall_score(result: VideoQAResult) -> int:
    dimensions = [
        result.hook_strength, result.script_coherence, result.shot_list_completeness, result.timing_score,
        result.on_screen_text_suitability, result.platform_fit, result.language_naturalness,
        result.factual_accuracy, result.brand_alignment, result.cta_effectiveness,
    ]
    if result.cover_creative_quality is not None:
        dimensions.append(result.cover_creative_quality)
    return round(sum(dimensions) / len(dimensions)) if dimensions else 0


# ---------------------------------------------------------------------------
# Part H / top-level orchestration — ties every QA surface above together.
# ---------------------------------------------------------------------------

async def _qa_one_static_variant(
    db: Session, *, variant: PlatformCampaignVariant, campaign: Campaign, brand, category_slug: str,
    spec: PlatformCreativeSpec, master_concept: MasterCampaignConcept | None, adaptation: PlatformAdaptation,
    config: AutopilotConfig, renderer: PlaywrightRenderer, image_provider: ImageProvider | None,
    ai_provider: AIProvider | None, quality_image_model: str, quality_tier: str, copy_data_raw: dict | None,
    creative_data_raw: dict | None, discovery_products: list, is_discovery: bool, brand_colors, logo_path,
    brand_style, sibling_headlines: dict[str, str], sibling_bodies: dict[str, str], sibling_ctas: dict[str, str],
    now: datetime, product: Product | None = None,
) -> None:
    """Carry-forward requirement 2: every field written below lands on THIS
    variant row, never only aggregated onto the parent Campaign — "Instagram/
    pt-BR = PASS, Instagram/en = NEEDS_REVIEW, Pinterest/en = PASS" stays
    exactly representable, because each call to this function only ever
    mutates its own one `variant`.

    Part E's own four worked examples set the revision priority order used
    below: a language hard-fail (an overlong headline, unnatural PT-BR copy)
    always gets a cheap, targeted COPY-ONLY revision first; failing that, a
    platform/technical hard-fail (wrong aspect ratio, a corrupt/missing file)
    gets a bare RE-RENDER with no copy or creative-direction change at all
    ("Pinterest aspect problem -> rerender Pinterest variant" — neither copy
    nor the scene caused that problem, so neither is touched); only once
    neither of those applies does a genuinely weak/wrong-feeling CREATIVE
    issue get a full creative-direction revision ("Instagram visual weak ->
    revise Instagram CreativeDirection only"), optionally Best-of-N (Part G)
    when `config.qa_best_of_n > 1`. When no AI provider is available at all
    (`creative` stays `None`), `_creative_overall_and_fails` already scores
    `overall_quality = 0` rather than a false pass — that variant simply
    settles at `NEEDS_REVIEW` once retries are exhausted, exactly as
    intended, rather than looping forever trying to "fix" a scorecard no
    provider can ever produce.
    """
    language = variant.language
    platform = variant.target_platform
    copy_data = _stage_language_variant(copy_data_raw, language) or {}
    headline = copy_data.get("headline", "")
    body = copy_data.get("body", "")
    cta = copy_data.get("cta", "") or campaign.cta or ""

    creative_direction: CreativeDirection | None = None
    if variant.creative_direction:
        try:
            creative_direction = CreativeDirection(**variant.creative_direction)
        except Exception:  # noqa: BLE001 - a malformed/legacy stored direction just means "none on file"
            creative_direction = None

    copy_override: RevisedCopy | None = None
    max_attempts = max(1, config.qa_max_retries + 1)
    # BUILD 6 FINAL REPAIR: resolved once per variant (not per attempt) since
    # `VerifiedProductFacts`/brand evidence don't change across QA retries —
    # `None` when this is a discovery campaign with no single `product` on
    # file, in which case the audit below simply has no evidence class A.
    verified_facts = resolve_verified_product_facts(db, product) if product is not None else None
    verified_facts_note = (
        format_verified_facts_for_prompt(verified_facts)
        if verified_facts is not None
        else ""
    )

    # BUILD 6R / Stage 3D: the visual critic must judge the
    # rendered creative against the same canonical brand/product
    # evidence already available to the pipeline.
    brand_requirement_parts: list[str] = []
    for field_name in (
        "voice",
        "colors",
        "typography",
        "spacing",
        "visual_style",
        "forbidden_styles",
        "campaign_rules",
        "creative_instructions",
        "preferred_ctas",
        "disallowed_terms",
        "disclaimers",
    ):
        value = getattr(brand, field_name, None)
        if value is None:
            continue

        rendered = str(value).strip()

        if rendered in ("", "{}", "[]", "null"):
            continue

        brand_requirement_parts.append(
            f"{field_name}={rendered}"
        )

    brand_requirements_note = "; ".join(
        brand_requirement_parts
    )

    source_product_image_path: Path | None = None

    if product is not None:
        source_candidates = _select_candidate_assets(
            db,
            brand_id=brand.id,
            category_id=campaign.category_id,
            product_id=product.id,
            limit=1,
        )

        if source_candidates:
            candidate_absolute_path = getattr(
                source_candidates[0],
                "absolute_path",
                None,
            )

            if candidate_absolute_path:
                candidate_path = Path(
                    candidate_absolute_path
                )

                if candidate_path.is_file():
                    source_product_image_path = candidate_path

    for attempt in range(1, max_attempts + 1):
        technical = run_technical_qa(variant, spec)
        platform_fails = detect_platform_hard_fails(variant, spec)
        language_fails = (
            detect_identical_copy_across_languages(headline, sibling_headlines, this_language=language)
            + detect_identical_copy_across_languages(body, sibling_bodies, this_language=language)
        )
        language_qa = await run_language_qa(
            ai_provider, headline=headline, body=body, cta=cta, language=language, platform=platform,
            model=config.creative_qa_model,
        )
        record_prompt_usage(
            db, campaign_id=campaign.id, purpose="language_qa_critique", language=language, platform=platform,
            extra={"rubric_version": QA_RUBRIC_VERSION, "model_role": "creative_qa_model", "variant_id": variant.id},
        )
        record_stage_usage(
            db, campaign_id=campaign.id, operation="language_qa_critique", providers=[ai_provider],
            platform=platform, language=language, content_type=variant.content_type,
        )
        if language_qa is not None:
            language_fails.extend(language_qa.hard_fails)

        image_paths = [Path(p) for p in variant.slide_asset_paths if Path(p).exists()]
        scoring_context = _build_creative_context(
            master_concept=master_concept, adaptation=adaptation, creative_direction=creative_direction,
            headline=headline, body=body, cta=cta, language=language, platform=platform,
            content_type=variant.content_type, slide_count=len(image_paths),
            verified_facts_text=verified_facts_note, brand_requirements_text=brand_requirements_note,
        )
        creative = await run_creative_qa(
            ai_provider, image_paths=image_paths, source_image_path=source_product_image_path, context=scoring_context,
            model=config.creative_qa_model,
        )
        record_prompt_usage(
            db, campaign_id=campaign.id, purpose="creative_qa_critique", language=language, platform=platform,
            extra={"rubric_version": QA_RUBRIC_VERSION, "model_role": "creative_qa_model", "variant_id": variant.id},
        )
        record_stage_usage(
            db, campaign_id=campaign.id, operation="creative_qa_critique", providers=[ai_provider],
            platform=platform, language=language, content_type=variant.content_type,
        )

        # BUILD 6 FINAL REPAIR: the real, code-enforced unsupported-claim gate
        # (see `services/claims_audit.py`'s module docstring for the exact
        # pre-repair defect this replaces). Inspects the actual USER-VISIBLE
        # text this attempt would ship — CampaignCopy fields plus every
        # carousel slide field named in REQUIREMENT 1 — never rendered file
        # paths. Layer 1 (deterministic) always runs; layer 2 (AI candidate
        # extraction) only adds recall and is skipped for free with no
        # `ai_provider`, but the gate itself is never weaker without one.
        planned_slides = _planned_slides_for_variant(creative_data_raw, language, spec)
        claims_fields = {
            **collect_campaign_copy_fields(copy_data),
            **collect_carousel_slide_fields(planned_slides),
        }
        claims_result = audit_text_fields(claims_fields, verified_facts, brand)
        claims_result = await augment_with_ai_extraction(
            ai_provider, fields=claims_fields, verified=verified_facts, brand=brand,
            model=config.creative_qa_model, existing=claims_result,
        )
        record_prompt_usage(
            db, campaign_id=campaign.id, purpose="claims_audit_extraction", language=language, platform=platform,
            extra={"rubric_version": CLAIM_AUDIT_VERSION, "model_role": "creative_qa_model", "variant_id": variant.id},
        )
        record_stage_usage(
            db, campaign_id=campaign.id, operation="claims_audit_extraction", providers=[ai_provider],
            platform=platform, language=language, content_type=variant.content_type,
        )
        claims_hard_fails = format_claims_hard_fails(claims_result)

        overall, hard_fails = _creative_overall_and_fails(technical, platform_fails, language_fails, creative)
        hard_fails = hard_fails + claims_hard_fails
        # Fail closed (REQUIREMENT 5): an unsupported claim can never receive
        # PASS regardless of how high `overall` scores otherwise.
        passed = not hard_fails and overall >= config.qa_pass_threshold

        payload = {
            "attempt": attempt, "overall": overall, "hard_fails": hard_fails, "passed": passed,
            "technical": technical.to_dict(),
            "creative": creative.model_dump() if creative is not None else None,
            "language": language_qa.model_dump() if language_qa is not None else None,
            "claims_audit": claims_result.model_dump(),
        }
        evidence_path = _write_qa_evidence(config, campaign=campaign, variant=variant, attempt=attempt, payload=payload)

        variant.qa_scores = {
            "overall": overall, "technical": technical.to_dict(),
            "creative": creative.model_dump() if creative is not None else None,
            "language": language_qa.model_dump() if language_qa is not None else None,
            "claims_audit": claims_result.model_dump(),
        }
        variant.qa_hard_fails = hard_fails
        variant.qa_attempts = attempt
        variant.qa_evidence_paths = list(variant.qa_evidence_paths or []) + [str(evidence_path)]
        variant.qa_versions = {
            "qa_prompt_version": QA_PROMPT_VERSION, "qa_rubric_version": QA_RUBRIC_VERSION,
            "revision_prompt_version": REVISION_PROMPT_VERSION if not passed and attempt < max_attempts else "",
        }

        if passed:
            variant.qa_status = "PASS"
            variant.qa_notes = ""
            db.commit()
            return
        if attempt == max_attempts:
            variant.qa_status = "NEEDS_REVIEW"
            variant.qa_notes = f"Retry limit ({config.qa_max_retries}) reached without a passing QA result."
            db.commit()
            return

        language_issue = bool(language_fails)
        # BUILD 6 FINAL REPAIR: checked immediately after the language branch
        # and before every other revision category — an unsupported factual
        # claim is a correctness/compliance problem, not a cosmetic one, so it
        # gets the same cheap targeted COPY-ONLY revision the language branch
        # uses (never a bare re-render, which wouldn't touch the offending
        # text at all) before any text-overflow/platform/creative handling.
        claims_issue = not language_issue and bool(claims_hard_fails)
        # Build 6 repair (Critical Defect 4/9): a text-overflow hard fail is a
        # purely mechanical fact about rendered DOM measurements (see
        # `services/creative/qa.py`'s "Text content overflowed its safe-margin
        # box" issue string, folded into `technical.issues` above) — checked
        # BEFORE the generic platform_issue bucket so it gets a deterministic
        # copy-shortening fix instead of a bare re-render (which doesn't touch
        # the copy and would therefore reproduce the identical overflow every
        # attempt) or an expensive creative-direction/scene regeneration.
        text_overflow_issue = not language_issue and not claims_issue and any(
            "overflow" in issue.lower() for issue in technical.issues
        )
        platform_issue = not text_overflow_issue and not claims_issue and (bool(platform_fails) or not technical.passed)
        creative_issue = creative is not None and (bool(creative.hard_fails) or overall < config.qa_pass_threshold)

        # Build 6 repair (Critical Defect 3): hash this variant's currently-
        # persisted render BEFORE this attempt's revision, so the result can
        # be compared against whatever the revision below actually produces —
        # a revision attempt is only ever accepted if it provably changed the
        # rendered bytes.
        pre_revision_hash = _hash_slide_files(list(variant.slide_asset_paths or []))
        revision_kind = "unspecified"

        new_slide_paths: list[str] = []
        new_qa_paths: list[str] = []
        if language_issue:
            revision_kind = "targeted_copy_revision"
            # "English headline too long -> revise English copy/layout only." /
            # "Portuguese copy unnatural -> revise PT-BR copy only." — text-only,
            # never touches the AI-generated scene.
            revised = await revise_copy_for_variant(
                ai_provider, headline=headline, body=body, cta=cta, issues=language_fails, language=language,
                platform=platform, model=config.creative_qa_model,
            verified_facts_note=verified_facts_note)
            record_prompt_usage(
                db, campaign_id=campaign.id, purpose="targeted_copy_revision", language=language, platform=platform,
                extra={"rubric_version": QA_RUBRIC_VERSION, "model_role": "creative_qa_model", "variant_id": variant.id},
            )
            record_stage_usage(
                db, campaign_id=campaign.id, operation="targeted_copy_revision", providers=[ai_provider],
                platform=platform, language=language, content_type=variant.content_type,
            )
            if revised is not None:
                headline, body, cta = revised.headline, revised.body, revised.cta
                copy_override = revised
            new_slide_paths, new_qa_paths = await _regenerate_variant_render(
                db, variant=variant, campaign=campaign, brand=brand, category_slug=category_slug, config=config,
                renderer=renderer, image_provider=image_provider, quality_image_model=quality_image_model,
                quality_tier=quality_tier, spec=spec, creative_data_raw=creative_data_raw,
                discovery_products=discovery_products, is_discovery=is_discovery, brand_colors=brand_colors,
                logo_path=logo_path, brand_style=brand_style, creative_direction=None, copy_override=copy_override,
                now=now,
            )
        elif claims_issue:
            # BUILD 6 FINAL REPAIR: reuses the same targeted, text-only,
            # scene-untouched copy revision the language branch uses — its
            # own system prompt already carries `_claims_boundary_
            # instruction()`, the identical preventive boundary this
            # enforcement layer is now backing up with a real post-generation
            # check. Only CampaignCopy's headline/body/cta can be revised
            # this way; an unsupported claim detected in carousel-slide-only
            # fields (badge_text, callout_value, etc.) is not rewritten here,
            # but stays a hard fail every subsequent attempt re-checks — this
            # variant honestly settles at NEEDS_REVIEW rather than a false
            # PASS if it's never actually removed from the slide content.
            revision_kind = "targeted_claims_revision"
            revised = await revise_copy_for_variant(
                ai_provider, headline=headline, body=body, cta=cta, issues=claims_hard_fails, language=language,
                platform=platform, model=config.creative_qa_model,
            verified_facts_note=verified_facts_note)
            record_prompt_usage(
                db, campaign_id=campaign.id, purpose="targeted_claims_revision", language=language, platform=platform,
                extra={"rubric_version": QA_RUBRIC_VERSION, "model_role": "creative_qa_model", "variant_id": variant.id},
            )
            record_stage_usage(
                db, campaign_id=campaign.id, operation="targeted_claims_revision", providers=[ai_provider],
                platform=platform, language=language, content_type=variant.content_type,
            )
            if revised is not None:
                headline, body, cta = revised.headline, revised.body, revised.cta
                copy_override = revised
            new_slide_paths, new_qa_paths = await _regenerate_variant_render(
                db, variant=variant, campaign=campaign, brand=brand, category_slug=category_slug, config=config,
                renderer=renderer, image_provider=image_provider, quality_image_model=quality_image_model,
                quality_tier=quality_tier, spec=spec, creative_data_raw=creative_data_raw,
                discovery_products=discovery_products, is_discovery=is_discovery, brand_colors=brand_colors,
                logo_path=logo_path, brand_style=brand_style, creative_direction=None, copy_override=copy_override,
                now=now,
            )
        elif text_overflow_issue:
            # Build 6 repair (Critical Defect 4/9): deterministic, no-AI copy
            # shortening keyed off this platform's own known copy-density
            # budget — never an AI call, never a new scene. Only touches the
            # first slide's text (mirrors the language-revision branch's own
            # documented scope), which is where a copy-driven overflow is
            # overwhelmingly reported.
            revision_kind = "deterministic_text_overflow_shortening"
            shortened = _deterministic_shorten_copy(headline=headline, body=body, cta=cta, spec=spec)
            headline, body, cta = shortened.headline, shortened.body, shortened.cta
            copy_override = shortened
            new_slide_paths, new_qa_paths = await _regenerate_variant_render(
                db, variant=variant, campaign=campaign, brand=brand, category_slug=category_slug, config=config,
                renderer=renderer, image_provider=image_provider, quality_image_model=quality_image_model,
                quality_tier=quality_tier, spec=spec, creative_data_raw=creative_data_raw,
                discovery_products=discovery_products, is_discovery=is_discovery, brand_colors=brand_colors,
                logo_path=logo_path, brand_style=brand_style, creative_direction=None, copy_override=copy_override,
                now=now,
            )
        elif platform_issue:
            # "Pinterest aspect problem -> rerender Pinterest variant." — a bare
            # re-render; neither the copy nor the scene caused this.
            revision_kind = "platform_rerender"
            new_slide_paths, new_qa_paths = await _regenerate_variant_render(
                db, variant=variant, campaign=campaign, brand=brand, category_slug=category_slug, config=config,
                renderer=renderer, image_provider=image_provider, quality_image_model=quality_image_model,
                quality_tier=quality_tier, spec=spec, creative_data_raw=creative_data_raw,
                discovery_products=discovery_products, is_discovery=is_discovery, brand_colors=brand_colors,
                logo_path=logo_path, brand_style=brand_style, creative_direction=None, copy_override=copy_override,
                now=now,
            )
        elif creative_issue:
            # "Instagram visual weak -> revise Instagram CreativeDirection only."
            revision_kind = "creative_direction_revision"
            fallback_direction = creative_direction or _deterministic_creative_direction(
                master_concept=master_concept, adaptation=adaptation, platform=platform, language=language,
                content_type=variant.content_type, slide_role="", brand_style=brand_style,
            )
            revised_direction = await revise_creative_direction_for_variant(
                ai_provider, previous_direction=fallback_direction, issues=(creative.hard_fails if creative else []),
                master_concept=master_concept, adaptation=adaptation, platform=platform, language=language,
                content_type=variant.content_type, slide_role="", model=config.creative_director_model,
                fallback=fallback_direction,
            verified_facts_note=verified_facts_note)
            _enforce_previsual_claim_grounding_gate(
                db,
                campaign=campaign,
                brand=brand,
                product=product,
                phase=f"qa_creative_direction_revision:{platform}:{language}",
                structures={"creative_direction": {
                    key: item
                    for key, item in revised_direction.model_dump().items()
                    if key not in {"prohibited_elements", "negative_constraints"}
                }},
            )
            record_prompt_usage(
                db, campaign_id=campaign.id, purpose="targeted_creative_direction_revision", language=language,
                platform=platform,
                extra={
                    "rubric_version": QA_RUBRIC_VERSION, "model_role": "creative_director_model",
                    "variant_id": variant.id,
                },
            )
            record_stage_usage(
                db, campaign_id=campaign.id, operation="targeted_creative_direction_revision", providers=[ai_provider],
                platform=platform, language=language, content_type=variant.content_type,
            )
            creative_direction = revised_direction
            new_slide_paths, new_qa_paths = await _regenerate_with_best_of_n(
                db, variant=variant, campaign=campaign, brand=brand, category_slug=category_slug, config=config,
                renderer=renderer, image_provider=image_provider, ai_provider=ai_provider,
                quality_image_model=quality_image_model, quality_tier=quality_tier, spec=spec,
                creative_data_raw=creative_data_raw, discovery_products=discovery_products, is_discovery=is_discovery,
                brand_colors=brand_colors, logo_path=logo_path, brand_style=brand_style,
                creative_direction=creative_direction, copy_override=copy_override, now=now,
                scoring_context=scoring_context,
            )
            variant.creative_direction = creative_direction.model_dump()
        else:
            # A hard fail exists with no clearer category (e.g. no AI provider
            # at all, so `overall=0` forces a retry with nothing concrete to
            # act on) — a bare re-render is the safest minimal action; this is
            # expected to keep failing through every remaining attempt and
            # settle at NEEDS_REVIEW, which is the correct, honest outcome.
            revision_kind = "fallback_rerender"
            new_slide_paths, new_qa_paths = await _regenerate_variant_render(
                db, variant=variant, campaign=campaign, brand=brand, category_slug=category_slug, config=config,
                renderer=renderer, image_provider=image_provider, quality_image_model=quality_image_model,
                quality_tier=quality_tier, spec=spec, creative_data_raw=creative_data_raw,
                discovery_products=discovery_products, is_discovery=is_discovery, brand_colors=brand_colors,
                logo_path=logo_path, brand_style=brand_style, creative_direction=None, copy_override=copy_override,
                now=now,
            )

        if new_slide_paths:
            # Build 6 repair (Critical Defect 3): a revision is only ever
            # accepted if it provably changed the rendered bytes — never
            # counted as a "successful" retry, and never repeated again,
            # when it reproduces the prior artifact byte-for-byte. This is
            # exactly the mechanism the owner's own live-acceptance zip
            # review used (a manual SHA256 dedup) to discover 27 of 54
            # rendered PNGs were wasted duplicate revision rounds.
            post_revision_hash = _hash_slide_files(new_slide_paths)
            if pre_revision_hash and post_revision_hash == pre_revision_hash:
                variant.qa_status = "NEEDS_REVIEW"
                variant.qa_notes = (
                    f"REVISION_NO_EFFECT: the {revision_kind} revision on attempt {attempt} produced a "
                    "byte-identical rendered result — stopping retries rather than repeating an "
                    "already-paid-for, provably ineffective action. Remaining hard fails: "
                    f"{'; '.join(hard_fails) or 'none named'}."
                )
                # The ineffective attempt's own freshly-rendered (but discarded)
                # files are cleaned up rather than left as orphaned duplicates
                # on disk, mirroring `_regenerate_with_best_of_n`'s own
                # losing-candidate cleanup.
                for p in new_slide_paths:
                    if p not in (variant.slide_asset_paths or []):
                        Path(p).unlink(missing_ok=True)
                db.commit()
                return
            variant.slide_asset_paths = new_slide_paths
            variant.qa_report_paths = new_qa_paths
        db.commit()


async def _qa_one_video_variant(
    db: Session, *, variant: PlatformCampaignVariant, campaign: Campaign, master_concept: MasterCampaignConcept | None,
    adaptation: PlatformAdaptation, config: AutopilotConfig, ai_provider: AIProvider | None, now: datetime,
    brand=None, product: Product | None = None,
) -> None:
    """Carry-forward requirement 3: a script-only, video-oriented variant gets
    format-appropriate QA (`run_video_qa`'s structured hook/script/shot-list
    critic) — never the static-image Part A/B checks, since there is no
    rendered image to check, and never a claim of video-visual fidelity since
    this app renders no video file (`is_rendered_video` stays `False`
    throughout).
    """
    language = variant.language
    platform = variant.target_platform
    video_concept = VideoConcept(**variant.video_concept) if variant.video_concept else None
    if video_concept is None:
        variant.qa_status = "NEEDS_REVIEW"
        variant.qa_hard_fails = ["No video concept on file to QA — this variant never produced a script."]
        variant.qa_attempts = (variant.qa_attempts or 0) + 1
        variant.qa_notes = "SCRIPT_UNAVAILABLE — nothing to evaluate."
        db.commit()
        return

    max_attempts = max(1, config.qa_max_retries + 1)
    # BUILD 6 FINAL REPAIR: resolved once per variant, same reasoning as the
    # static-variant loop above.
    verified_facts = resolve_verified_product_facts(db, product) if product is not None else None

    for attempt in range(1, max_attempts + 1):
        result = await run_video_qa(
            ai_provider, video_concept=video_concept, platform=platform, language=language,
            master_concept=master_concept, model=config.creative_qa_model,
        )
        record_prompt_usage(
            db, campaign_id=campaign.id, purpose="video_qa_critique", language=language, platform=platform,
            extra={"rubric_version": QA_RUBRIC_VERSION, "model_role": "creative_qa_model", "variant_id": variant.id},
        )
        record_stage_usage(
            db, campaign_id=campaign.id, operation="video_qa_critique", providers=[ai_provider],
            platform=platform, language=language, content_type=variant.content_type,
        )

        # BUILD 6 FINAL REPAIR: same real enforcement gate as the static-
        # variant loop, applied to this VideoConcept's own visible text
        # (hook, script, on_screen_text, caption) — REQUIREMENT 1's video
        # coverage.
        claims_fields = collect_video_concept_fields(video_concept.model_dump())
        claims_result = audit_text_fields(claims_fields, verified_facts, brand)
        claims_result = await augment_with_ai_extraction(
            ai_provider, fields=claims_fields, verified=verified_facts, brand=brand,
            model=config.creative_qa_model, existing=claims_result,
        )
        record_prompt_usage(
            db, campaign_id=campaign.id, purpose="claims_audit_extraction", language=language, platform=platform,
            extra={"rubric_version": CLAIM_AUDIT_VERSION, "model_role": "creative_qa_model", "variant_id": variant.id},
        )
        record_stage_usage(
            db, campaign_id=campaign.id, operation="claims_audit_extraction", providers=[ai_provider],
            platform=platform, language=language, content_type=variant.content_type,
        )
        claims_hard_fails = format_claims_hard_fails(claims_result)

        hard_fails = (list(result.hard_fails) if result is not None else []) + claims_hard_fails
        overall = _video_overall_score(result) if result is not None else 0
        # Fail closed (REQUIREMENT 5): identical guarantee as the static path.
        passed = result is not None and not hard_fails and overall >= config.qa_pass_threshold

        payload = {
            "attempt": attempt, "overall": overall, "hard_fails": hard_fails, "passed": passed,
            "video_scores": result.model_dump() if result is not None else None, "is_rendered_video": False,
            "claims_audit": claims_result.model_dump(),
        }
        evidence_path = _write_qa_evidence(config, campaign=campaign, variant=variant, attempt=attempt, payload=payload)

        variant.qa_scores = {
            "overall": overall, "video": result.model_dump() if result is not None else None,
            "claims_audit": claims_result.model_dump(),
        }
        variant.qa_hard_fails = hard_fails
        variant.qa_attempts = attempt
        variant.qa_evidence_paths = list(variant.qa_evidence_paths or []) + [str(evidence_path)]
        variant.qa_versions = {
            "qa_prompt_version": QA_PROMPT_VERSION, "qa_rubric_version": QA_RUBRIC_VERSION,
            "revision_prompt_version": REVISION_PROMPT_VERSION if not passed and attempt < max_attempts else "",
        }

        if passed:
            variant.qa_status = "PASS"
            variant.qa_notes = ""
            db.commit()
            return
        if attempt == max_attempts:
            variant.qa_status = "NEEDS_REVIEW"
            variant.qa_notes = "Retry limit reached without a passing video-concept QA result."
            db.commit()
            return

        issues = hard_fails or (result.issues if result is not None else [])
        revised = await revise_video_concept(
            ai_provider, previous=video_concept, issues=issues, master_concept=master_concept, platform=platform,
            language=language, adaptation=adaptation, model=config.platform_adapter_model,
        )
        record_prompt_usage(
            db, campaign_id=campaign.id, purpose="targeted_video_revision", language=language, platform=platform,
            extra={
                "rubric_version": QA_RUBRIC_VERSION, "model_role": "platform_adapter_model", "variant_id": variant.id,
            },
        )
        record_stage_usage(
            db, campaign_id=campaign.id, operation="targeted_video_revision", providers=[ai_provider],
            platform=platform, language=language, content_type=variant.content_type,
        )
        if revised is not None:
            video_concept = revised
            variant.video_concept = revised.model_dump()
        db.commit()


async def run_qa_stage(
    db: Session, *, campaign_id: str, renderer: PlaywrightRenderer, config: AutopilotConfig,
    image_provider: ImageProvider | None = None, ai_provider: AIProvider | None = None,
) -> Campaign:
    """Build 3's top-level QA stage — an independently callable stage
    (mirrors Build 1's Strategy/Copy/Visuals split; `AutopilotConfig.
    enable_qa_stage` only governs whether `run_autopilot` calls this
    automatically, never whether it CAN be called — exactly like Visuals
    itself). Evaluates every already-rendered/scripted `PlatformCampaignVariant`
    Build 2's Visuals stage produced, applying Part A (technical) + Part D
    (platform hard fails) deterministically, always, plus Part B/C (creative
    + language) — or carry-forward requirement 3's format-appropriate video
    QA for a script-only variant — whenever an AI provider is available.

    A variant still `PENDING`/`FAILED`/`SKIPPED_UNSUPPORTED`/
    `SCRIPT_UNAVAILABLE` never produced a real rendered/script result, so
    there is nothing here for QA to evaluate — it's simply skipped, keeping
    `qa_status="PENDING"` (never a fourth meaning bolted onto `status`).

    Guard: requires Visuals to have run first (i.e. at least one
    `PlatformCampaignVariant` row exists) — same "run the prior stage first"
    discipline as every other stage's own guard.
    """
    campaign, brand, category, product = _load_campaign_context(db, campaign_id)
    variants = get_platform_campaign_variants(db, campaign.id)
    if not variants:
        raise ValueError(
            "No platform/language variants found for this campaign — run the Visuals stage (which renders "
            "PlatformCampaignVariant rows) before running QA."
        )

    category_slug = category.slug if category else "general"
    master_concept_data = _load_stage_json(db, campaign.id, "master_concept")
    master_concept = MasterCampaignConcept(**master_concept_data) if master_concept_data else None
    copy_data_raw = _load_stage_json(db, campaign.id, "copy")
    creative_data_raw = _load_stage_json(db, campaign.id, "creative")
    discovery_products = list(campaign.discovery_products)
    is_discovery = campaign.product_id is None and len(discovery_products) > 0

    brand_colors = resolve_brand_colors(brand)
    logo_path = resolve_brand_logo_path(db, brand.id)
    brand_style = resolve_brand_style(db, brand, logo_path=logo_path)
    quality_image_model, quality_tier = _resolve_image_model_and_quality(config)
    now = datetime.now(timezone.utc)

    # Sibling copy text per language (headline/body), for the deterministic
    # "identical to another language" check (Part C) — copy is per-language,
    # not per-platform, so this is computed once for the whole campaign
    # rather than once per variant.
    languages = list(campaign.languages) if campaign.languages else [campaign.language or "pt-BR"]
    sibling_headlines: dict[str, str] = {}
    sibling_bodies: dict[str, str] = {}
    sibling_ctas: dict[str, str] = {}
    for language in languages:
        variant_copy = _stage_language_variant(copy_data_raw, language) or {}
        sibling_headlines[language] = variant_copy.get("headline", "")
        sibling_bodies[language] = variant_copy.get("body", "")
        sibling_ctas[language] = variant_copy.get("cta", "") or campaign.cta or ""

    adaptation_cache: dict[str, PlatformAdaptation] = {}
    evaluated = 0

    for variant in variants:
        if variant.status not in ("RENDERED", "SCRIPT_ONLY"):
            continue  # nothing was actually produced for this combination — no finished asset/script to QA

        if variant.target_platform not in adaptation_cache:
            adaptation_cache[variant.target_platform] = await _resolve_platform_adaptation(
                ai_provider, master_concept=master_concept, platform=variant.target_platform,
                content_type=variant.content_type, model=config.platform_adapter_model,
            )
        adaptation = adaptation_cache[variant.target_platform]

        if variant.status == "SCRIPT_ONLY":
            await _qa_one_video_variant(
                db, variant=variant, campaign=campaign, master_concept=master_concept, adaptation=adaptation,
                config=config, ai_provider=ai_provider, now=now, brand=brand, product=product,
            )
        else:
            spec = resolve_platform_creative_spec(variant.target_platform, variant.content_type)
            await _qa_one_static_variant(
                db, variant=variant, campaign=campaign, brand=brand, category_slug=category_slug, spec=spec,
                master_concept=master_concept, adaptation=adaptation, config=config, renderer=renderer,
                image_provider=image_provider, ai_provider=ai_provider, quality_image_model=quality_image_model,
                quality_tier=quality_tier, copy_data_raw=copy_data_raw, creative_data_raw=creative_data_raw,
                discovery_products=discovery_products, is_discovery=is_discovery, brand_colors=brand_colors,
                logo_path=logo_path, brand_style=brand_style, sibling_headlines=sibling_headlines,
                sibling_bodies=sibling_bodies, sibling_ctas=sibling_ctas, now=now, product=product,
            )
        evaluated += 1

    db.refresh(campaign)
    _audit(db, campaign.id, "qa.completed", {"variants_evaluated": evaluated})
    db.commit()
    return campaign
