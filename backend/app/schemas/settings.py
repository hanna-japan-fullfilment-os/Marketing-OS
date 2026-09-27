from __future__ import annotations

from .common import ORMModel


class SettingsOut(ORMModel):
    source_asset_root: str
    output_root: str
    openai_configured: bool
    openai_research_model: str
    openai_campaign_model: str
    openai_vision_model: str
    openai_image_model: str
    # Build 2 (Part D) model-role routing — see config.py for what each
    # replaces and its backward-compatible default.
    openai_strategy_model: str
    openai_copy_model: str
    openai_platform_adapter_model: str
    openai_creative_director_model: str
    openai_draft_image_model: str
    openai_premium_image_model: str
    openai_creative_qa_model: str
    openai_revision_model: str
    trend_research_ttl_hours: int
    category_research_ttl_hours: int
    novelty_too_similar_threshold: int
    novelty_acceptable_threshold: int
    facebook_page_id: str
    facebook_configured: bool
    instagram_business_account_id: str
    public_base_url: str


class SettingsUpdate(ORMModel):
    source_asset_root: str | None = None
    output_root: str | None = None
    openai_api_key: str | None = None
    openai_research_model: str | None = None
    openai_campaign_model: str | None = None
    openai_vision_model: str | None = None
    openai_image_model: str | None = None
    openai_strategy_model: str | None = None
    openai_copy_model: str | None = None
    openai_platform_adapter_model: str | None = None
    openai_creative_director_model: str | None = None
    openai_draft_image_model: str | None = None
    openai_premium_image_model: str | None = None
    openai_creative_qa_model: str | None = None
    openai_revision_model: str | None = None
    trend_research_ttl_hours: int | None = None
    category_research_ttl_hours: int | None = None
    novelty_too_similar_threshold: int | None = None
    novelty_acceptable_threshold: int | None = None
    facebook_page_id: str | None = None
    facebook_page_access_token: str | None = None
    instagram_business_account_id: str | None = None
    public_base_url: str | None = None
