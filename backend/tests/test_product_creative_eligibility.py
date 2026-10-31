"""Isolated, zero-provider tests of the app-wide creative eligibility rule."""
import json
from datetime import date
from types import SimpleNamespace

import pytest

from app.services import product_creative_eligibility as policy


@pytest.fixture
def catalog(tmp_path, monkeypatch):
    path = tmp_path / "eligibility.json"
    path.write_text('{"version":1,"assessments":[]}', encoding="utf-8")
    monkeypatch.setattr(policy, "CATALOG", path)
    return path


def assessment(**updates):
    return dict({
        "product_id": "product-a", "ingredient": "Example ingredient",
        "status": "CONFIRMED_PROHIBITED", "territory": "BR",
        "source_url": "https://example.org/official-rule",
        "source_excerpt": "Test evidence only; no real ingredient determination.",
        "verified_by": "isolated test reviewer", "reviewed_on": "2020-01-01",
        "valid_until": "2099-12-31", "exact_formula_match": True,
        "prohibition_applies_to_product_use": True,
    }, **updates)


def write(catalog, *rows):
    catalog.write_text(json.dumps({"version": 1, "assessments": rows}), encoding="utf-8")


@pytest.mark.parametrize("product_id", ["product-a", "different-brand-product", "new-product"])
def test_no_confirmed_prohibition_allows_creative_with_warning(catalog, product_id):
    decision = policy.require_creative_eligibility(product_id)
    assert decision["creative_use_allowed"]
    assert not decision["commercial_clearance_required_for_creative_use"]
    assert decision["warnings"] and "not certified" in decision["warnings"][0]


def test_confirmed_prohibition_blocks_exact_product_and_names_source(catalog):
    write(catalog, assessment())
    with pytest.raises(ValueError, match="Example ingredient.*https://example.org/official-rule"):
        policy.require_creative_eligibility("product-a")
    assert policy.require_creative_eligibility("product-b")["creative_use_allowed"]


@pytest.mark.parametrize("updates", [
    {"status": "UNRESOLVED", "exact_formula_match": False},
    {"valid_until": "2021-01-01"},
    {"reviewed_on": "2098-01-01"},
])
def test_uncertain_expired_and_future_findings_warn_without_prohibition(catalog, updates):
    write(catalog, assessment(**updates))
    decision = policy.creative_eligibility("product-a", today=date(2026, 10, 31))
    assert decision["creative_use_allowed"] and len(decision["warnings"]) == 2


@pytest.mark.parametrize("updates", [
    {"source_url": ""}, {"source_excerpt": " "}, {"verified_by": " "},
    {"exact_formula_match": False}, {"prohibition_applies_to_product_use": False},
    {"territory": "JP"},
])
def test_missing_or_mismatched_evidence_cannot_be_recorded_as_confirmed(catalog, updates):
    write(catalog, assessment(**updates))
    with pytest.raises(ValueError):
        policy.creative_eligibility("product-a")


def test_current_prohibition_not_overridden_by_an_unresolved_record(catalog):
    write(catalog, assessment(), assessment(status="UNRESOLVED"))
    assert not policy.creative_eligibility("product-a")["creative_use_allowed"]


@pytest.mark.parametrize("entry", ["multimodal", "direct", "locked"])
def test_policy_is_rechecked_before_provider_call_on_prepared_objects(catalog, entry):
    write(catalog, assessment())
    package = SimpleNamespace(product_id="product-a")
    delivery = SimpleNamespace(package=package)
    if entry == "multimodal":
        from app.services.multimodal_creative import compose_candidate
        coroutine = compose_candidate(package, None, None)
    elif entry == "direct":
        from app.services.creative_delivery import deliver_candidate
        coroutine = deliver_candidate(delivery, None)
    else:
        from app.services.locked_scene import generate_locked_scene
        assets = SimpleNamespace(plan=SimpleNamespace(delivery=delivery))
        coroutine = generate_locked_scene(assets, None)
    # The guard runs before any await/provider access; no event loop or sockets.
    with pytest.raises(ValueError, match="confirmed prohibited"):
        coroutine.send(None)


def test_orchestrator_policy_applies_before_any_stage_or_provider(catalog):
    write(catalog, assessment())
    from app.models import Campaign, Brand, Product
    from app.services.orchestrator import _load_campaign_context
    rows = {Campaign: SimpleNamespace(brand_id="b", category_id=None, product_id="product-a"),
            Brand: SimpleNamespace(), Product: SimpleNamespace(id="product-a")}
    db = SimpleNamespace(get=lambda model, key: rows[model])
    with pytest.raises(ValueError, match="confirmed prohibited"):
        _load_campaign_context(db, "c")


@pytest.mark.parametrize("entry", ["bind_handoff", "require_ready"])
def test_export_gate_rechecks_policy_even_for_old_handoffs(catalog, entry):
    write(catalog, assessment())
    from app.services import marketing_claims
    with pytest.raises(ValueError, match="confirmed prohibited"):
        getattr(marketing_claims, entry)(SimpleNamespace(product_id="product-a"))


def test_product_api_exposes_allowed_warning_and_blocked_evidence(catalog):
    from app.api.products import get_product_creative_eligibility
    db = SimpleNamespace(get=lambda *args: object())
    assert get_product_creative_eligibility("product-a", db)["warnings"]
    write(catalog, assessment())
    decision = get_product_creative_eligibility("product-a", db)
    assert not decision["creative_use_allowed"]
    assert decision["confirmed_prohibitions"][0]["ingredient"] == "Example ingredient"


def test_prepared_package_is_revalidated_against_new_policy(catalog, tmp_path):
    from test_build6r_v101_creative_package import package
    from app.schemas.creative_bridge import HannaCreativePackage
    prepared = package(tmp_path, product_id="product-a")
    write(catalog, assessment())
    with pytest.raises(ValueError, match="confirmed prohibited"):
        HannaCreativePackage.model_validate(prepared.model_dump())


@pytest.mark.parametrize("entry", ["compose_creative", "compose_direct_creative"])
def test_provider_boundary_blocks_before_sdk_or_budget_access(catalog, entry):
    write(catalog, assessment())
    from app.services.ai.openai_provider import OpenAIProvider
    package = SimpleNamespace(product_id="product-a")
    if entry == "compose_creative":
        coroutine = OpenAIProvider.compose_creative(None, package=package, options=None)
    else:
        coroutine = OpenAIProvider.compose_direct_creative(
            None, delivery=SimpleNamespace(package=package))
    with pytest.raises(ValueError, match="confirmed prohibited"):
        coroutine.send(None)
