"""Build 5 — GOLDEN BENCHMARK + PROMPT REGISTRY + MULTI-PLATFORM REGRESSION.

Two new tables, deliberately separate from everything Build 1-4 already
persists rather than reusing/overloading it:

- `BenchmarkCase` (Part B) — a fixed, EXPLICITLY curated golden test case:
  identity (brand/product/platform/content_type/language/objective/audience),
  inputs (source assets, a frozen Verified Product Facts snapshot), and
  expectations (expected truths, prohibited claims, expected creative
  characteristics). "Explicit membership" (carry-forward requirement 7 /
  Part G) is structural here: nothing in this codebase ever inserts a row
  into this table automatically from a plain APPROVE/REJECT action — only
  `services/benchmark_engine.py::curate_benchmark_case`, called on purpose,
  ever does. A case MAY be derived from a real `ReviewFeedback` row
  (`source_feedback_id`), in which case `owner_rating`/`baseline_output_
  snapshot` are copied from that feedback's own immutable `reviewed_*`
  snapshot at curation time — this table never joins back to `ReviewFeedback`
  live, and never mutates it (carry-forward requirement 3).

- `BenchmarkRun` (Part C/F) — one execution of the pipeline against a case:
  freezes the exact prompt-version-per-purpose snapshot and model-role
  configuration used, which test mode ran it (OFFLINE/MOCK/LOW_COST_SMOKE/
  LIVE_FULL), the resulting `qa_status` AND `human_review_status` as TWO
  separate columns (carry-forward requirement 4 — never collapsed into one
  ground truth), the platform-weighted score (`data/benchmark_scoring.py`)
  and the raw scorecard it was computed from, and a cost breakdown. Runs are
  never mutated after creation except to flag one as the case's current
  baseline (`is_baseline`) — comparing two runs (`compare_runs`) always reads
  both by id, never recomputes a past run's own frozen fields.

Platform/language identity is part of both tables' own row shape, never
inferred — Part H: "Instagram/pt-BR and Instagram/en are separate benchmark
executions even when they share the same MasterCampaignConcept."
"""
from __future__ import annotations

from sqlalchemy import Boolean, Float, ForeignKey, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db import Base
from ._mixins import TimestampMixin, UUIDPKMixin

BENCHMARK_CASE_STATUSES = ("CANDIDATE", "ACTIVE", "RETIRED")
BENCHMARK_TEST_MODES = ("OFFLINE", "MOCK", "LOW_COST_SMOKE", "LIVE_FULL")


class BenchmarkCase(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "benchmark_cases"

    name: Mapped[str] = mapped_column(String(200), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    # "CANDIDATE" (curated but not yet trusted as a regression gate) |
    # "ACTIVE" (counts toward regression reports) | "RETIRED" (kept for
    # history, excluded from new regression runs) — explicit curation,
    # never auto-promoted.
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE", index=True)

    # --- Identity (Part B/H) — brand/product/platform/content type/language/
    # objective/audience. Instagram/pt-BR and Instagram/en are two distinct
    # rows even for "the same" creative idea, per this module's own docstring.
    brand_id: Mapped[str] = mapped_column(ForeignKey("brands.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[str | None] = mapped_column(ForeignKey("products.id", ondelete="SET NULL"), nullable=True)
    category_id: Mapped[str | None] = mapped_column(ForeignKey("categories.id", ondelete="SET NULL"), nullable=True)
    platform: Mapped[str] = mapped_column(String(30), index=True)
    content_type: Mapped[str] = mapped_column(String(50), default="")
    language: Mapped[str] = mapped_column(String(20), index=True)
    objective: Mapped[str] = mapped_column(String(30), default="")
    audience: Mapped[str] = mapped_column(Text, default="")

    # --- Inputs ---------------------------------------------------------
    source_asset_paths: Mapped[list] = mapped_column(JSON, default=list)
    # A frozen copy of `VerifiedProductFact` at curation time — deliberately
    # NOT a live FK. A benchmark case must stay reproducible even if the
    # owner edits the product's real verified facts later (carry-forward
    # requirement 3's own reasoning, applied to product facts too).
    verified_product_facts_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)

    # --- Expectations (Part B) -------------------------------------------
    expected_truths: Mapped[list] = mapped_column(JSON, default=list)
    prohibited_claims: Mapped[list] = mapped_column(JSON, default=list)
    expected_creative_characteristics: Mapped[list] = mapped_column(JSON, default=list)

    # --- Baseline + owner ground truth, frozen at curation time -----------
    baseline_output_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    # "APPROVED" | "REJECTED" | "" (no linked feedback / not yet reviewed) —
    # copied once from `ReviewFeedback.action` at curation time, never a live
    # join back to that row.
    owner_rating: Mapped[str] = mapped_column(String(20), default="")
    # Explicit lineage (carry-forward requirement 3) when this case was
    # curated from real owner feedback — `SET NULL` (never cascade-delete the
    # case) if that feedback row is later removed, since the case's own
    # snapshot already carries everything it needs independently.
    source_feedback_id: Mapped[str | None] = mapped_column(
        ForeignKey("review_feedback.id", ondelete="SET NULL"), nullable=True
    )

    runs = relationship("BenchmarkRun", back_populates="case", cascade="all, delete-orphan")


class BenchmarkRun(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "benchmark_runs"

    benchmark_case_id: Mapped[str] = mapped_column(
        ForeignKey("benchmark_cases.id", ondelete="CASCADE"), index=True
    )
    # OFFLINE (no AI provider — deterministic fallback throughout, verified
    # to make no paid API call) | MOCK (a caller-supplied fake provider, for
    # deterministic tests) | LOW_COST_SMOKE (a real provider, cost-limited
    # config — no AI background/recreation, one slide, no retries) |
    # LIVE_FULL (the real, full-cost pipeline).
    mode: Mapped[str] = mapped_column(String(20))
    # Copied from the case at run time — a run is always scoped to ONE
    # platform/language execution (Part H), never averaged across several.
    platform: Mapped[str] = mapped_column(String(30), index=True)
    language: Mapped[str] = mapped_column(String(20), index=True)

    # The throwaway campaign/variant this run actually produced, kept for
    # traceability/debugging — never read live by `compare_runs` (every field
    # that matters is frozen onto this row itself).
    campaign_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    variant_id: Mapped[str | None] = mapped_column(
        ForeignKey("platform_campaign_variants.id", ondelete="SET NULL"), nullable=True
    )

    # --- Version traceability (Part F) — frozen at run time so a later
    # prompt/model change never silently reinterprets an old run. -----------
    prompt_versions_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    model_role_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    # Build 5 repair (Part 2) — the COMPLETE creative-system identity for this
    # run in ONE field: a nested copy of the per-purpose prompt versions
    # (including any revision purpose that actually fired — see
    # `services/benchmark_engine.py::build_creative_system_snapshot`) plus
    # version identities `prompt_versions_snapshot` alone doesn't cover —
    # the Verified Product Facts resolver, the renderer, and the template/
    # layout system — and this run's own platform/language/content_type/
    # quality_mode. The goal (repair spec's own words): a future engineer can
    # answer "what exact generation system produced run X?" from this ONE
    # frozen field, never from today's live, possibly-since-changed
    # configuration. Deliberately does not duplicate `model_role_snapshot`
    # (its own column already answers "which model per role") to avoid
    # storing the same fact twice.
    creative_system_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)

    # --- Ground truth — TWO separate columns, never collapsed (carry-forward
    # requirement 4). `qa_status` is the automated critic's verdict at run
    # time; `human_review_status` is the OWNER's verdict IF this run's own
    # variant/case has since been reviewed — "" when unreviewed, never
    # inferred from `qa_status`. ------------------------------------------
    qa_status: Mapped[str] = mapped_column(String(20), default="")
    human_review_status: Mapped[str] = mapped_column(String(20), default="")
    qa_scores: Mapped[dict] = mapped_column(JSON, default=dict)
    hard_fails: Mapped[list] = mapped_column(JSON, default=list)

    # --- Platform-weighted scoring (Part D) — documented, not opaque; see
    # `data/benchmark_scoring.py` for the actual weight tables. -------------
    weighted_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    weights_used: Mapped[dict] = mapped_column(JSON, default=dict)

    # --- Cost (Part 10) — "where usage information is available"; reads
    # from `AIUsage` rows attributed to `campaign_id`. Honestly empty/zero
    # when no usage rows exist yet (never a fabricated estimate) — see
    # `services/benchmark_engine.py::_cost_breakdown_for_campaign`. ---------
    cost_breakdown: Mapped[dict] = mapped_column(JSON, default=dict)

    is_baseline: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str] = mapped_column(Text, default="")

    case = relationship("BenchmarkCase", back_populates="runs")
