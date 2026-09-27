from __future__ import annotations

import inspect
from types import SimpleNamespace

import pytest

from app.services import claims_audit
from app.services import orchestrator


ELIGIBLE_CATEGORY = (
    "transformation_results"
)


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

    return orchestrator.CreativeBrief(
        design_concept=design_concept,
        visual_prompt=visual_prompt,
        template_suggestion=template_suggestion,
        tone_notes=tone_notes,
    )


def _finding(
    *,
    field_name,
    category,
    claim_text,
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
        reason="synthetic unsupported claim",
    )


def _result_for_fields(
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
            or ""
        ).lower()


        if (
            "before/after"
            in value
            or "before and after"
            in value
            or "guaranteed results"
            in value
        ):

            findings.append(
                _finding(
                    field_name=field_name,
                    category=(
                        "transformation_results"
                    ),
                    claim_text=(
                        "before/after"
                    ),
                )
            )


        if (
            "#1"
            in value
            or "bestseller"
            in value
            or "best-seller"
            in value
        ):

            findings.append(
                _finding(
                    field_name=field_name,
                    category=(
                        "ranking_bestseller"
                    ),
                    claim_text=(
                        "#1 bestseller"
                    ),
                )
            )


        if "retinol" in value:

            findings.append(
                _finding(
                    field_name=field_name,
                    category=(
                        "percentage_or_ingredient"
                    ),
                    claim_text=(
                        "retinol"
                    ),
                )
            )


        if (
            "price claim"
            in value
            or "preco promocional"
            in value
        ):

            findings.append(
                _finding(
                    field_name=field_name,
                    category=(
                        "price_discount"
                    ),
                    claim_text=(
                        "price claim"
                    ),
                )
            )


        if "stock claim" in value:

            findings.append(
                _finding(
                    field_name=field_name,
                    category=(
                        "availability_scarcity"
                    ),
                    claim_text=(
                        "stock claim"
                    ),
                )
            )


        if "unsupported benefit" in value:

            findings.append(
                _finding(
                    field_name=field_name,
                    category=(
                        "product_benefit"
                    ),
                    claim_text=(
                        "unsupported benefit"
                    ),
                )
            )


    return claims_audit.ClaimAuditResult(
        findings=findings
    )


@pytest.fixture
def context(
    monkeypatch,
):

    audit_events = []

    db = SimpleNamespace()

    campaign = SimpleNamespace(
        id="campaign-before-after-test"
    )

    brand = SimpleNamespace()

    product = SimpleNamespace(
        id="product-before-after-test"
    )


    monkeypatch.setattr(
        orchestrator,
        "resolve_verified_product_facts",
        lambda *args, **kwargs:
            SimpleNamespace(),
    )


    monkeypatch.setattr(
        claims_audit,
        "audit_text_fields",
        lambda *,
        fields,
        verified,
        brand:
            _result_for_fields(
                fields
            ),
    )


    monkeypatch.setattr(
        orchestrator,
        "_audit",
        lambda db,
        campaign_id,
        event_type,
        payload:
            audit_events.append(
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
        audit_events,
    )


@pytest.mark.parametrize(
    "field_name",
    [
        "design_concept",
        "visual_prompt",
        "template_suggestion",
        "tone_notes",
    ],
)
def test_each_creative_brief_field_is_repaired_independently(
    context,
    field_name,
):

    (
        db,
        campaign,
        brand,
        product,
        audit_events,
    ) = context


    original = _brief()

    values = {
        "design_concept":
            original.design_concept,

        "visual_prompt":
            original.visual_prompt,

        "template_suggestion":
            original.template_suggestion,

        "tone_notes":
            original.tone_notes,
    }

    values[
        field_name
    ] = "before/after"


    contaminated = _brief(
        **values
    )


    repaired = (
        orchestrator
        ._neutralize_creative_brief_before_after_only(
            db,
            campaign=campaign,
            brand=brand,
            product=product,
            creative_brief=contaminated,
        )
    )


    assert repaired is not contaminated


    for candidate_field in (
        "design_concept",
        "visual_prompt",
        "template_suggestion",
        "tone_notes",
    ):

        if (
            candidate_field
            == field_name
        ):

            assert (
                getattr(
                    repaired,
                    candidate_field,
                )
                != getattr(
                    contaminated,
                    candidate_field,
                )
            )

        else:

            assert (
                getattr(
                    repaired,
                    candidate_field,
                )
                == getattr(
                    contaminated,
                    candidate_field,
                )
            )


    assert len(
        audit_events
    ) == 1

    _, event_type, payload = (
        audit_events[0]
    )

    assert (
        event_type
        == "creative_brief_before_after_fields_locally_neutralized"
    )

    assert payload[
        "neutralized_fields"
    ] == [
        field_name
    ]

    assert payload[
        "claim_categories"
    ] == [
        ELIGIBLE_CATEGORY
    ]

    assert (
        payload[
            "provider_calls"
        ]
        == 0
    )

    assert (
        payload[
            "model_calls"
        ]
        == 0
    )

    assert (
        payload[
            "network_calls"
        ]
        == 0
    )

    assert (
        payload[
            "research_calls"
        ]
        == 0
    )

    assert (
        payload[
            "image_calls"
        ]
        == 0
    )

    assert (
        payload[
            "full_grounding_gate_required_after_repair"
        ]
        is True
    )


def test_exact_visual_prompt_before_after_is_neutralized(
    context,
):

    (
        db,
        campaign,
        brand,
        product,
        audit_events,
    ) = context


    brief = _brief(
        visual_prompt="before/after"
    )


    repaired = (
        orchestrator
        ._neutralize_creative_brief_before_after_only(
            db,
            campaign=campaign,
            brand=brand,
            product=product,
            creative_brief=brief,
        )
    )


    assert (
        repaired.visual_prompt
        == orchestrator
        ._BUILD6R_NEUTRAL_BEFORE_AFTER_VISUAL_PROMPT
    )


    lower = (
        repaired
        .visual_prompt
        .lower()
    )


    forbidden = (
        "before/after",
        "before and after",
        "transformation",
        "guaranteed result",
        "visible result",
        "#1",
        "bestseller",
        "price",
        "discount",
        "stock",
        "availability",
        "certification",
        "testimonial",
        "clinical proof",
        "ingredient action",
    )


    assert all(
        token not in lower
        for token
        in forbidden
    )


def test_clean_brief_is_unchanged(
    context,
):

    (
        db,
        campaign,
        brand,
        product,
        audit_events,
    ) = context


    brief = _brief()


    repaired = (
        orchestrator
        ._neutralize_creative_brief_before_after_only(
            db,
            campaign=campaign,
            brand=brand,
            product=product,
            creative_brief=brief,
        )
    )


    assert repaired is brief
    assert audit_events == []


def test_mixed_before_after_and_ranking_remains_fail_closed(
    context,
):

    (
        db,
        campaign,
        brand,
        product,
        audit_events,
    ) = context


    brief = _brief(
        visual_prompt=(
            "before/after with #1 bestseller"
        )
    )


    repaired = (
        orchestrator
        ._neutralize_creative_brief_before_after_only(
            db,
            campaign=campaign,
            brand=brand,
            product=product,
            creative_brief=brief,
        )
    )


    assert repaired is brief
    assert audit_events == []


def test_before_after_plus_unknown_ingredient_remains_fail_closed(
    context,
):

    (
        db,
        campaign,
        brand,
        product,
        audit_events,
    ) = context


    brief = _brief(
        visual_prompt=(
            "before/after with retinol"
        )
    )


    repaired = (
        orchestrator
        ._neutralize_creative_brief_before_after_only(
            db,
            campaign=campaign,
            brand=brand,
            product=product,
            creative_brief=brief,
        )
    )


    assert repaired is brief
    assert audit_events == []


def test_noneligible_benefit_category_remains_fail_closed(
    context,
):

    (
        db,
        campaign,
        brand,
        product,
        audit_events,
    ) = context


    brief = _brief(
        visual_prompt=(
            "unsupported benefit"
        )
    )


    repaired = (
        orchestrator
        ._neutralize_creative_brief_before_after_only(
            db,
            campaign=campaign,
            brand=brand,
            product=product,
            creative_brief=brief,
        )
    )


    assert repaired is brief
    assert audit_events == []


def test_price_and_stock_categories_remain_fail_closed(
    context,
):

    (
        db,
        campaign,
        brand,
        product,
        audit_events,
    ) = context


    brief = _brief(
        visual_prompt=(
            "price claim and stock claim"
        )
    )


    repaired = (
        orchestrator
        ._neutralize_creative_brief_before_after_only(
            db,
            campaign=campaign,
            brand=brand,
            product=product,
            creative_brief=brief,
        )
    )


    assert repaired is brief
    assert audit_events == []


def test_unknown_ingredient_remains_fail_closed(
    context,
):

    (
        db,
        campaign,
        brand,
        product,
        audit_events,
    ) = context


    brief = _brief(
        visual_prompt=(
            "retinol"
        )
    )


    repaired = (
        orchestrator
        ._neutralize_creative_brief_before_after_only(
            db,
            campaign=campaign,
            brand=brand,
            product=product,
            creative_brief=brief,
        )
    )


    assert repaired is brief
    assert audit_events == []


def test_ranking_only_is_left_for_existing_ranking_helper(
    context,
):

    (
        db,
        campaign,
        brand,
        product,
        audit_events,
    ) = context


    brief = _brief(
        visual_prompt=(
            "#1 bestseller"
        )
    )


    before_after_result = (
        orchestrator
        ._neutralize_creative_brief_before_after_only(
            db,
            campaign=campaign,
            brand=brand,
            product=product,
            creative_brief=brief,
        )
    )


    assert before_after_result is brief


    ranking_result = (
        orchestrator
        ._neutralize_creative_brief_ranking_only(
            db,
            campaign=campaign,
            brand=brand,
            product=product,
            creative_brief=brief,
        )
    )


    assert ranking_result is not brief

    assert (
        "#1"
        not in ranking_result
        .visual_prompt
    )

    assert (
        "bestseller"
        not in ranking_result
        .visual_prompt
        .lower()
    )


def test_helper_has_no_provider_or_network_boundary():

    source = inspect.getsource(
        orchestrator
        ._neutralize_creative_brief_before_after_only
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
        for marker
        in forbidden
    )


def test_run_copy_stage_orders_bounded_recoveries_before_final_gate():

    source = inspect.getsource(
        orchestrator.run_copy_stage
    )


    ranking_index = source.index(
        "_neutralize_creative_brief_ranking_only("
    )

    before_after_index = source.index(
        "_neutralize_creative_brief_before_after_only("
    )

    final_gate_index = source.index(
        "_enforce_generated_claim_grounding_gate(",
        before_after_index,
    )


    assert (
        ranking_index
        < before_after_index
        < final_gate_index
    )


def test_repaired_brief_passes_existing_full_canonical_gate(
    context,
):

    (
        db,
        campaign,
        brand,
        product,
        audit_events,
    ) = context


    brief = _brief(
        visual_prompt=(
            "before/after"
        )
    )


    repaired = (
        orchestrator
        ._neutralize_creative_brief_before_after_only(
            db,
            campaign=campaign,
            brand=brand,
            product=product,
            creative_brief=brief,
        )
    )


    # This calls the real existing final gate. The patched deterministic
    # audit fixture returns no unsupported findings for the neutral result.
    orchestrator._enforce_generated_claim_grounding_gate(
        db,
        campaign=campaign,
        brand=brand,
        product=product,
        phase="creative_brief",
        root_name="creative_brief",
        value=repaired,
    )
