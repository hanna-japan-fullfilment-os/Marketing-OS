from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from app.services.product_asset_selection import (
    choose_approved_product_master,
)
from app.services.product_master_contract import (
    APPROVED_PRODUCT_MASTER_ROLE,
    PRODUCT_MASTER_CONTRACT_VERSION,
)


SOURCE_SHA = (
    "94e7fb1436596f0566ddf0b83359cfff"
    "1c402bd36fc7435c5067243de1a591cb"
)


def source_asset():
    return SimpleNamespace(
        id="source-1",
        brand_id="brand-1",
        product_id="product-1",
        sha256=SOURCE_SHA,
        image_role="product",
        is_active=True,
        ai_metadata={
            "ai_generated": False,
        },
    )


def approved_master():
    return SimpleNamespace(
        id="master-1",
        brand_id="brand-1",
        product_id="product-1",
        sha256="b" * 64,
        image_role=APPROVED_PRODUCT_MASTER_ROLE,
        is_active=True,
        ai_metadata={
            "ai_generated": True,
            "product_master_contract_version":
                PRODUCT_MASTER_CONTRACT_VERSION,
            "asset_class":
                "reconstructed_product_master",
            "source_asset_id":
                "source-1",
            "source_sha256":
                SOURCE_SHA,
            "full_product_recreation":
                False,
            "identity_preservation_required":
                True,
            "campaign_time_immutable":
                True,
            "reconstruction_operations": [
                "background_removal",
                "localized_occlusion_reconstruction",
                "light_decrumpling",
            ],
            "product_fidelity": {
                "overall_verdict": "PASS",
                "package_shape": "match",
                "proportions": "match",
                "brand_logo": "match",
                "label_structure": "match",
                "visible_text": "match",
                "cap_or_closure": "match",
                "color": "match",
            },
            "human_review": {
                "status": "APPROVED",
                "authority": "owner",
                "reviewed_at":
                    "2026-09-19T18:00:00+09:00",
            },
        },
    )


def test_eligible_master_is_selected():
    source = source_asset()
    master = approved_master()

    selected = choose_approved_product_master(
        [master],
        source_lookup=lambda asset_id: (
            source
            if asset_id == source.id
            else None
        ),
    )

    assert selected is master


def test_missing_source_fails_closed():
    master = approved_master()

    selected = choose_approved_product_master(
        [master],
        source_lookup=lambda _asset_id: None,
    )

    assert selected is None


def test_unapproved_master_is_rejected():
    source = source_asset()
    master = approved_master()

    master.ai_metadata[
        "human_review"
    ]["status"] = "PENDING"

    selected = choose_approved_product_master(
        [master],
        source_lookup=lambda _asset_id: source,
    )

    assert selected is None


def test_text_fidelity_failure_blocks_master():
    source = source_asset()
    master = approved_master()

    master.ai_metadata[
        "product_fidelity"
    ]["visible_text"] = "mismatch"

    selected = choose_approved_product_master(
        [master],
        source_lookup=lambda _asset_id: source,
    )

    assert selected is None


def test_cross_product_master_is_rejected():
    source = source_asset()
    master = approved_master()

    master.product_id = "different-product"

    selected = choose_approved_product_master(
        [master],
        source_lookup=lambda _asset_id: source,
    )

    assert selected is None


def test_valid_master_can_follow_invalid_master():
    source = source_asset()

    invalid = approved_master()
    invalid.id = "invalid"
    invalid.ai_metadata[
        "human_review"
    ]["status"] = "PENDING"

    valid = approved_master()
    valid.id = "valid"

    selected = choose_approved_product_master(
        [
            invalid,
            valid,
        ],
        source_lookup=lambda _asset_id: source,
    )

    assert selected is valid


def test_orchestrator_separates_source_and_render_selection():
    text = Path(
        "app/services/orchestrator.py"
    ).read_text(
        encoding="utf-8"
    )

    assert (
        text.count(
            "candidate_assets = _select_candidate_assets("
        )
        == 1
    )

    assert (
        text.count(
            "per_product = _select_render_assets("
        )
        == 2
    )

    assert (
        text.count(
            "candidate_assets = _select_render_assets("
        )
        == 2
    )


def test_qa_keeps_canonical_source_authority():
    text = Path(
        "app/services/qa_engine.py"
    ).read_text(
        encoding="utf-8"
    )

    helper_start = text.index(
        "def _slide_assets_for_variant("
    )

    helper_end = text.index(
        "async def _regenerate_variant_render(",
        helper_start,
    )

    helper = text[
        helper_start:helper_end
    ]

    assert (
        helper.count(
            "_select_render_assets("
        )
        == 2
    )

    source_start = text.index(
        "source_product_image_path: Path | None = None"
    )

    attempt_start = text.index(
        "for attempt in range(",
        source_start,
    )

    source_block = text[
        source_start:attempt_start
    ]

    assert (
        "_select_candidate_assets("
        in source_block
    )

    assert (
        "_select_render_assets("
        not in source_block
    )
