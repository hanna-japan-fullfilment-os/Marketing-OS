from __future__ import annotations

from pathlib import Path

from app.models import Asset, Brand
from app.services.scanner import scan_repository


def _make_brand(db_module) -> str:
    session = db_module.SessionLocal()
    brand = Brand(name="Test Brand", slug="test-brand")
    session.add(brand)
    session.commit()
    brand_id = brand.id
    session.close()
    return brand_id


def test_scan_discovers_all_supported_images(temp_db, fixture_images):
    source, paths = fixture_images
    brand_id = _make_brand(temp_db)

    session = temp_db.SessionLocal()
    outcome = scan_repository(session, brand_id=brand_id, source_root=source)
    session.close()

    assert outcome.scanned_files == 3
    assert outcome.new_assets == 3
    assert outcome.errors == []

    session = temp_db.SessionLocal()
    assets = session.query(Asset).filter(Asset.brand_id == brand_id).all()
    assert {a.filename for a in assets} == {"front.jpg", "back.jpg", "hero.png"}
    for asset in assets:
        assert len(asset.sha256) == 64
        assert asset.width > 0 and asset.height > 0
        assert asset.times_used == 0
    session.close()


def test_rescan_is_idempotent_when_nothing_changed(temp_db, fixture_images):
    source, _ = fixture_images
    brand_id = _make_brand(temp_db)

    session = temp_db.SessionLocal()
    scan_repository(session, brand_id=brand_id, source_root=source)
    session.close()

    session = temp_db.SessionLocal()
    outcome = scan_repository(session, brand_id=brand_id, source_root=source)
    session.close()

    assert outcome.new_assets == 0
    assert outcome.updated_assets == 0
    assert outcome.unchanged_assets == 3


def test_rescan_detects_content_change(temp_db, fixture_images):
    from PIL import Image

    source, paths = fixture_images
    brand_id = _make_brand(temp_db)

    session = temp_db.SessionLocal()
    scan_repository(session, brand_id=brand_id, source_root=source)
    session.close()

    session = temp_db.SessionLocal()
    original_hash = session.query(Asset).filter(Asset.filename == "front.jpg").one().sha256
    session.close()

    # Modify the file content -> mtime and size change -> must be picked up as updated.
    Image.new("RGB", (400, 400), (9, 9, 9)).save(paths["front"])

    session = temp_db.SessionLocal()
    outcome = scan_repository(session, brand_id=brand_id, source_root=source)
    session.close()

    assert outcome.updated_assets == 1

    session = temp_db.SessionLocal()
    new_hash = session.query(Asset).filter(Asset.filename == "front.jpg").one().sha256
    session.close()
    assert new_hash != original_hash


def test_categories_are_created_from_top_level_folders(temp_db, fixture_images):
    from app.models import Category

    source, _ = fixture_images
    brand_id = _make_brand(temp_db)

    session = temp_db.SessionLocal()
    scan_repository(session, brand_id=brand_id, source_root=source)
    categories = {c.slug for c in session.query(Category).filter(Category.brand_id == brand_id).all()}
    session.close()

    assert categories == {"skincare", "haircare"}


def test_non_image_files_are_skipped(temp_db, fixture_images):
    source, _ = fixture_images
    (source / "skincare" / "product-a" / "notes.txt").write_text("not an image")
    brand_id = _make_brand(temp_db)

    session = temp_db.SessionLocal()
    outcome = scan_repository(session, brand_id=brand_id, source_root=source)
    session.close()

    assert outcome.skipped_non_images == 1
    assert outcome.new_assets == 3


def test_missing_source_root_is_reported_not_raised(temp_db, tmp_path):
    brand_id = _make_brand(temp_db)
    session = temp_db.SessionLocal()
    outcome = scan_repository(session, brand_id=brand_id, source_root=tmp_path / "does-not-exist")
    session.close()

    assert outcome.errors
    assert outcome.scanned_files == 0


def test_products_are_auto_created_from_second_level_folders(temp_db, fixture_images):
    """Round 19: the second path component (Source/<category>/<product>/photo.jpg)
    is auto-detected as the product, exactly like the first component already is
    for category — no manual per-photo tagging needed. This is what makes
    discovery-mode carousels (one distinct product per slide) possible from a
    library that already follows the documented folder convention.
    """
    from app.models import Product

    source, _ = fixture_images  # skincare/product-a/{front,back}.jpg, haircare/product-b/hero.png
    brand_id = _make_brand(temp_db)

    session = temp_db.SessionLocal()
    scan_repository(session, brand_id=brand_id, source_root=source)
    products = session.query(Product).filter(Product.brand_id == brand_id).all()
    by_slug = {p.slug: p for p in products}
    assert set(by_slug) == {"product-a", "product-b"}
    assert by_slug["product-a"].name == "Product A"

    assets_by_filename = {
        a.filename: a for a in session.query(Asset).filter(Asset.brand_id == brand_id).all()
    }
    assert assets_by_filename["front.jpg"].product_id == by_slug["product-a"].id
    assert assets_by_filename["back.jpg"].product_id == by_slug["product-a"].id
    assert assets_by_filename["hero.png"].product_id == by_slug["product-b"].id
    # product-a's Product row is correctly scoped to the skincare category, not haircare.
    skincare_category_id = assets_by_filename["front.jpg"].category_id
    assert by_slug["product-a"].category_id == skincare_category_id
    session.close()


def test_flat_files_directly_under_category_get_no_product(temp_db, tmp_path):
    """A file with no folder level between it and the category (Source/skincare/
    photo.jpg) has no product folder to infer one from — left product-less, not
    an error. Plenty of real libraries aren't organized per-product.
    """
    from PIL import Image

    source = tmp_path / "source"
    (source / "skincare").mkdir(parents=True)
    Image.new("RGB", (400, 400), (1, 2, 3)).save(source / "skincare" / "flat.jpg")
    brand_id = _make_brand(temp_db)

    session = temp_db.SessionLocal()
    scan_repository(session, brand_id=brand_id, source_root=source)
    asset = session.query(Asset).filter(Asset.brand_id == brand_id, Asset.filename == "flat.jpg").one()
    assert asset.category_id is not None
    assert asset.product_id is None
    session.close()


def test_rescan_backfills_product_id_on_unchanged_file(temp_db, fixture_images):
    """An asset scanned before product-folder detection existed (product_id left
    NULL, matching every asset scanned before this round) must pick up its
    product on a plain re-scan even though the file itself is unchanged on disk
    — the whole point is the user doesn't have to touch their files to benefit.
    """
    source, _ = fixture_images
    brand_id = _make_brand(temp_db)

    session = temp_db.SessionLocal()
    scan_repository(session, brand_id=brand_id, source_root=source)
    # Simulate a pre-round-19 asset: clear product_id back to NULL as if it had
    # been scanned by an older build that never derived it.
    front = session.query(Asset).filter(Asset.brand_id == brand_id, Asset.filename == "front.jpg").one()
    front.product_id = None
    session.commit()
    session.close()

    session = temp_db.SessionLocal()
    outcome = scan_repository(session, brand_id=brand_id, source_root=source)
    assert outcome.unchanged_assets == 3  # confirms this went through the fast unchanged path
    front = session.query(Asset).filter(Asset.brand_id == brand_id, Asset.filename == "front.jpg").one()
    assert front.product_id is not None
    assert front.product.slug == "product-a"
    session.close()
