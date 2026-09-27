
import inspect

from app.services.creative import (
    compositor,
    pipeline,
    templates,
)


def test_premium_product_zone_policy_is_role_specific():
    expected = {
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

    assert (
        pipeline._ADAPTIVE_PRODUCT_ZONES
        == expected
    )


def test_premium_shadow_uses_contact_shadow_contract():
    source = inspect.getsource(
        compositor._drop_shadow
    )

    assert (
        "BUILD6R_PREMIUM_CONTACT_SHADOW_V1"
        in source
    )

    assert (
        "effective_opacity"
        in source
    )

    assert (
        "ellipse_h"
        in source
    )


def test_feature_showcase_uses_premium_editorial_visual_language():
    source = inspect.getsource(
        templates._build_feature_showcase
    )

    assert (
        "BUILD6R_PREMIUM_EDITORIAL_SYSTEM_V1"
        in source
    )

    assert (
        ".layout-hero_editorial .text-block"
        in source
    )

    assert (
        ".layout-technical_grid .text-block"
        in source
    )

    assert (
        ".layout-sparse_hero .text-block"
        in source
    )

    assert (
        ".layout-discovery_story .text-block"
        in source
    )

    assert (
        'content: "  >";'
        in source
    )


def test_editorial_override_removes_ui_card_treatment():
    source = inspect.getsource(
        templates._build_feature_showcase
    )

    marker_index = source.index(
        "BUILD6R_PREMIUM_EDITORIAL_SYSTEM_V1"
    )

    override = source[
        marker_index:
    ]

    assert (
        "background: transparent;"
        in override
    )

    assert (
        "border-radius: 0;"
        in override
    )

    assert (
        "box-shadow: none;"
        in override
    )

    assert (
        "backdrop-filter: none;"
        in override
    )


def test_full_product_recreation_remains_outside_composition_policy():
    source = inspect.getsource(
        pipeline.render_slide
    )

    assert (
        "recreated_image"
        in source
    )

    assert (
        "immutable"
        in source.lower()
    )
