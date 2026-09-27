"""Build 6R-C2C commercial polish tests."""

import inspect
from pathlib import Path

from app.services.creative.pipeline import (
    SlideCreativeInput,
)
from app.services.creative.templates import (
    TEMPLATE_REGISTRY_VERSION,
    Feature,
    TemplateContext,
    _resolve_commercial_style,
    get_template,
)
from app.services.orchestrator import (
    _render_additional_platform_variants,
    run_visuals_stage,
)


def _ctx(
    layout,
    *,
    palette=None,
    secondary_font="'Georgia', serif",
    typography="",
    emphasis="",
    cta_treatment="",
    headline="Produto",
    body="Texto",
    bottom_features=None,
    trust_badges=None,
):
    return TemplateContext(
        width=1080,
        height=1350,
        composited_image_data_uri=(
            "data:image/png;base64,AA=="
        ),
        eyebrow="HANNA",
        headline=headline,
        body=body,
        cta="Conheca",
        accent_color="#E0477B",
        font_family=(
            "'Segoe UI', Arial, sans-serif"
        ),
        secondary_font_family=(
            secondary_font
        ),
        direction_palette=(
            palette
            or [
                "#8CC7D8",
                "#F4E8D8",
            ]
        ),
        typography_direction=(
            typography
        ),
        headline_emphasis=(
            emphasis
        ),
        cta_treatment=(
            cta_treatment
        ),
        layout_variant=layout,
        campaign_archetype="feature_demo",
        slide_role="benefit",
        features=[
            Feature(
                icon="1",
                title="Fato",
                subtitle="Detalhe",
            )
        ],
        bottom_features=(
            bottom_features
            or []
        ),
        trust_badges=(
            trust_badges
            or []
        ),
        slide_number=1,
        total_slides=6,
    )



def test_template_recipe_bumped():
    assert (
        TEMPLATE_REGISTRY_VERSION
        == '1.2.0'
    )


def test_input_contract_receives_direction_style():
    fields = (
        SlideCreativeInput
        .__dataclass_fields__
    )

    for field in (
        "direction_palette",
        "secondary_font_family",
        "typography_direction",
        "headline_emphasis",
        "cta_treatment",
        "hero_treatment",
        "visual_style",
        "mood",
        "negative_space",
    ):
        assert field in fields


def test_utility_is_light_not_generic_dark():
    style = (
        _resolve_commercial_style(
            _ctx(
                "utility_demo"
            )
        )
    )

    assert (
        style["family"]
        == "light"
    )

    assert (
        style["text"]
        == "#17181B"
    )


def test_commerce_is_light_not_dashboard_dark():
    style = (
        _resolve_commercial_style(
            _ctx(
                "feature_commerce"
            )
        )
    )

    assert (
        style["family"]
        == "light"
    )


def test_technical_remains_premium_dark():
    style = (
        _resolve_commercial_style(
            _ctx(
                "technical_grid"
            )
        )
    )

    assert (
        style["family"]
        == "dark"
    )

    assert (
        style["text"]
        == "#FFFFFF"
    )


def test_discovery_uses_editorial_treatment():
    style = (
        _resolve_commercial_style(
            _ctx(
                "discovery_story"
            )
        )
    )

    assert (
        style["family"]
        == "editorial"
    )


def test_direction_palette_reaches_ambient_design():
    style = (
        _resolve_commercial_style(
            _ctx(
                "utility_demo",
                palette=[
                    "#88CCEE",
                    "#FFCCAA",
                ],
            )
        )
    )

    assert (
        "rgba(136,204,238,0.10)"
        in style["ambient"]
    )


def test_editorial_uses_secondary_brand_font():
    style = (
        _resolve_commercial_style(
            _ctx(
                "discovery_story",
                secondary_font=(
                    "'Brand Serif', serif"
                ),
            )
        )
    )

    assert (
        style["headline_font"]
        == "'Brand Serif', serif"
    )


def test_outline_cta_direction_is_respected():
    style = (
        _resolve_commercial_style(
            _ctx(
                "feature_commerce",
                cta_treatment=(
                    "minimal outline"
                ),
            )
        )
    )

    assert (
        style["cta_fill"]
        == "transparent"
    )


def test_branding_is_signature_not_universal_white_pill():
    html = get_template(
        "feature_showcase"
    ).build_html(
        _ctx(
            "hero_editorial"
        )
    )

    assert (
        "brand-signature"
        in html
    )

    assert (
        "border-left:"
        in html
    )

    assert (
        "brand-lockup"
        not in html
    )


def test_footer_uses_compact_chips_not_old_dashboard_bar():
    ctx = _ctx(
        "feature_commerce",
        bottom_features=[
            "Origem",
            "Escolha",
        ],
        trust_badges=[
            "Informacao verificada"
        ],
    )

    html = get_template(
        "feature_showcase"
    ).build_html(
        ctx
    )

    assert (
        "support-chip"
        in html
    )

    assert (
        "commercial-footer"
        in html
    )

    assert (
        "background: rgba(10,10,10,0.52)"
        not in html
    )



def test_utf8_portuguese_is_preserved_in_real_dom():
    headline = (
        "Quando o produto "
        "\u00e9 \u00fanico, "
        "a hist\u00f3ria faz diferen\u00e7a."
    )

    body = (
        "Informa\u00e7\u00e3o "
        "do Jap\u00e3o."
    )

    ctx = _ctx(
        "discovery_story",
        headline=headline,
        body=body,
    )

    html = get_template(
        "feature_showcase"
    ).build_html(
        ctx
    )

    assert headline in html
    assert body in html
    assert "\ufffd" not in html



def test_primary_runtime_forwards_direction_style():
    source = inspect.getsource(
        run_visuals_stage
    )

    for field in (
        "direction_palette=",
        "typography_direction=",
        "headline_emphasis=",
        "cta_treatment=",
        "visual_style=",
        "mood=",
        "negative_space=",
    ):
        assert field in source


def test_secondary_runtime_forwards_direction_style():
    source = inspect.getsource(
        _render_additional_platform_variants
    )

    for field in (
        "direction_palette=",
        "typography_direction=",
        "headline_emphasis=",
        "cta_treatment=",
        "visual_style=",
    ):
        assert field in source


def test_technical_modules_are_larger():
    ctx = _ctx(
        "technical_grid"
    )

    html = get_template(
        "feature_showcase"
    ).build_html(
        ctx
    )

    assert (
        "commercial-dark"
        in html
    )

    assert (
        "repeat(" in html
    )


def test_existing_six_layout_identity_is_preserved():
    template = get_template(
        "feature_showcase"
    )

    layouts = (
        "sparse_hero",
        "hero_editorial",
        "utility_demo",
        "technical_grid",
        "discovery_story",
        "feature_commerce",
    )

    for layout in layouts:
        html = template.build_html(
            _ctx(layout)
        )

        assert (
            f"layout-{layout}"
            in html
        )
