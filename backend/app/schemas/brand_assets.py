"""Build 2, Part C: the structured result of validating a brand's real,
on-file creative assets before a campaign uses them. Deterministic — no AI
call, no invented content; see `services/brand_assets_validator.py`.
"""
from __future__ import annotations

from pydantic import BaseModel


class BrandAssetValidationResult(BaseModel):
    brand_id: str
    logo_present: bool = False
    logo_path: str = ""
    fonts_resolved: bool = False
    primary_font: str = ""
    secondary_font: str = ""
    palette_present: bool = False
    palette_colors: list[str] = []
    product_assets_present: bool = False
    products_with_photos: int = 0
    products_without_photos: int = 0
    approved_asset_kinds: list[str] = []  # BrandAsset kinds actually on file (logo, visual_reference, inspiration)
    issues: list[str] = []
    valid: bool = False
