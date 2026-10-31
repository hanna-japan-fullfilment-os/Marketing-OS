"""Provider-neutral, immutable handoff and fail-closed multimodal QA contracts."""
from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .ai import ProductFidelityCheck


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    def digest(self) -> str:
        payload = json.dumps(self.model_dump(mode="json"), sort_keys=True,
                             separators=(",", ":"), ensure_ascii=False, allow_nan=False)
        return hashlib.sha256(payload.encode()).hexdigest()


class CreativeImage(Contract):
    asset_id: str = Field(min_length=1)
    role: Literal["product_source", "product_master", "visual_reference", "logo", "base", "mask"]
    path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    mime_type: Literal["image/png", "image/jpeg", "image/webp"]
    authority: str = Field(min_length=1)
    # Approval provenance is evidence, never a permission inherited by sibling assets.
    provenance_json: str = Field(min_length=2)


class CopyField(Contract):
    key: str = Field(min_length=1)
    text: str = Field(min_length=1)


class TextRegion(Contract):
    key: str
    box: tuple[int, int, int, int]
    font_id: str
    font_size: int = Field(gt=0, le=300)
    color: str = Field(pattern=r"^#[a-fA-F0-9]{6}$")


class HannaCreativePackage(Contract):
    version: Literal[1] = 1
    campaign_id: str = Field(min_length=1)
    brand_id: str = Field(min_length=1)
    product_id: str = Field(min_length=1)
    product_name: str = Field(min_length=1)
    category: str = Field(min_length=1)
    slide_id: str = Field(min_length=1)
    slide_role: str = Field(min_length=1)
    locale: str = Field(min_length=1)
    channel: str = Field(min_length=1)
    # Serialized existing claim/fact contracts; no parallel evidence registry.
    approved_facts_json: str
    slide_contract_json: str
    approved_copy: tuple[CopyField, ...]
    prohibited_claims: tuple[str, ...] = Field(min_length=1)
    brand_instructions: str = Field(min_length=1)
    visual_objective: str = Field(min_length=1)
    width: int = Field(gt=0, le=4096)
    height: int = Field(gt=0, le=4096)
    aspect_ratio: str
    required_cta: str
    logo_required: bool = True
    images: tuple[CreativeImage, ...]
    text_mode: Literal["model_integrated", "negative_space_overlay"] = "model_integrated"
    text_regions: tuple[TextRegion, ...] = ()

    @model_validator(mode="after")
    def complete(self):
        from ..services.product_creative_eligibility import require_creative_eligibility
        require_creative_eligibility(self.product_id)
        roles = [a.role for a in self.images]
        if "product_source" not in roles or "visual_reference" not in roles:
            raise ValueError("Actual source product and approved reference images are required")
        if self.logo_required and roles.count("logo") != 1:
            raise ValueError("Exactly one canonical logo is required")
        if len({a.asset_id for a in self.images}) != len(self.images):
            raise ValueError("Duplicate asset identity")
        if any(roles.count(r) > 1 for r in ("base", "mask")) or ("mask" in roles and "base" not in roles):
            raise ValueError("Mask requires exactly one prepared base")
        keys = [c.key for c in self.approved_copy]
        if len(set(keys)) != len(keys):
            raise ValueError("Duplicate copy field")
        if self.required_cta and self.required_cta not in [c.text for c in self.approved_copy]:
            raise ValueError("Required CTA must be canonical copy")
        if self.aspect_ratio != f"{self.width}:{self.height}":
            raise ValueError("Aspect must identify exact output dimensions")
        facts = json.loads(self.approved_facts_json)
        if not facts or not json.loads(self.slide_contract_json):
            raise ValueError("Canonical fact and slide contracts required")
        regions = [r.key for r in self.text_regions]
        if self.text_mode == "negative_space_overlay" and sorted(regions) != sorted(keys):
            raise ValueError("Every canonical copy field needs exactly one prepared negative-space region")
        if self.text_mode == "model_integrated" and regions:
            raise ValueError("Overlay regions require overlay mode")
        return self


class CreativeOptions(Contract):
    director_model: str = Field(min_length=1)
    image_model: str = Field(min_length=1)
    image_size: str = Field(pattern=r"^\d+x\d+$")
    quality: Literal["high", "medium", "low"] = "high"
    max_output_tokens: int = Field(gt=0, le=16000)

    @model_validator(mode="after")
    def bounded_size(self):
        if any(not 0 < int(n) <= 4096 for n in self.image_size.split("x")):
            raise ValueError("Native image dimensions out of bounds")
        return self


class CreativeReview(Contract):
    package_sha256: str
    candidate_sha256: str
    product: ProductFidelityCheck
    major_elements: Literal["match", "mismatch", "uncertain"]
    components: Literal["match", "mismatch", "uncertain"]
    variant: Literal["match", "mismatch", "uncertain"]
    observed_copy: tuple[CopyField, ...]
    unexpected_marketing_text: tuple[str, ...]
    unsupported_claims: bool
    # Geometry is checked separately from style. Missing/uncertain answers cannot pass.
    no_clipping: bool
    no_overlap: bool
    product_box: tuple[int, int, int, int]
    scene_cohesion: Literal["PASS", "FAIL", "UNCERTAIN"]
    product_integration: Literal["PASS", "FAIL", "UNCERTAIN"]
    reference_style: Literal["PASS", "FAIL", "UNCERTAIN"]
    no_disconnected_cards: Literal["PASS", "FAIL", "UNCERTAIN"]
    logo_integration: Literal["PASS", "FAIL", "UNCERTAIN"]
    typography_integration: Literal["PASS", "FAIL", "UNCERTAIN"]
    premium_polish: Literal["PASS", "FAIL", "UNCERTAIN"]
    reasoning: str = Field(min_length=1)
