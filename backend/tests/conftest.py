from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    """Point the app at a throwaway SQLite file for this test by swapping the
    engine/SessionLocal that live on the `app.db` module (rather than reloading the
    module, which would create a second, disconnected `Base` class that the already
    -imported model modules aren't registered on).
    """
    from app import config as config_module
    from app import db as db_module
    from app import models  # noqa: F401  ensure every table is registered on Base

    db_path = tmp_path / "test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    config_module.get_settings.cache_clear()

    test_engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})

    @event.listens_for(test_engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, _connection_record):
        # Match app/db.py's `_make_engine()` — SQLite has foreign keys OFF by
        # default per connection, so without this, DB-level `ondelete="CASCADE"`
        # (e.g. Publication/CampaignOpportunity/CampaignVariant rows tied to a
        # deleted Campaign) would silently not fire in tests even though it does
        # in the real app, letting a real cascade-delete bug pass unnoticed.
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    test_session_local = sessionmaker(bind=test_engine, autoflush=False, autocommit=False, expire_on_commit=False)

    monkeypatch.setattr(db_module, "engine", test_engine)
    monkeypatch.setattr(db_module, "SessionLocal", test_session_local)

    db_module.Base.metadata.create_all(bind=test_engine)

    yield db_module

    config_module.get_settings.cache_clear()


@pytest.fixture()
def fixture_images(tmp_path):
    from PIL import Image

    source = tmp_path / "source"
    (source / "skincare" / "product-a").mkdir(parents=True)
    (source / "haircare" / "product-b").mkdir(parents=True)

    paths = {
        "front": source / "skincare" / "product-a" / "front.jpg",
        "back": source / "skincare" / "product-a" / "back.jpg",
        "hero": source / "haircare" / "product-b" / "hero.png",
    }
    Image.new("RGB", (800, 800), (200, 50, 50)).save(paths["front"])
    Image.new("RGB", (800, 1000), (50, 200, 50)).save(paths["back"])
    Image.new("RGB", (600, 600), (50, 50, 200)).save(paths["hero"])

    return source, paths
