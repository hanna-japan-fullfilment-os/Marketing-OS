"""Campaign endpoints. List/detail/lifecycle actions are real (backed by the DB
schema). `/campaigns/{id}/generate` runs the real Autopilot orchestrator
(services/orchestrator.py): research -> strategy candidates -> novelty check ->
copy -> carousel plan -> creative render.

All four `/generate*` endpoints below run their job via `services/jobs.py::
run_job_in_background` — a `Job` row is created and the HTTP response comes back
immediately with just `{job_id, job_status}` ("QUEUED"), rather than the caller's
request blocking until the whole pipeline finishes (a research call alone can take
tens of seconds, before rendering even starts). The frontend polls
`GET /api/jobs/{id}` (see api/jobs.py) for `status`/`progress`/`step`, and refetches
the campaign once the job reaches `COMPLETED` or `FAILED`. This is the same `Job`
row and progress-reporting mechanism as before (`JobContext`/`ProgressReporter`
haven't changed) — only *how* the job is run changed, from `await run_job(...)`
(caller's coroutine, request blocks) to `run_job_in_background(...)` (a scheduled
`asyncio.create_task`, request returns immediately). A validation failure that can
be caught before the job starts (bad status, missing settings) still raises an
HTTPException synchronously, same as before; a failure *during* the pipeline now
surfaces as `Job.status="FAILED"` + `Job.error` for the frontend to show, since the
original request has already returned and has nothing left to catch it with.

The Campaign Builder advanced mode splits that same pipeline into three separately
callable stages — `/generate/strategy`, `/generate/copy`, `/generate/visuals` — each
wrapping one of `services/orchestrator.py`'s `run_strategy_stage`/`run_copy_stage`/
`run_visuals_stage` functions the same way `/generate` wraps `run_autopilot` (which
itself just runs those three stages back to back). See that module's docstring for
why each stage can run standalone.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import db as db_module
from ..config import get_settings
from ..data.platform_capabilities import (
    PLATFORM_CAPABILITIES, SUPPORTED_LANGUAGES, validate_languages, validate_target_platforms,
)
from ..db import get_db
from ..models import (
    Asset, AuditEvent, Brand, Campaign, CampaignAsset, CampaignDiscoveryProduct, CampaignOpportunity,
    CampaignOutput, CampaignSequence, CampaignSlide, CampaignStrategyType, Category, Job, Opportunity,
    PlatformCampaignVariant, Product, Publication, ReviewFeedback,
)
from ..data.feedback_reasons import FEEDBACK_REASON_CODES
from ..services import settings_store
from ..services.ai.base import PublishCopy, PublishTarget
from ..services.ai.openai_provider import OpenAIProvider, openai_provider_from_effective_settings
from ..services.creative.brand_style import resolve_brand_style
from ..services.creative.pipeline import (
    SlideCreativeInput, build_qa_report_path, build_slide_output_path, render_slide,
)
from ..services.creative.renderer import get_renderer
from ..services.creative.templates import PLATFORM_FORMATS, TEMPLATES, get_platform_format
from ..services.jobs import create_job, run_job_in_background
from ..services.orchestrator import (
    AutopilotConfig, check_copy_stage_prerequisite, check_visuals_stage_prerequisite, detect_product_zone,
    generate_ai_background, get_campaign_copy, get_platform_campaign_variants,
    recreate_creative_image_with_fidelity_gate, resolve_brand_colors, resolve_brand_logo_path, run_autopilot,
    run_copy_stage, run_strategy_stage, run_visuals_stage,
)
from ..services.prompt_registry import record_prompt_usage
from ..services.qa_engine import run_qa_stage
from ..services.review_engine import LEVELS, apply_requested_revision, record_review_feedback
from ..services.publishing.meta_provider import MetaPublishingProvider

router = APIRouter(prefix="/api/campaigns", tags=["campaigns"])


class CampaignCreate(BaseModel):
    brand_id: str
    category_id: str | None = None
    product_id: str | None = None
    strategy_type_key: str | None = None
    objective: str = "awareness"
    channels: list[str] = []
    language: str = "pt-BR"
    geography: str = ""
    notes: str = ""
    triggered_by_event_id: str | None = None
    # Round 20: which real platform/format this campaign renders at, picked once
    # up front instead of only after the fact via PATCH. `None` (the default)
    # behaves exactly as before this field existed — falls back to
    # AutopilotConfig.platform_key's own default at render time.
    platform_key: str | None = None
    # Build 1 (Parts B/C): the canonical structured fields — `language` above is
    # kept for backward compatibility (existing rows, existing callers) but is no
    # longer authoritative once `languages` is set. See models/campaign.py for the
    # full rationale. Defaults match `data/platform_capabilities.py`'s own
    # defaults so a client that doesn't send these still gets today's behavior.
    languages: list[str] = ["pt-BR"]
    target_platforms: list[str] = ["instagram"]


def _next_display_id(db: Session, brand_id: str, category_slug: str, brand_slug: str) -> str:
    seq = (
        db.query(CampaignSequence)
        .filter(CampaignSequence.brand_id == brand_id, CampaignSequence.category_slug == category_slug)
        .one_or_none()
    )
    if seq is None:
        seq = CampaignSequence(brand_id=brand_id, category_slug=category_slug, next_value=1)
        db.add(seq)
        db.flush()
    value = seq.next_value
    seq.next_value += 1
    prefix = f"{brand_slug[:5].upper()}-{category_slug[:5].upper()}"
    return f"{prefix}-{value:06d}"


@router.get("")
def list_campaigns(
    brand_id: str,
    status: str | None = None,
    category_id: str | None = None,
    db: Session = Depends(get_db),
):
    q = db.query(Campaign).filter(Campaign.brand_id == brand_id)
    if status:
        q = q.filter(Campaign.status == status)
    if category_id:
        q = q.filter(Campaign.category_id == category_id)
    campaigns = q.order_by(Campaign.created_at.desc()).all()
    strategy_ids = {c.strategy_type_id for c in campaigns if c.strategy_type_id}
    strategy_names = {}
    if strategy_ids:
        for st in db.query(CampaignStrategyType).filter(CampaignStrategyType.id.in_(strategy_ids)).all():
            strategy_names[st.id] = st.name
    return [
        {
            "id": c.id,
            "display_id": c.display_id,
            "status": c.status,
            "objective": c.objective,
            "angle": c.angle,
            "strategy_type_name": strategy_names.get(c.strategy_type_id),
            "category_id": c.category_id,
            "created_at": c.created_at,
        }
        for c in campaigns
    ]


@router.post("", status_code=201)
def create_campaign(payload: CampaignCreate, db: Session = Depends(get_db)):
    """Records a campaign IDEA — brand, category, and a chosen Strategy Library type
    (optionally triggered by a Defense recommendation). This does NOT generate
    research/copy/creative yet; see /generate below. It's a real, persisted record
    of intent, not a stub screen — useful today for planning even before Autopilot
    exists.
    """
    brand = db.get(Brand, payload.brand_id)
    if brand is None:
        raise HTTPException(404, "Brand not found.")

    category_slug = "general"
    if payload.category_id:
        category = db.get(Category, payload.category_id)
        if category is None:
            raise HTTPException(404, "Category not found.")
        category_slug = category.slug

    strategy_type = None
    if payload.strategy_type_key:
        strategy_type = db.query(CampaignStrategyType).filter(
            CampaignStrategyType.key == payload.strategy_type_key
        ).one_or_none()
        if strategy_type is None:
            raise HTTPException(404, "Strategy type not found.")

    if payload.platform_key is not None and payload.platform_key not in PLATFORM_FORMATS:
        available = ", ".join(sorted(PLATFORM_FORMATS))
        raise HTTPException(400, f"Unknown platform_key {payload.platform_key!r}. Available: {available}")

    # Build 1 (Parts B/C): validate the new structured fields up front — never
    # silently drop or substitute an unrecognized language/platform.
    try:
        languages = validate_languages(payload.languages)
        target_platforms = validate_target_platforms(payload.target_platforms)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    display_id = _next_display_id(db, brand.id, category_slug, brand.slug)
    campaign = Campaign(
        display_id=display_id,
        brand_id=brand.id,
        category_id=payload.category_id,
        product_id=payload.product_id,
        strategy_type_id=strategy_type.id if strategy_type else None,
        angle=strategy_type.name if strategy_type else "",
        objective=payload.objective,
        channels=payload.channels or (strategy_type.channels if strategy_type else []),
        language=payload.language,
        languages=languages,
        target_platforms=target_platforms,
        geography=payload.geography,
        notes=payload.notes,
        triggered_by_event_id=payload.triggered_by_event_id,
        platform_key=payload.platform_key,
        status="IDEA",
    )
    db.add(campaign)
    db.commit()
    db.refresh(campaign)
    return {"id": campaign.id, "display_id": campaign.display_id, "status": campaign.status}


@router.get("/{campaign_id}")
def get_campaign(campaign_id: str, db: Session = Depends(get_db)):
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(404, "Campaign not found.")
    strategy_type = db.get(CampaignStrategyType, campaign.strategy_type_id) if campaign.strategy_type_id else None
    product = db.get(Product, campaign.product_id) if campaign.product_id else None
    # Round 19: which of the two carousel structures this campaign will use is
    # entirely a function of what's already picked at creation time — no extra
    # field, no extra decision. A specific Product means "deep-dive" (one product,
    # every slide a different AI-recreated composition of it, round 18's whole
    # fidelity-gated pipeline). No Product means "discovery" (one slide per
    # hand-picked product below) — but only once at least one has actually been
    # picked; a bare category-only campaign with none picked yet just falls back to
    # today's existing single-photo-pool behavior so nothing that already worked
    # changes underneath an existing campaign. See run_copy_stage/run_visuals_stage.
    discovery_products = campaign.discovery_products
    structure_mode = "deep_dive" if campaign.product_id or not discovery_products else "discovery"
    return {
        "id": campaign.id,
        "display_id": campaign.display_id,
        "status": campaign.status,
        "objective": campaign.objective,
        "audience": campaign.audience,
        "angle": campaign.angle,
        "strategy_type": (
            {"key": strategy_type.key, "name": strategy_type.name, "family_id": strategy_type.family_id}
            if strategy_type
            else None
        ),
        "hook": campaign.hook,
        "main_promise": campaign.main_promise,
        "cta": campaign.cta,
        "channels": campaign.channels,
        "language": campaign.language,
        "languages": campaign.languages,
        "target_platforms": campaign.target_platforms,
        "geography": campaign.geography,
        "notes": campaign.notes,
        "target_slide_count": campaign.target_slide_count,
        "platform_key": campaign.platform_key,
        "category_id": campaign.category_id,
        "product_id": campaign.product_id,
        "product_name": product.name if product else None,
        "structure_mode": structure_mode,
        "discovery_products": [
            {"product_id": dp.product_id, "name": dp.product.name, "sort_order": dp.sort_order}
            for dp in discovery_products
        ],
        "created_at": campaign.created_at,
        "slides": [
            {
                "slide_number": s.slide_number,
                "purpose": s.purpose,
                "headline": s.headline,
                "body": s.body,
                "rendered_asset_path": s.rendered_asset_path,
            }
            for s in campaign.slides
        ],
    }


class CampaignUpdate(BaseModel):
    """A real settings/update endpoint could grow more fields later, but only
    these two are edited in place today (strategy/copy/visuals are regenerated,
    not hand-edited).
    """

    target_slide_count: int | None = None
    platform_key: str | None = None
    # Build 1 (Parts B/C): editable post-creation for parity with the two fields
    # above — same "takes effect on the next Copy/Autopilot run, not retroactive"
    # rule. `None`/absent leaves the campaign's current value untouched; an empty
    # list is rejected by the validators below (a campaign must always target at
    # least one language and one platform), so there's no "clear it" null case
    # here unlike target_slide_count/platform_key.
    languages: list[str] | None = None
    target_platforms: list[str] | None = None


@router.patch("/{campaign_id}")
def update_campaign(campaign_id: str, payload: CampaignUpdate, db: Session = Depends(get_db)):
    """Updates `target_slide_count`, `platform_key`, `languages`, and/or
    `target_platforms`. Only fields actually present in the request body are
    touched (`model_fields_set`), so a client updating one doesn't have to also
    resend the others.

    `target_slide_count`: how many slides Autopilot's carousel planner should aim
    for on this campaign. Pass `null` explicitly to clear it and go back to the
    planner's own judgment ("up to" the configured default, see
    services/orchestrator.py::run_copy_stage). Editable at any time, including
    after Copy/Visuals has already run — it only takes effect the next time the
    Copy stage (or a full Autopilot run) executes; it does not retroactively
    change slides already rendered.

    Round 19: cap raised from 10 to 20 (real request: a single-product deep-dive
    campaign transformed into up to a 20-slide carousel). Has no effect on a
    discovery-mode campaign (see the new `/discovery-products` endpoint below) —
    there, slide count is simply how many products were picked, not this field.

    `platform_key` (round 20): which real platform/format this campaign renders
    at — must be a real key from `PLATFORM_FORMATS` (e.g. "instagram_square",
    "instagram_portrait", "instagram_story", "facebook_feed"), or `null` to fall
    back to `AutopilotConfig.platform_key`'s default, exactly like before this
    field existed. Same "takes effect on the next render, not retroactive" rule
    as `target_slide_count`. This is the campaign-level counterpart to the manual
    single-slide render panel's own per-render platform picker, which already
    existed — Autopilot and Campaign Builder had no way to pick a platform for a
    whole campaign until this field.
    """
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(404, "Campaign not found.")
    if "target_slide_count" in payload.model_fields_set:
        if payload.target_slide_count is not None and not (1 <= payload.target_slide_count <= 20):
            raise HTTPException(400, "target_slide_count must be between 1 and 20, or null to clear it.")
        campaign.target_slide_count = payload.target_slide_count
    if "platform_key" in payload.model_fields_set:
        if payload.platform_key is not None and payload.platform_key not in PLATFORM_FORMATS:
            available = ", ".join(sorted(PLATFORM_FORMATS))
            raise HTTPException(400, f"Unknown platform_key {payload.platform_key!r}. Available: {available}")
        campaign.platform_key = payload.platform_key
    if "languages" in payload.model_fields_set:
        try:
            campaign.languages = validate_languages(payload.languages)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
    if "target_platforms" in payload.model_fields_set:
        try:
            campaign.target_platforms = validate_target_platforms(payload.target_platforms)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
    if payload.model_fields_set & {"target_slide_count", "platform_key", "languages", "target_platforms"}:
        db.commit()
        db.refresh(campaign)
    return {
        "id": campaign.id,
        "target_slide_count": campaign.target_slide_count,
        "platform_key": campaign.platform_key,
        "languages": campaign.languages,
        "target_platforms": campaign.target_platforms,
    }


class DiscoveryProductsUpdate(BaseModel):
    product_ids: list[str]


@router.put("/{campaign_id}/discovery-products")
def set_discovery_products(campaign_id: str, payload: DiscoveryProductsUpdate, db: Session = Depends(get_db)):
    """Replaces this campaign's hand-picked "discovery" product list wholesale —
    the ordered set of distinct products that get one slide each (round 19). List
    order becomes carousel order (first id -> slide 1). Send an empty list to clear
    it (falls back to today's single-photo-pool behavior, same as a campaign that
    never had any picked).

    Only meaningful on a campaign with no single `product_id` set — that's the
    "deep-dive" shape instead (one product, recreated across every slide; see
    round 18). Rejected with 400 on a product-scoped campaign, so the two carousel
    structures never end up ambiguous for the same campaign.
    """
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(404, "Campaign not found.")
    if campaign.product_id:
        raise HTTPException(
            400,
            "This campaign is scoped to a single product (deep-dive mode) — clear its product to switch "
            "to multi-product discovery mode instead.",
        )
    if len(payload.product_ids) > 20:
        raise HTTPException(400, "A discovery carousel can feature at most 20 products.")
    if len(set(payload.product_ids)) != len(payload.product_ids):
        raise HTTPException(400, "The same product can't be picked twice in one discovery carousel.")

    if payload.product_ids:
        found = db.query(Product).filter(Product.id.in_(payload.product_ids), Product.brand_id == campaign.brand_id).all()
        found_ids = {p.id for p in found}
        missing = [pid for pid in payload.product_ids if pid not in found_ids]
        if missing:
            raise HTTPException(404, f"Product(s) not found for this brand: {', '.join(missing)}")

    db.query(CampaignDiscoveryProduct).filter(CampaignDiscoveryProduct.campaign_id == campaign.id).delete()
    for i, product_id in enumerate(payload.product_ids):
        db.add(CampaignDiscoveryProduct(campaign_id=campaign.id, product_id=product_id, sort_order=i))
    db.commit()

    campaign = db.get(Campaign, campaign_id)
    return {
        "id": campaign.id,
        "discovery_products": [
            {"product_id": dp.product_id, "name": dp.product.name, "sort_order": dp.sort_order}
            for dp in campaign.discovery_products
        ],
    }


@router.delete("/{campaign_id}", status_code=204)
def delete_campaign(campaign_id: str, db: Session = Depends(get_db)):
    """Permanently deletes a campaign — the record itself, and everything scoped to
    it: rendered slides, saved copy/creative/QA outputs, its novelty fingerprint,
    any logged publications and their performance metrics, and community-draft
    attachments. The DB side of that is cascading foreign keys (see
    models/campaign.py, models/opportunity.py, models/publishing.py — every child
    table's `campaign_id` is `ondelete="CASCADE"`); this function's own job is the
    part cascades can't do: best-effort removal of the real files those rows
    pointed at under OUTPUT_ROOT, since a deleted DB row doesn't delete a file on
    disk. Any `Job` history for this campaign (background-job progress records —
    not a real foreign key, see models/platform.py) is cleaned up too so a deleted
    campaign doesn't leave a phantom entry behind.

    Deliberately does NOT touch anything under SOURCE_ASSET_ROOT: the source
    photos a campaign used are shared, read-only assets other campaigns may still
    reference, so only this campaign's own generated output is ever removed.

    Refuses (409) while a background job for this campaign is still QUEUED/
    RUNNING — deleting out from under an in-flight Autopilot/stage run would have
    it fail confusingly trying to write to a campaign that no longer exists;
    finish or wait out the run first. Otherwise allowed from any status,
    including PUBLISHED — this is a real, permanent action with no undo, which is
    the frontend's job to make clear before calling it, not this endpoint's job
    to second-guess.
    """
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(404, "Campaign not found.")

    active_job = (
        db.query(Job)
        .filter(Job.campaign_id == campaign.id, Job.status.in_(["QUEUED", "RUNNING"]))
        .first()
    )
    if active_job is not None:
        raise HTTPException(
            409,
            "This campaign has a background job still running (or queued) — wait for it to finish before deleting.",
        )

    file_paths: list[str] = []
    for slide in campaign.slides:
        if slide.rendered_asset_path:
            file_paths.append(slide.rendered_asset_path)
        if slide.generated_background_path:
            file_paths.append(slide.generated_background_path)
    for output in campaign.outputs:
        if output.file_path:
            file_paths.append(output.file_path)

    for raw_path in file_paths:
        try:
            Path(raw_path).unlink(missing_ok=True)
        except OSError:
            pass  # best-effort — a locked or permission-denied file shouldn't block the delete

    db.add(AuditEvent(
        entity_type="campaign", entity_id=campaign.id, action="deleted",
        detail={"display_id": campaign.display_id, "status": campaign.status},
    ))
    db.query(Job).filter(Job.campaign_id == campaign.id).delete()
    db.delete(campaign)
    db.commit()
    return Response(status_code=204)


class SlideRenderRequest(BaseModel):
    asset_id: str
    slide_number: int = 1
    total_slides: int = 1  # round 18: drives the "N/total" marker; 1 = no marker
    template_id: str = "feature_showcase"
    platform_key: str = "instagram_square"
    eyebrow: str = ""
    headline: str
    body: str = ""
    cta: str = ""
    isolate_background: bool = False
    use_ai_background: bool = False
    detect_product_zone: bool = False
    recreate_with_ai: bool = False


@router.get("/creative/templates")
def list_creative_templates():
    """Real, static metadata for the two frontend dropdowns (template + platform
    format) that drive /slides/render below — not app state, so no DB round-trip.
    """
    return {
        "templates": [{"id": t.id, "name": t.name, "description": t.description} for t in TEMPLATES.values()],
        "platform_formats": [
            {"key": f.key, "label": f.label, "width": f.width, "height": f.height}
            for f in PLATFORM_FORMATS.values()
        ],
    }


@router.get("/config/platform-capabilities")
def list_platform_capabilities():
    """Build 1 (Parts B/C): real, static metadata for the campaign-creation and
    campaign-settings language/platform pickers — same "no DB round-trip" shape
    as `/creative/templates` above, since `SUPPORTED_LANGUAGES`/
    `PLATFORM_CAPABILITIES` are a fixed in-app registry, not app state.

    Deliberately a distinct concept from `/creative/templates`'s
    `platform_formats`: that's "what pixel size to render at" (`services/
    creative/templates.py::PLATFORM_FORMATS`); this is "which real-world social
    platform is this campaign being planned for" (`data/platform_capabilities.py`
    — instagram/facebook/tiktok/youtube_shorts/pinterest/linkedin/x). A campaign
    can target multiple platforms here while still only rendering at one pixel
    format today (see docs/campaign-pipeline.md's Build 1 section).
    """
    return {
        "languages": list(SUPPORTED_LANGUAGES),
        "platforms": [
            {
                "key": cap.key,
                "label": cap.label,
                "content_types": list(cap.content_types),
                "copy_notes": cap.copy_notes,
            }
            for cap in PLATFORM_CAPABILITIES.values()
        ],
    }


@router.post("/{campaign_id}/slides/render")
async def render_campaign_slide(campaign_id: str, payload: SlideRenderRequest, db: Session = Depends(get_db)):
    """Runs the real creative pipeline (services/creative/pipeline.py) for one slide:
    background isolation (optional) → brand-color or AI-generated background →
    optional per-photo product-zone detection → composite the actual product photo
    → render the chosen HTML template at exact platform pixel dimensions via
    Playwright → automated QA. This is a manual, per-slide render — Autopilot
    (see /generate and docs/campaign-pipeline.md) calls the same pipeline
    end-to-end for a whole campaign; this endpoint is what lets a slide be
    produced by hand instead, e.g. to fix up one slide after an Autopilot run.

    `detect_product_zone=true` opts into a vision-model call that locates the
    actual product in this specific photo and crops/anchors to it, instead of the
    chosen template's one fixed layout — see services/orchestrator.py::
    detect_product_zone.

    `recreate_with_ai=true` opts into a full AI recreation of this photo (product
    included, not just a new backdrop), verified against the real source photo
    before it's trusted — see services/orchestrator.py::
    recreate_creative_image_with_fidelity_gate. Takes priority over
    `use_ai_background`/`detect_product_zone` for this slide when it produces a
    verified image; falls back to them otherwise (generation failure, or a failed/
    unverifiable fidelity check even after one corrective retry). As of round 16,
    a successful recreation also bakes the eyebrow/headline/body/CTA text directly
    into the image (styled after any uploaded inspiration examples) instead of
    this endpoint's usual HTML/CSS text overlay — the two are mutually exclusive
    per slide so the text never renders twice; the payload's text fields are still
    saved on the `CampaignSlide` row either way.
    """
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(404, "Campaign not found.")
    brand = db.get(Brand, campaign.brand_id)
    if brand is None:
        raise HTTPException(404, "Brand not found.")

    asset = db.get(Asset, payload.asset_id)
    if asset is None or asset.brand_id != campaign.brand_id:
        raise HTTPException(404, "Asset not found for this brand.")
    source_path = Path(asset.absolute_path)
    if not source_path.exists():
        raise HTTPException(400, "The source image no longer exists on disk at its indexed path — rescan the library.")

    effective = settings_store.get_effective_settings(db)
    output_root = effective.get("output_root")
    if not output_root:
        raise HTTPException(400, "OUTPUT_ROOT is not configured. Set it in Settings first.")
    if payload.use_ai_background and not effective.get("openai_api_key"):
        raise HTTPException(
            400, "OpenAI API key is not configured. Set it in Settings first, or turn off "
            "'AI-generated background'.",
        )
    if payload.detect_product_zone and not effective.get("openai_api_key"):
        raise HTTPException(
            400, "OpenAI API key is not configured. Set it in Settings first, or turn off "
            "'Auto-detect product zone'.",
        )
    if payload.recreate_with_ai and not effective.get("openai_api_key"):
        raise HTTPException(
            400, "OpenAI API key is not configured. Set it in Settings first, or turn off "
            "'Recreate with AI'.",
        )

    try:
        category_slug = "general"
        if campaign.category_id:
            category = db.get(Category, campaign.category_id)
            if category is not None:
                category_slug = category.slug

        logo_path = resolve_brand_logo_path(db, brand.id)
        brand_colors = resolve_brand_colors(brand)
        # Build 1 (Part G/H): same resolver used by the Autopilot/Visuals-stage
        # path (services/orchestrator.py::run_visuals_stage) — a manual single-
        # slide render now gets real brand accent/text color, font, and
        # disclaimer text too, instead of this endpoint's own separate set of
        # hardcoded defaults.
        brand_style = resolve_brand_style(db, brand, logo_path=logo_path)

        recreated_image = None
        fidelity_outcome = None
        if payload.recreate_with_ai:
            fmt = get_platform_format(payload.platform_key)
            provider = openai_provider_from_effective_settings(effective)
            fidelity_outcome = await recreate_creative_image_with_fidelity_gate(
                db, image_provider=provider, ai_provider=provider, brand=brand,
                category_id=campaign.category_id, source_image_path=source_path,
                model=effective.get("openai_image_model"), vision_model=effective.get("openai_vision_model") or "gpt-5.1",
                width=fmt.width, height=fmt.height,
                angle=campaign.angle or "", main_promise=campaign.main_promise or "", visual_brief=payload.headline,
                eyebrow="", headline="", body="", cta="",
            )
            recreated_image = fidelity_outcome.image
            if recreated_image is not None:
                # Build 5 repair (Part 1): the manual single-slide render path is
                # "production" scene generation too — same recipe, same version
                # traceability as the Autopilot/Visuals-stage path.
                record_prompt_usage(
                    db, campaign_id=campaign.id, purpose="scene_generation", language="",
                    platform=payload.platform_key, extra={"mode": "full_recreation", "verified": fidelity_outcome.verified},
                )

        generated_background = None
        zone_detection = None
        if recreated_image is None:
            if payload.use_ai_background:
                fmt = get_platform_format(payload.platform_key)
                generated_background = await generate_ai_background(
                    db, image_provider=openai_provider_from_effective_settings(effective), brand=brand,
                    model=effective.get("openai_image_model"), width=fmt.width, height=fmt.height,
                    visual_brief=payload.headline,
                )
                if generated_background is not None:
                    record_prompt_usage(
                        db, campaign_id=campaign.id, purpose="scene_generation", language="",
                        platform=payload.platform_key, extra={"mode": "background_only"},
                    )

            if payload.detect_product_zone:
                zone_detection = await detect_product_zone(
                    ai_provider=openai_provider_from_effective_settings(effective), image_path=source_path,
                    model=effective.get("openai_vision_model") or "gpt-5.1",
                )

        now = datetime.now(timezone.utc)
        output_path = build_slide_output_path(
            output_root=Path(output_root),
            brand_slug=brand.slug,
            category_slug=category_slug,
            campaign_display_id=campaign.display_id,
            year=now.year,
            month=now.month,
            platform_key=payload.platform_key,
            slide_number=payload.slide_number,
        )
        qa_report_path = build_qa_report_path(
            output_root=Path(output_root),
            brand_slug=brand.slug,
            category_slug=category_slug,
            campaign_display_id=campaign.display_id,
            year=now.year,
            month=now.month,
            slide_number=payload.slide_number,
        )

        # As with the Autopilot/Visuals-stage path (services/orchestrator.py::
        # run_visuals_stage), a successful recreation bakes the text directly into
        # the image — pass empty text here so this app's own HTML/CSS layer doesn't
        # draw a second, competing copy of it on top. The CampaignSlide DB row below
        # still stores the real payload text either way, for the record.
        text_baked_in = False  # Build 6R-C1: deterministic renderer owns campaign text
        creative_input = SlideCreativeInput(
            source_image_path=source_path,
            template_id=payload.template_id,
            platform_key=payload.platform_key,
            eyebrow="" if text_baked_in else payload.eyebrow,
            headline="" if text_baked_in else payload.headline,
            body="" if text_baked_in else payload.body,
            cta="" if text_baked_in else payload.cta,
            brand_colors=brand_colors,
            logo_path=logo_path,
            accent_color=brand_style.accent_color,
            text_color=brand_style.text_color,
            font_family=brand_style.primary_font,
            isolate_background=payload.isolate_background,
            generated_background=generated_background,
            product_zone_detection=zone_detection,
            recreated_image=recreated_image,
            # Build 1 (Part H): same never-bake-text-twice rule as the other text
            # fields above (all suppressed via `text_baked_in` when this render
            # used a full AI recreation).
            disclaimer="" if text_baked_in else brand_style.disclaimer_text,
            slide_number=payload.slide_number, total_slides=payload.total_slides,
                             direction_palette=list(brand_colors or []),
                             secondary_font_family=brand_style.secondary_font,
        )
        result = await render_slide(creative_input, output_path=output_path, renderer=get_renderer())
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    qa_report_path.parent.mkdir(parents=True, exist_ok=True)
    qa_dict = result.qa.to_dict()
    if fidelity_outcome is not None:
        qa_dict["product_fidelity"] = {
            "attempted": True,
            "verified": fidelity_outcome.verified,
            "used_recreated_image": recreated_image is not None,
            "attempts": fidelity_outcome.attempts,
            "notes": fidelity_outcome.fidelity_notes,
        }
    qa_report_path.write_text(json.dumps(qa_dict, indent=2))

    slide = next((s for s in campaign.slides if s.slide_number == payload.slide_number), None)
    if slide is None:
        slide = CampaignSlide(campaign_id=campaign.id, slide_number=payload.slide_number, purpose="hero")
        db.add(slide)
    slide.eyebrow = payload.eyebrow
    slide.headline = payload.headline
    slide.body = payload.body
    slide.cta = payload.cta
    slide.source_asset_id = asset.id
    slide.template_id = payload.template_id
    slide.rendered_asset_path = str(result.output_path)

    if not any(ca.asset_id == asset.id for ca in campaign.assets):
        db.add(CampaignAsset(campaign_id=campaign.id, asset_id=asset.id, role="source"))

    db.add(
        CampaignOutput(
            campaign_id=campaign.id,
            kind="qa_report",
            platform=payload.platform_key,
            file_path=str(qa_report_path),
        )
    )

    asset.times_used = (asset.times_used or 0) + 1
    asset.last_used_at = now

    db.commit()

    return {
        "slide_number": payload.slide_number,
        "rendered_asset_path": str(result.output_path),
        "image_url": f"/api/campaigns/{campaign.id}/slides/{payload.slide_number}/image",
        "width": result.width,
        "height": result.height,
        "background_isolator_used": result.background_isolator_used,
        "product_zone_detected": result.product_zone_detected,
        "qa": qa_dict,
    }


@router.get("/{campaign_id}/slides/{slide_number}/image")
def get_campaign_slide_image(campaign_id: str, slide_number: int, db: Session = Depends(get_db)):
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(404, "Campaign not found.")
    slide = next((s for s in campaign.slides if s.slide_number == slide_number), None)
    if slide is None or not slide.rendered_asset_path:
        raise HTTPException(404, "This slide has not been rendered yet.")
    path = Path(slide.rendered_asset_path)
    if not path.exists():
        raise HTTPException(404, "Rendered file is missing from OUTPUT_ROOT — it may have been moved or deleted.")
    return FileResponse(path, media_type="image/png")


@router.post("/{campaign_id}/approve")
def approve_campaign(campaign_id: str, db: Session = Depends(get_db)):
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(404, "Campaign not found.")
    if campaign.status != "REVIEW":
        raise HTTPException(400, f"Campaign must be in REVIEW to approve (currently {campaign.status}).")
    campaign.status = "APPROVED"
    campaign.approved_at = datetime.now(timezone.utc)
    db.commit()
    return {"id": campaign.id, "status": campaign.status}


@router.post("/{campaign_id}/generate")
async def generate_campaign(
    campaign_id: str, use_ai_background: bool = False, detect_product_zone: bool = False,
    recreate_with_ai: bool = False, quality_mode: str = "standard", render_platform_variants: bool = True,
    db: Session = Depends(get_db),
):
    """Kicks off Autopilot end-to-end for this campaign (research -> strategy
    candidates -> novelty filter -> copy -> carousel plan -> creative render) as a
    background job and returns immediately with `{job_id, job_status}` — see this
    module's docstring for why, and services/orchestrator.py::run_autopilot for the
    numbered pipeline steps. Poll `GET /api/jobs/{job_id}` for progress, then
    refetch the campaign once it reaches COMPLETED or FAILED.

    `recreate_with_ai` history: it defaulted to true in rounds 15-16, was flipped
    to false in round 17 because a from-scratch AI recreation of the real photo
    turned out to be unreliable in practice — image models don't reliably keep the
    actual product accurate (they can invent a different product entirely) and
    often render dense on-package text as garbled nonsense, both reported
    directly against real campaigns. Round 17's fix was the `feature_showcase`
    template: a richer deterministic layout (real product photo composited,
    never redrawn) that closed the *visual quality* gap without touching product
    pixels. Round 18 flipped it back to true, paired with a fidelity-gate safety
    net (`recreate_creative_image_with_fidelity_gate` — every recreated image is
    checked against the real source photo, with one corrective retry, before it's
    trusted), reasoning that the gate had made the fabrication risk safe again.

    Build 1 (Part D) flips this back to **false** as the normal-production
    default everywhere (this endpoint, Autopilot, Visuals-only, and manual
    single-slide rendering all already agreed on `false` except this one
    endpoint) — full AI recreation is still fully available and still passes
    through the same fidelity gate, but real usage across rounds 17-20 showed
    the deterministic `feature_showcase` pipeline (real product photo
    composited, never redrawn, with brand colors/typography now actually wired
    in — see Part G/H) is the dependable everyday path, and full recreation is
    better treated as an explicit, opt-in choice (`recreate_with_ai=true`) for
    the specific campaigns that need a fully art-directed look, not something a
    campaign silently gets by default. Nothing about the fidelity gate itself
    changed — `recreate_with_ai=true` still works exactly as before.

    `use_ai_background=true` has each rendered slide's background come from an
    AI-generated scene (style-guided by the brand's uploaded visual-reference
    photos, see POST /brands/{id}/assets) instead of the deterministic brand-color
    gradient — see services/orchestrator.py::generate_ai_background. Only used as
    a fallback when `recreate_with_ai` is off or fails/is unverified for a slide.

    `detect_product_zone=true` has each slide's product placement come from a
    vision-model call per photo instead of the chosen template's one fixed layout
    — see services/orchestrator.py::detect_product_zone. Off by default, and also
    only relevant as a `recreate_with_ai` fallback.
    """
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(404, "Campaign not found.")
    if campaign.status not in ("IDEA", "FAILED"):
        raise HTTPException(
            400,
            f"Campaign must be in IDEA or FAILED status to run Autopilot (currently {campaign.status}).",
        )

    effective = settings_store.get_effective_settings(db)
    api_key = effective.get("openai_api_key")
    if not api_key:
        raise HTTPException(400, "OpenAI API key is not configured. Set it in Settings first.")
    output_root = effective.get("output_root")
    if not output_root:
        raise HTTPException(400, "OUTPUT_ROOT is not configured. Set it in Settings first.")

    job = create_job(db, type_="campaign_generate", campaign_id=campaign.id)

    config = _build_autopilot_config(
        effective, output_root, use_ai_background=use_ai_background, detect_product_zone=detect_product_zone,
        recreate_with_ai=recreate_with_ai, quality_mode=quality_mode, render_platform_variants=render_platform_variants,
    )
    provider = openai_provider_from_effective_settings(effective)
    needs_image_provider = use_ai_background or recreate_with_ai

    async def _job_fn(ctx) -> None:
        session = db_module.SessionLocal()
        try:
            await run_autopilot(
                session,
                campaign_id=campaign.id,
                ai_provider=provider,
                research_provider=provider,
                renderer=get_renderer(),
                config=config,
                progress=ctx,
                image_provider=provider if needs_image_provider else None,
            )
        finally:
            session.close()

    run_job_in_background(job.id, _job_fn)
    return {"job_id": job.id, "job_status": job.status}


# --------------------------------------------------------------------------------
# Campaign Builder advanced mode: the same pipeline as /generate above, split into
# three separately callable stages so a user can generate just a strategy, just
# copy, or just visuals rather than always running everything at once. Each wraps
# one function from services/orchestrator.py — see that module's docstring for why
# each stage persists its output to disk and can run standalone in a later request.
# --------------------------------------------------------------------------------


def _require_campaign(db: Session, campaign_id: str) -> Campaign:
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(404, "Campaign not found.")
    return campaign


def _require_openai_key(db: Session) -> tuple[dict, str]:
    effective = settings_store.get_effective_settings(db)
    api_key = effective.get("openai_api_key")
    if not api_key:
        raise HTTPException(400, "OpenAI API key is not configured. Set it in Settings first.")
    return effective, api_key


def _require_output_root(effective: dict) -> str:
    output_root = effective.get("output_root")
    if not output_root:
        raise HTTPException(400, "OUTPUT_ROOT is not configured. Set it in Settings first.")
    return output_root


def _build_autopilot_config(
    effective: dict, output_root: str, *, use_ai_background: bool = False, detect_product_zone: bool = False,
    recreate_with_ai: bool = False, quality_mode: str = "standard", render_platform_variants: bool = True,
    enable_qa_stage: bool = False, qa_pass_threshold: int = 60, qa_max_retries: int = 2, qa_best_of_n: int = 1,
) -> AutopilotConfig:
    return AutopilotConfig(
        campaign_model=effective.get("openai_campaign_model"),
        research_model=effective.get("openai_research_model"),
        trend_ttl_hours=effective.get("trend_research_ttl_hours"),
        category_ttl_hours=effective.get("category_research_ttl_hours"),
        too_similar_threshold=effective.get("novelty_too_similar_threshold"),
        acceptable_threshold=effective.get("novelty_acceptable_threshold"),
        output_root=Path(output_root),
        image_model=effective.get("openai_image_model") or "gpt-image-1",
        use_ai_background=use_ai_background,
        vision_model=effective.get("openai_vision_model") or "gpt-5.1",
        detect_product_zone=detect_product_zone,
        recreate_with_ai=recreate_with_ai,
        # Build 2, Part D: model role routing — see AutopilotConfig.__post_init__
        # for the fallback each one gets when Settings hasn't been touched
        # (empty string here, same as a config built without these kwargs).
        strategy_model=effective.get("openai_strategy_model") or "",
        copy_model=effective.get("openai_copy_model") or "",
        platform_adapter_model=effective.get("openai_platform_adapter_model") or "",
        creative_director_model=effective.get("openai_creative_director_model") or "",
        draft_image_model=effective.get("openai_draft_image_model") or "",
        premium_image_model=effective.get("openai_premium_image_model") or "",
        creative_qa_model=effective.get("openai_creative_qa_model") or "",
        revision_model=effective.get("openai_revision_model") or "",
        # Build 2, Part K.
        quality_mode=quality_mode,
        render_platform_variants=render_platform_variants,
        # Build 3.
        enable_qa_stage=enable_qa_stage, qa_pass_threshold=qa_pass_threshold, qa_max_retries=qa_max_retries,
        qa_best_of_n=qa_best_of_n,
    )


@router.post("/{campaign_id}/generate/strategy")
async def generate_campaign_strategy(campaign_id: str, db: Session = Depends(get_db)):
    """Advanced-mode partial run: research + strategy candidates + novelty filter
    only (services/orchestrator.py::run_strategy_stage) — stops at BRIEF_READY
    without writing copy or rendering anything. Needs an OpenAI API key. Runs as a
    background job — see this module's docstring — so the response comes back
    immediately with `{job_id, job_status}` for the frontend to poll.
    """
    campaign = _require_campaign(db, campaign_id)
    effective, api_key = _require_openai_key(db)
    output_root = _require_output_root(effective)

    job = create_job(db, type_="campaign_generate_strategy", campaign_id=campaign.id)
    config = _build_autopilot_config(effective, output_root)
    provider = openai_provider_from_effective_settings(effective)

    async def _job_fn(ctx) -> None:
        session = db_module.SessionLocal()
        try:
            await run_strategy_stage(
                session, campaign_id=campaign.id, ai_provider=provider, research_provider=provider,
                config=config, progress=ctx,
            )
        finally:
            session.close()

    run_job_in_background(job.id, _job_fn)
    return {"job_id": job.id, "job_status": job.status}


@router.post("/{campaign_id}/generate/copy")
async def generate_campaign_copy(campaign_id: str, db: Session = Depends(get_db)):
    """Advanced-mode partial run: creative brief + copy + carousel plan only
    (services/orchestrator.py::run_copy_stage), reading back the Strategy stage's
    already-persisted output rather than re-deriving it — 400s with a clear message
    if Strategy hasn't run yet for this campaign. Needs an OpenAI API key. Runs as a
    background job — see this module's docstring — so the response comes back
    immediately with `{job_id, job_status}` for the frontend to poll.
    """
    campaign = _require_campaign(db, campaign_id)
    effective, api_key = _require_openai_key(db)
    output_root = _require_output_root(effective)
    try:
        check_copy_stage_prerequisite(db, campaign.id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    job = create_job(db, type_="campaign_generate_copy", campaign_id=campaign.id)
    config = _build_autopilot_config(effective, output_root)
    provider = openai_provider_from_effective_settings(effective)

    async def _job_fn(ctx) -> None:
        session = db_module.SessionLocal()
        try:
            await run_copy_stage(
                session, campaign_id=campaign.id, ai_provider=provider, config=config, progress=ctx,
            )
        finally:
            session.close()

    run_job_in_background(job.id, _job_fn)
    return {"job_id": job.id, "job_status": job.status}


@router.post("/{campaign_id}/generate/visuals")
async def generate_campaign_visuals(
    campaign_id: str, use_ai_background: bool = False, detect_product_zone: bool = False,
    recreate_with_ai: bool = False, quality_mode: str = "standard", render_platform_variants: bool = True,
    db: Session = Depends(get_db),
):
    """Advanced-mode partial run: renders every planned slide from the Copy
    stage's persisted carousel plan (services/orchestrator.py::run_visuals_stage) —
    400s with a clear message if Copy hasn't run yet for this campaign. Needs
    **no** OpenAI key by default — this stage only reads back already-generated
    text and composites real photos, same as the manual `/slides/render` endpoint.

    `recreate_with_ai=true` opts into a full AI recreation of each slide's photo
    (product included, not just a new backdrop), verified against the real source
    photo before it's trusted — see services/orchestrator.py::
    recreate_creative_image_with_fidelity_gate. Unlike `/generate` above, this
    stays **off by default** here, deliberately, to preserve Visuals-only's
    documented "needs no OpenAI key at all" property for anyone iterating without
    one. `use_ai_background=true` opts into an AI-generated scene background per
    slide (see generate_campaign's docstring above) — only used as a fallback when
    `recreate_with_ai` is off, fails, or isn't verified. `detect_product_zone=true`
    opts into a per-photo vision-model product placement (see generate_campaign's
    docstring above) — also only relevant as a fallback. Any of the three needs an
    OpenAI key when run standalone; `recreate_with_ai` additionally needs the same
    key to run its fidelity check (both roles are the same `OpenAIProvider`
    instance).

    Runs as a background job — see this module's docstring — so the response
    comes back immediately with `{job_id, job_status}` for the frontend to poll.
    """
    campaign = _require_campaign(db, campaign_id)
    effective = settings_store.get_effective_settings(db)
    output_root = _require_output_root(effective)
    try:
        check_visuals_stage_prerequisite(db, campaign.id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    image_provider = None
    ai_provider = None
    if use_ai_background or detect_product_zone or recreate_with_ai:
        _, api_key = _require_openai_key(db)
        provider = openai_provider_from_effective_settings(effective)
        if use_ai_background or recreate_with_ai:
            image_provider = provider
        if detect_product_zone or recreate_with_ai:
            # recreate_with_ai needs ai_provider too now — it's what runs the
            # product-fidelity check (see recreate_creative_image_with_fidelity_
            # gate); without it, run_visuals_stage fails closed and skips
            # recreation entirely rather than trust an unverified image.
            ai_provider = provider

    job = create_job(db, type_="campaign_generate_visuals", campaign_id=campaign.id)
    config = _build_autopilot_config(
        effective, output_root, use_ai_background=use_ai_background, detect_product_zone=detect_product_zone,
        recreate_with_ai=recreate_with_ai, quality_mode=quality_mode, render_platform_variants=render_platform_variants,
    )

    async def _job_fn(ctx) -> None:
        session = db_module.SessionLocal()
        try:
            await run_visuals_stage(
                session, campaign_id=campaign.id, renderer=get_renderer(), config=config, progress=ctx,
                image_provider=image_provider, ai_provider=ai_provider,
            )
        finally:
            session.close()

    run_job_in_background(job.id, _job_fn)
    return {"job_id": job.id, "job_status": job.status}


@router.post("/{campaign_id}/generate/qa")
async def generate_campaign_qa(
    campaign_id: str, qa_pass_threshold: int = 60, qa_max_retries: int = 2, qa_best_of_n: int = 1,
    use_ai_background: bool = False, db: Session = Depends(get_db),
):
    """Build 3: evaluates every already-rendered/scripted `PlatformCampaignVariant`
    (services/qa_engine.py::run_qa_stage) — 400s with a clear message if Visuals
    hasn't run yet for this campaign (no variants to evaluate). Deterministic
    technical/platform checks (Parts A/D) always run; the multimodal creative
    critic, language QA, and targeted revisions (Parts B/C/E) additionally need an
    OpenAI key — without one, every variant still gets a real technical/platform
    pass but settles at NEEDS_REVIEW rather than a false PASS (see
    `_creative_overall_and_fails`'s docstring).

    `qa_max_retries` (Part H) is how many targeted-revision rounds a failing
    variant gets before settling at NEEDS_REVIEW; `qa_best_of_n` (Part G) is how
    many independent candidates a creative-direction revision generates per round,
    keeping whichever scores best. `use_ai_background=true` lets a targeted
    creative-direction revision (Part E) regenerate a real new AI scene for the
    variant it's fixing — same opt-in-only-with-a-key rule as `/generate/visuals`;
    left off, a creative-direction revision still updates the stored direction and
    re-renders, just without paying for a fresh AI background. Runs as a
    background job — see this module's docstring — so the response comes back
    immediately with `{job_id, job_status}` for the frontend to poll; check
    results via `GET /{campaign_id}/variants`.
    """
    campaign = _require_campaign(db, campaign_id)
    effective = settings_store.get_effective_settings(db)
    output_root = _require_output_root(effective)
    if not get_platform_campaign_variants(db, campaign.id):
        raise HTTPException(
            400, "No platform/language variants found for this campaign — run Visuals before running QA."
        )
    ai_provider = None
    image_provider = None
    if effective.get("openai_api_key"):
        provider = openai_provider_from_effective_settings(effective)
        ai_provider = provider
        if use_ai_background:
            image_provider = provider

    job = create_job(db, type_="campaign_generate_qa", campaign_id=campaign.id)
    config = _build_autopilot_config(
        effective, output_root, use_ai_background=use_ai_background, qa_pass_threshold=qa_pass_threshold,
        qa_max_retries=qa_max_retries, qa_best_of_n=qa_best_of_n,
    )

    async def _job_fn(ctx) -> None:
        session = db_module.SessionLocal()
        try:
            await run_qa_stage(
                session, campaign_id=campaign.id, renderer=get_renderer(), config=config,
                image_provider=image_provider, ai_provider=ai_provider,
            )
        finally:
            session.close()

    run_job_in_background(job.id, _job_fn)
    return {"job_id": job.id, "job_status": job.status}


# --------------------------------------------------------------------------------
# Campaign <-> Opportunity: the manual "draft a post for this community" workflow
# (brief section 46). No auto-posting into Groups the brand doesn't administer —
# see README.md for why that's a Meta platform rule, not a gap in this app — so
# this is: attach a real, discovered community to a campaign, get a draft post
# tailored to it, and track by hand whether it's actually been posted.
# --------------------------------------------------------------------------------


def _default_community_post_text(campaign: Campaign, opportunity: Opportunity) -> str:
    parts = [p for p in [campaign.hook, campaign.main_promise, campaign.cta] if p]
    body = "\n\n".join(parts) if parts else (campaign.angle or "New from our store.")
    if opportunity.promo_allowed is False:
        body += (
            "\n\n(This community typically doesn't allow direct promotion — lead with "
            "value or conversation, and only mention the product if it comes up naturally.)"
        )
    return body


class AttachOpportunityRequest(BaseModel):
    opportunity_id: str
    community_post_text: str | None = None


def _campaign_opportunity_out(co: CampaignOpportunity, opportunity: Opportunity) -> dict:
    return {
        "id": co.id,
        "opportunity_id": opportunity.id,
        "platform": opportunity.platform,
        "name": opportunity.name,
        "url": opportunity.url,
        "promo_allowed": opportunity.promo_allowed,
        "posting_rules": opportunity.posting_rules,
        "community_post_text": co.community_post_text,
        "posted": co.posted,
        "posted_at": co.posted_at,
    }


@router.get("/{campaign_id}/opportunities")
def list_campaign_opportunities(campaign_id: str, db: Session = Depends(get_db)):
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(404, "Campaign not found.")
    rows = db.query(CampaignOpportunity).filter(CampaignOpportunity.campaign_id == campaign_id).all()
    out = []
    for co in rows:
        opp = db.get(Opportunity, co.opportunity_id)
        if opp is not None:
            out.append(_campaign_opportunity_out(co, opp))
    return out


@router.get("/{campaign_id}/variants")
def list_campaign_variants(campaign_id: str, db: Session = Depends(get_db)):
    """Build 2, Part F — every `PlatformCampaignVariant` rendered for this campaign:
    one row per selected (target_platform, language, content_type) combination,
    including the PRIMARY combination (which reuses the legacy-path slide/QA
    assets rather than re-rendering them — see `_render_additional_platform_variants`
    in services/orchestrator.py).
    """
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(404, "Campaign not found.")
    variants = get_platform_campaign_variants(db, campaign_id)
    return [
        {
            "id": v.id,
            "target_platform": v.target_platform,
            "language": v.language,
            "content_type": v.content_type,
            "render_format_key": v.render_format_key,
            "status": v.status,
            "slide_asset_paths": v.slide_asset_paths,
            "copy_language": v.copy_language,
            "creative_direction": v.creative_direction,
            "video_concept": v.video_concept,
            "qa_report_paths": v.qa_report_paths,
            "shared_scene_source": v.shared_scene_source,
            "notes": v.notes,
            # Build 3 (Platform + Language Aware Multimodal QA) — carry-forward
            # requirement 2: this state is per-variant, never only aggregated
            # onto the parent Campaign, so the frontend can show e.g.
            # "Instagram/pt-BR PASS, Instagram/en NEEDS_REVIEW" side by side.
            "qa_status": v.qa_status,
            "qa_scores": v.qa_scores,
            "qa_hard_fails": v.qa_hard_fails,
            "qa_attempts": v.qa_attempts,
            "qa_evidence_paths": v.qa_evidence_paths,
            "qa_versions": v.qa_versions,
            "qa_notes": v.qa_notes,
            # Build 4 — carry-forward requirement 4: a genuinely separate axis
            # from `qa_status` above (see `models/campaign.py::
            # PlatformCampaignVariant.human_review_status`'s own docstring).
            "human_review_status": v.human_review_status,
            "created_at": v.created_at,
            "updated_at": v.updated_at,
        }
        for v in variants
    ]


# --------------------------------------------------------------------------------
# Build 4 — HUMAN APPROVAL + PLATFORM/LANGUAGE FEEDBACK LEARNING.
# --------------------------------------------------------------------------------

class ReviewActionRequest(BaseModel):
    level: str  # "CAMPAIGN" | "PLATFORM_VARIANT" | "ASSET"
    action: str  # "APPROVE" | "REJECT" | "REQUEST_REVISION"
    platform_campaign_variant_id: str | None = None  # required for PLATFORM_VARIANT/ASSET, omitted for CAMPAIGN
    asset_ref: str = ""  # only meaningful for level="ASSET"
    reason_code: str = ""  # one of data/feedback_reasons.py::FEEDBACK_REASON_CODES, or "" for free-text only
    reason_text: str = ""
    # Only consulted when action="REQUEST_REVISION" at level in
    # ("PLATFORM_VARIANT", "ASSET") — whether the automatically-applied
    # revision may pay for a fresh AI background, mirroring
    # `/generate/qa`'s own `use_ai_background` flag.
    use_ai_background: bool = False


def _review_feedback_out(fb: ReviewFeedback) -> dict:
    return {
        "id": fb.id,
        "campaign_id": fb.campaign_id,
        "platform_campaign_variant_id": fb.platform_campaign_variant_id,
        "level": fb.level,
        "asset_ref": fb.asset_ref,
        "action": fb.action,
        "reason_code": fb.reason_code,
        "reason_text": fb.reason_text,
        "platform": fb.platform,
        "language": fb.language,
        "content_type": fb.content_type,
        "objective": fb.objective,
        "reviewed_qa_status": fb.reviewed_qa_status,
        "reviewed_qa_scores": fb.reviewed_qa_scores,
        "reviewed_qa_hard_fails": fb.reviewed_qa_hard_fails,
        "reviewed_qa_attempts": fb.reviewed_qa_attempts,
        "reviewed_qa_evidence_paths": fb.reviewed_qa_evidence_paths,
        "reviewed_qa_versions": fb.reviewed_qa_versions,
        "reviewed_prompt_versions": fb.reviewed_prompt_versions,
        "reviewed_copy_snapshot": fb.reviewed_copy_snapshot,
        "reviewed_creative_direction": fb.reviewed_creative_direction,
        "reviewed_slide_asset_paths": fb.reviewed_slide_asset_paths,
        "reviewed_video_concept": fb.reviewed_video_concept,
        "revision_of_feedback_id": fb.revision_of_feedback_id,
        "created_at": fb.created_at,
        "updated_at": fb.updated_at,
    }


@router.post("/{campaign_id}/review", status_code=201)
async def submit_campaign_review(campaign_id: str, payload: ReviewActionRequest, db: Session = Depends(get_db)):
    """Build 4's one unified review action, for all three levels the spec
    names (campaign / platform+language variant / individual asset-slide) —
    see `services/review_engine.py::record_review_feedback` for the full
    behavior (traceability snapshot, lineage auto-linking, and the exact
    separation from `qa_status` this always preserves).

    A `REQUEST_REVISION` action against a specific variant (level in
    `("PLATFORM_VARIANT", "ASSET")`) additionally kicks off the actual
    revision as a background job — see `services/review_engine.py::
    apply_requested_revision`, which reuses Build 3's existing targeted-
    revision machinery (never a second, parallel pipeline). A campaign-level
    `REQUEST_REVISION` (no single variant to revise) records the feedback
    only — deliberately out of scope for this build to auto-apply "revise
    everything" across every platform/language at once, matching Build 3's
    own "never a blind full-campaign regeneration" discipline; the owner is
    expected to follow up with variant-level requests for whichever
    executions actually need work.
    """
    campaign = _require_campaign(db, campaign_id)
    if payload.level not in LEVELS:
        raise HTTPException(400, f"level must be one of {LEVELS}.")
    if payload.action not in ("APPROVE", "REJECT", "REQUEST_REVISION"):
        raise HTTPException(400, "action must be one of APPROVE, REJECT, REQUEST_REVISION.")
    if payload.reason_code and payload.reason_code not in FEEDBACK_REASON_CODES:
        raise HTTPException(400, f"reason_code, if set, must be one of {FEEDBACK_REASON_CODES}.")

    variant = None
    if payload.level in ("PLATFORM_VARIANT", "ASSET"):
        if not payload.platform_campaign_variant_id:
            raise HTTPException(400, f"platform_campaign_variant_id is required for level={payload.level!r}.")
        variant = db.get(PlatformCampaignVariant, payload.platform_campaign_variant_id)
        if variant is None or variant.campaign_id != campaign.id:
            raise HTTPException(404, "platform_campaign_variant_id not found on this campaign.")
    elif payload.platform_campaign_variant_id:
        raise HTTPException(400, "platform_campaign_variant_id must not be set for level='CAMPAIGN'.")

    try:
        feedback = record_review_feedback(
            db, campaign=campaign, variant=variant, level=payload.level, asset_ref=payload.asset_ref,
            action=payload.action, reason_code=payload.reason_code, reason_text=payload.reason_text,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    job_id = None
    if payload.action == "REQUEST_REVISION" and variant is not None:
        effective = settings_store.get_effective_settings(db)
        output_root = _require_output_root(effective)
        ai_provider = None
        image_provider = None
        if effective.get("openai_api_key"):
            provider = openai_provider_from_effective_settings(effective)
            ai_provider = provider
            if payload.use_ai_background:
                image_provider = provider
        config = _build_autopilot_config(effective, output_root, use_ai_background=payload.use_ai_background)
        job = create_job(db, type_="campaign_review_revision", campaign_id=campaign.id)
        job_id = job.id
        variant_id = variant.id
        feedback_id = feedback.id

        async def _job_fn(ctx) -> None:
            session = db_module.SessionLocal()
            try:
                fb_row = session.get(ReviewFeedback, feedback_id)
                variant_row = session.get(PlatformCampaignVariant, variant_id)
                campaign_row = session.get(Campaign, campaign.id)
                if fb_row is not None and variant_row is not None and campaign_row is not None:
                    await apply_requested_revision(
                        session, campaign=campaign_row, variant=variant_row, feedback=fb_row, config=config,
                        renderer=get_renderer(), image_provider=image_provider, ai_provider=ai_provider,
                    )
            finally:
                session.close()

        run_job_in_background(job.id, _job_fn)

    return {"feedback": _review_feedback_out(feedback), "job_id": job_id}


@router.get("/{campaign_id}/review-feedback")
def list_campaign_review_feedback(campaign_id: str, db: Session = Depends(get_db)):
    """Newest first, with lineage (`revision_of_feedback_id`) intact — see
    `services/review_engine.py::record_review_feedback`'s auto-linking.
    """
    _require_campaign(db, campaign_id)
    rows = (
        db.query(ReviewFeedback)
        .filter(ReviewFeedback.campaign_id == campaign_id)
        .order_by(ReviewFeedback.created_at.desc())
        .all()
    )
    return [_review_feedback_out(fb) for fb in rows]


@router.get("/{campaign_id}/review-summary")
def get_campaign_review_summary(campaign_id: str, db: Session = Depends(get_db)):
    """Carry-forward requirement 4: `campaign.human_review_status` is never
    written FROM variant-level activity (see `record_review_feedback`) — this
    endpoint is the read-only rollup instead, computed fresh on every call,
    that never writes back to any row. Preserves "child truth": each
    variant's own `human_review_status`/`qa_status` are returned exactly as
    stored, never collapsed or overridden by this summary.
    """
    campaign = _require_campaign(db, campaign_id)
    variants = get_platform_campaign_variants(db, campaign_id)
    return {
        "campaign_id": campaign.id,
        "campaign_human_review_status": campaign.human_review_status,
        "variants": [
            {
                "id": v.id,
                "target_platform": v.target_platform,
                "language": v.language,
                "content_type": v.content_type,
                "human_review_status": v.human_review_status,
                "qa_status": v.qa_status,
            }
            for v in variants
        ],
        "variant_counts_by_human_review_status": {
            status: sum(1 for v in variants if v.human_review_status == status)
            for status in ("PENDING", "APPROVED", "REJECTED", "REVISION_REQUESTED")
        },
    }


@router.post("/{campaign_id}/opportunities", status_code=201)
def attach_campaign_opportunity(campaign_id: str, payload: AttachOpportunityRequest, db: Session = Depends(get_db)):
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(404, "Campaign not found.")
    opportunity = db.get(Opportunity, payload.opportunity_id)
    if opportunity is None or opportunity.brand_id != campaign.brand_id:
        raise HTTPException(404, "Opportunity not found for this brand.")

    existing = (
        db.query(CampaignOpportunity)
        .filter(
            CampaignOpportunity.campaign_id == campaign_id,
            CampaignOpportunity.opportunity_id == opportunity.id,
        )
        .one_or_none()
    )
    text = payload.community_post_text or _default_community_post_text(campaign, opportunity)
    if existing is not None:
        existing.community_post_text = text
        db.commit()
        db.refresh(existing)
        return _campaign_opportunity_out(existing, opportunity)

    co = CampaignOpportunity(campaign_id=campaign_id, opportunity_id=opportunity.id, community_post_text=text)
    db.add(co)
    db.commit()
    db.refresh(co)
    return _campaign_opportunity_out(co, opportunity)


class UpdateCampaignOpportunityRequest(BaseModel):
    community_post_text: str | None = None
    posted: bool | None = None


@router.patch("/{campaign_id}/opportunities/{campaign_opportunity_id}")
def update_campaign_opportunity(
    campaign_id: str, campaign_opportunity_id: str, payload: UpdateCampaignOpportunityRequest,
    db: Session = Depends(get_db),
):
    co = db.get(CampaignOpportunity, campaign_opportunity_id)
    if co is None or co.campaign_id != campaign_id:
        raise HTTPException(404, "Campaign opportunity not found.")
    opportunity = db.get(Opportunity, co.opportunity_id)
    if payload.community_post_text is not None:
        co.community_post_text = payload.community_post_text
    if payload.posted is not None:
        co.posted = payload.posted
        if payload.posted:
            co.posted_at = datetime.now(timezone.utc)
            if opportunity is not None:
                opportunity.last_posted_at = co.posted_at
        else:
            co.posted_at = None
    db.commit()
    db.refresh(co)
    return _campaign_opportunity_out(co, opportunity) if opportunity else {"id": co.id, "posted": co.posted}


# --------------------------------------------------------------------------------
# Campaign -> Publication: logging where a campaign actually got posted (brief
# sections 36-38, Phase 9). Creating a Publication is a manual record of "this
# went out" for a campaign that's actually finished (approved/exported/scheduled/
# published) — not something you can log against a half-built IDEA campaign.
# Publication *status* changes and metric entry live in api/publishing.py, which
# owns the publications resource once it exists; this is just the "attach a new
# one to this campaign" entry point, mirroring the opportunities sub-resource above.
# --------------------------------------------------------------------------------

_PUBLISHABLE_STATUSES = {"APPROVED", "EXPORTED", "SCHEDULED", "PUBLISHED"}


class PublicationCreate(BaseModel):
    provider: str
    external_post_id: str = ""
    url: str = ""
    status: str = "draft"
    published_at: datetime | None = None


def _publication_out(pub: Publication) -> dict:
    return {
        "id": pub.id,
        "campaign_id": pub.campaign_id,
        "provider": pub.provider,
        "external_post_id": pub.external_post_id,
        "url": pub.url,
        "status": pub.status,
        "published_at": pub.published_at,
        "created_at": pub.created_at,
    }


@router.get("/{campaign_id}/publications")
def list_campaign_publications(campaign_id: str, db: Session = Depends(get_db)):
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(404, "Campaign not found.")
    rows = (
        db.query(Publication)
        .filter(Publication.campaign_id == campaign_id)
        .order_by(Publication.created_at.desc())
        .all()
    )
    return [_publication_out(p) for p in rows]


@router.post("/{campaign_id}/publications", status_code=201)
def create_campaign_publication(campaign_id: str, payload: PublicationCreate, db: Session = Depends(get_db)):
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(404, "Campaign not found.")
    if campaign.status not in _PUBLISHABLE_STATUSES:
        raise HTTPException(
            400,
            f"Campaign must be approved before logging a publication (current status: {campaign.status}).",
        )

    pub = Publication(
        campaign_id=campaign_id,
        provider=payload.provider,
        external_post_id=payload.external_post_id,
        url=payload.url,
        status=payload.status,
        published_at=payload.published_at,
    )
    db.add(pub)

    if payload.status == "published":
        campaign.status = "PUBLISHED"
        if pub.published_at is None:
            pub.published_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(pub)
    return _publication_out(pub)


# --------------------------------------------------------------------------------
# Auto-publish (brief sections 47/48): actually posting a rendered creative to the
# brand's own Facebook Page / linked Instagram Business account via Meta's Graph
# API — distinct from `POST /{id}/publications` above, which only *logs* that a
# post happened somewhere (including a Facebook Group, which no app can auto-post
# into — see services/opportunities.py). This endpoint calls the real
# `PublishingProvider` (services/publishing/meta_provider.py) that section 47/48
# had been a documented-but-unimplemented extension point for since round 1.
# --------------------------------------------------------------------------------


class AutoPublishRequest(BaseModel):
    provider: str  # facebook_page | instagram
    slide_number: int = 1


@router.post("/{campaign_id}/publish")
async def auto_publish_campaign(campaign_id: str, payload: AutoPublishRequest, db: Session = Depends(get_db)):
    """Posts a rendered slide to the brand's own Facebook Page or linked Instagram
    Business account. Requires the campaign to already be approved (same status
    gate as logging a manual publication) and a rendered slide to exist for
    `slide_number`. The caption defaults to whatever the Copy stage generated
    (`get_campaign_copy`); nothing is invented if Copy was never run.

    On success, this also creates a `Publication` row (provider/external_post_id/
    url/status=published) and bumps the campaign to `PUBLISHED`, exactly like
    logging one by hand — so the Publishing panel and Analytics see it either way.
    On failure, nothing is recorded: a failed post attempt did not happen, and the
    real Graph API error is surfaced via a 502 rather than swallowed.
    """
    campaign = _require_campaign(db, campaign_id)
    if campaign.status not in _PUBLISHABLE_STATUSES:
        raise HTTPException(
            400, f"Campaign must be approved before publishing (current status: {campaign.status}).",
        )
    if payload.provider not in ("facebook_page", "instagram"):
        raise HTTPException(400, "provider must be 'facebook_page' or 'instagram'.")

    effective = settings_store.get_effective_settings(db)
    access_token = effective.get("facebook_page_access_token")
    if not access_token:
        raise HTTPException(
            400, "Facebook Page access token is not configured. Set it in Settings first — see the README's "
            "'Facebook Page / Instagram auto-publish' section.",
        )

    public_asset_url: str | None = None
    if payload.provider == "facebook_page":
        external_id = effective.get("facebook_page_id")
        if not external_id:
            raise HTTPException(400, "Facebook Page ID is not configured. Set it in Settings first.")
    else:
        external_id = effective.get("instagram_business_account_id")
        if not external_id:
            raise HTTPException(400, "Instagram Business Account ID is not configured. Set it in Settings first.")
        public_base_url = effective.get("public_base_url")
        if public_base_url:
            public_asset_url = (
                f"{public_base_url.rstrip('/')}/api/campaigns/{campaign_id}/slides/{payload.slide_number}/image"
            )

    slide = next((s for s in campaign.slides if s.slide_number == payload.slide_number), None)
    if slide is None or not slide.rendered_asset_path or not Path(slide.rendered_asset_path).exists():
        raise HTTPException(400, f"Slide {payload.slide_number} has not been rendered yet.")

    campaign_copy = get_campaign_copy(db, campaign.id)
    caption = campaign_copy.caption if campaign_copy else (campaign.angle or campaign.main_promise or "")
    hashtags = campaign_copy.hashtags if campaign_copy else []

    target = PublishTarget(provider=payload.provider, external_id=external_id, public_asset_url=public_asset_url)
    copy = PublishCopy(caption=caption, hashtags=hashtags)
    provider = MetaPublishingProvider(access_token, api_version=get_settings().meta_graph_api_version)

    result = await provider.publish(target=target, assets=[Path(slide.rendered_asset_path)], copy=copy)
    if not result.success:
        raise HTTPException(502, result.error or "Publish failed for an unknown reason.")

    pub = Publication(
        campaign_id=campaign.id,
        provider=payload.provider,
        external_post_id=result.external_post_id or "",
        url=result.url or "",
        status="published",
        published_at=datetime.now(timezone.utc),
    )
    db.add(pub)
    campaign.status = "PUBLISHED"
    db.commit()
    db.refresh(pub)
    return _publication_out(pub)
