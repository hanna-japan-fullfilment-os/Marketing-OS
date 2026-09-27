from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db import Base
from ._mixins import TimestampMixin, UUIDPKMixin, utcnow


class Asset(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "assets"
    __table_args__ = (UniqueConstraint("absolute_path", name="uq_assets_absolute_path"),)

    brand_id: Mapped[str] = mapped_column(ForeignKey("brands.id", ondelete="CASCADE"), index=True)
    category_id: Mapped[str | None] = mapped_column(ForeignKey("categories.id", ondelete="SET NULL"), nullable=True, index=True)
    product_id: Mapped[str | None] = mapped_column(ForeignKey("products.id", ondelete="SET NULL"), nullable=True, index=True)

    absolute_path: Mapped[str] = mapped_column(String(2000), index=True)
    relative_path: Mapped[str] = mapped_column(String(2000))
    filename: Mapped[str] = mapped_column(String(500))
    extension: Mapped[str] = mapped_column(String(10))

    sha256: Mapped[str] = mapped_column(String(64), index=True)
    phash: Mapped[str] = mapped_column(String(64), index=True, default="")
    file_size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    width: Mapped[int] = mapped_column(Integer, default=0)
    height: Mapped[int] = mapped_column(Integer, default=0)
    aspect_ratio: Mapped[float] = mapped_column(Float, default=0.0)

    created_at_fs: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    modified_at_fs: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    first_indexed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_indexed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    image_role: Mapped[str] = mapped_column(String(30), default="unclassified")
    tags: Mapped[list] = mapped_column(JSON, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    times_used: Mapped[int] = mapped_column(Integer, default=0)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    visual_description: Mapped[str] = mapped_column(Text, default="")
    ai_metadata: Mapped[dict] = mapped_column(JSON, default=dict)
    user_notes: Mapped[str] = mapped_column(Text, default="")
    checksum_stale: Mapped[bool] = mapped_column(Boolean, default=False)

    brand = relationship("Brand")
    category = relationship("Category")
    product = relationship("Product")
