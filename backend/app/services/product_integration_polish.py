from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageFilter

CANVAS_SIZE = (1024, 1536)


@dataclass(frozen=True)
class ShadowProfile:
    name: str
    horizontal_scale: float
    height_px: int
    blur_radius: float
    opacity: float
    y_offset: int


SHADOW_PROFILES = (
    ShadowProfile(
        name="subtle",
        horizontal_scale=0.90,
        height_px=58,
        blur_radius=30.0,
        opacity=0.20,
        y_offset=8,
    ),
    ShadowProfile(
        name="balanced",
        horizontal_scale=0.92,
        height_px=66,
        blur_radius=27.0,
        opacity=0.24,
        y_offset=10,
    ),
    ShadowProfile(
        name="strong",
        horizontal_scale=0.94,
        height_px=74,
        blur_radius=24.0,
        opacity=0.28,
        y_offset=12,
    ),
)

RECOMMENDED_PROFILE = "balanced"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def save_png(image: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="PNG", optimize=False, compress_level=9)


def validate_layer(
    path: Path,
    expected_sha256: str,
    *,
    required_mode: str | None = None,
) -> dict[str, Any]:
    path = path.resolve()
    if not path.is_file():
        raise RuntimeError(f"Required V3.38 layer missing: {path}")
    actual_sha = sha256_file(path)
    if actual_sha.lower() != expected_sha256.lower():
        raise RuntimeError(f"V3.38 layer SHA-256 mismatch: {path.name}")
    with Image.open(path) as image:
        image.load()
        if image.size != CANVAS_SIZE:
            raise RuntimeError(
                f"Unexpected V3.38 layer dimensions for {path.name}: {image.size!r}"
            )
        if required_mode is not None and image.mode != required_mode:
            raise RuntimeError(
                f"Unexpected V3.38 layer mode for {path.name}: {image.mode!r}"
            )
        return {
            "path": str(path),
            "sha256": actual_sha,
            "width": image.width,
            "height": image.height,
            "mode": image.mode,
        }


def alpha_bbox(product_layer: Image.Image) -> tuple[int, int, int, int]:
    if product_layer.mode != "RGBA":
        raise RuntimeError("Locked product layer must be RGBA.")
    bbox = product_layer.getchannel("A").getbbox()
    if bbox is None:
        raise RuntimeError("Locked product layer contains no visible alpha.")
    return bbox


def build_contact_shadow(
    locked_product_layer: Image.Image,
    profile: ShadowProfile,
) -> tuple[Image.Image, dict[str, Any]]:
    if locked_product_layer.size != CANVAS_SIZE:
        raise RuntimeError("Locked product layer size mismatch.")
    bbox = alpha_bbox(locked_product_layer)
    x0, y0, x1, y1 = bbox
    alpha_crop = locked_product_layer.getchannel("A").crop(bbox)
    source_width = x1 - x0
    if source_width <= 0:
        raise RuntimeError("Locked product alpha width is invalid.")
    target_width = max(1, int(round(source_width * profile.horizontal_scale)))
    target_height = max(1, int(profile.height_px))
    compressed = alpha_crop.resize(
        (target_width, target_height),
        resample=Image.Resampling.LANCZOS,
    )
    compressed = compressed.filter(
        ImageFilter.GaussianBlur(radius=profile.blur_radius)
    )
    compressed = compressed.point(
        lambda value: int(round(value * profile.opacity))
    )
    shadow_x = int(round(((x0 + x1) / 2) - (target_width / 2)))
    shadow_y = int(round(y1 - (target_height / 2) + profile.y_offset))
    max_y = CANVAS_SIZE[1] - target_height
    shadow_y = max(0, min(shadow_y, max_y))
    shadow_x = max(0, min(shadow_x, CANVAS_SIZE[0] - target_width))
    shadow_rgba = Image.new("RGBA", CANVAS_SIZE, (0, 0, 0, 0))
    patch = Image.new(
        "RGBA",
        (target_width, target_height),
        (10, 6, 16, 255),
    )
    patch.putalpha(compressed)
    shadow_rgba.alpha_composite(patch, dest=(shadow_x, shadow_y))
    return shadow_rgba, {
        "profile": asdict(profile),
        "source_alpha_bbox": list(bbox),
        "shadow_x": shadow_x,
        "shadow_y": shadow_y,
        "shadow_width": target_width,
        "shadow_height": target_height,
        "source": "locked_product_alpha_mask",
        "ai_generated": False,
        "product_pixels_modified": False,
    }


def compose_polished(
    *,
    background: Image.Image,
    shadow_layer: Image.Image,
    locked_product_layer: Image.Image,
    text_layer: Image.Image,
) -> Image.Image:
    for name, image in (
        ("background", background),
        ("shadow", shadow_layer),
        ("locked product", locked_product_layer),
        ("text", text_layer),
    ):
        if image.size != CANVAS_SIZE:
            raise RuntimeError(f"{name} layer size mismatch.")
    final = background.convert("RGBA").copy()
    final.alpha_composite(shadow_layer.convert("RGBA"))
    final.alpha_composite(locked_product_layer.convert("RGBA"))
    final.alpha_composite(text_layer.convert("RGBA"))
    return final


def render_profile(
    *,
    background_path: Path,
    locked_product_path: Path,
    text_layer_path: Path,
    background_sha256: str,
    locked_product_sha256: str,
    text_layer_sha256: str,
    profile: ShadowProfile,
    output_dir: Path,
) -> dict[str, Any]:
    validate_layer(background_path, background_sha256)
    locked_validation = validate_layer(
        locked_product_path,
        locked_product_sha256,
        required_mode="RGBA",
    )
    validate_layer(
        text_layer_path,
        text_layer_sha256,
        required_mode="RGBA",
    )
    product_sha_before = sha256_file(locked_product_path)
    with Image.open(background_path) as background_image:
        background = background_image.convert("RGBA")
    with Image.open(locked_product_path) as product_image:
        locked_product = product_image.convert("RGBA")
    with Image.open(text_layer_path) as text_image:
        text_layer = text_image.convert("RGBA")
    shadow_layer, shadow_meta = build_contact_shadow(
        locked_product,
        profile,
    )
    shadow_path = output_dir / f"contact-shadow-{profile.name}.png"
    final_path = output_dir / f"final-{profile.name}.png"
    save_png(shadow_layer, shadow_path)
    final = compose_polished(
        background=background,
        shadow_layer=shadow_layer,
        locked_product_layer=locked_product,
        text_layer=text_layer,
    )
    save_png(final, final_path)
    product_sha_after = sha256_file(locked_product_path)
    if product_sha_after != product_sha_before:
        raise RuntimeError("Locked product layer changed during V3.39 rendering.")
    return {
        "profile": profile.name,
        "shadow": {
            **shadow_meta,
            "path": str(shadow_path),
            "sha256": sha256_file(shadow_path),
        },
        "final": {
            "path": str(final_path),
            "sha256": sha256_file(final_path),
            "width": final.width,
            "height": final.height,
        },
        "locked_product_source": locked_validation,
        "locked_product_sha256_before": product_sha_before,
        "locked_product_sha256_after": product_sha_after,
        "locked_product_layer_immutability": product_sha_before == product_sha_after,
        "product_pixel_mutation_count": 0,
        "reflection_enabled": False,
    }