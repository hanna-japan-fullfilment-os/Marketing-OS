from __future__ import annotations

import ast
from pathlib import Path

from app.services import orchestrator


HARD_STOPS = (
    "TEMPORAL/ROUTINE INFERENCE HARD STOP",
    "PACKAGE PURPOSE/ORGANIZATION HARD STOP",
    "PURCHASE-BEHAVIOR INFERENCE HARD STOP",
    "SUBJECTIVE QUALITY/COMFORT INFERENCE HARD STOP",
    "USAGE MODIFIER INFERENCE HARD STOP",
)


def _call_name(call: ast.Call) -> str:
    if isinstance(call.func, ast.Name):
        return call.func.id

    if isinstance(call.func, ast.Attribute):
        return call.func.attr

    return ""


def _keyword(call: ast.Call, name: str):
    for item in call.keywords:
        if item.arg == name:
            return item.value

    return None


def _schema_name(call: ast.Call) -> str:
    node = _keyword(
        call,
        "schema",
    )

    if isinstance(node, ast.Name):
        return node.id

    if isinstance(node, ast.Attribute):
        return node.attr

    return ""


def test_creativebrief_uses_shared_sparse_grounding_instruction():
    path = Path(
        orchestrator.__file__
    )

    source = path.read_text(
        encoding="utf-8"
    )

    tree = ast.parse(
        source
    )

    run_copy = [
        node
        for node in tree.body
        if isinstance(
            node,
            (
                ast.FunctionDef,
                ast.AsyncFunctionDef,
            ),
        )
        and node.name == "run_copy_stage"
    ]

    assert len(
        run_copy
    ) == 1

    calls = []

    for node in ast.walk(
        run_copy[0]
    ):
        if not isinstance(
            node,
            ast.Call,
        ):
            continue

        if (
            _call_name(node)
            == "generate_structured"
            and _schema_name(node)
            == "CreativeBrief"
        ):
            calls.append(
                node
            )

    assert len(
        calls
    ) == 1

    system_source = (
        ast.get_source_segment(
            source,
            _keyword(
                calls[0],
                "system",
            ),
        )
        or ""
    )

    assert (
        "_claims_boundary_instruction"
        in system_source
    )

    assert (
        "_sparse_fact_grounding_instruction"
        in system_source
    )


def test_creativebrief_shared_instruction_contains_hard_stops():
    instruction = (
        orchestrator
        ._sparse_fact_grounding_instruction()
    )

    for marker in HARD_STOPS:
        assert marker in instruction

    lowered = instruction.lower()

    assert "ranking" in lowered
    assert "popularity" in lowered


def test_creativebrief_shared_instruction_keeps_unicode_safe():
    instruction = (
        orchestrator
        ._sparse_fact_grounding_instruction()
    )

    expected = (
        "uso cont" + chr(0x00ED) + "nuo",
        "v" + chr(0x00E1) + "rios dias",
        "sequ" + chr(0x00EA) + "ncia",
        "toque confort" + chr(0x00E1) + "vel",
    )

    for value in expected:
        assert value in instruction
