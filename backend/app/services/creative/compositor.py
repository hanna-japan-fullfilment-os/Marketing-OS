"""Pillow compositor (campaign-pipeline.md hybrid pipeline, steps 5-6).

This is the step that keeps the brief's central promise: the pixels the user
actually photographed are pasted onto a new background, never redrawn by an AI
model. Everything here is deterministic (no AI calls) and operates purely on
Pillow Images already loaded into memory — safe to unit test without a network
call or an API key.
"""
from __future__ import annotations

from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFilter


@dataclass(frozen=True)
class ProductZone:
    """The rectangle (canvas pixels) the product is scaled to fit inside, anchored
    within it. Templates own this so the product placement and the text-safe areas
    are designed together and never collide.
    """

    left: int
    top: int
    width: int
    height: int
    anchor: str = "center"  # center | bottom | top

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("ProductZone width/height must be positive")
        if self.anchor not in ("center", "bottom", "top"):
            raise ValueError(f"Unsupported anchor: {self.anchor!r}")


_DEFAULT_GRADIENT = ("#f5f1ea", "#e4dccb")  # warm neutral studio backdrop


def make_background(
    *, width: int, height: int, colors: list[str] | None = None
) -> Image.Image:
    """Deterministic vertical-gradient background built from brand colors, used when
    no AI-generated scene is supplied (or as the base an AI background later replaces
    — see pipeline.py). Falls back to a neutral studio gradient when the brand hasn't
    configured colors yet, so the pipeline never breaks on an empty brand profile.
    """
    top_hex, bottom_hex = (colors[0], colors[-1]) if colors and len(colors) >= 1 else _DEFAULT_GRADIENT
    if colors and len(colors) == 1:
        bottom_hex = colors[0]
    top_rgb = _hex_to_rgb(top_hex)
    bottom_rgb = _hex_to_rgb(bottom_hex)

    canvas = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(canvas)
    for y in range(height):
        t = y / max(height - 1, 1)
        row = tuple(int(top_rgb[i] + (bottom_rgb[i] - top_rgb[i]) * t) for i in range(3))
        draw.line([(0, y), (width, y)], fill=row)
    return canvas


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    if len(value) == 3:
        value = "".join(ch * 2 for ch in value)
    if len(value) != 6:
        return _hex_to_rgb(_DEFAULT_GRADIENT[0])
    try:
        return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]
    except ValueError:
        return _hex_to_rgb(_DEFAULT_GRADIENT[0])


def _fit_dimensions(src_w: int, src_h: int, zone_w: int, zone_h: int) -> tuple[int, int]:
    """Scale-to-fit (preserve aspect ratio, never crop) within the zone. Allows
    modest upscaling (up to 1.5x native resolution) so a smaller-than-zone product
    photo still fills a reasonable amount of the zone, but caps it there to avoid
    visibly softening a real photo.
    """
    scale = min(zone_w / src_w, zone_h / src_h)
    scale = min(scale, 1.5)
    return max(1, round(src_w * scale)), max(1, round(src_h * scale))



def _placed_product_rgba(
    *,
    product: Image.Image,
    zone: ProductZone,
) -> tuple[Image.Image, int, int]:
    """Canonical deterministic resize + position transform for a product.

    BUILD6R_MASKED_SCENE_PRODUCT_TRANSFORM_V1
    """
    product_rgba = product.convert(
        "RGBA"
    )

    target_w, target_h = _fit_dimensions(
        product_rgba.width,
        product_rgba.height,
        zone.width,
        zone.height,
    )

    resized = product_rgba.resize(
        (
            target_w,
            target_h,
        ),
        Image.LANCZOS,
    )

    paste_x = (
        zone.left
        + (
            zone.width
            - target_w
        )
        // 2
    )

    if zone.anchor == "bottom":
        paste_y = (
            zone.top
            + zone.height
            - target_h
        )

    elif zone.anchor == "top":
        paste_y = zone.top

    else:
        paste_y = (
            zone.top
            + (
                zone.height
                - target_h
            )
            // 2
        )

    return (
        resized,
        paste_x,
        paste_y,
    )


def build_product_overlay(
    *,
    canvas_size: tuple[int, int],
    product: Image.Image,
    zone: ProductZone,
) -> Image.Image:
    """Return only the deterministic product pixels on a transparent canvas."""
    layer = Image.new(
        "RGBA",
        canvas_size,
        (
            0,
            0,
            0,
            0,
        ),
    )

    resized, paste_x, paste_y = (
        _placed_product_rgba(
            product=product,
            zone=zone,
        )
    )

    layer.paste(
        resized,
        (
            paste_x,
            paste_y,
        ),
        resized,
    )

    return layer


def build_product_protection_mask(
    *,
    canvas_size: tuple[int, int],
    product: Image.Image,
    zone: ProductZone,
    padding: int = 18,
) -> Image.Image:
    """Protect product pixels while leaving the surrounding scene editable.

    Transparent alpha is editable. Opaque alpha protects the product.
    The modest padded boundary protects anti-aliased edge pixels because
    the model mask is guidance rather than a mathematical pixel lock.
    """
    overlay = build_product_overlay(
        canvas_size=canvas_size,
        product=product,
        zone=zone,
    )

    alpha = overlay.getchannel(
        "A"
    )

    safe_padding = max(
        0,
        int(
            padding
        ),
    )

    if safe_padding:
        alpha = alpha.filter(
            ImageFilter.MaxFilter(
                safe_padding
                * 2
                + 1
            )
        )

    mask = Image.new(
        "RGBA",
        canvas_size,
        (
            255,
            255,
            255,
            255,
        ),
    )

    mask.putalpha(
        alpha
    )

    return mask


def _drop_shadow(
    size: tuple[int, int],
    *,
    blur: int = 24,
    opacity: int = 90,
) -> Image.Image:
    """BUILD6R_PREMIUM_CONTACT_SHADOW_V1.

    Render a restrained ground/contact shadow rather than a large
    floating catalog shadow. The authentic product pixels are never
    changed; this creates only a separate transparent shadow layer.
    """

    w, h = size

    pad = max(
        36,
        blur * 2,
    )

    shadow = Image.new(
        "RGBA",
        (
            w + pad * 2,
            h + pad * 2,
        ),
        (
            0,
            0,
            0,
            0,
        ),
    )

    draw = ImageDraw.Draw(
        shadow
    )

    ellipse_w = max(
        28,
        round(
            w * 0.56
        ),
    )

    ellipse_h = max(
        14,
        round(
            w * 0.055
        ),
    )

    center_x = (
        shadow.width
        // 2
    )

    center_y = (
        pad
        + h
        - round(
            ellipse_h * 0.12
        )
    )

    effective_opacity = min(
        int(opacity),
        42,
    )

    draw.ellipse(
        (
            center_x
            - ellipse_w
            // 2,
            center_y
            - ellipse_h
            // 2,
            center_x
            + ellipse_w
            // 2,
            center_y
            + ellipse_h
            // 2,
        ),
        fill=(
            30,
            25,
            18,
            effective_opacity,
        ),
    )

    effective_blur = max(
        10,
        round(
            blur * 0.75
        ),
    )

    return shadow.filter(
        ImageFilter.GaussianBlur(
            effective_blur
        )
    )



def composite_product(
    *,
    background: Image.Image,
    product: Image.Image,
    zone: ProductZone,
    shadow: bool = True,
) -> Image.Image:
    """Alpha-composite `product` (already background-isolated, RGBA) onto a copy of
    `background`, scaled to fit `zone` and anchored within it. Neither input is
    mutated. Returns an RGB image the same size as `background`.
    """
    canvas = background.convert("RGB").copy()
    resized, paste_x, paste_y = _placed_product_rgba(
        product=product,
        zone=zone,
    )

    target_w, target_h = resized.size

    if shadow:
        shadow_layer = _drop_shadow((target_w, target_h))
        shadow_x = paste_x - (shadow_layer.width - target_w) // 2
        shadow_y = paste_y - (shadow_layer.height - target_h) // 2
        canvas.paste(shadow_layer, (shadow_x, shadow_y), shadow_layer)

    canvas.paste(resized, (paste_x, paste_y), resized)
    return canvas
