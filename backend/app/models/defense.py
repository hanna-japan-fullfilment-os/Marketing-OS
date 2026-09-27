"""The Defense family (brief addendum): watch competitors, detect events, and
recommend a specific counter-response from the Strategy Library — distinct from
proactively launching an ATTACK-family campaign. Detection is manual/research-fed
for now (no live scraping); the recommendation logic is a real, deterministic rule
engine today, designed so an AI-driven version can slot in later without a schema
change (see docs/campaign-pipeline.md).
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db import Base
from ._mixins import TimestampMixin, UUIDPKMixin

COMPETITOR_EVENT_TYPES = (
    "price_change", "promotion_launch", "new_product", "campaign_detected", "restock", "other",
)
COMPETITOR_EVENT_STATUSES = ("NEW", "REVIEWED", "RESPONDED", "IGNORED")


class Competitor(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "competitors"

    brand_id: Mapped[str] = mapped_column(ForeignKey("brands.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    website: Mapped[str] = mapped_column(String(500), default="")
    social_handles: Mapped[dict] = mapped_column(JSON, default=dict)
    notes: Mapped[str] = mapped_column(Text, default="")
    monitoring_enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    events: Mapped[list["CompetitorEvent"]] = relationship(back_populates="competitor", cascade="all, delete-orphan")


class CompetitorEvent(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "competitor_events"

    competitor_id: Mapped[str] = mapped_column(ForeignKey("competitors.id", ondelete="CASCADE"), index=True)
    brand_id: Mapped[str] = mapped_column(ForeignKey("brands.id", ondelete="CASCADE"), index=True)
    event_type: Mapped[str] = mapped_column(String(30))
    detected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source: Mapped[str] = mapped_column(String(30), default="manual")  # manual | research | import
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    # e.g. {"product": "SPF50 sunscreen", "old_price": 3200, "new_price": 2560, "discount_pct": 20}
    severity: Mapped[str] = mapped_column(String(20), default="medium")  # low | medium | high
    status: Mapped[str] = mapped_column(String(20), default="NEW", index=True)

    competitor: Mapped[Competitor] = relationship(back_populates="events")


class DefensePlaybook(Base, UUIDPKMixin, TimestampMixin):
    """A rule mapping a competitor-event pattern to a recommended Strategy Library
    entry. `brand_id` NULL means a global default playbook available to every brand.
    """
    __tablename__ = "defense_playbooks"

    brand_id: Mapped[str | None] = mapped_column(ForeignKey("brands.id", ondelete="CASCADE"), nullable=True, index=True)
    event_type: Mapped[str] = mapped_column(String(30), index=True)
    min_severity: Mapped[str] = mapped_column(String(20), default="low")
    condition: Mapped[dict] = mapped_column(JSON, default=dict)
    # e.g. {"discount_pct_gte": 15} — simple key->threshold conditions evaluated against
    # the triggering event's `details`. Empty condition = matches on event_type/severity alone.
    recommended_strategy_key: Mapped[str] = mapped_column(String(60))
    rationale: Mapped[str] = mapped_column(Text, default="")
    priority: Mapped[int] = mapped_column(Integer, default=100)  # lower = evaluated first
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
