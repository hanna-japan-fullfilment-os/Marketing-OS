"""Build 6 — real AI cost/usage capture (`app/services/usage_tracking.py`,
`OpenAIProvider`'s new usage-accumulation, `AIUsage.platform/language/
content_type`). Unit-level coverage of the machinery itself, separate from
`tests/test_build6_acceptance.py`'s end-to-end pipeline proof.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

from app.models import AIUsage, Brand, Campaign
from app.services.ai.openai_provider import OpenAIProvider, _image_usage_cost, _text_usage_cost
from app.services.usage_tracking import build_campaign_cost_report, drain_provider_usage_events, record_ai_usage, \
    record_stage_usage


def _make_campaign(session):
    brand = Brand(name="Hanna From Japan", slug=f"hanna-{uuid.uuid4().hex[:8]}")
    session.add(brand)
    session.commit()
    campaign = Campaign(
        display_id=f"HANNA-SKIN-{uuid.uuid4().hex[:8]}", brand_id=brand.id, objective="awareness", status="IDEA",
    )
    session.add(campaign)
    session.commit()
    return campaign


# ---------------------------------------------------------------------------
# OpenAIProvider's own usage accumulation (mocked SDK responses — no network).
# ---------------------------------------------------------------------------

def test_openai_provider_records_real_token_counts_from_a_text_response():
    provider = OpenAIProvider(api_key="")  # no client needed; we call the private recorder directly
    fake_response = SimpleNamespace(usage=SimpleNamespace(input_tokens=1200, output_tokens=430))
    provider._record_text_usage(fake_response, "gpt-5.1")

    events = provider.drain_usage_events()
    assert len(events) == 1
    event = events[0]
    assert event["model"] == "gpt-5.1"
    assert event["input_tokens"] == 1200
    assert event["output_tokens"] == 430
    assert event["image_count"] == 0
    assert event["estimated_cost_usd"] > 0

    # drain_usage_events clears the buffer — never double-counted.
    assert provider.drain_usage_events() == []


def test_openai_provider_records_image_counts_and_prices_by_quality_tier():
    provider = OpenAIProvider(api_key="")
    provider._record_image_usage("gpt-image-1", "low", count=1)
    provider._record_image_usage("gpt-image-1", "high", count=1)

    events = provider.drain_usage_events()
    assert len(events) == 2
    assert events[0]["image_count"] == 1 and events[0]["input_tokens"] == 0
    # A higher quality tier costs strictly more per image, per the published
    # pricing table this app documents as approximate/best-effort.
    assert events[1]["estimated_cost_usd"] > events[0]["estimated_cost_usd"]


def test_unrecognized_model_prices_at_zero_rather_than_guessing():
    # Real token/image counts are still real; an unrecognized model simply
    # can't be priced — $0 is the honest fallback, never an invented number.
    assert _text_usage_cost("some-future-model-nobody-has-priced-yet", 10_000, 5_000) == 0.0
    assert _image_usage_cost("some-future-model-nobody-has-priced-yet", "high", 3) == 0.0


# ---------------------------------------------------------------------------
# usage_tracking.py's drain/record/report plumbing.
# ---------------------------------------------------------------------------

def test_drain_provider_usage_events_is_a_harmless_noop_for_a_fake_test_provider():
    class _Fake:
        async def generate_structured(self, **kwargs):
            raise NotImplementedError

    assert drain_provider_usage_events(None) == []
    assert drain_provider_usage_events(_Fake()) == []  # no drain_usage_events method at all


def test_record_stage_usage_writes_one_ai_usage_row_per_drained_event(temp_db):
    session = temp_db.SessionLocal()
    campaign = _make_campaign(session)

    class _ReportingProvider:
        def drain_usage_events(self):
            return [
                {"provider": "openai", "model": "gpt-5.1", "input_tokens": 500, "output_tokens": 200,
                 "image_count": 0, "estimated_cost_usd": 0.003},
                {"provider": "openai", "model": "gpt-image-1", "input_tokens": 0, "output_tokens": 0,
                 "image_count": 1, "estimated_cost_usd": 0.042},
            ]

    written = record_stage_usage(
        session, campaign_id=campaign.id, operation="scene_generation", providers=[_ReportingProvider()],
        platform="instagram", language="", content_type="feed_post",
    )
    session.commit()
    assert len(written) == 2

    rows = session.query(AIUsage).filter(AIUsage.campaign_id == campaign.id).all()
    assert len(rows) == 2
    assert {r.platform for r in rows} == {"instagram"}
    assert {r.content_type for r in rows} == {"feed_post"}
    assert {r.operation for r in rows} == {"scene_generation"}
    assert sum(r.image_count for r in rows) == 1
    session.close()


def test_record_stage_usage_records_nothing_for_a_provider_with_no_events(temp_db):
    session = temp_db.SessionLocal()
    campaign = _make_campaign(session)

    class _SilentProvider:
        def drain_usage_events(self):
            return []

    written = record_stage_usage(
        session, campaign_id=campaign.id, operation="research", providers=[_SilentProvider(), None],
    )
    session.commit()
    assert written == []
    assert session.query(AIUsage).filter(AIUsage.campaign_id == campaign.id).count() == 0
    session.close()


def test_build_campaign_cost_report_is_honestly_empty_with_no_recorded_usage(temp_db):
    session = temp_db.SessionLocal()
    campaign = _make_campaign(session)
    report = build_campaign_cost_report(session, campaign.id)
    assert report["usage_recorded"] is False
    assert report["total_usd"] == 0.0
    assert report["by_operation"] == {}
    assert report["by_variant"] == []
    assert build_campaign_cost_report(session, None) == report  # no campaign_id -> same honest empty shape
    session.close()


def test_build_campaign_cost_report_aggregates_by_operation_and_variant(temp_db):
    session = temp_db.SessionLocal()
    campaign = _make_campaign(session)

    record_ai_usage(
        session, campaign_id=campaign.id, operation="research",
        event={"provider": "openai", "model": "gpt-5.1", "input_tokens": 1000, "output_tokens": 300,
               "image_count": 0, "estimated_cost_usd": 0.004},
    )
    record_ai_usage(
        session, campaign_id=campaign.id, operation="scene_generation",
        event={"provider": "openai", "model": "gpt-image-1", "input_tokens": 0, "output_tokens": 0,
               "image_count": 1, "estimated_cost_usd": 0.167},
        platform="instagram", language="", content_type="feed_post",
    )
    record_ai_usage(
        session, campaign_id=campaign.id, operation="scene_generation",
        event={"provider": "openai", "model": "gpt-image-1", "input_tokens": 0, "output_tokens": 0,
               "image_count": 1, "estimated_cost_usd": 0.167},
        platform="facebook", language="", content_type="feed_post",
    )
    session.commit()

    report = build_campaign_cost_report(session, campaign.id)
    assert report["usage_recorded"] is True
    assert report["call_count"] == 3
    assert report["image_generation_usd"] == round(0.167 + 0.167, 6)
    assert report["text_generation_usd"] == round(0.004, 6)
    assert report["total_usd"] == round(0.004 + 0.167 + 0.167, 6)

    assert set(report["by_operation"].keys()) == {"research", "scene_generation"}
    assert report["by_operation"]["scene_generation"]["call_count"] == 2
    assert report["by_operation"]["scene_generation"]["image_count"] == 2

    variant_keys = {(v["platform"], v["language"], v["content_type"]) for v in report["by_variant"]}
    assert ("instagram", "", "feed_post") in variant_keys
    assert ("facebook", "", "feed_post") in variant_keys
    assert ("", "", "") in variant_keys  # the campaign-wide research call, never fabricated a fake platform for it
    session.close()


def test_build_campaign_cost_report_distinguishes_campaign_global_from_variant_scope(temp_db):
    """Build 6 repair (Critical Defect 7/13): a live-acceptance run had cost
    rows with blank platform/language that were impossible to tell apart from
    a bug versus a genuinely campaign-wide call. `scope` makes that an
    explicit, asserted fact rather than something inferred from blankness —
    verified here against real `AIUsage` rows carrying each scope value.
    """
    session = temp_db.SessionLocal()
    campaign = _make_campaign(session)

    record_ai_usage(
        session, campaign_id=campaign.id, operation="research",
        event={"provider": "openai", "model": "gpt-5.1", "input_tokens": 1000, "output_tokens": 300,
               "image_count": 0, "estimated_cost_usd": 0.004},
        scope="campaign_global",
    )
    record_ai_usage(
        session, campaign_id=campaign.id, operation="scene_generation",
        event={"provider": "openai", "model": "gpt-image-1", "input_tokens": 0, "output_tokens": 0,
               "image_count": 1, "estimated_cost_usd": 0.167},
        platform="instagram", language="pt-BR", content_type="feed_post", scope="variant",
    )
    session.commit()

    rows = session.query(AIUsage).filter(AIUsage.campaign_id == campaign.id).all()
    scopes = {r.operation: r.scope for r in rows}
    assert scopes["research"] == "campaign_global"
    assert scopes["scene_generation"] == "variant"

    report = build_campaign_cost_report(session, campaign.id)
    assert report["by_scope"]["campaign_global"]["call_count"] == 1
    assert report["by_scope"]["variant"]["call_count"] == 1
    assert report["by_scope"]["campaign_global"]["cost_usd"] == round(0.004, 6)
    assert report["by_scope"]["variant"]["cost_usd"] == round(0.167, 6)

    # A pre-migration/legacy row constructed without a `scope` kwarg still
    # gets the model's own honest "variant" default — never a KeyError or a
    # silently-dropped row from the aggregation above.
    default_row = AIUsage(provider="openai", model="gpt-5.1", operation="strategy", campaign_id=campaign.id)
    session.add(default_row)
    session.commit()
    assert default_row.scope == "variant"
    session.close()


def test_cost_report_marks_unpriced_gpt_image_2_5_usage_incomplete(
    temp_db,
):
    session = temp_db.SessionLocal()

    try:
        campaign_id = (
            "stage3b1-unpriced-gpt25"
        )

        record_ai_usage(
            session,
            campaign_id=campaign_id,
            operation="research",
            event={
                "provider": "openai",
                "model": "gpt-5.1",
                "input_tokens": 1000,
                "output_tokens": 300,
                "image_count": 0,
                "estimated_cost_usd": 0.004,
            },
            scope="campaign_global",
        )

        record_ai_usage(
            session,
            campaign_id=campaign_id,
            operation="scene_generation",
            event={
                "provider": "openai",
                "model": "gpt-image-2.5-sunburst-2026-09-08",
                "input_tokens": 0,
                "output_tokens": 0,
                "image_count": 2,
                "estimated_cost_usd": 0.0,
            },
            platform="instagram",
            language="pt-BR",
            content_type="carousel",
            scope="variant",
        )

        session.commit()

        report = (
            build_campaign_cost_report(
                session,
                campaign_id,
            )
        )

        # Backward-compatible dollar fields are known local subtotals.
        assert report[
            "usage_recorded"
        ] is True

        assert report[
            "call_count"
        ] == 2

        assert report[
            "total_usd"
        ] == 0.004

        assert report[
            "known_total_usd"
        ] == 0.004

        assert report[
            "image_generation_usd"
        ] == 0.0

        assert report[
            "text_generation_usd"
        ] == 0.004

        # But the report must never claim that subtotal is the complete bill.
        assert report[
            "cost_status"
        ] == "incomplete_unpriced_usage"

        assert report[
            "cost_complete"
        ] is False

        assert report[
            "total_usd_is_complete"
        ] is False

        assert report[
            "image_generation_usd_is_complete"
        ] is False

        assert report[
            "text_generation_usd_is_complete"
        ] is True

        assert report[
            "unpriced_call_count"
        ] == 1

        assert report[
            "unpriced_image_call_count"
        ] == 1

        assert report[
            "unpriced_text_call_count"
        ] == 0

        assert report[
            "unpriced_image_count"
        ] == 2

        assert report[
            "unpriced_models"
        ] == [
            "gpt-image-2.5-sunburst-2026-09-08"
        ]

        assert report[
            "unpriced_operations"
        ] == [
            "scene_generation"
        ]

        scene_bucket = report[
            "by_operation"
        ][
            "scene_generation"
        ]

        assert scene_bucket[
            "cost_usd"
        ] == 0.0

        assert scene_bucket[
            "known_cost_usd"
        ] == 0.0

        assert scene_bucket[
            "cost_complete"
        ] is False

        assert scene_bucket[
            "unpriced_image_call_count"
        ] == 1

        assert scene_bucket[
            "unpriced_image_count"
        ] == 2

    finally:
        session.close()

