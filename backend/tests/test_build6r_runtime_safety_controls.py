from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.services.ai import openai_provider as provider_module


ROOT = Path(__file__).resolve().parents[1]

PROVIDER_PATH = (
    ROOT
    / "app"
    / "services"
    / "ai"
    / "openai_provider.py"
)

RUNNER_PATH = (
    ROOT
    / "scripts"
    / "run_live_acceptance.py"
)


def _async_openai_constructor_call() -> ast.Call:
    tree = ast.parse(
        PROVIDER_PATH.read_text(
            encoding="utf-8"
        )
    )

    matches = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue

        if (
            isinstance(node.func, ast.Name)
            and node.func.id == "AsyncOpenAI"
        ):
            matches.append(node)

    assert len(matches) == 1

    return matches[0]


def test_provider_has_explicit_180_second_timeout_and_zero_retries():
    assert (
        provider_module._OPENAI_REQUEST_TIMEOUT_SECONDS
        == 180.0
    )

    assert (
        provider_module._OPENAI_MAX_RETRIES
        == 0
    )

    call = _async_openai_constructor_call()

    keywords = {
        keyword.arg: keyword.value
        for keyword in call.keywords
        if keyword.arg is not None
    }

    assert "timeout" in keywords
    assert "max_retries" in keywords

    assert isinstance(
        keywords["timeout"],
        ast.Name,
    )

    assert (
        keywords["timeout"].id
        == "_OPENAI_REQUEST_TIMEOUT_SECONDS"
    )

    assert isinstance(
        keywords["max_retries"],
        ast.Name,
    )

    assert (
        keywords["max_retries"].id
        == "_OPENAI_MAX_RETRIES"
    )


def test_provider_factory_override_wins_over_environment_limit(
    monkeypatch: pytest.MonkeyPatch,
):
    captured = {}

    class DummyProvider:
        def __init__(
            self,
            **kwargs,
        ):
            captured.update(kwargs)

    monkeypatch.setattr(
        provider_module,
        "OpenAIProvider",
        DummyProvider,
    )

    effective = {
        "openai_api_key": "test-key",
        "openai_project_id": "proj_test",
        "openai_project_hard_limit_attested": True,
        "openai_max_image_calls": 6,
    }

    provider_module.openai_provider_from_effective_settings(
        effective,
        hard_budget_usd=3.0,
        max_image_calls_override=1,
    )

    assert (
        captured["max_image_calls"]
        == 1
    )

    assert (
        captured["hard_budget_usd"]
        == 3.0
    )


def test_provider_factory_preserves_environment_limit_without_override(
    monkeypatch: pytest.MonkeyPatch,
):
    captured = {}

    class DummyProvider:
        def __init__(
            self,
            **kwargs,
        ):
            captured.update(kwargs)

    monkeypatch.setattr(
        provider_module,
        "OpenAIProvider",
        DummyProvider,
    )

    effective = {
        "openai_api_key": "test-key",
        "openai_project_id": "proj_test",
        "openai_project_hard_limit_attested": True,
        "openai_max_image_calls": 6,
    }

    provider_module.openai_provider_from_effective_settings(
        effective,
        hard_budget_usd=3.0,
    )

    assert (
        captured["max_image_calls"]
        == 6
    )


def test_premium_hero_runner_forces_one_image_call_override():
    tree = ast.parse(
        RUNNER_PATH.read_text(
            encoding="utf-8"
        )
    )

    calls = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue

        if (
            isinstance(node.func, ast.Name)
            and node.func.id
            == "openai_provider_from_effective_settings"
        ):
            calls.append(node)

    assert len(calls) == 1

    call = calls[0]

    keyword_map = {
        keyword.arg: keyword.value
        for keyword in call.keywords
        if keyword.arg is not None
    }

    assert (
        "max_image_calls_override"
        in keyword_map
    )

    value = keyword_map[
        "max_image_calls_override"
    ]

    assert isinstance(
        value,
        ast.IfExp,
    )

    assert isinstance(
        value.body,
        ast.Constant,
    )

    assert value.body.value == 1

    assert isinstance(
        value.orelse,
        ast.Constant,
    )

    assert value.orelse.value is None

    assert isinstance(
        value.test,
        ast.Attribute,
    )

    assert (
        value.test.attr
        == "premium_hero_only"
    )

    assert isinstance(
        value.test.value,
        ast.Name,
    )

    assert (
        value.test.value.id
        == "args"
    )
