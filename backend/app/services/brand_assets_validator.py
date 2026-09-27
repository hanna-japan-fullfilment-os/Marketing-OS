"""Build 2, Part C: validate a brand's real, on-file creative assets before a
campaign uses them — logo, fonts, palette, product photos, and which
`BrandAsset` kinds actually have at least one usable file. Purely
deterministic (no AI call): every check reads a real DB row and, for anything
file-backed, confirms the file still exists on disk. **Never synthesizes a
placeholder** — a brand with no logo uploaded gets `logo_present=False` and
`logo_path=""`, never a generated stand-in, matching this app's existing
"real files only" discipline (`services/orchestrator.py`'s asset-resolution
helpers already follow this same rule).
"""
from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from .creative.brand_style import resolve_brand_style
from ..models import Asset, Brand, BrandAsset, Product
from ..schemas.brand_assets import BrandAssetValidationResult


def validate_brand_assets(db: Session, brand: Brand, *, product_id: str | None = None) -> BrandAssetValidationResult:
    """Runs every check and returns one structured result. `product_id`, when
    given, narrows the product-photo check to that one product (e.g. before a
    deep-dive campaign starts); omitted, it checks every product under this
    brand that HAS at least one Asset row against every product that doesn't,
    so a brand with a genuinely empty catalog isn't reported as "0 products,
    all fine."
    """
    issues: list[str] = []

    logo_asset = db.query(BrandAsset).filter(BrandAsset.brand_id == brand.id, BrandAsset.kind == "logo").first()
    logo_path = Path(logo_asset.file_path) if logo_asset else None
    logo_present = bool(logo_path and logo_path.exists())
    if logo_asset is None:
        issues.append("No logo has been uploaded for this brand (BrandAsset kind=\"logo\").")
    elif not logo_present:
        issues.append(f"A logo is on record but its file is missing on disk: {logo_asset.file_path}")

    style = resolve_brand_style(db, brand, logo_path=logo_path if logo_present else None)
    # `resolve_brand_style` always returns SOMETHING (falling back to hardcoded
    # defaults per its own docstring) — "resolved" here means the brand
    # actually configured real values, not that the resolver merely ran.
    fonts_resolved = bool(isinstance(brand.typography, dict) and brand.typography)
    if not fonts_resolved:
        issues.append(
            "No brand fonts are configured — renders will use the hardcoded default font family "
            f"({style.primary_font!r}) rather than a brand-chosen one."
        )

    palette_colors = [c for c in (style.palette or []) if c]
    palette_present = bool(isinstance(brand.colors, dict) and brand.colors)
    if not palette_present:
        issues.append(
            "No brand colors are configured — renders will use the hardcoded default palette "
            f"({style.accent_color!r}/{style.text_color!r}) rather than brand-chosen colors."
        )

    products_query = db.query(Product).filter(Product.brand_id == brand.id)
    if product_id:
        products_query = products_query.filter(Product.id == product_id)
    products = products_query.all()
    products_with_photos = 0
    products_without_photos = 0
    for product in products:
        has_active_asset = (
            db.query(Asset)
            .filter(Asset.product_id == product.id, Asset.is_active.is_(True))
            .first()
            is not None
        )
        if has_active_asset:
            products_with_photos += 1
        else:
            products_without_photos += 1
            issues.append(f"Product {product.name!r} has no active photo on file.")
    product_assets_present = products_with_photos > 0

    approved_kinds = sorted(
        {
            row.kind
            for row in db.query(BrandAsset).filter(BrandAsset.brand_id == brand.id).all()
            if Path(row.file_path).exists()
        }
    )

    valid = logo_present and fonts_resolved and palette_present and (not products or product_assets_present)

    return BrandAssetValidationResult(
        brand_id=brand.id,
        logo_present=logo_present,
        logo_path=str(logo_path) if logo_present and logo_path else "",
        fonts_resolved=fonts_resolved,
        primary_font=style.primary_font,
        secondary_font=style.secondary_font,
        palette_present=palette_present,
        palette_colors=palette_colors,
        product_assets_present=product_assets_present,
        products_with_photos=products_with_photos,
        products_without_photos=products_without_photos,
        approved_asset_kinds=approved_kinds,
        issues=issues,
        valid=valid,
    )
