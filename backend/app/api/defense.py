from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Competitor, CompetitorEvent
from ..schemas.defense import (
    CompetitorCreate, CompetitorEventCreate, CompetitorEventOut, CompetitorOut, DefenseRecommendationOut,
)
from ..services.defense import recommend_response

router = APIRouter(prefix="/api", tags=["defense"])


@router.get("/competitors", response_model=list[CompetitorOut])
def list_competitors(brand_id: str, db: Session = Depends(get_db)):
    return db.query(Competitor).filter(Competitor.brand_id == brand_id).order_by(Competitor.name).all()


@router.post("/competitors", response_model=CompetitorOut, status_code=201)
def create_competitor(payload: CompetitorCreate, db: Session = Depends(get_db)):
    competitor = Competitor(**payload.model_dump())
    db.add(competitor)
    db.commit()
    db.refresh(competitor)
    return competitor


@router.get("/competitors/{competitor_id}/events", response_model=list[CompetitorEventOut])
def list_competitor_events(competitor_id: str, db: Session = Depends(get_db)):
    return (
        db.query(CompetitorEvent)
        .filter(CompetitorEvent.competitor_id == competitor_id)
        .order_by(CompetitorEvent.created_at.desc())
        .all()
    )


@router.get("/competitor-events", response_model=list[CompetitorEventOut])
def list_all_events(brand_id: str, status: str | None = None, db: Session = Depends(get_db)):
    q = db.query(CompetitorEvent).filter(CompetitorEvent.brand_id == brand_id)
    if status:
        q = q.filter(CompetitorEvent.status == status)
    return q.order_by(CompetitorEvent.created_at.desc()).all()


@router.post("/competitor-events", response_model=CompetitorEventOut, status_code=201)
def create_competitor_event(payload: CompetitorEventCreate, db: Session = Depends(get_db)):
    competitor = db.get(Competitor, payload.competitor_id)
    if competitor is None:
        raise HTTPException(404, "Competitor not found.")
    event = CompetitorEvent(**payload.model_dump())
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


@router.patch("/competitor-events/{event_id}/status", response_model=CompetitorEventOut)
def update_event_status(event_id: str, status: str, db: Session = Depends(get_db)):
    event = db.get(CompetitorEvent, event_id)
    if event is None:
        raise HTTPException(404, "Event not found.")
    if status not in ("NEW", "REVIEWED", "RESPONDED", "IGNORED"):
        raise HTTPException(400, "Invalid status.")
    event.status = status
    db.commit()
    db.refresh(event)
    return event


@router.get("/competitor-events/{event_id}/recommendation", response_model=list[DefenseRecommendationOut])
def get_recommendation(event_id: str, db: Session = Depends(get_db)):
    event = db.get(CompetitorEvent, event_id)
    if event is None:
        raise HTTPException(404, "Event not found.")
    recommendations = recommend_response(db, event)
    return [
        DefenseRecommendationOut(
            playbook_id=r.playbook_id, strategy_type_key=r.strategy_type_key,
            strategy_type_name=r.strategy_type_name, strategy_family_key=r.strategy_family_key,
            rationale=r.rationale, priority=r.priority,
        )
        for r in recommendations
    ]
