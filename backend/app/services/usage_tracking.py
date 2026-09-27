"""Real AI cost/usage capture (Build 6, Production Integration — carry-forward
requirement 6: "capture real cost/usage per variant... If exact monetary cost
cannot be calculated, record the available usage metrics instead of inventing
estimates.").

Why this module exists: `models/platform.py::AIUsage` has existed since round
1, and `services/benchmark_engine.py::_cost_breakdown_for_campaign` already
read from it — but nothing in this codebase ever WROTE an `AIUsage` row (a
grep confirms zero `AIUsage(` constructor calls before this module), so every
cost report was honestly `{..., "usage_recorded": False}` for every campaign,
always. This module is what actually closes that gap, following the same
"the real number only exists where a real call happened" discipline the rest
of this app already applies to research citations and product facts.

Design (deliberately additive, zero changes to `AIProvider`/`ResearchProvider`/
`ImageProvider`'s Protocol signatures in `services/ai/base.py` — those stay a
fixed contract with no campaign/db-session context of their own, exactly like
`services/prompt_registry.py::record_prompt_usage` already explains for
prompt-version tracking):

- `services/ai/openai_provider.py::OpenAIProvider` is the ONLY provider that
  can know a REAL token count or image count, because it's the only one
  making a real network call — so it accumulates one usage "event" dict per
  real API call into an internal list, and exposes `drain_usage_events()` to
  read-and-clear that list. A test's fake provider simply has no such method,
  so `drain_provider_usage_events` below treats its absence as "no events" —
  never a fabricated zero-cost row, an outright absence, exactly like a
  `BenchmarkRun` made with `_OfflineProvider` produces zero `AIUsage` rows.
- The orchestrator / qa_engine call sites that already call `record_prompt_
  usage` at each real generation point (a call site, never inside the
  low-level generation function — the same reasoning `record_prompt_usage`
  itself documents) are extended to ALSO call `record_stage_usage` right
  there, draining whatever the provider(s) accumulated since the last drain
  and attributing it to that stage's `operation` + platform/language/
  content_type. This gives per-variant, per-stage cost, not just a campaign
  total.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from ..models import AIUsage


def drain_provider_usage_events(provider: object | None) -> list[dict]:
    """Reads and clears whichever real usage events `provider` accumulated
    since the last drain. Returns `[]` for `None`, a fake test provider (no
    `drain_usage_events` method), or a real provider that made no calls since
    the last drain — never invents an event.
    """
    if provider is None:
        return []
    drain = getattr(provider, "drain_usage_events", None)
    if not callable(drain):
        return []
    events = drain()
    return list(events) if events else []


def record_ai_usage(
    db: Session, *, campaign_id: str, operation: str, event: dict,
    platform: str = "", language: str = "", content_type: str = "", scope: str = "variant",
) -> AIUsage:
    """Writes one real usage event as one `AIUsage` row. `event` is one of the
    dicts `OpenAIProvider.drain_usage_events()` returns — see that method for
    the exact keys; every key here defaults to the honest zero/empty value
    when a given event doesn't carry it (e.g. an image call has no token
    counts). Never commits — same best-effort, caller-commits-later
    convention as `prompt_registry.record_prompt_usage`.

    `scope` (Build 6 repair, Critical Defect 7/13): `"campaign_global"` for a
    stage that is genuinely not bound to one requested platform/language
    pairing, `"variant"` (the default) for everything attributed to a
    specific rendered/scripted `PlatformCampaignVariant`. See `AIUsage.scope`
    for the full rationale — this replaces inferring the distinction from
    whether `platform`/`language` happen to be blank, which a live-acceptance
    run showed was genuinely ambiguous.
    """
    row = AIUsage(
        provider=event.get("provider", "openai"),
        model=event.get("model", ""),
        operation=operation,
        campaign_id=campaign_id,
        input_tokens=event.get("input_tokens", 0),
        output_tokens=event.get("output_tokens", 0),
        image_count=event.get("image_count", 0),
        estimated_cost_usd=event.get("estimated_cost_usd", 0.0),
        duration_ms=event.get("duration_ms", 0),
        platform=platform,
        language=language,
        content_type=content_type,
        scope=scope,
    )
    db.add(row)
    return row


def record_stage_usage(
    db: Session, *, campaign_id: str, operation: str,
    providers: list[object | None], platform: str = "", language: str = "", content_type: str = "",
    scope: str = "variant",
) -> list[AIUsage]:
    """Drains every provider in `providers` (typically `[ai_provider]`,
    `[image_provider]`, or both) and records one `AIUsage` row per real event
    found, attributed to this one stage/variant. Call this at the SAME call
    site `record_prompt_usage` is already called from — right after the real
    generation call it's paired with — never inside a low-level generation
    helper. Returns the rows written (usually `[]` in every test, since fake
    providers never accumulate events — that's the correct, honest result,
    not a bug).

    `scope` (Build 6 repair): pass `"campaign_global"` explicitly from a call
    site whose cost isn't tied to one specific requested platform/language
    pairing (research, strategy, creative_brief, master_campaign_concept,
    campaign_copy, carousel_plan) — every other call site's default
    `"variant"` is correct as-is.
    """
    written: list[AIUsage] = []
    for provider in providers:
        for event in drain_provider_usage_events(provider):
            written.append(record_ai_usage(
                db, campaign_id=campaign_id, operation=operation, event=event,
                platform=platform, language=language, content_type=content_type, scope=scope,
            ))
    return written


def build_campaign_cost_report(
    db: Session,
    campaign_id: str | None,
) -> dict:
    """Build an honest persisted-usage cost report.

    Backward-compatible numeric fields such as `total_usd`,
    `image_generation_usd`, and bucket-level `cost_usd` remain the sum of
    dollar amounts that this application can actually price locally.

    They are therefore *known local subtotals*, not automatically the exact
    provider bill. A persisted usage row with a non-positive dollar amount is
    treated as unpriced usage: the row and its token/image counts remain real,
    but its provider cost is not invented.

    This matters especially for GPT Image 2.5 image generation, where the app
    can persist that an image call happened while not having an authoritative
    local dollar amount for that call.

    Consumers that need to know whether the numeric subtotal is the complete
    cost must inspect `total_usd_is_complete` / `cost_status`.
    """
    empty = {
        # Original compatibility contract.
        "total_usd": 0.0,
        "image_generation_usd": 0.0,
        "text_generation_usd": 0.0,
        "call_count": 0,
        "usage_recorded": False,
        "by_operation": {},
        "by_variant": [],
        "by_scope": {},

        # Stage 3B1 explicit completeness contract.
        "known_total_usd": 0.0,
        "known_image_generation_usd": 0.0,
        "known_text_generation_usd": 0.0,
        "cost_status": "no_usage",
        "cost_complete": False,
        "total_usd_is_complete": False,
        "image_generation_usd_is_complete": False,
        "text_generation_usd_is_complete": False,
        "unpriced_call_count": 0,
        "unpriced_image_call_count": 0,
        "unpriced_text_call_count": 0,
        "unpriced_image_count": 0,
        "unpriced_models": [],
        "unpriced_operations": [],
    }

    if not campaign_id:
        return empty

    rows = (
        db.query(
            AIUsage
        )
        .filter(
            AIUsage.campaign_id
            == campaign_id
        )
        .all()
    )

    if not rows:
        return empty

    def row_cost(
        row: AIUsage,
    ) -> float:
        return float(
            row.estimated_cost_usd
            or 0.0
        )

    def row_is_unpriced(
        row: AIUsage,
    ) -> bool:
        # A real persisted provider call with no positive local dollar value
        # is unknown/unpriced, never a claim that the provider charged $0.
        return (
            row_cost(
                row
            )
            <= 0.0
        )

    unpriced_rows = [
        row
        for row in rows
        if row_is_unpriced(
            row
        )
    ]

    unpriced_image_rows = [
        row
        for row in unpriced_rows
        if (
            row.image_count
            or 0
        )
        > 0
    ]

    unpriced_text_rows = [
        row
        for row in unpriced_rows
        if (
            row.image_count
            or 0
        )
        <= 0
    ]

    image_cost = sum(
        row_cost(
            row
        )
        for row in rows
        if (
            row.image_count
            or 0
        )
        > 0
    )

    text_cost = sum(
        row_cost(
            row
        )
        for row in rows
        if (
            row.image_count
            or 0
        )
        <= 0
    )

    known_total = round(
        image_cost
        + text_cost,
        6,
    )

    image_complete = (
        len(
            unpriced_image_rows
        )
        == 0
    )

    text_complete = (
        len(
            unpriced_text_rows
        )
        == 0
    )

    total_complete = (
        len(
            unpriced_rows
        )
        == 0
    )

    def update_cost_integrity(
        bucket: dict,
        row: AIUsage,
    ) -> None:
        cost = row_cost(
            row
        )

        bucket[
            "cost_usd"
        ] = round(
            bucket[
                "cost_usd"
            ]
            + cost,
            6,
        )

        bucket[
            "known_cost_usd"
        ] = bucket[
            "cost_usd"
        ]

        if row_is_unpriced(
            row
        ):
            bucket[
                "cost_complete"
            ] = False

            bucket[
                "unpriced_call_count"
            ] += 1

            if (
                row.image_count
                or 0
            ) > 0:
                bucket[
                    "unpriced_image_call_count"
                ] += 1

                bucket[
                    "unpriced_image_count"
                ] += int(
                    row.image_count
                    or 0
                )

    by_operation: dict[
        str,
        dict,
    ] = {}

    for row in rows:

        bucket = by_operation.setdefault(
            row.operation,
            {
                "cost_usd": 0.0,
                "known_cost_usd": 0.0,
                "cost_complete": True,
                "unpriced_call_count": 0,
                "unpriced_image_call_count": 0,
                "unpriced_image_count": 0,
                "call_count": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "image_count": 0,
            },
        )

        update_cost_integrity(
            bucket,
            row,
        )

        bucket[
            "call_count"
        ] += 1

        bucket[
            "input_tokens"
        ] += (
            row.input_tokens
            or 0
        )

        bucket[
            "output_tokens"
        ] += (
            row.output_tokens
            or 0
        )

        bucket[
            "image_count"
        ] += (
            row.image_count
            or 0
        )

    by_variant_key: dict[
        tuple[
            str,
            str,
            str,
        ],
        dict,
    ] = {}

    for row in rows:

        key = (
            row.platform,
            row.language,
            row.content_type,
        )

        bucket = by_variant_key.setdefault(
            key,
            {
                "platform": row.platform,
                "language": row.language,
                "content_type": row.content_type,
                "cost_usd": 0.0,
                "known_cost_usd": 0.0,
                "cost_complete": True,
                "unpriced_call_count": 0,
                "unpriced_image_call_count": 0,
                "unpriced_image_count": 0,
                "call_count": 0,
            },
        )

        update_cost_integrity(
            bucket,
            row,
        )

        bucket[
            "call_count"
        ] += 1

    by_scope: dict[
        str,
        dict,
    ] = {}

    for row in rows:

        scope = (
            getattr(
                row,
                "scope",
                "",
            )
            or "variant"
        )

        bucket = by_scope.setdefault(
            scope,
            {
                "cost_usd": 0.0,
                "known_cost_usd": 0.0,
                "cost_complete": True,
                "unpriced_call_count": 0,
                "unpriced_image_call_count": 0,
                "unpriced_image_count": 0,
                "call_count": 0,
            },
        )

        update_cost_integrity(
            bucket,
            row,
        )

        bucket[
            "call_count"
        ] += 1

    unpriced_models = sorted(
        {
            str(
                row.model
                or ""
            )
            for row in unpriced_rows
        }
    )

    unpriced_operations = sorted(
        {
            str(
                row.operation
                or ""
            )
            for row in unpriced_rows
        }
    )

    unpriced_image_count = sum(
        int(
            row.image_count
            or 0
        )
        for row in unpriced_image_rows
    )

    cost_status = (
        "complete"
        if total_complete
        else "incomplete_unpriced_usage"
    )

    return {
        # Original compatibility contract. These values are now explicitly
        # documented as known local subtotals.
        "total_usd": known_total,
        "image_generation_usd": round(
            image_cost,
            6,
        ),
        "text_generation_usd": round(
            text_cost,
            6,
        ),
        "call_count": len(
            rows
        ),
        "usage_recorded": True,
        "by_operation": by_operation,
        "by_variant": sorted(
            by_variant_key.values(),
            key=lambda value: (
                value[
                    "platform"
                ],
                value[
                    "language"
                ],
                value[
                    "content_type"
                ],
            ),
        ),
        "by_scope": by_scope,

        # Stage 3B1 explicit completeness contract.
        "known_total_usd": known_total,
        "known_image_generation_usd": round(
            image_cost,
            6,
        ),
        "known_text_generation_usd": round(
            text_cost,
            6,
        ),
        "cost_status": cost_status,
        "cost_complete": total_complete,
        "total_usd_is_complete": total_complete,
        "image_generation_usd_is_complete": image_complete,
        "text_generation_usd_is_complete": text_complete,
        "unpriced_call_count": len(
            unpriced_rows
        ),
        "unpriced_image_call_count": len(
            unpriced_image_rows
        ),
        "unpriced_text_call_count": len(
            unpriced_text_rows
        ),
        "unpriced_image_count": unpriced_image_count,
        "unpriced_models": unpriced_models,
        "unpriced_operations": unpriced_operations,
    }
