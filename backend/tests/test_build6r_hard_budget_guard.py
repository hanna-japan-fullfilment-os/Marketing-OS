from types import SimpleNamespace

import pytest

from app.services.ai import openai_provider as provider_module


class FakeResponses:
    def __init__(self):
        self.calls = []

    async def parse(self, **kwargs):
        self.calls.append(
            ("parse", kwargs)
        )

        return SimpleNamespace(
            usage=SimpleNamespace(
                input_tokens=100,
                output_tokens=50,
                input_tokens_details=SimpleNamespace(
                    cached_tokens=0
                ),
                output_tokens_details=SimpleNamespace(
                    reasoning_tokens=0
                ),
            ),
            output_parsed=object(),
        )

    async def create(self, **kwargs):
        self.calls.append(
            ("create", kwargs)
        )

        return SimpleNamespace(
            usage=SimpleNamespace(
                input_tokens=100,
                output_tokens=50,
                input_tokens_details=SimpleNamespace(
                    cached_tokens=0
                ),
                output_tokens_details=SimpleNamespace(
                    reasoning_tokens=0
                ),
            ),
            output_text="ok",
        )


class FakeImages:
    def __init__(self):
        self.calls = []

    async def generate(self, **kwargs):
        self.calls.append(
            ("generate", kwargs)
        )

        return SimpleNamespace(
            data=[
                SimpleNamespace(
                    b64_json="AA=="
                )
            ]
        )

    async def edit(self, **kwargs):
        self.calls.append(
            ("edit", kwargs)
        )

        return SimpleNamespace(
            data=[
                SimpleNamespace(
                    b64_json="AA=="
                )
            ]
        )


class FakeClient:
    def __init__(self):
        self.responses = FakeResponses()
        self.images = FakeImages()


@pytest.mark.asyncio
async def test_hard_budget_blocks_image_before_network(
    monkeypatch,
):
    monkeypatch.setattr(
        provider_module,
        "_image_usage_cost",
        lambda model, quality, count=1: (
            0.20 * count
        ),
    )

    ledger = (
        provider_module._HardBudgetLedger(
            0.10
        )
    )

    target = FakeImages()

    proxy = (
        provider_module._BudgetedImagesProxy(
            target,
            ledger,
        )
    )

    with pytest.raises(
        provider_module.HardBudgetExceededError,
        match="HARD_BUDGET_PRECALL_BLOCK",
    ):
        await proxy.generate(
            model="fixture-image",
            prompt="fixture",
            size="1024x1024",
            n=1,
            quality="medium",
        )

    assert target.calls == []

    snapshot = ledger.snapshot()

    assert snapshot["spent_usd"] == 0.0
    assert snapshot["blocked_call_count"] == 1


@pytest.mark.asyncio
async def test_hard_budget_commits_exact_image_reservation(
    monkeypatch,
):
    monkeypatch.setattr(
        provider_module,
        "_image_usage_cost",
        lambda model, quality, count=1: (
            0.20 * count
        ),
    )

    ledger = (
        provider_module._HardBudgetLedger(
            0.50
        )
    )

    target = FakeImages()

    proxy = (
        provider_module._BudgetedImagesProxy(
            target,
            ledger,
        )
    )

    await proxy.generate(
        model="fixture-image",
        prompt="fixture",
        size="1024x1024",
        n=1,
        quality="medium",
    )

    assert len(target.calls) == 1

    snapshot = ledger.snapshot()

    assert snapshot["spent_usd"] == 0.20
    assert snapshot["reserved_usd"] == 0.0
    assert snapshot["remaining_usd"] == 0.30


@pytest.mark.asyncio
async def test_hard_budget_text_call_is_bounded_before_network(
    monkeypatch,
):
    def fake_text_cost(
        model,
        input_tokens,
        output_tokens,
    ):
        return (
            input_tokens
            * 0.000001
            + output_tokens
            * 0.000002
        )

    monkeypatch.setattr(
        provider_module,
        "_text_usage_cost",
        fake_text_cost,
    )

    ledger = (
        provider_module._HardBudgetLedger(
            1.00
        )
    )

    target = FakeResponses()

    proxy = (
        provider_module._BudgetedResponsesProxy(
            target,
            ledger,
        )
    )

    await proxy.parse(
        model="fixture-text",
        input=[
            {
                "role": "user",
                "content": "hello",
            }
        ],
        text_format=dict,
    )

    assert len(target.calls) == 1

    kwargs = target.calls[0][1]

    assert (
        kwargs["max_output_tokens"]
        == provider_module._HARD_BUDGET_MAX_OUTPUT_TOKENS
    )

    snapshot = ledger.snapshot()

    assert snapshot["spent_usd"] > 0
    assert snapshot["spent_usd"] < 1.00
    assert snapshot["reserved_usd"] == 0.0


@pytest.mark.asyncio
async def test_hard_budget_text_block_makes_no_network_call(
    monkeypatch,
):
    monkeypatch.setattr(
        provider_module,
        "_text_usage_cost",
        lambda model, input_tokens, output_tokens: 0.75,
    )

    ledger = (
        provider_module._HardBudgetLedger(
            0.50
        )
    )

    target = FakeResponses()

    proxy = (
        provider_module._BudgetedResponsesProxy(
            target,
            ledger,
        )
    )

    with pytest.raises(
        provider_module.HardBudgetExceededError,
        match="HARD_BUDGET_PRECALL_BLOCK",
    ):
        await proxy.create(
            model="fixture-text",
            input="fixture",
        )

    assert target.calls == []


def test_hard_budget_snapshot_disabled_without_ceiling():
    ledger = (
        provider_module._HardBudgetLedger(
            None
        )
    )

    snapshot = ledger.snapshot()

    assert snapshot["enabled"] is False
    assert snapshot["limit_usd"] is None
    assert snapshot["remaining_usd"] is None


def test_runner_passes_ceiling_into_provider():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]

    text = (
        root
        / "scripts"
        / "run_live_acceptance.py"
    ).read_text(
        encoding="utf-8"
    )

    assert (
        "hard_budget_usd=args.max_budget_usd"
        in text
    )

    assert (
        "except HardBudgetExceededError as exc:"
        in text
    )

    assert (
        'report["hard_budget_snapshot"]'
        in text
    )

def test_hard_budget_uses_real_canonical_text_pricing_signature():
    import inspect

    signature = inspect.signature(
        provider_module._text_usage_cost
    )

    assert list(
        signature.parameters
    ) == [
        "model",
        "input_tokens",
        "output_tokens",
    ]

    reserve = (
        provider_module._hard_budget_text_cost_upper_bound(
            model="gpt-5-mini",
            request_kwargs={
                "model": "gpt-5-mini",
                "input": "fixture",
            },
        )
    )

    assert reserve > 0.0


def test_hard_budget_real_text_pricing_unknown_model_fails_closed():
    with pytest.raises(
        provider_module.HardBudgetExceededError,
        match="HARD_BUDGET_UNPRICEABLE_TEXT_CALL",
    ):
        provider_module._hard_budget_text_cost_upper_bound(
            model="definitely-not-a-priced-model",
            request_kwargs={
                "model": "definitely-not-a-priced-model",
                "input": "fixture",
            },
        )

def test_openai_provider_hard_budget_wraps_actual_require_client_path(
    monkeypatch,
):
    fake = FakeClient()

    monkeypatch.setattr(
        provider_module,
        "AsyncOpenAI",
        lambda **kwargs: fake,
    )

    provider = provider_module.OpenAIProvider(
        "sk-fake",
        hard_budget_usd=0.50,
    )

    assert isinstance(
        provider._client,
        provider_module._BudgetedOpenAIClient,
    )

    assert (
        provider._require_client()
        is provider._client
    )

    assert (
        provider._client._target
        is fake
    )

    snapshot = (
        provider.hard_budget_snapshot()
    )

    assert snapshot["enabled"] is True
    assert snapshot["limit_usd"] == 0.50


def test_openai_provider_without_budget_preserves_raw_client_path(
    monkeypatch,
):
    fake = FakeClient()

    monkeypatch.setattr(
        provider_module,
        "AsyncOpenAI",
        lambda **kwargs: fake,
    )

    provider = provider_module.OpenAIProvider(
        "sk-fake"
    )

    assert provider._client is fake

    assert (
        provider._require_client()
        is fake
    )

    snapshot = (
        provider.hard_budget_snapshot()
    )

    assert snapshot["enabled"] is False


@pytest.mark.asyncio
async def test_gpt_image_2_5_fails_closed_without_provider_limit_attestation(
    monkeypatch,
):
    class FakeResponses:
        pass

    class FakeImages:
        def __init__(self):
            self.calls = 0

        async def generate(
            self,
            **kwargs,
        ):
            self.calls += 1
            raise AssertionError(
                "Provider image call must not happen."
            )

    class FakeClient:
        def __init__(self):
            self.responses = FakeResponses()
            self.images = FakeImages()

    fake = FakeClient()

    monkeypatch.setattr(
        provider_module,
        "AsyncOpenAI",
        lambda **kwargs: fake,
    )

    provider = provider_module.OpenAIProvider(
        "sk-fake",
        hard_budget_usd=1.00,
        project_id="proj_marketing_os",
        max_image_calls=2,
    )

    with pytest.raises(
        provider_module.HardBudgetExceededError,
        match="PROVIDER_HARD_LIMIT_ATTESTATION_REQUIRED",
    ):
        await provider.generate(
            prompt="offline test",
            size="1088x1360",
            model="gpt-image-2.5-sunburst-2026-09-08",
            quality="high",
        )

    assert fake.images.calls == 0


@pytest.mark.asyncio
async def test_gpt_image_2_5_requires_project_id_and_call_limit_before_api(
    monkeypatch,
):
    class FakeResponses:
        pass

    class FakeImages:
        def __init__(self):
            self.calls = 0

        async def generate(
            self,
            **kwargs,
        ):
            self.calls += 1
            raise AssertionError(
                "Provider image call must not happen."
            )

    class FakeClient:
        def __init__(self):
            self.responses = FakeResponses()
            self.images = FakeImages()

    fake = FakeClient()

    monkeypatch.setattr(
        provider_module,
        "AsyncOpenAI",
        lambda **kwargs: fake,
    )

    missing_project = (
        provider_module.OpenAIProvider(
            "sk-fake",
            hard_budget_usd=1.00,
            provider_hard_limit_attested=True,
            max_image_calls=2,
        )
    )

    with pytest.raises(
        provider_module.HardBudgetExceededError,
        match="PROJECT_ID_REQUIRED",
    ):
        await missing_project.generate(
            prompt="offline test",
            size="1088x1360",
            model="gpt-image-2.5-sunburst-2026-09-08",
            quality="high",
        )

    missing_limit = (
        provider_module.OpenAIProvider(
            "sk-fake",
            hard_budget_usd=1.00,
            project_id="proj_marketing_os",
            provider_hard_limit_attested=True,
        )
    )

    with pytest.raises(
        provider_module.HardBudgetExceededError,
        match="IMAGE_CALL_LIMIT_REQUIRED",
    ):
        await missing_limit.generate(
            prompt="offline test",
            size="1088x1360",
            model="gpt-image-2.5-sunburst-2026-09-08",
            quality="high",
        )

    assert fake.images.calls == 0


@pytest.mark.asyncio
async def test_gpt_image_2_5_call_limit_is_enforced_on_real_provider_path(
    monkeypatch,
):
    class FakeResponses:
        pass

    class Datum:
        b64_json = "aGVsbG8="

    class Response:
        data = [
            Datum()
        ]

    class FakeImages:
        def __init__(self):
            self.calls = 0

        async def generate(
            self,
            **kwargs,
        ):
            self.calls += 1
            return Response()

    class FakeClient:
        def __init__(self):
            self.responses = FakeResponses()
            self.images = FakeImages()

    fake = FakeClient()

    monkeypatch.setattr(
        provider_module,
        "AsyncOpenAI",
        lambda **kwargs: fake,
    )

    provider = provider_module.OpenAIProvider(
        "sk-fake",
        # Exercise the independent historical counter; dollar-guarded
        # Sunburst calls are now tested separately and must fail closed.
        project_id="proj_marketing_os",
        provider_hard_limit_attested=True,
        max_image_calls=1,
    )

    result = await provider.generate(
        prompt="offline test",
        size="1088x1360",
        model="gpt-image-2.5-sunburst-2026-09-08",
        quality="high",
    )

    assert result == b"hello"
    assert fake.images.calls == 1

    snapshot = (
        provider.hard_budget_snapshot()
    )

    assert snapshot[
        "provider_hard_limit_attested"
    ] is True

    assert snapshot[
        "image_calls_used"
    ] == 1

    assert snapshot[
        "image_calls_remaining"
    ] == 0

    with pytest.raises(
        provider_module.HardBudgetExceededError,
        match="IMAGE_CALL_LIMIT_EXCEEDED",
    ):
        await provider.generate(
            prompt="blocked second attempt",
            size="1088x1360",
            model="gpt-image-2.5-sunburst-2026-09-08",
            quality="high",
        )

    assert fake.images.calls == 1


def test_gpt_image_2_5_usage_is_recorded_without_invented_dollar_price():
    provider = (
        provider_module.OpenAIProvider(
            api_key=""
        )
    )

    provider._record_image_usage(
        "gpt-image-2.5-sunburst-2026-09-08",
        "high",
        count=1,
    )

    events = (
        provider.drain_usage_events()
    )

    assert len(events) == 1

    event = events[0]

    assert event[
        "image_count"
    ] == 1

    assert event[
        "estimated_cost_usd"
    ] == 0.0

    assert event[
        "cost_known"
    ] is False

    assert event[
        "pricing_basis"
    ] == "provider_project_spend_limit"

    assert (
        provider_module._image_usage_cost(
            "gpt-image-2.5-sunburst-2026-09-08",
            "high",
            1,
        )
        == 0.0
    )




def test_runtime_provider_factory_carries_gpt_image_2_5_safety_settings():
    provider = (
        provider_module.openai_provider_from_effective_settings(
            {
                "openai_api_key": "",
                "openai_project_id": "proj_marketing_os",
                "openai_project_hard_limit_attested": True,
                "openai_max_image_calls": 3,
            }
        )
    )

    snapshot = (
        provider.hard_budget_snapshot()
    )

    assert snapshot[
        "project_id_configured"
    ] is True

    assert snapshot[
        "provider_hard_limit_attested"
    ] is True

    assert snapshot[
        "max_image_calls"
    ] == 3

    assert snapshot[
        "image_calls_used"
    ] == 0

    assert snapshot[
        "image_calls_remaining"
    ] == 3


def test_runtime_provider_factory_defaults_gpt_image_2_5_live_safety_closed():
    provider = (
        provider_module.openai_provider_from_effective_settings(
            {
                "openai_api_key": "",
                "openai_project_id": "",
                "openai_project_hard_limit_attested": False,
                "openai_max_image_calls": 8,
            }
        )
    )

    snapshot = (
        provider.hard_budget_snapshot()
    )

    assert snapshot[
        "project_id_configured"
    ] is False

    assert snapshot[
        "provider_hard_limit_attested"
    ] is False

    assert snapshot[
        "max_image_calls"
    ] == 8


def test_runtime_provider_factory_parses_env_style_safety_values():
    provider = (
        provider_module.openai_provider_from_effective_settings(
            {
                "openai_api_key": "",
                "openai_project_id": "proj_marketing_os",
                "openai_project_hard_limit_attested": "true",
                "openai_max_image_calls": "5",
            }
        )
    )

    snapshot = (
        provider.hard_budget_snapshot()
    )

    assert snapshot[
        "provider_hard_limit_attested"
    ] is True

    assert snapshot[
        "max_image_calls"
    ] == 5



def test_runtime_config_requires_explicit_gpt_image_2_5_image_call_limit():
    from app.config import Settings

    fields = getattr(
        Settings,
        "model_fields",
        None,
    )

    if fields is None:
        fields = getattr(
            Settings,
            "__fields__",
            None,
        )

    assert fields is not None

    field = fields[
        "openai_max_image_calls"
    ]

    assert field.default is None



def test_live_runner_marks_incomplete_local_cost_instead_of_claiming_actual_cost():
    from pathlib import Path

    root = (
        Path(__file__)
        .resolve()
        .parents[1]
    )

    text = (
        root
        / "scripts"
        / "run_live_acceptance.py"
    ).read_text(
        encoding="utf-8"
    )

    assert (
        'report["actual_cost_usd"] = combined_cost["total_usd"]'
        not in text
    )

    assert (
        "KNOWN_LOCAL_COST_USD="
        in text
    )

    assert (
        "ACTUAL_COST_COMPLETE="
        in text
    )

    assert (
        "ACTUAL_COST_USD="
        "UNAVAILABLE_INCOMPLETE_LOCAL_ACCOUNTING"
        in text
    )

    assert (
        "provider_cost_reconciliation_required"
        in text
    )

    assert (
        "UNAVAILABLE_PRECALL_MIXED_USAGE"
        in text
    )


def test_live_runner_stops_between_groups_when_local_usd_cost_is_incomplete():
    from pathlib import Path

    root = (
        Path(__file__)
        .resolve()
        .parents[1]
    )

    text = (
        root
        / "scripts"
        / "run_live_acceptance.py"
    ).read_text(
        encoding="utf-8"
    )

    assert (
        "prior_cost_reports"
        in text
    )

    assert (
        "total_usd_is_complete"
        in text
    )

    assert (
        "LOCAL_USD_BUDGET_UNSAFE_INCOMPLETE_COST_ACCOUNTING"
        in text
    )

    assert (
        'build_campaign_cost_report(session, cid)["total_usd"]'
        not in text
    )


def test_live_runner_preserves_provider_precall_budget_guard():
    from pathlib import Path

    root = (
        Path(__file__)
        .resolve()
        .parents[1]
    )

    text = (
        root
        / "scripts"
        / "run_live_acceptance.py"
    ).read_text(
        encoding="utf-8"
    )

    assert (
        "openai_provider_from_effective_settings"
        in text
    )

    assert (
        "hard_budget_usd=args.max_budget_usd"
        in text
    )


LIMITS = {"image": 6, "text": 10, "vision": 2, "other": 0}
SUNBURST = "gpt-image-2.5-sunburst-2026-09-08"


@pytest.mark.parametrize("kind,maximum", [("image", 6), ("text", 10), ("vision", 2), ("other", 0)])
def test_independent_attempt_caps(kind, maximum):
    ledger = provider_module._HardBudgetLedger(10, call_limits=LIMITS)
    for _ in range(maximum):
        ledger.count_attempt(kind)
    with pytest.raises(provider_module.HardBudgetExceededError, match="HARD_CALL_CAP_PRECALL_BLOCK"):
        ledger.count_attempt(kind)
    assert ledger.call_counts[kind] == maximum


@pytest.mark.asyncio
@pytest.mark.parametrize("vision,maximum", [(False, 10), (True, 2)])
async def test_response_caps_on_actual_proxy_prevent_extra_invocation(vision, maximum):
    ledger = provider_module._HardBudgetLedger(20, call_limits=LIMITS)
    target = FakeResponses()
    proxy = provider_module._BudgetedResponsesProxy(target, ledger)
    content = [{"type": "input_image", "image_url": "data:image/png;base64,AA=="}] if vision else "text"
    for _ in range(maximum):
        await proxy.parse(model="gpt-5.1", input=[{"role": "user", "content": content}])
    with pytest.raises(provider_module.HardBudgetExceededError, match="HARD_CALL_CAP_PRECALL_BLOCK"):
        await proxy.create(model="gpt-5.1", input=[{"role": "user", "content": content}])
    assert len(target.calls) == maximum
    assert all(call[1]["max_output_tokens"] == 4096 for call in target.calls)
    assert ledger.reserved_usd == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["generate", "edit"])
async def test_sunburst_unknown_maximum_blocks_before_fake_sdk(method):
    ledger = provider_module._HardBudgetLedger(10, call_limits=LIMITS)
    target = FakeImages()
    proxy = provider_module._BudgetedImagesProxy(target, ledger)
    with pytest.raises(provider_module.HardBudgetExceededError, match="UNKNOWN_IMAGE_MAXIMUM"):
        await getattr(proxy, method)(model=SUNBURST, prompt="fixture", size="1088x1360", quality="xhigh")
    assert target.calls == []
    assert ledger.reserved_usd == ledger.spent_usd == 0


@pytest.mark.asyncio
async def test_sunburst_no_longer_bypasses_non_strict_dollar_budget():
    target = FakeImages()
    proxy = provider_module._BudgetedImagesProxy(target, provider_module._HardBudgetLedger(0.000001))
    with pytest.raises(provider_module.HardBudgetExceededError, match="UNKNOWN_IMAGE_MAXIMUM"):
        await proxy.edit(model=SUNBURST)
    assert target.calls == []


@pytest.mark.asyncio
async def test_unknown_and_missing_pricing_block_before_sdk(monkeypatch):
    target = FakeResponses()
    proxy = provider_module._BudgetedResponsesProxy(target, provider_module._HardBudgetLedger(10, call_limits=LIMITS))
    with pytest.raises(provider_module.HardBudgetExceededError, match="MISSING_PRICING"):
        await proxy.create(model="unknown", input="text")
    monkeypatch.delitem(provider_module._ACCEPTANCE_PRICING, "gpt-5.1")
    with pytest.raises(provider_module.HardBudgetExceededError, match="MISSING_PRICING"):
        await proxy.create(model="gpt-5.1", input="text")
    assert target.calls == []


@pytest.mark.parametrize("rate", ["NaN", "Infinity", "0", "-1", "bad"])
def test_invalid_versioned_pricing_rejected(monkeypatch, rate):
    monkeypatch.setitem(provider_module._ACCEPTANCE_PRICING, "gpt-5.1", {"input": rate, "output": "10", "context": 400000})
    with pytest.raises(provider_module.HardBudgetExceededError, match="MISSING_PRICING"):
        provider_module._acceptance_text_reservation("gpt-5.1")


@pytest.mark.asyncio
@pytest.mark.parametrize("result", ["failure", "missing", "partial"])
async def test_failed_and_missing_usage_keep_full_reservation_and_attempt(result):
    class Target:
        calls = 0

        async def create(self, **kwargs):
            self.calls += 1
            assert ledger.reserved_usd == provider_module._acceptance_text_reservation("gpt-5.1")
            assert ledger.call_counts["text"] == 1
            if result == "failure":
                raise TimeoutError("fake timeout; potentially billed")
            return SimpleNamespace(usage=None if result == "missing" else SimpleNamespace(input_tokens=1))

    reservation = provider_module._acceptance_text_reservation("gpt-5.1")
    ledger = provider_module._HardBudgetLedger(reservation, call_limits=LIMITS)
    target = Target()
    proxy = provider_module._BudgetedResponsesProxy(target, ledger)
    if result == "failure":
        with pytest.raises(TimeoutError):
            await proxy.create(model="gpt-5.1", input="text")
    else:
        await proxy.create(model="gpt-5.1", input="text")
    assert ledger.reserved_usd == reservation and ledger.spent_usd == 0
    with pytest.raises(provider_module.HardBudgetExceededError, match="PRECALL_BLOCK"):
        await proxy.create(model="gpt-5.1", input="retry")
    assert target.calls == 1 and ledger.call_counts["text"] == 1


@pytest.mark.asyncio
async def test_application_retry_consumes_fresh_attempt_and_budget():
    class Target:
        calls = 0

        async def create(self, **kwargs):
            self.calls += 1
            raise TimeoutError("fake")

    ledger = provider_module._HardBudgetLedger(10, call_limits=LIMITS)
    target = Target()
    proxy = provider_module._BudgetedResponsesProxy(target, ledger)
    for _ in range(10):
        with pytest.raises(TimeoutError):
            await proxy.create(model="gpt-5.1", input="retry")
    with pytest.raises(provider_module.HardBudgetExceededError, match="HARD_CALL_CAP"):
        await proxy.create(model="gpt-5.1", input="retry")
    assert target.calls == ledger.call_counts["text"] == 10
    assert ledger.reserved_usd == 10 * provider_module._acceptance_text_reservation("gpt-5.1")


@pytest.mark.asyncio
async def test_text_and_vision_share_budget_and_reconcile_actual_usage():
    ledger = provider_module._HardBudgetLedger(1, call_limits=LIMITS)
    proxy = provider_module._BudgetedResponsesProxy(FakeResponses(), ledger)
    await proxy.parse(model="gpt-5.1", input="text")
    await proxy.create(model="gpt-5.1", input=[{"type": "input_image", "image_url": "fake"}])
    assert ledger.call_counts == {"image": 0, "text": 1, "vision": 1, "other": 0}
    assert ledger.spent_usd >= 2 * (100 * 1.25 + 50 * 10) / 1000000
    assert ledger.reserved_usd == 0


def test_breach_is_sticky_and_retains_reservation():
    ledger = provider_module._HardBudgetLedger(1, call_limits=LIMITS)
    reservation = ledger.reserve(0.1, operation="fixture")
    with pytest.raises(provider_module.HardBudgetExceededError, match="RESERVATION_BREACH"):
        ledger.commit(reservation, 0.2, operation="fixture")
    assert ledger.halted and ledger.reserved_usd == 0.1
    with pytest.raises(provider_module.HardBudgetExceededError):
        ledger.reserve(0.1, operation="cannot resume")


@pytest.mark.parametrize("limit", [float("nan"), float("inf"), 0, -1])
def test_invalid_budget_rejected(limit):
    with pytest.raises(ValueError):
        provider_module._HardBudgetLedger(limit, call_limits=LIMITS)


@pytest.mark.asyncio
@pytest.mark.parametrize("options", [{"max_output_tokens": 4097}, {"tools": [{"type": "web_search"}]},
                                         {"stream": True}, {"extra_body": {"model": "unknown"}},
                                         {"previous_response_id": "old"}])
async def test_unaccounted_request_variants_rejected(options):
    target = FakeResponses()
    proxy = provider_module._BudgetedResponsesProxy(target, provider_module._HardBudgetLedger(10, call_limits=LIMITS))
    with pytest.raises(provider_module.HardBudgetExceededError):
        await proxy.create(model="gpt-5.1", input="text", **options)
    assert target.calls == []


def test_guarded_sdk_public_paths_cannot_escape():
    client = provider_module._BudgetedOpenAIClient(FakeClient(), provider_module._HardBudgetLedger(10, call_limits=LIMITS))
    for obj, name in [(client, "chat"), (client, "with_options"), (client.responses, "with_raw_response"),
                      (client.images, "with_streaming_response"), (client.images, "create_variation")]:
        with pytest.raises(provider_module.HardBudgetExceededError, match="UNSUPPORTED"):
            getattr(obj, name)


@pytest.mark.asyncio
async def test_prepared_control_path_blocks_before_either_stage(monkeypatch):
    from scripts import run_live_acceptance as runner

    async def forbidden(*args, **kwargs):
        raise AssertionError("No stage, database write, renderer or provider may start")

    monkeypatch.setattr(runner, "run_visuals_stage", forbidden)
    monkeypatch.setattr(runner, "run_qa_stage", forbidden)
    provider = provider_module.OpenAIProvider(None, hard_budget_usd=10, acceptance_call_limits=LIMITS)
    config = SimpleNamespace(qa_max_retries=0, qa_best_of_n=1, recreate_with_ai=False,
                             use_masked_scene_edit=False, detect_product_zone=False, hero_only=False,
                             use_ai_background=True, require_ai_background_success=True,
                             enable_qa_stage=True, quality_mode="premium")
    with pytest.raises(provider_module.HardBudgetExceededError, match="UNKNOWN_IMAGE_MAXIMUM"):
        await runner.run_prepared_acceptance(None, campaign_id="prepared", config=config, renderer=None, provider=provider)
    assert provider.hard_budget_snapshot()["call_counts"] == dict.fromkeys(LIMITS, 0)


def test_actual_runtime_cost_calculation_refuses_fabricated_image_ceiling():
    from scripts import run_live_acceptance as runner

    with pytest.raises(provider_module.HardBudgetExceededError, match="UNKNOWN_IMAGE_MAXIMUM"):
        runner.prepared_acceptance_reserved_costs()


@pytest.mark.asyncio
async def test_synthetic_maximum_exercises_image_edit_ledger_and_seventh_call(monkeypatch):
    # Synthetic reservation tests accounting mechanics only. It is NOT a
    # Sunburst pricing assertion and cannot authorize or unblock a live run.
    monkeypatch.setattr(provider_module, "_sunburst_reservation", lambda: 0.2)
    ledger = provider_module._HardBudgetLedger(10, call_limits=LIMITS)

    class Images(FakeImages):
        async def edit(self, **kwargs):
            assert ledger.reserved_usd >= 0.2
            assert ledger.call_counts["image"] == len(self.calls) + 1
            return await super().edit(**kwargs)

    target = Images()
    images = provider_module._BudgetedImagesProxy(target, ledger)
    responses = provider_module._BudgetedResponsesProxy(FakeResponses(), ledger)
    await responses.create(model="gpt-5.1", input="text")
    await responses.create(model="gpt-5.1", input=[{"type": "input_image", "image_url": "fake"}])
    for _ in range(6):
        await images.edit(model=SUNBURST, prompt="fake", size="1088x1360", quality="xhigh")
    with pytest.raises(provider_module.HardBudgetExceededError, match="HARD_CALL_CAP"):
        await images.edit(model=SUNBURST)
    assert len(target.calls) == 6
    assert ledger.reserved_usd == 1.2  # missing usage retains all six maxima
    assert ledger.spent_usd > 0  # text and vision share this same ledger


@pytest.mark.asyncio
async def test_synthetic_image_usage_reconciliation(monkeypatch):
    monkeypatch.setattr(provider_module, "_sunburst_reservation", lambda: 0.2)
    ledger = provider_module._HardBudgetLedger(1, call_limits=LIMITS)

    class Images:
        async def edit(self, **kwargs):
            return SimpleNamespace(usage=SimpleNamespace(
                input_tokens_details=SimpleNamespace(text_tokens=100, image_tokens=200), output_tokens=1000))

    proxy = provider_module._BudgetedImagesProxy(Images(), ledger)
    await proxy.edit(model=SUNBURST)
    assert ledger.reserved_usd == 0
    assert ledger.spent_usd == 0.0321  # (100*5 + 200*8 + 1000*30)/1e6


def _bounded_upload(width=8, height=8):
    import io
    from PIL import Image
    stream = io.BytesIO()
    Image.new("RGB", (width, height)).save(stream, format="PNG")
    stream.name = "fixture.png"
    return stream


def _bounded_image_kwargs(**overrides):
    return dict(model=SUNBURST, prompt="Immutable prepared visual direction", size="1088x1360",
                quality="xhigh", image=[_bounded_upload()], **overrides)


@pytest.mark.asyncio
async def test_bounded_successful_exposure_schedule_and_independent_extra_attempts():
    ledger = provider_module._BoundedExposureLedger()
    raw = FakeClient()
    client = provider_module._BoundedAcceptanceClient(raw, ledger)
    for _ in range(10):
        await client.responses.parse(model="gpt-5.1", input="prepared")
    for _ in range(2):
        await client.responses.parse(model="gpt-5.1", input=[{"type": "input_image", "image_url": "fake"}])
    for _ in range(6):
        await client.images.edit(**_bounded_image_kwargs())
    for kwargs, call in [(_bounded_image_kwargs(), client.images.edit),
                         ({"model": "gpt-5.1", "input": "text"}, client.responses.parse),
                         ({"model": "gpt-5.1", "input": [{"type": "input_image"}]}, client.responses.parse)]:
        with pytest.raises(provider_module.HardBudgetExceededError, match="HARD_CALL_CAP"):
            await call(**kwargs)
    assert ledger.call_counts == LIMITS
    assert len(raw.images.calls) == 6 and len(raw.responses.calls) == 12
    assert ledger.snapshot()["actual_cost_usd"] is None  # fake images omit usage
    assert ledger.snapshot()["exact_per_run_usd_ceiling"] is False
    assert all(kwargs["partial_images"] == 0 and kwargs["n"] == 1 and kwargs["output_format"] == "png"
               for _, kwargs in raw.images.calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["image", "text", "vision"])
async def test_bounded_failed_attempt_halts_retry_and_fallback(kind):
    class Failure:
        calls = 0
        async def parse(self, **kwargs):
            self.calls += 1
            raise TimeoutError("fake potentially billed request")
        edit = parse
    target = Failure()
    ledger = provider_module._BoundedExposureLedger()
    proxy = provider_module._BoundedAcceptanceResource(target, ledger, image=kind == "image")
    kwargs = _bounded_image_kwargs() if kind == "image" else dict(
        model="gpt-5.1", input=[{"type": "input_image"}] if kind == "vision" else "text")
    method = proxy.edit if kind == "image" else proxy.parse
    with pytest.raises(TimeoutError):
        await method(**kwargs)
    with pytest.raises(provider_module.HardBudgetExceededError, match="HALTED_NO_RETRY_OR_FALLBACK"):
        await method(**kwargs)
    assert target.calls == ledger.call_counts[kind] == 1
    assert ledger.snapshot()["actual_cost_usd"] is None


@pytest.mark.asyncio
async def test_bounded_rejects_concurrent_request_before_invocation():
    class Pause:
        def __await__(self):
            yield "fake-in-flight"
    class Responses:
        calls = 0
        async def parse(self, **kwargs):
            self.calls += 1
            await Pause()
    target = Responses()
    ledger = provider_module._BoundedExposureLedger()
    proxy = provider_module._BoundedAcceptanceResource(target, ledger)
    pending = proxy.parse(model="gpt-5.1", input="first")
    assert pending.send(None) == "fake-in-flight"
    try:
        with pytest.raises(provider_module.HardBudgetExceededError, match="CONCURRENT"):
            await proxy.parse(model="gpt-5.1", input="second")
        assert target.calls == ledger.call_counts["text"] == 1
    finally:
        pending.close()
    assert ledger.halted and not ledger.in_flight


@pytest.mark.asyncio
@pytest.mark.parametrize("override", [{"size": "auto"}, {"quality": "auto"}, {"n": 2},
                                         {"partial_images": 1}, {"stream": True},
                                         {"output_format": "jpeg"}, {"model": "fallback-model"},
                                         {"input_fidelity": "high"}, {"extra_body": {"n": 10}},
                                         {"prompt": "x"*32001}, {"prompt": "\ud800"}])
async def test_bounded_rejects_cost_affecting_image_variants(override):
    raw = FakeImages()
    ledger = provider_module._BoundedExposureLedger()
    proxy = provider_module._BoundedAcceptanceResource(raw, ledger, image=True)
    kwargs = _bounded_image_kwargs(); kwargs.update(override)
    with pytest.raises((provider_module.HardBudgetExceededError, UnicodeError)):
        await proxy.edit(**kwargs)
    assert raw.calls == [] and ledger.call_counts["image"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("images", [[], [_bounded_upload(), _bounded_upload()], [_bounded_upload(2049, 1)]])
async def test_bounded_rejects_reference_count_or_dimensions(images):
    raw = FakeImages(); ledger = provider_module._BoundedExposureLedger()
    proxy = provider_module._BoundedAcceptanceResource(raw, ledger, image=True)
    kwargs = _bounded_image_kwargs(); kwargs["image"] = images
    with pytest.raises(provider_module.HardBudgetExceededError):
        await proxy.edit(**kwargs)
    assert not raw.calls


@pytest.mark.asyncio
async def test_bounded_rejects_reference_file_bytes(monkeypatch):
    monkeypatch.setitem(provider_module._SUNBURST_PAYLOAD_LIMITS, "reference_file_bytes", 1)
    raw = FakeImages(); ledger = provider_module._BoundedExposureLedger()
    with pytest.raises(provider_module.HardBudgetExceededError, match="FILE_BYTES"):
        await provider_module._BoundedAcceptanceResource(raw, ledger, image=True).edit(**_bounded_image_kwargs())
    assert not raw.calls


@pytest.mark.asyncio
async def test_bounded_unknown_pricing_and_unknown_paid_class_rejected(monkeypatch):
    raw = FakeImages(); ledger = provider_module._BoundedExposureLedger()
    with pytest.raises(provider_module.HardBudgetExceededError, match="UNKNOWN_CALL_CLASS"):
        ledger.begin("unclassified", {})
    monkeypatch.delitem(provider_module._ACCEPTANCE_PRICING, SUNBURST)
    with pytest.raises(provider_module.HardBudgetExceededError, match="MISSING_PRICING"):
        await provider_module._BoundedAcceptanceResource(raw, ledger, image=True).edit(**_bounded_image_kwargs())
    assert not raw.calls


@pytest.mark.asyncio
async def test_bounded_image_actual_cost_uses_official_token_rates():
    class Images:
        async def edit(self, **kwargs):
            return SimpleNamespace(data=[SimpleNamespace(b64_json="AA==")], usage=SimpleNamespace(
                input_tokens=300, input_tokens_details=SimpleNamespace(text_tokens=100, image_tokens=200), output_tokens=1000))
    ledger = provider_module._BoundedExposureLedger()
    await provider_module._BoundedAcceptanceResource(Images(), ledger, image=True).edit(**_bounded_image_kwargs())
    assert ledger.snapshot()["actual_cost_usd"] == 0.0321


@pytest.mark.asyncio
async def test_bounded_malformed_response_consumes_attempt():
    class Target:
        async def parse(self, **kwargs):return SimpleNamespace(output_parsed=None)
    ledger = provider_module._BoundedExposureLedger()
    with pytest.raises(ValueError, match="Malformed"):
        await provider_module._BoundedAcceptanceResource(Target(), ledger).parse(model="gpt-5.1", input="text")
    assert ledger.halted and ledger.call_counts["text"] == 1


def test_bounded_provider_uses_shared_wrapper_no_usd_guarantee_and_zero_sdk_retries(monkeypatch):
    captured = {}
    def factory(**kwargs):
        captured.update(kwargs)
        return FakeClient()
    monkeypatch.setattr(provider_module, "AsyncOpenAI", factory)
    provider = provider_module.OpenAIProvider("sk-fake", bounded_acceptance=True)
    assert isinstance(provider._require_client(), provider_module._BoundedAcceptanceClient)
    assert provider.hard_budget_snapshot()["bounded_exposure"] is True
    assert captured["max_retries"] == 0 and captured["timeout"] == 180
    assert captured["http_client"].follow_redirects is False
    assert provider._client.images._ledger is provider._client.responses._ledger
    with pytest.raises(ValueError, match="not an exact USD"):
        provider_module.OpenAIProvider(None, bounded_acceptance=True, hard_budget_usd=1)


@pytest.mark.asyncio
async def test_project_backstop_optional_read_only_and_not_exact_cap():
    from scripts import run_live_acceptance as runner
    absent = await runner.verify_project_spend_backstop("proj_fake")
    assert absent["readable"] is False and absent["enforced"] is False
    calls = []
    async def read_only_get(path, **kwargs):
        calls.append((path, kwargs))
        return dict(object="project.spend_limit", threshold_amount=1000, currency="USD",
                    interval="month", enforcement={"status": "enforcing"})
    result = await runner.verify_project_spend_backstop("proj_fake", read_only_get=read_only_get)
    assert result["limit_usd"] == 10 and result["enforced"] is True
    assert result["exact_per_run_cap"] is False
    assert calls == [("/organization/projects/proj_fake/spend_limit", {"timeout": 15, "retries": 0})]


@pytest.mark.parametrize("cta", ["", "Saiba mais"])
def test_explicit_slide_cta_is_preserved_without_campaign_substitution(cta):
    from app.schemas.ai import SlidePlan
    from app.services.orchestrator import _resolve_slide_cta
    plan = SlidePlan(slide_number=1, purpose="hero", headline="Prepared", visual_brief="Prepared", cta=cta)
    assert "cta" in plan.model_fields_set
    assert _resolve_slide_cta(plan, "Campaign CTA") == cta
    assert plan.cta == cta  # resolution must not mutate the approved plan


def test_unset_legacy_cta_still_uses_campaign_fallback():
    from app.schemas.ai import SlidePlan
    from app.services.orchestrator import _resolve_slide_cta
    plan = SlidePlan(slide_number=1, purpose="hero", headline="Legacy", visual_brief="Legacy")
    assert "cta" not in plan.model_fields_set
    assert _resolve_slide_cta(plan, "Campaign CTA") == "Campaign CTA"
    assert _resolve_slide_cta(SimpleNamespace(), "Campaign CTA") == "Campaign CTA"
    assert _resolve_slide_cta(SimpleNamespace(cta=None), "Campaign CTA") == "Campaign CTA"
    assert _resolve_slide_cta(SimpleNamespace(cta=""), "Campaign CTA") == ""


def test_provenance_plan_owns_default_cta_and_typed_null_remains_invalid():
    from app.schemas.ai import SlidePlan
    from app.services.orchestrator import _resolve_slide_cta
    from pydantic import ValidationError
    fields = dict(slide_number=1, purpose="hero", headline="Prepared", visual_brief="Prepared")
    plan = SlidePlan(**fields, slide_id="prepared:1")
    assert _resolve_slide_cta(plan, "Campaign CTA") == ""
    with pytest.raises(ValidationError):
        SlidePlan(**fields, cta=None)


def test_renderer_still_rejects_genuine_cta_substitution(tmp_path):
    import hashlib
    from PIL import Image
    from app.schemas.ai import SlidePlan, SlideAssetReference
    from app.services.orchestrator import _resolve_slide_cta
    from app.services.creative.pipeline import SlideCreativeInput, validate_render_slide_contract
    source = tmp_path / "source.png"
    Image.new("RGB", (8, 8)).save(source)
    asset = SlideAssetReference(asset_id="source", role="product", path=str(source),
                                sha256=hashlib.sha256(source.read_bytes()).hexdigest())
    plan = SlidePlan(slide_number=1, purpose="hero", headline="", visual_brief="Prepared", cta="",
                     slide_id="prepared:1", product_asset=asset, selection_rationale="Prepared source")
    creative = SlideCreativeInput(source_image_path=source, slide_plan=plan,
                                   template_id="feature_showcase", platform_key="instagram_square",
                                   headline="", body="", cta=_resolve_slide_cta(plan, "Campaign CTA"))
    validate_render_slide_contract(creative)
    creative.cta = "Campaign CTA"
    with pytest.raises(ValueError, match="Slide copy substitution: cta"):
        validate_render_slide_contract(creative)


@pytest.fixture
def calibration_attestation_case(tmp_path, monkeypatch):
    import json
    from app.schemas.ai import SlidePlan
    from app.services import qa_engine as qa
    from app.services.creative.pipeline import (build_render_context_path, slide_contract_digest,
        complete_slide_text_contract, structural_slide_text)

    plans = [SlidePlan(slide_number=i, slide_id=f"frozen:{i}", purpose="prepared",
                       headline=f"Canonical {i}", body="", cta="",
                       visual_brief="Frozen direction",
                       verified_claim_ids=[f"claim:{i}"],
                       evidence_references=[{"claim_id": f"claim:{i}", "source_ids": ["source"],
                                             "evidence_sha256": "a" * 64, "claim_text": f"Canonical {i}"}],
                       claim_bindings=[{"field_path": "headline", "claim_id": f"claim:{i}",
                                        "assertion_text": f"Canonical {i}"}]) for i in range(1, 7)]
    campaign = SimpleNamespace(id="prepared", target_slide_count=6,
                               target_platforms=["instagram"], languages=["pt-BR"])
    image = tmp_path / "slide1.png"
    image.write_bytes(b"existing-rendered-bytes")
    report = tmp_path / "technical.json"
    report.write_text(json.dumps({"passed": True}))
    context = {"slide_contract": plans[0].model_dump(),
               "slide_contract_sha256": slide_contract_digest(plans[0]),
               "render_sha256": __import__("hashlib").sha256(image.read_bytes()).hexdigest(),
               "complete_text_contract": complete_slide_text_contract(plans[0]),
               "rendered_text_fields": complete_slide_text_contract(plans[0])["fields"],
               "structural_text": structural_slide_text(1, 6)}
    context_path = build_render_context_path(image)
    context_path.write_text(json.dumps(context))
    variant = SimpleNamespace(language="pt-BR", target_platform="instagram", content_type="carousel",
        slide_asset_paths=[str(image)], qa_report_paths=[str(report)], render_format_key="instagram_portrait",
        creative_direction={}, status="RENDERED", qa_status="PASS", qa_hard_fails=[],
        qa_scores={"qa_mode": "CALIBRATION_SUBSET"})
    class Query:
        def filter(self, *args): return self
        def order_by(self, *args): return self
        def all(self): return []
    db = SimpleNamespace(query=lambda *args: Query())
    creative = {"carousel_plan": {"slides": [plan.model_dump() for plan in plans]}}
    monkeypatch.setattr(qa, "_stage_language_variant", lambda data, language: data)
    monkeypatch.setattr(qa, "_load_stage_json", lambda *args: {"headline": "Canonical"})
    seen = []
    monkeypatch.setattr(qa, "validate_slide_provenance", lambda db, campaign, plan: seen.append(plan))
    return SimpleNamespace(qa=qa, db=db, campaign=campaign, variant=variant, creative=creative,
                           plans=plans, context=context, context_path=context_path, seen=seen)


def _calibration_attest(case, **options):
    return case.qa.current_slide_attestations(case.db, case.campaign, case.variant,
        creative_data=case.creative, qa_mode="CALIBRATION_SUBSET", required_slide_numbers=[1], **options)


def test_calibration_scope_is_explicit_and_does_not_shrink_plans(calibration_attestation_case):
    import copy
    c = calibration_attestation_case
    before = copy.deepcopy(c.creative)
    result = _calibration_attest(c)
    assert len(result) == 1 and result[0]["slide_id"] == "frozen:1"
    assert result[0]["qa_mode"] == "CALIBRATION_SUBSET"
    assert c.creative == before and c.campaign.target_slide_count == 6
    assert len(c.seen) == 1
    with pytest.raises(ValueError, match="Missing or duplicate"):
        c.qa.current_slide_attestations(c.db, c.campaign, c.variant, creative_data=c.creative)


@pytest.mark.parametrize("change", ["wrong_slide", "duplicate", "missing", "copy", "claims", "reference", "product", "direction", "structural"])
def test_calibration_subset_rejects_substitutions(calibration_attestation_case, change):
    import json
    c = calibration_attestation_case
    if change == "duplicate": c.variant.slide_asset_paths *= 2
    elif change == "missing": c.variant.slide_asset_paths = []
    else:
        if change == "wrong_slide": c.context["slide_contract"] = c.plans[1].model_dump()
        elif change == "structural": c.context["structural_text"] = {}
        else:
            field = {"copy": "headline", "claims": "verified_claim_ids", "reference": "reference_asset_ids",
                     "product": "product_asset", "direction": "visual_brief"}[change]
            c.context["slide_contract"][field] = ["substituted"] if field.endswith("ids") else "substituted"
        c.context_path.write_text(json.dumps(c.context))
    with pytest.raises(ValueError): _calibration_attest(c)


@pytest.mark.parametrize("mode,numbers", [("FULL_CAMPAIGN", [1]), ("unknown", [1]),
    ("CALIBRATION_SUBSET", [2]), ("CALIBRATION_SUBSET", [1, 1]), ("CALIBRATION_SUBSET", []),
    ("CALIBRATION_SUBSET", None), ("CALIBRATION_SUBSET", [True])])
def test_calibration_rejects_invalid_scope(calibration_attestation_case, mode, numbers):
    c = calibration_attestation_case
    with pytest.raises(ValueError):
        c.qa.current_slide_attestations(c.db, c.campaign, c.variant, creative_data=c.creative,
                                      qa_mode=mode, required_slide_numbers=numbers)


def test_full_campaign_still_rejects_plan_count_mismatch(calibration_attestation_case):
    c = calibration_attestation_case
    c.creative["carousel_plan"]["slides"] = c.creative["carousel_plan"]["slides"][:1]
    with pytest.raises(ValueError, match="campaign slide count"):
        c.qa.current_slide_attestations(c.db, c.campaign, c.variant, creative_data=c.creative)
    with pytest.raises(ValueError, match="six canonical"):
        _calibration_attest(c)


def test_subset_never_approves_full_campaign(calibration_attestation_case):
    c = calibration_attestation_case
    class Query:
        def filter(self, *args): return self
        def all(self): return [c.variant]
    c.db.query = lambda *args: Query()
    with pytest.raises(ValueError, match="cannot approve"):
        c.qa.assert_campaign_creative_qa_current(c.db, c.campaign)


def test_calibration_and_qa_defaults_remain_full_campaign():
    import inspect
    from scripts import run_live_acceptance as runner
    from app.services import qa_engine as qa
    from app.services.orchestrator import run_visuals_stage
    assert inspect.signature(runner.run_prepared_acceptance).parameters["calibration_slide1"].default is False
    assert inspect.signature(run_visuals_stage).parameters["calibration_slide1"].default is False
    assert inspect.signature(qa.run_qa_stage).parameters["qa_mode"].default == "FULL_CAMPAIGN"
    assert inspect.signature(qa.current_slide_attestations).parameters["qa_mode"].default == "FULL_CAMPAIGN"


def test_isolated_calibration_session_does_not_write_source(tmp_path):
    import sqlite3
    import hashlib
    from scripts.run_live_acceptance import isolated_calibration_session
    path = tmp_path / "prepared.db"
    with sqlite3.connect(path) as db:
        db.execute("create table frozen (value text)")
        db.execute("insert into frozen values ('six-slide-plan')")
    before = hashlib.sha256(path.read_bytes()).digest()
    session = isolated_calibration_session(path)
    engine = session.bind
    try:
        session.connection().exec_driver_sql("update frozen set value='isolated-only'")
        session.commit()
        assert all(not row[2] for row in session.connection().exec_driver_sql("pragma database_list").all())
    finally:
        session.close()
        engine.dispose()
    assert hashlib.sha256(path.read_bytes()).digest() == before


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_stage", [None, "visuals", "qa"])
async def test_prepared_calibration_routes_subset_and_stops(monkeypatch, tmp_path, fail_stage):
    import copy
    import json
    from sqlalchemy import create_engine
    from app.models import PlatformCampaignVariant
    from app.schemas.ai import SlidePlan
    from app.services import orchestrator
    from scripts import run_live_acceptance as runner

    plans = [SlidePlan(slide_number=i, slide_id=f"prepared:{i}", purpose="hero", headline="Prepared",
                       visual_brief="Frozen", cta="").model_dump() for i in range(1, 7)]
    before = copy.deepcopy(plans)
    campaign = SimpleNamespace(target_slide_count=6, target_platforms=["instagram"], languages=["pt-BR"],
                               status="COPY_READY")
    variant = SimpleNamespace(slide_asset_paths=[], qa_status="PENDING", qa_scores={}, qa_hard_fails=[],
                              qa_evidence_paths=[])
    engine = create_engine("sqlite:///:memory:")
    connection = engine.connect()
    class Session:
        bind = engine
        def connection(self): return connection
        def get(self, *args): return campaign
        def query(self, model):
            class Query:
                def filter_by(self, **kwargs): return self
                def all(self): return [variant] if model is PlatformCampaignVariant else []
            return Query()
        def commit(self): pass
    monkeypatch.setattr(orchestrator, "_load_stage_json", lambda *args: {"carousel_plan": {"slides": plans}})
    monkeypatch.setattr(orchestrator, "_stage_language_variant", lambda data, language: data)
    monkeypatch.setattr(orchestrator, "validate_slide_provenance", lambda *args: None)
    stages = []
    async def visuals(session, **kwargs):
        stages.append("visuals")
        assert kwargs["calibration_slide1"] is True
        if fail_stage == "visuals": raise RuntimeError("mock failure")
        output = tmp_path / "slide1.png"
        output.write_bytes(b"mock output")
        variant.slide_asset_paths = [str(output)]
    async def qa(session, **kwargs):
        stages.append("qa")
        assert kwargs["qa_mode"] == "CALIBRATION_SUBSET" and kwargs["required_slide_numbers"] == [1]
        if fail_stage == "qa": raise RuntimeError("mock failure")
        variant.qa_status = "PASS"
        return campaign
    monkeypatch.setattr(runner, "run_visuals_stage", visuals)
    monkeypatch.setattr(runner, "run_qa_stage", qa)
    ledger = provider_module._BoundedExposureLedger()
    provider = SimpleNamespace(hard_budget_snapshot=ledger.snapshot)
    config = SimpleNamespace(qa_max_retries=0, qa_best_of_n=1, recreate_with_ai=False,
        use_masked_scene_edit=False, detect_product_zone=False, hero_only=False,
        use_ai_background=True, require_ai_background_success=True, enable_qa_stage=True,
        quality_mode="premium", output_root=tmp_path)
    try:
        if fail_stage:
            with pytest.raises(RuntimeError, match="mock failure"):
                await runner.run_prepared_acceptance(Session(), campaign_id="prepared", config=config,
                    renderer=None, provider=provider, calibration_slide1=True)
            assert stages == (["visuals"] if fail_stage == "visuals" else ["visuals", "qa"])
            failure = json.loads((tmp_path / "calibration-failure.json").read_text())
            assert failure["status"] == "SLIDE1_CALIBRATION_FAILED"
            assert failure["campaign_approval_created"] is False
        else:
            result = await runner.run_prepared_acceptance(Session(), campaign_id="prepared", config=config,
                renderer=None, provider=provider, calibration_slide1=True)
            assert stages == ["visuals", "qa"]
            assert result["stop_reason"] == "SLIDE1_CALIBRATION_COMPLETE"
            assert result["full_carousel_completed"] is False and result["campaign_approval_created"] is False
            assert result["slide1_operator_decision"] == "PENDING"
            assert campaign.status == "COPY_READY"
        assert plans == before and len(plans) == campaign.target_slide_count == 6
    finally:
        connection.close()
        engine.dispose()
