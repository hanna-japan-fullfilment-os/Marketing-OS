from __future__ import annotations

import ast
from pathlib import Path


ORCH = Path(
    "app/services/orchestrator.py"
)


def _strategy_source() -> str:
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
                (ast.FunctionDef, ast.AsyncFunctionDef),
            )
            and node.name == "run_strategy_stage"
        ):
            return (
                ast.get_source_segment(
                    text,
                    node,
                )
                or ""
            )

    raise AssertionError(
        "run_strategy_stage not found"
    )


def test_strategy_resolves_and_formats_verified_product_facts():
    source = _strategy_source()

    assert (
        "resolve_verified_product_facts(db, product)"
        in source
    )

    assert (
        "format_verified_facts_for_prompt("
        in source
    )

    assert (
        "verified_facts_note"
        in source
    )


def test_strategy_uses_existing_claims_boundary():
    source = _strategy_source()

    assert (
        "_claims_boundary_instruction()"
        in source
    )


def test_strategy_uses_sparse_fact_grounding():
    source = _strategy_source()

    assert (
        "_sparse_fact_grounding_instruction()"
        in source
    )


def test_strategy_marks_research_as_context_not_product_evidence():
    source = _strategy_source()

    assert (
        "CREATIVE CONTEXT ONLY"
        in source
    )

    assert (
        "never product-fact evidence"
        in source
    )


def test_strategy_boundary_explicitly_covers_all_candidate_fields():
    source = _strategy_source()

    for field in (
        "objective",
        "audience",
        "funnel_stage",
        "insight",
        "angle",
        "key_message",
        "reason_this_should_work",
        "research_basis",
    ):
        assert field in source


def test_strategy_verified_facts_precede_research_in_prompt():
    source = _strategy_source()

    facts_position = source.index(
        "verified_facts_note"
    )

    research_position = source.index(
        "Research insights ? CREATIVE CONTEXT ONLY"
    )

    assert facts_position < research_position


def test_strategy_does_not_remove_research_or_novelty_logic():
    source = _strategy_source()

    assert "run_research(" in source
    assert "classify_novelty(" in source
    assert "CampaignStrategyCandidates" in source
