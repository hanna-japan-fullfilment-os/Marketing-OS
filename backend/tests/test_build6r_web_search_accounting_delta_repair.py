"""BUILD6R web-search accounting delta repair.

Zero-network tests. They distinguish locally estimated provider cost from the
conservative amount the hard-budget guard accounts for web-search calls.
"""

from __future__ import annotations

import inspect
from types import SimpleNamespace

import pytest

from app.models import AIUsage
from app.services.ai import openai_provider as provider_module
from app.services.usage_tracking import (
    build_campaign_cost_report,
    record_ai_usage,
)


class _FakeQuery:
    def __init__(self, rows):
        self._rows = list(rows)

    def filter(self, *args, **kwargs):
        return self

    def all(self):
        return list(self._rows)


class _FakeSession:
    def __init__(self, rows=()):
        self._rows = list(rows)
        self.added = []

    def query(self, model):
        assert model is AIUsage
        return _FakeQuery(self._rows)

    def add(self, row):
        self.added.append(row)


def _response(input_tokens=1000, output_tokens=100):
    return SimpleNamespace(
        usage=SimpleNamespace(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
    )


def _provider_for_usage_event():
    provider = object.__new__(
        provider_module.OpenAIProvider
    )
    provider._usage_events = []
    return provider


def _row(
    *,
    operation,
    cost,
    adjustment,
    scope="campaign_global",
):
    return AIUsage(
        provider="openai",
        model="gpt-5.1",
        operation=operation,
        campaign_id="campaign-accounting-repair",
        input_tokens=100,
        output_tokens=10,
        image_count=0,
        estimated_cost_usd=cost,
        budget_guard_adjustment_usd=adjustment,
        duration_ms=0,
        platform="",
        language="",
        content_type="",
        scope=scope,
    )


def test_normal_text_usage_records_zero_budget_adjustment():
    provider = _provider_for_usage_event()

    provider._record_text_usage(
        _response(),
        "gpt-5.1",
    )

    [event] = provider.drain_usage_events()

    assert event["estimated_cost_usd"] > 0
    assert event["budget_guard_adjustment_usd"] == 0.0


def test_explicit_web_search_usage_keeps_provider_cost_separate():
    provider = _provider_for_usage_event()

    provider._record_text_usage(
        _response(),
        "gpt-5.1",
        budget_guard_adjustment_usd=(
            provider_module
            ._HARD_BUDGET_WEB_SEARCH_RESERVE_USD
        ),
    )

    [event] = provider.drain_usage_events()

    expected_provider_cost = provider_module._text_usage_cost(
        "gpt-5.1",
        1000,
        100,
    )

    assert event["estimated_cost_usd"] == pytest.approx(
        expected_provider_cost
    )
    assert event["budget_guard_adjustment_usd"] == pytest.approx(
        0.10
    )


@pytest.mark.parametrize(
    "method_name",
    [
        "research",
        "discover_opportunities",
    ],
)
def test_web_search_methods_explicitly_attribute_budget_adjustment(
    method_name,
):
    method = getattr(
        provider_module.OpenAIProvider,
        method_name,
    )

    source = inspect.getsource(method)

    assert 'tools=[{"type": "web_search"}]' in source
    assert (
        "budget_guard_adjustment_usd=("
        in source
    )
    assert (
        "_HARD_BUDGET_WEB_SEARCH_RESERVE_USD"
        in source
    )


def test_record_ai_usage_persists_adjustment_independently():
    session = _FakeSession()

    row = record_ai_usage(
        session,
        campaign_id="campaign-accounting-repair",
        operation="research",
        event={
            "provider": "openai",
            "model": "gpt-5.1",
            "input_tokens": 100,
            "output_tokens": 10,
            "image_count": 0,
            "estimated_cost_usd": 0.035855,
            "budget_guard_adjustment_usd": 0.10,
        },
        scope="campaign_global",
    )

    assert session.added == [row]
    assert row.estimated_cost_usd == pytest.approx(
        0.035855
    )
    assert row.budget_guard_adjustment_usd == pytest.approx(
        0.10
    )


def test_missing_adjustment_defaults_to_verified_zero_for_new_event():
    session = _FakeSession()

    row = record_ai_usage(
        session,
        campaign_id="campaign-accounting-repair",
        operation="strategy",
        event={
            "provider": "openai",
            "model": "gpt-5.1",
            "input_tokens": 100,
            "output_tokens": 10,
            "image_count": 0,
            "estimated_cost_usd": 0.023965,
        },
        scope="campaign_global",
    )

    assert row.budget_guard_adjustment_usd == 0.0


def test_v342_shape_reconciles_without_redefining_provider_cost():
    costs = [
        ("research", 0.035855, 0.10),
        ("strategy", 0.023965, 0.0),
        ("creative_brief", 0.030339, 0.0),
        ("master_campaign_concept", 0.033661, 0.0),
        ("campaign_copy", 0.018924, 0.0),
        ("claims_audit_extraction", 0.026680, 0.0),
    ]

    rows = [
        _row(
            operation=operation,
            cost=cost,
            adjustment=adjustment,
        )
        for operation, cost, adjustment in costs
    ]

    report = build_campaign_cost_report(
        _FakeSession(rows),
        "campaign-accounting-repair",
    )

    assert report["known_total_usd"] == pytest.approx(
        0.169424
    )

    assert report["total_usd"] == pytest.approx(
        0.169424
    )

    assert report["budget_guard_adjustment_usd"] == pytest.approx(
        0.100000
    )

    assert (
        report["budget_guard_adjustment_usd_is_complete"]
        is True
    )

    assert report["budget_accounted_total_usd"] == pytest.approx(
        0.269424
    )

    assert (
        report["budget_accounted_total_usd_is_complete"]
        is True
    )

    assert report["total_usd_is_complete"] is True


def test_multiple_web_search_adjustments_are_additive_per_call():
    rows = [
        _row(
            operation="research",
            cost=0.02,
            adjustment=0.10,
        ),
        _row(
            operation="opportunity_discovery",
            cost=0.03,
            adjustment=0.10,
        ),
    ]

    report = build_campaign_cost_report(
        _FakeSession(rows),
        "campaign-accounting-repair",
    )

    assert report["known_total_usd"] == pytest.approx(0.05)
    assert report["budget_guard_adjustment_usd"] == pytest.approx(
        0.20
    )
    assert report["budget_accounted_total_usd"] == pytest.approx(
        0.25
    )


def test_legacy_null_adjustment_is_not_fabricated_as_zero():
    row = _row(
        operation="research",
        cost=0.035855,
        adjustment=None,
    )

    report = build_campaign_cost_report(
        _FakeSession([row]),
        "campaign-accounting-repair",
    )

    # Historical provider-cost truth remains intact.
    assert report["known_total_usd"] == pytest.approx(
        0.035855
    )
    assert report["total_usd_is_complete"] is True

    # But the new budget-accounting dimension is honestly unknown.
    assert report["budget_guard_adjustment_usd"] == 0.0
    assert (
        report["budget_guard_adjustment_usd_is_complete"]
        is False
    )
    assert (
        report["budget_accounted_total_usd_is_complete"]
        is False
    )


def test_model_column_is_nullable_for_historical_rows():
    column = (
        AIUsage.__table__
        .c.budget_guard_adjustment_usd
    )

    assert column.nullable is True


class _FakeWebSearchResponses:
    def __init__(self, response):
        self._response = response
        self.calls = []

    async def parse(self, **kwargs):
        self.calls.append(kwargs)
        return self._response


class _FakeWebSearchClient:
    def __init__(self, response):
        self.responses = _FakeWebSearchResponses(
            response
        )


def _web_search_query():
    return SimpleNamespace(
        brand_name="Hanna Japan",
        category="beauty",
        product="test product",
        audience="Brazilian consumers",
        geography="Japan",
        objective="awareness",
        language="pt-BR",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method_name",
    [
        "research",
        "discover_opportunities",
    ],
)
@pytest.mark.parametrize(
    ("hard_budget_enabled", "expected_adjustment"),
    [
        (False, 0.0),
        (True, 0.10),
    ],
)
async def test_web_search_usage_adjustment_matches_hard_budget_state(
    method_name,
    hard_budget_enabled,
    expected_adjustment,
):
    provider = _provider_for_usage_event()

    provider._hard_budget_ledger = SimpleNamespace(
        enabled=hard_budget_enabled
    )

    response = _response()
    response.output_parsed = object()

    fake_client = _FakeWebSearchClient(
        response
    )

    provider._require_client = lambda: fake_client

    result = await getattr(
        provider,
        method_name,
    )(
        _web_search_query(),
        model="gpt-5.1",
    )

    assert result is response.output_parsed
    assert len(fake_client.responses.calls) == 1

    [request] = fake_client.responses.calls

    assert request["tools"] == [
        {"type": "web_search"}
    ]

    [event] = provider.drain_usage_events()

    assert event["estimated_cost_usd"] > 0

    assert event[
        "budget_guard_adjustment_usd"
    ] == pytest.approx(
        expected_adjustment
    )
