from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..schemas.settings import SettingsOut, SettingsUpdate
from ..services import settings_store

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("", response_model=SettingsOut)
def get_settings(db: Session = Depends(get_db)):
    effective = settings_store.get_effective_settings(db)
    return SettingsOut(
        source_asset_root=effective["source_asset_root"],
        output_root=effective["output_root"],
        openai_configured=bool(effective["openai_api_key"]),
        openai_research_model=effective["openai_research_model"],
        openai_campaign_model=effective["openai_campaign_model"],
        openai_vision_model=effective["openai_vision_model"],
        openai_image_model=effective["openai_image_model"],
        openai_strategy_model=effective["openai_strategy_model"],
        openai_copy_model=effective["openai_copy_model"],
        openai_platform_adapter_model=effective["openai_platform_adapter_model"],
        openai_creative_director_model=effective["openai_creative_director_model"],
        openai_draft_image_model=effective["openai_draft_image_model"],
        openai_premium_image_model=effective["openai_premium_image_model"],
        openai_creative_qa_model=effective["openai_creative_qa_model"],
        openai_revision_model=effective["openai_revision_model"],
        trend_research_ttl_hours=effective["trend_research_ttl_hours"],
        category_research_ttl_hours=effective["category_research_ttl_hours"],
        novelty_too_similar_threshold=effective["novelty_too_similar_threshold"],
        novelty_acceptable_threshold=effective["novelty_acceptable_threshold"],
        facebook_page_id=effective["facebook_page_id"],
        facebook_configured=bool(effective["facebook_page_access_token"]),
        instagram_business_account_id=effective["instagram_business_account_id"],
        public_base_url=effective["public_base_url"],
        pinterest_board_id=effective["pinterest_board_id"],
        pinterest_configured=bool(effective["pinterest_access_token"]),
    )


@router.patch("", response_model=SettingsOut)
def update_settings(payload: SettingsUpdate, db: Session = Depends(get_db)):
    settings_store.update_settings(db, payload.model_dump(exclude_unset=True))
    return get_settings(db)
