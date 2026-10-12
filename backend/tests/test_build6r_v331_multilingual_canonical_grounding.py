from __future__ import annotations

import asyncio
from types import SimpleNamespace

from app.schemas.claims_audit import ClaimAuditResult, ClaimFinding
from app.services import claims_audit


def _verified():
    return SimpleNamespace(
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
        verified_claims=[
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
        ],
        verified_usage=(
            "Manufacturer usage guidance: unfold the mask and fit it around "
            "the eyes and mouth, press out trapped air, lift the cheek cut "
            "sections along the face line, then press the whole mask into "
            "place with the palms. After removal, the manufacturer suggests "
            "folding the mask for wiping/light patting and following with an "
            "emulsion or cream. Manufacturer describes it as usable morning "
            "or evening in place of toner."
        ),
    )


def _finding(
    text: str,
    category: str,
    source: str,
    status: str = "UNSUPPORTED",
) -> ClaimFinding:
    return ClaimFinding(
        claim_text=text,
        claim_category=category,
        source_field=source,
        evidence_status=status,
        allowed_source=(
            "verified_product_facts"
            if status == "SUPPORTED"
            else ""
        ),
        reason=(
            "preexisting support"
            if status == "SUPPORTED"
            else "No matching text found."
        ),
    )


ATTEMPT5_FINDINGS = [
    _finding(
        (
            "A f\u00f3rmula traz exossomos derivados de c\u00e9lulas mesenquimais "
            "de tecido adiposo humano como ingrediente de condicionamento "
            "da pele"
        ),
        "ingredients_or_composition",
        "ai_extracted_candidate",
    ),
    _finding(
        (
            "lista de ingredientes explicitamente fornecida pelo fabricante, "
            "incluindo human adipose-derived mesenchymal cell exosomes "
            "(sem c\u00e9lulas-tronco), glutathione, arbutin, derivado de vitamina "
            "C (ascorbyl palmitate), ceramidas (AP, NP), atelocol\u00e1geno, "
            "hydroxypropyltrimonium hyaluronate e human recombinant "
            "oligopeptide-1"
        ),
        "ingredients_or_composition",
        "master_concept.product_category_context",
    ),
    _finding(
        (
            "Modo de uso segundo o fabricante: Desdobrar a m\u00e1scara; Ajustar "
            "ao redor dos olhos e da boca; Pressionar para tirar o ar preso; "
            "Erguer os recortes da bochecha ao longo da linha do rosto; "
            "Pressionar a m\u00e1scara inteira com as palmas das m\u00e3os; Depois de "
            "retirar, dobrar a m\u00e1scara para passar levemente no rosto; "
            "Finalizar com emuls\u00e3o ou creme; O fabricante descreve o uso de "
            "manh\u00e3 ou \u00e0 noite no lugar do t\u00f4nico"
        ),
        "usage_or_dosage_instructions",
        "ai_extracted_candidate",
    ),
    _finding(
        "Pressionar para tirar o ar preso",
        "usage_or_dosage_instructions",
        "copy.pt-BR.caption",
    ),
    _finding(
        "Erguer os recortes da bochecha ao longo da linha do rosto",
        "usage_or_dosage_instructions",
        "copy.pt-BR.caption",
    ),
    _finding(
        "Depois de retirar, dobrar a m\u00e1scara para passar levemente no rosto",
        "usage_or_dosage_instructions",
        "copy.pt-BR.caption",
    ),
    _finding(
        (
            "Uso conforme orienta\u00e7\u00e3o do fabricante: abrir, desdobrar, ajustar "
            "ao redor dos olhos e boca, pressionar para retirar o ar, erguer "
            "os recortes das bochechas na linha do rosto e pressionar com as "
            "palmas. Ap\u00f3s remover, usar o mask dobrado para leve batidinha ou "
            "'wipe' e finalizar com emuls\u00e3o ou creme. Pode ser usado pela "
            "manh\u00e3 ou \u00e0 noite no lugar do t\u00f4nico, conforme o fabricante."
        ),
        "usage_or_dosage_instructions",
        "creative.creative_brief.template_suggestion",
    ),
]


def test_v331_reconciles_all_seven_attempt5_false_negatives():
    result = ClaimAuditResult(
        findings=ATTEMPT5_FINDINGS
    )

    repaired = (
        claims_audit._build6r_v331_reconcile_result(
            result,
            _verified(),
        )
    )

    assert len(repaired.findings) == 7
    assert all(
        finding.evidence_status == "SUPPORTED"
        for finding in repaired.findings
    )
    assert all(
        finding.allowed_source == "verified_product_facts"
        for finding in repaired.findings
    )

    assert repaired.findings[0].source_field == "ai_extracted_candidate"
    assert repaired.findings[2].source_field == "ai_extracted_candidate"


def test_v331_unknown_extra_ingredient_remains_fail_closed():
    result = ClaimAuditResult(
        findings=[
            _finding(
                (
                    "A f\u00f3rmula cont\u00e9m glutathione, arbutin e niacinamide"
                ),
                "ingredients_or_composition",
                "master_concept.product_category_context",
            )
        ]
    )

    repaired = (
        claims_audit._build6r_v331_reconcile_result(
            result,
            _verified(),
        )
    )

    assert repaired.findings[0].evidence_status == "UNSUPPORTED"


def test_v331_unknown_extra_usage_step_remains_fail_closed():
    result = ClaimAuditResult(
        findings=[
            _finding(
                (
                    "Pressionar para tirar o ar preso e deixar agir por "
                    "20 minutos"
                ),
                "usage_or_dosage_instructions",
                "copy.pt-BR.caption",
            )
        ]
    )

    repaired = (
        claims_audit._build6r_v331_reconcile_result(
            result,
            _verified(),
        )
    )

    assert repaired.findings[0].evidence_status == "UNSUPPORTED"


def test_v331_research_only_fact_cannot_become_evidence():
    result = ClaimAuditResult(
        findings=[
            _finding(
                "A f\u00f3rmula cont\u00e9m bakuchiol",
                "ingredients_or_composition",
                "ai_extracted_candidate",
            )
        ]
    )

    repaired = (
        claims_audit._build6r_v331_reconcile_result(
            result,
            _verified(),
        )
    )

    assert repaired.findings[0].evidence_status == "UNSUPPORTED"


def test_v331_efficacy_and_results_categories_are_never_reconciled():
    result = ClaimAuditResult(
        findings=[
            _finding(
                "reduz rugas visivelmente",
                "product_benefit",
                "copy.pt-BR.caption",
            ),
            _finding(
                "resultado cl\u00ednico comprovado",
                "clinical_scientific",
                "ai_extracted_candidate",
            ),
        ]
    )

    repaired = (
        claims_audit._build6r_v331_reconcile_result(
            result,
            _verified(),
        )
    )

    assert all(
        finding.evidence_status == "UNSUPPORTED"
        for finding in repaired.findings
    )


def test_v331_exosome_stem_cell_meaning_remains_fail_closed():
    result = ClaimAuditResult(
        findings=[
            _finding(
                "A f\u00f3rmula cont\u00e9m c\u00e9lulas-tronco humanas",
                "ingredients_or_composition",
                "ai_extracted_candidate",
            ),
            _finding(
                "Os exossomos regeneram a pele",
                "ingredients_or_composition",
                "ai_extracted_candidate",
            ),
        ]
    )

    repaired = (
        claims_audit._build6r_v331_reconcile_result(
            result,
            _verified(),
        )
    )

    assert all(
        finding.evidence_status == "UNSUPPORTED"
        for finding in repaired.findings
    )


def test_v331_exact_preexisting_support_is_unchanged():
    original = _finding(
        "Glutathione",
        "ingredients_or_composition",
        "copy.pt-BR.caption",
        status="SUPPORTED",
    )

    result = ClaimAuditResult(
        findings=[original]
    )

    repaired = (
        claims_audit._build6r_v331_reconcile_result(
            result,
            _verified(),
        )
    )

    assert repaired.findings[0].evidence_status == "SUPPORTED"
    assert repaired.findings[0].reason == "preexisting support"


def test_v331_final_augment_wrapper_runs_after_all_prior_layers(monkeypatch):
    base = ClaimAuditResult(
        findings=[
            _finding(
                "Pressionar para tirar o ar preso",
                "usage_or_dosage_instructions",
                "copy.pt-BR.caption",
            )
        ]
    )

    async def fake_prior(*args, **kwargs):
        return base

    monkeypatch.setattr(
        claims_audit,
        "_build6r_augment_before_v331",
        fake_prior,
    )

    repaired = asyncio.run(
        claims_audit.augment_with_ai_extraction(
            ai_provider=None,
            fields={
                "copy.pt-BR.caption":
                    "Pressionar para tirar o ar preso"
            },
            verified=_verified(),
            brand=None,
            model="zero-cost-test",
            existing=ClaimAuditResult(
                findings=[]
            ),
        )
    )

    assert repaired.findings[0].evidence_status == "SUPPORTED"


def test_v331_source_scope_does_not_expand_to_unapproved_fields():
    result = ClaimAuditResult(
        findings=[
            _finding(
                "Pressionar para tirar o ar preso",
                "usage_or_dosage_instructions",
                "research.insight",
            )
        ]
    )

    repaired = (
        claims_audit._build6r_v331_reconcile_result(
            result,
            _verified(),
        )
    )

    assert repaired.findings[0].evidence_status == "UNSUPPORTED"