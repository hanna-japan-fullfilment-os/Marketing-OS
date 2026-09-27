"""Build 4 — selective, bounded feedback retrieval (carry-forward requirement 5).

A deliberate LEAF module: depends only on `models`/`data`, never on
`services/orchestrator.py` or `services/qa_engine.py`. This is what lets
`orchestrator.py` itself import `select_feedback_examples`/
`format_feedback_for_prompt` for prompt-grounding (`run_copy_stage`'s
`CampaignCopy` call, `_generate_creative_direction`'s prompt) without an
import cycle — `services/review_engine.py` (which DOES import one-
directionally FROM `orchestrator.py` and `qa_engine.py`, to reuse their
revision primitives) re-exports both names for its own callers.

Design, matching the spec's own worked example ("repeated Instagram PT-BR
feedback 'Too much text' should primarily influence similar future variants;
must NOT blindly affect Pinterest English creatives unless relevant"):

- **Filter, not just rank**: platform-specific feedback (`ReviewFeedback.
  platform` set) for a DIFFERENT platform than the one being generated for is
  excluded entirely, not merely ranked lower — same for language. Campaign-
  level feedback (`platform`/`language` both `""`, i.e. `level="CAMPAIGN"`)
  always matches, since it was never scoped to one execution in the first
  place.
- **Rank** what survives the filter by how many of (platform, language,
  category, product, objective, content_type) it shares with the current
  generation context, most-relevant first, ties broken by recency.
- **Deduplicate** by `reason_code` within each of positive/negative (the
  same reason repeated ten times teaches nothing a single instance doesn't),
  keeping the highest-ranked instance of each.
- **Bound**: capped at `limit` positive and `limit` negative examples —
  `AutopilotConfig.feedback_examples_limit` is what callers pass through.

Positive examples deliberately never carry the approved variant's actual
headline/body/CTA text into the prompt (carry-forward requirement 7: "must
not cause cloning") — only its reason/characterization and context. Negative
examples carry the flagged reason (structured code and/or free text) but,
same discipline, never the rejected copy's literal wording either.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from ..data.feedback_reasons import FEEDBACK_REASON_LABELS
from ..models import AuditEvent, ReviewFeedback

_POSITIVE_ACTIONS = ("APPROVE",)
_NEGATIVE_ACTIONS = ("REJECT", "REQUEST_REVISION")

# How many of this brand's most recent feedback rows are even considered
# before filtering/ranking/dedup — keeps a single query bounded regardless of
# how much feedback history a long-lived brand accumulates, independent of
# the caller's own `limit` (which governs the OUTPUT size, not this scan).
_MAX_CANDIDATES_SCANNED = 200


@dataclass
class FeedbackSelection:
    positive: list[ReviewFeedback] = field(default_factory=list)
    negative: list[ReviewFeedback] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not self.positive and not self.negative


def _matches_context(fb: ReviewFeedback, *, platform: str, language: str) -> bool:
    """A hard filter, not a ranking signal — see module docstring. Feedback
    scoped to a specific platform/language that does NOT match the current
    generation context is excluded outright; feedback with no platform/
    language of its own (campaign-level) always passes through.
    """
    if platform and fb.platform and fb.platform != platform:
        return False
    if language and fb.language and fb.language != language:
        return False
    return True


def _relevance_score(
    fb: ReviewFeedback, *, platform: str, language: str, category_id: str | None, product_id: str | None,
    objective: str, content_type: str,
) -> int:
    score = 0
    if platform and fb.platform == platform:
        score += 8
    if language and fb.language == language:
        score += 8
    if category_id and fb.category_id == category_id:
        score += 4
    if product_id and fb.product_id == product_id:
        score += 4
    if objective and fb.objective == objective:
        score += 2
    if content_type and fb.content_type == content_type:
        score += 2
    return score


def _rank_and_dedupe(rows: list[ReviewFeedback], *, limit: int, **score_kwargs) -> list[ReviewFeedback]:
    scored = sorted(
        rows, key=lambda fb: (_relevance_score(fb, **score_kwargs), fb.created_at), reverse=True,
    )
    deduped: list[ReviewFeedback] = []
    seen_reasons: set[str] = set()
    for fb in scored:
        key = fb.reason_code or f"__freeform__:{fb.id}"  # freeform-only feedback never dedupes against another
        if key in seen_reasons:
            continue
        seen_reasons.add(key)
        deduped.append(fb)
        if len(deduped) >= max(0, limit):
            break
    return deduped


def select_feedback_examples(
    db: Session, *, brand_id: str | None, platform: str = "", language: str = "", category_id: str | None = None,
    product_id: str | None = None, objective: str = "", content_type: str = "", limit: int = 5,
) -> FeedbackSelection:
    """Carry-forward requirement 5 + Build 4's own "FEEDBACK RETRIEVAL"
    section. `brand_id=None` returns an empty selection (never a cross-brand
    query) rather than raising — a campaign with no brand context yet simply
    gets no grounding, same as an empty feedback table.
    """
    if not brand_id:
        return FeedbackSelection()

    candidates = (
        db.query(ReviewFeedback)
        .filter(ReviewFeedback.brand_id == brand_id)
        .order_by(ReviewFeedback.created_at.desc())
        .limit(_MAX_CANDIDATES_SCANNED)
        .all()
    )
    contextual = [fb for fb in candidates if _matches_context(fb, platform=platform, language=language)]

    score_kwargs = dict(
        platform=platform, language=language, category_id=category_id, product_id=product_id,
        objective=objective, content_type=content_type,
    )
    positive_rows = [fb for fb in contextual if fb.action in _POSITIVE_ACTIONS]
    negative_rows = [fb for fb in contextual if fb.action in _NEGATIVE_ACTIONS]

    return FeedbackSelection(
        positive=_rank_and_dedupe(positive_rows, limit=limit, **score_kwargs),
        negative=_rank_and_dedupe(negative_rows, limit=limit, **score_kwargs),
    )


def _describe(fb: ReviewFeedback) -> str:
    label = FEEDBACK_REASON_LABELS.get(fb.reason_code, "") if fb.reason_code else ""
    if not label:
        label = fb.reason_text.strip() if fb.reason_text else "unspecified reason"
    context = f"{fb.platform or 'any platform'}/{fb.language or 'any language'}"
    return f"{context}: {label}"


def format_feedback_for_prompt(selection: FeedbackSelection) -> str:
    """Plain additive text, appended to a prompt's `user=` string the same
    way `_brand_creative_instructions_block`/`verified_facts_note`/etc.
    already are (see `orchestrator.py`) — "" (never a placeholder sentence)
    when there's nothing to say, so a brand with no feedback history yet gets
    a byte-for-byte identical prompt to pre-Build-4 behavior.

    Deliberately characterization-only (reason + platform/language context),
    never the reviewed variant's literal headline/body/CTA text — see the
    module docstring's cloning-prevention note.
    """
    if selection.is_empty():
        return ""
    lines: list[str] = []
    if selection.positive:
        lines.append(
            "Past campaigns the owner APPROVED in similar contexts (use only to guide tone, density, "
            "product scale, visual direction, CTA style, and composition tendencies — never copy their "
            "exact headline, wording, or scene): " + "; ".join(_describe(fb) for fb in selection.positive) + "."
        )
    if selection.negative:
        lines.append(
            "The owner previously REJECTED or asked to revise campaigns for these specific reasons — avoid "
            "repeating them: " + "; ".join(_describe(fb) for fb in selection.negative) + "."
        )
    return "\n".join(lines)


def snapshot_prompt_versions(db: Session, *, campaign_id: str, platform: str = "", language: str = "") -> dict:
    """Best-effort {"campaign_copy": "1.0.0", "creative_direction": "1.0.0",
    ...} read back from the EXISTING `AuditEvent(entity_type=
    "campaign_prompt_usage")` rows `record_prompt_usage` (Build 1/3) already
    writes — see `models/review.py::ReviewFeedback.reviewed_prompt_versions`.
    Never fabricated: an empty dict when nothing matches, not a guessed
    version. Most-recent-wins per purpose; a row is considered a match when
    its own platform/language is blank (shared across every combination,
    e.g. `master_campaign_concept`) or equals the one asked for.
    """
    rows = (
        db.query(AuditEvent)
        .filter(AuditEvent.entity_type == "campaign_prompt_usage", AuditEvent.entity_id == campaign_id)
        .order_by(AuditEvent.created_at.desc())
        .all()
    )
    versions: dict[str, str] = {}
    for row in rows:
        detail = row.detail or {}
        purpose = detail.get("purpose")
        if not purpose or purpose in versions:
            continue
        row_platform = detail.get("platform") or ""
        row_language = detail.get("language") or ""
        if platform and row_platform and row_platform != platform:
            continue
        if language and row_language and row_language != language:
            continue
        versions[purpose] = detail.get("version", "unknown")
    return versions
