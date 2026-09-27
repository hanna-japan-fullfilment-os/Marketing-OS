from __future__ import annotations

import io
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Asset
from ..schemas.asset import AssetOut, AssetUpdate

router = APIRouter(prefix="/api", tags=["assets"])


@router.get("/assets", response_model=list[AssetOut])
def list_assets(
    brand_id: str,
    category_id: str | None = None,
    product_id: str | None = None,
    unused_only: bool = False,
    image_role: str | None = None,
    active_only: bool = True,
    search: str | None = None,
    limit: int = 200,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    stmt = select(Asset).where(Asset.brand_id == brand_id)
    if category_id:
        stmt = stmt.where(Asset.category_id == category_id)
    if product_id:
        stmt = stmt.where(Asset.product_id == product_id)
    if unused_only:
        stmt = stmt.where(Asset.times_used == 0)
    if image_role:
        stmt = stmt.where(Asset.image_role == image_role)
    if active_only:
        stmt = stmt.where(Asset.is_active.is_(True))
    if search:
        like = f"%{search}%"
        stmt = stmt.where(Asset.filename.ilike(like) | Asset.visual_description.ilike(like))
    stmt = stmt.order_by(Asset.last_indexed_at.desc()).offset(offset).limit(limit)
    return list(db.scalars(stmt).all())


@router.get("/assets/{asset_id}", response_model=AssetOut)
def get_asset(asset_id: str, db: Session = Depends(get_db)):
    asset = db.get(Asset, asset_id)
    if asset is None:
        raise HTTPException(404, "Asset not found.")
    return asset


@router.get("/assets/{asset_id}/image")
def get_asset_image(asset_id: str, max_size: int = 640, db: Session = Depends(get_db)):
    """Streams a resized JPEG preview of the real source file for use in the Library
    grid and creative-picker UIs. Opens the file under SOURCE_ASSET_ROOT read-only
    (Path.open in "rb" mode via PIL) and never writes back to it — the resize happens
    entirely in memory, matching the same immutability guarantee the scanner upholds.
    """
    asset = db.get(Asset, asset_id)
    if asset is None:
        raise HTTPException(404, "Asset not found.")
    path = Path(asset.absolute_path)
    if not path.exists():
        raise HTTPException(404, "Source file no longer exists at its indexed path.")

    max_size = max(64, min(max_size, 2000))
    try:
        with Image.open(path) as img:
            img = img.convert("RGB")
            img.thumbnail((max_size, max_size), Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=85)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"Could not read image: {exc}") from exc

    return Response(content=buf.getvalue(), media_type="image/jpeg")


@router.patch("/assets/{asset_id}", response_model=AssetOut)
def update_asset(asset_id: str, payload: AssetUpdate, db: Session = Depends(get_db)):
    asset = db.get(Asset, asset_id)
    if asset is None:
        raise HTTPException(404, "Asset not found.")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(asset, key, value)
    db.commit()
    db.refresh(asset)
    return asset
