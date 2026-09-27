from __future__ import annotations

import ast
import inspect
from pathlib import Path

import app.services.orchestrator as orchestrator


ROOT = Path(__file__).resolve().parents[1]

ORCH = (
    ROOT
    / "app"
    / "services"
    / "orchestrator.py"
)

RUNNER = (
    ROOT
    / "scripts"
    / "run_live_acceptance.py"
)


def _run_copy_source() -> str:
    return inspect.getsource(
        orchestrator.run_copy_stage
    )


def test_skip_carousel_plan_defaults_false_for_normal_campaigns():

    field = (
        orchestrator
        .AutopilotConfig
        .__dataclass_fields__[
            "skip_carousel_plan"
        ]
    )

    assert field.default is False


def test_runner_does_not_enable_legacy_skip_only_for_explicit_premium_hero_block():

    text = RUNNER.read_text(
        encoding="utf-8"
    )

    tree = ast.parse(
        text
    )

    premium_blocks = []

    for node in ast.walk(
        tree
    ):

        if not isinstance(
            node,
            ast.If,
        ):
            continue

        test_text = (
            ast.get_source_segment(
                text,
                node.test,
            )
            or ""
        )

        if (
            "args.premium_hero_only"
            in test_text
        ):
            premium_blocks.append(
                node
            )

    assert premium_blocks

    skip_assignments = []

    hero_true_assignments = []

    for node in premium_blocks:

        for child in ast.walk(
            node
        ):

            if not isinstance(
                child,
                ast.Assign,
            ):
                continue

            for target in child.targets:

                if not isinstance(
                    target,
                    ast.Attribute,
                ):
                    continue

                if (
                    target.attr
                    == "skip_carousel_plan"
                ):
                    skip_assignments.append(
                        child
                    )

                if (
                    target.attr
                    == "hero_only"
                    and isinstance(
                        child.value,
                        ast.Constant,
                    )
                    and child.value.value
                    is True
                ):
                    hero_true_assignments.append(
                        child
                    )

    assert len(
        skip_assignments
    ) == 0

    assert len(
        hero_true_assignments
    ) == 1



def test_hero_bypass_precedes_all_carousel_model_work():

    source = _run_copy_source()

    branch = source.index(
        "if config.skip_carousel_plan:"
    )

    planning = source.index(
        'f"Planning the carousel ({language})"',
        branch,
    )

    generation = source.index(
        "schema=CarouselPlan",
        branch,
    )

    prompt_usage = source.index(
        'purpose="carousel_plan"',
        branch,
    )

    stage_usage = source.index(
        'operation="carousel_plan"',
        branch,
    )

    assert (
        branch
        < planning
        < generation
        < prompt_usage
        < stage_usage
    )


def test_hero_bypass_is_one_deterministic_existing_fallback_slide():

    source = _run_copy_source()

    start = source.index(
        "if config.skip_carousel_plan:"
    )

    end = source.index(
        'f"Planning the carousel ({language})"',
        start,
    )

    branch = source[
        start:
        end
    ]

    assert (
        "planned_slides_by_language[language] = ["
        in branch
    )

    assert (
        "SlidePlanFallback("
        in branch
    )

    assert (
        "headline=campaign_copy.headline"
        in branch
    )

    assert (
        "body=campaign_copy.supporting_copy"
        in branch
    )

    assert (
        "cta=campaign_copy.cta"
        in branch
    )

    assert (
        "continue"
        in branch
    )


def test_hero_bypass_contains_no_carousel_ai_or_accounting_call():

    source = _run_copy_source()

    start = source.index(
        "if config.skip_carousel_plan:"
    )

    end = source.index(
        'f"Planning the carousel ({language})"',
        start,
    )

    branch = source[
        start:
        end
    ]

    assert (
        "generate_structured("
        not in branch
    )

    assert (
        "schema=CarouselPlan"
        not in branch
    )

    assert (
        'purpose="carousel_plan"'
        not in branch
    )

    assert (
        'operation="carousel_plan"'
        not in branch
    )

    assert (
        "record_prompt_usage("
        not in branch
    )

    assert (
        "record_stage_usage("
        not in branch
    )


def test_normal_carousel_path_remains_intact():

    source = _run_copy_source()

    assert (
        "schema=CarouselPlan"
        in source
    )

    assert (
        'purpose="carousel_plan"'
        in source
    )

    assert (
        'operation="carousel_plan"'
        in source
    )

    assert (
        "carousel_plan.slides[:effective_max_slides]"
        in source
    )


def test_one_slide_target_alone_does_not_trigger_the_bypass():

    source = _run_copy_source()

    assert (
        "if target_slide_count == 1"
        not in source
    )

    assert (
        "if config.max_slides == 1"
        not in source
    )

    assert (
        "if config.skip_carousel_plan:"
        in source
    )


def test_persisted_creative_slide_contract_is_preserved():

    source = _run_copy_source()

    assert (
        "_slide_plan_to_dict(slide)"
        in source
    )

    assert (
        "planned_slides_by_language"
        in source
    )

    visual_source = inspect.getsource(
        orchestrator.run_visuals_stage
    )

    assert (
        'creative_variant["carousel_plan"]["slides"]'
        in visual_source
        or (
            'creative_variant.get("carousel_plan", {})'
            in visual_source
        )
    )


def test_existing_premium_image_scope_remains_one_primary_masked_visual():

    text = RUNNER.read_text(
        encoding="utf-8"
    )

    required = (
        "config.max_slides = 1",
        "config.hero_only = True",
        "config.use_ai_background = False",
        "config.use_masked_scene_edit = True",
        "config.require_masked_scene_edit_success = True",
        "config.render_platform_variants = False",
    )

    for token in required:
        assert token in text

    # Premium hero now owns the deterministic one-slide planning
    # path and therefore must not activate the older shortcut.
    assert (
        "config.skip_carousel_plan = True"
        not in text
    )

