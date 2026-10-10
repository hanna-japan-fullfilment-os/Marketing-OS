from __future__ import annotations

import asyncio
import inspect
from types import SimpleNamespace

import app.services.claims_audit as claims_audit
import app.services.orchestrator as orchestrator
from app.services.prompt_registry import PROMPT_VERSIONS


def _verified():
    return SimpleNamespace(
        verified_name="Example Mask 7 Sheets",
        verified_description="Exact 7-sheet pouch variant.",
        verified_ingredients=[
            (
                "Human adipose-derived mesenchymal cell exosomes "
                "(manufacturer states stem cells are not contained)"
            ),
        ],
        verified_features=[
            "7-sheet pouch variant",
            "Contains 150 mL of essence",
        ],
        verified_benefits=[],
        verified_usage=(
            "Manufacturer usage guidance: after removal, fold the mask "
            "for wiping/light patting and follow with an emulsion or cream."
        ),
        verified_size="7 sheets / essence 150 mL",
        verified_variant="7-sheet pouch",
        verified_price="",
        verified_availability="",
        verified_country_of_origin="",
        verified_claims=[],
        prohibited_claims=[],
    )


def _finding(
    text,
    category,
    source="ai_extracted_candidate",
):
    return SimpleNamespace(
        claim_text=text,
        claim_category=category,
        source_field=source,
        evidence_status="UNSUPPORTED",
        allowed_source="",
        reason="",
    )


def test_v323_pouch_seven_sheet_quantity_reconciles():
    finding = _finding(
        "Versão pouch com 7 folhas",
        "format_quantity_or_dosage",
    )

    assert claims_audit._build6r_v323_candidate_supported(
        finding,
        _verified(),
        {},
    )


def test_v323_150_ml_essence_quantity_reconciles():
    finding = _finding(
        "150 mL de essência por pacote",
        "format_quantity_or_dosage",
    )

    assert claims_audit._build6r_v323_candidate_supported(
        finding,
        _verified(),
        {},
    )


def test_v323_bounded_post_removal_usage_reconciles():
    finding = _finding(
        (
            "Depois de remover, o fabricante sugere dobrar a máscara "
            "para usar dando leves batidinhas ou como lenço"
        ),
        "directions_for_use",
    )

    assert claims_audit._build6r_v323_candidate_supported(
        finding,
        _verified(),
        {},
    )


def test_v323_advanced_positioning_residuals_remain_blocked():
    phrases = [
        "Uma sheet mask avançada",
        "Sheet mask avançada para sua rotina",
        "Ingredientes avançados",
        "Fórmula avançada",
        "Uma máscara avançada",
        "Tecnologia avançada para skincare",
    ]

    for phrase in phrases:
        assert not claims_audit._build6r_v323_candidate_supported(
            _finding(
                phrase,
                "product_features_attributes",
            ),
            _verified(),
            {},
        )


def test_v323_exosome_without_same_field_caveat_remains_blocked():
    finding = _finding(
        "Contém exossomos derivados de células mesenquimais",
        "ingredients_contents",
    )

    assert not claims_audit._build6r_v323_candidate_supported(
        finding,
        _verified(),
        {},
    )


def test_v323_planning_only_phrase_is_narrowly_meta():
    finding = _finding(
        "Top of funil, sem pressao de compra",
        "marketing_or_promotion_terms",
    )

    assert claims_audit._build6r_v323_is_non_product_planning_meta(
        finding
    )


def test_v323_meta_category_with_product_fact_fails_closed():
    finding = _finding(
        "Top of funil: produto contém 150 mL",
        "marketing_or_promotion_terms",
    )

    assert not claims_audit._build6r_v323_is_non_product_planning_meta(
        finding
    )


def test_v323_arbitrary_marketing_terms_are_not_exempt():
    finding = _finding(
        "Campanha premium com ingredientes avançados",
        "marketing_or_promotion_terms",
    )

    assert not claims_audit._build6r_v323_is_non_product_planning_meta(
        finding
    )


def test_v323_bad_quantity_number_fails_closed():
    finding = _finding(
        "200 mL de essência por pacote",
        "format_quantity_or_dosage",
    )

    assert not claims_audit._build6r_v323_candidate_supported(
        finding,
        _verified(),
        {},
    )


def test_v323_quantity_without_format_atom_fails_closed():
    finding = _finding(
        "O produto tem 7",
        "format_quantity_or_dosage",
    )

    assert not claims_audit._build6r_v323_candidate_supported(
        finding,
        _verified(),
        {},
    )


def test_v323_unsupported_usage_variant_fails_closed():
    finding = _finding(
        "Use por 30 minutos e massageie vigorosamente",
        "directions_for_use",
    )

    assert not claims_audit._build6r_v323_candidate_supported(
        finding,
        _verified(),
        {},
    )


def test_v323_stem_safety_remains_owned_by_previous_chain():
    source = inspect.getsource(
        claims_audit._build6r_v323_candidate_supported
    )

    assert "exosome" in source
    assert "return False" in source


def test_v323_cross_field_stem_caveat_cannot_rescue_residual():
    finding = _finding(
        "Exosome ingredient for skin conditioning",
        "ingredients_contents",
    )

    verified = _verified()

    assert "stem cells are not contained" in (
        verified.verified_ingredients[0]
    )

    assert not claims_audit._build6r_v323_candidate_supported(
        finding,
        verified,
        {},
    )


def test_v323_no_global_ai_extracted_candidate_bypass():
    source = inspect.getsource(
        claims_audit._build6r_v323_candidate_supported
    )

    assert "_build6r_v322_source_field_allowed" in source
    assert "format quantity or dosage" in source
    assert "directions for use" in source


def test_v323_shared_prompt_blocks_evaluative_positioning():
    text = orchestrator._claims_boundary_instruction().lower()

    assert "advanced/avancado" in text
    assert "superior" in text
    assert "innovative" in text
    assert "premium" in text


def test_v323_shared_prompt_preserves_same_field_stem_qualification():
    text = orchestrator._claims_boundary_instruction().lower()

    assert "same generated textual field" in text
    assert "no-stem-cell qualification" in text


def test_v323_prompt_versions_and_creative_brief_identity():
    assert (
        PROMPT_VERSIONS[
            "master_campaign_concept"
        ].version
        == "1.6.0"
    )

    assert (
        PROMPT_VERSIONS[
            "campaign_copy"
        ].version
        == "1.5.0"
    )

    assert (
        PROMPT_VERSIONS[
            "carousel_plan"
        ].version
        == "1.5.0"
    )

    assert "creative_brief" not in PROMPT_VERSIONS


def test_v323_wrapper_executes_v322_chain_once(monkeypatch):
    calls = {
        "previous": 0,
    }

    async def fake_previous(
        *args,
        **kwargs,
    ):
        calls["previous"] += 1

        return SimpleNamespace(
            findings=[]
        )

    monkeypatch.setattr(
        claims_audit,
        "_build6r_augment_before_v323",
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
