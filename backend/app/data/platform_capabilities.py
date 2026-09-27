"""Central registry for the two structured-configuration concepts Build 1 (Parts
B/C of the Multi-Platform + Bilingual Quality Recovery Program) adds: which
languages a campaign can target, and which real-world social platforms it's
being planned for.

Nothing in this app should ever hardcode "Instagram" or "pt-BR" as an implicit
assumption outside this file — every other module reads from here (see
`services/orchestrator.py::run_copy_stage`, `api/campaigns.py`'s
CampaignCreate/CampaignUpdate validation).
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Canonical locale values — deliberately just these two, not a free-text field.
# `en` is generic marketing English, not tied to one English-speaking country;
# `pt-BR` is specifically Brazilian Portuguese, not European Portuguese.
SUPPORTED_LANGUAGES: tuple[str, ...] = ("pt-BR", "en")

DEFAULT_LANGUAGES: list[str] = ["pt-BR"]


@dataclass(frozen=True)
class PlatformCapability:
    key: str
    label: str
    # Content shapes this platform actually supports — informational, and used
    # to tailor copy-writing guidance (see `_platform_requirements_note` in
    # services/orchestrator.py). Deliberately NOT every platform gets every
    # content type: a carousel makes sense for Instagram, not for X.
    content_types: tuple[str, ...]
    # Which `services/creative/templates.py::PLATFORM_FORMATS` key this
    # platform's content is closest to by default, for anything that still
    # needs one canvas size today (full per-platform rendering variants are not
    # built in Build 1 — see docs/campaign-pipeline.md's Build 1 section).
    default_platform_format: str
    # Short, concrete copywriting guidance specific to this platform's real
    # conventions — folded into the CampaignCopy/CarouselPlan prompt so "write
    # for TikTok" means something more specific than "write an Instagram post
    # but shorter". Never a substitute for brand voice/language rules — additive.
    copy_notes: str


PLATFORM_CAPABILITIES: dict[str, PlatformCapability] = {
    "instagram": PlatformCapability(
        key="instagram", label="Instagram",
        content_types=("feed_carousel", "story", "reel"),
        default_platform_format="instagram_square",
        copy_notes=(
            "Visual-first. Hook in the first 3 words of the caption before the 'more' fold. "
            "Carousels work well for step-by-step or before/reason/after structures. Hashtags "
            "(5-15) belong at the end of the caption, not inline."
        ),
    ),
    "facebook": PlatformCapability(
        key="facebook", label="Facebook",
        content_types=("feed_post", "story"),
        default_platform_format="facebook_feed",
        copy_notes=(
            "Slightly longer-form and more conversational than Instagram is tolerated; an older, "
            "more price/offer-sensitive audience on average. Groups and community tone read well; "
            "heavy hashtag use reads as spam here, unlike Instagram."
        ),
    ),
    "tiktok": PlatformCapability(
        key="tiktok", label="TikTok",
        content_types=("short_video",),
        default_platform_format="instagram_story",
        copy_notes=(
            "Spoken-language, hook-in-the-first-second style — write copy as if it will be said "
            "out loud over a video, not read as ad copy. Caption is a short amplifier of the video, "
            "not the main message. Avoid a hard, salesy CTA; native/organic tone performs better."
        ),
    ),
    "youtube_shorts": PlatformCapability(
        key="youtube_shorts", label="YouTube Shorts",
        content_types=("short_video",),
        default_platform_format="instagram_story",
        copy_notes=(
            "Same short-vertical-video format as TikTok, but titles matter more here (Shorts titles "
            "are searchable) — keep the title concrete and keyword-bearing, not just a hook."
        ),
    ),
    "pinterest": PlatformCapability(
        key="pinterest", label="Pinterest",
        content_types=("pin",),
        default_platform_format="instagram_portrait",
        copy_notes=(
            "Written to be found via search, not scrolled past — the pin title and description "
            "should read like a helpful, keyword-rich answer to a real search query, not a hook. "
            "Evergreen tone (this pin may surface in searches for months); avoid urgency/scarcity "
            "language that dates badly."
        ),
    ),
    "linkedin": PlatformCapability(
        key="linkedin", label="LinkedIn",
        content_types=("feed_post",),
        default_platform_format="facebook_feed",
        copy_notes=(
            "Professional register — no slang, no excessive emoji, no hard-sell exclamation points. "
            "Frame around the business/professional angle even for a consumer product (e.g. the "
            "founder's story, sourcing, craftsmanship) rather than a straight product pitch."
        ),
    ),
    "x": PlatformCapability(
        key="x", label="X",
        content_types=("feed_post",),
        default_platform_format="facebook_feed",
        copy_notes=(
            "Short and punchy — a single sharp line beats a paragraph. Conversational, often "
            "topical/reactive tone; hashtags are used sparingly (0-2), not as a discovery tactic."
        ),
    ),
}

DEFAULT_TARGET_PLATFORMS: list[str] = ["instagram"]


def validate_languages(values: list[str]) -> list[str]:
    """Returns `values` unchanged if every entry is a real `SUPPORTED_LANGUAGES`
    value and the list isn't empty; raises `ValueError` (for the API layer to
    turn into a 400) otherwise — never silently drops or substitutes an unknown
    value.
    """
    if not values:
        raise ValueError("At least one language must be selected.")
    unknown = [v for v in values if v not in SUPPORTED_LANGUAGES]
    if unknown:
        raise ValueError(
            f"Unknown language(s) {unknown!r}. Supported: {', '.join(SUPPORTED_LANGUAGES)}."
        )
    return values


def validate_target_platforms(values: list[str]) -> list[str]:
    if not values:
        raise ValueError("At least one target platform must be selected.")
    unknown = [v for v in values if v not in PLATFORM_CAPABILITIES]
    if unknown:
        raise ValueError(
            f"Unknown platform(s) {unknown!r}. Supported: {', '.join(sorted(PLATFORM_CAPABILITIES))}."
        )
    return values
