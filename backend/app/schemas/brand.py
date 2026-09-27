from __future__ import annotations

from .common import ORMModel, Timestamped


class BrandCreate(ORMModel):
    name: str
    slug: str
    voice: str = ""
    website: str = ""
    target_countries: list[str] = []
    target_audiences: list[str] = []


class BrandUpdate(ORMModel):
    name: str | None = None
    voice: str | None = None
    colors: dict | None = None
    typography: dict | None = None
    visual_style: dict | None = None
    forbidden_styles: list[str] | None = None
    preferred_ctas: list[str] | None = None
    disallowed_terms: list[str] | None = None
    disclaimers: list[str] | None = None
    target_audiences: list[str] | None = None
    target_countries: list[str] | None = None
    social_handles: dict | None = None
    website: str | None = None
    campaign_rules: dict | None = None
    creative_instructions: str | None = None
    is_active: bool | None = None


class BrandOut(Timestamped):
    id: str
    name: str
    slug: str
    is_active: bool
    voice: str
    colors: dict
    typography: dict
    visual_style: dict
    forbidden_styles: list
    preferred_ctas: list
    disallowed_terms: list
    disclaimers: list
    target_audiences: list
    target_countries: list
    social_handles: dict
    website: str
    campaign_rules: dict
    creative_instructions: str


class BrandAssetOut(Timestamped):
    id: str
    brand_id: str
    kind: str
    category_id: str | None = None
    label: str


class CategoryCreate(ORMModel):
    brand_id: str
    name: str
    slug: str
    parent_category_id: str | None = None


class CategoryOut(Timestamped):
    id: str
    brand_id: str
    name: str
    slug: str
    parent_category_id: str | None


class ProductCreate(ORMModel):
    brand_id: str
    category_id: str | None = None
    name: str
    slug: str
    notes: str = ""


class ProductOut(Timestamped):
    id: str
    brand_id: str
    category_id: str | None
    name: str
    slug: str
    notes: str
