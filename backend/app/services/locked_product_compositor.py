from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

CANVAS_WIDTH = 1024
CANVAS_HEIGHT = 1536
PRODUCT_MAX_WIDTH = 820
PRODUCT_MAX_HEIGHT = 1100
PRODUCT_CENTER_X = 512
PRODUCT_BOTTOM_Y = 1490

FROZEN_HEADLINE = "LuLuLun Hydra EX"
FROZEN_SUPPORT = "Máscara facial • 7 folhas"
FROZEN_DETAIL = "150 mL de essência"

HEADLINE_FONT_SIZE = 86
SUPPORT_FONT_SIZE = 48
DETAIL_FONT_SIZE = 44
HEADLINE_Y = 70
SUPPORT_Y = 194
DETAIL_Y = 268
TEXT_MAX_WIDTH = 900

TEXT_FILL = (255, 255, 255, 255)
TEXT_STROKE_FILL = (41, 25, 59, 180)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def save_png(image: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="PNG", optimize=False, compress_level=9)


def validate_locked_master(master_path: Path, expected_sha256: str) -> dict[str, Any]:
    master_path = master_path.resolve()
    if not master_path.is_file():
        raise RuntimeError(f"Approved product master not found: {master_path}")
    actual_sha = sha256_file(master_path)
    if actual_sha.lower() != expected_sha256.lower():
        raise RuntimeError("Approved product master SHA-256 mismatch.")
    with Image.open(master_path) as image:
        if image.format != "PNG":
            raise RuntimeError("Approved product master must be PNG.")
        if image.mode != "RGBA":
            raise RuntimeError("Approved product master must be RGBA.")
        alpha = image.getchannel("A")
        alpha_extrema = alpha.getextrema()
        alpha_bbox = alpha.getbbox()
        if alpha_bbox is None:
            raise RuntimeError("Approved product master alpha contains no visible pixels.")
        if alpha_extrema is None or alpha_extrema[0] >= 255:
            raise RuntimeError("Approved product master must contain transparent alpha pixels.")
        if alpha_extrema[1] <= 0:
            raise RuntimeError("Approved product master contains no opaque/visible alpha.")
        width, height = image.size
    return {
        "path": str(master_path),
        "sha256": actual_sha,
        "width": width,
        "height": height,
        "mode": "RGBA",
        "format": "PNG",
        "alpha_bbox": list(alpha_bbox),
        "alpha_extrema": list(alpha_extrema),
    }


def build_locked_product_layer(master_path: Path, expected_sha256: str) -> tuple[Image.Image, dict[str, Any]]:
    validation = validate_locked_master(master_path, expected_sha256)
    with Image.open(master_path) as source:
        source = source.convert("RGBA")
        alpha_bbox = tuple(validation["alpha_bbox"])
        cropped = source.crop(alpha_bbox)
        crop_width, crop_height = cropped.size
        if crop_width <= 0 or crop_height <= 0:
            raise RuntimeError("Approved master alpha crop is empty.")
        scale = min(
            PRODUCT_MAX_WIDTH / crop_width,
            PRODUCT_MAX_HEIGHT / crop_height,
        )
        if scale <= 0:
            raise RuntimeError("Invalid locked product scale.")
        rendered_width = max(1, int(round(crop_width * scale)))
        rendered_height = max(1, int(round(crop_height * scale)))
        resized = cropped.resize(
            (rendered_width, rendered_height),
            resample=Image.Resampling.LANCZOS,
        )
        x = int(round(PRODUCT_CENTER_X - (rendered_width / 2)))
        y = PRODUCT_BOTTOM_Y - rendered_height
        if x < 0 or y < 0:
            raise RuntimeError("Locked product placement exceeds canvas.")
        if x + rendered_width > CANVAS_WIDTH:
            raise RuntimeError("Locked product width exceeds canvas.")
        if y + rendered_height > CANVAS_HEIGHT:
            raise RuntimeError("Locked product height exceeds canvas.")
        if y < 340:
            raise RuntimeError("Locked product intrudes into deterministic typography safe area.")
        layer = Image.new("RGBA", (CANVAS_WIDTH, CANVAS_HEIGHT), (0, 0, 0, 0))
        layer.alpha_composite(resized, dest=(x, y))
    metadata = {
        **validation,
        "crop_width": crop_width,
        "crop_height": crop_height,
        "rendered_width": rendered_width,
        "rendered_height": rendered_height,
        "product_x": x,
        "product_y": y,
        "product_center_x": PRODUCT_CENTER_X,
        "product_bottom_y": PRODUCT_BOTTOM_Y,
        "product_max_width": PRODUCT_MAX_WIDTH,
        "product_max_height": PRODUCT_MAX_HEIGHT,
        "rotation_degrees": 0,
        "perspective_transform": False,
        "resampling_method": "LANCZOS",
    }
    return layer, metadata


def _centered_text_position(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    y: int,
) -> tuple[int, int, tuple[int, int, int, int]]:
    bbox = draw.textbbox((0, 0), text, font=font, stroke_width=1)
    width = bbox[2] - bbox[0]
    if width > TEXT_MAX_WIDTH:
        raise RuntimeError(f"Text exceeds configured safe width: {text!r}")
    x = int(round((CANVAS_WIDTH - width) / 2 - bbox[0]))
    return x, y, bbox


def render_text_layer(
    *,
    headline_font_path: Path,
    support_font_path: Path,
) -> tuple[Image.Image, dict[str, Any]]:
    headline_font_path = headline_font_path.resolve()
    support_font_path = support_font_path.resolve()
    if not headline_font_path.is_file():
        raise RuntimeError("Configured headline font file is missing.")
    if not support_font_path.is_file():
        raise RuntimeError("Configured support font file is missing.")
    headline_font = ImageFont.truetype(str(headline_font_path), HEADLINE_FONT_SIZE)
    support_font = ImageFont.truetype(str(support_font_path), SUPPORT_FONT_SIZE)
    detail_font = ImageFont.truetype(str(support_font_path), DETAIL_FONT_SIZE)
    layer = Image.new("RGBA", (CANVAS_WIDTH, CANVAS_HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    placements: list[dict[str, Any]] = []
    for role, text, font, y, size in (
        ("headline", FROZEN_HEADLINE, headline_font, HEADLINE_Y, HEADLINE_FONT_SIZE),
        ("support", FROZEN_SUPPORT, support_font, SUPPORT_Y, SUPPORT_FONT_SIZE),
        ("detail", FROZEN_DETAIL, detail_font, DETAIL_Y, DETAIL_FONT_SIZE),
    ):
        x, actual_y, bbox = _centered_text_position(draw, text, font, y)
        draw.text(
            (x, actual_y),
            text,
            font=font,
            fill=TEXT_FILL,
            stroke_width=1,
            stroke_fill=TEXT_STROKE_FILL,
        )
        placements.append(
            {
                "role": role,
                "text": text,
                "x": x,
                "y": actual_y,
                "font_size": size,
                "bbox": list(bbox),
            }
        )
    draw.line((150, 178, 874, 178), fill=(255, 255, 255, 120), width=1)
    draw.line((214, 254, 810, 254), fill=(255, 255, 255, 105), width=1)
    metadata = {
        "headline_font_path": str(headline_font_path),
        "headline_font_sha256": sha256_file(headline_font_path),
        "support_font_path": str(support_font_path),
        "support_font_sha256": sha256_file(support_font_path),
        "placements": placements,
        "copy": [FROZEN_HEADLINE, FROZEN_SUPPORT, FROZEN_DETAIL],
    }
    return layer, metadata


def compose_layers(
    *,
    background: Image.Image,
    locked_product_layer: Image.Image,
    text_layer: Image.Image,
) -> Image.Image:
    if background.size != (CANVAS_WIDTH, CANVAS_HEIGHT):
        raise RuntimeError("Background dimensions do not match locked composite canvas.")
    if locked_product_layer.size != (CANVAS_WIDTH, CANVAS_HEIGHT):
        raise RuntimeError("Locked product layer dimensions do not match canvas.")
    if text_layer.size != (CANVAS_WIDTH, CANVAS_HEIGHT):
        raise RuntimeError("Text layer dimensions do not match canvas.")
    final = background.convert("RGBA").copy()
    final.alpha_composite(locked_product_layer)
    final.alpha_composite(text_layer)
    return final