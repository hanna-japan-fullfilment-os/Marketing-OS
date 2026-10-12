# BUILD6R V3.30 master-concept before/after recovery regressions.

from types import SimpleNamespace
import inspect

import app.services.claims_audit as claims_audit
import app.services.orchestrator as orchestrator
from app.schemas.creative_director import MasterCampaignConcept


def _concept(
    visual_identity="Product-first editorial system",
):
    return MasterCampaignConcept(
        concept_name="Grounded concept",
        campaign_promise="Grounded product discovery",
        key_message="Verified product information",
        emotional_goal="Confidence",
        audience="Customer",
        objective="Consideration",
        visual_identity=visual_identity,
        story_arc="Introduce > explain > act",
        cta_intent="Learn more",
        product_category_context="Product category",
        campaign_archetype="product_education",
        archetype_reasoning="Verified purchase information",
        visual_story_system="Product-first sequence",
        hero_treatment="Clean product hero",
        proof_or_demo_strategy="Verified information only",
    )


def _install_audit(
    monkeypatch,
    category_map,
):
    events = []

    monkeypatch.setattr(
        orchestrator,
        "resolve_verified_product_facts",
        lambda db, product: object(),
    )

    def fake_audit_text_fields(
        *,
        fields,
        verified,
        brand,
    ):
        assert verified is not None
        assert brand is not None
        assert list(fields) == [
            "master_concept.visual_identity"
        ]

        value = next(
            iter(
                fields.values()
            )
        )

        categories = category_map.get(
            value,
            (),
        )

        return SimpleNamespace(
            findings=[
                SimpleNamespace(
                    evidence_status="UNSUPPORTED",
                    claim_category=category,
                )
                for category in categories
            ]
        )

    monkeypatch.setattr(
        claims_audit,
        "audit_text_fields",
        fake_audit_text_fields,
    )

    monkeypatch.setattr(
        orchestrator,
        "_audit",
        lambda db, campaign_id, action, detail: (
            events.append(
                (
                    campaign_id,
                    action,
                    detail,
                )
            )
        ),
    )

    return events


def _call_helper(
    *,
    master_concept,
    product=object(),
):
    return (
        orchestrator
        ._neutralize_master_concept_visual_identity_before_after_only(
            None,
            campaign=SimpleNamespace(
                id="campaign-v330"
            ),
            brand=object(),
            product=product,
            master_concept=master_concept,
        )
    )


def test_exact_before_after_visual_identity_is_neutralized(
    monkeypatch,
):
    _install_audit(
        monkeypatch,
        {
            "before/after": (
                "transformation_results",
            ),
        },
    )

    original = _concept(
        visual_identity="before/after"
    )

    repaired = _call_helper(
        master_concept=original
    )

    assert repaired is not original

    assert (
        repaired.visual_identity
        == orchestrator
        ._BUILD6R_NEUTRAL_MASTER_CONCEPT_VISUAL_IDENTITY
    )

    original_dump = original.model_dump()
    repaired_dump = repaired.model_dump()

    original_dump.pop(
        "visual_identity"
    )
    repaired_dump.pop(
        "visual_identity"
    )

    assert repaired_dump == original_dump


def test_clean_visual_identity_is_unchanged(
    monkeypatch,
):
    _install_audit(
        monkeypatch,
        {},
    )

    original = _concept()

    repaired = _call_helper(
        master_concept=original
    )

    assert repaired is original


def test_mixed_transformation_and_unrelated_category_remains_fail_closed(
    monkeypatch,
):
    contaminated = (
        "before/after with clinical proof"
    )

    _install_audit(
        monkeypatch,
        {
            contaminated: (
                "transformation_results",
                "clinical_proof",
            ),
        },
    )

    original = _concept(
        visual_identity=contaminated
    )

    repaired = _call_helper(
        master_concept=original
    )

    assert repaired is original
    assert repaired.visual_identity == contaminated


def test_unrelated_category_is_never_neutralized(
    monkeypatch,
):
    contaminated = "clinically proven"

    _install_audit(
        monkeypatch,
        {
            contaminated: (
                "clinical_proof",
            ),
        },
    )

    original = _concept(
        visual_identity=contaminated
    )

    repaired = _call_helper(
        master_concept=original
    )

    assert repaired is original


def test_product_none_is_unchanged(
    monkeypatch,
):
    _install_audit(
        monkeypatch,
        {
            "before/after": (
                "transformation_results",
            ),
        },
    )

    original = _concept(
        visual_identity="before/after"
    )

    repaired = _call_helper(
        master_concept=original,
        product=None,
    )

    assert repaired is original


def test_repair_audit_event_is_zero_provider_and_requires_full_gate(
    monkeypatch,
):
    events = _install_audit(
        monkeypatch,
        {
            "before/after": (
                "transformation_results",
            ),
        },
    )

    repaired = _call_helper(
        master_concept=_concept(
            visual_identity="before/after"
        )
    )

    assert repaired.visual_identity
    assert len(events) == 1

    campaign_id, action, payload = events[0]

    assert campaign_id == "campaign-v330"

    assert (
        action
        == "master_concept_before_after_visual_identity_locally_neutralized"
    )

    assert payload["claim_categories"] == [
        "transformation_results"
    ]

    assert payload["neutralized_fields"] == [
        "visual_identity"
    ]

    assert payload["provider_calls"] == 0
    assert payload["model_calls"] == 0
    assert payload["network_calls"] == 0
    assert payload["research_calls"] == 0
    assert payload["image_calls"] == 0

    assert (
        payload[
            "full_grounding_gate_required_after_repair"
        ]
        is True
    )


def test_helper_has_no_provider_or_network_boundary():
    source = inspect.getsource(
        orchestrator
        ._neutralize_master_concept_visual_identity_before_after_only
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
        "ai_provider",
    )

    assert all(
        marker not in source
        for marker in forbidden
    )


def test_master_concept_prompt_keeps_research_as_inspiration_not_evidence():
    source = inspect.getsource(
        orchestrator.run_copy_stage
    )

    assert (
        "For visual_identity, research/trend context is "
        in source
    )

    assert (
        "inspiration only and never factual substantiation."
        in source
    )

    assert (
        "Do not use before/after, transformation, "
        in source
    )

    assert (
        "result-comparison, or outcome-proof framing unless it is "
        in source
    )

    assert (
        "explicitly supported by verified product facts or "
        in source
    )

    assert (
        "owner-confirmed brand facts."
        in source
    )


def test_run_copy_stage_orders_recovery_and_full_gate_before_copy_loop():
    source = inspect.getsource(
        orchestrator.run_copy_stage
    )

    helper_index = source.index(
        "_neutralize_master_concept_visual_identity_before_after_only("
    )

    gate_index = source.index(
        "_enforce_generated_claim_grounding_gate(",
        helper_index,
    )

    copy_loop_index = source.index(
        "for idx, language in enumerate(languages):",
        helper_index,
    )

    assert (
        helper_index
        < gate_index
        < copy_loop_index
    )


def test_repaired_master_concept_is_submitted_to_existing_full_gate(
    monkeypatch,
):
    _install_audit(
        monkeypatch,
        {
            "before/after": (
                "transformation_results",
            ),
        },
    )

    repaired = _call_helper(
        master_concept=_concept(
            visual_identity="before/after"
        )
    )

    captured = {}

    def fake_full_gate(
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
        fake_full_gate,
    )

    result = (
        orchestrator
        ._enforce_generated_claim_grounding_gate(
            None,
            campaign=SimpleNamespace(
                id="campaign-v330"
            ),
            brand=object(),
            product=object(),
            phase="master_concept_v330_recovery",
            root_name="master_concept",
            value=repaired,
        )
    )

    assert result == []

    assert (
        captured[
            "structures"
        ][
            "master_concept"
        ][
            "visual_identity"
        ]
        == orchestrator
        ._BUILD6R_NEUTRAL_MASTER_CONCEPT_VISUAL_IDENTITY
    )
