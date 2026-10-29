"""Narrow estimator seam. Estimates and enforceable maxima are different values.

No GPT Image 2.5 image-input token formula is implemented or inferred here.
"""
from decimal import Decimal
from typing import Literal, Protocol

from pydantic import Field, model_validator

from ..schemas.creative_bridge import Contract


class CostComponent(Contract):
    status: Literal["BOUND", "ESTIMATE", "UNRESOLVED"]
    usd: Decimal | None = Field(default=None, ge=0)
    tokens: int | None = Field(default=None, ge=0)
    authority: str = Field(min_length=1)

    @model_validator(mode="after")
    def truthful(self):
        if self.status == "UNRESOLVED" and (self.usd is not None or self.tokens is not None):
            raise ValueError("Unknown cost must not be represented as zero")
        if self.status != "UNRESOLVED" and (self.usd is None or self.tokens is None):
            raise ValueError("Known cost requires tokens and amount")
        return self


class MultimodalCostEstimator(Protocol):
    def estimate_text_input_cost(self, prompt: str, settings) -> CostComponent: ...
    def estimate_image_input_cost(self, references, settings) -> CostComponent: ...
    def estimate_image_output_cost(self, settings) -> CostComponent: ...


class CostQuote(Contract):
    text_input: CostComponent
    image_input: CostComponent
    image_output: CostComponent

    @property
    def total_request_max_cost(self) -> Decimal | None:
        parts = (self.text_input, self.image_input, self.image_output)
        if any(p.status != "BOUND" for p in parts):
            return None
        return sum((p.usd for p in parts), Decimal(0))

    def require_within(self, maximum: Decimal):
        if not maximum.is_finite() or maximum <= 0:
            raise ValueError("Explicit finite positive budget required")
        total = self.total_request_max_cost
        if total is None:
            raise ValueError("HARD_BUDGET_UNKNOWN_MULTIMODAL_MAXIMUM")
        if total > maximum:
            raise ValueError("HARD_BUDGET_MULTIMODAL_MAXIMUM_EXCEEDED")


class SunburstCostEstimator:
    """Verified official output estimate snapshot; NEVER a total-price authorization.

    2026-10-29 official image-generation calculator, high 1024x1536: 1372 output
    tokens at $30/M = $0.04116. This estimate is not promoted to a hard maximum.
    Text tokenizer/overhead and edit-image token maxima are unresolved here.
    """
    source = "https://developers.openai.com/api/docs/guides/image-generation"

    @staticmethod
    def _supported(settings):
        return (settings.model in ("gpt-image-2.5-sunburst", "gpt-image-2.5-sunburst-2026-09-08")
                and settings.quality == "high" and settings.size == "1024x1536" and settings.n == 1
                and settings.partial_images == 0 and settings.stream is False)

    def estimate_text_input_cost(self, prompt, settings):
        return CostComponent(status="UNRESOLVED", authority="Supported exact tokenizer and request overhead not established")

    def estimate_image_input_cost(self, references, settings):
        return CostComponent(status="UNRESOLVED", authority="No supported Sunburst edit image-input token maximum established")

    def estimate_image_output_cost(self, settings):
        if not self._supported(settings):
            return CostComponent(status="UNRESOLVED", authority="Unknown model/quality/size output estimate")
        return CostComponent(status="ESTIMATE", tokens=1372, usd=Decimal("0.04116"),
            authority=self.source + "#gpt-image-25-and-gpt-image-2-output-tokens; official estimate verified 2026-10-29")


def estimate_multimodal_cost(prompt, references, settings, *, estimator: MultimodalCostEstimator | None = None):
    strategy = estimator if estimator is not None else SunburstCostEstimator()
    return CostQuote(text_input=strategy.estimate_text_input_cost(prompt, settings),
        image_input=strategy.estimate_image_input_cost(references, settings),
        image_output=strategy.estimate_image_output_cost(settings))
