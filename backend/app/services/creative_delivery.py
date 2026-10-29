"""Direct-edit preparation and crop/text delivery, separate from every V9 renderer."""
import io
import json

from PIL import Image

from ..schemas.creative_bridge import HannaCreativePackage, TextRegion
from ..schemas.creative_delivery import CompositionGuide, PreparedDelivery, SelectedReference
from .hanna_creative_package import CREATIVE_DIRECTOR_INSTRUCTIONS, canonical_json, verified_image_bytes


def select_references(package, *, alternate_product_ids=(), additional_style_ids=()):
    """Smallest useful set: source + strongest composition + required canonical logo.

    Alternates are explicit needs, not automatic image-count filling. Package order
    cannot change selection. An existing reconstructed master is never the primary
    photographic authority. The logo is labeled brand_identity, not a style exemplar.
    """
    images = {a.asset_id: a for a in package.images}
    canonical_sources = {json.loads(a.provenance_json).get("source_asset_id") for a in images.values()
                         if a.role == "product_master"}
    sources = sorted((a for a in images.values() if a.role == "product_source"),
                     key=lambda a: (a.asset_id not in canonical_sources, -a.width*a.height, a.asset_id))
    styles = sorted((a for a in images.values() if a.role == "visual_reference"),
                    key=lambda a: (a.authority != "owner-approved-target", a.asset_id))
    if not sources or not styles:
        raise ValueError("Source product and approved style references required")
    chosen = [SelectedReference(role="PRODUCT_REFERENCE", purpose="product_identity", asset=sources[0]),
              SelectedReference(role="STYLE_REFERENCE", purpose="composition_language", asset=styles[0])]
    if len(set(alternate_product_ids)) != len(alternate_product_ids) or len(set(additional_style_ids)) != len(additional_style_ids):
        raise ValueError("Duplicate requested alternate")
    for purpose, role, keys, allowed in (("product_identity", "PRODUCT_REFERENCE", alternate_product_ids,
            ("product_source", "product_master")), ("composition_language", "STYLE_REFERENCE", additional_style_ids,
            ("visual_reference",))):
        for key in sorted(keys):
            asset = images.get(key)
            if asset is None or asset.role not in allowed:
                raise ValueError("Alternate absent from canonical image role")
            chosen.append(SelectedReference(role=role, purpose=purpose, asset=asset))
    if package.logo_required:
        logos = [a for a in images.values() if a.role == "logo"]
        if len(logos) != 1:
            raise ValueError("Exactly one canonical logo required")
        chosen.append(SelectedReference(role="STYLE_REFERENCE", purpose="brand_identity", asset=logos[0]))
    if (len(chosen) > 7 or sum(r.role == "PRODUCT_REFERENCE" for r in chosen) > 3
            or sum(r.role == "STYLE_REFERENCE" for r in chosen) > 4
            or len({r.asset.asset_id for r in chosen}) != len(chosen)):
        raise ValueError("Reference selection exceeds governed counts or duplicates an input")
    for reference in chosen:
        verified_image_bytes(reference.asset)
    return tuple(chosen)


def prepare_delivery(package: HannaCreativePackage, *, text_mode="negative_space_overlay",
                     alternate_product_ids=(), additional_style_ids=()):
    regions = {"headline": (56, 70, 480, 250), "support": (56, 280, 480, 465),
               "facts": (56, 495, 480, 790), "cta": (56, 1090, 480, 1170),
               "footer": (320, 1200, 980, 1240)}
    groups = {}
    for copy in package.approved_copy:
        kind = ("headline" if copy.key in ("headline", "eyebrow") else "cta" if copy.key == "cta"
                else "footer" if copy.key in ("slide_marker", "disclaimer") else "facts"
                if copy.key.startswith(("features.", "callout_", "bottom_features.", "trust_badges.")) else "support")
        groups.setdefault(kind, []).append(copy)
    text_regions = []
    for kind, fields in groups.items():
        l, t, r, b = regions[kind]
        step = (b - t) // len(fields)
        if step < 24:
            raise ValueError("Canonical copy needs explicit re-layout; no shrink/panel fallback")
        for index, copy in enumerate(fields):
            text_regions.append(TextRegion(key=copy.key, box=(l, t + index*step, r, t+(index+1)*step-4),
                font_id="hanna_headline" if kind == "headline" else "hanna_body",
                font_size=48 if kind == "headline" else 18, color="#FFFFFF"))
    if text_mode == "model_integrated":
        text_regions = []
    final = HannaCreativePackage.model_validate({**package.model_dump(), "width": 1024, "height": 1280,
        "aspect_ratio": "1024:1280", "text_mode": text_mode, "text_regions": tuple(text_regions)})
    quiet = tuple(dict.fromkeys([*regions.values(), (56, 1200, 300, 1240), *(r.box for r in text_regions)]))
    guide = CompositionGuide(quiet_zones=quiet)
    return PreparedDelivery(original_package_sha256=package.digest(), package=final, guide=guide,
        references=select_references(final, alternate_product_ids=alternate_product_ids,
                                     additional_style_ids=additional_style_ids))


def direct_edit_prompt(delivery: PreparedDelivery):
    guide = delivery.guide
    legend = [{"image_index": index+1, "role": ref.role, "purpose": ref.purpose,
               "asset_id": ref.asset.asset_id, "sha256": ref.asset.sha256} for index, ref in enumerate(delivery.references)]
    handoff = delivery.package.model_dump(mode="json")
    # File paths and bulky historical renderer plans are not executable art direction.
    # Canonical copy/claim authority is preserved separately and unchanged.
    handoff.pop("images")
    handoff.pop("slide_contract_json")
    # Decode existing serialized data before serializing the request once. Do
    # not double-escape provenance or truncate facts to meet the API prompt cap.
    handoff["approved_facts"] = json.loads(handoff.pop("approved_facts_json"))
    prefix, separator, encoded = handoff["brand_instructions"].partition(": ")
    if separator:
        try:
            unwrapped = json.loads(encoded)
            if isinstance(unwrapped, str):
                handoff["brand_instructions"] = prefix + separator + unwrapped
        except (ValueError, TypeError):
            pass
    return (CREATIVE_DIRECTOR_INSTRUCTIONS + "\nCompose one coordinated premium advertising artwork. "
        "PRODUCT_REFERENCE defines product identity: do not substitute another model/variant, invent physical "
        "components, materially change packaging geometry, or corrupt labels. STYLE_REFERENCE defines visual "
        "language only: never blend its depicted product into the canonical product. A brand_identity image "
        "is the exact Hanna logo, not a reference product or a composition exemplar. Integrate it naturally, "
        "without a white tile or arbitrary badge. Use sophisticated depth, lighting, editorial hierarchy "
        "and deliberate negative space. No ecommerce-template appearance, Japanese clichés or clutter. "
        "The generation canvas is 1024x1536; ONLY x=[0,1024), y=[128,1408) survives. Final coordinates "
        "are 1024x1280: ADD 128 to every final y-coordinate to locate it on the generation canvas. "
        "All product, text and logo content must remain inside the retained crop. Crop margins contain "
        "expendable atmosphere only. The guide's quiet zones are genuinely designed low-detail negative "
        "space, NOT blank rectangular cards. Decorative detail belongs in decorative zones and cannot "
        "invade text, logo, product priority or breathing space. "
        + ("Emit no marketing text; design the listed exact text regions for later canonical typography. "
           if delivery.package.text_mode == "negative_space_overlay" else
           "Integrate all canonical copy verbatim in the coordinated artwork; exact-copy QA remains mandatory. ")
        + "The prepared guide controls this authorized delivery geometry; factual claims and prohibitions "
        "remain canonical. No automatic retries, no V9 compositor and no generic panel fallback.\n"
        + canonical_json({"image_roles": legend, "creative_composition_guide": guide.model_dump(),
                          "canonical_handoff": handoff}))


def crop_and_treat(delivery: PreparedDelivery, native_bytes: bytes, *, fonts=None):
    """Precomputed lossless crop, then chosen exact-text mode. Never resize/stretch."""
    if not native_bytes or len(native_bytes) > 32 * 1024 * 1024:
        raise ValueError("Invalid native candidate size")
    with Image.open(io.BytesIO(native_bytes)) as image:
        image.load()
        if image.format != "PNG" or image.size != (1024, 1536):
            raise ValueError("Unexpected native image size")
        image = image.crop(delivery.guide.final_crop)
        output = io.BytesIO()
        image.save(output, "PNG")
    data = output.getvalue()
    if delivery.package.text_mode == "negative_space_overlay":
        from .multimodal_creative import overlay_canonical_copy
        data = overlay_canonical_copy(delivery.package, data, fonts=fonts or {})
    return data


async def deliver_candidate(delivery, provider, *, fonts=None):
    """One direct edit attempt; product/copy/visual acceptance is still mandatory."""
    native = await provider.compose_direct_creative(delivery=delivery)
    return crop_and_treat(delivery, native, fonts=fonts)


def accept_delivery(delivery, data, review, destination):
    from .multimodal_creative import store_accepted_asset
    return store_accepted_asset(delivery.package, data, review, destination)
