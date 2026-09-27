from __future__ import annotations

from app.services.creative.templates import (
    TemplateContext,
    get_template,
)


def _context(
    *,
    masked_scene_background: bool,
    layout_variant: str = "sparse_hero",
):
    return TemplateContext(
        width=1080,
        height=1080,
        composited_image_data_uri="data:image/png;base64,AA==",
        eyebrow="HANNA JAPAN",
        headline="Beleza japonesa, em um ritual especial.",
        body="Uma experi?ncia editorial de produto.",
        cta="Descubra",
        accent_color="#B99252",
        text_color="#181716",
        font_family="Georgia, serif",
        layout_variant=layout_variant,
        campaign_archetype="product_hero",
        slide_role="hero",
        direction_palette=[
            "#F4EFE7",
            "#181716",
            "#B99252",
        ],
        hero_treatment="premium editorial",
        visual_style="product-led editorial",
        mood="refined",
        negative_space="intentional",
        masked_scene_background=masked_scene_background,
    )


def test_masked_scene_feature_showcase_adds_edgeless_text_protection():
    template = get_template(
        "feature_showcase"
    )

    html = template.build_html(
        _context(
            masked_scene_background=True,
            layout_variant="sparse_hero",
        )
    )

    assert (
        "masked-scene-background"
        in html
    )

    assert (
        "BUILD6R_MASKED_SCENE_TEXT_PROTECTION_V1"
        in html
    )

    assert (
        ".canvas.masked-scene-background .text-block"
        in html
    )

    assert (
        "linear-gradient("
        in html
    )

    assert (
        "backdrop-filter: blur(6px)"
        in html
    )

    # Premium protection is deliberately not a rounded UI card.
    protected = html.split(
        "BUILD6R_MASKED_SCENE_TEXT_PROTECTION_V1",
        1,
    )[1]

    assert (
        "border-radius: 0"
        in protected
    )

    assert (
        "box-shadow: none"
        in protected
    )


def test_masked_scene_protection_is_after_sparse_hero_transparency_override():
    template = get_template(
        "feature_showcase"
    )

    html = template.build_html(
        _context(
            masked_scene_background=True,
            layout_variant="sparse_hero",
        )
    )

    sparse_override = html.index(
        ".layout-sparse_hero .headline"
    )

    protection = html.index(
        "BUILD6R_MASKED_SCENE_TEXT_PROTECTION_V1"
    )

    assert (
        protection
        > sparse_override
    )


def test_masked_scene_uses_commercial_text_pair_not_fixed_brand_text():
    template = get_template(
        "feature_showcase"
    )

    html = template.build_html(
        _context(
            masked_scene_background=True,
            layout_variant="hero_editorial",
        )
    )

    protection = html.split(
        "BUILD6R_MASKED_SCENE_TEXT_PROTECTION_V1",
        1,
    )[1]

    assert (
        ".canvas.masked-scene-background .headline"
        in protection
    )

    assert (
        ".canvas.masked-scene-background .body"
        in protection
    )


def test_non_masked_scene_does_not_receive_runtime_protection_class():
    template = get_template(
        "feature_showcase"
    )

    html = template.build_html(
        _context(
            masked_scene_background=False,
            layout_variant="sparse_hero",
        )
    )

    # CSS contract may exist in the document, but the canvas does not opt in.
    assert (
        'class="canvas layout-sparse_hero'
        in html
    )

    opening_canvas = html.split(
        "<body>",
        1,
    )[1].split(
        ">",
        1,
    )[0]

    assert (
        "masked-scene-background"
        not in opening_canvas
    )


def test_all_feature_showcase_layouts_accept_masked_scene_protection():
    template = get_template(
        "feature_showcase"
    )

    layouts = [
        "sparse_hero",
        "hero_editorial",
        "utility_demo",
        "technical_grid",
        "discovery_story",
        "feature_commerce",
    ]

    for layout in layouts:
        html = template.build_html(
            _context(
                masked_scene_background=True,
                layout_variant=layout,
            )
        )

        assert (
            "masked-scene-background"
            in html
        )

        assert (
            "BUILD6R_MASKED_SCENE_TEXT_PROTECTION_V1"
            in html
        )
