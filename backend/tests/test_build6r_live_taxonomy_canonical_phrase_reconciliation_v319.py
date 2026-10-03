from __future__ import annotations

import asyncio
import inspect
from copy import deepcopy
from types import SimpleNamespace

import pytest

import app.services.claims_audit as claims_audit


LIVE_CORPUS = {
    1: (
        "7 sheets / 150 mL",
        "product_format_or_quantity",
        "ai_extracted_candidate",
    ),
    2: (
        "caracter\u00edsticas declaradas (colorant-free, fragrance-free, "
        "mineral-oil-free, alcohol-free, descrita como Melty Feel Sheet)",
        "ingredients_or_composition",
        "master_concept.archetype_reasoning",
    ),
    3: (
        "Caracter\u00edsticas de formula\u00e7\u00e3o: \"Colorant-free\", "
        "\"Fragrance-free\", \"Mineral-oil-free\", \"Alcohol-free\", e "
        "\"Sheet described by the manufacturer as a Melty Feel Sheet\"",
        "ingredients_or_composition",
        "ai_extracted_candidate",
    ),
    4: (
        "Nome do produto e do fabricante conforme verificado: LuLuLun Hydra "
        "EX facial sheet mask, Face Mask LuLuLun EX 1FS (7-sheet pouch variant)",
        "product_identity",
        "master_concept.must_include[1]",
    ),
    5: (
        "Informa\u00e7\u00e3o clara de formato e quantidade: "
        "7 sheets / essence 150 mL",
        "product_format_or_quantity",
        "master_concept.must_include[2]",
    ),
    6: (
        "Caracter\u00edsticas de formula\u00e7\u00e3o confirmadas: "
        "colorant-free, fragrance-free, mineral-oil-free, alcohol-free, "
        "e men\u00e7\u00e3o de que o fabricante descreve a folha como "
        "\"Melty Feel Sheet\"",
        "ingredients_or_composition",
        "master_concept.must_include[4]",
    ),
    7: (
        "Sequ\u00eancia de uso exatamente como o fabricante descreve: "
        "desdobrar a m\u00e1scara, ajustar ao redor de olhos e boca, "
        "pressionar para retirar o ar preso, levantar se\u00e7\u00f5es de "
        "corte da bochecha ao longo da linha do rosto, pressionar toda a "
        "m\u00e1scara com as palmas, ap\u00f3s remover dobrar a m\u00e1scara "
        "para wiping/light patting e seguir com emuls\u00e3o ou creme; "
        "men\u00e7\u00e3o de que o fabricante descreve como utiliz\u00e1vel "
        "pela manh\u00e3 ou \u00e0 noite em lugar do t\u00f4nico",
        "usage_instructions",
        "master_concept.must_include[5]",
    ),
    8: (
        "Vers\u00e3o pouch com 7 folhas",
        "product_format_or_quantity",
        "ai_extracted_candidate",
    ),
    9: (
        "150 mL de ess\u00eancia no mesmo pacote",
        "product_format_or_quantity",
        "ai_extracted_candidate",
    ),
    10: (
        "Cont\u00e9m exossomos derivados de c\u00e9lulas-tronco "
        "mesenquimais de tecido adiposo humano como ingrediente de "
        "condicionamento da pele",
        "ingredients_or_composition",
        "ai_extracted_candidate",
    ),
    11: (
        "Cont\u00e9m palmitato de ascorbila (derivado de vitamina C)",
        "ingredients_or_composition",
        "ai_extracted_candidate",
    ),
    12: (
        "7 sheet masks no mesmo pouch",
        "product_format_or_quantity",
        "ai_extracted_candidate",
    ),
    13: (
        "\u00c9 a vers\u00e3o pouch com 7 folhas",
        "product_format_or_quantity",
        "copy.pt-BR.caption",
    ),
    14: (
        "Cont\u00e9m 150 mL de ess\u00eancia no pacote",
        "product_format_or_quantity",
        "copy.pt-BR.caption",
    ),
    15: (
        "7 m\u00e1scaras em folha no mesmo pouch",
        "product_format_or_quantity",
        "copy.pt-BR.caption",
    ),
}


EXPECTED_SUPPORTED = {
    1, 2, 3, 4, 5, 6, 7, 8, 9, 11, 12, 13, 14, 15,
}

EXPECTED_UNSUPPORTED = {
    10,
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
        verified_benefits=[],
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
            (
                "Human adipose-derived mesenchymal cell exosomes "
                "(manufacturer-listed skin-conditioning ingredient; "
                "manufacturer states stem cells are not contained)"
            ),
            "Glutathione",
            "Arbutin",
            "Ascorbyl palmitate (vitamin C derivative)",
            "Ceramide AP",
            "Ceramide NP",
            "Atelocollagen",
            "Hydroxypropyltrimonium hyaluronate",
            "Human recombinant oligopeptide-1 (EGF)",
        ],
        prohibited_claims=[],
        missing_information=[],
        provenance="manufacturer_official",
    )


def _finding(
    index,
    *,
    category=None,
    source=None,
    text=None,
):
    claim_text, claim_category, source_field = LIVE_CORPUS[index]

    return claims_audit.ClaimFinding(
        claim_text=(
            claim_text
            if text is None
            else text
        ),
        claim_category=(
            claim_category
            if category is None
            else category
        ),
        source_field=(
            source_field
            if source is None
            else source
        ),
        evidence_status="UNSUPPORTED",
        allowed_source="",
        reason="sealed post-V3.18 live hard fail",
    )


def _fields_without_stem_qualification():
    fields = {}

    for index, (
        text,
        _category,
        source,
    ) in LIVE_CORPUS.items():
        if source == "ai_extracted_candidate":
            continue

        fields[source] = (
            fields.get(source, "")
            + (" | " if source in fields else "")
            + text
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
        ._build6r_v319_reconcile_live_phrase_candidates(
            claims_audit.ClaimAuditResult(
                findings=findings
            ),
            (
                _verified()
                if verified is None
                else verified
            ),
            (
                _fields_without_stem_qualification()
                if fields is None
                else fields
            ),
        )
    )


def test_v319_exact_sealed_15_finding_contract():
    result = _reconcile(
        [
            _finding(index)
            for index in sorted(LIVE_CORPUS)
        ]
    )

    statuses = {
        index:
            finding.evidence_status
        for index, finding in zip(
            sorted(LIVE_CORPUS),
            result.findings,
        )
    }

    supported = {
        index
        for index, status in statuses.items()
        if status == "SUPPORTED"
    }

    unsupported = {
        index
        for index, status in statuses.items()
        if status == "UNSUPPORTED"
    }

    assert supported == EXPECTED_SUPPORTED
    assert unsupported == EXPECTED_UNSUPPORTED

    for index, finding in zip(
        sorted(LIVE_CORPUS),
        result.findings,
    ):
        if index in EXPECTED_SUPPORTED:
            assert finding.allowed_source == "verified_product_facts"
            assert "V3.19" in finding.reason


@pytest.mark.parametrize(
    "category,expected",
    [
        (
            "product_format_or_quantity",
            "product features attributes",
        ),
        (
            "product_identity",
            "product features attributes",
        ),
        (
            "usage_instructions",
            "directions for use",
        ),
        (
            "ingredients_or_composition",
            "ingredients percentages",
        ),
    ],
)
def test_v319_live_taxonomy_aliases_are_bounded(
    category,
    expected,
):
    finding = claims_audit.ClaimFinding(
        claim_text="7 sheets / 150 mL",
        claim_category=category,
        source_field="ai_extracted_candidate",
        evidence_status="UNSUPPORTED",
        allowed_source="",
        reason="taxonomy",
    )

    assert (
        claims_audit
        ._build6r_v319_category_alias(
            finding
        )
        == expected
    )


def test_v319_stem_without_same_field_qualification_remains_unsupported():
    result = _reconcile(
        [_finding(10)],
        fields={},
    )

    assert (
        result.findings[0].evidence_status
        == "UNSUPPORTED"
    )


def test_v319_stem_same_generated_field_qualification_can_reconcile():
    claim = LIVE_CORPUS[10][0]

    fields = {
        "copy.pt-BR.caption": (
            claim
            + " O fabricante afirma que esse ingrediente "
            + "n\u00e3o cont\u00e9m c\u00e9lulas-tronco."
        )
    }

    result = _reconcile(
        [_finding(10)],
        fields=fields,
    )

    assert (
        result.findings[0].evidence_status
        == "SUPPORTED"
    )

    assert (
        result.findings[0].allowed_source
        == "verified_product_facts"
    )


def test_v319_stem_cross_field_qualification_remains_unsupported():
    claim = LIVE_CORPUS[10][0]

    fields = {
        "copy.pt-BR.caption":
            claim,
        "copy.pt-BR.slide_2": (
            "O fabricante afirma que esse ingrediente "
            "n\u00e3o cont\u00e9m c\u00e9lulas-tronco."
        ),
    }

    result = _reconcile(
        [_finding(10)],
        fields=fields,
    )

    assert (
        result.findings[0].evidence_status
        == "UNSUPPORTED"
    )


def test_v319_stem_same_field_requires_canonical_no_stem_backing():
    verified = deepcopy(
        _verified()
    )

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

    claim = LIVE_CORPUS[10][0]

    fields = {
        "copy.pt-BR.caption": (
            claim
            + " O fabricante afirma que esse ingrediente "
            + "n\u00e3o cont\u00e9m c\u00e9lulas-tronco."
        )
    }

    result = _reconcile(
        [_finding(10)],
        verified=verified,
        fields=fields,
    )

    assert (
        result.findings[0].evidence_status
        == "UNSUPPORTED"
    )


@pytest.mark.parametrize(
    "category",
    [
        "product benefit",
        "product efficacy",
        "product result",
        "ranking",
        "popularity",
        "bestseller",
        "product price",
        "availability",
        "scarcity",
        "source verification",
        "provenance",
        "clinical claim",
        "scientific claim",
    ],
)
def test_v319_protected_taxonomy_families_remain_fail_closed(
    category,
):
    finding = claims_audit.ClaimFinding(
        claim_text="7 sheets / 150 mL",
        claim_category=category,
        source_field="copy.pt-BR.caption",
        evidence_status="UNSUPPORTED",
        allowed_source="",
        reason="negative",
    )

    result = _reconcile(
        [finding]
    )

    assert (
        result.findings[0].evidence_status
        == "UNSUPPORTED"
    )


@pytest.mark.parametrize(
    "source",
    [
        "strategy.research_basis[0]",
        "research.trends[0]",
        "master_concept.unknown_generated_field",
        "creative.unknown.visual_prompt",
    ],
)
def test_v319_research_and_unknown_sources_remain_fail_closed(
    source,
):
    result = _reconcile(
        [
            _finding(
                1,
                source=source,
            )
        ]
    )

    assert (
        result.findings[0].evidence_status
        == "UNSUPPORTED"
    )


@pytest.mark.parametrize(
    "text",
    [
        "Informacoes verificadas: 7 sheets / 150 mL",
        "Fonte direta: 7 sheets / 150 mL",
        "Verified information: 7 sheets / 150 mL",
        "Variante confirmada: 7 sheets / 150 mL",
    ],
)
def test_v319_meta_provenance_assertions_remain_fail_closed(
    text,
):
    result = _reconcile(
        [
            _finding(
                1,
                text=text,
            )
        ]
    )

    assert (
        result.findings[0].evidence_status
        == "UNSUPPORTED"
    )


def test_v319_unrelated_product_facts_do_not_ground_live_corpus():
    unrelated = SimpleNamespace(
        verified_description="Unrelated cleansing oil bottle.",
        verified_usage="Apply to dry skin and rinse.",
        verified_size="100 mL",
        verified_variant="100 mL bottle",
        verified_price="",
        verified_availability="",
        verified_country_of_origin="",
        verified_features=["Pump bottle"],
        verified_benefits=[],
        verified_claims=[],
        verified_ingredients=["Mineral oil"],
        prohibited_claims=[],
        missing_information=[],
        provenance="manufacturer_official",
    )

    for index in EXPECTED_SUPPORTED:
        result = _reconcile(
            [_finding(index)],
            verified=unrelated,
            fields={},
        )

        assert (
            result.findings[0].evidence_status
            == "UNSUPPORTED"
        )


def test_v319_existing_supported_finding_is_immutable():
    finding = claims_audit.ClaimFinding(
        claim_text="already supported",
        claim_category="product features/attributes",
        source_field="copy.pt-BR.caption",
        evidence_status="SUPPORTED",
        allowed_source="verified_product_facts",
        reason="existing",
    )

    result = _reconcile(
        [finding]
    )

    assert result.findings[0] == finding


def test_v319_wrapper_executes_previous_chain_once(
    monkeypatch,
):
    calls = {
        "count": 0,
    }

    async def previous(
        *args,
        **kwargs,
    ):
        calls["count"] += 1

        return claims_audit.ClaimAuditResult(
            findings=[
                _finding(index)
                for index in sorted(LIVE_CORPUS)
            ]
        )

    monkeypatch.setattr(
        claims_audit,
        "_build6r_augment_before_v319",
        previous,
    )

    result = asyncio.run(
        claims_audit.augment_with_ai_extraction(
            None,
            verified=_verified(),
            fields=
                _fields_without_stem_qualification(),
        )
    )

    assert calls["count"] == 1

    supported = {
        index
        for index, finding in zip(
            sorted(LIVE_CORPUS),
            result.findings,
        )
        if finding.evidence_status == "SUPPORTED"
    }

    assert supported == EXPECTED_SUPPORTED


def test_v319_wrapper_preserves_all_historical_contract_markers():
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
        "_build6r_augment_before_v317",
        "_build6r_v317_reconcile_runtime_alias_candidates",
        "_build6r_augment_before_v318",
        "_build6r_v318_reconcile_previsual_candidates",
        "_build6r_augment_before_v319",
        "_build6r_v319_reconcile_live_phrase_candidates",
    )

    assert all(
        marker in source
        for marker in markers
    )


def test_v319_production_layer_is_zero_cost_and_product_agnostic():
    source = "\n".join(
        (
            inspect.getsource(
                claims_audit
                ._build6r_v319_category_alias
            ),
            inspect.getsource(
                claims_audit
                ._build6r_v319_validation_text
            ),
            inspect.getsource(
                claims_audit
                ._build6r_v319_candidate_supported
            ),
            inspect.getsource(
                claims_audit
                ._build6r_v319_reconcile_live_phrase_candidates
            ),
            inspect.getsource(
                claims_audit
                .augment_with_ai_extraction
            ),
        )
    ).lower()

    forbidden = (
        "openai",
        "requests.",
        "httpx",
        "urllib",
        "socket",
        "sqlite",
        "sessionlocal",
        "lululun",
        "hanna-japan",
        "7cb6581d567e486d982a0cca439c9914",
        "77a666b299dd4b978e3f4d900de9dca1",
    )

    assert all(
        token not in source
        for token in forbidden
    )

def test_v319_noop_reconciliation_preserves_result_identity():
    original = claims_audit.ClaimAuditResult(
        findings=[]
    )

    returned = (
        claims_audit
        ._build6r_v319_reconcile_live_phrase_candidates(
            original,
            _verified(),
            {},
        )
    )

    assert returned is original

