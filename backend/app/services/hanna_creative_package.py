"""Read-only canonical handoff. No SDK, renderer, registry writes or claim inference."""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path

from PIL import Image

from ..schemas.creative_bridge import CopyField, CreativeImage, HannaCreativePackage


CREATIVE_DIRECTOR_INSTRUCTIONS = """Act as a premium campaign art director. Compose one
unified artwork, not a background with disconnected UI cards. Study the actual approved
reference images for visual language, composition philosophy, hierarchy, depth, lighting,
product integration, integrated typography and brand restraint; do not pixel-copy them.
The actual source product photography is identity authority. Preserve package color,
shape, major elements, components, brand, labels and variant. A historical approved
master may have reconstruction provenance: it does not override source identity.
Integrate the canonical logo and required CTA naturally. Prioritize visual hierarchy
over filling space. Use natural Brazilian Portuguese when locale is pt-BR, preserving
every approved copy string exactly. Never invent unsupported claims, awards or rankings.
Reference copy is inspiration, never factual authority. Physical package text is not
permission to add promotional claims. No generic rectangular panel fallback.
In negative_space_overlay mode emit no marketing text: design genuinely clean space
at the prepared regions for later direct typography. Mask guidance is not proof of
identity preservation. Every final candidate needs independent product, exact-copy,
structural and visual QA. Technical render success is not visual acceptance."""


def canonical_json(value) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def image_record(*, asset_id, role, path, expected_sha256, authority, provenance) -> CreativeImage:
    data = Path(path).read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if digest != expected_sha256.lower():
        raise ValueError("Canonical asset SHA256 mismatch")
    with Image.open(io.BytesIO(data)) as image:
        image.load()
        mime = Image.MIME.get(image.format)
        width, height = image.size
    return CreativeImage(asset_id=asset_id, role=role, path=str(Path(path).resolve()),
                         sha256=digest, width=width, height=height, mime_type=mime,
                         authority=authority, provenance_json=canonical_json(provenance))


def verified_image_bytes(asset: CreativeImage) -> bytes:
    data = Path(asset.path).read_bytes()
    if hashlib.sha256(data).hexdigest() != asset.sha256:
        raise ValueError("Supplied image changed after handoff")
    with Image.open(io.BytesIO(data)) as image:
        image.load()
        if image.size != (asset.width, asset.height) or Image.MIME.get(image.format) != asset.mime_type:
            raise ValueError("Image metadata mismatch")
    return data


def build_hanna_creative_package(db, campaign, plan, *, campaign_plans, locale, channel,
                                 brand_instructions, prohibited_claims, visual_objective,
                                 width=1080, height=1350, text_mode="model_integrated",
                                 text_regions=()):
    """Resolve existing authority at handoff time; does not approve assets or mutate plans."""
    from ..models import Asset, BrandAsset, Product, Category
    from .orchestrator import validate_slide_provenance, resolve_brand_logo_path
    from .product_facts import resolve_verified_product_facts
    from .creative.pipeline import complete_slide_text_contract, structural_slide_text
    from .qa_engine import _package_mark_permission

    if db.new or db.dirty or db.deleted:
        raise ValueError("Handoff requires a clean read-only session")
    plans = tuple(campaign_plans)
    if not plans or plan not in plans or len(plans) != campaign.target_slide_count:
        raise ValueError("Complete canonical campaign plan required")
    selected = validate_slide_provenance(db, campaign, plan)
    claims = {}
    for other in plans:
        validate_slide_provenance(db, campaign, other)
        for ref in other.evidence_references:
            value = ref.model_dump(mode="json")
            if ref.claim_id in claims and claims[ref.claim_id] != value:
                raise ValueError("Inconsistent campaign claim evidence")
            claims[ref.claim_id] = value
    product = db.get(Product, campaign.product_id)
    category = db.get(Category, product.category_id) if product.category_id else None
    facts = resolve_verified_product_facts(db, product)
    facts = facts.model_dump(mode="json") if hasattr(facts, "model_dump") else facts
    from .product_creative_eligibility import require_creative_eligibility
    eligibility = require_creative_eligibility(product.id)
    images = []
    source = selected
    if selected.image_role == "product_master_approved":
        source = db.get(Asset, selected.ai_metadata["source_asset_id"])
        images.append(image_record(asset_id=selected.id, role="product_master", path=selected.absolute_path,
            expected_sha256=selected.sha256, authority="existing owner-approved master; source remains identity authority",
            provenance=selected.ai_metadata))
    if not source or not source.is_active or source.product_id != product.id or source.brand_id != campaign.brand_id:
        raise ValueError("Source product identity scope mismatch")
    images.insert(0, image_record(asset_id=source.id, role="product_source", path=source.absolute_path,
        expected_sha256=source.sha256, authority="canonical source photograph", provenance={"product_id": product.id}))
    for ref in plan.reference_assets:
        registered = db.get(BrandAsset, ref.asset_id)
        if not registered or registered.brand_id != campaign.brand_id or registered.kind != "visual_reference" or registered.label not in (
                "owner-approved-target", "approved-custom-gpt-quality-benchmark"):
            raise ValueError("Reference lacks explicit existing owner approval")
        images.append(image_record(asset_id=registered.id, role="visual_reference", path=registered.file_path,
            expected_sha256=ref.sha256, authority=registered.label, provenance=ref.model_dump(mode="json")))
    logo = resolve_brand_logo_path(db, campaign.brand_id)
    if not logo:
        raise ValueError("Canonical logo missing")
    logo_row = db.query(BrandAsset).filter_by(brand_id=campaign.brand_id, kind="logo", file_path=str(logo)).one()
    images.append(image_record(asset_id=logo_row.id, role="logo", path=logo,
        expected_sha256=hashlib.sha256(Path(logo).read_bytes()).hexdigest(), authority="canonical brand logo",
        provenance={"brand_id": campaign.brand_id, "label": logo_row.label}))
    contract = complete_slide_text_contract(plan)
    fields = dict(contract["fields"])
    fields.update(structural_slide_text(plans.index(plan) + 1, len(plans)))
    permission = _package_mark_permission(db, campaign, plan)
    return HannaCreativePackage(campaign_id=campaign.id, brand_id=campaign.brand_id,
        product_id=product.id, product_name=product.name, category=category.name if category else "Uncategorized",
        slide_id=plan.slide_id, slide_role=plan.purpose, locale=locale, channel=channel,
        approved_facts_json=canonical_json({"verified_product_facts": facts, "claim_evidence": claims,
            "creative_eligibility": eligibility,
            "asset_scoped_package_mark_permission": permission.model_dump(mode="json") if permission else None}),
        slide_contract_json=canonical_json({"plan": plan.model_dump(mode="json"), "text": contract}),
        approved_copy=tuple(CopyField(key=k, text=v) for k, v in fields.items()),
        prohibited_claims=tuple(dict.fromkeys([*facts.get("prohibited_claims", []), *prohibited_claims])), brand_instructions=brand_instructions,
        visual_objective=visual_objective, width=width, height=height, aspect_ratio=f"{width}:{height}",
        required_cta=plan.cta or "", images=tuple(images), text_mode=text_mode, text_regions=text_regions)
