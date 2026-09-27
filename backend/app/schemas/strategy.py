from __future__ import annotations

from .common import ORMModel


class StrategyFamilyOut(ORMModel):
    id: str
    key: str
    name: str
    description: str
    color: str
    sort_order: int


class StrategyTypeOut(ORMModel):
    id: str
    key: str
    name: str
    family_id: str
    secondary_family_keys: list[str]
    example: str
    product_scope: str  # round 20: "single" | "multi" | "either" — see data/strategy_library.py
    objective: str
    trigger_type: str
    trigger_description: str
    audience: str
    psychology: list[str]
    offer_types: list[str]
    channels: list[str]
    content_types: list[str]
    typical_duration: str
    budget_notes: str
    success_metrics: list[str]
    notes: str
    is_active: bool


class StrategyFamilyWithTypes(StrategyFamilyOut):
    types: list[StrategyTypeOut] = []
