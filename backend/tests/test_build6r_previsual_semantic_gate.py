import asyncio
import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services import claims_audit
from app.services import orchestrator as orch


def _run(coro):
    return asyncio.run(coro)


def test_copy_stage_awaits_semantic_previsual_gate():
    path = Path(orch.__file__)
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text)

    fn = next(
        node
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef)
        and node.name == "run_copy_stage"
    )

    semantic_calls = [
        node
        for node in ast.walk(fn)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id
        == "_enforce_previsual_semantic_claim_grounding_gate"
    ]

    assert len(semantic_calls) == 1

    assert any(
        isinstance(node, ast.Await)
        and node.value in semantic_calls
        for node in ast.walk(fn)
    )


def test_visuals_keeps_only_deterministic_defense_gate():
    path = Path(orch.__file__)
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text)

    fn = next(
        node
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef)
        and node.name == "run_visuals_stage"
    )

    call_names = [
        node.func.id
        for node in ast.walk(fn)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
    ]

    # Build 6R downstream grounding intentionally has three
    # ZERO-COST deterministic guards in run_visuals_stage:
    #   1. campaign/visual payload defense-in-depth,
    #   2. primary PlatformAdaptation grounding,
    #   3. primary CreativeDirection grounding before image spend.
    #
    # The semantic extraction gate remains copy-stage-only so visuals
    # do not duplicate the paid semantic claims-audit call.
    assert call_names.count(
        "_enforce_previsual_claim_grounding_gate"
    ) == 3

    assert (
        "_enforce_previsual_semantic_claim_grounding_gate"
        not in call_names
    )


def test_semantic_gate_blocks_formatted_unsupported_claim(monkeypatch):
    campaign = SimpleNamespace(
        id="campaign-test",
        status="COPY_READY",
    )

    db = SimpleNamespace(
        commit=lambda: None,
    )

    seed = object()
    result = object()
    audit_events = []

    monkeypatch.setattr(
        orch,
        "_enforce_previsual_claim_grounding_gate",
        lambda *args, **kwargs: [],
    )

    monkeypatch.setattr(
        orch,
        "resolve_verified_product_facts",
        lambda *args, **kwargs: object(),
    )

    monkeypatch.setattr(
        claims_audit,
        "audit_text_fields",
        lambda *args, **kwargs: seed,
    )

    async def fake_augment(*args, **kwargs):
        return result

    monkeypatch.setattr(
        claims_audit,
        "augment_with_ai_extraction",
        fake_augment,
    )

    monkeypatch.setattr(
        claims_audit,
        "format_claims_hard_fails",
        lambda value: [
            "UNSUPPORTED_CLAIM: vitamina c"
        ],
    )

    monkeypatch.setattr(
        orch,
        "record_prompt_usage",
        lambda *args, **kwargs: None,
    )

    monkeypatch.setattr(
        orch,
        "record_stage_usage",
        lambda *args, **kwargs: None,
    )

    monkeypatch.setattr(
        orch,
        "_audit",
        lambda *args, **kwargs: audit_events.append(
            (
                args,
                kwargs,
            )
        ),
    )

    with pytest.raises(
        orch.PreVisualClaimGroundingError
    ):
        _run(
            orch._enforce_previsual_semantic_claim_grounding_gate(
                db,
                campaign=campaign,
                brand=object(),
                product=object(),
                phase="copy_stage",
                structures={
                    "creative": {
                        "headline": "Vitamina C"
                    }
                },
                ai_provider=object(),
                model="test-model",
                language="pt-BR",
                platform="instagram",
            )
        )

    assert campaign.status == "FAILED"
    assert audit_events


def test_semantic_gate_fails_closed_when_extraction_is_unavailable(monkeypatch):
    campaign = SimpleNamespace(
        id="campaign-test",
        status="COPY_READY",
    )

    db = SimpleNamespace(
        commit=lambda: None,
    )

    seed = object()
    audit_events = []

    monkeypatch.setattr(
        orch,
        "_enforce_previsual_claim_grounding_gate",
        lambda *args, **kwargs: [],
    )

    monkeypatch.setattr(
        orch,
        "resolve_verified_product_facts",
        lambda *args, **kwargs: object(),
    )

    monkeypatch.setattr(
        claims_audit,
        "audit_text_fields",
        lambda *args, **kwargs: seed,
    )

    async def fake_augment(*args, **kwargs):
        return seed

    monkeypatch.setattr(
        claims_audit,
        "augment_with_ai_extraction",
        fake_augment,
    )

    monkeypatch.setattr(
        orch,
        "record_prompt_usage",
        lambda *args, **kwargs: None,
    )

    monkeypatch.setattr(
        orch,
        "record_stage_usage",
        lambda *args, **kwargs: None,
    )

    monkeypatch.setattr(
        orch,
        "_audit",
        lambda *args, **kwargs: audit_events.append(
            (
                args,
                kwargs,
            )
        ),
    )

    with pytest.raises(
        orch.PreVisualClaimGroundingError
    ) as exc:
        _run(
            orch._enforce_previsual_semantic_claim_grounding_gate(
                db,
                campaign=campaign,
                brand=object(),
                product=object(),
                phase="copy_stage",
                structures={
                    "copy": {
                        "headline": "Neutral text"
                    }
                },
                ai_provider=object(),
                model="test-model",
                language="pt-BR",
                platform="instagram",
            )
        )

    assert (
        "PREVISUAL_CLAIM_AUDIT_UNAVAILABLE"
        in str(
            exc.value
        )
    )

    assert campaign.status == "FAILED"
    assert audit_events

