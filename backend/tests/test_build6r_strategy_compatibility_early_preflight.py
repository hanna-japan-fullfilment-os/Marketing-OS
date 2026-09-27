from __future__ import annotations

import ast
import inspect
from pathlib import Path
from types import SimpleNamespace

from app.services import orchestrator


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

    matches = [
        node
        for node in tree.body
        if isinstance(
            node,
            (
                ast.FunctionDef,
                ast.AsyncFunctionDef,
            ),
        )
        and node.name == name
    ]

    assert len(matches) == 1

    return (
        ast.get_source_segment(
            text,
            matches[0],
        )
        or ""
    )


def test_selector_preserves_brand_id_contract():
    signature = inspect.signature(
        orchestrator._select_underused_strategy_type
    )

    assert "brand_id" in signature.parameters
    assert "category_id" in signature.parameters


def test_selector_filters_before_usage_rotation():
    source = _source(
        "_select_underused_strategy_type"
    )

    assert (
        source.index(
            "candidate_types"
        )
        <
        source.index(
            "usage_counts"
        )
    )

    assert (
        "_strategy_type_fact_hard_fails("
        in source
    )

    assert (
        "average_engagement_rate_for_strategy_type"
        in source
    )


def test_strategy_preserves_exact_fact_resolver_contract():
    source = _source(
        "run_strategy_stage"
    )

    assert (
        "resolve_verified_product_facts(db, product)"
        in source
    )


def test_auto_strategy_type_name_is_not_written_to_angle():
    source = _source(
        "run_strategy_stage"
    )

    assert (
        "campaign.angle = strategy_type.name"
        not in source
    )

    assert (
        "campaign.angle = accepted.angle"
        in source
    )


def test_preselected_strategy_angle_has_explicit_preservation_contract():
    source = _source(
        "run_strategy_stage"
    )

    assert (
        "preserve_preselected_strategy_angle"
        in source
    )

    assert (
        "strategy_type is not None"
        in source
    )

    assert (
        "and campaign.angle"
        in source
    )

    assert (
        "if not preserve_preselected_strategy_angle:"
        in source
    )

    assert (
        "if not campaign.angle"
        not in source
    )


def test_accepted_strategy_gate_precedes_angle_decision():
    source = _source(
        "run_strategy_stage"
    )

    assert (
        source.index(
            'phase="strategy_candidate"'
        )
        <
        source.index(
            "if not preserve_preselected_strategy_angle:"
        )
    )


def test_creativebrief_gate_precedes_master_concept():
    source = _source(
        "run_copy_stage"
    )

    assert (
        source.index(
            'phase="creative_brief"'
        )
        <
        source.index(
            'progress.set_progress(15, "Defining the master campaign concept")'
        )
    )


def test_generated_gate_delegates_to_deterministic_gate(
    monkeypatch,
):
    captured = {}


    def fake_gate(
        db,
        *,
        campaign,
        brand,
        product,
        phase,
        structures,
    ):
        captured["phase"] = phase
        captured["structures"] = structures
        return []


    monkeypatch.setattr(
        orchestrator,
        "_enforce_previsual_claim_grounding_gate",
        fake_gate,
    )


    value = SimpleNamespace(
        model_dump=lambda: {
            "visual_prompt":
                "clean",
        }
    )


    result = (
        orchestrator
        ._enforce_generated_claim_grounding_gate(
            "db",
            campaign="campaign",
            brand="brand",
            product="product",
            phase="creative_brief",
            root_name="creative_brief",
            value=value,
        )
    )


    assert result == []

    assert (
        captured["structures"]
        == {
            "creative_brief": {
                "visual_prompt":
                    "clean",
            },
        }
    )


def test_generated_gate_has_no_semantic_ai_path():
    source = _source(
        "_enforce_generated_claim_grounding_gate"
    )

    assert (
        "_enforce_previsual_claim_grounding_gate"
        in source
    )

    assert (
        "_enforce_previsual_semantic_claim_grounding_gate"
        not in source
    )

    assert (
        "augment_with_ai_extraction"
        not in source
    )


def test_strategy_compatibility_reuses_claims_engine():
    source = _source(
        "_strategy_type_fact_hard_fails"
    )

    assert "audit_text_fields" in source
    assert "format_claims_hard_fails" in source
    assert "strategy_type.name" in source
    assert "strategy_type.trigger_description" in source
