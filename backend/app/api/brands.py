from __future__ import annotations

import io
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from PIL import Image
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Brand, BrandAsset, Category, Product
from ..schemas.ai import BrandVisualStyleAnalysis
from ..schemas.brand import (
    BrandAssetOut, BrandCreate, BrandOut, BrandUpdate, CategoryCreate, CategoryOut,
    ProductCreate, ProductOut,
)
from ..schemas.brand_assets import BrandAssetValidationResult
from ..services import settings_store
from ..services.ai.openai_provider import OpenAIProvider, openai_provider_from_effective_settings
from ..services.brand_assets_validator import validate_brand_assets

router = APIRouter(prefix="/api", tags=["brands"])

_BRAND_ASSET_KINDS = ("logo", "font", "visual_reference", "inspiration")


@router.get("/brands", response_model=list[BrandOut])
def list_brands(db: Session = Depends(get_db)):
    return db.query(Brand).order_by(Brand.created_at).all()


@router.post("/brands", response_model=BrandOut, status_code=201)
def create_brand(payload: BrandCreate, db: Session = Depends(get_db)):
    if db.query(Brand).filter(Brand.slug == payload.slug).first():
        raise HTTPException(409, "A brand with this slug already exists.")
    brand = Brand(**payload.model_dump())
    db.add(brand)
    db.commit()
    db.refresh(brand)
    return brand


@router.get("/brands/{brand_id}", response_model=BrandOut)
def get_brand(brand_id: str, db: Session = Depends(get_db)):
    brand = db.get(Brand, brand_id)
    if brand is None:
        raise HTTPException(404, "Brand not found.")
    return brand


@router.patch("/brands/{brand_id}", response_model=BrandOut)
def update_brand(brand_id: str, payload: BrandUpdate, db: Session = Depends(get_db)):
    brand = db.get(Brand, brand_id)
    if brand is None:
        raise HTTPException(404, "Brand not found.")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(brand, key, value)
    db.commit()
    db.refresh(brand)
    return brand


def _require_brand(db: Session, brand_id: str) -> Brand:
    brand = db.get(Brand, brand_id)
    if brand is None:
        raise HTTPException(404, "Brand not found.")
    return brand


def _brand_assets_dir(output_root: str, brand_slug: str, kind: str) -> Path:
    """Brand assets (logo/font/visual_reference photos) aren't tied to any one
    campaign, so they live in their own corner of OUTPUT_ROOT rather than the
    per-campaign folder structure documented in README.md — no new setting needed,
    and it's still somewhere the user can find them on disk if they want to.
    """
    return Path(output_root) / "_brand_assets" / brand_slug / kind


@router.post("/brands/{brand_id}/assets", response_model=BrandAssetOut, status_code=201)
async def upload_brand_asset(
    brand_id: str,
    kind: str = Form(...),
    label: str = Form(""),
    category_id: str | None = Form(None),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Uploads a brand asset: a logo (composited into every rendered slide via
    `resolve_brand_logo_path`), a font, a visual-reference photo (an example of the
    look the brand wants — used by `POST /brands/{id}/visual-style/analyze` below,
    and, when `use_ai_background` is on, as a live style reference handed to the
    image-generation model in services/orchestrator.py::generate_ai_background), or
    an inspiration example (a real ad/post/carousel the user wants campaigns to draw
    creative direction from — see services/orchestrator.py::recreate_creative_image,
    the `recreate_with_ai` pipeline step). Nothing here was previously exposed over
    the API — `BrandAsset` has existed in the schema since round 1, but there was no
    way to actually create one until round 10, so a brand's logo has never yet
    appeared on a rendered creative in this app before that round.

    `category_id` only means something for `kind="inspiration"` — it scopes that
    example to one category (e.g. an inspiration ad only relevant to Skincare
    campaigns) instead of the whole brand; every other kind ignores it. Left unset,
    an inspiration example applies brand-wide across every category.
    """
    if kind not in _BRAND_ASSET_KINDS:
        raise HTTPException(400, f"kind must be one of {_BRAND_ASSET_KINDS}.")
    brand = _require_brand(db, brand_id)
    if category_id:
        category = db.get(Category, category_id)
        if category is None or category.brand_id != brand.id:
            raise HTTPException(404, "Category not found for this brand.")
    effective = settings_store.get_effective_settings(db)
    output_root = effective.get("output_root")
    if not output_root:
        raise HTTPException(400, "OUTPUT_ROOT is not configured. Set it in Settings first.")

    data = await file.read()
    if not data:
        raise HTTPException(400, "Uploaded file is empty.")
    suffix = Path(file.filename or "").suffix or ".png"
    dest_dir = _brand_assets_dir(output_root, brand.slug, kind)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / f"{uuid.uuid4().hex}{suffix}"
    dest_path.write_bytes(data)

    asset = BrandAsset(
        brand_id=brand.id, kind=kind, category_id=category_id or None, file_path=str(dest_path), label=label,
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return asset


@router.get("/brands/{brand_id}/assets", response_model=list[BrandAssetOut])
def list_brand_assets(
    brand_id: str, kind: str | None = None, category_id: str | None = None, db: Session = Depends(get_db),
):
    _require_brand(db, brand_id)
    q = db.query(BrandAsset).filter(BrandAsset.brand_id == brand_id)
    if kind:
        q = q.filter(BrandAsset.kind == kind)
    if category_id:
        q = q.filter(BrandAsset.category_id == category_id)
    return q.order_by(BrandAsset.created_at.desc()).all()


@router.get("/brands/{brand_id}/assets/{asset_id}/file")
def get_brand_asset_file(brand_id: str, asset_id: str, max_size: int = 640, db: Session = Depends(get_db)):
    """Streams a resized JPEG preview, same pattern as `GET /api/assets/{id}/image`,
    so the frontend can show thumbnails of uploaded logos/reference photos without
    ever exposing a raw filesystem path to the browser.
    """
    asset = db.get(BrandAsset, asset_id)
    if asset is None or asset.brand_id != brand_id:
        raise HTTPException(404, "Brand asset not found.")
    path = Path(asset.file_path)
    if not path.exists():
        raise HTTPException(404, "Asset file no longer exists on disk.")
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


@router.delete("/brands/{brand_id}/assets/{asset_id}", status_code=204)
def delete_brand_asset(brand_id: str, asset_id: str, db: Session = Depends(get_db)):
    asset = db.get(BrandAsset, asset_id)
    if asset is None or asset.brand_id != brand_id:
        raise HTTPException(404, "Brand asset not found.")
    path = Path(asset.file_path)
    if path.exists():
        path.unlink(missing_ok=True)
    db.delete(asset)
    db.commit()
    return Response(status_code=204)


@router.post("/brands/{brand_id}/visual-style/analyze", response_model=BrandVisualStyleAnalysis)
async def analyze_brand_visual_style(brand_id: str, db: Session = Depends(get_db)):
    """Shows the model every uploaded 'visual_reference' photo for this brand and
    asks it to describe the visual style they establish — dominant colors,
    typography mood, photography style — as a proposal only. This never writes to
    the brand itself; the frontend pre-fills an editable form from the response and
    the user applies it (or not) via the existing `PATCH /api/brands/{id}`, keeping
    human approval authoritative over the brand's actual style, same as every other
    AI output in this app.
    """
    brand = _require_brand(db, brand_id)
    effective = settings_store.get_effective_settings(db)
    api_key = effective.get("openai_api_key")
    if not api_key:
        raise HTTPException(400, "OpenAI API key is not configured. Set it in Settings first.")

    references = (
        db.query(BrandAsset)
        .filter(BrandAsset.brand_id == brand.id, BrandAsset.kind == "visual_reference")
        .order_by(BrandAsset.created_at.desc())
        .all()
    )
    image_paths = [Path(a.file_path) for a in references if Path(a.file_path).exists()]
    if not image_paths:
        raise HTTPException(
            400,
            "Upload at least one visual-reference photo first (POST /brands/{id}/assets with "
            "kind=visual_reference) before analyzing style.",
        )

    provider = openai_provider_from_effective_settings(effective)
    try:
        return await provider.analyze_visual_style(
            image_paths=image_paths[:6], brand_name=brand.name, model=effective.get("openai_vision_model"),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"Visual style analysis failed: {exc}") from exc


@router.get("/brands/{brand_id}/asset-validation", response_model=BrandAssetValidationResult)
def get_brand_asset_validation(brand_id: str, product_id: str | None = None, db: Session = Depends(get_db)):
    """Build 2, Part C: a deterministic (no AI call, no invented content) check
    of this brand's real on-file logo/fonts/palette/product-photo assets — see
    `services/brand_assets_validator.py`. `product_id` narrows the product-
    photo check to one product; omitted, every product under this brand is
    checked. Never fabricates a placeholder for a missing asset (a brand with
    no logo gets `logo_present=false`, not a generated stand-in).
    """
    brand = _require_brand(db, brand_id)
    return validate_brand_assets(db, brand, product_id=product_id)


@router.get("/categories", response_model=list[CategoryOut])
def list_categories(brand_id: str, db: Session = Depends(get_db)):
    return db.query(Category).filter(Category.brand_id == brand_id).order_by(Category.name).all()


@router.post("/categories", response_model=CategoryOut, status_code=201)
def create_category(payload: CategoryCreate, db: Session = Depends(get_db)):
    category = Category(**payload.model_dump())
    db.add(category)
    db.commit()
    db.refresh(category)
    return category


@router.get("/products", response_model=list[ProductOut])
def list_products(brand_id: str, category_id: str | None = None, db: Session = Depends(get_db)):
    q = db.query(Product).filter(Product.brand_id == brand_id)
    if category_id:
        q = q.filter(Product.category_id == category_id)
    return q.order_by(Product.name).all()


@router.post("/products", response_model=ProductOut, status_code=201)
def create_product(payload: ProductCreate, db: Session = Depends(get_db)):
    product = Product(**payload.model_dump())
    db.add(product)
    db.commit()
    db.refresh(product)
    return product
