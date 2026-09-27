"""The Defense engine: given a logged CompetitorEvent, recommend a specific
Strategy Library response by matching it against DefensePlaybook rules.

This is deliberately a plain, inspectable rule engine today — not an AI call — so
the recommendation is always explainable ("why did the system suggest this?") and
never dependent on an API key being configured. An AI-assisted version (weighing
softer signals an if/else tree can't capture) can be added later behind the same
`recommend_response()` signature without changing callers; see
docs/campaign-pipeline.md.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from ..models import CampaignStrategyType, CompetitorEvent, DefensePlaybook

SEVERITY_ORDER = {"low": 0, "medium": 1, "high": 2}


def _condition_met(condition: dict, details: dict) -> bool:
    for key, threshold in condition.items():
        if key.endswith("_gte"):
            field = key[: -len("_gte")]
            if not (details.get(field, 0) >= threshold):
                return False
        elif key.endswith("_lte"):
            field = key[: -len("_lte")]
            if not (details.get(field, 0) <= threshold):
                return False
        elif key.endswith("_eq"):
            field = key[: -len("_eq")]
            if details.get(field) != threshold:
                return False
        # Unknown condition shapes are ignored rather than raising, so a playbook
        # with a typo doesn't crash recommendation — it just won't match on that key.
    return True


@dataclass
class DefenseRecommendation:
    playbook_id: str
    strategy_type_key: str
    strategy_type_name: str
    strategy_family_key: str
    rationale: str
    priority: int


def recommend_response(db: Session, event: CompetitorEvent, *, limit: int = 3) -> list[DefenseRecommendation]:
    event_severity_rank = SEVERITY_ORDER.get(event.severity, 0)

    playbooks = (
        db.query(DefensePlaybook)
        .filter(
            DefensePlaybook.event_type == event.event_type,
            DefensePlaybook.is_active.is_(True),
            (DefensePlaybook.brand_id == event.brand_id) | (DefensePlaybook.brand_id.is_(None)),
        )
        .order_by(DefensePlaybook.priority.asc())
        .all()
    )

    matches: list[DefensePlaybook] = []
    for playbook in playbooks:
        if SEVERITY_ORDER.get(playbook.min_severity, 0) > event_severity_rank:
            continue
        if not _condition_met(playbook.condition or {}, event.details or {}):
            continue
        matches.append(playbook)

    # Brand-specific playbooks should win over global ones at the same priority.
    matches.sort(key=lambda p: (p.priority, 0 if p.brand_id else 1))

    strategy_types = {
        st.key: st for st in db.query(CampaignStrategyType).all()
    }

    recommendations: list[DefenseRecommendation] = []
    for playbook in matches[:limit]:
        strategy_type = strategy_types.get(playbook.recommended_strategy_key)
        if strategy_type is None:
            continue
        recommendations.append(
            DefenseRecommendation(
                playbook_id=playbook.id,
                strategy_type_key=strategy_type.key,
                strategy_type_name=strategy_type.name,
                strategy_family_key=strategy_type.family.key,
                rationale=playbook.rationale,
                priority=playbook.priority,
            )
        )
    return recommendations
