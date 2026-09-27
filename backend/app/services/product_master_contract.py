"""Build 6R / Stage 3D ? reconstructed product-master acceptance contract.

This module does NOT generate or alter images.

Its only responsibility is to decide whether a product-specific derived image
is eligible to become a reusable, owner-approved product master.

Important architectural distinction:

- The canonical real product photo remains the factual/provenance authority.
- A reconstructed product master may use tightly-scoped restoration before
  campaign creation (for example removing a hanger occlusion or reducing
  distracting pouch wrinkles).
- Full product reconstruction remains prohibited by default; a separate human-verified class may pass only when its immutable SHA, canonical-source fidelity review, owner approval, and exact variant are explicitly verified.
- Human approval is mandatory.
- Once approved, the reconstructed product master becomes immutable INPUT to
  the campaign renderer. Campaign-time AI product recreation remains prohibited.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


PRODUCT_MASTER_CONTRACT_VERSION = (
    "build6r-reconstructed-product-master-v2"
)

SOURCE_PRODUCT_ROLE = "product"

CANDIDATE_PRODUCT_MASTER_ROLE = (
    "product_master_candidate"
)

APPROVED_PRODUCT_MASTER_ROLE = (
    "product_master_approved"
)

RECONSTRUCTED_PRODUCT_MASTER_CLASS = (
    "reconstructed_product_master"
)

HUMAN_VERIFIED_FULL_RECONSTRUCTION_CLASS = (
    "human_verified_full_reconstruction_product_master"
)

ALLOWED_RECONSTRUCTION_OPERATIONS = frozenset(
    {
        "background_removal",
        "localized_occlusion_reconstruction",
        "light_decrumpling",
        "perspective_cleanup",
        "edge_cleanup",
        "full_product_reconstruction",
    }
)

REQUIRED_FIDELITY_MATCHES = (
    "package_shape",
    "proportions",
    "brand_logo",
    "label_structure",
    "visible_text",
    "cap_or_closure",
    "color",
)


@dataclass(frozen=True)
class ProductMasterContractResult:
    eligible: bool
    hard_fails: tuple[str, ...]
    contract_version: str = PRODUCT_MASTER_CONTRACT_VERSION

    def to_dict(self) -> dict[str, object]:
        return {
            "eligible": self.eligible,
            "hard_fails": list(self.hard_fails),
            "contract_version": self.contract_version,
        }


def _metadata(asset: Any) -> dict:
    value = getattr(
        asset,
        "ai_metadata",
        None,
    )

    return (
        dict(value)
        if isinstance(value, dict)
        else {}
    )


def _text(value: object) -> str:
    return str(
        value or ""
    ).strip()


def evaluate_reconstructed_product_master(
    *,
    candidate: Any,
    source: Any,
) -> ProductMasterContractResult:
    """Fail-closed eligibility decision for one reconstructed product master."""

    failures: list[str] = []

    source_meta = _metadata(
        source
    )

    candidate_meta = _metadata(
        candidate
    )

    if not _text(
        getattr(
            source,
            "id",
            "",
        )
    ):
        failures.append(
            "source_asset_id_missing"
        )

    if (
        _text(
            getattr(
                source,
                "brand_id",
                "",
            )
        )
        !=
        _text(
            getattr(
                candidate,
                "brand_id",
                "",
            )
        )
    ):
        failures.append(
            "brand_mismatch"
        )

    if (
        _text(
            getattr(
                source,
                "product_id",
                "",
            )
        )
        !=
        _text(
            getattr(
                candidate,
                "product_id",
                "",
            )
        )
    ):
        failures.append(
            "product_mismatch"
        )

    source_sha = _text(
        getattr(
            source,
            "sha256",
            "",
        )
    )

    candidate_sha = _text(
        getattr(
            candidate,
            "sha256",
            "",
        )
    )

    if not source_sha:
        failures.append(
            "source_sha256_missing"
        )

    if not candidate_sha:
        failures.append(
            "candidate_sha256_missing"
        )

    if (
        source_sha
        and candidate_sha
        and source_sha == candidate_sha
    ):
        failures.append(
            "candidate_not_distinct_from_source"
        )

    if (
        getattr(
            source,
            "image_role",
            "",
        )
        != SOURCE_PRODUCT_ROLE
    ):
        failures.append(
            "source_not_canonical_product_role"
        )

    if (
        source_meta.get(
            "ai_generated"
        )
        is not False
    ):
        failures.append(
            "source_not_verified_non_ai"
        )

    if (
        candidate_meta.get(
            "product_master_contract_version"
        )
        != PRODUCT_MASTER_CONTRACT_VERSION
    ):
        failures.append(
            "contract_version_mismatch"
        )

    asset_class = candidate_meta.get(
        "asset_class"
    )

    if asset_class not in {
        RECONSTRUCTED_PRODUCT_MASTER_CLASS,
        HUMAN_VERIFIED_FULL_RECONSTRUCTION_CLASS,
    }:
        failures.append(
            "asset_class_invalid"
        )

    if (
        _text(
            candidate_meta.get(
                "source_asset_id"
            )
        )
        !=
        _text(
            getattr(
                source,
                "id",
                "",
            )
        )
    ):
        failures.append(
            "source_asset_link_mismatch"
        )

    if (
        _text(
            candidate_meta.get(
                "source_sha256"
            )
        )
        != source_sha
    ):
        failures.append(
            "source_sha256_link_mismatch"
        )

    full_product_recreation = candidate_meta.get(
        "full_product_recreation"
    )

    is_human_verified_full_reconstruction = (
        asset_class
        == HUMAN_VERIFIED_FULL_RECONSTRUCTION_CLASS
        and full_product_recreation is True
    )

    if full_product_recreation is True:

        if (
            asset_class
            != HUMAN_VERIFIED_FULL_RECONSTRUCTION_CLASS
        ):
            failures.append(
                "full_product_recreation_prohibited"
            )

        else:
            exception = candidate_meta.get(
                "full_reconstruction_exception",
                {},
            )

            if not isinstance(
                exception,
                dict,
            ):
                failures.append(
                    "full_reconstruction_exception_invalid"
                )

                exception = {}

            if (
                candidate_meta.get(
                    "ai_generated"
                )
                is not True
            ):
                failures.append(
                    "full_reconstruction_ai_provenance_missing"
                )

            if (
                exception.get(
                    "status"
                )
                != "APPROVED"
            ):
                failures.append(
                    "full_reconstruction_exception_not_approved"
                )

            if (
                exception.get(
                    "authority"
                )
                != "owner"
            ):
                failures.append(
                    "full_reconstruction_owner_authority_missing"
                )

            if (
                _text(
                    exception.get(
                        "approved_sha256"
                    )
                )
                != candidate_sha
            ):
                failures.append(
                    "full_reconstruction_approved_sha256_mismatch"
                )

            if (
                exception.get(
                    "source_fidelity_authority"
                )
                != "canonical_real_product_photo"
            ):
                failures.append(
                    "full_reconstruction_source_authority_invalid"
                )

            if (
                exception.get(
                    "fidelity_verification_method"
                )
                != "owner_visual_review_against_canonical_source"
            ):
                failures.append(
                    "full_reconstruction_fidelity_method_invalid"
                )

            if (
                exception.get(
                    "exact_variant_status"
                )
                != "VERIFIED"
            ):
                failures.append(
                    "full_reconstruction_exact_variant_not_verified"
                )

            if (
                exception.get(
                    "exact_variant_authority"
                )
                != "official_manufacturer_page"
            ):
                failures.append(
                    "full_reconstruction_variant_authority_invalid"
                )

            if not _text(
                exception.get(
                    "exact_variant"
                )
            ):
                failures.append(
                    "full_reconstruction_exact_variant_missing"
                )

    elif full_product_recreation is False:

        if (
            asset_class
            == HUMAN_VERIFIED_FULL_RECONSTRUCTION_CLASS
        ):
            failures.append(
                "full_reconstruction_class_requires_full_product_recreation"
            )

    else:
        failures.append(
            "full_product_recreation_flag_invalid"
        )

    if (
        candidate_meta.get(
            "identity_preservation_required"
        )
        is not True
    ):
        failures.append(
            "identity_preservation_not_required"
        )

    if (
        candidate_meta.get(
            "campaign_time_immutable"
        )
        is not True
    ):
        failures.append(
            "campaign_time_immutability_missing"
        )

    operations_raw = candidate_meta.get(
        "reconstruction_operations",
        [],
    )

    if not isinstance(
        operations_raw,
        list,
    ):
        failures.append(
            "reconstruction_operations_invalid"
        )

        operations: set[str] = set()

    else:
        operations = {
            _text(value)
            for value in operations_raw
            if _text(value)
        }

    if not operations:
        failures.append(
            "reconstruction_operations_missing"
        )

    unknown_operations = (
        operations
        - ALLOWED_RECONSTRUCTION_OPERATIONS
    )

    if unknown_operations:
        failures.append(
            "unsupported_reconstruction_operation:"
            + ",".join(
                sorted(
                    unknown_operations
                )
            )
        )

    if is_human_verified_full_reconstruction:

        if (
            "full_product_reconstruction"
            not in operations
        ):
            failures.append(
                "full_reconstruction_operation_missing"
            )

    elif (
        "full_product_reconstruction"
        in operations
    ):
        failures.append(
            "full_reconstruction_operation_not_allowed"
        )

    fidelity = candidate_meta.get(
        "product_fidelity",
        {},
    )

    if not isinstance(
        fidelity,
        dict,
    ):
        failures.append(
            "product_fidelity_invalid"
        )

        fidelity = {}

    if (
        fidelity.get(
            "overall_verdict"
        )
        != "PASS"
    ):
        failures.append(
            "product_fidelity_not_pass"
        )

    for field_name in REQUIRED_FIDELITY_MATCHES:

        if (
            fidelity.get(
                field_name
            )
            != "match"
        ):
            failures.append(
                "product_fidelity_"
                + field_name
                + "_not_match"
            )

    human_review = candidate_meta.get(
        "human_review",
        {},
    )

    if not isinstance(
        human_review,
        dict,
    ):
        failures.append(
            "human_review_invalid"
        )

        human_review = {}

    if (
        human_review.get(
            "status"
        )
        != "APPROVED"
    ):
        failures.append(
            "owner_approval_required"
        )

    if (
        human_review.get(
            "authority"
        )
        != "owner"
    ):
        failures.append(
            "owner_approval_authority_missing"
        )

    if not _text(
        human_review.get(
            "reviewed_at"
        )
    ):
        failures.append(
            "owner_approval_timestamp_missing"
        )

    if (
        getattr(
            candidate,
            "image_role",
            "",
        )
        != APPROVED_PRODUCT_MASTER_ROLE
    ):
        failures.append(
            "candidate_role_not_approved_master"
        )

    if (
        getattr(
            candidate,
            "is_active",
            False
        )
        is not True
    ):
        failures.append(
            "candidate_not_active"
        )

    return ProductMasterContractResult(
        eligible=not failures,
        hard_fails=tuple(
            failures
        ),
    )


def is_approved_reconstructed_product_master(
    *,
    candidate: Any,
    source: Any,
) -> bool:
    return evaluate_reconstructed_product_master(
        candidate=candidate,
        source=source,
    ).eligible
