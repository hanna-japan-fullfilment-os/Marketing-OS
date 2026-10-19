"""Pydantic contracts for BUILD6R V3.45 claim evidence."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from .common import ORMModel


class ProductClaimEvidenceCreate(ORMModel):
    product_id: str
    research_run_id: str
    research_insight_id: str | None = None

    claim_text: str
    claim_type: str

    source_ids: list[str] = Field(
        default_factory=list
    )

    source_excerpt: str = ""

    source_scope: dict = Field(
        default_factory=dict
    )

    territory: str = ""
    evidence_period: str = ""


class ProductClaimVerification(ORMModel):
    evidence_strength: str

    marketing_eligible: bool = False

    source_ids: list[str] = Field(
        default_factory=list
    )

    source_excerpt: str

    source_scope: dict = Field(
        default_factory=dict
    )

    footnote: str = ""

    verification_method: str

    verifier: str

    expires_at: datetime | None = None


class ProductClaimRejection(ORMModel):
    rejection_reason: str
    verifier: str


class ProductClaimEvidenceOut(ORMModel):
    id: str

    product_id: str

    research_run_id: str | None
    research_insight_id: str | None

    claim_key: str
    claim_text: str
    normalized_claim: str
    claim_type: str

    status: str
    evidence_strength: str
    marketing_eligible: bool

    source_ids: list[str]
    source_excerpt: str
    source_scope: dict

    territory: str
    evidence_period: str
    footnote: str

    rejection_reason: str
    verification_method: str
    verifier: str

    verified_at: datetime | None
    expires_at: datetime | None
    promoted_at: datetime | None

    created_at: datetime
    updated_at: datetime
