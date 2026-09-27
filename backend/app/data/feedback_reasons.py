"""Structured feedback reason codes (Build 4).

The exact 20 named reasons from the Build 4 spec's "FEEDBACK REASONS" list,
normalized to snake_case codes, plus "other" as a catch-all — 21 total. A
review action's `reason_code` is one of these (or "" when the owner gave only
free text via `reason_text`; see `app/models/review.py::ReviewFeedback`).

`REASON_TO_REVISION_KIND` is this app's own mapping decision (not named by
the spec) used by `services/review_engine.py::apply_requested_revision` to
decide which of Build 3's existing QA-engine revision primitives a
REQUEST_REVISION action should invoke — reusing that Build 3 machinery
(`revise_copy_for_variant` / revise creative direction / re-render /
`revise_video_concept`) rather than building a second revision pipeline.
Every code maps to exactly one of four kinds:

- "copy"               -> `qa_engine.revise_copy_for_variant` (headline/body/
                          CTA/hook/caption wording issues)
- "creative_direction" -> a fresh `_generate_creative_direction` call + a
                          `_regenerate_variant_render`/`_regenerate_with_best_of_n`
                          re-render (visual direction, layout, framing, style)
- "rerender"            -> re-render from the existing creative direction/copy
                           unchanged (used when nothing about *what was asked
                           for* was wrong, only the specific execution — or, for
                           "other", as a safe default that doesn't guess)
- "video_concept"       -> `qa_engine.revise_video_concept` (hook/script/shot
                           list/timing/on-screen text/caption/cover, for
                           SCRIPT_ONLY TikTok/Reels/Shorts variants)

`product_inaccurate` intentionally maps to "rerender" rather than
"creative_direction": if the rendered product doesn't match the real product,
that's usually a source-photo/compositing problem no amount of re-prompted
creative direction can fix automatically — the safest automated action is a
plain re-render attempt, with the reason text preserved for a human to act on
if it recurs.
"""
from __future__ import annotations

FEEDBACK_REASON_CODES: tuple[str, ...] = (
    "too_generic",
    "looks_ai_generated",
    "poor_typography",
    "too_much_text",
    "product_too_small",
    "product_inaccurate",
    "wrong_colors",
    "does_not_match_brand",
    "does_not_feel_japanese",
    "too_corporate",
    "too_formal",
    "unnatural_portuguese",
    "unnatural_english",
    "cta_weak",
    "boring_concept",
    "wrong_platform_style",
    "content_unsuitable_for_tiktok",
    "pinterest_creative_too_horizontal",
    "too_similar_to_previous_campaign",
    "inaccurate_claim",
    "other",
)

# Human-readable labels, in the same order/casing as the spec listed them —
# used only for display (e.g. an API `GET` of the reason list); never used to
# drive any behavior itself.
FEEDBACK_REASON_LABELS: dict[str, str] = {
    "too_generic": "Too generic",
    "looks_ai_generated": "Looks AI-generated",
    "poor_typography": "Poor typography",
    "too_much_text": "Too much text",
    "product_too_small": "Product too small",
    "product_inaccurate": "Product inaccurate",
    "wrong_colors": "Wrong colors",
    "does_not_match_brand": "Does not match brand",
    "does_not_feel_japanese": "Does not feel Japanese",
    "too_corporate": "Too corporate",
    "too_formal": "Too formal",
    "unnatural_portuguese": "Unnatural Portuguese",
    "unnatural_english": "Unnatural English",
    "cta_weak": "CTA weak",
    "boring_concept": "Boring concept",
    "wrong_platform_style": "Wrong platform style",
    "content_unsuitable_for_tiktok": "Content unsuitable for TikTok",
    "pinterest_creative_too_horizontal": "Pinterest creative too horizontal",
    "too_similar_to_previous_campaign": "Too similar to previous campaign",
    "inaccurate_claim": "Inaccurate claim",
    "other": "Other",
}

REASON_TO_REVISION_KIND: dict[str, str] = {
    "too_generic": "creative_direction",
    "looks_ai_generated": "creative_direction",
    "poor_typography": "creative_direction",
    "too_much_text": "copy",
    "product_too_small": "creative_direction",
    "product_inaccurate": "rerender",
    "wrong_colors": "creative_direction",
    "does_not_match_brand": "creative_direction",
    "does_not_feel_japanese": "creative_direction",
    "too_corporate": "creative_direction",
    "too_formal": "copy",
    "unnatural_portuguese": "copy",
    "unnatural_english": "copy",
    "cta_weak": "copy",
    "boring_concept": "creative_direction",
    "wrong_platform_style": "creative_direction",
    "content_unsuitable_for_tiktok": "video_concept",
    "pinterest_creative_too_horizontal": "creative_direction",
    "too_similar_to_previous_campaign": "creative_direction",
    "inaccurate_claim": "copy",
    "other": "rerender",
}

REVISION_KINDS: tuple[str, ...] = ("copy", "creative_direction", "rerender", "video_concept")


def revision_kind_for(reason_code: str) -> str:
    """Safe default of "rerender" for an unrecognized/blank reason_code — never
    raises, since a REQUEST_REVISION with only free-text `reason_text` (no
    structured code) is a valid, spec-supported case, not an error.
    """
    return REASON_TO_REVISION_KIND.get(reason_code, "rerender")
