"""Idempotent seeding for reference/catalog data (Strategy Library, Defense
playbooks). Safe to call on every startup and from tests — upserts by natural key
(`key` for strategy types/families, a composite for playbooks) so re-running never
duplicates rows, and updates existing rows if the seed content changed.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from ..data.defense_playbooks import DEFAULT_PLAYBOOKS
from ..data.strategy_library import FAMILIES, STRATEGY_TYPES
from ..models import CampaignStrategyFamily, CampaignStrategyType, DefensePlaybook
from .prompt_registry import ensure_prompt_versions_seeded


def seed_strategy_library(db: Session) -> None:
    family_by_key: dict[str, CampaignStrategyFamily] = {
        f.key: f for f in db.query(CampaignStrategyFamily).all()
    }

    for family_data in FAMILIES:
        family = family_by_key.get(family_data["key"])
        if family is None:
            family = CampaignStrategyFamily(
                key=family_data["key"],
                name=family_data["name"],
                description=family_data["description"],
                color=family_data["color"],
                sort_order=family_data["sort_order"],
            )
            db.add(family)
            family_by_key[family_data["key"]] = family
        else:
            family.name = family_data["name"]
            family.description = family_data["description"]
            family.color = family_data["color"]
            family.sort_order = family_data["sort_order"]

    db.flush()

    type_by_key: dict[str, CampaignStrategyType] = {
        t.key: t for t in db.query(CampaignStrategyType).all()
    }

    for type_data in STRATEGY_TYPES:
        strategy_type = type_by_key.get(type_data["key"])
        if strategy_type is None:
            strategy_type = CampaignStrategyType(key=type_data["key"])
            db.add(strategy_type)
            type_by_key[type_data["key"]] = strategy_type

        strategy_type.name = type_data["name"]
        strategy_type.family_id = family_by_key[type_data["family"]].id
        strategy_type.secondary_family_keys = type_data["secondary_families"]
        strategy_type.example = type_data["example"]
        strategy_type.product_scope = type_data["product_scope"]
        strategy_type.objective = type_data["objective"]
        strategy_type.trigger_type = type_data["trigger_type"]
        strategy_type.trigger_description = type_data["trigger_description"]
        strategy_type.audience = type_data["audience"]
        strategy_type.psychology = type_data["psychology"]
        strategy_type.offer_types = type_data["offer_types"]
        strategy_type.channels = type_data["channels"]
        strategy_type.content_types = type_data["content_types"]
        strategy_type.typical_duration = type_data["typical_duration"]
        strategy_type.budget_notes = type_data["budget_notes"]
        strategy_type.success_metrics = type_data["success_metrics"]
        strategy_type.notes = type_data["notes"]
        strategy_type.is_active = True

    db.commit()


def seed_defense_playbooks(db: Session) -> None:
    existing = {
        (p.brand_id, p.event_type, p.recommended_strategy_key): p
        for p in db.query(DefensePlaybook).filter(DefensePlaybook.brand_id.is_(None)).all()
    }
    for pb_data in DEFAULT_PLAYBOOKS:
        natural_key = (None, pb_data["event_type"], pb_data["recommended_strategy_key"])
        playbook = existing.get(natural_key)
        if playbook is None:
            playbook = DefensePlaybook(brand_id=None, event_type=pb_data["event_type"],
                                        recommended_strategy_key=pb_data["recommended_strategy_key"])
            db.add(playbook)
            existing[natural_key] = playbook
        playbook.min_severity = pb_data["min_severity"]
        playbook.condition = pb_data["condition"]
        playbook.rationale = pb_data["rationale"]
        playbook.priority = pb_data["priority"]
        playbook.is_active = True

    db.commit()


def seed_all(db: Session) -> None:
    seed_strategy_library(db)
    seed_defense_playbooks(db)
    ensure_prompt_versions_seeded(db)
