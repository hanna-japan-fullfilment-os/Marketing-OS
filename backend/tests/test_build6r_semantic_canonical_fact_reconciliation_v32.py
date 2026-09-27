from __future__ import annotations

import asyncio
import inspect
from types import SimpleNamespace

import pytest

import app.services.claims_audit as claims_audit


SUPPORTED_INDICES = {
    1,
    2,
    6,
    7,
    10,
    11,
    12,
    13,
    15,
    16,
    17,
    19,
    20,
    21,
    23,
    24,
    25,
    26,
    27,
}


UNSUPPORTED_INDICES = {
    3,
    4,
    5,
    8,
    9,
    14,
    18,
    22,
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
            "the manufacturer suggests folding the mask for wiping/"
            "light patting and following with an emulsion or cream. "
            "Manufacturer describes it as usable morning or evening "
            "in place of toner."
        ),

        verified_size=(
            "7 sheets / essence 150 mL"
        ),

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
                "ingredient; manufacturer states stem cells are not contained"
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


TARGETS = {
    1: (
        "A LuLuLun Hydra EX vem em um pouch com 7 m\u00e1scaras "
        "e 150 mL de ess\u00eancia",
        "ingredients/contents/format",
        "ai_extracted_candidate",
    ),

    2: (
        "pode ser usada de manh\u00e3 ou \u00e0 noite, no lugar do "
        "t\u00f4nico, seguindo o passo a passo do fabricante",
        "directions for use",
        "ai_extracted_candidate",
    ),

    3: (
        "A Hydra EX \u00e9 frequentemente citada em conte\u00fados "
        "educacionais sobre J-beauty",
        "ranking/positioning/authority",
        "strategy.research_basis[2]",
    ),

    4: (
        "A embalagem com 7 m\u00e1scaras \u00e9 vista, no contexto, "
        "como um bom formato de descoberta da categoria",
        "product benefit/effect",
        "strategy.research_basis[3]",
    ),

    5: (
        "Sheet mask n\u00e3o \u00e9 s\u00f3 momento de selfie "
        "\u2014 \u00e9 um passo claro de rotina",
        "product benefit/effect",
        "ai_extracted_candidate",
    ),

    6: (
        "a LuLuLun Hydra EX \u00e9 uma m\u00e1scara facial em pouch "
        "com 7 folhas e 150 mL de ess\u00eancia",
        "ingredients/contents/format",
        "ai_extracted_candidate",
    ),

    7: (
        "pode ser usada de manh\u00e3 ou \u00e0 noite, "
        "no lugar do t\u00f4nico",
        "directions for use",
        "ai_extracted_candidate",
    ),

    8: (
        "Gerar awareness da LuLuLun Hydra EX como a refer\u00eancia "
        "did\u00e1tica para entender o \u201cpasso m\u00e1scara\u201d "
        "dentro da rotina de skincare",
        "ranking/positioning/authority",
        "master_concept.objective",
    ),

    9: (
        "Facial sheet mask em pouch multi-sheet "
        "(LuLuLun Hydra EX 7 sheets / 150 mL), usada como passo "
        "de tratamento em rotina de skincare",
        "ingredients/contents/format",
        "master_concept.product_category_context",
    ),

    10: (
        "instru\u00e7\u00f5es claras de uso do fabricante e fun\u00e7\u00e3o "
        "de substitui\u00e7\u00e3o do t\u00f4nico em manh\u00e3 ou noite",
        "directions for use",
        "master_concept.product_category_context",
    ),

    11: (
        "fatos objetivos \u2014 7-sheet pouch com 150 mL de ess\u00eancia",
        "ingredients/contents/format",
        "master_concept.proof_or_demo_strategy",
    ),

    12: (
        "caracter\u00edsticas colorant-free, fragrance-free, "
        "mineral-oil-free e alcohol-free",
        "ingredients/contents/format",
        "master_concept.proof_or_demo_strategy",
    ),

    13: (
        "clarifica\u00e7\u00e3o de que o fabricante descreve uso de "
        "manh\u00e3 ou noite em lugar do t\u00f4nico",
        "directions for use",
        "master_concept.proof_or_demo_strategy",
    ),

    14: (
        "3 passos: 1. Limpeza; 2. LuLuLun Hydra EX "
        "(no lugar do t\u00f4nico); 3. Emuls\u00e3o ou creme",
        "directions for use",
        "master_concept.story_beats[4]",
    ),

    15: (
        "instru\u00e7\u00e3o p\u00f3s-uso fiel: dobrar a m\u00e1scara "
        "retirada e usar para wiping/light patting",
        "directions for use",
        "master_concept.must_include[5]",
    ),

    16: (
        "A LuLuLun Hydra EX \u00e9 uma m\u00e1scara facial em folha "
        "num pouch com 7 unidades e 150 mL de ess\u00eancia",
        "ingredients/contents/format",
        "ai_extracted_candidate",
    ),

    17: (
        "O pr\u00f3prio fabricante indica usar como um passo de cuidado, "
        "de manh\u00e3 ou \u00e0 noite, no lugar do t\u00f4nico",
        "directions for use",
        "ai_extracted_candidate",
    ),

    18: (
        "Pensa nela como um \u201cpasso m\u00e1scara\u201d entre a limpeza "
        "e o seu hidratante/emuls\u00e3o",
        "directions for use",
        "ai_extracted_candidate",
    ),

    19: (
        "A f\u00f3rmula da Hydra EX vem com ingredientes como exossomos "
        "derivados de c\u00e9lulas mesenquimais de tecido adiposo humano "
        "(listado pelo fabricante como ingrediente de condicionamento "
        "da pele, sem conter c\u00e9lulas-tronco), glutathione, arbutin, "
        "derivado de vitamina C (ascorbyl palmitate), ceramidas AP e NP, "
        "atelocollagen, hydroxypropyltrimonium hyaluronate e human "
        "recombinant oligopeptide\u20111",
        "ingredients/contents/format",
        "ai_extracted_candidate",
    ),

    20: (
        "Segundo o fabricante, \u00e9 uma m\u00e1scara sem corantes, "
        "sem fragr\u00e2ncia, sem \u00f3leo mineral e sem \u00e1lcool",
        "ingredients/contents/format",
        "ai_extracted_candidate",
    ),

    21: (
        "o tecido \u00e9 descrito como Melty Feel Sheet",
        "ingredients/contents/format",
        "ai_extracted_candidate",
    ),

    22: (
        "\u00e9 um passo claro, com lugar definido entre limpeza e "
        "hidrata\u00e7\u00e3o, que voc\u00ea pode encaixar no seu cuidado "
        "da manh\u00e3 ou da noite, como o fabricante orienta",
        "directions for use",
        "ai_extracted_candidate",
    ),

    23: (
        "O que ela \u00e9: \u2022 M\u00e1scara facial em folha "
        "\u2022 Pouch com 7 m\u00e1scaras "
        "\u2022 150 mL de ess\u00eancia no total",
        "ingredients/contents/format",
        "ai_extracted_candidate",
    ),

    24: (
        "O pr\u00f3prio fabricante indica a Hydra EX como um passo "
        "de cuidado que pode ser usado de manh\u00e3 ou \u00e0 noite, "
        "no lugar do t\u00f4nico",
        "directions for use",
        "copy.pt-BR.caption",
    ),

    25: (
        "Na f\u00f3rmula, o fabricante lista ingredientes como: "
        "\u2022 Exossomos derivados de c\u00e9lulas mesenquimais de "
        "tecido adiposo humano (como ingrediente de condicionamento "
        "da pele; o pr\u00f3prio fabricante informa que n\u00e3o cont\u00e9m "
        "c\u00e9lulas-tronco) "
        "\u2022 Glutathione, arbutin, derivado de vitamina C "
        "(ascorbyl palmitate) "
        "\u2022 Ceramide AP, Ceramide NP, atelocollagen "
        "\u2022 Hydroxypropyltrimonium hyaluronate e human "
        "recombinant oligopeptide\u20111",
        "ingredients/contents/format",
        "ai_extracted_candidate",
    ),

    26: (
        "o fabricante indica que a m\u00e1scara \u00e9 sem corantes, "
        "sem fragr\u00e2ncia, sem \u00f3leo mineral e sem \u00e1lcool",
        "ingredients/contents/format",
        "ai_extracted_candidate",
    ),

    27: (
        "7 sheet masks em um pouch com 150 mL de ess\u00eancia",
        "ingredients/contents/format",
        "ai_extracted_candidate",
    ),
}


def _finding(
    text,
    category,
    source_field,
):
    return claims_audit.ClaimFinding(
        claim_text=text,
        claim_category=category,
        source_field=source_field,
        evidence_status="UNSUPPORTED",
        allowed_source="",
        reason="synthetic V3.2 target",
    )


def _status(
    text,
    category,
    source_field,
):
    result = (
        claims_audit
        .ClaimAuditResult(
            findings=[
                _finding(
                    text,
                    category,
                    source_field,
                )
            ]
        )
    )

    reconciled = (
        claims_audit
        ._build6r_reconcile_generated_semantic_findings_v32(
            result,
            _verified(),
        )
    )

    return reconciled.findings[0]


@pytest.mark.parametrize(
    "index",
    sorted(
        TARGETS
    ),
)
def test_exact_target_27_contract(
    index,
):
    text, category, source_field = (
        TARGETS[index]
    )

    finding = _status(
        text,
        category,
        source_field,
    )

    expected = (
        "SUPPORTED"
        if index in SUPPORTED_INDICES
        else "UNSUPPORTED"
    )

    assert (
        finding.evidence_status
        == expected
    )

    if expected == "SUPPORTED":
        assert (
            finding.allowed_source
            == "verified_product_facts"
        )


def test_exact_supported_and_blocked_sets():
    actual_supported = set()
    actual_blocked = set()

    for (
        index,
        (
            text,
            category,
            source_field,
        ),
    ) in TARGETS.items():
        finding = _status(
            text,
            category,
            source_field,
        )

        if (
            finding.evidence_status
            == "SUPPORTED"
        ):
            actual_supported.add(
                index
            )
        else:
            actual_blocked.add(
                index
            )

    assert (
        actual_supported
        == SUPPORTED_INDICES
    )

    assert (
        actual_blocked
        == UNSUPPORTED_INDICES
    )


@pytest.mark.parametrize(
    "source_field",
    [
        "strategy.research_basis[0]",
        "strategy.research_basis[2]",
        "research.summary",
        "research.findings[0]",
        "creative.research_basis",
        "strategy.other_field",
    ],
)
def test_research_and_other_fields_never_become_product_fact(
    source_field,
):
    finding = _status(
        (
            "7 sheet masks em um pouch "
            "com 150 mL de ess\u00eancia"
        ),
        "ingredients/contents/format",
        source_field,
    )

    assert (
        finding.evidence_status
        == "UNSUPPORTED"
    )


@pytest.mark.parametrize(
    "text",
    [
        (
            "A LuLuLun Hydra EX vem em um pouch "
            "com 8 m\u00e1scaras e 150 mL de ess\u00eancia"
        ),
        (
            "A LuLuLun Hydra EX vem em um pouch "
            "com 7 m\u00e1scaras e 200 mL de ess\u00eancia"
        ),
        (
            "pouch com 7 m\u00e1scaras em sach\u00eas separados "
            "e 150 mL de ess\u00eancia"
        ),
        (
            "pouch com 7 m\u00e1scaras, 150 mL de ess\u00eancia "
            "e refil separado"
        ),
    ],
)
def test_package_format_unknown_facts_fail_closed(
    text,
):
    assert (
        _status(
            text,
            "ingredients/contents/format",
            "ai_extracted_candidate",
        ).evidence_status
        == "UNSUPPORTED"
    )


@pytest.mark.parametrize(
    "text",
    [
        "glutathione e retinol",
        "ceramidas",
        "contem ceramidas",
        (
            "exossomos derivados de c\u00e9lulas mesenquimais "
            "de tecido adiposo humano e cont\u00e9m c\u00e9lulas-tronco"
        ),
        (
            "derivado de vitamina C (ascorbyl palmitate) "
            "com retinol"
        ),
    ],
)
def test_ingredient_unknown_residue_fail_closed(
    text,
):
    assert (
        _status(
            text,
            "ingredients/contents/format",
            "ai_extracted_candidate",
        ).evidence_status
        == "UNSUPPORTED"
    )


@pytest.mark.parametrize(
    "text",
    [
        (
            "sem corantes, sem fragr\u00e2ncia, sem \u00f3leo "
            "mineral, sem \u00e1lcool e hipoalerg\u00eanica"
        ),
        (
            "sem corantes e cont\u00e9m \u00e1lcool"
        ),
        (
            "Melty Feel Sheet ultra macio"
        ),
    ],
)
def test_free_from_and_melty_unknown_residue_fail_closed(
    text,
):
    assert (
        _status(
            text,
            "ingredients/contents/format",
            "ai_extracted_candidate",
        ).evidence_status
        == "UNSUPPORTED"
    )


@pytest.mark.parametrize(
    "text",
    [
        (
            "usar depois da limpeza, de manh\u00e3 ou \u00e0 noite, "
            "no lugar do t\u00f4nico"
        ),
        (
            "usar como passo de tratamento de manh\u00e3 ou "
            "\u00e0 noite no lugar do t\u00f4nico"
        ),
        (
            "usar entre a limpeza e a hidrata\u00e7\u00e3o, "
            "de manh\u00e3 ou \u00e0 noite"
        ),
        (
            "usar de manh\u00e3 ou \u00e0 noite no lugar do "
            "t\u00f4nico por 10 minutos"
        ),
        (
            "usar de manh\u00e3 ou \u00e0 noite no lugar do "
            "t\u00f4nico diariamente"
        ),
        (
            "usar de manh\u00e3 ou \u00e0 noite no lugar do "
            "t\u00f4nico para resultados vis\u00edveis"
        ),
        (
            "3 passos: limpeza, Hydra EX, hidrata\u00e7\u00e3o"
        ),
    ],
)
def test_usage_unknown_sequence_timing_positioning_fail_closed(
    text,
):
    assert (
        _status(
            text,
            "directions for use",
            "ai_extracted_candidate",
        ).evidence_status
        == "UNSUPPORTED"
    )


def test_product_feature_category_not_broadly_enabled():
    finding = _status(
        (
            "7 sheet masks em um pouch "
            "com 150 mL de ess\u00eancia"
        ),
        "product features",
        "ai_extracted_candidate",
    )

    assert (
        finding.evidence_status
        == "UNSUPPORTED"
    )


def test_copy_and_master_concept_are_bounded_eligible_sources():
    copy_finding = _status(
        (
            "pode ser usada de manh\u00e3 ou \u00e0 noite, "
            "no lugar do t\u00f4nico"
        ),
        "directions for use",
        "copy.pt-BR.caption",
    )

    master_finding = _status(
        (
            "fatos objetivos \u2014 "
            "7-sheet pouch com 150 mL de ess\u00eancia"
        ),
        "ingredients/contents/format",
        "master_concept.proof_or_demo_strategy",
    )

    assert (
        copy_finding.evidence_status
        == "SUPPORTED"
    )

    assert (
        master_finding.evidence_status
        == "SUPPORTED"
    )


def test_v32_wrapper_runs_after_existing_reconciliation():
    source = inspect.getsource(
        claims_audit
        .augment_with_ai_extraction
    )

    assert (
        "_build6r_augment_before_v32"
        in source
    )

    assert (
        "_build6r_reconcile_generated_semantic_findings_v32"
        in source
    )


def test_v32_previous_wrapper_is_v31_chain():
    source = inspect.getsource(
        claims_audit
        ._build6r_augment_before_v32
    )

    assert (
        "_build6r_reconcile_ai_extracted_canonical_fact_families_v31"
        in source
    )

    assert (
        "_build6r_recover_semantic_candidate_source_fields"
        in source
    )

    assert (
        "_build6r_filter_explicit_negation_findings"
        in source
    )

    assert (
        "_build6r_reconcile_semantic_contents_findings"
        in source
    )


def test_v32_has_no_provider_network_or_research_evidence_path():
    source = inspect.getsource(
        claims_audit
        ._build6r_reconcile_generated_semantic_findings_v32
    )

    helper_source = inspect.getsource(
        claims_audit
        ._build6r_v32_generated_finding_supported
    )

    combined = (
        source
        + "\n"
        + helper_source
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


def test_final_wrapper_target_contract(
    monkeypatch,
):
    findings = [
        _finding(
            text,
            category,
            source_field,
        )
        for (
            _index,
            (
                text,
                category,
                source_field,
            ),
        )
        in TARGETS.items()
    ]

    async def fake_previous(
        *args,
        **kwargs,
    ):
        return (
            claims_audit
            .ClaimAuditResult(
                findings=findings
            )
        )

    monkeypatch.setattr(
        claims_audit,
        "_build6r_augment_before_v32",
        fake_previous,
    )

    result = asyncio.run(
        claims_audit
        .augment_with_ai_extraction(
            None,
            fields={},
            verified=_verified(),
            brand=None,
            model="synthetic",
            existing=(
                claims_audit
                .ClaimAuditResult(
                    findings=[]
                )
            ),
        )
    )

    actual_supported = {
        index
        for index, finding
        in zip(
            TARGETS,
            result.findings,
        )
        if (
            finding.evidence_status
            == "SUPPORTED"
        )
    }

    actual_blocked = (
        set(TARGETS)
        - actual_supported
    )

    assert (
        actual_supported
        == SUPPORTED_INDICES
    )

    assert (
        actual_blocked
        == UNSUPPORTED_INDICES
    )
