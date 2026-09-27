"""Build 6R downstream grounding regression."""

import inspect

from app.services.orchestrator import (
    _generate_creative_direction,
    _render_additional_platform_variants,
    _resolve_platform_adaptation,
    run_visuals_stage,
)
from app.services.prompt_registry import PROMPT_VERSIONS
from app.services.qa_engine import (
    _qa_one_static_variant,
    revise_copy_for_variant,
    revise_creative_direction_for_variant,
)


def test_downstream_prompt_versions_and_fact_variables():
    expected = {
        "platform_adaptation": "1.2.0",
        "creative_direction": "1.2.0",
        "targeted_copy_revision": "1.1.0",
        "targeted_claims_revision": "1.1.0",
        "targeted_creative_direction_revision": "1.3.0",
    }

    for key, version in expected.items():
        assert PROMPT_VERSIONS[key].version == version
        assert (
            "verified_product_facts"
            in PROMPT_VERSIONS[key].variables
        )


def test_downstream_prompts_receive_verified_facts():
    for function in (
        _resolve_platform_adaptation,
        _generate_creative_direction,
        revise_copy_for_variant,
        revise_creative_direction_for_variant,
    ):
        assert (
            "verified_facts_note"
            in inspect.signature(function).parameters
        )

        source = inspect.getsource(function)

        assert (
            "_sparse_fact_grounding_instruction()"
            in source
        )

        assert "verified_facts_note" in source


def test_primary_direction_is_gated_before_image_spend():
    source = inspect.getsource(
        run_visuals_stage
    )

    phase = (
        'phase=f"creative_direction:{primary_platform}:'
        '{primary_language}:slide-{i}"'
    )

    start = source.index(
        "primary_creative_direction ="
    )

    gate = source.index(
        phase,
        start,
    )

    recreate = source.index(
        "recreate_creative_image_with_fidelity_gate(",
        start,
    )

    background = source.index(
        "generate_ai_background(",
        start,
    )

    assert gate < recreate
    assert gate < background


def test_secondary_direction_is_gated_before_image_spend():
    source = inspect.getsource(
        _render_additional_platform_variants
    )

    phase = (
        'phase=f"creative_direction:{platform}:'
        '{language}:slide-{idx}"'
    )

    start = source.index(
        "creative_direction = await "
        "_generate_creative_direction"
    )

    gate = source.index(
        phase,
        start,
    )

    image = source.index(
        "generate_ai_background(",
        start,
    )

    assert gate < image


def test_negative_guidance_is_excluded_from_claim_surface():
    for source in (
        inspect.getsource(
            run_visuals_stage
        ),
        inspect.getsource(
            _render_additional_platform_variants
        ),
        inspect.getsource(
            _qa_one_static_variant
        ),
    ):
        assert '"prohibited_elements"' in source
        assert '"negative_constraints"' in source


def test_qa_revision_is_gated_before_best_of_n():
    source = inspect.getsource(
        _qa_one_static_variant
    )

    phase = (
        'phase=f"qa_creative_direction_revision:'
        '{platform}:{language}"'
    )

    start = source.index(
        "revised_direction = await "
        "revise_creative_direction_for_variant"
    )

    gate = source.index(
        phase,
        start,
    )

    best = source.index(
        "_regenerate_with_best_of_n(",
        start,
    )

    assert gate < best

    assert (
        "verified_facts_note=verified_facts_note"
        in source
    )
