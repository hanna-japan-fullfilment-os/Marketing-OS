from __future__ import annotations

import asyncio
import inspect
from types import SimpleNamespace

import pytest

import app.services.claims_audit as claims_audit


LIVE_CAMPAIGN_ID = "466987c226b64949a95a4a9378b9b073"

LIVE_FINDINGS = [
    (
        1,
        'LuLuLun Hydra EX Mask 7 Sheets \xe9 uma m\xe1scara facial em pouch com 7 unidades e 150 mL de ess\xeancia',
        'product structure/format',
        'ai_extracted_candidate',
    ),
    (
        2,
        'combina\xe7\xe3o espec\xedfica de ingredientes \u2014 como exossomos derivados de c\xe9lulas-tronco de tecido adiposo humano (sem conter c\xe9lulas-tronco, segundo o fabricante), glutathione, arbutin, derivado de vitamina C, ceramidas, atelocol\xe1geno e \xe1cido hialur\xf4nico modificado',
        'ingredients/composition',
        'ai_extracted_candidate',
    ),
    (
        3,
        'sheet descrito pelo fabricante como Melty Feel Sheet',
        'product feature/material',
        'ai_extracted_candidate',
    ),
    (
        4,
        'livre de corantes, fragr\xe2ncia, \xf3leo mineral e \xe1lcool, segundo o fabricante',
        'ingredients free-from claim',
        'ai_extracted_candidate',
    ),
    (
        5,
        '\xe9 apresentada como uma m\xe1scara facial em pouch com 7 unidades e 150 mL de ess\xeancia',
        'product structure/format',
        'master_concept.key_message',
    ),
    (
        6,
        'incluindo exossomos derivados de c\xe9lulas-tronco de tecido adiposo humano (sem conter c\xe9lulas-tronco, segundo o fabricante), glutathione, arbutin, derivado de vitamina C, ceramidas, atelocol\xe1geno, \xe1cido hialur\xf4nico modificado e human recombinant oligopeptide-1',
        'ingredients/composition',
        'master_concept.key_message',
    ),
    (
        7,
        'colorant-free, fragrance-free, mineral-oil-free e alcohol-free, segundo o fabricante',
        'ingredients free-from claim',
        'ai_extracted_candidate',
    ),
    (
        8,
        '7-sheet pouch, 150 mL de ess\xeancia',
        'product structure/format',
        'ai_extracted_candidate',
    ),
    (
        9,
        'human adipose-derived mesenchymal cell exosomes (citando que o fabricante afirma n\xe3o conter c\xe9lulas-tronco)',
        'ingredients/composition',
        'master_concept.proof_or_demo_strategy',
    ),
    (
        10,
        'glutathione, arbutin, ascorbyl palmitate, human recombinant oligopeptide-1, Ceramide AP, Ceramide NP, atelocollagen e hydroxypropyltrimonium hyaluronate',
        'ingredients/composition',
        'ai_extracted_candidate',
    ),
    (
        11,
        'colorant-free, fragrance-free, mineral-oil-free, alcohol-free',
        'ingredients free-from claim',
        'ai_extracted_candidate',
    ),
    (
        12,
        'pouch com 7 sheets e 150 mL de ess\xeancia',
        'product structure/format',
        'ai_extracted_candidate',
    ),
    (
        13,
        'human adipose-derived mesenchymal cell exosomes (mencionando que o fabricante afirma que n\xe3o cont\xeam c\xe9lulas-tronco)',
        'ingredients/composition',
        'master_concept.story_beats[3]',
    ),
    (
        14,
        'colorant-free, fragrance-free, mineral-oil-free e alcohol-free',
        'ingredients free-from claim',
        'ai_extracted_candidate',
    ),
    (
        15,
        'desdobrar, ajustar em torno dos olhos e boca, pressionar para tirar o ar, levantar cortes das bochechas e pressionar, depois remover, usar para wiping/light patting e seguir com emulsion ou cream, podendo ser usado de manh\xe3 ou \xe0 noite em vez de t\xf4nico',
        'directions for use',
        'master_concept.story_beats[5]',
    ),
    (
        16,
        '\xc9 um pouch com 7 m\xe1scaras faciais e 150 mL de ess\xeancia',
        'product structure/format',
        'ai_extracted_candidate',
    ),
    (
        17,
        'exossomos derivados de c\xe9lulas-tronco de tecido adiposo humano como ingrediente de condicionamento da pele \u2014 e deixa claro que n\xe3o cont\xeam c\xe9lulas-tronco \u2014 al\xe9m de glutathione, arbutin, o derivado de vitamina C ascorbyl palmitate, human recombinant oligopeptide-1, ceramide AP, ceramide NP, atelocol\xe1geno e hydroxypropyltrimonium hyaluronate',
        'ingredients/composition',
        'copy.pt-BR.supporting_copy',
    ),
    (
        18,
        'A folha \xe9 descrita pelo fabricante como \u201cMelty Feel Sheet\u201d',
        'product feature/material',
        'copy.pt-BR.supporting_copy',
    ),
    (
        19,
        'Segundo o fabricante, a f\xf3rmula \xe9 livre de corantes, fragr\xe2ncia, \xf3leo mineral e \xe1lcool',
        'ingredients free-from claim',
        'copy.pt-BR.supporting_copy',
    ),
    (
        20,
        'Na parte de uso, o fabricante orienta: desdobrar a m\xe1scara, ajustar ao redor dos olhos e da boca, tirar o ar preso, levantar os recortes das bochechas ao longo da linha do rosto e, depois, pressionar tudo com as palmas',
        'directions for use',
        'copy.pt-BR.supporting_copy',
    ),
    (
        21,
        'Ap\xf3s remover, sugerem dobrar a m\xe1scara para passar no rosto com leves batidinhas e seguir com emuls\xe3o ou creme',
        'directions for use',
        'copy.pt-BR.supporting_copy',
    ),
    (
        22,
        'A marca tamb\xe9m descreve a Hydra EX como uma op\xe7\xe3o que pode ser usada de manh\xe3 ou \xe0 noite no lugar do t\xf4nico',
        'directions for use/usage context',
        'copy.pt-BR.supporting_copy',
    ),
    (
        23,
        'Formato: um pouch com 7 m\xe1scaras faciais e 150 mL de ess\xeancia',
        'product structure/format',
        'copy.pt-BR.caption',
    ),
    (
        24,
        'Ingredientes que o fabricante destaca na lista: exossomos derivados de c\xe9lulas-tronco de tecido adiposo humano como ingrediente de condicionamento da pele (com a observa\xe7\xe3o de que n\xe3o cont\xeam c\xe9lulas-tronco), glutathione, arbutin, o derivado de vitamina C ascorbyl palmitate, human recombinant oligopeptide-1, ceramide AP, ceramide NP, atelocol\xe1geno e hydroxypropyltrimonium hyaluronate',
        'ingredients/composition',
        'copy.pt-BR.caption',
    ),
    (
        25,
        'Tecido: o sheet \xe9 descrito como \u201cMelty Feel Sheet\u201d',
        'product feature/material',
        'copy.pt-BR.caption',
    ),
    (
        26,
        'Formula\xe7\xe3o, segundo o fabricante: colorant-free, fragrance-free, mineral-oil-free, alcohol-free (ou seja, livre de corantes, fragr\xe2ncia, \xf3leo mineral e \xe1lcool)',
        'ingredients free-from claim',
        'copy.pt-BR.caption',
    ),
    (
        27,
        'Modo de uso descrito pelo fabricante: desdobrar a m\xe1scara, ajustar em volta de olhos e boca, tirar o ar preso, levantar os recortes da bochecha ao longo da linha do rosto e pressionar com as palmas',
        'directions for use',
        'copy.pt-BR.caption',
    ),
    (
        28,
        'Depois de tirar, usar a pr\xf3pria m\xe1scara dobrada para passar no rosto com batidinhas leves e finalizar com emuls\xe3o ou creme',
        'directions for use',
        'copy.pt-BR.caption',
    ),
    (
        29,
        'Eles tamb\xe9m descrevem que pode ser usada de manh\xe3 ou \xe0 noite no lugar do t\xf4nico',
        'directions for use/usage context',
        'copy.pt-BR.caption',
    ),
    (
        30,
        'M\xe1scara facial em pouch com 7 sheets',
        'product structure/format',
        'creative.creative_brief.template_suggestion',
    ),
    (
        31,
        'Conte\xfado de 150 mL de ess\xeancia (informa\xe7\xe3o do fabricante)',
        'product structure/format',
        'creative.creative_brief.template_suggestion',
    ),
    (
        32,
        'Exossomos derivados de c\xe9lulas-tronco de tecido adiposo humano como ingrediente de condicionamento da pele, listado pelo fabricante',
        'ingredients/composition',
        'creative.creative_brief.template_suggestion',
    ),
    (
        33,
        'Segundo o fabricante, esse ingrediente n\xe3o cont\xe9m c\xe9lulas-tronco',
        'ingredient property/qualification',
        'creative.creative_brief.template_suggestion',
    ),
    (
        34,
        'Ascorbyl palmitate (derivado de vitamina C)',
        'ingredients/composition',
        'ai_extracted_candidate',
    ),
    (
        35,
        'Sheet descrito pelo fabricante como \u201cMelty Feel Sheet\u201d',
        'product feature/material',
        'creative.creative_brief.template_suggestion',
    ),
    (
        36,
        'Segundo o fabricante, a f\xf3rmula \xe9 colorant-free, fragrance-free, mineral-oil-free e alcohol-free',
        'ingredients free-from claim',
        'creative.creative_brief.template_suggestion',
    ),
    (
        37,
        'O fabricante descreve a folha como \u201cMelty Feel Sheet\u201d',
        'product feature/material',
        'creative.languages.pt-BR.carousel_plan.slides[4].body',
    ),
    (
        38,
        'Diz tamb\xe9m que a f\xf3rmula \xe9 livre de corantes, fragr\xe2ncia, \xf3leo mineral e \xe1lcool',
        'ingredients free-from claim',
        'creative.languages.pt-BR.carousel_plan.slides[4].body',
    ),
    (
        39,
        'o r\xf3tulo orienta: desdobrar a m\xe1scara, ajustar ao redor dos olhos e da boca, tirar o ar preso, levantar os recortes das bochechas ao longo da linha do rosto e pressionar com as palmas',
        'directions for use',
        'creative.languages.pt-BR.carousel_plan.slides[4].body',
    ),
    (
        40,
        'Depois de remover, sugerem dobrar a m\xe1scara pra passar no rosto com leves batidinhas e seguir com emuls\xe3o ou creme',
        'directions for use',
        'creative.languages.pt-BR.carousel_plan.slides[4].body',
    ),
    (
        41,
        'A marca ainda descreve a Hydra EX como uma op\xe7\xe3o que pode ser usada de manh\xe3 ou \xe0 noite no lugar do t\xf4nico',
        'directions for use/usage context',
        'creative.languages.pt-BR.carousel_plan.slides[4].body',
    ),
    (
        42,
        'LuLuLun Hydra EX Mask 7 Sheets',
        'product identity/name',
        'ai_extracted_candidate',
    ),
]


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
            (
                "Manufacturer describes the sheet as a Melty Feel Sheet"
            ),
        ],
    )


def _finding(text, category, source_field):
    return claims_audit.ClaimFinding(
        claim_text=text,
        claim_category=category,
        source_field=source_field,
        evidence_status="UNSUPPORTED",
        allowed_source="",
        reason="exact V3.4 live replay target",
    )


def _reconcile(findings):
    result = claims_audit.ClaimAuditResult(
        findings=findings
    )
    return (
        claims_audit
        ._build6r_reconcile_generated_semantic_findings_v34(
            result,
            _verified(),
        )
    )


def test_exact_live_campaign_42_findings_are_pinned():
    assert LIVE_CAMPAIGN_ID == "466987c226b64949a95a4a9378b9b073"
    assert len(LIVE_FINDINGS) == 42
    assert [row[0] for row in LIVE_FINDINGS] == list(range(1, 43))


def test_exact_live_campaign_42_findings_reconcile_as_one_result():
    findings = [
        _finding(text, category, source_field)
        for _index, text, category, source_field
        in LIVE_FINDINGS
    ]

    result = _reconcile(findings)

    failures = [
        (
            index,
            finding.claim_category,
            finding.source_field,
            finding.claim_text,
        )
        for (
            index,
            _text,
            _category,
            _source_field,
        ), finding
        in zip(LIVE_FINDINGS, result.findings)
        if finding.evidence_status != "SUPPORTED"
    ]

    assert failures == []

    assert all(
        finding.allowed_source == "verified_product_facts"
        for finding in result.findings
    )


@pytest.mark.parametrize(
    "category,expected",
    [
        ("product structure/format", "format"),
        ("ingredients/composition", "ingredients"),
        ("product feature/material", "material"),
        ("ingredients free-from claim", "free_from"),
        ("directions for use", "usage"),
        ("directions for use/usage context", "usage"),
        ("ingredient property/qualification", "ingredient_property"),
        ("product identity/name", "identity"),
    ],
)
def test_exact_live_category_vocabulary(category, expected):
    assert (
        claims_audit._build6r_v34_live_category_family(category)
        == expected
    )


def test_anaphoric_stem_cell_absence_requires_same_source_exosome_context():
    property_only = _finding(
        "Segundo o fabricante, esse ingrediente não contém células-tronco",
        "ingredient property/qualification",
        "creative.creative_brief.template_suggestion",
    )

    isolated = _reconcile([property_only])
    assert isolated.findings[0].evidence_status == "UNSUPPORTED"

    exosome = _finding(
        (
            "Exossomos derivados de células-tronco de tecido adiposo humano "
            "como ingrediente de condicionamento da pele, listado pelo fabricante"
        ),
        "ingredients/composition",
        "creative.creative_brief.template_suggestion",
    )

    linked = _reconcile([exosome, property_only])

    assert linked.findings[0].evidence_status == "SUPPORTED"
    assert linked.findings[1].evidence_status == "SUPPORTED"


@pytest.mark.parametrize(
    "text,category,source_field",
    [
        (
            "No Japão, sheet mask não é só mimo de spa: é um passo de rotina",
            "product structure/format",
            "ai_extracted_candidate",
        ),
        (
            "Em vez de vários sachês soltos, ela vem em um pouch com "
            "7 máscaras faciais e 150 mL de essência",
            "product structure/format",
            "copy.pt-BR.supporting_copy",
        ),
        (
            "um único pacote com 7 sheet masks imersas em 150 mL de essência",
            "product structure/format",
            "master_concept.campaign_promise",
        ),
        (
            "7 folhas no mesmo pouch para vários dias de uso contínuo",
            "directions for use/usage context",
            "copy.pt-BR.caption",
        ),
        (
            "Fabricante descreve o sheet como Melty Feel Sheet, "
            "com toque confortável",
            "product feature/material",
            "creative.creative_brief.template_suggestion",
        ),
        (
            "Contém células-tronco de tecido adiposo humano",
            "ingredients/composition",
            "ai_extracted_candidate",
        ),
        (
            "Contém glutathione e retinol",
            "ingredients/composition",
            "ai_extracted_candidate",
        ),
        (
            "A fórmula é colorant-free e contém fragrância",
            "ingredients free-from claim",
            "copy.pt-BR.caption",
        ),
        (
            "7 máscaras e 150 mL, disponíveis agora em estoque",
            "product structure/format",
            "copy.pt-BR.caption",
        ),
        (
            "LuLuLun Hydra EX Mask 7 Sheets",
            "product identity/name",
            "strategy.research_basis[0]",
        ),
        (
            "Melty Feel Sheet",
            "product feature/material",
            "creative.creative_brief.design_concept",
        ),
    ],
)
def test_unsupported_mixed_or_unapproved_sources_remain_fail_closed(
    text,
    category,
    source_field,
):
    result = _reconcile([
        _finding(
            text,
            category,
            source_field,
        )
    ])

    assert result.findings[0].evidence_status == "UNSUPPORTED"


def test_v34_source_allowlist_remains_narrow():
    assert claims_audit._build6r_v34_source_field_allowed(
        "ai_extracted_candidate"
    )
    assert claims_audit._build6r_v34_source_field_allowed(
        "master_concept.key_message"
    )
    assert claims_audit._build6r_v34_source_field_allowed(
        "copy.pt-BR.caption"
    )
    assert claims_audit._build6r_v34_source_field_allowed(
        "creative.creative_brief.template_suggestion"
    )
    assert claims_audit._build6r_v34_source_field_allowed(
        "creative.languages.pt-BR.carousel_plan.slides[4].body"
    )

    assert not claims_audit._build6r_v34_source_field_allowed(
        "strategy.research_basis[0]"
    )
    assert not claims_audit._build6r_v34_source_field_allowed(
        "creative.creative_brief.design_concept"
    )


def test_v34_wrapper_preserves_sealed_chain_contracts():
    source = inspect.getsource(
        claims_audit.augment_with_ai_extraction
    )

    for marker in (
        "_build6r_augment_before_v32",
        "_build6r_reconcile_generated_semantic_findings_v32",
        "_build6r_augment_before_v33",
        "_build6r_reconcile_generated_semantic_findings_v33",
        "_build6r_augment_before_v34",
        "_build6r_reconcile_generated_semantic_findings_v34",
    ):
        assert marker in source


def test_final_wrapper_applies_v34(monkeypatch):
    async def fake_previous(*args, **kwargs):
        return claims_audit.ClaimAuditResult(
            findings=[
                _finding(
                    "Formato: um pouch com 7 máscaras faciais e 150 mL de essência",
                    "product structure/format",
                    "copy.pt-BR.caption",
                )
            ]
        )

    monkeypatch.setattr(
        claims_audit,
        "_build6r_augment_before_v34",
        fake_previous,
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

    assert result.findings[0].evidence_status == "SUPPORTED"


def test_v34_has_no_provider_network_or_research_evidence_path():
    names = (
        "_build6r_v34_live_category_family",
        "_build6r_v34_source_field_allowed",
        "_build6r_v34_global_residue_blocked",
        "_build6r_v34_format_supported",
        "_build6r_v34_material_supported",
        "_build6r_v34_free_from_supported",
        "_build6r_v34_ingredient_supported",
        "_build6r_v34_usage_supported",
        "_build6r_v34_identity_supported",
        "_build6r_v34_contextual_exosome_sources",
        "_build6r_v34_generated_finding_supported",
        "_build6r_reconcile_generated_semantic_findings_v34",
    )

    combined = "\n".join(
        inspect.getsource(getattr(claims_audit, name))
        for name in names
    )

    forbidden = (
        "generate_structured",
        "generate_image",
        "edit_image",
        "responses.",
        "images.",
        "httpx",
        "requests.",
        "socket.",
        "research_provider",
    )

    assert all(
        marker not in combined
        for marker in forbidden
    )
