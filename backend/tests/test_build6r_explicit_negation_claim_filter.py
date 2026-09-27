from __future__ import annotations

import asyncio
from types import SimpleNamespace

import app.services.claims_audit as claims_audit


FIELD = (
    "creative.creative_brief.visual_prompt"
)


def _verified(
    ingredients=None,
):
    return SimpleNamespace(
        verified_description="",
        verified_usage="",
        verified_size="",
        verified_variant="",
        verified_price="",
        verified_availability="",
        verified_country_of_origin="",
        verified_ingredients=list(
            ingredients
            or []
        ),
        verified_features=[],
        verified_benefits=[],
        verified_claims=[],
    )


def _unsupported(
    text: str,
):
    result = claims_audit.audit_text_fields(
        fields={
            FIELD:
                text,
        },
        verified=_verified(),
        brand=None,
    )

    return [
        finding
        for finding
        in result.findings
        if (
            finding.evidence_status
            == "UNSUPPORTED"
        )
    ]


def test_real_bestseller_assertion_remains_blocked():
    assert _unsupported(
        "This product is a bestseller"
    )


def test_bare_bestseller_remains_blocked():
    assert _unsupported(
        "bestseller"
    )


def test_no1_bestseller_remains_blocked():
    assert _unsupported(
        "No.1 bestseller"
    )


def test_not_only_bestseller_remains_blocked():
    assert _unsupported(
        "Not only a bestseller, it is the category leader"
    )


def test_negated_do_not_bestseller_instruction_is_not_a_claim():
    assert not _unsupported(
        "Do not show a bestseller badge"
    )


def test_negated_avoid_bestseller_instruction_is_not_a_claim():
    assert not _unsupported(
        "Avoid bestseller claims"
    )


def test_negated_without_bestseller_instruction_is_not_a_claim():
    assert not _unsupported(
        "Premium composition without bestseller badges"
    )


def test_negated_never_bestseller_instruction_is_not_a_claim():
    assert not _unsupported(
        "Never imply bestseller or No.1 status"
    )


def test_portuguese_unicode_negation_is_not_a_claim():
    assert not _unsupported(
        "N\u00e3o usar alega\u00e7\u00e3o de bestseller"
    )


def test_portuguese_ascii_fallback_negation_is_not_a_claim():
    assert not _unsupported(
        "Nao usar alegacao de bestseller"
    )


def test_portuguese_sem_negation_is_not_a_claim():
    assert not _unsupported(
        "Composicao premium sem selo bestseller"
    )


def test_negated_suffix_bestseller_instruction_is_not_a_claim():
    assert not _unsupported(
        "Bestseller badges are prohibited"
    )


def test_mixed_negative_and_positive_occurrences_still_fail_closed():
    assert _unsupported(
        "Do not show a bestseller badge. "
        "This product is a bestseller."
    )


def test_do_not_hide_reversal_remains_blocked():
    assert _unsupported(
        "Do not hide the fact that this product is a bestseller"
    )


def test_unsupported_ingredient_in_negative_instruction_is_not_a_claim():
    assert not _unsupported(
        "Do not claim niacinamide"
    )


def test_real_unsupported_ingredient_remains_blocked():
    assert _unsupported(
        "Contains niacinamide"
    )


def test_existing_ceramide_family_repair_still_passes():

    result = claims_audit.audit_text_fields(
        fields={
            "master_concept.must_include[3]":
                "ceramides",
        },
        verified=_verified(
            [
                "Ceramide AP",
                "Ceramide NP",
            ]
        ),
        brand=None,
    )

    unsupported = [
        finding
        for finding
        in result.findings
        if (
            finding.evidence_status
            == "UNSUPPORTED"
        )
    ]

    assert unsupported == []


def _synthetic_bestseller_result():

    return claims_audit.ClaimAuditResult(
        findings=[
            claims_audit.ClaimFinding(
                claim_text="bestseller",
                claim_category="ranking_bestseller",
                source_field=FIELD,
                evidence_status="UNSUPPORTED",
                allowed_source="",
                reason="synthetic unsupported claim",
            )
        ]
    )


def test_semantic_layer_filters_negated_false_positive(
    monkeypatch,
):

    async def fake_raw(
        *args,
        **kwargs,
    ):
        return _synthetic_bestseller_result()

    monkeypatch.setattr(
        claims_audit,
        "_build6r_augment_without_negation_filter",
        fake_raw,
    )

    result = asyncio.run(
        claims_audit.augment_with_ai_extraction(
            None,
            fields={
                FIELD:
                    "Do not show a bestseller badge",
            },
            verified=_verified(),
            brand=None,
            model="synthetic",
            existing=claims_audit.ClaimAuditResult(
                findings=[]
            ),
        )
    )

    assert not [
        finding
        for finding
        in result.findings
        if (
            finding.evidence_status
            == "UNSUPPORTED"
        )
    ]


def test_semantic_layer_preserves_real_bestseller_claim(
    monkeypatch,
):

    async def fake_raw(
        *args,
        **kwargs,
    ):
        return _synthetic_bestseller_result()

    monkeypatch.setattr(
        claims_audit,
        "_build6r_augment_without_negation_filter",
        fake_raw,
    )

    result = asyncio.run(
        claims_audit.augment_with_ai_extraction(
            None,
            fields={
                FIELD:
                    "This product is a bestseller",
            },
            verified=_verified(),
            brand=None,
            model="synthetic",
            existing=claims_audit.ClaimAuditResult(
                findings=[]
            ),
        )
    )

    assert any(
        finding.evidence_status
        == "UNSUPPORTED"
        for finding
        in result.findings
    )
