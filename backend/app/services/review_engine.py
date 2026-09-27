"""Build 4 — HUMAN APPROVAL + PLATFORM/LANGUAGE FEEDBACK LEARNING.

New module, one-directional dependency on both `orchestrator.py` and
`qa_engine.py` (imports FROM them, never the reverse — same discipline
`qa_engine.py` itself already follows relative to `orchestrator.py`), so
Build 1-3's own tested code paths stay completely untouched by this build.
`feedback_selector.py` is the one piece of Build 4 `orchestrator.py` itself
depends on (for prompt-grounding); this module re-exports it so a caller
never has to know it lives in a separate file.

Three functions carry the whole build:

- `record_review_feedback` — writes ONE `ReviewFeedback` row for a human
  APPROVE/REJECT/REQUEST_REVISION action at whichever level (campaign /
  platform+language variant / individual asset-slide) the owner actually
  reviewed. Snapshots what was reviewed (carry-forward requirement 2), writes
  ONLY `human_review_status` on the reviewed row (never `qa_*` — carry-
  forward requirement 9), and auto-links lineage (carry-forward requirement
  3) via `revision_of_feedback_id`.
- `apply_requested_revision` — the actual mechanics of a REQUEST_REVISION
  action: maps the feedback's `reason_code` to one of Build 3's existing QA-
  engine revision primitives (`data/feedback_reasons.py::revision_kind_for`)
  and invokes it, reusing that tested machinery rather than a second
  from-scratch revision pipeline. Resets the variant's `human_review_status`
  back to `PENDING` once done, since the revised version awaits a fresh
  owner look.
- `select_feedback_examples` / `format_feedback_for_prompt` — re-exported
  from `feedback_selector.py` (see that module for the full design) so
  `services/review_engine` is the one obvious place to import Build 4's
  public surface from.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from ..data.feedback_reasons import revision_kind_for
from ..models import Campaign, PlatformCampaignVariant, ReviewFeedback
from ..schemas.creative_director import CreativeDirection, MasterCampaignConcept, VideoConcept
from ..schemas.qa import RevisedCopy
from .ai.base import AIProvider, ImageProvider
from .creative.brand_style import resolve_brand_style
from .creative.renderer import PlaywrightRenderer
from .feedback_selector import (  # re-exported — see module docstring
    FeedbackSelection, format_feedback_for_prompt, select_feedback_examples, snapshot_prompt_versions,
)
from .orchestrator import (
    AutopilotConfig, _audit, _deterministic_creative_direction, _load_campaign_context, _load_stage_json,
    _resolve_image_model_and_quality, _resolve_platform_adaptation, _stage_language_variant, resolve_brand_colors,
    resolve_brand_logo_path,
)
from .qa_engine import (
    _regenerate_variant_render, _regenerate_with_best_of_n, revise_copy_for_variant,
    revise_creative_direction_for_variant, revise_video_concept,
)
from ..data.platform_creative_specs import resolve_platform_creative_spec

__all__ = [
    "record_review_feedback", "apply_requested_revision", "select_feedback_examples", "format_feedback_for_prompt",
    "FeedbackSelection",
]

LEVELS = ("CAMPAIGN", "PLATFORM_VARIANT", "ASSET")
ACTIONS = ("APPROVE", "REJECT", "REQUEST_REVISION")
# For level="ASSET" on a SCRIPT_ONLY variant — carry-forward requirement 8:
# never a control implying a rendered video file exists.
SCRIPT_ASSET_REFS = ("hook", "script", "shot_list", "timing", "on_screen_text", "caption", "cover")


def _snapshot_variant(variant: PlatformCampaignVariant | None, db: Session, campaign_id: str) -> dict:
    """Carry-forward requirement 2: everything the spec named by name, frozen
    at review time. Returns an all-empty snapshot (never raises) for
    `level="CAMPAIGN"` feedback, which has no single variant to snapshot.
    """
    if variant is None:
        return dict(
            reviewed_slide_asset_paths=[], reviewed_video_concept=None, reviewed_copy_snapshot={},
            reviewed_creative_direction={}, reviewed_qa_status="", reviewed_qa_scores=None,
            reviewed_qa_hard_fails=[], reviewed_qa_attempts=0, reviewed_qa_evidence_paths=[],
            reviewed_qa_versions={}, reviewed_prompt_versions={},
        )
    copy_data_raw = _load_stage_json(db, campaign_id, "copy")
    copy_variant = _stage_language_variant(copy_data_raw, variant.language) or {}
    copy_snapshot = {
        "headline": copy_variant.get("headline", ""), "body": copy_variant.get("body", ""),
        "cta": copy_variant.get("cta", ""), "hook": copy_variant.get("hook", ""),
    }
    return dict(
        reviewed_slide_asset_paths=list(variant.slide_asset_paths or []),
        reviewed_video_concept=dict(variant.video_concept) if variant.video_concept else None,
        reviewed_copy_snapshot=copy_snapshot,
        reviewed_creative_direction=dict(variant.creative_direction or {}),
        reviewed_qa_status=variant.qa_status or "",
        reviewed_qa_scores=dict(variant.qa_scores) if variant.qa_scores else None,
        reviewed_qa_hard_fails=list(variant.qa_hard_fails or []),
        reviewed_qa_attempts=variant.qa_attempts or 0,
        reviewed_qa_evidence_paths=list(variant.qa_evidence_paths or []),
        reviewed_qa_versions=dict(variant.qa_versions or {}),
        reviewed_prompt_versions=snapshot_prompt_versions(
            db, campaign_id=campaign_id, platform=variant.target_platform, language=variant.language,
        ),
    )


def _validate_asset_ref(variant: PlatformCampaignVariant | None, asset_ref: str) -> None:
    if not asset_ref:
        return
    if variant is not None and variant.status == "SCRIPT_ONLY":
        if asset_ref not in SCRIPT_ASSET_REFS:
            raise ValueError(
                f"asset_ref {asset_ref!r} is not valid for a script-only (no rendered video file) variant — "
                f"must be one of {SCRIPT_ASSET_REFS} (carry-forward requirement 8)."
            )


def record_review_feedback(
    db: Session, *, campaign: Campaign, variant: PlatformCampaignVariant | None, level: str, asset_ref: str = "",
    action: str, reason_code: str = "", reason_text: str = "",
) -> ReviewFeedback:
    """Writes one `ReviewFeedback` row and updates ONLY the reviewed row's own
    `human_review_status` — carry-forward requirement 1 (a variant-scoped
    action never touches a sibling variant or the parent campaign) and
    requirement 4 (never collapses into `qa_status`, never mutated here).

    `level="CAMPAIGN"` requires `variant is None` and updates
    `campaign.human_review_status`. `level` in `("PLATFORM_VARIANT", "ASSET")`
    requires a `variant` and updates ONLY `variant.human_review_status` —
    never the parent campaign's, honoring "Parent Campaign status may
    aggregate these, but must preserve child truth" (the aggregation itself
    is `GET /api/campaigns/{id}/review-summary`'s job, a read-only rollup,
    never a write-back).

    Lineage (carry-forward requirement 3): auto-links to the most recent
    still-unanswered `REQUEST_REVISION` feedback at the same level/scope, if
    one exists — no explicit parameter needed. "Unanswered" means no later
    feedback at this same scope already points back to it.
    """
    if level not in LEVELS:
        raise ValueError(f"level must be one of {LEVELS}, got {level!r}.")
    if action not in ACTIONS:
        raise ValueError(f"action must be one of {ACTIONS}, got {action!r}.")
    if level == "CAMPAIGN" and variant is not None:
        raise ValueError("level='CAMPAIGN' feedback must not reference a platform_campaign_variant.")
    if level in ("PLATFORM_VARIANT", "ASSET") and variant is None:
        raise ValueError(f"level={level!r} feedback requires a variant.")
    if level != "ASSET" and asset_ref:
        raise ValueError("asset_ref is only meaningful for level='ASSET' feedback.")
    _validate_asset_ref(variant, asset_ref)

    scope_query = db.query(ReviewFeedback).filter(ReviewFeedback.campaign_id == campaign.id, ReviewFeedback.level == level)
    if variant is not None:
        scope_query = scope_query.filter(ReviewFeedback.platform_campaign_variant_id == variant.id)
    else:
        scope_query = scope_query.filter(ReviewFeedback.platform_campaign_variant_id.is_(None))
    if level == "ASSET":
        scope_query = scope_query.filter(ReviewFeedback.asset_ref == asset_ref)
    prior_rows = scope_query.order_by(ReviewFeedback.created_at.asc()).all()
    answered_ids = {row.revision_of_feedback_id for row in prior_rows if row.revision_of_feedback_id}
    unanswered_revision = next(
        (row for row in reversed(prior_rows) if row.action == "REQUEST_REVISION" and row.id not in answered_ids),
        None,
    )

    snapshot = _snapshot_variant(variant, db, campaign.id)
    feedback = ReviewFeedback(
        campaign_id=campaign.id,
        platform_campaign_variant_id=variant.id if variant is not None else None,
        level=level, asset_ref=asset_ref, action=action, reason_code=reason_code, reason_text=reason_text,
        brand_id=campaign.brand_id, category_id=campaign.category_id, product_id=campaign.product_id,
        platform=variant.target_platform if variant is not None else "",
        language=variant.language if variant is not None else "",
        content_type=(variant.content_type if variant is not None else campaign.content_type) or "",
        objective=campaign.objective or "",
        revision_of_feedback_id=unanswered_revision.id if unanswered_revision is not None else None,
        **snapshot,
    )
    db.add(feedback)

    # Human review status: written ONLY to the exact row that was reviewed —
    # never aggregated onto anything else (carry-forward requirement 1/4).
    review_status = {"APPROVE": "APPROVED", "REJECT": "REJECTED", "REQUEST_REVISION": "REVISION_REQUESTED"}[action]
    if level == "CAMPAIGN":
        campaign.human_review_status = review_status
    else:
        variant.human_review_status = review_status

    _audit(db, campaign.id, "review.feedback_recorded", {
        "level": level, "action": action, "reason_code": reason_code,
        "variant_id": variant.id if variant is not None else None,
    })
    db.commit()
    db.refresh(feedback)
    return feedback


async def apply_requested_revision(
    db: Session, *, campaign: Campaign, variant: PlatformCampaignVariant, feedback: ReviewFeedback,
    config: AutopilotConfig, renderer: PlaywrightRenderer, image_provider: ImageProvider | None = None,
    ai_provider: AIProvider | None = None,
) -> PlatformCampaignVariant:
    """Carry-forward requirement 3's own mechanics: actually APPLIES a
    REQUEST_REVISION action's implied fix, reusing Build 3's existing QA-
    engine revision primitives (never a second, parallel revision pipeline —
    `qa_engine.py`'s own `revise_copy_for_variant` / `revise_creative_
    direction_for_variant` / `_regenerate_variant_render` /
    `_regenerate_with_best_of_n` / `revise_video_concept` do the real work
    here, exactly as they already do inside `run_qa_stage`'s own retry loop).

    `feedback.reason_code` (via `data/feedback_reasons.py::revision_kind_for`)
    picks WHICH kind of revision to run: "copy" | "creative_direction" |
    "rerender" | "video_concept" — the mapping documented on that module.
    `feedback.reason_text` alone (no structured code) safely defaults to
    "rerender", per that same module's own documented reasoning.

    Never overwrites `feedback` itself or any prior `ReviewFeedback` row —
    lineage is preserved because the REVIEWED version is already frozen in
    `feedback`'s own `reviewed_*` snapshot columns; this only mutates the
    LIVE `variant` row going forward, exactly like every pre-Build-4 revision
    already did. Resets `variant.human_review_status` back to `PENDING`
    afterward (the revised version awaits a fresh owner look) and leaves
    `variant.qa_status`/QA evidence exactly as this revision naturally
    changes them (a real re-render legitimately changes `qa_*`; a plain
    APPROVE/REJECT action never does — see `record_review_feedback`).
    """
    if feedback.action != "REQUEST_REVISION":
        raise ValueError("apply_requested_revision requires a REQUEST_REVISION feedback row.")
    if feedback.platform_campaign_variant_id != variant.id:
        raise ValueError("feedback does not reference this variant.")

    kind = revision_kind_for(feedback.reason_code)
    issues = [feedback.reason_text] if feedback.reason_text else (
        [f"Owner feedback: {feedback.reason_code}"] if feedback.reason_code else ["Owner requested a revision."]
    )

    if variant.status == "SCRIPT_ONLY" or (kind == "video_concept" and variant.video_concept):
        # Carry-forward requirement 8: format-aware — a script-only variant is
        # only ever revised as a script, never treated as a rendered asset.
        video_concept = VideoConcept(**variant.video_concept) if variant.video_concept else None
        if video_concept is None:
            return variant
        master_concept_data = _load_stage_json(db, campaign.id, "master_concept")
        master_concept = MasterCampaignConcept(**master_concept_data) if master_concept_data else None
        adaptation = await _resolve_platform_adaptation(
            ai_provider, master_concept=master_concept, platform=variant.target_platform,
            content_type=variant.content_type, model=config.platform_adapter_model,
        )
        revised = await revise_video_concept(
            ai_provider, previous=video_concept, issues=issues, master_concept=master_concept,
            platform=variant.target_platform, language=variant.language, adaptation=adaptation,
            model=config.platform_adapter_model,
        )
        if revised is not None:
            variant.video_concept = revised.model_dump()
        variant.human_review_status = "PENDING"
        db.commit()
        db.refresh(variant)
        return variant

    campaign_full, brand, category, _product = _load_campaign_context(db, campaign.id)
    category_slug = category.slug if category else "general"
    spec = resolve_platform_creative_spec(variant.target_platform, variant.content_type)
    copy_data_raw = _load_stage_json(db, campaign.id, "copy")
    creative_data_raw = _load_stage_json(db, campaign.id, "creative")
    discovery_products = list(campaign.discovery_products)
    is_discovery = campaign.product_id is None and len(discovery_products) > 0
    brand_colors = resolve_brand_colors(brand)
    logo_path = resolve_brand_logo_path(db, brand.id)
    brand_style = resolve_brand_style(db, brand, logo_path=logo_path)
    quality_image_model, quality_tier = _resolve_image_model_and_quality(config)
    now = datetime.now(timezone.utc)

    copy_variant = _stage_language_variant(copy_data_raw, variant.language) or {}
    headline, body = copy_variant.get("headline", ""), copy_variant.get("body", "")
    cta = copy_variant.get("cta", "") or campaign.cta or ""

    creative_direction: CreativeDirection | None = None
    if variant.creative_direction:
        try:
            creative_direction = CreativeDirection(**variant.creative_direction)
        except Exception:  # noqa: BLE001 - a malformed/legacy stored direction just means "none on file"
            creative_direction = None

    copy_override: RevisedCopy | None = None
    new_creative_direction = creative_direction

    if kind == "copy":
        revised = await revise_copy_for_variant(
            ai_provider, headline=headline, body=body, cta=cta, issues=issues, language=variant.language,
            platform=variant.target_platform, model=config.creative_qa_model,
        )
        if revised is not None:
            copy_override = revised
        new_slide_paths, new_qa_paths = await _regenerate_variant_render(
            db, variant=variant, campaign=campaign_full, brand=brand, category_slug=category_slug, config=config,
            renderer=renderer, image_provider=image_provider, quality_image_model=quality_image_model,
            quality_tier=quality_tier, spec=spec, creative_data_raw=creative_data_raw,
            discovery_products=discovery_products, is_discovery=is_discovery, brand_colors=brand_colors,
            logo_path=logo_path, brand_style=brand_style, creative_direction=None, copy_override=copy_override,
            now=now,
        )
    elif kind == "creative_direction":
        master_concept_data = _load_stage_json(db, campaign.id, "master_concept")
        master_concept = MasterCampaignConcept(**master_concept_data) if master_concept_data else None
        adaptation = await _resolve_platform_adaptation(
            ai_provider, master_concept=master_concept, platform=variant.target_platform,
            content_type=variant.content_type, model=config.platform_adapter_model,
        )
        fallback_direction = creative_direction or _deterministic_creative_direction(
            master_concept=master_concept, adaptation=adaptation, platform=variant.target_platform,
            language=variant.language, content_type=variant.content_type, slide_role="", brand_style=brand_style,
        )
        new_creative_direction = await revise_creative_direction_for_variant(
            ai_provider, previous_direction=fallback_direction, issues=issues, master_concept=master_concept,
            adaptation=adaptation, platform=variant.target_platform, language=variant.language,
            content_type=variant.content_type, slide_role="", model=config.creative_director_model,
            fallback=fallback_direction,
        )
        scoring_context = (
            f"Revision requested. Platform: {variant.target_platform}. Language: {variant.language}. Issues: {issues}."
        )
        new_slide_paths, new_qa_paths = await _regenerate_with_best_of_n(
            db, variant=variant, campaign=campaign_full, brand=brand, category_slug=category_slug, config=config,
            renderer=renderer, image_provider=image_provider, ai_provider=ai_provider,
            quality_image_model=quality_image_model, quality_tier=quality_tier, spec=spec,
            creative_data_raw=creative_data_raw, discovery_products=discovery_products, is_discovery=is_discovery,
            brand_colors=brand_colors, logo_path=logo_path, brand_style=brand_style,
            creative_direction=new_creative_direction, copy_override=None, now=now, scoring_context=scoring_context,
        )
        variant.creative_direction = new_creative_direction.model_dump()
    else:  # "rerender" — safe default, no copy/creative-direction change.
        new_slide_paths, new_qa_paths = await _regenerate_variant_render(
            db, variant=variant, campaign=campaign_full, brand=brand, category_slug=category_slug, config=config,
            renderer=renderer, image_provider=image_provider, quality_image_model=quality_image_model,
            quality_tier=quality_tier, spec=spec, creative_data_raw=creative_data_raw,
            discovery_products=discovery_products, is_discovery=is_discovery, brand_colors=brand_colors,
            logo_path=logo_path, brand_style=brand_style, creative_direction=None, copy_override=None, now=now,
        )

    if new_slide_paths:
        variant.slide_asset_paths = new_slide_paths
        variant.qa_report_paths = new_qa_paths
    variant.human_review_status = "PENDING"
    _audit(db, campaign.id, "review.revision_applied", {"variant_id": variant.id, "kind": kind})
    db.commit()
    db.refresh(variant)
    return variant
