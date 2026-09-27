from __future__ import annotations

import inspect
from types import SimpleNamespace

import pytest

import app.services.claims_audit as claims_audit
import app.services.orchestrator as orchestrator


LIVE_V37_STRATEGY_CORPUS = (('strategy.insight', 'Muita gente se interessa por máscaras faciais, mas trava quando lê rótulos cheios de termos técnicos — especialmente quando aparecem nomes como exossomos, peptídeos, ceramidas e derivados de vitamina C.', True), ('strategy.angle', '“Decifrando o rótulo” — transformar a LuLuLun Hydra EX 7-sheet pouch em exemplo didático e visual para explicar, em linguagem simples, o que está escrito na própria embalagem e como esse tipo de fórmula pode entrar na rotina, sem prometer resultados específicos.', True), ('strategy.key_message', 'LuLuLun Hydra EX é uma máscara em tecido em pouch com 7 unidades e 150 mL de essência, formulada com uma combinação de ingredientes listados no rótulo — como exossomos de origem adiposa, glutationa, arbutina, derivado de vitamina C, ceramidas, atelocolágeno e ácido hialurônico modificado — em uma folha descrita pelo fabricante como Melty Feel Sheet, sem corante, fragrância, óleo mineral nem álcool.', True), ('strategy.reason_this_should_work', 'O foco na leitura e na tradução do rótulo reforça autoridade e confiança: em vez de prometer efeitos, Hanna mostra o produto de perto, destaca a pouch de 7 folhas com 150 mL de essência e usa os próprios nomes de ingredientes e características confirmadas (como ser colorant-free, fragrance-free, mineral-oil-free e alcohol-free) para educar. Isso atende quem busca informação objetiva e desperta curiosidade sobre a categoria de máscaras em tecido sem recorrer a hype.', True), ('strategy.research_basis[1]', 'Menções a exossomos, glutationa, vitamina C derivada, ceramidas, peptídeos e ácido hialurônico em conteúdos de skincare indicam que essas palavras podem gerar curiosidade — o que orienta a ideia de ‘guia de rótulo’, sem atribuir a essas substâncias efeitos específicos na comunicação da campanha.', False))


def _verified():
    return SimpleNamespace(
        verified_description=(
            "LuLuLun Hydra EX facial sheet mask, exact 7-sheet pouch variant. "
            "Manufacturer sales name: Face Mask LuLuLun EX 1FS."
        ),
        verified_usage=(
            "Manufacturer usage guidance: unfold the mask and fit it around the "
            "eyes and mouth, press out trapped air, lift the cheek cut sections "
            "along the face line, then press the whole mask into place with the "
            "palms. After removal, the manufacturer suggests folding the mask "
            "for wiping/light patting and following with an emulsion or cream. "
            "Manufacturer describes it as usable morning or evening in place of toner."
        ),
        verified_size="7 sheets / essence 150 mL",
        verified_variant="Face Mask LuLuLun EX 1FS - 7-sheet pouch",
        verified_price="",
        verified_availability="",
        verified_country_of_origin="",
        verified_ingredients=[
            "Human adipose-derived mesenchymal cell exosomes (manufacturer-listed skin-conditioning ingredient; manufacturer states stem cells are not contained)",
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
        verified_claims=[
            "7-sheet pouch containing 150 mL of essence",
            "Contains human adipose-derived mesenchymal cell exosomes as a manufacturer-listed skin-conditioning ingredient; manufacturer states stem cells are not contained",
            "Contains glutathione, arbutin, and the vitamin C derivative ascorbyl palmitate",
            "Contains Ceramide AP, Ceramide NP, atelocollagen, hydroxypropyltrimonium hyaluronate, and human recombinant oligopeptide-1",
            "Manufacturer states the formula is colorant-free, fragrance-free, mineral-oil-free, and alcohol-free",
            "Manufacturer describes the sheet as a Melty Feel Sheet",
        ],
    )


def test_v37_live_five_field_corpus_has_expected_field_semantics():
    assert len(LIVE_V37_STRATEGY_CORPUS) == 5

    for path, text, expected_violation in LIVE_V37_STRATEGY_CORPUS:
        assert (
            orchestrator._build6r_v37_strategy_field_violation(
                path,
                text,
                _verified(),
            )
            is expected_violation
        )


def test_v37_explicit_research_context_is_not_product_fact_evidence():
    path, text, _expected = LIVE_V37_STRATEGY_CORPUS[-1]

    assert orchestrator._build6r_v37_explicit_research_context_allowed(
        path,
        text,
    )

    assert not orchestrator._build6r_v37_strategy_field_violation(
        path,
        text,
        _verified(),
    )


def test_v37_direct_product_claim_inside_research_basis_is_still_audited():
    text = (
        "Pesquisa indica que LuLuLun Hydra EX e bestseller no Japao."
    )

    assert not orchestrator._build6r_v37_explicit_research_context_allowed(
        "strategy.research_basis[0]",
        text,
    )

    assert orchestrator._build6r_v37_strategy_field_violation(
        "strategy.research_basis[0]",
        text,
        _verified(),
    )


def test_v37_clearly_nonfactual_strategy_rationale_is_allowed():
    text = (
        "Estrutura educativa sem prometer resultados especificos; "
        "foco em clareza visual e organizacao da mensagem."
    )

    assert not orchestrator._build6r_v37_strategy_field_violation(
        "strategy.reason_this_should_work",
        text,
        _verified(),
    )


def test_v37_unsupported_consumer_rationale_remains_fail_closed():
    text = (
        "A abordagem atende quem busca informacao objetiva e desperta curiosidade."
    )

    assert orchestrator._build6r_v37_strategy_field_violation(
        "strategy.reason_this_should_work",
        text,
        _verified(),
    )


def test_v37_unsupported_provenance_remains_fail_closed():
    for path, text in (
        (
            "strategy.angle",
            "Explicar o que esta escrito na propria embalagem da LuLuLun Hydra EX.",
        ),
        (
            "strategy.key_message",
            "LuLuLun Hydra EX traz ingredientes listados no rotulo.",
        ),
    ):
        assert orchestrator._build6r_v37_strategy_field_violation(
            path,
            text,
            _verified(),
        )


def test_v37_canonical_strategy_claim_is_still_allowed():
    assert not orchestrator._build6r_v37_strategy_field_violation(
        "strategy.key_message",
        "LuLuLun Hydra EX Mask 7 Sheets: 7 sheets / 150 mL de essencia",
        _verified(),
    )


def test_v37_enforcer_routes_through_field_aware_failures():
    source = inspect.getsource(
        orchestrator._build6r_v35_enforce_strategy_containment
    )

    assert "_build6r_v37_strategy_containment_failures(" in source
    assert "_build6r_v35_strategy_containment_failures(" not in source


def test_v37_preserves_v35_and_v36_strategy_integration_contracts():
    source = inspect.getsource(
        orchestrator.run_strategy_stage
    )

    assert source.count(
        "_build6r_v35_enforce_strategy_containment("
    ) == 1
    assert source.count(
        "_build6r_v36_strategy_generation_grounding_instruction()"
    ) == 1
    assert source.count(
        "_sparse_fact_grounding_instruction()"
    ) == 1

    assert (
        source.index("_build6r_v35_enforce_strategy_containment(")
        < source.index("_enforce_generated_claim_grounding_gate(")
        < source.index("campaign.audience = accepted.audience")
    )


def test_v37_claims_layer_is_still_sealed_v35_primitive():
    source = inspect.getsource(
        orchestrator._build6r_v37_strategy_field_violation
    )

    assert "_build6r_v35_strategy_product_fact_violation" in source
    assert "augment_with_ai_extraction" not in source


def test_v37_helpers_are_zero_cost_and_provider_free():
    names = (
        "_build6r_v37_normalized_strategy_text",
        "_build6r_v37_explicit_research_context_allowed",
        "_build6r_v37_unscoped_context_violation",
        "_build6r_v37_strategy_field_violation",
        "_build6r_v37_strategy_containment_failures",
    )

    source = "\n".join(
        inspect.getsource(getattr(orchestrator, name))
        for name in names
    )

    for forbidden in (
        "generate_structured",
        "generate_image",
        "edit_image",
        "run_research",
        "httpx",
        "requests.",
        "socket.",
        "OpenAI",
    ):
        assert forbidden not in source
