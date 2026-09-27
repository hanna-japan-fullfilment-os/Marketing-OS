from __future__ import annotations

import asyncio
import inspect
from types import SimpleNamespace

import pytest

import app.services.claims_audit as claims_audit
import app.services.orchestrator as orchestrator


LIVE_42_CAMPAIGN_ID = "466987c226b64949a95a4a9378b9b073"
LIVE_49_CAMPAIGN_ID = "26a9081bae2044c697c1b57098f1090b"

LIVE_42 = [('LuLuLun Hydra EX Mask 7 Sheets é uma máscara facial em pouch com 7 unidades e 150 mL de essência',
  'product structure/format',
  'ai_extracted_candidate'),
 ('combinação específica de ingredientes — como exossomos derivados de células-tronco de tecido adiposo '
  'humano (sem conter células-tronco, segundo o fabricante), glutathione, arbutin, derivado de vitamina C, '
  'ceramidas, atelocolágeno e ácido hialurônico modificado',
  'ingredients/composition',
  'ai_extracted_candidate'),
 ('sheet descrito pelo fabricante como Melty Feel Sheet',
  'product feature/material',
  'ai_extracted_candidate'),
 ('livre de corantes, fragrância, óleo mineral e álcool, segundo o fabricante',
  'ingredients free-from claim',
  'ai_extracted_candidate'),
 ('é apresentada como uma máscara facial em pouch com 7 unidades e 150 mL de essência',
  'product structure/format',
  'master_concept.key_message'),
 ('incluindo exossomos derivados de células-tronco de tecido adiposo humano (sem conter células-tronco, '
  'segundo o fabricante), glutathione, arbutin, derivado de vitamina C, ceramidas, atelocolágeno, ácido '
  'hialurônico modificado e human recombinant oligopeptide-1',
  'ingredients/composition',
  'master_concept.key_message'),
 ('colorant-free, fragrance-free, mineral-oil-free e alcohol-free, segundo o fabricante',
  'ingredients free-from claim',
  'ai_extracted_candidate'),
 ('7-sheet pouch, 150 mL de essência', 'product structure/format', 'ai_extracted_candidate'),
 ('human adipose-derived mesenchymal cell exosomes (citando que o fabricante afirma não conter '
  'células-tronco)',
  'ingredients/composition',
  'master_concept.proof_or_demo_strategy'),
 ('glutathione, arbutin, ascorbyl palmitate, human recombinant oligopeptide-1, Ceramide AP, Ceramide NP, '
  'atelocollagen e hydroxypropyltrimonium hyaluronate',
  'ingredients/composition',
  'ai_extracted_candidate'),
 ('colorant-free, fragrance-free, mineral-oil-free, alcohol-free',
  'ingredients free-from claim',
  'ai_extracted_candidate'),
 ('pouch com 7 sheets e 150 mL de essência', 'product structure/format', 'ai_extracted_candidate'),
 ('human adipose-derived mesenchymal cell exosomes (mencionando que o fabricante afirma que não contêm '
  'células-tronco)',
  'ingredients/composition',
  'master_concept.story_beats[3]'),
 ('colorant-free, fragrance-free, mineral-oil-free e alcohol-free',
  'ingredients free-from claim',
  'ai_extracted_candidate'),
 ('desdobrar, ajustar em torno dos olhos e boca, pressionar para tirar o ar, levantar cortes das bochechas e '
  'pressionar, depois remover, usar para wiping/light patting e seguir com emulsion ou cream, podendo ser '
  'usado de manhã ou à noite em vez de tônico',
  'directions for use',
  'master_concept.story_beats[5]'),
 ('É um pouch com 7 máscaras faciais e 150 mL de essência',
  'product structure/format',
  'ai_extracted_candidate'),
 ('exossomos derivados de células-tronco de tecido adiposo humano como ingrediente de condicionamento da '
  'pele — e deixa claro que não contêm células-tronco — além de glutathione, arbutin, o derivado de vitamina '
  'C ascorbyl palmitate, human recombinant oligopeptide-1, ceramide AP, ceramide NP, atelocolágeno e '
  'hydroxypropyltrimonium hyaluronate',
  'ingredients/composition',
  'copy.pt-BR.supporting_copy'),
 ('A folha é descrita pelo fabricante como “Melty Feel Sheet”',
  'product feature/material',
  'copy.pt-BR.supporting_copy'),
 ('Segundo o fabricante, a fórmula é livre de corantes, fragrância, óleo mineral e álcool',
  'ingredients free-from claim',
  'copy.pt-BR.supporting_copy'),
 ('Na parte de uso, o fabricante orienta: desdobrar a máscara, ajustar ao redor dos olhos e da boca, tirar o '
  'ar preso, levantar os recortes das bochechas ao longo da linha do rosto e, depois, pressionar tudo com as '
  'palmas',
  'directions for use',
  'copy.pt-BR.supporting_copy'),
 ('Após remover, sugerem dobrar a máscara para passar no rosto com leves batidinhas e seguir com emulsão ou '
  'creme',
  'directions for use',
  'copy.pt-BR.supporting_copy'),
 ('A marca também descreve a Hydra EX como uma opção que pode ser usada de manhã ou à noite no lugar do '
  'tônico',
  'directions for use/usage context',
  'copy.pt-BR.supporting_copy'),
 ('Formato: um pouch com 7 máscaras faciais e 150 mL de essência',
  'product structure/format',
  'copy.pt-BR.caption'),
 ('Ingredientes que o fabricante destaca na lista: exossomos derivados de células-tronco de tecido adiposo '
  'humano como ingrediente de condicionamento da pele (com a observação de que não contêm células-tronco), '
  'glutathione, arbutin, o derivado de vitamina C ascorbyl palmitate, human recombinant oligopeptide-1, '
  'ceramide AP, ceramide NP, atelocolágeno e hydroxypropyltrimonium hyaluronate',
  'ingredients/composition',
  'copy.pt-BR.caption'),
 ('Tecido: o sheet é descrito como “Melty Feel Sheet”', 'product feature/material', 'copy.pt-BR.caption'),
 ('Formulação, segundo o fabricante: colorant-free, fragrance-free, mineral-oil-free, alcohol-free (ou seja, '
  'livre de corantes, fragrância, óleo mineral e álcool)',
  'ingredients free-from claim',
  'copy.pt-BR.caption'),
 ('Modo de uso descrito pelo fabricante: desdobrar a máscara, ajustar em volta de olhos e boca, tirar o ar '
  'preso, levantar os recortes da bochecha ao longo da linha do rosto e pressionar com as palmas',
  'directions for use',
  'copy.pt-BR.caption'),
 ('Depois de tirar, usar a própria máscara dobrada para passar no rosto com batidinhas leves e finalizar com '
  'emulsão ou creme',
  'directions for use',
  'copy.pt-BR.caption'),
 ('Eles também descrevem que pode ser usada de manhã ou à noite no lugar do tônico',
  'directions for use/usage context',
  'copy.pt-BR.caption'),
 ('Máscara facial em pouch com 7 sheets',
  'product structure/format',
  'creative.creative_brief.template_suggestion'),
 ('Conteúdo de 150 mL de essência (informação do fabricante)',
  'product structure/format',
  'creative.creative_brief.template_suggestion'),
 ('Exossomos derivados de células-tronco de tecido adiposo humano como ingrediente de condicionamento da '
  'pele, listado pelo fabricante',
  'ingredients/composition',
  'creative.creative_brief.template_suggestion'),
 ('Segundo o fabricante, esse ingrediente não contém células-tronco',
  'ingredient property/qualification',
  'creative.creative_brief.template_suggestion'),
 ('Ascorbyl palmitate (derivado de vitamina C)', 'ingredients/composition', 'ai_extracted_candidate'),
 ('Sheet descrito pelo fabricante como “Melty Feel Sheet”',
  'product feature/material',
  'creative.creative_brief.template_suggestion'),
 ('Segundo o fabricante, a fórmula é colorant-free, fragrance-free, mineral-oil-free e alcohol-free',
  'ingredients free-from claim',
  'creative.creative_brief.template_suggestion'),
 ('O fabricante descreve a folha como “Melty Feel Sheet”',
  'product feature/material',
  'creative.languages.pt-BR.carousel_plan.slides[4].body'),
 ('Diz também que a fórmula é livre de corantes, fragrância, óleo mineral e álcool',
  'ingredients free-from claim',
  'creative.languages.pt-BR.carousel_plan.slides[4].body'),
 ('o rótulo orienta: desdobrar a máscara, ajustar ao redor dos olhos e da boca, tirar o ar preso, levantar '
  'os recortes das bochechas ao longo da linha do rosto e pressionar com as palmas',
  'directions for use',
  'creative.languages.pt-BR.carousel_plan.slides[4].body'),
 ('Depois de remover, sugerem dobrar a máscara pra passar no rosto com leves batidinhas e seguir com emulsão '
  'ou creme',
  'directions for use',
  'creative.languages.pt-BR.carousel_plan.slides[4].body'),
 ('A marca ainda descreve a Hydra EX como uma opção que pode ser usada de manhã ou à noite no lugar do '
  'tônico',
  'directions for use/usage context',
  'creative.languages.pt-BR.carousel_plan.slides[4].body'),
 ('LuLuLun Hydra EX Mask 7 Sheets', 'product identity/name', 'ai_extracted_candidate')]

LIVE_49 = [('pensada para entrar no lugar do tônico, de manhã ou à noite, com um modo de uso simples e direto',
  'product usage/placement in routine',
  'ai_extracted_candidate'),
 ('A LuLuLun Hydra EX 7 Sheets tem especificações claras (pouch com 7 folhas, 150 mL de essência, usos '
  'sugeridos pelo fabricante, fórmula sem corante, sem fragrância, sem óleo mineral e sem álcool)',
  'ingredients/contents',
  'strategy.reason_this_should_work'),
 ('A própria marca trabalha a linha Hydra como passo comparável ao tônico e a embalagem multi-sheet como '
  'formato de uso frequente',
  'product usage/placement in routine',
  'strategy.research_basis[2]'),
 ('Apresentar a LuLuLun Hydra EX Mask 7 Sheets como um exemplo claro e didático de sheet mask japonesa',
  'product category/positioning',
  'master_concept.campaign_promise'),
 ('que o fabricante descreve como utilizável de manhã ou à noite no lugar do tônico',
  'product usage/placement in routine',
  'master_concept.key_message'),
 ('Máscara facial em tecido (sheet mask) em pouch multi-sheet, usada como etapa de cuidado da pele do rosto, '
  'com 7 unidades e 150 mL de essência',
  'ingredients/contents',
  'master_concept.product_category_context'),
 ('uso descrito pelo fabricante como podendo substituir o tônico pela manhã ou à noite',
  'product usage/placement in routine',
  'master_concept.product_category_context'),
 ('O pouch 7-sheet é sempre mostrado com proporções, cores, logo e detalhes fiéis',
  'visual/representation claim',
  'master_concept.visual_identity'),
 ('Representação fiel do passo a passo do fabricante',
  'product usage/placement in routine',
  'master_concept.proof_or_demo_strategy'),
 ('textos curtos junto ao produto reforçando "7 sheets / 150 mL de essência"',
  'ingredients/contents',
  'master_concept.proof_or_demo_strategy'),
 ('o que é uma sheet mask japonesa, mostrando a LuLuLun Hydra EX 7 Sheets como exemplo concreto de máscara '
  'facial em tecido em pouch multi-sheet',
  'product category/positioning',
  'master_concept.story_beats[1]'),
 ('visual simples que mostra a máscara como etapa que pode ser usada de manhã ou à noite no lugar do tônico, '
  'conforme o fabricante descreve',
  'product usage/placement in routine',
  'master_concept.story_beats[2]'),
 ('close no pouch destacando objetivamente que são 7 sheets com 150 mL de essência',
  'ingredients/contents',
  'master_concept.story_beats[3]'),
 ('ser colorant-free, fragrance-free, mineral-oil-free, alcohol-free',
  'ingredients/contents',
  'ai_extracted_candidate'),
 ('nome de venda Face Mask LuLuLun EX 1FS', 'product identity', 'master_concept.must_include[3]'),
 ('o fabricante descreve a folha como Melty Feel Sheet',
  'product feature/texture',
  'master_concept.must_include[4]'),
 ('Listar apenas os ingredientes confirmados: human adipose-derived mesenchymal cell exosomes (com a '
  'ressalva de que o fabricante afirma não conter células-tronco), glutathione, arbutin, ascorbyl palmitate, '
  'human recombinant oligopeptide-1, ceramide AP, ceramide NP, atelocollagen e hydroxypropyltrimonium '
  'hyaluronate',
  'ingredients/contents',
  'master_concept.must_include[6]'),
 ('Explicar visualmente o passo a passo de aplicação exatamente como descrito pelo fabricante',
  'product usage/placement in routine',
  'master_concept.must_include[7]'),
 ('LuLuLun Hydra EX Mask 7 Sheets é usada como exemplo didático de sheet mask japonesa',
  'product category/positioning',
  'master_concept.must_include[1]'),
 ('Mencionar de forma fiel que o fabricante descreve o uso da máscara como podendo ser de manhã ou à noite '
  'no lugar do tônico',
  'product usage/placement in routine',
  'master_concept.must_include[2]'),
 ('Incluir explicitamente os dados verificados: 7 sheets, 150 mL de essência, nome de venda Face Mask '
  'LuLuLun EX 1FS',
  'ingredients/contents',
  'master_concept.must_include[3]'),
 ('Citar que o fabricante descreve a folha como Melty Feel Sheet',
  'product feature/texture',
  'master_concept.must_include[4]'),
 ('Mencionar de forma correta que a fórmula é colorant-free, fragrance-free, mineral-oil-free e alcohol-free',
  'ingredients/contents',
  'master_concept.must_include[5]'),
 ('O pouch da LuLuLun Hydra EX Mask 7 Sheets em destaque sobre um fundo limpo e claro',
  'visual/representation claim',
  'ai_extracted_candidate'),
 ('Uma sheet mask facial (máscara em tecido embebida em essência)',
  'product category/positioning',
  'ai_extracted_candidate'),
 ('O fabricante descreve o tecido como Melty Feel Sheet',
  'product feature/texture',
  'ai_extracted_candidate'),
 ('Entre os ingredientes listados pelo fabricante estão: human adipose-derived mesenchymal cell exosomes (o '
  'fabricante indica que esse ingrediente não contém células-tronco), glutationa, arbutina, derivado de '
  'vitamina C (ascorbyl palmitate), ceramida AP, ceramida NP, atelocolágeno, hydroxypropyltrimonium '
  'hyaluronate e human recombinant oligopeptide-1 (EGF)',
  'ingredients/contents',
  'ai_extracted_candidate'),
 ('O próprio fabricante sugere usar a LuLuLun Hydra EX no lugar do tônico, de manhã ou à noite',
  'product usage/placement in routine',
  'ai_extracted_candidate'),
 ('A ordem básica fica assim: 1) Limpeza 2) LuLuLun Hydra EX Mask 7 Sheets (ocupando o passo do tônico) 3) '
  'Emulsão ou creme',
  'product usage/placement in routine',
  'ai_extracted_candidate'),
 ('Depois de remover, o fabricante sugere dobrar a máscara e usar para dar leves batidinhas/“wiping”',
  'product usage/placement in routine',
  'ai_extracted_candidate'),
 ('Finalize com emulsão ou creme', 'product usage/placement in routine', 'ai_extracted_candidate'),
 ('você pode usar a Hydra EX de manhã ou à noite, sempre no lugar do tônico',
  'product usage/placement in routine',
  'ai_extracted_candidate'),
 ('um formato em tecido, em pouch com 7 folhas e 150 mL de essência, com modo de uso direto',
  'ingredients/contents',
  'copy.pt-BR.supporting_copy'),
 ('Pouch da LuLuLun Hydra EX Mask 7 Sheets em destaque no centro, bem nítido, respeitando cores e proporções '
  'reais da embalagem',
  'visual/representation claim',
  'ai_extracted_candidate'),
 ('É uma sheet mask facial em pouch, com 7 máscaras dentro',
  'ingredients/contents',
  'ai_extracted_candidate'),
 ('O pouch tem 150 mL de essência', 'ingredients/contents', 'ai_extracted_candidate'),
 ('O fabricante sugere usar no lugar do tônico, de manhã ou à noite',
  'product usage/placement in routine',
  'ai_extracted_candidate'),
 ('Depois da máscara, ele indica seguir com emulsão ou creme',
  'product usage/placement in routine',
  'ai_extracted_candidate'),
 ('A fórmula é descrita pelo fabricante como sem corante, sem fragrância, sem óleo mineral e sem álcool',
  'ingredients/contents',
  'ai_extracted_candidate'),
 ('O tecido é descrito como Melty Feel Sheet', 'product feature/texture', 'ai_extracted_candidate'),
 ('Entre os ingredientes listados pelo fabricante estão human adipose-derived mesenchymal cell exosomes (sem '
  'células-tronco, segundo o fabricante), glutationa, arbutina, derivado de vitamina C (ascorbyl palmitate), '
  'ceramida AP, ceramida NP, atelocolágeno, hydroxypropyltrimonium hyaluronate e human recombinant '
  'oligopeptide-1 (EGF)',
  'ingredients/contents',
  'ai_extracted_candidate'),
 ('O próprio fabricante sugere usar a LuLuLun Hydra EX Mask 7 Sheets no lugar do tônico, de manhã ou à noite',
  'product usage/placement in routine',
  'ai_extracted_candidate'),
 ('É uma sheet mask facial (máscara em tecido embebida em essência)',
  'product category/positioning',
  'ai_extracted_candidate'),
 ('O fabricante descreve o tecido como “Melty Feel Sheet”',
  'product feature/texture',
  'ai_extracted_candidate'),
 ('Entre os ingredientes listados pelo fabricante estão, por exemplo, glutationa, arbutina, derivado de '
  'vitamina C (ascorbyl palmitate), ceramidas AP e NP, atelocolágeno, hydroxypropyltrimonium hyaluronate e '
  'human recombinant oligopeptide-1 (EGF), além de human adipose-derived mesenchymal cell exosomes (que o '
  'fabricante indica que não contêm células-tronco)',
  'ingredients/contents',
  'ai_extracted_candidate'),
 ('La LuLuLun Hydra EX Mask 7 Sheets é uma sheet mask facial em pouch com 7 unidades e 150 mL de essência',
  'ingredients/contents',
  'ai_extracted_candidate'),
 ('O fabricante orienta o uso no lugar do tônico, de manhã ou à noite, com um modo de uso simples e direto',
  'product usage/placement in routine',
  'creative.creative_brief.visual_prompt'),
 ('Contém human adipose-derived mesenchymal cell exosomes como ingrediente de condicionamento da pele, '
  'segundo o fabricante. O fabricante informa que não há células-tronco nesse ingrediente',
  'ingredients/contents',
  'ai_extracted_candidate'),
 ('Contém human recombinant oligopeptide-1 (EGF), segundo o fabricante',
  'ingredients/contents',
  'ai_extracted_candidate')]

SUPPORTED_49 = {
    5, 6, 7, 10, 12, 13, 14, 15, 16, 17, 20, 21, 22, 23,
    26, 27, 28, 30, 31, 35, 36, 37, 38, 39, 40, 41, 42, 44,
    45, 46, 48, 49,
}

BLOCKED_49 = {
    1, 2, 3, 4, 11, 19, 25, 29, 32, 33, 43, 47,
}

NONFACTUAL_49 = {
    8, 9, 18, 24, 34,
}


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
        verified_size="7 sheets / essence 150 mL",
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
                "ingredient; manufacturer states stem cells are not "
                "contained"
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
    )


def _finding(text, category, source_field):
    return claims_audit.ClaimFinding(
        claim_text=text,
        claim_category=category,
        source_field=source_field,
        evidence_status="UNSUPPORTED",
        allowed_source="",
        reason="synthetic V3.5 replay target",
    )


def _reconcile(items):
    return claims_audit._build6r_reconcile_generated_semantic_findings_v35(
        claims_audit.ClaimAuditResult(
            findings=[
                _finding(*item)
                for item in items
            ]
        ),
        _verified(),
    )


def _by_text(result):
    return {
        finding.claim_text: finding
        for finding in result.findings
    }


def test_exact_live_42_replay_all_canonical_findings_support():
    result = _reconcile(LIVE_42)
    assert len(result.findings) == 42
    assert all(
        finding.evidence_status == "SUPPORTED"
        for finding in result.findings
    )
    assert all(
        finding.allowed_source == "verified_product_facts"
        for finding in result.findings
    )


def test_live_42_category_fuzz_does_not_change_support():
    fuzzed = [
        (text, "arbitrary model category wording", source)
        for text, _category, source in LIVE_42
    ]
    result = _reconcile(fuzzed)
    assert len(result.findings) == 42
    assert all(
        finding.evidence_status == "SUPPORTED"
        for finding in result.findings
    )


def test_exact_live_49_replay_has_expected_three_way_split():
    result = _reconcile(LIVE_49)
    actual = _by_text(result)

    assert len(result.findings) == 44

    for index, (text, _category, _source) in enumerate(LIVE_49, 1):
        if index in NONFACTUAL_49:
            assert text not in actual
            continue

        assert text in actual

        if index in SUPPORTED_49:
            assert actual[text].evidence_status == "SUPPORTED"
            assert actual[text].allowed_source == "verified_product_facts"
        else:
            assert index in BLOCKED_49
            assert actual[text].evidence_status == "UNSUPPORTED"


def test_live_49_supported_category_fuzz_is_category_independent():
    items = [
        (text, "totally different free form category", source)
        for index, (text, _category, source) in enumerate(LIVE_49, 1)
        if index in SUPPORTED_49
    ]
    result = _reconcile(items)
    assert len(result.findings) == len(SUPPORTED_49)
    assert all(
        finding.evidence_status == "SUPPORTED"
        for finding in result.findings
    )


def test_live_49_blocked_findings_remain_fail_closed_under_category_fuzz():
    items = [
        (text, "benign looking category", source)
        for index, (text, _category, source) in enumerate(LIVE_49, 1)
        if index in BLOCKED_49
    ]
    result = _reconcile(items)
    assert len(result.findings) == len(BLOCKED_49)
    assert all(
        finding.evidence_status == "UNSUPPORTED"
        for finding in result.findings
    )


def test_nonfactual_visual_filter_is_narrow_and_source_aware():
    result = _reconcile([
        LIVE_49[index - 1]
        for index in sorted(NONFACTUAL_49)
    ])
    assert result.findings == []

    factual_visual_prompt = _reconcile([
        (
            "O fabricante orienta o uso no lugar do tonico, de manha ou a noite, "
            "com um modo de uso simples e direto",
            "visual/representation claim",
            "creative.creative_brief.visual_prompt",
        )
    ])
    assert len(factual_visual_prompt.findings) == 1
    assert factual_visual_prompt.findings[0].evidence_status == "UNSUPPORTED"


def test_research_source_never_becomes_product_fact_evidence():
    result = _reconcile([
        (
            "LuLuLun Hydra EX Mask 7 Sheets em pouch com 7 unidades e 150 mL de essencia",
            "anything",
            "strategy.research_basis[0]",
        )
    ])
    assert result.findings[0].evidence_status == "UNSUPPORTED"


def test_v35_alias_removal_requires_actual_progress():
    original = "7 sheet masks em um pouch"

    updated, found = (
        claims_audit._build6r_v35_remove_first_alias(
            original,
            (
                "sheet mask",
            ),
        )
    )

    assert updated == original
    assert found == ""

    updated, found = (
        claims_audit._build6r_v35_remove_first_alias(
            original,
            (
                "sheet masks",
            ),
        )
    )

    assert updated != original
    assert found == "sheet masks"


@pytest.mark.parametrize(
    "text",
    [
        "7 sheets e 150 mL de essencia, bestseller no Japao",
        "Melty Feel Sheet premium e superior",
        "Pode ser usada todos os dias no lugar do tonico",
        "Mascara facial em tecido embebida em essencia",
        "7 sheets e 150 mL de essencia com resultados visiveis",
        "O pouch esta em estoque agora",
    ],
)
def test_mixed_or_unsupported_residue_remains_fail_closed(text):
    result = _reconcile([
        (
            text,
            "arbitrary",
            "ai_extracted_candidate",
        )
    ])
    assert result.findings[0].evidence_status == "UNSUPPORTED"


@pytest.mark.parametrize(
    "text",
    [
        "Guia rapido de sheet mask japonesa - use a LuLuLun Hydra EX Mask 7 Sheets como exemplo concreto",
        "A LuLuLun Hydra EX 7 Sheets tem especificacoes claras (pouch com 7 folhas, 150 mL de essencia)",
        "A propria marca trabalha a linha Hydra como passo comparavel ao tonico e formato de uso frequente",
    ],
)
def test_strategy_product_fact_containment_flags_unsupported_product_assertions(text):
    assert claims_audit._build6r_v35_strategy_product_fact_violation(
        text,
        _verified(),
    )


@pytest.mark.parametrize(
    "text",
    [
        "LuLuLun Hydra EX Mask 7 Sheets: 7 sheets / 150 mL de essencia",
        "Decodificando o rotulo: por dentro da formula e do tecido",
        "Sheet masks are trending in Brazil",
    ],
)
def test_strategy_product_fact_containment_allows_canonical_or_generic_strategy(text):
    assert not claims_audit._build6r_v35_strategy_product_fact_violation(
        text,
        _verified(),
    )


def test_strategy_containment_enforcer_fails_before_persistence(monkeypatch):
    campaign = SimpleNamespace(id="campaign-v35", status="IDEA")
    audit_calls = []

    class FakeDB:
        def __init__(self):
            self.commits = 0

        def commit(self):
            self.commits += 1

    db = FakeDB()

    monkeypatch.setattr(
        orchestrator,
        "_audit",
        lambda *args, **kwargs: audit_calls.append((args, kwargs)),
    )

    accepted = SimpleNamespace(
        model_dump=lambda: {
            "angle": (
                "Guia rapido de sheet mask japonesa - use a "
                "LuLuLun Hydra EX Mask 7 Sheets como exemplo concreto"
            ),
            "key_message": "Learn the label",
            "reason_this_should_work": "Educational structure",
            "research_basis": [],
        }
    )

    with pytest.raises(
        orchestrator.PreVisualClaimGroundingError,
        match="PREVISUAL_UNSUPPORTED_STRATEGY_CLAIM",
    ):
        orchestrator._build6r_v35_enforce_strategy_containment(
            db,
            campaign=campaign,
            accepted=accepted,
            verified=_verified(),
        )

    assert campaign.status == "FAILED"
    assert db.commits == 1
    assert audit_calls
    assert audit_calls[0][0][2] == "strategy_candidate_claim_grounding_failed"


def test_strategy_containment_enforcer_allows_canonical_without_commit(monkeypatch):
    campaign = SimpleNamespace(id="campaign-v35-ok", status="IDEA")
    audit_calls = []

    class FakeDB:
        def commit(self):
            raise AssertionError(
                "canonical strategy must not force a containment commit"
            )

    db = FakeDB()

    monkeypatch.setattr(
        orchestrator,
        "_audit",
        lambda *args, **kwargs: audit_calls.append((args, kwargs)),
    )

    accepted = SimpleNamespace(
        model_dump=lambda: {
            "angle": "Decodificando o rotulo: por dentro da formula e do tecido",
            "key_message": (
                "LuLuLun Hydra EX Mask 7 Sheets: "
                "7 sheets / 150 mL de essencia"
            ),
            "reason_this_should_work": "Educational structure",
            "research_basis": [],
        }
    )

    result = orchestrator._build6r_v35_enforce_strategy_containment(
        db,
        campaign=campaign,
        accepted=accepted,
        verified=_verified(),
    )

    assert result == []
    assert campaign.status == "IDEA"
    assert audit_calls == []


def test_v35_strategy_integration_preserves_single_function_and_legacy_order():
    module_source = inspect.getsource(orchestrator)
    module_tree = __import__("ast").parse(module_source)
    ast_module = __import__("ast")

    strategy_defs = [
        node
        for node in module_tree.body
        if isinstance(
            node,
            (
                ast_module.FunctionDef,
                ast_module.AsyncFunctionDef,
            ),
        )
        and node.name == "run_strategy_stage"
    ]

    assert len(strategy_defs) == 1

    source = inspect.getsource(
        orchestrator.run_strategy_stage
    )

    assert source.count(
        "_build6r_v35_enforce_strategy_containment("
    ) == 1

    assert (
        source.index(
            "_build6r_v35_enforce_strategy_containment("
        )
        <
        source.index(
            "_enforce_generated_claim_grounding_gate("
        )
        <
        source.index(
            "campaign.audience = accepted.audience"
        )
    )

    assert source.count(
        "_sparse_fact_grounding_instruction()"
    ) == 1

    for marker in (
        "RESEARCH-TO-FACT HARD STOP",
        "cultural norms",
        "pharmacy presence",
        "brand-role claims",
        "resolve_verified_product_facts(db, product)",
        "strategy_type_operational_evidence_failed",
        "PREVISUAL_NO_VERIFIED_OPERATIONAL_STRATEGY",
    ):
        assert marker in source

    assert (
        source.index(
            "strategy_type_operational_evidence_failed"
        )
        <
        source.index(
            "run_research("
        )
    )




def test_v35_wrapper_preserves_v34_chain_and_is_content_first():
    source = inspect.getsource(
        claims_audit.augment_with_ai_extraction
    )
    assert "_build6r_augment_before_v35" in source
    assert "_build6r_reconcile_generated_semantic_findings_v35" in source

    content_source = inspect.getsource(
        claims_audit._build6r_v35_content_supported
    )
    assert "claim_category" not in content_source


def test_v35_strategy_containment_is_zero_cost_itself():
    source = "\n".join(
        (
            inspect.getsource(
                orchestrator._build6r_v35_strategy_containment_failures
            ),
            inspect.getsource(
                orchestrator._build6r_v35_enforce_strategy_containment
            ),
        )
    )

    for forbidden in (
        "generate_structured",
        "generate_image",
        "edit_image",
        "research_provider.research",
        "httpx",
        "requests.",
        "socket.",
    ):
        assert forbidden not in source

    strategy_source = inspect.getsource(
        orchestrator.run_strategy_stage
    )

    assert (
        "_build6r_v35_enforce_strategy_containment("
        in strategy_source
    )
    assert "strategy_candidate_claim_grounding_failed" in source




def test_v35_claims_layer_has_no_provider_or_network_path():
    names = (
        "_build6r_v35_source_field_allowed",
        "_build6r_v35_remove_first_alias",
        "_build6r_v35_blocked_residue",
        "_build6r_v35_nonfactual_visual_instruction",
        "_build6r_v35_content_supported",
        "_build6r_v35_contextual_exosome_sources",
        "_build6r_v35_strategy_product_fact_violation",
        "_build6r_reconcile_generated_semantic_findings_v35",
    )

    source = "\n".join(
        inspect.getsource(getattr(claims_audit, name))
        for name in names
    )

    for forbidden in (
        "generate_structured",
        "generate_image",
        "edit_image",
        "httpx",
        "requests.",
        "socket.",
        "research_provider",
    ):
        assert forbidden not in source
