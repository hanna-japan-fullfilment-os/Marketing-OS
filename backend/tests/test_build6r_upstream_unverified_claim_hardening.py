from __future__ import annotations

import ast
from pathlib import Path

import app.services.orchestrator as orchestrator


ORCH = Path(
    "app/services/orchestrator.py"
)


def _source(name: str) -> str:

    text = ORCH.read_text(
        encoding="utf-8"
    )

    tree = ast.parse(
        text
    )

    for node in tree.body:

        if (
            isinstance(
                node,
                (
                    ast.FunctionDef,
                    ast.AsyncFunctionDef,
                ),
            )
            and node.name == name
        ):
            return (
                ast.get_source_segment(
                    text,
                    node,
                )
                or ""
            )

    raise AssertionError(
        name + " not found"
    )


def test_runtime_grounding_instruction_contains_origin_hard_stop():
    instruction = (
        orchestrator
        ._sparse_fact_grounding_instruction()
    )

    assert (
        "ORIGIN/PROVENANCE HARD STOP"
        in instruction
    )

    assert (
        "pouch japones"
        in instruction
    )

    assert (
        "Use it ONLY when country of origin is "
        "explicitly populated in VERIFIED PRODUCT FACTS"
        in instruction
    )


def test_runtime_grounding_instruction_rejects_third_party_endorsement_inference():
    instruction = (
        orchestrator
        ._sparse_fact_grounding_instruction()
    )

    assert (
        "THIRD-PARTY AUTHORITY HARD STOP"
        in instruction
    )

    assert (
        "Research can inspire creative direction only"
        in instruction
    )

    assert (
        "recommended for that benefit"
        in instruction
    )


def test_runtime_grounding_instruction_rejects_subjective_quantity_inflation():
    instruction = (
        orchestrator
        ._sparse_fact_grounding_instruction()
    )

    assert (
        "QUALITATIVE QUANTITY/INTENSITY HARD STOP"
        in instruction
    )

    assert (
        "muita formula"
        in instruction
    )

    assert (
        "150 mL and 7 sheets"
        in instruction
    )


def test_runtime_grounding_instruction_requires_fact_preserving_paraphrase():
    instruction = (
        orchestrator
        ._sparse_fact_grounding_instruction()
    )

    assert (
        "PARAPHRASE DISCIPLINE"
        in instruction
    )

    for concept in (
        "origin modifier",
        "benefit/effect",
        "endorsement",
        "quantity judgment",
        "efficacy implication",
    ):
        assert concept in instruction


def test_strategy_stage_inherits_hardened_shared_grounding():
    source = _source(
        "run_strategy_stage"
    )

    assert (
        "_sparse_fact_grounding_instruction()"
        in source
    )

    assert (
        "verified_facts_note"
        in source
    )

    assert (
        "CREATIVE CONTEXT ONLY"
        in source
    )


def test_copy_stage_inherits_hardened_shared_grounding():
    source = _source(
        "run_copy_stage"
    )

    assert (
        "_sparse_fact_grounding_instruction()"
        in source
    )

    assert (
        "verified_facts_note"
        in source
    )

    assert (
        "research_note"
        in source
    )


def test_hardening_is_shared_not_lululun_specific_runtime_logic():
    source = _source(
        "_sparse_fact_grounding_instruction"
    )

    assert (
        "lululun"
        not in source.lower()
    )

    assert (
        "a5ea2272"
        not in source.lower()
    )


def test_existing_fail_closed_language_remains_present():
    instruction = (
        orchestrator
        ._sparse_fact_grounding_instruction()
    )

    for phrase in (
        "VERIFIED PRODUCT FACTS are the complete factual evidence boundary",
        "Empty, blank, omitted, or unknown fields mean UNKNOWN",
        "Research, trends, competitor examples",
        "When facts are sparse, STAY SPARSE",
    ):
        assert phrase in instruction
