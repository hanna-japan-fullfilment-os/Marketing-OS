"""Build 6R deterministic pre-visual claim gate tests."""

from types import SimpleNamespace
import inspect

import pytest

import app.services.orchestrator as orchestrator


class FakeDB:
    def __init__(self):
        self.commit_count = 0

    def commit(self):
        self.commit_count += 1


def _verified_sparse():
    return SimpleNamespace(
        verified_description="",
        verified_usage="",
        verified_size="",
        verified_variant="",
        verified_price="",
        verified_availability="",
        verified_country_of_origin="Japan",
        verified_ingredients=[],
        verified_features=[],
        verified_benefits=[],
        verified_claims=[],
    )


def _brand():
    return SimpleNamespace(
        voice="",
        creative_instructions="",
        disclaimers=[],
        preferred_ctas=[],
        target_audiences=[],
        target_countries=[],
        disallowed_terms=[],
    )


def _campaign():
    return SimpleNamespace(
        id="campaign-test",
        status="COPY_READY",
    )


def test_nested_text_collector_preserves_source_paths():
    fields = {}

    orchestrator._collect_previsual_claim_text_fields(
        {
            "headline": "Headline",
            "slides": [
                {
                    "badge_text": "Badge",
                }
            ],
        },
        prefix="copy",
        fields=fields,
    )

    assert fields["copy.headline"] == "Headline"
    assert (
        fields["copy.slides[1].badge_text"]
        == "Badge"
    )


def test_sparse_product_rejects_unverified_number_one_claim(
    monkeypatch,
):
    db = FakeDB()
    campaign = _campaign()
    events = []

    monkeypatch.setattr(
        orchestrator,
        "resolve_verified_product_facts",
        lambda _db, _product: _verified_sparse(),
    )

    monkeypatch.setattr(
        orchestrator,
        "_audit",
        lambda *args, **kwargs: events.append(
            (args, kwargs)
        ),
    )

    with pytest.raises(
        orchestrator.PreVisualClaimGroundingError,
        match="PREVISUAL_UNSUPPORTED_CLAIM",
    ):
        orchestrator._enforce_previsual_claim_grounding_gate(
            db,
            campaign=campaign,
            brand=_brand(),
            product=SimpleNamespace(
                name="Melano CC Essence"
            ),
            phase="copy_stage",
            structures={
                "copy": {
                    "headline": (
                        "O s\u00e9rum n\u00ba 1 do Jap\u00e3o"
                    ),
                },
            },
        )

    assert campaign.status == "FAILED"
    assert db.commit_count == 1
    assert len(events) == 1

    payload = events[0][0][3]

    assert (
        payload["hard_fail_count"]
        >= 1
    )

    assert any(
        "UNSUPPORTED_CLAIM:"
        in item
        for item
        in payload["hard_fails"]
    )


def test_generic_nonfactual_copy_passes(
    monkeypatch,
):
    db = FakeDB()
    campaign = _campaign()

    monkeypatch.setattr(
        orchestrator,
        "resolve_verified_product_facts",
        lambda _db, _product: _verified_sparse(),
    )

    monkeypatch.setattr(
        orchestrator,
        "_audit",
        lambda *args, **kwargs: (
            pytest.fail(
                "PASS path should not "
                "write a failure audit."
            )
        ),
    )

    result = (
        orchestrator
        ._enforce_previsual_claim_grounding_gate(
            db,
            campaign=campaign,
            brand=_brand(),
            product=SimpleNamespace(
                name="Melano CC Essence"
            ),
            phase="copy_stage",
            structures={
                "copy": {
                    "headline": (
                        "Um novo olhar para sua rotina"
                    ),
                    "cta": "Conhe?a a sele??o",
                },
            },
        )
    )

    assert result == []
    assert campaign.status == "COPY_READY"
    assert db.commit_count == 0


def test_category_campaign_does_not_use_single_product_gate(
    monkeypatch,
):
    db = FakeDB()
    campaign = _campaign()

    monkeypatch.setattr(
        orchestrator,
        "resolve_verified_product_facts",
        lambda *_args, **_kwargs: (
            pytest.fail(
                "Discovery/category campaign "
                "must not resolve one fake shared "
                "product-facts record."
            )
        ),
    )

    result = (
        orchestrator
        ._enforce_previsual_claim_grounding_gate(
            db,
            campaign=campaign,
            brand=_brand(),
            product=None,
            phase="copy_stage",
            structures={
                "copy": {
                    "headline": "Anything",
                },
            },
        )
    )

    assert result == []
    assert db.commit_count == 0


def test_copy_gate_precedes_stage_persistence():
    source = inspect.getsource(
        orchestrator.run_copy_stage
    )

    gate = source.index(
        "_enforce_previsual_semantic_claim_grounding_gate("
    )

    persist = source.index(
        "_save_stage_json("
    )

    assert gate < persist


def test_visual_gate_precedes_identity_and_paid_visual_logic():
    source = inspect.getsource(
        orchestrator.run_visuals_stage
    )

    gate = source.index(
        "_enforce_previsual_claim_grounding_gate("
    )

    identity = source.index(
        "await _enforce_source_product_identity_gate("
    )

    adaptation = source.index(
        "await _resolve_platform_adaptation("
    )

    assert gate < identity
    assert gate < adaptation


@pytest.mark.parametrize(
    "claim",
    [
        "O serum n\u00ba 1 do Japao",
        "O serum n\u00b0 1 do Japao",
        "O serum no. 1 do Japao",
        "O serum n\u00famero 1 do Japao",
        "The number 1 serum in Japan",
        "O serum #1 do Japao",
    ],
)
def test_number_one_ranking_variants_are_detected(
    monkeypatch,
    claim,
):
    db = FakeDB()
    campaign = _campaign()

    monkeypatch.setattr(
        orchestrator,
        "resolve_verified_product_facts",
        lambda _db, _product: _verified_sparse(),
    )

    monkeypatch.setattr(
        orchestrator,
        "_audit",
        lambda *args, **kwargs: None,
    )

    with pytest.raises(
        orchestrator.PreVisualClaimGroundingError,
        match="PREVISUAL_UNSUPPORTED_CLAIM",
    ):
        orchestrator._enforce_previsual_claim_grounding_gate(
            db,
            campaign=campaign,
            brand=_brand(),
            product=SimpleNamespace(
                name="Melano CC Essence"
            ),
            phase="copy_stage",
            structures={
                "copy": {
                    "headline": claim,
                },
            },
        )


def test_must_avoid_metadata_does_not_block(
    monkeypatch,
):
    db = FakeDB()
    campaign = _campaign()

    monkeypatch.setattr(
        orchestrator,
        "resolve_verified_product_facts",
        lambda _db, _product: _verified_sparse(),
    )

    monkeypatch.setattr(
        orchestrator,
        "_audit",
        lambda *args, **kwargs: (
            pytest.fail(
                "must_avoid metadata must not "
                "produce a grounding failure."
            )
        ),
    )

    result = (
        orchestrator
        ._enforce_previsual_claim_grounding_gate(
            db,
            campaign=campaign,
            brand=_brand(),
            product=SimpleNamespace(
                name="Melano CC Essence"
            ),
            phase="copy_stage",
            structures={
                "master_concept": {
                    "must_avoid": [
                        "Never claim this is "
                        "n\u00ba 1 without evidence"
                    ],
                },
            },
        )
    )

    assert result == []
    assert campaign.status == "COPY_READY"
    assert db.commit_count == 0


def test_duplicate_hard_fail_messages_are_deduplicated(
    monkeypatch,
):
    db = FakeDB()
    campaign = _campaign()
    events = []

    monkeypatch.setattr(
        orchestrator,
        "resolve_verified_product_facts",
        lambda _db, _product: _verified_sparse(),
    )

    monkeypatch.setattr(
        orchestrator,
        "_audit",
        lambda *args, **kwargs: events.append(
            (args, kwargs)
        ),
    )

    with pytest.raises(
        orchestrator.PreVisualClaimGroundingError,
        match="PREVISUAL_UNSUPPORTED_CLAIM",
    ):
        orchestrator._enforce_previsual_claim_grounding_gate(
            db,
            campaign=campaign,
            brand=_brand(),
            product=SimpleNamespace(
                name="Melano CC Essence"
            ),
            phase="copy_stage",
            structures={
                "copy": {
                    "headline": (
                        "O serum n\u00ba 1. "
                        "O serum n\u00ba 1."
                    ),
                },
            },
        )

    assert len(events) == 1

    payload = events[0][0][3]

    hard_fails = payload[
        "hard_fails"
    ]

    assert len(hard_fails) == 1
    assert payload["hard_fail_count"] == 1
    assert "n\u00ba 1" in hard_fails[0]

