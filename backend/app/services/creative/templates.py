"""Template registry (campaign-pipeline.md hybrid pipeline, step 7).

A template pairs (a) a `ProductZone` fraction — where the compositor places the real
product photo — with (b) an HTML/CSS builder that lays text out as real DOM text,
never baked into the AI-touched image. Playwright renders the HTML at the platform's
exact pixel dimensions, so typography, logo placement, and layout are pixel-exact and
the copy stays fully editable data up until the final render.

Adding a new template means adding one `CreativeTemplate` entry here — nothing else
in the pipeline needs to change.
"""
from __future__ import annotations

import html
from dataclasses import dataclass, field
from typing import Callable

from .compositor import ProductZone

# Build 5 repair (Part 3): a version identity for the TEMPLATE/LAYOUT SYSTEM as a
# whole (this registry's own structure — `CreativeTemplate`/`TemplateContext`'s
# shape, how a template's HTML/CSS is composed from them) — not a per-template
# version, since `template_id` (e.g. "feature_showcase", "premium_product_hero")
# already identifies WHICH template rendered a slide; this identifies the
# registry MECHANICS producing that HTML from a template's own definition. Bump
# when that composition mechanism changes in a way that could make an old
# benchmark baseline's layout not directly comparable to a new run's (a new
# section type, a changed text-block/scrim contract) — never when adding an
# unrelated new template or tweaking one template's own CSS.
TEMPLATE_REGISTRY_VERSION = '1.2.0'


@dataclass(frozen=True)
class Feature:
    """One icon + bold title + short subtitle bullet, as used by the left-side
    feature list and the bottom icon-feature strip in `feature_showcase` (round
    17) — the structure the user's own reference ads use throughout. `icon` is a
    single emoji/glyph (AI-authored, see `schemas/ai.py::SlideFeature`) rather than
    an image asset, so this never needs an icon library or extra file uploads.
    """

    icon: str = ""
    title: str = ""
    subtitle: str = ""


@dataclass(frozen=True)
class PlatformFormat:
    key: str
    label: str
    width: int
    height: int


PLATFORM_FORMATS: dict[str, PlatformFormat] = {
    "instagram_square": PlatformFormat("instagram_square", "Instagram / Facebook Feed (1:1)", 1080, 1080),
    # Instagram's actual portrait carousel/post shape (4:5) — referenced in this
    # app's own docs/prompts for several rounds as "Instagram's real carousel
    # slide shape (1080x1350)" but never actually registered here until round 20,
    # when picking a platform for a *whole* campaign (not just one manual render)
    # surfaced that every carousel produced so far had been generated at 1:1 or
    # 9:16 only, never the 4:5 shape most real Instagram carousels actually use.
    "instagram_portrait": PlatformFormat("instagram_portrait", "Instagram Portrait Carousel (4:5)", 1080, 1350),
    "instagram_story": PlatformFormat("instagram_story", "Instagram / Facebook Story (9:16)", 1080, 1920),
    "facebook_feed": PlatformFormat("facebook_feed", "Facebook Feed (1.91:1)", 1200, 630),
    # Build 2 (Part A/B, PlatformCreativeSpec): Pinterest's real Pin shape
    # (2:3 vertical) — the first render format this registry gains for a
    # platform that isn't Instagram/Facebook, now that `target_platforms` can
    # include Pinterest and `_render_additional_platform_variants` (services/
    # orchestrator.py) actually renders an independent variant for it.
    "pinterest_vertical": PlatformFormat("pinterest_vertical", "Pinterest Pin (2:3)", 1000, 1500),
}

DEFAULT_PLATFORM_FORMAT = "instagram_square"


@dataclass(frozen=True)
class TemplateContext:
    width: int
    height: int
    composited_image_data_uri: str
    eyebrow: str = ""
    headline: str = ""
    body: str = ""
    cta: str = ""
    logo_data_uri: str | None = None
    accent_color: str = "#c65d3b"
    text_color: str = "#ffffff"
    font_family: str = "'Helvetica Neue', Arial, sans-serif"
    # Round 17 fields for the richer `feature_showcase` template (see that
    # function's docstring) — all optional and unused by `premium_product_hero`,
    # so existing callers/tests that never set them are unaffected.
    badge_text: str = ""
    intro: str = ""
    features: list[Feature] = field(default_factory=list)
    callout_label: str = ""
    callout_value: str = ""
    bottom_features: list[str] = field(default_factory=list)
    trust_badges: list[str] = field(default_factory=list)
    # Round 18: the "consistent slide-number system such as 1/6, 2/6, 3/6" the
    # user's own uploaded design-profile doc calls for (HSC-PROD-001). Rendered
    # as real HTML/CSS — never baked into an AI-generated image — so it's exact
    # regardless of which template or generation path produced the slide.
    # `total_slides <= 1` renders nothing: a single-image post has no carousel
    # position to show.
    slide_number: int = 0
    total_slides: int = 0
    # Build 1 (Part H): deterministic disclaimer text (see pipeline.py::
    # SlideCreativeInput.disclaimer). Empty renders nothing — existing
    # templates/tests that never set this are unaffected.
    disclaimer: str = ""

    layout_variant: str = ""
    campaign_archetype: str = ""
    slide_role: str = ""

    direction_palette: list[str] = field(default_factory=list)
    secondary_font_family: str = ""
    typography_direction: str = ""
    headline_emphasis: str = ""
    cta_treatment: str = ""
    hero_treatment: str = ""
    visual_style: str = ""
    mood: str = ""
    negative_space: str = ""

    # Stage 3D: true only for the bounded masked AI-scene path.
    # Templates may use this to add deterministic local copy protection
    # because the generated scene behind the copy is not predictable.
    masked_scene_background: bool = False


def _esc(value: str) -> str:
    return html.escape(value, quote=True)


def _slide_marker_html(ctx: TemplateContext) -> str:
    if ctx.total_slides <= 1 or ctx.slide_number <= 0:
        return ""
    return f'<div class="slide-marker">{ctx.slide_number}/{ctx.total_slides}</div>'


def _slide_marker_css(ctx: TemplateContext) -> str:
    return f"""
  .slide-marker {{
    position: absolute;
    top: 4%; left: 4%;
    background: rgba(0,0,0,0.5);
    color: #ffffff;
    font-weight: 700;
    font-size: {max(round(ctx.width * 0.018), 12)}px;
    letter-spacing: 0.03em;
    border-radius: 999px;
    padding: {round(ctx.height * 0.01)}px {round(ctx.width * 0.022)}px;
    backdrop-filter: blur(2px);
  }}
"""


def _build_premium_product_hero(ctx: TemplateContext) -> str:
    """Full-bleed composited image, a bottom gradient scrim for text legibility, and
    eyebrow/headline/body/CTA stacked above it, with the brand logo in the top-right
    corner when supplied. Deliberately simple and readable at small sizes — the first
    template in the library, meant to work for any single hero product shot.

    When the caller passes no text at all (eyebrow/headline/body/CTA all empty —
    e.g. a full AI recreation baked its own text directly into the image, see
    `services/orchestrator.py::recreate_creative_image`), the scrim and text block
    are skipped entirely rather than rendering an empty dark gradient over an image
    that has nothing to caption. The logo still renders independently either way —
    it's never left to the AI regardless of whether text was baked in.
    """
    has_text = bool(ctx.eyebrow or ctx.headline or ctx.body or ctx.cta)
    logo_html = (
        f'<img class="logo" src="{ctx.logo_data_uri}" alt="brand logo" />'
        if ctx.logo_data_uri
        else ""
    )
    eyebrow_html = f'<div class="eyebrow">{_esc(ctx.eyebrow)}</div>' if ctx.eyebrow else ""
    body_html = f'<div class="body-copy">{_esc(ctx.body)}</div>' if ctx.body else ""
    cta_html = f'<div class="cta">{_esc(ctx.cta)}</div>' if ctx.cta else ""
    headline_html = f'<div class="headline">{_esc(ctx.headline)}</div>' if ctx.headline else ""
    disclaimer_html = f'<div class="disclaimer">{_esc(ctx.disclaimer)}</div>' if ctx.disclaimer else ""
    # A disclaimer with otherwise no other text (e.g. a full AI recreation baked
    # eyebrow/headline/body/cta into the image but disclaimer text is never baked
    # in — see brand_style.py's docstring) still needs the scrim + text-block to
    # render, or it would have nothing to sit on.
    text_block_html = (
        f"""<div class="scrim"></div>
    <div class="text-block">
      {eyebrow_html}
      {headline_html}
      {body_html}
      {cta_html}
      {disclaimer_html}
    </div>"""
        if (has_text or ctx.disclaimer)
        else ""
    )

    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8" />
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  html, body {{ width: {ctx.width}px; height: {ctx.height}px; overflow: hidden; }}
  .canvas {{
    position: relative;
    width: {ctx.width}px;
    height: {ctx.height}px;
    font-family: {ctx.font_family};
  }}
  .canvas img.background {{
    position: absolute;
    top: 0; left: 0;
    width: {ctx.width}px;
    height: {ctx.height}px;
    object-fit: cover;
  }}
  .scrim {{
    position: absolute;
    left: 0; right: 0; bottom: 0;
    height: 46%;
    background: linear-gradient(to bottom, rgba(0,0,0,0) 0%, rgba(0,0,0,0.72) 62%, rgba(0,0,0,0.82) 100%);
  }}
  .logo {{
    position: absolute;
    top: 4%; right: 5%;
    max-height: 9%;
    max-width: 28%;
    object-fit: contain;
    filter: drop-shadow(0 2px 6px rgba(0,0,0,0.35));
  }}
  .text-block {{
    position: absolute;
    left: 6%; right: 6%; bottom: 6%;
    color: {ctx.text_color};
  }}
  .eyebrow {{
    text-transform: uppercase;
    letter-spacing: 0.14em;
    font-size: {max(round(ctx.width * 0.022), 14)}px;
    font-weight: 600;
    color: {ctx.accent_color};
    margin-bottom: {round(ctx.height * 0.012)}px;
  }}
  .headline {{
    font-size: {max(round(ctx.width * 0.062), 24)}px;
    font-weight: 800;
    line-height: 1.08;
    margin-bottom: {round(ctx.height * 0.016)}px;
    text-shadow: 0 2px 10px rgba(0,0,0,0.35);
  }}
  .body-copy {{
    font-size: {max(round(ctx.width * 0.026), 15)}px;
    font-weight: 400;
    line-height: 1.35;
    max-width: 92%;
    margin-bottom: {round(ctx.height * 0.022)}px;
    opacity: 0.94;
  }}
  .cta {{
    display: inline-block;
    background: {ctx.accent_color};
    color: #ffffff;
    font-weight: 700;
    font-size: {max(round(ctx.width * 0.024), 14)}px;
    padding: {round(ctx.height * 0.016)}px {round(ctx.width * 0.05)}px;
    border-radius: 999px;
  }}
  .disclaimer {{
    font-size: {max(round(ctx.width * 0.013), 9)}px;
    line-height: 1.3;
    opacity: 0.72;
    margin-top: {round(ctx.height * 0.012)}px;
    max-width: 92%;
  }}
  {_slide_marker_css(ctx)}
</style>
</head>
<body>
  <div class="canvas">
    <img class="background" src="{ctx.composited_image_data_uri}" alt="" />
    {logo_html}
    {text_block_html}
    {_slide_marker_html(ctx)}
  </div>
</body>
</html>"""


def _normalize_hex_color(value: str) -> str | None:
    value = (value or "").strip()

    if not value.startswith("#"):
        return None

    if len(value) == 4:
        value = (
            "#"
            + value[1] * 2
            + value[2] * 2
            + value[3] * 2
        )

    if len(value) != 7:
        return None

    try:
        int(value[1:], 16)
    except ValueError:
        return None

    return value.upper()


def _hex_rgb(value: str) -> tuple[int, int, int]:
    normalized = (
        _normalize_hex_color(value)
        or "#777777"
    )

    return (
        int(normalized[1:3], 16),
        int(normalized[3:5], 16),
        int(normalized[5:7], 16),
    )


def _rgba(value: str, alpha: float) -> str:
    red, green, blue = _hex_rgb(value)

    return (
        f"rgba("
        f"{red},"
        f"{green},"
        f"{blue},"
        f"{alpha:.2f}"
        f")"
    )


def _resolve_commercial_style(
    ctx: TemplateContext,
) -> dict[str, object]:
    """Resolve deterministic commercial styling from real direction data.

    This changes presentation only. It never invents a product claim or
    changes which factual modules exist on the slide.
    """

    palette = [
        color
        for color in (
            _normalize_hex_color(value)
            for value
            in ctx.direction_palette
        )
        if color
    ]

    accent = (
        _normalize_hex_color(
            ctx.accent_color
        )
        or "#E0477B"
    )

    base = (
        palette[0]
        if palette
        else accent
    )

    secondary = (
        palette[1]
        if len(palette) > 1
        else base
    )

    layout = (
        ctx.layout_variant
        or "feature_commerce"
    )

    if layout == "technical_grid":
        family = "dark"

    elif layout == "sparse_hero":
        family = "cinematic"

    elif layout in {
        "hero_editorial",
        "discovery_story",
    }:
        family = "editorial"

    else:
        family = "light"

    if family == "dark":
        style = {
            "family": family,
            "canvas_bg": "#101620",
            "ambient": (
                "linear-gradient("
                "120deg,"
                f"{_rgba(base, 0.18)} 0%,"
                "rgba(7,10,16,0.28) 42%,"
                "rgba(7,10,16,0.04) 100%)"
            ),
            "panel_bg": (
                "rgba(11,16,25,0.79)"
            ),
            "panel_border": (
                _rgba(base, 0.30)
            ),
            "text": "#FFFFFF",
            "muted": (
                "rgba(255,255,255,0.74)"
            ),
            "module_bg": (
                "rgba(255,255,255,0.10)"
            ),
            "module_border": (
                _rgba(base, 0.30)
            ),
            "chip_bg": (
                "rgba(255,255,255,0.10)"
            ),
            "brand_bg": (
                "rgba(255,255,255,0.82)"
            ),
            "shadow": (
                "0 18px 48px "
                "rgba(0,0,0,0.24)"
            ),
        }

    elif family == "cinematic":
        style = {
            "family": family,
            "canvas_bg": "#171719",
            "ambient": (
                "linear-gradient("
                "to bottom,"
                "rgba(0,0,0,0) 38%,"
                f"{_rgba(base, 0.08)} 62%,"
                "rgba(5,5,7,0.28) 100%)"
            ),
            "panel_bg": (
                "rgba(10,10,12,0.60)"
            ),
            "panel_border": (
                "rgba(255,255,255,0.13)"
            ),
            "text": "#FFFFFF",
            "muted": (
                "rgba(255,255,255,0.78)"
            ),
            "module_bg": (
                "rgba(255,255,255,0.11)"
            ),
            "module_border": (
                "rgba(255,255,255,0.16)"
            ),
            "chip_bg": (
                "rgba(10,10,12,0.56)"
            ),
            "brand_bg": (
                "rgba(255,255,255,0.78)"
            ),
            "shadow": (
                "0 16px 44px "
                "rgba(0,0,0,0.20)"
            ),
        }

    elif family == "editorial":
        style = {
            "family": family,
            "canvas_bg": "#F5F1ED",
            "ambient": (
                "linear-gradient("
                "120deg,"
                f"{_rgba(base, 0.09)} 0%,"
                f"{_rgba(secondary, 0.04)} 46%,"
                "rgba(255,255,255,0) 100%)"
            ),
            "panel_bg": (
                "rgba(255,252,248,0.84)"
            ),
            "panel_border": (
                _rgba(base, 0.20)
            ),
            "text": "#1B1A19",
            "muted": (
                "rgba(27,26,25,0.70)"
            ),
            "module_bg": (
                "rgba(255,255,255,0.66)"
            ),
            "module_border": (
                _rgba(base, 0.22)
            ),
            "chip_bg": (
                "rgba(255,252,248,0.82)"
            ),
            "brand_bg": (
                "rgba(255,255,255,0.70)"
            ),
            "shadow": (
                "0 18px 48px "
                "rgba(74,58,46,0.11)"
            ),
        }

    else:
        style = {
            "family": family,
            "canvas_bg": "#F4F3F1",
            "ambient": (
                "linear-gradient("
                "115deg,"
                f"{_rgba(base, 0.10)} 0%,"
                f"{_rgba(secondary, 0.04)} 50%,"
                "rgba(255,255,255,0) 100%)"
            ),
            "panel_bg": (
                "rgba(255,255,255,0.84)"
            ),
            "panel_border": (
                _rgba(base, 0.22)
            ),
            "text": "#17181B",
            "muted": (
                "rgba(23,24,27,0.70)"
            ),
            "module_bg": (
                "rgba(255,255,255,0.72)"
            ),
            "module_border": (
                _rgba(base, 0.24)
            ),
            "chip_bg": (
                "rgba(255,255,255,0.82)"
            ),
            "brand_bg": (
                "rgba(255,255,255,0.70)"
            ),
            "shadow": (
                "0 16px 42px "
                "rgba(48,48,48,0.10)"
            ),
        }

    typography_hint = (
        ctx.typography_direction
        or ""
    ).lower()

    emphasis_hint = (
        ctx.headline_emphasis
        or ""
    ).lower()

    secondary_font = (
        ctx.secondary_font_family
        or ctx.font_family
    )

    if (
        layout
        in {
            "hero_editorial",
            "discovery_story",
        }
        or any(
            token
            in typography_hint
            for token
            in (
                "serif",
                "editorial",
                "refined",
            )
        )
    ):
        headline_font = (
            secondary_font
        )
    else:
        headline_font = (
            ctx.font_family
        )

    if layout == "technical_grid":
        headline_weight = 780
    elif layout == "discovery_story":
        headline_weight = 740
    elif layout == "hero_editorial":
        headline_weight = 780
    else:
        headline_weight = 840

    emphasis_multiplier = 1.0

    if any(
        token in emphasis_hint
        for token in (
            "dominant",
            "large",
            "bold",
            "strong",
        )
    ):
        emphasis_multiplier = 1.05

    elif any(
        token in emphasis_hint
        for token in (
            "restrained",
            "subtle",
            "quiet",
        )
    ):
        emphasis_multiplier = 0.95

    cta_hint = (
        ctx.cta_treatment
        or ""
    ).lower()

    outline_cta = any(
        token in cta_hint
        for token in (
            "outline",
            "subtle",
            "minimal",
            "text",
        )
    )

    if outline_cta:
        cta_fill = (
            "transparent"
        )
        cta_text = accent
        cta_border = (
            f"1.5px solid {accent}"
        )
    else:
        cta_fill = accent
        cta_text = "#FFFFFF"
        cta_border = (
            "1px solid transparent"
        )

    return {
        **style,
        "base": base,
        "secondary": secondary,
        "accent": accent,
        "headline_font": headline_font,
        "headline_weight": (
            headline_weight
        ),
        "emphasis_multiplier": (
            emphasis_multiplier
        ),
        "cta_fill": cta_fill,
        "cta_text": cta_text,
        "cta_border": cta_border,
    }


def _build_feature_showcase(ctx: TemplateContext) -> str:
    """Build 6R-C2C product-driven deterministic commercial composition."""

    valid_layouts = {
        "sparse_hero",
        "hero_editorial",
        "utility_demo",
        "technical_grid",
        "discovery_story",
        "feature_commerce",
    }

    layout = (
        ctx.layout_variant
        if ctx.layout_variant
        in valid_layouts
        else "feature_commerce"
    )

    commercial = (
        _resolve_commercial_style(
            ctx
        )
    )

    masked_scene_class = (
        " masked-scene-background"
        if ctx.masked_scene_background
        else ""
    )

    profiles = {
        "sparse_hero": {
            "text_left": 6,
            "text_top": 62,
            "text_width": 88,
            "headline_scale": 0.061,
            "columns": 1,
            "module_scale": 1.0,
        },
        "hero_editorial": {
            "text_left": 5,
            "text_top": 16,
            "text_width": 42,
            "headline_scale": 0.054,
            "columns": 1,
            "module_scale": 1.0,
        },
        "utility_demo": {
            "text_left": 5,
            "text_top": 14,
            "text_width": 43,
            "headline_scale": 0.048,
            "columns": 1,
            "module_scale": 1.08,
        },
        "technical_grid": {
            "text_left": 5,
            "text_top": 13,
            "text_width": 47,
            "headline_scale": 0.046,
            "columns": 2,
            "module_scale": 1.13,
        },
        "discovery_story": {
            "text_left": 6,
            "text_top": 57,
            "text_width": 88,
            "headline_scale": 0.052,
            "columns": 2,
            "module_scale": 1.0,
        },
        "feature_commerce": {
            "text_left": 5,
            "text_top": 14,
            "text_width": 44,
            "headline_scale": 0.046,
            "columns": 1,
            "module_scale": 1.05,
        },
    }

    profile = profiles[
        layout
    ]

    features = [
        feature
        for feature
        in ctx.features
        if feature.title
    ][:5]

    copy_volume = (
        len(ctx.eyebrow or "")
        + len(ctx.headline or "")
        + len(ctx.intro or "")
        + len(ctx.body or "")
        + sum(
            len(
                feature.title
                or ""
            )
            + len(
                feature.subtitle
                or ""
            )
            for feature
            in features
        )
    )

    if (
        len(features) >= 5
        or copy_volume > 430
    ):
        scale = 0.74

    elif (
        len(features) >= 3
        or copy_volume > 300
    ):
        scale = 0.84

    elif copy_volume > 210:
        scale = 0.92

    else:
        scale = 1.0

    headline_px = max(
        round(
            ctx.width
            * profile[
                "headline_scale"
            ]
            * scale
            * float(
                commercial[
                    "emphasis_multiplier"
                ]
            )
        ),
        24,
    )

    module_scale = float(
        profile[
            "module_scale"
        ]
    )

    logo_html = (
        f"""<div class="brand-signature">
      <img class="logo" src="{ctx.logo_data_uri}" alt="brand logo" />
    </div>"""
        if ctx.logo_data_uri
        else ""
    )

    badge_html = (
        f'<div class="badge">{_esc(ctx.badge_text)}</div>'
        if ctx.badge_text
        else ""
    )

    eyebrow_html = (
        f'<div class="eyebrow">{_esc(ctx.eyebrow)}</div>'
        if ctx.eyebrow
        else ""
    )

    headline_html = (
        f'<div class="headline">{_esc(ctx.headline)}</div>'
        if ctx.headline
        else ""
    )

    intro_html = (
        f'<div class="intro">{_esc(ctx.intro)}</div>'
        if ctx.intro
        else ""
    )

    body_html = (
        f'<div class="body-copy">{_esc(ctx.body)}</div>'
        if ctx.body
        else ""
    )

    features_html = ""

    if features:
        rows = "".join(
            f"""<div class="feature-card">
        <div class="feature-icon">{_esc(feature.icon) or "&#10022;"}</div>
        <div class="feature-copy">
          <div class="feature-title">{_esc(feature.title)}</div>
          {
              f'<div class="feature-subtitle">{_esc(feature.subtitle)}</div>'
              if feature.subtitle
              else ""
          }
        </div>
      </div>"""
            for feature
            in features
        )

        features_html = (
            f'<div class="feature-list">{rows}</div>'
        )

    callout_html = ""

    if (
        ctx.callout_label
        or ctx.callout_value
    ):
        label_html = (
            f'<div class="callout-label">{_esc(ctx.callout_label)}</div>'
            if ctx.callout_label
            else ""
        )

        value_html = (
            f'<div class="callout-value">{_esc(ctx.callout_value)}</div>'
            if ctx.callout_value
            else ""
        )

        callout_html = (
            '<div class="callout">'
            + label_html
            + value_html
            + "</div>"
        )

    text_block_html = ""

    if any(
        (
            eyebrow_html,
            headline_html,
            intro_html,
            body_html,
            features_html,
            callout_html,
        )
    ):
        text_block_html = f"""<div class="text-block">
      {eyebrow_html}
      {headline_html}
      {intro_html}
      {body_html}
      {features_html}
      {callout_html}
    </div>"""

    bottom_features = [
        value
        for value
        in ctx.bottom_features
        if value
    ][:4]

    strip_html = ""

    if bottom_features:
        chips = "".join(
            f"""<div class="support-chip">
        <span class="support-check">&#10003;</span>
        <span>{_esc(value)}</span>
      </div>"""
            for value
            in bottom_features
        )

        strip_html = (
            f'<div class="support-strip">{chips}</div>'
        )

    cta_html = ""

    if ctx.cta:
        cta_html = (
            f'<div class="cta-pill">{_esc(ctx.cta)}</div>'
        )

    trust_html = ""

    if ctx.trust_badges:
        trust_html = (
            '<div class="trust-badges">'
            + " &nbsp;&middot;&nbsp; ".join(
                _esc(value)
                for value
                in ctx.trust_badges
                if value
            )
            + "</div>"
        )

    footer_html = ""

    if (
        cta_html
        or trust_html
    ):
        footer_html = (
            '<div class="commercial-footer">'
            + cta_html
            + trust_html
            + "</div>"
        )

    disclaimer_html = (
        f'<div class="disclaimer">{_esc(ctx.disclaimer)}</div>'
        if ctx.disclaimer
        else ""
    )

    footer_h = (
        0.052
        if footer_html
        else 0.0
    )

    strip_h = (
        0.044
        if strip_html
        else 0.0
    )

    disclaimer_h = (
        0.028
        if disclaimer_html
        else 0.0
    )

    lower_reserved = (
        footer_h
        + strip_h
        + disclaimer_h
    )

    marker_clearance = (
        6
        if (
            ctx.total_slides > 1
            and ctx.slide_number > 0
            and profile[
                "text_top"
            ] < 30
        )
        else 0
    )

    text_top = (
        profile[
            "text_top"
        ]
        + marker_clearance
    )

    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8" />
<style>
  * {{
    margin: 0;
    padding: 0;
    box-sizing: border-box;
  }}

  html,
  body {{
    width: {ctx.width}px;
    height: {ctx.height}px;
    overflow: hidden;
  }}

  .canvas {{
    position: relative;
    width: {ctx.width}px;
    height: {ctx.height}px;
    overflow: hidden;
    font-family: {ctx.font_family};
    background: {commercial["canvas_bg"]};
  }}

  .canvas img.background {{
    position: absolute;
    inset: 0;
    width: {ctx.width}px;
    height: {ctx.height}px;
    object-fit: cover;
  }}

  .art-overlay {{
    position: absolute;
    inset: 0;
    z-index: 2;
    pointer-events: none;
    background: {commercial["ambient"]};
  }}

  .brand-signature {{
    position: absolute;
    z-index: 10;
    top: 3.7%;
    right: 4%;
    max-width: 22%;
    min-height: {max(round(ctx.height * 0.040), 32)}px;
    display: flex;
    align-items: center;
    justify-content: center;
    padding:
      {max(round(ctx.height * 0.006), 5)}px
      {max(round(ctx.width * 0.012), 8)}px;
    border-left:
      {max(round(ctx.width * 0.004), 3)}px
      solid {ctx.accent_color};
    border-radius:
      {max(round(ctx.width * 0.010), 8)}px;
    background: {commercial["brand_bg"]};
    box-shadow:
      0 5px 18px rgba(0,0,0,0.09);
    backdrop-filter: blur(8px);
  }}

  .logo {{
    display: block;
    max-height: {max(round(ctx.height * 0.038), 26)}px;
    max-width: 100%;
    object-fit: contain;
  }}

  .badge {{
    position: absolute;
    z-index: 9;
    top: 10.4%;
    right: 4%;
    max-width: 31%;
    color: #ffffff;
    background: {ctx.accent_color};
    font-size: {max(round(ctx.width * 0.0165), 10)}px;
    font-weight: 800;
    line-height: 1.1;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    padding:
      {max(round(ctx.height * 0.0075), 6)}px
      {max(round(ctx.width * 0.019), 10)}px;
    border-radius: 999px;
    box-shadow:
      0 7px 22px rgba(0,0,0,0.15);
  }}

  .text-block {{
    position: absolute;
    z-index: 6;
    left: {profile["text_left"]}%;
    top: {text_top}%;
    width: {profile["text_width"]}%;
    height: fit-content;
    max-height:
      calc(
        100%
        - {text_top}%
        - {lower_reserved * 100 + 4.0}%
      );
    color: {commercial["text"]};
    display: flex;
    flex-direction: column;
    justify-content: flex-start;
    gap: {max(round(ctx.height * 0.010 * scale), 6)}px;
    overflow: hidden;
    padding:
      {max(round(ctx.height * 0.012), 10)}px
      {max(round(ctx.width * 0.017), 12)}px;
    border-radius:
      {max(round(ctx.width * 0.018), 14)}px;
    border:
      1px solid {commercial["panel_border"]};
    background:
      {commercial["panel_bg"]};
    box-shadow:
      {commercial["shadow"]};
    backdrop-filter: blur(11px);
  }}

  .eyebrow {{
    color: {ctx.accent_color};
    font-size: {max(round(ctx.width * 0.017 * scale), 10)}px;
    font-weight: 800;
    line-height: 1.15;
    letter-spacing: 0.11em;
    text-transform: uppercase;
  }}

  .headline {{
    max-width: 100%;
    font-family:
      {commercial["headline_font"]};
    font-size: {headline_px}px;
    font-weight:
      {commercial["headline_weight"]};
    line-height: 1.03;
    letter-spacing: -0.022em;
  }}

  .intro {{
    max-width: 96%;
    color: {commercial["text"]};
    font-size: {max(round(ctx.width * 0.019 * scale), 12)}px;
    font-weight: 600;
    line-height: 1.34;
  }}

  .body-copy {{
    max-width: 96%;
    color: {commercial["muted"]};
    font-size: {max(round(ctx.width * 0.0165 * scale), 11)}px;
    line-height: 1.40;
  }}

  .feature-list {{
    display: grid;
    grid-template-columns:
      repeat(
        {profile["columns"]},
        minmax(0,1fr)
      );
    gap:
      {max(round(ctx.height * 0.0085 * scale), 5)}px
      {max(round(ctx.width * 0.009 * scale), 6)}px;
    margin-top:
      {max(round(ctx.height * 0.004), 3)}px;
  }}

  .feature-card {{
    min-width: 0;
    display: flex;
    align-items: flex-start;
    gap:
      {max(round(ctx.width * 0.011 * scale), 7)}px;
    padding:
      {max(round(ctx.height * 0.0095 * scale * module_scale), 8)}px
      {max(round(ctx.width * 0.013 * scale * module_scale), 9)}px;
    border-radius:
      {max(round(ctx.width * 0.013), 9)}px;
    background:
      {commercial["module_bg"]};
    border:
      1px solid
      {commercial["module_border"]};
  }}

  .feature-icon {{
    flex: none;
    width:
      {max(round(ctx.width * 0.039 * scale * module_scale), 24)}px;
    height:
      {max(round(ctx.width * 0.039 * scale * module_scale), 24)}px;
    border-radius: 50%;
    background:
      {commercial["chip_bg"]};
    border:
      1px solid
      {commercial["module_border"]};
    color:
      {commercial["text"]};
    display: flex;
    align-items: center;
    justify-content: center;
    font-size:
      {max(round(ctx.width * 0.018 * scale * module_scale), 11)}px;
    font-weight: 800;
  }}

  .feature-copy {{
    min-width: 0;
  }}

  .feature-title {{
    color: {commercial["text"]};
    font-size:
      {max(round(ctx.width * 0.0168 * scale * module_scale), 11)}px;
    font-weight: 800;
    line-height: 1.17;
  }}

  .feature-subtitle {{
    margin-top: 2px;
    color:
      {commercial["muted"]};
    font-size:
      {max(round(ctx.width * 0.0128 * scale * module_scale), 9)}px;
    line-height: 1.26;
  }}

  .callout {{
    align-self: flex-start;
    max-width: 100%;
    margin-top:
      {max(round(ctx.height * 0.004), 3)}px;
    padding:
      {max(round(ctx.height * 0.009 * scale), 7)}px
      {max(round(ctx.width * 0.018 * scale), 10)}px;
    border-radius:
      {max(round(ctx.width * 0.013), 9)}px;
    background:
      {commercial["module_bg"]};
    border-left:
      {max(round(ctx.width * 0.004), 3)}px
      solid {ctx.accent_color};
  }}

  .callout-label {{
    color: {ctx.accent_color};
    font-size:
      {max(round(ctx.width * 0.013 * scale), 9)}px;
    font-weight: 800;
    letter-spacing: 0.07em;
    text-transform: uppercase;
  }}

  .callout-value {{
    margin-top: 2px;
    color:
      {commercial["text"]};
    font-size:
      {max(round(ctx.width * 0.022 * scale), 14)}px;
    font-weight: 820;
    line-height: 1.10;
  }}

  .support-strip {{
    position: absolute;
    z-index: 7;
    left: 5%;
    bottom:
      {(footer_h + disclaimer_h) * 100 + 1.0}%;
    max-width: 88%;
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap:
      {max(round(ctx.width * 0.008), 6)}px;
  }}

  .support-chip {{
    display: inline-flex;
    align-items: center;
    gap:
      {max(round(ctx.width * 0.005), 4)}px;
    padding:
      {max(round(ctx.height * 0.006), 5)}px
      {max(round(ctx.width * 0.012), 8)}px;
    border-radius: 999px;
    background:
      {commercial["chip_bg"]};
    border:
      1px solid
      {commercial["module_border"]};
    color:
      {commercial["text"]};
    font-size:
      {max(round(ctx.width * 0.0125), 9)}px;
    font-weight: 650;
    backdrop-filter: blur(8px);
  }}

  .support-check {{
    color: {ctx.accent_color};
    font-weight: 900;
  }}

  .commercial-footer {{
    position: absolute;
    z-index: 8;
    left: 5%;
    bottom:
      {disclaimer_h * 100 + 1.0}%;
    max-width: 90%;
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap:
      {max(round(ctx.width * 0.012), 8)}px;
  }}

  .cta-pill {{
    display: inline-flex;
    align-items: center;
    justify-content: center;
    color:
      {commercial["cta_text"]};
    background:
      {commercial["cta_fill"]};
    border:
      {commercial["cta_border"]};
    font-size:
      {max(round(ctx.width * 0.0155), 10)}px;
    font-weight: 820;
    line-height: 1;
    padding:
      {max(round(ctx.height * 0.008), 7)}px
      {max(round(ctx.width * 0.021), 12)}px;
    border-radius: 999px;
    box-shadow:
      0 6px 18px rgba(0,0,0,0.10);
  }}

  .trust-badges {{
    color:
      {commercial["muted"]};
    font-size:
      {max(round(ctx.width * 0.0118), 9)}px;
    font-weight: 650;
    line-height: 1.25;
  }}

  .disclaimer {{
    position: absolute;
    z-index: 8;
    left: 6%;
    right: 6%;
    bottom: 0.5%;
    color:
      {commercial["muted"]};
    font-size:
      {max(round(ctx.width * 0.0102), 8)}px;
    line-height: 1.25;
    text-align: center;
  }}

  .layout-sparse_hero .text-block {{
    top: auto;
    bottom:
      {lower_reserved * 100 + 3.0}%;
    max-height: 35%;
    justify-content: flex-start;
  }}

  .layout-technical_grid .text-block {{
    border-color:
      {commercial["module_border"]};
  }}

  .layout-discovery_story .text-block {{
    top: auto;
    bottom:
      {lower_reserved * 100 + 3.0}%;
    max-height: 34%;
    justify-content: flex-start;
  }}

  /* BUILD6R_PREMIUM_EDITORIAL_SYSTEM_V1 */

  /*
   * Brand presentation:
   * retain the real logo but remove the floating glass badge.
   */
  .brand-signature {{
    min-height: 0;
    padding:
      0
      0
      0
      {max(round(ctx.width * 0.010), 7)}px;
    border-left:
      {max(round(ctx.width * 0.003), 2)}px
      solid {ctx.accent_color};
    border-radius: 0;
    background: transparent;
    box-shadow: none;
    backdrop-filter: none;
  }}

  .logo {{
    max-height:
      {max(round(ctx.height * 0.032), 24)}px;
  }}

  /*
   * Badges become editorial labels rather than pills.
   */
  .badge {{
    color: {ctx.accent_color};
    background: transparent;
    box-shadow: none;
    border-radius: 0;
    padding:
      0
      0
      {max(round(ctx.height * 0.004), 3)}px
      0;
    border-bottom:
      1px solid {ctx.accent_color};
  }}

  /*
   * The main copy is no longer a floating rounded UI card.
   */
  .text-block {{
    height: fit-content;
    padding: 0;
    border: 0;
    border-radius: 0;
    background: transparent;
    box-shadow: none;
    backdrop-filter: none;
    overflow: visible;
  }}

  .headline {{
    text-shadow: none;
  }}

  /*
   * Feature information becomes a clean editorial specification
   * system instead of nested rounded cards.
   */
  .feature-list {{
    margin-top:
      {max(round(ctx.height * 0.009), 7)}px;
    gap: 0;
  }}

  .feature-card {{
    border: 0;
    border-top:
      1px solid {commercial["module_border"]};
    border-radius: 0;
    background: transparent;
    padding:
      {max(round(ctx.height * 0.010 * scale), 8)}px
      0;
  }}

  .feature-icon {{
    background: transparent;
    border:
      1px solid {ctx.accent_color};
    color: {ctx.accent_color};
    box-shadow: none;
  }}

  .callout {{
    border-radius: 0;
    background: transparent;
    border-left:
      {max(round(ctx.width * 0.003), 2)}px
      solid {ctx.accent_color};
    padding:
      {max(round(ctx.height * 0.006), 5)}px
      0
      {max(round(ctx.height * 0.006), 5)}px
      {max(round(ctx.width * 0.014), 9)}px;
  }}

  .support-strip {{
    gap:
      {max(round(ctx.width * 0.015), 9)}px;
  }}

  .support-chip {{
    padding: 0;
    border: 0;
    border-radius: 0;
    background: transparent;
    backdrop-filter: none;
  }}

  /*
   * CTA becomes a restrained editorial action, not an app button.
   */
  .cta-pill {{
    color: {ctx.accent_color};
    background: transparent;
    border: 0;
    border-bottom:
      2px solid {ctx.accent_color};
    border-radius: 0;
    box-shadow: none;
    padding:
      0
      0
      {max(round(ctx.height * 0.004), 3)}px
      0;
  }}

  .cta-pill::after {{
    content: "  >";
  }}

  /*
   * Layout-specific copy territories. Product geometry is controlled
   * independently by the production product-zone policy.
   */
  .layout-hero_editorial .text-block {{
    left: 5%;
    top: 18%;
    width: 35%;
    max-height: 58%;
  }}

  .layout-utility_demo .text-block {{
    left: 5%;
    top: 16%;
    width: 36%;
    max-height: 62%;
  }}

  .layout-feature_commerce .text-block {{
    left: 5%;
    top: 15%;
    width: 37%;
    max-height: 64%;
  }}

  .layout-technical_grid .text-block {{
    left: 5%;
    top: 15%;
    width: 40%;
    max-height: 64%;
    padding-left:
      {max(round(ctx.width * 0.014), 10)}px;
    border-left:
      {max(round(ctx.width * 0.003), 2)}px
      solid {ctx.accent_color};
  }}

  /*
   * Sparse hero remains a cover rather than becoming another
   * side-by-side card template.
   */
  .layout-sparse_hero .text-block {{
    left: 6%;
    right: auto;
    width: 54%;
    top: auto;
    bottom:
      {lower_reserved * 100 + 5.0}%;
    max-height: 28%;
  }}

  /*
   * Discovery keeps a quieter narrative footer.
   */
  .layout-discovery_story .text-block {{
    left: 6%;
    right: 6%;
    width: auto;
    top: auto;
    bottom:
      {lower_reserved * 100 + 5.0}%;
    max-height: 25%;
  }}

  /* BUILD6R_ROLE_ART_DIRECTION_V2 */

  /*
   * V2 rule:
   * ambient art direction belongs to the slide role.
   * It must not indiscriminately tint the authentic product.
   */

  .layout-sparse_hero .art-overlay {{
    background: transparent;
  }}

  .layout-hero_editorial .art-overlay {{
    background:
      linear-gradient(
        90deg,
        rgba(249,245,235,0.94) 0%,
        rgba(249,245,235,0.78) 30%,
        rgba(249,245,235,0.28) 47%,
        rgba(249,245,235,0.00) 60%
      );
  }}

  .layout-feature_commerce .art-overlay {{
    background:
      linear-gradient(
        90deg,
        rgba(249,245,235,0.97) 0%,
        rgba(249,245,235,0.88) 35%,
        rgba(249,245,235,0.25) 52%,
        rgba(249,245,235,0.00) 64%
      );
  }}

  .layout-utility_demo .art-overlay {{
    background:
      linear-gradient(
        90deg,
        rgba(249,245,235,0.91) 0%,
        rgba(249,245,235,0.67) 30%,
        rgba(249,245,235,0.00) 54%
      );
  }}

  .layout-discovery_story .art-overlay {{
    background:
      linear-gradient(
        90deg,
        rgba(249,245,235,0.98) 0%,
        rgba(249,245,235,0.90) 28%,
        rgba(249,245,235,0.48) 42%,
        rgba(249,245,235,0.00) 58%
      );
  }}

  /*
   * Technical role:
   * a contained left technical rail, never a full-frame gray wash.
   * The authentic product remains visually untouched on the right.
   */
  .layout-technical_grid .art-overlay {{
    background:
      linear-gradient(
        90deg,
        rgba(31,31,28,0.94) 0%,
        rgba(31,31,28,0.94) 41.5%,
        rgba(31,31,28,0.20) 41.7%,
        rgba(31,31,28,0.00) 53%
      );
  }}


  /*
   * HERO EDITORIAL
   * Strong typographic magazine hierarchy.
   */
  .layout-hero_editorial .text-block {{
    left: 5%;
    top: 21%;
    width: 33%;
    max-height: 55%;
  }}

  .layout-hero_editorial .headline {{
    font-size:
      {max(round(ctx.width * 0.060), 34)}px;
    line-height: 0.98;
    letter-spacing: -0.035em;
  }}

  .layout-hero_editorial .body {{
    max-width: 90%;
  }}


  /*
   * FEATURE COMMERCE
   * More structured and transactional than editorial.
   */
  .layout-feature_commerce .text-block {{
    left: 5%;
    top: 15%;
    width: 35%;
    max-height: 65%;
    padding-top:
      {max(round(ctx.height * 0.012), 10)}px;
    border-top:
      {max(round(ctx.height * 0.002), 2)}px
      solid {ctx.accent_color};
  }}

  .layout-feature_commerce .feature-card {{
    border-top:
      1px solid {commercial["module_border"]};
  }}

  .layout-feature_commerce .cta-pill {{
    display: inline-flex;
    align-self: flex-start;
    padding:
      {max(round(ctx.height * 0.008), 7)}px
      {max(round(ctx.width * 0.016), 11)}px;
    border: 0;
    border-radius: 0;
    background: {ctx.accent_color};
    color: #ffffff;
    box-shadow: none;
  }}

  .layout-feature_commerce .cta-pill::after {{
    content: "  >";
  }}


  /*
   * UTILITY DEMO
   * A visible instructional rail differentiates it from commerce
   * without inventing product facts.
   */
  .layout-utility_demo .text-block {{
    left: 7%;
    top: 18%;
    width: 31%;
    max-height: 58%;
    padding-left:
      {max(round(ctx.width * 0.018), 13)}px;
    border-left:
      {max(round(ctx.width * 0.003), 2)}px
      solid {ctx.accent_color};
  }}

  .layout-utility_demo .headline {{
    font-size:
      {max(round(ctx.width * 0.050), 29)}px;
    line-height: 1.00;
  }}

  .layout-utility_demo .feature-card {{
    padding-left: 0;
    padding-right: 0;
  }}


  /*
   * DISCOVERY STORY
   * Narrative column on the left; authentic product occupies the right.
   * This removes the detached-footer composition.
   */
  .layout-discovery_story .text-block {{
    left: 6%;
    right: auto;
    top: 23%;
    bottom: auto;
    width: 30%;
    max-height: 48%;
  }}

  .layout-discovery_story .headline {{
    font-size:
      {max(round(ctx.width * 0.053), 31)}px;
    line-height: 1.00;
  }}

  .layout-discovery_story .body {{
    max-width: 92%;
  }}


  /*
   * SPARSE HERO
   * No full-width dark banner.
   * A local edge-fade supports text while keeping the cover open.
   */
  .layout-sparse_hero .text-block {{
    left: 5%;
    right: auto;
    top: auto;
    bottom:
      {lower_reserved * 100 + 4.5}%;
    width: 44%;
    max-height: 24%;
    padding:
      {max(round(ctx.height * 0.012), 9)}px
      {max(round(ctx.width * 0.034), 22)}px
      {max(round(ctx.height * 0.014), 10)}px
      {max(round(ctx.width * 0.014), 10)}px;
    background:
      linear-gradient(
        90deg,
        rgba(32,29,23,0.82) 0%,
        rgba(32,29,23,0.62) 64%,
        rgba(32,29,23,0.00) 100%
      );
    border: 0;
    border-radius: 0;
    box-shadow: none;
  }}

  .layout-sparse_hero .headline {{
    font-size:
      {max(round(ctx.width * 0.064), 36)}px;
    line-height: 0.95;
  }}


  /*
   * TECHNICAL GRID
   * Copy lives only inside the left technical rail.
   * The package itself is not darkened.
   */
  .layout-technical_grid .text-block {{
    left: 5%;
    top: 16%;
    width: 31%;
    max-height: 63%;
    padding-left:
      {max(round(ctx.width * 0.014), 10)}px;
    border-left:
      {max(round(ctx.width * 0.003), 2)}px
      solid {ctx.accent_color};
    color: #ffffff;
  }}

  .layout-technical_grid .headline,
  .layout-technical_grid .body,
  .layout-technical_grid .intro {{
    color: #ffffff;
  }}

  .layout-technical_grid .feature-card {{
    border-top:
      1px solid rgba(255,255,255,0.24);
  }}

  .layout-technical_grid .feature-title,
  .layout-technical_grid .feature-copy {{
    color: #ffffff;
  }}

  /* BUILD6R_FINAL_OFFLINE_VISUAL_POLISH_V21 */

  /*
   * SPARSE HERO
   *
   * Remove the last remaining dark caption-panel treatment.
   * Copy becomes part of the composition itself:
   * clean typography, narrow accent rail, no card, no gradient box.
   */
  .layout-sparse_hero .text-block {{
    left: 6%;
    right: auto;
    top: auto;
    bottom:
      {lower_reserved * 100 + 6.0}%;
    width: 31%;
    max-height: 25%;

    padding:
      0
      0
      0
      {max(round(ctx.width * 0.014), 10)}px;

    background: transparent;
    border: 0;
    border-left:
      {max(round(ctx.width * 0.003), 2)}px
      solid {ctx.accent_color};
    border-radius: 0;
    box-shadow: none;
    backdrop-filter: none;
  }}

  .layout-sparse_hero .eyebrow {{
    color: {ctx.accent_color};
  }}

  .layout-sparse_hero .headline {{
    color: {ctx.text_color};
    font-size:
      {max(round(ctx.width * 0.056), 34)}px;
    line-height: 0.96;
    letter-spacing: -0.035em;
    text-shadow: none;
  }}

  .layout-sparse_hero .intro,
  .layout-sparse_hero .body {{
    color: {ctx.text_color};
    opacity: 0.76;
    text-shadow: none;
  }}


  /*
   * FEATURE COMMERCE
   *
   * The CTA currently lives in the separate absolute commercial-footer.
   * Move that footer into the same visual column as the commerce message
   * instead of leaving a tiny action stranded at the bottom-left.
   */
  .layout-feature_commerce .commercial-footer {{
    left: 5%;
    right: auto;

    top: 51%;
    bottom: auto;

    width: 35%;
    max-width: 35%;

    display: flex;
    flex-direction: column;
    align-items: flex-start;

    gap:
      {max(round(ctx.height * 0.010), 8)}px;

    padding-top:
      {max(round(ctx.height * 0.012), 10)}px;

    border-top:
      1px solid {ctx.accent_color};
  }}

  .layout-feature_commerce .cta-pill {{
    display: inline-flex;
    align-items: center;
    justify-content: center;

    min-height:
      {max(round(ctx.height * 0.038), 34)}px;

    padding:
      {max(round(ctx.height * 0.010), 9)}px
      {max(round(ctx.width * 0.022), 15)}px;

    color: #ffffff;
    background: {ctx.accent_color};

    border: 0;
    border-radius: 0;
    box-shadow: none;

    font-size:
      {max(round(ctx.width * 0.018), 13)}px;

    font-weight: 820;
    line-height: 1;
    letter-spacing: 0.01em;
  }}

  .layout-feature_commerce .cta-pill::after {{
    content: "  >";
  }}

  .layout-feature_commerce .trust-badges {{
    max-width: 100%;
    color: {ctx.text_color};
    opacity: 0.72;
    text-align: left;
  }}


  /*
   * BUILD6R_MASKED_SCENE_TEXT_PROTECTION_V1
   *
   * AI-edited scenes are visually dynamic. For those scenes only, keep
   * editorial typography legible with a soft local gradient under the copy.
   * This is intentionally edgeless: no rounded UI card, no hard rectangle,
   * no global image tint and no product recoloring.
   */
  .canvas.masked-scene-background .text-block {{
    color: {commercial["text"]};
    background:
      linear-gradient(
        90deg,
        {commercial["panel_bg"]} 0%,
        {commercial["panel_bg"]} 72%,
        rgba(0,0,0,0) 100%
      );
    border: 0;
    border-radius: 0;
    box-shadow: none;
    backdrop-filter: blur(6px);
  }}

  .canvas.masked-scene-background .headline,
  .canvas.masked-scene-background .intro,
  .canvas.masked-scene-background .body,
  .canvas.masked-scene-background .trust-badges {{
    color: {commercial["text"]};
  }}

  {_slide_marker_css(ctx)}
</style>
</head>

<body>
  <div
    class="canvas layout-{layout} commercial-{commercial["family"]}{masked_scene_class}"
    data-layout="{layout}"
    data-commercial-style="{commercial["family"]}"
    data-archetype="{_esc(ctx.campaign_archetype)}"
    data-slide-role="{_esc(ctx.slide_role)}"
  >
    <img
      class="background"
      src="{ctx.composited_image_data_uri}"
      alt=""
    />

    <div class="art-overlay"></div>

    {logo_html}
    {badge_html}
    {text_block_html}
    {strip_html}
    {footer_html}
    {disclaimer_html}
    {_slide_marker_html(ctx)}
  </div>
</body>
</html>"""





@dataclass(frozen=True)
class CreativeTemplate:
    id: str
    name: str
    description: str
    # (left, top, width, height, anchor) as fractions of the canvas — resolved to
    # pixel ProductZone via `product_zone_for` once a platform format is chosen.
    product_zone_fraction: tuple[float, float, float, float, str]
    build_html: Callable[[TemplateContext], str]


TEMPLATES: dict[str, CreativeTemplate] = {
    "premium_product_hero": CreativeTemplate(
        id="premium_product_hero",
        name="Premium Product Hero",
        description=(
            "A single hero product shot filling most of the frame, with a bottom "
            "gradient scrim carrying eyebrow/headline/body/CTA text and the brand "
            "logo top-right. Works for one strong product photo per post."
        ),
        product_zone_fraction=(0.08, 0.06, 0.84, 0.62, "top"),
        build_html=_build_premium_product_hero,
    ),
    "feature_showcase": CreativeTemplate(
        id="feature_showcase",
        name="Feature Showcase",
        description=(
            "Eyebrow + big headline + intro over a left-side scrim, a top-right badge "
            "ribbon, a vertical icon/title/subtitle feature list, an ingredients/results "
            "callout box, a bottom icon-feature strip, and a bottom CTA bar with trust "
            "badges — modeled on the user's own reference ads (round 17). The default "
            "template as of round 17."
        ),
        product_zone_fraction=(0.34, 0.0, 0.66, 1.0, "center"),
        build_html=_build_feature_showcase,
    ),
}


def get_template(template_id: str) -> CreativeTemplate:
    try:
        return TEMPLATES[template_id]
    except KeyError as exc:
        available = ", ".join(sorted(TEMPLATES))
        raise ValueError(f"Unknown creative template {template_id!r}. Available: {available}") from exc


def get_platform_format(platform_key: str) -> PlatformFormat:
    try:
        return PLATFORM_FORMATS[platform_key]
    except KeyError as exc:
        available = ", ".join(sorted(PLATFORM_FORMATS))
        raise ValueError(f"Unknown platform format {platform_key!r}. Available: {available}") from exc


def product_zone_for(template: CreativeTemplate, fmt: PlatformFormat) -> ProductZone:
    left, top, width, height, anchor = template.product_zone_fraction
    return ProductZone(
        left=round(left * fmt.width),
        top=round(top * fmt.height),
        width=round(width * fmt.width),
        height=round(height * fmt.height),
        anchor=anchor,
    )
