"""Verified Product Facts schemas (Build 1, Part A). See `models/product_facts.py`
for why this is stored separately from research insights and creative ideas.
"""
from __future__ import annotations

from .common import ORMModel

# The verified_* fields checked for `missing_information` — kept as one list so
# the resolver and any future UI/test agree on exactly what counts as "filled in".
VERIFIED_FACT_FIELDS: tuple[str, ...] = (
    "verified_description", "verified_ingredients", "verified_features", "verified_benefits",
    "verified_usage", "verified_size", "verified_variant", "verified_price",
    "verified_availability", "verified_country_of_origin",
)


class VerifiedProductFactsUpdate(ORMModel):
    """What the brand owner can actually set — deliberately excludes product_id/
    product_name/category/brand_name/owner_notes, which are derived from
    Product/Category/Brand and never edited here.
    """

    verified_description: str | None = None
    verified_ingredients: list[str] | None = None
    verified_features: list[str] | None = None
    verified_benefits: list[str] | None = None
    verified_usage: str | None = None
    verified_size: str | None = None
    verified_variant: str | None = None
    verified_price: str | None = None
    verified_availability: str | None = None
    verified_country_of_origin: str | None = None
    verified_claims: list[str] | None = None
    prohibited_claims: list[str] | None = None
    source_asset_ids: list[str] | None = None
    source_references: list[str] | None = None
    confidence: float | None = None
    provenance: str | None = None


class VerifiedProductFactsOut(ORMModel):
    """The one canonical, assembled structure `services/product_facts.py::
    resolve_verified_product_facts` returns — combines the owner-editable
    `VerifiedProductFact` row (if one exists yet) with read-only context already
    on `Product`/`Category`/`Brand`, plus a computed `missing_information` list
    so a caller (a human reviewing the form, or the copy-generation prompt) can
    see at a glance what's still unverified rather than guessing from absence.
    """

    product_id: str
    product_name: str
    category: str | None
    brand_name: str
    owner_notes: str

    verified_description: str
    verified_ingredients: list[str]
    verified_features: list[str]
    verified_benefits: list[str]
    verified_usage: str
    verified_size: str
    verified_variant: str
    verified_price: str
    verified_availability: str
    verified_country_of_origin: str
    verified_claims: list[str]
    prohibited_claims: list[str]

    source_asset_ids: list[str]
    source_references: list[str]
    confidence: float
    # Names of `VERIFIED_FACT_FIELDS` entries that are still blank — computed,
    # never stored, so it's always in sync with the actual row.
    missing_information: list[str]
    provenance: str
