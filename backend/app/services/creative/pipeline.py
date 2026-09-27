"""Creative pipeline orchestration entrypoint (campaign-pipeline.md hybrid pipeline,
steps 3-8: background isolation → background → composite → template → render → QA).

Deliberately DB-agnostic and callable with no AI/network involved: every input is a
plain value the caller already resolved, so this module is independently testable
today (see tests/test_creative.py) even though the full Autopilot orchestrator that
will call it end-to-end doesn't exist yet. That orchestrator (or, until it exists,
the campaign-detail render endpoint) owns pulling brand/campaign/slide rows from the
database and persisting `campaign_slides.rendered_asset_path` /
`campaign_outputs` from the `SlideRenderResult` this returns.

Two AI-touched steps in the full design are documented hooks (plain values the
caller already resolved) rather than something this module calls itself, keeping
it runnable with zero API key for development, testing, and any campaign that
just wants the deterministic defaults:
- an AI-generated scene background via `ImageProvider.generate(...)`
  (`generated_background`)
- a vision-model per-photo product zone via `AIProvider.detect_product_zone(...)`
  (`product_zone_detection`, see `services/orchestrator.py::detect_product_zone`)
"""
from __future__ import annotations

import base64
import io
from dataclasses import dataclass, replace
from pathlib import Path

from PIL import Image

from ...schemas.ai import ProductZoneDetection
from .background import BackgroundIsolator, get_isolator
from .compositor import (
    build_product_overlay,
    build_product_protection_mask,
    composite_product,
    make_background,
)
from .qa import CreativeQAResult, run_creative_qa
from .renderer import PlaywrightRenderer
from .templates import Feature, TemplateContext, get_platform_format, get_template, product_zone_for


def _image_to_data_uri(image: Image.Image) -> str:
    buf = io.BytesIO()
    image.convert("RGB").save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{b64}"


def _file_to_data_uri(path: Path) -> str:
    data = path.read_bytes()
    b64 = base64.b64encode(data).decode("ascii")
    ext = path.suffix.lstrip(".").lower() or "png"
    mime = "image/png" if ext == "png" else f"image/{ext}"
    return f"data:{mime};base64,{b64}"


@dataclass
class SlideCreativeInput:
    """Everything the pipeline needs for one slide, already resolved by the caller.
    Kept as plain paths/strings (not ORM rows) so this module never needs a database
    session to be tested or reused.
    """

    source_image_path: Path  # real path under SOURCE_ASSET_ROOT — opened read-only, once
    template_id: str
    platform_key: str
    eyebrow: str = ""
    headline: str = ""
    body: str = ""
    cta: str = ""
    brand_colors: list[str] | None = None  # hex strings, e.g. from brand.colors
    accent_color: str = "#c65d3b"
    text_color: str = "#ffffff"
    font_family: str = "'Helvetica Neue', Arial, sans-serif"
    logo_path: Path | None = None  # a brand_assets kind=logo path — opened read-only, once
    isolate_background: bool = False  # opt-in; silently falls back if rembg isn't installed
    generated_background: Image.Image | None = None  # hook for a future AI-generated scene
    product_zone_detection: ProductZoneDetection | None = None  # opt-in per-photo AI zone (see orchestrator.detect_product_zone)
    # Opt-in full recreation (see orchestrator.recreate_creative_image): the *entire*
    # image already reimagined by an AI edit call from the real source photo — the
    # product, background, lighting and composition all restyled together for the
    # campaign, not just a new backdrop behind the untouched product cutout. When
    # set, this replaces isolation/background/compositing entirely below. As of
    # round 16, the caller decides whether the marketing text is baked into this
    # image (by passing headline/body/cta/eyebrow into recreate_creative_image and
    # leaving eyebrow/headline/body/cta on *this* dataclass empty) or drawn
    # separately as real HTML/CSS on top (by leaving text out of the recreation
    # call and populating eyebrow/headline/body/cta here instead) — the two are
    # mutually exclusive per slide so text never renders twice; see
    # `services/orchestrator.py::run_visuals_stage` for how it picks. The brand
    # logo is never left to the AI either way — it always renders separately via
    # `logo_path` below, per the brief's "no AI-generated logos" rule.
    recreated_image: Image.Image | None = None
    # Round 17 fields for the `feature_showcase` template — passed straight
    # through to TemplateContext (see templates.py::_build_feature_showcase).
    # Unused by other templates, so left empty is always safe.
    badge_text: str = ""
    intro: str = ""
    features: list[Feature] = None  # type: ignore[assignment]  # see __post_init__
    callout_label: str = ""
    callout_value: str = ""
    bottom_features: list[str] = None  # type: ignore[assignment]  # see __post_init__
    trust_badges: list[str] = None  # type: ignore[assignment]  # see __post_init__
    # Round 18: "N/total" carousel-position marker (see templates.py::
    # _slide_marker_html) — real HTML/CSS on every template, regardless of
    # whether the slide's image came from the deterministic pipeline or a full
    # AI recreation. `total_slides <= 1` renders nothing.
    slide_number: int = 0
    total_slides: int = 0
    # Build 1 (Part H): deterministic disclaimer text — e.g. "Results may vary."
    # or a regulatory line — rendered as real HTML/CSS, never baked into an
    # AI-generated image. Sourced from `Brand.disclaimers` via
    # `services/creative/brand_style.py::resolve_brand_style`; empty means no
    # disclaimer line renders at all, same "skip empty sections" rule as every
    # other optional field here.
    disclaimer: str = ""

    campaign_archetype: str = ""
    slide_role: str = ""
    layout_variant: str = ""

    direction_palette: list[str] | None = None
    secondary_font_family: str = ""
    typography_direction: str = ""
    headline_emphasis: str = ""
    cta_treatment: str = ""
    hero_treatment: str = ""
    visual_style: str = ""
    mood: str = ""
    negative_space: str = ""

    # True only when generated_background came from the bounded masked
    # integrated-scene editor. In that mode the edited scene may already
    # contain natural contact lighting/shadow around the protected product,
    # so render_slide performs only the final exact product overlay.
    masked_scene_background: bool = False

    def __post_init__(self) -> None:
        # dataclass fields can't default to a mutable list directly; normalize
        # the Nones from the three fields above into real empty lists here so
        # callers never need to remember to pass `[]` explicitly.
        if self.features is None:
            self.features = []
        if self.bottom_features is None:
            self.bottom_features = []
        if self.trust_badges is None:
            self.trust_badges = []


@dataclass
class SlideRenderResult:
    output_path: Path
    width: int
    height: int
    qa: CreativeQAResult
    background_isolator_used: str
    product_zone_detected: bool = False


def _resize_cover(image: Image.Image, width: int, height: int) -> Image.Image:
    """Fits `image` into an exact `width`x`height` box by scaling to COVER the box
    (never stretching) and center-cropping the overflow, instead of a plain
    `Image.resize` to the exact dimensions.

    Why this matters: the AI image-generation API only ever returns one of three
    fixed aspect ratios (1:1, 2:3, or 3:2 — see `_nearest_ai_image_size` in
    `services/orchestrator.py`), and none of those exactly match most real
    platform slide shapes (Instagram's 4:5 portrait carousel is 1080x1350, a
    story is 9:16). A plain `resize` to the target dimensions was therefore
    non-uniformly stretching every AI-generated image whose aspect ratio didn't
    already match the target — squeezing product photos, warping bottle shapes,
    distorting labels and reflections, on every single slide in a 4:5 or
    story-format carousel, independent of prompt quality. `resize` is still
    correct (and cheap) for the rare case the sizes already match exactly, since
    a cover-crop of an already-matching image is a no-op scale with zero crop.
    """
    if image.size == (width, height):
        return image
    src_w, src_h = image.size
    target_ratio = width / height
    src_ratio = src_w / src_h
    if src_ratio > target_ratio:
        # Source is relatively wider than the target — scale to match height,
        # then crop the excess width off both sides evenly.
        scale = height / src_h
    else:
        # Source is relatively taller than the target — scale to match width,
        # then crop the excess height off top/bottom evenly.
        scale = width / src_w
    scaled = image.resize((max(1, round(src_w * scale)), max(1, round(src_h * scale))), Image.LANCZOS)
    scaled_w, scaled_h = scaled.size
    left = max(0, (scaled_w - width) // 2)
    top = max(0, (scaled_h - height) // 2)
    return scaled.crop((left, top, left + width, top + height))


def _crop_to_fraction_box(image: Image.Image, detection: ProductZoneDetection) -> Image.Image:
    """Crops `image` (the isolated product, still at the full source-photo canvas
    size) down to the tight bounding box a vision model identified around the
    actual product — see `ProductZoneDetection`. Fractions are clamped to the
    image's real pixel bounds so a slightly out-of-range model response can never
    crop to an empty image or read outside it.
    """
    w, h = image.size
    left = max(0, min(w - 1, round(detection.crop_left * w)))
    top = max(0, min(h - 1, round(detection.crop_top * h)))
    right = max(left + 1, min(w, round((detection.crop_left + detection.crop_width) * w)))
    bottom = max(top + 1, min(h, round((detection.crop_top + detection.crop_height) * h)))
    return image.crop((left, top, right, bottom))


ADAPTIVE_LAYOUT_VARIANTS = {
    "sparse_hero",
    "hero_editorial",
    "utility_demo",
    "technical_grid",
    "discovery_story",
    "feature_commerce",
}


def resolve_layout_variant(
    creative_input: SlideCreativeInput,
) -> str:
    """Choose a deterministic composition from product/story context.

    This router does not infer product facts. It only uses the already
    grounded campaign archetype, slide role and modules that actually
    exist on the slide.
    """

    explicit = (
        creative_input.layout_variant
        or ""
    ).strip().lower()

    if (
        explicit
        in ADAPTIVE_LAYOUT_VARIANTS
    ):
        return explicit

    archetype = (
        creative_input.campaign_archetype
        or ""
    ).strip().lower()

    role = (
        creative_input.slide_role
        or ""
    ).strip().lower()

    features = [
        feature
        for feature
        in (
            creative_input.features
            or []
        )
        if getattr(
            feature,
            "title",
            "",
        )
    ]

    feature_count = len(
        features
    )

    has_callout = bool(
        creative_input.callout_label
        or creative_input.callout_value
    )

    has_modules = bool(
        feature_count
        or creative_input.badge_text
        or has_callout
        or creative_input.bottom_features
        or creative_input.trust_badges
    )

    copy_volume = sum(
        len(value or "")
        for value
        in (
            creative_input.eyebrow,
            creative_input.headline,
            creative_input.intro,
            creative_input.body,
            creative_input.cta,
        )
    )

    technical_roles = (
        "technical",
        "spec",
        "proof",
        "mechanism",
        "how",
        "performance",
    )

    hero_roles = (
        "hero",
        "cover",
        "opening",
        "intro",
        "hook",
    )

    demo_roles = (
        "demo",
        "feature",
        "use",
        "benefit",
        "routine",
    )

    if any(
        token in role
        for token
        in technical_roles
    ):
        return "technical_grid"

    if (
        any(
            token in role
            for token
            in hero_roles
        )
        and feature_count <= 2
        and not has_callout
    ):
        return "hero_editorial"

    if archetype in {
        "technical_performance",
        "how_it_works",
    }:
        return "technical_grid"

    if (
        archetype
        in {
            "lifestyle_utility",
            "feature_demo",
            "routine_integration",
            "problem_solution",
        }
        or any(
            token in role
            for token
            in demo_roles
        )
    ):
        return "utility_demo"

    if archetype in {
        "premium_discovery",
        "origin_story",
        "sensory_experience",
    }:
        if (
            feature_count <= 2
            and copy_volume <= 300
        ):
            return "discovery_story"

        return "feature_commerce"

    if archetype == "variant_choice":
        return "feature_commerce"

    if (
        not has_modules
        and copy_volume <= 220
    ):
        return "sparse_hero"

    if (
        feature_count >= 3
        or has_modules
        or copy_volume > 300
    ):
        return "feature_commerce"

    return "hero_editorial"


# BUILD6R_PREMIUM_PRODUCT_ZONE_POLICY_V1
# BUILD6R_PREMIUM_PRODUCT_ZONE_POLICY_V2
_ADAPTIVE_PRODUCT_ZONES = {
    "sparse_hero": (
        0.12,
        0.03,
        0.76,
        0.72,
        "center",
    ),

    "hero_editorial": (
        0.44,
        0.08,
        0.52,
        0.76,
        "bottom",
    ),

    "utility_demo": (
        0.44,
        0.08,
        0.52,
        0.76,
        "bottom",
    ),

    "technical_grid": (
        0.50,
        0.08,
        0.46,
        0.76,
        "bottom",
    ),

    # V2: create genuine narrative space on the left.
    "discovery_story": (
        0.30,
        0.03,
        0.62,
        0.70,
        "top",
    ),

    "feature_commerce": (
        0.44,
        0.08,
        0.52,
        0.76,
        "bottom",
    ),
}




def _apply_adaptive_product_zone(
    zone,
    fmt,
    layout_variant: str,
):
    """Apply composition-specific placement to the real source product."""

    values = (
        _ADAPTIVE_PRODUCT_ZONES.get(
            layout_variant
        )
    )

    if values is None:
        return zone

    (
        left,
        top,
        width,
        height,
        anchor,
    ) = values

    return replace(
        zone,
        left=round(
            left * fmt.width
        ),
        top=round(
            top * fmt.height
        ),
        width=round(
            width * fmt.width
        ),
        height=round(
            height * fmt.height
        ),
        anchor=anchor,
    )



@dataclass
class MaskedSceneEditInputs:
    """Deterministic input tuple for one bounded image-edit call."""

    base_image: Image.Image
    mask_image: Image.Image
    product_overlay: Image.Image
    background_isolator_used: str
    product_zone_detected: bool


def _resolve_product_zone(
    creative_input: SlideCreativeInput,
    *,
    fmt,
    template,
    layout_variant: str,
):
    """Single product-zone resolver shared before and after the AI edit."""
    zone = product_zone_for(
        template,
        fmt,
    )

    if (
        creative_input.template_id
        == "feature_showcase"
    ):
        zone = _apply_adaptive_product_zone(
            zone,
            fmt,
            layout_variant,
        )

    detection = (
        creative_input.product_zone_detection
    )

    if detection is not None:
        zone = replace(
            zone,
            anchor=detection.anchor,
        )

    return zone


def prepare_masked_scene_edit_inputs(
    creative_input: SlideCreativeInput,
) -> MaskedSceneEditInputs:
    """Build same-size base, protection mask, and deterministic product layer.

    BUILD6R_BOUNDED_MASKED_SCENE_EDIT_INPUTS_V2

    This function is pure/local. It never calls an AI provider.
    """
    if creative_input.recreated_image is not None:
        raise RuntimeError(
            "Masked scene editing cannot accept AI-recreated product pixels."
        )

    fmt = get_platform_format(
        creative_input.platform_key
    )

    template = get_template(
        creative_input.template_id
    )

    layout_variant = resolve_layout_variant(
        creative_input
    )

    with Image.open(
        creative_input.source_image_path
    ) as src:
        product_image = src.convert(
            "RGBA"
        ).copy()

    detection = (
        creative_input.product_zone_detection
    )

    isolator: BackgroundIsolator = (
        get_isolator(
            enabled=creative_input.isolate_background,
            source_path=creative_input.source_image_path,
            prefer_immutable=True,
        )
    )

    isolated_product = isolator.isolate(
        product_image
    )

    product_zone_detected = False

    if detection is not None:
        isolated_product = (
            _crop_to_fraction_box(
                isolated_product,
                detection,
            )
        )

        product_zone_detected = True

    zone = _resolve_product_zone(
        creative_input,
        fmt=fmt,
        template=template,
        layout_variant=layout_variant,
    )

    background = make_background(
        width=fmt.width,
        height=fmt.height,
        colors=creative_input.brand_colors,
    )

    background = _resize_cover(
        background,
        fmt.width,
        fmt.height,
    )

    # No deterministic shadow in the AI input. The editable surrounding
    # scene is responsible for integrated contact lighting/shadow.
    base_image = composite_product(
        background=background,
        product=isolated_product,
        zone=zone,
        shadow=False,
    )

    product_overlay = build_product_overlay(
        canvas_size=(
            fmt.width,
            fmt.height,
        ),
        product=isolated_product,
        zone=zone,
    )

    mask_image = (
        build_product_protection_mask(
            canvas_size=(
                fmt.width,
                fmt.height,
            ),
            product=isolated_product,
            zone=zone,
            padding=18,
        )
    )

    if not (
        base_image.size
        == mask_image.size
        == product_overlay.size
    ):
        raise RuntimeError(
            "Masked scene base/mask/product dimensions diverged."
        )

    return MaskedSceneEditInputs(
        base_image=base_image,
        mask_image=mask_image,
        product_overlay=product_overlay,
        background_isolator_used=isolator.name,
        product_zone_detected=product_zone_detected,
    )


async def render_slide(
    creative_input: SlideCreativeInput,
    *,
    output_path: Path,
    renderer: PlaywrightRenderer,
) -> SlideRenderResult:
    """Runs the hybrid pipeline for one slide and writes the PNG to `output_path`.
    Never opens `source_image_path`/`logo_path` in a writing mode, and never writes
    anywhere except under `output_path` — safe to point at a real SOURCE_ASSET_ROOT
    file (see tests/test_creative.py::test_pipeline_never_touches_source).
    """
    # BUILD6R_IMMUTABLE_PRODUCT_LAYER_RENDER_GUARD
    # AI-generated backgrounds are allowed; AI-generated product
    # pixels are not. Legacy recreated-image inputs fail closed
    # instead of bypassing deterministic product compositing.
    if creative_input.recreated_image is not None:
        raise RuntimeError(
            "AI-recreated product imagery is prohibited. "
            "Provide generated_background only; render_slide must "
            "composite the authentic source product layer."
        )

    fmt = get_platform_format(creative_input.platform_key)
    template = get_template(creative_input.template_id)

    layout_variant = resolve_layout_variant(
        creative_input
    )

    # Load the real source photo, read-only, exactly once.
    with Image.open(creative_input.source_image_path) as src:
        product_image = src.convert("RGBA").copy()

    detection = creative_input.product_zone_detection
    product_zone_detected = False
    background_isolator_used = "none"

    if creative_input.recreated_image is not None:
        # Full AI recreation already produced the whole scene (product included) —
        # isolation/background/compositing below are skipped entirely; just get it
        # to the exact platform canvas size.
        composited = creative_input.recreated_image.convert("RGB")
        composited = _resize_cover(composited, fmt.width, fmt.height)
        background_isolator_used = "ai_recreated"
    else:
        # BUILD6R_IMMUTABLE_PRODUCT_CUTOUT_SELECTION
        # Prefer the SHA-keyed deterministic cutout for every supported
        # product render. It modifies only a derived alpha mask; the
        # authentic source file and RGB package artwork remain untouched.
        isolator: BackgroundIsolator = get_isolator(
            enabled=creative_input.isolate_background,
            source_path=creative_input.source_image_path,
            prefer_immutable=True,
        )
        isolated_product = isolator.isolate(product_image)
        background_isolator_used = isolator.name

        if detection is not None:
            # Tightly crop to where the vision model says the product actually sits in
            # this photo, so the compositor fills the template's zone with the product
            # itself rather than the whole framed shot (empty margin and all).
            isolated_product = _crop_to_fraction_box(isolated_product, detection)
            product_zone_detected = True

        background = creative_input.generated_background or make_background(
            width=fmt.width, height=fmt.height, colors=creative_input.brand_colors
        )
        background = _resize_cover(background, fmt.width, fmt.height)

        zone = _resolve_product_zone(
            creative_input,
            fmt=fmt,
            template=template,
            layout_variant=layout_variant,
        )

        composited = composite_product(
            background=background,
            product=isolated_product,
            zone=zone,
            shadow=not creative_input.masked_scene_background,
        )

    logo_data_uri = _file_to_data_uri(creative_input.logo_path) if creative_input.logo_path else None
    ctx = TemplateContext(
        width=fmt.width,
        height=fmt.height,
        composited_image_data_uri=_image_to_data_uri(composited),
        eyebrow=creative_input.eyebrow,
        headline=creative_input.headline,
        body=creative_input.body,
        cta=creative_input.cta,
        logo_data_uri=logo_data_uri,
        accent_color=creative_input.accent_color,
        text_color=creative_input.text_color,
        font_family=creative_input.font_family,
        badge_text=creative_input.badge_text,
        intro=creative_input.intro,
        features=creative_input.features,
        callout_label=creative_input.callout_label,
        callout_value=creative_input.callout_value,
        bottom_features=creative_input.bottom_features,
        trust_badges=creative_input.trust_badges,
        slide_number=creative_input.slide_number,
        total_slides=creative_input.total_slides,
        disclaimer=creative_input.disclaimer,
        layout_variant=layout_variant,
        campaign_archetype=creative_input.campaign_archetype,
        slide_role=creative_input.slide_role,
              direction_palette=list(creative_input.direction_palette or []),
              secondary_font_family=creative_input.secondary_font_family,
              typography_direction=creative_input.typography_direction,
              headline_emphasis=creative_input.headline_emphasis,
              cta_treatment=creative_input.cta_treatment,
              hero_treatment=creative_input.hero_treatment,
              visual_style=creative_input.visual_style,
              mood=creative_input.mood,
              negative_space=creative_input.negative_space,
              masked_scene_background=creative_input.masked_scene_background,
    )
    html_doc = template.build_html(ctx)

    png_bytes, diagnostics = await renderer.render_png_with_diagnostics(
        html=html_doc, width=fmt.width, height=fmt.height
    )

    qa_result = run_creative_qa(
        png_bytes=png_bytes,
        expected_width=fmt.width,
        expected_height=fmt.height,
        diagnostics=diagnostics,
        logo_expected=creative_input.logo_path is not None,
        logo_included=logo_data_uri is not None,
        # Only fields that actually land inside `.text-block` (see
        # templates.py::_build_feature_showcase) belong here — badge_text/
        # bottom_features/trust_badges render as separate elements outside it,
        # so including them would make QA expect a `.text-block` that a
        # badge-only slide never draws.
        # `disclaimer` deliberately excluded here even though `_build_premium_
        # product_hero` renders it inside `.text-block` when it's the only text
        # present — `_build_feature_showcase` (the default template) renders it
        # as its own separate element outside `.text-block` (like badge_text/
        # trust_badges above), so including it here would make QA expect a
        # `.text-block` that the default template's disclaimer-only case never
        # draws. A disclaimer-only premium_product_hero slide is a narrow edge
        # case not exercised by real campaigns today.
        text_expected=bool(
            creative_input.eyebrow
            or creative_input.headline
            or creative_input.body
            or creative_input.cta
            or creative_input.intro
            or creative_input.features
            or creative_input.callout_label
            or creative_input.callout_value
        ),
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(png_bytes)

    return SlideRenderResult(
        output_path=output_path,
        width=fmt.width,
        height=fmt.height,
        qa=qa_result,
        background_isolator_used=background_isolator_used,
        product_zone_detected=product_zone_detected,
    )



RENDER_CONTEXT_VERSION = "build6r-render-context-v1"


def build_render_context_path(
    slide_output_path: Path,
) -> Path:
    slide_output_path = Path(
        slide_output_path
    )

    return slide_output_path.with_name(
        slide_output_path.stem
        + ".render-context.json"
    )


def build_render_visual_base_path(
    slide_output_path: Path,
) -> Path:
    slide_output_path = Path(
        slide_output_path
    )

    return slide_output_path.with_name(
        slide_output_path.stem
        + ".visual-base.png"
    )


def persist_render_context(
    *,
    slide_output_path: Path,
    creative_direction: dict | None,
    visual_base,
    visual_base_kind: str,
    product_zone_detection=None,
    slide_role: str = "",
) -> Path:
    """Persist text-free visual state for later zero-cost QA rerenders."""
    import hashlib
    import json

    slide_output_path = Path(
        slide_output_path
    )

    context_path = build_render_context_path(
        slide_output_path
    )

    visual_base_path = build_render_visual_base_path(
        slide_output_path
    )

    context_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    valid_kinds = {
        "none",
        "generated_background",
        "recreated_image",
    }

    if visual_base_kind not in valid_kinds:
        raise ValueError(
            "Unsupported visual_base_kind: "
            + str(
                visual_base_kind
            )
        )

    zone_payload = None

    if product_zone_detection is not None:
        model_dump = getattr(
            product_zone_detection,
            "model_dump",
            None,
        )

        if callable(
            model_dump
        ):
            zone_payload = model_dump()

        elif isinstance(
            product_zone_detection,
            dict,
        ):
            zone_payload = dict(
                product_zone_detection
            )

        else:
            raise TypeError(
                "Unsupported product_zone_detection type."
            )

    visual_base_sha256 = ""
    stored_visual_base_path = ""

    if (
        visual_base is not None
        and visual_base_kind != "none"
    ):
        temporary_base = visual_base_path.with_name(
            visual_base_path.name
            + ".tmp"
        )

        visual_base.save(
            temporary_base,
            format="PNG",
        )

        temporary_base.replace(
            visual_base_path
        )

        visual_base_sha256 = hashlib.sha256(
            visual_base_path.read_bytes()
        ).hexdigest()

        stored_visual_base_path = str(
            visual_base_path
        )

    else:
        visual_base_kind = "none"

        if visual_base_path.exists():
            visual_base_path.unlink()

    payload = {
        "version": RENDER_CONTEXT_VERSION,
        "slide_output_path": str(
            slide_output_path
        ),
        "creative_direction": dict(
            creative_direction
            or {}
        ),
        "visual_base_kind": visual_base_kind,
        "visual_base_path": stored_visual_base_path,
        "visual_base_sha256": visual_base_sha256,
        "product_zone_detection": zone_payload,
        "slide_role": slide_role or "",
    }

    temporary_context = context_path.with_name(
        context_path.name
        + ".tmp"
    )

    temporary_context.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    temporary_context.replace(
        context_path
    )

    return context_path


def load_render_context(
    slide_output_path: Path,
) -> dict | None:
    import json

    context_path = build_render_context_path(
        slide_output_path
    )

    if not context_path.is_file():
        return None

    try:
        payload = json.loads(
            context_path.read_text(
                encoding="utf-8"
            )
        )
    except Exception as exc:
        raise RuntimeError(
            "Unreadable render-context sidecar: "
            + str(
                context_path
            )
        ) from exc

    if not isinstance(
        payload,
        dict,
    ):
        raise RuntimeError(
            "Render-context sidecar is not an object."
        )

    if (
        payload.get(
            "version"
        )
        != RENDER_CONTEXT_VERSION
    ):
        raise RuntimeError(
            "Unsupported render-context sidecar version."
        )

    return payload


def load_render_visual_base(
    slide_output_path: Path,
):
    import hashlib
    from PIL import Image as PILImage

    context = load_render_context(
        slide_output_path
    )

    if context is None:
        return None, "none", None

    kind = str(
        context.get(
            "visual_base_kind",
            "none",
        )
        or "none"
    )

    if kind == "none":
        return None, "none", context

    if kind not in {
        "generated_background",
        "recreated_image",
    }:
        raise RuntimeError(
            "Unknown persisted visual-base kind: "
            + kind
        )

    stored_path = str(
        context.get(
            "visual_base_path",
            "",
        )
        or ""
    )

    visual_base_path = (
        Path(
            stored_path
        )
        if stored_path
        else build_render_visual_base_path(
            slide_output_path
        )
    )

    if not visual_base_path.is_file():
        raise RuntimeError(
            "Persisted visual base is missing: "
            + str(
                visual_base_path
            )
        )

    expected_sha = str(
        context.get(
            "visual_base_sha256",
            "",
        )
        or ""
    )

    actual_sha = hashlib.sha256(
        visual_base_path.read_bytes()
    ).hexdigest()

    if (
        expected_sha
        and actual_sha != expected_sha
    ):
        raise RuntimeError(
            "Persisted visual base SHA256 mismatch: "
            + str(
                visual_base_path
            )
        )

    with PILImage.open(
        visual_base_path
    ) as opened:
        opened.load()
        image = opened.copy()

    return image, kind, context


def build_slide_output_path(
    *,
    output_root: Path,
    brand_slug: str,
    category_slug: str,
    campaign_display_id: str,
    year: int,
    month: int,
    platform_key: str,
    slide_number: int,
) -> Path:
    """The deterministic folder structure documented in README.md / architecture.md:
    OUTPUT_ROOT/<brand>/<category>/<year>/<year-month>/<campaign>/<platform>/slide-NN.png
    """
    return (
        output_root
        / brand_slug
        / category_slug
        / f"{year:04d}"
        / f"{year:04d}-{month:02d}"
        / campaign_display_id
        / platform_key
        / f"slide-{slide_number:02d}.png"
    )


def build_qa_report_path(
    *,
    output_root: Path,
    brand_slug: str,
    category_slug: str,
    campaign_display_id: str,
    year: int,
    month: int,
    slide_number: int,
) -> Path:
    return (
        output_root
        / brand_slug
        / category_slug
        / f"{year:04d}"
        / f"{year:04d}-{month:02d}"
        / campaign_display_id
        / "qa"
        / f"slide-{slide_number:02d}.json"
    )


def build_variant_slide_output_path(
    *,
    output_root: Path,
    brand_slug: str,
    category_slug: str,
    campaign_display_id: str,
    year: int,
    month: int,
    platform_key: str,
    language: str,
    slide_number: int,
) -> Path:
    """Build 2: same deterministic scheme as `build_slide_output_path`, with one
    more path segment (`language`) so an ADDITIONAL rendered variant (a
    non-primary platform, or a non-primary language on the same platform)
    never collides with the primary combo's own output path — which stays
    exactly `OUTPUT_ROOT/.../<platform_key>/slide-NN.png`, unchanged, since
    that path predates languages ever varying by platform at all. Only ever
    used for a variant OTHER than the primary (target_platform, language)
    combination — see `services/orchestrator.py::
    _render_additional_platform_variants`.
    """
    return (
        output_root
        / brand_slug
        / category_slug
        / f"{year:04d}"
        / f"{year:04d}-{month:02d}"
        / campaign_display_id
        / platform_key
        / language
        / f"slide-{slide_number:02d}.png"
    )


def build_variant_qa_report_path(
    *,
    output_root: Path,
    brand_slug: str,
    category_slug: str,
    campaign_display_id: str,
    year: int,
    month: int,
    platform_key: str,
    language: str,
    slide_number: int,
) -> Path:
    return (
        output_root
        / brand_slug
        / category_slug
        / f"{year:04d}"
        / f"{year:04d}-{month:02d}"
        / campaign_display_id
        / "qa"
        / platform_key
        / language
        / f"slide-{slide_number:02d}.json"
    )
