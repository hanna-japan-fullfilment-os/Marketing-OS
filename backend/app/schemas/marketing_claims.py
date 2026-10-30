"""Reviewed wording projection over product evidence; never an efficacy inference."""
from typing import Literal
from pydantic import Field, model_validator
from .creative_bridge import Contract

ClaimClass = Literal["APPROVED_DIRECT", "APPROVED_WITH_QUALIFIER", "FACT_ONLY", "NEEDS_REVIEW", "PROHIBITED_UNSUPPORTED"]


class MarketingClaim(Contract):
    claim_id: str = Field(min_length=1)
    source_language_text_or_meaning: str = Field(min_length=1)
    source_publisher: str = Field(min_length=1)
    source_type: Literal["MANUFACTURER_PRODUCT", "MANUFACTURER_LAUNCH", "PACKAGING", "REGULATOR", "OWNER_EDITORIAL"]
    source_reference: str = Field(min_length=1)
    evidence_scope: Literal["PRODUCT_BENEFIT", "INGREDIENT_PRESENCE", "PRODUCT_FACT", "EDITORIAL", "UNSUPPORTED"]
    claim_class: ClaimClass
    approved_pt_br_wording: dict[str, str]
    mandatory_qualifier: str = ""
    prohibited_variants: tuple[str, ...]
    notes: str = Field(min_length=1)
    review_status: Literal["APPROVED", "NEEDS_REVIEW", "PROHIBITED"]
    language_review: Literal["VERIFIED", "PENDING"]
    language_reviewer: str = Field(min_length=1)
    group: str
    benefit_priority: Literal["PRIMARY", "SECONDARY", "SUPPORTING"]
    legacy_claim_ids: tuple[str, ...] = ()
    study_context: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def consistent_review(self):
        usable = self.claim_class in {"APPROVED_DIRECT", "APPROVED_WITH_QUALIFIER", "FACT_ONLY"}
        if usable and (self.review_status != "APPROVED" or self.language_review != "VERIFIED" or not self.approved_pt_br_wording):
            raise ValueError("Usable claims require reviewed PT-BR wording")
        if self.claim_class == "APPROVED_WITH_QUALIFIER" and not self.mandatory_qualifier:
            raise ValueError("Qualified claim requires its qualifier")
        if self.claim_class == "FACT_ONLY" and self.evidence_scope not in {"INGREDIENT_PRESENCE", "PRODUCT_FACT"}:
            raise ValueError("Fact-only record cannot assert product efficacy")
        if usable and self.evidence_scope == "UNSUPPORTED":
            raise ValueError("Unsupported evidence cannot authorize copy")
        if usable and self.evidence_scope != "EDITORIAL" and self.source_type not in {"MANUFACTURER_PRODUCT", "MANUFACTURER_LAUNCH", "PACKAGING"}:
            raise ValueError("Usable product statement requires exact-product primary evidence")
        if self.claim_class == "NEEDS_REVIEW" and self.review_status != "NEEDS_REVIEW":
            raise ValueError("Unresolved claim cannot be approved")
        if self.claim_class == "PROHIBITED_UNSUPPORTED" and self.review_status != "PROHIBITED":
            raise ValueError("Prohibited claim cannot be approved")
        if set(self.approved_pt_br_wording) - {"SHORT", "STANDARD", "EDITORIAL"}:
            raise ValueError("Unknown wording strength")
        if any(not wording.strip() for wording in self.approved_pt_br_wording.values()):
            raise ValueError("Blank wording cannot grant approval")
        return self


class ClaimLibrary(Contract):
    version: Literal[1] = 1
    product_id: str
    product_name: str
    variant: str
    jan: str
    researched_at: str
    reviewed_by: str
    owner_library_review_status: Literal["PENDING", "APPROVED"]
    brazil_market_review_status: Literal["REVIEW_REQUIRED", "CLEARED"] = "REVIEW_REQUIRED"
    brazil_clearance_evidence: str = ""
    research_categories: dict[str, bool]
    source_notes: dict[str, str]
    prohibited_language: tuple[str, ...]
    claims: tuple[MarketingClaim, ...]

    @model_validator(mode="after")
    def identities(self):
        if not self.claims or len({c.claim_id for c in self.claims}) != len(self.claims):
            raise ValueError("Claim IDs must be unique and nonempty")
        if self.brazil_market_review_status == "CLEARED" and not self.brazil_clearance_evidence.strip():
            raise ValueError("Brazil market clearance requires documented exact-product assessment")
        return self
