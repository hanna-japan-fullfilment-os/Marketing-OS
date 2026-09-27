from __future__ import annotations

import ast
from pathlib import Path

from app.services import orchestrator


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


def _source(path):
    return path.read_text(
        encoding="utf-8-sig"
    )


def _function(tree, name):
    matches = [
        node
        for node in tree.body
        if isinstance(
            node,
            ast.AsyncFunctionDef,
        )
        and node.name == name
    ]

    assert len(matches) == 1

    return matches[0]


def _call_name(node):
    if isinstance(node.func, ast.Name):
        return node.func.id

    if isinstance(node.func, ast.Attribute):
        return node.func.attr

    return ""


def _kw(node, name):
    for kw in node.keywords:
        if (
            kw.arg == name
            and isinstance(
                kw.value,
                ast.Constant,
            )
        ):
            return kw.value.value

    return None


def _schema(node):
    for kw in node.keywords:
        if (
            kw.arg == "schema"
            and isinstance(
                kw.value,
                ast.Name,
            )
        ):
            return kw.value.id

    return None


def _model_calls(nodes):
    return sum(
        1
        for root in nodes
        for node in ast.walk(root)
        if isinstance(node, ast.Call)
        and _call_name(node)
        == "generate_structured"
        and _schema(node)
        == "CarouselPlan"
    )


def _usage_calls(nodes):
    total = 0

    for root in nodes:
        for node in ast.walk(root):
            if not isinstance(node, ast.Call):
                continue

            if (
                _call_name(node)
                == "record_prompt_usage"
                and _kw(
                    node,
                    "purpose",
                )
                == "carousel_plan"
            ):
                total += 1

            if (
                _call_name(node)
                == "record_stage_usage"
                and _kw(
                    node,
                    "operation",
                )
                == "carousel_plan"
            ):
                total += 1

    return total


def _branches():
    source = _source(ORCH)

    tree = ast.parse(source)

    fn = _function(
        tree,
        "run_copy_stage",
    )

    hero = []

    usage = []

    for node in ast.walk(fn):
        if not isinstance(node, ast.If):
            continue

        condition = (
            ast.get_source_segment(
                source,
                node.test,
            )
            or ""
        ).strip()

        if condition == "config.hero_only":
            hero.append(node)

        if condition == "not config.hero_only":
            usage.append(node)

    assert len(hero) == 1
    assert len(usage) == 1

    return (
        source,
        fn,
        hero[0],
        usage[0],
    )


def test_hero_only_defaults_false():
    field = (
        orchestrator
        .AutopilotConfig
        .__dataclass_fields__[
            "hero_only"
        ]
    )

    assert field.default is False


def test_hero_only_makes_zero_carousel_model_calls():
    _source_text, _fn, hero, _usage = _branches()

    assert _model_calls(
        hero.body
    ) == 0

    assert _model_calls(
        hero.orelse
    ) == 2


def test_carousel_usage_accounting_is_normal_path_only():
    _source_text, fn, hero, usage = _branches()

    assert _usage_calls(
        hero.body
    ) == 0

    assert _usage_calls(
        usage.body
    ) == 2

    assert _usage_calls(
        fn.body
    ) == 2


def test_common_planned_slides_remains_after_hero_branch():
    source, fn, hero, usage = _branches()

    assignments = []

    for node in ast.walk(fn):
        if not isinstance(node, ast.Assign):
            continue

        if len(node.targets) != 1:
            continue

        target = node.targets[0]

        if (
            isinstance(target, ast.Name)
            and target.id
            == "planned_slides"
        ):
            assignments.append(node)

    assert len(assignments) == 1

    planned = assignments[0]

    assert (
        hero.end_lineno
        < planned.lineno
        < usage.lineno
    )


def test_deterministic_hero_shape_is_one_slide():
    source, _fn, hero, _usage = _branches()

    segment = (
        ast.get_source_segment(
            source,
            hero,
        )
        or ""
    )

    for token in (
        "CarouselPlan(",
        "SlidePlan(",
        "slide_number=1",
        'purpose="hero"',
        "headline=campaign_copy.headline",
        "body=campaign_copy.supporting_copy",
        "cta=campaign_copy.cta",
        "effective_max_slides = 1",
    ):
        assert token in segment


def test_no_product_specific_special_case():
    source, _fn, hero, _usage = _branches()

    segment = (
        ast.get_source_segment(
            source,
            hero,
        )
        or ""
    ).lower()

    assert "lululun" not in segment
    assert "hanna" not in segment
    assert "a5ea2272" not in segment


def test_runner_opts_in_only_for_premium_hero():
    source = _source(RUNNER)

    tree = ast.parse(source)

    assignments = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue

        segment = (
            ast.get_source_segment(
                source,
                node,
            )
            or ""
        )

        if (
            "config.hero_only = True"
            in segment
        ):
            assignments.append(node)

    assert len(assignments) == 1

    assignment = assignments[0]

    parents = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue

        if not (
            node.lineno
            <= assignment.lineno
            <= node.end_lineno
        ):
            continue

        condition = (
            ast.get_source_segment(
                source,
                node.test,
            )
            or ""
        )

        if (
            "args.premium_hero_only"
            in condition
        ):
            parents.append(node)

    assert len(parents) == 1


def test_existing_premium_safety_switches_remain():
    source = _source(RUNNER)

    for token in (
        "config.max_slides = 1",
        "config.hero_only = True",
        "config.use_ai_background = False",
        "config.use_masked_scene_edit = True",
        "config.require_masked_scene_edit_success = True",
        "config.render_platform_variants = False",
    ):
        assert source.count(token) == 1
