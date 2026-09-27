from __future__ import annotations

from datetime import datetime

from .common import ORMModel, Timestamped


class AssetOut(Timestamped):
    id: str
    brand_id: str
    category_id: str | None
    product_id: str | None
    absolute_path: str
    relative_path: str
    filename: str
    extension: str
    sha256: str
    phash: str
    file_size_bytes: int
    width: int
    height: int
    aspect_ratio: float
    image_role: str
    tags: list
    is_active: bool
    times_used: int
    last_used_at: datetime | None
    visual_description: str
    user_notes: str


class AssetUpdate(ORMModel):
    category_id: str | None = None
    product_id: str | None = None
    image_role: str | None = None
    tags: list[str] | None = None
    is_active: bool | None = None
    user_notes: str | None = None


class ScanRequest(ORMModel):
    brand_id: str


class ScanResult(ORMModel):
    scanned_files: int
    new_assets: int
    updated_assets: int
    unchanged_assets: int
    skipped_non_images: int
    errors: list[str]
