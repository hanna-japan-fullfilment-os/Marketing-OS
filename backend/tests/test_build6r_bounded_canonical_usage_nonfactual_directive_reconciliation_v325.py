from types import SimpleNamespace
import inspect

import pytest

from app.services import claims_audit


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
        prohibited_claims=[
            "Do not use research as product-fact evidence",
        ],
    )


def _finding(
    text,
    category,
    source="ai_extracted_candidate",
):
    return claims_audit.ClaimFinding(
        claim_text=text,
        claim_category=category,
        source_field=source,
        evidence_status="UNSUPPORTED",
        allowed_source="",
        reason="post-v324-live-finding",
    )


LIVE_FACTUAL_FINDINGS = [
    (
        "conscientizar sobre o formato de sheet mask como uma etapa possível "
        "de cuidado facial (usável em lugar do tônico)",
        "product benefits/effects",
        "master_concept.objective",
    ),
    (
        "sheet mask facial em pouch com 7 unidades e 150 mL de essência, "
        "posicionada como exemplo concreto de máscara em tecido que pode ser "
        "usada em lugar do tônico, segundo orientação do fabricante",
        "product benefits/effects",
        "master_concept.product_category_context",
    ),
    (
        "descrição do fabricante de que o sheet é um “Melty Feel Sheet”",
        "product benefits/effects",
        "master_concept.proof_or_demo_strategy",
    ),
    (
        "sugestão de uso em lugar do tônico",
        "product benefits/effects",
        "master_concept.proof_or_demo_strategy",
    ),
    (
        "Pressionar para tirar o ar preso entre a pele e o tecido",
        "instructions for use",
        "ai_extracted_candidate",
    ),
    (
        "Erguer os cortes da região das bochechas ao longo da linha do rosto",
        "instructions for use",
        "ai_extracted_candidate",
    ),
    (
        "Depois de remover, o fabricante sugere dobrar a máscara para usar "
        "como “lenço” para dar leves batidinhas",
        "instructions for use",
        "ai_extracted_candidate",
    ),
    (
        "Em seguida, o fabricante indica finalizar com emulsão ou creme",
        "instructions for use",
        "ai_extracted_candidate",
    ),
    (
        "O fabricante descreve que ela pode ser usada de manhã ou à noite "
        "no lugar do tônico/loção",
        "product benefits/effects",
        "ai_extracted_candidate",
    ),
    (
        "Segundo o fabricante, a Hydra EX pode ser usada de manhã ou à noite "
        "no lugar do tônico/loção",
        "product benefits/effects",
        "copy.pt-BR.caption",
    ),
    (
        "1. Desdobrar a máscara 2. Ajustar em volta dos olhos e da boca "
        "3. Pressionar para tirar o ar preso entre a pele e o tecido "
        "4. Erguer os cortes da região das bochechas acompanhando a linha "
        "do rosto 5. Pressionar a máscara inteira com as palmas das mãos "
        "6. Após remover, dobrar a máscara usada para passar na pele com "
        "leves batidinhas 7. Finalizar com emulsão ou creme, conforme o "
        "fabricante",
        "instructions for use",
        "ai_extracted_candidate",
    ),
    (
        "Uso de manhã ou à noite, no lugar do tônico/loção, conforme "
        "orientação do fabricante",
        "product benefits/effects",
        "copy.pt-BR.caption",
    ),
    (
        "LuLuLun Hydra EX – máscara facial em pouch com 7 sheet masks",
        "product category",
        "creative.creative_brief.template_suggestion",
    ),
    (
        "Modo de uso conforme o fabricante",
        "instructions for use",
        "creative.creative_brief.template_suggestion",
    ),
    (
        "Desdobrar a máscara, ajustar ao redor dos olhos e boca, pressionar "
        "o ar para fora, erguer os cortes das bochechas ao longo da linha do "
        "rosto e pressionar o conjunto com as palmas das mãos. Após remover, "
        "o fabricante sugere dobrar a máscara para leves toques na pele e "
        "finalizar com emulsão ou creme. Descrito como utilizável pela manhã "
        "ou à noite, em substituição ao tônico",
        "instructions for use",
        "creative.creative_brief.template_suggestion",
    ),
]


@pytest.mark.parametrize(
    ("text", "category", "source"),
    LIVE_FACTUAL_FINDINGS,
)
def test_v325_exact_post_v324_live_factual_findings_reconcile(
    text,
    category,
    source,
):
    assert claims_audit._build6r_v325_candidate_supported(
        _finding(
            text,
            category,
            source,
        ),
        _verified(),
        {},
    )


def test_v325_exact_post_v324_visual_identity_is_nonfactual():
    finding = _finding(
        "pouch Hydra EX é sempre o centro da composição",
        "availability/scarcity/stock",
        "master_concept.visual_identity",
    )

    assert (
        claims_audit
        ._build6r_v325_nonfactual_visual_instruction(
            finding
        )
    )


def test_v325_exact_16_finding_corpus_leaves_no_unsupported_findings():
    findings = [
        _finding(
            text,
            category,
            source,
        )
        for text, category, source in LIVE_FACTUAL_FINDINGS
    ]

    findings.insert(
        2,
        _finding(
            "pouch Hydra EX é sempre o centro da composição",
            "availability/scarcity/stock",
            "master_concept.visual_identity",
        ),
    )

    result = claims_audit.ClaimAuditResult(
        findings=findings
    )

    reconciled = (
        claims_audit
        ._build6r_v325_reconcile_bounded_usage_and_nonfactual_directives(
            result,
            _verified(),
            {},
        )
    )

    assert len(findings) == 16
    assert len(reconciled.findings) == 15

    assert all(
        finding.evidence_status == "SUPPORTED"
        for finding in reconciled.findings
    )

    assert all(
        finding.allowed_source == "verified_product_facts"
        for finding in reconciled.findings
    )

    assert not any(
        finding.source_field == "master_concept.visual_identity"
        for finding in reconciled.findings
    )


@pytest.mark.parametrize(
    "text",
    [
        "Pressionar para tirar o ar preso e massagear por 20 minutos",
        "Usar de manhã ou à noite e aplicar também no pescoço",
        "Desdobrar a máscara e ativar o Bluetooth",
        "Modo de uso conforme o fabricante: usar 3 vezes por dia",
    ],
)
def test_v325_usage_residual_guard_blocks_unverified_instruction(
    text,
):
    assert not claims_audit._build6r_v325_candidate_supported(
        _finding(
            text,
            "instructions for use",
        ),
        _verified(),
        {},
    )


@pytest.mark.parametrize(
    "text",
    [
        "hidrata profundamente",
        "reduz linhas",
        "resultado visível em 10 minutos",
        "mais eficaz que outras máscaras",
        "tecnologia superior",
    ],
)
def test_v325_real_benefit_effect_or_superiority_remains_blocked(
    text,
):
    assert not claims_audit._build6r_v325_candidate_supported(
        _finding(
            text,
            "product benefits/effects",
        ),
        _verified(),
        {},
    )


@pytest.mark.parametrize(
    "text",
    [
        "bestseller no centro da composição",
        "últimas unidades no centro da composição",
        "hidratação profunda no centro da composição",
        "preço 1990 no centro da composição",
        "produto premium no centro da composição",
    ],
)
def test_v325_visual_directive_with_factual_or_marketing_residue_stays_blocked(
    text,
):
    assert not (
        claims_audit
        ._build6r_v325_nonfactual_visual_instruction(
            _finding(
                text,
                "availability/scarcity/stock",
                "master_concept.visual_identity",
            )
        )
    )


def test_v325_melty_feature_mislabeled_as_benefit_reconciles():
    assert claims_audit._build6r_v325_candidate_supported(
        _finding(
            "descrição do fabricante de que o sheet é um Melty Feel Sheet",
            "product benefits/effects",
            "master_concept.proof_or_demo_strategy",
        ),
        _verified(),
        {},
    )


def test_v325_melty_feature_with_unknown_quality_residue_is_blocked():
    assert not claims_audit._build6r_v325_candidate_supported(
        _finding(
            "Melty Feel Sheet luxuoso",
            "product benefits/effects",
        ),
        _verified(),
        {},
    )


def test_v325_wrong_package_count_remains_blocked():
    assert not claims_audit._build6r_v325_candidate_supported(
        _finding(
            "máscara facial em pouch com 8 sheet masks",
            "product category",
            "creative.creative_brief.template_suggestion",
        ),
        _verified(),
        {},
    )


def test_v325_research_source_remains_ineligible_for_usage():
    assert not claims_audit._build6r_v325_candidate_supported(
        _finding(
            "pode ser usada de manhã ou à noite no lugar do tônico",
            "instructions for use",
            "strategy.research_basis[0]",
        ),
        _verified(),
        {},
    )


def test_v325_unqualified_exosome_remains_blocked():
    assert not claims_audit._build6r_v325_candidate_supported(
        _finding(
            "Contém exossomos derivados de células mesenquimais",
            "product benefits/effects",
        ),
        _verified(),
        {},
    )


def test_v325_cross_product_usage_is_product_agnostic():
    verified = SimpleNamespace(
        verified_name="Generic Serum",
        verified_description="Generic facial serum.",
        verified_ingredients=[],
        verified_features=[],
        verified_benefits=[],
        verified_usage="Apply 2 drops once daily after cleansing.",
        verified_size="30 mL",
        verified_variant="30 mL bottle",
        verified_price="",
        verified_availability="",
        verified_country_of_origin="",
        verified_claims=[],
        prohibited_claims=[],
    )

    assert claims_audit._build6r_v325_candidate_supported(
        _finding(
            "Apply 2 drops once daily after cleansing",
            "instructions for use",
        ),
        verified,
        {},
    )

    assert not claims_audit._build6r_v325_candidate_supported(
        _finding(
            "Apply 3 drops once daily after cleansing",
            "instructions for use",
        ),
        verified,
        {},
    )


def test_v325_is_append_only_after_v324():
    assert (
        claims_audit._build6r_augment_before_v325
        is not claims_audit.augment_with_ai_extraction
    )


def test_v325_wrapper_preserves_historical_contract_markers():
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
        "_build6r_augment_before_v322",
        "_build6r_v322_reconcile_fresh_live_composite_candidates",
        "_build6r_augment_before_v323",
        "_build6r_v323_reconcile_residual_live_semantic_boundaries",
        "_build6r_augment_before_v324",
        "_build6r_v324_reconcile_residual_canonical_semantic_atoms",
        "_build6r_augment_before_v325",
        "_build6r_v325_reconcile_bounded_usage_and_nonfactual_directives",
    )

    assert all(
        marker in source
        for marker in markers
    )


def test_v325_production_layer_is_zero_cost_product_agnostic_and_no_fuzzy():
    functions = (
        claims_audit._build6r_v325_strip_numbered_step_labels,
        claims_audit._build6r_v325_usage_alias_groups,
        claims_audit._build6r_v325_usage_requirement_present,
        claims_audit._build6r_v325_verified_context_text,
        claims_audit._build6r_v325_usage_context_is_bounded,
        claims_audit._build6r_v325_usage_relations_are_bounded,
        claims_audit._build6r_v325_usage_supported,
        claims_audit._build6r_v325_feature_context_is_bounded,
        claims_audit._build6r_v325_visual_has_factual_usage_residue,
        claims_audit._build6r_v325_nonfactual_visual_instruction,
        claims_audit._build6r_v325_candidate_supported,
        claims_audit._build6r_v325_reconcile_bounded_usage_and_nonfactual_directives,
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

    assert all(
        token not in source
        for token in forbidden
    )
@pytest.mark.parametrize(
    "text",
    [
        "Use with toner",
        "Usar com tonico",
        "Use on eyes and mouth",
        "Usar nos olhos e boca",
        "Remove cheek cuts",
        "Remover os cortes das bochechas",
        "Fold the mask before removal",
        "Dobrar a mascara antes de remover",
        "Emulsion or cream before the mask",
        "Manufacturer usage guidance: apply daily",
    ],
)
def test_v325_canonical_tokens_cannot_form_wrong_usage_relationship(
    text,
):
    assert not claims_audit._build6r_v325_candidate_supported(
        _finding(
            text,
            "instructions for use",
        ),
        _verified(),
        {},
    )


def test_v325_generic_usage_reference_is_exact_not_prefix_authority():
    assert claims_audit._build6r_v325_candidate_supported(
        _finding(
            "Modo de uso conforme o fabricante",
            "instructions for use",
            "creative.creative_brief.template_suggestion",
        ),
        _verified(),
        {},
    )

    assert not claims_audit._build6r_v325_candidate_supported(
        _finding(
            "Modo de uso conforme o fabricante: usar diariamente",
            "instructions for use",
            "creative.creative_brief.template_suggestion",
        ),
        _verified(),
        {},
    )


def test_v325_cross_product_canonical_frequency_still_works_after_guard():
    verified = SimpleNamespace(
        verified_name="Generic Serum",
        verified_description="Generic facial serum.",
        verified_ingredients=[],
        verified_features=[],
        verified_benefits=[],
        verified_usage="Apply 2 drops once daily after cleansing.",
        verified_size="30 mL",
        verified_variant="30 mL bottle",
        verified_price="",
        verified_availability="",
        verified_country_of_origin="",
        verified_claims=[],
        prohibited_claims=[],
    )

    assert claims_audit._build6r_v325_candidate_supported(
        _finding(
            "Apply 2 drops once daily after cleansing",
            "instructions for use",
        ),
        verified,
        {},
    )

    assert not claims_audit._build6r_v325_candidate_supported(
        _finding(
            "Apply 3 drops once daily after cleansing",
            "instructions for use",
        ),
        verified,
        {},
    )

@pytest.mark.parametrize(
    ("usage", "claim"),
    [
        (
            "Usar de manha ou a noite no lugar do tonico.",
            "Usar com tonico",
        ),
        (
            "Ajustar ao redor dos olhos e boca.",
            "Usar nos olhos e boca",
        ),
        (
            "Erguer os cortes das bochechas ao longo da linha do rosto.",
            "Remover os cortes das bochechas",
        ),
        (
            "Pressionar a mascara com as palmas.",
            "Remover com as palmas",
        ),
    ],
)
def test_v325_portuguese_canonical_relationships_fail_closed(
    usage,
    claim,
):
    verified = SimpleNamespace(
        verified_name="Produto Generico",
        verified_description="Produto generico.",
        verified_ingredients=[],
        verified_features=[],
        verified_benefits=[],
        verified_usage=usage,
        verified_size="",
        verified_variant="",
        verified_price="",
        verified_availability="",
        verified_country_of_origin="",
        verified_claims=[],
        prohibited_claims=[],
    )

    assert not claims_audit._build6r_v325_candidate_supported(
        _finding(
            claim,
            "instructions for use",
        ),
        verified,
        {},
    )


@pytest.mark.parametrize(
    ("usage", "claim"),
    [
        (
            "Usar de manha ou a noite no lugar do tonico.",
            "Usar no lugar do tonico",
        ),
        (
            "Ajustar ao redor dos olhos e boca.",
            "Ajustar ao redor dos olhos e boca",
        ),
        (
            "Erguer os cortes das bochechas ao longo da linha do rosto.",
            "Erguer os cortes das bochechas ao longo da linha do rosto",
        ),
        (
            "Pressionar a mascara com as palmas.",
            "Pressionar a mascara com as palmas",
        ),
    ],
)
def test_v325_portuguese_canonical_relationships_preserve_valid_relation(
    usage,
    claim,
):
    verified = SimpleNamespace(
        verified_name="Produto Generico",
        verified_description="Produto generico.",
        verified_ingredients=[],
        verified_features=[],
        verified_benefits=[],
        verified_usage=usage,
        verified_size="",
        verified_variant="",
        verified_price="",
        verified_availability="",
        verified_country_of_origin="",
        verified_claims=[],
        prohibited_claims=[],
    )

    assert claims_audit._build6r_v325_candidate_supported(
        _finding(
            claim,
            "instructions for use",
        ),
        verified,
        {},
    )


@pytest.mark.parametrize(
    "category",
    [
        "instructions for use",
        "availability/scarcity/stock",
    ],
)
def test_v325_visual_layout_cannot_hide_factual_usage_residue(
    category,
):
    finding = _finding(
        "usar de manha no centro da composicao",
        category,
        "master_concept.visual_identity",
    )

    assert not (
        claims_audit
        ._build6r_v325_nonfactual_visual_instruction(
            finding
        )
    )


def test_v325_pure_visual_layout_direction_remains_nonfactual():
    finding = _finding(
        "produto no centro da composicao",
        "availability/scarcity/stock",
        "master_concept.visual_identity",
    )

    assert (
        claims_audit
        ._build6r_v325_nonfactual_visual_instruction(
            finding
        )
    )
