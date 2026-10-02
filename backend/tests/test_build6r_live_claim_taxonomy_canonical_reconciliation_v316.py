from __future__ import annotations

import asyncio
import inspect
from copy import deepcopy
from types import SimpleNamespace

import pytest

import app.services.claims_audit as claims_audit


SUPPORTED_INDICES = {
    2,
    4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23,
    26, 27, 28, 29, 30, 31, 32,
}

UNSUPPORTED_INDICES = {
    1, 3, 24, 25,
}


LIVE_TARGETS = {
    1: ('Gerar reconhecimento do LuLuLun Hydra EX como uma sheet mask tecnicamente interessante', 'product benefits/effects', 'ai_extracted_candidate'),
    2: ('LuLuLun Hydra EX Mask 7 Sheets — fórmula, formato, composição e modo de uso', 'product features/attributes', 'master_concept.campaign_promise'),
    3: ('LuLuLun Hydra EX como uma sheet mask tecnicamente interessante', 'product benefits/effects', 'ai_extracted_candidate'),
    4: ('ingredientes específicos (como exossomos listados como ingrediente de condicionamento da pele, glutathione, arbutin, derivado de vitamina C, ceramidas, atelocollagen, hydroxypropyltrimonium hyaluronate, EGF)', 'ingredients/percentages', 'master_concept.archetype_reasoning'),
    5: ('o fato de ser um pouch com 7 sheets e 150 mL de essência', 'product features/attributes', 'master_concept.archetype_reasoning'),
    6: ('presença de human adipose-derived mesenchymal cell exosomes como ingrediente de condicionamento da pele, esclarecendo visualmente que o fabricante afirma que não contém células-tronco', 'clinical/scientific claims', 'master_concept.proof_or_demo_strategy'),
    7: ('menção a glutathione, arbutin, ascorbyl palmitate, ceramides AP e NP, atelocollagen, hydroxypropyltrimonium hyaluronate, human recombinant oligopeptide-1', 'ingredients/percentages', 'master_concept.proof_or_demo_strategy'),
    8: ('indicações de ser colorant-free, fragrance-free, mineral-oil-free, alcohol-free', 'ingredients/percentages', 'master_concept.proof_or_demo_strategy'),
    9: ('modo de uso é demonstrado passo a passo em ilustrações simples ou em sequências fotográficas neutras (unfold, ajustar em torno de olhos e boca, pressionar o ar, levantar cortes das bochechas, pressionar com as palmas; depois dobrar a máscara para wiping/light patting e seguir com emulsão ou creme, podendo ser usada manhã ou noite em substituição ao toner)', 'directions for use', 'master_concept.proof_or_demo_strategy'),
    10: ('LuLuLun Hydra EX Mask 7 Sheets é mostrado como um pouch de 7 folhas com 150 mL de essência', 'product features/attributes', 'master_concept.story_beats[1]'),
    11: ('nome oficial Face Mask LuLuLun EX 1FS', 'product features/attributes', 'master_concept.story_beats[1]'),
    12: ('human adipose-derived mesenchymal cell exosomes como ingrediente de condicionamento da pele (com indicação clara de que o fabricante afirma que não contém células-tronco)', 'clinical/scientific claims', 'master_concept.story_beats[2]'),
    13: ('glutathione, arbutin, derivado de vitamina C (ascorbyl palmitate), ceramides AP e NP, atelocollagen, hydroxypropyltrimonium hyaluronate e human recombinant oligopeptide-1', 'ingredients/percentages', 'master_concept.story_beats[2]'),
    14: ('descrição do sheet como Melty Feel Sheet', 'product features/attributes', 'master_concept.story_beats[3]'),
    15: ('Presença dos ingredientes listados: human adipose-derived mesenchymal cell exosomes (como ingrediente de condicionamento da pele, com a informação de que o fabricante declara não conter células-tronco), glutathione, arbutin, ascorbyl palmitate, Ceramide AP, Ceramide NP, atelocollagen, hydroxypropyltrimonium hyaluronate e human recombinant oligopeptide-1', 'ingredients/percentages', 'master_concept.must_include[2]'),
    16: ('Destaque para as características de fórmula declaradas: colorant-free, fragrance-free, mineral-oil-free, alcohol-free', 'ingredients/percentages', 'master_concept.must_include[3]'),
    17: ('Menção de que o sheet é descrito pelo fabricante como Melty Feel Sheet', 'product features/attributes', 'master_concept.must_include[4]'),
    18: ('Nome de venda oficial: Face Mask LuLuLun EX 1FS', 'product features/attributes', 'master_concept.must_include[5]'),
    19: ('Versão exata de pouch com 7 máscaras', 'product features/attributes', 'ai_extracted_candidate'),
    20: ('Embalagem com 7 sheets', 'product features/attributes', 'ai_extracted_candidate'),
    21: ('Exossomos derivados de células-tronco mesenquimais de tecido adiposo humano – listados como ingrediente de condicionamento da pele; o fabricante afirma que não há células-tronco contidas', 'clinical/scientific claims', 'ai_extracted_candidate'),
    22: ('Livre de, segundo o fabricante: • Corantes • Fragrância • Óleo mineral • Álcool', 'ingredients/percentages', 'ai_extracted_candidate'),
    23: ('Modo de uso descrito pelo fabricante: 1. Desdobrar a máscara e ajustar em volta dos olhos e da boca. 2. Pressionar para tirar o ar preso. 3. Erguer os recortes da região da bochecha ao longo da linha do rosto. 4. Pressionar toda a máscara com as palmas das mãos. 5. Após retirar, o fabricante sugere dobrar a sheet para usar para "wiping/light patting" e, em seguida, finalizar com emulsão ou creme. 6. O fabricante descreve o uso pela manhã ou à noite no lugar do tônico.', 'directions for use', 'ai_extracted_candidate'),
    24: ('Tudo acima vem de fonte direta do fabricante desta LuLuLun Hydra EX 7 sheets', 'source/verification claim', 'ai_extracted_candidate'),
    25: ('Este carrossel foi montado só com informações verificadas da LuLuLun Hydra EX 7 sheets – sem extrapolar nada', 'source/verification claim', 'copy.pt-BR.caption'),
    26: ('Categoria: máscara facial em sheet', 'product features/attributes', 'copy.pt-BR.caption'),
    27: ('Quantidade de essência: 150 mL no pacote', 'product features/attributes', 'copy.pt-BR.caption'),
    28: ('Tipo de sheet: o fabricante descreve como “Melty Feel Sheet”', 'product features/attributes', 'copy.pt-BR.caption'),
    29: ('Componentes listados na fórmula: • Exossomos derivados de células mesenquimais de tecido adiposo humano – indicados pelo fabricante como ingrediente de condicionamento da pele. O próprio fabricante afirma que não há células-tronco contidas nesse ingrediente. • Glutationa • Arbutin • Ascorbyl palmitate (derivado de vitamina C) • Ceramide AP • Ceramide NP • Atelocollagen • Hydroxypropyltrimonium hyaluronate • Human recombinant oligopeptide-1 (EGF)', 'ingredients/percentages', 'ai_extracted_candidate'),
    30: ('Uso sugerido: pela manhã ou à noite, no lugar do tônico', 'directions for use', 'copy.pt-BR.caption'),
    31: ('Passo a passo descrito pelo fabricante: 1. Desdobrar a máscara e encaixar em volta dos olhos e da boca. 2. Pressionar para tirar o ar preso. 3. Puxar os recortes da bochecha acompanhando a linha do rosto. 4. Pressionar a máscara inteira com as palmas das mãos. 5. Depois de retirar, o fabricante sugere dobrar a sheet para usar para "wiping/light patting" e então seguir com emulsão ou creme.', 'directions for use', 'ai_extracted_candidate'),
    32: ('Uso descrito pelo fabricante: manhã ou noite, em substituição ao tônico', 'directions for use', 'creative.creative_brief.template_suggestion'),
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
        verified_benefits=[],
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
        reason="V3.16 exact live regression target",
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
        ._build6r_v316_reconcile_live_taxonomy_candidates(
            result,
            _verified() if verified is None else verified,
        )
    )

    return reconciled.findings[0]


@pytest.mark.parametrize("index", sorted(LIVE_TARGETS))
def test_v316_exact_live_32_contract(index):
    finding = _status(index)

    expected = (
        "SUPPORTED"
        if index in SUPPORTED_INDICES
        else "UNSUPPORTED"
    )

    assert finding.evidence_status == expected

    if expected == "SUPPORTED":
        assert finding.allowed_source == "verified_product_facts"


def test_v316_exact_supported_and_blocked_sets():
    actual_supported = {
        index
        for index in LIVE_TARGETS
        if _status(index).evidence_status == "SUPPORTED"
    }

    assert actual_supported == SUPPORTED_INDICES
    assert set(LIVE_TARGETS) - actual_supported == UNSUPPORTED_INDICES


@pytest.mark.parametrize("index", sorted(UNSUPPORTED_INDICES))
def test_v316_required_live_negatives_remain_blocked(index):
    assert _status(index).evidence_status == "UNSUPPORTED"


def test_v316_product_benefit_category_remains_fail_closed_even_for_canonical_words():
    finding = claims_audit.ClaimFinding(
        claim_text="facial sheet mask",
        claim_category="product benefits/effects",
        source_field="copy.pt-BR.caption",
        evidence_status="UNSUPPORTED",
        allowed_source="",
        reason="negative",
    )

    result = claims_audit.ClaimAuditResult(findings=[finding])

    reconciled = (
        claims_audit
        ._build6r_v316_reconcile_live_taxonomy_candidates(
            result,
            _verified(),
        )
    )

    assert reconciled.findings[0].evidence_status == "UNSUPPORTED"


@pytest.mark.parametrize(
    "category",
    [
        "source/verification claim",
        "product price",
        "availability/scarcity",
        "ranking/bestseller",
        "product efficacy",
        "popularity claim",
    ],
)
def test_v316_blocked_taxonomy_families_remain_fail_closed(category):
    finding = claims_audit.ClaimFinding(
        claim_text="LuLuLun Hydra EX facial sheet mask",
        claim_category=category,
        source_field="copy.pt-BR.caption",
        evidence_status="UNSUPPORTED",
        allowed_source="",
        reason="negative",
    )

    result = claims_audit.ClaimAuditResult(findings=[finding])

    reconciled = (
        claims_audit
        ._build6r_v316_reconcile_live_taxonomy_candidates(
            result,
            _verified(),
        )
    )

    assert reconciled.findings[0].evidence_status == "UNSUPPORTED"


def test_v316_invented_percentage_fails_closed():
    finding = claims_audit.ClaimFinding(
        claim_text="Glutathione 10%",
        claim_category="ingredients/percentages",
        source_field="ai_extracted_candidate",
        evidence_status="UNSUPPORTED",
        allowed_source="",
        reason="negative",
    )

    result = claims_audit.ClaimAuditResult(findings=[finding])

    reconciled = (
        claims_audit
        ._build6r_v316_reconcile_live_taxonomy_candidates(
            result,
            _verified(),
        )
    )

    assert reconciled.findings[0].evidence_status == "UNSUPPORTED"


def test_v316_exact_canonical_percentage_can_reconcile():
    verified = SimpleNamespace(
        verified_description="Example serum",
        verified_usage="",
        verified_size="30 mL",
        verified_variant="Example serum",
        verified_features=[],
        verified_benefits=[],
        verified_claims=["Contains Niacinamide 5%"],
        verified_ingredients=["Niacinamide 5%"],
        provenance="manufacturer_official",
    )

    finding = claims_audit.ClaimFinding(
        claim_text="Niacinamide 5%",
        claim_category="ingredients/percentages",
        source_field="ai_extracted_candidate",
        evidence_status="UNSUPPORTED",
        allowed_source="",
        reason="positive",
    )

    result = claims_audit.ClaimAuditResult(findings=[finding])

    reconciled = (
        claims_audit
        ._build6r_v316_reconcile_live_taxonomy_candidates(
            result,
            verified,
        )
    )

    assert reconciled.findings[0].evidence_status == "SUPPORTED"


def test_v316_positive_stem_cell_assertion_without_explicit_negation_fails_closed():
    finding = claims_audit.ClaimFinding(
        claim_text=(
            "Exossomos derivados de células-tronco mesenquimais de tecido "
            "adiposo humano como ingrediente de condicionamento da pele"
        ),
        claim_category="clinical/scientific claims",
        source_field="ai_extracted_candidate",
        evidence_status="UNSUPPORTED",
        allowed_source="",
        reason="negative",
    )

    result = claims_audit.ClaimAuditResult(findings=[finding])

    reconciled = (
        claims_audit
        ._build6r_v316_reconcile_live_taxonomy_candidates(
            result,
            _verified(),
        )
    )

    assert reconciled.findings[0].evidence_status == "UNSUPPORTED"


def test_v316_clinical_category_is_not_broadly_opened():
    finding = claims_audit.ClaimFinding(
        claim_text="Ceramide NP clinicamente comprovada",
        claim_category="clinical/scientific claims",
        source_field="ai_extracted_candidate",
        evidence_status="UNSUPPORTED",
        allowed_source="",
        reason="negative",
    )

    result = claims_audit.ClaimAuditResult(findings=[finding])

    reconciled = (
        claims_audit
        ._build6r_v316_reconcile_live_taxonomy_candidates(
            result,
            _verified(),
        )
    )

    assert reconciled.findings[0].evidence_status == "UNSUPPORTED"


def test_v316_official_sales_name_requires_manufacturer_official_provenance():
    verified = deepcopy(_verified())
    verified.provenance = "owner_confirmed"

    assert (
        _status(
            18,
            verified=verified,
        ).evidence_status
        == "UNSUPPORTED"
    )


def test_v316_research_source_remains_blocked():
    assert (
        _status(
            4,
            source_override="strategy.research_basis[0]",
        ).evidence_status
        == "UNSUPPORTED"
    )


def test_v316_existing_supported_finding_is_immutable():
    finding = claims_audit.ClaimFinding(
        claim_text="already supported",
        claim_category="product features/attributes",
        source_field="copy.pt-BR.caption",
        evidence_status="SUPPORTED",
        allowed_source="verified_product_facts",
        reason="existing",
    )

    result = claims_audit.ClaimAuditResult(findings=[finding])

    reconciled = (
        claims_audit
        ._build6r_v316_reconcile_live_taxonomy_candidates(
            result,
            _verified(),
        )
    )

    assert reconciled.findings[0] == finding


def test_v316_missing_canonical_backing_fails_closed():
    verified = deepcopy(_verified())
    verified.verified_features = []
    verified.verified_claims = []
    verified.verified_size = ""

    assert (
        _status(
            27,
            verified=verified,
        ).evidence_status
        == "UNSUPPORTED"
    )


def test_v316_unrelated_product_facts_do_not_ground_live_copy():
    verified = SimpleNamespace(
        verified_description="Unrelated cleansing oil bottle.",
        verified_usage="Apply to dry skin and rinse.",
        verified_size="100 mL",
        verified_variant="100 mL bottle",
        verified_features=["Pump bottle"],
        verified_benefits=[],
        verified_claims=[],
        verified_ingredients=["Mineral oil"],
        provenance="manufacturer_official",
    )

    assert all(
        _status(
            index,
            verified=verified,
        ).evidence_status
        == "UNSUPPORTED"
        for index in SUPPORTED_INDICES
    )


@pytest.mark.parametrize(
    "text, verified",
    [
        (
            "Embalagem com 5 sheets",
            SimpleNamespace(
                verified_description="Example facial sheet mask, exact 5-sheet pouch variant.",
                verified_usage="",
                verified_size="5 sheets / essence 120 mL",
                verified_variant="5-sheet pouch",
                verified_features=["5-sheet pouch variant", "Contains 120 mL of essence"],
                verified_benefits=[],
                verified_claims=["5-sheet pouch containing 120 mL of essence"],
                verified_ingredients=[],
                provenance="manufacturer_official",
            ),
        ),
        (
            "Quantidade de essência: 120 mL no pacote",
            SimpleNamespace(
                verified_description="Example facial sheet mask.",
                verified_usage="",
                verified_size="5 sheets / essence 120 mL",
                verified_variant="5-sheet pouch",
                verified_features=["Contains 120 mL of essence"],
                verified_benefits=[],
                verified_claims=["5-sheet pouch containing 120 mL of essence"],
                verified_ingredients=[],
                provenance="manufacturer_official",
            ),
        ),
    ],
)
def test_v316_generic_product_feature_families_are_not_sentence_whitelists(text, verified):
    finding = claims_audit.ClaimFinding(
        claim_text=text,
        claim_category="product features/attributes",
        source_field="copy.pt-BR.caption",
        evidence_status="UNSUPPORTED",
        allowed_source="",
        reason="generic positive",
    )

    result = claims_audit.ClaimAuditResult(findings=[finding])

    reconciled = (
        claims_audit
        ._build6r_v316_reconcile_live_taxonomy_candidates(
            result,
            verified,
        )
    )

    assert reconciled.findings[0].evidence_status == "SUPPORTED"


def test_v316_wrapper_executes_previous_chain_once(monkeypatch):
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
        "_build6r_augment_before_v316",
        previous,
    )

    result = asyncio.run(
        claims_audit.augment_with_ai_extraction(
            None,
            verified=_verified(),
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


def test_v316_wrapper_preserves_historical_contract_markers():
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
        "_build6r_augment_before_v316",
        "_build6r_v316_reconcile_live_taxonomy_candidates",
    )

    assert all(
        marker in source
        for marker in markers
    )


def test_v316_production_tail_is_product_agnostic_zero_cost():
    source = "\n".join(
        (
            inspect.getsource(
                claims_audit._build6r_v316_verified_strings
            ),
            inspect.getsource(
                claims_audit._build6r_v316_percentage_literals
            ),
            inspect.getsource(
                claims_audit._build6r_v316_translate_candidate
            ),
            inspect.getsource(
                claims_audit._build6r_v316_candidate_supported
            ),
            inspect.getsource(
                claims_audit._build6r_v316_reconcile_live_taxonomy_candidates
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


def test_v316_does_not_redefine_core_detector():
    source = inspect.getsource(
        claims_audit._build6r_v316_reconcile_live_taxonomy_candidates
    )

    assert "def _evaluate(" not in source
    assert "def detect_claims_in_text(" not in source
