"""
Central configuration. NO model name, file path, or threshold should ever be
hardcoded anywhere else in the application — everything reads from here.

Values load from environment (.env) first, then can be overridden at runtime by
rows in the `settings` DB table (see services/settings_store.py) so the Settings
UI can change them without a restart. This module only defines the env-backed
defaults; the runtime-overridable read path lives in services/settings_store.py.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- OpenAI ---
    openai_api_key: str = ""
    openai_research_model: str = "gpt-5.1"
    # Legacy, still read directly by a couple of call sites for backward
    # compatibility (e.g. `AutopilotConfig.campaign_model`'s own default) — the
    # Build 2 (Part D) model-role fields below are what new/updated call sites
    # actually read now. Kept at the same literal default so nothing changes
    # for a deployment that never touches Settings.
    openai_campaign_model: str = "gpt-5.1"
    openai_vision_model: str = "gpt-5.1"
    openai_image_model: str = "gpt-image-2.5-sunburst-2026-09-08"

    # --- Model role routing (Build 2, Part D) ---
    # No business-logic module should ever hardcode a provider model name —
    # every AI call in `services/orchestrator.py` reads one of these "roles"
    # off `AutopilotConfig` instead (see `api/campaigns.py::_build_autopilot_
    # config`), so a deployment can point any one role at a different model
    # without touching code. Every role defaults to the same literal value the
    # pre-Build-2 call site it replaces already used, so a deployment that
    # never opens Settings sees byte-for-byte the same models as before.
    openai_strategy_model: str = "gpt-5.1"  # strategy candidates (was openai_campaign_model)
    openai_copy_model: str = "gpt-5.1"  # CampaignCopy + CarouselPlan (was openai_campaign_model)
    openai_platform_adapter_model: str = "gpt-5.1"  # Part F: master concept -> per-platform adaptation
    openai_creative_director_model: str = "gpt-5.1"  # Part G: CreativeBrief + CreativeDirection
    openai_draft_image_model: str = "gpt-image-2.5-flare-2026-09-08"  # GPT Image 2.5 fast draft role
    openai_premium_image_model: str = "gpt-image-2.5-sunburst-2026-09-08"  # GPT Image 2.5 premium role
    openai_creative_qa_model: str = "gpt-5.1"  # product-fidelity / visual QA checks (was openai_vision_model)
    openai_revision_model: str = "gpt-image-2.5-sunburst-2026-09-08"  # fidelity-gate corrective image role
    # GPT Image 2.5 live safety. These remain env/config backed rather
    # than DB-overridable UI settings.
    openai_project_id: str = ""
    openai_project_hard_limit_attested: bool = False
    openai_max_image_calls: int | None = None

    # --- Repositories ---
    source_asset_root: str = ""
    output_root: str = ""

    # --- Meta (Facebook Page / Instagram) auto-publish, sections 47/48 ---
    facebook_page_id: str = ""
    facebook_page_access_token: str = ""
    instagram_business_account_id: str = ""
    # Not overridable from Settings (same tier as backend_host/cors_origins below) —
    # this rarely changes and isn't a secret, so it stays a plain env/config value.
    meta_graph_api_version: str = "v21.0"
    # Required only for Instagram auto-publish: a URL Meta's own servers can reach
    # (this app's generated images are served from a local backend, which Meta
    # cannot fetch on its own — see services/publishing/meta_provider.py). Typically
    # a tunnel like ngrok pointed at this backend. Not needed for Facebook Page
    # posts, which upload the file directly.
    public_base_url: str = ""

    # --- Database ---
    database_url: str = "sqlite:///./data/app.db"

    # --- Research caching (hours) ---
    trend_research_ttl_hours: int = 24
    category_research_ttl_hours: int = 168

    # --- Novelty thresholds ---
    novelty_too_similar_threshold: int = 75
    novelty_acceptable_threshold: int = 45

    # --- Server ---
    backend_host: str = "127.0.0.1"
    backend_port: int = 8000
    cors_origins: str = "http://localhost:5173"

    @property
    def source_asset_root_path(self) -> Path | None:
        return Path(self.source_asset_root) if self.source_asset_root else None

    @property
    def output_root_path(self) -> Path | None:
        return Path(self.output_root) if self.output_root else None

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
