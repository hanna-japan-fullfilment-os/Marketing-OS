from __future__ import annotations

import ast
import importlib.util
import os
from pathlib import Path

import pytest
from PIL import Image


BACKEND = Path(__file__).resolve().parents[1]

BRIDGE_PATH = (
    BACKEND
    / "scripts"
    / "run_v344_single_slide_acceptance.py"
)

PREFLIGHT_PATH = (
    BACKEND
    / "scripts"
    / "preflight_v344_single_slide_acceptance.py"
)


def _load(
    path: Path,
    name: str,
):
    spec = importlib.util.spec_from_file_location(
        name,
        path,
    )

    assert spec is not None
    assert spec.loader is not None

    module = importlib.util.module_from_spec(
        spec
    )

    spec.loader.exec_module(
        module
    )

    return module


def _bridge():
    return _load(
        BRIDGE_PATH,
        "v344_bridge_test",
    )


def _preflight():
    return _load(
        PREFLIGHT_PATH,
        "v344_preflight_test",
    )


def test_bridge_and_preflight_exist():
    assert BRIDGE_PATH.is_file()
    assert PREFLIGHT_PATH.is_file()


def test_static_bridge_contract_is_one_image_call():
    bridge = _bridge()

    report = bridge.build_static_report()

    assert (
        report[
            "v338_provider_generate_call_count"
        ]
        == 1
    )

    assert (
        report[
            "v338_provider_generate_inside_loop"
        ]
        is False
    )

    assert (
        report[
            "bridge_direct_provider_generate_calls"
        ]
        == 0
    )

    assert report["max_image_calls"] == 1
    assert (
        report["automatic_image_retries"]
        == 0
    )
    assert report["best_of_n"] == 1


def test_bridge_requires_locked_product_and_typography():
    bridge = _bridge()

    report = bridge.build_static_report()

    assert (
        report[
            "v338_locked_product_compositor"
        ]
        is True
    )

    assert (
        report[
            "v338_deterministic_typography"
        ]
        is True
    )

    assert (
        report["ai_text_rendering"]
        is False
    )


def test_bridge_target_is_exact_instagram_4x5():
    bridge = _bridge()

    report = bridge.build_static_report()

    assert report["target_width"] == 1080
    assert report["target_height"] == 1350


def test_four_by_five_adapter_preserves_overlay_aspect(tmp_path):
    bridge = _bridge()

    overlay = Image.new(
        "RGBA",
        (
            bridge.EXPECTED_NATIVE_WIDTH,
            bridge.EXPECTED_NATIVE_HEIGHT,
        ),
        (0, 0, 0, 0),
    )

    fitted = (
        bridge._fit_overlay_by_height(
            overlay
        )
    )

    assert fitted.size == (1080, 1350)


def test_end_to_end_local_composition_outputs_1080x1350(
    tmp_path,
):
    bridge = _bridge()

    native_dir = (
        tmp_path
        / "native"
    )

    native_dir.mkdir()

    background = Image.new(
        "RGBA",
        (1024, 1536),
        (32, 24, 48, 255),
    )

    product = Image.new(
        "RGBA",
        (1024, 1536),
        (0, 0, 0, 0),
    )

    text = Image.new(
        "RGBA",
        (1024, 1536),
        (0, 0, 0, 0),
    )

    product.alpha_composite(
        Image.new(
            "RGBA",
            (300, 700),
            (240, 240, 240, 255),
        ),
        dest=(362, 650),
    )

    text.alpha_composite(
        Image.new(
            "RGBA",
            (600, 120),
            (255, 255, 255, 180),
        ),
        dest=(212, 80),
    )

    background_path = (
        native_dir
        / "background.png"
    )

    product_path = (
        native_dir
        / "product.png"
    )

    text_path = (
        native_dir
        / "text.png"
    )

    background.save(background_path)
    product.save(product_path)
    text.save(text_path)

    result = (
        bridge.compose_instagram_output(
            native_output={
                "background_only_path": str(
                    background_path
                ),
                "locked_product_layer_path": str(
                    product_path
                ),
                "text_layer_path": str(
                    text_path
                ),
                "locked_product_layer_immutability": True,
            },
            output_dir=(
                tmp_path
                / "final"
            ),
        )
    )

    assert result["final_width"] == 1080
    assert result["final_height"] == 1350
    assert (
        result["deterministic_typography"]
        is True
    )
    assert (
        result["ai_text_rendering"]
        is False
    )

    with Image.open(
        result["final_path"]
    ) as image:
        assert image.size == (1080, 1350)


def test_paid_path_is_fail_closed_without_v344_authorization(
    tmp_path,
    monkeypatch,
):
    bridge = _bridge()

    monkeypatch.delenv(
        bridge.PAID_AUTH_ENV,
        raising=False,
    )

    with pytest.raises(
        bridge.V344BridgeError,
        match="not authorized",
    ):
        bridge.execute_paid_once(
            database=(
                tmp_path
                / "isolated.db"
            ),
            evidence_dir=(
                tmp_path
                / "evidence"
            ),
            output_dir=(
                tmp_path
                / "output"
            ),
            max_budget_usd=0.50,
        )


def test_paid_path_rejects_canonical_database(
    monkeypatch,
    tmp_path,
):
    bridge = _bridge()

    monkeypatch.setenv(
        bridge.PAID_AUTH_ENV,
        "TRUE",
    )

    for name, value in (
        bridge.REQUIRED_LIVE_ENV.items()
    ):
        monkeypatch.setenv(
            name,
            value,
        )

    with pytest.raises(
        bridge.V344BridgeError,
        match="canonical SQLite",
    ):
        bridge.execute_paid_once(
            database=bridge.CANONICAL_DB,
            evidence_dir=(
                tmp_path
                / "evidence"
            ),
            output_dir=(
                tmp_path
                / "output"
            ),
            max_budget_usd=0.50,
        )


def test_bridge_source_contains_no_direct_generate_call():
    source = BRIDGE_PATH.read_text(
        encoding="utf-8",
    )

    tree = ast.parse(source)

    direct_generate = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and (
            (
                isinstance(
                    node.func,
                    ast.Attribute,
                )
                and node.func.attr
                == "generate"
            )
            or (
                isinstance(
                    node.func,
                    ast.Name,
                )
                and node.func.id
                == "generate"
            )
        )
    ]

    assert direct_generate == []


def test_preflight_passes_zero_cost_static_contract():
    preflight = _preflight()

    report = preflight.build_report()

    assert (
        report["network_calls"]
        == 0
    )

    assert (
        report["openai_api_calls"]
        == 0
    )

    assert (
        report["image_provider_calls"]
        == 0
    )

    assert report["paid_calls"] == 0

    assert (
        report[
            "ready_for_end_to_end_dry_run"
        ]
        is True
    )