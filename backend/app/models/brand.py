from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db import Base
from ._mixins import TimestampMixin, UUIDPKMixin


class Brand(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "brands"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(200), unique=True, nullable=False, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    voice: Mapped[str] = mapped_column(Text, default="")
    language_rules: Mapped[dict] = mapped_column(JSON, default=dict)
    colors: Mapped[dict] = mapped_column(JSON, default=dict)
    typography: Mapped[dict] = mapped_column(JSON, default=dict)
    spacing: Mapped[dict] = mapped_column(JSON, default=dict)
    visual_style: Mapped[dict] = mapped_column(JSON, default=dict)
    forbidden_styles: Mapped[list] = mapped_column(JSON, default=list)
    preferred_ctas: Mapped[list] = mapped_column(JSON, default=list)
    disallowed_terms: Mapped[list] = mapped_column(JSON, default=list)
    disclaimers: Mapped[list] = mapped_column(JSON, default=list)
    target_audiences: Mapped[list] = mapped_column(JSON, default=list)
    target_countries: Mapped[list] = mapped_column(JSON, default=list)
    social_handles: Mapped[dict] = mapped_column(JSON, default=dict)
    website: Mapped[str] = mapped_column(String(500), default="")
    campaign_rules: Mapped[dict] = mapped_column(JSON, default=dict)
    # Free-text creative direction threaded into every AI call this brand's
    # campaigns make (strategy, creative brief, copy, and the image-recreation
    # prompt) — see `_brand_creative_instructions_note` in `services/
    # orchestrator.py`. Round 1's `campaign_rules` JSON field above looked like
    # it might already cover this, but a full audit (round 20) found it's dead
    # code: defined in the model and schema, never read by anything. This field
    # is the real thing — meant to hold a brand's own custom-GPT-style prompt
    # (system rules, tone, formatting conventions, non-negotiables) so it
    # actually reaches generation instead of only the handful of narrow
    # structured fields (voice/visual_style/preferred_ctas/disallowed_terms)
    # every AI call got before this existed. Empty string is the default —
    # every existing brand behaves exactly as before until someone fills it in.
    creative_instructions: Mapped[str] = mapped_column(Text, default="")

    assets_brand: Mapped[list["BrandAsset"]] = relationship(back_populates="brand", cascade="all, delete-orphan")
    categories: Mapped[list["Category"]] = relationship(back_populates="brand", cascade="all, delete-orphan")


class BrandAsset(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "brand_assets"

    brand_id: Mapped[str] = mapped_column(ForeignKey("brands.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(30))  # logo | font | visual_reference | inspiration
    # Only meaningful for kind="inspiration": scopes an example ad/post/carousel to one
    # category (e.g. only used as creative reference for Skincare campaigns) instead of
    # the whole brand. Null means brand-wide — every other kind always leaves this null.
    category_id: Mapped[str | None] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL"), nullable=True, index=True
    )
    file_path: Mapped[str] = mapped_column(String(1000))
    label: Mapped[str] = mapped_column(String(200), default="")

    brand: Mapped[Brand] = relationship(back_populates="assets_brand")
    category: Mapped["Category | None"] = relationship()


class Category(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "categories"

    brand_id: Mapped[str] = mapped_column(ForeignKey("brands.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(200), index=True)
    parent_category_id: Mapped[str | None] = mapped_column(ForeignKey("categories.id"), nullable=True)

    brand: Mapped[Brand] = relationship(back_populates="categories")
    products: Mapped[list["Product"]] = relationship(back_populates="category", cascade="all, delete-orphan")


class Product(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "products"

    brand_id: Mapped[str] = mapped_column(ForeignKey("brands.id", ondelete="CASCADE"), index=True)
    category_id: Mapped[str | None] = mapped_column(ForeignKey("categories.id", ondelete="SET NULL"), nullable=True)
    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(200), index=True)
    notes: Mapped[str] = mapped_column(Text, default="")

    category: Mapped[Category | None] = relationship(back_populates="products")
