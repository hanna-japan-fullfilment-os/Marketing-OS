import asyncio
from types import SimpleNamespace

import app.services.claims_audit as claims_audit


class FakeFinding:
    def __init__(
        self,
        claim_text,
        claim_category,
        source_field="ai_extracted_candidate",
        evidence_status="UNSUPPORTED",
        allowed_source="",
        reason="baseline unsupported",
    ):
        self.claim_text = claim_text
        self.claim_category = claim_category
        self.source_field = source_field
        self.evidence_status = evidence_status
        self.allowed_source = allowed_source
        self.reason = reason

    def model_copy(self, update=None):
        data = {
            "claim_text": self.claim_text,
            "claim_category": self.claim_category,
            "source_field": self.source_field,
            "evidence_status": self.evidence_status,
            "allowed_source": self.allowed_source,
            "reason": self.reason,
        }

        data.update(update or {})

        return FakeFinding(**data)


class FakeResult:
    def __init__(self, findings):
        self.findings = list(findings)

    def model_copy(self, update=None):
        data = {
            "findings": self.findings,
        }

        data.update(update or {})

        return FakeResult(**data)


def verified():
    return SimpleNamespace(
        verified_description=(
            "LuLuLun Hydra EX facial sheet mask, exact "
            "7-sheet pouch variant."
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
            "Manufacturer describes the sheet as a Melty Feel Sheet",
            "Colorant-free",
            "Fragrance-free",
            "Mineral-oil-free",
            "Alcohol-free",
        ],
        verified_benefits=[],
        verified_usage=(
            "Apply the sheet around the eyes and mouth, press to remove "
            "air, fit the cheek cuts along the face and press with the "
            "palms. After removing, use the folded mask for gentle pats "
            "and follow with emulsion or cream."
        ),
        verified_size="7 sheets / essence 150 mL",
        verified_variant="Face Mask LuLuLun EX 1FS - 7-sheet pouch",
        verified_price=None,
        verified_availability=None,
        verified_country_of_origin=None,
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
            "Manufacturer describes the sheet as a Melty Feel Sheet",
        ],
        prohibited_claims=[
            "Do not claim the product contains stem cells",
            "Do not claim clinical proof",
        ],
        missing_information=[],
    )


def reconcile(
    text,
    category,
    source="ai_extracted_candidate",
):
    result = FakeResult(
        [
            FakeFinding(
                text,
                category,
                source,
            )
        ]
    )

    out = (
        claims_audit
        ._build6r_v328_reconcile_live_taxonomy(
            result,
            verified(),
        )
    )

    return out.findings[0]


def test_live_objective_7_units_is_grounded():
    finding = reconcile(
        (
            "Gerar reconhecimento da LuLuLun Hydra EX como uma "
            "sheet mask especifica, explicando com clareza o que ha "
            "dentro do pouch de 7 unidades."
        ),
        "product_category_or_positioning",
        "strategy.objective",
    )

    assert finding.evidence_status == "SUPPORTED"


def test_live_7_sheets_150_ml_is_grounded():
    finding = reconcile(
        (
            "Mascara facial de tecido em pouch com multiplas "
            "unidades (LuLuLun Hydra EX Mask 7 Sheets), com "
            "7 sheets em 150 mL de essencia, lista conhecida de "
            "ingredientes e instrucoes de uso detalhadas pelo fabricante."
        ),
        "product_format_or_quantity",
        "master_concept.product_category_context",
    )

    assert finding.evidence_status == "SUPPORTED"
    assert finding.allowed_source == "verified_product_facts"


def test_story_arc_quantity_is_grounded():
    finding = reconcile(
        "recapitular o formato (7 sheets / 150 mL)",
        "product_format_or_quantity",
        "master_concept.story_arc",
    )

    assert finding.evidence_status == "SUPPORTED"


def test_wrong_quantity_remains_fail_closed():
    finding = reconcile(
        "pouch com 8 mascaras e 150 mL de essencia",
        "product_format_or_quantity",
    )

    assert finding.evidence_status == "UNSUPPORTED"


def test_exosome_with_same_field_safety_is_grounded():
    finding = reconcile(
        (
            "a presenca dos ingredientes listados, incluindo o "
            "ingrediente de exossomos descrito corretamente como "
            "human adipose-derived mesenchymal cell exosomes com a "
            "qualificacao de ausencia de celulas-tronco conforme o "
            "fabricante"
        ),
        "ingredients_or_composition",
        "master_concept.proof_or_demo_strategy",
    )

    assert finding.evidence_status == "SUPPORTED"


def test_exosome_without_same_field_safety_stays_blocked_in_factual_copy():
    finding = reconcile(
        (
            "Contem human adipose-derived mesenchymal cell exosomes."
        ),
        "ingredients_or_composition",
        "copy.pt-BR.supporting_copy",
    )

    assert finding.evidence_status == "UNSUPPORTED"


def test_unknown_ingredient_stays_blocked():
    finding = reconcile(
        "A formula contem glutathione e niacinamida.",
        "ingredients_or_composition",
    )

    assert finding.evidence_status == "UNSUPPORTED"


def test_melty_feel_sheet_is_grounded():
    finding = reconcile(
        "folha Melty Feel Sheet",
        "product_feature_or_material",
    )

    assert finding.evidence_status == "SUPPORTED"


def test_free_from_combination_is_grounded():
    finding = reconcile(
        "formula sem corantes, fragrancia, oleo mineral e alcool",
        "ingredients_free_from_claim",
    )

    assert finding.evidence_status == "SUPPORTED"


def test_usage_paraphrase_is_grounded():
    finding = reconcile(
        (
            "Aplicar ao redor dos olhos e boca, pressionar para tirar "
            "o ar e pressionar com as palmas; depois retirar e seguir "
            "com emulsao ou creme."
        ),
        "product_usage_or_instructions",
    )

    assert finding.evidence_status == "SUPPORTED"


def test_unverified_usage_atom_stays_blocked():
    finding = reconcile(
        (
            "Aplicar por 20 minutos e depois retirar."
        ),
        "product_usage_or_instructions",
    )

    assert finding.evidence_status == "UNSUPPORTED"


def test_nonassertive_formula_heading_is_not_product_claim():
    finding = reconcile(
        "O que a formula contem (segundo o fabricante):",
        "other_objective_or_process_claim",
    )

    assert finding.evidence_status == "SUPPORTED"
    assert finding.allowed_source == ""


def test_bounded_campaign_promise_metadata_does_not_create_product_evidence():
    finding = reconcile(
        (
            "Apresentar a LuLuLun Hydra EX Mask 7 Sheets com total "
            "transparencia visual e textual, mostrando apenas o que e "
            "verificado sobre formula, formato, ingrediente de exossomos "
            "e modo de uso - sem extrapolar beneficios ou interpretar "
            "tendencias como promessa."
        ),
        "other_objective_or_process_claim",
        "master_concept.campaign_promise",
    )

    assert finding.evidence_status == "SUPPORTED"
    assert finding.allowed_source == ""


def test_supported_fact_plus_clinical_residue_remains_blocked():
    finding = reconcile(
        (
            "pouch com 7 mascaras e 150 mL de essencia, "
            "clinicamente comprovado para anti-aging"
        ),
        "product_format_or_quantity",
    )

    assert finding.evidence_status == "UNSUPPORTED"


def test_research_derived_claim_remains_blocked():
    finding = reconcile(
        (
            "Guia internacional de J-beauty recomenda a Hydra EX "
            "para hidratacao."
        ),
        "product_category_or_positioning",
    )

    assert finding.evidence_status == "UNSUPPORTED"


def test_comparison_remains_blocked():
    finding = reconcile(
        (
            "LuLuLun Hydra EX e superior a outras sheet masks."
        ),
        "product_category_or_positioning",
    )

    assert finding.evidence_status == "UNSUPPORTED"


def test_wrapper_executes_previous_chain_once_and_then_reconciles(monkeypatch):
    calls = []

    async def previous(
        *args,
        **kwargs,
    ):
        calls.append("called")

        return FakeResult(
            [
                FakeFinding(
                    "recapitular o formato (7 sheets / 150 mL)",
                    "product_format_or_quantity",
                    "master_concept.story_arc",
                )
            ]
        )

    monkeypatch.setattr(
        claims_audit,
        "_build6r_augment_before_v328",
        previous,
    )

    result = asyncio.run(
        claims_audit.augment_with_ai_extraction(
            None,
            fields={},
            verified=verified(),
            brand=None,
            model="zero-cost-test",
            existing=FakeResult([]),
        )
    )

    assert calls == ["called"]
    assert (
        result.findings[0].evidence_status
        == "SUPPORTED"
    )


def test_v328_preserves_result_identity_when_no_finding_changes():
    result = claims_audit.ClaimAuditResult(findings=[])

    returned = claims_audit._build6r_v328_reconcile_live_taxonomy(
        result,
        verified(),
        {},
    )

    assert returned is result


def test_v328_wrapper_uses_historical_varargs_contract():
    import inspect

    signature = str(
        inspect.signature(
            claims_audit.augment_with_ai_extraction
        )
    )

    assert signature == "(*args, **kwargs)"


def test_v328_runtime_wrapper_preserves_all_historical_markers():
    import inspect

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
        "_build6r_augment_before_v326",
        "_build6r_v326_reconcile_residual_taxonomy_and_nonclaims",
        "_build6r_augment_before_v327",
        "_build6r_v327_reconcile_usage_ingredients_and_meta_provenance",
        "_build6r_augment_before_v328",
        "_build6r_v328_reconcile_live_taxonomy",
    )

    assert all(marker in source for marker in markers)


def test_v328_usage_signal_uses_word_boundaries():
    for text in (
        "gerar reconhecimento",
        "recapitular o formato",
        "detalhadas pelo fabricante",
        "apresentar a formula",
    ):
        normalized = claims_audit._build6r_v328_normalize(text)
        assert not claims_audit._build6r_v328_usage_signal(normalized)


def test_v328_single_usage_token_does_not_rescue_legacy_positioning():
    normalized = claims_audit._build6r_v328_normalize(
        "Pensa nela como um passo mascara entre a limpeza e o seu hidratante/emulsao"
    )

    assert not claims_audit._build6r_v328_usage_supported(
        normalized,
        verified(),
    )


def test_v328_production_layer_remains_product_agnostic_zero_cost():
    import inspect

    source = inspect.getsource(claims_audit)
    marker = "BUILD6R_V328_CANONICAL_VERIFIED_FACT_LIVE_TAXONOMY_RECONCILIATION"
    tail = source[source.index(marker):].lower()

    for forbidden in (
        "lululun",
        "hydra",
        "campaign_id",
        "product_id",
        "openai",
        "httpx.",
        "requests.",
        "sqlite3",
        "rapidfuzz",
        "difflib",
        "sequencematcher",
        "embedding",
        "cosine",
        "generate_structured(",
        "generate_image(",
        "edit_image(",
    ):
        assert forbidden not in tail


def test_unknown_free_from_residue_stays_blocked():
    finding = reconcile(
        "formula sem corantes e parabenos",
        "ingredients_free_from_claim",
    )

    assert finding.evidence_status == "UNSUPPORTED"


def test_v328_legacy_routine_shape_stays_blocked():
    finding = reconcile(
        "3 passos: 1. Limpeza; 2. Produto (no lugar do tonico); 3. Emulsao ou creme",
        "directions for use",
        "master_concept.story_beats[4]",
    )

    assert finding.evidence_status == "UNSUPPORTED"


def test_v328_legacy_between_cleaning_and_moisturizer_stays_blocked():
    finding = reconcile(
        "Pensa nela como um passo mascara entre a limpeza e o seu hidratante/emulsao",
        "directions for use",
    )

    assert finding.evidence_status == "UNSUPPORTED"


def test_v328_vague_specific_ingredient_set_stays_blocked():
    finding = reconcile(
        (
            "Produto exatamente como descrito pelo fabricante: uma sheet mask "
            "facial em pouch com 7 folhas e 150 mL de essencia, com esse "
            "conjunto especifico de ingredientes e caracteristicas de formula"
        ),
        "ingredients_contents",
    )

    assert finding.evidence_status == "UNSUPPORTED"
