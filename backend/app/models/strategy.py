"""Campaign Strategy Library — the catalog of campaign archetypes ("Campaign DNA"),
organized into 8 strategic families (ATTACK/ACQUIRE/CONVERT/RETAIN/BRAND/HYPE/
COMMUNITY/DEFENSE). This is a seeded, queryable catalog (not free text) so the
future orchestrator can reason over "which strategy types are underused for this
category" and so the Defense engine can recommend a specific type by key.
"""
from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db import Base
from ._mixins import TimestampMixin, UUIDPKMixin

STRATEGY_FAMILIES = (
    "ATTACK", "ACQUIRE", "CONVERT", "RETAIN", "BRAND", "HYPE", "COMMUNITY", "DEFENSE",
)


class CampaignStrategyFamily(Base, UUIDPKMixin):
    __tablename__ = "campaign_strategy_families"

    key: Mapped[str] = mapped_column(String(20), unique=True, index=True)  # ATTACK, ACQUIRE, ...
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text, default="")
    color: Mapped[str] = mapped_column(String(20), default="")  # UI accent, e.g. "red"
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    types: Mapped[list["CampaignStrategyType"]] = relationship(back_populates="family")


class CampaignStrategyType(Base, UUIDPKMixin, TimestampMixin):
    """One row per campaign archetype, holding its full 'Campaign DNA'."""
    __tablename__ = "campaign_strategy_types"

    key: Mapped[str] = mapped_column(String(60), unique=True, index=True)  # e.g. "guerrilla_marketing"
    name: Mapped[str] = mapped_column(String(150))
    family_id: Mapped[str] = mapped_column(ForeignKey("campaign_strategy_families.id", ondelete="CASCADE"), index=True)
    secondary_family_keys: Mapped[list] = mapped_column(JSON, default=list)  # e.g. ["BRAND"] for Anti-Ad

    example: Mapped[str] = mapped_column(String(300), default="")
    # Round 20: "single" | "multi" | "either" — which carousel structure (round
    # 19's deep-dive vs. discovery) this type naturally fits. See
    # `data/strategy_library.py`'s module docstring for the full rule. Purely
    # informational — surfaced in the API/frontend, never used to gate or
    # auto-set a campaign's actual structure_mode.
    product_scope: Mapped[str] = mapped_column(String(10), default="either")

    # --- Campaign DNA ---
    objective: Mapped[str] = mapped_column(Text, default="")
    trigger_type: Mapped[str] = mapped_column(String(30), default="manual")
    # manual | competitor_event | seasonal | inventory | customer_behavior | scheduled
    trigger_description: Mapped[str] = mapped_column(Text, default="")
    audience: Mapped[str] = mapped_column(Text, default="")
    psychology: Mapped[list] = mapped_column(JSON, default=list)  # e.g. ["scarcity", "fomo"]
    offer_types: Mapped[list] = mapped_column(JSON, default=list)
    channels: Mapped[list] = mapped_column(JSON, default=list)
    content_types: Mapped[list] = mapped_column(JSON, default=list)
    typical_duration: Mapped[str] = mapped_column(String(100), default="")
    budget_notes: Mapped[str] = mapped_column(Text, default="")
    success_metrics: Mapped[list] = mapped_column(JSON, default=list)
    notes: Mapped[str] = mapped_column(Text, default="")

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    family: Mapped[CampaignStrategyFamily] = relationship(back_populates="types")
