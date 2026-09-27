# Data Model

SQLite (WAL mode) via SQLAlchemy, migrated with Alembic. All primary keys are UUID
strings (`uuid4().hex`) except autoincrement-friendly join/log tables noted below.
Timestamps are UTC `datetime`. This document is the source of truth for the schema
implemented in `backend/app/models/`.

## Brand & catalog

**brands** — id, name, slug, is_active, voice, language_rules(json), colors(json),
typography(json), spacing(json), visual_style(json), forbidden_styles(json),
preferred_ctas(json), disallowed_terms(json), disclaimers(json), target_audiences(json),
target_countries(json), social_handles(json), website, campaign_rules(json, unused —
see creative_instructions below), creative_instructions (text, default `""` — round 20:
the brand's own standing creative-direction text, threaded into every AI call), created_at,
updated_at.

**brand_assets** — id, brand_id → brands, kind (`logo`|`font`|`visual_reference`),
file_path, label, created_at.

**categories** — id, brand_id → brands, name, slug, parent_category_id (nullable,
self-referential for a light tree), created_at.

**products** — id, brand_id → brands, category_id → categories, name, slug, notes,
created_at.

**verified_product_facts** (Build 1, Part A) — id, product_id → products (unique — one
row per product), verified_description, verified_ingredients(json list),
verified_features(json list), verified_benefits(json list), verified_usage,
verified_size, verified_variant, verified_price (string, deliberately never a float —
never assumed to be one currency or format), verified_availability,
verified_country_of_origin, verified_claims(json list — confirmed-safe claims the copy
prompt may use), prohibited_claims(json list), source_asset_ids(json list),
source_references(json list), confidence (float 0-1), provenance (string, e.g.
`owner_provided`|`brand_website`|`unverified`), created_at, updated_at. The owner-
editable half of the one canonical `VerifiedProductFacts` structure
(`services/product_facts.py::resolve_verified_product_facts`) that also pulls in
read-only `product_name`/`category`/`brand_name`/`owner_notes` from `products`/
`categories`/`brands` and computes `missing_information` — never stored, always
derived from which `VERIFIED_FACT_FIELDS` are still blank. A product with no row here
yet resolves to an all-empty structure with everything listed as missing, never an
error. Deliberately separate from `research_insights` (external market research, not
product truth) and from anything creative/AI-authored (`CreativeBrief`,
`CampaignCopy`) — see `models/product_facts.py`'s docstring for the full separation
rationale. Never invented: ingredients, percentages, certifications, rankings,
medical benefits, prices, discounts, availability, shipping guarantees, clinical
claims, or awards beyond what's actually entered here.

## Asset library

**assets** — id, brand_id → brands, category_id (nullable) → categories, product_id
(nullable) → products, absolute_path (unique), relative_path, filename, extension,
sha256 (indexed), phash (indexed), file_size_bytes, width, height, aspect_ratio,
created_at_fs, modified_at_fs, first_indexed_at, last_indexed_at, image_role
(`hero`|`lifestyle`|`packaging`|`logo`|`reference`|`unclassified`), tags(json list),
is_active, times_used, last_used_at, visual_description (AI-generated, nullable),
ai_metadata(json), user_notes, checksum_stale (bool — set when re-scan sees a changed
mtime so a re-describe can be queued).

Never stores a copy of the source file. A separate on-disk thumbnail cache
(`backend/data/thumbnails/<sha256>.jpg`) is keyed by hash, safely regenerable, and not a
DB table.

## Campaign Strategy Library (Campaign DNA)

The catalog of campaign archetypes, organized into 8 strategic families — seeded data,
not user input, so the orchestrator can reason over it (see
`backend/app/data/strategy_library.py` for the full seed content).

**campaign_strategy_families** — id, key (`ATTACK`|`ACQUIRE`|`CONVERT`|`RETAIN`|
`BRAND`|`HYPE`|`COMMUNITY`|`DEFENSE`), name, description, color (UI accent),
sort_order.

**campaign_strategy_types** — id, key (slug, e.g. `guerrilla_marketing`), name,
family_id → campaign_strategy_families, secondary_family_keys(json list — e.g.
Anti-Ad is primarily ATTACK but secondarily BRAND), example, and the full Campaign DNA:
objective, trigger_type (`manual`|`competitor_event`|`seasonal`|`inventory`|
`customer_behavior`|`scheduled`), trigger_description, audience, psychology(json list
— e.g. `scarcity`, `fomo`, `price_anchoring`), offer_types(json list), channels(json
list), content_types(json list), typical_duration, budget_notes, success_metrics(json
list), notes, product_scope (`single`|`multi`|`either`, default `either` — round 20,
informational only, which carousel structure this type naturally fits), is_active,
created_at, updated_at.

64 types ship seeded across the 8 families (7-13 per family); `app/services/seed.py`
upserts them by `key` on every startup, so adding/editing an entry in the data file
updates existing rows rather than duplicating them.

## Defense engine

Distinct from the ATTACK family: ATTACK campaigns are proactive; Defense **detects** a
competitor move and **recommends** a specific Strategy Library response, with a visible
rationale — never an automatic price match.

**competitors** — id, brand_id, name, website, social_handles(json), notes,
monitoring_enabled, created_at.

**competitor_events** — id, competitor_id, brand_id, event_type (`price_change`|
`promotion_launch`|`new_product`|`campaign_detected`|`restock`|`other`), detected_at,
source (`manual`|`research`|`import`), details(json — e.g. `{"discount_pct": 20}`),
severity (`low`|`medium`|`high`), status (`NEW`|`REVIEWED`|`RESPONDED`|`IGNORED`),
created_at.

**defense_playbooks** — id, brand_id (nullable = global default), event_type,
min_severity, condition(json — simple `{field}_gte`/`_lte`/`_eq` threshold checks
against the event's `details`), recommended_strategy_key (→
campaign_strategy_types.key), rationale, priority (lower evaluated first), is_active.
`app/services/defense.py`'s `recommend_response()` matches an event against active
playbooks (brand-specific rows win ties over global ones) and returns ranked,
explainable recommendations — a plain rule engine today by design, so "why did it
suggest this?" always has a real answer; see docs/campaign-pipeline.md for how an
AI-assisted version could extend it later without an API change.

## Campaigns

**campaigns** — id (uuid), display_id (human-readable, e.g. `HANNA-SKIN-000123`,
generated from a per-brand+category sequence table), brand_id, category_id, product_id
(nullable), strategy_type_id (nullable) → campaign_strategy_types — the chosen
Campaign DNA, if any (free-text `angle` still exists for campaigns that don't fit any
library type), triggered_by_event_id (nullable) → competitor_events — set when a
Defense recommendation created this campaign, objective (`awareness`|`discovery`|
`education`|`engagement`|`lead`|`booking`|`sale`|`retention`), audience, funnel_stage,
channels(json list), angle, hook, main_promise, cta, content_type, template_id
(nullable → creative templates, Phase 6), language (legacy single-value field, kept
for backward compatibility — see `languages` below, which is authoritative as of
Build 1), geography, campaign_family (nullable, groups variants), status (enum, see
below), research_run_id (nullable) → research_runs, target_slide_count (nullable int,
round 16 — pins the carousel planner to an exact slide count), platform_key (nullable
string(50), round 20 — which `PLATFORM_FORMATS` pixel-rendering key this campaign
renders at; null falls back to the account-wide AutopilotConfig default),
human_review_status (string(20), Build 4, default `PENDING` — `PENDING`|`APPROVED`|
`REJECTED`|`REVISION_REQUESTED`; a genuinely separate axis from `status` below and
from `platform_campaign_variants.human_review_status` — set ONLY by a `level=
"CAMPAIGN"` `ReviewFeedback` action, never aggregated automatically from variant-level
activity; see `review_feedback` below and `docs/architecture.md`'s Build 4 section),
languages
(json list, Build 1 Part B — default `["pt-BR"]`; canonical values `pt-BR`/`en` from
`data/platform_capabilities.py::SUPPORTED_LANGUAGES`; drives an independent, natively-
written `CampaignCopy`+`CarouselPlan` per language in `run_copy_stage` — see
campaign-pipeline.md's Build 1 section), target_platforms (json list, Build 1 Part C —
default `["instagram"]`; real-world platform keys from
`data/platform_capabilities.py::PLATFORM_CAPABILITIES`
(instagram/facebook/tiktok/youtube_shorts/pinterest/linkedin/x), distinct from
`platform_key` above — this is "which platform", not "what pixel size"), created_at,
updated_at, approved_at, published_at, notes.

Status enum: `IDEA, RESEARCHING, BRIEF_READY, GENERATING, REVIEW, APPROVED, EXPORTED,
SCHEDULED, PUBLISHED, ARCHIVED, FAILED`.

**campaign_assets** — id, campaign_id → campaigns, asset_id → assets, role
(`source`|`reference`), created_at. (Many-to-many: which library assets fed this
campaign.)

**campaign_slides** — id, campaign_id → campaigns, slide_number, purpose, eyebrow,
headline, body, cta, visual_brief, source_asset_id (nullable) → assets,
generated_background_path, template_id, rendered_asset_path, created_at.

**campaign_outputs** — id, campaign_id → campaigns, kind (`copy`|`creative`|`research`|
`qa_report`|`master_concept`), platform (nullable), file_path, version, created_at. As
of Build 1, the `copy` and `creative` kinds' JSON files are nested per language —
`{"primary_language": "pt-BR", "languages": {"pt-BR": {...}, "en": {...}}}` (`creative`
additionally has a top-level `creative_brief`, shared across languages — the design/
visual direction is one campaign idea, not per-language text) — instead of one flat
object, so a multi-language campaign's independently-generated variants are all
persisted, not just the primary one. A pre-Build-1 campaign's already-persisted flat
JSON still reads back correctly (`services/orchestrator.py::_stage_language_variant`
handles both shapes). Build 2 (Part E) adds `kind="master_concept"`: one
`MasterCampaignConcept` JSON blob per campaign (`services/orchestrator.py::
run_copy_stage`), read back by `_render_additional_platform_variants` as the one
consistent campaign idea every platform/language adaptation is told to adapt.

**campaign_variants** — id, parent_campaign_id → campaigns, variant_campaign_id →
campaigns, varies (`hook`|`visual`|`cta`|`caption`|`first_slide`), created_at.
Declared since round 1 for an A/B-style same-platform/same-language variant concept;
confirmed dead code (never read or written by any code path) — see
`platform_campaign_variants` below, a deliberately separate new table for a different
concept, not a repurposing of this one.

**platform_campaign_variants** (Build 2, Part F) — id, campaign_id → campaigns
(cascade delete), target_platform (string(30), a `PLATFORM_CAPABILITIES` key),
language (string(20), a `SUPPORTED_LANGUAGES` value), content_type (string(50), a
`data/platform_creative_specs.py` content-type key), render_format_key (string(50),
a `PLATFORM_FORMATS` key, `""` for script-only content), status (`PENDING`|`RENDERED`|
`SCRIPT_ONLY`|`SCRIPT_UNAVAILABLE`|`SKIPPED_UNSUPPORTED`|`FAILED`), slide_asset_paths
(json list — rendered PNG path(s), empty for script-only/failed), copy_language
(string(20) — which `CampaignOutput(kind="copy")` language variant this used),
creative_direction (json — `CreativeDirection.model_dump()`, or `{}`), video_concept
(json, nullable — `VideoConcept.model_dump()` for script-only content types, `null`
otherwise), qa_report_paths (json list), shared_scene_source (string(50) — which
platform+slide-index this variant's AI-generated background/composite was actually
reused from, `""` when it generated its own or nothing was cached — pure
traceability), notes (text), created_at, updated_at. Unique on (campaign_id,
target_platform, language, content_type) — `uq_platform_variant` — so re-running
Visuals replaces a campaign's variant rows (delete-then-recreate) rather than
accumulating stale duplicates. One row per (target_platform x language) combination a
campaign selects: the primary (first-selected platform x first-selected language)
combination gets a row referencing the paths `run_visuals_stage`'s own unchanged
legacy loop already rendered (never re-rendered); every other combination is rendered
independently by `services/orchestrator.py::_render_additional_platform_variants`.
Plus 7 Build 3 QA columns (migration `b2c3d4e5f6a7`): qa_status (string(20),
`PENDING`|`PASS`|`NEEDS_REVIEW`, default `PENDING` — a variant this never runs QA on
simply keeps `PENDING`, not a fourth meaning bolted onto `status` above), qa_scores
(json, nullable — the latest attempt's full scorecard: `CreativeCritiqueResult` for a
static-image variant, `VideoQAResult` for a script-only one, `None` when QA never
ran), qa_hard_fails (json list — every hard-fail reason from the latest attempt,
platform + language + creative combined, empty once a variant genuinely passes),
qa_attempts (integer, default 0 — how many QA rounds, including the first, this
variant has been through), qa_evidence_paths (json list — one path per attempt's
persisted evidence JSON, never overwritten), qa_versions (json — the latest attempt's
`{qa_prompt_version, qa_rubric_version, revision_prompt_version}`, each `""` when
that step didn't run for this attempt), qa_notes (text). See `services/qa_engine.py::
run_qa_stage` (the writer of all 7) and `docs/architecture.md`'s Build 3 section. Plus
1 Build 4 column (migration `c4d5e6f7a8b9`): human_review_status (string(20), default
`PENDING` — same 4 values as `campaigns.human_review_status` above, genuinely
independent of `qa_status` above it — `QA_PASS`+`OWNER_REJECTED` and
`QA_NEEDS_REVIEW`+`OWNER_APPROVED` are both valid, real states; set by a `level=
"PLATFORM_VARIANT"` or `level="ASSET"` `ReviewFeedback` action scoped to THIS row
only, and reset to `PENDING` by `services/review_engine.py::apply_requested_revision`
once a requested revision is applied, since the revised version awaits a fresh owner
look).

**review_feedback** (Build 4, migration `c4d5e6f7a8b9`) — id (uuid), campaign_id →
campaigns (cascade delete), platform_campaign_variant_id (nullable) →
platform_campaign_variants (cascade delete — null for `level="CAMPAIGN"` feedback,
which spans every platform/language at once), level (`CAMPAIGN`|`PLATFORM_VARIANT`|
`ASSET` — "platform variant" and "language variant" from the spec collapse into the
single `PLATFORM_VARIANT` value, since `platform_campaign_variants` already keys on
platform+language jointly), asset_ref (string(100), default `""` — for `level=
"ASSET"` only: a slide reference like `"slide-2"` for a rendered variant, or one of
`hook`/`script`/`shot_list`/`timing`/`on_screen_text`/`caption`/`cover` for a
`SCRIPT_ONLY` variant, never a rendered-slide-style reference for the latter), action
(`APPROVE`|`REJECT`|`REQUEST_REVISION`), reason_code (string(50), default `""` — one
of `data/feedback_reasons.py::FEEDBACK_REASON_CODES`, or `""` for free-text-only
feedback), reason_text (text). Denormalized filter/rank context (captured at write
time so the feedback selector is a single indexed scan, never a join back through
`platform_campaign_variants`/`campaigns` per candidate): brand_id (nullable) → brands,
category_id (nullable) → categories, product_id (nullable) → products, platform
(string(30), default `""` — `""` for `level="CAMPAIGN"`), language (string(20),
default `""`), content_type (string(50), default `""`), objective (string(30),
default `""`). Traceability snapshot — a frozen COPY of what was actually reviewed,
never a live reference (see `docs/architecture.md`'s Build 4 section, carry-forward
requirement 2): reviewed_slide_asset_paths (json list), reviewed_video_concept (json,
nullable), reviewed_copy_snapshot (json — headline/body/cta/hook), reviewed_creative_
direction (json), reviewed_qa_status (string(20)), reviewed_qa_scores (json,
nullable), reviewed_qa_hard_fails (json list), reviewed_qa_attempts (integer),
reviewed_qa_evidence_paths (json list), reviewed_qa_versions (json), reviewed_prompt_
versions (json — best-effort `{purpose: version}` read back from existing
`AuditEvent(entity_type="campaign_prompt_usage")` rows, never fabricated, `{}` when
nothing matches). Lineage: revision_of_feedback_id (nullable, self-referential FK,
`ondelete="SET NULL"`) — auto-linked by `services/review_engine.py::record_review_
feedback` to the most recent still-unanswered `REQUEST_REVISION` feedback for the same
variant, no explicit parameter needed; walking this field answers "what was rejected,
why, what changed, whether it improved, what was finally approved" without ever
overwriting a prior row. created_at, updated_at. See `services/review_engine.py` and
`services/feedback_selector.py`, and `docs/architecture.md`'s Build 4 section.

**campaign_fingerprints** — id, campaign_id → campaigns (unique), text_hash (normalized
hash of hook+headline+body+cta), text_embedding(json — list[float], small local
embedding or None if unavailable), angle, promise_summary, objective, format,
asset_sha256_list(json), computed_at.

## Research

**research_runs** — id, brand_id, category_id (nullable), product_id (nullable),
query_context(json: geography/audience/objective/date/season), ttl_kind
(`trend`|`category`), created_at, expires_at.

**research_sources** — id, research_run_id → research_runs, url, source_title,
publisher, query, retrieved_at, source_type, geography, relevance_score.

**research_insights** — id, research_run_id → research_runs, statement,
source_ids(json list of research_sources.id), confidence, freshness, category,
recommended_implication.

## Opportunities (posting communities)

**opportunities** — id, brand_id, platform (`facebook_group`|`reddit`|`forum`|
`local_community`|`directory`|`influencer`|`creator`|`blog`|`website`|`newsletter`|
`marketplace`|`instagram_account`|`youtube_channel`|`other`), name, url, description,
audience, category_id (nullable), country, region_city, language, estimated_relevance,
audience_size (nullable), visibility (`public`|`private`), joined_status, promo_allowed
(nullable bool), posting_rules, recommended_content_style, notes, source,
discovered_at, last_checked_at, last_posted_at, status (`DISCOVERED|REVIEW|APPROVED|
JOINED|ACTIVE|PAUSED|REJECTED`), favorite (bool), blocked (bool).

**campaign_opportunities** — id, campaign_id → campaigns, opportunity_id →
opportunities, community_post_text, posted (bool), posted_at, created_at.

## Publishing & performance

**publications** — id, campaign_id → campaigns, provider (`facebook_page`|
`instagram`|`manual`), external_post_id (nullable), url (nullable), published_at,
status.

**performance_metrics** — id, publication_id → publications, impressions, reach,
likes, comments, shares, saves, clicks, leads, bookings, sales, revenue, recorded_at,
source (`manual`|`api`).

**performance_insights** — id, brand_id, statement, supporting_campaign_ids(json),
created_at.

## Platform plumbing

**jobs** — id, type, campaign_id (nullable), status (`QUEUED|RUNNING|COMPLETED|FAILED|
CANCELLED`), progress (0-100), step, attempts, started_at, completed_at, error,
metadata(json).

**prompt_versions** — id, purpose, version, file_path, variables(json),
change_notes, created_at, **platform_applicability(json list, Build 5)**,
**language_applicability(json list, Build 5)**, **active(bool, default true,
Build 5)**. Defined since round 1 but was dead code (never read or
written by anything) until Build 1 (Part I) — `services/prompt_registry.py`'s
`ensure_prompt_versions_seeded` now upserts one row per tracked prompt purpose
(`campaign_copy`, `carousel_plan` from Build 1; `master_campaign_concept`,
`platform_adaptation`, `creative_direction`, `video_concept` added in Build 2)
on every startup, and `record_prompt_usage` logs every actual generation
(purpose, version, language, platform) to `audit_events`
(`entity_type="campaign_prompt_usage"`) for traceability. The three Build 5
columns make the registry's own applicability self-describing — an empty list
means "all" (e.g. `video_concept`/`video_qa_critique`/`targeted_video_revision`
carry `platform_applicability=["tiktok", "youtube_shorts"]`, everything else
stays `[]`/all-platforms) — and are re-seeded from the live `PromptSpec`
dataclasses on every startup exactly like the pre-existing columns, never
hand-edited in the DB.

**ai_usage** — id, provider, model, operation, campaign_id (nullable), input_tokens,
output_tokens, image_count, estimated_cost_usd, duration_ms, created_at,
platform, language, content_type (all string, default "", Build 6),
**scope (string, default "variant", Build 6 REPAIR)**.
Existed since round 1 but was never actually written to until Build 6 — see
`app/services/usage_tracking.py` (the `record_ai_usage`/`record_stage_usage`/
`build_campaign_cost_report` functions) and `app/services/ai/openai_
provider.py`'s new `drain_usage_events()` mechanism, which is the only code
path that can ever populate a real, non-zero row (it's the only provider
implementation making a real network call). The `platform`/`language`/
`content_type` columns let a row be attributed to a specific
`PlatformCampaignVariant` (platform x language x content_type), not just a
campaign as a whole. `scope` (Build 6 REPAIR, Critical Defect 7/13) removes
the ambiguity that was left when those three columns are blank: `"campaign_
global"` for a stage that is genuinely not bound to one requested platform/
language pairing (`research`, `strategy`, `creative_brief`, `master_campaign_
concept`, `campaign_copy`, `carousel_plan` — the last three still carry a
`platform`/`language` tag for traceability even though they're campaign-wide),
`"variant"` (the default) for everything attributed to a specific rendered/
scripted `PlatformCampaignVariant` (`platform_adaptation`, `scene_generation`,
`creative_direction`, `video_concept`, and every QA/revision operation).
`build_campaign_cost_report`'s `by_scope` breakdown aggregates on this column.

**audit_events** — id, entity_type, entity_id, action, detail(json), created_at.

**settings** — key (pk), value(json), updated_at. (Backs the Settings UI; overrides
`.env` when present.)

## Golden benchmark + regression (Build 5)

**benchmark_cases** — id, name, notes, status (`CANDIDATE|ACTIVE|RETIRED`),
brand_id → brands (cascade delete), product_id (nullable FK, `SET NULL`),
category_id (nullable FK, `SET NULL`), platform, content_type, language,
objective, audience, source_asset_paths(json list),
verified_product_facts_snapshot(json dict), expected_truths(json list),
prohibited_claims(json list), expected_creative_characteristics(json list),
baseline_output_snapshot(json dict), owner_rating(string), source_feedback_id
(nullable FK → review_feedback, `SET NULL` — never `CASCADE`), created_at,
updated_at. One row is one explicitly-curated, immutable golden test case —
only `curate_benchmark_case` ever inserts one (never automatically from an
ordinary APPROVE/REJECT/REQUEST_REVISION action). When curated from a real
`ReviewFeedback` row, `owner_rating`/`baseline_output_snapshot` are copied
ONCE at curation time, not live-joined — deleting the source feedback row
later sets `source_feedback_id` to `NULL` but leaves the case's own copied
fields untouched, since a golden case is meant to outlive the review history
it was drawn from.

**benchmark_runs** — id, benchmark_case_id → benchmark_cases (cascade delete),
mode (`OFFLINE|MOCK|LOW_COST_SMOKE|LIVE_FULL`), platform, language, campaign_id
(plain string — the throwaway campaign the run executed against, not a FK,
since that campaign is typically deleted/disposable), variant_id (nullable FK
→ platform_campaign_variants, `SET NULL`), prompt_versions_snapshot(json dict),
model_role_snapshot(json dict), **creative_system_snapshot(json dict, Build 5
repair)**, qa_status(string), human_review_status(string
— kept as a SEPARATE column from `qa_status`, same discipline as Build 4's
`PlatformCampaignVariant.qa_status`/`human_review_status` split: a
QA_PASS+OWNER_REJECTED run is never collapsed into one ground truth),
qa_scores(json dict), hard_fails(json list), weighted_score(nullable float —
`data/benchmark_scoring.py`'s documented per-platform weight table, normalized
by the sum of weights actually matched), weights_used(json dict — the exact
weight table applied, for traceability), cost_breakdown(json dict), is_baseline
(bool), notes, created_at. One row is one real, frozen execution of the actual
pipeline (`run_strategy_stage`/`run_copy_stage`/`run_visuals_stage`/
`qa_engine.run_qa_stage` — never a parallel reimplementation) against a
benchmark case, snapshotting exactly which prompt versions/model roles/scores/
costs applied at that moment so a later prompt change can be compared against
it without the comparison drifting as the live prompt registry changes.

`creative_system_snapshot` (added by the Build 5 repair, migration
`e6f7a8b9c0d1`) is a nested, complete answer to "what exact generation
system produced this run?" in one field — a copy of the per-purpose prompt-
version dict `prompt_versions_snapshot` already holds (including whichever
targeted-revision purpose, e.g. `targeted_copy_revision`, actually fired for
this run — never collapsed into the original purpose's own version) plus
three version identities no other column tracks: `verified_product_facts_
resolver_version` (`services/product_facts.py::VERIFIED_PRODUCT_FACTS_
RESOLVER_VERSION`), `renderer_version` (`services/creative/renderer.py::
RENDERER_VERSION`), `template_version` (`services/creative/templates.py::
TEMPLATE_REGISTRY_VERSION`) — plus this run's own `platform`/`language`/
`content_type`/`quality_mode`. Deliberately does not duplicate `model_role_
snapshot`'s own column. Built by `services/benchmark_engine.py::build_
creative_system_snapshot`. The prompt registry itself (`services/prompt_
registry.py::PROMPT_VERSIONS`) also gained a `"scene_generation"` entry
(version `1.0.0`) as part of this repair — it versions the RECIPE that
composes `generate_ai_background`/`recreate_creative_image`'s dynamic,
per-slide prompt (which inputs feed it, what's structurally forbidden, how
product preservation is enforced), not one frozen literal prompt string,
since the actual text sent to the model still varies per slide.

## Relationships at a glance

```
brands 1─* categories 1─* products
brands 1─* assets ; categories 1─* assets ; products 1─* assets
brands 1─* campaigns ; categories/products 1─* campaigns
campaign_strategy_families 1─* campaign_strategy_types
campaigns *─1 campaign_strategy_types (nullable — a campaign may use free-text angle instead)
campaigns 1─* campaign_assets *─1 assets
campaigns 1─* campaign_slides
campaigns 1─* platform_campaign_variants
campaigns 1─1 campaign_fingerprints
campaigns *─1 research_runs 1─* research_sources
research_runs 1─* research_insights (*─* source_ids into research_sources)
campaigns *─* opportunities  (through campaign_opportunities)
campaigns 1─* publications 1─* performance_metrics
brands 1─* competitors 1─* competitor_events
competitor_events *─1 campaigns (nullable triggered_by_event_id — a campaign born from a Defense recommendation)
defense_playbooks reference campaign_strategy_types by key (recommended_strategy_key), not a hard FK
jobs reference campaigns loosely by id (nullable FK, jobs may be non-campaign work)
```

## Duplicate detection data (section 50/51 of the brief)

- Image duplicate/reuse: `assets.sha256` (exact) + `assets.phash` (near-duplicate,
  Hamming distance) + `assets.times_used`/`last_used_at` (recency).
- Text similarity: `campaign_fingerprints.text_hash` (exact) and a lightweight
  local similarity (token-set/Jaccard or a small sentence-embedding model run locally)
  over `text_embedding` when available — no external vector DB required for the MVP;
  comparisons run in application code over the (small, single-user) campaign table.
- Strategy similarity: compare `angle` + `promise_summary` + `objective` + `format`
  across `campaign_fingerprints` rows in the same category.
- Novelty classification: `EXACT_REPEAT | TOO_SIMILAR | SIMILAR_BUT_ACCEPTABLE | FRESH`,
  thresholds configurable in `settings`.
