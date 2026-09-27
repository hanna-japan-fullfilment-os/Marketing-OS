from __future__ import annotations

from app.models import Brand, Competitor, CompetitorEvent
from app.services.defense import recommend_response
from app.services.seed import seed_all


def _setup(session):
    seed_all(session)
    brand = Brand(name="Hanna", slug="hanna")
    session.add(brand)
    session.commit()
    competitor = Competitor(brand_id=brand.id, name="Rival Store")
    session.add(competitor)
    session.commit()
    return brand, competitor


def test_high_discount_promotion_recommends_counterattack(temp_db):
    session = temp_db.SessionLocal()
    brand, competitor = _setup(session)

    event = CompetitorEvent(
        competitor_id=competitor.id, brand_id=brand.id, event_type="promotion_launch",
        severity="high", details={"discount_pct": 25},
    )
    session.add(event)
    session.commit()

    recs = recommend_response(session, event)
    assert recs[0].strategy_type_key == "competitor_counterattack"
    session.close()


def test_moderate_discount_recommends_value_bundle_not_price_match(temp_db):
    session = temp_db.SessionLocal()
    brand, competitor = _setup(session)

    event = CompetitorEvent(
        competitor_id=competitor.id, brand_id=brand.id, event_type="promotion_launch",
        severity="medium", details={"discount_pct": 12},
    )
    session.add(event)
    session.commit()

    recs = recommend_response(session, event)
    assert recs[0].strategy_type_key == "value_bundle_defense"
    session.close()


def test_low_severity_falls_back_to_counter_marketing(temp_db):
    session = temp_db.SessionLocal()
    brand, competitor = _setup(session)

    event = CompetitorEvent(
        competitor_id=competitor.id, brand_id=brand.id, event_type="promotion_launch",
        severity="low", details={},
    )
    session.add(event)
    session.commit()

    recs = recommend_response(session, event)
    assert recs[0].strategy_type_key == "counter_marketing"
    session.close()


def test_campaign_detected_recommends_share_of_voice_defense(temp_db):
    session = temp_db.SessionLocal()
    brand, competitor = _setup(session)

    event = CompetitorEvent(
        competitor_id=competitor.id, brand_id=brand.id, event_type="campaign_detected",
        severity="high", details={},
    )
    session.add(event)
    session.commit()

    recs = recommend_response(session, event)
    assert recs[0].strategy_type_key == "share_of_voice_defense"
    session.close()


def test_recommendation_never_crashes_on_unmatched_event_type(temp_db):
    session = temp_db.SessionLocal()
    brand, competitor = _setup(session)

    event = CompetitorEvent(
        competitor_id=competitor.id, brand_id=brand.id, event_type="other", severity="low", details={},
    )
    session.add(event)
    session.commit()

    recs = recommend_response(session, event)
    assert isinstance(recs, list)
    session.close()


def test_brand_specific_playbook_takes_priority_over_global(temp_db):
    from app.models import DefensePlaybook

    session = temp_db.SessionLocal()
    brand, competitor = _setup(session)

    # A brand-specific override for restock events, higher priority than the global default.
    override = DefensePlaybook(
        brand_id=brand.id, event_type="restock", min_severity="low", condition={},
        recommended_strategy_key="price_attack", rationale="This brand prefers to price-attack restocks.",
        priority=5,
    )
    session.add(override)
    session.commit()

    event = CompetitorEvent(
        competitor_id=competitor.id, brand_id=brand.id, event_type="restock", severity="low", details={},
    )
    session.add(event)
    session.commit()

    recs = recommend_response(session, event)
    assert recs[0].strategy_type_key == "price_attack"
    session.close()
