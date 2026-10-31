"""Planning-only strategy inputs. Advertising copy comes from the claims library."""
from typing import Literal
from pydantic import Field, field_validator, model_validator
from .creative_bridge import Contract

Format = Literal['INSTAGRAM_CAROUSEL_5', 'INSTAGRAM_CAROUSEL_10', 'META_PAID_SOCIAL',
                 'INSTAGRAM_STORIES', 'REEL_SHORT_VIDEO', 'INSTAGRAM_STATIC', 'FACEBOOK_STATIC']
Category = Literal['principal_benefit', 'secondary_benefit', 'differentiation', 'technology',
                   'formula', 'usage', 'pack', 'origin', 'proof', 'objections', 'buying_information']


class CoverageItem(Contract):
    key: str = Field(min_length=1)
    category: Category
    priority: Literal['PRIMARY', 'SECONDARY', 'SUPPORTING']
    claim_id: str = Field(min_length=1)
    # Omission has to be explained against the chosen tactic, not silently lost.
    relevant: bool = True
    omission_reason: str = ''

    @model_validator(mode='after')
    def explained_omission(self):
        if not self.relevant and not self.omission_reason.strip():
            raise ValueError('Intentional omission requires a strategy rationale')
        return self


class MessageUsage(Contract):
    tactic_key: str
    hook_claim_id: str
    angle: str
    primary_claim_id: str
    layout_family: str


class CampaignCreativeStrategyRequest(Contract):
    product_id: str = Field(min_length=1)
    objective: Literal['awareness', 'education', 'discovery', 'engagement', 'authority', 'consideration', 'conversion']
    audience: str = Field(min_length=1)
    funnel_stage: Literal['awareness', 'consideration', 'conversion', 'retention']
    tactic_key: str = Field(min_length=1)
    angle: str = Field(min_length=1)
    hook_claim_id: str
    primary_claim_id: str
    secondary_claim_ids: tuple[str, ...] = ()
    proof_claim_ids: tuple[str, ...] = Field(min_length=1)
    cta_claim_id: str
    formats: tuple[Format, ...] = Field(min_length=1)
    coverage: tuple[CoverageItem, ...] = Field(min_length=1)
    # History is explicit caller context; no hidden analytics/DB/provider access.
    history: tuple[MessageUsage, ...] = ()
    product_novelty: Literal['new', 'established'] = 'established'
    complexity: Literal['low', 'high'] = 'low'
    objections: tuple[str, ...] = ()
    visual_benchmark: str = Field(min_length=1)
    funnel_cta_claim_ids: dict[Literal['awareness', 'consideration', 'conversion'], str] = Field(default_factory=dict)

    @field_validator('audience', 'angle', 'visual_benchmark', 'tactic_key', 'product_id')
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError('Blank strategy field')
        return value.strip()

    @model_validator(mode='after')
    def unique_inputs(self):
        if len(set(self.formats)) != len(self.formats):
            raise ValueError('Duplicate format')
        if len({c.key for c in self.coverage}) != len(self.coverage):
            raise ValueError('Duplicate coverage key')
        if len({c.claim_id for c in self.coverage}) != len(self.coverage):
            raise ValueError('Duplicate evidence item would inflate coverage')
        return self
