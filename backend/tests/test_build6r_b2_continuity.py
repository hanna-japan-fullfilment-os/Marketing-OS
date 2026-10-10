"""Build 6R-B2 continuity/cache/cost tests."""

import inspect

from app.services.orchestrator import (
    _render_additional_platform_variants,
    run_visuals_stage,
)
from app.services.qa_engine import (
    revise_creative_direction_for_variant,
)
from app.services.prompt_registry import (
    PROMPT_VERSIONS,
)


def test_variant_engine_accepts_primary_creative_state():
    signature = inspect.signature(
        _render_additional_platform_variants
    )

    assert "primary_adaptation" in signature.parameters
    assert (
        "primary_creative_directions"
        in signature.parameters
    )

    assert (
        signature.parameters[
            "primary_adaptation"
        ].default
        is None
    )

    assert (
        signature.parameters[
            "primary_creative_directions"
        ].default
        is None
    )


def test_primary_state_is_passed_from_visuals_stage():
    source = inspect.getsource(
        run_visuals_stage
    )

    assert (
        "primary_adaptation=primary_adaptation"
        in source
    )

    assert (
        "primary_creative_directions="
        "primary_creative_directions"
        in source
    )


def test_primary_platform_adaptation_is_reused():
    source = inspect.getsource(
        _render_additional_platform_variants
    )

    assert (
        "platform == primary_platform"
        in source
    )

    assert (
        "primary_adaptation is not None"
        in source
    )

    assert (
        "adaptation = primary_adaptation"
        in source
    )


def test_primary_cache_uses_real_creative_direction():
    source = inspect.getsource(
        _render_additional_platform_variants
    )

    assert (
        "primary_creative_directions"
        in source
    )

    assert (
        "primary_fallback_signature"
        not in source
    )

    assert (
        "_scene_signature("
        in source
    )


def test_primary_variant_persists_creative_direction():
    source = inspect.getsource(
        _render_additional_platform_variants
    )

    assert (
        "creative_direction=("
        in source
    )

    assert (
        "max(primary_creative_directions)"
        in source
    )


def test_qa_revision_preserves_archetype():
    source = inspect.getsource(
        revise_creative_direction_for_variant
    ).lower()

    assert "campaign archetype" in source
    assert "visual story system" in source
    assert "product/category context" in source
    assert "generic luxury" in source


def test_all_build6r_prompt_versions_are_now_1_1():
    expected = {
        "master_campaign_concept": "1.7.0",
        "platform_adaptation": '1.2.0',
        "creative_direction": '1.2.0',
        "scene_generation": "1.1.0",
        "targeted_creative_direction_revision": "1.3.0",
    }

    for key, version in expected.items():
        assert (
            PROMPT_VERSIONS[key].version
            == version
        )

