"""Campaign Copy Prompt Versioning (Build 1, Part I).

`models/platform.py::PromptVersion` has existed since round 1 but was
confirmed (round-20+ audit) to be dead code — defined in the model and schema,
never read or written by anything. This module is what actually uses it: a
small, versioned registry of this app's AI prompts (today: the ones
`services/orchestrator.py::run_copy_stage` builds), plus a `record_prompt_usage`
helper that logs which version, language, and platform produced a given
campaign's copy — so a campaign's `CampaignOutput`/`AuditEvent` history can
answer "which prompt version, in which language, for which platform, generated
this?" after the fact.

Deliberately NOT a change to `AIProvider.generate_structured`'s signature
(`services/ai/base.py` — a fixed Protocol with no room for extra kwargs; see
that module's docstring). Prompt content itself is still built as plain
`system`/`user` strings inside `run_copy_stage`; this registry only tracks
*which named, versioned prompt* those strings represent, recorded out-of-band
via `AuditEvent` rather than threaded through the AI-call signature.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from ..models import AuditEvent, PromptVersion


@dataclass(frozen=True)
class PromptSpec:
    purpose: str
    version: str
    file_path: str
    variables: list[str]
    change_notes: str
    # Build 5, Part A: [] means "applies to every platform"/"every language"
    # (most purposes below) — a non-empty list scopes a purpose that
    # structurally only ever fires for those platforms/languages (e.g.
    # `video_concept` only ever runs for TikTok/YouTube Shorts, per
    # `data/platform_creative_specs.py`'s own `supports_static=False` set).
    # `active=False` marks a purpose retired without deleting its row/history.
    platform_applicability: list[str] = field(default_factory=list)
    language_applicability: list[str] = field(default_factory=list)
    active: bool = True


# Bump `version` (and update `change_notes`) whenever the actual prompt text in
# `services/orchestrator.py::run_copy_stage` changes in a way worth tracing a
# past campaign's copy back to — not on every unrelated orchestrator edit.
PROMPT_VERSIONS: dict[str, PromptSpec] = {
    "campaign_copy": PromptSpec(
        purpose="campaign_copy",
        version='1.6.0',
        file_path="services/orchestrator.py::run_copy_stage (CampaignCopy)",
        variables=[
            "brand_name", "brand_voice", "brand_language_rules", "brand_preferred_ctas",
            "brand_disallowed_terms", "brand_disclaimers", "brand_target_audiences",
            "brand_target_countries", "brand_creative_instructions", "verified_product_facts",
            "strategy_objective", "strategy_audience", "strategy_funnel_stage", "strategy_insight",
            "strategy_angle", "strategy_key_message", "strategy_reason_this_should_work",
            "research_insights", "platform_key", "platform_content_types", "platform_copy_notes",
            "language",
        ],
        change_notes=(
            ((((("Build 1 (Part E/F): brand/product-facts/strategy/research/platform/language grounding "
            "all reach this prompt for the first time; pt-BR and en each get independently "
            "language-native instructions (Part F) instead of one shared prompt.") + ' Build 6R sparse-fact grounding hardening: unknown facts remain unknown; research, category, product notes, and upstream AI output are not product-fact evidence; visual briefs obey the same verified-facts boundary.' + ' Build 6R Stage 3D anti-inference hardening: shared verified-facts grounding now explicitly forbids temporal/routine inference, package-purpose inference, purchase-behavior inference, subjective quality/comfort inference, and unverified usage modifiers.' + ' Build 6R V3.23 residual semantic-boundary hardening: prohibit unsupported evaluative positioning, preserve same-field exosome/no-stem qualification, and keep planning metadata separate from product-fact evidence.' + ' Build 6R V3.26 residual taxonomy/non-claim hardening: route only canonically grounded residual taxonomy drift through sealed evaluators; reject unsupported comparative/superlative rhetoric; and prohibit rhetorical comparison hooks unless verified comparison evidence explicitly supports every comparative relation.' + ' Build 6R V3.27 canonical usage/ingredient taxonomy and meta-provenance generation hardening: route residual instructions_or_directions only through complete canonical verified_usage proof; allow explicit ingredient lists only when every listed ingredient is canonical; keep deictic ingredient references, endorsement/meta-provenance copy, research-derived facts, and stem/exosome safety boundaries fail-closed; harden shared generation wording accordingly.'))))
        ),
    ),
    "carousel_plan": PromptSpec(
        purpose="carousel_plan",
        version='1.6.0',
        file_path="services/orchestrator.py::run_copy_stage (CarouselPlan)",
        variables=[
            "brand_name", "brand_voice", "verified_product_facts", "strategy_angle",
            "strategy_key_message", "platform_key", "platform_content_types", "language",
            "target_slide_count",
        ],
        change_notes=((((("Build 1 (Part E/F): same grounding expansion as campaign_copy, generated per language.") + ' Build 6R sparse-fact grounding hardening: unknown facts remain unknown; research, category, product notes, and upstream AI output are not product-fact evidence; visual briefs obey the same verified-facts boundary.' + ' Build 6R Stage 3D anti-inference hardening: shared verified-facts grounding now explicitly forbids temporal/routine inference, package-purpose inference, purchase-behavior inference, subjective quality/comfort inference, and unverified usage modifiers.' + ' Build 6R V3.23 residual semantic-boundary hardening: prohibit unsupported evaluative positioning, preserve same-field exosome/no-stem qualification, and keep planning metadata separate from product-fact evidence.' + ' Build 6R V3.26 residual taxonomy/non-claim hardening: route only canonically grounded residual taxonomy drift through sealed evaluators; reject unsupported comparative/superlative rhetoric; and prohibit rhetorical comparison hooks unless verified comparison evidence explicitly supports every comparative relation.' + ' Build 6R V3.27 canonical usage/ingredient taxonomy and meta-provenance generation hardening: route residual instructions_or_directions only through complete canonical verified_usage proof; allow explicit ingredient lists only when every listed ingredient is canonical; keep deictic ingredient references, endorsement/meta-provenance copy, research-derived facts, and stem/exosome safety boundaries fail-closed; harden shared generation wording accordingly.')))),
    ),
    "master_campaign_concept": PromptSpec(
        purpose="master_campaign_concept",
        version='1.7.0',
        file_path="services/orchestrator.py::run_copy_stage (MasterCampaignConcept)",
        variables=[
            "strategy_angle", "strategy_key_message", "strategy_audience", "strategy_objective",
            "strategy_reason_this_should_work", "creative_brief_design_concept", "brand_visual_style",
            "brand_creative_instructions",
            "verified_product_facts",
            "research_insights",
            "product_category_context",
            "campaign_archetype_catalog",
        ],
        change_notes=(
            ((((("Build 2 (Part E): the ONE campaign concept generated once per campaign and held constant "
            "across every platform/language adaptation — deliberately platform- and language-agnostic.") + ' Build 6R sparse-fact grounding hardening: unknown facts remain unknown; research, category, product notes, and upstream AI output are not product-fact evidence; visual briefs obey the same verified-facts boundary.' + ' Build 6R Stage 3D anti-inference hardening: shared verified-facts grounding now explicitly forbids temporal/routine inference, package-purpose inference, purchase-behavior inference, subjective quality/comfort inference, and unverified usage modifiers.' + ' Build 6R V3.23 residual semantic-boundary hardening: prohibit unsupported evaluative positioning, preserve same-field exosome/no-stem qualification, and keep planning metadata separate from product-fact evidence.' + ' Build 6R V3.26 residual taxonomy/non-claim hardening: route only canonically grounded residual taxonomy drift through sealed evaluators; reject unsupported comparative/superlative rhetoric; and prohibit rhetorical comparison hooks unless verified comparison evidence explicitly supports every comparative relation.' + ' Build 6R V3.27 canonical usage/ingredient taxonomy and meta-provenance generation hardening: route residual instructions_or_directions only through complete canonical verified_usage proof; allow explicit ingredient lists only when every listed ingredient is canonical; keep deictic ingredient references, endorsement/meta-provenance copy, research-derived facts, and stem/exosome safety boundaries fail-closed; harden shared generation wording accordingly.'))))
        ),
    ),
    "platform_adaptation": PromptSpec(
        purpose="platform_adaptation",
        version="1.2.0",
        file_path="services/orchestrator.py::_resolve_platform_adaptation (PlatformAdaptation)",
        variables=["verified_product_facts", 
            "master_concept_name", "master_concept_promise", "master_concept_key_message",
            "master_concept_story_arc", "master_concept_visual_identity", "target_platform",
            "platform_label", "content_type", "platform_copy_notes",
            "product_category_context",
            "campaign_archetype",
            "visual_story_system",
            "hero_treatment",
            "proof_or_demo_strategy",
        ],
        change_notes=(
            "Build 2 (Part F): adapts the master concept to one platform's real conventions, once per "
            "(campaign, platform) — shared across that platform's targeted languages."
        ),
    ),
    "creative_direction": PromptSpec(
        purpose="creative_direction",
        version="1.2.0",
        file_path="services/orchestrator.py::_generate_creative_direction (CreativeDirection)",
        variables=["verified_product_facts", 
            "master_concept_name", "master_concept_promise", "master_concept_visual_identity", "platform",
            "adaptation_strategy", "adaptation_narrative_shape", "language", "content_type", "slide_purpose",
            "slide_headline", "slide_visual_brief",
            "product_category_context",
            "campaign_archetype",
            "archetype_reasoning",
            "visual_story_system",
            "hero_treatment",
            "proof_or_demo_strategy",
        ],
        change_notes=(
            "Build 2 (Part G/H): the concrete visual/layout direction for one (platform, language, slide) "
            "variant — generated once PER language (never shared), so typography/layout can genuinely "
            "differ between e.g. pt-BR and en."
        ),
    ),
    "video_concept": PromptSpec(
        purpose="video_concept",
        version="1.0.0",
        file_path="services/orchestrator.py::generate_video_concept (VideoConcept)",
        variables=[
            "master_concept_name", "master_concept_promise", "master_concept_key_message", "target_platform",
            "platform_label", "language", "adaptation_strategy", "platform_copy_notes",
        ],
        change_notes=(
            "Build 2 (Part L): the structured hook/script/shot-list output for a video-oriented content "
            "type (TikTok/YouTube Shorts) that this app does not render as an actual video file."
        ),
        platform_applicability=["tiktok", "youtube_shorts"],
    ),
    "scene_generation": PromptSpec(
        purpose="scene_generation",
        version="1.1.0",
        file_path=(
            "services/orchestrator.py::generate_ai_background / recreate_creative_image / "
            "recreate_creative_image_with_fidelity_gate (the scene/image-generation RECIPE)"
        ),
        variables=[
            "creative_direction_background_concept", "creative_direction_lighting", "creative_direction_mood",
            "creative_direction_scene_generation_prompt", "master_campaign_concept_visual_identity",
            "platform_creative_spec_render_format", "brand_visual_style", "brand_colors",
            "brand_visual_reference_photos", "brand_inspiration_examples", "visual_master_reference",
            "source_product_preservation_requirement", "composition_and_depth_requirement",
            "negative_space_requirement", "lighting_requirement", "background_scene_concept",
            "prohibited_elements", "claims_safety_negative_constraints", "quality_tier",
            "product_category_context",
            "campaign_archetype",
            "archetype_reasoning",
            "visual_story_system",
            "hero_treatment",
            "proof_or_demo_strategy",
        ],
        change_notes=(
            "Build 5 repair (Part 1): versions the CANONICAL RECIPE that composes a scene/image-generation "
            "call — not one frozen literal prompt string, since the actual text sent to the model is built "
            "dynamically per slide from CreativeDirection/MasterCampaignConcept/PlatformCreativeSpec/brand "
            "style/product-safety instructions (see generate_ai_background's and recreate_creative_image's "
            "own docstrings for the exact composition). Bump this version when the RECIPE's composition "
            "logic itself changes — which inputs feed the prompt, what's structurally forbidden (product "
            "label/logo/copy text staying out of generate_ai_background's backdrop-only call; the "
            "product-accuracy/no-fabricated-claims rules in recreate_creative_image), or how product-"
            "preservation is enforced — never on a wording-only tweak that leaves the recipe's inputs and "
            "rules unchanged. Deliberately language-independent (recorded with language=\"\", mirroring "
            "platform_adaptation's own platform-shared/language-agnostic precedent) — a scene's lighting "
            "and composition never vary by copy language."
        ),
    ),
    "creative_qa_critique": PromptSpec(
        purpose="creative_qa_critique",
        version="1.0.0",
        file_path="services/qa_engine.py::run_creative_qa (CreativeCritiqueResult)",
        variables=[
            "master_concept", "platform_adaptation", "creative_direction", "campaign_copy",
            "verified_product_facts", "brand_requirements", "locale", "platform", "content_type",
            "carousel_context", "qa_rubric_version",
        ],
        change_notes=(
            "Build 3, Part B: the multimodal structured critic scoring one finished PlatformCampaignVariant "
            "against the full campaign context — visual quality, brand quality, product fidelity, language, "
            "and platform fit, plus creative hard-fails (pasted-on product, bad shadow/light, wrong product)."
        ),
    ),
    "language_qa_critique": PromptSpec(
        purpose="language_qa_critique",
        version="1.0.0",
        file_path="services/qa_engine.py::run_language_qa (LanguageQAResult)",
        variables=["headline", "body", "cta", "language", "platform"],
        change_notes=(
            "Build 3, Part C: language hard-fail judgment (wrong language, untranslated text, PT-BR/English "
            "mixing, broken grammar, literal translation, spelling corruption) on the real copy text used by "
            "one variant — separate from Part B's creative critique, which covers visual dimensions."
        ),
    ),
    "video_qa_critique": PromptSpec(
        purpose="video_qa_critique",
        version="1.0.0",
        file_path="services/qa_engine.py::run_video_qa (VideoQAResult)",
        variables=["hook", "script", "shot_list", "caption", "platform", "language", "master_concept"],
        change_notes=(
            "Build 3 carry-forward requirement 3 + Part L: format-appropriate QA for a script-only, "
            "video-oriented variant — judges the structured text output only, never a claim of video-visual "
            "fidelity, since no video file is ever rendered."
        ),
        platform_applicability=["tiktok", "youtube_shorts"],
    ),
    "targeted_copy_revision": PromptSpec(
        purpose="targeted_copy_revision",
        version="1.1.0",
        file_path="services/qa_engine.py::revise_copy_for_variant (RevisedCopy)",
        variables=["verified_product_facts", "current_headline", "current_body", "current_cta", "issues", "language", "platform"],
        change_notes=(
            "Build 3, Part E: rewrites ONE variant's own copy only — never touches the shared "
            "CampaignOutput(kind=\"copy\") row every other platform/language reads from, so an English "
            "revision never touches Portuguese and an Instagram revision never touches Facebook."
        ),
    ),
    "claims_audit_extraction": PromptSpec(
        purpose="claims_audit_extraction",
        version="1.0.0",
        file_path="services/claims_audit.py::augment_with_ai_extraction (CandidateClaimExtractionResult)",
        variables=["fields"],
        change_notes=(
            "BUILD 6 FINAL REPAIR: OPTIONAL recall-only layer of the unsupported-claim ENFORCEMENT gate — "
            "extracts candidate factual-sounding phrases from a variant's own visible copy/carousel/video "
            "text that the always-on deterministic pattern detector (services/claims_audit.py, layer 1) "
            "might miss. Never itself decides a claim is supported: every candidate is independently "
            "re-checked against VerifiedProductFacts + owner-confirmed brand facts by this app's own code "
            "before ever becoming a hard-fail. Runs with no effect on the fail-closed guarantee when no "
            "provider is configured — layer 1 alone still enforces the gate."
        ),
    ),
    "targeted_claims_revision": PromptSpec(
        purpose="targeted_claims_revision",
        version="1.1.0",
        file_path="services/qa_engine.py::revise_copy_for_variant (RevisedCopy, reused for claims_issue)",
        variables=["verified_product_facts", "current_headline", "current_body", "current_cta", "issues", "language", "platform"],
        change_notes=(
            "BUILD 6 FINAL REPAIR: the claims-enforcement revision branch — reuses targeted_copy_revision's "
            "own prompt/function unchanged, fed the unsupported-claim findings as `issues`, so the same "
            "claims-boundary instruction that prevents new claims at generation time also grounds the "
            "revision attempt that removes a claim the enforcement gate caught."
        ),
    ),
    "targeted_creative_direction_revision": PromptSpec(
        purpose="targeted_creative_direction_revision",
        version="1.3.0",
        file_path="services/qa_engine.py::revise_creative_direction_for_variant (CreativeDirection)",
        variables=["verified_product_facts", 
            "previous_direction", "issues", "master_concept", "adaptation", "platform", "language",
            "content_type", "slide_role",
            "product_category_context",
            "campaign_archetype",
            "archetype_reasoning",
            "visual_story_system",
            "hero_treatment",
            "proof_or_demo_strategy",
        ],
        change_notes=(
            ("Build 3, Part E: rewrites ONE variant's own CreativeDirection only, in response to specific QA "
            "issues — the revised direction then re-grounds a fresh, targeted background/scene regeneration "
            "for that variant alone, never every platform/language." + " Build 6R final hardening: targeted CreativeDirection revision now receives the full claims boundary in addition to sparse grounding and verified product facts.")
        ),
    ),
    "targeted_video_revision": PromptSpec(
        purpose="targeted_video_revision",
        version="1.0.0",
        file_path="services/qa_engine.py::revise_video_concept (VideoConcept)",
        variables=["previous_hook", "previous_script", "issues", "platform", "language", "adaptation"],
        change_notes=(
            "Build 3, Part E's video counterpart: rewrites ONE script-only variant's structured hook/script/"
            "shot-list in response to specific QA issues, staying grounded in the same master concept and "
            "platform adaptation strategy rather than inventing a new concept."
        ),
        platform_applicability=["tiktok", "youtube_shorts"],
    ),
}


def ensure_prompt_versions_seeded(db: Session) -> None:
    """Idempotent upsert by `purpose` (the natural key here — this app only ever
    has one current version per purpose; old versions aren't kept as separate
    rows, `change_notes` documents what changed instead) — same pattern as
    `services/seed.py::seed_strategy_library`. Safe to call on every startup.
    """
    existing = {row.purpose: row for row in db.query(PromptVersion).all()}
    for spec in PROMPT_VERSIONS.values():
        row = existing.get(spec.purpose)
        if row is None:
            row = PromptVersion(purpose=spec.purpose)
            db.add(row)
            existing[spec.purpose] = row
        row.version = spec.version
        row.file_path = spec.file_path
        row.variables = spec.variables
        row.change_notes = spec.change_notes
        row.platform_applicability = list(spec.platform_applicability)
        row.language_applicability = list(spec.language_applicability)
        row.active = spec.active
    db.commit()


def record_prompt_usage(
    db: Session, *, campaign_id: str, purpose: str, language: str, platform: str | None = None,
    extra: dict | None = None,
) -> None:
    """Logs one generation event for traceability (Part I: "traceability must
    include prompt name, version, language, platform"). Best-effort — an unknown
    `purpose` (not in `PROMPT_VERSIONS`) still logs with `version="unknown"`
    rather than raising, since a missing audit-trail entry should never fail a
    real campaign generation.

    `extra` (Build 3, Part F: "record QA prompt version, rubric version,
    revision prompt version, platform, locale, model role") merges additional
    fields into `detail` beyond the base purpose/version/language/platform —
    e.g. `{"rubric_version": ..., "model_role": ..., "variant_id": ...}` from
    a QA/revision call site. Purely additive: every pre-Build-3 caller that
    never passes it gets byte-for-byte the same `detail` shape as before.
    """
    spec = PROMPT_VERSIONS.get(purpose)
    detail = {
        "purpose": purpose,
        "version": spec.version if spec else "unknown",
        "language": language,
        "platform": platform,
    }
    if extra:
        detail.update(extra)
    db.add(
        AuditEvent(
            entity_type="campaign_prompt_usage",
            entity_id=campaign_id,
            action=purpose,
            detail=detail,
        )
    )
