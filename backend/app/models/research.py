from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db import Base
from ._mixins import TimestampMixin, UUIDPKMixin


class ResearchRun(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "research_runs"

    brand_id: Mapped[str] = mapped_column(ForeignKey("brands.id", ondelete="CASCADE"), index=True)
    category_id: Mapped[str | None] = mapped_column(ForeignKey("categories.id", ondelete="SET NULL"), nullable=True)
    product_id: Mapped[str | None] = mapped_column(ForeignKey("products.id", ondelete="SET NULL"), nullable=True)
    query_context: Mapped[dict] = mapped_column(JSON, default=dict)
    ttl_kind: Mapped[str] = mapped_column(String(20), default="trend")  # trend | category
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    sources: Mapped[list["ResearchSource"]] = relationship(back_populates="research_run", cascade="all, delete-orphan")
    insights: Mapped[list["ResearchInsight"]] = relationship(back_populates="research_run", cascade="all, delete-orphan")


class ResearchSource(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "research_sources"

    research_run_id: Mapped[str] = mapped_column(ForeignKey("research_runs.id", ondelete="CASCADE"), index=True)
    url: Mapped[str] = mapped_column(String(2000))
    source_title: Mapped[str] = mapped_column(String(500), default="")
    publisher: Mapped[str] = mapped_column(String(200), default="")
    query: Mapped[str] = mapped_column(String(500), default="")
    retrieved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_type: Mapped[str] = mapped_column(String(50), default="")
    geography: Mapped[str] = mapped_column(String(100), default="")
    relevance_score: Mapped[float] = mapped_column(Float, default=0.0)

    research_run: Mapped[ResearchRun] = relationship(back_populates="sources")


class ResearchInsight(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "research_insights"

    research_run_id: Mapped[str] = mapped_column(ForeignKey("research_runs.id", ondelete="CASCADE"), index=True)
    statement: Mapped[str] = mapped_column(Text)
    source_ids: Mapped[list] = mapped_column(JSON, default=list)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    freshness: Mapped[str] = mapped_column(String(50), default="")
    category: Mapped[str] = mapped_column(String(100), default="")
    recommended_implication: Mapped[str] = mapped_column(Text, default="")

    research_run: Mapped[ResearchRun] = relationship(back_populates="insights")
