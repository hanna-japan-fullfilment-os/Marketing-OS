from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db import Base
from ._mixins import TimestampMixin, UUIDPKMixin

CAMPAIGN_STATUSES = (
    "IDEA", "RESEARCHING", "BRIEF_READY", "COPY_READY", "GENERATING", "REVIEW",
    "APPROVED", "EXPORTED", "SCHEDULED", "PUBLISHED", "ARCHIVED", "FAILED",
)


class CampaignSequence(Base, UUIDPKMixin):
    """Backs human-readable sequential campaign IDs, e.g. HANNA-SKIN-000123."""
    __tablename__ = "campaign_sequences"
    __table_args__ = (UniqueConstraint("brand_id", "category_slug", name="uq_seq_brand_category"),)

    brand_id: Mapped[str] = mapped_column(ForeignKey("brands.id", ondelete="CASCADE"), index=True)
    category_slug: Mapped[str] = mapped_column(String(200))
    next_value: Mapped[int] = mapped_column(Integer, default=1)


class Campaign(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "campaigns"

    display_id: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    brand_id: Mapped[str] = mapped_column(ForeignKey("brands.id", ondelete="CASCADE"), index=True)
    category_id: Mapped[str | None] = mapped_column(ForeignKey("categories.id", ondelete="SET NULL"), nullable=True)
    product_id: Mapped[str | None] = mapped_column(ForeignKey("products.id", ondelete="SET NULL"), nullable=True)

    objective: Mapped[str] = mapped_column(String(30), default="awareness")
    audience: Mapped[str] = mapped_column(Text, default="")
    funnel_stage: Mapped[str] = mapped_column(String(30), default="")
    channels: Mapped[list] = mapped_column(JSON, default=list)

    angle: Mapped[str] = mapped_column(String(100), default="")
    strategy_type_id: Mapped[str | None] = mapped_column(
        ForeignKey("campaign_strategy_types.id", ondelete="SET NULL"), nullable=True, index=True
    )
    triggered_by_event_id: Mapped[str | None] = mapped_column(
        ForeignKey("competitor_events.id", ondelete="SET NULL"), nullable=True
    )
    hook: Mapped[str] = mapped_column(Text, default="")
    main_promise: Mapped[str] = mapped_column(Text, default="")
    cta: Mapped[str] = mapped_column(String(300), default="")
    content_type: Mapped[str] = mapped_column(String(50), default="")
    template_id: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Legacy single-locale field, kept only for backward-compatible display on
    # rows created before `languages` (below) existed — never authoritative for
    # new logic. `languages` is the real, canonical field as of Build 1 of the
    # Multi-Platform + Bilingual Quality Recovery Program: a free-text
    # `language` column couldn't represent "pt-BR AND en" and had no fixed set
    # of allowed values, so a caller had no way to know if "portuguese" and
    # "pt-BR" meant the same campaign. See `data/platform_capabilities.py::
    # SUPPORTED_LANGUAGES` for the only two canonical values, and `run_copy_stage`
    # (services/orchestrator.py), which reads `languages` (falling back to
    # `[language]` for a pre-migration row that never got `languages` set).
    language: Mapped[str] = mapped_column(String(20), default="pt-BR")
    # Canonical, validated list of locales this campaign generates copy for —
    # any non-empty subset of `SUPPORTED_LANGUAGES` (`["pt-BR"]`, `["en"]`, or
    # `["pt-BR", "en"]`). Each language gets its own independently AI-generated,
    # natively-written CampaignCopy/CarouselPlan variant (never a blind
    # translation of another language's copy — see run_copy_stage's per-
    # language loop). Defaults to `["pt-BR"]` so every pre-existing campaign's
    # effective behavior is unchanged (single-language, Portuguese).
    languages: Mapped[list] = mapped_column(JSON, default=lambda: ["pt-BR"])
    geography: Mapped[str] = mapped_column(String(100), default="")
    campaign_family: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Which real-world social platform(s) this campaign is being planned for —
    # e.g. ["instagram", "facebook"] — a MARKETING platform identifier from
    # `data/platform_capabilities.py::PLATFORM_CAPABILITIES`, distinct from
    # `platform_key` below (a rendering FORMAT/pixel size). A campaign can target
    # several platforms; copy generation is told which ones so it can write with
    # each platform's real content-type conventions in mind (see
    # `_platform_requirements_note` in services/orchestrator.py). Defaults to
    # `["instagram"]` so every pre-existing campaign's effective behavior (which
    # always implicitly meant Instagram) is unchanged.
    target_platforms: Mapped[list] = mapped_column(JSON, default=lambda: ["instagram"])

    status: Mapped[str] = mapped_column(String(20), default="IDEA", index=True)
    research_run_id: Mapped[str | None] = mapped_column(ForeignKey("research_runs.id", ondelete="SET NULL"), nullable=True)

    # How many slides Autopilot's carousel planner should aim for on this campaign.
    # NULL (the default) preserves the original behavior: the model plans "up to"
    # AutopilotConfig.max_slides on its own judgment, which can genuinely be fewer
    # than the cap for a concept that only needs one hero image. Set this to make
    # the planner target an exact count instead — see run_copy_stage in
    # services/orchestrator.py.
    target_slide_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Which real platform/format this campaign's slides render at — one of
    # `services/creative/templates.py`'s PLATFORM_FORMATS keys (e.g.
    # "instagram_square", "instagram_portrait", "instagram_story",
    # "facebook_feed"). NULL preserves the original behavior: every render call
    # falls back to AutopilotConfig.platform_key ("instagram_square"), exactly as
    # before this column existed, so no pre-existing campaign changes shape.
    # Set this so Autopilot/Campaign Builder — not just the manual single-slide
    # render panel, which already had its own per-render picker — renders a whole
    # campaign at the size the user actually intends to post it at. Validated
    # against the real registry (not just any string) in the PATCH endpoint.
    platform_key: Mapped[str | None] = mapped_column(String(50), nullable=True)

    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")

    # --- Build 4 (Human Approval + Platform/Language Feedback Learning) ------
    # A SEPARATE concept from `status` above (the campaign's own production
    # lifecycle: IDEA -> ... -> PUBLISHED) and from `approved_at`/the existing
    # `/approve` endpoint (which only ever gate REVIEW -> APPROVED, a workflow
    # checkpoint, not a quality verdict). `human_review_status` is the owner's
    # OWN explicit, campaign-wide review verdict — set ONLY by a `level=
    # "CAMPAIGN"` `ReviewFeedback` action (`services/review_engine.py`), never
    # inferred or aggregated automatically from child `PlatformCampaignVariant.
    # human_review_status` values below — carry-forward requirement 4's own
    # instruction ("Parent Campaign status may aggregate these, but must
    # preserve child truth") is honored by never overwriting this field from
    # variant-level activity; a computed, read-only rollup across variants is
    # what `GET /api/campaigns/{id}/review-summary` exposes instead.
    # PENDING (no explicit campaign-level review yet) | APPROVED | REJECTED |
    # REVISION_REQUESTED.
    human_review_status: Mapped[str] = mapped_column(String(20), default="PENDING")

    assets: Mapped[list["CampaignAsset"]] = relationship(back_populates="campaign", cascade="all, delete-orphan")
    slides: Mapped[list["CampaignSlide"]] = relationship(
        back_populates="campaign", cascade="all, delete-orphan", order_by="CampaignSlide.slide_number"
    )
    discovery_products: Mapped[list["CampaignDiscoveryProduct"]] = relationship(
        back_populates="campaign", cascade="all, delete-orphan",
        order_by="CampaignDiscoveryProduct.sort_order",
    )
    outputs: Mapped[list["CampaignOutput"]] = relationship(back_populates="campaign", cascade="all, delete-orphan")
    fingerprint: Mapped["CampaignFingerprint | None"] = relationship(
        back_populates="campaign", uselist=False, cascade="all, delete-orphan"
    )


class CampaignAsset(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "campaign_assets"

    campaign_id: Mapped[str] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), index=True)
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(20), default="source")  # source | reference

    campaign: Mapped[Campaign] = relationship(back_populates="assets")
    asset = relationship("Asset")


class CampaignDiscoveryProduct(Base, UUIDPKMixin, TimestampMixin):
    """Round 19: the hand-picked, ordered product list for a "discovery" campaign
    (many different products, one slide each) — as opposed to a "deep-dive"
    campaign (`Campaign.product_id` set), which recreates ONE product across many
    slides. Only meaningful when `Campaign.product_id IS NULL`; see
    `services/orchestrator.py`'s discovery-mode branch in `run_copy_stage`/
    `run_visuals_stage` and docs/campaign-pipeline.md's round-19 section.
    `sort_order` is the carousel order — slide 1 is the lowest `sort_order`.
    """
    __tablename__ = "campaign_discovery_products"
    __table_args__ = (UniqueConstraint("campaign_id", "product_id", name="uq_discovery_campaign_product"),)

    campaign_id: Mapped[str] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    campaign: Mapped[Campaign] = relationship(back_populates="discovery_products")
    product = relationship("Product")


class CampaignSlide(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "campaign_slides"

    campaign_id: Mapped[str] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), index=True)
    slide_number: Mapped[int] = mapped_column(Integer)
    purpose: Mapped[str] = mapped_column(String(100), default="")
    eyebrow: Mapped[str] = mapped_column(String(200), default="")
    headline: Mapped[str] = mapped_column(String(300), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    cta: Mapped[str] = mapped_column(String(300), default="")
    visual_brief: Mapped[str] = mapped_column(Text, default="")
    source_asset_id: Mapped[str | None] = mapped_column(ForeignKey("assets.id", ondelete="SET NULL"), nullable=True)
    generated_background_path: Mapped[str] = mapped_column(String(2000), default="")
    template_id: Mapped[str] = mapped_column(String(100), default="")
    rendered_asset_path: Mapped[str] = mapped_column(String(2000), default="")

    campaign: Mapped[Campaign] = relationship(back_populates="slides")


class CampaignOutput(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "campaign_outputs"

    campaign_id: Mapped[str] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(30))  # copy | creative | research | qa_report
    platform: Mapped[str] = mapped_column(String(30), default="")
    file_path: Mapped[str] = mapped_column(String(2000), default="")
    version: Mapped[int] = mapped_column(Integer, default=1)

    campaign: Mapped[Campaign] = relationship(back_populates="outputs")


class CampaignVariant(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "campaign_variants"

    parent_campaign_id: Mapped[str] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), index=True)
    variant_campaign_id: Mapped[str] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), index=True)
    varies: Mapped[str] = mapped_column(String(30))  # hook | visual | cta | caption | first_slide


class PlatformCampaignVariant(Base, UUIDPKMixin, TimestampMixin):
    """Build 2 (Platform Adapter + Creative Director + Hybrid Visual Engine),
    the core deliverable carried forward from Build 1's own documented
    limitation: Build 1 generated copy/carousel plans for every selected
    language but rendered only the primary one. This table is what makes every
    selected (`Campaign.target_platforms` x `Campaign.languages`) combination
    that supports static rendered content an independently reviewable variant
    — see `services/orchestrator.py::_render_additional_platform_variants` and
    `data/platform_creative_specs.py::PlatformCreativeSpec` (the new canonical
    TARGET PLATFORM -> CONTENT TYPE -> RENDER FORMAT resolver this reads).

    Deliberately a NEW table, not a repurposing of the pre-existing
    `CampaignVariant` above — that table has sat undisturbed (and, per a grep
    across this codebase, entirely unused — declared in Build/round 1,
    exercised by no code path) since round 1 for a different concept
    (A/B-style hook/visual/cta/caption variants of the SAME platform+language),
    not a platform x language cross-product. Repurposing it would have
    conflated two unrelated ideas; leaving it alone and adding this instead
    keeps both honestly named for what they actually are.

    One row per (campaign, target_platform, language, content_type) — the
    `uq_platform_variant` constraint mirrors that a campaign can only ever
    have ONE current variant for a given platform+language+content-type
    combination; re-running Visuals replaces rows the same way it already
    replaces `CampaignSlide` rows (delete-then-recreate, never accumulate
    stale duplicates from a retry).
    """
    __tablename__ = "platform_campaign_variants"
    __table_args__ = (
        UniqueConstraint(
            "campaign_id", "target_platform", "language", "content_type",
            name="uq_platform_variant",
        ),
    )

    campaign_id: Mapped[str] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), index=True)
    target_platform: Mapped[str] = mapped_column(String(30))  # data/platform_capabilities.py::PLATFORM_CAPABILITIES key
    language: Mapped[str] = mapped_column(String(20))  # data/platform_capabilities.py::SUPPORTED_LANGUAGES value
    content_type: Mapped[str] = mapped_column(String(50))  # data/platform_creative_specs.py content-type key
    render_format_key: Mapped[str] = mapped_column(String(50), default="")  # PLATFORM_FORMATS key, "" for script-only

    # PENDING (row created, not yet rendered) | RENDERED (static image(s) written) |
    # SCRIPT_ONLY (a VideoConcept was produced instead — see video_concept below,
    # this content type never renders a video file) | SCRIPT_UNAVAILABLE (a
    # video-oriented content type with no AI provider on hand to write the
    # script) | SKIPPED_UNSUPPORTED (a content type this catalog has no safe
    # default for) | FAILED (rendering was attempted and raised)
    status: Mapped[str] = mapped_column(String(30), default="PENDING")

    # Traceability the user's own spec asked for by name: "rendered asset",
    # "copy reference", "layout pass", "status", "traceability", "future QA
    # target" — each has its own field below rather than being folded into one
    # opaque blob, so a future QA pass (or a frontend list view) can query any
    # one of them directly.
    slide_asset_paths: Mapped[list] = mapped_column(JSON, default=list)  # rendered PNG path(s), empty for script-only
    copy_language: Mapped[str] = mapped_column(String(20), default="")  # which CampaignOutput(kind="copy") language variant this used
    creative_direction: Mapped[dict] = mapped_column(JSON, default=dict)  # schemas.ai.CreativeDirection.model_dump(), or {}
    video_concept: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # schemas.ai.VideoConcept.model_dump(), script-only content types
    qa_report_paths: Mapped[list] = mapped_column(JSON, default=list)  # future QA target: one per rendered slide
    # Which platform+slide index this variant's expensive AI-generated
    # background/product composition was actually reused from (see
    # `_render_additional_platform_variants`'s per-platform cache) — "" when
    # this variant is the one that generated it, or when nothing was cached
    # (deterministic gradient background, no AI call made). Pure traceability;
    # nothing reads this back to make a decision.
    shared_scene_source: Mapped[str] = mapped_column(String(50), default="")
    notes: Mapped[str] = mapped_column(Text, default="")

    # --- Build 3 (MARKETING OS — PLATFORM + LANGUAGE AWARE MULTIMODAL QA) ---
    # Carry-forward requirement 2: QA state attaches to THIS row (one specific
    # platform x language execution) rather than only to the parent Campaign,
    # so "Instagram/pt-BR = PASS, Instagram/en = NEEDS_REVIEW, Pinterest/en =
    # PASS" stays exactly representable — see `services/qa_engine.py::
    # run_qa_stage`, which is what actually populates these. A variant this
    # never runs on (PENDING/FAILED/SKIPPED_UNSUPPORTED/SCRIPT_UNAVAILABLE
    # render status) simply keeps `qa_status="PENDING"` — not a fourth
    # meaning bolted onto `status` above, which stays the render outcome only.
    #
    # PENDING (not yet QA'd, or not eligible to be) | PASS | NEEDS_REVIEW
    # (hard-fail or below-threshold after `AutopilotConfig.qa_max_retries`
    # targeted-revision attempts — Part H, never silently dropped).
    qa_status: Mapped[str] = mapped_column(String(20), default="PENDING")
    # The LATEST attempt's full scorecard — `schemas.qa.CreativeCritiqueResult`
    # for a static-image variant, `schemas.qa.VideoQAResult` for a script-only
    # one, `None` when QA never ran (no AI provider, or not yet run).
    qa_scores: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Every hard-fail reason from the LATEST attempt — platform (Part D),
    # language (Part C), and creative (Part B) hard-fails combined into one
    # list; empty (not merely absent) once a variant genuinely passes.
    qa_hard_fails: Mapped[list] = mapped_column(JSON, default=list)
    # Retry counter — how many targeted-revision rounds this variant has been
    # through (Part H: "retry exhaustion -> NEEDS_REVIEW").
    qa_attempts: Mapped[int] = mapped_column(Integer, default=0)
    # One path per QA attempt's persisted evidence JSON (Part F/test 11:
    # "QA evidence stored per platform/language variant") — never overwritten,
    # so a human reviewer can see exactly what every retry round found.
    qa_evidence_paths: Mapped[list] = mapped_column(JSON, default=list)
    # Part F: "record QA prompt version, rubric version, revision prompt
    # version" for the LATEST attempt — `{"qa_prompt_version", "qa_rubric_
    # version", "revision_prompt_version"}`, each "" when that step never ran
    # for this attempt (e.g. no revision was needed).
    qa_versions: Mapped[dict] = mapped_column(JSON, default=dict)
    qa_notes: Mapped[str] = mapped_column(Text, default="")

    # --- Build 4 (Human Approval + Platform/Language Feedback Learning) ------
    # Carry-forward requirement 4: a genuinely SEPARATE state from `qa_status`
    # above, never collapsed into it — `qa_status` is what an automated critic
    # concluded; `human_review_status` is what the owner actually decided,
    # and the two can legitimately disagree (QA_PASS + OWNER_REJECTED,
    # QA_NEEDS_REVIEW + OWNER_APPROVED are both valid, real states) when the
    # workflow allows an owner override. Set by a `level="PLATFORM_VARIANT"`
    # or `level="ASSET"` `ReviewFeedback` action scoped to THIS row
    # (`services/review_engine.py::record_review_feedback`) — carry-forward
    # requirement 1: a feedback action on Instagram/en never touches this
    # column on Instagram/pt-BR or Pinterest/en, by construction (each
    # variant's own row is the only thing a variant-scoped feedback action
    # ever writes to). PENDING (no explicit review yet, or reset here after a
    # requested revision has been applied and is awaiting the owner's next
    # look) | APPROVED | REJECTED | REVISION_REQUESTED.
    human_review_status: Mapped[str] = mapped_column(String(20), default="PENDING")

    campaign: Mapped[Campaign] = relationship()


class CampaignFingerprint(Base, UUIDPKMixin):
    __tablename__ = "campaign_fingerprints"

    campaign_id: Mapped[str] = mapped_column(
        ForeignKey("campaigns.id", ondelete="CASCADE"), unique=True, index=True
    )
    text_hash: Mapped[str] = mapped_column(String(64), index=True)
    text_embedding: Mapped[list | None] = mapped_column(JSON, nullable=True)
    angle: Mapped[str] = mapped_column(String(100), default="")
    promise_summary: Mapped[str] = mapped_column(Text, default="")
    objective: Mapped[str] = mapped_column(String(30), default="")
    format: Mapped[str] = mapped_column(String(50), default="")
    asset_sha256_list: Mapped[list] = mapped_column(JSON, default=list)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    campaign: Mapped[Campaign] = relationship(back_populates="fingerprint")
