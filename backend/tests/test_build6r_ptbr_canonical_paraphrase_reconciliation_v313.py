from __future__ import annotations

import asyncio
import inspect
from types import SimpleNamespace

import pytest

import app.services.claims_audit as claims_audit


LIVE_FINDINGS = (
    (
        "Cada pouch tem 150 mL de essência",
        "ai_extracted_candidate",
    ),
    (
        (
            "O próprio fabricante afirma que não há "
            "células-tronco nesse ingrediente"
        ),
        "ai_extracted_candidate",
    ),
    (
        (
            "Desdobrar a máscara e encaixar em volta "
            "dos olhos e da boca"
        ),
        "ai_extracted_candidate",
    ),
    (
        "Pressionar o ar preso para fora",
        "ai_extracted_candidate",
    ),
    (
        (
            "Elevar os cortes da região da bochecha "
            "ao longo da linha do rosto"
        ),
        "ai_extracted_candidate",
    ),
    (
        (
            "Em seguida, pressionar a máscara inteira "
            "no rosto com as palmas das mãos"
        ),
        "ai_extracted_candidate",
    ),
    (
        (
            "Depois de retirar, o fabricante sugere "
            "dobrar a máscara para usar para "
            "“wiping/light patting” (passadas leves) "
            "e seguir com emulsão ou creme"
        ),
        "ai_extracted_candidate",
    ),
    (
        "150 mL de essência no total",
        "copy.pt-BR.caption",
    ),
    (
        (
            "O próprio fabricante afirma que esse "
            "ingrediente não contém células-tronco"
        ),
        "copy.pt-BR.caption",
    ),
    (
        (
            "Pode ser usada de manhã ou à noite no "
            "lugar do tônico (de acordo com o fabricante)"
        ),
        "copy.pt-BR.caption",
    ),
    (
        "Pouch com 7 sheet masks e 150 mL de essência",
        "creative.creative_brief.template_suggestion",
    ),
    (
        (
            "Características de fórmula: colorant-free, "
            "fragrance-free, mineral-oil-free, alcohol-free"
        ),
        "creative.creative_brief.template_suggestion",
    ),
)


NEGATIVE_CASES = (
    "Este produto hidrata profundamente a pele",
    "Clinicamente comprovado para rejuvenescer",
    "Produto número 1 no Japão",
    "Mais vendido da categoria",
    "Agora por 990 ienes",
    "Este produto contém células-tronco",
    "Resultados garantidos em 7 dias",
)


def _verified():
    return SimpleNamespace(
        verified_description=(
            "LuLuLun Hydra EX facial sheet mask, exact "
            "7-sheet pouch variant. Manufacturer sales name: "
            "Face Mask LuLuLun EX 1FS."
        ),

        verified_usage=(
            "Manufacturer usage guidance: unfold the mask and fit it "
            "around the eyes and mouth, press out trapped air, lift "
            "the cheek cut sections along the face line, then press "
            "the whole mask into place with the palms. After removal, "
            "the manufacturer suggests folding the mask for "
            "wiping/light patting and following with an emulsion or "
            "cream. Manufacturer describes it as usable morning or "
            "evening in place of toner."
        ),

        verified_size=(
            "7 sheets / essence 150 mL"
        ),

        verified_variant=(
            "Face Mask LuLuLun EX 1FS - 7-sheet pouch"
        ),

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
            (
                "Contains human adipose-derived mesenchymal "
                "cell exosomes as a manufacturer-listed "
                "skin-conditioning ingredient; manufacturer "
                "states stem cells are not contained"
            ),
        ],

        verified_ingredients=[
            (
                "Human adipose-derived mesenchymal cell "
                "exosomes (manufacturer-listed "
                "skin-conditioning ingredient; manufacturer "
                "states stem cells are not contained)"
            ),
        ],

        verified_benefits=[],
    )


def _finding(
    text,
    source_field,
):
    return claims_audit.ClaimFinding(
        claim_text=text,
        claim_category="synthetic",
        source_field=source_field,
        evidence_status="UNSUPPORTED",
        allowed_source="",
        reason="pre-v313",
    )


@pytest.mark.parametrize(
    "text,source_field",
    LIVE_FINDINGS,
)
def test_v313_all_12_exact_live_false_negatives_are_supported(
    text,
    source_field,
):
    assert (
        claims_audit
        ._build6r_v313_copy_stage_claim_supported(
            text,
            _verified(),
        )
    )

    assert (
        claims_audit
        ._build6r_v313_finding_supported(
            _finding(
                text,
                source_field,
            ),
            _verified(),
        )
    )


@pytest.mark.parametrize(
    "text",
    NEGATIVE_CASES,
)
def test_v313_required_negative_cases_fail_closed(
    text,
):
    assert not (
        claims_audit
        ._build6r_v313_copy_stage_claim_supported(
            text,
            _verified(),
        )
    )


def test_v313_unknown_factual_residue_fails_closed():
    assert not (
        claims_audit
        ._build6r_v313_copy_stage_claim_supported(
            (
                "150 mL de essência no total "
                "e hidrata profundamente a pele"
            ),
            _verified(),
        )
    )


def test_v313_quantity_requires_canonical_backing():
    verified = _verified()

    verified.verified_size = ""

    verified.verified_features = [
        item
        for item in verified.verified_features
        if "150 mL" not in item
    ]

    verified.verified_claims = [
        item
        for item in verified.verified_claims
        if "150 mL" not in item
    ]

    assert not (
        claims_audit
        ._build6r_v313_copy_stage_claim_supported(
            "Cada pouch tem 150 mL de essência",
            verified,
        )
    )


def test_v313_stem_cell_negation_requires_canonical_backing():
    verified = _verified()

    verified.verified_ingredients = []

    verified.verified_claims = [
        item
        for item in verified.verified_claims
        if "stem cells" not in item
    ]

    assert not (
        claims_audit
        ._build6r_v313_copy_stage_claim_supported(
            (
                "O próprio fabricante afirma que "
                "não há células-tronco nesse ingrediente"
            ),
            verified,
        )
    )


def test_v313_usage_requires_canonical_backing():
    verified = _verified()

    verified.verified_usage = ""

    assert not (
        claims_audit
        ._build6r_v313_copy_stage_claim_supported(
            "Pressionar o ar preso para fora",
            verified,
        )
    )


def test_v313_free_from_requires_canonical_backing():
    verified = _verified()

    verified.verified_features = [
        item
        for item in verified.verified_features
        if "free" not in item.lower()
    ]

    assert not (
        claims_audit
        ._build6r_v313_copy_stage_claim_supported(
            (
                "Características de fórmula: colorant-free, "
                "fragrance-free, mineral-oil-free, alcohol-free"
            ),
            verified,
        )
    )


def test_v313_research_source_remains_blocked():
    finding = _finding(
        "150 mL de essência no total",
        "strategy.research_basis[0]",
    )

    assert not (
        claims_audit
        ._build6r_v313_finding_supported(
            finding,
            _verified(),
        )
    )


def test_v313_reconciles_exact_live_findings():
    result = claims_audit.ClaimAuditResult(
        findings=[
            _finding(
                text,
                source_field,
            )
            for text, source_field
            in LIVE_FINDINGS
        ]
    )

    reconciled = (
        claims_audit
        ._build6r_v313_reconcile_copy_stage_canonical_findings(
            result,
            _verified(),
        )
    )

    assert len(
        reconciled.findings
    ) == 12

    assert all(
        finding.evidence_status
        == "SUPPORTED"
        for finding in reconciled.findings
    )

    assert all(
        finding.allowed_source
        == "verified_product_facts"
        for finding in reconciled.findings
    )


def test_v313_existing_supported_finding_is_immutable():
    finding = claims_audit.ClaimFinding(
        claim_text="already supported",
        claim_category="other",
        source_field="copy.pt-BR.caption",
        evidence_status="SUPPORTED",
        allowed_source="verified_product_facts",
        reason="existing",
    )

    result = claims_audit.ClaimAuditResult(
        findings=[finding]
    )

    reconciled = (
        claims_audit
        ._build6r_v313_reconcile_copy_stage_canonical_findings(
            result,
            _verified(),
        )
    )

    assert (
        reconciled.findings[0]
        == finding
    )


def test_v313_wrapper_executes_previous_chain_once(
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
                    "Cada pouch tem 150 mL de essência",
                    "ai_extracted_candidate",
                ),
                _finding(
                    "Este produto contém células-tronco",
                    "ai_extracted_candidate",
                ),
            ]
        )

    monkeypatch.setattr(
        claims_audit,
        "_build6r_augment_before_v313",
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


def test_v313_helpers_are_zero_cost():
    helper_names = (
        "_build6r_v313_source_field_allowed",
        "_build6r_v313_canonical_has",
        "_build6r_v313_consume_one",
        "_build6r_v313_residue_allowed",
        "_build6r_v313_quantity_supported",
        "_build6r_v313_no_stem_cells_supported",
        "_build6r_v313_usage_unfold_supported",
        "_build6r_v313_usage_air_supported",
        "_build6r_v313_usage_cheeks_supported",
        "_build6r_v313_usage_palms_supported",
        "_build6r_v313_usage_post_removal_supported",
        "_build6r_v313_usage_morning_evening_supported",
        "_build6r_v313_free_from_supported",
        "_build6r_v313_copy_stage_claim_supported",
        "_build6r_v313_finding_supported",
        "_build6r_v313_reconcile_copy_stage_canonical_findings",
    )

    forbidden = (
        "generate_structured",
        "generate_image",
        "edit_image",
        "responses.",
        "images.",
        "httpx",
        "requests.",
    )

    combined = "\n".join(
        inspect.getsource(
            getattr(
                claims_audit,
                name,
            )
        )
        for name in helper_names
    )

    assert all(
        token not in combined
        for token in forbidden
    )

def test_v313_wrapper_preserves_all_sealed_source_contracts():
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
        "_build6r_augment_before_v313",
        "_build6r_v313_reconcile_copy_stage_canonical_findings",
    )

    for marker in markers:
        assert marker in source
