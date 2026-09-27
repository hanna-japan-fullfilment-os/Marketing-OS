"""Build 6R single-case acceptance CLI regression."""

from importlib.util import (
    module_from_spec,
    spec_from_file_location,
)
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]

SCRIPT = (
    ROOT
    / "scripts"
    / "run_live_acceptance.py"
)


def _load():
    spec = spec_from_file_location(
        "build6r_live_acceptance",
        SCRIPT,
    )

    assert spec is not None
    assert spec.loader is not None

    module = module_from_spec(
        spec
    )

    spec.loader.exec_module(
        module
    )

    return module


def test_single_case_selects_only_instagram_pt_br():
    module = _load()

    selected = (
        module._select_acceptance_matrix(
            module.ACCEPTANCE_MATRIX,
            case_selector=(
                "instagram:pt-BR"
            ),
        )
    )

    assert selected == [
        (
            "instagram",
            "pt-BR",
        )
    ]


def test_single_case_selector_is_case_insensitive_but_returns_canonical_case():
    module = _load()

    selected = (
        module._select_acceptance_matrix(
            module.ACCEPTANCE_MATRIX,
            case_selector=(
                "INSTAGRAM:PT-br"
            ),
        )
    )

    assert selected == [
        (
            "instagram",
            "pt-BR",
        )
    ]


def test_invalid_case_cannot_create_new_cartesian_case():
    module = _load()

    with pytest.raises(
        ValueError,
        match="Allowed cases",
    ):
        module._select_acceptance_matrix(
            module.ACCEPTANCE_MATRIX,
            case_selector=(
                "facebook:en"
            ),
        )


def test_malformed_case_is_rejected():
    module = _load()

    with pytest.raises(
        ValueError,
        match="PLATFORM:LANGUAGE",
    ):
        module._select_acceptance_matrix(
            module.ACCEPTANCE_MATRIX,
            case_selector="instagram",
        )


def test_case_and_smoke_are_mutually_exclusive():
    module = _load()

    with pytest.raises(
        ValueError,
        match="cannot be used together",
    ):
        module._select_acceptance_matrix(
            module.ACCEPTANCE_MATRIX,
            case_selector=(
                "instagram:pt-BR"
            ),
            smoke=True,
        )


def test_no_scope_selector_preserves_full_matrix():
    module = _load()

    selected = (
        module._select_acceptance_matrix(
            module.ACCEPTANCE_MATRIX,
        )
    )

    assert selected == list(
        module.ACCEPTANCE_MATRIX
    )


def test_smoke_behavior_is_preserved():
    module = _load()

    selected = (
        module._select_acceptance_matrix(
            module.ACCEPTANCE_MATRIX,
            smoke=True,
        )
    )

    assert selected == (
        module._smoke_matrix(
            module.ACCEPTANCE_MATRIX
        )
    )


def test_single_case_preserves_scope_without_invented_preflight_cost():
    module = _load()

    one_case = (
        module._select_acceptance_matrix(
            module.ACCEPTANCE_MATRIX,
            case_selector=(
                "instagram:pt-BR"
            ),
        )
    )

    assert one_case == [
        (
            "instagram",
            "pt-BR",
        )
    ]

    assert (
        module._estimate_matrix_cost_usd(
            one_case
        )
        is None
    )

    assert (
        module._estimate_matrix_cost_usd(
            list(
                module.ACCEPTANCE_MATRIX
            )
        )
        is None
    )

def test_cli_source_contains_case_argument_and_scope_summary():
    source = SCRIPT.read_text(
        encoding="utf-8"
    )

    assert '"--case"' in source

    assert (
        "ACCEPTANCE_CASE_COUNT="
        in source
    )

    assert (
        "ACCEPTANCE_CASE="
        in source
    )

    assert (
        "case_selector=args.case_selector"
        in source
    )
