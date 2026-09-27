"""Section 59 of the project brief: SOURCE_ASSET_ROOT must remain immutable.

Snapshots SHA256 of every fixture source file, runs a full simulated scan (and,
as more of the pipeline lands, the rest of a campaign run against these fixtures
belongs here too), then asserts every original file has the exact same hash
afterward. This is a hard requirement, not a nice-to-have — a single failure here
means the app violated the one rule the user cares about most.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from app.models import Brand
from app.services.scanner import scan_repository


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _snapshot(source_root: Path) -> dict[str, str]:
    return {str(p): _sha256(p) for p in sorted(source_root.rglob("*")) if p.is_file()}


def test_source_files_are_byte_identical_after_full_scan(temp_db, fixture_images):
    source, _ = fixture_images
    before = _snapshot(source)
    before_mtimes = {str(p): p.stat().st_mtime for p in source.rglob("*") if p.is_file()}

    session = temp_db.SessionLocal()
    brand = Brand(name="Immutability Test Brand", slug="immutability-test")
    session.add(brand)
    session.commit()
    brand_id = brand.id

    # Run the scan twice (covers both "first index" and "re-index" code paths).
    scan_repository(session, brand_id=brand_id, source_root=source)
    scan_repository(session, brand_id=brand_id, source_root=source)
    session.close()

    after = _snapshot(source)
    after_mtimes = {str(p): p.stat().st_mtime for p in source.rglob("*") if p.is_file()}

    assert after == before, "Source asset content changed after scanning — SOURCE_ASSET_ROOT must be read-only."
    assert after_mtimes == before_mtimes, "Source file modification times changed — scanner must not touch source files."
    assert set(before.keys()) == set(after.keys()), "Files were added or removed under SOURCE_ASSET_ROOT by the scan."


def test_scanner_never_opens_source_files_for_writing(temp_db, fixture_images, monkeypatch):
    """Belt-and-suspenders: fail loudly if scan_repository ever calls Path.open in a
    writing mode against a file under the source root.
    """
    source, _ = fixture_images
    original_open = Path.open

    def guarded_open(self, mode="r", *args, **kwargs):
        if str(self).startswith(str(source)) and any(c in mode for c in ("w", "a", "x", "+")):
            raise AssertionError(f"Attempted to open source file in writing mode: {self} ({mode})")
        return original_open(self, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)

    session = temp_db.SessionLocal()
    brand = Brand(name="Guarded Brand", slug="guarded-brand")
    session.add(brand)
    session.commit()
    outcome = scan_repository(session, brand_id=brand.id, source_root=source)
    session.close()

    assert outcome.errors == []
