"""Build 2 (Parts A/B of MARKETING OS — PLATFORM ADAPTER + CREATIVE DIRECTOR +
HYBRID VISUAL ENGINE): the canonical TARGET PLATFORM -> CONTENT TYPE -> RENDER
FORMAT resolver.

This is a NEW, separate concept from the two Build-1-and-earlier registries it
sits alongside — deliberately not collapsed into either:

- `data/platform_capabilities.py::PLATFORM_CAPABILITIES` — which real-world
  marketing platform(s) a *campaign* targets, and broad copywriting guidance
  per platform (Build 1, Parts B/C). Keeps its own, coarser `content_types`
  tuple used only for copy-prompt grounding (`_platform_requirements_note`).
- `services/creative/templates.py::PLATFORM_FORMATS` — pixel-exact render
  canvases (width/height), addressed by a flat `platform_key` string
  (`Campaign.platform_key`, `AutopilotConfig.platform_key`).

`PlatformCreativeSpec` is the missing middle layer: for one (platform,
content_type) pair, it says whether that content is even renderable as a
static image today, which `PLATFORM_FORMATS` key to render it at when it is,
and the structural creative rules (copy density, safe zones, slide-count,
caption/CTA style, whether a cover frame or a script is required) that the new
Platform Adapter / Creative Director (`services/creative_director.py`) and the
multi-variant renderer (`services/orchestrator.py::_render_additional_
platform_variants`) both read from — never scattered ad hoc across those
modules.

Only content types the current architecture can genuinely support are given a
`render_format_key` (a real static image, composited and rendered by the
existing hybrid pipeline). Video-oriented content types (`short_video_concept`
and friends) are represented too — structurally, so platforms like TikTok/
YouTube Shorts aren't silently absent from this catalog — but with
`supports_static=False` and `script_required=True`: this app does not, and
must not pretend to, generate an actual video file. See `schemas/ai.py::
VideoConcept` and `services/orchestrator.py::generate_video_concept` for the
structured hook/script/shot-list output produced for those instead.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PlatformCreativeSpec:
    platform: str
    content_type: str
    label: str
    # Pixel canvas, when this content type renders as a static image — mirrors
    # `services/creative/templates.py::PlatformFormat`, and `render_format_key`
    # names exactly which `PLATFORM_FORMATS` entry supplies these dimensions
    # (kept here too so a caller never needs to cross-reference both modules
    # just to know a spec's own shape). Both are 0 / "" for a script-only
    # content type — never a fabricated placeholder size.
    width: int = 0
    height: int = 0
    render_format_key: str = ""
    aspect_ratio: str = ""
    max_copy_density: str = "medium"  # "low" | "medium" | "high" — how much on-slide text this format tolerates well
    safe_zones: tuple[str, ...] = ()  # e.g. "avoid_bottom_20pct" for a UI-overlay-heavy surface (Stories, Shorts)
    supports_carousel: bool = False
    supports_static: bool = False
    supports_short_video: bool = False
    supports_story: bool = False
    recommended_slide_count: int = 1
    caption_style: str = ""
    cta_style: str = ""
    visual_hierarchy: str = ""
    cover_required: bool = False
    script_required: bool = False


def _static(
    platform: str, content_type: str, label: str, *, render_format_key: str, width: int, height: int,
    aspect_ratio: str, max_copy_density: str, supports_carousel: bool = False, supports_story: bool = False,
    recommended_slide_count: int = 1, caption_style: str, cta_style: str, visual_hierarchy: str,
    cover_required: bool = False, safe_zones: tuple[str, ...] = (),
) -> PlatformCreativeSpec:
    return PlatformCreativeSpec(
        platform=platform, content_type=content_type, label=label, width=width, height=height,
        render_format_key=render_format_key, aspect_ratio=aspect_ratio, max_copy_density=max_copy_density,
        safe_zones=safe_zones, supports_carousel=supports_carousel, supports_static=True,
        supports_short_video=False, supports_story=supports_story, recommended_slide_count=recommended_slide_count,
        caption_style=caption_style, cta_style=cta_style, visual_hierarchy=visual_hierarchy,
        cover_required=cover_required, script_required=False,
    )


def _video_concept(
    platform: str, content_type: str, label: str, *, caption_style: str, cta_style: str, visual_hierarchy: str,
    cover_required: bool = True,
) -> PlatformCreativeSpec:
    """A content type this app represents structurally (hook/script/shot-list,
    see `VideoConcept`) but never renders as an actual video file — see this
    module's docstring. `supports_static=False` is what routes the multi-variant
    renderer to the script-only path instead of the image pipeline.
    """
    return PlatformCreativeSpec(
        platform=platform, content_type=content_type, label=label, width=0, height=0, render_format_key="",
        aspect_ratio="9:16", max_copy_density="low", safe_zones=("avoid_bottom_20pct", "avoid_top_10pct"),
        supports_carousel=False, supports_static=False, supports_short_video=True, supports_story=False,
        recommended_slide_count=1, caption_style=caption_style, cta_style=cta_style,
        visual_hierarchy=visual_hierarchy, cover_required=cover_required, script_required=True,
    )


def _text_only(platform: str, content_type: str, label: str, *, caption_style: str, cta_style: str) -> PlatformCreativeSpec:
    """A pure-copy content type with no creative asset of its own (a pin's SEO
    title/description, a thread's individual posts) — `supports_static=False`
    and `script_required=False` alike: there's nothing for the multi-variant
    renderer OR the video-script path to produce here, this is copy-stage
    territory (`CampaignCopy.caption`), not a `PlatformCampaignVariant`.
    """
    return PlatformCreativeSpec(
        platform=platform, content_type=content_type, label=label, max_copy_density="low",
        caption_style=caption_style, cta_style=cta_style, visual_hierarchy="text-led, no image asset",
    )


# ---------------------------------------------------------------------------
# Instagram
# ---------------------------------------------------------------------------
_INSTAGRAM = {
    "feed_post": _static(
        "instagram", "feed_post", "Instagram Feed Post", render_format_key="instagram_square",
        width=1080, height=1080, aspect_ratio="1:1", max_copy_density="medium",
        caption_style="hook-first, 5-15 hashtags at the end", cta_style="soft, link-in-bio or Shop tag",
        visual_hierarchy="product hero centered, headline upper third",
    ),
    "carousel": _static(
        "instagram", "carousel", "Instagram Carousel", render_format_key="instagram_portrait",
        width=1080, height=1350, aspect_ratio="4:5", max_copy_density="medium", supports_carousel=True,
        recommended_slide_count=6, caption_style="hook-first, step-by-step or before/reason/after structure",
        cta_style="soft, swipe-to-see / link-in-bio", visual_hierarchy="one idea per slide, consistent visual system",
    ),
    "story": _static(
        "instagram", "story", "Instagram Story", render_format_key="instagram_story",
        width=1080, height=1920, aspect_ratio="9:16", max_copy_density="low", supports_story=True,
        caption_style="short, casual, sticker/poll-friendly", cta_style="swipe-up / link sticker",
        visual_hierarchy="full-bleed image, text kept out of top/bottom UI-overlay zones",
        safe_zones=("avoid_bottom_20pct", "avoid_top_10pct"),
    ),
    "reel_cover": _static(
        "instagram", "reel_cover", "Instagram Reel Cover", render_format_key="instagram_portrait",
        width=1080, height=1350, aspect_ratio="4:5", max_copy_density="low", cover_required=True,
        caption_style="one punchy line, large type", cta_style="implicit — the cover sells the tap, not a CTA",
        visual_hierarchy="single dominant visual + short headline, must read at thumbnail size",
    ),
    "reel_script_caption": _video_concept(
        "instagram", "reel_script_caption", "Instagram Reel Script + Caption",
        caption_style="hook in the first line, short paragraphs, 3-5 hashtags",
        cta_style="spoken CTA in the script, reinforced softly in the caption",
        visual_hierarchy="hook shot first 1-2 seconds, then a clear shot progression",
    ),
}

# ---------------------------------------------------------------------------
# Facebook
# ---------------------------------------------------------------------------
_FACEBOOK = {
    "feed_post": _static(
        "facebook", "feed_post", "Facebook Feed Post", render_format_key="facebook_feed",
        width=1200, height=630, aspect_ratio="1.91:1", max_copy_density="medium",
        caption_style="slightly longer-form, conversational, minimal hashtags",
        cta_style="direct — price/offer-forward is tolerated here",
        visual_hierarchy="product hero with room for a headline band",
    ),
    "multi_image_campaign": _static(
        "facebook", "multi_image_campaign", "Facebook Multi-Image Campaign",
        render_format_key="facebook_feed", width=1200, height=630, aspect_ratio="1.91:1",
        max_copy_density="medium", supports_carousel=True, recommended_slide_count=4,
        caption_style="one campaign narrative spread across images, conversational",
        cta_style="direct, offer-forward", visual_hierarchy="consistent visual system across all images",
    ),
    "promotional_creative": _static(
        "facebook", "promotional_creative", "Facebook Promotional Creative",
        render_format_key="facebook_feed", width=1200, height=630, aspect_ratio="1.91:1",
        max_copy_density="high", caption_style="offer-led, price/discount-forward when genuinely true",
        cta_style="direct, urgency only when honestly warranted",
        visual_hierarchy="offer/badge given equal weight to the product",
    ),
}

# ---------------------------------------------------------------------------
# TikTok
# ---------------------------------------------------------------------------
_TIKTOK = {
    "short_video_concept": _video_concept(
        "tiktok", "short_video_concept", "TikTok Short-Video Concept",
        caption_style="short amplifier of the video, not the main message",
        cta_style="native/organic, avoid a hard salesy CTA",
        visual_hierarchy="hook in the first second, fast shot progression",
    ),
    "script": _video_concept(
        "tiktok", "script", "TikTok Script", cover_required=False,
        caption_style="spoken-language, written to be said out loud",
        cta_style="native, avoid a hard salesy CTA", visual_hierarchy="scene-by-scene beats, no cover needed alone",
    ),
    "shot_list": _video_concept(
        "tiktok", "shot_list", "TikTok Shot List", cover_required=False,
        caption_style="n/a — production reference, not audience-facing copy",
        cta_style="n/a", visual_hierarchy="ordered list of concrete shots/angles/durations",
    ),
    "cover": _static(
        "tiktok", "cover", "TikTok Cover", render_format_key="instagram_story",
        width=1080, height=1920, aspect_ratio="9:16", max_copy_density="low", cover_required=True,
        caption_style="one punchy line, large type", cta_style="implicit — the cover sells the tap",
        visual_hierarchy="single dominant visual, must read at thumbnail size",
        safe_zones=("avoid_bottom_20pct", "avoid_top_10pct"),
    ),
    "caption": _text_only(
        "tiktok", "caption", "TikTok Caption",
        caption_style="short amplifier of the video, 3-5 hashtags", cta_style="native, soft",
    ),
}

# ---------------------------------------------------------------------------
# YouTube Shorts
# ---------------------------------------------------------------------------
_YOUTUBE_SHORTS = {
    "short_video_concept": _video_concept(
        "youtube_shorts", "short_video_concept", "YouTube Shorts Concept",
        caption_style="title matters more than caption — searchable, keyword-bearing",
        cta_style="native, subscribe/next-video soft CTA", visual_hierarchy="hook in the first second",
    ),
    "script": _video_concept(
        "youtube_shorts", "script", "YouTube Shorts Script", cover_required=False,
        caption_style="spoken-language", cta_style="native", visual_hierarchy="scene-by-scene beats",
    ),
    "title": _text_only(
        "youtube_shorts", "title", "YouTube Shorts Title",
        caption_style="concrete, keyword-bearing, searchable — not just a hook", cta_style="n/a",
    ),
    "description": _text_only(
        "youtube_shorts", "description", "YouTube Shorts Description",
        caption_style="short, keyword-bearing summary plus links", cta_style="soft, link-forward",
    ),
    "cover": _static(
        "youtube_shorts", "cover", "YouTube Shorts Cover", render_format_key="instagram_story",
        width=1080, height=1920, aspect_ratio="9:16", max_copy_density="low", cover_required=True,
        caption_style="one punchy line, large type", cta_style="implicit — the cover sells the tap",
        visual_hierarchy="single dominant visual, must read at thumbnail size",
        safe_zones=("avoid_bottom_20pct", "avoid_top_10pct"),
    ),
}

# ---------------------------------------------------------------------------
# Pinterest
# ---------------------------------------------------------------------------
_PINTEREST = {
    "pin": _static(
        "pinterest", "pin", "Pinterest Pin", render_format_key="pinterest_vertical",
        width=1000, height=1500, aspect_ratio="2:3", max_copy_density="low",
        caption_style="written to be found via search, evergreen, no urgency/scarcity language",
        cta_style="informational, helpful-answer framing rather than a hook",
        visual_hierarchy="tall vertical composition, headline near the top",
    ),
    "vertical_creative": _static(
        "pinterest", "vertical_creative", "Pinterest Vertical Creative",
        render_format_key="pinterest_vertical", width=1000, height=1500, aspect_ratio="2:3",
        max_copy_density="low", caption_style="evergreen, keyword-rich",
        cta_style="informational", visual_hierarchy="tall vertical composition",
    ),
    "pin_title": _text_only(
        "pinterest", "pin_title", "Pinterest Pin Title",
        caption_style="keyword-rich, reads like a helpful search answer", cta_style="n/a",
    ),
    "pin_description": _text_only(
        "pinterest", "pin_description", "Pinterest Pin Description",
        caption_style="keyword-rich, evergreen, avoid dated urgency language", cta_style="soft",
    ),
}

# ---------------------------------------------------------------------------
# LinkedIn
# ---------------------------------------------------------------------------
_LINKEDIN = {
    "image_post": _static(
        "linkedin", "image_post", "LinkedIn Image Post", render_format_key="facebook_feed",
        width=1200, height=630, aspect_ratio="1.91:1", max_copy_density="medium",
        caption_style="professional register, no slang, no excessive emoji",
        cta_style="soft, business/professional framing rather than a hard sell",
        visual_hierarchy="product framed through a business/professional angle",
    ),
    "educational_post": _static(
        "linkedin", "educational_post", "LinkedIn Educational Post", render_format_key="facebook_feed",
        width=1200, height=630, aspect_ratio="1.91:1", max_copy_density="high",
        caption_style="professional, informative, no hard-sell exclamation points",
        cta_style="soft, learn-more framing", visual_hierarchy="information-dense, diagram-friendly",
    ),
    "carousel_document_concept": _static(
        "linkedin", "carousel_document_concept", "LinkedIn Carousel / Document Concept",
        render_format_key="facebook_feed", width=1200, height=630, aspect_ratio="1.91:1",
        max_copy_density="high", supports_carousel=True, recommended_slide_count=5,
        caption_style="professional, structured, one idea per slide",
        cta_style="soft, learn-more/download framing",
        visual_hierarchy="document-style slides, consistent professional visual system",
    ),
}

# ---------------------------------------------------------------------------
# X
# ---------------------------------------------------------------------------
_X = {
    "image_post": _static(
        "x", "image_post", "X Image Post", render_format_key="facebook_feed",
        width=1200, height=630, aspect_ratio="1.91:1", max_copy_density="low",
        caption_style="short and punchy, a single sharp line beats a paragraph",
        cta_style="conversational, sparse hashtags (0-2)",
        visual_hierarchy="single strong visual, minimal on-image text",
    ),
    "short_post": _text_only(
        "x", "short_post", "X Short Post",
        caption_style="short and punchy, conversational/topical", cta_style="sparse, 0-2 hashtags",
    ),
    "thread": _text_only(
        "x", "thread", "X Thread",
        caption_style="a numbered sequence of short, punchy posts, one idea per post", cta_style="soft, at the end only",
    ),
}

PLATFORM_CONTENT_TYPES: dict[str, dict[str, PlatformCreativeSpec]] = {
    "instagram": _INSTAGRAM,
    "facebook": _FACEBOOK,
    "tiktok": _TIKTOK,
    "youtube_shorts": _YOUTUBE_SHORTS,
    "pinterest": _PINTEREST,
    "linkedin": _LINKEDIN,
    "x": _X,
}

# Which content type `services/orchestrator.py`'s multi-variant renderer picks
# by default for a given platform, as a function of how many slides the Copy
# stage actually planned — never user-facing config in this build (no new
# frontend picker was added), just the sensible default per platform's real
# conventions. A platform not listed here has no safe default content type yet.
_CAROUSEL_CONTENT_TYPE = {
    "instagram": "carousel",
    "facebook": "multi_image_campaign",
    "linkedin": "carousel_document_concept",
}
_SINGLE_CONTENT_TYPE = {
    "instagram": "feed_post",
    "facebook": "feed_post",
    "pinterest": "pin",
    "linkedin": "image_post",
    "x": "image_post",
    "tiktok": "short_video_concept",
    "youtube_shorts": "short_video_concept",
}


def default_content_type_for_platform(platform: str, *, slide_count: int) -> str | None:
    """The content type `_render_additional_platform_variants` targets for one
    platform, given how many slides the Copy stage planned — a multi-slide plan
    prefers that platform's carousel-shaped content type when it has one (e.g.
    Instagram carousel, Facebook multi-image campaign), otherwise its default
    single-asset type. Returns `None` for a platform this catalog doesn't cover
    at all (shouldn't happen — `target_platforms` is validated against
    `PLATFORM_CAPABILITIES`, whose keys are exactly this dict's keys).
    """
    if platform not in PLATFORM_CONTENT_TYPES:
        return None
    if slide_count > 1 and platform in _CAROUSEL_CONTENT_TYPE:
        return _CAROUSEL_CONTENT_TYPE[platform]
    return _SINGLE_CONTENT_TYPE.get(platform)


def resolve_platform_creative_spec(platform: str, content_type: str) -> PlatformCreativeSpec:
    by_platform = PLATFORM_CONTENT_TYPES.get(platform)
    if by_platform is None:
        raise ValueError(f"Unknown platform {platform!r}. Supported: {', '.join(sorted(PLATFORM_CONTENT_TYPES))}.")
    spec = by_platform.get(content_type)
    if spec is None:
        raise ValueError(
            f"Unknown content type {content_type!r} for platform {platform!r}. "
            f"Supported: {', '.join(sorted(by_platform))}."
        )
    return spec


def list_content_types_for_platform(platform: str) -> list[str]:
    return sorted(PLATFORM_CONTENT_TYPES.get(platform, {}))
