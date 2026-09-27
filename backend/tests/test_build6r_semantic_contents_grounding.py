from __future__ import annotations

import asyncio
from types import SimpleNamespace

import app.services.claims_audit as claims_audit


FIELD = (
    "creative.creative_brief.visual_prompt"
)


def _verified():
    return SimpleNamespace(
        verified_description=(
            "LuLuLun Hydra EX facial sheet mask, exact 7-sheet "
            "pouch variant. Manufacturer sales name: "
            "Face Mask LuLuLun EX 1FS."
        ),
        verified_usage="",
        verified_size=(
            "7 sheets / essence 150 mL"
        ),
        verified_variant=(
            "Face Mask LuLuLun EX 1FS - 7-sheet pouch"
        ),
        verified_price="",
        verified_availability="",
        verified_country_of_origin="",
        verified_ingredients=[
            (
                "Human adipose-derived mesenchymal cell exosomes "
                "(manufacturer-listed skin-conditioning ingredient; "
                "manufacturer states stem cells are not contained)"
            ),
            "Glutathione",
            "Arbutin",
            "Ascorbyl palmitate (vitamin C derivative)",
            "Human recombinant oligopeptide-1 (EGF)",
            "Ceramide AP",
            "Ceramide NP",
            "Atelocollagen",
            "Hydroxypropyltrimonium hyaluronate",
        ],
        verified_features=[
            "7-sheet pouch variant",
            "Contains 150 mL of essence",
            "Manufacturer sales name: Face Mask LuLuLun EX 1FS",
            "Manufacturer describes the sheet as a Melty Feel Sheet",
            "Colorant-free",
            "Fragrance-free",
            "Mineral-oil-free",
            "Alcohol-free",
        ],
        verified_benefits=[],
        verified_claims=[
            "7-sheet pouch containing 150 mL of essence",
            (
                "Contains human adipose-derived mesenchymal cell "
                "exosomes as a manufacturer-listed skin-conditioning "
                "ingredient; manufacturer states stem cells are not contained"
            ),
            (
                "Contains glutathione, arbutin, and the vitamin C "
                "derivative ascorbyl palmitate"
            ),
            (
                "Contains Ceramide AP, Ceramide NP, atelocollagen, "
                "hydroxypropyltrimonium hyaluronate, and human "
                "recombinant oligopeptide-1"
            ),
            (
                "Manufacturer states the formula is colorant-free, "
                "fragrance-free, mineral-oil-free, and alcohol-free"
            ),
        ],
    )


def _finding(
    text,
    category="ingredients/contents",
    source_field="ai_extracted_candidate",
):
    return claims_audit.ClaimFinding(
        claim_text=text,
        claim_category=category,
        source_field=source_field,
        evidence_status="UNSUPPORTED",
        allowed_source="",
        reason="synthetic unsupported",
    )


def _reconcile(
    text,
    category="ingredients/contents",
):
    result = claims_audit.ClaimAuditResult(
        findings=[
            _finding(
                text,
                category,
            )
        ]
    )

    return (
        claims_audit
        ._build6r_reconcile_semantic_contents_findings(
            result,
            _verified(),
        )
        .findings[0]
    )


def test_verified_portuguese_ingredient_bundle_is_supported():
    finding = _reconcile(
        (
            "ingredientes como exossomos de origem adiposa humana "
            "para condicionamento da pele, glutathione, arbutin, "
            "derivado de vitamina C, ceramidas, atelocollagen e "
            "hydroxypropyltrimonium hyaluronate"
        )
    )

    assert finding.evidence_status == "SUPPORTED"


def test_verified_portuguese_free_from_bundle_is_supported():
    finding = _reconcile(
        (
            "formula sem corantes, fragrancia, "
            "oleo mineral e alcool"
        )
    )

    assert finding.evidence_status == "SUPPORTED"


def test_verified_package_without_origin_inference_is_supported():
    finding = _reconcile(
        (
            "LuLuLun Hydra EX e o pouch com "
            "7 sheet masks e 150 mL de essencia"
        )
    )

    assert finding.evidence_status == "SUPPORTED"


def test_unverified_japanese_origin_keeps_package_candidate_blocked():
    finding = _reconcile(
        (
            "LuLuLun Hydra EX e o pouch japones com "
            "7 sheet masks e 150 mL de essencia"
        )
    )

    assert finding.evidence_status == "UNSUPPORTED"


def test_unknown_niacinamide_stays_blocked():
    finding = _reconcile(
        "ingredientes como glutathione e niacinamide"
    )

    assert finding.evidence_status == "UNSUPPORTED"


def test_unknown_retinol_stays_blocked():
    finding = _reconcile(
        "ingredientes como arbutin e retinol"
    )

    assert finding.evidence_status == "UNSUPPORTED"


def test_unknown_bakuchiol_stays_blocked():
    finding = _reconcile(
        "ingredientes como glutathione e bakuchiol"
    )

    assert finding.evidence_status == "UNSUPPORTED"


def test_positive_fragrance_claim_cannot_invert_fragrance_free_fact():
    finding = _reconcile(
        "formula com fragrancia"
    )

    assert finding.evidence_status == "UNSUPPORTED"


def test_research_recommendation_category_is_never_semantically_whitelisted():
    finding = _reconcile(
        (
            "Guias internacionais de J-beauty citam a Hydra EX "
            "entre as linhas recomendadas para hidratacao"
        ),
        "clinical/scientific/expert endorsement",
    )

    assert finding.evidence_status == "UNSUPPORTED"


def test_unverified_benefit_flourish_is_never_semantically_whitelisted():
    finding = _reconcile(
        "E literalmente muita formula dividida em 7 paninhos",
        "product benefits/effects",
    )

    assert finding.evidence_status == "UNSUPPORTED"


def test_exact_source_field_is_recovered():
    fields = {
        FIELD:
            "Do not show a bestseller badge",
        "copy.headline":
            "Rotina simples",
    }

    result = claims_audit.ClaimAuditResult(
        findings=[
            _finding(
                "bestseller",
                "ranking_bestseller",
            )
        ]
    )

    recovered = (
        claims_audit
        ._build6r_recover_semantic_candidate_source_fields(
            result,
            fields,
        )
    )

    assert (
        recovered.findings[0].source_field
        == FIELD
    )


def test_real_semantic_wrapper_filters_negated_bestseller_after_source_recovery(
    monkeypatch,
):
    async def fake_previous(
        *args,
        **kwargs,
    ):
        return claims_audit.ClaimAuditResult(
            findings=[
                _finding(
                    "bestseller",
                    "ranking_bestseller",
                )
            ]
        )

    monkeypatch.setattr(
        claims_audit,
        "_build6r_augment_without_semantic_contents_repair",
        fake_previous,
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
        for finding in result.findings
        if finding.evidence_status == "UNSUPPORTED"
    ]


def test_real_semantic_wrapper_keeps_positive_bestseller_blocked(
    monkeypatch,
):
    async def fake_previous(
        *args,
        **kwargs,
    ):
        return claims_audit.ClaimAuditResult(
            findings=[
                _finding(
                    "bestseller",
                    "ranking_bestseller",
                )
            ]
        )

    monkeypatch.setattr(
        claims_audit,
        "_build6r_augment_without_semantic_contents_repair",
        fake_previous,
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
        finding.evidence_status == "UNSUPPORTED"
        for finding in result.findings
    )


def test_ambiguous_source_field_stays_fail_closed():
    fields = {
        FIELD:
            "bestseller",
        "copy.headline":
            "bestseller",
    }

    result = claims_audit.ClaimAuditResult(
        findings=[
            _finding(
                "bestseller",
                "ranking_bestseller",
            )
        ]
    )

    recovered = (
        claims_audit
        ._build6r_recover_semantic_candidate_source_fields(
            result,
            fields,
        )
    )

    assert (
        recovered.findings[0].source_field
        == "ai_extracted_candidate"
    )
