from __future__ import annotations

import asyncio
import inspect
from types import SimpleNamespace

import app.services.claims_audit as claims_audit


COMPOSED = (
    "Produto de skincare voltado ao rosto e "
    "Formato: pouch com 7 sheet masks, com "
    "150 mL de ess\u00eancia no total"
)


def _verified():
    return SimpleNamespace(
        verified_description=(
            "LuLuLun Hydra EX facial sheet mask, exact "
            "7-sheet pouch variant."
        ),

        verified_usage=(
            "Manufacturer describes it as usable morning or "
            "evening in place of toner."
        ),

        verified_size=
            "7 sheets / essence 150 mL",

        verified_variant=
            "Face Mask LuLuLun EX 1FS",

        verified_features=[
            "7-sheet pouch variant",
            "Contains 150 mL of essence",
            (
                "Manufacturer describes the sheet "
                "as a Melty Feel Sheet"
            ),
            "Colorant-free",
            "Fragrance-free",
            "Mineral-oil-free",
            "Alcohol-free",
        ],

        verified_claims=[
            "7-sheet pouch containing 150 mL of essence",
        ],

        verified_ingredients=[],

        verified_benefits=[],
    )


def _finding(text):
    return claims_audit.ClaimFinding(
        claim_text=text,
        claim_category="synthetic",
        source_field="copy.pt-BR.synthetic",
        evidence_status="UNSUPPORTED",
        allowed_source="",
        reason="pre-v312",
    )


def test_v312_composes_two_distinct_v311_alias_families():
    assert (
        claims_audit
        ._build6r_v312_copy_stage_claim_supported(
            COMPOSED,
            _verified(),
        )
    )


def test_v312_v311_single_alias_does_not_expand():
    text = (
        "Produto de skincare voltado ao rosto"
    )

    assert (
        claims_audit
        ._build6r_v311_copy_stage_claim_supported(
            text,
            _verified(),
        )
    )

    assert not (
        claims_audit
        ._build6r_v312_copy_stage_claim_supported(
            text,
            _verified(),
        )
    )


def test_v312_duplicate_same_family_is_not_composition():
    text = (
        "Produto de skincare voltado ao rosto e "
        "Produto de skincare voltado ao rosto"
    )

    assert not (
        claims_audit
        ._build6r_v312_copy_stage_claim_supported(
            text,
            _verified(),
        )
    )


def test_v312_mixed_new_benefit_fails_closed():
    text = (
        COMPOSED
        + " e hidrata profundamente a pele"
    )

    assert not (
        claims_audit
        ._build6r_v312_copy_stage_claim_supported(
            text,
            _verified(),
        )
    )


def test_v312_unknown_claim_family_fails_closed():
    text = (
        COMPOSED
        + " e agora por 990 ienes"
    )

    assert not (
        claims_audit
        ._build6r_v312_copy_stage_claim_supported(
            text,
            _verified(),
        )
    )


def test_v312_missing_canonical_atom_fails_closed():
    verified = _verified()

    verified.verified_size = ""

    verified.verified_features = [
        item
        for item in verified.verified_features
        if "150 mL" not in item
    ]

    verified.verified_claims = []

    assert not (
        claims_audit
        ._build6r_v312_copy_stage_claim_supported(
            COMPOSED,
            verified,
        )
    )


def test_v312_wrapper_reconciles_only_composition(
    monkeypatch,
):
    calls = {
        "count": 0,
    }

    async def previous(
        *args,
        **kwargs,
    ):
        calls["count"] += 1

        return claims_audit.ClaimAuditResult(
            findings=[
                _finding(
                    COMPOSED
                ),
                _finding(
                    COMPOSED
                    + " e hidrata profundamente a pele"
                ),
            ]
        )

    monkeypatch.setattr(
        claims_audit,
        "_build6r_augment_before_v312",
        previous,
    )

    result = asyncio.run(
        claims_audit.augment_with_ai_extraction(
            None,
            fields={},
            verified=_verified(),
            brand=None,
            model="synthetic",
            existing=
                claims_audit.ClaimAuditResult(
                    findings=[]
                ),
        )
    )

    assert calls["count"] == 1

    assert (
        result.findings[0].evidence_status
        == "SUPPORTED"
    )

    assert (
        result.findings[1].evidence_status
        == "UNSUPPORTED"
    )


def test_v312_existing_supported_finding_is_immutable():
    finding = claims_audit.ClaimFinding(
        claim_text="already supported",
        claim_category="other",
        source_field="copy.pt-BR.caption",
        evidence_status="SUPPORTED",
        allowed_source="verified_product_facts",
        reason="existing",
    )

    result = (
        claims_audit
        ._build6r_v312_reconcile_copy_stage_canonical_findings(
            claims_audit.ClaimAuditResult(
                findings=[
                    finding
                ]
            ),
            _verified(),
        )
    )

    assert (
        result.findings[0]
        == finding
    )


def test_v312_wrapper_preserves_v311_source_contracts():
    source = inspect.getsource(
        claims_audit.augment_with_ai_extraction
    )

    markers = (
        "_build6r_augment_before_v32",
        "_build6r_reconcile_generated_semantic_findings_v32",

        "_build6r_augment_before_v33",
        "_build6r_reconcile_generated_semantic_findings_v33",

        "_build6r_augment_before_v34",
        "_build6r_reconcile_generated_semantic_findings_v34",

        "_build6r_augment_before_v35",
        "_build6r_reconcile_generated_semantic_findings_v35",

        "_build6r_augment_before_v311",
        "_build6r_v311_reconcile_copy_stage_canonical_findings",

        "_build6r_augment_before_v312",
        "_build6r_v312_reconcile_copy_stage_canonical_findings",
    )

    for marker in markers:
        assert (
            marker
            in source
        )


def test_v312_helpers_are_zero_cost():
    source = "\n".join(
        (
            inspect.getsource(
                claims_audit
                ._build6r_v312_copy_stage_claim_supported
            ),

            inspect.getsource(
                claims_audit
                ._build6r_v312_reconcile_copy_stage_canonical_findings
            ),
        )
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
        item not in source
        for item in forbidden
    )
