"""App-wide creative-use policy, separate from commercial market clearance.

Assessments are reviewed exact-product evidence, never keyword matches against
ingredient names or an inference from a registration/import-review status.
"""
from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

CATALOG = Path(__file__).resolve().parents[1] / "data" / "PRODUCT_CREATIVE_ELIGIBILITY.json"
logger = logging.getLogger(__name__)


class IngredientAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    product_id: str = Field(min_length=1)
    ingredient: str = Field(min_length=1)
    status: Literal["CONFIRMED_PROHIBITED", "UNRESOLVED"]
    territory: Literal["BR"] = "BR"
    source_url: HttpUrl
    source_excerpt: str = Field(min_length=1)
    verified_by: str = Field(min_length=1)
    reviewed_on: date
    valid_until: date
    exact_formula_match: bool = False
    prohibition_applies_to_product_use: bool = False

    @model_validator(mode="after")
    def confirmed_scope(self):
        if any(not value.strip() for value in
               (self.product_id, self.ingredient, self.source_excerpt, self.verified_by)):
            raise ValueError("Ingredient assessment evidence must not be blank")
        if self.valid_until < self.reviewed_on:
            raise ValueError("Assessment validity ends before review")
        if self.status == "CONFIRMED_PROHIBITED" and not (
                self.exact_formula_match and self.prohibition_applies_to_product_use):
            raise ValueError("Confirmed prohibition requires exact formula and applicable-use evidence")
        return self


class EligibilityCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal[1]
    assessments: list[IngredientAssessment]


def creative_eligibility(product_id: str, *, today: date | None = None) -> dict:
    """No network, database or mutation. Absence of evidence is NOT clearance."""
    catalog = EligibilityCatalog.model_validate_json(CATALOG.read_text(encoding="utf-8"))
    today = today or date.today()
    records = [r for r in catalog.assessments if r.product_id == product_id]
    confirmed = [r for r in records if r.status == "CONFIRMED_PROHIBITED"
                 and r.reviewed_on <= today <= r.valid_until]
    warnings = []
    if confirmed:
        warnings.extend(f"Creative creation blocked: {r.ingredient} is confirmed prohibited "
                        f"for this product's use in Brazil. Source: {r.source_url}" for r in confirmed)
    else:
        warnings.append("No current confirmed ingredient prohibition is recorded for this product. "
                        "Creative use is allowed; ingredient permissibility is not certified.")
    for r in records:
        if r not in confirmed:
            warnings.append(f"Ingredient assessment unresolved, expired or not yet effective: "
                            f"{r.ingredient}. Source: {r.source_url}")
    return {
        "policy": "CONFIRMED_INGREDIENT_PROHIBITION_ONLY",
        "product_id": product_id,
        "creative_use_allowed": not confirmed,
        "ingredient_review_status": "CONFIRMED_PROHIBITED" if confirmed else "NOT_CONFIRMED_PROHIBITED",
        "commercial_clearance_required_for_creative_use": False,
        "warnings": warnings,
        "confirmed_prohibitions": [r.model_dump(mode="json") for r in confirmed],
    }


def require_creative_eligibility(product_id: str) -> dict:
    decision = creative_eligibility(product_id)
    if not decision["creative_use_allowed"]:
        raise ValueError(" ".join(decision["warnings"]))
    for warning in decision["warnings"]:
        logger.warning("Product %s: %s", product_id, warning)
    return decision
