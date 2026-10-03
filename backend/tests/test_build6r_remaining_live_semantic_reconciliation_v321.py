from __future__ import annotations

import asyncio
import inspect
from copy import deepcopy
from types import SimpleNamespace

import app.services.claims_audit as claims_audit


LIVE_REMAINDER = {
    1: (
        "categoria (sheet mask facial), quantidade (7 sheets) e volume de ess\u00eancia (150 mL)",
        "ingredients/contents",
        "master_concept.story_beats[2]",
    ),
    2: (
        "Nome completo do produto: LuLuLun Hydra EX Mask 7 Sheets e manufacturer sales name Face Mask LuLuLun EX 1FS",
        "product identity",
        "master_concept.must_include[1]",
    ),
    3: (
        "Men\u00e7\u00e3o clara ao formato: pouch com 7 sheets contendo 150 mL de ess\u00eancia",
        "ingredients/contents",
        "master_concept.must_include[2]",
    ),
    4: (
        "Lista factual dos ingredientes confirmados pelo fabricante: human adipose-derived mesenchymal cell exosomes como ingrediente de condicionamento da pele sem conter c\u00e9lulas-tronco; glutathione; arbutin; ascorbyl palmitate (vitamin C derivative); human recombinant oligopeptide-1 (EGF); Ceramide AP; Ceramide NP; atelocollagen; hydroxypropyltrimonium hyaluronate",
        "ingredients/contents",
        "master_concept.must_include[3]",
    ),
    5: (
        "Caracter\u00edsticas de formula\u00e7\u00e3o verificadas: colorant-free, fragrance-free, mineral-oil-free, alcohol-free",
        "ingredients/contents",
        "master_concept.must_include[4]",
    ),
    6: (
        "Men\u00e7\u00e3o de que o fabricante descreve o tecido como Melty Feel Sheet",
        "product feature/benefit",
        "master_concept.must_include[5]",
    ),
    7: (
        "Human adipose-derived mesenchymal cell exosomes (ingrediente de condicionamento da pele; fabricante declara que n\u00e3o cont\u00e9m c\u00e9lulas-tronco)",
        "ingredients/contents",
        "creative.creative_brief.template_suggestion",
    ),
    8: (
        "Oligopept\u00eddeo-1 humano recombinante (EGF)",
        "ingredients/contents",
        "ai_extracted_candidate",
    ),
    9: (
        "Hydra EX 7 Sheets \u00e9 uma sheet mask com essa combina\u00e7\u00e3o espec\u00edfica de ingredientes e esse modo de uso descrito pelo fabricante",
        "ingredients/contents",
        "ai_extracted_candidate",
    ),
    10: (
        "Informa\u00e7\u00f5es de formula\u00e7\u00e3o \u2013 Sem corante (colorant-free) \u2013 Sem fragr\u00e2ncia (fragrance-free) \u2013 Sem \u00f3leo mineral (mineral-oil-free) \u2013 Sem \u00e1lcool (alcohol-free)",
        "ingredients/contents",
        "ai_extracted_candidate",
    ),
}

SUPPORTED = {2, 3, 4, 5, 6, 7, 8, 10}
BLOCKED = {1, 9}


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


def _finding(index, *, text=None, category=None, source=None):
    claim_text, claim_category, source_field = LIVE_REMAINDER[index]

    return claims_audit.ClaimFinding(
        claim_text=claim_text if text is None else text,
        claim_category=claim_category if category is None else category,
        source_field=source_field if source is None else source,
        evidence_status="UNSUPPORTED",
        allowed_source="",
        reason="authoritative V3.20 live remainder",
    )


def _fields_for_corpus():
    fields = {}

    for text, _category, source in LIVE_REMAINDER.values():
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
        ._build6r_v321_reconcile_remaining_live_semantic_candidates(
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


def test_v321_exact_authoritative_partition_is_8_0_2():
    result = _reconcile(
        [
            _finding(index)
            for index in sorted(LIVE_REMAINDER)
        ]
    )

    supported = {
        index
        for index, finding in zip(
            sorted(LIVE_REMAINDER),
            result.findings,
        )
        if finding.evidence_status == "SUPPORTED"
    }

    assert supported == SUPPORTED
    assert BLOCKED == set(LIVE_REMAINDER) - supported
    assert all(
        finding.allowed_source != "non_assertive_statement"
        for finding in result.findings
    )


def test_v321_live_finding_2_product_identity_reconciles():
    assert _status(_finding(2)).evidence_status == "SUPPORTED"


def test_v321_live_finding_3_quantity_format_reconciles():
    assert _status(_finding(3)).evidence_status == "SUPPORTED"


def test_v321_live_finding_4_full_ingredient_list_reconciles():
    assert _status(_finding(4)).evidence_status == "SUPPORTED"


def test_v321_live_finding_5_free_from_framing_reconciles():
    assert _status(_finding(5)).evidence_status == "SUPPORTED"


def test_v321_live_finding_6_pure_feature_under_ambiguous_category_reconciles():
    assert _status(_finding(6)).evidence_status == "SUPPORTED"


def test_v321_live_finding_7_same_field_stem_caveat_reconciles():
    assert _status(_finding(7)).evidence_status == "SUPPORTED"


def test_v321_live_finding_8_portuguese_egf_alias_reconciles():
    assert _status(_finding(8)).evidence_status == "SUPPORTED"


def test_v321_live_finding_10_free_from_portuguese_reconciles():
    assert _status(_finding(10)).evidence_status == "SUPPORTED"


def test_v321_live_finding_1_mixed_unverified_category_remains_blocked():
    finding = _status(_finding(1))
    assert finding.evidence_status == "UNSUPPORTED"


def test_v321_live_finding_9_contextual_reference_remains_blocked():
    finding = _status(_finding(9))
    assert finding.evidence_status == "UNSUPPORTED"


def test_v321_product_feature_benefit_actual_benefit_remains_blocked():
    finding = _finding(
        6,
        text="Melty Feel Sheet reduz linhas e firma a pele",
    )
    assert _status(finding).evidence_status == "UNSUPPORTED"


def test_v321_product_feature_benefit_efficacy_remains_blocked():
    finding = _finding(
        6,
        text="Melty Feel Sheet melhora a eficacia do produto",
    )
    assert _status(finding).evidence_status == "UNSUPPORTED"


def test_v321_product_feature_benefit_result_remains_blocked():
    finding = _finding(
        6,
        text="Melty Feel Sheet entrega resultado visivel",
    )
    assert _status(finding).evidence_status == "UNSUPPORTED"


def test_v321_product_feature_benefit_superiority_remains_blocked():
    finding = _finding(
        6,
        text="Melty Feel Sheet tem performance superior",
    )
    assert _status(finding).evidence_status == "UNSUPPORTED"


def test_v321_egf_alias_is_bounded_to_canonical_tokens():
    good = _finding(8)
    bad = _finding(
        8,
        text="Oligopeptideo-1 humano recombinante (EGF) premium",
    )

    assert _status(good).evidence_status == "SUPPORTED"
    assert _status(bad).evidence_status == "UNSUPPORTED"


def test_v321_free_from_normalization_is_bounded():
    good = _finding(10)
    bad = _finding(
        10,
        text=(
            "Informacoes de formulacao - Sem corante - Sem fragrancia - "
            "Sem oleo mineral - Sem alcool e hipoalergenico"
        ),
    )

    assert _status(good).evidence_status == "SUPPORTED"
    assert _status(bad).evidence_status == "UNSUPPORTED"


def test_v321_same_field_stem_qualification_is_required_for_master_field():
    finding = _finding(4)
    fields = _fields_for_corpus()

    assert (
        claims_audit._build6r_v321_same_source_stem_cell_qualified(
            finding,
            _verified(),
            fields,
        )
        is True
    )


def test_v321_same_field_stem_qualification_is_required_for_direct_source():
    finding = _finding(7)
    fields = _fields_for_corpus()

    assert (
        claims_audit._build6r_v321_same_source_stem_cell_qualified(
            finding,
            _verified(),
            fields,
        )
        is True
    )


def test_v321_positive_stem_lineage_without_same_field_caveat_remains_blocked():
    finding = _finding(
        7,
        text=(
            "Human adipose-derived mesenchymal cell exosomes "
            "como ingrediente de condicionamento da pele"
        ),
    )

    fields = {
        finding.source_field:
            finding.claim_text,
    }

    assert (
        _status(
            finding,
            fields=fields,
        ).evidence_status
        == "UNSUPPORTED"
    )


def test_v321_cross_field_stem_caveat_inheritance_remains_blocked():
    finding = _finding(
        7,
        text=(
            "Human adipose-derived mesenchymal cell exosomes "
            "como ingrediente de condicionamento da pele"
        ),
    )

    fields = {
        finding.source_field:
            finding.claim_text,
        "copy.pt-BR.caption":
            "O fabricante declara que nao contem celulas-tronco",
    }

    assert (
        _status(
            finding,
            fields=fields,
        ).evidence_status
        == "UNSUPPORTED"
    )


def test_v321_canonical_no_stem_backing_remains_required():
    verified = deepcopy(_verified())
    verified.verified_claims = [
        claim.replace(
            "; manufacturer states stem cells are not contained",
            "",
        )
        for claim in verified.verified_claims
    ]
    verified.verified_ingredients = [
        ingredient.replace(
            "; manufacturer states stem cells are not contained",
            "",
        )
        for ingredient in verified.verified_ingredients
    ]

    assert (
        _status(
            _finding(7),
            verified=verified,
        ).evidence_status
        == "UNSUPPORTED"
    )


def test_v321_unknown_source_field_remains_blocked():
    finding = _finding(
        8,
        source="unknown.generated.field",
    )
    assert _status(finding).evidence_status == "UNSUPPORTED"


def test_v321_research_trend_source_remains_non_evidence():
    finding = _finding(
        8,
        source="research.trends[0]",
    )
    assert _status(finding).evidence_status == "UNSUPPORTED"


def test_v321_price_claim_remains_blocked():
    finding = _finding(
        8,
        text="Preco de 1000 JPY",
        category="price_or_availability",
    )
    assert _status(finding).evidence_status == "UNSUPPORTED"


def test_v321_availability_scarcity_ranking_popularity_remain_blocked():
    claims = (
        "Disponivel em estoque",
        "Ultimas unidades",
        "Numero 1 no ranking",
        "Produto muito popular",
    )

    for text in claims:
        finding = _finding(
            8,
            text=text,
            category="price_or_availability",
        )
        assert _status(finding).evidence_status == "UNSUPPORTED"


def test_v321_mixed_category_guard_does_not_infer_empty_verified_category():
    verified = deepcopy(_verified())
    verified.category = None

    assert (
        _status(
            _finding(1),
            verified=verified,
        ).evidence_status
        == "UNSUPPORTED"
    )


def test_v321_contextual_reference_stays_blocked_on_other_allowed_source():
    finding = _finding(
        9,
        source="copy.pt-BR.caption",
    )
    fields = {
        "copy.pt-BR.caption":
            finding.claim_text,
    }

    assert (
        _status(
            finding,
            fields=fields,
        ).evidence_status
        == "UNSUPPORTED"
    )


def test_v321_supported_findings_use_verified_product_facts_only():
    for index in sorted(SUPPORTED):
        finding = _status(_finding(index))
        assert finding.evidence_status == "SUPPORTED"
        assert finding.allowed_source == "verified_product_facts"


def test_v321_sealed_v320_layer_alone_still_rejects_exact_remainder():
    result = (
        claims_audit
        ._build6r_v320_reconcile_live_semantic_candidates(
            claims_audit.ClaimAuditResult(
                findings=[
                    _finding(index)
                    for index in sorted(LIVE_REMAINDER)
                ]
            ),
            _verified(),
            _fields_for_corpus(),
        )
    )

    assert all(
        finding.evidence_status == "UNSUPPORTED"
        for finding in result.findings
    )


def test_v321_wrapper_executes_sealed_v320_chain_exactly_once(monkeypatch):
    original = claims_audit.ClaimAuditResult(findings=[])
    calls = {"count": 0}

    async def fake_previous(*args, **kwargs):
        calls["count"] += 1
        return original

    monkeypatch.setattr(
        claims_audit,
        "_build6r_augment_before_v321",
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


def test_v321_wrapper_preserves_all_historical_contract_markers():
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
        "_build6r_augment_before_v320",
        "_build6r_v320_reconcile_live_semantic_candidates",
        "_build6r_augment_before_v321",
        "_build6r_v321_reconcile_remaining_live_semantic_candidates",
    )

    assert all(
        marker in source
        for marker in markers
    )


def test_v321_production_layer_is_zero_cost_and_product_agnostic():
    source = "\n".join(
        (
            inspect.getsource(
                claims_audit._build6r_v321_has_contextual_reference
            ),
            inspect.getsource(
                claims_audit._build6r_v321_has_benefit_effect_language
            ),
            inspect.getsource(
                claims_audit._build6r_v321_category_alias
            ),
            inspect.getsource(
                claims_audit._build6r_v321_validation_text
            ),
            inspect.getsource(
                claims_audit._build6r_v321_same_source_stem_cell_qualified
            ),
            inspect.getsource(
                claims_audit._build6r_v321_candidate_supported
            ),
            inspect.getsource(
                claims_audit._build6r_v321_reconcile_remaining_live_semantic_candidates
            ),
            inspect.getsource(
                claims_audit.augment_with_ai_extraction
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
        "campaign_id",
        "product_id",
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


def test_v321_does_not_expand_source_field_admission():
    allowed = (
        "master_concept.must_include[1]",
        "master_concept.story_beats[2]",
        "ai_extracted_candidate",
        "copy.pt-BR.caption",
        "creative.creative_brief.template_suggestion",
    )

    for source in allowed:
        assert (
            claims_audit._build6r_v320_source_field_allowed(source)
            is True
        )

    assert (
        claims_audit._build6r_v320_source_field_allowed(
            "unknown.generated.field"
        )
        is False
    )
