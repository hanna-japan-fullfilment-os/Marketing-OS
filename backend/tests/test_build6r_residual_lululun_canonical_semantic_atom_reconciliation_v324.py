from types import SimpleNamespace

import pytest

from app.services import claims_audit


def _verified():
    return SimpleNamespace(
        verified_name="LuLuLun Hydra EX Mask 7 Sheets",
        verified_description=(
            "LuLuLun Hydra EX is a facial sheet mask in a "
            "7-sheet pouch containing 150 mL of essence."
        ),
        verified_ingredients=[
            (
                "Human adipose-derived mesenchymal cell exosomes "
                "(manufacturer-listed skin-conditioning ingredient; "
                "manufacturer states stem cells are not contained)"
            ),
            "Glutathione",
            "Arbutin",
            "Ascorbyl palmitate",
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
            "Manufacturer usage guidance: unfold the mask and fit it "
            "around the eyes and mouth. After removal, fold the mask "
            "for wiping/light patting and follow with an emulsion or cream."
        ),
        verified_size="7 sheets / essence 150 mL",
        verified_variant="Face Mask LuLuLun EX 1FS - 7-sheet pouch",
        verified_price="",
        verified_availability="",
        verified_country_of_origin="",
        verified_claims=[
            "7-sheet pouch containing 150 mL of essence",
            (
                "Contains human adipose-derived mesenchymal cell exosomes "
                "as a manufacturer-listed skin-conditioning ingredient; "
                "manufacturer states stem cells are not contained"
            ),
            "Manufacturer describes the sheet as a Melty Feel Sheet",
        ],
        prohibited_claims=[],
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
        reason="live-v323-finding",
    )


@pytest.mark.parametrize(
    ("text", "category"),
    [
        (
            "7 máscaras com 150 mL de essência",
            "product structure/format",
        ),
        (
            "pouch com 7 sheet masks",
            "product structure/format",
        ),
        (
            "pouch com 7 máscaras",
            "product structure/format",
        ),
        (
            "Manufacturer describes the sheet as a Melty Feel Sheet",
            "product feature/packaging benefit",
        ),
        (
            "Tecido descrito como Melty Feel Sheet",
            "product feature/packaging benefit",
        ),
        (
            "LuLuLun Hydra EX é uma facial sheet mask",
            "product type",
        ),
        (
            (
                "LuLuLun Hydra EX é uma máscara facial em pouch "
                "com 7 unidades e 150 mL de essência"
            ),
            "product structure/format",
        ),
    ],
)
def test_v324_verified_lululun_fact_paraphrases_reconcile(
    text,
    category,
):
    assert claims_audit._build6r_v324_candidate_supported(
        _finding(
            text,
            category,
        ),
        _verified(),
        {},
    )


@pytest.mark.parametrize(
    ("text", "category"),
    [
        (
            "máscara de ingredientes avançados",
            "product feature/packaging benefit",
        ),
        (
            "sheet mask avançada",
            "product structure/format",
        ),
        (
            "tecnologia superior",
            "product feature/packaging benefit",
        ),
        (
            "fórmula premium",
            "ingredients/formulation",
        ),
        (
            "melhora a pele",
            "product benefits/effects",
        ),
        (
            "hidrata profundamente",
            "product benefits/effects",
        ),
        (
            "queridinha do Brasil",
            "rankings/bestseller/market adoption",
        ),
        (
            "mais eficaz",
            "product benefits/effects",
        ),
        (
            "revolucionária",
            "product feature/packaging benefit",
        ),
        (
            "diretamente do Japão",
            "ingredients/formulation/origin",
        ),
    ],
)
def test_v324_unsupported_marketing_or_origin_claims_remain_blocked(
    text,
    category,
):
    assert not claims_audit._build6r_v324_candidate_supported(
        _finding(
            text,
            category,
        ),
        _verified(),
        {},
    )


def test_v324_unqualified_exosome_claim_remains_blocked():
    assert not claims_audit._build6r_v324_candidate_supported(
        _finding(
            "Contém exossomos derivados de células mesenquimais",
            "ingredients/formulation/origin",
        ),
        _verified(),
        {},
    )


def test_v324_research_remains_ineligible_as_evidence():
    assert not claims_audit._build6r_v324_candidate_supported(
        _finding(
            "7 máscaras com 150 mL de essência",
            "product structure/format",
            source="strategy.research_basis[0]",
        ),
        _verified(),
        {},
    )


def test_v324_bad_quantity_remains_blocked():
    assert not claims_audit._build6r_v324_candidate_supported(
        _finding(
            "pouch com 7 máscaras e 200 mL de essência",
            "product structure/format",
        ),
        _verified(),
        {},
    )


def test_v324_reconciler_changes_only_supported_finding():
    supported = _finding(
        "7 máscaras com 150 mL de essência",
        "product structure/format",
    )

    unsupported = _finding(
        "máscara de ingredientes avançados",
        "product feature/packaging benefit",
    )

    result = claims_audit.ClaimAuditResult(
        findings=[
            supported,
            unsupported,
        ]
    )

    reconciled = (
        claims_audit
        ._build6r_v324_reconcile_residual_canonical_semantic_atoms(
            result,
            _verified(),
            {},
        )
    )

    assert reconciled.findings[0].evidence_status == "SUPPORTED"
    assert (
        reconciled.findings[0].allowed_source
        == "verified_product_facts"
    )

    assert reconciled.findings[1].evidence_status == "UNSUPPORTED"


def test_v324_is_append_only_after_v323():
    assert (
        claims_audit._build6r_augment_before_v324
        is not claims_audit.augment_with_ai_extraction
    )


def test_v324_no_fuzzy_or_network_dependency():
    import inspect

    source = inspect.getsource(
        claims_audit._build6r_v324_candidate_supported
    ).lower()

    forbidden = (
        "openai",
        "requests.",
        "http://",
        "https://",
        "embedding",
        "vector",
        "cosine",
        "fuzzy",
    )

    for token in forbidden:
        assert token not in source



@pytest.mark.parametrize(
    "text",
    [
        "produto avançado",
        "sheet mask avançada",
        "ingredientes avançados",
        "tecnologias avançadas",
    ],
)
def test_v324_portuguese_advanced_inflections_remain_blocked(
    text,
):
    assert not claims_audit._build6r_v324_candidate_supported(
        _finding(
            text,
            "product structure/format",
        ),
        _verified(),
        {},
    )



# BUILD6R_V324_EXACT_LIVE_AND_CROSS_PRODUCT_MATRIX_V1


@pytest.mark.parametrize(
    ("text", "category", "source"),
    [
        (
            "Tratamento em 7 máscaras faciais, com 150 mL de essência",
            "product_composition_or_quantity",
            "ai_extracted_candidate",
        ),
        (
            "O pouch contém 7 sheet masks e 150 mL de essência",
            "product_composition_or_quantity",
            "master_concept.must_include[3]",
        ),
        (
            "A descrição do tecido como “Melty Feel Sheet”",
            "product_feature_or_material",
            "master_concept.must_include[6]",
        ),
        (
            "Tratamento em 7 máscaras faciais, com 150 mL de essência.",
            "product_composition_or_quantity",
            "ai_extracted_candidate",
        ),
        (
            (
                "Máscara facial em folha LuLuLun Hydra EX, "
                "variante em pouch com 7 máscaras."
            ),
            "product_type_or_usage",
            "ai_extracted_candidate",
        ),
        (
            (
                "Contém exossomos de células mesenquimais derivadas "
                "de tecido adiposo humano como ingrediente de "
                "condicionamento da pele; o fabricante informa que "
                "não contém células-tronco."
            ),
            "product_composition_or_quantity",
            "ai_extracted_candidate",
        ),
        (
            "Pouch com 7 sheet masks.",
            "product_composition_or_quantity",
            "ai_extracted_candidate",
        ),
    ],
)
def test_v324_exact_v323_live_supported_corpus(
    text,
    category,
    source,
):
    fields = (
        {}
        if source == "ai_extracted_candidate"
        else {
            source: text,
        }
    )

    assert claims_audit._build6r_v324_candidate_supported(
        _finding(
            text,
            category,
            source,
        ),
        _verified(),
        fields,
    )


def test_v324_exact_live_positioning_claim_remains_blocked():
    text = (
        "LuLuLun Hydra EX Mask 7 Sheets apresentada como uma "
        "“máscara de ingredientes avançados”"
    )

    source = "master_concept.key_message"

    assert not claims_audit._build6r_v324_candidate_supported(
        _finding(
            text,
            "product_positioning_or_quality",
            source,
        ),
        _verified(),
        {
            source: text,
        },
    )


def _generic_verified(
    *,
    features=None,
    size="",
    variant="",
    claims=None,
):
    return SimpleNamespace(
        verified_name="Generic Product",
        verified_description="",
        verified_ingredients=[],
        verified_features=list(
            features or []
        ),
        verified_benefits=[],
        verified_usage="",
        verified_size=size,
        verified_variant=variant,
        verified_price="",
        verified_availability="",
        verified_country_of_origin="",
        verified_claims=list(
            claims or []
        ),
        prohibited_claims=[],
    )


@pytest.mark.parametrize(
    ("verified", "text"),
    [
        (
            _generic_verified(
                features=[
                    "3 modes",
                    "20 intensity levels",
                ]
            ),
            "3 modos e 20 níveis de intensidade",
        ),
        (
            _generic_verified(
                size="50 mL refill",
            ),
            "refil de 50 mL",
        ),
        (
            _generic_verified(
                size="4-piece set",
            ),
            "kit com 4 peças",
        ),
    ],
)
def test_v324_cross_product_quantity_formats_are_canonical(
    verified,
    text,
):
    assert claims_audit._build6r_v324_candidate_supported(
        _finding(
            text,
            "product_composition_or_quantity",
        ),
        verified,
        {},
    )


def test_v324_cross_product_wrong_quantity_remains_blocked():
    verified = _generic_verified(
        features=[
            "3 modes",
            "20 intensity levels",
        ]
    )

    assert not claims_audit._build6r_v324_candidate_supported(
        _finding(
            "3 modos e 21 níveis de intensidade",
            "product_composition_or_quantity",
        ),
        verified,
        {},
    )


def test_v324_cross_product_evaluative_positioning_remains_blocked():
    verified = _generic_verified(
        features=[
            "3 modes",
        ]
    )

    assert not claims_audit._build6r_v324_candidate_supported(
        _finding(
            "3 modos premium",
            "product_composition_or_quantity",
        ),
        verified,
        {},
    )



# BUILD6R_V324_GENERIC_FALLBACK_SAFETY_MATRIX_V1


@pytest.mark.parametrize(
    "text",
    [
        "3 modos premium",
        "3 modos inovadores",
        "3 modos revolucionários",
        "3 modes bestseller",
        "3 modos disponíveis",
        "3 modos fabricados no Japão",
        "3 modos com Bluetooth",
        "3 modos para reduzir linhas",
    ],
)
def test_v324_generic_quantity_fallback_does_not_rescue_extra_claims(
    text,
):
    verified = _generic_verified(
        features=[
            "3 modes",
            "20 intensity levels",
        ]
    )

    assert not claims_audit._build6r_v324_candidate_supported(
        _finding(
            text,
            "product_composition_or_quantity",
        ),
        verified,
        {},
    )


def test_v324_generic_quantity_fallback_does_not_rescue_unqualified_exosome():
    verified = _generic_verified(
        features=[
            "3 capsules",
        ]
    )

    assert not claims_audit._build6r_v324_candidate_supported(
        _finding(
            "3 cápsulas com exossomos",
            "product_composition_or_quantity",
        ),
        verified,
        {},
    )



# BUILD6R_V324_RESIDUAL_SUPPORTED_ATOM_SAFETY_MATRIX_V1


@pytest.mark.parametrize(
    "text",
    [
        "pouch com 7 máscaras e Bluetooth",
        "7 sheet masks luxury",
        "7 máscaras com NFC",
    ],
)
def test_v324_sealed_mask_format_support_cannot_rescue_extra_residue(
    text,
):
    assert not claims_audit._build6r_v324_candidate_supported(
        _finding(
            text,
            "product_composition_or_quantity",
        ),
        _verified(),
        {},
    )


def test_v324_generic_volume_support_cannot_rescue_extra_residue():
    verified = _generic_verified(
        size="50 mL refill",
    )

    assert not claims_audit._build6r_v324_candidate_supported(
        _finding(
            "50 mL clinically proven",
            "product_composition_or_quantity",
        ),
        verified,
        {},
    )


def test_v324_reconciler_reason_matches_actual_v324_evidence_path():
    verified = _generic_verified(
        features=[
            "3 modes",
            "20 intensity levels",
        ]
    )

    finding = _finding(
        "3 modos e 20 níveis de intensidade",
        "product_composition_or_quantity",
    )

    result = claims_audit.ClaimAuditResult(
        findings=[
            finding,
        ]
    )

    reconciled = (
        claims_audit
        ._build6r_v324_reconcile_residual_canonical_semantic_atoms(
            result,
            verified,
            {},
        )
    )

    supported = reconciled.findings[0]

    assert supported.evidence_status == "SUPPORTED"

    assert (
        supported.allowed_source
        == "verified_product_facts"
    )

    assert (
        "deterministic canonical evaluator"
        in supported.reason
    )

    assert (
        "V3.22 canonical semantic-atom evaluator independently proved"
        not in supported.reason
    )
