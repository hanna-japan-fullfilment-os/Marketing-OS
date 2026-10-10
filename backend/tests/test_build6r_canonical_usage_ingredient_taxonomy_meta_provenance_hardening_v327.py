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
        provenance="manufacturer_official+owner_confirmed",
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
        reason="post-v326-live-finding",
    )


LIVE_12 = [
    (
        "Aqui a ideia não é prometer resultado, e sim mostrar que esses nomes "
        "realmente constam na lista de ingredientes da Hydra EX.",
        "ingredients",
        "ai_extracted_candidate",
        "UNSUPPORTED",
    ),
    (
        "As instruções oficiais do fabricante para essa máscara são: "
        "1. Desdobrar a máscara. 2. Ajustar ao redor dos olhos e da boca. "
        "3. Pressionar para tirar o ar preso. 4. Puxar os cortes na região "
        "das bochechas ao longo da linha do rosto. 5. Pressionar toda a "
        "máscara no rosto com as palmas das mãos.",
        "instructions_or_directions",
        "ai_extracted_candidate",
        "SUPPORTED_USAGE",
    ),
    (
        "Depois de remover, o fabricante sugere: - dobrar a máscara usada "
        "para passar no rosto (como um leve “wiping/patting”) - em seguida, "
        "usar um emulsão ou creme.",
        "instructions_or_directions",
        "ai_extracted_candidate",
        "SUPPORTED_USAGE",
    ),
    (
        "O fabricante também descreve essa máscara como algo que pode ser "
        "usado de manhã ou à noite, no lugar do tônico.",
        "instructions_or_directions",
        "ai_extracted_candidate",
        "SUPPORTED_USAGE",
    ),
    (
        "Tudo acima vem diretamente das informações do fabricante para a "
        "LuLuLun Hydra EX 7-sheet pouch.",
        "endorsement_or_testimonial",
        "ai_extracted_candidate",
        "UNSUPPORTED",
    ),
    (
        "O fabricante também informa a presença de: • Glutationa • Arbutin "
        "• Ascorbyl palmitate (derivado de vitamina C) • Ceramide AP "
        "• Ceramide NP • Atelocollagen • Hydroxypropyltrimonium hyaluronate "
        "• Human recombinant oligopeptide-1 (EGF)",
        "ingredients",
        "ai_extracted_candidate",
        "SUPPORTED_INGREDIENT",
    ),
    (
        "A ideia desse carrossel é só te mostrar que esses nomes realmente "
        "constam como ingredientes da LuLuLun Hydra EX 7-sheet pouch — sem "
        "completar com benefícios que a gente não tem verificados para o Brasil.",
        "ingredients",
        "copy.pt-BR.caption",
        "UNSUPPORTED",
    ),
    (
        "Passo a passo oficial: 1. Desdobrar a máscara. 2. Ajustar ao redor "
        "dos olhos e da boca. 3. Pressionar pra tirar o ar preso. 4. Puxar "
        "os recortes das bochechas ao longo da linha do rosto. 5. Pressionar "
        "a máscara inteira no rosto com as palmas das mãos.",
        "instructions_or_directions",
        "ai_extracted_candidate",
        "SUPPORTED_USAGE",
    ),
    (
        "Depois de tirar, o fabricante sugere: • dobrar a folha usada pra "
        "passar/wiping no rosto • finalizar com emulsão ou creme.",
        "instructions_or_directions",
        "ai_extracted_candidate",
        "SUPPORTED_USAGE",
    ),
    (
        "o fabricante descreve essa máscara como utilizável de manhã ou à "
        "noite, no lugar do tônico.",
        "instructions_or_directions",
        "copy.pt-BR.caption",
        "SUPPORTED_USAGE",
    ),
    (
        "*Fabricante indica que este ingrediente não contém células-tronco.",
        "ingredients",
        "creative.creative_brief.visual_prompt",
        "UNSUPPORTED",
    ),
    (
        "Conteúdo desta peça limitado às informações verificadas fornecidas "
        "pelo fabricante para a LuLuLun Hydra EX 7 Sheets.",
        "endorsement_or_testimonial",
        "creative.creative_brief.visual_prompt",
        "UNSUPPORTED",
    ),
]


@pytest.mark.parametrize(
    ("text", "category", "source"),
    [
        (text, category, source)
        for text, category, source, disposition in LIVE_12
        if disposition == "SUPPORTED_USAGE"
    ],
)
def test_v327_exact_live_usage_findings_reconcile(text, category, source):
    assert claims_audit._build6r_v327_candidate_supported(
        _finding(text, category, source),
        _verified(),
        {},
    )


def test_v327_exact_live_explicit_ingredient_list_reconciles():
    text, category, source, _ = LIVE_12[5]
    assert claims_audit._build6r_v327_candidate_supported(
        _finding(text, category, source),
        _verified(),
        {},
    )


@pytest.mark.parametrize(
    ("text", "category", "source"),
    [
        (text, category, source)
        for text, category, source, disposition in LIVE_12
        if disposition == "UNSUPPORTED"
    ],
)
def test_v327_exact_live_context_and_meta_findings_remain_unsupported(
    text,
    category,
    source,
):
    assert not claims_audit._build6r_v327_candidate_supported(
        _finding(text, category, source),
        _verified(),
        {},
    )


def test_v327_exact_12_corpus_finishes_7_supported_5_unsupported():
    findings = [
        _finding(text, category, source)
        for text, category, source, _disposition in LIVE_12
    ]
    result = claims_audit.ClaimAuditResult(findings=findings)

    reconciled = (
        claims_audit._build6r_v327_reconcile_usage_ingredients_and_meta_provenance(
            result,
            _verified(),
            {},
        )
    )

    assert len(reconciled.findings) == 12

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
    assert len(unsupported) == 5
    assert all(
        finding.allowed_source == "verified_product_facts"
        for finding in supported
    )

    assert sum(
        finding.claim_category == "instructions_or_directions"
        for finding in supported
    ) == 6
    assert sum(
        finding.claim_category == "ingredients"
        for finding in supported
    ) == 1


def test_v327_taxonomy_alias_alone_is_never_evidence():
    assert not claims_audit._build6r_v327_candidate_supported(
        _finding(
            "Use conforme instruções.",
            "instructions_or_directions",
        ),
        _verified(),
        {},
    )


def test_v327_usage_requires_verified_usage():
    verified = _verified()
    verified.verified_usage = ""

    assert not claims_audit._build6r_v327_candidate_supported(
        _finding(
            "Desdobrar a máscara e ajustar ao redor dos olhos e da boca.",
            "instructions_or_directions",
        ),
        verified,
        {},
    )


@pytest.mark.parametrize(
    "text",
    [
        (
            "Desdobrar a máscara, ajustar ao redor dos olhos e da boca e "
            "massagear o rosto depois."
        ),
        (
            "Desdobrar a máscara e deixar por 10 minutos."
        ),
        (
            "Usar a máscara diariamente de manhã ou à noite no lugar do tônico."
        ),
        (
            "Usar de manhã ou à noite no lugar do tônico para hidratar profundamente."
        ),
    ],
)
def test_v327_usage_extra_unverified_residue_fails(text):
    assert not claims_audit._build6r_v327_candidate_supported(
        _finding(
            text,
            "instructions_or_directions",
        ),
        _verified(),
        {},
    )


def test_v327_invented_numbered_cleanse_mask_cream_routine_remains_blocked():
    assert not claims_audit._build6r_v327_candidate_supported(
        _finding(
            "Passos: 1 limpeza 2 máscara 3 emulsão ou creme.",
            "instructions_or_directions",
        ),
        _verified(),
        {},
    )


def test_v327_every_explicit_ingredient_must_be_canonical():
    assert claims_audit._build6r_v327_candidate_supported(
        _finding(
            "Ingredientes: • Glutationa • Arbutin • Ceramide NP",
            "ingredients",
        ),
        _verified(),
        {},
    )

    assert not claims_audit._build6r_v327_candidate_supported(
        _finding(
            "Ingredientes: • Glutationa • Arbutin • Retinol",
            "ingredients",
        ),
        _verified(),
        {},
    )


@pytest.mark.parametrize(
    "text",
    [
        "Esses nomes constam na lista de ingredientes.",
        "Estes nomes são ingredientes verificados.",
    ],
)
def test_v327_ingredient_deictic_names_remain_unsupported(text):
    assert not claims_audit._build6r_v327_candidate_supported(
        _finding(text, "ingredients"),
        _verified(),
        {},
    )


def test_v327_this_ingredient_stem_reference_remains_unsupported():
    assert not claims_audit._build6r_v327_candidate_supported(
        _finding(
            "Este ingrediente não contém células-tronco.",
            "ingredients",
        ),
        _verified(),
        {},
    )


def test_v327_stem_exosome_same_field_safety_is_not_bypassed():
    assert not claims_audit._build6r_v327_candidate_supported(
        _finding(
            "Ingredientes: • Human adipose-derived mesenchymal cell exosomes",
            "ingredients",
        ),
        _verified(),
        {},
    )

    assert claims_audit._build6r_v322_same_source_stem_cell_qualified(
        _finding(
            "Human adipose-derived mesenchymal cell exosomes; "
            "manufacturer states stem cells are not contained.",
            "ingredients/contents",
        ),
        _verified(),
        {},
    )


@pytest.mark.parametrize(
    "text",
    [
        "Tudo acima vem diretamente das informações do fabricante.",
        "Conteúdo limitado às informações verificadas fornecidas pelo fabricante.",
    ],
)
def test_v327_meta_manufacturer_provenance_remains_unsupported(text):
    assert not claims_audit._build6r_v327_candidate_supported(
        _finding(
            text,
            "endorsement_or_testimonial",
        ),
        _verified(),
        {},
    )


def test_v327_endorsement_or_testimonial_is_not_aliased():
    assert not claims_audit._build6r_v327_candidate_supported(
        _finding(
            "Informação do fabricante.",
            "endorsement_or_testimonial",
        ),
        _verified(),
        {},
    )


def test_v327_research_source_remains_ineligible():
    assert not claims_audit._build6r_v327_candidate_supported(
        _finding(
            "Ingredientes: • Glutationa • Arbutin • Ceramide NP",
            "ingredients",
            "strategy.research_basis[0]",
        ),
        _verified(),
        {},
    )


@pytest.mark.parametrize(
    ("text", "category"),
    [
        (
            "Usar de manhã ou à noite no lugar do tônico para resultados superiores.",
            "instructions_or_directions",
        ),
        (
            "Usar de manhã ou à noite no lugar do tônico por ¥1.990.",
            "instructions_or_directions",
        ),
        (
            "Usar de manhã ou à noite no lugar do tônico enquanto houver estoque.",
            "instructions_or_directions",
        ),
        (
            "Ingredientes premium do Japão: • Glutationa • Arbutin",
            "ingredients",
        ),
        (
            "Ingredientes mais populares: • Glutationa • Arbutin",
            "ingredients",
        ),
    ],
)
def test_v327_existing_fail_closed_commercial_and_positioning_boundaries_hold(
    text,
    category,
):
    assert not claims_audit._build6r_v327_candidate_supported(
        _finding(text, category),
        _verified(),
        {},
    )


def test_v327_bounded_pt_en_normalization_is_product_agnostic():
    verified = SimpleNamespace(
        verified_name="Example Sheet Mask",
        verified_description="Example facial sheet mask.",
        provenance="manufacturer_official",
        verified_ingredients=[
            "Glutathione",
            "Niacinamide",
            "Ceramide NP",
        ],
        verified_features=[],
        verified_benefits=[],
        verified_usage=(
            "Manufacturer usage guidance: unfold the mask and fit it around "
            "the eyes and mouth. Manufacturer describes it as usable morning "
            "or evening in place of toner."
        ),
        verified_size="",
        verified_variant="",
        verified_price="",
        verified_availability="",
        verified_country_of_origin="",
        verified_claims=[],
        prohibited_claims=[],
    )

    assert claims_audit._build6r_v327_candidate_supported(
        _finding(
            "Ingredientes: • Glutationa • Niacinamide • Ceramide NP",
            "ingredients",
        ),
        verified,
        {},
    )

    assert claims_audit._build6r_v327_candidate_supported(
        _finding(
            "Desdobrar a máscara e ajustar ao redor dos olhos e da boca.",
            "instructions_or_directions",
        ),
        verified,
        {},
    )

    assert not claims_audit._build6r_v327_candidate_supported(
        _finding(
            "Ingredientes: • Glutationa • Niacinamide • Retinol",
            "ingredients",
        ),
        verified,
        {},
    )


def test_v327_shared_prompt_hardens_deictic_meta_and_explicit_fact_wording():
    text = orchestrator._claims_boundary_instruction().lower()
    assert "v3.27 explicit-fact reference boundary" in text
    assert "esses nomes" in text
    assert "este ingrediente" in text
    assert "tudo acima" in text
    assert "meta-provenance" in text
    assert "same generated field" in text


def test_v327_prompt_versions_are_traceable():
    assert PROMPT_VERSIONS["campaign_copy"].version == "1.6.0"
    assert PROMPT_VERSIONS["carousel_plan"].version == "1.6.0"
    assert PROMPT_VERSIONS["master_campaign_concept"].version == "1.7.0"
    assert "creative_brief" not in PROMPT_VERSIONS


def test_v327_is_append_only_after_v326():
    assert (
        claims_audit._build6r_augment_before_v327
        is not claims_audit.augment_with_ai_extraction
    )


def test_v327_wrapper_preserves_contract_markers():
    source = inspect.getsource(
        claims_audit.augment_with_ai_extraction
    )
    for marker in (
        "_build6r_augment_before_v325",
        "_build6r_v325_reconcile_bounded_usage_and_nonfactual_directives",
        "_build6r_augment_before_v326",
        "_build6r_v326_reconcile_residual_taxonomy_and_nonclaims",
        "_build6r_augment_before_v327",
        "_build6r_v327_reconcile_usage_ingredients_and_meta_provenance",
    ):
        assert marker in source


def test_v327_wrapper_executes_v326_chain_once(monkeypatch):
    calls = {"previous": 0}

    async def fake_previous(*args, **kwargs):
        calls["previous"] += 1
        return claims_audit.ClaimAuditResult(findings=[])

    monkeypatch.setattr(
        claims_audit,
        "_build6r_augment_before_v327",
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


def test_v327_production_is_zero_cost_product_agnostic_no_fuzzy():
    functions = (
        claims_audit._build6r_v327_clone,
        claims_audit._build6r_v327_has_deictic_or_meta_provenance_language,
        claims_audit._build6r_v327_phrase_present,
        claims_audit._build6r_v327_usage_alias_groups,
        claims_audit._build6r_v327_usage_supported,
        claims_audit._build6r_v327_ingredient_list_header_supported,
        claims_audit._build6r_v327_ingredient_segments,
        claims_audit._build6r_v327_ingredient_alias_specs,
        claims_audit._build6r_v327_ingredient_segment_supported,
        claims_audit._build6r_v327_explicit_ingredient_list_supported,
        claims_audit._build6r_v327_candidate_supported,
        claims_audit._build6r_v327_reconcile_usage_ingredients_and_meta_provenance,
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
