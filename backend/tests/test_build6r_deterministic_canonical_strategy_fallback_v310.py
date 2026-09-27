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

    def model_copy(self, *, update):
        payload = self.model_dump()
        payload.update(update)
        return type(self)(**payload)


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


def _unsupported_model_candidate():
    return _Candidate(
        angle=(
            "Raio-X editorial com ingredientes listados pelo fabricante e "
            "linguagem de dossie tecnico."
        ),
        key_message=(
            "Segundo o fabricante, a formula demonstra sofisticacao da composicao."
        ),
        insight="Muita gente pode achar esse formato dificil de entender.",
        reason_this_should_work=(
            "Pode tornar o produto mais acessivel e fortalecer a sensacao de clareza."
        ),
        research_basis=[
            "External research context: materiais da LuLuLun destacam tecnologia avancada."
        ],
    )


def test_v310_fallback_is_deterministic():
    candidate = _unsupported_model_candidate()
    verified = _verified()

    first = orchestrator._build6r_v310_deterministic_canonical_strategy_fallback(
        [candidate],
        verified,
    )
    second = orchestrator._build6r_v310_deterministic_canonical_strategy_fallback(
        [candidate],
        verified,
    )

    assert first.model_dump() == second.model_dump()


def test_v310_requires_canonical_source_presence():
    empty = SimpleNamespace(
        verified_description="",
        verified_usage="",
        verified_size="",
        verified_variant="",
        verified_features=[],
        verified_claims=[],
        verified_ingredients=[],
    )

    try:
        orchestrator._build6r_v310_deterministic_canonical_strategy_fallback(
            [_unsupported_model_candidate()],
            empty,
        )
    except orchestrator.PreVisualClaimGroundingError as exc:
        assert "PREVISUAL_DETERMINISTIC_FALLBACK_NO_SAFE_CANONICAL_FACTS" in str(exc)
    else:
        raise AssertionError("Expected fail-closed canonical-source guard.")


def test_v310_fallback_replaces_all_strategy_fields_conservatively():
    fallback = orchestrator._build6r_v310_deterministic_canonical_strategy_fallback(
        [_unsupported_model_candidate()],
        _verified(),
    )

    assert fallback.insight == (
        "Organizar a narrativa visual usando apenas informacoes verificadas."
    )
    assert fallback.angle == (
        "Tratamento visual educativo e simples, sem adicionar alegacoes "
        "alem do que foi verificado."
    )
    assert fallback.key_message == (
        "Apresentar somente informacoes verificadas do produto, "
        "sem extrapolacao."
    )
    assert fallback.reason_this_should_work == (
        "Estrutura criada para manter a comunicacao clara e limitada "
        "ao que foi verificado."
    )
    assert fallback.research_basis == []


def test_v310_fallback_is_canonical_bounded_without_raw_fact_injection():
    fallback = orchestrator._build6r_v310_deterministic_canonical_strategy_fallback(
        [_unsupported_model_candidate()],
        _verified(),
    )
    combined = " ".join(
        [
            fallback.insight,
            fallback.angle,
            fallback.key_message,
            fallback.reason_this_should_work,
            " ".join(fallback.research_basis),
        ]
    ).lower()

    assert "informacoes verificadas" in combined
    assert "7 sheets" not in combined
    assert "150 ml" not in combined
    assert "lululun" not in combined
    assert "hydra ex" not in combined
    assert "colorant-free" not in combined
    assert "fragrance-free" not in combined
    assert "manufacturer" not in combined
    assert "fabricante" not in combined
    assert "label" not in combined
    assert "materials" not in combined


def test_v310_fallback_removes_observed_v39_live_failure_vocabulary():
    fallback = orchestrator._build6r_v310_deterministic_canonical_strategy_fallback(
        [_unsupported_model_candidate()],
        _verified(),
    )
    combined = " ".join(
        [
            fallback.insight,
            fallback.angle,
            fallback.key_message,
            fallback.reason_this_should_work,
            " ".join(fallback.research_basis),
        ]
    ).lower()

    for forbidden in (
        "segundo o fabricante",
        "listados pelo fabricante",
        "materiais da lululun",
        "sofisticacao",
        "mais acessivel",
        "sensacao de clareza",
        "muita gente",
    ):
        assert forbidden not in combined


def test_v310_fallback_passes_sealed_v38_v37_grounding_path():
    fallback = orchestrator._build6r_v310_deterministic_canonical_strategy_fallback(
        [_unsupported_model_candidate()],
        _verified(),
    )

    grounded, rejected = (
        orchestrator._build6r_v38_filter_grounded_strategy_candidates(
            [fallback],
            _verified(),
        )
    )

    assert grounded == [fallback], rejected
    assert rejected == []


def test_v310_helper_is_zero_cost_and_provider_free():
    source = inspect.getsource(
        orchestrator._build6r_v310_deterministic_canonical_strategy_fallback
    )

    for forbidden in (
        "generate_structured",
        "generate_image",
        "edit_image",
        "run_research",
        "classify_novelty(",
        "record_stage_usage",
        "_audit(",
        "db.commit",
        "httpx",
        "requests.",
        "socket.",
        "OpenAI",
    ):
        assert forbidden not in source


def test_v310_fallback_triggers_only_after_all_model_candidates_are_rejected():
    source = inspect.getsource(orchestrator.run_strategy_stage)

    initial_filter = source.index(
        "_build6r_v38_filter_grounded_strategy_candidates("
    )
    empty_guard = source.index(
        "if not grounded_strategy_candidates:",
        initial_filter,
    )
    fallback_build = source.index(
        "_build6r_v310_deterministic_canonical_strategy_fallback(",
        empty_guard,
    )

    assert initial_filter < empty_guard < fallback_build


def test_v310_fallback_is_revalidated_by_v38_before_novelty():
    source = inspect.getsource(orchestrator.run_strategy_stage)

    fallback_build = source.index(
        "_build6r_v310_deterministic_canonical_strategy_fallback("
    )
    fallback_filter = source.index(
        "_build6r_v38_filter_grounded_strategy_candidates(",
        fallback_build,
    )
    novelty = source.index("classify_novelty(", fallback_filter)

    assert fallback_build < fallback_filter < novelty


def test_v310_preserves_single_paid_strategy_generation_call():
    source = inspect.getsource(orchestrator.run_strategy_stage)

    assert source.count("ai_provider.generate_structured(") == 1
    assert source.count(
        "_build6r_v39_field_specific_strategy_generation_contract()"
    ) == 1


def test_v310_preserves_v39_generation_contract_and_v38_filter():
    source = inspect.getsource(orchestrator.run_strategy_stage)

    assert "_build6r_v39_field_specific_strategy_generation_contract()" in source
    assert source.count(
        "_build6r_v38_filter_grounded_strategy_candidates("
    ) == 2
    assert "autopilot.strategy_candidates_grounding_filtered" in source
    assert "autopilot.strategy_deterministic_fallback" in source


def test_v310_preserves_existing_all_unsupported_fail_closed_marker():
    source = inspect.getsource(orchestrator.run_strategy_stage)

    assert "PREVISUAL_ALL_STRATEGY_CANDIDATES_UNSUPPORTED" in source
    assert "PREVISUAL_DETERMINISTIC_FALLBACK_NO_SAFE_CANONICAL_FACTS" in inspect.getsource(
        orchestrator._build6r_v310_deterministic_canonical_strategy_fallback
    )


def test_v310_preserves_novelty_and_final_containment_order():
    source = inspect.getsource(orchestrator.run_strategy_stage)

    fallback_filter = source.index(
        "_build6r_v38_filter_grounded_strategy_candidates(",
        source.index("_build6r_v310_deterministic_canonical_strategy_fallback("),
    )
    novelty = source.index("classify_novelty(", fallback_filter)
    containment = source.index(
        "_build6r_v35_enforce_strategy_containment(",
        novelty,
    )
    generated_gate = source.index(
        "_enforce_generated_claim_grounding_gate(",
        containment,
    )

    assert fallback_filter < novelty < containment < generated_gate
