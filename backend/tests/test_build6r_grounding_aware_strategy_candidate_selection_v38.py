from __future__ import annotations

import inspect
from types import SimpleNamespace

import app.services.orchestrator as orchestrator


class _Candidate:
    def __init__(
        self,
        *,
        angle,
        key_message="LuLuLun Hydra EX Mask 7 Sheets: 7 sheets / 150 mL de essencia",
        insight="Estrutura educativa sobre o produto.",
        reason_this_should_work="Estrutura educativa sem prometer resultados especificos.",
        research_basis=None,
    ):
        self.angle = angle
        self.key_message = key_message
        self.insight = insight
        self.reason_this_should_work = reason_this_should_work
        self.research_basis = list(research_basis or [])

    def model_dump(self):
        return {
            "angle": self.angle,
            "key_message": self.key_message,
            "insight": self.insight,
            "reason_this_should_work": self.reason_this_should_work,
            "research_basis": self.research_basis,
        }


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


def test_v38_filter_skips_unsupported_and_preserves_grounded_order():
    unsupported = _Candidate(
        angle="Guia de iniciacao a sheet mask japonesa.",
    )
    grounded_one = _Candidate(
        angle="Como usar a mascara seguindo o modo de uso do fabricante.",
    )
    grounded_two = _Candidate(
        angle="Como usar a mascara seguindo o modo de uso do fabricante.",
    )

    grounded, rejected = (
        orchestrator._build6r_v38_filter_grounded_strategy_candidates(
            [unsupported, grounded_one, grounded_two],
            _verified(),
        )
    )

    assert grounded == [grounded_one, grounded_two]
    assert len(rejected) == 1
    assert rejected[0][0] == 0
    assert rejected[0][1]


def test_v38_all_unsupported_returns_no_grounded_candidates():
    candidates = [
        _Candidate(angle="Sheet mask japonesa vendida nas farmacias japonesas."),
        _Candidate(
            angle="Rotina japonesa popular com LuLuLun.",
            insight="Muita gente no Brasil procura esse tipo de rotina japonesa.",
        ),
    ]

    grounded, rejected = (
        orchestrator._build6r_v38_filter_grounded_strategy_candidates(
            candidates,
            _verified(),
        )
    )

    assert grounded == []
    assert len(rejected) == 2


def test_v38_explicit_research_context_can_survive_filter():
    candidate = _Candidate(
        angle="Como usar a mascara seguindo o modo de uso do fabricante.",
        research_basis=[
            'Menções a exossomos, glutationa, vitamina C derivada, ceramidas, peptídeos e ácido hialurônico em conteúdos de skincare indicam que essas palavras podem gerar curiosidade — o que orienta a ideia de ‘guia de rótulo’, sem atribuir a essas substâncias efeitos específicos na comunicação da campanha.'
        ],
    )

    research_text = candidate.research_basis[0]

    assert orchestrator._build6r_v37_explicit_research_context_allowed(
        "strategy.research_basis[0]",
        research_text,
    )
    assert not orchestrator._build6r_v37_strategy_field_violation(
        "strategy.research_basis[0]",
        research_text,
        _verified(),
    )

    grounded, rejected = (
        orchestrator._build6r_v38_filter_grounded_strategy_candidates(
            [candidate],
            _verified(),
        )
    )

    assert grounded == [candidate]
    assert rejected == []


def test_v38_direct_product_claim_inside_research_context_still_rejects():
    candidate = _Candidate(
        angle="Como usar a mascara seguindo o modo de uso do fabricante.",
        research_basis=[
            "Pesquisa indica que LuLuLun Hydra EX e bestseller no Japao."
        ],
    )

    grounded, rejected = (
        orchestrator._build6r_v38_filter_grounded_strategy_candidates(
            [candidate],
            _verified(),
        )
    )

    assert grounded == []
    assert len(rejected) == 1


def test_v38_filter_is_zero_cost_and_provider_free():
    source = inspect.getsource(
        orchestrator._build6r_v38_filter_grounded_strategy_candidates
    )

    assert "_build6r_v37_strategy_containment_failures(" in source
    for forbidden in (
        "generate_structured",
        "generate_image",
        "edit_image",
        "run_research",
        "classify_novelty(",
        "httpx",
        "requests.",
        "socket.",
        "OpenAI",
    ):
        assert forbidden not in source


def test_v38_grounding_filter_runs_before_legacy_novelty_loop():
    source = inspect.getsource(orchestrator.run_strategy_stage)

    filter_pos = source.index(
        "_build6r_v38_filter_grounded_strategy_candidates("
    )
    loop_pos = source.index(
        "for candidate in grounded_strategy_candidates:"
    )
    novelty_pos = source.index(
        "classify_novelty(",
        loop_pos,
    )

    assert filter_pos < loop_pos < novelty_pos


def test_v38_preserves_stage3d_research_and_novelty_source_contract():
    source = inspect.getsource(orchestrator.run_strategy_stage)

    assert "run_research(" in source
    assert "classify_novelty(" in source


def test_v38_preserves_single_strategy_generation_call_and_final_containment():
    source = inspect.getsource(orchestrator.run_strategy_stage)

    assert source.count("ai_provider.generate_structured(") == 1
    assert source.count(
        "_build6r_v35_enforce_strategy_containment("
    ) == 1
    assert (
        source.index("_build6r_v38_filter_grounded_strategy_candidates(")
        < source.index("classify_novelty(")
        < source.index("_build6r_v35_enforce_strategy_containment(")
        < source.index("_enforce_generated_claim_grounding_gate(")
    )


def test_v38_all_unsupported_failure_marker_is_in_strategy_stage():
    source = inspect.getsource(orchestrator.run_strategy_stage)

    assert "PREVISUAL_ALL_STRATEGY_CANDIDATES_UNSUPPORTED" in source
    assert "autopilot.strategy_candidates_grounding_filtered" in source
