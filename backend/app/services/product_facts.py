"""Resolves the one canonical `VerifiedProductFactsOut` structure for a product —
Build 1, Part A. Never invents a value: every field either comes from the
owner-editable `VerifiedProductFact` row, or from Product/Category/Brand rows the
owner already entered elsewhere. A field nobody has filled in yet shows up empty
AND is named in `missing_information`, so a prompt built from this can tell the
model "this is unknown — do not guess" instead of silently omitting it.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from ..models import Brand, Category, Product, VerifiedProductFact
from ..schemas.product_facts import VERIFIED_FACT_FIELDS, VerifiedProductFactsOut

# Build 5 repair (Part 2): a version identity for the RESOLVER's own assembly
# logic (which fields it reads, what counts as "missing", the never-invent
# discipline above) — not a per-product-fact version, since the facts
# themselves are owner-edited data, not a versioned recipe. Bump this when
# `resolve_verified_product_facts`'s own field-resolution/fallback logic
# changes in a way worth tracing a past benchmark run back to.
VERIFIED_PRODUCT_FACTS_RESOLVER_VERSION = "1.0.0"


def get_or_none(db: Session, product_id: str) -> VerifiedProductFact | None:
    return db.query(VerifiedProductFact).filter(VerifiedProductFact.product_id == product_id).one_or_none()


def resolve_verified_product_facts(db: Session, product: Product) -> VerifiedProductFactsOut:
    """Assembles the full structure for one product. `product` must already be
    loaded (this never queries for it) — callers already have it via
    `_load_campaign_context` or a direct `db.get(Product, ...)`.
    """
    category = db.get(Category, product.category_id) if product.category_id else None
    brand = db.get(Brand, product.brand_id)
    row = get_or_none(db, product.id)

    list_fields = {"verified_ingredients", "verified_features", "verified_benefits"}
    values: dict[str, str | list[str]] = {}
    for f in VERIFIED_FACT_FIELDS:
        raw = getattr(row, f) if row is not None else None
        if f in list_fields:
            values[f] = list(raw) if raw else []
        else:
            values[f] = raw or ""

    missing = [f for f in VERIFIED_FACT_FIELDS if not values.get(f)]

    return VerifiedProductFactsOut(
        product_id=product.id,
        product_name=product.name,
        category=category.name if category else None,
        brand_name=brand.name if brand else "",
        owner_notes=product.notes or "",
        verified_description=values["verified_description"],
        verified_ingredients=values["verified_ingredients"],
        verified_features=values["verified_features"],
        verified_benefits=values["verified_benefits"],
        verified_usage=values["verified_usage"],
        verified_size=values["verified_size"],
        verified_variant=values["verified_variant"],
        verified_price=values["verified_price"],
        verified_availability=values["verified_availability"],
        verified_country_of_origin=values["verified_country_of_origin"],
        verified_claims=list(row.verified_claims) if row is not None and row.verified_claims else [],
        prohibited_claims=list(row.prohibited_claims) if row is not None and row.prohibited_claims else [],
        source_asset_ids=list(row.source_asset_ids) if row is not None and row.source_asset_ids else [],
        source_references=list(row.source_references) if row is not None and row.source_references else [],
        confidence=row.confidence if row is not None else 0.0,
        missing_information=missing,
        provenance=row.provenance if row is not None else "unverified",
    )


def format_verified_facts_for_prompt(facts: VerifiedProductFactsOut) -> str:
    """Turns the resolved structure into a prompt-ready block that clearly labels
    it as VERIFIED FACTS (as opposed to research or creative-idea text elsewhere
    in the same prompt) and explicitly lists what's missing, so the model is told
    not to invent those fields rather than left to infer their absence.
    """
    lines = [f"VERIFIED PRODUCT FACTS for '{facts.product_name}' (brand: {facts.brand_name}):"]
    if facts.category:
        lines.append(f"- Category: {facts.category}")
    if facts.owner_notes:
        lines.append(f"- Owner notes: {facts.owner_notes}")
    if facts.verified_description:
        lines.append(f"- Description: {facts.verified_description}")
    if facts.verified_ingredients:
        lines.append(f"- Ingredients: {', '.join(facts.verified_ingredients)}")
    if facts.verified_features:
        lines.append(f"- Features: {', '.join(facts.verified_features)}")
    if facts.verified_benefits:
        lines.append(f"- Benefits: {', '.join(facts.verified_benefits)}")
    if facts.verified_usage:
        lines.append(f"- Usage: {facts.verified_usage}")
    if facts.verified_size:
        lines.append(f"- Size: {facts.verified_size}")
    if facts.verified_variant:
        lines.append(f"- Variant: {facts.verified_variant}")
    if facts.verified_price:
        lines.append(f"- Price: {facts.verified_price}")
    if facts.verified_availability:
        lines.append(f"- Availability: {facts.verified_availability}")
    if facts.verified_country_of_origin:
        lines.append(f"- Country of origin: {facts.verified_country_of_origin}")
    if facts.verified_claims:
        lines.append(f"- Confirmed-safe claims you MAY use: {', '.join(facts.verified_claims)}")
    if facts.prohibited_claims:
        lines.append(f"- PROHIBITED claims — never use these: {', '.join(facts.prohibited_claims)}")
    if facts.missing_information:
        lines.append(
            "- NOT YET VERIFIED (do not invent a value for these — omit or write only what's "
            f"already given above instead): {', '.join(facts.missing_information)}"
        )
    lines.append(
        "These are the only facts confirmed true for this specific product. Do not invent "
        "ingredients, percentages, certifications, rankings, medical benefits, prices, discounts, "
        "availability, shipping guarantees, clinical claims, or awards beyond what's listed above."
    )
    return "\n".join(lines)
