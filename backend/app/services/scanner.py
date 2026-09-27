"""Repository scanner (brief sections 4-5).

SOURCE_ASSET_ROOT is treated as strictly read-only: this module only ever calls
Path.open("rb") / stat() / iterdir() on it. It never writes, moves, renames, or
deletes anything under that root. See tests/test_source_immutability.py for the
automated guarantee.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image
import imagehash
from sqlalchemy.orm import Session

from ..models import Asset, Category, Product

SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
# HEIC is optional per the brief; enabled automatically if pillow-heif is installed.
try:
    import pillow_heif  # type: ignore

    pillow_heif.register_heif_opener()
    SUPPORTED_EXTENSIONS.add(".heic")
except ImportError:
    pass


def _sha256_of_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _phash_of_image(path: Path) -> str:
    try:
        with Image.open(path) as img:
            return str(imagehash.phash(img))
    except Exception:
        return ""


def _dimensions(path: Path) -> tuple[int, int]:
    try:
        with Image.open(path) as img:
            return img.size
    except Exception:
        return (0, 0)


def _guess_category_slug(relative_path: Path) -> str | None:
    """First path component under the source root is treated as the category, matching
    the folder convention documented in the brief (e.g. Source/skincare/product-a/...).
    Not enforced as the only valid layout — just the default heuristic.
    """
    parts = relative_path.parts
    return parts[0] if parts else None


def _guess_product_slug(relative_path: Path) -> str | None:
    """Second path component (the folder directly above the file itself) is treated
    as the product, matching the same documented convention
    (Source/skincare/product-a/photo.jpg → category "skincare", product "product-a").
    Only applies when there actually IS a second directory level — a file sitting
    directly under the category folder (Source/skincare/photo.jpg) has no product
    folder to infer one from, and is left product-less (not an error; plenty of
    real libraries are flat within a category). Round 19: this is what makes
    "one campaign, many different products, one slide each" (discovery-mode
    carousels) possible without any manual per-photo tagging — see
    docs/campaign-pipeline.md's round-19 section.
    """
    parts = relative_path.parts
    return parts[1] if len(parts) >= 3 else None


@dataclass
class ScanOutcome:
    scanned_files: int = 0
    new_assets: int = 0
    updated_assets: int = 0
    unchanged_assets: int = 0
    skipped_non_images: int = 0
    errors: list[str] = field(default_factory=list)


def scan_repository(db: Session, *, brand_id: str, source_root: Path) -> ScanOutcome:
    outcome = ScanOutcome()
    if not source_root.exists() or not source_root.is_dir():
        outcome.errors.append(f"Source root does not exist or is not a directory: {source_root}")
        return outcome

    # Cache existing categories by slug for this brand so we don't create duplicates.
    existing_categories = {c.slug: c for c in db.query(Category).filter(Category.brand_id == brand_id).all()}
    # Cache existing products by (category_id, slug) — the same product-folder slug
    # could in principle exist under two different categories, so scope the cache key
    # by category rather than by slug alone.
    existing_products = {
        (p.category_id, p.slug): p for p in db.query(Product).filter(Product.brand_id == brand_id).all()
    }

    def _resolve_category_and_product(relative_path: Path) -> tuple[Category | None, Product | None]:
        category_slug = _guess_category_slug(relative_path)
        category = None
        if category_slug:
            category = existing_categories.get(category_slug)
            if category is None:
                category = Category(
                    brand_id=brand_id,
                    name=category_slug.replace("-", " ").replace("_", " ").title(),
                    slug=category_slug,
                )
                db.add(category)
                db.flush()
                existing_categories[category_slug] = category

        product = None
        product_slug = _guess_product_slug(relative_path)
        if product_slug and category is not None:
            key = (category.id, product_slug)
            product = existing_products.get(key)
            if product is None:
                product = Product(
                    brand_id=brand_id,
                    category_id=category.id,
                    name=product_slug.replace("-", " ").replace("_", " ").title(),
                    slug=product_slug,
                )
                db.add(product)
                db.flush()
                existing_products[key] = product
        return category, product

    for path in sorted(source_root.rglob("*")):
        if not path.is_file():
            continue
        outcome.scanned_files += 1
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            outcome.skipped_non_images += 1
            continue

        try:
            stat = path.stat()
            relative_path = path.relative_to(source_root)
            absolute_path = str(path.resolve())

            existing = db.query(Asset).filter(Asset.absolute_path == absolute_path).one_or_none()
            fs_modified = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)

            def _same_instant(a: datetime | None, b: datetime) -> bool:
                if a is None:
                    return False
                a_ts = a.timestamp() if a.tzinfo else a.replace(tzinfo=timezone.utc).timestamp()
                return abs(a_ts - b.timestamp()) < 1.0  # sub-second SQLite round-trip tolerance

            if (
                existing is not None
                and _same_instant(existing.modified_at_fs, fs_modified)
                and existing.file_size_bytes == stat.st_size
            ):
                outcome.unchanged_assets += 1
                existing.last_indexed_at = datetime.now(timezone.utc)
                # Round 19 backfill: an asset scanned before product-folder detection
                # existed (or one whose category/product wasn't resolved for any other
                # reason) picks up its category/product on a plain re-scan, with no
                # hashing needed — never overwrites a value that's already set, so this
                # only ever fills in a gap, matching category_id's existing "set once"
                # behavior for everything else about the file.
                if existing.category_id is None or existing.product_id is None:
                    category, product = _resolve_category_and_product(relative_path)
                    if existing.category_id is None and category is not None:
                        existing.category_id = category.id
                    if existing.product_id is None and product is not None:
                        existing.product_id = product.id
                continue

            sha256 = _sha256_of_file(path)
            phash = _phash_of_image(path)
            width, height = _dimensions(path)
            aspect_ratio = round(width / height, 4) if height else 0.0

            category, product = _resolve_category_and_product(relative_path)

            if existing is None:
                asset = Asset(
                    brand_id=brand_id,
                    category_id=category.id if category else None,
                    product_id=product.id if product else None,
                    absolute_path=absolute_path,
                    relative_path=str(relative_path),
                    filename=path.name,
                    extension=path.suffix.lower(),
                    sha256=sha256,
                    phash=phash,
                    file_size_bytes=stat.st_size,
                    width=width,
                    height=height,
                    aspect_ratio=aspect_ratio,
                    created_at_fs=datetime.fromtimestamp(stat.st_ctime, tz=timezone.utc),
                    modified_at_fs=fs_modified,
                )
                db.add(asset)
                outcome.new_assets += 1
            else:
                existing.sha256 = sha256
                existing.phash = phash
                existing.width = width
                existing.height = height
                existing.aspect_ratio = aspect_ratio
                existing.file_size_bytes = stat.st_size
                existing.modified_at_fs = fs_modified
                existing.last_indexed_at = datetime.now(timezone.utc)
                existing.checksum_stale = True
                # Same backfill-only-a-gap rule as the unchanged path above.
                if existing.category_id is None and category is not None:
                    existing.category_id = category.id
                if existing.product_id is None and product is not None:
                    existing.product_id = product.id
                outcome.updated_assets += 1
        except Exception as exc:  # noqa: BLE001 - we want to keep scanning other files
            outcome.errors.append(f"{path}: {exc}")

    db.commit()
    return outcome
