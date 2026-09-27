from __future__ import annotations

from types import SimpleNamespace

from app.services.claims_audit import (
    _evaluate,
    _verified_evidence_text,
    audit_text_fields,
)


def _verified(
    ingredients: list[str],
):
    return SimpleNamespace(
        verified_description="",
        verified_usage="",
        verified_size="",
        verified_variant="",
        verified_price="",
        verified_availability="",
        verified_country_of_origin="",
        verified_ingredients=ingredients,
        verified_features=[],
        verified_benefits=[],
        verified_claims=[],
    )


def _evaluate_ingredient(
    claim: str,
    verified,
):
    return _evaluate(
        claim,
        "percentage_or_ingredient",
        "master_concept.must_include[0]",
        _verified_evidence_text(
            verified
        ),
        "",
    )


def test_two_distinct_verified_ceramide_subtypes_support_generic_plural():
    verified = _verified(
        [
            "Ceramide AP",
            "Ceramide NP",
        ]
    )

    evidence = _verified_evidence_text(
        verified
    )

    assert "ceramide ap" in evidence
    assert "ceramide np" in evidence
    assert "ceramides" in evidence

    finding = _evaluate_ingredient(
        "ceramides",
        verified,
    )

    assert (
        finding.evidence_status
        == "SUPPORTED"
    )

    assert (
        finding.allowed_source
        == "verified_product_facts"
    )


def test_generic_ceramide_plural_passes_full_deterministic_audit():
    verified = _verified(
        [
            "Ceramide AP",
            "Ceramide NP",
        ]
    )

    result = audit_text_fields(
        fields={
            "master_concept.must_include[0]":
                "ceramides",
        },
        verified=verified,
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


def test_one_verified_ceramide_subtype_does_not_entail_plural():
    verified = _verified(
        [
            "Ceramide AP",
        ]
    )

    evidence = _verified_evidence_text(
        verified
    )

    assert "ceramides" not in evidence

    finding = _evaluate_ingredient(
        "ceramides",
        verified,
    )

    assert (
        finding.evidence_status
        == "UNSUPPORTED"
    )


def test_duplicate_ceramide_subtype_does_not_entail_plural():
    verified = _verified(
        [
            "Ceramide AP",
            "Ceramide AP",
        ]
    )

    evidence = _verified_evidence_text(
        verified
    )

    assert "ceramides" not in evidence

    finding = _evaluate_ingredient(
        "ceramides",
        verified,
    )

    assert (
        finding.evidence_status
        == "UNSUPPORTED"
    )


def test_unrelated_ingredient_remains_unsupported():
    verified = _verified(
        [
            "Ceramide AP",
            "Ceramide NP",
        ]
    )

    finding = _evaluate_ingredient(
        "niacinamide",
        verified,
    )

    assert (
        finding.evidence_status
        == "UNSUPPORTED"
    )


def test_retinol_remains_unsupported():
    verified = _verified(
        [
            "Ceramide AP",
            "Ceramide NP",
        ]
    )

    finding = _evaluate_ingredient(
        "retinol",
        verified,
    )

    assert (
        finding.evidence_status
        == "UNSUPPORTED"
    )


def test_hyphenated_ceramide_free_text_does_not_create_family_alias():
    verified = _verified(
        [
            "Ceramide-free",
            "Other ingredient",
        ]
    )

    evidence = _verified_evidence_text(
        verified
    )

    assert "ceramides" not in evidence

    finding = _evaluate_ingredient(
        "ceramides",
        verified,
    )

    assert (
        finding.evidence_status
        == "UNSUPPORTED"
    )
