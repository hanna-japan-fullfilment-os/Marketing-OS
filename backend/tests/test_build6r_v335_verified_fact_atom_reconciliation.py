from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.schemas.claims_audit import ClaimAuditResult, ClaimFinding
from app.services import claims_audit


def _verified():
    return SimpleNamespace(
        verified_name="LuLuLun Hydra EX Mask 7 Sheets",
        verified_description=(
            "LuLuLun Hydra EX facial sheet mask, exact 7-sheet pouch "
            "variant. Manufacturer sales name: Face Mask LuLuLun EX 1FS."
        ),
        verified_usage=(
            "Manufacturer usage guidance: unfold the mask and fit it around "
            "the eyes and mouth, press out trapped air, lift the cheek cut "
            "sections along the face line, then press the whole mask into "
            "place with the palms. After removal, the manufacturer suggests "
            "folding the mask for wiping/light patting and following with an "
            "emulsion or cream. Manufacturer describes it as usable morning "
            "or evening in place of toner."
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
                "Contains human adipose-derived mesenchymal cell exosomes "
                "as a manufacturer-listed skin-conditioning ingredient; "
                "manufacturer states stem cells are not contained"
            ),
            (
                "Contains glutathione, arbutin, and the vitamin C derivative "
                "ascorbyl palmitate"
            ),
            (
                "Contains Ceramide AP, Ceramide NP, atelocollagen, "
                "hydroxypropyltrimonium hyaluronate, and human recombinant "
                "oligopeptide-1"
            ),
            (
                "Manufacturer states the formula is colorant-free, "
                "fragrance-free, mineral-oil-free, and alcohol-free"
            ),
            "Manufacturer describes the sheet as a Melty Feel Sheet",
        ],
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
    )


def _finding(
    text: str,
    category: str,
    *,
    source: str = "ai_extracted_candidate",
    status: str = "UNSUPPORTED",
):
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


ATTEMPT9_FIXTURES = [
    (
        (
            "Esta máscara facial em folha vem em um pouch com 7 unidades e "
            "150 mL de essência (nome de venda do fabricante: Face Mask "
            "LuLuLun EX 1FS)."
        ),
        "format/quantity",
    ),
    (
        (
            "Na fórmula, o fabricante lista: Oligopeptídeo-1 humano "
            "recombinante (EGF)"
        ),
        "ingredients/composition",
    ),
    (
        (
            "Sobre a estrutura da máscara, o fabricante descreve o tecido "
            "como um “Melty Feel Sheet”"
        ),
        "product/feature",
    ),
    (
        (
            "Modo de uso de acordo com o fabricante: Levantar os recortes "
            "da região das bochechas acompanhando o contorno do rosto."
        ),
        "directions for use",
    ),
]


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
        f"copy.pt-BR.v335_{index}": finding.claim_text
        for index, finding in enumerate(findings, start=1)
    }


def _run_chain(
    findings,
    *,
    fields=None,
    verified=None,
):
    verified_value = _verified() if verified is None else verified
    fields_value = (
        _fields_for(findings)
        if fields is None
        else fields
    )

    result = ClaimAuditResult(findings=list(findings))

    result = claims_audit._build6r_v334_reconcile_result(
        result,
        verified_value,
        fields_value,
    )

    return claims_audit._build6r_v335_reconcile_result(
        result,
        verified_value,
        fields_value,
    )


def test_v335_exact_live_alias_map_only():
    assert claims_audit._BUILD6R_V335_CATEGORY_ALIASES == {
        "format quantity": "format or quantity",
        "ingredients composition": "ingredients or composition",
        "product feature": "product features or attributes",
        "directions for use": "usage or dosage instructions",
    }


def test_v335_attempt9_exact_four_live_findings_supported():
    findings = [
        _finding(text, category)
        for text, category in ATTEMPT9_FIXTURES
    ]
    result = _run_chain(findings)

    assert len(result.findings) == 4
    assert sum(
        item.evidence_status == "SUPPORTED"
        for item in result.findings
    ) == 4
    assert sum(
        item.evidence_status == "UNSUPPORTED"
        for item in result.findings
    ) == 0
    assert all(
        item.allowed_source == "verified_product_facts"
        for item in result.findings
    )


def test_v335_attempt8_six_remain_supported():
    findings = [
        _finding(text, category)
        for text, category in ATTEMPT8_FIXTURES
    ]
    result = _run_chain(findings)

    assert len(result.findings) == 6
    assert sum(
        item.evidence_status == "SUPPORTED"
        for item in result.findings
    ) == 6
    assert sum(
        item.evidence_status == "UNSUPPORTED"
        for item in result.findings
    ) == 0


@pytest.mark.parametrize(
    ("text", "category"),
    [
        (
            (
                "Pouch com 7 unidades, máscara facial em folha, essência "
                "150 mL, Face Mask LuLuLun EX 1FS."
            ),
            "format/quantity",
        ),
        (
            (
                "O fabricante lista Oligopeptídeo-1 humano recombinante "
                "(EGF)."
            ),
            "ingredients/composition",
        ),
        (
            "O fabricante descreve o tecido como Melty Feel Sheet.",
            "product/feature",
        ),
        (
            "Erguer os recortes das bochechas ao longo da linha do rosto.",
            "directions for use",
        ),
    ],
)
def test_v335_bounded_paraphrases_are_not_full_sentence_allowlists(
    text,
    category,
):
    result = _run_chain([_finding(text, category)])
    assert result.findings[0].evidence_status == "SUPPORTED"


@pytest.mark.parametrize(
    ("text", "category"),
    [
        (
            (
                "Esta máscara facial em folha vem em um pouch com 8 unidades "
                "e 150 mL de essência."
            ),
            "format/quantity",
        ),
        (
            (
                "Esta máscara facial em folha vem em um pouch com 7 unidades "
                "e 200 mL de essência."
            ),
            "format/quantity",
        ),
        (
            (
                "Esta máscara facial em folha vem em um pouch com 7 unidades "
                "e 150 mL de essência, nome de venda do fabricante: "
                "Face Mask LuLuLun EX 2FS."
            ),
            "format/quantity",
        ),
        (
            "Na fórmula, o fabricante lista: Retinol",
            "ingredients/composition",
        ),
        (
            (
                "Na fórmula, o fabricante lista: Oligopeptídeo-2 humano "
                "recombinante (EGF)"
            ),
            "ingredients/composition",
        ),
        (
            (
                "Sobre a estrutura da máscara, o fabricante descreve o "
                "tecido como um “Cloud Feel Sheet”"
            ),
            "product/feature",
        ),
        (
            (
                "Modo de uso de acordo com o fabricante: Levantar os recortes "
                "da região das bochechas acompanhando o contorno do rosto "
                "por 20 minutos."
            ),
            "directions for use",
        ),
        (
            (
                "Modo de uso de acordo com o fabricante: Levantar os recortes "
                "da região das bochechas acompanhando o contorno do rosto "
                "duas vezes ao dia."
            ),
            "directions for use",
        ),
        (
            (
                "Sobre a estrutura da máscara, o fabricante descreve o tecido "
                "como um Melty Feel Sheet que trata acne."
            ),
            "product/feature",
        ),
        (
            (
                "Na fórmula, o fabricante lista: Oligopeptídeo-1 humano "
                "recombinante (EGF) e retinol."
            ),
            "ingredients/composition",
        ),
    ],
)
def test_v335_adversarial_fact_residue_fails_closed(
    text,
    category,
):
    result = _run_chain([_finding(text, category)])
    assert result.findings[0].evidence_status == "UNSUPPORTED"


def test_v335_research_only_provenance_fails_closed():
    text, category = ATTEMPT9_FIXTURES[0]
    finding = _finding(
        text,
        category,
        source="research.summary",
    )
    result = _run_chain(
        [finding],
        fields={"research.summary": text},
    )
    assert result.findings[0].evidence_status == "UNSUPPORTED"


def test_v335_ai_provenance_absent_fails_closed():
    text, category = ATTEMPT9_FIXTURES[0]
    result = _run_chain(
        [_finding(text, category)],
        fields={"copy.pt-BR.other": "different text"},
    )
    assert result.findings[0].evidence_status == "UNSUPPORTED"


def test_v335_ai_provenance_ambiguous_fails_closed():
    text, category = ATTEMPT9_FIXTURES[0]
    result = _run_chain(
        [_finding(text, category)],
        fields={
            "copy.pt-BR.one": text,
            "copy.pt-BR.two": text,
        },
    )
    assert result.findings[0].evidence_status == "UNSUPPORTED"


def test_v335_unknown_near_miss_category_fails_closed():
    text, _ = ATTEMPT9_FIXTURES[0]
    result = _run_chain(
        [_finding(text, "format quantities")]
    )
    assert result.findings[0].evidence_status == "UNSUPPORTED"


def test_v335_existing_supported_finding_is_not_downgraded():
    text, category = ATTEMPT9_FIXTURES[0]
    result = _run_chain(
        [_finding(text, category, status="SUPPORTED")]
    )
    assert result.findings[0].evidence_status == "SUPPORTED"
