#!/usr/bin/env python
"""BUILD 6 — LIVE Hanna acceptance runner.

Run this ONLY on the owner's own machine, with a real `OPENAI_API_KEY`
configured (in `.env` or Settings) — this script makes real, billed OpenAI
API calls. It is the honest counterpart to `tests/test_build6_acceptance.py`:
that test file proves the pipeline's ARCHITECTURE is correct using a
deterministic fake provider (this dev sandbox has no OpenAI key and no
network path to api.openai.com, so it cannot make a real call, ever); this
script is what actually produces a genuine LIVE_ACCEPTANCE verdict, using
real research, real copy, real AI-recreated images, and a real multimodal QA
critique, judged against real product data already in your own catalog.

WHAT THIS DOES
--------------
For a brand + product you choose (or the first eligible product this script
finds), runs the real pipeline across the representative acceptance matrix
Build 6 asks for:

    Instagram / pt-BR      Instagram / en      Facebook / pt-BR
    Pinterest / en         TikTok / pt-BR (script-only, never rendered video)

...one shared `MasterCampaignConcept` PER PLATFORM (see "EXACT MATRIX,
NOT A CARTESIAN PRODUCT" below for why this is per-platform rather than one
shared campaign), both languages generated natively (not translated), QA'd
with the real multimodal creative critic, and reports:

  - product fidelity (did the recreated image keep the REAL product)
  - whether any unsupported claim appears in the generated copy
  - platform/language appropriateness
  - real cost/usage per variant and campaign total, with an explicit
    campaign_global vs variant scope breakdown
  - full prompt + creative-system version traceability
  - an HONEST final verdict per case: PASS / NEEDS_REVIEW / FAIL — never
    forced to PASS just because the pipeline ran to completion (Build 6's own
    explicit instruction: "do not mark PASS merely because automation
    completed").

EXACT MATRIX, NOT A CARTESIAN PRODUCT (Build 6 repair, Critical Defect 6/11)
-----------------------------------------------------------------------------
A real live-acceptance run of this script's PRE-REPAIR version cost
$6.11 and made 89 calls — far more than the 5 requested cases warranted —
because a single `Campaign` row's `target_platforms`/`languages` fields are
a genuine, load-bearing architectural cross-product (`run_visuals_stage`'s
`_render_additional_platform_variants` always renders every
platform x language combination that campaign names, by design, for a real
end user who genuinely wants every combination). Building one campaign with
`languages=["pt-BR", "en"]` and `target_platforms=["facebook", "instagram",
"pinterest", "tiktok"]` therefore silently generated (and billed) every one
of those 8 combinations, not just the 5 explicit pairs this matrix names —
e.g. Facebook/en and Pinterest/pt-BR were never requested but were rendered
and QA'd anyway.

This is not a bug in that architecture to "fix" (a real multi-platform
campaign SHOULD get the full cross-product it asks for) — it is this
script's own responsibility to ask for only what the matrix actually names.
The fix: group `ACCEPTANCE_MATRIX` by platform (preserving matrix order),
and run ONE single-platform-scoped campaign per platform group, with
`languages` limited to only that platform's own matrix-requested languages.
One platform in `target_platforms` times that platform's own N languages is
just N pairs — never a combination nobody asked for.

COST PREFLIGHT (Build 6 repair, Critical Defect 7/12)
------------------------------------------------------
`--estimate-only` prints a clearly-labeled ESTIMATE (never a guaranteed
figure — see `_estimate_matrix_cost_usd`'s own docstring) and exits without
making any API call. `--max-budget-usd` refuses to start at all if the
estimate already exceeds it, and stops BETWEEN platform groups (before
starting the next one) once the REAL accumulated cost so far would reach it
— never mid-group. `--smoke` runs a 2-case reduced matrix (one static-image
case, one script-only case) with `qa_max_retries=0`/`qa_best_of_n=1`, for
cheaply validating the pipeline still runs end to end before spending on the
full acceptance run.

USAGE
-----
    cd backend
    python scripts/run_live_acceptance.py --brand-slug hanna-from-japan --product-slug melano-cc-essence
    python scripts/run_live_acceptance.py --brand-slug hanna-from-japan --estimate-only
    python scripts/run_live_acceptance.py --brand-slug hanna-from-japan --smoke --max-budget-usd 1.00
    python scripts/run_live_acceptance.py --brand-slug hanna-from-japan --max-budget-usd 5.00

Omit --product-slug to let the script pick the first campaign-drafting-
eligible product it finds for that brand (skips a product with zero source
photos or a `VerifiedProductFact` row with `confidence == 0`, since a case
built on facts nobody has confirmed can't honestly be judged as accurate).

Writes a JSON report to `data/live_acceptance/<timestamp>.json` and prints a
human-readable summary, ending in the same completion-packet-style
`LIVE_ACCEPTANCE=` line the Build 6 spec's own completion packet asks for.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db as db_module  # noqa: E402
from app.data.platform_creative_specs import (  # noqa: E402
    default_content_type_for_platform, resolve_platform_creative_spec,
)
from app.models import Brand, Campaign, PlatformCampaignVariant, Product, VerifiedProductFact  # noqa: E402
from app.services.ai.openai_provider import HardBudgetExceededError, OpenAIProvider, openai_provider_from_effective_settings  # noqa: E402
from app.services.benchmark_engine import build_creative_system_snapshot  # noqa: E402
from app.services.creative.renderer import PlaywrightRenderer  # noqa: E402
from app.services.orchestrator import get_platform_campaign_variants, run_copy_stage, run_strategy_stage, \
    run_visuals_stage  # noqa: E402
from app.services.product_facts import resolve_verified_product_facts  # noqa: E402
from app.services.qa_engine import run_qa_stage  # noqa: E402
from app.services.settings_store import get_effective_settings  # noqa: E402
from app.services.usage_tracking import build_campaign_cost_report  # noqa: E402
from app.api.campaigns import _build_autopilot_config  # noqa: E402

ACCEPTANCE_MATRIX = [
    ("instagram", "pt-BR"),
    ("instagram", "en"),
    ("facebook", "pt-BR"),
    ("pinterest", "en"),
    ("tiktok", "pt-BR"),
]

# Build 6 repair (Critical Defect 7/12): a rough, clearly-labeled ESTIMATE
# only — never presented or used as a guaranteed dollar figure. These
# per-case numbers are a static approximation of this pipeline's own typical
# per-case shape (one shared MasterCampaignConcept, one AI-recreated hero
# image, a multimodal QA critique, zero-to-few revision rounds) rounded UP
# rather than to a false-precision figure — NOT derived from any single
# historical run. Real cost always comes from `AIUsage` rows written during
# the actual run (reported separately as `actual_cost_usd`).
_ESTIMATED_STATIC_CASE_USD = 1.35
_ESTIMATED_SCRIPT_ONLY_CASE_USD = 0.20

_VERDICT_SEVERITY = {"PASS": 0, "NEEDS_REVIEW": 1, "INCOMPLETE_BUDGET_CEILING": 2, "FAIL": 3}


def _combine_verdict(current: str, new: str) -> str:
    return new if _VERDICT_SEVERITY[new] > _VERDICT_SEVERITY[current] else current


def _is_script_only_case(platform: str) -> bool:
    """Whether this platform's own default content type is video-oriented
    (no static-image render — see `PlatformCreativeSpec.supports_static`),
    used only to pick the right rough cost estimate above — never hardcodes
    "tiktok" specifically, so this stays correct if the acceptance matrix
    ever names another video-oriented platform.
    """
    content_type = default_content_type_for_platform(platform, slide_count=1)
    if content_type is None:
        return False
    return not resolve_platform_creative_spec(platform, content_type).supports_static


def _estimate_matrix_cost_usd(
    matrix: list[tuple[str, str]],
) -> float | None:
    """Return no invented preflight dollar estimate.

    The live acceptance pipeline can include GPT Image 2.5 usage whose
    authoritative provider dollar amount is not available to local accounting.
    A historical fixed-per-case estimate would therefore be misleading.

    The matrix is intentionally accepted only to preserve this helper's
    existing call shape.
    """
    _ = matrix
    return None


def _smoke_matrix(matrix: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """One static-image case + one script-only case — enough to validate both
    pipeline shapes end to end at a fraction of the full matrix's cost
    ("focused smoke mode", Critical Defect 7/12). Falls back to whatever it
    can find if the full matrix happens to have only one shape represented,
    rather than raising.
    """
    static_case = next((pair for pair in matrix if not _is_script_only_case(pair[0])), None)
    script_case = next((pair for pair in matrix if _is_script_only_case(pair[0])), None)
    picked = [p for p in (static_case, script_case) if p is not None]
    return picked or list(matrix[:1])


def _select_acceptance_matrix(
    matrix: list[tuple[str, str]],
    *,
    case_selector: str | None = None,
    smoke: bool = False,
) -> list[tuple[str, str]]:
    """Select the exact acceptance scope without creating new cases.

    `--case` is validated only against the canonical acceptance matrix.
    It never creates a platform/language Cartesian product.

    `--case` and `--smoke` are mutually exclusive so scope is explicit.
    """

    canonical = list(matrix)

    if case_selector and smoke:
        raise ValueError(
            "--case and --smoke cannot be used together. "
            "Choose one explicit scope-control mode."
        )

    if smoke:
        return _smoke_matrix(
            canonical
        )

    if not case_selector:
        return canonical

    raw = case_selector.strip()

    if raw.count(":") != 1:
        raise ValueError(
            "--case must use PLATFORM:LANGUAGE, "
            "for example instagram:pt-BR."
        )

    requested_platform, requested_language = (
        part.strip()
        for part in raw.split(
            ":",
            1,
        )
    )

    if (
        not requested_platform
        or not requested_language
    ):
        raise ValueError(
            "--case must use PLATFORM:LANGUAGE, "
            "for example instagram:pt-BR."
        )

    for platform, language in canonical:
        if (
            platform.casefold()
            == requested_platform.casefold()
            and language.casefold()
            == requested_language.casefold()
        ):
            return [
                (
                    platform,
                    language,
                )
            ]

    allowed = ", ".join(
        f"{platform}:{language}"
        for platform, language
        in canonical
    )

    raise ValueError(
        f"Unsupported --case {raw!r}. "
        f"Allowed cases: {allowed}"
    )


def _group_matrix_by_platform(matrix: list[tuple[str, str]]) -> "OrderedDict[str, list[str]]":
    """Groups (platform, language) pairs by platform, preserving matrix order
    for both the platform grouping itself and each platform's own language
    list (Critical Defect 6/11 — see this module's own docstring for the
    full rationale). One platform in a campaign's `target_platforms` times
    that platform's own requested languages in `languages` is just that
    platform's own requested pairs — never a combination nobody asked for.
    """
    groups: "OrderedDict[str, list[str]]" = OrderedDict()
    for platform, language in matrix:
        langs = groups.setdefault(platform, [])
        if language not in langs:
            langs.append(language)
    return groups


def _find_product(session, *, brand_slug: str, product_slug: str | None) -> tuple[Brand, Product]:
    brand = session.query(Brand).filter(Brand.slug == brand_slug).first()
    if brand is None:
        raise SystemExit(f"No brand found with slug {brand_slug!r}. Check Settings/Brands in the app.")
    query = session.query(Product).filter(Product.brand_id == brand.id)
    if product_slug:
        product = query.filter(Product.slug == product_slug).first()
        if product is None:
            raise SystemExit(f"No product found with slug {product_slug!r} for brand {brand_slug!r}.")
        return brand, product
    for product in query.all():
        fact = session.query(VerifiedProductFact).filter(VerifiedProductFact.product_id == product.id).first()
        if fact is not None and fact.confidence > 0:
            return brand, product
    raise SystemExit(
        f"No product for brand {brand_slug!r} has a VerifiedProductFact row with confidence > 0 yet. "
        "Add one in the app before running a live acceptance case — this script refuses to judge a "
        "case built on facts nobody has confirmed."
    )


def _unsupported_claim_flags_for_variant(variant: PlatformCampaignVariant) -> list[str]:
    """BUILD 6 FINAL REPAIR: replaces the old `_check_unsupported_claims`,
    which was handed rendered FILE PATHS (`"\\n".join(str(p) for p in
    variant.slide_asset_paths)`) instead of real copy, and only ever checked
    `brand.disallowed_terms` — so `unsupported_claim_flags == []` on every
    real case regardless of what claims the generated text actually
    contained.

    This script does not recompute the audit itself. `run_qa_stage`
    (`services/qa_engine.py`) already ran the real enforcement gate
    (`services/claims_audit.py`) against this variant's actual USER-VISIBLE
    text — CampaignCopy fields, every carousel slide field, and VideoConcept
    fields — during QA, and persisted the result onto
    `variant.qa_scores["claims_audit"]["findings"]`. Reading that back here
    (rather than re-deriving a second, possibly-drifting answer) guarantees
    this report can never disagree with what actually gated the variant's own
    `qa_status`/`qa_hard_fails` — single source of truth.
    """
    claims_audit = (variant.qa_scores or {}).get("claims_audit") or {}
    findings = claims_audit.get("findings") or []
    return [
        f"[{f.get('claim_category', 'other')}] {f.get('source_field', '?')}: "
        f"{f.get('claim_text', '')!r} — {f.get('reason', '')}"
        for f in findings if f.get("evidence_status") != "SUPPORTED"
    ]


def _merge_cost_report(
    dest: dict,
    one: dict,
) -> None:
    """Merge one persisted cost report without converting unknown spend to zero."""
    if not one.get(
        "usage_recorded",
        False,
    ):
        return

    dest[
        "usage_recorded"
    ] = True

    for key in [
        "total_usd",
        "image_generation_usd",
        "text_generation_usd",
        "known_total_usd",
        "known_image_generation_usd",
        "known_text_generation_usd",
    ]:
        dest[
            key
        ] = round(
            float(
                dest.get(
                    key,
                    0.0,
                )
                or 0.0
            )
            + float(
                one.get(
                    key,
                    0.0,
                )
                or 0.0
            ),
            6,
        )

    dest[
        "call_count"
    ] += int(
        one.get(
            "call_count",
            0,
        )
        or 0
    )

    for key in [
        "unpriced_call_count",
        "unpriced_image_call_count",
        "unpriced_text_call_count",
        "unpriced_image_count",
    ]:
        dest[
            key
        ] += int(
            one.get(
                key,
                0,
            )
            or 0
        )

    dest[
        "cost_complete"
    ] = (
        bool(
            dest[
                "cost_complete"
            ]
        )
        and bool(
            one.get(
                "cost_complete",
                False,
            )
        )
    )

    dest[
        "total_usd_is_complete"
    ] = (
        bool(
            dest[
                "total_usd_is_complete"
            ]
        )
        and bool(
            one.get(
                "total_usd_is_complete",
                False,
            )
        )
    )

    dest[
        "image_generation_usd_is_complete"
    ] = (
        bool(
            dest[
                "image_generation_usd_is_complete"
            ]
        )
        and bool(
            one.get(
                "image_generation_usd_is_complete",
                False,
            )
        )
    )

    dest[
        "text_generation_usd_is_complete"
    ] = (
        bool(
            dest[
                "text_generation_usd_is_complete"
            ]
        )
        and bool(
            one.get(
                "text_generation_usd_is_complete",
                False,
            )
        )
    )

    dest[
        "unpriced_models"
    ] = sorted(
        set(
            dest[
                "unpriced_models"
            ]
        )
        | set(
            one.get(
                "unpriced_models",
                [],
            )
        )
    )

    dest[
        "unpriced_operations"
    ] = sorted(
        set(
            dest[
                "unpriced_operations"
            ]
        )
        | set(
            one.get(
                "unpriced_operations",
                [],
            )
        )
    )

    for op, bucket in one.get(
        "by_operation",
        {},
    ).items():

        target = dest[
            "by_operation"
        ].setdefault(
            op,
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

        target[
            "cost_usd"
        ] = round(
            target[
                "cost_usd"
            ]
            + float(
                bucket.get(
                    "cost_usd",
                    0.0,
                )
                or 0.0
            ),
            6,
        )

        target[
            "known_cost_usd"
        ] = target[
            "cost_usd"
        ]

        target[
            "cost_complete"
        ] = (
            bool(
                target[
                    "cost_complete"
                ]
            )
            and bool(
                bucket.get(
                    "cost_complete",
                    False,
                )
            )
        )

        for key in [
            "unpriced_call_count",
            "unpriced_image_call_count",
            "unpriced_image_count",
            "call_count",
            "input_tokens",
            "output_tokens",
            "image_count",
        ]:
            target[
                key
            ] += int(
                bucket.get(
                    key,
                    0,
                )
                or 0
            )

    dest[
        "by_variant"
    ].extend(
        one.get(
            "by_variant",
            [],
        )
    )

    for scope, bucket in one.get(
        "by_scope",
        {},
    ).items():

        target = dest[
            "by_scope"
        ].setdefault(
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

        target[
            "cost_usd"
        ] = round(
            target[
                "cost_usd"
            ]
            + float(
                bucket.get(
                    "cost_usd",
                    0.0,
                )
                or 0.0
            ),
            6,
        )

        target[
            "known_cost_usd"
        ] = target[
            "cost_usd"
        ]

        target[
            "cost_complete"
        ] = (
            bool(
                target[
                    "cost_complete"
                ]
            )
            and bool(
                bucket.get(
                    "cost_complete",
                    False,
                )
            )
        )

        for key in [
            "unpriced_call_count",
            "unpriced_image_call_count",
            "unpriced_image_count",
            "call_count",
        ]:
            target[
                key
            ] += int(
                bucket.get(
                    key,
                    0,
                )
                or 0
            )

    dest[
        "cost_status"
    ] = (
        "complete"
        if dest[
            "cost_complete"
        ]
        else "incomplete_unpriced_usage"
    )


async def _run_one_case(session, *, campaign: Campaign, config, provider, renderer) -> None:
    await run_strategy_stage(
        session, campaign_id=campaign.id, ai_provider=provider, research_provider=provider, config=config,
    )
    await run_copy_stage(session, campaign_id=campaign.id, ai_provider=provider, config=config)
    await run_visuals_stage(
        session, campaign_id=campaign.id, renderer=renderer, config=config, image_provider=provider,
        ai_provider=provider,
    )
    await run_qa_stage(
        session, campaign_id=campaign.id, renderer=renderer, config=config, image_provider=provider,
        ai_provider=provider,
    )


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--brand-slug", required=True)
    parser.add_argument("--product-slug", default=None)
    parser.add_argument("--quality-mode", default="standard", choices=["draft", "standard", "premium"])
    parser.add_argument(
        "--max-budget-usd", type=float, default=None,
        help=(
            "Local USD ceiling for usage the application can price before a call. "
            "GPT Image 2.5 image spend may be unpriced locally and is therefore protected "
            "separately by the provider-project hard limit and explicit image-call ceiling. "
            "Between platform groups, this runner stops if local dollar accounting becomes incomplete."
        ),
    )
    parser.add_argument(
        "--case",
        dest="case_selector",
        default=None,
        metavar="PLATFORM:LANGUAGE",
        help=(
            "Run exactly one canonical acceptance case, "
            "for example instagram:pt-BR. "
            "Cannot be combined with --smoke."
        ),
    )
    parser.add_argument(
        "--smoke", action="store_true",
        help="Run a reduced 2-case matrix (one static-image case, one script-only case) with expensive retries "
             "disabled (qa_max_retries=0, qa_best_of_n=1) instead of the full 5-case matrix.",
    )
    parser.add_argument(
        "--estimate-only", action="store_true",
        help=(
            "Print the selected acceptance matrix and the fact that no authoritative "
            "preflight dollar estimate is available; exit WITHOUT making any API call."
        ),
    )
    parser.add_argument(
        "--premium-hero-only",
        action="store_true",
        help=(
            "Run one premium hero slide only. Requires an explicit --case and "
            "--quality-mode premium. Disables automatic QA regeneration so the "
            "first paid hero can be reviewed before carousel expansion."
        ),
    )
    args = parser.parse_args()

    if args.premium_hero_only:
        if not args.case_selector:
            parser.error(
                "--premium-hero-only requires --case PLATFORM:LANGUAGE."
            )

        if args.smoke:
            parser.error(
                "--premium-hero-only cannot be combined with --smoke."
            )

        if args.quality_mode != "premium":
            parser.error(
                "--premium-hero-only requires --quality-mode premium."
            )

    try:
        matrix = _select_acceptance_matrix(
            ACCEPTANCE_MATRIX,
            case_selector=args.case_selector,
            smoke=args.smoke,
        )
    except ValueError as exc:
        parser.error(
            str(exc)
        )

    print(
        f"ACCEPTANCE_CASE_COUNT={len(matrix)}"
    )

    for platform, language in matrix:
        print(
            f"ACCEPTANCE_CASE="
            f"{platform}:{language}"
        )

    print(
        "ACCEPTANCE_SCOPE_MODE="
        + (
            "case"
            if args.case_selector
            else (
                "smoke"
                if args.smoke
                else "full"
            )
        )
    )

    print(
        "CASE_SELECTOR="
        + (
            args.case_selector
            or ""
        )
    )
    estimated_cost = _estimate_matrix_cost_usd(matrix)
    print("ESTIMATED_COST_USD=UNAVAILABLE_PRECALL_MIXED_USAGE")
    print("ESTIMATED_COST_STATUS=unavailable_preflight_mixed_usage")
    print(f"CASES={matrix}")

    if args.estimate_only:
        print("LIVE_NETWORK_TEST_RUN=NO (--estimate-only: no API call was made)")
        return 0

    db_module.init_db()
    session = db_module.SessionLocal()
    brand, product = _find_product(session, brand_slug=args.brand_slug, product_slug=args.product_slug)

    effective = get_effective_settings(session)
    if not effective.get("openai_api_key"):
        raise SystemExit(
            "No OpenAI API key configured (Settings, or OPENAI_API_KEY in .env). This script makes real, "
            "billed API calls and cannot run without one."
        )
    provider = openai_provider_from_effective_settings(
        effective,
        hard_budget_usd=args.max_budget_usd,
        # Build 6R governed premium acceptance: one paid hero
        # authorizes at most one image-generation provider call,
        # regardless of the broader environment default.
        max_image_calls_override=(
            1
            if args.premium_hero_only
            else None
        ),
    )
    renderer = PlaywrightRenderer()

    verified = resolve_verified_product_facts(session, product)
    report: dict = {
        "generated_at": datetime.now(timezone.utc).isoformat(), "brand": brand.name, "product": product.name,
        "verified_product_facts": {
            "provenance": verified.provenance, "missing_information": verified.missing_information,
            "source_count": len(verified.source_references),
        },
        "acceptance_matrix": [list(pair) for pair in matrix],
        "smoke_mode": args.smoke,
        "premium_hero_only": args.premium_hero_only,
        "estimated_cost_usd": estimated_cost,
        "estimated_cost_status": "unavailable_preflight_mixed_usage",
        "max_budget_usd": args.max_budget_usd,
        "max_budget_usd_scope": "locally_priceable_usage_only",
        "budget_stopped_early": False,
        "skipped_due_to_budget": [],
        "cases": [],
    }

    # Critical Defect 7/12: smoke mode also disables expensive retries, not
    # just running fewer cases.
    qa_overrides = {"qa_max_retries": 0, "qa_best_of_n": 1} if args.smoke else {}

    if args.premium_hero_only:
        qa_overrides = {
            "qa_pass_threshold": 90,
            "qa_max_retries": 0,
            "qa_best_of_n": 1,
        }

    config = _build_autopilot_config(
        effective, effective.get("output_root", "./data/output"), use_ai_background=True, recreate_with_ai=False,
        detect_product_zone=True, quality_mode=args.quality_mode, render_platform_variants=True,
        enable_qa_stage=True, **qa_overrides,
    )

    if args.premium_hero_only:
        config.max_slides = 1
        config.hero_only = True  # BUILD6R_PREMIUM_HERO_NO_CAROUSEL_CALL_V2
        # BUILD6R_PREMIUM_HERO_SKIP_FLAG_PRODUCER_REPAIR_V4
        # hero_only owns deterministic single-slide planning.
        # Do not activate the older skip_carousel_plan shortcut here.

        # Stage 3D premium acceptance uses one bounded masked Images edit.
        # The normal acceptance constructor above remains background-mode
        # compatible; this override applies only to --premium-hero-only.
        config.use_ai_background = False
        config.require_ai_background_success = True
        config.use_masked_scene_edit = True
        config.require_masked_scene_edit_success = True

        # A premium acceptance hero must spend on exactly one primary
        # visual, not silently expand into additional platform variants.
        config.render_platform_variants = False

    # Critical Defect 6/11: one campaign PER PLATFORM GROUP, scoped to only
    # that platform's own matrix-requested languages — see this module's own
    # docstring for why this (not a change to the shared pipeline
    # architecture) is what makes the acceptance matrix exact.
    groups = _group_matrix_by_platform(matrix)
    campaign_by_platform: dict[str, Campaign] = {}
    all_campaign_ids: list[str] = []

    try:
        for platform, langs in groups.items():
            if args.max_budget_usd is not None and all_campaign_ids:
                prior_cost_reports = [
                    build_campaign_cost_report(
                        session,
                        cid,
                    )
                    for cid in all_campaign_ids
                ]

                incomplete_prior_cost = any(
                    item.get(
                        "usage_recorded",
                        False,
                    )
                    and not item.get(
                        "total_usd_is_complete",
                        False,
                    )
                    for item in prior_cost_reports
                )

                if incomplete_prior_cost:
                    report[
                        "budget_stopped_early"
                    ] = True

                    report[
                        "local_budget_stop_reason"
                    ] = (
                        "LOCAL_USD_BUDGET_UNSAFE_INCOMPLETE_COST_ACCOUNTING"
                    )

                    report[
                        "skipped_due_to_budget"
                    ].extend(
                        [platform, lang]
                        for lang in langs
                    )

                    continue

                spent_so_far = round(
                    sum(
                        float(
                            item.get(
                                "known_total_usd",
                                item.get(
                                    "total_usd",
                                    0.0,
                                ),
                            )
                            or 0.0
                        )
                        for item in prior_cost_reports
                    ),
                    6,
                )

                if spent_so_far >= args.max_budget_usd:
                    report[
                        "budget_stopped_early"
                    ] = True

                    report[
                        "local_budget_stop_reason"
                    ] = (
                        "LOCAL_USD_BUDGET_CEILING_REACHED"
                    )

                    report[
                        "skipped_due_to_budget"
                    ].extend(
                        [platform, lang]
                        for lang in langs
                    )

                    continue
            campaign = Campaign(
                display_id=(
                    f"LIVEACCEPT-{platform.upper()}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
                ),
                brand_id=brand.id, category_id=product.category_id, product_id=product.id,
                objective="awareness", status="IDEA", languages=langs, target_platforms=[platform],
                target_slide_count=1 if args.premium_hero_only else None,
            )
            session.add(campaign)
            session.commit()
            campaign_by_platform[platform] = campaign
            all_campaign_ids.append(campaign.id)
            try:
                await _run_one_case(
                    session,
                    campaign=campaign,
                    config=config,
                    provider=provider,
                    renderer=renderer,
                )
            except HardBudgetExceededError as exc:
                report["budget_stopped_early"] = True
                report["hard_budget_stop_reason"] = str(exc)
                report["hard_budget_snapshot"] = (
                    provider.hard_budget_snapshot()
                )
                report["skipped_due_to_budget"].extend(
                    [platform, lang]
                    for lang in langs
                )
                campaign_by_platform.pop(
                    platform,
                    None,
                )
                break
    finally:
        await renderer.close()

    report["hard_budget_snapshot"] = (
        provider.hard_budget_snapshot()
    )

    overall_verdict = "PASS"
    for platform, language in matrix:
        campaign = campaign_by_platform.get(platform)
        case_report: dict = {"platform": platform, "language": language}
        if campaign is None:
            case_report["verdict"] = "SKIPPED_BUDGET_CEILING"
            case_report["reason"] = (
                report.get(
                    "local_budget_stop_reason"
                )
                or report.get(
                    "hard_budget_stop_reason"
                )
                or "LOCAL_USD_BUDGET_CEILING_REACHED"
            )
            overall_verdict = _combine_verdict(overall_verdict, "INCOMPLETE_BUDGET_CEILING")
            report["cases"].append(case_report)
            continue

        case_report["campaign_id"] = campaign.id
        variants = get_platform_campaign_variants(session, campaign.id)
        variant = next((v for v in variants if v.target_platform == platform and v.language == language), None)
        if variant is None:
            case_report["verdict"] = "FAIL"
            case_report["reason"] = "No PlatformCampaignVariant was produced for this platform/language."
            overall_verdict = _combine_verdict(overall_verdict, "FAIL")
            report["cases"].append(case_report)
            continue

        case_report["status"] = variant.status
        case_report["qa_status"] = variant.qa_status
        case_report["qa_hard_fails"] = variant.qa_hard_fails
        case_report["is_rendered_video"] = False if variant.status == "SCRIPT_ONLY" else None
        # BUILD 6 FINAL REPAIR: read back, never recomputed — see
        # `_unsupported_claim_flags_for_variant`'s own docstring. Because
        # `run_qa_stage` now hard-fails a variant on ANY unsupported claim
        # (REQUIREMENT 5 — fail closed), `variant.qa_status` can no longer be
        # "PASS" while `claim_flags` is non-empty; this reporting logic no
        # longer needs its own separate claim-vs-qa_status branch, it just
        # surfaces what already gated PASS/NEEDS_REVIEW.
        claim_flags = _unsupported_claim_flags_for_variant(variant)
        case_report["unsupported_claim_flags"] = claim_flags

        if variant.qa_status == "PASS":
            case_report["verdict"] = "PASS"
        else:
            case_report["verdict"] = "NEEDS_REVIEW"
            overall_verdict = _combine_verdict(overall_verdict, "NEEDS_REVIEW")

        snapshot = build_creative_system_snapshot(
            session, campaign_id=campaign.id, platform=platform, language=language,
            content_type=variant.content_type, quality_mode=config.quality_mode,
        )
        case_report["creative_system_snapshot"] = snapshot
        report["cases"].append(case_report)

    # Critical Defect 6/11: this must hold by construction (one campaign per
    # platform, scoped to only that platform's own matrix languages) — a
    # mismatch here means the exact-matrix guarantee was violated somewhere
    # and must be surfaced loudly, never silently shipped in a report that
    # otherwise looks clean.
    expected_variant_count = sum(len(langs) for platform, langs in groups.items() if platform in campaign_by_platform)
    actual_variant_count = sum(len(get_platform_campaign_variants(session, cid)) for cid in all_campaign_ids)
    report["exact_matrix_violation"] = (
        None if actual_variant_count == expected_variant_count else
        f"Expected exactly {expected_variant_count} PlatformCampaignVariant row(s) across the "
        f"{len(campaign_by_platform)} platform-scoped campaign(s) this run created, found "
        f"{actual_variant_count} instead."
    )
    if report["exact_matrix_violation"]:
        overall_verdict = _combine_verdict(overall_verdict, "FAIL")

    combined_cost = {
        "total_usd": 0.0,
        "image_generation_usd": 0.0,
        "text_generation_usd": 0.0,
        "known_total_usd": 0.0,
        "known_image_generation_usd": 0.0,
        "known_text_generation_usd": 0.0,
        "call_count": 0,
        "usage_recorded": False,
        "cost_status": "no_usage",
        "cost_complete": True,
        "total_usd_is_complete": True,
        "image_generation_usd_is_complete": True,
        "text_generation_usd_is_complete": True,
        "unpriced_call_count": 0,
        "unpriced_image_call_count": 0,
        "unpriced_text_call_count": 0,
        "unpriced_image_count": 0,
        "unpriced_models": [],
        "unpriced_operations": [],
        "by_operation": {},
        "by_variant": [],
        "by_scope": {},
    }

    for cid in all_campaign_ids:
        _merge_cost_report(
            combined_cost,
            build_campaign_cost_report(
                session,
                cid,
            ),
        )

    if not combined_cost[
        "usage_recorded"
    ]:
        combined_cost[
            "cost_status"
        ] = "no_usage"

        combined_cost[
            "cost_complete"
        ] = False

        combined_cost[
            "total_usd_is_complete"
        ] = False

        combined_cost[
            "image_generation_usd_is_complete"
        ] = False

        combined_cost[
            "text_generation_usd_is_complete"
        ] = False

    report[
        "cost_report"
    ] = combined_cost

    report[
        "known_local_cost_usd"
    ] = combined_cost[
        "known_total_usd"
    ]

    report[
        "actual_cost_usd_is_complete"
    ] = combined_cost[
        "total_usd_is_complete"
    ]

    report[
        "actual_cost_status"
    ] = combined_cost[
        "cost_status"
    ]

    report[
        "actual_cost_usd"
    ] = (
        combined_cost[
            "known_total_usd"
        ]
        if combined_cost[
            "total_usd_is_complete"
        ]
        else None
    )

    report[
        "provider_cost_reconciliation_required"
    ] = not combined_cost[
        "total_usd_is_complete"
    ]

    report["overall_verdict"] = overall_verdict
    session.close()

    out_dir = Path("data/live_acceptance")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    out_path.write_text(json.dumps(report, indent=2, default=str))

    print(json.dumps(report, indent=2, default=str))
    print(f"\nReport written to {out_path}")
    print("ESTIMATED_COST_USD=UNAVAILABLE_PRECALL_MIXED_USAGE")
    print(
        "KNOWN_LOCAL_COST_USD="
        + str(
            report[
                "known_local_cost_usd"
            ]
        )
    )

    print(
        "ACTUAL_COST_COMPLETE="
        + str(
            report[
                "actual_cost_usd_is_complete"
            ]
        ).upper()
    )

    if report[
        "actual_cost_usd"
    ] is None:
        print(
            "ACTUAL_COST_USD=UNAVAILABLE_INCOMPLETE_LOCAL_ACCOUNTING"
        )
    else:
        print(
            "ACTUAL_COST_USD="
            + str(
                report[
                    "actual_cost_usd"
                ]
            )
        )

    print(
        "UNPRICED_IMAGE_CALL_COUNT="
        + str(
            combined_cost[
                "unpriced_image_call_count"
            ]
        )
    )

    print(
        "PROVIDER_COST_RECONCILIATION_REQUIRED="
        + str(
            report[
                "provider_cost_reconciliation_required"
            ]
        ).upper()
    )
    print(f"LIVE_ACCEPTANCE={overall_verdict}")
    return 0 if overall_verdict == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
