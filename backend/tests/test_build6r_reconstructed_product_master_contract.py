from __future__ import annotations

from types import SimpleNamespace

from app.services.product_master_contract import (
    APPROVED_PRODUCT_MASTER_ROLE,
    HUMAN_VERIFIED_FULL_RECONSTRUCTION_CLASS,
    PRODUCT_MASTER_CONTRACT_VERSION,
    evaluate_reconstructed_product_master,
    is_approved_reconstructed_product_master,
)


SOURCE_SHA = (
    "94e7fb1436596f0566ddf0b83359cfff"
    "1c402bd36fc7435c5067243de1a591cb"
)


def source_asset():
    return SimpleNamespace(
        id="source-asset-1",
        brand_id="brand-1",
        product_id="product-1",
        sha256=SOURCE_SHA,
        image_role="product",
        is_active=True,
        ai_metadata={
            "ai_generated": False,
            "source_type": "owner_real_store_photo",
        },
    )


def approved_candidate():
    return SimpleNamespace(
        id="candidate-1",
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
                "source-asset-1",
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
                "notes":
                    "Premium but still believable.",
            },
        },
    )


def test_approved_localized_reconstruction_is_eligible():
    result = evaluate_reconstructed_product_master(
        candidate=approved_candidate(),
        source=source_asset(),
    )

    assert result.eligible is True
    assert result.hard_fails == ()
    assert (
        is_approved_reconstructed_product_master(
            candidate=approved_candidate(),
            source=source_asset(),
        )
        is True
    )


def test_owner_approval_is_mandatory():
    candidate = approved_candidate()

    candidate.ai_metadata[
        "human_review"
    ]["status"] = "PENDING"

    result = evaluate_reconstructed_product_master(
        candidate=candidate,
        source=source_asset(),
    )

    assert result.eligible is False
    assert (
        "owner_approval_required"
        in result.hard_fails
    )


def test_ai_qa_pass_does_not_override_owner_review():
    candidate = approved_candidate()

    candidate.ai_metadata[
        "human_review"
    ] = {}

    assert (
        evaluate_reconstructed_product_master(
            candidate=candidate,
            source=source_asset(),
        ).eligible
        is False
    )


def test_visible_text_mismatch_fails_closed():
    candidate = approved_candidate()

    candidate.ai_metadata[
        "product_fidelity"
    ]["visible_text"] = "mismatch"

    result = evaluate_reconstructed_product_master(
        candidate=candidate,
        source=source_asset(),
    )

    assert result.eligible is False
    assert (
        "product_fidelity_visible_text_not_match"
        in result.hard_fails
    )


def test_uncertain_logo_fails_closed():
    candidate = approved_candidate()

    candidate.ai_metadata[
        "product_fidelity"
    ]["brand_logo"] = "uncertain"

    result = evaluate_reconstructed_product_master(
        candidate=candidate,
        source=source_asset(),
    )

    assert result.eligible is False
    assert (
        "product_fidelity_brand_logo_not_match"
        in result.hard_fails
    )


def test_full_product_recreation_is_prohibited():
    candidate = approved_candidate()

    candidate.ai_metadata[
        "full_product_recreation"
    ] = True

    result = evaluate_reconstructed_product_master(
        candidate=candidate,
        source=source_asset(),
    )

    assert result.eligible is False
    assert (
        "full_product_recreation_prohibited"
        in result.hard_fails
    )


def test_unknown_reconstruction_operation_fails():
    candidate = approved_candidate()

    candidate.ai_metadata[
        "reconstruction_operations"
    ].append(
        "complete_package_redesign"
    )

    result = evaluate_reconstructed_product_master(
        candidate=candidate,
        source=source_asset(),
    )

    assert result.eligible is False
    assert any(
        failure.startswith(
            "unsupported_reconstruction_operation:"
        )
        for failure in result.hard_fails
    )


def test_cross_product_master_is_rejected():
    candidate = approved_candidate()

    candidate.product_id = "other-product"

    result = evaluate_reconstructed_product_master(
        candidate=candidate,
        source=source_asset(),
    )

    assert result.eligible is False
    assert (
        "product_mismatch"
        in result.hard_fails
    )


def test_source_hash_lineage_must_match():
    candidate = approved_candidate()

    candidate.ai_metadata[
        "source_sha256"
    ] = "0" * 64

    result = evaluate_reconstructed_product_master(
        candidate=candidate,
        source=source_asset(),
    )

    assert result.eligible is False
    assert (
        "source_sha256_link_mismatch"
        in result.hard_fails
    )


def test_campaign_time_immutability_is_required():
    candidate = approved_candidate()

    candidate.ai_metadata[
        "campaign_time_immutable"
    ] = False

    result = evaluate_reconstructed_product_master(
        candidate=candidate,
        source=source_asset(),
    )

    assert result.eligible is False
    assert (
        "campaign_time_immutability_missing"
        in result.hard_fails
    )


def test_inactive_candidate_is_not_production_eligible():
    candidate = approved_candidate()

    candidate.is_active = False

    result = evaluate_reconstructed_product_master(
        candidate=candidate,
        source=source_asset(),
    )

    assert result.eligible is False
    assert (
        "candidate_not_active"
        in result.hard_fails
    )


def test_source_must_remain_verified_non_ai_authority():
    source = source_asset()

    source.ai_metadata[
        "ai_generated"
    ] = True

    result = evaluate_reconstructed_product_master(
        candidate=approved_candidate(),
        source=source,
    )

    assert result.eligible is False
    assert (
        "source_not_verified_non_ai"
        in result.hard_fails
    )


def human_verified_full_reconstruction_candidate():
    candidate = approved_candidate()

    candidate.sha256 = (
        "747df22f2a227a5705f2fff9a831f9a3"
        "34ec17f1973953ccd9f86d17216992bc"
    )

    candidate.ai_metadata[
        "asset_class"
    ] = HUMAN_VERIFIED_FULL_RECONSTRUCTION_CLASS

    candidate.ai_metadata[
        "full_product_recreation"
    ] = True

    candidate.ai_metadata[
        "reconstruction_operations"
    ] = [
        "full_product_reconstruction",
    ]

    candidate.ai_metadata[
        "full_reconstruction_exception"
    ] = {
        "status":
            "APPROVED",

        "authority":
            "owner",

        "approved_sha256":
            candidate.sha256,

        "source_fidelity_authority":
            "canonical_real_product_photo",

        "fidelity_verification_method":
            "owner_visual_review_against_canonical_source",

        "exact_variant_status":
            "VERIFIED",

        "exact_variant_authority":
            "official_manufacturer_page",

        "exact_variant":
            "LuLuLun Hydra EX Mask 7 Sheets / 150 mL",
    }

    return candidate


def test_human_verified_full_reconstruction_can_pass():
    candidate = (
        human_verified_full_reconstruction_candidate()
    )

    result = evaluate_reconstructed_product_master(
        candidate=candidate,
        source=source_asset(),
    )

    assert result.eligible is True
    assert result.hard_fails == ()


def test_regular_class_still_prohibits_full_product_recreation():
    candidate = approved_candidate()

    candidate.ai_metadata[
        "full_product_recreation"
    ] = True

    candidate.ai_metadata[
        "reconstruction_operations"
    ] = [
        "full_product_reconstruction",
    ]

    result = evaluate_reconstructed_product_master(
        candidate=candidate,
        source=source_asset(),
    )

    assert result.eligible is False
    assert (
        "full_product_recreation_prohibited"
        in result.hard_fails
    )


def test_full_reconstruction_is_bound_to_exact_owner_approved_sha():
    candidate = (
        human_verified_full_reconstruction_candidate()
    )

    candidate.ai_metadata[
        "full_reconstruction_exception"
    ][
        "approved_sha256"
    ] = "0" * 64

    result = evaluate_reconstructed_product_master(
        candidate=candidate,
        source=source_asset(),
    )

    assert result.eligible is False
    assert (
        "full_reconstruction_approved_sha256_mismatch"
        in result.hard_fails
    )


def test_full_reconstruction_requires_verified_exact_variant():
    candidate = (
        human_verified_full_reconstruction_candidate()
    )

    candidate.ai_metadata[
        "full_reconstruction_exception"
    ][
        "exact_variant_status"
    ] = "UNRESOLVED"

    result = evaluate_reconstructed_product_master(
        candidate=candidate,
        source=source_asset(),
    )

    assert result.eligible is False
    assert (
        "full_reconstruction_exact_variant_not_verified"
        in result.hard_fails
    )


def test_full_reconstruction_requires_canonical_source_review_method():
    candidate = (
        human_verified_full_reconstruction_candidate()
    )

    candidate.ai_metadata[
        "full_reconstruction_exception"
    ][
        "fidelity_verification_method"
    ] = "self_comparison"

    result = evaluate_reconstructed_product_master(
        candidate=candidate,
        source=source_asset(),
    )

    assert result.eligible is False
    assert (
        "full_reconstruction_fidelity_method_invalid"
        in result.hard_fails
    )


def test_full_reconstruction_class_cannot_hide_false_recreation_flag():
    candidate = (
        human_verified_full_reconstruction_candidate()
    )

    candidate.ai_metadata[
        "full_product_recreation"
    ] = False

    candidate.ai_metadata[
        "reconstruction_operations"
    ] = [
        "background_removal",
    ]

    result = evaluate_reconstructed_product_master(
        candidate=candidate,
        source=source_asset(),
    )

    assert result.eligible is False
    assert (
        "full_reconstruction_class_requires_full_product_recreation"
        in result.hard_fails
    )

