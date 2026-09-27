from __future__ import annotations

import inspect

import app.services.orchestrator as orchestrator


def _contract() -> str:
    return (
        orchestrator
        ._build6r_v39_field_specific_strategy_generation_contract()
    )


def test_v39_contract_has_explicit_field_rules():
    contract = _contract()

    for marker in (
        "FIELD-SPECIFIC STRATEGY OUTPUT CONTRACT",
        "INSIGHT FIELD",
        "ANGLE FIELD",
        "KEY_MESSAGE FIELD",
        "REASON_THIS_SHOULD_WORK FIELD",
        "RESEARCH_BASIS FIELD",
        "FINAL SELF-CHECK",
    ):
        assert marker in contract


def test_v39_contract_prohibits_live_failure_classes():
    lowered = _contract().lower()

    for marker in (
        "consumer behavior",
        "market behavior",
        "manufacturer communication",
        "audience reaction",
        "authority",
        "trust",
        "interpretive product assertions",
        "lululun materials emphasize",
        "the manufacturer focuses on",
    ):
        assert marker in lowered


def test_v39_contract_requires_exact_product_evidence_boundary():
    contract = _contract()

    assert "VERIFIED PRODUCT FACTS" in contract
    assert "Every factual product atom" in contract
    assert "Do not simplify or rename a technical ingredient" in contract
    assert "Never use research_basis to justify a product claim" in contract


def test_v39_contract_requires_conservative_fallback_candidate():
    contract = _contract()

    assert "CONSERVATIVE FALLBACK CANDIDATE" in contract
    assert "at least one candidate MUST be a conservative fallback candidate" in contract
    assert "neutral non-factual creative premise" in contract
    assert "canonical VERIFIED PRODUCT FACTS without interpretation" in contract
    assert "research_basis should be empty" in contract


def test_v39_contract_scopes_research_as_external_context_only():
    contract = _contract()

    assert "Research is explicitly external creative context only" in contract
    assert "External research context: ..." in contract
    assert "If a research statement cannot be kept clearly external, omit it." in contract


def test_v39_helper_is_prompt_only_and_zero_cost():
    source = inspect.getsource(
        orchestrator._build6r_v39_field_specific_strategy_generation_contract
    )

    for forbidden in (
        "generate_structured",
        "generate_image",
        "edit_image",
        "run_research",
        "record_stage_usage",
        "_audit(",
        "db.commit",
        "httpx",
        "requests.",
        "socket.",
        "OpenAI",
    ):
        assert forbidden not in source


def test_v39_is_wired_after_v36_and_before_strategy_schema():
    source = inspect.getsource(orchestrator.run_strategy_stage)

    v36_pos = source.index(
        "_build6r_v36_strategy_generation_grounding_instruction()"
    )
    v39_pos = source.index(
        "_build6r_v39_field_specific_strategy_generation_contract()"
    )
    schema_pos = source.index("schema=CampaignStrategyCandidates")

    assert v36_pos < v39_pos < schema_pos


def test_v39_preserves_single_paid_strategy_generation_call():
    source = inspect.getsource(orchestrator.run_strategy_stage)

    assert source.count("ai_provider.generate_structured(") == 1
    assert source.count(
        "_build6r_v39_field_specific_strategy_generation_contract()"
    ) == 1


def test_v39_preserves_v38_grounding_before_novelty():
    source = inspect.getsource(orchestrator.run_strategy_stage)

    generation_pos = source.index("schema=CampaignStrategyCandidates")
    filter_pos = source.index(
        "_build6r_v38_filter_grounded_strategy_candidates("
    )
    novelty_pos = source.index(
        "classify_novelty(",
        filter_pos,
    )

    assert generation_pos < filter_pos < novelty_pos


def test_v39_preserves_final_containment_gates():
    source = inspect.getsource(orchestrator.run_strategy_stage)

    assert (
        source.index("_build6r_v38_filter_grounded_strategy_candidates(")
        < source.index("_build6r_v35_enforce_strategy_containment(")
        < source.index("_enforce_generated_claim_grounding_gate(")
    )
