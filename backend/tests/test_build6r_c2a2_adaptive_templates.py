"""Build 6R-C2A2 visible adaptive template tests."""

from app.services.creative.templates import (
    Feature,
    TemplateContext,
    get_template,
)


def _html(
    layout,
    *,
    features=None,
    logo=False,
    cta="",
    badge="",
):
    template = get_template(
        "feature_showcase"
    )

    ctx = TemplateContext(
        width=1080,
        height=1350,
        composited_image_data_uri=(
            "data:image/png;base64,AA=="
        ),
        eyebrow="HANNA",
        headline="Product headline",
        intro="Short supporting sentence.",
        cta=cta,
        logo_data_uri=(
            "data:image/png;base64,AA=="
            if logo
            else None
        ),
        badge_text=badge,
        features=features or [],
        layout_variant=layout,
        campaign_archetype="feature_demo",
        slide_role="benefit",
        slide_number=2,
        total_slides=6,
    )

    return template.build_html(ctx)


def test_all_six_layouts_emit_unique_identity():
    layouts = (
        "sparse_hero",
        "hero_editorial",
        "utility_demo",
        "technical_grid",
        "discovery_story",
        "feature_commerce",
    )

    for layout in layouts:
        html = _html(layout)

        assert (
            f"layout-{layout}"
            in html
        )

        assert (
            f'data-layout="{layout}"'
            in html
        )


def test_technical_layout_uses_two_column_grid():
    html = _html(
        "technical_grid",
        features=[
            Feature(
                icon="1",
                title="Mode one",
                subtitle="Detail",
            ),
            Feature(
                icon="2",
                title="Mode two",
                subtitle="Detail",
            ),
            Feature(
                icon="3",
                title="Mode three",
                subtitle="Detail",
            ),
        ],
    )

    compact = " ".join(
        html.split()
    )

    assert (
        "layout-technical_grid"
        in html
    )

    assert (
        "commercial-dark"
        in html
    )

    assert (
        "grid-template-columns:"
        in html
    )

    assert (
        "repeat( 2, minmax(0,1fr) );"
        in compact
    )

    assert (
        html.count(
            'class="feature-card"'
        )
        == 3
    )



def test_utility_layout_has_utility_class():
    html = _html(
        "utility_demo",
        features=[
            Feature(
                icon="*",
                title="Feature",
                subtitle="Explanation",
            )
        ],
        cta="Saiba mais",
        badge="HANNA PICKS",
    )

    assert (
        "layout-utility_demo"
        in html
    )

    assert (
        'class="feature-card"'
        in html
    )

    assert (
        'class="cta-pill"'
        in html
    )

    assert (
        'class="badge"'
        in html
    )


def test_logo_is_integrated_inside_brand_lockup():
    html = _html(
        "hero_editorial",
        logo=True,
    )

    assert (
        'class="brand-signature"'
        in html
    )

    assert (
        'class="logo"'
        in html
    )

    assert (
        "border-left:"
        in html
    )

    assert (
        'class="brand-lockup"'
        not in html
    )



def test_sparse_hero_has_bottom_story_behavior():
    html = _html(
        "sparse_hero"
    )

    assert (
        "layout-sparse_hero"
        in html
    )

    assert (
        ".layout-sparse_hero .text-block"
        in html
    )

    assert (
        "top: auto;"
        in html
    )

    assert (
        "max-height: 35%;"
        in html
    )

    assert (
        "justify-content: flex-start"
        in html
    )

    assert (
        "height: fit-content;"
        in html
    )



def test_discovery_story_has_editorial_bottom_behavior():
    html = _html(
        "discovery_story"
    )

    assert (
        "layout-discovery_story"
        in html
    )

    assert (
        ".layout-discovery_story .text-block"
        in html
    )


def test_feature_commerce_has_separate_module_behavior():
    html = _html(
        "feature_commerce",
        features=[
            Feature(
                icon="*",
                title="Feature",
                subtitle="Detail",
            ),
        ],
        cta="Conheca",
    )

    assert (
        "layout-feature_commerce"
        in html
    )

    assert (
        'data-commercial-style="light"'
        in html
    )

    assert (
        'class="feature-card"'
        in html
    )

    assert (
        'class="commercial-footer"'
        in html
    )



def test_carousel_marker_stays_deterministic():
    html = _html(
        "sparse_hero"
    )

    assert (
        'class="slide-marker"'
        in html
    )

    assert "2/6" in html


def test_campaign_copy_is_real_dom_not_image_text():
    html = _html(
        "feature_commerce",
        cta="Comprar",
    )

    assert (
        'class="headline"'
        in html
    )

    assert (
        "Product headline"
        in html
    )

    assert (
        'class="cta-pill"'
        in html
    )

    assert (
        'class="background"'
        in html
    )


def test_art_overlay_exists_for_scene_legibility():
    html = _html(
        "hero_editorial"
    )

    assert (
        'class="art-overlay"'
        in html
    )
