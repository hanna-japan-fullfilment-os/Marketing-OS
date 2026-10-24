from __future__ import annotations

import hashlib
import io
import json
import re
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageFilter, ImageOps


V338_BASE_WIDTH = 1024
V338_BASE_HEIGHT = 1536

PRODUCT_MAX_WIDTH_RATIO = 820 / V338_BASE_WIDTH
PRODUCT_MAX_HEIGHT_RATIO = 1100 / V338_BASE_HEIGHT
PRODUCT_CENTER_X_RATIO = 512 / V338_BASE_WIDTH
PRODUCT_BOTTOM_Y_RATIO = 1490 / V338_BASE_HEIGHT
PRODUCT_SAFE_TOP_RATIO = 340 / V338_BASE_HEIGHT


@dataclass(frozen=True)
class ProductPlacement:
    """Validated geometry; package artwork is never edited or cropped."""
    width_fraction: float
    horizontal: str
    vertical: str

    def __post_init__(self):
        if (isinstance(self.width_fraction, bool)
                or not isinstance(self.width_fraction, (int, float))
                or not math.isfinite(self.width_fraction)
                or not 0 < self.width_fraction <= 1
                or self.horizontal not in ("left", "center", "right")
                or self.vertical not in ("upper", "center", "lower")):
            raise ValueError("Invalid prepared product placement")


def prepared_product_placement(visual_brief: str) -> ProductPlacement | None:
    """Read explicit prepared JSON geometry, never infer it from AI prose.

    Legacy briefs without geometry retain their existing layout. A partial or
    malformed explicit contract fails closed rather than silently reverting.
    """
    if not visual_brief or not visual_brief.lstrip().startswith("{"):
        return None
    try:
        brief = json.loads(visual_brief)
    except (TypeError, ValueError) as exc:
        raise ValueError("Malformed prepared placement JSON") from exc
    if not isinstance(brief, dict):
        raise ValueError("Prepared visual brief must be an object")
    if not ({"PRODUCT_SCALE", "PRODUCT_PLACEMENT"} & brief.keys()):
        return None
    scale, position = brief.get("PRODUCT_SCALE"), brief.get("PRODUCT_PLACEMENT")
    if not isinstance(scale, str) or not isinstance(position, str):
        raise ValueError("Prepared width and placement are both required")
    match = re.fullmatch(r"(\d+(?:\.\d+)?)% canvas width", scale.strip())
    anchors = {
        f"{horizontal} {vertical} half": (horizontal, vertical)
        for horizontal in ("left", "center", "right")
        for vertical in ("upper", "lower")
    }
    anchors.update({f"{vertical}-{horizontal}": (horizontal, vertical)
                    for horizontal in ("left", "center", "right")
                    for vertical in ("upper", "lower")})
    anchors["center"] = ("center", "center")
    if match is None or position.strip() not in anchors:
        raise ValueError("Unsupported prepared product placement")
    horizontal, vertical = anchors[position.strip()]
    return ProductPlacement(float(match.group(1)) / 100, horizontal, vertical)


@dataclass(frozen=True)
class ShadowProfile:
    name: str
    horizontal_scale: float
    height_ratio: float
    blur_radius_ratio: float
    opacity: float
    y_offset_ratio: float


V339_STRONG_SHADOW_PROFILE = ShadowProfile(
    name="strong",
    horizontal_scale=0.94,
    height_ratio=74 / V338_BASE_HEIGHT,
    blur_radius_ratio=24 / V338_BASE_HEIGHT,
    opacity=0.28,
    y_offset_ratio=12 / V338_BASE_HEIGHT,
)


@dataclass
class LockedProductCompositeResult:
    image: Image.Image
    locked_product_layer: Image.Image
    shadow_layer: Image.Image
    metadata: dict[str, Any]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_png(image: Image.Image) -> str:
    payload = io.BytesIO()
    image.save(payload, format="PNG", optimize=False, compress_level=9)
    return hashlib.sha256(payload.getvalue()).hexdigest()


def _looks_like_approved_master_path(path: Path) -> bool:
    return any(
        part.lower() == "approved_product_masters"
        for part in path.resolve().parts
    )


def inspect_locked_product_master_candidate(
    master_path: Path,
    *,
    expected_sha256: str,
) -> dict[str, Any] | None:
    """Return locked-master metadata only for explicit approved master paths.

    Ordinary legacy JPEG/PNG assets must bypass the locked-product route without
    canonical SHA enforcement. Explicit approved masters fail closed on missing
    SHA, SHA mismatch, decode failure, or alpha-contract failure.
    """
    master_path = master_path.resolve()
    if not master_path.is_file():
        raise RuntimeError(f"Render asset not found: {master_path}")

    claimed_approved_master = _looks_like_approved_master_path(master_path)
    if not claimed_approved_master:
        return None

    expected = str(expected_sha256 or "").strip().lower()
    if not expected:
        raise RuntimeError(
            "Approved product master is missing its canonical SHA-256."
        )

    actual_sha = sha256_file(master_path).lower()
    if actual_sha != expected:
        raise RuntimeError(
            f"Approved product master SHA-256 mismatch: {master_path.name}"
        )

    try:
        with Image.open(master_path) as image:
            image.load()
            image_format = str(image.format or "").upper()
            image_mode = image.mode

            if image_format != "PNG" or image_mode != "RGBA":
                raise RuntimeError(
                    "Approved product master must be a PNG RGBA image."
                )

            alpha = image.getchannel("A")
            alpha_extrema = alpha.getextrema()
            alpha_bbox = alpha.getbbox()

            eligible = (
                alpha_bbox is not None
                and alpha_extrema is not None
                and alpha_extrema[0] < 255
                and alpha_extrema[1] > 0
            )
            if not eligible:
                raise RuntimeError(
                    "Approved product master must contain transparent and "
                    "visible alpha pixels."
                )

            return {
                "path": str(master_path),
                "sha256": actual_sha,
                "width": image.width,
                "height": image.height,
                "format": image_format,
                "mode": image_mode,
                "alpha_bbox": list(alpha_bbox),
                "alpha_extrema": list(alpha_extrema),
                "approved_master_path": True,
            }
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(
            f"Unable to decode approved product master: {exc}"
        ) from exc


def _build_locked_product_layer(
    *,
    master_path: Path,
    validation: dict[str, Any],
    canvas_size: tuple[int, int],
    placement: ProductPlacement | None = None,
) -> tuple[Image.Image, dict[str, Any]]:
    canvas_width, canvas_height = canvas_size
    if canvas_width <= 0 or canvas_height <= 0:
        raise RuntimeError("Locked-product canvas dimensions must be positive.")

    with Image.open(master_path) as source:
        source = source.convert("RGBA")
        alpha_bbox = tuple(validation["alpha_bbox"])
        cropped = source.crop(alpha_bbox)

    crop_width, crop_height = cropped.size
    if crop_width <= 0 or crop_height <= 0:
        raise RuntimeError("Approved master alpha crop is empty.")

    product_max_width = max(1, int(round(canvas_width * PRODUCT_MAX_WIDTH_RATIO)))
    product_max_height = max(1, int(round(canvas_height * PRODUCT_MAX_HEIGHT_RATIO)))
    product_center_x = int(round(canvas_width * PRODUCT_CENTER_X_RATIO))
    product_bottom_y = int(round(canvas_height * PRODUCT_BOTTOM_Y_RATIO))
    product_safe_top = int(round(canvas_height * PRODUCT_SAFE_TOP_RATIO))

    scale = min(
        product_max_width / crop_width,
        product_max_height / crop_height,
    )
    if scale <= 0:
        raise RuntimeError("Invalid locked-product scale.")

    if placement is not None:
        if not isinstance(placement, ProductPlacement):
            raise ValueError("Validated product placement required")
        scale = canvas_width * placement.width_fraction / crop_width

    rendered_width = max(1, int(round(crop_width * scale)))
    rendered_height = max(1, int(round(crop_height * scale)))
    resized = cropped.resize(
        (rendered_width, rendered_height),
        resample=Image.Resampling.LANCZOS,
    )

    x = int(round(product_center_x - (rendered_width / 2)))
    y = product_bottom_y - rendered_height

    if placement is not None:
        margin_x = int(round(canvas_width * (1 - PRODUCT_BOTTOM_Y_RATIO)))
        x = {"left": margin_x, "center": (canvas_width - rendered_width) // 2,
             "right": canvas_width - margin_x - rendered_width}[placement.horizontal]
        y = {"upper": product_safe_top,
             "center": (product_safe_top + product_bottom_y - rendered_height) // 2,
             "lower": product_bottom_y - rendered_height}[placement.vertical]
        if y + rendered_height > product_bottom_y:
            raise ValueError("Prepared product placement exceeds safe bounds")
        product_center_x = x + rendered_width / 2

    if x < 0 or y < 0:
        raise RuntimeError("Locked-product placement exceeds canvas.")
    if x + rendered_width > canvas_width:
        raise RuntimeError("Locked-product width exceeds canvas.")
    if y + rendered_height > canvas_height:
        raise RuntimeError("Locked-product height exceeds canvas.")
    if y < product_safe_top:
        raise RuntimeError(
            "Locked product intrudes into deterministic typography safe area."
        )

    layer = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
    layer.alpha_composite(resized, dest=(x, y))

    return layer, {
        "source_alpha_bbox": list(alpha_bbox),
        **({"prepared_width_fraction": placement.width_fraction,
            "horizontal_anchor": placement.horizontal, "vertical_anchor": placement.vertical}
           if placement is not None else {}),
        "crop_width": crop_width,
        "crop_height": crop_height,
        "rendered_width": rendered_width,
        "rendered_height": rendered_height,
        "product_x": x,
        "product_y": y,
        "product_center_x": product_center_x,
        "product_bottom_y": product_bottom_y,
        "product_max_width": product_max_width,
        "product_max_height": product_max_height,
        "product_safe_top": product_safe_top,
        "rotation_degrees": 0,
        "perspective_transform": False,
        "resampling_method": "LANCZOS",
    }


def _build_contact_shadow(
    *,
    locked_product_layer: Image.Image,
    profile: ShadowProfile,
) -> tuple[Image.Image, dict[str, Any]]:
    if locked_product_layer.mode != "RGBA":
        raise RuntimeError("Locked product layer must be RGBA.")

    canvas_width, canvas_height = locked_product_layer.size
    alpha = locked_product_layer.getchannel("A")
    bbox = alpha.getbbox()
    if bbox is None:
        raise RuntimeError("Locked product layer contains no visible alpha.")

    x0, _y0, x1, y1 = bbox
    alpha_crop = alpha.crop(bbox)
    source_width = x1 - x0
    if source_width <= 0:
        raise RuntimeError("Locked product alpha width is invalid.")

    target_width = max(1, int(round(source_width * profile.horizontal_scale)))
    target_height = max(1, int(round(canvas_height * profile.height_ratio)))
    blur_radius = max(0.1, canvas_height * profile.blur_radius_ratio)
    y_offset = int(round(canvas_height * profile.y_offset_ratio))

    compressed = alpha_crop.resize(
        (target_width, target_height),
        resample=Image.Resampling.LANCZOS,
    )
    compressed = compressed.filter(
        ImageFilter.GaussianBlur(radius=blur_radius)
    )
    compressed = compressed.point(
        lambda value: int(round(value * profile.opacity))
    )

    shadow_x = int(round(((x0 + x1) / 2) - (target_width / 2)))
    shadow_y = int(round(y1 - (target_height / 2) + y_offset))
    shadow_x = max(0, min(shadow_x, canvas_width - target_width))
    shadow_y = max(0, min(shadow_y, canvas_height - target_height))

    shadow = Image.new("RGBA", locked_product_layer.size, (0, 0, 0, 0))
    patch = Image.new("RGBA", (target_width, target_height), (10, 6, 16, 255))
    patch.putalpha(compressed)
    shadow.alpha_composite(patch, dest=(shadow_x, shadow_y))

    return shadow, {
        "profile": asdict(profile),
        "source_alpha_bbox": list(bbox),
        "shadow_x": shadow_x,
        "shadow_y": shadow_y,
        "shadow_width": target_width,
        "shadow_height": target_height,
        "blur_radius_px": blur_radius,
        "y_offset_px": y_offset,
        "source": "locked_product_alpha_mask",
        "ai_generated": False,
        "product_pixels_modified": False,
    }


def build_locked_product_composite(
    *,
    background: Image.Image,
    master_path: Path,
    expected_sha256: str,
    canvas_size: tuple[int, int],
    shadow_profile: ShadowProfile = V339_STRONG_SHADOW_PROFILE,
    placement: ProductPlacement | None = None,
) -> LockedProductCompositeResult:
    validation = inspect_locked_product_master_candidate(
        master_path,
        expected_sha256=expected_sha256,
    )
    if validation is None:
        raise RuntimeError(
            "Render asset is not eligible for locked-product composition."
        )

    source_sha_before = sha256_file(master_path)
    fitted_background = ImageOps.fit(
        background.convert("RGBA"),
        canvas_size,
        method=Image.Resampling.LANCZOS,
        centering=(0.5, 0.5),
    )

    locked_product_layer, placement = _build_locked_product_layer(
        master_path=master_path,
        validation=validation,
        canvas_size=canvas_size,
        placement=placement,
    )
    shadow_layer, shadow = _build_contact_shadow(
        locked_product_layer=locked_product_layer,
        profile=shadow_profile,
    )

    final = fitted_background.copy()
    final.alpha_composite(shadow_layer)
    final.alpha_composite(locked_product_layer)

    source_sha_after = sha256_file(master_path)
    if source_sha_after != source_sha_before:
        raise RuntimeError(
            "Approved product master changed during locked composition."
        )

    metadata = {
        "mode": "locked_product_composite",
        "master": validation,
        "placement": placement,
        "shadow": shadow,
        "shadow_profile": shadow_profile.name,
        "source_master_sha256_before": source_sha_before,
        "source_master_sha256_after": source_sha_after,
        "source_master_immutability": source_sha_before == source_sha_after,
        "locked_product_layer_sha256": sha256_png(locked_product_layer),
        "shadow_layer_sha256": sha256_png(shadow_layer),
        "composite_visual_sha256": sha256_png(final),
        "contact_shadow_generated": True,
        "product_pixel_mutation_count": 0,
        "ai_product_generation": False,
        "ai_product_editing": False,
        "product_reference_image_count": 0,
        "background_reference_image_count": 0,
        "deterministic_typography_owner": "existing_creative_renderer",
        "background_fit_method": "ImageOps.fit/LANCZOS/center",
        "canvas_width": canvas_size[0],
        "canvas_height": canvas_size[1],
    }

    return LockedProductCompositeResult(
        image=final,
        locked_product_layer=locked_product_layer,
        shadow_layer=shadow_layer,
        metadata=metadata,
    )
