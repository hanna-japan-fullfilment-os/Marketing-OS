from __future__ import annotations

import inspect
from pathlib import Path
from types import SimpleNamespace

import pytest

import app.services.claims_audit as claims_audit


CORPUS = {
    1: (
        "LuLuLun Hydra EX Hydra EX conhecida como uma sheet mask "
        "tecnicamente interessante e diferente, destacando sua composicao "
        "e formato de pouch com 7 mascaras e 150 mL de essencia",
        "product_features",
        "ai_extracted_candidate",
    ),
    2: (
        "LuLuLun Hydra EX Mask 7 Sheets como uma sheet mask tecnicamente "
        "interessante e diferente, mostrando apenas o que e verificado "
        "sobre sua composicao, ingredientes e formato de pouch com "
        "7 mascaras e 150 mL de essencia",
        "product_features",
        "master_concept.campaign_promise",
    ),
    3: (
        "Tudo o que voce ve aqui sobre a Hydra EX vem diretamente de "
        "informacoes verificadas: ingredientes, formato 7-sheet, 150 mL "
        "de essencia, caracteristicas de formula e modo de uso",
        "other_factual",
        "master_concept.key_message",
    ),
    4: (
        "Tornar a LuLuLun Hydra EX conhecida como uma sheet mask "
        "tecnicamente interessante e distinta, destacando sua lista de "
        "ingredientes verificados, a descricao do tecido, o fato de ser "
        "colorant-free, fragrance-free, mineral-oil-free, alcohol-free, "
        "e o formato pouch com 7 mascaras em 150 mL de essencia",
        "product_features",
        "master_concept.objective",
    ),
    5: (
        "Sheet mask facial em pouch com multiplas unidades "
        "(7 folhas) e 150 mL de essencia",
        "product_features",
        "master_concept.product_category_context",
    ),
    6: (
        "exossomos listados como ingrediente de condicionamento da pele, "
        "glutathione, arbutin, ascorbyl palmitate, ceramidas, "
        "atelocollagen, hydroxypropyltrimonium hyaluronate, EGF, e o "
        "fato de ser colorant-free, fragrance-free, mineral-oil-free, "
        "alcohol-free",
        "ingredients",
        "master_concept.archetype_reasoning",
    ),
    7: (
        "fato de ser colorant-free, fragrance-free, mineral-oil-free, "
        "alcohol-free",
        "ingredients",
        "ai_extracted_candidate",
    ),
    8: (
        "Tecido: mencao textual de que o fabricante descreve a sheet "
        "como Melty Feel Sheet",
        "product_features",
        "master_concept.proof_or_demo_strategy",
    ),
    9: (
        "modo de uso descrito pelo fabricante (desdobrar, ajustar ao redor "
        "dos olhos e boca, pressionar, levantar cortes da bochecha, "
        "pressionar com as palmas, e sugestao pos-uso de dobrar a mascara "
        "para leve batidinha/limpeza e seguir com emulsao ou creme, "
        "mencionando que pode ser usada pela manha ou a noite em lugar "
        "do tonico)",
        "instructions_or_directions",
        "ai_extracted_candidate",
    ),
    10: (
        "Encontro com o objeto: Apresentar o pouch LuLuLun Hydra EX Mask "
        "7 Sheets em visual editorial limpo, evidenciando que e a variante "
        "de 7 mascaras com 150 mL de essencia",
        "product_features",
        "master_concept.story_beats[1]",
    ),
    11: (
        "o fabricante declara que a formula e colorant-free, "
        "fragrance-free, mineral-oil-free, e alcohol-free, usando essas "
        "expressoes exatamente",
        "ingredients",
        "master_concept.must_include[4]",
    ),
    12: (
        "A descricao do tecido como Melty Feel Sheet, claramente atribuida "
        "ao fabricante",
        "product_features",
        "master_concept.must_include[5]",
    ),
    13: (
        "Fidelidade total a aparencia real do pouch: logo, cores, "
        "proporcoes, textos impressos",
        "other_factual",
        "master_concept.must_include[8]",
    ),
    14: (
        "Versao exata pouch com 7 mascaras",
        "product_features",
        "ai_extracted_candidate",
    ),
    15: (
        "1 pouch com 7 sheet masks",
        "product_features",
        "ai_extracted_candidate",
    ),
    16: (
        "Variante confirmada: Face Mask LuLuLun EX 1FS - 7-sheet pouch",
        "product_features",
        "ai_extracted_candidate",
    ),
    17: (
        "O fabricante lista estes componentes na formula",
        "ingredients",
        "ai_extracted_candidate",
    ),
    18: (
        "Exossomos derivados de celulas-tronco mesenquimais de gordura "
        "humana como ingrediente de condicionamento da pele",
        "ingredients",
        "ai_extracted_candidate",
    ),
    19: (
        "O fabricante afirma que esses exossomos nao contem celulas-tronco",
        "ingredients",
        "ai_extracted_candidate",
    ),
    20: (
        "Como o fabricante orienta o uso",
        "instructions_or_directions",
        "ai_extracted_candidate",
    ),
    21: (
        "O fabricante tambem descreve que a mascara pode ser usada de "
        "manha ou a noite, no lugar do tonico (toner)",
        "instructions_or_directions",
        "ai_extracted_candidate",
    ),
    22: (
        "O fabricante lista na formula",
        "ingredients",
        "copy.pt-BR.caption",
    ),
    23: (
        "o proprio fabricante afirma que esses exossomos nao contem "
        "celulas-tronco",
        "ingredients",
        "ai_extracted_candidate",
    ),
    24: (
        "Ascorbyl palmitate (derivado de vitamina C, segundo a descricao "
        "do fabricante)",
        "ingredients",
        "ai_extracted_candidate",
    ),
    25: (
        "Base: fotografia real do LuLuLun Hydra EX 7-sheet pouch "
        "(Face Mask LuLuLun EX 1FS)",
        "product_features",
        "creative.creative_brief.visual_prompt",
    ),
    26: (
        "cor e acabamento da embalagem",
        "other_factual",
        "creative.creative_brief.visual_prompt",
    ),
    27: (
        "nome Hydra EX / Face Mask LuLuLun EX 1FS",
        "other_factual",
        "creative.creative_brief.visual_prompt",
    ),
    28: (
        "selo de 7 sheets",
        "product_features",
        "creative.creative_brief.visual_prompt",
    ),
    29: (
        "Pouch com 7 sheet masks - 150 mL de essencia",
        "product_features",
        "creative.creative_brief.visual_prompt",
    ),
    30: (
        "Face Mask LuLuLun EX 1FS",
        "product_features",
        "creative.creative_brief.visual_prompt",
    ),
    31: (
        "Inclui: human adipose-derived mesenchymal cell exosomes",
        "ingredients",
        "creative.creative_brief.visual_prompt",
    ),
    32: (
        "Contem: glutathione, arbutin, ascorbyl palmitate "
        "(derivado de vitamina C), Ceramide AP, Ceramide NP, "
        "atelocollagen, hydroxypropyltrimonium hyaluronate, "
        "human recombinant oligopeptide-1",
        "ingredients",
        "creative.creative_brief.visual_prompt",
    ),
}


# These are the corpus members that are allowed to reconcile.
# Every omitted member intentionally remains fail closed.
EXPECTED_SUPPORTED = {
    1,
    5,
    6,
    7,
    8,
    9,
    10,
    11,
    12,
    14,
    15,
    19,
    21,
    23,
    24,
    27,
    29,
    30,
    31,
    32,
}


def _verified():
    return SimpleNamespace(
        verified_description=(
            "LuLuLun Hydra EX Mask 7 Sheets is a facial sheet mask. "
            "Face Mask LuLuLun EX 1FS."
        ),
        verified_usage=(
            "Unfold the mask and adjust around the eyes and mouth. "
            "Press out air, lift the cheek cuts along the face line, "
            "press with palms. After removal, fold the sheet for light "
            "wiping or patting and then apply emulsion or cream. "
            "Manufacturer describes that the mask can be used morning "
            "or night instead of toner."
        ),
        verified_size="7 sheets / essence 150 mL",
        verified_variant="Face Mask LuLuLun EX 1FS",
        verified_price="",
        verified_availability="",
        verified_country_of_origin="",
        verified_features=[
            "7-sheet pouch containing 150 mL of essence",
            "Manufacturer describes the sheet as a Melty Feel Sheet",
            "Colorant-free",
            "Fragrance-free",
            "Mineral-oil-free",
            "Alcohol-free",
        ],
        verified_claims=[
            "7-sheet pouch containing 150 mL of essence",
            (
                "Human adipose-derived mesenchymal cell exosomes are "
                "listed as a skin conditioning ingredient; manufacturer "
                "states stem cells are not contained"
            ),
            (
                "Contains glutathione, arbutin, and the vitamin C "
                "derivative ascorbyl palmitate"
            ),
            (
                "Manufacturer states the formula is colorant-free, "
                "fragrance-free, mineral-oil-free, and alcohol-free"
            ),
            (
                "Manufacturer describes that the mask can be used "
                "morning or night instead of toner"
            ),
        ],
        verified_ingredients=[
            "Human adipose-derived mesenchymal cell exosomes",
            "Glutathione",
            "Arbutin",
            "Ascorbyl palmitate",
            "Ceramide AP",
            "Ceramide NP",
            "Atelocollagen",
            "Hydroxypropyltrimonium hyaluronate",
            "Human recombinant oligopeptide-1 (EGF)",
        ],
        prohibited_claims=[],
        missing_information=[],
    )


def _finding(index):
    text, category, source = CORPUS[index]

    return claims_audit.ClaimFinding(
        claim_text=text,
        claim_category=category,
        source_field=source,
        evidence_status="UNSUPPORTED",
        allowed_source="",
        reason="recorded post-V3.17 previsual hard fail",
    )


def _fields_for_corpus():
    fields = {}

    for text, _category, source in CORPUS.values():
        if source == "ai_extracted_candidate":
            continue

        if source in fields:
            fields[source] += " | " + text
        else:
            fields[source] = text

    return fields


def test_v318_complete_32_finding_corpus_classification():
    findings = [
        _finding(index)
        for index in sorted(CORPUS)
    ]

    result = claims_audit.ClaimAuditResult(
        findings=findings
    )

    reconciled = (
        claims_audit
        ._build6r_v318_reconcile_previsual_candidates(
            result,
            _verified(),
            _fields_for_corpus(),
        )
    )

    statuses = {
        index:
            reconciled.findings[index - 1].evidence_status
        for index in sorted(CORPUS)
    }

    supported = {
        index
        for index, status in statuses.items()
        if status == "SUPPORTED"
    }

    assert len(CORPUS) == 32
    assert supported == EXPECTED_SUPPORTED

    for index in EXPECTED_SUPPORTED:
        finding = reconciled.findings[index - 1]
        assert finding.allowed_source == "verified_product_facts"
        assert "V3.18" in finding.reason

    for index in (
        set(CORPUS)
        - EXPECTED_SUPPORTED
    ):
        finding = reconciled.findings[index - 1]
        assert finding.evidence_status == "UNSUPPORTED"


def test_v318_corpus_category_and_source_counts_match_live_event():
    categories = {}
    sources = {}

    for _text, category, source in CORPUS.values():
        categories[category] = categories.get(category, 0) + 1
        sources[source] = sources.get(source, 0) + 1

    assert categories == {
        "ingredients": 11,
        "instructions_or_directions": 3,
        "other_factual": 4,
        "product_features": 14,
    }

    assert sources["ai_extracted_candidate"] == 13
    assert sources["copy.pt-BR.caption"] == 1
    assert sources["creative.creative_brief.visual_prompt"] == 8

    master_count = sum(
        count
        for source, count in sources.items()
        if source.startswith("master_concept.")
    )

    assert master_count == 10


@pytest.mark.parametrize(
    "text,category,source",
    [
        (
            "Clinically proven skin transformation",
            "clinical_scientific_claims",
            "master_concept.objective",
        ),
        (
            "Best seller number one",
            "ranking_bestseller",
            "master_concept.campaign_promise",
        ),
        (
            "Only today at a special price",
            "price_availability",
            "creative.creative_brief.visual_prompt",
        ),
        (
            "External research says this is popular",
            "product_features",
            "strategy.research_basis[0]",
        ),
        (
            "Glutathione 10%",
            "ingredients",
            "master_concept.archetype_reasoning",
        ),
        (
            "The package has a gold 7-sheet seal",
            "product_features",
            "creative.creative_brief.visual_prompt",
        ),
        (
            "Verified information from the direct source",
            "other_factual",
            "master_concept.key_message",
        ),
        (
            "Unknown patented delivery technology",
            "product_features",
            "master_concept.product_category_context",
        ),
    ],
)
def test_v318_negative_boundaries_remain_unsupported(
    text,
    category,
    source,
):
    finding = claims_audit.ClaimFinding(
        claim_text=text,
        claim_category=category,
        source_field=source,
        evidence_status="UNSUPPORTED",
        allowed_source="",
        reason="negative control",
    )

    result = claims_audit.ClaimAuditResult(
        findings=[finding]
    )

    reconciled = (
        claims_audit
        ._build6r_v318_reconcile_previsual_candidates(
            result,
            _verified(),
            {
                source: text,
            },
        )
    )

    assert (
        reconciled.findings[0].evidence_status
        == "UNSUPPORTED"
    )


def test_v318_cross_field_stem_cell_qualification_is_forbidden():
    claim = (
        "Human adipose-derived mesenchymal stem-cell exosomes "
        "are listed as a skin conditioning ingredient"
    )

    finding = claims_audit.ClaimFinding(
        claim_text=claim,
        claim_category="ingredients",
        source_field="ai_extracted_candidate",
        evidence_status="UNSUPPORTED",
        allowed_source="",
        reason="stem-cell safety control",
    )

    assert not (
        claims_audit
        ._build6r_v318_same_context_stem_cell_qualified(
            finding,
            _verified(),
            {
                "master_concept.archetype_reasoning":
                    claim,
                "master_concept.must_include[0]":
                    "Manufacturer states stem cells are not contained",
            },
        )
    )


def test_v318_same_field_stem_cell_qualification_is_bounded():
    claim = (
        "Human adipose-derived mesenchymal stem-cell exosomes "
        "are listed as a skin conditioning ingredient"
    )

    finding = claims_audit.ClaimFinding(
        claim_text=claim,
        claim_category="ingredients",
        source_field="ai_extracted_candidate",
        evidence_status="UNSUPPORTED",
        allowed_source="",
        reason="stem-cell safety control",
    )

    source = (
        claim
        + "; manufacturer states stem cells are not contained"
    )

    assert (
        claims_audit
        ._build6r_v318_same_context_stem_cell_qualified(
            finding,
            _verified(),
            {
                "master_concept.archetype_reasoning":
                    source,
            },
        )
    )


def test_v318_already_supported_findings_are_preserved():
    finding = claims_audit.ClaimFinding(
        claim_text="7 sheet pouch",
        claim_category="product_features",
        source_field="copy.pt-BR.caption",
        evidence_status="SUPPORTED",
        allowed_source="verified_product_facts",
        reason="already supported",
    )

    result = claims_audit.ClaimAuditResult(
        findings=[finding]
    )

    reconciled = (
        claims_audit
        ._build6r_v318_reconcile_previsual_candidates(
            result,
            _verified(),
            {},
        )
    )

    assert reconciled.findings[0] == finding


@pytest.mark.asyncio
async def test_v318_wrapper_executes_sealed_v317_chain_once(
    monkeypatch,
):
    calls = {
        "base": 0,
        "v318": 0,
    }

    original = claims_audit.ClaimAuditResult(
        findings=[]
    )

    async def fake_base(*args, **kwargs):
        calls["base"] += 1
        return original

    def fake_v318(result, verified, fields):
        calls["v318"] += 1
        assert result is original
        assert fields == {
            "master_concept.objective":
                "example",
        }
        return result

    monkeypatch.setattr(
        claims_audit,
        "_build6r_augment_before_v318",
        fake_base,
    )

    monkeypatch.setattr(
        claims_audit,
        "_build6r_v318_reconcile_previsual_candidates",
        fake_v318,
    )

    returned = await (
        claims_audit.augment_with_ai_extraction(
            object(),
            verified=_verified(),
            fields={
                "master_concept.objective":
                    "example",
            },
        )
    )

    assert returned is original
    assert calls == {
        "base": 1,
        "v318": 1,
    }


def test_v318_source_boundary_is_bounded():
    allowed = (
        "master_concept.campaign_promise",
        "master_concept.key_message",
        "master_concept.objective",
        "master_concept.product_category_context",
        "master_concept.archetype_reasoning",
        "master_concept.proof_or_demo_strategy",
        "master_concept.story_beats[1]",
        "master_concept.must_include[5]",
        "creative.creative_brief.visual_prompt",
        "ai_extracted_candidate",
        "copy.pt-BR.caption",
    )

    for source in allowed:
        assert (
            claims_audit
            ._build6r_v318_source_field_allowed(
                source
            )
        )

    for source in (
        "strategy.research_basis[0]",
        "research.trends[0]",
        "master_concept.unknown_generated_field",
        "creative.unknown.visual_prompt",
    ):
        assert not (
            claims_audit
            ._build6r_v318_source_field_allowed(
                source
            )
        )


def test_v318_static_safety_boundaries():
    source = inspect.getsource(
        claims_audit
    )

    marker = (
        "BUILD6R_PREVISUAL_CANONICAL_SOURCE_FIELD_"
        "COMPOSITIONAL_RECONCILIATION_V3_18"
    )

    assert marker in source

    block = source.split(
        marker,
        1,
    )[1]

    assert "ad9ce9fe28c1421284d00954304b20cb" not in block
    assert "a5ea2272a1f89d743c089461bb2fb50f" not in block
    assert "lululun-hydra-ex-mask-7-sheets" not in block

    assert "def detect_claims_in_text(" not in block
    assert "import openai" not in block
    assert "import requests" not in block
    assert "import httpx" not in block
    assert "import socket" not in block
    assert "sqlite3" not in block
    assert "sqlalchemy" not in block

    assert (
        "_build6r_augment_before_v318 = "
        "augment_with_ai_extraction"
    ) in block

    assert (
        "_build6r_v316_candidate_supported("
        in block
    )


def test_v318_authorized_production_file_boundary():
    path = Path(
        claims_audit.__file__
    ).resolve()

    assert path.name == "claims_audit.py"
