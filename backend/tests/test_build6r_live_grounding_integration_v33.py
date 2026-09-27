from __future__ import annotations

import asyncio
import inspect
from types import SimpleNamespace

import pytest

import app.services.claims_audit as claims_audit
import app.services.orchestrator as orchestrator
from app.services.prompt_registry import PROMPT_VERSIONS


def _verified():
    return SimpleNamespace(
        verified_description=(
            "LuLuLun Hydra EX facial sheet mask, exact "
            "7-sheet pouch variant. Manufacturer sales name: "
            "Face Mask LuLuLun EX 1FS."
        ),
        verified_usage=(
            "Manufacturer usage guidance: unfold the mask and fit it "
            "around the eyes and mouth, press out trapped air, lift "
            "the cheek cut sections along the face line, then press "
            "the whole mask into place with the palms. After removal, "
            "the manufacturer suggests folding the mask for "
            "wiping/light patting and following with an emulsion or "
            "cream. Manufacturer describes it as usable morning or "
            "evening in place of toner."
        ),
        verified_size="7 sheets / essence 150 mL",
        verified_variant=(
            "Face Mask LuLuLun EX 1FS - 7-sheet pouch"
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
        verified_claims=[
            "7-sheet pouch containing 150 mL of essence",
            (
                "Contains human adipose-derived mesenchymal cell "
                "exosomes as a manufacturer-listed skin-conditioning "
                "ingredient; manufacturer states stem cells are not "
                "contained"
            ),
            (
                "Manufacturer states the formula is colorant-free, "
                "fragrance-free, mineral-oil-free, and alcohol-free"
            ),
            "Manufacturer describes the sheet as a Melty Feel Sheet",
        ],
    )


def _finding(text, category, source_field):
    return claims_audit.ClaimFinding(
        claim_text=text,
        claim_category=category,
        source_field=source_field,
        evidence_status="UNSUPPORTED",
        allowed_source="",
        reason="synthetic V3.3 live target",
    )


def _status(text, category, source_field):
    result = claims_audit.ClaimAuditResult(
        findings=[
            _finding(
                text,
                category,
                source_field,
            )
        ]
    )

    reconciled = (
        claims_audit
        ._build6r_reconcile_generated_semantic_findings_v33(
            result,
            _verified(),
        )
    )

    return reconciled.findings[0]


SUPPORTED = [
    (
        "Na orientação do fabricante, essa máscara pode ser usada "
        "de manhã ou à noite no lugar do tônico",
        "product use/instructions",
        "copy.pt-BR.supporting_copy",
    ),
    (
        "O próprio fabricante descreve que essa máscara pode ser "
        "usada de manhã ou à noite no lugar do tônico",
        "product use/instructions",
        "creative.languages.pt-BR.carousel_plan.slides[3].body",
    ),
    (
        "Depois de remover, dá pra dobrar a sheet e usar pra dar "
        "leves batidinhas, e seguir com um emulsion ou creme",
        "product use/instructions",
        "copy.pt-BR.caption",
    ),
    (
        "Em seguida, o fabricante sugere seguir com emulsion ou creme",
        "product use/instructions",
        "creative.languages.pt-BR.carousel_plan.slides[3].body",
    ),
    (
        "São 7 sheets no mesmo pacote",
        "ingredients/contents",
        "creative.languages.pt-BR.carousel_plan.slides[2].body",
    ),
    (
        "Com 150 mL de essência no pouch",
        "ingredients/contents",
        "creative.languages.pt-BR.carousel_plan.slides[2].body",
    ),
    (
        "Contém human adipose-derived mesenchymal cell exosomes "
        "como ingrediente de condicionamento da pele; o fabricante "
        "afirma que não contém células-tronco",
        "ingredients/contents",
        "creative.creative_brief.template_suggestion",
    ),
    (
        "Fabricante descreve o sheet como Melty Feel Sheet",
        "product material/feature",
        "creative.creative_brief.template_suggestion",
    ),
    (
        "LuLuLun Hydra EX Mask 7 Sheets",
        "product identification",
        "ai_extracted_candidate",
    ),
    (
        "A LuLuLun Hydra EX Mask 7 Sheets é um pouch de máscara "
        "facial em tecido",
        "product type",
        "creative.languages.pt-BR.carousel_plan.slides[2].body",
    ),
]


BLOCKED = [
    (
        "No Japão, sheet mask não é só mimo de spa: é um passo de rotina",
        "product use/context",
        "ai_extracted_candidate",
    ),
    (
        "as prateleiras de farmácia de lá estão cheias de máscaras "
        "em pouch, com várias unidades dentro",
        "availability/prevalence",
        "copy.pt-BR.caption",
    ),
    (
        "Na Hanna Japan, a nossa curadoria olha justamente pra esses "
        "jeitos de cuidar da pele que você vê nas farmácias japonesas",
        "brand/curation role",
        "copy.pt-BR.supporting_copy",
    ),
    (
        "Em vez de vários sachês soltos, ela vem em um pouch com "
        "7 máscaras faciais e 150 mL de essência",
        "ingredients/contents",
        "copy.pt-BR.supporting_copy",
    ),
    (
        "um único pacote com 7 sheet masks imersas em 150 mL de essência",
        "ingredients/contents",
        "master_concept.campaign_promise",
    ),
    (
        "A Hydra EX vem em um pouch com 7 folhas mergulhadas em "
        "150 mL de essência",
        "ingredients/contents",
        "copy.pt-BR.caption",
    ),
    (
        "7 folhas no mesmo pouch para vários dias de uso contínuo",
        "product use/instructions",
        "copy.pt-BR.caption",
    ),
    (
        "Fabricante descreve o sheet como Melty Feel Sheet, com toque confortável",
        "product material/feature",
        "creative.creative_brief.template_suggestion",
    ),
    (
        "No contexto japonês, sheet mask é parte de rotina - não só dia de spa",
        "product use/context",
        "creative.creative_brief.design_concept",
    ),
]


@pytest.mark.parametrize(
    "text,category,source_field",
    SUPPORTED,
)
def test_real_live_supported_claims_reconcile(
    text,
    category,
    source_field,
):
    finding = _status(
        text,
        category,
        source_field,
    )

    assert finding.evidence_status == "SUPPORTED"
    assert finding.allowed_source == "verified_product_facts"


@pytest.mark.parametrize(
    "text,category,source_field",
    BLOCKED,
)
def test_unsupported_and_mixed_live_claims_stay_blocked(
    text,
    category,
    source_field,
):
    finding = _status(
        text,
        category,
        source_field,
    )

    assert finding.evidence_status == "UNSUPPORTED"


def test_creative_source_allowlist_is_narrow():
    assert (
        claims_audit
        ._build6r_v33_source_field_allowed(
            "creative.languages.pt-BR.carousel_plan.slides[2].body"
        )
        is True
    )

    assert (
        claims_audit
        ._build6r_v33_source_field_allowed(
            "creative.creative_brief.template_suggestion"
        )
        is True
    )

    assert (
        claims_audit
        ._build6r_v33_source_field_allowed(
            "creative.creative_brief.design_concept"
        )
        is False
    )

    assert (
        claims_audit
        ._build6r_v33_source_field_allowed(
            "strategy.research_basis[0]"
        )
        is False
    )


def test_sealed_v32_categories_do_not_get_reinterpreted_by_v33():
    finding = _status(
        "No Japão, sheet mask é parte da rotina diária",
        "ingredients/contents/format",
        "copy.pt-BR.caption",
    )

    assert finding.evidence_status == "UNSUPPORTED"


def test_prompt_versions_bumped_for_v33():
    assert PROMPT_VERSIONS["campaign_copy"].version == "1.3.0"
    assert PROMPT_VERSIONS["carousel_plan"].version == "1.3.0"
    assert PROMPT_VERSIONS["master_campaign_concept"].version == "1.4.0"


def test_cultural_market_context_hard_stop_is_shared():
    text = orchestrator._claims_boundary_instruction()

    for phrase in (
        "CULTURAL/MARKET CONTEXT HARD STOP",
        "cultural norms",
        "consumer behavior or prevalence",
        "pharmacy presence or shelf prevalence",
        "Hanna Japan",
    ):
        assert phrase in text


def test_strategy_prompt_forbids_research_as_market_fact():
    source = inspect.getsource(
        orchestrator.run_strategy_stage
    )

    assert "RESEARCH-TO-FACT HARD STOP" in source
    assert "cultural norms" in source
    assert "pharmacy presence" in source
    assert "brand-role claims" in source


def test_final_wrapper_applies_v33(monkeypatch):
    async def fake_previous(
        *args,
        **kwargs,
    ):
        return claims_audit.ClaimAuditResult(
            findings=[
                _finding(
                    "LuLuLun Hydra EX Mask 7 Sheets",
                    "product identification",
                    "ai_extracted_candidate",
                )
            ]
        )

    monkeypatch.setattr(
        claims_audit,
        "_build6r_augment_before_v33",
        fake_previous,
    )

    result = asyncio.run(
        claims_audit.augment_with_ai_extraction(
            None,
            fields={},
            verified=_verified(),
            brand=None,
            model="synthetic",
            existing=claims_audit.ClaimAuditResult(
                findings=[]
            ),
        )
    )

    assert (
        result.findings[0].evidence_status
        == "SUPPORTED"
    )
