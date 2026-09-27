from __future__ import annotations

from datetime import datetime

from .common import ORMModel


class CompetitorCreate(ORMModel):
    brand_id: str
    name: str
    website: str = ""
    social_handles: dict = {}
    notes: str = ""
    monitoring_enabled: bool = True


class CompetitorOut(ORMModel):
    id: str
    brand_id: str
    name: str
    website: str
    social_handles: dict
    notes: str
    monitoring_enabled: bool


class CompetitorEventCreate(ORMModel):
    competitor_id: str
    brand_id: str
    event_type: str
    detected_at: datetime | None = None
    source: str = "manual"
    details: dict = {}
    severity: str = "medium"


class CompetitorEventOut(ORMModel):
    id: str
    competitor_id: str
    brand_id: str
    event_type: str
    detected_at: datetime | None
    source: str
    details: dict
    severity: str
    status: str
    created_at: datetime


class DefenseRecommendationOut(ORMModel):
    playbook_id: str
    strategy_type_key: str
    strategy_type_name: str
    strategy_family_key: str
    rationale: str
    priority: int
