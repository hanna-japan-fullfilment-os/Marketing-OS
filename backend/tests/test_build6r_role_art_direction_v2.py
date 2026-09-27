
import inspect

from app.services.creative import (
    pipeline,
    templates,
)


def test_role_art_direction_v2_is_installed():
    source = inspect.getsource(
        templates._build_feature_showcase
    )

    assert (
        "BUILD6R_ROLE_ART_DIRECTION_V2"
        in source
    )


def test_sparse_hero_disables_full_canvas_ambient_overlay():
    source = inspect.getsource(
        templates._build_feature_showcase
    )

    marker = source.index(
        "BUILD6R_ROLE_ART_DIRECTION_V2"
    )

    v2 = source[
        marker:
    ]

    assert (
        ".layout-sparse_hero .art-overlay"
        in v2
    )

    assert (
        "background: transparent;"
        in v2
    )

    assert (
        ".layout-sparse_hero .text-block"
        in v2
    )


def test_technical_grid_uses_contained_left_rail():
    source = inspect.getsource(
        templates._build_feature_showcase
    )

    marker = source.index(
        "BUILD6R_ROLE_ART_DIRECTION_V2"
    )

    v2 = source[
        marker:
    ]

    assert (
        ".layout-technical_grid .art-overlay"
        in v2
    )

    assert (
        "41.5%"
        in v2
    )

    assert (
        ".layout-technical_grid .text-block"
        in v2
    )


def test_commerce_utility_and_editorial_have_distinct_treatments():
    source = inspect.getsource(
        templates._build_feature_showcase
    )

    marker = source.index(
        "BUILD6R_ROLE_ART_DIRECTION_V2"
    )

    v2 = source[
        marker:
    ]

    assert (
        ".layout-feature_commerce .cta-pill"
        in v2
    )

    assert (
        ".layout-utility_demo .text-block"
        in v2
    )

    assert (
        ".layout-hero_editorial .headline"
        in v2
    )


def test_discovery_story_has_real_left_narrative_space():
    assert (
        pipeline._ADAPTIVE_PRODUCT_ZONES[
            "discovery_story"
        ]
        == (
            0.30,
            0.03,
            0.62,
            0.70,
            "top",
        )
    )

    source = inspect.getsource(
        templates._build_feature_showcase
    )

    marker = source.index(
        "BUILD6R_ROLE_ART_DIRECTION_V2"
    )

    v2 = source[
        marker:
    ]

    assert (
        ".layout-discovery_story .text-block"
        in v2
    )

    assert (
        "width: 30%;"
        in v2
    )


def test_v2_does_not_enable_product_recreation():
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
