"""Structured per-claim evidence boundary for BUILD6R V3.45.

Research remains non-canonical until one claim passes the deterministic
verification gate in services/claim_evidence.py.  The existing
VerifiedProductFact.verified_claims list[str] contract remains unchanged.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base
from ._mixins import TimestampMixin, UUIDPKMixin


CLAIM_EVIDENCE_STATUSES = (
    "candidate",
    "verified",
    "rejected",
)

CLAIM_EVIDENCE_STRENGTHS = (
    "",
    "official_primary",
    "official_secondary",
    "authoritative_third_party",
    "owner_confirmed",
)

CLAIM_TYPES = (
    "ingredient",
    "composition",
    "feature",
    "benefit",
    "usage",
    "size",
    "origin",
    "ranking",
    "award",
    "quantified_result",
    "certification",
    "regulatory_status",
    "popularity",
    "availability",
    "other",
)


class ProductClaimEvidence(
    Base,
    UUIDPKMixin,
    TimestampMixin,
):
    __tablename__ = "product_claim_evidence"

    __table_args__ = (
        UniqueConstraint(
            "product_id",
            "claim_key",
            name="uq_product_claim_evidence_product_key",
        ),
        CheckConstraint(
            "status IN ('candidate', 'verified', 'rejected')",
            name="ck_product_claim_evidence_status",
        ),
        CheckConstraint(
            (
                "evidence_strength IN "
                "('', 'official_primary', 'official_secondary', "
                "'authoritative_third_party', 'owner_confirmed')"
            ),
            name="ck_product_claim_evidence_strength",
        ),
        CheckConstraint(
            (
                "claim_type IN "
                "('ingredient', 'composition', 'feature', 'benefit', "
                "'usage', 'size', 'origin', 'ranking', 'award', "
                "'quantified_result', 'certification', "
                "'regulatory_status', 'popularity', "
                "'availability', 'other')"
            ),
            name="ck_product_claim_evidence_type",
        ),
    )

    product_id: Mapped[str] = mapped_column(
        ForeignKey(
            "products.id",
            ondelete="CASCADE",
        ),
        index=True,
    )

    research_run_id: Mapped[str | None] = mapped_column(
        ForeignKey(
            "research_runs.id",
            ondelete="SET NULL",
        ),
        nullable=True,
        index=True,
    )

    research_insight_id: Mapped[str | None] = mapped_column(
        ForeignKey(
            "research_insights.id",
            ondelete="SET NULL",
        ),
        nullable=True,
        index=True,
    )

    claim_key: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    claim_text: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    normalized_claim: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    claim_type: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(20),
        default="candidate",
        index=True,
    )

    evidence_strength: Mapped[str] = mapped_column(
        String(40),
        default="",
    )

    marketing_eligible: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
    )

    source_ids: Mapped[list] = mapped_column(
        JSON,
        default=list,
    )

    source_excerpt: Mapped[str] = mapped_column(
        Text,
        default="",
    )

    source_scope: Mapped[dict] = mapped_column(
        JSON,
        default=dict,
    )

    territory: Mapped[str] = mapped_column(
        String(100),
        default="",
    )

    evidence_period: Mapped[str] = mapped_column(
        String(200),
        default="",
    )

    footnote: Mapped[str] = mapped_column(
        Text,
        default="",
    )

    rejection_reason: Mapped[str] = mapped_column(
        Text,
        default="",
    )

    verification_method: Mapped[str] = mapped_column(
        String(100),
        default="",
    )

    verifier: Mapped[str] = mapped_column(
        String(200),
        default="",
    )

    verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    promoted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
