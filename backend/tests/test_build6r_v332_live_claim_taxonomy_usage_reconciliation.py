from __future__ import annotations

import asyncio
from types import SimpleNamespace

from app.schemas.claims_audit import ClaimAuditResult, ClaimFinding
from app.services import claims_audit


def _verified():
    return SimpleNamespace(
        verified_description=(
            "LuLuLun Hydra EX facial sheet mask, exact 7-sheet pouch variant. "
            "Manufacturer sales name: Face Mask LuLuLun EX 1FS."
        ),
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
        verified_price="",
        verified_availability="",
        verified_country_of_origin="",
        verified_claims=[
            "7-sheet pouch containing 150 mL of essence",
            (
                "Contains human adipose-derived mesenchymal cell exosomes as "
                "a manufacturer-listed skin-conditioning ingredient; "
                "manufacturer states stem cells are not contained"
            ),
            "Contains glutathione, arbutin, and the vitamin C derivative ascorbyl palmitate",
            (
                "Contains Ceramide AP, Ceramide NP, atelocollagen, "
                "hydroxypropyltrimonium hyaluronate, and human recombinant oligopeptide-1"
            ),
            (
                "Manufacturer states the formula is colorant-free, fragrance-free, "
                "mineral-oil-free, and alcohol-free"
            ),
            "Manufacturer describes the sheet as a Melty Feel Sheet",
        ],
    )


def _finding(text: str, category: str, source: str = "ai_extracted_candidate") -> ClaimFinding:
    return ClaimFinding(
        claim_text=text,
        claim_category=category,
        source_field=source,
        evidence_status="UNSUPPORTED",
        allowed_source="",
        reason="No matching text found.",
    )


# Exact 15 Attempt-6 rejected findings, preserving the live categories.
ATTEMPT6_FINDINGS = [
    _finding(
        "A LuLuLun Hydra EX é uma máscara facial em tecido (sheet mask) em embalagem tipo pouch com 7 folhas.",
        "product_feature_general",
    ),
    _finding(
        "Este pouch tem 7 máscaras embebidas em 150 mL de essência.",
        "product_feature_general",
    ),
    _finding(
        "Pressionar para tirar o ar preso",
        "directions_or_usage",
    ),
    _finding(
        "Erguer os recortes da bochecha ao longo da linha do rosto",
        "directions_or_usage",
    ),
    _finding(
        "Depois de remover, o fabricante sugere dobrar a máscara para passar na pele como toalhinha/toque final e, em seguida, usar uma emulsão ou creme",
        "directions_or_usage",
    ),
    _finding(
        "Usando a Hydra EX como exemplo, o que a gente sabe de forma objetiva: • É uma máscara facial em tecido (sheet mask) • Vem em um pouch com 7 folhas • Esse pouch contém 150 mL de essência • O nome de venda do fabricante é Face Mask LuLuLun EX 1FS",
        "product_feature_general",
    ),
    _finding(
        "Sobre a folha, o fabricante descreve como Melty Feel Sheet.",
        "product_feature_general",
        "copy.pt-BR.caption",
    ),
    _finding(
        "Modo de uso, só com o que está indicado: • Desdobrar a máscara e encaixar ao redor dos olhos e da boca • Pressionar pra tirar o ar preso • Levantar os recortes da bochecha acompanhando a linha do rosto • Pressionar a máscara inteira com as palmas das mãos • Depois de tirar, o fabricante sugere dobrar a folha e usar pra um leve toque final na pele, e depois seguir com emulsão ou creme • Ele também descreve que a máscara pode ser usada de manhã ou à noite no lugar do tônico",
        "directions_or_usage",
    ),
    _finding(
        "Variant Face Mask LuLuLun EX 1FS, com 7 sheet masks em um pouch com 150 mL de essencia.",
        "product_feature_general",
    ),
    _finding(
        "Desdobre a mascara e encaixe ao redor dos olhos e da boca.",
        "directions_or_usage",
    ),
    _finding(
        "Pressione para tirar o ar preso.",
        "directions_or_usage",
    ),
    _finding(
        "Levante os cortes na regiao das bochechas ao longo da linha do rosto.",
        "directions_or_usage",
    ),
    _finding(
        "Pressione toda a mascara com as palmas das maos.",
        "directions_or_usage",
    ),
    _finding(
        "Apos remover, o fabricante sugere dobrar a folha para dar leves batidinhas/limpeza.",
        "directions_or_usage",
    ),
    _finding(
        "Em seguida, o fabricante indica seguir com emulsao ou creme.",
        "directions_or_usage",
    ),
]


def _attempt6_fields():
    fields = {}
    for index, finding in enumerate(ATTEMPT6_FINDINGS, start=1):
        if finding.source_field != "ai_extracted_candidate":
            continue
        fields[f"copy.pt-BR.v332_fixture_{index:02d}"] = finding.claim_text
    return fields


def _run_v332(findings, fields=None):
    result = ClaimAuditResult(findings=list(findings))
    result = claims_audit._build6r_v332_recover_unique_provenance(
        result,
        fields or {},
    )
    return claims_audit._build6r_v332_reconcile_result(
        result,
        _verified(),
    )


def test_v332_exact_attempt6_fixture_count_and_categories():
    assert len(ATTEMPT6_FINDINGS) == 15
    assert sum(f.claim_category == "product_feature_general" for f in ATTEMPT6_FINDINGS) == 5
    assert sum(f.claim_category == "directions_or_usage" for f in ATTEMPT6_FINDINGS) == 10


def test_v332_all_five_attempt6_product_fixtures_pass():
    repaired = _run_v332(ATTEMPT6_FINDINGS, _attempt6_fields())
    product = [f for f in repaired.findings if f.claim_category == "product_feature_general"]
    assert len(product) == 5
    assert all(f.evidence_status == "SUPPORTED" for f in product)
    assert all(f.allowed_source == "verified_product_facts" for f in product)


def test_v332_all_ten_attempt6_usage_fixtures_pass():
    repaired = _run_v332(ATTEMPT6_FINDINGS, _attempt6_fields())
    usage = [f for f in repaired.findings if f.claim_category == "directions_or_usage"]
    assert len(usage) == 10
    assert all(f.evidence_status == "SUPPORTED" for f in usage)
    assert all(f.allowed_source == "verified_product_facts" for f in usage)


def test_v332_exact_ptbr_morphology_variants_are_bounded_and_supported():
    variants = [ATTEMPT6_FINDINGS[index] for index in (7, 9, 10, 11, 12, 13, 14)]
    fields = {f"copy.pt-BR.variant_{i}": f.claim_text for i, f in enumerate(variants)}
    repaired = _run_v332(variants, fields)
    assert all(f.evidence_status == "SUPPORTED" for f in repaired.findings)


def test_v332_unsupported_quantity_fails_closed():
    finding = _finding(
        "Este pouch tem 7 máscaras embebidas em 200 mL de essência.",
        "product_feature_general",
    )
    repaired = _run_v332([finding], {"copy.pt-BR.caption": finding.claim_text})
    assert repaired.findings[0].evidence_status == "UNSUPPORTED"
    assert "unsupported_quantity_atom" in repaired.findings[0].reason


def test_v332_unsupported_ingredient_residue_fails_closed():
    finding = _finding(
        "Este pouch tem 7 máscaras embebidas em 150 mL de essência e niacinamida.",
        "product_feature_general",
    )
    repaired = _run_v332([finding], {"copy.pt-BR.caption": finding.claim_text})
    assert repaired.findings[0].evidence_status == "UNSUPPORTED"
    assert "unsupported_product_factual_residue" in repaired.findings[0].reason


def test_v332_unsupported_efficacy_claim_fails_closed():
    finding = _finding(
        "Este pouch tem 7 máscaras e garante resultados visíveis.",
        "product_feature_general",
    )
    repaired = _run_v332([finding], {"copy.pt-BR.caption": finding.claim_text})
    assert repaired.findings[0].evidence_status == "UNSUPPORTED"
    assert "blocked_meaning_marker" in repaired.findings[0].reason


def test_v332_unsupported_medical_claim_fails_closed():
    finding = _finding(
        "Este pouch tem 7 máscaras e trata acne.",
        "product_feature_general",
    )
    repaired = _run_v332([finding], {"copy.pt-BR.caption": finding.claim_text})
    assert repaired.findings[0].evidence_status == "UNSUPPORTED"
    assert "blocked_meaning_marker" in repaired.findings[0].reason


def test_v332_unknown_category_remains_fail_closed():
    finding = _finding(
        "Este pouch tem 7 máscaras e 150 mL de essência.",
        "mystery_live_category",
        "copy.pt-BR.caption",
    )
    repaired = _run_v332([finding], {})
    assert repaired.findings[0].evidence_status == "UNSUPPORTED"
    assert repaired.findings[0].reason == "No matching text found."


def test_v332_research_only_provenance_cannot_authorize_claim():
    finding = _finding(
        "Pressione para tirar o ar preso.",
        "directions_or_usage",
    )
    repaired = _run_v332(
        [finding],
        {"research.insight": finding.claim_text},
    )
    assert repaired.findings[0].evidence_status == "UNSUPPORTED"
    assert repaired.findings[0].source_field == "ai_extracted_candidate"
    assert "provenance_unresolved_or_disallowed" in repaired.findings[0].reason


def test_v332_compound_usage_fails_if_any_component_is_unsupported():
    finding = _finding(
        "Pressione para tirar o ar preso e deixe agir por 20 minutos.",
        "directions_or_usage",
    )
    repaired = _run_v332([finding], {"copy.pt-BR.caption": finding.claim_text})
    assert repaired.findings[0].evidence_status == "UNSUPPORTED"
    assert "unsupported_usage_duration_or_frequency" in repaired.findings[0].reason


def test_v332_compound_product_fails_if_unknown_residue_is_added():
    finding = _finding(
        "A LuLuLun Hydra EX é uma máscara facial em tecido (sheet mask) em embalagem tipo pouch com 7 folhas e tecnologia exclusiva.",
        "product_feature_general",
    )
    repaired = _run_v332([finding], {"copy.pt-BR.caption": finding.claim_text})
    assert repaired.findings[0].evidence_status == "UNSUPPORTED"
    assert "unsupported_product_factual_residue" in repaired.findings[0].reason


def test_v332_unique_verbatim_provenance_is_recovered():
    finding = _finding("Pressione para tirar o ar preso.", "directions_or_usage")
    result = claims_audit._build6r_v332_recover_unique_provenance(
        ClaimAuditResult(findings=[finding]),
        {"copy.pt-BR.caption": finding.claim_text},
    )
    assert result.findings[0].source_field == "copy.pt-BR.caption"


def test_v332_absent_provenance_remains_fail_closed():
    finding = _finding("Pressione para tirar o ar preso.", "directions_or_usage")
    repaired = _run_v332([finding], {})
    assert repaired.findings[0].source_field == "ai_extracted_candidate"
    assert repaired.findings[0].evidence_status == "UNSUPPORTED"
    assert "provenance_unresolved_or_disallowed" in repaired.findings[0].reason


def test_v332_ambiguous_provenance_remains_fail_closed():
    finding = _finding("Pressione para tirar o ar preso.", "directions_or_usage")
    repaired = _run_v332(
        [finding],
        {
            "copy.pt-BR.caption": finding.claim_text,
            "creative.creative_brief.template_suggestion": finding.claim_text,
        },
    )
    assert repaired.findings[0].source_field == "ai_extracted_candidate_ambiguous"
    assert repaired.findings[0].evidence_status == "UNSUPPORTED"


def test_v332_original_model_category_is_preserved_separately_from_route():
    finding = _finding("Pressione para tirar o ar preso.", "directions_or_usage")
    repaired = _run_v332([finding], {"copy.pt-BR.caption": finding.claim_text})
    assert repaired.findings[0].claim_category == "directions_or_usage"
    assert "canonical_route=usage_or_dosage_instructions" in repaired.findings[0].reason


def test_v332_failure_diagnostics_retain_route_matcher_source_and_reason():
    finding = _finding(
        "Pressione para tirar o ar preso e deixe agir por 20 minutos.",
        "directions_or_usage",
    )
    repaired = _run_v332([finding], {"copy.pt-BR.caption": finding.claim_text})
    diagnostics = claims_audit.build6r_v332_claim_diagnostics(repaired)
    assert len(diagnostics) == 1
    diagnostic = diagnostics[0]
    assert diagnostic["original_claim_category"] == "directions_or_usage"
    assert diagnostic["canonical_category"] == "usage_or_dosage_instructions"
    assert diagnostic["source_field"] == "copy.pt-BR.caption"
    assert diagnostic["matcher_path"] == "v332_bounded_usage_atoms"
    assert "unsupported_usage_duration_or_frequency" in diagnostic["decision_reason"]


def test_v332_final_augment_wrapper_runs_after_v331_and_recovers_provenance(monkeypatch):
    finding = _finding("Pressione para tirar o ar preso.", "directions_or_usage")

    async def fake_prior(*args, **kwargs):
        return ClaimAuditResult(findings=[finding])

    monkeypatch.setattr(claims_audit, "_build6r_augment_before_v332", fake_prior)

    repaired = asyncio.run(
        claims_audit.augment_with_ai_extraction(
            ai_provider=None,
            fields={"copy.pt-BR.caption": finding.claim_text},
            verified=_verified(),
            brand=None,
            model="zero-cost-test",
            existing=ClaimAuditResult(findings=[]),
        )
    )

    assert repaired.findings[0].source_field == "copy.pt-BR.caption"
    assert repaired.findings[0].evidence_status == "SUPPORTED"


def test_v332_preexisting_supported_finding_is_not_downgraded():
    finding = ClaimFinding(
        claim_text="Pressionar para tirar o ar preso",
        claim_category="directions_or_usage",
        source_field="copy.pt-BR.caption",
        evidence_status="SUPPORTED",
        allowed_source="verified_product_facts",
        reason="preexisting support",
    )
    repaired = claims_audit._build6r_v332_reconcile_result(
        ClaimAuditResult(findings=[finding]),
        _verified(),
    )
    assert repaired.findings[0].evidence_status == "SUPPORTED"
    assert repaired.findings[0].reason == "preexisting support"


def test_v332_does_not_reconcile_existing_v331_category_by_itself():
    finding = _finding(
        "Pressionar para tirar o ar preso",
        "usage_or_dosage_instructions",
        "copy.pt-BR.caption",
    )
    repaired = claims_audit._build6r_v332_reconcile_result(
        ClaimAuditResult(findings=[finding]),
        _verified(),
    )
    # Sealed V3.31 owns this category; direct V3.32 reconciliation does nothing.
    assert repaired.findings[0].evidence_status == "UNSUPPORTED"
    assert repaired.findings[0].reason == "No matching text found."


def test_v332_orchestrator_failure_audit_records_locale_platform_and_diagnostics():
    from pathlib import Path

    orchestrator_path = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "services"
        / "orchestrator.py"
    )
    source = orchestrator_path.read_text(encoding="utf-8")
    marker = '"previsual_semantic_claim_grounding_failed"'
    start = source.index(marker)
    block = source[start:start + 1800]

    assert '"language": language' in block
    assert '"platform": platform' in block
    assert '"claim_diagnostics"' in block
    assert "build6r_v332_claim_diagnostics" in block
