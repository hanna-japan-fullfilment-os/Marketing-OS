"""Runtime settings: DB `settings` table overrides `.env` values so the Settings UI
can change repositories/model names/thresholds without restarting the process.
Secrets (the API key) are stored but never echoed back to the frontend.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import SettingRow

OVERRIDABLE_KEYS = {
    "source_asset_root", "output_root", "openai_api_key",
    "openai_research_model", "openai_campaign_model", "openai_vision_model", "openai_image_model",
    # Build 2 (Part D): configurable model roles — see config.py's own comment
    # on each field for what it replaces and its backward-compatible default.
    "openai_strategy_model", "openai_copy_model", "openai_platform_adapter_model",
    "openai_creative_director_model", "openai_draft_image_model", "openai_premium_image_model",
    "openai_creative_qa_model", "openai_revision_model",
    "trend_research_ttl_hours", "category_research_ttl_hours",
    "novelty_too_similar_threshold", "novelty_acceptable_threshold",
    "facebook_page_id", "facebook_page_access_token", "instagram_business_account_id",
    "public_base_url",
}


def get_effective_settings(db: Session) -> dict:
    base = get_settings()
    effective = {
        "source_asset_root": base.source_asset_root,
        "output_root": base.output_root,
        "openai_api_key": base.openai_api_key,
        "openai_research_model": base.openai_research_model,
        "openai_campaign_model": base.openai_campaign_model,
        "openai_vision_model": base.openai_vision_model,
        "openai_image_model": base.openai_image_model,
        "openai_strategy_model": base.openai_strategy_model,
        "openai_copy_model": base.openai_copy_model,
        "openai_platform_adapter_model": base.openai_platform_adapter_model,
        "openai_creative_director_model": base.openai_creative_director_model,
        "openai_draft_image_model": base.openai_draft_image_model,
        "openai_premium_image_model": base.openai_premium_image_model,
        "openai_creative_qa_model": base.openai_creative_qa_model,
        "openai_revision_model": base.openai_revision_model,
        # Provider-safety controls are intentionally env/config only;
        # do not add them to OVERRIDABLE_KEYS.
        "openai_project_id": base.openai_project_id,
        "openai_project_hard_limit_attested": base.openai_project_hard_limit_attested,
        "openai_max_image_calls": base.openai_max_image_calls,
        "trend_research_ttl_hours": base.trend_research_ttl_hours,
        "category_research_ttl_hours": base.category_research_ttl_hours,
        "novelty_too_similar_threshold": base.novelty_too_similar_threshold,
        "novelty_acceptable_threshold": base.novelty_acceptable_threshold,
        "facebook_page_id": base.facebook_page_id,
        "facebook_page_access_token": base.facebook_page_access_token,
        "instagram_business_account_id": base.instagram_business_account_id,
        "public_base_url": base.public_base_url,
    }
    rows = db.query(SettingRow).filter(SettingRow.key.in_(OVERRIDABLE_KEYS)).all()
    for row in rows:
        effective[row.key] = row.value.get("v") if isinstance(row.value, dict) else row.value
    return effective


def update_settings(db: Session, updates: dict) -> dict:
    for key, value in updates.items():
        if key not in OVERRIDABLE_KEYS or value is None:
            continue
        row = db.get(SettingRow, key)
        if row is None:
            row = SettingRow(key=key, value={"v": value})
            db.add(row)
        else:
            row.value = {"v": value}
    db.commit()
    return get_effective_settings(db)
