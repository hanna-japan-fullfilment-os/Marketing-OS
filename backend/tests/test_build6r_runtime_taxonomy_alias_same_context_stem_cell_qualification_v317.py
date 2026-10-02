from __future__ import annotations

import asyncio
import inspect
from copy import deepcopy
from types import SimpleNamespace

import pytest

import app.services.claims_audit as claims_audit


BASE_SUPPORTED = {
    1, 2, 4, 5, 6, 7, 8, 9, 10, 11, 13, 14, 15,
}

BASE_UNSUPPORTED = {
    3, 12,
}


LIVE_TARGETS = {
    1: (
        "Versão pouch com 7 máscaras",
        "format_or_quantity",
        "ai_extracted_candidate",
    ),
    2: (
        "Contém 150 mL de essência no pacote",
        "format_or_quantity",
        "ai_extracted_candidate",
    ),
    3: (
        "Contém exossomos derivados de células-tronco mesenquimais "
        "de tecido adiposo humano como ingrediente de condicionamento "
        "da pele",
        "ingredients_or_composition",
        "ai_extracted_candidate",
    ),
    4: (
        "Desdobrar a máscara e ajustar na área dos olhos e da boca",
        "directions_or_how_to_use",
        "ai_extracted_candidate",
    ),
    5: (
        "Pressionar para tirar o ar preso",
        "directions_or_how_to_use",
        "ai_extracted_candidate",
    ),
    6: (
        "Erguer os recortes das bochechas ao longo da linha do rosto",
        "directions_or_how_to_use",
        "ai_extracted_candidate",
    ),
    7: (
        'Depois de remover, o fabricante sugere dobrar a máscara para '
        'usar para "wiping/light patting" (passadas leves) e finalizar '
        "com emulsão ou creme",
        "directions_or_how_to_use",
        "ai_extracted_candidate",
    ),
    8: (
        "O fabricante descreve que pode ser usada de manhã ou à noite "
        "no lugar do toner",
        "directions_or_how_to_use",
        "ai_extracted_candidate",
    ),
    9: (
        "O pouch traz 7 sheet masks e 150 mL de essência, conforme "
        "descrito pelo fabricante",
        "format_or_quantity",
        "creative.creative_brief.tone_notes",
    ),
    10: (
        "O fabricante lista, entre os ingredientes, glutathione, arbutin "
        "e o derivado de vitamina C ascorbyl palmitate",
        "ingredients_or_composition",
        "creative.creative_brief.tone_notes",
    ),
    11: (
        "O fabricante descreve a sheet como ‘Melty Feel Sheet’ e indica "
        "que a fórmula é colorant-free, fragrance-free, mineral-oil-free "
        "e alcohol-free",
        "ingredients_or_composition",
        "creative.creative_brief.tone_notes",
    ),
    12: (
        "Exossomos derivados de células-tronco mesenquimais de tecido "
        "adiposo humano como ingrediente de condicionamento da pele",
        "ingredients_or_composition",
        "ai_extracted_candidate",
    ),
    13: (
        "Com um ponto importante: o próprio fabricante afirma que esse "
        "ingrediente não contém células-tronco",
        "other_factual_claim",
        "copy.pt-BR.caption",
    ),
    14: (
        "7 sheets em um único pouch",
        "format_or_quantity",
        "copy.pt-BR.caption",
    ),
    15: (
        "Pode ser usada de manhã ou à noite no lugar do toner "
        "(conforme descrição do fabricante)",
        "directions_or_how_to_use",
        "copy.pt-BR.caption",
    ),
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
        provenance="manufacturer_official",
    )


def _verified_without_no_stem():
    verified = deepcopy(_verified())

    def strip(value):
        return str(value).replace(
            "manufacturer states stem cells are not contained",
            "",
        )

    verified.verified_claims = [
        strip(value)
        for value in verified.verified_claims
    ]

    verified.verified_ingredients = [
        strip(value)
        for value in verified.verified_ingredients
    ]

    return verified


def _finding(
    index,
    *,
    source_override=None,
    category_override=None,
    text_override=None,
    evidence_status="UNSUPPORTED",
):
    text, category, source = LIVE_TARGETS[index]

    return claims_audit.ClaimFinding(
        claim_text=(
            text
            if text_override is None
            else text_override
        ),
        claim_category=(
            category
            if category_override is None
            else category_override
        ),
        source_field=(
            source
            if source_override is None
            else source_override
        ),
        evidence_status=evidence_status,
        allowed_source="",
        reason="V3.17 live regression target",
    )


def _status(
    index,
    *,
    fields=None,
    verified=None,
    source_override=None,
    category_override=None,
    text_override=None,
):
    result = claims_audit.ClaimAuditResult(
        findings=[
            _finding(
                index,
                source_override=source_override,
                category_override=category_override,
                text_override=text_override,
            )
        ]
    )

    reconciled = (
        claims_audit
        ._build6r_v317_reconcile_runtime_alias_candidates(
            result,
            (
                _verified()
                if verified is None
                else verified
            ),
            fields or {},
        )
    )

    return reconciled.findings[0]


@pytest.mark.parametrize(
    "index",
    sorted(LIVE_TARGETS),
)
def test_v317_exact_15_live_failure_baseline(index):
    finding = _status(index)

    expected = (
        "SUPPORTED"
        if index in BASE_SUPPORTED
        else "UNSUPPORTED"
    )

    assert finding.evidence_status == expected

    if expected == "SUPPORTED":
        assert (
            finding.allowed_source
            == "verified_product_facts"
        )


@pytest.mark.parametrize(
    "kind,value,expected",
    [
        (
            "category",
            "format_or_quantity",
            "product features attributes",
        ),
        (
            "category",
            "directions_or_how_to_use",
            "directions for use",
        ),
        (
            "category",
            "ingredients_or_composition",
            "ingredients percentages",
        ),
        (
            "source",
            "creative.creative_brief.tone_notes",
            True,
        ),
        (
            "source",
            "creative.creative_brief.template_suggestion",
            True,
        ),
        (
            "source",
            "strategy.research_basis[0]",
            False,
        ),
        (
            "clinical",
            "clinical/scientific claims",
            "UNSUPPORTED",
        ),
    ],
)
def test_v317_category_and_source_boundaries(
    kind,
    value,
    expected,
):
    if kind == "category":
        assert (
            claims_audit
            ._build6r_v317_category_alias(
                value
            )
            == expected
        )
        return

    if kind == "source":
        assert (
            claims_audit
            ._build6r_v317_source_field_allowed(
                value
            )
            is expected
        )
        return

    finding = claims_audit.ClaimFinding(
        claim_text="Clinically proven skin transformation",
        claim_category=value,
        source_field="copy.pt-BR.caption",
        evidence_status="UNSUPPORTED",
        allowed_source="",
        reason="generic clinical claim",
    )

    result = claims_audit.ClaimAuditResult(
        findings=[finding]
    )

    reconciled = (
        claims_audit
        ._build6r_v317_reconcile_runtime_alias_candidates(
            result,
            _verified(),
            {},
        )
    )

    assert (
        reconciled.findings[0].evidence_status
        == expected
    )


@pytest.mark.parametrize(
    "scenario,expected",
    [
        ("same_field_unique_ai", "SUPPORTED"),
        ("same_field_direct_source", "SUPPORTED"),
        ("disclaimer_different_field", "UNSUPPORTED"),
        ("ambiguous_two_fields", "UNSUPPORTED"),
        ("no_source_match", "UNSUPPORTED"),
        ("canonical_no_stem_missing", "UNSUPPORTED"),
        ("research_only_context", "UNSUPPORTED"),
        ("same_field_without_disclaimer", "UNSUPPORTED"),
    ],
)
def test_v317_same_context_stem_cell_guard(
    scenario,
    expected,
):
    claim = LIVE_TARGETS[3][0]

    disclaimer = (
        "O fabricante afirma que esse ingrediente "
        "não contém células-tronco."
    )

    source_override = None
    verified = _verified()

    if scenario == "same_field_unique_ai":
        fields = {
            "copy.pt-BR.caption":
                claim + " " + disclaimer,
        }

    elif scenario == "same_field_direct_source":
        source_override = "copy.pt-BR.caption"
        fields = {
            "copy.pt-BR.caption":
                claim + " " + disclaimer,
        }

    elif scenario == "disclaimer_different_field":
        fields = {
            "copy.pt-BR.caption":
                claim,
            "copy.pt-BR.slide_2":
                disclaimer,
        }

    elif scenario == "ambiguous_two_fields":
        fields = {
            "copy.pt-BR.caption":
                claim + " " + disclaimer,
            "copy.pt-BR.slide_2":
                claim + " " + disclaimer,
        }

    elif scenario == "no_source_match":
        fields = {
            "copy.pt-BR.caption":
                "Texto sem o candidato. " + disclaimer,
        }

    elif scenario == "canonical_no_stem_missing":
        fields = {
            "copy.pt-BR.caption":
                claim + " " + disclaimer,
        }

        verified = (
            _verified_without_no_stem()
        )

    elif scenario == "research_only_context":
        fields = {
            "strategy.research_basis[0]":
                claim + " " + disclaimer,
        }

    else:
        fields = {
            "copy.pt-BR.caption":
                claim,
        }

    finding = _status(
        3,
        fields=fields,
        verified=verified,
        source_override=source_override,
    )

    assert finding.evidence_status == expected


@pytest.mark.parametrize(
    "text,category,source",
    [
        (
            "reduz poros e rejuvenesce visivelmente a pele",
            "product benefits/effects",
            "copy.pt-BR.caption",
        ),
        (
            "resultados visíveis garantidos por eficácia superior",
            "efficacy/result",
            "copy.pt-BR.caption",
        ),
        (
            "produto número 1 e bestseller",
            "ranking/bestseller",
            "copy.pt-BR.caption",
        ),
        (
            "o produto mais popular entre consumidoras",
            "popularity",
            "copy.pt-BR.caption",
        ),
        (
            "preço especial de ¥1.980",
            "price",
            "copy.pt-BR.caption",
        ),
        (
            "estoque limitado e disponibilidade por poucos dias",
            "availability/scarcity",
            "copy.pt-BR.caption",
        ),
        (
            "Glutathione 10%",
            "ingredients_or_composition",
            "copy.pt-BR.caption",
        ),
        (
            "Afirmação factual genérica sem vínculo ao contrato permitido",
            "other_factual_claim",
            "copy.pt-BR.caption",
        ),
    ],
)
def test_v317_fail_closed_safety_families(
    text,
    category,
    source,
):
    finding = claims_audit.ClaimFinding(
        claim_text=text,
        claim_category=category,
        source_field=source,
        evidence_status="UNSUPPORTED",
        allowed_source="",
        reason="negative safety case",
    )

    result = claims_audit.ClaimAuditResult(
        findings=[finding]
    )

    reconciled = (
        claims_audit
        ._build6r_v317_reconcile_runtime_alias_candidates(
            result,
            _verified(),
            {},
        )
    )

    assert (
        reconciled.findings[0].evidence_status
        == "UNSUPPORTED"
    )


def test_v317_wrapper_executes_previous_chain_once(monkeypatch):
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
        "_build6r_augment_before_v317",
        previous,
    )

    result = asyncio.run(
        claims_audit.augment_with_ai_extraction(
            None,
            verified=_verified(),
            fields={},
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

    assert supported == BASE_SUPPORTED


def test_v317_wrapper_preserves_historical_contract_markers():
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
    )

    assert all(
        marker in source
        for marker in markers
    )


def test_v317_production_tail_is_product_agnostic_zero_cost():
    source = "\n".join(
        (
            inspect.getsource(
                claims_audit._build6r_v317_source_field_allowed
            ),
            inspect.getsource(
                claims_audit._build6r_v317_category_alias
            ),
            inspect.getsource(
                claims_audit._build6r_v317_same_context_stem_cell_qualified
            ),
            inspect.getsource(
                claims_audit._build6r_v317_candidate_supported
            ),
            inspect.getsource(
                claims_audit._build6r_v317_reconcile_runtime_alias_candidates
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
        "sqlite",
        "sessionlocal",
    )

    assert all(
        token not in source
        for token in forbidden
    )


def test_v317_preserves_existing_supported_and_core_helpers():
    finding = claims_audit.ClaimFinding(
        claim_text="already supported",
        claim_category="format_or_quantity",
        source_field="copy.pt-BR.caption",
        evidence_status="SUPPORTED",
        allowed_source="verified_product_facts",
        reason="existing",
    )

    result = claims_audit.ClaimAuditResult(
        findings=[finding]
    )

    reconciled = (
        claims_audit
        ._build6r_v317_reconcile_runtime_alias_candidates(
            result,
            _verified(),
            {},
        )
    )

    assert (
        reconciled.findings[0].evidence_status
        == "SUPPORTED"
    )
    assert (
        reconciled.findings[0].reason
        == "existing"
    )

    source = "\n".join(
        (
            inspect.getsource(
                claims_audit._build6r_v317_candidate_supported
            ),
            inspect.getsource(
                claims_audit._build6r_v317_reconcile_runtime_alias_candidates
            ),
        )
    )

    assert "def _evaluate(" not in source
    assert "def detect_claims_in_text(" not in source
    assert (
        "def _build6r_recover_semantic_candidate_source_fields("
        not in source
    )
