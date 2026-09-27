from __future__ import annotations

import inspect
from types import SimpleNamespace

from app.services import claims_audit
from app.services import orchestrator


def _brand(approved=None):

    rules = {}

    if approved is not None:

        rules[
            "verified_operational_strategy_keys"
        ] = approved

    return SimpleNamespace(
        campaign_rules=rules,
    )


def _strategy(key):

    return SimpleNamespace(
        key=key,
        name=key,
    )


def test_empty_rules_fail_closed_for_arbitrary_strategy_types():

    for key in (
        "bundle_campaign",
        "countdown_campaign",
        "educational_campaign",
        "guerrilla_marketing",
    ):

        failures = (
            orchestrator
            ._strategy_type_operational_hard_fails(
                brand=_brand(),
                strategy_type=_strategy(
                    key
                ),
            )
        )

        assert failures
        assert key in failures[0]


def test_exact_owner_confirmation_unlocks_exact_key():

    assert (
        orchestrator
        ._strategy_type_operational_hard_fails(
            brand=_brand(
                [
                    "educational_campaign",
                ]
            ),
            strategy_type=_strategy(
                "educational_campaign"
            ),
        )
        == []
    )


def test_owner_confirmation_does_not_unlock_other_key():

    assert (
        orchestrator
        ._strategy_type_operational_hard_fails(
            brand=_brand(
                [
                    "educational_campaign",
                ]
            ),
            strategy_type=_strategy(
                "countdown_campaign"
            ),
        )
    )


def test_malformed_operational_contract_fails_closed():

    brand = SimpleNamespace(
        campaign_rules={
            "verified_operational_strategy_keys":
                "educational_campaign",
        }
    )

    assert (
        orchestrator
        ._strategy_type_operational_hard_fails(
            brand=brand,
            strategy_type=_strategy(
                "educational_campaign"
            ),
        )
    )


def test_missing_strategy_key_fails_closed():

    strategy = SimpleNamespace(
        key="",
        name="Missing",
    )

    assert (
        orchestrator
        ._strategy_type_operational_hard_fails(
            brand=_brand(
                [
                    "educational_campaign",
                ]
            ),
            strategy_type=strategy,
        )
    )


def test_old_six_key_scope_is_gone():

    source = inspect.getsource(
        orchestrator
        ._strategy_type_operational_hard_fails
    )

    assert (
        "_STRATEGY_OPERATIONAL_EVIDENCE_REQUIRED_KEYS"
        not in source
    )


def test_auto_selector_applies_gate_before_usage_rotation():

    source = inspect.getsource(
        orchestrator
        ._select_underused_strategy_type
    )

    assert (
        source.index(
            "_strategy_type_operational_hard_fails("
        )
        <
        source.index(
            "average_engagement_rate_for_strategy_type("
        )
    )


def test_preselected_gate_runs_before_research():

    source = inspect.getsource(
        orchestrator.run_strategy_stage
    )

    assert (
        source.index(
            "strategy_type_operational_evidence_failed"
        )
        <
        source.index(
            "run_research("
        )
    )


def test_no_candidate_gate_runs_before_research():

    source = inspect.getsource(
        orchestrator.run_strategy_stage
    )

    assert (
        "PREVISUAL_NO_VERIFIED_OPERATIONAL_STRATEGY"
        in source
    )

    assert (
        "strategy_type_operational_evidence_missing"
        in source
    )

    assert (
        source.index(
            "PREVISUAL_NO_VERIFIED_OPERATIONAL_STRATEGY"
        )
        <
        source.index(
            "run_research("
        )
    )


def test_campaign_rules_are_not_product_claim_evidence():

    source = inspect.getsource(
        claims_audit._brand_evidence_text
    )

    assert "campaign_rules" not in source
