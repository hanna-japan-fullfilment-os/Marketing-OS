from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db import Base
from ._mixins import TimestampMixin, UUIDPKMixin


class Opportunity(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "opportunities"

    brand_id: Mapped[str] = mapped_column(ForeignKey("brands.id", ondelete="CASCADE"), index=True)
    platform: Mapped[str] = mapped_column(String(30))
    name: Mapped[str] = mapped_column(String(300))
    url: Mapped[str] = mapped_column(String(2000), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    audience: Mapped[str] = mapped_column(Text, default="")
    category_id: Mapped[str | None] = mapped_column(ForeignKey("categories.id", ondelete="SET NULL"), nullable=True)
    country: Mapped[str] = mapped_column(String(100), default="")
    region_city: Mapped[str] = mapped_column(String(200), default="")
    language: Mapped[str] = mapped_column(String(50), default="")
    estimated_relevance: Mapped[float] = mapped_column(Float, default=0.0)
    audience_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    visibility: Mapped[str] = mapped_column(String(20), default="public")
    joined_status: Mapped[str] = mapped_column(String(30), default="not_joined")
    promo_allowed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    posting_rules: Mapped[str] = mapped_column(Text, default="")
    recommended_content_style: Mapped[str] = mapped_column(Text, default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(200), default="")
    discovered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="DISCOVERED")
    favorite: Mapped[bool] = mapped_column(Boolean, default=False)
    blocked: Mapped[bool] = mapped_column(Boolean, default=False)


class CampaignOpportunity(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "campaign_opportunities"

    campaign_id: Mapped[str] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), index=True)
    opportunity_id: Mapped[str] = mapped_column(ForeignKey("opportunities.id", ondelete="CASCADE"), index=True)
    community_post_text: Mapped[str] = mapped_column(Text, default="")
    posted: Mapped[bool] = mapped_column(Boolean, default=False)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
