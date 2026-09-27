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
        hard_budget_usd=1.00,
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
