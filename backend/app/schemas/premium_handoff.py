"""Governed external creative handoff and human review contracts."""
from typing import Literal
from pydantic import Field, StrictBool, field_validator, model_validator
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


class ExecutionReference(Contract):
    asset_id: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    rationale: str = Field(min_length=1)
    permitted_influences: tuple[Literal["composition", "lighting", "palette", "hierarchy", "finish"], ...] = Field(min_length=1)

    @field_validator("asset_id", "rationale")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Concrete reference identity/rationale required")
        return value.strip()


class CreativeExecutionPlan(Contract):
    """Structural planning evidence, never visual acceptance or a provider permit."""
    version: Literal[1] = 1
    slide_key: str = Field(min_length=1)
    brief_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    communication_objective: str = Field(min_length=1)
    visual_mechanism: str = Field(min_length=1)
    product_role: Literal["dominant_hero", "contextual_hero"]
    composition_family: Literal["product_hero", "editorial_detail", "ritual_context"]
    composition_rationale: str = Field(min_length=1)
    references: tuple[ExecutionReference, ...] = Field(min_length=1)
    camera_relationship: str = Field(min_length=1)
    spatial_relationship: str = Field(min_length=1)
    lighting_integration: str = Field(min_length=1)
    typography_requirements: str = Field(min_length=1)
    prohibited_imagery: tuple[str, ...] = Field(min_length=1)
    imagery_mode: Literal["product_only", "human_context_no_demonstration"] = "product_only"
    owner_review_status: Literal["PENDING", "APPROVED", "REJECTED"] = "PENDING"
    owner_reviewer: str = ""
    reviewed_content_sha256: str = ""

    @field_validator("slide_key", "communication_objective", "visual_mechanism",
                     "composition_rationale", "camera_relationship", "spatial_relationship",
                     "lighting_integration", "typography_requirements")
    @classmethod
    def concrete_text(cls, value):
        if not value.strip():
            raise ValueError("Nonblank execution requirement required")
        return value.strip()

    @field_validator("prohibited_imagery")
    @classmethod
    def explicit_prohibitions(cls, values):
        if any(not v.strip() for v in values):
            raise ValueError("Blank imagery prohibition")
        required = {"invented packaging", "unsupported claims", "misleading demonstrations"}
        if not required.issubset(values):
            raise ValueError("Product/claim/demonstration protections required")
        return values

    def content_digest(self):
        import hashlib
        import json
        payload = self.model_dump(mode="json", exclude={
            "owner_review_status", "owner_reviewer", "reviewed_content_sha256"})
        return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"),
            ensure_ascii=False, allow_nan=False).encode()).hexdigest()

    @model_validator(mode="after")
    def review_binding(self):
        if len({r.asset_id for r in self.references}) != len(self.references):
            raise ValueError("Duplicate execution reference")
        if self.owner_review_status == "APPROVED" and (
                not self.owner_reviewer.strip() or self.reviewed_content_sha256 != self.content_digest()):
            raise ValueError("Named owner review of exact execution content required")
        return self


class PremiumExecutionSlideBrief(PremiumSlideBrief):
    execution_plan: CreativeExecutionPlan


class PremiumExecutionHandoff(PremiumCreativeHandoff):
    # Separate model keeps every legacy v1 field and digest byte-compatible.
    version: Literal[2] = 2
    slides: tuple[PremiumExecutionSlideBrief, ...]


class ReconciliationEvidence(Contract):
    path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class CanonicalCampaignReconciliation(Contract):
    """Persisted import recipe/provenance; never an approval or claim registry."""
    version: Literal[1] = 1
    campaign_id: str = Field(min_length=1)
    product_id: str = Field(min_length=1)
    architecture: ReconciliationEvidence
    architecture_approval: ReconciliationEvidence
    freeze: ReconciliationEvidence
    creative_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    evidence_ids: dict[str, str]
    master_asset_id: str = Field(min_length=1)
    logo: CreativeImage
    references: tuple[CreativeImage, ...] = Field(min_length=1)


class ProductionScopeEnvelope(Contract):
    """Separate opt-in contract: complete authority, selected output only."""
    scope_version: Literal[1] = 1
    canonical_handoff: PremiumCreativeHandoff
    reconciliation_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    dispositions: dict[str, Literal["FROZEN_EXTERNAL_REFERENCE", "SELECTED_PENDING_OWNER_REVIEW", "DEFERRED_UNRENDERED"]]
    execution_plans: dict[str, CreativeExecutionPlan]
    owner_review_status: Literal["PENDING", "APPROVED", "REJECTED"] = "PENDING"
    owner_reviewer: str = ""
    reviewed_content_sha256: str = ""

    def content_digest(self):
        from .creative_bridge import Contract
        return Contract.digest(self.model_copy(update={"owner_review_status": "PENDING",
            "owner_reviewer": "", "reviewed_content_sha256": ""}))

    @property
    def slides(self):
        return tuple(PremiumExecutionSlideBrief(**s.model_dump(), execution_plan=self.execution_plans[s.key])
            for s in self.canonical_handoff.slides if s.key in self.execution_plans)

    @property
    def assets(self):
        return self.canonical_handoff.assets

    @property
    def campaign_id(self):
        return self.canonical_handoff.campaign_id

    @property
    def product_id(self):
        return self.canonical_handoff.product_id

    @property
    def expected_slide_count(self):
        return len(self.execution_plans)

    def execution_handoff(self):
        payload = self.canonical_handoff.model_dump(mode="json")
        payload.update(version=2, expected_slide_count=len(self.slides),
            slides=[s.model_dump(mode="json") for s in self.slides])
        return PremiumExecutionHandoff.model_validate(payload)


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
