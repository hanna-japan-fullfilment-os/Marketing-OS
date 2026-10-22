"""Tests for the creative pipeline (campaign-pipeline.md hybrid pipeline steps 3-8).

Covers the compositor, template HTML building, the Playwright renderer, automated
QA, and the full pipeline end to end — including extending the source-asset
immutability guarantee (see test_source_immutability.py) to this new code path,
since render_slide() is the second module in the codebase (after the scanner) that
reads real files from SOURCE_ASSET_ROOT.
"""
from __future__ import annotations

import hashlib
import io
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from app.services.creative import templates as templates_module
from app.services.creative.background import NoOpBackgroundIsolator
from app.services.creative.compositor import ProductZone, composite_product, make_background
from app.services.creative.pipeline import (
    SlideCreativeInput,
    _crop_to_fraction_box,
    _resize_cover,
    build_qa_report_path,
    build_slide_output_path,
    render_slide,
)
from app.services.creative.qa import run_creative_qa
from app.services.creative.renderer import PlaywrightRenderer, RenderDiagnostics
from app.services.creative.templates import Feature, TemplateContext, get_template
from app.schemas.ai import ProductZoneDetection


# --------------------------------------------------------------------------------
# compositor
# --------------------------------------------------------------------------------


def test_make_background_has_requested_size_and_gradient_endpoints():
    bg = make_background(width=200, height=100, colors=["#ff0000", "#0000ff"])
    assert bg.size == (200, 100)
    top_pixel = bg.getpixel((100, 0))
    bottom_pixel = bg.getpixel((100, 99))
    assert top_pixel[0] > top_pixel[2]  # top is red-dominant
    assert bottom_pixel[2] > bottom_pixel[0]  # bottom is blue-dominant


def test_make_background_falls_back_to_neutral_gradient_without_brand_colors():
    bg = make_background(width=100, height=100, colors=None)
    assert bg.size == (100, 100)


def test_composite_product_preserves_canvas_size_and_changes_pixels_in_zone():
    background = Image.new("RGB", (400, 400), (10, 10, 10))
    product = Image.new("RGBA", (100, 100), (255, 0, 0, 255))
    zone = ProductZone(left=50, top=50, width=200, height=200, anchor="center")

    result = composite_product(background=background, product=product, zone=zone, shadow=False)

    assert result.size == (400, 400)
    # Center of the zone should now show (scaled) product color, not the background.
    center_pixel = result.getpixel((150, 150))
    assert center_pixel != (10, 10, 10)
    # A far corner outside the zone should be untouched background.
    assert result.getpixel((5, 5)) == (10, 10, 10)


def test_composite_product_does_not_mutate_inputs():
    background = Image.new("RGB", (300, 300), (20, 20, 20))
    product = Image.new("RGBA", (50, 50), (0, 255, 0, 255))
    background_before = background.copy()
    product_before = product.copy()
    zone = ProductZone(left=0, top=0, width=300, height=300, anchor="center")

    composite_product(background=background, product=product, zone=zone)

    assert list(background.getdata()) == list(background_before.getdata())
    assert list(product.getdata()) == list(product_before.getdata())


def test_noop_background_isolator_returns_rgba_copy():
    isolator = NoOpBackgroundIsolator()
    src = Image.new("RGB", (10, 10), (1, 2, 3))
    out = isolator.isolate(src)
    assert out.mode == "RGBA"
    assert out.size == (10, 10)


# --------------------------------------------------------------------------------
# templates
# --------------------------------------------------------------------------------


def test_premium_product_hero_template_escapes_text_and_includes_fields():
    template = get_template("premium_product_hero")
    ctx = TemplateContext(
        width=1080,
        height=1080,
        composited_image_data_uri="data:image/png;base64,AAAA",
        eyebrow="Limited Time",
        headline="<script>alert(1)</script>",
        body="Straight from Japan",
        cta="Shop now",
    )
    html_doc = template.build_html(ctx)

    assert "<script>alert(1)</script>" not in html_doc  # must be escaped, never executed
    assert "&lt;script&gt;" in html_doc
    assert "Limited Time" in html_doc
    assert "Straight from Japan" in html_doc
    assert "Shop now" in html_doc
    assert "data:image/png;base64,AAAA" in html_doc


def test_premium_product_hero_omits_scrim_and_text_block_when_no_text_given():
    """Round 16: when a full AI recreation bakes the marketing text directly into
    the image (see orchestrator.py::recreate_creative_image), the caller passes no
    eyebrow/headline/body/CTA at all — the template must not render an empty dark
    scrim over an image that has nothing to caption. The logo is unaffected either
    way; it's never left to the AI regardless of whether text was baked in.
    """
    template = get_template("premium_product_hero")
    ctx = TemplateContext(
        width=1080,
        height=1080,
        composited_image_data_uri="data:image/png;base64,AAAA",
        logo_data_uri="data:image/png;base64,BBBB",
        # eyebrow/headline/body/cta all default to ""
    )
    html_doc = template.build_html(ctx)

    assert 'class="scrim"' not in html_doc
    assert 'class="text-block"' not in html_doc
    assert 'class="logo"' in html_doc  # still rendered — logo is independent of text


def test_premium_product_hero_includes_scrim_and_text_block_when_any_text_given():
    """The inverse of the above — a single non-empty field (eyebrow here) is enough
    to bring the scrim/text-block back, matching pre-round-16 behavior exactly.
    """
    template = get_template("premium_product_hero")
    ctx = TemplateContext(
        width=1080,
        height=1080,
        composited_image_data_uri="data:image/png;base64,AAAA",
        eyebrow="New",
    )
    html_doc = template.build_html(ctx)

    assert 'class="scrim"' in html_doc
    assert 'class="text-block"' in html_doc


def test_feature_showcase_template_escapes_text_and_includes_all_sections():
    """Round 17: the richer default template — badge, intro, feature list,
    ingredients/results callout, bottom icon-feature strip, and CTA bar with
    trust badges — modeled on the user's own reference ads (see templates.py's
    `_build_feature_showcase` docstring).
    """
    template = get_template("feature_showcase")
    ctx = TemplateContext(
        width=1080,
        height=1080,
        composited_image_data_uri="data:image/png;base64,AAAA",
        eyebrow="Limited Time",
        headline="<script>alert(1)</script>",
        body="Straight from Japan",
        cta="Shop now",
        badge_text="Best Seller",
        intro="Loved by thousands of customers across Brazil.",
        features=[
            templates_module.Feature(icon="\U0001F4A7", title="Deep hydration", subtitle="24h moisture"),
            templates_module.Feature(icon="\U0001F343", title="Natural", subtitle="No parabens"),
        ],
        callout_label="Key ingredient",
        callout_value="Niacinamide 10%",
        bottom_features=["Ships nationwide", "Dermatologically tested"],
        trust_badges=["Guaranteed", "100% original"],
        logo_data_uri="data:image/png;base64,BBBB",
    )
    html_doc = template.build_html(ctx)

    assert "<script>alert(1)</script>" not in html_doc  # must be escaped, never executed
    assert "&lt;script&gt;" in html_doc
    assert "Limited Time" in html_doc
    assert "Straight from Japan" in html_doc
    assert "Best Seller" in html_doc
    assert "Loved by thousands" in html_doc
    assert "Deep hydration" in html_doc
    assert "24h moisture" in html_doc
    assert "Natural" in html_doc
    assert "Key ingredient" in html_doc
    assert "Niacinamide 10%" in html_doc
    assert "Ships nationwide" in html_doc
    assert "Shop now" in html_doc
    assert "Guaranteed" in html_doc
    assert 'class="logo"' in html_doc
    assert 'class="badge"' in html_doc
    assert 'class="feature-list"' in html_doc
    assert 'class="callout"' in html_doc
    assert 'class="support-strip"' in html_doc
    assert 'class="commercial-footer"' in html_doc




def test_feature_showcase_omits_optional_sections_when_fields_empty():
    """Every section (badge/features/callout/bottom-strip/CTA-bar) is independently
    optional — a slide with none of them (e.g. text baked into an AI recreation,
    see orchestrator.py::run_visuals_stage) renders just the photo and logo, same
    as `premium_product_hero`'s no-text case.
    """
    template = get_template("feature_showcase")
    ctx = TemplateContext(
        width=1080,
        height=1080,
        composited_image_data_uri="data:image/png;base64,AAAA",
        logo_data_uri="data:image/png;base64,BBBB",
    )
    html_doc = template.build_html(ctx)

    assert 'class="badge"' not in html_doc
    assert 'class="text-block"' not in html_doc
    assert 'class="feature-list"' not in html_doc
    assert 'class="callout"' not in html_doc
    assert 'class="bottom-strip"' not in html_doc
    assert 'class="cta-bar"' not in html_doc
    assert 'class="logo"' in html_doc  # logo is independent of everything else


def test_slide_marker_renders_on_both_templates_when_total_slides_set():
    """Round 18: the "N/total" carousel-position marker (see templates.py::
    _slide_marker_html) — real HTML/CSS, so it's exact regardless of which
    template or generation path produced the slide. Checked on both registered
    templates since it's a shared helper, not something either template builder
    hand-rolls itself.
    """
    for template_id in ("feature_showcase", "premium_product_hero"):
        template = get_template(template_id)
        ctx = TemplateContext(
            width=1080, height=1080, composited_image_data_uri="data:image/png;base64,AAAA",
            slide_number=2, total_slides=6,
        )
        html_doc = template.build_html(ctx)
        assert 'class="slide-marker"' in html_doc
        assert "2/6" in html_doc


def test_feature_showcase_text_block_clears_the_slide_marker():
    import re

    template = get_template(
        "feature_showcase"
    )

    with_marker = template.build_html(
        TemplateContext(
            width=1080,
            height=1080,
            composited_image_data_uri=(
                "data:image/png;base64,AAAA"
            ),
            eyebrow="Eyebrow",
            headline="Headline",
            slide_number=2,
            total_slides=6,
        )
    )

    without_marker = template.build_html(
        TemplateContext(
            width=1080,
            height=1080,
            composited_image_data_uri=(
                "data:image/png;base64,AAAA"
            ),
            eyebrow="Eyebrow",
            headline="Headline",
        )
    )

    pattern = (
        r"\.text-block\s*\{"
        r".*?"
        r"top:\s*([0-9.]+)%"
    )

    with_match = re.search(
        pattern,
        with_marker,
        re.S,
    )

    without_match = re.search(
        pattern,
        without_marker,
        re.S,
    )

    assert with_match is not None
    assert without_match is not None

    with_top = float(
        with_match.group(1)
    )

    without_top = float(
        without_match.group(1)
    )

    assert with_top > without_top



def test_slide_marker_omitted_when_total_slides_is_one_or_unset():
    """A single-image post (no carousel) must render no marker at all — the
    default `slide_number=0, total_slides=0` on TemplateContext, and explicitly
    `total_slides=1` (a one-slide carousel), both mean "nothing to show".
    """
    template = get_template("feature_showcase")
    for slide_number, total_slides in ((0, 0), (1, 1)):
        ctx = TemplateContext(
            width=1080, height=1080, composited_image_data_uri="data:image/png;base64,AAAA",
            slide_number=slide_number, total_slides=total_slides,
        )
        html_doc = template.build_html(ctx)
        assert 'class="slide-marker"' not in html_doc


def test_feature_showcase_caps_feature_list_at_five_and_skips_blank_titles():
    template = get_template("feature_showcase")
    ctx = TemplateContext(
        width=1080,
        height=1080,
        composited_image_data_uri="data:image/png;base64,AAAA",
        features=[
            templates_module.Feature(icon="1", title=""),  # blank title — skipped
            *[templates_module.Feature(icon="X", title=f"Feature {i}") for i in range(7)],
        ],
    )
    html_doc = template.build_html(ctx)
    assert html_doc.count('class="feature-card"') == 5



def test_unknown_template_id_raises_clear_error():
    with pytest.raises(ValueError, match="Unknown creative template"):
        get_template("does-not-exist")


def test_unknown_platform_format_raises_clear_error():
    with pytest.raises(ValueError, match="Unknown platform format"):
        templates_module.get_platform_format("does-not-exist")


def test_product_zone_for_resolves_fractions_to_pixels():
    template = get_template("premium_product_hero")
    fmt = templates_module.get_platform_format("instagram_square")
    zone = templates_module.product_zone_for(template, fmt)
    assert 0 <= zone.left < fmt.width
    assert 0 <= zone.top < fmt.height
    assert zone.left + zone.width <= fmt.width
    assert zone.top + zone.height <= fmt.height


# --------------------------------------------------------------------------------
# renderer
# --------------------------------------------------------------------------------


@pytest.fixture()
async def shared_renderer():
    renderer = PlaywrightRenderer()
    yield renderer
    await renderer.close()


async def test_renderer_produces_png_at_exact_dimensions(shared_renderer):
    html_doc = "<html><body style='margin:0;background:#336699;width:300px;height:150px;'></body></html>"
    png_bytes = await shared_renderer.render_png(html=html_doc, width=300, height=150)
    with Image.open(io.BytesIO(png_bytes)) as img:
        assert img.format == "PNG"
        assert img.size == (300, 150)


async def test_renderer_diagnostics_detect_text_block_and_overflow(shared_renderer):
    template = get_template("premium_product_hero")
    ctx = TemplateContext(
        width=1080,
        height=1080,
        composited_image_data_uri=_solid_png_data_uri((1080, 1080), (120, 120, 120)),
        eyebrow="New",
        headline="A short headline",
        body="Short body copy.",
        cta="Buy now",
    )
    html_doc = template.build_html(ctx)
    _png, diagnostics = await shared_renderer.render_png_with_diagnostics(html=html_doc, width=1080, height=1080)
    assert isinstance(diagnostics, RenderDiagnostics)
    assert diagnostics.text_block_present is True
    assert diagnostics.text_overflowed is False


async def test_feature_showcase_renders_without_overflow_at_full_content(shared_renderer):
    """A realistically full slide (eyebrow + headline + intro + 5 features + a
    callout box, the maximum this template supports) must still fit within its
    safe-margin box on the default 1080x1080 canvas — this is what actually
    catches a layout that looks fine with two features but breaks with five.
    """
    template = get_template("feature_showcase")
    ctx = TemplateContext(
        width=1080,
        height=1080,
        composited_image_data_uri=_solid_png_data_uri((1080, 1080), (120, 120, 120)),
        eyebrow="Novidade",
        headline="Hidratação profunda para todo tipo de pele",
        intro="Formulado com ingredientes reais, testado dermatologicamente.",
        features=[
            templates_module.Feature(icon="\U0001F4A7", title="Hidratação 24h", subtitle="Efeito imediato"),
            templates_module.Feature(icon="\U0001F343", title="100% natural", subtitle="Sem parabenos"),
            templates_module.Feature(icon="✨", title="Pele renovada", subtitle="Resultados visíveis"),
            templates_module.Feature(icon="\U0001F3F5", title="Aroma suave", subtitle="Sem excessos"),
            templates_module.Feature(icon="✅", title="Aprovado", subtitle="Milhares de clientes"),
        ],
        callout_label="Ingrediente-chave",
        callout_value="Niacinamida 10%",
        cta="Compre agora",
        trust_badges=["Compra garantida", "Original"],
        bottom_features=["Envio para todo o Brasil", "Testado dermatologicamente"],
    )
    html_doc = template.build_html(ctx)
    _png, diagnostics = await shared_renderer.render_png_with_diagnostics(html=html_doc, width=1080, height=1080)
    assert diagnostics.text_block_present is True
    assert diagnostics.text_overflowed is False


def _solid_png_data_uri(size: tuple[int, int], color: tuple[int, int, int]) -> str:
    import base64

    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{b64}"


# --------------------------------------------------------------------------------
# qa
# --------------------------------------------------------------------------------


def _png_bytes(size: tuple[int, int]) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, (10, 20, 30)).save(buf, format="PNG")
    return buf.getvalue()


def test_qa_passes_for_correct_dimensions_and_no_overflow():
    result = run_creative_qa(
        png_bytes=_png_bytes((1080, 1080)),
        expected_width=1080,
        expected_height=1080,
        diagnostics=RenderDiagnostics(text_block_present=True, text_overflowed=False),
        logo_expected=False,
        logo_included=False,
    )
    assert result.passed is True
    assert result.issues == []


def test_qa_flags_dimension_mismatch():
    result = run_creative_qa(
        png_bytes=_png_bytes((500, 500)),
        expected_width=1080,
        expected_height=1080,
        diagnostics=RenderDiagnostics(text_block_present=True, text_overflowed=False),
        logo_expected=False,
        logo_included=False,
    )
    assert result.passed is False
    assert any("1080x1080" in issue for issue in result.issues)


def test_qa_does_not_flag_missing_text_block_when_text_not_expected():
    """Round 16: a slide with no text at all (full AI recreation baking its own
    text into the image) correctly renders no `.text-block` element — that must
    not be reported as a QA failure the way a *missing* text block would be when
    text was actually expected (see the next test).
    """
    result = run_creative_qa(
        png_bytes=_png_bytes((1080, 1080)),
        expected_width=1080,
        expected_height=1080,
        diagnostics=RenderDiagnostics(text_block_present=False, text_overflowed=False),
        logo_expected=False,
        logo_included=False,
        text_expected=False,
    )
    assert result.passed is True
    assert result.issues == []
    assert result.checks["text_block_present"] is True  # nothing was expected, nothing to flag


def test_qa_flags_missing_text_block_when_text_was_expected():
    result = run_creative_qa(
        png_bytes=_png_bytes((1080, 1080)),
        expected_width=1080,
        expected_height=1080,
        diagnostics=RenderDiagnostics(text_block_present=False, text_overflowed=False),
        logo_expected=False,
        logo_included=False,
        text_expected=True,
    )
    assert result.passed is False
    assert any("text-block" in issue for issue in result.issues)


def test_qa_flags_text_overflow():
    result = run_creative_qa(
        png_bytes=_png_bytes((1080, 1080)),
        expected_width=1080,
        expected_height=1080,
        diagnostics=RenderDiagnostics(text_block_present=True, text_overflowed=True),
        logo_expected=False,
        logo_included=False,
    )
    assert result.passed is False
    assert any("overflowed" in issue for issue in result.issues)


def test_qa_flags_missing_expected_logo():
    result = run_creative_qa(
        png_bytes=_png_bytes((1080, 1080)),
        expected_width=1080,
        expected_height=1080,
        diagnostics=RenderDiagnostics(text_block_present=True, text_overflowed=False),
        logo_expected=True,
        logo_included=False,
    )
    assert result.passed is False
    assert any("logo" in issue.lower() for issue in result.issues)


def test_qa_flags_invalid_image_bytes():
    result = run_creative_qa(
        png_bytes=b"not a real image",
        expected_width=1080,
        expected_height=1080,
        diagnostics=RenderDiagnostics(text_block_present=True, text_overflowed=False),
        logo_expected=False,
        logo_included=False,
    )
    assert result.passed is False
    assert result.checks["file_integrity"] is False


# --------------------------------------------------------------------------------
# full pipeline, including the source-immutability guarantee
# --------------------------------------------------------------------------------


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture()
def source_and_logo(tmp_path):
    source_root = tmp_path / "source"
    (source_root / "skincare" / "product-a").mkdir(parents=True)
    product_photo = source_root / "skincare" / "product-a" / "hero.jpg"
    Image.new("RGB", (900, 900), (180, 90, 40)).save(product_photo)

    logo_path = source_root / "brand" / "logo.png"
    logo_path.parent.mkdir(parents=True)
    Image.new("RGBA", (200, 80), (255, 255, 255, 0)).save(logo_path)

    return source_root, product_photo, logo_path


async def test_render_slide_writes_expected_output(tmp_path, source_and_logo, shared_renderer):
    source_root, product_photo, logo_path = source_and_logo
    output_path = tmp_path / "output" / "slide-01.png"

    creative_input = SlideCreativeInput(
        source_image_path=product_photo,
        template_id="premium_product_hero",
        platform_key="instagram_square",
        eyebrow="Direct from Japan",
        headline="Your new skincare favorite",
        body="Sourced firsthand, shipped to Brazil.",
        cta="Shop the drop",
        brand_colors=["#f2ede3", "#d8c9ad"],
        logo_path=logo_path,
    )

    result = await render_slide(creative_input, output_path=output_path, renderer=shared_renderer)

    assert result.output_path == output_path
    assert output_path.exists()
    assert result.width == 1080 and result.height == 1080
    with Image.open(output_path) as img:
        assert img.size == (1080, 1080)
        assert img.format == "PNG"
    assert result.qa.passed is True, result.qa.issues
    # Build 6R immutable-product layer is always selected first.
    # This synthetic fixture has no safely removable studio background,
    # so the deterministic isolator correctly falls back to NoOp while
    # preserving traceability in the result.
    assert (
        result.background_isolator_used
        == "immutable_fallback_none"
    )


async def test_render_slide_never_touches_source_files(tmp_path, source_and_logo, shared_renderer, monkeypatch):
    source_root, product_photo, logo_path = source_and_logo
    before_hashes = {str(p): _sha256(p) for p in source_root.rglob("*") if p.is_file()}
    before_mtimes = {str(p): p.stat().st_mtime for p in source_root.rglob("*") if p.is_file()}

    original_open = Path.open

    def guarded_open(self, mode="r", *args, **kwargs):
        if str(self).startswith(str(source_root)) and any(c in mode for c in ("w", "a", "x", "+")):
            raise AssertionError(f"Attempted to open source file in writing mode: {self} ({mode})")
        return original_open(self, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)

    output_path = tmp_path / "output" / "slide-01.png"
    creative_input = SlideCreativeInput(
        source_image_path=product_photo,
        template_id="premium_product_hero",
        platform_key="instagram_story",
        headline="Guarded render",
        logo_path=logo_path,
    )
    await render_slide(creative_input, output_path=output_path, renderer=shared_renderer)

    after_hashes = {str(p): _sha256(p) for p in source_root.rglob("*") if p.is_file()}
    after_mtimes = {str(p): p.stat().st_mtime for p in source_root.rglob("*") if p.is_file()}
    assert after_hashes == before_hashes
    assert after_mtimes == before_mtimes


async def test_render_slide_flags_qa_issue_when_logo_missing_but_expected(tmp_path, source_and_logo, shared_renderer):
    """logo_expected is derived straight from whether logo_path was supplied, so
    this really just exercises the wiring end to end rather than duplicating the
    qa.py unit test above.
    """
    _source_root, product_photo, _logo_path = source_and_logo
    output_path = tmp_path / "output" / "slide-01.png"
    creative_input = SlideCreativeInput(
        source_image_path=product_photo,
        template_id="premium_product_hero",
        platform_key="facebook_feed",
        headline="No logo supplied",
        logo_path=None,
    )
    result = await render_slide(creative_input, output_path=output_path, renderer=shared_renderer)
    assert result.qa.checks["logo_present"] is True  # none expected, so nothing to flag


# --------------------------------------------------------------------------------
# deterministic output paths
# --------------------------------------------------------------------------------


def test_build_slide_output_path_is_deterministic(tmp_path):
    path = build_slide_output_path(
        output_root=tmp_path,
        brand_slug="hanna",
        category_slug="skincare",
        campaign_display_id="HANNA-SKIN-000123",
        year=2026,
        month=9,
        platform_key="instagram_square",
        slide_number=1,
    )
    assert path == tmp_path / "hanna" / "skincare" / "2026" / "2026-09" / "HANNA-SKIN-000123" / "instagram_square" / "slide-01.png"


def test_build_qa_report_path_is_deterministic(tmp_path):
    path = build_qa_report_path(
        output_root=tmp_path,
        brand_slug="hanna",
        category_slug="skincare",
        campaign_display_id="HANNA-SKIN-000123",
        year=2026,
        month=9,
        slide_number=1,
    )
    assert path == tmp_path / "hanna" / "skincare" / "2026" / "2026-09" / "HANNA-SKIN-000123" / "qa" / "slide-01.json"


# --------------------------------------------------------------------------------
# per-photo product-zone detection (vision-model hook)
# --------------------------------------------------------------------------------


def test_crop_to_fraction_box_crops_to_the_detected_rectangle():
    image = Image.new("RGBA", (1000, 500), (0, 0, 0, 0))
    detection = ProductZoneDetection(crop_left=0.1, crop_top=0.2, crop_width=0.5, crop_height=0.4, anchor="bottom")

    cropped = _crop_to_fraction_box(image, detection)

    # 0.1*1000=100 .. (0.1+0.5)*1000=600 -> width 500; 0.2*500=100 .. (0.2+0.4)*500=300 -> height 200
    assert cropped.size == (500, 200)


def test_crop_to_fraction_box_clamps_an_out_of_range_detection_instead_of_erroring():
    image = Image.new("RGBA", (400, 300), (0, 0, 0, 0))
    # A box that would run past the right/bottom edges if taken literally.
    detection = ProductZoneDetection(crop_left=0.9, crop_top=0.9, crop_width=0.5, crop_height=0.5, anchor="top")

    cropped = _crop_to_fraction_box(image, detection)
    assert cropped.width >= 1 and cropped.height >= 1
    assert cropped.width <= image.width and cropped.height <= image.height


def _bounding_box_size_of_color(image: Image.Image, color: tuple[int, int, int]) -> tuple[int, int]:
    """Pixel width/height of the bounding box of every pixel matching `color`
    exactly — used below to measure whether a drawn circle survived a resize as
    a circle (equal width/height) or was stretched into an ellipse.
    """
    pixels = image.load()
    xs, ys = [], []
    for y in range(image.height):
        for x in range(image.width):
            if pixels[x, y][:3] == color:
                xs.append(x)
                ys.append(y)
    assert xs and ys, "expected color not found in image"
    return (max(xs) - min(xs) + 1, max(ys) - min(ys) + 1)


def test_resize_cover_fills_the_target_box_without_stretching():
    """The bug this guards against: a plain `Image.resize` to an exact target
    size non-uniformly stretches any image whose aspect ratio doesn't already
    match — which every AI-generated image hits in practice, since the image API
    only ever returns 1:1, 2:3, or 3:2, none of which match Instagram's 4:5
    carousel slide or a 9:16 story. `_resize_cover` must scale uniformly (no
    distortion) and crop the overflow instead, so a circle drawn on the source
    is still a circle — not an ellipse — after fitting into a differently-shaped
    target box.
    """
    # 2:3 portrait source (matches the AI API's actual "portrait" bucket), with a
    # circle centered in it, being fit into a 4:5 target (Instagram's real
    # carousel-slide shape) — the two ratios are deliberately different (0.667 vs
    # 0.8) so a stretch bug would be caught.
    source = Image.new("RGB", (400, 600), (255, 255, 255))
    draw = ImageDraw.Draw(source)
    color = (200, 30, 30)
    draw.ellipse((150, 250, 250, 350), fill=color)  # a 100x100 circle, centered

    result = _resize_cover(source, 480, 600)  # target ratio 0.8, source ratio 0.667

    assert result.size == (480, 600)
    box_w, box_h = _bounding_box_size_of_color(result, color)
    # Allow a couple of pixels of anti-aliasing/rounding slack; a stretch bug
    # would skew this ratio by ~20%, far outside this tolerance.
    assert abs(box_w - box_h) <= 2, f"circle became an ellipse ({box_w}x{box_h}) — image was stretched, not cropped"


def test_resize_cover_is_a_noop_when_size_already_matches():
    source = Image.new("RGB", (300, 300), (10, 20, 30))
    result = _resize_cover(source, 300, 300)
    assert result is source


async def test_render_slide_with_product_zone_detection_crops_and_overrides_anchor(
    tmp_path, source_and_logo, shared_renderer
):
    """End-to-end wiring check: passing a ProductZoneDetection actually reaches the
    compositor (crops the isolated product before compositing, per _crop_to_fraction_box
    above) and overrides the template's fixed anchor — and the render still succeeds
    and reports `product_zone_detected=True` for observability.
    """
    _source_root, product_photo, logo_path = source_and_logo
    output_path = tmp_path / "output" / "slide-01.png"

    detection = ProductZoneDetection(
        crop_left=0.1, crop_top=0.1, crop_width=0.6, crop_height=0.6, anchor="bottom",
        reasoning="Bottle stands on a table in the lower-left of the frame.",
    )
    creative_input = SlideCreativeInput(
        source_image_path=product_photo,
        template_id="premium_product_hero",  # this template's fixed anchor is "top"
        platform_key="instagram_square",
        headline="Per-photo zone detection",
        logo_path=logo_path,
        product_zone_detection=detection,
    )

    result = await render_slide(creative_input, output_path=output_path, renderer=shared_renderer)

    assert result.product_zone_detected is True
    assert output_path.exists()
    assert result.qa.passed is True, result.qa.issues


async def test_render_slide_without_detection_reports_product_zone_detected_false(
    tmp_path, source_and_logo, shared_renderer
):
    _source_root, product_photo, logo_path = source_and_logo
    output_path = tmp_path / "output" / "slide-01.png"
    creative_input = SlideCreativeInput(
        source_image_path=product_photo,
        template_id="premium_product_hero",
        platform_key="instagram_square",
        headline="No detection",
        logo_path=logo_path,
    )
    result = await render_slide(creative_input, output_path=output_path, renderer=shared_renderer)
    assert result.product_zone_detected is False


async def test_render_slide_rejects_ai_recreated_product_pixels(
    tmp_path, source_and_logo, shared_renderer
):
    """Build 6R immutable-product contract: a recreated full-scene image
    containing AI-generated product pixels must fail closed before rendering.
    """

    _source_root, product_photo, logo_path = source_and_logo

    output_path = (
        tmp_path
        / "output"
        / "slide-01.png"
    )

    recreated = Image.new(
        "RGB",
        (400, 300),
        (12, 200, 90),
    )

    creative_input = SlideCreativeInput(
        source_image_path=product_photo,
        template_id="premium_product_hero",
        platform_key="instagram_square",
        headline="Protected product",
        logo_path=logo_path,
        recreated_image=recreated,
        product_zone_detection=ProductZoneDetection(
            crop_left=0.1,
            crop_top=0.1,
            crop_width=0.6,
            crop_height=0.6,
            anchor="bottom",
        ),
    )

    caught = None

    try:
        await render_slide(
            creative_input,
            output_path=output_path,
            renderer=shared_renderer,
        )
    except RuntimeError as exc:
        caught = exc

    assert caught is not None

    assert (
        "AI-recreated product imagery is prohibited"
        in str(caught)
    )

    assert not output_path.exists()



# Creative Output Repair V2: synchronous fake coroutines avoid any browser,
# socket, subprocess, provider, or Windows event-loop dependency.
def _repair_finish(coro):
    try:
        coro.send(None)
    except StopIteration as done:
        return done.value
    finally:
        coro.close()
    raise AssertionError("Deterministic fake unexpectedly yielded external work")


class _RepairRenderer:
    async def render_png_with_diagnostics(self, *, html, width, height):
        self.html = html
        data = io.BytesIO()
        Image.new("RGB", (width, height), (20, 30, 40)).save(data, format="PNG")
        return data.getvalue(), RenderDiagnostics(text_block_present=True, text_overflowed=False)


def _repair_plan(tmp_path, *, approved=False):
    from app.schemas.ai import SlidePlan, SlideAssetReference, SlideEvidenceReference
    product = tmp_path / "approved_product_masters" / "p" / "master.png" if approved else tmp_path / "product.png"
    product.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGBA", (360, 480), (0, 0, 0, 0))
    ImageDraw.Draw(image).rectangle((70, 45, 290, 445), fill=(180, 160, 220, 255))
    image.save(product)
    ref = tmp_path / "style.png"
    Image.new("RGB", (40, 40), "blue").save(ref)
    plan = SlidePlan(slide_number=1, purpose="hero", headline="Meet the collection", visual_brief="Editorial scene",
        slide_id="campaign:en:1", selection_rationale="Canonical product and selected lighting reference",
        verified_claim_ids=["claim-1"], evidence_references=[SlideEvidenceReference(claim_id="claim-1",
            source_ids=["source-1"], evidence_sha256="a" * 64, claim_text="Meet the collection")],
        product_asset=SlideAssetReference(asset_id="product-asset", role="product_master_approved" if approved else "product",
            path=str(product), sha256=hashlib.sha256(product.read_bytes()).hexdigest()),
        reference_asset_ids=["ref-1"], reference_assets=[SlideAssetReference(asset_id="ref-1", role="visual_reference",
            path=str(ref), sha256=hashlib.sha256(ref.read_bytes()).hexdigest())])

    from app.services.creative.pipeline import canonical_slide_claim_bindings
    return plan.model_copy(update={"claim_bindings": canonical_slide_claim_bindings(plan)})


def _repair_input(plan):
    return SlideCreativeInput(source_image_path=Path(plan.product_asset.path), template_id="feature_showcase",
        platform_key="instagram_portrait", headline=plan.headline, body=plan.body, cta=plan.cta,
        eyebrow=plan.eyebrow, badge_text=plan.badge_text, intro=plan.intro,
        features=[Feature(**f.model_dump()) for f in plan.features],
        callout_label=plan.callout_label, callout_value=plan.callout_value,
        bottom_features=list(plan.bottom_features), trust_badges=list(plan.trust_badges),
        disclaimer=plan.disclaimer, slide_plan=plan)


@pytest.mark.parametrize("field", ["verified_claim_ids", "evidence_references", "reference_asset_ids", "reference_assets", "product_asset"])
def test_repair_typed_slide_provenance_round_trip(tmp_path, field):
    from app.schemas.ai import SlidePlan
    plan = _repair_plan(tmp_path)
    restored = SlidePlan.model_validate_json(plan.model_dump_json())
    assert getattr(restored, field) == getattr(plan, field)
    assert restored == plan


def test_repair_legacy_slide_plan_and_unknown_provenance():
    from app.schemas.ai import SlidePlan
    from pydantic import ValidationError
    payload = dict(slide_number=1, purpose="hero", headline="Hello", visual_brief="Scene")
    assert SlidePlan(**payload).verified_claim_ids == []
    for unknown in ("claim_ids", "evidence_refs", "reference_ids"):
        with pytest.raises(ValidationError):
            SlidePlan(**payload, **{unknown: ["must-not-disappear"]})


@pytest.mark.parametrize("mutation", ["claim", "reference", "source", "copy", "bytes", "role"])
def test_repair_renderer_rejects_contract_substitution(tmp_path, mutation):
    from app.services.creative.pipeline import validate_render_slide_contract
    plan = _repair_plan(tmp_path)
    data = _repair_input(plan)
    if mutation == "claim": plan.verified_claim_ids = ["substituted"]
    if mutation == "reference": plan.reference_asset_ids = ["substituted"]
    if mutation == "source": data.source_image_path = tmp_path / "substituted.png"
    if mutation == "copy": data.headline = "substituted"
    if mutation == "bytes": Path(plan.reference_assets[0].path).write_bytes(b"changed")
    if mutation == "role": plan.reference_assets[0].role = "product_master_approved"
    with pytest.raises(ValueError): validate_render_slide_contract(data)


def test_repair_locked_composite_renderer_acceptance_and_untrusted_escalation(tmp_path):
    from app.services.creative.pipeline import build_trusted_product_composite, TrustedProductComposite
    plan = _repair_plan(tmp_path, approved=True)
    data = _repair_input(plan)
    background = Image.new("RGB", (1080, 1350), "navy")
    from test_build6r_product_master_selection import source_asset, approved_master
    source, master = source_asset(), approved_master()
    source_path = tmp_path / "original.png"
    Image.new("RGB", (40, 40), "white").save(source_path)
    source.absolute_path = str(source_path)
    source.sha256 = hashlib.sha256(source_path.read_bytes()).hexdigest()
    master.id = plan.product_asset.asset_id
    master.absolute_path = plan.product_asset.path
    master.sha256 = plan.product_asset.sha256
    master.ai_metadata["source_sha256"] = source.sha256
    kwargs = dict(background=background, master_path=data.source_image_path,
        expected_sha256=plan.product_asset.sha256, canvas_size=(1080, 1350),
        approved_asset=master, source_lookup=lambda key: source if key == source.id else None)
    capability = build_trusted_product_composite(**kwargs)
    # A matching filename, path, SHA and approved-role label without real owner provenance cannot mint trust.
    master.ai_metadata["human_review"]["status"] = "PENDING"
    with pytest.raises(ValueError, match="Canonical approved product provenance"):
        build_trusted_product_composite(**kwargs)
    master.ai_metadata["human_review"]["status"] = "APPROVED"
    data.locked_product_composite = capability
    renderer = _RepairRenderer()
    result = _repair_finish(render_slide(data, output_path=tmp_path / "render.png", renderer=renderer))
    assert result.qa.passed
    assert "Meet the collection" in renderer.html
    assert hashlib.sha256(data.source_image_path.read_bytes()).hexdigest() == plan.product_asset.sha256
    for untrusted in (background, TrustedProductComposite(background, {}, plan.product_asset.sha256, "x", "fake-id", object())):
        data.locked_product_composite = untrusted
        with pytest.raises(ValueError, match="Untrusted"):
            _repair_finish(render_slide(data, output_path=tmp_path / "bad.png", renderer=renderer))
    data.locked_product_composite = capability
    capability.image.putpixel((0, 0), (255, 0, 0, 255))
    with pytest.raises(ValueError, match="identity changed"):
        _repair_finish(render_slide(data, output_path=tmp_path / "bad.png", renderer=renderer))
    data.locked_product_composite = None
    data.recreated_image = background
    with pytest.raises(RuntimeError, match="prohibited"):
        _repair_finish(render_slide(data, output_path=tmp_path / "bad.png", renderer=renderer))


def test_repair_legacy_render_remains_valid_without_approval_attestation(tmp_path):
    plan = _repair_plan(tmp_path)
    data = _repair_input(plan)
    data.slide_plan = None
    result = _repair_finish(render_slide(data, output_path=tmp_path / "legacy.png", renderer=_RepairRenderer()))
    assert result.qa.passed


@pytest.fixture()
def repair_case(temp_db, tmp_path, monkeypatch):
    import json
    from types import SimpleNamespace
    from test_build6r_v345_claim_evidence_foundation import _seed, _candidate, _verification
    from app.models import Asset, BrandAsset, Campaign, PlatformCampaignVariant
    from app.services.claim_evidence import create_claim_candidate, verify_claim_evidence, promote_verified_claim
    from app.services import orchestrator as orch, qa_engine as qa
    from app.services.creative.pipeline import persist_render_context
    db = temp_db.SessionLocal()
    seed = _seed(db)
    claim = create_claim_candidate(db, _candidate(seed, claim_text="150 mL of essence"))
    verify_claim_evidence(db, claim.id, _verification(seed))
    promote_verified_claim(db, claim.id)
    raw = _repair_plan(tmp_path)
    asset = Asset(brand_id=seed["brand"].id, product_id=seed["product"].id, image_role="product",
        absolute_path=raw.product_asset.path, relative_path="product.png", filename="product.png", extension=".png",
        sha256=raw.product_asset.sha256, is_active=True)
    ref = BrandAsset(brand_id=seed["brand"].id, kind="visual_reference", file_path=raw.reference_assets[0].path)
    campaign = Campaign(brand_id=seed["brand"].id, product_id=seed["product"].id, display_id="REPAIR-1",
        status="REVIEW", languages=["en"], language="en", target_platforms=["instagram"], target_slide_count=1)
    db.add_all([asset, ref, campaign]); db.commit()
    from app.schemas.ai import SlidePlan
    plan = SlidePlan(slide_number=1, purpose="hero", headline="150 mL of essence", visual_brief="Editorial scene",
        verified_claim_ids=[claim.id], selection_rationale="Selected canonical size evidence")
    plan = orch._bind_slide_provenance(db, campaign, [plan], language="en", cta="")[0]
    # Exercise the actual persisted plan serialization boundary.
    creative = {"languages": {"en": {"carousel_plan": {"slides": [json.loads(plan.model_dump_json())]}}}}
    copy = {"languages": {"en": {"headline": plan.headline, "body": "", "cta": ""}}}
    monkeypatch.setattr(qa, "_load_stage_json", lambda _db, _id, kind: creative if kind == "creative" else copy)
    output = tmp_path / "current.png"
    result = _repair_finish(render_slide(_repair_input(plan), output_path=output, renderer=_RepairRenderer()))
    persist_render_context(slide_output_path=output, creative_direction={}, visual_base=None, visual_base_kind="none")
    report = tmp_path / "technical.json"
    report.write_text(json.dumps(result.qa.to_dict()), encoding="utf-8")
    variant = PlatformCampaignVariant(campaign_id=campaign.id, target_platform="instagram", language="en",
        content_type="carousel", render_format_key="instagram_portrait", status="RENDERED",
        slide_asset_paths=[str(output)], qa_report_paths=[str(report)], creative_direction={})
    db.add(variant); db.commit()
    yield SimpleNamespace(db=db, seed=seed, claim=claim, campaign=campaign, plan=plan, variant=variant,
        creative=creative, copy=copy, output=output, root=tmp_path, qa=qa, orch=orch, renderer=_RepairRenderer())
    db.close()


def _repair_run_qa(case, monkeypatch, *, passing=True):
    from datetime import datetime, timezone
    from app.schemas.qa import CreativeCritiqueResult
    from app.schemas.creative_director import PlatformAdaptation
    from app.data.platform_creative_specs import resolve_platform_creative_spec
    seen = []
    async def fake_critic(*args, **kwargs):
        seen.append(kwargs)
        return CreativeCritiqueResult(overall_quality=95 if passing else 10, product_fidelity=95,
            hard_fails=[] if passing else ["weak creative"])
    monkeypatch.setattr(case.qa, "run_creative_qa", fake_critic)
    config = case.orch.AutopilotConfig(output_root=case.root, qa_max_retries=0, campaign_model="fake", research_model="fake",
        trend_ttl_hours=1, category_ttl_hours=1, too_similar_threshold=0.9, acceptable_threshold=0.7)
    _repair_finish(case.qa._qa_one_static_variant(case.db, variant=case.variant, campaign=case.campaign,
        brand=case.seed["brand"], category_slug="general", spec=resolve_platform_creative_spec("instagram", "carousel"),
        master_concept=None, adaptation=PlatformAdaptation(platform="instagram", adaptation_strategy="Editorial", narrative_shape="", tone_adjustment="", content_type="carousel"),
        config=config, renderer=case.renderer, image_provider=None, ai_provider=None, quality_image_model="fake",
        quality_tier="standard", copy_data_raw=case.copy, creative_data_raw=case.creative,
        discovery_products=[], is_discovery=False, brand_colors=[], logo_path=None, brand_style=None,
        sibling_headlines={}, sibling_bodies={}, sibling_ctas={}, now=datetime.now(timezone.utc), product=case.seed["product"]))
    return seen


def test_repair_current_creative_qa_pass_allows_approval_and_preserves_provenance(repair_case, monkeypatch):
    import json
    from app.api.campaigns import approve_campaign
    c = repair_case
    seen = _repair_run_qa(c, monkeypatch)
    assert c.variant.qa_status == "PASS", c.variant.qa_hard_fails
    c.qa.assert_campaign_creative_qa_current(c.db, c.campaign)
    assert c.plan.verified_claim_ids == [c.claim.id]
    assert c.plan.evidence_references[0].source_ids == [c.seed["source"].id]
    assert c.plan.reference_asset_ids == [c.plan.reference_assets[0].asset_id]
    assert c.plan.product_asset.asset_id in seen[0]["context"]
    assert c.claim.id in seen[0]["context"]
    assert json.dumps(c.plan.model_dump(), sort_keys=True) in seen[0]["context"]
    assert approve_campaign(c.campaign.id, c.db)["status"] == "APPROVED"


@pytest.mark.parametrize("state", ["not_run", "failed", "technical_only", "missing_slide", "missing_report"])
def test_repair_approval_rejects_incomplete_creative_qa(repair_case, monkeypatch, state):
    from fastapi import HTTPException
    from app.api.campaigns import approve_campaign
    c = repair_case
    if state == "failed": _repair_run_qa(c, monkeypatch, passing=False)
    if state in ("technical_only", "missing_slide", "missing_report"):
        _repair_run_qa(c, monkeypatch)
        if state == "technical_only": c.variant.qa_scores = {"technical": {"passed": True}}
        if state == "missing_slide": c.variant.slide_asset_paths = []
        if state == "missing_report": c.variant.qa_report_paths = []
    with pytest.raises(HTTPException) as exc:
        approve_campaign(c.campaign.id, c.db)
    assert exc.value.status_code == 409
    assert c.campaign.status == "REVIEW"


@pytest.mark.parametrize("change", ["output", "copy", "plan", "evidence", "reference", "product", "direction", "campaign", "evidence_file", "required_language"])
def test_repair_stale_creative_qa_rejects_approval(repair_case, monkeypatch, change):
    from fastapi import HTTPException
    from app.api.campaigns import approve_campaign
    c = repair_case
    _repair_run_qa(c, monkeypatch)
    assert c.variant.qa_status == "PASS"
    if change == "output": c.output.write_bytes(b"changed")
    if change == "copy": c.copy["languages"]["en"]["headline"] = "Changed"
    if change == "plan": c.creative["languages"]["en"]["carousel_plan"]["slides"][0]["headline"] = "Changed"
    if change == "evidence": c.claim.status = "rejected"
    if change == "reference": Path(c.plan.reference_assets[0].path).write_bytes(b"changed")
    if change == "product": Path(c.plan.product_asset.path).write_bytes(b"changed")
    if change == "direction": c.variant.creative_direction = {"mood": "Changed"}
    if change == "campaign": c.campaign.cta = "Changed"
    if change == "evidence_file": Path(c.variant.qa_evidence_paths[-1]).write_text("{}")
    if change == "required_language": c.campaign.languages = ["en", "pt-BR"]
    with pytest.raises(HTTPException): approve_campaign(c.campaign.id, c.db)


def test_repair_canonical_claim_substitution_and_reference_substitution_rejected(repair_case):
    c = repair_case
    from app.schemas.ai import SlideAssetReference
    original = c.plan.evidence_references[0].evidence_sha256
    c.plan.evidence_references[0].evidence_sha256 = "f" * 64
    with pytest.raises(ValueError, match="Claim evidence"):
        c.orch.validate_slide_provenance(c.db, c.campaign, c.plan)
    c.plan.evidence_references[0].evidence_sha256 = original
    c.plan.reference_assets[0].asset_id = "another-canonical-id"
    c.plan.reference_asset_ids = ["another-canonical-id"]
    with pytest.raises(ValueError, match="Reference asset"):
        c.orch.validate_slide_provenance(c.db, c.campaign, c.plan)


def test_repair_unbound_factual_copy_rejected(repair_case):
    c = repair_case
    c.plan.verified_claim_ids = []
    c.plan.evidence_references = []
    with pytest.raises(ValueError, match="selected canonical claim IDs"):
        c.orch.validate_slide_provenance(c.db, c.campaign, c.plan)


# V4: bindings must authorize the actual assertion, not merely contain real IDs.
def _v4_add_claim(case, text="Official packaging has a blue label"):
    from test_build6r_v345_claim_evidence_foundation import _candidate, _verification
    from app.services.claim_evidence import create_claim_candidate, verify_claim_evidence, promote_verified_claim
    row = create_claim_candidate(case.db, _candidate(case.seed, claim_text=text))
    verify_claim_evidence(case.db, row.id, _verification(case.seed))
    promote_verified_claim(case.db, row.id)
    return row


def _v4_production_hero_plan(headline, body="", cta=""):
    import ast
    import inspect
    from types import SimpleNamespace
    from app.schemas.ai import CarouselPlan, SlidePlan
    from app.services import orchestrator
    tree = ast.parse(inspect.getsource(orchestrator.run_copy_stage))
    hero = next(node for node in ast.walk(tree) if isinstance(node, ast.If)
                and ast.unparse(node.test) == "config.hero_only")
    assignment = next(node for node in hero.body if isinstance(node, ast.Assign)
                      and any(isinstance(target, ast.Name) and target.id == "carousel_plan" for target in node.targets))
    # Execute the production hero construction expression, with zero model calls.
    plan = eval(compile(ast.Expression(assignment.value), "production-hero-plan", "eval"), {
        "CarouselPlan": CarouselPlan, "SlidePlan": SlidePlan,
        "campaign_copy": SimpleNamespace(headline=headline, supporting_copy=body, cta=cta, alt_text="Product"),
        "creative_brief": SimpleNamespace(design_concept="Editorial"),
    })
    binding = next(node for node in ast.walk(tree) if isinstance(node, ast.Call)
                   and isinstance(node.func, ast.Name) and node.func.id == "_bind_slide_provenance")
    assert any(kw.arg == "select_claims_for_hero" and ast.unparse(kw.value) == "config.hero_only" for kw in binding.keywords)
    return plan.slides


@pytest.mark.parametrize("mismatch", ["wrong_claim_id", "wrong_reference", "missing_reference", "changed_assertion", "generic_valid_evidence"])
def test_v4_wrong_evidence_cannot_approve_visible_assertion(repair_case, monkeypatch, mismatch):
    from app.schemas.ai import SlideClaimBinding
    from app.api.campaigns import approve_campaign
    from fastapi import HTTPException
    c = repair_case
    other = _v4_add_claim(c)
    wrong = c.plan.model_copy(deep=True)
    if mismatch == "wrong_claim_id": wrong.verified_claim_ids = [other.id]
    if mismatch == "wrong_reference": wrong.evidence_references = [c.orch._claim_reference(c.db, other.id, c.seed["product"].id)]
    if mismatch == "missing_reference": wrong.evidence_references = []
    if mismatch == "changed_assertion": wrong.headline = "300 mL of essence"
    if mismatch == "generic_valid_evidence":
        wrong.verified_claim_ids = [other.id]
        wrong.evidence_references = [c.orch._claim_reference(c.db, other.id, c.seed["product"].id)]
        wrong.claim_bindings = [SlideClaimBinding(field_path="headline", claim_id=other.id, assertion_text=wrong.headline)]
    with pytest.raises(ValueError): c.orch.validate_slide_provenance(c.db, c.campaign, wrong)
    # Neither pre-existing successful output nor a passing critic may override
    # the actual canonical claim-to-evidence relationship at QA/approval.
    c.creative["languages"]["en"]["carousel_plan"]["slides"] = [wrong.model_dump()]
    seen = _repair_run_qa(c, monkeypatch)
    assert not seen  # invalid contracts rejected before any critic invocation
    assert c.variant.qa_status == "NEEDS_REVIEW"
    with pytest.raises(HTTPException) as exc: approve_campaign(c.campaign.id, c.db)
    assert exc.value.status_code == 409
    assert c.campaign.status == "REVIEW"


def test_v4_observed_150ml_vs_blue_label_rejected_at_planning_and_render(repair_case):
    from app.services.creative.pipeline import validate_render_slide_contract
    c = repair_case
    other = _v4_add_claim(c)
    candidate = c.plan.model_copy(update={"verified_claim_ids": [other.id], "evidence_references": [], "claim_bindings": []})
    with pytest.raises(ValueError, match="exact selected canonical claim support"):
        c.orch._bind_slide_provenance(c.db, c.campaign, [candidate], language="en", cta="")
    forged = candidate.model_copy(update={"evidence_references": [c.orch._claim_reference(c.db, other.id, c.seed["product"].id)]})
    with pytest.raises(ValueError, match="exact selected canonical claim support"):
        validate_render_slide_contract(_repair_input(forged))


def test_v4_correct_hero_preserves_matching_claim_and_evidence_deterministically(repair_case):
    from app.schemas.ai import SlidePlan
    c = repair_case
    unrelated = _v4_add_claim(c)
    raw = _v4_production_hero_plan("150 mL of essence")
    first = c.orch._bind_slide_provenance(c.db, c.campaign, raw, language="en", cta="", select_claims_for_hero=True)[0]
    second = c.orch._bind_slide_provenance(c.db, c.campaign, raw, language="en", cta="", select_claims_for_hero=True)[0]
    assert first == second
    assert first.verified_claim_ids == [c.claim.id]
    assert unrelated.id not in first.verified_claim_ids
    assert first.evidence_references[0].claim_text == first.headline
    assert first.evidence_references[0].source_ids == c.claim.source_ids
    assert first.claim_bindings[0].claim_id == c.claim.id
    assert first.claim_bindings[0].assertion_text == first.headline
    assert SlidePlan.model_validate_json(first.model_dump_json()) == first
    # With two claims actually used, select each matching ID, in visible-field order.
    two = c.orch._bind_slide_provenance(c.db, c.campaign,
        _v4_production_hero_plan(c.claim.claim_text, unrelated.claim_text),
        language="en", cta="", select_claims_for_hero=True)[0]
    assert two.verified_claim_ids == [c.claim.id, unrelated.id]
    assert [(b.field_path, b.claim_id) for b in two.claim_bindings] == [("headline", c.claim.id), ("body", unrelated.id)]


@pytest.mark.parametrize("reason", ["unsupported_quantity", "expired", "rejected", "unrelated_only"])
def test_v4_hero_without_eligible_support_never_fabricates_linkage(repair_case, reason):
    from datetime import datetime, timedelta, timezone
    from app.models import ProductClaimEvidence
    c = repair_case
    _v4_add_claim(c)
    if reason in ("rejected", "unrelated_only"): c.claim.status = "rejected"
    if reason == "expired": c.claim.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
    c.db.commit()
    before = {r.id for r in c.db.query(ProductClaimEvidence).all()}
    raw = _v4_production_hero_plan("300 mL of essence" if reason == "unsupported_quantity" else "150 mL of essence")
    with pytest.raises(ValueError, match="no eligible exact canonical claim"):
        c.orch._bind_slide_provenance(c.db, c.campaign, raw, language="en", cta="", select_claims_for_hero=True)
    assert {r.id for r in c.db.query(ProductClaimEvidence).all()} == before
    assert not raw[0].verified_claim_ids and not raw[0].evidence_references


def test_v4_renderer_cannot_invent_fact_outside_authorized_plan(repair_case):
    c = repair_case
    data = _repair_input(c.plan)
    data.headline = "300 mL of essence"
    with pytest.raises(ValueError, match="copy substitution"):
        _repair_finish(render_slide(data, output_path=c.root / "unauthorized.png", renderer=_RepairRenderer()))
    assert not (c.root / "unauthorized.png").exists()


def test_v4_qa_binding_disagreement_cannot_approve(repair_case, monkeypatch):
    import copy
    from app.api.campaigns import approve_campaign
    from fastapi import HTTPException
    c = repair_case
    _repair_run_qa(c, monkeypatch)
    assert c.variant.qa_status == "PASS"
    scores = copy.deepcopy(c.variant.qa_scores)
    scores["slide_attestations"][0]["contract_sha256"] = "f" * 64
    c.variant.qa_scores = scores
    with pytest.raises(HTTPException) as exc: approve_campaign(c.campaign.id, c.db)
    assert exc.value.status_code == 409


def test_v4_correct_claim_correct_evidence_can_still_reach_approval(repair_case, monkeypatch):
    from app.api.campaigns import approve_campaign
    c = repair_case
    _repair_run_qa(c, monkeypatch)
    assert c.variant.qa_status == "PASS"
    assert approve_campaign(c.campaign.id, c.db)["status"] == "APPROVED"


@pytest.mark.parametrize("field", ["body", "badge_text", "intro", "callout_value", "bottom_features", "trust_badges", "features"])
def test_v4_unknown_factual_copy_cannot_hide_in_optional_fields(repair_case, field):
    from app.schemas.ai import SlideFeature
    c = repair_case
    plan = c.plan.model_copy(deep=True)
    value = "300 mL of essence"
    if field in ("bottom_features", "trust_badges"): value = [value]
    if field == "features": value = [SlideFeature(icon="", title=value, subtitle="")]
    setattr(plan, field, value)
    with pytest.raises(ValueError, match="exact selected canonical claim support"):
        c.orch.validate_slide_provenance(c.db, c.campaign, plan)



def test_v4_production_hero_contract_reaches_render_qa_and_approval(repair_case, monkeypatch):
    import json
    from app.api.campaigns import approve_campaign
    from app.services.creative.pipeline import persist_render_context, build_render_context_path
    c = repair_case
    _v4_add_claim(c)  # unrelated valid evidence must not replace the actual claim
    c.plan = c.orch._bind_slide_provenance(c.db, c.campaign,
        _v4_production_hero_plan("150 mL of essence"), language="en", cta="", select_claims_for_hero=True)[0]
    c.creative["languages"]["en"]["carousel_plan"]["slides"] = [c.plan.model_dump()]
    renderer = _RepairRenderer()
    rendered = _repair_finish(render_slide(_repair_input(c.plan), output_path=c.output, renderer=renderer))
    assert "150 mL of essence" in renderer.html
    persist_render_context(slide_output_path=c.output, creative_direction={}, visual_base=None, visual_base_kind="none")
    Path(c.variant.qa_report_paths[0]).write_text(json.dumps(rendered.qa.to_dict()), encoding="utf-8")
    context = json.loads(build_render_context_path(c.output).read_text(encoding="utf-8"))
    assert context["slide_contract"]["claim_bindings"] == [b.model_dump() for b in c.plan.claim_bindings]
    seen = _repair_run_qa(c, monkeypatch)
    assert c.variant.qa_status == "PASS"
    assert c.claim.id in seen[0]["context"]
    assert approve_campaign(c.campaign.id, c.db)["status"] == "APPROVED"


# V5: all actual template text slots, including the brand-style footer.
def _v5_bind_brand_footer(case, lines, *, plan=None):
    case.seed["brand"].disclaimers = list(lines)
    case.db.commit()
    raw = (plan or case.plan).model_copy(update={"disclaimer": "", "claim_bindings": []})
    return case.orch._bind_slide_provenance(case.db, case.campaign, [raw], language="en", cta="")[0]


def _v5_render_current(case, plan):
    import json
    from app.services.creative.pipeline import persist_render_context
    case.plan = plan
    case.creative["languages"]["en"]["carousel_plan"]["slides"] = [plan.model_dump()]
    case.copy["languages"]["en"].update(headline=plan.headline, body=plan.body, cta=plan.cta)
    renderer = _RepairRenderer()
    result = _repair_finish(render_slide(_repair_input(plan), output_path=case.output, renderer=renderer))
    persist_render_context(slide_output_path=case.output, creative_direction={}, visual_base=None, visual_base_kind="none")
    Path(case.variant.qa_report_paths[0]).write_text(json.dumps(result.qa.to_dict()), encoding="utf-8")
    return renderer


def _v5_assert_approval_rejected(case):
    from app.api.campaigns import approve_campaign
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc: approve_campaign(case.campaign.id, case.db)
    assert exc.value.status_code == 409
    assert case.campaign.status == "REVIEW"


def test_v5_renderer_disclaimer_cannot_bypass_authorized_text(repair_case):
    c = repair_case
    data = _repair_input(c.plan)
    data.disclaimer = "300 mL of essence"
    with pytest.raises(ValueError, match="disclaimer"):
        _repair_finish(render_slide(data, output_path=c.root / "unbound-footer.png", renderer=_RepairRenderer()))
    assert not (c.root / "unbound-footer.png").exists()


def test_v5_real_brand_disclaimer_300ml_rejected_by_planning_qa_and_approval(repair_case, monkeypatch):
    from app.services.creative.brand_style import resolve_brand_style
    c = repair_case
    c.seed["brand"].disclaimers = ["300 mL of essence"]
    c.db.commit()
    style = resolve_brand_style(c.db, c.seed["brand"])
    assert style.disclaimer_text == "300 mL of essence"
    # Exact former bypass route; the caller may not inject live brand text into
    # a renderer whose authorized plan has a different complete text set.
    data = _repair_input(c.plan); data.disclaimer = style.disclaimer_text
    with pytest.raises(ValueError, match="disclaimer"):
        _repair_finish(render_slide(data, output_path=c.output, renderer=_RepairRenderer()))
    with pytest.raises(ValueError, match="canonical claim support"):
        c.orch._bind_slide_provenance(c.db, c.campaign, [c.plan], language="en", cta="")
    seen = _repair_run_qa(c, monkeypatch)
    assert not seen and c.variant.qa_status == "NEEDS_REVIEW"
    _v5_assert_approval_rejected(c)


def test_v5_correct_body_with_wrong_factual_footnote_rejected(repair_case):
    c = repair_case
    raw = c.plan.model_copy(update={"headline": "Meet the collection", "body": "150 mL of essence", "claim_bindings": []})
    with pytest.raises(ValueError, match="canonical claim support"):
        _v5_bind_brand_footer(c, ["300 mL of essence"], plan=raw)


@pytest.mark.parametrize("field", ["eyebrow", "headline", "body", "cta", "badge_text", "intro", "callout_label", "callout_value", "bottom_features", "trust_badges", "features_title", "features_subtitle", "features_icon"])
def test_v5_product_assertions_cannot_hide_in_any_text_role(repair_case, field):
    from app.schemas.ai import SlideFeature
    c = repair_case
    plan = c.plan.model_copy(deep=True)
    bad = "300 mL of essence"
    if field.startswith("features_"):
        plan.features = [SlideFeature(icon="", title="Details", subtitle="")]
        setattr(plan.features[0], field.removeprefix("features_"), "300%" if field == "features_icon" else bad)
    else:
        setattr(plan, field, [bad] if field in ("bottom_features", "trust_badges") else bad)
    with pytest.raises(ValueError, match="canonical claim support"):
        c.orch.validate_slide_provenance(c.db, c.campaign, plan)


@pytest.mark.parametrize("footer", ["150 mL of essence", "Results may vary.", "150 mL of essence · Results may vary."])
def test_v5_authorized_or_nonfactual_disclaimer_reaches_qa_and_approval(repair_case, monkeypatch, footer):
    import json
    from app.api.campaigns import approve_campaign
    from app.services.creative.pipeline import build_render_context_path
    c = repair_case
    plan = _v5_bind_brand_footer(c, footer.split(" · "))
    renderer = _v5_render_current(c, plan)
    assert footer in renderer.html
    context = json.loads(build_render_context_path(c.output).read_text(encoding="utf-8"))
    assert context["rendered_text_fields"]["disclaimer"] == footer
    assert context["complete_text_contract"]["fields"]["disclaimer"] == footer
    if "150 mL" in footer:
        assert any(b.field_path.startswith("disclaimer") and b.claim_id == c.claim.id for b in plan.claim_bindings)
    else:
        assert not any(b.field_path.startswith("disclaimer") for b in plan.claim_bindings)
    seen = _repair_run_qa(c, monkeypatch)
    assert c.variant.qa_status == "PASS", c.variant.qa_hard_fails
    assert json.dumps(footer)[1:-1] in seen[0]["context"]
    assert approve_campaign(c.campaign.id, c.db)["status"] == "APPROVED"


def test_v5_pure_nonfactual_creative_and_legal_copy_need_no_product_claim_ids(repair_case, monkeypatch):
    from app.api.campaigns import approve_campaign
    c = repair_case
    raw = c.plan.model_copy(update={"headline": "Meet the collection", "body": "Learn more", "cta": "Shop now",
        "verified_claim_ids": [], "evidence_references": [], "claim_bindings": []})
    plan = _v5_bind_brand_footer(c, ["For informational purposes only."], plan=raw)
    assert not plan.verified_claim_ids and not plan.evidence_references and not plan.claim_bindings
    _v5_render_current(c, plan); _repair_run_qa(c, monkeypatch)
    assert c.variant.qa_status == "PASS", c.variant.qa_hard_fails
    assert approve_campaign(c.campaign.id, c.db)["status"] == "APPROVED"


def test_v5_multisurface_valid_headline_body_disclaimer_accepted(repair_case, monkeypatch):
    from app.api.campaigns import approve_campaign
    c = repair_case
    other = _v4_add_claim(c)
    raw = c.plan.model_copy(update={"body": other.claim_text, "verified_claim_ids": [c.claim.id, other.id],
        "evidence_references": [], "claim_bindings": []})
    plan = _v5_bind_brand_footer(c, [c.claim.claim_text], plan=raw)
    assert {b.field_path for b in plan.claim_bindings} == {"headline", "body", "disclaimer"}
    _v5_render_current(c, plan); _repair_run_qa(c, monkeypatch)
    assert c.variant.qa_status == "PASS", c.variant.qa_hard_fails
    assert approve_campaign(c.campaign.id, c.db)["status"] == "APPROVED"


@pytest.mark.parametrize("mutation", ["missing_footer_binding", "wrong_claim_for_footer", "stale_footer_after_claim_revision"])
def test_v5_missing_wrong_or_stale_footer_authority_rejected(repair_case, monkeypatch, mutation):
    from app.schemas.ai import SlideClaimBinding
    c = repair_case
    correct = _v5_bind_brand_footer(c, [c.claim.claim_text])
    wrong = correct.model_copy(deep=True)
    if mutation == "missing_footer_binding":
        wrong.claim_bindings = [b for b in wrong.claim_bindings if b.field_path != "disclaimer"]
    else:
        other = _v4_add_claim(c)
        if mutation == "wrong_claim_for_footer":
            wrong.verified_claim_ids = [c.claim.id, other.id]
            wrong.evidence_references.append(c.orch._claim_reference(c.db, other.id, c.seed["product"].id))
            wrong.claim_bindings = [SlideClaimBinding(field_path=b.field_path, claim_id=other.id if b.field_path == "disclaimer" else b.claim_id,
                assertion_text=b.assertion_text) for b in wrong.claim_bindings]
        else:
            wrong.headline = other.claim_text
            wrong.verified_claim_ids = [other.id]
            wrong.evidence_references = [c.orch._claim_reference(c.db, other.id, c.seed["product"].id)]
            wrong.claim_bindings = [SlideClaimBinding(field_path="headline", claim_id=other.id, assertion_text=other.claim_text)]
    with pytest.raises(ValueError): c.orch.validate_slide_provenance(c.db, c.campaign, wrong)
    c.creative["languages"]["en"]["carousel_plan"]["slides"] = [wrong.model_dump()]
    seen = _repair_run_qa(c, monkeypatch)
    assert not seen and c.variant.qa_status == "NEEDS_REVIEW"
    _v5_assert_approval_rejected(c)


def test_v5_qa_cannot_ignore_renderer_footer_text_set_disagreement(repair_case, monkeypatch):
    import json
    from app.services.creative.pipeline import build_render_context_path
    c = repair_case
    plan = _v5_bind_brand_footer(c, [c.claim.claim_text]); _v5_render_current(c, plan)
    path = build_render_context_path(c.output); context = json.loads(path.read_text(encoding="utf-8"))
    context["rendered_text_fields"]["disclaimer"] = "300 mL of essence"
    path.write_text(json.dumps(context), encoding="utf-8")
    seen = _repair_run_qa(c, monkeypatch)
    assert not seen and c.variant.qa_status == "NEEDS_REVIEW"
    _v5_assert_approval_rejected(c)


@pytest.mark.parametrize("field", ["disclaimer", "badge_text", "callout_value", "body"])
def test_v5_factual_text_changes_after_qa_invalidate_approval(repair_case, monkeypatch, field):
    c = repair_case
    plan = _v5_bind_brand_footer(c, [c.claim.claim_text]); _v5_render_current(c, plan)
    _repair_run_qa(c, monkeypatch); assert c.variant.qa_status == "PASS"
    if field == "disclaimer":
        c.seed["brand"].disclaimers = ["300 mL of essence"]; c.db.commit()
    else:
        c.creative["languages"]["en"]["carousel_plan"]["slides"][0][field] = "300 mL of essence"
    _v5_assert_approval_rejected(c)


def test_v5_matching_new_canonical_footer_still_requires_fresh_render_and_qa(repair_case, monkeypatch):
    c = repair_case
    plan = _v5_bind_brand_footer(c, [c.claim.claim_text]); _v5_render_current(c, plan)
    _repair_run_qa(c, monkeypatch); assert c.variant.qa_status == "PASS"
    other = _v4_add_claim(c)
    raw = c.plan.model_copy(update={"verified_claim_ids": [c.claim.id, other.id], "evidence_references": [], "claim_bindings": [], "disclaimer": ""})
    revised = _v5_bind_brand_footer(c, [other.claim_text], plan=raw)
    c.creative["languages"]["en"]["carousel_plan"]["slides"] = [revised.model_dump()]
    _v5_assert_approval_rejected(c)


@pytest.mark.parametrize("control", ["font_family", "secondary_font_family", "accent_color", "direction_palette"])
def test_v5_style_controls_cannot_inject_unbound_generated_text(repair_case, control):
    c = repair_case
    data = _repair_input(c.plan)
    bad = "Arial;}.headline:after{content:'300 mL of essence';}"
    setattr(data, control, [bad] if control == "direction_palette" else bad)
    with pytest.raises(ValueError, match="CSS controls"):
        _repair_finish(render_slide(data, output_path=c.root / "style-injection.png", renderer=_RepairRenderer()))
    assert not (c.root / "style-injection.png").exists()


def test_v5_future_unexamined_text_slot_fails_closed(repair_case, monkeypatch):
    from dataclasses import make_dataclass
    from app.services.creative import pipeline
    c = repair_case
    monkeypatch.setattr(pipeline, "TemplateContext", make_dataclass("UnknownContext", [("unexamined_footnote", str)]))
    with pytest.raises(ValueError, match="Unexamined template context"):
        _repair_finish(render_slide(_repair_input(c.plan), output_path=c.root / "unknown-slot.png", renderer=_RepairRenderer()))


def test_v5_structural_counter_is_not_an_arbitrary_text_slot(repair_case):
    c = repair_case
    data = _repair_input(c.plan); data.slide_number = "300 mL of essence"; data.total_slides = 2
    with pytest.raises(ValueError, match="counters must be integers"):
        _repair_finish(render_slide(data, output_path=c.root / "counter-injection.png", renderer=_RepairRenderer()))
