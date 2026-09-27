from __future__ import annotations

import ast
import inspect
import socket

import pytest

from app.schemas.ai import CreativeBrief
from app.services import claims_audit
from app.services import orchestrator


class DummyDB:

    def commit(self):

        return None


class DummyCampaign:

    def __init__(self):

        self.id = "campaign-test"
        self.status = "BRIEF_READY"


class DummyBrand:

    pass


class DummyProduct:

    pass


def _finding(
    *,
    field_name: str,
    category: str,
    claim_text: str,
):

    return claims_audit.ClaimFinding(
        claim_text=claim_text,
        claim_category=category,
        source_field=(
            "creative_brief."
            + field_name
        ),
        evidence_status="UNSUPPORTED",
        allowed_source="",
        reason=(
            "synthetic unsupported claim"
        ),
    )


def _audit_result_for_fields(
    fields,
):

    findings = []

    for (
        source_field,
        raw_value,
    ) in fields.items():

        field_name = (
            source_field
            .split(".")[-1]
        )

        value = str(
            raw_value
        ).lower()


        if "#1" in value:

            findings.append(
                _finding(
                    field_name=field_name,
                    category=(
                        "ranking_bestseller"
                    ),
                    claim_text="#1",
                )
            )

            findings.append(
                _finding(
                    field_name=field_name,
                    category=(
                        "ranking_or_bestseller"
                    ),
                    claim_text="#1",
                )
            )


        if (
            "best-seller"
            in value
            or "bestseller"
            in value
        ):

            findings.append(
                _finding(
                    field_name=field_name,
                    category=(
                        "ranking_bestseller"
                    ),
                    claim_text=(
                        "best-seller"
                    ),
                )
            )


        if (
            "guaranteed results"
            in value
        ):

            findings.append(
                _finding(
                    field_name=field_name,
                    category=(
                        "transformation_results"
                    ),
                    claim_text=(
                        "guaranteed results"
                    ),
                )
            )


    return (
        claims_audit.ClaimAuditResult(
            findings=findings
        )
    )


def _install_claim_engine(
    monkeypatch,
):

    calls = []

    def fake_audit_text_fields(
        *,
        fields,
        verified,
        brand,
    ):

        calls.append(
            dict(fields)
        )

        return (
            _audit_result_for_fields(
                fields
            )
        )

    monkeypatch.setattr(
        claims_audit,
        "audit_text_fields",
        fake_audit_text_fields,
    )

    return calls


def _brief(
    *,
    design_concept=(
        "Clean product hero with balanced negative space"
    ),
    visual_prompt=(
        "Product centered on a clean neutral background"
    ),
    template_suggestion=(
        "premium_product_hero"
    ),
    tone_notes=(
        "Warm and restrained"
    ),
):

    return CreativeBrief(
        design_concept=design_concept,
        visual_prompt=visual_prompt,
        template_suggestion=template_suggestion,
        tone_notes=tone_notes,
    )


@pytest.fixture
def context(
    monkeypatch,
):

    db = DummyDB()
    campaign = DummyCampaign()
    brand = DummyBrand()
    product = DummyProduct()

    monkeypatch.setattr(
        orchestrator,
        "resolve_verified_product_facts",
        lambda db, product:
            object(),
    )

    events = []

    monkeypatch.setattr(
        orchestrator,
        "_audit",
        lambda db, campaign_id, event_type, payload:
            events.append(
                (
                    campaign_id,
                    event_type,
                    payload,
                )
            ),
    )

    return (
        db,
        campaign,
        brand,
        product,
        events,
    )


def _repair(
    context,
    brief,
):

    (
        db,
        campaign,
        brand,
        product,
        _events,
    ) = context

    return (
        orchestrator
        ._neutralize_creative_brief_ranking_only(
            db,
            campaign=campaign,
            brand=brand,
            product=product,
            creative_brief=brief,
        )
    )


def _run_final_gate(
    context,
    brief,
):

    (
        db,
        campaign,
        brand,
        product,
        _events,
    ) = context

    return (
        orchestrator
        ._enforce_generated_claim_grounding_gate(
            db,
            campaign=campaign,
            brand=brand,
            product=product,
            phase="creative_brief",
            root_name="creative_brief",
            value=brief,
        )
    )


def test_design_concept_ranking_only_is_locally_repaired(
    monkeypatch,
    context,
):

    calls = _install_claim_engine(
        monkeypatch
    )

    brief = _brief(
        design_concept=(
            "Premium best-seller presentation"
        )
    )

    repaired = _repair(
        context,
        brief,
    )

    assert repaired is not brief

    assert (
        repaired.design_concept
        == orchestrator._BUILD6R_NEUTRAL_DESIGN_CONCEPT
    )

    assert (
        repaired.visual_prompt
        == brief.visual_prompt
    )

    assert (
        repaired.template_suggestion
        == brief.template_suggestion
    )

    assert (
        repaired.tone_notes
        == brief.tone_notes
    )

    assert (
        _run_final_gate(
            context,
            repaired,
        )
        == []
    )

    (
        _db,
        _campaign,
        _brand,
        _product,
        events,
    ) = context

    assert len(events) == 1

    (
        _campaign_id,
        event_type,
        payload,
    ) = events[0]

    assert (
        event_type
        == "creative_brief_ranking_fields_locally_neutralized"
    )

    assert (
        payload[
            "neutralized_fields"
        ]
        == [
            "design_concept"
        ]
    )

    assert payload[
        "provider_calls"
    ] == 0

    assert payload[
        "model_calls"
    ] == 0

    assert payload[
        "network_calls"
    ] == 0

    assert payload[
        "research_calls"
    ] == 0

    assert payload[
        "image_calls"
    ] == 0

    assert len(calls) >= 5


def test_visual_prompt_ranking_only_remains_supported(
    monkeypatch,
    context,
):

    _install_claim_engine(
        monkeypatch
    )

    brief = _brief(
        visual_prompt=(
            "Hero image with #1 badge"
        )
    )

    repaired = _repair(
        context,
        brief,
    )

    assert repaired is not brief

    assert (
        repaired.design_concept
        == brief.design_concept
    )

    assert "#1" not in (
        repaired.visual_prompt
    )

    assert (
        brief.design_concept
        in repaired.visual_prompt
    )

    assert (
        repaired.template_suggestion
        == brief.template_suggestion
    )

    assert (
        repaired.tone_notes
        == brief.tone_notes
    )

    assert (
        _run_final_gate(
            context,
            repaired,
        )
        == []
    )


def test_multiple_ranking_contaminated_fields_are_repaired(
    monkeypatch,
    context,
):

    _install_claim_engine(
        monkeypatch
    )

    brief = _brief(
        design_concept=(
            "Best-seller hero direction"
        ),
        visual_prompt=(
            "Show a #1 badge"
        ),
        template_suggestion=(
            "bestseller_layout"
        ),
        tone_notes=(
            "Best-seller energy"
        ),
    )

    repaired = _repair(
        context,
        brief,
    )

    assert repaired is not brief

    assert (
        repaired.design_concept
        == orchestrator._BUILD6R_NEUTRAL_DESIGN_CONCEPT
    )

    assert (
        repaired.template_suggestion
        == orchestrator._BUILD6R_NEUTRAL_TEMPLATE_SUGGESTION
    )

    assert (
        repaired.tone_notes
        == orchestrator._BUILD6R_NEUTRAL_TONE_NOTES
    )

    assert "#1" not in (
        repaired.visual_prompt
    )

    assert (
        "best-seller"
        not in repaired.visual_prompt.lower()
    )

    assert (
        repaired.design_concept
        in repaired.visual_prompt
    )

    assert (
        _run_final_gate(
            context,
            repaired,
        )
        == []
    )

    events = context[-1]

    assert len(events) == 1

    assert (
        events[0][2][
            "neutralized_fields"
        ]
        == [
            "design_concept",
            "template_suggestion",
            "tone_notes",
            "visual_prompt",
        ]
    )


def test_safe_creative_brief_is_returned_unchanged(
    monkeypatch,
    context,
):

    _install_claim_engine(
        monkeypatch
    )

    brief = _brief()

    repaired = _repair(
        context,
        brief,
    )

    assert repaired is brief

    assert context[-1] == []


def test_only_contaminated_field_changes(
    monkeypatch,
    context,
):

    _install_claim_engine(
        monkeypatch
    )

    brief = _brief(
        tone_notes=(
            "Best-seller energy"
        )
    )

    repaired = _repair(
        context,
        brief,
    )

    assert (
        repaired.design_concept
        == brief.design_concept
    )

    assert (
        repaired.visual_prompt
        == brief.visual_prompt
    )

    assert (
        repaired.template_suggestion
        == brief.template_suggestion
    )

    assert (
        repaired.tone_notes
        == orchestrator._BUILD6R_NEUTRAL_TONE_NOTES
    )


def test_mixed_ranking_and_nonranking_claims_are_never_repaired(
    monkeypatch,
    context,
):

    _install_claim_engine(
        monkeypatch
    )

    brief = _brief(
        design_concept=(
            "Best-seller hero"
        ),
        visual_prompt=(
            "Show guaranteed results"
        ),
    )

    repaired = _repair(
        context,
        brief,
    )

    assert repaired is brief
    assert context[-1] == []

    with pytest.raises(
        orchestrator.PreVisualClaimGroundingError
    ):

        _run_final_gate(
            context,
            repaired,
        )

    assert (
        context[1].status
        == "FAILED"
    )


def test_nonranking_unsupported_claim_is_never_repaired(
    monkeypatch,
    context,
):

    _install_claim_engine(
        monkeypatch
    )

    brief = _brief(
        design_concept=(
            "Guaranteed results presentation"
        )
    )

    repaired = _repair(
        context,
        brief,
    )

    assert repaired is brief
    assert context[-1] == []

    with pytest.raises(
        orchestrator.PreVisualClaimGroundingError
    ):

        _run_final_gate(
            context,
            repaired,
        )


def test_repair_has_no_provider_model_network_or_image_boundary():

    signature = inspect.signature(
        orchestrator
        ._neutralize_creative_brief_ranking_only
    )

    assert (
        "ai_provider"
        not in signature.parameters
    )

    source = inspect.getsource(
        orchestrator
        ._neutralize_creative_brief_ranking_only
    )

    forbidden = (
        "generate_structured",
        "generate_image",
        "edit_image",
        "responses.",
        "images.",
        "httpx",
        "requests.",
        "socket.",
        "research_provider",
    )

    assert all(
        marker not in source
        for marker
        in forbidden
    )


def test_network_is_not_required_for_cross_field_repair(
    monkeypatch,
    context,
):

    _install_claim_engine(
        monkeypatch
    )

    def blocked(
        *args,
        **kwargs,
    ):

        raise AssertionError(
            "network access attempted"
        )

    monkeypatch.setattr(
        socket.socket,
        "connect",
        blocked,
    )

    repaired = _repair(
        context,
        _brief(
            design_concept=(
                "Best-seller presentation"
            )
        ),
    )

    assert (
        repaired.design_concept
        == orchestrator._BUILD6R_NEUTRAL_DESIGN_CONCEPT
    )


def test_run_copy_stage_executes_cross_field_repair_before_final_gate():

    source = inspect.getsource(
        orchestrator.run_copy_stage
    )

    repair_position = (
        source.find(
            "_neutralize_creative_brief_ranking_only("
        )
    )

    gate_position = (
        source.find(
            "_enforce_generated_claim_grounding_gate("
        )
    )

    assert repair_position >= 0
    assert gate_position >= 0

    assert (
        repair_position
        < gate_position
    )


    tree = ast.parse(
        source
    )

    assignment_found = False
    gate_uses_repaired_brief = False


    for node in ast.walk(
        tree
    ):

        if (
            isinstance(
                node,
                ast.Assign,
            )
            and len(
                node.targets
            )
            == 1
            and isinstance(
                node.targets[0],
                ast.Name,
            )
            and node.targets[0].id
            == "creative_brief"
            and isinstance(
                node.value,
                ast.Call,
            )
            and isinstance(
                node.value.func,
                ast.Name,
            )
            and node.value.func.id
            == "_neutralize_creative_brief_ranking_only"
        ):

            assignment_found = True


        if (
            isinstance(
                node,
                ast.Call,
            )
            and isinstance(
                node.func,
                ast.Name,
            )
            and node.func.id
            == "_enforce_generated_claim_grounding_gate"
        ):

            keyword_map = {
                keyword.arg:
                    keyword.value
                for keyword
                in node.keywords
                if keyword.arg
                is not None
            }

            value = (
                keyword_map.get(
                    "value"
                )
            )

            if (
                isinstance(
                    value,
                    ast.Name,
                )
                and value.id
                == "creative_brief"
            ):

                gate_uses_repaired_brief = True


    assert assignment_found

    assert (
        gate_uses_repaired_brief
    )
