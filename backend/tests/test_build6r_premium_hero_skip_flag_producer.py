from __future__ import annotations

import ast
import textwrap
from pathlib import Path
from types import SimpleNamespace

from app.services.orchestrator import AutopilotConfig


ROOT = Path(__file__).resolve().parents[1]

RUNNER = (
    ROOT
    / "scripts"
    / "run_live_acceptance.py"
)


def _config():
    return AutopilotConfig(
        campaign_model="test-campaign",
        research_model="test-research",
        trend_ttl_hours=24,
        category_ttl_hours=168,
        too_similar_threshold=75,
        acceptable_threshold=45,
        output_root=Path("./data/output"),
    )


def _source():
    return RUNNER.read_text(
        encoding="utf-8-sig"
    )


def _premium_runtime_block():
    source = _source()

    tree = ast.parse(
        source
    )

    candidates = []

    for node in ast.walk(
        tree
    ):

        if not isinstance(
            node,
            ast.If,
        ):
            continue

        condition = (
            ast.get_source_segment(
                source,
                node.test,
            )
            or ""
        ).strip()

        if (
            condition
            != "args.premium_hero_only"
        ):
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
            candidates.append(
                segment
            )

    assert len(candidates) == 1

    return textwrap.dedent(
        candidates[0]
    )


def test_default_skip_flag_is_false():
    config = _config()

    assert config.skip_carousel_plan is False
    assert config.hero_only is False


def test_runner_has_no_skip_carousel_assignment():
    source = _source()

    tree = ast.parse(
        source
    )

    assignments = []

    for node in ast.walk(
        tree
    ):

        if not isinstance(
            node,
            ast.Assign,
        ):
            continue

        for target in node.targets:

            if (
                isinstance(
                    target,
                    ast.Attribute,
                )
                and target.attr
                == "skip_carousel_plan"
            ):
                assignments.append(
                    node
                )

    assert assignments == []


def test_runner_still_enables_hero_only_once():
    source = _source()

    assert (
        source.count(
            "config.hero_only = True"
        )
        == 1
    )


def test_premium_runtime_keeps_legacy_skip_false():
    config = _config()

    args = SimpleNamespace(
        premium_hero_only=True
    )

    namespace = {
        "args": args,
        "config": config,
    }

    exec(
        compile(
            _premium_runtime_block(),
            "<premium-hero-runtime>",
            "exec",
        ),
        namespace,
        namespace,
    )

    assert config.hero_only is True

    assert (
        config.skip_carousel_plan
        is False
    )

    assert config.max_slides == 1

    assert (
        config.use_ai_background
        is False
    )

    assert (
        config.require_ai_background_success
        is True
    )

    assert (
        config.use_masked_scene_edit
        is True
    )

    assert (
        config.require_masked_scene_edit_success
        is True
    )

    assert (
        config.render_platform_variants
        is False
    )


def test_previous_paid_failure_control_flow_is_unreachable():
    config = _config()

    config.hero_only = True

    legacy_skip_continue = bool(
        config.skip_carousel_plan
    )

    deterministic_hero_branch = bool(
        config.hero_only
    )

    assert legacy_skip_continue is False
    assert deterministic_hero_branch is True


def test_copy_stage_branch_structure_remains_unchanged():
    path = (
        ROOT
        / "app"
        / "services"
        / "orchestrator.py"
    )

    source = path.read_text(
        encoding="utf-8-sig"
    )

    assert (
        source.count(
            "if config.skip_carousel_plan:"
        )
        == 1
    )

    assert (
        source.count(
            "if config.hero_only:"
        )
        == 1
    )

    assert (
        source.count(
            "if not config.hero_only:"
        )
        == 1
    )
