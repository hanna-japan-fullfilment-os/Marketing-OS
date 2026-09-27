from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import CampaignStrategyFamily, CampaignStrategyType
from ..schemas.strategy import StrategyFamilyWithTypes, StrategyTypeOut

router = APIRouter(prefix="/api/strategy-library", tags=["strategy-library"])


@router.get("", response_model=list[StrategyFamilyWithTypes])
def list_strategy_library(db: Session = Depends(get_db)):
    families = db.query(CampaignStrategyFamily).order_by(CampaignStrategyFamily.sort_order).all()
    result = []
    for family in families:
        types = (
            db.query(CampaignStrategyType)
            .filter(CampaignStrategyType.family_id == family.id, CampaignStrategyType.is_active.is_(True))
            .order_by(CampaignStrategyType.name)
            .all()
        )
        result.append(
            StrategyFamilyWithTypes(
                id=family.id, key=family.key, name=family.name, description=family.description,
                color=family.color, sort_order=family.sort_order, types=types,
            )
        )
    return result


@router.get("/types/{key}", response_model=StrategyTypeOut)
def get_strategy_type(key: str, db: Session = Depends(get_db)):
    strategy_type = db.query(CampaignStrategyType).filter(CampaignStrategyType.key == key).one_or_none()
    if strategy_type is None:
        raise HTTPException(404, "Strategy type not found.")
    return strategy_type
