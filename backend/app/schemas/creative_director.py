"""Structured-output contracts for Build 2 (MARKETING OS — PLATFORM ADAPTER +
CREATIVE DIRECTOR + HYBRID VISUAL ENGINE), Parts E/F/G/H/L. Same discipline as
`schemas/ai.py`: every AI response this app depends on for state validates
against one of these, never parsed from free-form text.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class MasterCampaignConcept(BaseModel):
    """Part E: the ONE campaign idea, generated once per campaign (in
    `run_copy_stage`, alongside `CreativeBrief`) and held constant across every
    platform/language adaptation that follows — see `PlatformAdaptation` below,
    which is explicitly told to adapt THIS, never to invent a new concept per
    platform. Deliberately platform- and language-agnostic: nothing here names
    a specific platform's format or a specific language's wording.
    """

    concept_name: str
    campaign_promise: str
    key_message: str
    emotional_goal: str
    audience: str
    objective: str
    visual_identity: str
    story_arc: str
    cta_intent: str

    # Build 6R: universal product-aware creative intelligence.
    # Defaults preserve old persisted campaign compatibility.
    product_category_context: str = ""
    campaign_archetype: str = ""
    archetype_reasoning: str = ""
    visual_story_system: str = ""
    hero_treatment: str = ""
    proof_or_demo_strategy: str = ""
    story_beats: list[str] = []

    must_include: list[str] = []
    must_avoid: list[str] = []


class PlatformAdaptation(BaseModel):
    """Part F: how the `MasterCampaignConcept` adapts to ONE specific target
    platform — the actual answer to "do not simply resize the same creative".
    Generated once per (campaign, platform) — shared across that platform's
    targeted languages, since the adaptation strategy (TikTok: hook + script +
    shot progression; Pinterest: vertical discovery creative; etc.) is a
    platform-level decision, not a per-language one; `CreativeDirection` below
    is where per-language layout differences actually get decided.
    """

    platform: str
    adaptation_strategy: str  # e.g. "hook + script + shot progression" for TikTok, "vertical discovery creative" for Pinterest
    narrative_shape: str  # how the concept's story_arc compresses/expands for this platform's real format
    tone_adjustment: str  # e.g. "slightly fuller promotional context" (Facebook) vs "short concise execution" (X)
    content_type: str  # data/platform_creative_specs.py key this adaptation targets
    reasoning: str = ""


class CreativeDirection(BaseModel):
    """Part G (+ Part H's multi-language requirement): the concrete visual/
    layout direction for ONE rendered variant — one (platform, language,
    content_type) combination, not a generic per-campaign brief. This is what
    `_render_additional_platform_variants` (services/orchestrator.py) uses to
    ground the AI-generated background/scene prompt (Part J: scene/atmosphere/
    lighting only — never the exact label, logo, headline, price, CTA, or legal
    text, all of which stay real HTML/CSS or the real product photo, per the
    Hybrid Renderer's own separation) and the deterministic template's colors/
    typography choice.

    `typography_direction`/`headline_emphasis` are language-aware BY
    CONSTRUCTION — this schema is generated (or deterministically derived) once
    PER (platform, language), never shared across languages the way
    `PlatformAdaptation` is shared across a platform's languages, because text
    length/layout genuinely differs between e.g. pt-BR and en (see this
    module's docstring and Part H).
    """

    concept_name: str = ""
    platform: str = ""
    content_type: str = ""
    language: str = ""
    campaign_visual_identity: str = ""

    # Build 6R: per-slide execution of the selected archetype.
    product_category_context: str = ""
    campaign_archetype: str = ""
    archetype_reasoning: str = ""
    visual_story_system: str = ""
    hero_treatment: str = ""
    proof_or_demo_strategy: str = ""

    rationale: str = ""
    emotional_goal: str = ""
    visual_style: str = ""
    mood: str = ""
    composition: str = ""
    product_position: str = ""
    product_scale: str = ""
    background_concept: str = ""
    lighting: str = ""
    depth: str = ""
    texture: str = ""
    palette: list[str] = []
    typography_direction: str = ""
    headline_emphasis: str = ""
    cta_treatment: str = ""
    negative_space: str = ""
    slide_role: str = ""
    continuity_notes: str = ""
    prohibited_elements: list[str] = Field(
        default_factory=lambda: [
            "exact product label text rendered by the AI",
            "brand logo rendered by the AI",
            "headline/body/CTA copy rendered by the AI",
            "price or discount graphic",
            "legal or disclaimer text rendered by the AI",
        ]
    )
    scene_generation_prompt: str = ""
    negative_constraints: str = ""


class VideoConcept(BaseModel):
    """Part L: the structured hook/script/shot-list output produced for a
    video-oriented content type (TikTok/Reels/YouTube Shorts short-video
    concepts) when this app has no actual video-rendering capability. Never a
    stand-in for a rendered video file — `is_rendered_video` is fixed at
    `False` (not a caller-settable flag) so nothing downstream can mistake this
    for a finished asset; see `PlatformCampaignVariant.status="SCRIPT_ONLY"`
    (`services/orchestrator.py`), which is the only status a video-oriented
    variant with a populated `video_concept` can ever have.
    """

    hook: str
    script: str
    shot_list: list[str] = []
    timing: str = ""
    visual_direction: str = ""
    on_screen_text: list[str] = []
    caption: str = ""
    cover_creative_brief: str = ""
    is_rendered_video: bool = False

    def model_post_init(self, __context) -> None:  # noqa: D401 - pydantic hook
        # Belt-and-suspenders: even if a caller (or a future refactor)
        # constructs this with is_rendered_video=True, force it back to False.
        # This field exists to be checked, not to be set true by anything.
        self.is_rendered_video = False
