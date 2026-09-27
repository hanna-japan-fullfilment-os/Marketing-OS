"""Build 6R-C2A1 adaptive layout wiring tests."""

import inspect
from pathlib import Path

from app.services.creative.pipeline import (
    ADAPTIVE_LAYOUT_VARIANTS,
    SlideCreativeInput,
    _apply_adaptive_product_zone,
    resolve_layout_variant,
)
from app.services.creative.templates import (
    Feature,
    TemplateContext,
    get_platform_format,
    get_template,
    product_zone_for,
)
from app.services.orchestrator import (
    _render_additional_platform_variants,
    run_visuals_stage,
)


def _input(
    *,
    archetype="",
    role="",
    headline="Product",
    body="",
    features=None,
    callout_label="",
    callout_value="",
    bottom_features=None,
    trust_badges=None,
):
    return SlideCreativeInput(
        source_image_path=Path(
            "dummy.png"
        ),
        template_id="feature_showcase",
        platform_key="instagram_portrait",
        headline=headline,
        body=body,
        campaign_archetype=archetype,
        slide_role=role,
        features=features or [],
        callout_label=callout_label,
        callout_value=callout_value,
        bottom_features=(
            bottom_features
            or []
        ),
        trust_badges=(
            trust_badges
            or []
        ),
    )


def test_six_layout_modes_exist():
    assert ADAPTIVE_LAYOUT_VARIANTS == {
        "sparse_hero",
        "hero_editorial",
        "utility_demo",
        "technical_grid",
        "discovery_story",
        "feature_commerce",
    }


def test_sparse_copy_routes_to_sparse_hero():
    assert (
        resolve_layout_variant(
            _input(
                headline="One product",
            )
        )
        == "sparse_hero"
    )


def test_hero_role_routes_to_editorial():
    assert (
        resolve_layout_variant(
            _input(
                archetype="lifestyle_utility",
                role="hero cover",
            )
        )
        == "hero_editorial"
    )


def test_utility_archetype_routes_to_demo():
    assert (
        resolve_layout_variant(
            _input(
                archetype="lifestyle_utility",
                role="benefit",
            )
        )
        == "utility_demo"
    )


def test_feature_demo_routes_to_utility():
    assert (
        resolve_layout_variant(
            _input(
                archetype="feature_demo",
            )
        )
        == "utility_demo"
    )


def test_technical_performance_routes_to_grid():
    assert (
        resolve_layout_variant(
            _input(
                archetype="technical_performance",
            )
        )
        == "technical_grid"
    )


def test_how_it_works_routes_to_grid():
    assert (
        resolve_layout_variant(
            _input(
                archetype="how_it_works",
            )
        )
        == "technical_grid"
    )


def test_discovery_routes_to_story():
    assert (
        resolve_layout_variant(
            _input(
                archetype="premium_discovery",
            )
        )
        == "discovery_story"
    )


def test_dense_discovery_routes_to_commerce():
    features = [
        Feature(title="One"),
        Feature(title="Two"),
        Feature(title="Three"),
    ]

    assert (
        resolve_layout_variant(
            _input(
                archetype="premium_discovery",
                features=features,
            )
        )
        == "feature_commerce"
    )


def test_generic_dense_slide_routes_to_commerce():
    features = [
        Feature(title="One"),
        Feature(title="Two"),
        Feature(title="Three"),
    ]

    assert (
        resolve_layout_variant(
            _input(
                features=features,
            )
        )
        == "feature_commerce"
    )


def test_product_zone_changes_with_layout():
    fmt = get_platform_format(
        "instagram_portrait"
    )

    template = get_template(
        "feature_showcase"
    )

    base = product_zone_for(
        template,
        fmt,
    )

    hero = (
        _apply_adaptive_product_zone(
            base,
            fmt,
            "sparse_hero",
        )
    )

    technical = (
        _apply_adaptive_product_zone(
            base,
            fmt,
            "technical_grid",
        )
    )

    assert hero.width > technical.width
    assert hero.left < technical.left
    assert hero.height != technical.height


def test_slidecreativeinput_has_layout_context():
    fields = (
        SlideCreativeInput.__dataclass_fields__
    )

    for name in (
        "campaign_archetype",
        "slide_role",
        "layout_variant",
    ):
        assert name in fields


def test_templatecontext_has_layout_context():
    fields = (
        TemplateContext.__dataclass_fields__
    )

    for name in (
        "campaign_archetype",
        "slide_role",
        "layout_variant",
    ):
        assert name in fields


def test_primary_runtime_passes_archetype():
    source = inspect.getsource(
        run_visuals_stage
    )

    assert (
        "primary_creative_direction."
        "campaign_archetype"
        in source
    )

    assert (
        "campaign_archetype="
        in source
    )


def test_secondary_runtime_passes_archetype():
    source = inspect.getsource(
        _render_additional_platform_variants
    )

    assert (
        "creative_direction."
        "campaign_archetype"
        in source
    )


def test_instagram_portrait_stays_1080_by_1350():
    fmt = get_platform_format(
        "instagram_portrait"
    )

    assert (
        fmt.width,
        fmt.height,
    ) == (
        1080,
        1350,
    )
