from __future__ import annotations

from pathlib import Path
from collections.abc import Generator

from sqlalchemy import create_engine, event, inspect
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    pass


def _make_engine():
    settings = get_settings()
    url = settings.database_url
    if url.startswith("sqlite"):
        # Ensure the parent directory for file-based sqlite DBs exists.
        db_path = url.split("///")[-1]
        if db_path and db_path not in (":memory:",):
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        engine = create_engine(url, connect_args={"check_same_thread": False})

        @event.listens_for(engine, "connect")
        def _set_sqlite_pragma(dbapi_connection, _connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        return engine
    return create_engine(url)


engine = _make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _run_migrations() -> None:
    """Applies pending Alembic migrations automatically on every backend startup,
    instead of requiring the user to separately remember `alembic upgrade head`
    after updating the app. Added in round 15, prompted by that round's own
    migration being the first one ever to alter an *existing* table
    (`brand_assets` gaining a `category_id` column) rather than only add new ones
    — every prior round's schema change was a brand-new table, which `create_all`
    below always handled fine on its own with no migration needed at all, so this
    gap simply never surfaced before now. Left unfixed, every existing install
    would 500 the moment it tried to read/write `brand_assets.category_id` until
    the user found and ran the manual migration command themselves — the same
    class of "silent staleness" problem as round 14's stuck-campaign-status bug,
    just at the schema layer instead of the job layer.

    Safe on every database shape this app has ever shipped:
    - A brand-new, empty database has no `alembic_version` table and no
      application tables either — every migration runs from scratch, in order,
      building the full schema. `create_all` below then finds everything already
      present and does nothing.
    - An existing install has real tables but, until this round, was *never*
      alembic-tracked (`init_db` only ever called `create_all` directly) — so it
      has no `alembic_version` table either, but unlike the case above it already
      has tables. Running every migration from scratch against it would crash on
      "table already exists" the moment it replayed a `create_table` for
      something that's already there. So this case is `stamp`ped first — marked
      as already being at whichever of this app's own past schema revisions its
      real table set matches (never executing that revision's migration, just
      recording that it's already satisfied) — before `upgrade` runs, so only the
      genuinely new migration(s) after that point actually execute.
    - A database this function has already run against once has a real
      `alembic_version` row from the `upgrade` below, so future runs just apply
      whatever's newly pending, the normal Alembic story.
    """
    from alembic import command
    from alembic.config import Config
    from alembic.runtime.migration import MigrationContext

    backend_root = Path(__file__).resolve().parent.parent
    alembic_ini = backend_root / "alembic.ini"
    if not alembic_ini.exists():
        return  # e.g. a stripped-down test/deploy layout with no alembic/ at all

    cfg = Config(str(alembic_ini))
    cfg.set_main_option("script_location", str(backend_root / "alembic"))
    cfg.set_main_option("sqlalchemy.url", get_settings().database_url)

    with engine.connect() as connection:
        current_rev = MigrationContext.configure(connection).get_current_revision()

    if current_rev is None:
        inspector = inspect(engine)
        existing_tables = set(inspector.get_table_names())
        if existing_tables:
            # Never alembic-tracked, but not empty either — stamp at whichever
            # past revision this app's real table set already matches, so
            # `upgrade` below only replays what's genuinely new. Checked by the
            # actual columns present, not just which revision "should" have added
            # them — a DB built by `create_all` against *current* models (every
            # test's `temp_db` fixture, or a fresh install that got a version of
            # the app past this round) already has `category_id` with no
            # migration having run at all, and stamping at a957c6dc54e6 for that
            # case would make `upgrade` try to add a column that's already there.
            # A later migration extending this function should follow the same
            # pattern: check what its own change would add before assuming an
            # older stamp is correct.
            brand_asset_columns = (
                {c["name"] for c in inspector.get_columns("brand_assets")} if "brand_assets" in existing_tables
                else set()
            )
            campaign_columns = (
                {c["name"] for c in inspector.get_columns("campaigns")} if "campaigns" in existing_tables
                else set()
            )
            strategy_type_columns = (
                {c["name"] for c in inspector.get_columns("campaign_strategy_types")}
                if "campaign_strategy_types" in existing_tables else set()
            )
            platform_variant_columns = (
                {c["name"] for c in inspector.get_columns("platform_campaign_variants")}
                if "platform_campaign_variants" in existing_tables else set()
            )
            prompt_version_columns = (
                {c["name"] for c in inspector.get_columns("prompt_versions")}
                if "prompt_versions" in existing_tables else set()
            )
            benchmark_run_columns = (
                {c["name"] for c in inspector.get_columns("benchmark_runs")}
                if "benchmark_runs" in existing_tables else set()
            )
            ai_usage_columns = (
                {c["name"] for c in inspector.get_columns("ai_usage")}
                if "ai_usage" in existing_tables else set()
            )
            if "scope" in ai_usage_columns:
                stamp_at = "b6c7d8e9f0a1"
            elif "platform" in ai_usage_columns:
                stamp_at = "f7a8b9c0d1e2"
            elif "creative_system_snapshot" in benchmark_run_columns:
                stamp_at = "e6f7a8b9c0d1"
            elif "benchmark_runs" in existing_tables and "active" in prompt_version_columns:
                stamp_at = "d5e6f7a8b9c0"
            elif "review_feedback" in existing_tables and "human_review_status" in platform_variant_columns:
                stamp_at = "c4d5e6f7a8b9"
            elif "qa_status" in platform_variant_columns:
                stamp_at = "b2c3d4e5f6a7"
            elif "platform_campaign_variants" in existing_tables:
                stamp_at = "a1b2c3d4e5f6"
            elif "languages" in campaign_columns:
                stamp_at = "f4a8c2e6b1d9"
            elif "product_scope" in strategy_type_columns:
                stamp_at = "e7b3c5a9d1f4"
            elif "platform_key" in campaign_columns:
                stamp_at = "d4f6a1c8b9e2"
            elif "campaign_discovery_products" in existing_tables:
                stamp_at = "c3a1f9d2b6e4"
            elif "target_slide_count" in campaign_columns:
                stamp_at = "f1882366252f"
            elif "category_id" in brand_asset_columns:
                stamp_at = "b94f4ec947d4"
            elif "campaign_strategy_types" in existing_tables:
                stamp_at = "a957c6dc54e6"
            else:
                stamp_at = "ba2d83aa362d"
            command.stamp(cfg, stamp_at)

    command.upgrade(cfg, "head")


def init_db() -> None:
    """Bring the schema fully up to date (see `_run_migrations` above for exactly
    how that stays safe across every database shape this app has shipped), then
    `create_all` as a no-op safety net for local/test setups where migrations
    were skipped entirely.
    """
    from . import models  # noqa: F401  (ensure all models are registered on Base)

    _run_migrations()
    Base.metadata.create_all(bind=engine)
