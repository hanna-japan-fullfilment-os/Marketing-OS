"""Build 5, Part D — PLATFORM-SPECIFIC SCORING.

"Different platforms may weight factors differently... Do not create
arbitrary opaque weights without documentation." This module is the one
place those weights live, as plain, named, documented dicts — never computed
on the fly, never hidden inside `services/benchmark_engine.py`'s own logic.

Weights operate on the SAME dimension names Build 3's QA engine already
produces (`schemas/qa.py::CreativeCritiqueResult` for a static/image variant,
`VideoQAResult` for a script-only video-oriented variant) — this module
invents no new scoring dimension of its own, only how much each existing one
counts for a given platform's real conventions:

- **Pinterest**: vertical composition and discovery appeal matter more than a
  typical feed post — weighted toward `composition`, `originality` (a proxy
  for "will this stand out in a discovery feed"), and `platform_fit`.
- **TikTok / YouTube Shorts** (video-oriented, scored via `VideoQAResult`):
  hook/script strength matters strongly — weighted toward `hook_strength` and
  `script_coherence`.
- **Instagram**: visual quality and carousel storytelling matter strongly —
  weighted toward `composition`, `carousel_consistency`, and
  `professional_ad_quality`.
- **LinkedIn**: clarity and professional relevance matter more — weighted
  toward `readability`, `professional_ad_quality`, and `copy_visual_fit`.
- Every other platform (Facebook, X, and any platform not named above) gets
  `_DEFAULT_STATIC_WEIGHTS` — a balanced weighting across the dimensions that
  matter for any static creative, so an unlisted platform never silently
  falls back to a hidden all-or-nothing rule.

A weight table need not sum to any particular total — `compute_platform_
weighted_score` normalizes by the sum of weights actually matched, so a
partial scorecard (a dimension the QA critic didn't score, still `0` by
schema default but excluded here when genuinely absent from `qa_scores`)
never silently drags the score toward zero.
"""
from __future__ import annotations

_DEFAULT_STATIC_WEIGHTS: dict[str, float] = {
    "overall_quality": 3.0,
    "brand_alignment": 2.0,
    "product_fidelity": 2.0,
    "composition": 1.5,
    "copy_visual_fit": 1.5,
    "cta_visibility": 1.0,
    "platform_fit": 1.5,
    "language_naturalness": 1.5,
}

_STATIC_PLATFORM_WEIGHTS: dict[str, dict[str, float]] = {
    "pinterest": {
        "overall_quality": 2.0,
        "composition": 3.0,
        "originality": 2.5,
        "platform_fit": 2.5,
        "product_fidelity": 1.5,
        "language_naturalness": 1.0,
    },
    "instagram": {
        "overall_quality": 2.0,
        "composition": 2.5,
        "carousel_consistency": 2.5,
        "professional_ad_quality": 2.0,
        "brand_alignment": 1.5,
        "product_fidelity": 1.5,
        "language_naturalness": 1.0,
    },
    "linkedin": {
        "overall_quality": 2.0,
        "readability": 2.5,
        "professional_ad_quality": 2.5,
        "copy_visual_fit": 2.0,
        "brand_alignment": 1.5,
        "language_naturalness": 1.0,
    },
    "facebook": dict(_DEFAULT_STATIC_WEIGHTS),
    "x": dict(_DEFAULT_STATIC_WEIGHTS),
}

# Video-oriented platforms (script-only, `VideoQAResult` dimensions) — hook +
# script strength weighted heavily, per this module's own docstring.
_VIDEO_PLATFORM_WEIGHTS: dict[str, dict[str, float]] = {
    "tiktok": {
        "hook_strength": 3.0,
        "script_coherence": 2.5,
        "platform_fit": 2.0,
        "shot_list_completeness": 1.5,
        "cta_effectiveness": 1.5,
        "language_naturalness": 1.5,
        "factual_accuracy": 1.5,
        "brand_alignment": 1.0,
    },
    "youtube_shorts": {
        "hook_strength": 2.5,
        "script_coherence": 2.5,
        "platform_fit": 2.0,
        "shot_list_completeness": 2.0,
        "timing_score": 1.5,
        "cta_effectiveness": 1.5,
        "language_naturalness": 1.5,
        "factual_accuracy": 1.5,
        "brand_alignment": 1.0,
    },
}

_DEFAULT_VIDEO_WEIGHTS: dict[str, float] = {
    "hook_strength": 2.0,
    "script_coherence": 2.0,
    "platform_fit": 1.5,
    "shot_list_completeness": 1.5,
    "timing_score": 1.0,
    "cta_effectiveness": 1.0,
    "language_naturalness": 1.0,
    "factual_accuracy": 1.0,
    "brand_alignment": 1.0,
}


def weights_for(platform: str, *, is_video: bool) -> dict[str, float]:
    """The documented weight table for one platform — never computed, always
    one of the named dicts above (or its named default).
    """
    if is_video:
        return dict(_VIDEO_PLATFORM_WEIGHTS.get(platform, _DEFAULT_VIDEO_WEIGHTS))
    return dict(_STATIC_PLATFORM_WEIGHTS.get(platform, _DEFAULT_STATIC_WEIGHTS))


def compute_platform_weighted_score(platform: str, qa_scores: dict) -> dict:
    """Turns one variant's raw `qa_scores` (as stored on `PlatformCampaign
    Variant.qa_scores` / snapshotted onto `BenchmarkRun.qa_scores`) into a
    single platform-weighted score using this platform's own documented
    weight table.

    `qa_scores` is expected in the shape `qa_engine.py` actually writes:
    `{"overall": int, "creative": {...CreativeCritiqueResult dims...},
    "language": {...}}` for a static variant, or `{"overall": int, "video":
    {...VideoQAResult dims...}}` for a script-only one. Returns `{"weighted_
    score": float | None, "weights_used": dict, "dimensions_scored": dict}` —
    `None` (never a fabricated `0`) when there's nothing to score at all
    (e.g. `qa_scores` is empty because QA never ran).
    """
    qa_scores = qa_scores or {}
    is_video = "video" in qa_scores
    dims: dict = {}
    if is_video and qa_scores.get("video"):
        dims = dict(qa_scores["video"])
    elif qa_scores.get("creative"):
        dims = dict(qa_scores["creative"])
        # `overall_quality` lives on the creative critique itself; `overall`
        # (the campaign-wide combined score qa_engine.py computes, blending
        # technical/platform/language hard-fail deductions in too) is kept
        # available under its own key for weight tables that reference it.
    if "overall" in qa_scores and qa_scores["overall"] is not None:
        dims.setdefault("overall_quality", qa_scores["overall"])

    weights = weights_for(platform, is_video=is_video)
    matched = {dim: (weight, dims[dim]) for dim, weight in weights.items() if dim in dims and dims[dim] is not None}
    if not matched:
        return {"weighted_score": None, "weights_used": weights, "dimensions_scored": {}}

    total_weight = sum(weight for weight, _ in matched.values())
    weighted_sum = sum(weight * score for weight, score in matched.values())
    weighted_score = round(weighted_sum / total_weight, 2) if total_weight else None
    return {
        "weighted_score": weighted_score,
        "weights_used": {dim: weight for dim, (weight, _) in matched.items()},
        "dimensions_scored": {dim: score for dim, (_, score) in matched.items()},
    }
