"""API-layer tests for Build 1 ("Verified Product Facts + Campaign Foundation"):
Part A's VerifiedProductFacts endpoints, and Parts B/C's `languages`/
`target_platforms` campaign fields + the new platform-capabilities endpoint.
Orchestrator-level (prompt-grounding) tests live in test_orchestrator.py, next to
the rest of that module's coverage.
"""
from __future__ import annotations

from tests.test_api import _client


def _make_brand_and_product(client) -> tuple[str, str, str]:
    r = client.post("/api/brands", json={"name": "Hanna", "slug": "hanna"})
    assert r.status_code == 201
    brand_id = r.json()["id"]
    r = client.post("/api/categories", json={"brand_id": brand_id, "name": "Skincare", "slug": "skincare"})
    assert r.status_code == 201
    category_id = r.json()["id"]
    r = client.post(
        "/api/products",
        json={"brand_id": brand_id, "category_id": category_id, "name": "Rice Serum", "slug": "rice-serum"},
    )
    assert r.status_code == 201
    return brand_id, category_id, r.json()["id"]


def test_verified_product_facts_creation_and_round_trip(temp_db):
    """Test 1: a `VerifiedProductFacts` structure can be created (via the owner-
    editable PUT endpoint) and read back with every field intact.
    """
    with _client(temp_db) as client:
        _, _, product_id = _make_brand_and_product(client)

        r = client.get(f"/api/products/{product_id}/verified-facts")
        assert r.status_code == 200
        assert r.json()["product_name"] == "Rice Serum"
        assert r.json()["provenance"] == "unverified"  # nothing entered yet

        r = client.put(
            f"/api/products/{product_id}/verified-facts",
            json={
                "verified_description": "A lightweight rice-bran serum for daily hydration.",
                "verified_ingredients": ["Rice bran extract", "Hyaluronic acid"],
                "verified_size": "30ml",
                "verified_price": "R$89,90",
                "provenance": "owner_provided",
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert body["verified_description"] == "A lightweight rice-bran serum for daily hydration."
        assert body["verified_ingredients"] == ["Rice bran extract", "Hyaluronic acid"]
        assert body["verified_size"] == "30ml"
        assert body["verified_price"] == "R$89,90"

        r = client.get(f"/api/products/{product_id}/verified-facts")
        assert r.status_code == 200
        assert r.json()["verified_description"] == "A lightweight rice-bran serum for daily hydration."


def test_verified_product_facts_provenance_preserved(temp_db):
    """Test 2: `provenance` round-trips exactly as set, and defaults sensibly
    ("unverified") before anything has been entered at all.
    """
    with _client(temp_db) as client:
        _, _, product_id = _make_brand_and_product(client)

        assert client.get(f"/api/products/{product_id}/verified-facts").json()["provenance"] == "unverified"

        r = client.put(f"/api/products/{product_id}/verified-facts", json={"provenance": "brand_website"})
        assert r.status_code == 200
        assert r.json()["provenance"] == "brand_website"
        assert client.get(f"/api/products/{product_id}/verified-facts").json()["provenance"] == "brand_website"


def test_verified_product_facts_unsupported_fields_stay_unavailable(temp_db):
    """Test 3: a field nobody has entered is never invented — it stays empty
    (`""`/`[]`) AND is named in `missing_information`, rather than silently
    omitted or guessed at.
    """
    with _client(temp_db) as client:
        _, _, product_id = _make_brand_and_product(client)

        client.put(f"/api/products/{product_id}/verified-facts", json={"verified_description": "Rice-based serum."})

        body = client.get(f"/api/products/{product_id}/verified-facts").json()
        assert body["verified_description"] == "Rice-based serum."
        assert body["verified_price"] == ""
        assert body["verified_ingredients"] == []
        assert "verified_price" in body["missing_information"]
        assert "verified_ingredients" in body["missing_information"]
        assert "verified_description" not in body["missing_information"]


def test_platform_capabilities_endpoint_lists_languages_and_all_seven_platforms(temp_db):
    """Supporting check for Parts B/C: the config endpoint the frontend reads to
    build its language/platform pickers actually exposes both supported
    languages and all seven documented platforms (never just Instagram).
    """
    with _client(temp_db) as client:
        r = client.get("/api/campaigns/config/platform-capabilities")
        assert r.status_code == 200
        body = r.json()
        assert set(body["languages"]) == {"pt-BR", "en"}
        platform_keys = {p["key"] for p in body["platforms"]}
        assert platform_keys == {
            "instagram", "facebook", "tiktok", "youtube_shorts", "pinterest", "linkedin", "x",
        }
        facebook = next(p for p in body["platforms"] if p["key"] == "facebook")
        assert facebook["copy_notes"]  # real guidance text, not a stub


def test_campaign_create_accepts_pt_br_language(temp_db):
    """Test 4: pt-BR is a selectable campaign language."""
    with _client(temp_db) as client:
        brand_id, category_id, _ = _make_brand_and_product(client)
        r = client.post(
            "/api/campaigns",
            json={"brand_id": brand_id, "category_id": category_id, "languages": ["pt-BR"]},
        )
        assert r.status_code == 201
        campaign_id = r.json()["id"]
        detail = client.get(f"/api/campaigns/{campaign_id}").json()
        assert detail["languages"] == ["pt-BR"]


def test_campaign_create_accepts_en_language(temp_db):
    """Test 5: en is a selectable campaign language."""
    with _client(temp_db) as client:
        brand_id, category_id, _ = _make_brand_and_product(client)
        r = client.post(
            "/api/campaigns",
            json={"brand_id": brand_id, "category_id": category_id, "languages": ["en"]},
        )
        assert r.status_code == 201
        detail = client.get(f"/api/campaigns/{r.json()['id']}").json()
        assert detail["languages"] == ["en"]


def test_campaign_create_accepts_both_languages_together(temp_db):
    """Test 6: both languages can be selected on the same campaign."""
    with _client(temp_db) as client:
        brand_id, category_id, _ = _make_brand_and_product(client)
        r = client.post(
            "/api/campaigns",
            json={"brand_id": brand_id, "category_id": category_id, "languages": ["pt-BR", "en"]},
        )
        assert r.status_code == 201
        detail = client.get(f"/api/campaigns/{r.json()['id']}").json()
        assert detail["languages"] == ["pt-BR", "en"]


def test_campaign_create_rejects_unknown_language(temp_db):
    with _client(temp_db) as client:
        brand_id, category_id, _ = _make_brand_and_product(client)
        r = client.post(
            "/api/campaigns",
            json={"brand_id": brand_id, "category_id": category_id, "languages": ["es"]},
        )
        assert r.status_code == 400


def test_campaign_create_and_update_platform_targets_structurally(temp_db):
    """Test 7: target platforms are selectable structurally (a real validated
    list field), not inferred from free text — and can be edited post-creation.
    """
    with _client(temp_db) as client:
        brand_id, category_id, _ = _make_brand_and_product(client)
        r = client.post(
            "/api/campaigns",
            json={"brand_id": brand_id, "category_id": category_id, "target_platforms": ["facebook", "tiktok"]},
        )
        assert r.status_code == 201
        campaign_id = r.json()["id"]
        detail = client.get(f"/api/campaigns/{campaign_id}").json()
        assert detail["target_platforms"] == ["facebook", "tiktok"]

        r = client.patch(f"/api/campaigns/{campaign_id}", json={"target_platforms": ["pinterest"]})
        assert r.status_code == 200
        assert client.get(f"/api/campaigns/{campaign_id}").json()["target_platforms"] == ["pinterest"]

        r = client.patch(f"/api/campaigns/{campaign_id}", json={"target_platforms": ["not_a_real_platform"]})
        assert r.status_code == 400


def test_campaign_create_default_is_not_silently_instagram_only_forever(temp_db):
    """Test 8: Instagram is no longer assumed globally — a campaign that never
    mentions Instagram at all (only Facebook/LinkedIn) is created and persisted
    exactly as selected, never silently coerced back to Instagram.
    """
    with _client(temp_db) as client:
        brand_id, category_id, _ = _make_brand_and_product(client)
        r = client.post(
            "/api/campaigns",
            json={"brand_id": brand_id, "category_id": category_id, "target_platforms": ["linkedin"]},
        )
        assert r.status_code == 201
        detail = client.get(f"/api/campaigns/{r.json()['id']}").json()
        assert detail["target_platforms"] == ["linkedin"]
        assert "instagram" not in detail["target_platforms"]


def test_campaign_generate_endpoint_recreate_with_ai_defaults_to_false(temp_db):
    """Test 9 (API-layer half): `POST /generate`'s `recreate_with_ai` query
    parameter itself now defaults to false — inspected directly off the FastAPI
    route signature rather than exercised end-to-end (the end-to-end version is
    `test_campaign_generate_endpoint_end_to_end_with_fake_provider` in
    test_api.py, which already runs with no image provider configured at all —
    only possible because recreation isn't attempted by default).
    """
    import inspect

    from app.api.campaigns import generate_campaign

    sig = inspect.signature(generate_campaign)
    assert sig.parameters["recreate_with_ai"].default is False
