"""Tests for `app.db._run_migrations`/`init_db` (round 15) — the fix for a real gap
that round's own migration exposed: every prior schema change was a brand-new
table, which `Base.metadata.create_all` alone always handled fine with no Alembic
step required, so nothing ever verified that an *existing* install (which has
never been Alembic-tracked — `init_db` only ever called `create_all` directly)
could pick up a migration that alters a table it already has. These tests exercise
the real Alembic config/migration files on disk (not mocked), against throwaway
SQLite files, since a migration bug is exactly the kind of thing a fake would hide.

Round 16 added a second table-altering migration (`campaigns.target_slide_count`)
on top of round 15's `brand_assets.category_id` — the "existing install" test below
now models a database missing *both*, exercising the multi-hop stamp-then-upgrade
path in one call, per the extension pattern `app/db.py::_run_migrations` documents
for itself.
"""
from __future__ import annotations

import sqlite3

from sqlalchemy import create_engine, inspect


def _fresh_db_env(monkeypatch, db_path):
    from app import config as config_module

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    config_module.get_settings.cache_clear()


def test_init_db_on_a_brand_new_database_builds_the_full_schema(tmp_path, monkeypatch):
    """No database at all yet (a genuinely new install): every migration should run
    from scratch, building the complete schema — the same shape `create_all` alone
    has always produced — with nothing left for the `create_all` safety-net call
    afterward to actually do.
    """
    db_path = tmp_path / "fresh.db"
    _fresh_db_env(monkeypatch, db_path)

    from app import db as db_module

    # monkeypatch.setattr (not a plain assignment) so this reverts automatically —
    # `engine` is shared module state every other test relies on too.
    monkeypatch.setattr(db_module, "engine", create_engine(f"sqlite:///{db_path}"))
    db_module.init_db()

    inspector = inspect(db_module.engine)
    tables = set(inspector.get_table_names())
    assert "brand_assets" in tables
    assert "campaign_strategy_types" in tables  # a957c6dc54e6
    brand_asset_columns = {c["name"] for c in inspector.get_columns("brand_assets")}
    assert "category_id" in brand_asset_columns  # b94f4ec947d4 (round 15)
    campaign_columns = {c["name"] for c in inspector.get_columns("campaigns")}
    assert "target_slide_count" in campaign_columns  # f1882366252f (round 16)

    # Idempotent: running it again on an already-migrated DB must not crash.
    db_module.init_db()


def test_init_db_on_an_existing_never_tracked_database_migrates_without_data_loss(tmp_path, monkeypatch):
    """The real scenario round 15's migration created for the first time, now
    exercised across six pending migrations at once: a database that already has
    every table *through* round 14 (built, like every real install before round 15,
    purely via `create_all` — no `alembic_version` table exists) needs
    `brand_assets.category_id` (round 15), `campaigns.target_slide_count`
    (round 16), the whole `campaign_discovery_products` table (round 19),
    `campaigns.platform_key` + `brands.creative_instructions` (round 20),
    `campaign_strategy_types.product_scope` (also round 20), Build 1's
    `campaigns.languages`/`campaigns.target_platforms` + the whole
    `verified_product_facts` table, AND Build 2's whole `platform_campaign_variants`
    table added on top, with existing rows intact. Simulates that "existing
    install" shape directly (build the full current schema, then drop everything
    newer via raw DDL, matching what a round-14-or-earlier database actually looks
    like) rather than trusting that shape to itself, since asserting against the
    fixture would be circular.
    """
    db_path = tmp_path / "existing.db"
    _fresh_db_env(monkeypatch, db_path)

    from app import db as db_module
    from app import models  # noqa: F401  ensure every table is registered on Base

    engine = create_engine(f"sqlite:///{db_path}")
    db_module.Base.metadata.create_all(bind=engine)
    engine.dispose()

    conn = sqlite3.connect(db_path)
    conn.execute("ALTER TABLE brand_assets RENAME TO brand_assets_old_shape")
    conn.execute(
        """CREATE TABLE brand_assets (
            id VARCHAR(32) NOT NULL, brand_id VARCHAR(32) NOT NULL, kind VARCHAR(30) NOT NULL,
            file_path VARCHAR(1000) NOT NULL, label VARCHAR(200) NOT NULL,
            created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL, PRIMARY KEY (id)
        )"""
    )
    conn.execute("DROP TABLE brand_assets_old_shape")
    conn.execute(
        "INSERT INTO brand_assets (id, brand_id, kind, file_path, label, created_at, updated_at) "
        "VALUES ('a1', 'b1', 'logo', '/tmp/x.png', 'My logo', datetime('now'), datetime('now'))"
    )
    # SQLite 3.35+ supports DROP COLUMN natively — simpler and more faithful to the
    # real table's other column types/constraints than a manual rename-and-rebuild
    # (which is what the brand_assets simulation above has to do instead, since it
    # also needs to shrink the table below what any real prior schema looked like).
    conn.execute("ALTER TABLE campaigns DROP COLUMN target_slide_count")
    # Round 19's migration adds a whole new table rather than a column — a
    # round-14-or-earlier database wouldn't have it at all, so drop it entirely
    # (not just strip a column) to faithfully simulate that older shape.
    conn.execute("DROP TABLE campaign_discovery_products")
    # Round 20 added two columns and one more column on a separate table — strip
    # all three so this simulated pre-round-19 database doesn't accidentally
    # already look like it's past round 20 too (which `create_all` against
    # *current* models would otherwise make true, same trap round 19's version of
    # this test hit for its own new table).
    conn.execute("ALTER TABLE campaigns DROP COLUMN platform_key")
    conn.execute("ALTER TABLE brands DROP COLUMN creative_instructions")
    conn.execute("ALTER TABLE campaign_strategy_types DROP COLUMN product_scope")
    # Build 1 added `campaigns.languages`/`campaigns.target_platforms` and a whole
    # new `verified_product_facts` table — strip those too, same reasoning as
    # round 19's `campaign_discovery_products` above: a round-14-or-earlier
    # database wouldn't have any of this yet either.
    conn.execute("ALTER TABLE campaigns DROP COLUMN languages")
    conn.execute("ALTER TABLE campaigns DROP COLUMN target_platforms")
    conn.execute("DROP TABLE verified_product_facts")
    # Build 2 added a whole new `platform_campaign_variants` table — strip it too,
    # same reasoning as `campaign_discovery_products`/`verified_product_facts`
    # above: a round-14-or-earlier database wouldn't have it either. Without this,
    # `existing_tables` (app/db.py's stamp-detection) would see the table `create_
    # all` above just built from *current* models and wrongly stamp this database
    # at Build 2's own head revision, skipping every migration this test exists to
    # exercise — the same trap every earlier addition to this test had to avoid.
    conn.execute("DROP TABLE platform_campaign_variants")
    # Build 4 added `campaigns.human_review_status` and a whole new
    # `review_feedback` table — strip both too, same reasoning as every
    # addition above: a round-14-or-earlier database wouldn't have them, and
    # leaving them in place (since `create_all` above built them from
    # *current* models) would make the later `ALTER TABLE campaigns ADD
    # COLUMN human_review_status` migration fail with "duplicate column name"
    # once this database gets stamped at an old revision and replayed
    # forward. `platform_campaign_variants.human_review_status` needs no
    # separate handling since that whole table is already dropped above.
    conn.execute("ALTER TABLE campaigns DROP COLUMN human_review_status")
    conn.execute("DROP TABLE review_feedback")
    # Build 5 added `prompt_versions.platform_applicability`/
    # `language_applicability`/`active` plus two whole new tables
    # (`benchmark_cases`, `benchmark_runs`) — same reasoning as every
    # addition above, one more time: strip them so the later Build 5
    # migration has real work to do instead of hitting "duplicate column
    # name"/"table already exists" once this database is stamped at an old
    # revision and replayed forward.
    conn.execute("DROP TABLE benchmark_runs")
    conn.execute("DROP TABLE benchmark_cases")
    conn.execute("ALTER TABLE prompt_versions DROP COLUMN platform_applicability")
    conn.execute("ALTER TABLE prompt_versions DROP COLUMN language_applicability")
    conn.execute("ALTER TABLE prompt_versions DROP COLUMN active")
    # Build 6 added `ai_usage.platform`/`language`/`content_type` — unlike
    # every addition above, `ai_usage` itself predates round 1 and is never
    # otherwise touched by this synthetic "old" database, so `create_all()`
    # (which always builds from CURRENT models) would silently leave these
    # three columns already present without this strip, defeating the whole
    # point of this test: proving the migration chain actually adds them to a
    # database that genuinely lacks them, not just to one that never lost
    # them in the first place.
    conn.execute("ALTER TABLE ai_usage DROP COLUMN platform")
    conn.execute("ALTER TABLE ai_usage DROP COLUMN language")
    conn.execute("ALTER TABLE ai_usage DROP COLUMN content_type")
    # Build 6 repair added `ai_usage.scope` (the migration right after
    # f7a8b9c0d1e2) — same reasoning as the three columns just above.
    conn.execute("ALTER TABLE ai_usage DROP COLUMN scope")
    conn.commit()
    conn.close()

    monkeypatch.setattr(db_module, "engine", create_engine(f"sqlite:///{db_path}"))
    db_module.init_db()

    inspector = inspect(db_module.engine)
    brand_asset_columns_after = {c["name"] for c in inspector.get_columns("brand_assets")}
    assert "category_id" in brand_asset_columns_after
    campaign_columns_after = {c["name"] for c in inspector.get_columns("campaigns")}
    assert "target_slide_count" in campaign_columns_after
    assert "platform_key" in campaign_columns_after
    assert "campaign_discovery_products" in set(inspector.get_table_names())
    brand_columns_after = {c["name"] for c in inspector.get_columns("brands")}
    assert "creative_instructions" in brand_columns_after
    strategy_type_columns_after = {c["name"] for c in inspector.get_columns("campaign_strategy_types")}
    assert "product_scope" in strategy_type_columns_after
    assert "languages" in campaign_columns_after
    assert "target_platforms" in campaign_columns_after
    assert "verified_product_facts" in set(inspector.get_table_names())
    assert "platform_campaign_variants" in set(inspector.get_table_names())
    platform_variant_columns_after = {c["name"] for c in inspector.get_columns("platform_campaign_variants")}
    assert {"target_platform", "language", "content_type", "status"} <= platform_variant_columns_after
    assert "human_review_status" in campaign_columns_after
    assert "human_review_status" in platform_variant_columns_after
    assert "review_feedback" in set(inspector.get_table_names())

    table_names_after = set(inspector.get_table_names())
    assert "benchmark_cases" in table_names_after
    assert "benchmark_runs" in table_names_after
    prompt_version_columns_after = {c["name"] for c in inspector.get_columns("prompt_versions")}
    assert {"platform_applicability", "language_applicability", "active"} <= prompt_version_columns_after
    # Build 5 repair (Part 2): the new benchmark_runs column, added by the
    # migration right after d5e6f7a8b9c0 — since the whole table was stripped
    # above (not just one column), this also proves the migration CHAIN
    # replays both Build 5 migrations in order, not just the first one.
    benchmark_run_columns_after = {c["name"] for c in inspector.get_columns("benchmark_runs")}
    assert "creative_system_snapshot" in benchmark_run_columns_after
    # Build 6: ai_usage gained platform/language/content_type attribution columns
    # (the migration right after e6f7a8b9c0d1) — ai_usage itself is never
    # dropped above (it has existed since round 1), so this proves a plain
    # ADD COLUMN migration on a pre-existing table replays correctly too, not
    # just the "whole table stripped and rebuilt" migrations exercised above.
    ai_usage_columns_after = {c["name"] for c in inspector.get_columns("ai_usage")}
    assert {"platform", "language", "content_type"} <= ai_usage_columns_after
    # Build 6 repair: ai_usage gained a `scope` column (campaign_global vs
    # variant) — the migration right after f7a8b9c0d1e2 — proving the chain
    # replays this later plain ADD COLUMN migration too.
    assert "scope" in ai_usage_columns_after

    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT id, brand_id, kind, label, category_id FROM brand_assets WHERE id = 'a1'"
    ).fetchone()
    conn.close()
    assert row == ("a1", "b1", "logo", "My logo", None)  # the pre-migration row survived, category_id defaults null
