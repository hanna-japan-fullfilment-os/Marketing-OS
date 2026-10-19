"""Fail-closed research -> verified-claim promotion boundary.

This service never treats ResearchInsight text as canonical product evidence by
itself.  Promotion requires one explicitly VERIFIED, marketing-eligible
ProductClaimEvidence row backed by real ResearchSource IDs.

The canonical VerifiedProductFact schema and claims_audit authority stay
unchanged: approved claim text is promoted as a plain string.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from ..models import (
    Product,
    ProductClaimEvidence,
    ResearchInsight,
    ResearchRun,
    ResearchSource,
    VerifiedProductFact,
)
from ..models.claim_evidence import (
    CLAIM_EVIDENCE_STRENGTHS,
    CLAIM_TYPES,
)
from ..schemas.claim_evidence import (
    ProductClaimEvidenceCreate,
    ProductClaimRejection,
    ProductClaimVerification,
)


SENSITIVE_MARKETING_CLAIM_TYPES = {
    "ranking",
    "award",
    "quantified_result",
    "certification",
}

STRONG_MARKETING_EVIDENCE = {
    "official_primary",
    "authoritative_third_party",
}


class ClaimEvidenceError(ValueError):
    """Fail-closed claim-evidence contract violation."""


def normalize_claim_text(
    value: str,
) -> str:
    text = unicodedata.normalize(
        "NFKC",
        str(value or ""),
    )

    text = re.sub(
        r"\s+",
        " ",
        text,
    ).strip()

    text = text.casefold()

    return text.rstrip(
        " .;:"
    )


def _required_text(
    value: str,
    *,
    field: str,
) -> str:
    result = str(
        value or ""
    ).strip()

    if not result:
        raise ClaimEvidenceError(
            f"{field} is required."
        )

    return result


def _unique_ids(
    values: list[str],
) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()

    for raw in values or []:
        value = str(
            raw or ""
        ).strip()

        if not value:
            continue

        if value in seen:
            continue

        seen.add(value)
        result.append(value)

    return result


def _utc_now() -> datetime:
    return datetime.now(
        timezone.utc
    )


def _as_utc(
    value: datetime,
) -> datetime:
    if value.tzinfo is None:
        return value.replace(
            tzinfo=timezone.utc
        )

    return value.astimezone(
        timezone.utc
    )


def _is_expired(
    value: datetime | None,
    *,
    now: datetime | None = None,
) -> bool:
    if value is None:
        return False

    check_now = (
        now
        or _utc_now()
    )

    return (
        _as_utc(value)
        <= _as_utc(check_now)
    )


def build_claim_key(
    *,
    claim_text: str,
    claim_type: str,
    territory: str = "",
    evidence_period: str = "",
) -> str:
    normalized = normalize_claim_text(
        claim_text
    )

    if not normalized:
        raise ClaimEvidenceError(
            "claim_text is required."
        )

    normalized_type = str(
        claim_type or ""
    ).strip().casefold()

    if normalized_type not in CLAIM_TYPES:
        raise ClaimEvidenceError(
            "Unsupported claim_type: "
            + normalized_type
        )

    payload = "\x1f".join(
        (
            normalized,
            normalized_type,
            normalize_claim_text(
                territory
            ),
            normalize_claim_text(
                evidence_period
            ),
        )
    )

    return hashlib.sha256(
        payload.encode("utf-8")
    ).hexdigest()


def _require_product(
    db: Session,
    product_id: str,
) -> Product:
    product = db.get(
        Product,
        product_id,
    )

    if product is None:
        raise ClaimEvidenceError(
            "Unknown product_id."
        )

    return product


def _require_research_run(
    db: Session,
    *,
    research_run_id: str,
    product_id: str,
) -> ResearchRun:
    run = db.get(
        ResearchRun,
        research_run_id,
    )

    if run is None:
        raise ClaimEvidenceError(
            "Unknown research_run_id."
        )

    if run.product_id != product_id:
        raise ClaimEvidenceError(
            "Research run is not scoped "
            "to the same product."
        )

    return run


def _require_insight(
    db: Session,
    *,
    research_insight_id: str | None,
    research_run_id: str,
) -> ResearchInsight | None:
    if not research_insight_id:
        return None

    insight = db.get(
        ResearchInsight,
        research_insight_id,
    )

    if insight is None:
        raise ClaimEvidenceError(
            "Unknown research_insight_id."
        )

    if (
        insight.research_run_id
        != research_run_id
    ):
        raise ClaimEvidenceError(
            "Research insight belongs to "
            "a different research run."
        )

    return insight


def _validate_sources(
    db: Session,
    *,
    research_run_id: str,
    research_insight: ResearchInsight | None,
    source_ids: list[str],
) -> list[str]:
    normalized_ids = _unique_ids(
        source_ids
    )

    if not normalized_ids:
        raise ClaimEvidenceError(
            "At least one research source "
            "is required."
        )

    rows = (
        db.query(
            ResearchSource
        )
        .filter(
            ResearchSource.id.in_(
                normalized_ids
            )
        )
        .all()
    )

    by_id = {
        row.id: row
        for row in rows
    }

    missing = [
        source_id
        for source_id
        in normalized_ids
        if source_id not in by_id
    ]

    if missing:
        raise ClaimEvidenceError(
            "Unknown research source ID(s): "
            + ", ".join(missing)
        )

    wrong_run = [
        source_id
        for source_id
        in normalized_ids
        if (
            by_id[source_id].research_run_id
            != research_run_id
        )
    ]

    if wrong_run:
        raise ClaimEvidenceError(
            "Research source belongs to "
            "a different research run."
        )

    if research_insight is not None:
        insight_sources = set(
            str(value)
            for value
            in (
                research_insight.source_ids
                or []
            )
        )

        outside_insight = [
            source_id
            for source_id
            in normalized_ids
            if source_id
            not in insight_sources
        ]

        if outside_insight:
            raise ClaimEvidenceError(
                "Source is not cited by the "
                "linked research insight."
            )

    return normalized_ids


def _validate_source_scope(
    source_scope: dict,
) -> dict:
    scope = dict(
        source_scope
        or {}
    )

    if (
        scope.get(
            "exact_product_match"
        )
        is not True
    ):
        raise ClaimEvidenceError(
            "source_scope.exact_product_match "
            "must be true before verification."
        )

    if (
        scope.get(
            "claim_supported"
        )
        is not True
    ):
        raise ClaimEvidenceError(
            "source_scope.claim_supported "
            "must be true before verification."
        )

    return scope


def _validate_marketing_values(
    *,
    claim_type: str,
    marketing_eligible: bool,
    evidence_strength: str,
    evidence_period: str,
    footnote: str,
    territory: str,
) -> None:
    if not marketing_eligible:
        return

    if (
        claim_type
        in SENSITIVE_MARKETING_CLAIM_TYPES
    ):
        if (
            evidence_strength
            not in STRONG_MARKETING_EVIDENCE
        ):
            raise ClaimEvidenceError(
                "Sensitive marketing claims "
                "require official_primary or "
                "authoritative_third_party evidence."
            )

        if not str(
            evidence_period
            or ""
        ).strip():
            raise ClaimEvidenceError(
                "Sensitive marketing claims "
                "require an evidence_period."
            )

        if not str(
            footnote
            or ""
        ).strip():
            raise ClaimEvidenceError(
                "Sensitive marketing claims "
                "require a footnote."
            )

    if (
        claim_type
        in {
            "ranking",
            "award",
        }
        and not str(
            territory
            or ""
        ).strip()
    ):
        raise ClaimEvidenceError(
            "Ranking/award claims require "
            "an explicit territory."
        )


def _validate_marketing_evidence(
    evidence: ProductClaimEvidence,
) -> None:
    _validate_marketing_values(
        claim_type=evidence.claim_type,
        marketing_eligible=evidence.marketing_eligible,
        evidence_strength=evidence.evidence_strength,
        evidence_period=evidence.evidence_period,
        footnote=evidence.footnote,
        territory=evidence.territory,
    )


def create_claim_candidate(
    db: Session,
    payload: ProductClaimEvidenceCreate,
) -> ProductClaimEvidence:
    product_id = _required_text(
        payload.product_id,
        field="product_id",
    )

    _require_product(
        db,
        product_id,
    )

    research_run_id = _required_text(
        payload.research_run_id,
        field="research_run_id",
    )

    _require_research_run(
        db,
        research_run_id=research_run_id,
        product_id=product_id,
    )

    insight = _require_insight(
        db,
        research_insight_id=(
            payload.research_insight_id
        ),
        research_run_id=research_run_id,
    )

    claim_text = _required_text(
        payload.claim_text,
        field="claim_text",
    )

    claim_type = str(
        payload.claim_type
        or ""
    ).strip().casefold()

    if claim_type not in CLAIM_TYPES:
        raise ClaimEvidenceError(
            "Unsupported claim_type: "
            + claim_type
        )

    source_ids = _validate_sources(
        db,
        research_run_id=research_run_id,
        research_insight=insight,
        source_ids=payload.source_ids,
    )

    source_excerpt = _required_text(
        payload.source_excerpt,
        field="source_excerpt",
    )

    territory = str(
        payload.territory
        or ""
    ).strip()

    evidence_period = str(
        payload.evidence_period
        or ""
    ).strip()

    normalized_claim = (
        normalize_claim_text(
            claim_text
        )
    )

    claim_key = build_claim_key(
        claim_text=claim_text,
        claim_type=claim_type,
        territory=territory,
        evidence_period=evidence_period,
    )

    existing = (
        db.query(
            ProductClaimEvidence
        )
        .filter(
            ProductClaimEvidence.product_id
            == product_id,
            ProductClaimEvidence.claim_key
            == claim_key,
        )
        .one_or_none()
    )

    if existing is not None:
        return existing

    row = ProductClaimEvidence(
        product_id=product_id,
        research_run_id=research_run_id,
        research_insight_id=(
            payload.research_insight_id
        ),
        claim_key=claim_key,
        claim_text=claim_text,
        normalized_claim=normalized_claim,
        claim_type=claim_type,
        status="candidate",
        evidence_strength="",
        marketing_eligible=False,
        source_ids=source_ids,
        source_excerpt=source_excerpt,
        source_scope=dict(
            payload.source_scope
            or {}
        ),
        territory=territory,
        evidence_period=evidence_period,
    )

    db.add(row)
    db.flush()

    return row


def verify_claim_evidence(
    db: Session,
    claim_evidence_id: str,
    payload: ProductClaimVerification,
) -> ProductClaimEvidence:
    evidence = db.get(
        ProductClaimEvidence,
        claim_evidence_id,
    )

    if evidence is None:
        raise ClaimEvidenceError(
            "Unknown claim evidence ID."
        )

    if evidence.status != "candidate":
        raise ClaimEvidenceError(
            "Only candidate claims can "
            "transition to verified."
        )

    if not evidence.research_run_id:
        raise ClaimEvidenceError(
            "Research-linked verification "
            "requires research_run_id."
        )

    _require_research_run(
        db,
        research_run_id=(
            evidence.research_run_id
        ),
        product_id=evidence.product_id,
    )

    insight = _require_insight(
        db,
        research_insight_id=(
            evidence.research_insight_id
        ),
        research_run_id=(
            evidence.research_run_id
        ),
    )

    strength = str(
        payload.evidence_strength
        or ""
    ).strip().casefold()

    if (
        strength
        not in CLAIM_EVIDENCE_STRENGTHS
        or not strength
    ):
        raise ClaimEvidenceError(
            "Unsupported or empty "
            "evidence_strength."
        )

    source_ids = _validate_sources(
        db,
        research_run_id=(
            evidence.research_run_id
        ),
        research_insight=insight,
        source_ids=payload.source_ids,
    )

    excerpt = _required_text(
        payload.source_excerpt,
        field="source_excerpt",
    )

    scope = _validate_source_scope(
        payload.source_scope
    )

    method = _required_text(
        payload.verification_method,
        field="verification_method",
    )

    verifier = _required_text(
        payload.verifier,
        field="verifier",
    )

    if _is_expired(
        payload.expires_at
    ):
        raise ClaimEvidenceError(
            "Expired evidence cannot "
            "be verified."
        )

    marketing_eligible = bool(
        payload.marketing_eligible
    )

    footnote = str(
        payload.footnote
        or ""
    ).strip()

    # Validate the proposed verification before mutating the ORM row.
    # A rejected attempt therefore leaves the candidate clean even
    # when the caller catches ClaimEvidenceError without rollback.
    _validate_marketing_values(
        claim_type=evidence.claim_type,
        marketing_eligible=marketing_eligible,
        evidence_strength=strength,
        evidence_period=evidence.evidence_period,
        footnote=footnote,
        territory=evidence.territory,
    )

    evidence.evidence_strength = (
        strength
    )

    evidence.marketing_eligible = (
        marketing_eligible
    )

    evidence.source_ids = (
        source_ids
    )

    evidence.source_excerpt = (
        excerpt
    )

    evidence.source_scope = (
        scope
    )

    evidence.footnote = (
        footnote
    )

    evidence.verification_method = (
        method
    )

    evidence.verifier = (
        verifier
    )

    evidence.expires_at = (
        payload.expires_at
    )

    evidence.status = "verified"

    evidence.verified_at = (
        _utc_now()
    )

    db.flush()

    return evidence


def reject_claim_evidence(
    db: Session,
    claim_evidence_id: str,
    payload: ProductClaimRejection,
) -> ProductClaimEvidence:
    evidence = db.get(
        ProductClaimEvidence,
        claim_evidence_id,
    )

    if evidence is None:
        raise ClaimEvidenceError(
            "Unknown claim evidence ID."
        )

    if evidence.status != "candidate":
        raise ClaimEvidenceError(
            "Only candidate claims can "
            "transition to rejected."
        )

    reason = _required_text(
        payload.rejection_reason,
        field="rejection_reason",
    )

    verifier = _required_text(
        payload.verifier,
        field="verifier",
    )

    evidence.status = "rejected"
    evidence.marketing_eligible = False
    evidence.rejection_reason = reason
    evidence.verifier = verifier

    db.flush()

    return evidence


def promote_verified_claim(
    db: Session,
    claim_evidence_id: str,
) -> ProductClaimEvidence:
    evidence = db.get(
        ProductClaimEvidence,
        claim_evidence_id,
    )

    if evidence is None:
        raise ClaimEvidenceError(
            "Unknown claim evidence ID."
        )

    if evidence.status != "verified":
        raise ClaimEvidenceError(
            "Only VERIFIED claims may "
            "enter canonical verified_claims."
        )

    if not evidence.marketing_eligible:
        raise ClaimEvidenceError(
            "Claim is not marketing eligible."
        )

    if evidence.verified_at is None:
        raise ClaimEvidenceError(
            "Verified claim is missing "
            "verified_at."
        )

    if _is_expired(
        evidence.expires_at
    ):
        raise ClaimEvidenceError(
            "Expired evidence cannot "
            "be promoted."
        )

    _validate_source_scope(
        evidence.source_scope
    )

    if not _unique_ids(
        evidence.source_ids
    ):
        raise ClaimEvidenceError(
            "Verified claim has no "
            "research sources."
        )

    _required_text(
        evidence.source_excerpt,
        field="source_excerpt",
    )

    _validate_marketing_evidence(
        evidence
    )

    facts = (
        db.query(
            VerifiedProductFact
        )
        .filter(
            VerifiedProductFact.product_id
            == evidence.product_id
        )
        .one_or_none()
    )

    if facts is None:
        raise ClaimEvidenceError(
            "Canonical VerifiedProductFact "
            "row does not exist."
        )

    current_claims = list(
        facts.verified_claims
        or []
    )

    if not all(
        isinstance(value, str)
        for value in current_claims
    ):
        raise ClaimEvidenceError(
            "Existing verified_claims contract "
            "is not list[str]."
        )

    current_prohibited = list(
        facts.prohibited_claims
        or []
    )

    if not all(
        isinstance(value, str)
        for value in current_prohibited
    ):
        raise ClaimEvidenceError(
            "Existing prohibited_claims "
            "contract is not list[str]."
        )

    normalized_prohibited = {
        normalize_claim_text(value)
        for value
        in current_prohibited
    }

    if (
        evidence.normalized_claim
        in normalized_prohibited
    ):
        raise ClaimEvidenceError(
            "Claim is explicitly prohibited "
            "for this product."
        )

    normalized_existing = {
        normalize_claim_text(value)
        for value
        in current_claims
    }

    if (
        evidence.normalized_claim
        not in normalized_existing
    ):
        current_claims.append(
            evidence.claim_text
        )

        facts.verified_claims = (
            current_claims
        )

    source_references = list(
        facts.source_references
        or []
    )

    if not all(
        isinstance(value, str)
        for value in source_references
    ):
        raise ClaimEvidenceError(
            "Existing source_references "
            "contract is not list[str]."
        )

    marker = (
        "product_claim_evidence:"
        + evidence.id
    )

    if marker not in source_references:
        source_references.append(
            marker
        )

        facts.source_references = (
            source_references
        )

    if evidence.promoted_at is None:
        evidence.promoted_at = (
            _utc_now()
        )

    db.flush()

    return evidence


def list_verified_marketing_claims(
    db: Session,
    *,
    product_id: str,
) -> list[ProductClaimEvidence]:
    rows = (
        db.query(
            ProductClaimEvidence
        )
        .filter(
            ProductClaimEvidence.product_id
            == product_id,
            ProductClaimEvidence.status
            == "verified",
            ProductClaimEvidence.marketing_eligible
            .is_(True),
        )
        .order_by(
            ProductClaimEvidence.created_at,
            ProductClaimEvidence.id,
        )
        .all()
    )

    return [
        row
        for row in rows
        if not _is_expired(
            row.expires_at
        )
    ]
