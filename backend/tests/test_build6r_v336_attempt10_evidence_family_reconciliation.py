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
        provenance="manufacturer_official+owner_confirmed",
    )


def _finding(
    text: str,
    category: str,
    source: str,
    *,
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


ATTEMPT10_FIXTURES = [
    (
        (
            "Ingredientes em destaque (todos listados pelo fabricante) – "
            "Exossomos derivados de células mesenquimais de tecido adiposo "
            "humano como ingrediente de condicionamento da pele"
        ),
        "ingredient/functional role",
        "ai_extracted_candidate",
    ),
    (
        (
            "O fabricante informa que não há células-tronco contidas "
            "nesse ingrediente"
        ),
        "scientific/technical claim",
        "ai_extracted_candidate",
    ),
    (
        (
            "O que a fórmula NÃO tem (segundo o fabricante) – Sem corante – "
            "Sem fragrância – Sem óleo mineral – Sem álcool"
        ),
        "free-from/absence claim",
        "ai_extracted_candidate",
    ),
    (
        (
            "Tudo acima vem diretamente do que o fabricante descreve para "
            "esta versão de 7 folhas"
        ),
        "provenance/substantiation statement",
        "ai_extracted_candidate",
    ),
    (
        (
            "Ingredientes citados pelo fabricante – Human adipose-derived "
            "mesenchymal cell exosomes como ingrediente de condicionamento "
            "da pele"
        ),
        "ingredient/functional role",
        "ai_extracted_candidate",
    ),
    (
        (
            "O que NÃO entra na fórmula, segundo o fabricante – Sem corante – "
            "Sem fragrância – Sem óleo mineral – Sem álcool"
        ),
        "free-from/absence claim",
        "ai_extracted_candidate",
    ),
    (
        (
            "Nenhuma promessa de resultado aparece na imagem, apenas o "
            "produto em destaque e texto discreto identificando nome e "
            "quantidade"
        ),
        "marketing/positioning claim",
        "copy.pt-BR.alt_text",
    ),
    (
        (
            "Sempre que se tratar de exossomos, a informação vem junto com "
            "a qualificação de que o fabricante indica não conter "
            "células-tronco"
        ),
        "scientific/technical claim",
        "master_concept.visual_story_system",
    ),
    (
        (
            "Apresentar human adipose-derived mesenchymal cell exosomes "
            "como ingrediente de condicionamento da pele listado pelo "
            "fabricante, junto com a informação de que o fabricante indica "
            "que esses exossomos não contêm células-tronco"
        ),
        "ingredient/functional role",
        "master_concept.story_beats[3]",
    ),
    (
        (
            "organizar em lista clara os demais ingredientes verificados: "
            "glutathione, arbutin, ascorbyl palmitate (derivado de vitamina C), "
            "human recombinant oligopeptide-1 (EGF), ceramide AP, ceramide NP, "
            "atelocollagen e hydroxypropyltrimonium hyaluronate"
        ),
        "ingredient presence",
        "master_concept.story_beats[4]",
    ),
    (
        (
            "Características da fórmula: em um quadro separado, listar que, "
            "segundo o fabricante, a formulação é colorant-free, "
            "fragrance-free, mineral-oil-free e alcohol-free"
        ),
        "free-from/absence claim",
        "master_concept.story_beats[5]",
    ),
    (
        (
            "Descrição da folha: mencionar em destaque textual que o "
            "fabricante descreve a sheet como Melty Feel Sheet"
        ),
        "product feature/description",
        "master_concept.story_beats[6]",
    ),
    (
        (
            "Listar claramente os ingredientes destacados que são "
            "verificados: human adipose-derived mesenchymal cell exosomes "
            "(com a observação de que o fabricante indica não conter "
            "células-tronco), glutathione, arbutin, ascorbyl palmitate "
            "(derivado de vitamina C), human recombinant oligopeptide-1 "
            "(EGF), ceramide AP, ceramide NP, atelocollagen e "
            "hydroxypropyltrimonium hyaluronate"
        ),
        "ingredient presence",
        "master_concept.proof_or_demo_strategy",
    ),
    (
        (
            "Apresentar os pontos verificados sobre a fórmula: colorant-free, "
            "fragrance-free, mineral-oil-free e alcohol-free"
        ),
        "free-from/absence claim",
        "master_concept.proof_or_demo_strategy",
    ),
]


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


def _attempt10_fields(findings):
    ai_claims = [
        finding.claim_text
        for finding in findings
        if finding.source_field == "ai_extracted_candidate"
    ]

    fields = {
        "copy.pt-BR.body": " | ".join(ai_claims),
    }

    for finding in findings:
        if finding.source_field == "ai_extracted_candidate":
            continue

        fields[finding.source_field] = finding.claim_text

    return fields


def _generic_fields(findings):
    return {
        f"copy.pt-BR.fixture_{index}": finding.claim_text
        for index, finding in enumerate(findings, start=1)
    }


def _run_chain(
    findings,
    *,
    verified=None,
    fields=None,
):
    verified_value = (
        _verified()
        if verified is None
        else verified
    )

    fields_value = (
        _generic_fields(findings)
        if fields is None
        else fields
    )

    result = ClaimAuditResult(
        findings=list(findings)
    )

    result = claims_audit._build6r_v334_reconcile_result(
        result,
        verified_value,
        fields_value,
    )

    result = claims_audit._build6r_v335_reconcile_result(
        result,
        verified_value,
        fields_value,
    )

    return claims_audit._build6r_v336_reconcile_result(
        result,
        verified_value,
        fields_value,
    )


def test_v336_exact_route_map_is_bounded():
    assert claims_audit._BUILD6R_V336_CATEGORY_ROUTES == {
        "ingredient functional role": "ingredient_family",
        "ingredient presence": "ingredient_presence",
        "scientific technical claim": "technical_qualification",
        "free from absence claim": "free_from",
        "product feature description": "product_feature",
        "marketing positioning claim": "nonfactual_editorial",
        "provenance substantiation statement": "collective_provenance",
    }


def test_v336_attempt10_exact_14_fixture_corpus_reaches_zero_hard_fails():
    findings = [
        _finding(text, category, source)
        for text, category, source in ATTEMPT10_FIXTURES
    ]

    result = _run_chain(
        findings,
        fields=_attempt10_fields(findings),
    )

    assert len(result.findings) == 14
    assert sum(
        item.evidence_status == "SUPPORTED"
        for item in result.findings
    ) == 14
    assert sum(
        item.evidence_status == "UNSUPPORTED"
        for item in result.findings
    ) == 0

    assert (
        result.findings[6].allowed_source
        == "nonfactual_editorial"
    )

    assert (
        "all_same_context_factual_siblings_grounded"
        in result.findings[3].reason
    )


def test_v336_attempt9_four_remain_supported():
    findings = [
        _finding(
            text,
            category,
            "ai_extracted_candidate",
        )
        for text, category in ATTEMPT9_FIXTURES
    ]

    result = _run_chain(
        findings,
        fields=_generic_fields(findings),
    )

    assert sum(
        item.evidence_status == "SUPPORTED"
        for item in result.findings
    ) == 4
    assert sum(
        item.evidence_status == "UNSUPPORTED"
        for item in result.findings
    ) == 0


def test_v336_attempt8_six_remain_supported():
    findings = [
        _finding(
            text,
            category,
            "ai_extracted_candidate",
        )
        for text, category in ATTEMPT8_FIXTURES
    ]

    result = _run_chain(
        findings,
        fields=_generic_fields(findings),
    )

    assert sum(
        item.evidence_status == "SUPPORTED"
        for item in result.findings
    ) == 6
    assert sum(
        item.evidence_status == "UNSUPPORTED"
        for item in result.findings
    ) == 0


@pytest.mark.parametrize(
    ("text", "category", "source"),
    [
        (
            (
                "Plant-derived exosomes como ingrediente de condicionamento "
                "da pele listado pelo fabricante"
            ),
            "ingredient/functional role",
            "master_concept.story_beats[3]",
        ),
        (
            (
                "Human adipose-derived mesenchymal cell exosomes como "
                "ingrediente de condicionamento da pele que reduz rugas"
            ),
            "ingredient/functional role",
            "master_concept.story_beats[3]",
        ),
        (
            (
                "O fabricante informa que esse ingrediente contém "
                "células-tronco"
            ),
            "scientific/technical claim",
            "master_concept.visual_story_system",
        ),
        (
            "O produto não contém células-tronco",
            "scientific/technical claim",
            "master_concept.visual_story_system",
        ),
        (
            (
                "organizar em lista clara os ingredientes verificados: "
                "glutathione, arbutin e retinol"
            ),
            "ingredient presence",
            "master_concept.story_beats[4]",
        ),
        (
            (
                "organizar em lista clara os ingredientes verificados: "
                "glutathion, arbutin"
            ),
            "ingredient presence",
            "master_concept.story_beats[4]",
        ),
        (
            "Sem corante e paraben-free",
            "free-from/absence claim",
            "master_concept.story_beats[5]",
        ),
        (
            "Sem fragrância e silicone-free",
            "free-from/absence claim",
            "master_concept.story_beats[5]",
        ),
        (
            (
                "Descrição da folha: mencionar que o fabricante descreve "
                "a sheet como Cloud Feel Sheet"
            ),
            "product feature/description",
            "master_concept.story_beats[6]",
        ),
        (
            (
                "Descrição da folha: mencionar Melty Feel Sheet que reduz "
                "rugas"
            ),
            "product feature/description",
            "master_concept.story_beats[6]",
        ),
        (
            (
                "Nenhuma promessa de resultado aparece na imagem, apenas o "
                "produto com hidratação profunda"
            ),
            "marketing/positioning claim",
            "copy.pt-BR.alt_text",
        ),
        (
            "Glutathione",
            "ingredient presences",
            "master_concept.story_beats[4]",
        ),
    ],
)
def test_v336_adversarial_content_or_taxonomy_fails_closed(
    text,
    category,
    source,
):
    result = _run_chain(
        [_finding(text, category, source)],
        fields={source: text},
    )

    assert result.findings[0].evidence_status == "UNSUPPORTED"


def test_v336_exosome_role_requires_canonical_skin_conditioning_role():
    verified = _verified()

    verified.verified_ingredients = [
        item.replace(
            "manufacturer-listed skin-conditioning ingredient; ",
            "",
        )
        for item in verified.verified_ingredients
    ]

    text, category, source = ATTEMPT10_FIXTURES[0]

    result = _run_chain(
        [_finding(text, category, source)],
        verified=verified,
        fields={"copy.pt-BR.body": text},
    )

    assert result.findings[0].evidence_status == "UNSUPPORTED"


def test_v336_collective_provenance_fails_with_unsupported_same_context_sibling():
    good = _finding(
        ATTEMPT10_FIXTURES[0][0],
        ATTEMPT10_FIXTURES[0][1],
        "ai_extracted_candidate",
    )

    bad = _finding(
        "ingredientes verificados: glutathione e retinol",
        "ingredient presence",
        "ai_extracted_candidate",
    )

    provenance = _finding(
        ATTEMPT10_FIXTURES[3][0],
        ATTEMPT10_FIXTURES[3][1],
        "ai_extracted_candidate",
    )

    findings = [
        good,
        bad,
        provenance,
    ]

    result = _run_chain(
        findings,
        fields={
            "copy.pt-BR.body": " | ".join(
                item.claim_text
                for item in findings
            )
        },
    )

    assert result.findings[0].evidence_status == "SUPPORTED"
    assert result.findings[1].evidence_status == "UNSUPPORTED"
    assert result.findings[2].evidence_status == "UNSUPPORTED"


def test_v336_collective_provenance_fails_with_research_only_same_context_sibling():
    valid = _finding(
        ATTEMPT10_FIXTURES[0][0],
        ATTEMPT10_FIXTURES[0][1],
        "ai_extracted_candidate",
    )

    research = _finding(
        "glutathione",
        "ingredient presence",
        "research.summary",
    )

    provenance = _finding(
        ATTEMPT10_FIXTURES[3][0],
        ATTEMPT10_FIXTURES[3][1],
        "ai_extracted_candidate",
    )

    findings = [
        valid,
        research,
        provenance,
    ]

    body = " | ".join(
        item.claim_text
        for item in findings
    )

    result = _run_chain(
        findings,
        fields={
            "copy.pt-BR.body": body,
            "research.summary": research.claim_text,
        },
    )

    assert result.findings[0].evidence_status == "SUPPORTED"
    assert result.findings[1].evidence_status == "UNSUPPORTED"
    assert result.findings[2].evidence_status == "UNSUPPORTED"


def test_v336_ambiguous_ai_provenance_fails_closed():
    text, category, source = ATTEMPT10_FIXTURES[0]

    result = _run_chain(
        [_finding(text, category, source)],
        fields={
            "copy.pt-BR.one": text,
            "copy.pt-BR.two": text,
        },
    )

    assert result.findings[0].evidence_status == "UNSUPPORTED"


def test_v336_collective_provenance_requires_manufacturer_canonical_provenance():
    findings = [
        _finding(
            ATTEMPT10_FIXTURES[0][0],
            ATTEMPT10_FIXTURES[0][1],
            "ai_extracted_candidate",
        ),
        _finding(
            ATTEMPT10_FIXTURES[3][0],
            ATTEMPT10_FIXTURES[3][1],
            "ai_extracted_candidate",
        ),
    ]

    verified = _verified()
    verified.provenance = "unverified"

    result = _run_chain(
        findings,
        verified=verified,
        fields={
            "copy.pt-BR.body": " | ".join(
                item.claim_text
                for item in findings
            )
        },
    )

    assert result.findings[0].evidence_status == "SUPPORTED"
    assert result.findings[1].evidence_status == "UNSUPPORTED"
