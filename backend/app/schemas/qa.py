"""Structured-output contracts for Build 3 (MARKETING OS — PLATFORM + LANGUAGE
AWARE MULTIMODAL QA). Same discipline as `schemas/ai.py`/`schemas/creative_
director.py`: every AI response this app depends on for state validates
against one of these, never parsed from free-form text.

Four distinct QA surfaces, matching the spec's own Parts A-D and the carry-
forward requirements:

- `TechnicalQAResult` (Part A) — purely deterministic, no AI involved at all;
  built directly in `services/qa_engine.py::run_technical_qa`, not by an AI
  call, so it has no `model`/prompt-version story of its own.
- `CreativeCritiqueResult` (Part B) — the multimodal structured critic, one
  call per static-image `PlatformCampaignVariant`, scored across every
  dimension the spec named by name.
- `LanguageQAResult` (Part C) — text-only judgment of the actual copy used,
  scoped to hard-fail conditions the spec names by name (wrong language,
  untranslated text, PT-BR/English mixing, broken grammar, literal
  translation, spelling corruption).
- `VideoQAResult` (carry-forward requirement 3 + Part L) — format-appropriate
  QA for a video-oriented, script-only `PlatformCampaignVariant`. Deliberately
  NEVER judges "visual fidelity" of a video file, because no video file is
  ever rendered by this app (`VideoConcept.is_rendered_video` is always
  `False`) — only the structured hook/script/shot-list/etc. text itself, plus
  a cover image's creative quality when one actually exists (it never does
  yet in this app's architecture, so `cover_creative_quality` stays `None`
  rather than a fabricated score).

Every numeric score below is 0-100, always meant to reflect the model's real
judgment; when it can't be produced at all (no AI provider, or the call
fails), the caller in `services/qa_engine.py` returns `None` for the whole
result rather than accepting Pydantic's bare `0` defaults as if they were a
real "this creative scored zero" verdict — the `0` defaults exist only so a
genuinely degenerate/empty parse fails closed (reads as "needs review", never
as "passed") rather than crashing.
"""
from __future__ import annotations

from pydantic import BaseModel


class TechnicalQAResult(BaseModel):
    """Part A: dimensions, valid file, aspect ratio, safe zones, text
    overflow, logo presence, export correctness, platform format
    correctness — for one `PlatformCampaignVariant` as a whole (every
    rendered slide in it), not just one slide. Purely mechanical: built by
    `services/qa_engine.py::run_technical_qa` from the real PNG bytes on disk
    plus the `PlatformCreativeSpec` the variant was rendered against, and the
    per-slide mechanical `CreativeQAResult` reports `services/creative/qa.py`
    already wrote at render time — never a fabricated "passed": true.
    """

    passed: bool
    issues: list[str] = []
    checks: dict[str, bool] = {}

    def to_dict(self) -> dict:
        return {"passed": self.passed, "issues": self.issues, "checks": self.checks}


class CreativeCritiqueResult(BaseModel):
    """Part B: the multimodal structured critic's full scorecard — every
    dimension the spec named by name. `hard_fails` here are the CREATIVE
    dimension's own (e.g. "technically valid but aesthetically weak", "wrong
    product", "bad shadow/light integration" — see carry-forward requirement
    4's finished-asset defect list) — distinct from the deterministic
    platform hard-fails (`services/qa_engine.py::detect_platform_hard_fails`)
    and the language hard-fails (`LanguageQAResult` below), which the caller
    combines with these into one final hard-fail list.

    `revision_targets` names what a failing score should trigger (Part E):
    values this app's own revision logic understands are `"copy"` (rewrite
    just this variant's headline/body/cta) and `"creative_direction"`
    (rewrite just this variant's visual direction and regenerate its scene) —
    an unrecognized value is simply not actioned, never causing a crash.
    """

    overall_quality: int = 0
    brand_alignment: int = 0
    product_fidelity: int = 0
    product_prominence: int = 0
    composition: int = 0
    typography: int = 0
    readability: int = 0
    color_harmony: int = 0
    hierarchy: int = 0
    clutter: int = 0  # higher = cleaner/less cluttered, same "higher is always better" convention as every other score
    copy_visual_fit: int = 0
    cta_visibility: int = 0
    mobile_readability: int = 0
    originality: int = 0
    professional_ad_quality: int = 0
    carousel_consistency: int = 0
    platform_fit: int = 0
    language_naturalness: int = 0
    hard_fails: list[str] = []
    strengths: list[str] = []
    issues: list[str] = []
    revision_targets: list[str] = []
    rationale: str = ""


class LanguageQAResult(BaseModel):
    """Part C: language hard-fail judgment for the actual copy text used by
    one variant. `hard_fails` values are free-text but should name one of the
    spec's own six conditions (wrong language, untranslated text remains,
    PT-BR/English mixing, broken grammar, obvious literal translation,
    spelling corruption) when applicable — `services/qa_engine.py` also runs
    a deterministic identical-text-across-languages check independent of this
    AI call (see `detect_identical_copy_across_languages`), so "untranslated
    text remains" can be caught even with no AI provider at all.
    """

    language_naturalness: int = 0
    hard_fails: list[str] = []
    notes: str = ""


class VideoQAResult(BaseModel):
    """Carry-forward requirement 3 + Part L: format-appropriate QA for a
    script-only, video-oriented variant. Every dimension here judges the
    STRUCTURED TEXT OUTPUT (hook/script/shot-list/timing/on-screen-text/
    caption) — never a claim about visual fidelity of a rendered video, since
    this app renders no video file. `cover_creative_quality` is the one
    dimension that WOULD need an actual image — it stays `None` unless a real
    cover image exists for this variant (never does yet in this
    architecture), per this schema's own module docstring.
    """

    hook_strength: int = 0
    script_coherence: int = 0
    shot_list_completeness: int = 0
    timing_score: int = 0
    on_screen_text_suitability: int = 0
    platform_fit: int = 0
    language_naturalness: int = 0
    factual_accuracy: int = 0
    brand_alignment: int = 0
    cta_effectiveness: int = 0
    cover_creative_quality: int | None = None
    hard_fails: list[str] = []
    issues: list[str] = []
    rationale: str = ""


class RevisedCopy(BaseModel):
    """Part E, targeted copy revision: a rewritten headline/body/cta for ONE
    variant only — `services/qa_engine.py::revise_copy_for_variant` applies
    this to that variant's own stored slide text, never to the shared
    `CampaignOutput(kind="copy")` row every other platform/language reads
    from, so revising English copy never touches Portuguese, and revising
    Instagram's copy never touches Facebook's.
    """

    headline: str
    body: str
    cta: str
