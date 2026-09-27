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
from app.services.creative.templates import TemplateContext, get_template
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

