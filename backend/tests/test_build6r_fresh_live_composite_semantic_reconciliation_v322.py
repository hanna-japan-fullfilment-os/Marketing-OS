from __future__ import annotations

import asyncio
import inspect
import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

import app.services.claims_audit as claims_audit


LIVE_FIXTURE = json.loads(
    r"""[{"index":1,"claim":"Apresentar o Hydra EX como \u201cm\u00e1scara de ingredientes avan\u00e7ados\u201d","category":"product benefits/effects","source_field":"strategy.objective"},{"index":2,"claim":"LuLuLun Hydra EX Mask 7 Sheets como uma m\u00e1scara de ingredientes avan\u00e7ados","category":"product benefits/effects","source_field":"master_concept.campaign_promise"},{"index":3,"claim":"Tudo o que voc\u00ea v\u00ea aqui sobre o Hydra EX vem diretamente do que foi verificado: composi\u00e7\u00e3o, formato e modo de uso, sem extrapolar para promessas de resultado","category":"other (verification/source of info)","source_field":"master_concept.key_message"},{"index":4,"claim":"Apresentar o Hydra EX como uma \u201cm\u00e1scara de ingredientes avan\u00e7ados\u201d e explicar o que torna essa formula\u00e7\u00e3o interessante usando apenas fatos verificados sobre ingredientes, formato e uso, sem prometer benef\u00edcios ou resultados","category":"other (verification/source of info)","source_field":"master_concept.objective"},{"index":5,"claim":"M\u00e1scara facial em folha em pouch com 7 unidades, categoria skincare","category":"product composition/format","source_field":"master_concept.product_category_context"},{"index":6,"claim":"formato multi-sheet (7 folhas em um \u00fanico pouch com 150 mL de ess\u00eancia)","category":"product composition/format","source_field":"master_concept.product_category_context"},{"index":7,"claim":"caracter\u00edsticas da f\u00f3rmula como ser colorant-free, fragrance-free, mineral-oil-free, alcohol-free","category":"ingredients/production details","source_field":"master_concept.product_category_context"},{"index":8,"claim":"pode ser usada pela manh\u00e3 ou \u00e0 noite em lugar do t\u00f4nico","category":"directions for use","source_field":"master_concept.product_category_context"},{"index":9,"claim":"A campanha precisa educar sobre o Hydra EX mostrando apenas fatos verificados: ingredientes nomeados, formato 7-sheet com 150 mL de ess\u00eancia, descri\u00e7\u00e3o do tecido, caracter\u00edsticas da f\u00f3rmula e modo de uso conforme o fabricante","category":"other (verification/source of info)","source_field":"master_concept.archetype_reasoning"},{"index":10,"claim":"mostrar o conte\u00fado (7 folhas / 150 mL), apontar ingredientes e descrever o uso passo a passo","category":"product composition/format","source_field":"master_concept.archetype_reasoning"},{"index":11,"claim":"as caracter\u00edsticas da f\u00f3rmula (colorant-free, fragrance-free, mineral-oil-free, alcohol-free)","category":"ingredients/production details","source_field":"master_concept.visual_story_system"},{"index":12,"claim":"Demonstra\u00e7\u00e3o visual do formato: mostrar o pouch identificado como 7-sheet variant, com men\u00e7\u00e3o clara ao conte\u00fado de 150 mL de ess\u00eancia","category":"product composition/format","source_field":"master_concept.proof_or_demo_strategy"},{"index":13,"claim":"organizar em um quadro visual os nomes confirmados \u2014 human adipose-derived mesenchymal cell exosomes (com a observa\u00e7\u00e3o de que o fabricante afirma que n\u00e3o cont\u00e9m c\u00e9lulas-tronco), glutathione, arbutin, ascorbyl palmitate (derivado de vitamina C), human recombinant oligopeptide-1 (EGF), ceramide AP, ceramide NP, atelocollagen, hydroxypropyltrimonium hyaluronate","category":"ingredients/production details","source_field":"master_concept.proof_or_demo_strategy"},{"index":14,"claim":"destacar visualmente que \u00e9 colorant-free, fragrance-free, mineral-oil-free e alcohol-free","category":"ingredients/production details","source_field":"master_concept.proof_or_demo_strategy"},{"index":15,"claim":"etapas verificadas (desdobrar, ajustar em torno de olhos e boca, pressionar para tirar o ar, levantar o corte das bochechas, pressionar com as palmas, retirar, dobrar para leve \u201cwiping/light patting\u201d e, depois, aplicar emuls\u00e3o ou creme; men\u00e7\u00e3o de que o fabricante descreve como utiliz\u00e1vel pela manh\u00e3 ou noite no lugar do t\u00f4nico)","category":"directions for use","source_field":"master_concept.proof_or_demo_strategy"},{"index":16,"claim":"Mostrar o pouch Hydra EX 7 Sheets como uma m\u00e1scara facial em folha (Face Mask LuLuLun EX 1FS), com layout que enfatiza o nome e o fato de ser um pouch com v\u00e1rias unidades","category":"product composition/format","source_field":"master_concept.story_beats[1]"},{"index":17,"claim":"se trata do variant de 7 folhas com 150 mL de ess\u00eancia em um \u00fanico pouch","category":"product composition/format","source_field":"master_concept.story_beats[2]"},{"index":18,"claim":"descri\u00e7\u00e3o do fabricante para o tecido (\u201cMelty Feel Sheet\u201d)","category":"ingredients/production details","source_field":"master_concept.story_beats[3]"},{"index":19,"claim":"lista todos os ingredientes confirmados relacionados \u00e0 condi\u00e7\u00e3o da pele: human adipose-derived mesenchymal cell exosomes (com nota de que o fabricante afirma n\u00e3o conter c\u00e9lulas-tronco), glutathione, arbutin, ascorbyl palmitate (derivado de vitamina C), human recombinant oligopeptide-1 (EGF), ceramide AP, ceramide NP, atelocollagen e hydroxypropyltrimonium hyaluronate","category":"ingredients/production details","source_field":"ai_extracted_candidate"},{"index":20,"claim":"Destacar, em um bloco pr\u00f3prio, que a f\u00f3rmula \u00e9 colorant-free, fragrance-free, mineral-oil-free e alcohol-free","category":"ingredients/production details","source_field":"master_concept.story_beats[6]"},{"index":21,"claim":"Visualizar o guia do fabricante em etapas numeradas","category":"directions for use","source_field":"master_concept.story_beats[7]"},{"index":22,"claim":"uso sugerido em lugar do t\u00f4nico, de manh\u00e3 ou \u00e0 noite","category":"directions for use","source_field":"master_concept.must_include[6]"},{"index":23,"claim":"chamar o Hydra EX de uma m\u00e1scara de ingredientes avan\u00e7ados","category":"product benefits/effects","source_field":"master_concept.story_beats[8]"},{"index":24,"claim":"Presen\u00e7a clara do nome do produto: LuLuLun Hydra EX Mask 7 Sheets, com men\u00e7\u00e3o ao manufacturer sales name Face Mask LuLuLun EX 1FS","category":"product identity","source_field":"master_concept.must_include[1]"},{"index":25,"claim":"Destaque para o formato: 7 sheets em um \u00fanico pouch, com 150 mL de essence","category":"product composition/format","source_field":"master_concept.must_include[2]"},{"index":26,"claim":"Men\u00e7\u00e3o textual de que o fabricante descreve a folha como \u201cMelty Feel Sheet\u201d","category":"ingredients/production details","source_field":"master_concept.must_include[3]"},{"index":27,"claim":"Listagem expl\u00edcita dos ingredientes confirmados: human adipose-derived mesenchymal cell exosomes (com nota clara de que o fabricante afirma que n\u00e3o cont\u00e9m c\u00e9lulas-tronco), glutathione, arbutin, ascorbyl palmitate (vitamin C derivative), human recombinant oligopeptide-1 (EGF), ceramide AP, ceramide NP, atelocollagen, hydroxypropyltrimonium hyaluronate","category":"ingredients/production details","source_field":"master_concept.must_include[4]"},{"index":28,"claim":"Bloco de informa\u00e7\u00e3o destacando que o fabricante afirma que a f\u00f3rmula \u00e9 colorant-free, fragrance-free, mineral-oil-free e alcohol-free","category":"ingredients/production details","source_field":"master_concept.must_include[5]"},{"index":29,"claim":"Explicita\u00e7\u00e3o visual ou textual do modo de uso conforme as orienta\u00e7\u00f5es do fabricante, incluindo o uso sugerido em lugar do t\u00f4nico, de manh\u00e3 ou \u00e0 noite","category":"directions for use","source_field":"master_concept.must_include[6]"},{"index":30,"claim":"Nenhuma men\u00e7\u00e3o ou insinua\u00e7\u00e3o de conter c\u00e9lulas-tronco; se o ingrediente de exossomo aparecer, a aus\u00eancia de stem cells deve ser explicitada conforme a informa\u00e7\u00e3o verificada","category":"ingredients/production details","source_field":"master_concept.must_include[10]"},{"index":31,"claim":"LuLuLun Hydra EX: a sheet mask de ingredientes avan\u00e7ados","category":"product benefits/effects","source_field":"ai_extracted_candidate"},{"index":32,"claim":"\u00c9 a LuLuLun Hydra EX facial sheet mask, na vers\u00e3o pouch com 7 m\u00e1scaras e 150 mL de ess\u00eancia","category":"product composition/format","source_field":"ai_extracted_candidate"},{"index":33,"claim":"Exossomos derivados de c\u00e9lulas mesenquimais de gordura humana como ingrediente de condicionamento da pele \u2013 e o pr\u00f3prio fabricante afirma que n\u00e3o cont\u00e9m c\u00e9lulas-tronco","category":"ingredients/production details","source_field":"ai_extracted_candidate"},{"index":34,"claim":"Desdobrar a m\u00e1scara, encaixar ao redor dos olhos e boca, apertar para tirar o ar, puxar os cortes da bochecha na linha do rosto e ent\u00e3o pressionar a m\u00e1scara inteira com as palmas","category":"directions for use","source_field":"ai_extracted_candidate"},{"index":35,"claim":"Depois de remover, o fabricante sugere dobrar a m\u00e1scara para usar em movimentos de limpeza/batidinhas leves e finalizar com emuls\u00e3o ou creme","category":"directions for use","source_field":"ai_extracted_candidate"},{"index":36,"claim":"Hydra EX como uma m\u00e1scara de ingredientes avan\u00e7ados","category":"product benefits/effects","source_field":"ai_extracted_candidate"},{"index":37,"claim":"Hydra EX \u00e9 um bom exemplo de sheet mask para explorar essa leitura mais atenta","category":"product positioning/other benefits","source_field":"ai_extracted_candidate"},{"index":38,"claim":"LuLuLun Hydra EX Mask 7 Sheets s\u00f3 com as informa\u00e7\u00f5es verificadas, sem inventar benef\u00edcio nem promessa","category":"other (verification/source of info)","source_field":"ai_extracted_candidate"},{"index":39,"claim":"\u00c9 a LuLuLun Hydra EX facial sheet mask na vers\u00e3o pouch com 7 m\u00e1scaras","category":"product composition/format","source_field":"ai_extracted_candidate"},{"index":40,"claim":"V\u00eam 7 m\u00e1scaras em um \u00fanico pacote, com 150 mL de ess\u00eancia","category":"product composition/format","source_field":"ai_extracted_candidate"},{"index":41,"claim":"O nome de venda informado pelo fabricante \u00e9 Face Mask LuLuLun EX 1FS","category":"product identity","source_field":"ai_extracted_candidate"},{"index":42,"claim":"Na f\u00f3rmula, segundo a lista do fabricante, constam: Exossomos derivados de c\u00e9lulas mesenquimais de gordura humana como ingrediente de condicionamento da pele \u2013 com o pr\u00f3prio fabricante deixando claro que n\u00e3o cont\u00e9m c\u00e9lulas-tronco","category":"ingredients/production details","source_field":"ai_extracted_candidate"},{"index":43,"claim":"E algumas caracter\u00edsticas da composi\u00e7\u00e3o, tamb\u00e9m declaradas pelo fabricante: Sem corantes; Sem fragr\u00e2ncia; Sem \u00f3leo mineral; Sem \u00e1lcool","category":"ingredients/production details","source_field":"ai_extracted_candidate"},{"index":44,"claim":"Modo de uso, conforme orienta\u00e7\u00e3o do fabricante","category":"directions for use","source_field":"copy.pt-BR.caption"},{"index":45,"claim":"j\u00e1 d\u00e1 para enxergar a Hydra EX como uma m\u00e1scara de ingredientes avan\u00e7ados","category":"product benefits/effects","source_field":"ai_extracted_candidate"},{"index":46,"claim":"O fabricante descreve o uso pela manh\u00e3 ou \u00e0 noite, em lugar do toner","category":"directions for use","source_field":"creative.creative_brief.template_suggestion"},{"index":47,"claim":"Este conte\u00fado apresenta apenas informa\u00e7\u00f5es fornecidas pelo fabricante para o LuLuLun Hydra EX Mask 7 Sheets, sem extrapolar para promessas de resultado ou benef\u00edcios n\u00e3o confirmados","category":"other (verification/source of info)","source_field":"creative.creative_brief.template_suggestion"}]"""
)

LIVE_BY_INDEX = {
    int(item["index"]): item
    for item in LIVE_FIXTURE
}

EXPECTED_SUPPORTED = {
    6, 7, 8, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22,
    24, 25, 26, 27, 28, 29, 30, 32, 33, 34, 35, 39, 40, 41, 42, 43,
    44, 46,
}

EXPECTED_BLOCKED = set(range(1, 48)) - EXPECTED_SUPPORTED


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
        prohibited_claims=[
            (
                "Do not claim that the product contains stem cells; the "
                "manufacturer explicitly states that the listed exosome "
                "ingredient does not contain stem cells"
            ),
        ],
        missing_information=[
            "verified_benefits",
            "verified_price",
            "verified_availability",
            "verified_country_of_origin",
        ],
        provenance="manufacturer_official+owner_confirmed",
    )


def _entry(index):
    return LIVE_BY_INDEX[index]


def _finding(
    index,
    *,
    text=None,
    category=None,
    source=None,
):
    item = _entry(index)

    return claims_audit.ClaimFinding(
        claim_text=(
            item["claim"]
            if text is None
            else text
        ),
        claim_category=(
            item["category"]
            if category is None
            else category
        ),
        source_field=(
            item["source_field"]
            if source is None
            else source
        ),
        evidence_status="UNSUPPORTED",
        allowed_source="",
        reason="authoritative V3.21 live failure fixture",
    )


def _fields_for_fixture():
    fields = {}

    for item in LIVE_FIXTURE:
        source = item["source_field"]

        if source == "ai_extracted_candidate":
            continue

        fields[source] = (
            fields.get(source, "")
            + (
                " | "
                if source in fields
                else ""
            )
            + item["claim"]
        )

    return fields


def _reconcile(
    findings,
    *,
    verified=None,
    fields=None,
):
    return (
        claims_audit
        ._build6r_v322_reconcile_fresh_live_composite_candidates(
            claims_audit.ClaimAuditResult(
                findings=findings
            ),
            (
                _verified()
                if verified is None
                else verified
            ),
            (
                _fields_for_fixture()
                if fields is None
                else fields
            ),
        )
    )


def _status(
    finding,
    *,
    verified=None,
    fields=None,
):
    return _reconcile(
        [finding],
        verified=verified,
        fields=fields,
    ).findings[0]


@pytest.mark.parametrize(
    "index",
    list(range(1, 48)),
)
def test_v322_authoritative_47_failure_fixture_exact_status(index):
    finding = _status(
        _finding(index)
    )

    expected = (
        "SUPPORTED"
        if index in EXPECTED_SUPPORTED
        else "UNSUPPORTED"
    )

    assert finding.evidence_status == expected

    if expected == "SUPPORTED":
        assert finding.allowed_source == "verified_product_facts"


def test_v322_exact_authoritative_partition_is_34_supported_13_blocked():
    result = _reconcile(
        [
            _finding(index)
            for index in range(1, 48)
        ]
    )

    supported = {
        index
        for index, finding
        in zip(
            range(1, 48),
            result.findings,
        )
        if finding.evidence_status
        == "SUPPORTED"
    }

    assert supported == EXPECTED_SUPPORTED
    assert (
        set(range(1, 48))
        - supported
    ) == EXPECTED_BLOCKED


def test_v322_7_sheet_150ml_composite_reconciles():
    assert (
        _status(
            _finding(6)
        ).evidence_status
        == "SUPPORTED"
    )


def test_v322_manufacturer_sales_name_paraphrase_reconciles():
    assert (
        _status(
            _finding(41)
        ).evidence_status
        == "SUPPORTED"
    )


def test_v322_melty_feel_sheet_paraphrase_reconciles():
    assert (
        _status(
            _finding(18)
        ).evidence_status
        == "SUPPORTED"
    )


def test_v322_free_from_composition_reconciles():
    assert (
        _status(
            _finding(43)
        ).evidence_status
        == "SUPPORTED"
    )


def test_v322_canonical_multi_ingredient_list_reconciles():
    assert (
        _status(
            _finding(27)
        ).evidence_status
        == "SUPPORTED"
    )


def test_v322_manufacturer_direction_steps_reconcile():
    assert (
        _status(
            _finding(34)
        ).evidence_status
        == "SUPPORTED"
    )

    assert (
        _status(
            _finding(35)
        ).evidence_status
        == "SUPPORTED"
    )


def test_v322_morning_night_in_place_of_toner_reconciles():
    assert (
        _status(
            _finding(46)
        ).evidence_status
        == "SUPPORTED"
    )


def test_v322_mixed_supported_unsupported_composite_remains_blocked():
    finding = _finding(
        6,
        text=(
            "formato multi-sheet com 7 folhas e 150 mL de essencia, "
            "categoria premium"
        ),
    )

    assert (
        _status(
            finding
        ).evidence_status
        == "UNSUPPORTED"
    )


def test_v322_categoria_skincare_mixed_composite_remains_blocked():
    assert (
        _status(
            _finding(5)
        ).evidence_status
        == "UNSUPPORTED"
    )


def test_v322_advanced_ingredients_positioning_remains_blocked():
    for index in (
        1,
        2,
        23,
        31,
        36,
        45,
    ):
        assert (
            _status(
                _finding(index)
            ).evidence_status
            == "UNSUPPORTED"
        )


def test_v322_meta_verification_language_remains_blocked():
    for index in (
        3,
        9,
        38,
        47,
    ):
        assert (
            _status(
                _finding(index)
            ).evidence_status
            == "UNSUPPORTED"
        )


def test_v322_interpretive_positioning_remains_blocked():
    assert (
        _status(
            _finding(37)
        ).evidence_status
        == "UNSUPPORTED"
    )


def test_v322_positive_exosome_lineage_with_same_field_caveat_reconciles():
    finding = _finding(13)

    assert (
        _status(
            finding
        ).evidence_status
        == "SUPPORTED"
    )


def test_v322_portuguese_nao_conter_same_field_variant_reconciles():
    finding = _finding(19)

    assert (
        _status(
            finding
        ).evidence_status
        == "SUPPORTED"
    )


def test_v322_positive_exosome_lineage_without_same_field_caveat_remains_blocked():
    finding = _finding(
        33,
        text=(
            "Exossomos derivados de celulas mesenquimais de gordura humana "
            "como ingrediente de condicionamento da pele"
        ),
    )

    assert (
        _status(
            finding
        ).evidence_status
        == "UNSUPPORTED"
    )


def test_v322_cross_field_stem_caveat_inheritance_remains_blocked():
    finding = _finding(
        13,
        text=(
            "human adipose-derived mesenchymal cell exosomes, glutathione, "
            "arbutin, ascorbyl palmitate, human recombinant oligopeptide-1, "
            "ceramide AP, ceramide NP, atelocollagen, "
            "hydroxypropyltrimonium hyaluronate"
        ),
    )

    fields = {
        finding.source_field:
            finding.claim_text,
        "copy.pt-BR.caption":
            "O fabricante afirma que nao contem celulas-tronco",
    }

    assert (
        _status(
            finding,
            fields=fields,
        ).evidence_status
        == "UNSUPPORTED"
    )


def test_v322_canonical_no_stem_backing_remains_required():
    verified = deepcopy(
        _verified()
    )

    verified.verified_claims = [
        value.replace(
            "; manufacturer states stem cells are not contained",
            "",
        )
        for value
        in verified.verified_claims
    ]

    verified.verified_ingredients = [
        value.replace(
            "; manufacturer states stem cells are not contained",
            "",
        )
        for value
        in verified.verified_ingredients
    ]

    assert (
        _status(
            _finding(33),
            verified=verified,
        ).evidence_status
        == "UNSUPPORTED"
    )


def test_v322_stem_safety_runs_before_permissive_ingredient_support():
    finding = _finding(
        27,
        text=(
            "human adipose-derived mesenchymal cell exosomes, glutathione, "
            "arbutin, ascorbyl palmitate, human recombinant oligopeptide-1, "
            "ceramide AP, ceramide NP, atelocollagen, "
            "hydroxypropyltrimonium hyaluronate"
        ),
    )

    assert (
        _status(
            finding,
            fields={
                finding.source_field:
                    finding.claim_text
            },
        ).evidence_status
        == "UNSUPPORTED"
    )


def test_v322_research_trend_source_remains_non_evidence():
    finding = _finding(
        40,
        source="research.trends[0]",
    )

    assert (
        _status(
            finding
        ).evidence_status
        == "UNSUPPORTED"
    )


def test_v322_price_claim_remains_blocked():
    finding = _finding(
        40,
        text="Preco de 1000 JPY",
        category="price_or_availability",
    )

    assert (
        _status(
            finding
        ).evidence_status
        == "UNSUPPORTED"
    )


def test_v322_availability_scarcity_ranking_popularity_bestseller_remain_blocked():
    samples = (
        "Disponivel em estoque",
        "Ultimas unidades",
        "Numero 1 no ranking",
        "Produto muito popular",
        "Bestseller da categoria",
    )

    for text in samples:
        finding = _finding(
            40,
            text=text,
            category="price_or_availability",
        )

        assert (
            _status(
                finding
            ).evidence_status
            == "UNSUPPORTED"
        )


def test_v322_benefit_effect_efficacy_result_superiority_remain_blocked():
    samples = (
        "Melty Feel Sheet hidrata a pele",
        "Melty Feel Sheet melhora a eficacia",
        "Melty Feel Sheet entrega resultado visivel",
        "Melty Feel Sheet tem performance superior",
        "Melty Feel Sheet firma a pele",
    )

    for text in samples:
        finding = _finding(
            18,
            text=text,
            category="product feature/benefit",
        )

        assert (
            _status(
                finding
            ).evidence_status
            == "UNSUPPORTED"
        )


def test_v322_unknown_source_remains_blocked():
    finding = _finding(
        40,
        source="unknown.generated.field",
    )

    assert (
        _status(
            finding
        ).evidence_status
        == "UNSUPPORTED"
    )


def test_v322_empty_verified_category_is_not_used_to_infer_generated_category():
    verified = deepcopy(
        _verified()
    )
    verified.category = None

    assert (
        _status(
            _finding(5),
            verified=verified,
        ).evidence_status
        == "UNSUPPORTED"
    )


def test_v322_local_source_admission_is_narrow():
    allowed = (
        "strategy.objective",
        "master_concept.product_category_context",
        "master_concept.archetype_reasoning",
        "master_concept.visual_story_system",
        "master_concept.proof_or_demo_strategy",
        "master_concept.story_beats[8]",
        "master_concept.must_include[10]",
        "master_concept.campaign_promise",
        "master_concept.key_message",
        "master_concept.objective",
        "copy.pt-BR.caption",
        "creative.creative_brief.template_suggestion",
        "ai_extracted_candidate",
    )

    assert all(
        claims_audit._build6r_v322_source_field_allowed(
            source
        )
        is True
        for source in allowed
    )

    assert (
        claims_audit._build6r_v322_source_field_allowed(
            "unknown.generated.field"
        )
        is False
    )

    assert (
        claims_audit._build6r_v322_source_field_allowed(
            "research.trends[0]"
        )
        is False
    )


def test_v322_wrapper_executes_sealed_v321_chain_exactly_once(monkeypatch):
    original = claims_audit.ClaimAuditResult(
        findings=[]
    )
    calls = {
        "count": 0,
    }

    async def fake_previous(
        *args,
        **kwargs,
    ):
        calls["count"] += 1
        return original

    monkeypatch.setattr(
        claims_audit,
        "_build6r_augment_before_v322",
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


def test_v322_wrapper_preserves_v317_through_v322_contract_markers():
    source = inspect.getsource(
        claims_audit.augment_with_ai_extraction
    )

    markers = (
        "_build6r_augment_before_v317",
        "_build6r_v317_reconcile_runtime_alias_candidates",
        "_build6r_augment_before_v318",
        "_build6r_v318_reconcile_previsual_candidates",
        "_build6r_augment_before_v319",
        "_build6r_v319_reconcile_live_phrase_candidates",
        "_build6r_augment_before_v320",
        "_build6r_v320_reconcile_live_semantic_candidates",
        "_build6r_augment_before_v321",
        "_build6r_v321_reconcile_remaining_live_semantic_candidates",
        "_build6r_augment_before_v322",
        "_build6r_v322_reconcile_fresh_live_composite_candidates",
    )

    assert all(
        marker in source
        for marker in markers
    )


def test_v322_production_layer_is_product_agnostic_zero_cost_and_offline():
    source = "\n".join(
        (
            inspect.getsource(
                claims_audit._build6r_v322_source_field_allowed
            ),
            inspect.getsource(
                claims_audit._build6r_v322_verified_values
            ),
            inspect.getsource(
                claims_audit._build6r_v322_canonical_text
            ),
            inspect.getsource(
                claims_audit._build6r_v322_has_meta_verification_language
            ),
            inspect.getsource(
                claims_audit._build6r_v322_has_benefit_effect_language
            ),
            inspect.getsource(
                claims_audit._build6r_v322_has_unsupported_positioning
            ),
            inspect.getsource(
                claims_audit._build6r_v322_same_source_stem_cell_qualified
            ),
            inspect.getsource(
                claims_audit._build6r_v322_candidate_supported
            ),
            inspect.getsource(
                claims_audit._build6r_v322_reconcile_fresh_live_composite_candidates
            ),
            inspect.getsource(
                claims_audit.augment_with_ai_extraction
            ),
        )
    ).lower()

    forbidden = (
        "lululun",
        "hydra",
        "hanna-japan",
        "campaign_id",
        "product_id",
        "4507de",
        "7f767",
        "4c9d",
        "openai",
        "requests.",
        "httpx",
        "urllib",
        "socket",
        "sqlite",
        "sessionlocal",
        "rapidfuzz",
        "difflib",
        "sequencematcher",
        "embedding",
        "cosine",
        "generate_structured(",
        "generate_image(",
        "edit_image(",
    )

    assert all(
        token not in source
        for token in forbidden
    )


def test_v322_does_not_rewrite_claim_text():
    original = _finding(6)

    returned = _status(
        original
    )

    assert (
        returned.claim_text
        == original.claim_text
    )
    assert (
        returned.claim_category
        == original.claim_category
    )
    assert (
        returned.source_field
        == original.source_field
    )


def test_v322_v315_vague_specific_set_reference_remains_blocked():
    finding = claims_audit.ClaimFinding(
        claim_text=(
            "LuLuLun Hydra EX exatamente como ela e descrita pelo fabricante: "
            "uma sheet mask facial em pouch com 7 folhas e 150 mL de essencia, "
            "com esse conjunto especifico de ingredientes e caracteristicas de "
            "formula"
        ),
        claim_category="ingredients/contents",
        source_field="ai_extracted_candidate",
        evidence_status="UNSUPPORTED",
        allowed_source="",
        reason="legacy V3.15 compatibility fixture",
    )

    returned = _status(
        finding,
        fields={},
    )

    assert (
        returned.evidence_status
        == "UNSUPPORTED"
    )


def test_v322_v32_numbered_routine_sequence_remains_blocked():
    finding = claims_audit.ClaimFinding(
        claim_text=(
            "3 passos: 1. Limpeza; 2. LuLuLun Hydra EX "
            "(no lugar do tonico); 3. Emulsao ou creme"
        ),
        claim_category="directions for use",
        source_field="master_concept.story_beats[4]",
        evidence_status="UNSUPPORTED",
        allowed_source="",
        reason="legacy V3.2 compatibility fixture",
    )

    fields = {
        "master_concept.story_beats[4]":
            finding.claim_text,
    }

    returned = _status(
        finding,
        fields=fields,
    )

    assert (
        returned.evidence_status
        == "UNSUPPORTED"
    )
