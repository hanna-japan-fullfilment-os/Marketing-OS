"""Build 4 (Human Approval + Platform/Language Feedback Learning).

`ReviewFeedback` is the one new table this build adds: a single, append-only,
immutable-after-creation row per human review ACTION (APPROVE | REJECT |
REQUEST_REVISION), at whichever level the owner actually reviewed
(campaign / platform+language variant / individual asset-or-slide).

Two closely related, easy-to-conflate ideas this table deliberately keeps
separate:

- `Campaign.status` / `PlatformCampaignVariant.status` (existing, Build 1-3)
  is a PRODUCTION-PIPELINE state (IDEA -> ... -> PUBLISHED; PENDING ->
  RENDERED/SCRIPT_ONLY/FAILED/...). `Campaign.human_review_status` /
  `PlatformCampaignVariant.human_review_status` (new, Build 4) is the OWNER'S
  OWN quality verdict — a different axis entirely, only ever set by the
  actions this table records.
- `PlatformCampaignVariant.qa_status` (Build 3) is an AUTOMATED critic's
  verdict. `human_review_status` is the OWNER'S verdict. Carry-forward
  requirement 4 is explicit that these must never collapse into one field —
  a variant can honestly be `qa_status=PASS` and `human_review_status=
  REJECTED` at the same time (the owner didn't like something the automated
  critic didn't catch), or the reverse (the owner is fine shipping something
  QA flagged). Nothing in this module ever writes to a `qa_*` field except
  as the honest, expected side effect of a REQUEST_REVISION action actually
  triggering a real re-render + re-QA (see `services/review_engine.py::
  apply_requested_revision`) — a plain APPROVE/REJECT touches ONLY the
  `human_review_status` column and this table, never `qa_*` (carry-forward
  requirement 9, proven by `tests/test_build4_review_engine.py::
  test_approve_and_reject_never_mutate_qa_state`).

Every traceability field the spec named by name is captured as a SNAPSHOT at
the moment of the review action (`reviewed_*` columns below) rather than as a
live foreign-key into mutable state — carry-forward requirement 2's own
reasoning: a later QA rerun, or a later revision that overwrites
`PlatformCampaignVariant.slide_asset_paths`/`creative_direction`/`qa_*` in
place (Build 3's existing re-render mechanism does exactly this — it has no
history of its own), must never make a past owner decision ambiguous about
what was actually being looked at when they made it. This is also what makes
carry-forward requirement 3 ("Request Revision must create lineage, not
overwrite history") possible without needing to rebuild Build 1-3's own
delete-and-recreate persistence model: the snapshot IS the history, and
`revision_of_feedback_id` chains one review action to the specific earlier
REQUEST_REVISION it was made in response to (see `record_review_feedback`'s
own auto-linking logic).
"""
from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db import Base
from ._mixins import TimestampMixin, UUIDPKMixin

REVIEW_LEVELS = ("CAMPAIGN", "PLATFORM_VARIANT", "ASSET")
REVIEW_ACTIONS = ("APPROVE", "REJECT", "REQUEST_REVISION")


class ReviewFeedback(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "review_feedback"

    campaign_id: Mapped[str] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), index=True)
    # NULL for level="CAMPAIGN" feedback; set for "PLATFORM_VARIANT"/"ASSET" —
    # see `level` below. `ondelete="CASCADE"` matches every other row scoped to
    # a variant (qa evidence, slide assets) — deleting a variant's row (a full
    # Visuals re-run) also clears the feedback history scoped to that specific
    # rendered execution, since a brand-new variant row for the same (platform,
    # language, content_type) is a genuinely different execution to review.
    platform_campaign_variant_id: Mapped[str | None] = mapped_column(
        ForeignKey("platform_campaign_variants.id", ondelete="CASCADE"), nullable=True, index=True
    )

    # CAMPAIGN (the whole campaign, every platform/language at once — the ONLY
    # level that ever touches `Campaign.human_review_status`) | PLATFORM_VARIANT
    # (one specific (platform, language, content_type) execution — "platform
    # variant level" and "language variant level" from the spec are the SAME
    # granularity in this schema, since `PlatformCampaignVariant` already keys
    # on platform+language jointly) | ASSET (one specific slide, or for a
    # script-only variant one specific structured field — hook/script/
    # shot_list/timing/on_screen_text/caption/cover, never implying a rendered
    # video file exists, per carry-forward requirement 8).
    level: Mapped[str] = mapped_column(String(20))
    # For level="ASSET" only: which slide ("slide-2") or, for a script-only
    # variant, which VideoConcept field ("hook", "shot_list", ...). "" for
    # CAMPAIGN/PLATFORM_VARIANT feedback.
    asset_ref: Mapped[str] = mapped_column(String(100), default="")

    action: Mapped[str] = mapped_column(String(20))  # APPROVE | REJECT | REQUEST_REVISION
    # One of `data/feedback_reasons.py::FEEDBACK_REASON_CODES`, or "" when the
    # owner gave only free text (still valid — `reason_text` alone is a real
    # reason, just not a structured one this app can pattern-match on later).
    reason_code: Mapped[str] = mapped_column(String(50), default="")
    reason_text: Mapped[str] = mapped_column(Text, default="")

    # --- Denormalized filter/rank context (Part 5: "preserve platform/
    # language/category context" for the feedback selector) — captured at
    # write time so `services/review_engine.py::select_feedback_examples` is a
    # single indexed scan over this table, never a join back through
    # `PlatformCampaignVariant`/`Campaign` for every candidate row. -------
    brand_id: Mapped[str | None] = mapped_column(ForeignKey("brands.id", ondelete="SET NULL"), nullable=True, index=True)
    category_id: Mapped[str | None] = mapped_column(ForeignKey("categories.id", ondelete="SET NULL"), nullable=True)
    product_id: Mapped[str | None] = mapped_column(ForeignKey("products.id", ondelete="SET NULL"), nullable=True)
    platform: Mapped[str] = mapped_column(String(30), default="")  # "" for level="CAMPAIGN" (spans every platform)
    language: Mapped[str] = mapped_column(String(20), default="")  # "" for level="CAMPAIGN"
    content_type: Mapped[str] = mapped_column(String(50), default="")
    objective: Mapped[str] = mapped_column(String(30), default="")

    # --- Traceability snapshot (Part 2) — exactly what the owner actually
    # reviewed, frozen at review time. ---------------------------------------
    reviewed_slide_asset_paths: Mapped[list] = mapped_column(JSON, default=list)
    reviewed_video_concept: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    reviewed_copy_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)  # headline/body/cta/hook/caption
    reviewed_creative_direction: Mapped[dict] = mapped_column(JSON, default=dict)
    reviewed_qa_status: Mapped[str] = mapped_column(String(20), default="")
    reviewed_qa_scores: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    reviewed_qa_hard_fails: Mapped[list] = mapped_column(JSON, default=list)
    reviewed_qa_attempts: Mapped[int] = mapped_column(Integer, default=0)
    reviewed_qa_evidence_paths: Mapped[list] = mapped_column(JSON, default=list)
    reviewed_qa_versions: Mapped[dict] = mapped_column(JSON, default=dict)
    # Best-effort {"campaign_copy": "1.0.0", "creative_direction": "1.0.0", ...}
    # read back from `AuditEvent(entity_type="campaign_prompt_usage")` rows
    # matching this campaign/platform/language at snapshot time — see
    # `services/review_engine.py::_snapshot_prompt_versions`. Empty dict when
    # nothing matched (never fabricated).
    reviewed_prompt_versions: Mapped[dict] = mapped_column(JSON, default=dict)

    # --- Lineage (Part 3) — never destroys the reviewed version; chains a
    # later review action back to the specific REQUEST_REVISION it answers.
    # See `record_review_feedback`'s auto-linking: the next feedback row
    # created for the same variant after an unanswered REQUEST_REVISION
    # automatically points back to it, so the full chain (reviewed version ->
    # feedback -> requested revision -> revised version -> new QA result ->
    # new owner decision) is answerable by walking this field. -------------
    revision_of_feedback_id: Mapped[str | None] = mapped_column(
        ForeignKey("review_feedback.id", ondelete="SET NULL"), nullable=True
    )

    campaign = relationship("Campaign")
    variant = relationship("PlatformCampaignVariant")
