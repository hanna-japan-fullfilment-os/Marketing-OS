from __future__ import annotations

import asyncio
import inspect
from copy import deepcopy
from types import SimpleNamespace

import app.services.claims_audit as claims_audit


LIVE_CORPUS = {
    1: (
        "descri\u00e7\u00e3o do tecido como Melty Feel Sheet",
        "product_feature",
        "master_concept.archetype_reasoning",
    ),
    2: (
        "isen\u00e7\u00f5es de corante, fragr\u00e2ncia, \u00f3leo mineral e \u00e1lcool",
        "ingredients/contents",
        "master_concept.archetype_reasoning",
    ),
    3: (
        "7-sheet pouch contendo 150 mL de ess\u00eancia",
        "product_feature",
        "ai_extracted_candidate",
    ),
    4: (
        "Lista de ingredientes espec\u00edficos (incluindo exossomos listados como ingrediente de condicionamento da pele, vitamina C derivada, ceramidas, atelocol\u00e1geno, etc.)",
        "ingredients/contents",
        "master_concept.archetype_reasoning",
    ),
    5: (
        "Demonstrar \u201c7-sheet pouch contendo 150 mL de ess\u00eancia\u201d",
        "product_feature",
        "master_concept.proof_or_demo_strategy",
    ),
    6: (
        "Listar textualmente os ingredientes verific\u00e1veis: human adipose-derived mesenchymal cell exosomes (mencionando que o fabricante afirma que n\u00e3o cont\u00eam c\u00e9lulas-tronco), glutathione, arbutin, ascorbyl palmitate, human recombinant oligopeptide-1, Ceramide AP, Ceramide NP, atelocollagen, hydroxypropyltrimonium hyaluronate.",
        "ingredients/contents",
        "master_concept.proof_or_demo_strategy",
    ),
    7: (
        "Destacar \u201cMelty Feel Sheet\u201d como frase descritiva fornecida pelo fabricante.",
        "product_feature",
        "master_concept.proof_or_demo_strategy",
    ),
    8: (
        "Exibir claramente os pontos \u201ccolorant-free, fragrance-free, mineral-oil-free, alcohol-free\u201d como caracter\u00edsticas declaradas",
        "ingredients/contents",
        "master_concept.proof_or_demo_strategy",
    ),
    9: (
        "LuLuLun Hydra EX 7 Sheets em um cen\u00e1rio editorial limpo",
        "product_identity",
        "master_concept.story_beats[1]",
    ),
    10: (
        "se trata da facial sheet mask LuLuLun Hydra EX, variante pouch com 7 folhas, Manufacturer sales name: Face Mask LuLuLun EX 1FS, contendo 150 mL de ess\u00eancia",
        "product_feature",
        "master_concept.story_beats[2]",
    ),
    11: (
        "M\u00e1scara facial em folha (sheet mask) em pouch com 7 unidades, categoria skincare geral",
        "product_feature",
        "master_concept.product_category_context",
    ),
    12: (
        "dado \u201c7 sheets / essence 150 mL\u201d, refor\u00e7ando que todas as m\u00e1scaras est\u00e3o no mesmo pouch",
        "product_feature",
        "master_concept.story_beats[3]",
    ),
    13: (
        "ingredientes verificados: human adipose-derived mesenchymal cell exosomes (com a observa\u00e7\u00e3o de que o fabricante afirma que n\u00e3o cont\u00eam c\u00e9lulas-tronco), glutathione, arbutin, ascorbyl palmitate (derivado de vitamina C), human recombinant oligopeptide-1, Ceramide AP, Ceramide NP, atelocollagen, hydroxypropyltrimonium hyaluronate",
        "ingredients/contents",
        "master_concept.story_beats[4]",
    ),
    14: (
        "uso poss\u00edvel pela manh\u00e3 ou \u00e0 noite em lugar do toner",
        "usage_instructions",
        "ai_extracted_candidate",
    ),
    15: (
        "Preservar fielmente a apar\u00eancia do pouch LuLuLun Hydra EX 7 Sheets, incluindo cores, logo, textos e propor\u00e7\u00f5es reais",
        "product_identity",
        "master_concept.must_include[1]",
    ),
    16: (
        "Mencionar que \u00e9 o 7-sheet pouch contendo 150 mL de ess\u00eancia",
        "product_feature",
        "master_concept.must_include[2]",
    ),
    17: (
        "Incluir a observa\u00e7\u00e3o verificada de que o fabricante afirma que os exossomos listados n\u00e3o cont\u00eam c\u00e9lulas-tronco",
        "ingredients/contents",
        "master_concept.must_include[4]",
    ),
    18: (
        "Destacar as caracter\u00edsticas declaradas da f\u00f3rmula: colorant-free, fragrance-free, mineral-oil-free e alcohol-free",
        "ingredients/contents",
        "master_concept.must_include[5]",
    ),
    19: (
        "Representar graficamente o modo de uso exatamente como descrito pelo fabricante",
        "usage_instructions",
        "master_concept.must_include[7]",
    ),
    20: (
        "Deixar claro que o uso pode ser pela manh\u00e3 ou \u00e0 noite em lugar do toner",
        "usage_instructions",
        "master_concept.must_include[8]",
    ),
    21: (
        "LuLuLun Hydra EX como \u201cm\u00e1scara laborat\u00f3rio\u201d: o que a gente sabe, de fato",
        "product_positioning",
        "ai_extracted_candidate",
    ),
    22: (
        "Cont\u00e9m exossomos de c\u00e9lulas-tronco mesenquimais derivadas de gordura humana como ingrediente de condicionamento da pele \u2014 e o pr\u00f3prio fabricante afirma que n\u00e3o h\u00e1 c\u00e9lulas-tronco contidas nesse ingrediente",
        "ingredients/contents",
        "ai_extracted_candidate",
    ),
    23: (
        "Sem corantes adicionados (colorant-free), segundo o fabricante",
        "ingredients/contents",
        "ai_extracted_candidate",
    ),
    24: (
        "Sem fragr\u00e2ncia adicionada (fragrance-free), segundo o fabricante",
        "ingredients/contents",
        "ai_extracted_candidate",
    ),
    25: (
        "Pressionar para tirar o ar preso",
        "usage_instructions",
        "ai_extracted_candidate",
    ),
    26: (
        "Erguer os cortes da regi\u00e3o das bochechas ao longo da linha do rosto",
        "usage_instructions",
        "ai_extracted_candidate",
    ),
    27: (
        "Depois de remover, o fabricante sugere dobrar a m\u00e1scara para usar em movimentos de \u201cwiping\u201d/leve batidinha",
        "usage_instructions",
        "ai_extracted_candidate",
    ),
    28: (
        "Em seguida, o fabricante indica finalizar com emuls\u00e3o ou creme",
        "usage_instructions",
        "ai_extracted_candidate",
    ),
    29: (
        "O que N\u00c3O est\u00e1 verificado (e que, por isso, n\u00e3o vamos afirmar aqui): \u2022 Benef\u00edcios garantidos na pele (como clarear, rejuvenescer, firmar, reduzir linhas, etc.)",
        "product_benefit_or_effect",
        "ai_extracted_candidate",
    ),
    30: (
        "O que N\u00c3O est\u00e1 verificado (e que, por isso, n\u00e3o vamos afirmar aqui): \u2022 Resultados vis\u00edveis em X dias ou minutos",
        "result_timing_or_magnitude",
        "ai_extracted_candidate",
    ),
    31: (
        "O que N\u00c3O est\u00e1 verificado (e que, por isso, n\u00e3o vamos afirmar aqui): \u2022 Pa\u00eds de origem ou local de fabrica\u00e7\u00e3o",
        "product_origin",
        "ai_extracted_candidate",
    ),
    32: (
        "O que N\u00c3O est\u00e1 verificado (e que, por isso, n\u00e3o vamos afirmar aqui): \u2022 Pre\u00e7o, disponibilidade, estoque ou status de \u201chit\u201d, \u201cviral\u201d ou \u201cmais vendido\u201d",
        "price_or_availability",
        "ai_extracted_candidate",
    ),
    33: (
        "A proposta aqui n\u00e3o \u00e9 prometer resultado \u2014 \u00e9 organizar o que J\u00c1 est\u00e1 confirmado sobre a LuLuLun Hydra EX 7 Sheets, sem extrapolar",
        "disclaimer_or_limitation",
        "copy.pt-BR.caption",
    ),
    34: (
        "Exossomos de c\u00e9lulas-tronco mesenquimais derivadas de gordura humana como ingrediente de condicionamento da pele, deixando claro que N\u00c3O h\u00e1 c\u00e9lulas-tronco contidas",
        "ingredients/contents",
        "copy.pt-BR.caption",
    ),
    35: (
        "Sem corante adicionado (colorant-free)",
        "ingredients/contents",
        "copy.pt-BR.caption",
    ),
    36: (
        "Depois de tirar, o fabricante sugere dobrar e usar para \u201cwiping\u201d/leve batidinha",
        "usage_instructions",
        "copy.pt-BR.caption",
    ),
    37: (
        "Nenhum resultado garantido (clarear, firmar, rejuvenescer, etc.)",
        "product_benefit_or_effect",
        "copy.pt-BR.caption",
    ),
    38: (
        "Nenhum prazo de \u201cem tantos dias\u201d ou \u201cem 10 minutos\u201d",
        "result_timing_or_magnitude",
        "copy.pt-BR.caption",
    ),
    39: (
        "Nenhuma info de origem, pre\u00e7o, estoque, ranking ou status de popularidade",
        "price_or_availability",
        "copy.pt-BR.caption",
    ),
    40: (
        "Sem corantes adicionados, sem fragr\u00e2ncia, sem \u00f3leo mineral, sem \u00e1lcool \u2013 conforme declara\u00e7\u00e3o do fabricante",
        "ingredients/contents",
        "creative.creative_brief.template_suggestion",
    ),
    41: (
        "Cont\u00e9m human adipose-derived mesenchymal cell exosomes como ingrediente de condicionamento de pele; o fabricante afirma que n\u00e3o cont\u00e9m c\u00e9lulas-tronco",
        "ingredients/contents",
        "creative.creative_brief.template_suggestion",
    ),
    42: (
        "O fabricante descreve o uso poss\u00edvel pela manh\u00e3 ou \u00e0 noite, em substitui\u00e7\u00e3o ao toner",
        "usage_instructions",
        "creative.creative_brief.template_suggestion",
    ),
}

CANONICAL_INDICES = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 13, 14, 16, 17, 18, 20, 22, 23, 24, 25, 26, 27, 28, 34, 35, 36, 40, 41, 42]
NONASSERTIVE_INDICES = [15, 19, 29, 30, 31, 32, 33, 37, 38, 39]
BLOCKED_INDICES = [11, 21]

def _verified():
    return SimpleNamespace(
        category=None,
        verified_description=(
            "LuLuLun Hydra EX facial sheet mask, exact 7-sheet pouch variant. "
            "Manufacturer sales name: Face Mask LuLuLun EX 1FS."
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
        verified_price="",
        verified_availability="",
        verified_country_of_origin="",
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
        prohibited_claims=[],
        missing_information=[
            "verified_benefits",
            "verified_price",
            "verified_availability",
            "verified_country_of_origin",
        ],
        provenance="manufacturer_official+owner_confirmed",
    )


def _finding(
    index,
    *,
    text=None,
    category=None,
    source=None,
):
    claim_text, claim_category, source_field = LIVE_CORPUS[index]

    return claims_audit.ClaimFinding(
        claim_text=claim_text if text is None else text,
        claim_category=claim_category if category is None else category,
        source_field=source_field if source is None else source,
        evidence_status="UNSUPPORTED",
        allowed_source="",
        reason="sealed V3.19 live audit finding",
    )


def _fields_for_corpus():
    fields = {}

    for index, (text, _category, source) in LIVE_CORPUS.items():
        if source == "ai_extracted_candidate":
            continue

        fields[source] = (
            fields.get(source, "")
            + (" | " if source in fields else "")
            + text
        )

    return fields


def _reconcile(findings, *, verified=None, fields=None):
    return (
        claims_audit
        ._build6r_v320_reconcile_live_semantic_candidates(
            claims_audit.ClaimAuditResult(findings=findings),
            _verified() if verified is None else verified,
            _fields_for_corpus() if fields is None else fields,
        )
    )


def _status(finding, *, verified=None, fields=None):
    return _reconcile(
        [finding],
        verified=verified,
        fields=fields,
    ).findings[0]


def test_v320_exact_authoritative_42_finding_contract():
    result = _reconcile(
        [_finding(index) for index in range(1, 43)]
    )

    assert len(result.findings) == 42

    supported = {
        index
        for index, finding in zip(range(1, 43), result.findings)
        if finding.evidence_status == "SUPPORTED"
    }

    unsupported = {
        index
        for index, finding in zip(range(1, 43), result.findings)
        if finding.evidence_status == "UNSUPPORTED"
    }

    assert supported == (set(CANONICAL_INDICES) | set(NONASSERTIVE_INDICES))
    assert unsupported == set(BLOCKED_INDICES)

    for index, finding in zip(range(1, 43), result.findings):
        if index in CANONICAL_INDICES:
            assert finding.allowed_source == "verified_product_facts"
            assert "V3.20" in finding.reason
        elif index in NONASSERTIVE_INDICES:
            assert finding.allowed_source == "non_assertive_statement"
            assert "non-assertion" in finding.reason
        else:
            assert finding.allowed_source == ""


def test_v320_exact_classification_partition_is_30_10_2():
    assert len(CANONICAL_INDICES) == 30
    assert len(NONASSERTIVE_INDICES) == 10
    assert len(BLOCKED_INDICES) == 2
    assert not (set(CANONICAL_INDICES) & set(NONASSERTIVE_INDICES))
    assert not (set(CANONICAL_INDICES) & set(BLOCKED_INDICES))
    assert not (set(NONASSERTIVE_INDICES) & set(BLOCKED_INDICES))
    assert (
        set(CANONICAL_INDICES)
        | set(NONASSERTIVE_INDICES)
        | set(BLOCKED_INDICES)
    ) == set(range(1, 43))


def test_v320_runtime_taxonomy_alias_for_ingredients_contents_is_bounded():
    finding = claims_audit.ClaimFinding(
        claim_text="colorant-free",
        claim_category="ingredients/contents",
        source_field="ai_extracted_candidate",
        evidence_status="UNSUPPORTED",
        allowed_source="",
        reason="taxonomy",
    )

    assert (
        claims_audit._build6r_v320_category_alias(finding)
        == "ingredients percentages"
    )


def test_v320_template_suggestion_is_the_only_new_direct_source():
    assert claims_audit._build6r_v320_source_field_allowed(
        "creative.creative_brief.template_suggestion"
    )
    assert not claims_audit._build6r_v320_source_field_allowed(
        "creative.creative_brief.unreviewed_future_field"
    )


def test_v320_blocked_live_finding_11_stays_unsupported():
    finding = _status(_finding(11))
    assert finding.evidence_status == "UNSUPPORTED"


def test_v320_blocked_live_finding_21_stays_unsupported():
    finding = _status(_finding(21))
    assert finding.evidence_status == "UNSUPPORTED"


def test_v320_unknown_source_stays_unsupported_even_for_canonical_fact():
    finding = _status(
        _finding(
            3,
            source="creative.creative_brief.unknown_future_field",
        )
    )
    assert finding.evidence_status == "UNSUPPORTED"


def test_v320_research_source_stays_non_evidence():
    finding = _status(
        _finding(
            3,
            source="strategy.research_basis[0]",
        )
    )
    assert finding.evidence_status == "UNSUPPORTED"


def test_v320_affirmative_benefit_stays_unsupported():
    finding = claims_audit.ClaimFinding(
        claim_text="Clareia e rejuvenesce a pele",
        claim_category="product_benefit_or_effect",
        source_field="copy.pt-BR.caption",
        evidence_status="UNSUPPORTED",
        allowed_source="",
        reason="safety",
    )
    assert _status(finding).evidence_status == "UNSUPPORTED"


def test_v320_affirmative_result_timing_stays_unsupported():
    finding = claims_audit.ClaimFinding(
        claim_text="Resultados visiveis em 10 minutos",
        claim_category="result_timing_or_magnitude",
        source_field="copy.pt-BR.caption",
        evidence_status="UNSUPPORTED",
        allowed_source="",
        reason="safety",
    )
    assert _status(finding).evidence_status == "UNSUPPORTED"


def test_v320_affirmative_price_availability_stays_unsupported():
    finding = claims_audit.ClaimFinding(
        claim_text="Em estoque por R$ 99",
        claim_category="price_or_availability",
        source_field="copy.pt-BR.caption",
        evidence_status="UNSUPPORTED",
        allowed_source="",
        reason="safety",
    )
    assert _status(finding).evidence_status == "UNSUPPORTED"


def test_v320_affirmative_origin_stays_unsupported_when_canonical_origin_empty():
    finding = claims_audit.ClaimFinding(
        claim_text="Fabricado no Japao",
        claim_category="product_origin",
        source_field="copy.pt-BR.caption",
        evidence_status="UNSUPPORTED",
        allowed_source="",
        reason="safety",
    )
    assert _status(finding).evidence_status == "UNSUPPORTED"


def test_v320_product_positioning_does_not_gain_a_canonical_route():
    finding = claims_audit.ClaimFinding(
        claim_text="Mascara laboratorio",
        claim_category="product_positioning",
        source_field="copy.pt-BR.caption",
        evidence_status="UNSUPPORTED",
        allowed_source="",
        reason="safety",
    )
    assert _status(finding).evidence_status == "UNSUPPORTED"


def test_v320_positive_stem_without_same_field_qualification_stays_unsupported():
    claim = (
        "Contem exossomos de celulas-tronco mesenquimais derivadas de "
        "gordura humana como ingrediente de condicionamento da pele"
    )
    finding = claims_audit.ClaimFinding(
        claim_text=claim,
        claim_category="ingredients/contents",
        source_field="ai_extracted_candidate",
        evidence_status="UNSUPPORTED",
        allowed_source="",
        reason="stem safety",
    )

    assert _status(finding, fields={}).evidence_status == "UNSUPPORTED"


def test_v320_positive_stem_same_generated_field_qualification_can_reconcile():
    claim = (
        "Contem exossomos de celulas-tronco mesenquimais derivadas de "
        "gordura humana como ingrediente de condicionamento da pele"
    )
    source = "copy.pt-BR.caption"
    finding = claims_audit.ClaimFinding(
        claim_text=claim,
        claim_category="ingredients/contents",
        source_field="ai_extracted_candidate",
        evidence_status="UNSUPPORTED",
        allowed_source="",
        reason="stem safety",
    )

    fields = {
        source: (
            claim
            + ". O fabricante afirma que esse ingrediente nao contem "
            + "celulas-tronco."
        )
    }

    result = _status(finding, fields=fields)
    assert result.evidence_status == "SUPPORTED"
    assert result.allowed_source == "verified_product_facts"


def test_v320_positive_stem_cross_field_qualification_stays_unsupported():
    claim = (
        "Contem exossomos de celulas-tronco mesenquimais derivadas de "
        "gordura humana como ingrediente de condicionamento da pele"
    )
    finding = claims_audit.ClaimFinding(
        claim_text=claim,
        claim_category="ingredients/contents",
        source_field="copy.pt-BR.caption",
        evidence_status="UNSUPPORTED",
        allowed_source="",
        reason="stem safety",
    )

    fields = {
        "copy.pt-BR.caption": claim,
        "copy.pt-BR.slide_2": (
            "O fabricante afirma que esse ingrediente nao contem "
            "celulas-tronco."
        ),
    }

    assert _status(finding, fields=fields).evidence_status == "UNSUPPORTED"


def test_v320_stem_reconciliation_requires_canonical_no_stem_backing():
    verified = deepcopy(_verified())

    verified.verified_claims = [
        value.replace(
            "manufacturer states stem cells are not contained",
            "",
        )
        for value in verified.verified_claims
    ]

    verified.verified_ingredients = [
        value.replace(
            "manufacturer states stem cells are not contained",
            "",
        )
        for value in verified.verified_ingredients
    ]

    assert (
        _status(
            _finding(22),
            verified=verified,
            fields={},
        ).evidence_status
        == "UNSUPPORTED"
    )


def test_v320_nonassertive_benefit_guard_rejects_contrast_escape():
    finding = claims_audit.ClaimFinding(
        claim_text=(
            "Nenhum resultado garantido, mas clareia e rejuvenesce a pele"
        ),
        claim_category="product_benefit_or_effect",
        source_field="copy.pt-BR.caption",
        evidence_status="UNSUPPORTED",
        allowed_source="",
        reason="safety",
    )
    assert _status(finding).evidence_status == "UNSUPPORTED"


def test_v320_nonassertive_price_guard_rejects_contrast_escape():
    finding = claims_audit.ClaimFinding(
        claim_text=(
            "Nenhuma info de preco, estoque ou ranking, mas esta em estoque"
        ),
        claim_category="price_or_availability",
        source_field="copy.pt-BR.caption",
        evidence_status="UNSUPPORTED",
        allowed_source="",
        reason="safety",
    )
    assert _status(finding).evidence_status == "UNSUPPORTED"


def test_v320_visual_fidelity_directive_rejects_concrete_color():
    finding = claims_audit.ClaimFinding(
        claim_text=(
            "Preservar fielmente a aparencia do pouch, incluindo cores, "
            "logo, textos e proporcoes reais, com embalagem vermelha"
        ),
        claim_category="product_identity",
        source_field="master_concept.must_include[1]",
        evidence_status="UNSUPPORTED",
        allowed_source="",
        reason="safety",
    )
    assert _status(finding).evidence_status == "UNSUPPORTED"


def test_v320_generic_usage_directive_rejects_added_action():
    finding = claims_audit.ClaimFinding(
        claim_text=(
            "Representar graficamente o modo de uso exatamente como "
            "descrito pelo fabricante e deixar por 20 minutos"
        ),
        claim_category="usage_instructions",
        source_field="master_concept.must_include[7]",
        evidence_status="UNSUPPORTED",
        allowed_source="",
        reason="safety",
    )
    assert _status(finding).evidence_status == "UNSUPPORTED"


def test_v320_noop_reconciliation_preserves_result_identity():
    original = claims_audit.ClaimAuditResult(findings=[])
    returned = (
        claims_audit
        ._build6r_v320_reconcile_live_semantic_candidates(
            original,
            _verified(),
            {},
        )
    )
    assert returned is original


def test_v320_supported_reconciliation_preserves_generated_text_and_taxonomy():
    original = _finding(3)
    result = _status(original)

    assert result.evidence_status == "SUPPORTED"
    assert result.claim_text == original.claim_text
    assert result.claim_category == original.claim_category
    assert result.source_field == original.source_field


def test_v320_nonassertive_reconciliation_is_not_labeled_verified_product_facts():
    result = _status(_finding(29))
    assert result.evidence_status == "SUPPORTED"
    assert result.allowed_source == "non_assertive_statement"
    assert result.allowed_source != "verified_product_facts"


def test_v320_production_layer_contains_no_product_specific_whitelist_or_io():
    source = inspect.getsource(claims_audit)
    marker = "BUILD6R_LIVE_SEMANTIC_TAXONOMY_PARAPHRASE_RECONCILIATION_V3_20"
    assert source.count(marker) == 1

    tail = source[source.index(marker):].lower()

    for forbidden in (
        "lululun",
        "hydra",
        "campaign_id",
        "product_id",
        "067c96",
        "7d927e",
        "openai",
        "httpx.",
        "requests.",
        "sqlite3",
        "rapidfuzz",
        "difflib",
        "sequencematcher",
        "embedding",
        "cosine",
        "generate_structured(",
        "generate_image(",
        "edit_image(",
    ):
        assert forbidden not in tail


def test_v320_wrapper_executes_sealed_v319_chain_exactly_once(monkeypatch):
    original = claims_audit.ClaimAuditResult(findings=[])
    calls = {"count": 0}

    async def fake_previous(*args, **kwargs):
        calls["count"] += 1
        return original

    monkeypatch.setattr(
        claims_audit,
        "_build6r_augment_before_v320",
        fake_previous,
    )

    returned = asyncio.run(
        claims_audit.augment_with_ai_extraction(
            verified=_verified(),
            fields={},
        )
    )

    assert calls["count"] == 1
    assert returned is original
