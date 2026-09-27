from pathlib import Path
import inspect

from app.services import orchestrator
from app.services.creative import pipeline


ROOT = Path(__file__).resolve().parents[1]


def test_live_acceptance_uses_background_only_ai_mode():
    source = (
        ROOT
        / "scripts"
        / "run_live_acceptance.py"
    ).read_text(
        encoding="utf-8"
    )

    assert (
        "use_ai_background=True, recreate_with_ai=False"
        in source
    )

    assert (
        "use_ai_background=False, recreate_with_ai=True"
        not in source
    )


def test_visuals_stage_fails_closed_on_full_product_recreation():
    source = inspect.getsource(
        orchestrator.run_visuals_stage
    )

    assert (
        "BUILD6R_IMMUTABLE_PRODUCT_LAYER_RUN_VISUALS_GUARD"
        in source
    )

    assert "if config.recreate_with_ai:" in source
    assert "immutable-product-layer contract" in source


def test_renderer_rejects_ai_recreated_product_pixels():
    source = inspect.getsource(
        pipeline.render_slide
    )

    assert (
        "BUILD6R_IMMUTABLE_PRODUCT_LAYER_RENDER_GUARD"
        in source
    )

    assert (
        "creative_input.recreated_image is not None"
        in source
    )

    assert (
        "AI-recreated product imagery is prohibited"
        in source
    )


def test_renderer_keeps_deterministic_product_compositor():
    source = inspect.getsource(
        pipeline.render_slide
    )

    assert "composite_product(" in source


def test_ai_background_prompt_excludes_product_and_text():
    source = inspect.getsource(
        orchestrator.generate_ai_background
    ).lower()

    required = [
        "no text of any kind",
        "no exact product label or packaging text",
        "no brand logo",
        "no product in frame",
        "real product photo",
        "real, unaltered elements",
    ]

    for phrase in required:
        assert phrase in source


def test_autopilot_defaults_do_not_enable_full_recreation():
    source = inspect.getsource(
        orchestrator.AutopilotConfig
    )

    assert "use_ai_background: bool = False" in source
    assert "recreate_with_ai: bool = False" in source
