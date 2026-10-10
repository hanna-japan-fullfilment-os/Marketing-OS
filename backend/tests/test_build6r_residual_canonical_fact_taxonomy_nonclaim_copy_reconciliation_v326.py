from __future__ import annotations

import asyncio
import inspect
from types import SimpleNamespace

import pytest

from app.services import claims_audit
from app.services import orchestrator
from app.services.prompt_registry import PROMPT_VERSIONS


def _verified():
    return SimpleNamespace(
        verified_name="LuLuLun Hydra EX Mask 7 Sheets",
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
        verified_variant="Face Mask LuLuLun EX 1FS - 7-sheet pouch",
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
        prohibited_claims=["Do not use research as product-fact evidence"],
    )


def _finding(text, category, source="ai_extracted_candidate"):
    return claims_audit.ClaimFinding(
        claim_text=text,
        claim_category=category,
        source_field=source,
        evidence_status="UNSUPPORTED",
        allowed_source="",
        reason="post-v325-live-finding",
    )


LIVE_11 = [
    ("Versão em pouch com 7 máscaras.", "product_quantity_or_size", "ai_extracted_candidate", "SUPPORTED"),
    ("Contém 150 mL de essência dentro da embalagem.", "product_quantity_or_size", "ai_extracted_candidate", "SUPPORTED"),
    ("Fórmula sem corantes adicionados.", "free_from_or_without", "ai_extracted_candidate", "SUPPORTED"),
    ("Categoria: máscara facial em tecido (sheet mask).", "product_category_context", "copy.pt-BR.caption", "SUPPORTED"),
    ("Variante: pouch com 7 máscaras, com 150 mL de essência no total.", "product_quantity_or_size", "copy.pt-BR.caption", "SUPPORTED"),
    ("Ingredientes listados pelo fabricante (seleção):", "ingredients_or_composition", "copy.pt-BR.caption", "DROP_STRUCTURAL"),
    ("Sheet mask não é tudo igual.", "comparative_or_superlative_claim", "ai_extracted_candidate", "UNSUPPORTED"),
    ("LuLuLun Hydra EX Mask 7 Sheets, variante 7-sheet pouch contendo 150 mL de essência.", "product_quantity_or_size", "master_concept.must_include[1]", "SUPPORTED"),
    ("o pacote contém 7 máscaras faciais em folha e 150 mL de essência.", "product_quantity_or_size", "ai_extracted_candidate", "SUPPORTED"),
    ("O pouch 7-sheet é o centro da composição, em escala realista, com sombras credíveis e leve reflexão para reforçar a sensação de produto físico.", "visual_presentation_or_packaging", "master_concept.visual_identity", "DROP_VISUAL"),
    ("Hero is the exact 7-sheet pouch as supplied in the owner photo – preserve true proportions, logo, colors, printed typography and all visible details.", "visual_presentation_or_packaging", "creative.creative_brief.visual_prompt", "DROP_VISUAL"),
]


@pytest.mark.parametrize(
    ("text", "category", "source"),
    [
        (text, category, source)
        for text, category, source, disposition in LIVE_11
        if disposition == "SUPPORTED"
    ],
)
def test_v326_exact_live_supported_facts_reconcile(text, category, source):
    assert claims_audit._build6r_v326_candidate_supported(
        _finding(text, category, source),
        _verified(),
        {},
    )


def test_v326_exact_structural_heading_is_nonclaim():
    assert claims_audit._build6r_v326_structural_nonclaim_label(
        _finding(
            "Ingredientes listados pelo fabricante (seleção):",
            "ingredients_or_composition",
            "copy.pt-BR.caption",
        )
    )


@pytest.mark.parametrize(
    "text",
    [
        "Ingredientes listados pelo fabricante: retinol milagroso",
        "Ingredientes premium listados pelo fabricante:",
        "Ingredientes listados pelo fabricante para rejuvenescimento:",
        "Ingredientes listados pelo fabricante – somente no Japão:",
        "Ingredientes listados pelo fabricante: 10 ativos",
    ],
)
def test_v326_structural_heading_cannot_hide_factual_residue(text):
    assert not claims_audit._build6r_v326_structural_nonclaim_label(
        _finding(
            text,
            "ingredients_or_composition",
            "copy.pt-BR.caption",
        )
    )


def test_v326_live_comparative_remains_fail_closed():
    assert not claims_audit._build6r_v326_candidate_supported(
        _finding(
            "Sheet mask não é tudo igual.",
            "comparative_or_superlative_claim",
        ),
        _verified(),
        {},
    )


@pytest.mark.parametrize(
    ("text", "source"),
    [
        (
            "O pouch 7-sheet é o centro da composição, em escala realista, com sombras credíveis e leve reflexão para reforçar a sensação de produto físico.",
            "master_concept.visual_identity",
        ),
        (
            "Hero is the exact 7-sheet pouch as supplied in the owner photo – preserve true proportions, logo, colors, printed typography and all visible details.",
            "creative.creative_brief.visual_prompt",
        ),
    ],
)
def test_v326_live_visual_directives_require_canonical_residue(text, source):
    assert claims_audit._build6r_v326_visual_directive_with_canonical_residue(
        _finding(
            text,
            "visual_presentation_or_packaging",
            source,
        ),
        _verified(),
    )


@pytest.mark.parametrize(
    "text",
    [
        "Hero is the bestselling 7-sheet pouch at the center.",
        "Hero is the limited-stock 7-sheet pouch at the center.",
        "Hero is the clinically superior 7-sheet pouch at the center.",
        "Hero is the 8-sheet pouch at the center.",
        "Hero is the 7-sheet pouch that visibly reduces lines at the center.",
        "Hero is the 7-sheet pouch made in Japan at the center.",
        "Hero is the 7-sheet pouch priced at 1990 yen at the center.",
    ],
)
def test_v326_visual_never_launders_unsupported_fact(text):
    assert not claims_audit._build6r_v326_visual_directive_with_canonical_residue(
        _finding(
            text,
            "visual_presentation_or_packaging",
            "creative.creative_brief.visual_prompt",
        ),
        _verified(),
    )


def test_v326_exact_11_corpus_leaves_one_intentional_hard_fail():
    findings = [
        _finding(text, category, source)
        for text, category, source, _disposition in LIVE_11
    ]
    result = claims_audit.ClaimAuditResult(findings=findings)

    reconciled = claims_audit._build6r_v326_reconcile_residual_taxonomy_and_nonclaims(
        result,
        _verified(),
        {},
    )

    assert len(reconciled.findings) == 8

    supported = [
        finding
        for finding in reconciled.findings
        if finding.evidence_status == "SUPPORTED"
    ]
    unsupported = [
        finding
        for finding in reconciled.findings
        if finding.evidence_status == "UNSUPPORTED"
    ]

    assert len(supported) == 7
    assert len(unsupported) == 1
    assert all(
        finding.allowed_source == "verified_product_facts"
        for finding in supported
    )
    assert unsupported[0].claim_category == "comparative_or_superlative_claim"
    assert unsupported[0].claim_text == "Sheet mask não é tudo igual."

    assert not any(
        finding.claim_text
        == "Ingredientes listados pelo fabricante (seleção):"
        for finding in reconciled.findings
    )
    assert not any(
        finding.claim_category == "visual_presentation_or_packaging"
        for finding in reconciled.findings
    )


@pytest.mark.parametrize(
    ("text", "category"),
    [
        ("Versão em pouch com 8 máscaras.", "product_quantity_or_size"),
        ("Contém 200 mL de essência.", "product_quantity_or_size"),
        ("Fórmula sem corantes adicionados e clinicamente superior.", "free_from_or_without"),
        ("Categoria: máscara facial em tecido mais eficaz.", "product_category_context"),
        ("Ingredientes listados pelo fabricante: retinol milagroso.", "ingredients_or_composition"),
    ],
)
def test_v326_aliasing_never_becomes_evidence(text, category):
    assert not claims_audit._build6r_v326_candidate_supported(
        _finding(text, category),
        _verified(),
        {},
    )


def test_v326_research_source_remains_ineligible():
    assert not claims_audit._build6r_v326_candidate_supported(
        _finding(
            "Versão em pouch com 7 máscaras.",
            "product_quantity_or_size",
            "strategy.research_basis[0]",
        ),
        _verified(),
        {},
    )


def test_v326_stem_exosome_residual_remains_fail_closed():
    assert not claims_audit._build6r_v326_candidate_supported(
        _finding(
            "Contém human adipose-derived mesenchymal cell exosomes como ingrediente de condicionamento da pele.",
            "ingredients_or_composition",
        ),
        _verified(),
        {},
    )


def test_v326_cross_product_routing_is_product_agnostic():
    verified = SimpleNamespace(
        verified_name="Example Facial Mask 5 Sheets",
        verified_description="Facial sheet mask in an exact 5-sheet pouch.",
        verified_ingredients=["Glycerin"],
        verified_features=[
            "5-sheet pouch",
            "Contains 100 mL of essence",
            "Colorant-free",
        ],
        verified_benefits=[],
        verified_usage="",
        verified_size="5 sheets / 100 mL",
        verified_variant="5-sheet pouch",
        verified_price="",
        verified_availability="",
        verified_country_of_origin="",
        verified_claims=[
            "5-sheet pouch containing 100 mL of essence",
            "Manufacturer states the formula is colorant-free",
        ],
        prohibited_claims=[],
    )

    assert claims_audit._build6r_v326_candidate_supported(
        _finding(
            "Pouch com 5 máscaras e 100 mL.",
            "product_quantity_or_size",
        ),
        verified,
        {},
    )
    assert claims_audit._build6r_v326_candidate_supported(
        _finding(
            "Fórmula sem corantes.",
            "free_from_or_without",
        ),
        verified,
        {},
    )
    assert not claims_audit._build6r_v326_candidate_supported(
        _finding(
            "Pouch com 6 máscaras e 100 mL.",
            "product_quantity_or_size",
        ),
        verified,
        {},
    )


def test_v326_shared_prompt_blocks_unverified_comparison():
    text = orchestrator._claims_boundary_instruction().lower()
    assert "v3.26 comparative boundary" in text
    assert "not all x are equal" in text
    assert "x nao e tudo igual" in text
    assert "verified comparison" in text
    assert "neutral descriptive wording" in text


def test_v326_prompt_versions_are_traceable():
    assert PROMPT_VERSIONS["campaign_copy"].version == "1.6.0"
    assert PROMPT_VERSIONS["carousel_plan"].version == "1.6.0"
    assert PROMPT_VERSIONS["master_campaign_concept"].version == "1.7.0"
    assert "creative_brief" not in PROMPT_VERSIONS


def test_v326_is_append_only_after_v325():
    assert claims_audit._build6r_augment_before_v326 is not claims_audit.augment_with_ai_extraction


def test_v326_wrapper_preserves_contract_markers():
    source = inspect.getsource(claims_audit.augment_with_ai_extraction)
    for marker in (
        "_build6r_augment_before_v324",
        "_build6r_v324_reconcile_residual_canonical_semantic_atoms",
        "_build6r_augment_before_v325",
        "_build6r_v325_reconcile_bounded_usage_and_nonfactual_directives",
        "_build6r_augment_before_v326",
        "_build6r_v326_reconcile_residual_taxonomy_and_nonclaims",
    ):
        assert marker in source


def test_v326_wrapper_executes_v325_chain_once(monkeypatch):
    calls = {"previous": 0}

    async def fake_previous(*args, **kwargs):
        calls["previous"] += 1
        return claims_audit.ClaimAuditResult(findings=[])

    monkeypatch.setattr(
        claims_audit,
        "_build6r_augment_before_v326",
        fake_previous,
    )

    result = asyncio.run(
        claims_audit.augment_with_ai_extraction(
            verified=_verified(),
            fields={},
        )
    )

    assert calls["previous"] == 1
    assert result.findings == []


def test_v326_production_is_zero_cost_product_agnostic_no_fuzzy():
    functions = (
        claims_audit._build6r_v326_live_category_alias,
        claims_audit._build6r_v326_clone,
        claims_audit._build6r_v326_structural_nonclaim_label,
        claims_audit._build6r_v326_product_category_context_supported,
        claims_audit._build6r_v326_visual_directive_with_canonical_residue,
        claims_audit._build6r_v326_candidate_supported,
        claims_audit._build6r_v326_reconcile_residual_taxonomy_and_nonclaims,
        claims_audit.augment_with_ai_extraction,
    )

    source = "\n".join(
        inspect.getsource(function)
        for function in functions
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

    assert all(token not in source for token in forbidden)

# =====================================================================
# BUILD6R_V326_TARGETED_DEDICATED_QA_REPAIR_TESTS_V1
# =====================================================================

def test_v326_repair_quantity_complete_residue_blocks_extra_fact():
    assert not claims_audit._build6r_v326_candidate_supported(
        _finding(
            "Contém 150 mL de essência dentro da embalagem com retinol.",
            "product_quantity_or_size",
        ),
        _verified(),
        {},
    )


def test_v326_repair_quantity_requires_every_number_to_have_supported_unit_atom():
    assert not claims_audit._build6r_v326_candidate_supported(
        _finding(
            "Pouch com 7 máscaras, 150 mL de essência e 20.",
            "product_quantity_or_size",
        ),
        _verified(),
        {},
    )


def test_v326_repair_single_free_from_requires_canonical_atom():
    verified = _verified()
    verified.verified_features = [
        item
        for item in verified.verified_features
        if item != "Colorant-free"
    ]
    verified.verified_claims = [
        item
        for item in verified.verified_claims
        if "colorant-free" not in item
    ]

    assert not claims_audit._build6r_v326_candidate_supported(
        _finding(
            "Fórmula sem corantes adicionados.",
            "free_from_or_without",
        ),
        verified,
        {},
    )


def test_v326_repair_single_free_from_complete_residue_blocks_hidden_ingredient():
    assert not claims_audit._build6r_v326_candidate_supported(
        _finding(
            "Fórmula sem corantes e retinol.",
            "free_from_or_without",
        ),
        _verified(),
        {},
    )


def test_v326_repair_visual_portuguese_credible_token_is_layout_only():
    assert claims_audit._build6r_v326_visual_directive_with_canonical_residue(
        _finding(
            "O pouch 7-sheet é o centro da composição, em escala realista, "
            "com sombras credíveis e leve reflexão para reforçar a sensação "
            "de produto físico.",
            "visual_presentation_or_packaging",
            "master_concept.visual_identity",
        ),
        _verified(),
    )


def test_v326_repair_helpers_are_product_agnostic_zero_cost():
    import inspect

    functions = (
        claims_audit._build6r_v326_structure_families_supported,
        claims_audit._build6r_v326_quantity_taxonomy_supported,
        claims_audit._build6r_v326_single_free_from_supported,
        claims_audit._build6r_v326_visual_directive_with_canonical_residue,
        claims_audit._build6r_v326_candidate_supported,
    )

    source = "\n".join(
        inspect.getsource(function)
        for function in functions
    ).lower()

    forbidden = (
        "lululun",
        "hanna-japan",
        "campaign_id",
        "product_id",
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
