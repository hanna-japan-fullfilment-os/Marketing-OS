import ast
from pathlib import Path

import pytest
from PIL import Image

from app.services.creative.pipeline import (
    build_render_context_path,
    build_render_visual_base_path,
    load_render_context,
    load_render_visual_base,
    persist_render_context,
)


ROOT = Path(__file__).resolve().parents[1]
ORCH = ROOT / "app" / "services" / "orchestrator.py"
QA = ROOT / "app" / "services" / "qa_engine.py"


def _call_name(call):
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return ""


def test_render_context_roundtrip_preserves_visual_state(tmp_path):
    slide = tmp_path / "slide-01.png"

    visual = Image.new(
        "RGB",
        (8, 8),
        (12, 34, 56),
    )

    direction = {
        "visual_style": "cinematic",
        "mood": "dark aqua",
        "campaign_archetype": "routine_integration",
    }

    zone = {
        "crop_left": 0.1,
        "crop_top": 0.2,
        "crop_width": 0.5,
        "crop_height": 0.6,
        "anchor": "bottom",
        "reasoning": "fixture",
    }

    persist_render_context(
        slide_output_path=slide,
        creative_direction=direction,
        visual_base=visual,
        visual_base_kind="generated_background",
        product_zone_detection=zone,
        slide_role="hero",
    )

    context = load_render_context(
        slide
    )

    assert context is not None
    assert context["creative_direction"] == direction
    assert context["product_zone_detection"] == zone
    assert context["visual_base_kind"] == "generated_background"
    assert context["slide_role"] == "hero"

    loaded, kind, loaded_context = load_render_visual_base(
        slide
    )

    assert loaded is not None
    assert loaded.size == (8, 8)
    assert kind == "generated_background"
    assert loaded_context == context

    assert build_render_context_path(
        slide
    ).is_file()

    assert build_render_visual_base_path(
        slide
    ).is_file()


def test_render_context_detects_visual_base_tampering(tmp_path):
    slide = tmp_path / "slide-01.png"

    visual = Image.new(
        "RGB",
        (4, 4),
        (1, 2, 3),
    )

    persist_render_context(
        slide_output_path=slide,
        creative_direction={},
        visual_base=visual,
        visual_base_kind="recreated_image",
    )

    build_render_visual_base_path(
        slide
    ).write_bytes(
        b"tampered"
    )

    with pytest.raises(
        RuntimeError,
        match="SHA256 mismatch",
    ):
        load_render_visual_base(
            slide
        )


def test_orchestrator_persists_context_on_both_render_paths():
    text = ORCH.read_text(
        encoding="utf-8"
    )

    tree = ast.parse(
        text
    )

    owners = set()

    for fn in tree.body:
        if not isinstance(
            fn,
            (
                ast.FunctionDef,
                ast.AsyncFunctionDef,
            ),
        ):
            continue

        for node in ast.walk(
            fn
        ):
            if (
                isinstance(
                    node,
                    ast.Call,
                )
                and _call_name(
                    node
                )
                == "_persist_render_context"
            ):
                owners.add(
                    fn.name
                )

    assert owners == {
        "run_visuals_stage",
        "_render_additional_platform_variants",
    }


def test_qa_rerender_restores_full_build6r_visual_state():
    text = QA.read_text(
        encoding="utf-8"
    )

    tree = ast.parse(
        text
    )

    fn = next(
        node
        for node in tree.body
        if (
            isinstance(
                node,
                ast.AsyncFunctionDef,
            )
            and node.name
            == "_regenerate_variant_render"
        )
    )

    source = (
        ast.get_source_segment(
            text,
            fn,
        )
        or ""
    )

    required = [
        "load_render_context(",
        "load_render_visual_base(",
        "ProductZoneDetection(",
        "product_zone_detection=zone_detection",
        "recreated_image=recreated_image",
        "campaign_archetype=",
        "direction_palette=",
        "secondary_font_family=",
        "typography_direction=",
        "headline_emphasis=",
        "cta_treatment=",
        "hero_treatment=",
        "visual_style=",
        "mood=",
        "negative_space=",
    ]

    for token in required:
        assert token in source


def test_only_best_of_n_creative_path_can_regenerate_visual_base():
    text = QA.read_text(
        encoding="utf-8"
    )

    tree = ast.parse(
        text
    )

    calls = [
        node
        for node in ast.walk(
            tree
        )
        if (
            isinstance(
                node,
                ast.Call,
            )
            and _call_name(
                node
            )
            == "_regenerate_variant_render"
        )
    ]

    assert len(calls) == 6

    true_count = 0
    omitted_count = 0

    for call in calls:
        value = next(
            (
                keyword.value
                for keyword in call.keywords
                if keyword.arg
                == "regenerate_visual_base"
            ),
            None,
        )

        if value is None:
            omitted_count += 1

        elif (
            isinstance(
                value,
                ast.Constant,
            )
            and value.value is True
        ):
            true_count += 1

        else:
            pytest.fail(
                "Unexpected regenerate_visual_base argument."
            )

    assert true_count == 1
    assert omitted_count == 5


def test_best_of_n_cleans_render_context_sidecars_for_losers():
    text = QA.read_text(
        encoding="utf-8"
    )

    tree = ast.parse(
        text
    )

    fn = next(
        node
        for node in tree.body
        if (
            isinstance(
                node,
                ast.AsyncFunctionDef,
            )
            and node.name
            == "_regenerate_with_best_of_n"
        )
    )

    source = (
        ast.get_source_segment(
            text,
            fn,
        )
        or ""
    )

    assert "build_render_context_path(" in source
    assert "build_render_visual_base_path(" in source
    assert "regenerate_visual_base=True" in source

