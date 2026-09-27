from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base
from ._mixins import TimestampMixin, UUIDPKMixin, utcnow

JOB_STATUSES = ("QUEUED", "RUNNING", "COMPLETED", "FAILED", "CANCELLED")


class Job(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "jobs"

    type: Mapped[str] = mapped_column(String(50))
    campaign_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(20), default="QUEUED", index=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    step: Mapped[str] = mapped_column(String(200), default="")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str] = mapped_column(Text, default="")
    job_metadata: Mapped[dict] = mapped_column(JSON, default=dict)


class PromptVersion(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "prompt_versions"

    purpose: Mapped[str] = mapped_column(String(100), index=True)
    version: Mapped[str] = mapped_column(String(20))
    file_path: Mapped[str] = mapped_column(String(500))
    variables: Mapped[list] = mapped_column(JSON, default=list)
    change_notes: Mapped[str] = mapped_column(Text, default="")
    # Build 5, Part A: "prompt metadata should support platform applicability,
    # language applicability, version, active status." Empty list means "every
    # platform"/"every language" (most purposes here — e.g. `campaign_copy` —
    # apply everywhere); a non-empty list scopes a purpose that only ever
    # fires for specific platforms (e.g. `video_concept` only ever runs for
    # TikTok/YouTube Shorts) — see `services/prompt_registry.py::PROMPT_
    # VERSIONS` for the actual per-purpose values, never guessed here.
    platform_applicability: Mapped[list] = mapped_column(JSON, default=list)
    language_applicability: Mapped[list] = mapped_column(JSON, default=list)
    # "Active status" — False marks a purpose retired/superseded without
    # deleting its row (so a `BenchmarkRun`'s frozen `prompt_versions_snapshot`
    # from before the retirement stays a meaningful historical record).
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class AIUsage(Base, UUIDPKMixin):
    __tablename__ = "ai_usage"

    provider: Mapped[str] = mapped_column(String(50))
    model: Mapped[str] = mapped_column(String(100))
    operation: Mapped[str] = mapped_column(String(100))
    campaign_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    image_count: Mapped[int] = mapped_column(Integer, default=0)
    estimated_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    # --- Build 6 (Production Integration + Multi-Platform Hanna Acceptance) ---
    # Carry-forward requirement 6: "capture real cost/usage per variant" needs
    # more than `campaign_id` to attribute a row to a specific
    # `PlatformCampaignVariant` (platform x language x content_type) — these
    # three columns are that attribution, all "" (the honest "not applicable/
    # not platform-or-language-specific yet" default) for a row logged before
    # this migration or for a campaign-wide stage (e.g. research, strategy)
    # that isn't scoped to one platform/language. See `services/
    # usage_tracking.py::build_campaign_cost_report`'s `by_variant` breakdown,
    # which groups on exactly these three fields.
    platform: Mapped[str] = mapped_column(String(30), default="")
    language: Mapped[str] = mapped_column(String(20), default="")
    content_type: Mapped[str] = mapped_column(String(50), default="")

    # --- Build 6 repair (Critical Defect 7/13) ---
    # An empty `platform`/`language` above was ambiguous: it could mean "not
    # yet attributed" or "genuinely campaign-wide", and a live-acceptance run
    # showed real cost rows with blank attribution that were hard to tell
    # apart from a bug. `scope` makes the distinction an explicit, asserted
    # fact instead of something a reader has to infer: "campaign_global" for
    # a stage that is genuinely not bound to one requested platform/language
    # pairing (research, strategy, creative_brief, master_campaign_concept,
    # campaign_copy, carousel_plan — see each call site's own comment), and
    # "variant" for everything attributed to a specific rendered/scripted
    # `PlatformCampaignVariant` (or a scene shared across that variant's own
    # languages). Defaults to "variant" — the common case, and a strictly
    # more honest default than an empty string for any row a future call site
    # forgets to set explicitly.
    scope: Mapped[str] = mapped_column(String(20), default="variant")


class AuditEvent(Base, UUIDPKMixin):
    __tablename__ = "audit_events"

    entity_type: Mapped[str] = mapped_column(String(50))
    entity_id: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(100))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SettingRow(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(200), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
