from __future__ import annotations

import ast
import inspect
from types import SimpleNamespace

import app.services.claims_audit as claims_audit
import app.services.orchestrator as orchestrator


LIVE_V36_STRATEGY_CORPUS = (
    (
        "strategy.insight",
        "Muita gente v\u00ea sheet mask como algo \u201cfofo de selfie\u201d, "
        "mas n\u00e3o faz ideia de como esse tipo de produto \u00e9 pensado, "
        "que tipo de ingredientes pode trazer e como pode entrar na rotina "
        "no lugar de um t\u00f4nico.",
    ),
    (
        "strategy.angle",
        "\u201cGuia de inicia\u00e7\u00e3o \u00e0 sheet mask japonesa\u201d: "
        "use a LuLuLun Hydra EX 7 Sheets como exemplo concreto para ensinar "
        "o que \u00e9 uma sheet mask, como funciona o formato multi-sheet e "
        "apresentar os principais ingredientes listados pela fabricante, "
        "sem prometer resultados.",
    ),
    (
        "strategy.key_message",
        "\u201cEste \u00e9 o formato de sheet mask que voc\u00ea v\u00ea nas "
        "prateleiras japonesas \u2014 um pouch com 7 m\u00e1scaras e 150 mL "
        "de ess\u00eancia, com uma f\u00f3rmula sem corantes, sem fragr\u00e2ncia, "
        "sem \u00f3leo mineral e sem \u00e1lcool, e ingredientes de cuidado de "
        "pele como exossomos, ceramidas e derivados de vitamina C.\u201d",
    ),
    (
        "strategy.research_basis[1]",
        "A curiosidade em torno de rotinas japonesas e de ingredientes "
        "diferentes serve como gatilho criativo para detalhar os ingredientes "
        "listados (exossomos, ceramidas, arbutin, derivados de vitamina C, etc.) "
        "sem extrapolar benef\u00edcios.",
    ),
)


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
        verified_claims=[
            "7-sheet pouch containing 150 mL of essence",
            (
                "Contains human adipose-derived mesenchymal cell exosomes as a "
                "manufacturer-listed skin-conditioning ingredient; manufacturer "
                "states stem cells are not contained"
            ),
            "Contains glutathione, arbutin, and the vitamin C derivative ascorbyl palmitate",
            (
                "Contains Ceramide AP, Ceramide NP, atelocollagen, "
                "hydroxypropyltrimonium hyaluronate, and human recombinant oligopeptide-1"
            ),
            (
                "Manufacturer states the formula is colorant-free, fragrance-free, "
                "mineral-oil-free, and alcohol-free"
            ),
            "Manufacturer describes the sheet as a Melty Feel Sheet",
        ],
    )


def test_exact_live_v36_four_finding_corpus_is_retained_and_fail_closed():
    assert len(LIVE_V36_STRATEGY_CORPUS) == 4

    for _path, text in LIVE_V36_STRATEGY_CORPUS:
        assert claims_audit._build6r_v35_strategy_product_fact_violation(
            text,
            _verified(),
        )


def test_v36_generation_instruction_blocks_each_live_failure_class():
    instruction = (
        orchestrator
        ._build6r_v36_strategy_generation_grounding_instruction()
    )

    for marker in (
        "STRATEGY-GENERATION GROUNDING HARD STOP",
        "consumer behavior",
        "cultural norms",
        "retail presence",
        "pharmacy presence",
        "market prevalence",
        "brand-role claims",
        "Japanese",
        "Japanese shelves",
        "Japanese pharmacies",
        "research_basis",
        "MIXED-FIELD HARD STOP",
        "every factual clause",
        "rewrite the whole field",
    ):
        assert marker in instruction


def test_v36_strategy_prompt_uses_generation_guard_exactly_once():
    source = inspect.getsource(
        orchestrator.run_strategy_stage
    )

    assert source.count(
        "_build6r_v36_strategy_generation_grounding_instruction()"
    ) == 1

    assert (
        source.index(
            "_claims_boundary_instruction()"
        )
        <
        source.index(
            "_sparse_fact_grounding_instruction()"
        )
        <
        source.index(
            "_build6r_v36_strategy_generation_grounding_instruction()"
        )
    )


def test_v36_user_prompt_explicitly_demotes_research_to_creative_context():
    source = inspect.getsource(
        orchestrator.run_strategy_stage
    )

    for marker in (
        "V3.6 FINAL STRATEGY INSTRUCTION",
        "creative direction only, never factual grounding",
        "VERIFIED PRODUCT FACTS",
        "Do not infer cultural, origin, retail, market, consumer-behavior",
    ):
        assert marker in source


def test_v36_preserves_v35_containment_and_single_strategy_function():
    module_source = inspect.getsource(
        orchestrator
    )
    module_tree = ast.parse(
        module_source
    )

    strategy_defs = [
        node
        for node in module_tree.body
        if isinstance(
            node,
            (
                ast.FunctionDef,
                ast.AsyncFunctionDef,
            ),
        )
        and node.name == "run_strategy_stage"
    ]

    assert len(strategy_defs) == 1

    source = inspect.getsource(
        orchestrator.run_strategy_stage
    )

    assert source.count(
        "_build6r_v35_enforce_strategy_containment("
    ) == 1

    assert (
        source.index(
            "_build6r_v35_enforce_strategy_containment("
        )
        <
        source.index(
            "_enforce_generated_claim_grounding_gate("
        )
        <
        source.index(
            "campaign.audience = accepted.audience"
        )
    )


def test_v36_preserves_sealed_strategy_source_contracts():
    source = inspect.getsource(
        orchestrator.run_strategy_stage
    )

    assert source.count(
        "_sparse_fact_grounding_instruction()"
    ) == 1

    for marker in (
        "RESEARCH-TO-FACT HARD STOP",
        "cultural norms",
        "pharmacy presence",
        "brand-role claims",
        "resolve_verified_product_facts(db, product)",
        "strategy_type_operational_evidence_failed",
        "PREVISUAL_NO_VERIFIED_OPERATIONAL_STRATEGY",
        "run_research(",
    ):
        assert marker in source

    assert (
        source.index(
            "strategy_type_operational_evidence_failed"
        )
        <
        source.index(
            "run_research("
        )
    )


def test_v36_instruction_is_zero_cost_and_provider_free():
    source = inspect.getsource(
        orchestrator
        ._build6r_v36_strategy_generation_grounding_instruction
    )

    for forbidden in (
        "generate_structured",
        "generate_image",
        "edit_image",
        "OpenAI",
        "httpx",
        "requests.",
        "socket.",
        "run_research",
    ):
        assert forbidden not in source
