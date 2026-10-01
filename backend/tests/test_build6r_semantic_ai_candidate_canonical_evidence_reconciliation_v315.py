from __future__ import annotations

import asyncio
import inspect
from copy import deepcopy
from types import SimpleNamespace

import pytest

import app.services.claims_audit as claims_audit


SUPPORTED_INDICES = {
    4, 5, 6, 7, 8, 9, 10, 11, 12, 13,
    14, 15, 16, 17, 18, 19, 21, 22, 23, 24,
}

UNSUPPORTED_INDICES = {
    1, 2, 3, 20,
}


LIVE_TARGETS = {
    1: (
        "LuLuLun Hydra EX Mask 7 Sheets como um “dossiê visual” "
        "totalmente transparente: apenas o que é verificado sobre "
        "fórmula, formato e uso",
        "product benefits/effects",
        "master_concept.campaign_promise",
    ),
    2: (
        "Tudo o que você vê aqui sobre LuLuLun Hydra EX vem diretamente "
        "do que o fabricante confirma — sem extrapolar benefícios, "
        "resultados ou rotina",
        "other factual claim",
        "master_concept.key_message",
    ),
    3: (
        "Gerar reconhecimento da LuLuLun Hydra EX como sheet mask de "
        "cuidado avançado dentro do universo Hanna Japan",
        "product benefits/effects",
        "ai_extracted_candidate",
    ),
    4: (
        "incluindo exossomos de origem adiposa humana para condicionamento "
        "da pele, glutathione, arbutin, derivado de vitamina C ascorbyl "
        "palmitate, ceramidas AP e NP, atelocollagen, "
        "hydroxypropyltrimonium hyaluronate e EGF humano recombinante "
        "oligopeptídeo‑1",
        "ingredients/contents",
        "master_concept.product_category_context",
    ),
    5: (
        "Quadro com o nome de venda do fabricante: "
        "“Face Mask LuLuLun EX 1FS – 7-sheet pouch”",
        "other factual claim",
        "master_concept.proof_or_demo_strategy",
    ),
    6: (
        "Lista clara dos ingredientes destacados pelo fabricante: human "
        "adipose-derived mesenchymal cell exosomes (com nota de que o "
        "fabricante declara que não contém células-tronco), glutathione, "
        "arbutin, ascorbyl palmitate (derivado de vitamina C), ceramide AP, "
        "ceramide NP, atelocollagen, hydroxypropyltrimonium hyaluronate, "
        "human recombinant oligopeptide-1",
        "ingredients/contents",
        "master_concept.proof_or_demo_strategy",
    ),
    7: (
        "características declaradas da fórmula: colorant-free, "
        "fragrance-free, mineral‑oil‑free, alcohol‑free",
        "ingredients/contents",
        "master_concept.proof_or_demo_strategy",
    ),
    8: (
        "O produto como objeto de estudo: quadro principal com o pouch "
        "LuLuLun Hydra EX Mask 7 Sheets, título editorial e breve "
        "identificação como máscara facial em tecido em pouch de 7 folhas",
        "ingredients/contents",
        "master_concept.story_beats[1]",
    ),
    9: (
        "Nome de venda do fabricante (Face Mask LuLuLun EX 1FS), "
        "categoria (sheet mask) e formato (7 sheets / 150 mL de essência)",
        "ingredients/contents",
        "master_concept.story_beats[2]",
    ),
    10: (
        "Declarações do fabricante de colorant-free, fragrance-free, "
        "mineral‑oil‑free e alcohol‑free",
        "ingredients/contents",
        "master_concept.story_beats[4]",
    ),
    11: (
        "descrição da folha como “Melty Feel Sheet”",
        "ingredients/contents",
        "ai_extracted_candidate",
    ),
    12: (
        "Fato de que o pouch contém 7 sheets e 150 mL de essência",
        "ingredients/contents",
        "master_concept.must_include[3]",
    ),
    13: (
        "Nota de que o fabricante declara que o ingrediente de exossomos "
        "não contém células-tronco",
        "ingredients/contents",
        "master_concept.must_include[5]",
    ),
    14: (
        "Tipo de produto: máscara facial em tecido (sheet mask) em pouch "
        "com 7 unidades",
        "ingredients/contents",
        "ai_extracted_candidate",
    ),
    15: (
        "Conteúdo: 7 folhas com 150 mL de essência no total",
        "ingredients/contents",
        "ai_extracted_candidate",
    ),
    16: (
        "Ingrediente listado pelo fabricante como condicionante da pele: "
        "Exossomos derivados de células-tronco mesenquimais de tecido "
        "adiposo humano (o fabricante informa que não há células-tronco "
        "nesse ingrediente)",
        "ingredients/contents",
        "ai_extracted_candidate",
    ),
    17: (
        "Outros ingredientes presentes na fórmula, segundo o fabricante: "
        "Glutationa; Arbutin; Ascorbyl palmitate (derivado de vitamina C); "
        "Human recombinant oligopeptide-1 (EGF); Ceramide AP; Ceramide NP; "
        "Atelocollagen; Hydroxypropyltrimonium hyaluronate",
        "ingredients/contents",
        "ai_extracted_candidate",
    ),
    18: (
        "Fórmula descrita como: sem corante, sem fragrância, sem óleo "
        "mineral e sem álcool, de acordo com o fabricante",
        "ingredients/contents",
        "ai_extracted_candidate",
    ),
    19: (
        "Modo de uso segundo o fabricante: Desdobrar a máscara e posicionar "
        "em volta dos olhos e da boca; Pressionar para retirar o ar preso; "
        "Erguer os cortes da parte das bochechas ao longo da linha do rosto; "
        "Pressionar a máscara inteira com as palmas das mãos; Após remover, "
        "o fabricante sugere dobrar a máscara para passar no rosto com leves "
        "batidinhas; Em seguida, usar uma emulsão ou creme; O fabricante "
        "descreve que pode ser usada de manhã ou à noite no lugar do tônico",
        "usage instructions",
        "ai_extracted_candidate",
    ),
    20: (
        "LuLuLun Hydra EX exatamente como ela é descrita pelo fabricante: "
        "uma sheet mask facial em pouch com 7 folhas e 150 mL de essência, "
        "com esse conjunto específico de ingredientes e características de "
        "fórmula",
        "ingredients/contents",
        "ai_extracted_candidate",
    ),
    21: (
        "Máscara facial em tecido (sheet mask) em embalagem tipo pouch com "
        "7 unidades",
        "ingredients/contents",
        "copy.pt-BR.caption",
    ),
    22: (
        "De acordo com o fabricante, a fórmula contém: Exossomos derivados "
        "de células-tronco mesenquimais de tecido adiposo humano como "
        "ingrediente de condicionamento da pele",
        "ingredients/contents",
        "ai_extracted_candidate",
    ),
    23: (
        "O próprio fabricante informa que esse ingrediente não contém "
        "células-tronco",
        "ingredients/contents",
        "copy.pt-BR.caption",
    ),
    24: (
        "Segundo a descrição do fabricante: Tecido descrito como "
        "“Melty Feel Sheet”",
        "ingredients/contents",
        "ai_extracted_candidate",
    ),
}


def _verified():
    return SimpleNamespace(
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
        verified_variant="Face Mask LuLuLun EX 1FS — 7-sheet pouch",
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


def _finding(index, *, source_override=None):
    text, category, source = LIVE_TARGETS[index]

    return claims_audit.ClaimFinding(
        claim_text=text,
        claim_category=category,
        source_field=(
            source_override
            if source_override is not None
            else source
        ),
        evidence_status="UNSUPPORTED",
        allowed_source="",
        reason="V3.15 live regression target",
    )


def _status(index, *, verified=None, source_override=None):
    result = claims_audit.ClaimAuditResult(
        findings=[
            _finding(
                index,
                source_override=source_override,
            )
        ]
    )

    reconciled = (
        claims_audit
        ._build6r_v315_reconcile_semantic_candidates(
            result,
            _verified() if verified is None else verified,
        )
    )

    return reconciled.findings[0]


@pytest.mark.parametrize(
    "index",
    sorted(LIVE_TARGETS),
)
def test_v315_exact_live_24_contract(index):
    finding = _status(index)

    expected = (
        "SUPPORTED"
        if index in SUPPORTED_INDICES
        else "UNSUPPORTED"
    )

    assert finding.evidence_status == expected

    if expected == "SUPPORTED":
        assert (
            finding.allowed_source
            == "verified_product_facts"
        )


def test_v315_exact_supported_and_blocked_sets():
    actual_supported = {
        index
        for index in LIVE_TARGETS
        if _status(index).evidence_status == "SUPPORTED"
    }

    assert actual_supported == SUPPORTED_INDICES

    assert (
        set(LIVE_TARGETS)
        - actual_supported
        == UNSUPPORTED_INDICES
    )


@pytest.mark.parametrize(
    "text,category,source",
    [
        (
            "sheet mask de cuidado avançado com resultados visíveis",
            "product benefits/effects",
            "ai_extracted_candidate",
        ),
        (
            "Tudo nesta campanha vem diretamente do fabricante e foi "
            "confirmado por ele",
            "other factual claim",
            "master_concept.key_message",
        ),
        (
            "reduz poros e rejuvenesce visivelmente a pele",
            "product benefits/effects",
            "ai_extracted_candidate",
        ),
        (
            "uma das máscaras mais populares do Japão",
            "social proof/popularity",
            "ai_extracted_candidate",
        ),
        (
            "por apenas 990 ienes",
            "price/discount",
            "copy.pt-BR.caption",
        ),
        (
            "estoque limitado, compre antes que acabe",
            "availability/scarcity",
            "copy.pt-BR.caption",
        ),
        (
            "A fórmula contém células-tronco",
            "ingredients/contents",
            "copy.pt-BR.caption",
        ),
        (
            "A fórmula contém retinol",
            "ingredients/contents",
            "copy.pt-BR.caption",
        ),
    ],
)
def test_v315_required_negative_cases_fail_closed(
    text,
    category,
    source,
):
    result = claims_audit.ClaimAuditResult(
        findings=[
            claims_audit.ClaimFinding(
                claim_text=text,
                claim_category=category,
                source_field=source,
                evidence_status="UNSUPPORTED",
                allowed_source="",
                reason="negative target",
            )
        ]
    )

    reconciled = (
        claims_audit
        ._build6r_v315_reconcile_semantic_candidates(
            result,
            _verified(),
        )
    )

    assert (
        reconciled.findings[0].evidence_status
        == "UNSUPPORTED"
    )


@pytest.mark.parametrize(
    "text,category",
    [
        (
            "Categoria: sheet mask facial, pouch de 7 folhas com "
            "150 mL de essência",
            "ingredients/contents",
        ),
        (
            "Glutationa e Ceramide NP",
            "ingredients/contents",
        ),
        (
            "Desdobrar a máscara e posicionar em volta dos olhos e da boca",
            "usage instructions",
        ),
        (
            "sem corante, sem fragrância, sem óleo mineral e sem álcool",
            "ingredients/contents",
        ),
        (
            "Tecido descrito como Melty Feel Sheet",
            "ingredients/contents",
        ),
    ],
)
def test_v315_is_fact_family_based_not_sentence_whitelist(
    text,
    category,
):
    result = claims_audit.ClaimAuditResult(
        findings=[
            claims_audit.ClaimFinding(
                claim_text=text,
                claim_category=category,
                source_field="ai_extracted_candidate",
                evidence_status="UNSUPPORTED",
                allowed_source="",
                reason="generic family target",
            )
        ]
    )

    finding = (
        claims_audit
        ._build6r_v315_reconcile_semantic_candidates(
            result,
            _verified(),
        )
        .findings[0]
    )

    assert finding.evidence_status == "SUPPORTED"


def test_v315_research_source_remains_blocked():
    finding = _status(
        12,
        source_override="strategy.research_basis[0]",
    )

    assert finding.evidence_status == "UNSUPPORTED"


def test_v315_existing_supported_finding_is_immutable():
    finding = claims_audit.ClaimFinding(
        claim_text="already supported",
        claim_category="other factual claim",
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
        ._build6r_v315_reconcile_semantic_candidates(
            result,
            _verified(),
        )
    )

    assert reconciled.findings[0] == finding


def test_v315_missing_quantity_backing_fails_closed():
    verified = deepcopy(_verified())

    verified.verified_size = ""
    verified.verified_description = ""
    verified.verified_variant = ""
    verified.verified_features = [
        item
        for item in verified.verified_features
        if "150" not in item
        and "7-sheet" not in item
    ]
    verified.verified_claims = [
        item
        for item in verified.verified_claims
        if "150" not in item
        and "7-sheet" not in item
    ]

    assert (
        _status(
            15,
            verified=verified,
        ).evidence_status
        == "UNSUPPORTED"
    )


def test_v315_missing_ingredient_backing_fails_closed():
    verified = deepcopy(_verified())

    verified.verified_ingredients = []
    verified.verified_claims = [
        item
        for item in verified.verified_claims
        if "glutathione" not in item.lower()
        and "ceramide" not in item.lower()
    ]

    assert (
        _status(
            17,
            verified=verified,
        ).evidence_status
        == "UNSUPPORTED"
    )


def test_v315_missing_usage_backing_fails_closed():
    verified = deepcopy(_verified())
    verified.verified_usage = ""

    assert (
        _status(
            19,
            verified=verified,
        ).evidence_status
        == "UNSUPPORTED"
    )


def test_v315_missing_free_from_backing_fails_closed():
    verified = deepcopy(_verified())

    verified.verified_features = [
        item
        for item in verified.verified_features
        if "free" not in item.lower()
    ]

    verified.verified_claims = [
        item
        for item in verified.verified_claims
        if "free" not in item.lower()
    ]

    assert (
        _status(
            18,
            verified=verified,
        ).evidence_status
        == "UNSUPPORTED"
    )


def test_v315_missing_melty_backing_fails_closed():
    verified = deepcopy(_verified())

    verified.verified_features = [
        item
        for item in verified.verified_features
        if "melty" not in item.lower()
    ]

    verified.verified_claims = [
        item
        for item in verified.verified_claims
        if "melty" not in item.lower()
    ]

    assert (
        _status(
            24,
            verified=verified,
        ).evidence_status
        == "UNSUPPORTED"
    )


def test_v315_missing_stem_negation_backing_fails_closed():
    verified = deepcopy(_verified())

    verified.verified_ingredients = [
        item
        for item in verified.verified_ingredients
        if "stem cells" not in item.lower()
    ]

    verified.verified_claims = [
        item
        for item in verified.verified_claims
        if "stem cells" not in item.lower()
    ]

    assert (
        _status(
            23,
            verified=verified,
        ).evidence_status
        == "UNSUPPORTED"
    )


def test_v315_unrelated_product_facts_do_not_ground_live_copy():
    verified = SimpleNamespace(
        verified_description="Unrelated cleansing oil bottle.",
        verified_usage="Apply to dry skin and rinse.",
        verified_size="100 mL",
        verified_variant="100 mL bottle",
        verified_features=["Pump bottle"],
        verified_claims=[],
        verified_ingredients=["Mineral oil"],
    )

    assert all(
        _status(
            index,
            verified=verified,
        ).evidence_status
        == "UNSUPPORTED"
        for index in SUPPORTED_INDICES
    )


def test_v315_wrapper_executes_previous_chain_once(
    monkeypatch,
):
    calls = {"count": 0}

    async def previous(*args, **kwargs):
        calls["count"] += 1

        return claims_audit.ClaimAuditResult(
            findings=[
                _finding(index)
                for index in LIVE_TARGETS
            ]
        )

    monkeypatch.setattr(
        claims_audit,
        "_build6r_augment_before_v315",
        previous,
    )

    result = asyncio.run(
        claims_audit.augment_with_ai_extraction(
            None,
            fields={},
            verified=_verified(),
            brand=None,
            model="synthetic",
            existing=claims_audit.ClaimAuditResult(
                findings=[]
            ),
        )
    )

    assert calls["count"] == 1

    supported = {
        index
        for index, finding in zip(
            LIVE_TARGETS,
            result.findings,
        )
        if finding.evidence_status == "SUPPORTED"
    }

    assert supported == SUPPORTED_INDICES


def test_v315_wrapper_preserves_historical_contract_markers():
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
        "_build6r_augment_before_v315",
        "_build6r_v315_reconcile_semantic_candidates",
    )

    assert all(
        marker in source
        for marker in markers
    )


def test_v315_production_tail_is_product_agnostic_zero_cost():
    source = "\n".join(
        (
            inspect.getsource(
                claims_audit
                ._build6r_v315_translate_candidate
            ),
            inspect.getsource(
                claims_audit
                ._build6r_v315_candidate_supported
            ),
            inspect.getsource(
                claims_audit
                ._build6r_v315_reconcile_semantic_candidates
            ),
            inspect.getsource(
                claims_audit.augment_with_ai_extraction
            ),
        )
    ).lower()

    forbidden = (
        "lululun",
        "hydra",
        "generate_structured(",
        "generate_image(",
        "edit_image(",
        "httpx.",
        "requests.",
        "rapidfuzz",
        "difflib",
        "sequencematcher",
        "embedding",
        "cosine",
        "research_provider",
    )

    assert all(
        token not in source
        for token in forbidden
    )


def test_v315_does_not_redefine_core_detector():
    source = inspect.getsource(
        claims_audit
        ._build6r_v315_reconcile_semantic_candidates
    )

    assert "def _evaluate(" not in source
    assert "def detect_claims_in_text(" not in source
