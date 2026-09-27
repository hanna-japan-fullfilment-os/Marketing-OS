from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Brand
from ..schemas.asset import ScanRequest, ScanResult
from ..services import settings_store
from ..services.scanner import scan_repository

router = APIRouter(prefix="/api/repositories", tags=["repositories"])


@router.post("/scan", response_model=ScanResult)
def scan_now(payload: ScanRequest, db: Session = Depends(get_db)):
    brand = db.get(Brand, payload.brand_id)
    if brand is None:
        raise HTTPException(404, "Brand not found.")

    effective = settings_store.get_effective_settings(db)
    source_root = effective.get("source_asset_root")
    if not source_root:
        raise HTTPException(400, "SOURCE_ASSET_ROOT is not configured. Set it in Settings first.")

    outcome = scan_repository(db, brand_id=brand.id, source_root=Path(source_root))
    return ScanResult(
        scanned_files=outcome.scanned_files,
        new_assets=outcome.new_assets,
        updated_assets=outcome.updated_assets,
        unchanged_assets=outcome.unchanged_assets,
        skipped_non_images=outcome.skipped_non_images,
        errors=outcome.errors,
    )


@router.get("/test-path")
def test_path(path: str):
    p = Path(path)
    exists = p.exists()
    is_dir = p.is_dir() if exists else False
    return {"path": str(p), "exists": exists, "is_dir": is_dir}
