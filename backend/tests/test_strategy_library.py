from __future__ import annotations

from app.data.strategy_library import FAMILIES, STRATEGY_TYPES
from app.models import CampaignStrategyFamily, CampaignStrategyType
from app.services.seed import seed_strategy_library


def test_seed_creates_all_families_and_types(temp_db):
    session = temp_db.SessionLocal()
    seed_strategy_library(session)

    families = session.query(CampaignStrategyFamily).all()
    types = session.query(CampaignStrategyType).all()
    assert len(families) == len(FAMILIES) == 8
    assert len(types) == len(STRATEGY_TYPES)
    session.close()


def test_seed_is_idempotent(temp_db):
    session = temp_db.SessionLocal()
    seed_strategy_library(session)
    seed_strategy_library(session)  # run twice

    families = session.query(CampaignStrategyFamily).all()
    types = session.query(CampaignStrategyType).all()
    assert len(families) == 8
    assert len(types) == len(STRATEGY_TYPES)
    session.close()


def test_every_type_has_complete_campaign_dna(temp_db):
    """Every entry must actually have DNA filled in — no empty placeholder rows."""
    session = temp_db.SessionLocal()
    seed_strategy_library(session)

    for strategy_type in session.query(CampaignStrategyType).all():
        assert strategy_type.objective, f"{strategy_type.key} missing objective"
        assert strategy_type.audience, f"{strategy_type.key} missing audience"
        assert strategy_type.psychology, f"{strategy_type.key} missing psychology"
        assert strategy_type.channels, f"{strategy_type.key} missing channels"
        assert strategy_type.content_types, f"{strategy_type.key} missing content_types"
        assert strategy_type.success_metrics, f"{strategy_type.key} missing success_metrics"
        assert strategy_type.family is not None
    session.close()


def test_every_type_family_and_secondary_families_are_valid(temp_db):
    session = temp_db.SessionLocal()
    seed_strategy_library(session)

    family_keys = {f.key for f in session.query(CampaignStrategyFamily).all()}
    for strategy_type in session.query(CampaignStrategyType).all():
        assert strategy_type.family.key in family_keys
        for secondary in strategy_type.secondary_family_keys:
            assert secondary in family_keys, f"{strategy_type.key} has invalid secondary family {secondary}"
    session.close()


def test_defense_family_has_types_referencing_other_families(temp_db):
    """The Defense family's entries should be tagged as secondary ATTACK/CONVERT/BRAND
    responses, distinguishing them from spontaneous ATTACK campaigns."""
    session = temp_db.SessionLocal()
    seed_strategy_library(session)

    defense_family = session.query(CampaignStrategyFamily).filter_by(key="DEFENSE").one()
    defense_types = session.query(CampaignStrategyType).filter_by(family_id=defense_family.id).all()
    assert len(defense_types) >= 4
    assert all(t.trigger_type == "competitor_event" for t in defense_types)
    session.close()


def test_strategy_library_api_returns_grouped_families(temp_db):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        r = client.get("/api/strategy-library")
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 8
        keys = {f["key"] for f in data}
        assert keys == {"ATTACK", "ACQUIRE", "CONVERT", "RETAIN", "BRAND", "HYPE", "COMMUNITY", "DEFENSE"}
        total_types = sum(len(f["types"]) for f in data)
        assert total_types == len(STRATEGY_TYPES)


def test_get_single_strategy_type_by_key(temp_db):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        r = client.get("/api/strategy-library/types/competitor_counterattack")
        assert r.status_code == 200
        body = r.json()
        assert body["name"] == "Competitor Counterattack"
        assert "price_anchoring" in body["psychology"]

        r = client.get("/api/strategy-library/types/does-not-exist")
        assert r.status_code == 404
