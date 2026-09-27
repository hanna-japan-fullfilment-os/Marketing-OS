"""Verified Product Facts (Build 1, Part A of the Multi-Platform + Bilingual
Quality Recovery Program) — the one canonical, owner-controlled store of what is
actually TRUE about a product, kept deliberately separate from two things it is
easy to blur together with:

- RESEARCH INSIGHT (`models/research.py::ResearchInsight`) — what the market/
  competitors/trends look like. Never product truth on its own.
- CREATIVE IDEA (angle/hook/key_message on `CampaignStrategy`, copy on
  `CampaignCopy`) — what we're saying about the product for a specific
  campaign. Persuasive framing, not a fact register.

Everything on this table is either what the brand owner typed in themselves, or
something an AI call explicitly cited a real source for — see `services/
product_facts.py::resolve_verified_product_facts`, which is the only place this
table's rows get turned into the full `VerifiedProductFactsOut` structure copy
generation actually reads. Every field here is nullable/optional by design (the
spec: "Do not force fields that existing source data cannot support safely") —
an empty field is surfaced as `missing_information`, never guessed at.
"""
from __future__ import annotations

from sqlalchemy import Float, ForeignKey, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base
from ._mixins import TimestampMixin, UUIDPKMixin


class VerifiedProductFact(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "verified_product_facts"

    # One row per product — enforced at the DB level (unique) so "the verified
    # facts for this product" is never ambiguous. product_name/category/
    # brand_name/owner_notes are deliberately NOT duplicated here: they already
    # live on Product/Category/Brand, and the resolver assembles them into the
    # final structure rather than risking two copies drifting apart.
    product_id: Mapped[str] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), unique=True, index=True
    )

    verified_description: Mapped[str] = mapped_column(Text, default="")
    verified_ingredients: Mapped[list] = mapped_column(JSON, default=list)
    verified_features: Mapped[list] = mapped_column(JSON, default=list)
    verified_benefits: Mapped[list] = mapped_column(JSON, default=list)
    verified_usage: Mapped[str] = mapped_column(Text, default="")
    verified_size: Mapped[str] = mapped_column(String(200), default="")
    verified_variant: Mapped[str] = mapped_column(String(200), default="")
    # Deliberately a string, not a number: lets the owner write "R$129,90" (or a
    # range, or leave it blank) without this app inventing a currency/precision
    # it wasn't given — matches the "never invent a price" rule.
    verified_price: Mapped[str] = mapped_column(String(100), default="")
    verified_availability: Mapped[str] = mapped_column(String(200), default="")
    verified_country_of_origin: Mapped[str] = mapped_column(String(200), default="")
    # Claims the owner has confirmed are true and safe to use in copy.
    verified_claims: Mapped[list] = mapped_column(JSON, default=list)
    # Claims explicitly forbidden for this product (e.g. a past regulatory note,
    # a claim competitors got in trouble for) — checked by copy generation
    # alongside `Brand.disallowed_terms`, but scoped to this one product.
    prohibited_claims: Mapped[list] = mapped_column(JSON, default=list)

    # Provenance: which real assets/documents this row's facts were confirmed
    # against — never a bare confidence number with nothing behind it.
    source_asset_ids: Mapped[list] = mapped_column(JSON, default=list)
    source_references: Mapped[list] = mapped_column(JSON, default=list)  # free-text: URLs, doc names, "owner verbally confirmed 2026-09-11"
    # 0-1, owner- or reviewer-set — never computed/inferred by this app. Defaults
    # to 0 (no confidence claimed) rather than a falsely reassuring 1.0.
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    # Free text describing how this row was populated, e.g. "owner_provided",
    # "verified_from_packaging_photo", "verified_from_supplier_spec_sheet".
    provenance: Mapped[str] = mapped_column(String(200), default="owner_provided")
