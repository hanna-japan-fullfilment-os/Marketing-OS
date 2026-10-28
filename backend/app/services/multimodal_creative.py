"""Unified creative bridge. No V9 renderer, automatic retry, fallback or publication."""
from __future__ import annotations

import hashlib
import io
import unicodedata
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from ..schemas.creative_bridge import CreativeReview, HannaCreativePackage
from .hanna_creative_package import verified_image_bytes


def normalize_copy(value: str) -> str:
    # Whitespace/Unicode canonical equivalence only; accents, digits and case stay exact.
    return " ".join(unicodedata.normalize("NFC", value).split())


def candidate_size(data: bytes, package: HannaCreativePackage):
    if not data or len(data) > 32 * 1024 * 1024:
        raise ValueError("Invalid candidate size")
    with Image.open(io.BytesIO(data)) as image:
        image.load()
        if image.size != (package.width, package.height):
            raise ValueError("Candidate dimensions differ from handoff")


def require_final_acceptance(package: HannaCreativePackage, data: bytes, review: CreativeReview):
    """Only a bound, complete independent review can authorize a final asset."""
    for image in package.images:
        verified_image_bytes(image)
    candidate_size(data, package)
    if review.package_sha256 != package.digest() or review.candidate_sha256 != hashlib.sha256(data).hexdigest():
        raise ValueError("Stale or unrelated QA")
    product = review.product.model_dump()
    if product.pop("overall_verdict") != "PASS":
        raise ValueError("Product identity QA failed")
    product.pop("reasoning")
    if any(value != "match" for value in product.values()) or any(
            getattr(review, key) != "match" for key in ("major_elements", "components", "variant")):
        raise ValueError("Product identity uncertain or mismatched")
    expected = {c.key: normalize_copy(c.text) for c in package.approved_copy}
    observed = {c.key: normalize_copy(c.text) for c in review.observed_copy}
    if len(observed) != len(review.observed_copy) or expected != observed or review.unexpected_marketing_text or review.unsupported_claims:
        raise ValueError("Canonical copy/claim QA failed")
    x, y, right, bottom = review.product_box
    if not (0 <= x < right <= package.width and 0 <= y < bottom <= package.height):
        raise ValueError("Invalid product geometry")
    if not review.no_clipping or not review.no_overlap:
        raise ValueError("Structural QA failed")
    for key in ("scene_cohesion", "product_integration", "reference_style", "no_disconnected_cards",
                "logo_integration", "typography_integration", "premium_polish"):
        if getattr(review, key) != "PASS":
            raise ValueError("Visual QA failed: " + key)


def overlay_canonical_copy(package: HannaCreativePackage, clean_canvas: bytes, *, fonts: dict[str, Path]) -> bytes:
    """Direct transparent typography only. No panel, shortening, resize or placement fallback.

    The final result still requires whole-image QA; prepared negative space is not
    inferred from a layout rectangle or treated as proof of visual acceptance.
    """
    if package.text_mode != "negative_space_overlay":
        raise ValueError("Explicit overlay mode required")
    candidate_size(clean_canvas, package)
    with Image.open(io.BytesIO(clean_canvas)) as source:
        canvas = source.convert("RGBA")
    draw = ImageDraw.Draw(canvas)
    copy = {c.key: c.text for c in package.approved_copy}
    boxes = []
    for region in package.text_regions:
        x, y, right, bottom = region.box
        if not 0 <= x < right <= package.width or not 0 <= y < bottom <= package.height:
            raise ValueError("Prepared text region out of bounds")
        if any(x < r and right > l and y < b and bottom > t for l, t, r, b in boxes):
            raise ValueError("Prepared typography overlaps")
        boxes.append(region.box)
        if region.font_id not in fonts:
            raise ValueError("Approved font unavailable")
        font = ImageFont.truetype(str(fonts[region.font_id]), region.font_size)
        text = copy[region.key]
        left, top, r, b = draw.multiline_textbbox((0, 0), text, font=font)
        if r - left > right - x or b - top > bottom - y:
            raise ValueError("Canonical text does not fit; explicit re-layout required")
        draw.multiline_text((x-left, y-top), text, font=font, fill=region.color)
    output = io.BytesIO()
    canvas.save(output, "PNG")
    return output.getvalue()


async def compose_candidate(package, provider, options):
    """One explicit attempt. Exceptions propagate; no implicit alternate backend."""
    native = tuple(int(n) for n in options.image_size.split("x"))
    if native[0] * package.height != native[1] * package.width:
        raise ValueError("Native generation aspect differs from final handoff")
    for image in package.images:
        verified_image_bytes(image)
    data = await provider.compose_creative(package=package, options=options)
    if not data or len(data) > 32 * 1024 * 1024:
        raise ValueError("Invalid candidate size")
    with Image.open(io.BytesIO(data)) as image:
        image.load()
        if image.size != native:
            raise ValueError("Provider returned unexpected native dimensions")
        if image.size != (package.width, package.height):
            # Whole-artwork resampling only, never cropping/rebuilding a package.
            image = image.resize((package.width, package.height), Image.Resampling.LANCZOS)
            output = io.BytesIO()
            image.save(output, "PNG")
            data = output.getvalue()
    candidate_size(data, package)
    return data


async def review_candidate(package, data, provider, *, model):
    candidate_size(data, package)
    review = await provider.review_creative(package=package, candidate=data, model=model)
    require_final_acceptance(package, data, review)
    return review


def store_accepted_asset(package, data, review, destination: Path):
    require_final_acceptance(package, data, review)
    # Exclusive creation: preserve every accepted artifact and its hash; no DB mutation.
    with destination.open("xb") as stream:
        stream.write(data)
    return {"path": str(destination), "sha256": hashlib.sha256(data).hexdigest(),
            "package_sha256": package.digest(), "review_sha256": review.digest()}
