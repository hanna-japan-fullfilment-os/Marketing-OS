from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.schemas.claims_audit import ClaimAuditResult, ClaimFinding
from app.services import claims_audit


def _verified():
    return SimpleNamespace(
        verified_name="LuLuLun Hydra EX Mask",
        verified_description=(
            "LuLuLun Hydra EX facial sheet mask, exact 7-sheet pouch "
            "variant. Manufacturer sales name: Face Mask LuLuLun EX 1FS."
        ),
        verified_size="7 sheets / essence 150 mL",
        verified_variant="Face Mask LuLuLun EX 1FS - 7-sheet pouch",
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
        verified_claims=[
            "7-sheet pouch containing 150 mL of essence",
            (
                "Contains glutathione, arbutin, and the vitamin C derivative "
                "ascorbyl palmitate"
            ),
            (
                "Contains Ceramide AP, Ceramide NP, atelocollagen, "
                "hydroxypropyltrimonium hyaluronate, and human recombinant "
                "oligopeptide-1"
            ),
        ],
        verified_ingredients=[
            "Glutathione",
            "Arbutin",
            "Ascorbyl palmitate (vitamin C derivative)",
            "Ceramide AP",
            "Ceramide NP",
            "Atelocollagen",
            "Hydroxypropyltrimonium hyaluronate",
            "Human recombinant oligopeptide-1 (EGF)",
        ],
        verified_usage=(
            "Manufacturer usage guidance: unfold the mask and fit it around "
            "the eyes and mouth, press out trapped air, lift the cheek cut "
            "sections along the face line, then press the whole mask into "
            "place with the palms. After removal, the manufacturer suggests "
            "folding the mask for wiping/light patting and following with an "
            "emulsion or cream. Manufacturer describes it as usable morning "
            "or evening in place of toner."
        ),
    )


def _finding(
    text: str,
    category: str,
    source: str = "ai_extracted_candidate",
    status: str = "UNSUPPORTED",
) -> ClaimFinding:
    return ClaimFinding(
        claim_text=text,
        claim_category=category,
        source_field=source,
        evidence_status=status,
        allowed_source=(
            "verified_product_facts"
            if status == "SUPPORTED"
            else ""
        ),
        reason=(
            "preexisting support"
            if status == "SUPPORTED"
            else "No matching text found."
        ),
    )


ATTEMPT8_FIXTURES = [
    (
        (
            "É um pack com 7 máscaras em folha, em um pouch único que "
            "contém 150 mL de essência"
        ),
        "product format/quantity",
    ),
    (
        (
            "Contém glutathiona, arbutin e o derivado de vitamina C "
            "ascorbyl palmitate"
        ),
        "ingredients/contents",
    ),
    (
        (
            "Sobre o formato: são 7 folhas dentro de um único pouch, com "
            "150 mL de essência compartilhados entre elas"
        ),
        "product format/quantity",
    ),
    (
        (
            "Modo de uso, de acordo com o fabricante: 1. Desdobrar a "
            "máscara. 2. Ajustar ao redor dos olhos e da boca. 3. "
            "Pressionar para tirar o ar preso entre a máscara e a pele. "
            "4. Erguer os recortes da região das bochechas ao longo da "
            "linha do rosto. 5. Pressionar a máscara inteira no rosto "
            "usando as palmas das mãos"
        ),
        "usage instructions",
    ),
    (
        (
            "Depois de remover, o fabricante sugere dobrar a máscara para "
            "usar como pano de apoio para leves batidinhas e, em seguida, "
            "finalizar com emulsão ou creme"
        ),
        "usage instructions",
    ),
    (
        (
            "Uso, conforme orientação do fabricante: 1. Desdobrar a máscara "
            "e ajustar ao redor dos olhos e da boca. 2. Pressionar para tirar "
            "o ar preso. 3. Erguer os recortes das bochechas ao longo da "
            "linha do rosto. 4. Pressionar a máscara inteira no rosto com "
            "as palmas. 5. Depois de remover, usar a máscara dobrada para "
            "passar ou dar leves batidinhas. 6. Finalizar com emulsão ou creme"
        ),
        "usage instructions",
    ),
]


def _fields_for(findings):
    return {
        f"copy.pt-BR.v334_attempt8_{index}": finding.claim_text
        for index, finding in enumerate(
            findings,
            start=1,
        )
    }


def _run(
    findings,
    *,
    fields=None,
    verified=None,
):
    result = ClaimAuditResult(
        findings=list(findings)
    )

    return claims_audit._build6r_v334_reconcile_result(
        result,
        (
            _verified()
            if verified is None
            else verified
        ),
        (
            _fields_for(findings)
            if fields is None
            else fields
        ),
    )


def test_v334_exact_alias_map_only():
    assert claims_audit._BUILD6R_V334_CATEGORY_ALIASES == {
        "product format quantity": "format or quantity",
        "ingredients contents": "ingredients or composition",
        "usage instructions": "usage or dosage instructions",
    }


def test_v334_attempt8_exact_six_fixture_all_supported():
    findings = [
        _finding(text, category)
        for text, category in ATTEMPT8_FIXTURES
    ]

    result = _run(findings)

    assert len(findings) == 6
    assert len(result.findings) == 6
    assert sum(
        finding.evidence_status == "SUPPORTED"
        for finding in result.findings
    ) == 6
    assert sum(
        finding.evidence_status == "UNSUPPORTED"
        for finding in result.findings
    ) == 0

    assert all(
        finding.allowed_source == "verified_product_facts"
        for finding in result.findings
    )


def test_v334_product_format_requires_canonical_pouch_quantity_and_format():
    text, category = ATTEMPT8_FIXTURES[0]
    finding = _finding(text, category)

    bad = _verified()
    bad.verified_size = "7 sheets / essence 200 mL"
    bad.verified_claims = [
        "7-sheet pouch containing 200 mL of essence"
    ]
    bad.verified_features = [
        "7-sheet pouch variant",
        "Contains 200 mL of essence",
    ]

    result = _run(
        [finding],
        verified=bad,
    )

    assert result.findings[0].evidence_status == "UNSUPPORTED"


def test_v334_wrong_quantity_fails_closed():
    text = (
        "É um pack com 7 máscaras em folha, em um pouch único que "
        "contém 200 mL de essência"
    )
    finding = _finding(
        text,
        "product format/quantity",
    )

    result = _run([finding])

    assert result.findings[0].evidence_status == "UNSUPPORTED"


def test_v334_unsupported_ingredient_fails_closed():
    text = (
        "Contém glutathiona, arbutin e retinol"
    )
    finding = _finding(
        text,
        "ingredients/contents",
    )

    result = _run([finding])

    assert result.findings[0].evidence_status == "UNSUPPORTED"


def test_v334_invented_usage_duration_fails_closed():
    text = (
        "Modo de uso, de acordo com o fabricante: manter a máscara "
        "por 20 minutos"
    )
    finding = _finding(
        text,
        "usage instructions",
    )

    result = _run([finding])

    assert result.findings[0].evidence_status == "UNSUPPORTED"


@pytest.mark.parametrize(
    "category",
    [
        "future unknown taxonomy",
        "product format quantities",
        "ingredients content",
        "usage instruction",
    ],
)
def test_v334_unknown_and_near_miss_taxonomy_fails_closed(category):
    text = ATTEMPT8_FIXTURES[0][0]
    finding = _finding(
        text,
        category,
    )

    result = _run([finding])

    assert result.findings[0].evidence_status == "UNSUPPORTED"


def test_v334_research_only_source_fails_closed():
    text, category = ATTEMPT8_FIXTURES[0]
    finding = _finding(
        text,
        category,
        source="research.summary",
    )

    result = _run(
        [finding],
        fields={
            "research.summary": text,
        },
    )

    assert result.findings[0].evidence_status == "UNSUPPORTED"


def test_v334_ai_provenance_absent_fails_closed():
    text, category = ATTEMPT8_FIXTURES[0]
    finding = _finding(
        text,
        category,
    )

    result = _run(
        [finding],
        fields={
            "copy.pt-BR.other": "different text",
        },
    )

    assert result.findings[0].evidence_status == "UNSUPPORTED"


def test_v334_ai_provenance_ambiguous_fails_closed():
    text, category = ATTEMPT8_FIXTURES[0]
    finding = _finding(
        text,
        category,
    )

    result = _run(
        [finding],
        fields={
            "copy.pt-BR.one": text,
            "copy.pt-BR.two": text,
        },
    )

    assert result.findings[0].evidence_status == "UNSUPPORTED"


def test_v334_unsupported_compound_residue_fails_closed():
    text = (
        "Contém glutathiona, arbutin, ascorbyl palmitate e retinol"
    )
    finding = _finding(
        text,
        "ingredients/contents",
    )

    result = _run([finding])

    assert result.findings[0].evidence_status == "UNSUPPORTED"


def test_v334_medical_or_efficacy_content_fails_closed():
    text = (
        "Uso, conforme orientação do fabricante: desdobrar a máscara "
        "para tratar acne"
    )
    finding = _finding(
        text,
        "usage instructions",
    )

    result = _run([finding])

    assert result.findings[0].evidence_status == "UNSUPPORTED"


def test_v334_brand_editorial_category_remains_unowned():
    text = (
        "Na Hanna Japan, a proposta é aproximar você dos detalhes."
    )
    finding = _finding(
        text,
        "brand values or practices",
        source="copy.pt-BR.caption",
    )

    result = _run(
        [finding],
        fields={
            "copy.pt-BR.caption": text,
        },
    )

    assert result.findings[0].evidence_status == "UNSUPPORTED"


def test_v334_mixed_visual_composition_fails_closed():
    text = (
        "É um pack com 7 máscaras em folha, em um pouch único que contém "
        "150 mL de essência, sobre fundo rosa com o pouch à esquerda"
    )
    finding = _finding(
        text,
        "product format/quantity",
        source="copy.pt-BR.alt_text",
    )

    result = _run(
        [finding],
        fields={
            "copy.pt-BR.alt_text": text,
        },
    )

    assert result.findings[0].evidence_status == "UNSUPPORTED"


def test_v334_existing_supported_finding_not_downgraded():
    text, category = ATTEMPT8_FIXTURES[0]
    finding = _finding(
        text,
        category,
        status="SUPPORTED",
    )

    result = _run([finding])

    assert result.findings[0].evidence_status == "SUPPORTED"


def test_v334_recognized_but_unsupported_alias_has_bounded_diagnostic():
    text = (
        "É um pack com 7 máscaras em folha, em um pouch único que "
        "contém 200 mL de essência"
    )

    finding = _finding(
        text,
        "product format/quantity",
        source="copy.pt-BR.caption",
    )

    result = _run(
        [finding],
        fields={
            "copy.pt-BR.caption": text,
        },
    )

    diagnostics = (
        claims_audit.build6r_v334_claim_diagnostics(
            result
        )
    )

    assert len(diagnostics) == 1
    assert diagnostics[0]["normalized_category"] == "product format quantity"
    assert diagnostics[0]["v334_canonical_category"] == "format or quantity"
    assert diagnostics[0]["v334_owner"] == (
        "V3.33_CANONICAL_PRODUCT_FACT_EVIDENCE"
    )


def test_v334_public_augment_wrapper_runs_after_sealed_chain():
    text, category = ATTEMPT8_FIXTURES[1]
    finding = _finding(
        text,
        category,
    )

    async def fake_prior(*args, **kwargs):
        return ClaimAuditResult(
            findings=[finding]
        )

    original = (
        claims_audit._build6r_augment_before_v334
    )

    claims_audit._build6r_augment_before_v334 = fake_prior

    try:
        result = asyncio.run(
            claims_audit.augment_with_ai_extraction(
                verified=_verified(),
                fields={
                    "copy.pt-BR.integration": text,
                },
            )
        )
    finally:
        claims_audit._build6r_augment_before_v334 = original

    assert result.findings[0].evidence_status == "SUPPORTED"
