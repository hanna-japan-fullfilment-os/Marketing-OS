"""Structured-output contracts for AI calls (section 29 of the brief).
Every AI response the application depends on for state must validate against one of
these — never parsed from free-form Markdown.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ResearchQuery(BaseModel):
    brand_name: str
    category: str
    product: str | None = None
    geography: str
    audience: str
    objective: str
    language: str = "pt-BR"


class ResearchInsightItem(BaseModel):
    statement: str
    confidence: float = Field(ge=0, le=1)
    freshness: str
    category: str
    recommended_implication: str
    source_urls: list[str] = []


class ResearchResult(BaseModel):
    insights: list[ResearchInsightItem]
    notable_dates: list[str] = []
    competitor_observations: list[str] = []
    customer_questions: list[str] = []


class CampaignStrategy(BaseModel):
    objective: str
    audience: str
    funnel_stage: str
    insight: str
    angle: str
    key_message: str
    reason_this_should_work: str
    research_basis: list[str] = []


class CampaignStrategyCandidates(BaseModel):
    """Wrapper so the Autopilot orchestrator gets 2-3 genuinely different strategy
    candidates from a single structured-output call (brief section 18 step 7),
    rather than one call per candidate.
    """

    candidates: list[CampaignStrategy]


class CreativeBrief(BaseModel):
    design_concept: str
    visual_prompt: str
    template_suggestion: str
    tone_notes: str


class CampaignCopy(BaseModel):
    hook: str
    headline: str
    supporting_copy: str
    cta: str
    caption: str
    hashtags: list[str] = []
    alt_text: str
    community_version: str | None = None


class SlideFeature(BaseModel):
    """One icon + bold title + short subtitle bullet for the left-side feature
    list in the `feature_showcase` template (round 17) — see
    `services/creative/templates.py::Feature`/`_build_feature_showcase`.
    `icon` should be a single emoji the model judges relevant to `title`
    (e.g. a droplet for hydration, a leaf for natural ingredients) — there is no
    icon image library, so this is the only source of the icon glyph.
    """

    icon: str = Field(default="", max_length=4)
    title: str
    subtitle: str = ""


class SlidePlan(BaseModel):
    slide_number: int
    purpose: str
    eyebrow: str = ""
    headline: str
    body: str = ""
    cta: str = ""
    visual_brief: str
    # Round 17 fields for the `feature_showcase` template — all optional so a
    # model response that omits them still produces a valid, if plainer, slide
    # (see `_build_feature_showcase`'s per-section conditional rendering).
    badge_text: str = ""
    intro: str = ""
    features: list[SlideFeature] = []
    callout_label: str = ""
    callout_value: str = ""
    bottom_features: list[str] = []
    trust_badges: list[str] = []


class CarouselPlan(BaseModel):
    slides: list[SlidePlan]
    narrative_summary: str


class BrandVisualStyleAnalysis(BaseModel):
    """Structured result of showing the model a brand's own reference/example photos
    (BrandAsset kind='visual_reference') and asking it to describe the visual style
    those photos establish — never invented from a text description alone. This is
    a proposal only: the API layer returns it for a human to review/edit and then
    apply via the normal `PATCH /api/brands/{id}` endpoint, never written to the
    brand directly, matching the app's human-approval-is-authoritative rule.
    """

    summary: str
    dominant_colors: list[str] = []  # hex codes, e.g. "#f5e6d3"
    typography_mood: str = ""
    photography_style: str = ""
    visual_style_descriptors: list[str] = []
    voice_suggestion: str = ""
    forbidden_style_suggestions: list[str] = []


class OpportunityRecommendation(BaseModel):
    platform: str
    name: str
    url: str = ""
    rationale: str
    estimated_relevance: float = Field(ge=0, le=1)
    recommended_content_style: str
    country: str = ""
    language: str = ""
    audience_size: int | None = None
    promo_allowed: bool | None = None
    posting_rules: str = ""
    source_urls: list[str] = []


class OpportunityDiscoveryResult(BaseModel):
    """Wrapper so opportunity discovery is one structured-output call, mirroring
    ResearchResult/CampaignStrategyCandidates rather than one call per community.
    """

    recommendations: list[OpportunityRecommendation]


class VisualQAResult(BaseModel):
    passed: bool
    issues: list[str] = []
    notes: str = ""


class ProductFidelityCheck(BaseModel):
    """Structured result of comparing an AI-recreated marketing image against the
    real source product photo it was generated from — the mechanical
    implementation of the user's own uploaded governance rubric's "H. Product
    fidelity" check (see the Claude Project's `claude/hanna-gpt-system/
    05-content-and-creative-review-rubric.md`): "Fail if the creative replaces
    the real product with a fictional lookalike or redesign." Checks the same
    concrete aspects that rubric names: package shape, proportions, brand/logo,
    label structure, visible text, cap/pump/dropper or other closure, color, and
    distinctive marks.

    Never trusted blindly — `services/orchestrator.py::
    recreate_creative_image_with_fidelity_gate` treats anything short of an
    explicit `overall_verdict="PASS"` (including a failed/unavailable check
    itself) as reason to retry once with a corrective prompt and, failing that,
    fall back to the deterministic pipeline rather than ship an unverified
    image — "fail-closed", matching the user's own uploaded campaign rules ("A
    blocker is better than invented content", doc 04 section 22). `overall_
    verdict` defaults to "FAIL" (not "PASS") so a degenerate/empty parse can
    never accidentally read as a pass.
    """

    package_shape: Literal["match", "mismatch", "uncertain"] = "uncertain"
    proportions: Literal["match", "mismatch", "uncertain"] = "uncertain"
    brand_logo: Literal["match", "mismatch", "uncertain"] = "uncertain"
    label_structure: Literal["match", "mismatch", "uncertain"] = "uncertain"
    visible_text: Literal["match", "mismatch", "uncertain"] = "uncertain"
    cap_or_closure: Literal["match", "mismatch", "uncertain"] = "uncertain"
    color: Literal["match", "mismatch", "uncertain"] = "uncertain"
    distinctive_marks: Literal["match", "mismatch", "uncertain"] = "uncertain"
    overall_verdict: Literal["PASS", "FAIL"] = "FAIL"
    reasoning: str = ""


class SourceProductIdentityCheck(BaseModel):
    """Build 6 repair (Critical Defect 1) — a PRE-GENERATION gate, run before
    any billed AI image generation, that checks whether a real source photo
    actually depicts the catalog `Product` this campaign claims it does. This
    is deliberately a DIFFERENT question from `ProductFidelityCheck` above
    (which compares an AI-RECREATED image back against its own source photo,
    after generation): this one compares the source photo itself against the
    catalog's own product identity (name/category), before any generation
    spends money, to catch the case where the wrong source asset was ever
    selected for this product in the first place — a real live-acceptance
    defect where a campaign titled "Melano CC Essence" (a serum) rendered a
    package clearly labeled as a cleanser/wash, because the selected source
    photo was never actually of the named product.

    `verdict` is a three-way call, not a boolean, because a vision model
    genuinely cannot always tell — a distant/blurry/back-of-package/heavily
    cropped photo may leave a real "I can't tell" case that must NOT be
    silently treated as a pass: only `MATCH` is safe to proceed on.
    `UNVERIFIABLE` is deliberately a separate value from `MISMATCH` (a
    caller might want to know that the check itself was inconclusive, versus
    a confident contradiction) but both fail the gate identically — the
    caller (`services/orchestrator.py::_enforce_source_product_identity_
    gate`) never proceeds to a billed generation call on anything but a
    genuine `MATCH`.

    Deliberately does NOT try to extract new product facts from the
    packaging (e.g. ingredients, claims) — that would blur this into
    `VerifiedProductFactsOut`'s job and risk exactly the "research/observation
    silently becomes a verified fact" failure mode this repair also fixes
    elsewhere. `observed_product_type`/`observed_label_text` exist only to
    give a human a concrete, checkable reason for a MISMATCH/UNVERIFIABLE
    verdict — they are evidence for the verdict, never treated as verified
    facts themselves.
    """

    verdict: Literal["MATCH", "MISMATCH", "UNVERIFIABLE"] = "UNVERIFIABLE"
    observed_product_type: str = ""
    observed_label_text: str = ""
    reasoning: str = ""


class ProductZoneDetection(BaseModel):
    """Structured result of a vision-model call that looks at one real source photo
    and locates the product within it: the crop box that tightly bounds the product
    (fractions of the photo's width/height, top-left origin) and which edge of that
    box the product is visually anchored to. This is what lets the creative
    pipeline fill a template's product zone with just the product, per photo,
    instead of assuming every uploaded photo happens to already be framed the way
    the template's one fixed layout expects (see services/creative/pipeline.py::
    render_slide and services/orchestrator.py::detect_product_zone). Never invented
    from a description alone — the caller always shows the model the real photo.
    """

    crop_left: float = Field(ge=0, le=1)
    crop_top: float = Field(ge=0, le=1)
    crop_width: float = Field(gt=0, le=1)
    crop_height: float = Field(gt=0, le=1)
    anchor: Literal["center", "bottom", "top"] = "center"
    reasoning: str = ""
