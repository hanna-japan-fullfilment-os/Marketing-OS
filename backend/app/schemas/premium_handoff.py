"""Governed external creative handoff and human review contracts."""
from typing import Literal
from pydantic import Field, StrictBool, field_validator
from .creative_bridge import Contract, CreativeImage, CopyField


class PremiumSlideBrief(Contract):
    key: str
    slide_number: int = Field(gt=0)
    slide_role: str
    primary_message: str
    approved_copy: tuple[CopyField, ...]
    facts_allowed_json: str
    product_asset_ids: tuple[str, ...]
    reference_asset_ids: tuple[str, ...]
    visual_intent: str
    required_elements: tuple[str, ...]
    prohibited_elements: tuple[str, ...]
    cta: str
    output_size: tuple[int,int]
    locale: str
    channel: str
    canonical_package_sha256: str
    approved_claim_ids: dict[str, str] = Field(default_factory=dict)
    mandatory_qualifiers: dict[str, str] = Field(default_factory=dict)
    benefit_hierarchy: tuple[str, ...] = ()
    claim_library_sha256: str = ""
    creative_brief_status: Literal["DRAFT", "CREATIVE_READY"] = "DRAFT"


class PremiumCreativeHandoff(Contract):
    version: Literal[1] = 1
    campaign_id: str
    product_id: str
    product_name: str
    category: str
    objective: str
    concept: str
    audience: str
    brand_instructions: str
    approved_facts_json: str
    prohibited_claims: tuple[str,...]
    expected_slide_count: int
    slides: tuple[PremiumSlideBrief,...]
    assets: tuple[CreativeImage,...]
    creative_source: Literal["external_chatgpt_creative_workflow"] = "external_chatgpt_creative_workflow"
    production_mode: Literal["EXTERNAL_PREMIUM_HANDOFF"] = "EXTERNAL_PREMIUM_HANDOFF"


FeedbackCode = Literal["product_fidelity","copy","typography","hierarchy","brand_mismatch","composition","cta","visual_quality","other"]


class PremiumReviewRequest(Contract):
    expected_version: int = Field(gt=0)
    slide_key: str
    decision: Literal["APPROVED","REJECTED"]
    reviewer: str = Field(min_length=1,max_length=200)
    product_visible: StrictBool = False
    product_fidelity_confirmed: StrictBool = False
    observed_copy: dict[str,str] = Field(default_factory=dict)
    feedback_codes: tuple[FeedbackCode,...] = ()
    feedback: str = Field(default="",max_length=5000)

    @field_validator("reviewer")
    @classmethod
    def named_reviewer(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("A named human reviewer is required")
        return value.strip()
