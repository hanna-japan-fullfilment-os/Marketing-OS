"""Brand Style Resolver (Build 1, Part G) — the single place that turns a Brand's
free-form `colors`/`typography` JSON fields, its `disclaimers` list, and its
uploaded visual-reference assets into the concrete values the creative pipeline
renders with.

This closes a real, confirmed gap: `SlideCreativeInput`/`TemplateContext`'s
`accent_color`/`text_color`/`font_family` were always the same hardcoded
defaults at both real call sites (`services/orchestrator.py::run_visuals_stage`
and `api/campaigns.py::render_campaign_slide`) — `brand.colors` was only ever
read for the deterministic gradient *background* (see `resolve_brand_colors` in
orchestrator.py, used by `compositor.make_background`), never for on-slide
text/badge/CTA color, and `brand.typography` was never read by anything at all
before this module.

`colors`/`typography` are free-form dicts, not a fixed schema — the brand-detail
UI (frontend/src/pages/BrandDetail.tsx) lets an owner type any key name for a
color swatch (its own placeholder example is literally "primary", but nothing
enforces that). So this resolver can't just do `brand.colors["accent"]`.
Instead it looks for a small set of common key spellings (case-insensitive),
then falls back to positional order among whatever colors exist, then finally
to the same hardcoded values the pipeline always used — so a brand that already
has colors entered (under any reasonable key name) starts getting real brand
colors on its rendered text/badges/CTA today, and a brand with nothing entered
yet behaves exactly as before this module existed. Same pattern for
`typography`, which today has no editing UI at all (round-20 audit confirmed
it's simply never read) — this resolver is what makes filling it in via the
API actually do something, with graceful, deterministic fallback otherwise.

Every fallback here is explicit and named (Part G's "deterministic, explicit
fallbacks" requirement) — never a silent empty string that would make text
invisible or unstyled.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy.orm import Session

from ...models import Brand, BrandAsset

# Same values `SlideCreativeInput`/`TemplateContext` have always hardcoded —
# kept here as the one named source of truth for "brand has nothing configured"
# rather than re-declaring them independently in pipeline.py/templates.py.
DEFAULT_PRIMARY_COLOR = "#c65d3b"
DEFAULT_ACCENT_COLOR = "#c65d3b"
DEFAULT_SECONDARY_COLOR = "#2c2622"
DEFAULT_TEXT_COLOR = "#ffffff"
DEFAULT_FONT_FAMILY = "'Helvetica Neue', Arial, sans-serif"

_ACCENT_KEYS = ("accent", "accent_color", "primary_accent", "highlight", "cta")
_PRIMARY_KEYS = ("primary", "primary_color", "brand", "brand_color", "main")
_SECONDARY_KEYS = ("secondary", "secondary_color", "alt", "alternate")
_TEXT_KEYS = ("text", "text_color", "on_dark", "foreground", "copy")

_PRIMARY_FONT_KEYS = ("primary_font", "heading_font", "display_font", "font", "font_family")
_SECONDARY_FONT_KEYS = ("secondary_font", "body_font", "text_font")


@dataclass(frozen=True)
class ResolvedBrandStyle:
    """The one canonical structure Part G asks for. Every field is always
    populated (never `None`) — colors/fonts fall back to the deterministic
    defaults above, `palette`/`visual_reference_paths` fall back to an empty
    list, `logo_path` is the only field that can genuinely be absent (a brand
    with no uploaded logo really has none to render).
    """

    primary_color: str
    accent_color: str
    secondary_color: str
    text_color: str
    # Informational, not itself a color: "brand_colors" when at least one real
    # brand color was found (so the deterministic gradient background in
    # `compositor.make_background` is using real brand data), "default" when it
    # fell back to the app's own neutral defaults.
    background_preference: str
    primary_font: str
    secondary_font: str
    palette: list[str] = field(default_factory=list)
    logo_path: Path | None = None
    visual_reference_paths: list[str] = field(default_factory=list)
    disclaimer_text: str = ""


def _lower_str_map(values: dict) -> dict[str, str]:
    return {str(k).strip().lower(): v for k, v in values.items() if isinstance(v, str) and v.strip()}


def _find(mapping: dict[str, str], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        if key in mapping:
            return mapping[key]
    return None


def resolve_brand_style(db: Session, brand: Brand, *, logo_path: Path | None = None) -> ResolvedBrandStyle:
    """Assembles the full structure for one brand. `logo_path` is accepted
    rather than recomputed here because `services/orchestrator.py::
    resolve_brand_logo_path` already does that lookup (a query over
    `BrandAsset` for `kind="logo"`) and both real call sites already call it —
    this just folds the result into one structure alongside everything else
    instead of duplicating that query.
    """
    colors = _lower_str_map(brand.colors if isinstance(brand.colors, dict) else {})
    # Preserves the dict's own iteration order (Python 3.7+ dicts are
    # insertion-ordered) so "positional order" fallback below means "the order
    # the brand owner entered them in the UI", not an arbitrary re-sort.
    palette = list(colors.values())

    accent = _find(colors, _ACCENT_KEYS) or _find(colors, _PRIMARY_KEYS)
    primary = _find(colors, _PRIMARY_KEYS) or accent
    secondary = _find(colors, _SECONDARY_KEYS)
    text = _find(colors, _TEXT_KEYS)

    # No recognized key name matched but the brand does have colors entered —
    # use them by position rather than ignoring real brand data because of a
    # naming mismatch.
    if accent is None and palette:
        accent = palette[0]
    if primary is None and palette:
        primary = palette[0]
    if secondary is None and len(palette) > 1:
        secondary = palette[1]

    typography = _lower_str_map(brand.typography if isinstance(brand.typography, dict) else {})
    primary_font = _find(typography, _PRIMARY_FONT_KEYS)
    secondary_font = _find(typography, _SECONDARY_FONT_KEYS)

    visual_reference_paths = [
        a.file_path
        for a in db.query(BrandAsset)
        .filter(BrandAsset.brand_id == brand.id, BrandAsset.kind == "visual_reference")
        .all()
    ]

    disclaimer_text = " · ".join(
        d.strip() for d in (brand.disclaimers or []) if isinstance(d, str) and d.strip()
    )

    return ResolvedBrandStyle(
        primary_color=primary or DEFAULT_PRIMARY_COLOR,
        accent_color=accent or DEFAULT_ACCENT_COLOR,
        secondary_color=secondary or DEFAULT_SECONDARY_COLOR,
        text_color=text or DEFAULT_TEXT_COLOR,
        background_preference="brand_colors" if palette else "default",
        primary_font=primary_font or DEFAULT_FONT_FAMILY,
        secondary_font=secondary_font or primary_font or DEFAULT_FONT_FAMILY,
        palette=palette,
        logo_path=logo_path,
        visual_reference_paths=visual_reference_paths,
        disclaimer_text=disclaimer_text,
    )
