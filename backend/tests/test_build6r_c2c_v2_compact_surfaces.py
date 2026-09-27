"""Build 6R-C2C-V2 compact surface regression."""

from app.services.creative.templates import (
    TEMPLATE_REGISTRY_VERSION,
    Feature,
    TemplateContext,
    get_template,
)


def _html(
    layout,
    *,
    features=None,
):
    ctx = TemplateContext(
        width=1080,
        height=1350,
        composited_image_data_uri=(
            "data:image/png;base64,AA=="
        ),
        eyebrow="HANNA",
        headline="Headline",
        intro="Supporting sentence.",
        features=features or [],
        accent_color="#E0477B",
        font_family=(
            "'Segoe UI', Arial, sans-serif"
        ),
        secondary_font_family=(
            "'Georgia', serif"
        ),
        direction_palette=[
            "#F3E8E4",
            "#D9C4BC",
        ],
        layout_variant=layout,
        slide_number=1,
        total_slides=6,
    )

    return get_template(
        "feature_showcase"
    ).build_html(
        ctx
    )


def test_visual_recipe_version_is_1_2_0():
    assert (
        TEMPLATE_REGISTRY_VERSION
        == "1.2.0"
    )


def test_text_surface_uses_natural_content_height():
    html = _html(
        "utility_demo",
        features=[
            Feature(
                icon="1",
                title="Feature",
                subtitle="Detail",
            )
        ],
    )

    assert (
        "height: fit-content;"
        in html
    )

    assert (
        "max-height:"
        in html
    )


def test_sparse_hero_is_bottom_anchored_without_stretch():
    html = _html(
        "sparse_hero"
    )

    assert (
        ".layout-sparse_hero .text-block"
        in html
    )

    assert (
        "max-height: 35%;"
        in html
    )

    assert (
        "top: auto;"
        in html
    )


def test_discovery_story_is_bottom_anchored_without_stretch():
    html = _html(
        "discovery_story"
    )

    assert (
        ".layout-discovery_story .text-block"
        in html
    )

    assert (
        "max-height: 34%;"
        in html
    )


def test_technical_grid_hugs_modules():
    html = _html(
        "technical_grid",
        features=[
            Feature(
                icon="1",
                title="Mode 1",
                subtitle="Verified detail",
            ),
            Feature(
                icon="2",
                title="Mode 2",
                subtitle="Verified detail",
            ),
        ],
    )

    assert (
        "commercial-dark"
        in html
    )

    assert (
        "height: fit-content;"
        in html
    )


def test_commerce_hugs_content():
    html = _html(
        "feature_commerce",
        features=[
            Feature(
                icon="A",
                title="Information",
                subtitle="Verified detail",
            )
        ],
    )

    assert (
        'data-commercial-style="light"'
        in html
    )

    assert (
        "height: fit-content;"
        in html
    )
