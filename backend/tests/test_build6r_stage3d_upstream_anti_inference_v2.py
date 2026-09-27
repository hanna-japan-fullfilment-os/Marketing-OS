from __future__ import annotations

import inspect

from app.services import orchestrator
from app.services.prompt_registry import PROMPT_VERSIONS


def test_stage3d_shared_anti_inference_hard_stops_exist():
    instruction = (
        orchestrator
        ._sparse_fact_grounding_instruction()
    )

    for marker in (
        "TEMPORAL/ROUTINE INFERENCE HARD STOP",
        "PACKAGE PURPOSE/ORGANIZATION HARD STOP",
        "PURCHASE-BEHAVIOR INFERENCE HARD STOP",
        "SUBJECTIVE QUALITY/COMFORT INFERENCE HARD STOP",
        "USAGE MODIFIER INFERENCE HARD STOP",
    ):
        assert marker in instruction


def test_stage3d_exact_failed_inference_language_is_explicitly_forbidden():
    instruction = (
        orchestrator
        ._sparse_fact_grounding_instruction()
        .lower()
    )

    for phrase in (
        "continuous use",
        "uso cont\u00ednuo",
        "several days",
        "v\u00e1rios dias",
        "alguns dias de cuidado seguido",
        "impulse purchases",
        "toque confort\u00e1vel",
        "bem feita",
        "press gently",
        "pressionando suavemente",
    ):
        assert phrase in instruction


def test_stage3d_timing_permission_does_not_become_frequency_claim():
    instruction = (
        orchestrator
        ._sparse_fact_grounding_instruction()
        .lower()
    )

    assert "morning or evening" in instruction

    assert (
        "does not establish daily, consecutive, continuous, or multi-day use"
        in instruction
    )


def test_stage3d_package_count_does_not_become_package_purpose():
    instruction = (
        orchestrator
        ._sparse_fact_grounding_instruction()
        .lower()
    )

    assert (
        "multiple units in one pouch do not prove"
        in instruction
    )

    assert (
        "invented purpose or consumer benefit"
        in instruction
    )


def test_stage3d_purchase_behavior_is_not_inferred():
    instruction = (
        orchestrator
        ._sparse_fact_grounding_instruction()
        .lower()
    )

    for phrase in (
        "buying one sheet at a time",
        "impulse purchases",
        "loose purchases",
        "random purchases",
        "sachets lost in a drawer",
    ):
        assert phrase in instruction


def test_stage3d_subjective_quality_is_not_inferred_from_feature_name():
    instruction = (
        orchestrator
        ._sparse_fact_grounding_instruction()
        .lower()
    )

    for phrase in (
        "comfort",
        "softness",
        "luxury",
        "premium quality",
        "craftsmanship",
        "sensory superiority",
    ):
        assert phrase in instruction


def test_stage3d_usage_modifiers_require_verified_evidence():
    instruction = (
        orchestrator
        ._sparse_fact_grounding_instruction()
        .lower()
    )

    for phrase in (
        "gently",
        "softly",
        "firmly",
        "lightly",
        "leave-on duration",
        "frequency",
        "cadence",
    ):
        assert phrase in instruction


def test_stage3d_hardening_is_shared_not_lululun_specific():
    source = inspect.getsource(
        orchestrator
        ._sparse_fact_grounding_instruction
    ).lower()

    assert "lululun" not in source
    assert "hydra ex" not in source
    assert "a5ea2272" not in source


def test_stage3d_shared_instruction_reaches_strategy_and_copy_generation():
    copy_source = inspect.getsource(
        orchestrator.run_copy_stage
    )

    strategy_source = inspect.getsource(
        orchestrator.run_strategy_stage
    )

    assert (
        copy_source.count(
            "_sparse_fact_grounding_instruction()"
        )
        == 5
    )

    assert (
        strategy_source.count(
            "_sparse_fact_grounding_instruction()"
        )
        == 1
    )


def test_stage3d_traceable_prompt_versions():
    expected = {
        "campaign_copy":
            "1.3.0",
        "carousel_plan":
            "1.3.0",
        "master_campaign_concept":
            "1.4.0",
    }

    for purpose, version in expected.items():
        spec = PROMPT_VERSIONS[
            purpose
        ]

        assert spec.version == version

        assert (
            "Stage 3D anti-inference hardening"
            in spec.change_notes
        )

        assert (
            "temporal/routine inference"
            in spec.change_notes
        )

        assert (
            "unverified usage modifiers"
            in spec.change_notes
        )


def test_stage3d_prior_fail_closed_contract_remains_present():
    instruction = (
        orchestrator
        ._sparse_fact_grounding_instruction()
    )

    for phrase in (
        "VERIFIED PRODUCT FACTS are the complete factual evidence boundary",
        "ORIGIN/PROVENANCE HARD STOP",
        "THIRD-PARTY AUTHORITY HARD STOP",
        "QUALITATIVE QUANTITY/INTENSITY HARD STOP",
        "PARAPHRASE DISCIPLINE",
        "When facts are sparse, STAY SPARSE",
    ):
        assert phrase in instruction


def test_stage3d_portuguese_examples_are_encoding_safe():
    source = inspect.getsource(
        orchestrator._sparse_fact_grounding_instruction
    )

    instruction = (
        orchestrator._sparse_fact_grounding_instruction()
    )

    q = chr(63)

    broken_tokens = (
        "uso cont" + q + "nuo",
        "v" + q + "rios dias",
        "sequ" + q + "ncia",
        "toque confort" + q + "vel",
    )

    for token in broken_tokens:
        assert token not in source
        assert token not in instruction

    escaped_source_tokens = (
        "uso cont" + "\\u00ed" + "nuo",
        "v" + "\\u00e1" + "rios dias",
        "sequ" + "\\u00ea" + "ncia",
        "toque confort" + "\\u00e1" + "vel",
    )

    for token in escaped_source_tokens:
        assert token in source

    runtime_tokens = (
        "uso cont" + chr(0x00ED) + "nuo",
        "v" + chr(0x00E1) + "rios dias",
        "sequ" + chr(0x00EA) + "ncia",
        "toque confort" + chr(0x00E1) + "vel",
    )

    for token in runtime_tokens:
        assert token in instruction

