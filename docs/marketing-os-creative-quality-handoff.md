# Marketing OS — Creative Quality & Multi-Platform Handoff (Build 6)

This is the Build 6 "Codex handoff" document the carry-forward spec asked
for: a single reference to the full multi-platform/multi-language
architecture, aimed at whoever picks this codebase up next (human or AI).
It intentionally duplicates a little of `docs/architecture.md` /
`docs/campaign-pipeline.md` for the sake of being readable on its own.

## 1. What this app is

A local-first Marketing Operating System for Hanna From Japan (a real
Brazil-facing, Japan-based personal-shopper business — see
`claude/hanna-gpt-system/01-company-and-service-profile.md` and
`02-canonical-product-catalog.md` in the Claude Project this codebase was
built from). FastAPI + SQLAlchemy 2.0 + Alembic + SQLite backend; React/TS/
Vite frontend. Designed to run on the owner's own PC against the owner's own
OpenAI key and a real local photo repository — **not** a hosted SaaS.

## 2. The end-to-end pipeline

```
SELECT BRAND -> SELECT PRODUCT -> SELECT PLATFORMS -> SELECT LANGUAGES
  -> SELECT OBJECTIVE -> VERIFIED FACTS -> RESEARCH -> MASTER CAMPAIGN STRATEGY
  -> PLATFORM ADAPTATION -> LANGUAGE ADAPTATION -> COPY -> CREATIVE DIRECTION
  -> RENDER/SCRIPT -> QA -> TARGETED REVISION -> REVIEW -> SAVE
```

Implemented as three independently-callable stages (`services/orchestrator.py`)
plus two more bolted on since Build 3/4:

1. **Strategy** (`run_strategy_stage`) — candidate photos, Strategy Library
   type, real cited research (`services/research/openai_research.py`),
   2-3 strategy candidates, novelty-checked against campaign history.
2. **Copy** (`run_copy_stage`) — creative brief, ONE `MasterCampaignConcept`
   (platform/language-agnostic, held constant everywhere downstream), then
   a genuinely independent, natively-written `CampaignCopy` +
   `CarouselPlan` PER language in `Campaign.languages` (never a translation).
3. **Visuals** (`run_visuals_stage`) — renders the PRIMARY (first platform,
   first language) combination directly, then
   `_render_additional_platform_variants` creates one independently
   reviewable `PlatformCampaignVariant` row per remaining
   (`target_platform` x `language`) combination — adapting `PlatformAdaptation`
   per platform and `CreativeDirection` per (platform, language, slide) via
   real AI calls (see §4 for exactly which combo does/doesn't trigger this).
4. **QA** (`services/qa_engine.py::run_qa_stage`) — Build 3's four QA
   surfaces (technical/deterministic, creative/multimodal, language, video)
   evaluate every already-rendered/scripted variant independently, with
   targeted revision + retry (never a blind full regeneration) up to
   `AutopilotConfig.qa_max_retries`.
5. **Review** (`services/review_engine.py`) — the OWNER's own separate
   verdict (`human_review_status`), independent of `qa_status` by design
   (Build 4) — `record_review_feedback` + `apply_requested_revision` cover
   the full generation -> QA -> human review -> REQUEST_REVISION -> targeted
   revision -> QA rerun -> APPROVE loop, with full lineage
   (`ReviewFeedback.revision_of_feedback_id`) and QA evidence
   (`qa_evidence_paths`, never overwritten) kept at every attempt.

## 3. Generation modes

The four "modes" the Build 6 spec names (SINGLE PLATFORM / CROSS-PLATFORM /
BILINGUAL / FULL CAMPAIGN PACK) are not separate code paths — they are all
the SAME mechanism (`Campaign.target_platforms` x `Campaign.languages`,
both plain arrays picked once at campaign creation), just different array
sizes:

| Mode              | `target_platforms`            | `languages`          |
|-------------------|--------------------------------|----------------------|
| Single platform   | `["instagram"]`                | `["pt-BR"]`          |
| Cross-platform     | `["instagram", "facebook"]`    | `["pt-BR"]`          |
| Bilingual          | `["instagram"]`                | `["pt-BR", "en"]`    |
| Full campaign pack | every selected platform        | every selected language |

There is no separate "estimate cost before running" endpoint yet — this is
an honest gap, not a Build 6 claim otherwise. `len(target_platforms) *
len(languages)` is the number of `PlatformCampaignVariant` rows a run will
produce (the primary combo is one of them, rendered directly; every other
combo goes through `_render_additional_platform_variants`), which is enough
for a caller to describe the expected scope before running Visuals — a
dedicated pre-flight estimate endpoint is a reasonable Build 7 addition.

## 4. Model routing

Every AI call's model comes from `AutopilotConfig` (never hardcoded),
populated from Settings via `api/campaigns.py::_build_autopilot_config`:
`strategy_model`, `copy_model`, `platform_adapter_model`,
`creative_director_model`, `draft_image_model` / `image_model` /
`premium_image_model`, `creative_qa_model`, `revision_model` — each falls
back to `campaign_model`/`image_model`/`vision_model` respectively when
unset (`AutopilotConfig.__post_init__`), so an untouched Settings page
behaves exactly as it always did.

## 5. Quality modes (DRAFT / STANDARD / PREMIUM)

`AutopilotConfig.quality_mode` resolves (via `_resolve_image_model_and_quality`)
to a concrete `(image_model, quality_tier)` pair:

- **draft** -> `draft_image_model` at `quality="low"`.
- **standard** (default) -> `image_model` at `quality="high"` — byte-for-byte
  what every pre-Build-2 run always did.
- **premium** -> `premium_image_model` at `quality="high"`.

**Honest gap**: `quality_mode` alone does NOT automatically change
`qa_best_of_n`/`qa_max_retries` — those are independent `AutopilotConfig`
fields a caller sets separately. "PREMIUM may use stricter QA or additional
candidate/revision behavior where implemented" is true in the sense that the
mechanism exists and is fully wired (`qa_best_of_n` genuinely drives
`_regenerate_with_best_of_n`'s candidate count), but nothing today
auto-links `quality_mode="premium"` to a higher `qa_best_of_n` by default.
Wiring that link (e.g. `_build_autopilot_config` bumping `qa_best_of_n`
when `quality_mode == "premium"` and the caller didn't explicitly override
it) is a reasonable, small Build 7 addition — see
`tests/test_build6_acceptance.py::test_quality_modes_resolve_to_materially_different_configuration`
for where this is verified today (config-level, per the spec's own explicit
allowance to avoid requiring expensive live tests for all three modes).

## 6. Cost / usage capture (new in Build 6)

`models/platform.py::AIUsage` existed since round 1 but nothing ever wrote a
row to it (`_cost_breakdown_for_campaign` was honestly always
`{usage_recorded: False}`). Build 6 closes this:

- `services/ai/openai_provider.py::OpenAIProvider` — the only implementation
  making a real network call — now accumulates one usage event (real token
  counts from the Responses API's `usage` field; an image call's `count`) per
  call into `self._usage_events`, drained via `drain_usage_events()`.
  Approximate published per-model pricing lives in that same file
  (`_TEXT_PRICING_USD_PER_1M_TOKENS`, `_IMAGE_PRICING_USD_PER_IMAGE`) — an
  unrecognized model prices at `$0`, never a guess.
- `services/usage_tracking.py` — `record_stage_usage` drains whatever a
  provider accumulated and writes one `AIUsage` row per event, tagged with
  `operation` (research/strategy/creative_brief/master_campaign_concept/
  campaign_copy/carousel_plan/platform_adaptation/creative_direction/
  scene_generation/video_concept/language_qa_critique/creative_qa_critique/
  video_qa_critique/targeted_copy_revision/
  targeted_creative_direction_revision/targeted_video_revision) plus
  `platform`/`language`/`content_type` — called at the SAME 19 call sites
  `record_prompt_usage` already logs from (never inside a low-level
  generation helper).
- `build_campaign_cost_report` (what `benchmark_engine.py`'s
  `_cost_breakdown_for_campaign` now delegates to) aggregates
  `total_usd`/`image_generation_usd`/`text_generation_usd`/`call_count` (kept
  byte-for-byte compatible with the pre-existing shape) plus new
  `by_operation` and `by_variant` breakdowns.
- A fake test provider never implements `drain_usage_events` (or returns
  `[]`), so every test in this suite still, correctly, records zero cost —
  this is the honest result, not a bug. **Real dollar figures only ever
  come from `scripts/run_live_acceptance.py` run on the owner's own machine.**

## 7. Prompt + creative-system traceability

`services/prompt_registry.py::PROMPT_VERSIONS` versions the RECIPE (which
inputs compose a prompt, what's structurally forbidden) for every AI-authored
purpose — never a frozen expanded string, since most of these are built
dynamically per call. `record_prompt_usage` logs which version/language/
platform produced a real generation, as an `AuditEvent`.

`services/benchmark_engine.py::build_creative_system_snapshot(db,
campaign_id=..., platform=..., language=..., content_type=...,
quality_mode=...)` needs no `BenchmarkRun` — it reads back that same
`AuditEvent` trail for ANY real campaign, live, and returns:

- every prompt-purpose version that fired for that platform/language (note:
  `master_campaign_concept`/`campaign_copy` are campaign-wide/per-language
  concepts recorded under the PRIMARY platform they happened to run under,
  not every platform that later reuses them — query with the primary
  platform/language to trace those two specifically; every platform-scoped
  purpose — `platform_adaptation`/`creative_direction`/`scene_generation`/
  QA/revision purposes — traces correctly for the exact platform/language
  asked for).
- `verified_product_facts_resolver_version`, `renderer_version`,
  `template_version`, `qa_rubric_version` (plain module-level constants).
- the run's own `platform`/`language`/`content_type`/`quality_mode`.

See `tests/test_build6_acceptance.py::
test_cross_platform_bilingual_campaign_variants_are_independent_and_traceable`
for this exercised against a real (non-benchmark) pipeline run, not merely
asserting the database columns exist.

## 8. Scene reuse (cost discipline)

An AI-generated background/scene is language-independent; only the
deterministic typography layer differs per language. `_render_additional_
platform_variants` caches a generated background per (platform, slide index,
scene signature) and reuses it across that platform's other targeted
languages whenever their `CreativeDirection`s produce the identical
`_scene_signature` — `PlatformCampaignVariant.shared_scene_source` records
which earlier variant's scene was reused (`""` when this variant is the one
that generated it, or when no AI background ran at all). Full AI
recreation (`recreate_with_ai`) is NOT shareable this way — the copy text
bakes directly into those pixels — so each language pays for its own
recreation; this is a real, documented cost difference between the two
image modes, not an oversight.

## 9. Video-oriented platforms (TikTok / YouTube Shorts)

`data/platform_creative_specs.py` marks these content types
`supports_static=False` — `run_visuals_stage` never attempts to render an
image for them. Instead `generate_video_concept` produces a structured
`VideoConcept` (hook/script/shot_list/timing/on_screen_text/caption/
cover_creative_brief), the variant's `status` becomes `SCRIPT_ONLY` (or
`SCRIPT_UNAVAILABLE` with no AI provider), `slide_asset_paths` stays `[]`,
and `VideoConcept.is_rendered_video` is hard-fixed `False` (not
caller-settable). QA (`qa_engine.py::run_video_qa`/`_qa_one_video_variant`)
judges only the structured text — hook/script/shot-list/timing/on-screen-text
/platform fit/language/brand alignment/CTA — and never claims a
rendered-video fidelity score, because no video file is ever produced by
this app.

## 10. Real Hanna acceptance

`tests/test_build6_acceptance.py` proves the architecture against Hanna's
own real brand/product identity (Hanna From Japan; Melano CC Essence,
canonical ID `HANNA-PROD-000006`) using a deterministic fake provider — see
that file's own module docstring for why (**this development sandbox has no
OpenAI key and no network path to the OpenAI API — it has never made, and
cannot make, a real call**).

**`scripts/run_live_acceptance.py` is the genuinely LIVE counterpart**,
meant to be run on the owner's own PC with their own key:

```
cd backend
python scripts/run_live_acceptance.py --brand-slug hanna-from-japan --product-slug melano-cc-essence
```

It runs the real pipeline across `[instagram/pt-BR, instagram/en,
facebook/pt-BR, pinterest/en, tiktok/pt-BR]` for one shared
`MasterCampaignConcept`, refuses to run against a product with no confirmed
`VerifiedProductFact`, and reports a per-case `PASS`/`NEEDS_REVIEW`/`FAIL`
verdict (never forced to `PASS` just because the run completed), real cost,
and the full creative-system snapshot — written to
`data/live_acceptance/<timestamp>.json`.

## 11. Known gaps (stated honestly, not hidden)

1. No dedicated pre-flight "expected generation scope" endpoint yet (§3) —
   the multiplication (`platforms x languages`) is trivially computable
   client-side today, but nothing surfaces it as a first-class API response.
2. `quality_mode="premium"` does not automatically raise `qa_best_of_n`/
   `qa_max_retries` (§5) — the mechanism exists, the auto-link doesn't.
3. Benchmark campaigns (Build 5's `run_benchmark_case`) are always
   single-platform/single-language, so a `BenchmarkRun`'s own
   `PlatformCampaignVariant` never exercises `CreativeDirection`'s AI-
   generation path — documented since the Build 5 repair
   (`docs/architecture.md`'s "6a-2" section); Build 6's own acceptance test
   exercises that path via a real multi-platform/bilingual pipeline run
   instead, since the benchmark system structurally cannot.
4. `estimated_cost_usd` (§6) is best-effort against a hardcoded,
   point-in-time pricing table — never live-fetched, never claimed exact to
   the cent. Real token/image COUNTS are always exact (straight from the
   API response); only the dollar conversion is approximate.
5. This sandbox cannot execute `scripts/run_live_acceptance.py` itself (no
   OpenAI key, no network path to the OpenAI API) — every "LIVE_ACCEPTANCE"
   figure in the Build 6 completion packet reflects this honestly rather
   than fabricating a pass.


## Prepared product geometry and two-stage image dimensions

The locked product compositor consumes explicit JSON `PRODUCT_SCALE` (for example,
`46% canvas width`) and `PRODUCT_PLACEMENT` (`right lower half` or `lower-right`).
Widths are percentages of the final canvas, preserving package aspect ratio and
all authentic artwork. Left/center/right and upper/lower anchors use the existing
safe top and bottom margins; no rotation, label removal, or synthetic packaging is
permitted. Unsupported/partial geometry or a product that cannot fit the safe
canvas fails closed. Briefs without explicit geometry retain legacy placement.
No offsets or arbitrary free-form positioning are inferred from generated prose.

Sunburst native generation remains **1088x1360**, xhigh, one image. Instagram
portrait final export remains **1080x1350**. These are intentionally distinct
stages: the background is fitted to the platform canvas before deterministic
product placement and HTML typography. A final 1080x1350 PNG is the expected QA
size, not a dimension failure; never resize it back to 1088x1360. Native generation
size, model, quality, call limits and retry policy remain unchanged.

The slide-1 calibration's package-label clutter finding remains a failed visual
acceptance. Geometry verification alone does not establish creative QA PASS or
operator publishability. Preserve that failed artifact and its original report;
any future paid calibration requires separate authorization and canonical QA.


## Owner target reference contract (count-preserving)

A governed prepared `visual_brief` may contain `REFERENCE_TARGET`, a typed
`ReferenceTarget`: exact `reference_id`, lowercase SHA256, `role: TARGET`,
`source: OWNER_APPROVED_TARGET`, minimum fidelity (85-100), and `ReferenceGrammar`.
The selected BrandAsset must be a visual_reference in the same brand with an
owner-managed `owner-approved-target` or existing `approved-custom-gpt-quality-benchmark`
label. Explicit target selection overrides latest/generic benchmark lookup. Target
snapshots must be the single selected reference and resolve to matching real bytes.
Role INSPIRATION does not activate or satisfy this target contract.

The grammar uses controlled style values for typeface, headline scale/position,
supporting-copy position, density, callout treatment, environment/materials,
lighting/depth, negative space, color/hierarchy and production-finish signals.
It contains no new campaign copy, product facts or factual badges. Text creative
direction receives this grammar and exact identity, never image pixels. Image
generation receives the exact target pixels but only a scene-only specification:
NO PRODUCT OBJECTS, PACKAGING, DUPLICATES, BRAND MARKS, GENERATED LABELS/TEXT,
FAKE AWARDS or BADGES. A reference's product is explicitly excluded. Positive
product/pouch instructions and arbitrary full-scene prose are not concatenated
into this background request. Prompt obedience alone is not acceptance.

Deterministic rendering consumes the same typed grammar rather than imposing a
pale editorial panel. All visible text retains existing claim/evidence binding;
no extra promotional wording is injected through CSS or grammar. Existing product
placement, aspect ratio and native/final dimensions remain unchanged.

The existing final vision call receives labeled owner-target pixels, native
backgrounds, the factual source photo and final output(s). Missing target images,
identity substitution, missing native backgrounds, low reference fidelity, or
unknown/positive generated-product/duplicate-product findings cannot PASS, even
with a high generic score. Reference checks compare composition, hierarchy, type,
placement, density, callouts, negative space, environment, light/depth/materials,
color and production finish. Operator publishability remains a human decision.
Legacy campaigns without a target retain their existing renderer and QA contracts.
Background generation now consistently uses the background-only instruction.

No extra calls: calibration stays 1 image / 5 text / 2 vision; full mode stays
6 / 10 / 2. Added reference/native images change payload exposure, not call class
or count. Before a future paid run disclose the new image/token payload; retain
all pre-call caps, image-payload limits, zero retries and no automatic regeneration.

LuLuLun direction data and artwork are NOT changed by this system capability.
A later governed direction update must bind the exact owner target, attach its
approved structured grammar, replace restrained-serif/sparse/quiet directives
and populate only approved supported claim/callout text. Keep 46% lower-right and
1088x1360 native -> 1080x1350 final. The @cosme artwork conflict remains unresolved:
(A) acquire/approve a genuine exact-variant label-free asset, or (B) explicitly
permit depiction of the authentic label under owner policy, or (C) submit another
evidence-backed exact-product asset strategy. No automatic selection, label
retouching, 28-sheet substitution, or next paid run is authorized.

## Campaign reference variation QA

Target campaigns share exact owner identity/hash/role/source/threshold and the
same typography, callout design, density, background/material/lighting/depth,
color behavior, hierarchy, premium signals and prohibited elements. Headline
scale/side, supporting-copy side and negative-space enum may vary only according
to each prepared slide. Product position/scale remain the separate prepared
placement contract. A rendered sidecar cannot authorize its own variation.

The existing final vision call receives an ordered prepared-slide manifest with
slide IDs, contract digests, individual grammar and product geometry. It must
return exact per-slide coverage and explicit campaign-reference coherence.
Missing, repeated, foreign or stale results fail closed; every slide must meet
its own fidelity threshold and background-only/one-product checks. High aggregate
scores cannot hide a weak slide or unrelated aesthetics. Calibration requires
only the supplied slide's result, while full mode requires all six. Call counts
remain 1/5/2 and 6/10/2; no extra vision request is introduced.

This QA capability does not approve blank registry labels, mutate the preserved
52-field direction proposal, resolve product artwork policy, or add renderer
finishes/icons/circular text. Those remain separate governed steps.

## Optional deterministic reference paint

`ReferenceGrammar.headline_paint` optionally selects `linear_gradient`: 2–8
strictly ordered `{offset, color}` stops from 0 to 1, exact six-digit hex colors,
and a finite angle from 0–360 degrees. Metallic bands are ordinary explicit
gradient stops, not a brand preset. Stroke width is 0–2 px; shadow blur 0–12 px
and vertical offset -2–4 px at the 1080 px baseline, scaled by canvas width.
The existing escaped headline is clipped to the fill; no additional text exists.

`ReferenceGrammar.icon_paint` optionally selects `luminous_vector`, with hex tint
and glow color, glow radius 0–12 baseline px, opacity 0–1, vector stroke .5–3,
ring width 0–2 and size scale 1–1.5. Only existing decorative star/sparkle,
droplet, leaf and check glyphs map to fixed code-owned paths. Unknown luminous
glyphs fail closed. No raw SVG, scripts, URLs or asset paths are accepted.
The original glyph and all factual card text retain their existing evidence
inventory; paint cannot add a claim or authorize a benefit/award symbol.

Both controls default off and are omitted from serialized grammar when absent,
preserving old targets and contract digests. No-target and unpainted HTML remain
unchanged. Present paint controls are part of the shared campaign visual language.
Determinism assumes the same local Chromium/fonts; no cross-platform pixel
identity is promised. No network, extra provider call, new font or external icon
asset is needed. Circular text is excluded. Product placement and dimensions,
background-only generation, reference/duplicate/coherence QA and call guards stay
unchanged. The preserved 52-field proposal does not activate these controls;
later explicit direction deltas, owner trust approval and product-artwork policy
remain separately governed before any paid calibration.

### Prepared paint variation in campaign QA

Campaign reference identity and paint language remain shared. Only
`headline_paint.angle_degrees` and `icon_paint.size_scale` are slide-variable,
and each must equal the exact prepared slide contract. Their existing typed
bounds remain enforced. Campaign comparison retains effect presence/kind,
all gradient stops (colors and offsets), headline stroke/color and shadow
color/blur/offset, icon tint, glow color/radius/opacity, stroke and ring width.
Material, lighting and the rest of the shared reference grammar remain enforced.
Unknown properties fail schema validation; no other paint freedom is inferred.

The ordered manifest and contract digest bind every slide; unprepared values,
different target identities, low individual fidelity or incoherent paint language
fail regardless of generic scores. The existing final-QA request assesses these
rules without additional calls. Absent paint controls preserve legacy behavior.

This QA-only repair does not activate candidate values or grant reference trust.
The preserved 52-entry direction proposal remains immutable; prospective paint
objects fit inside its already-counted visual_brief updates. Reference approval,
direction mutation, product-artwork decisions and paid visual acceptance remain
separately governed. Structural/mock QA does not establish live visual acceptance.


### Explicit physical package-mark permission

The optional `Asset.ai_metadata.authentic_package_mark_permissions` list lives on
verified real source assets. Missing/empty grants no exception. Strict version-1
entries bind campaign_id, brand_id, product_id, source_asset_id, render_asset_id,
source_sha256, render_sha256, OWNER authority, timezone-aware approved_at,
owner_decision_sha256, APPROVED/REVOKED status and
use=PHYSICAL_PACKAGE_DEPICTION_ONLY. allowed_marks contains unique mark_id,
award/ranking kind and quoted visible_text identity tokens. Unknown, partial,
duplicate or mismatched metadata fails closed. Siblings inherit nothing.
Actual hashes and the existing approved-master/source contract remain required.

Source-anchored policy leaves the selected approved master's full metadata
provenance and prepared direction untouched. QA separately attests the resolved
permission digest: changing/removing/revoking it invalidates prior QA. A directly
rendered source whose metadata changes still needs explicit provenance rebinding;
no existing identity check is relaxed.

The existing final vision request gains typed host-only per-slide context and
labeled source, exact render asset, native background and final images. Strict
PackageMarkSlideQA results must match slide/contract/permission/asset identities,
be complete, and classify allowed marks as AUTHORIZED_PRODUCT_LAYER with a
matching approved mark_id. GENERATED_BACKGROUND, RENDERER_ADDED, UNKNOWN, added
award/ranking content and unsupported promotional award/ranking copy fail.
Missing assessments cannot approve permission-enabled evaluations. No free-text
hard failure is suppressed. All claim, reference, duplicate-product, background
and campaign-coherence gates remain required. Legacy parsing remains compatible
and grants no exception without policy. No additional provider call is created.

Package pixels and permission never create claim evidence or authorize headline,
callout, translation, emphasis or promotional award assertions. There is no
brand/product/award-name exception. Canonical permission data has not been
activated by this source repair; its mutation remains separately governed.
Structural/mock tests do not establish live visual acceptance.


### Governed prepared-run monetary authorization

Prepared runs require `--max-budget-usd` with a finite positive USD amount.
`--bounded-exposure` selects the prepared request restrictions; it does not
substitute attempt limits for monetary authorization. The pure whole-run gate
resolves the execution policy and model maxima before constructing the SDK client.
Maximum exposure must be <= authorization (equality is allowed); currency maxima
round upward. Missing/unpriced/unbounded exposure fails closed.

The provider owns a shared policy: `CALIBRATION_SLIDE1` independently caps image,
text, vision attempts at 1/5/2; `FULL` retains 6/10/2. The same counts determine
maximum monetary exposure. Best-of-N=1, QA/SDK retries=0, fallbacks=0 and concurrency=1
are enforced; unsupported multipliers are rejected rather than silently omitted.
The existing monetary ledger reserves before each invocation, retains reservations
on failure or missing usage, and reconciles known actual usage. Unknown usage halts
the governed run. Actual spend cannot retroactively authorize an over-budget call.
Text/vision reserve the full configured model context plus capped output; a local
serialized request/schema byte cap is additional protection, not an image-token
pricing formula. All governed responses cap output at 4096 tokens.

Sunburst's versioned token rates exist, but its authoritative maximum billable
request exposure remains unresolved. `_sunburst_reservation` therefore continues
to reject execution before client construction. This repair does **not** make V5
paid-ready. Historical ~$0.19 costs, operator estimates and project spend-limit
attestations cannot replace an authoritative maximum. A separately authorized
post-repair zero-cost preflight and separate paid authorization remain required.


### V6 local background source contract (inactive)

V6 adds an explicit `LOCAL_COMFY_SDXL` adapter implementing the existing image
provider contract and a separate local slide-1 preview entrypoint. It never
falls back to Sunburst or a paid provider. The existing Sunburst monetary guard
is unchanged; V5 remains closed for external billing-authority reasons.

This source build installs/starts no ComfyUI runtime, approves/downloads no model
or custom node, and activates no URL or production backend. The repository
manifest deliberately has `UNAPPROVED` status and null artifact/workflow hashes.
It must fail before HTTP client construction until a separate governed host
activation approves and hashes the exact checkpoint, image encoder, IP-Adapter,
custom-node code, runtime lock, workflow and dedicated single-job runtime identity.
The graph is a contract template; custom-node schema compatibility is untested.
No auto-download or arbitrary/cloud workflow nodes are supported.

Only an explicitly supplied 127.0.0.1 HTTP endpoint is accepted. Redirects and
proxy environment inheritance are disabled. The adapter allows one attempt,
one reference with exact hash, a bounded prompt, fixed 1024x1280 latent and PNG
output, fixed sampling bounds and explicit seed. Errors/timeouts/missing output
fail closed; a submitted failed job gets a bounded interrupt on the dedicated
runtime, never a retry. No package/model installation is part of the adapter.

The reference remains style authority only. A negative prompt forbids products,
packages, text, logos, awards and ranking graphics; prompting is not a semantic
absence guarantee. Strict existing duplicate/product/reference/claim/package-mark
QA and owner review remain mandatory. Local generation never creates product
provenance or claim evidence. Workflow/model/reference/output hashes and seed are
recorded as LOCAL_GENERATED_BACKGROUND sidecar provenance. The original product
compositor, claims, owner reference, 52-field direction and permission stay intact.
Final deterministic output remains 1080x1350 with locked product placement.

A later separately authorized preview copies SQLite into shared writable memory,
uses frozen plans and deterministic direction, disables paid text/vision clients,
and reports PREVIEW_ONLY with semantic QA NOT_RUN and owner acceptance PENDING.
It cannot approve the campaign. Local image generation has zero provider cost,
but electricity/runtime work is not free and provider-backed text/vision QA is
still separate and paid. No full-QA-zero-cost or premium-visual-acceptance claim
is made. Complete Git governance, runtime/license/model hash verification and
compatibility preflight before authorizing any actual local preview.


#### V6 absolute deadline and streaming ceilings

HTTPX read/inactivity timeouts are secondary controls, not the governing timer.
The local adapter now uses the asyncio loop monotonic clock and an absolute
`asyncio.timeout_at` deadline across the HTTP operation, polling and cleanup.
The configured timeout includes cleanup: `min(5 seconds, timeout/4)` is reserved
inside that budget, so normal work has an earlier deadline. No request restarts
this budget. Cleanup never receives a fresh five seconds after expiry.

All response bodies are read through `AsyncClient.stream` and raw chunk iteration.
The image ceiling remains 33,554,432 bytes (32 MiB); metadata/JSON/interrupt bodies
have a 4 MiB ceiling. The running byte count is checked before appending each
chunk, with 64 KiB iteration chunks. Exactly-at-limit plus EOF is accepted by the
reader; limit+1 fails immediately on detection, without consuming the remaining
body. PNG/dimension checks remain independent. Content-Length is only an early
validation aid. Identity content encoding is required; compressed responses are
rejected before decoding to prevent decompression-based size bypasses.

Stream contexts close responses on success, malformed data, size failure,
network errors and cancellation. One bounded interrupt is attempted only if a
submission may have occurred; the owned HTTP client is closed in `finally` using
the same remaining total budget. Interrupt/client cleanup errors are noted on the
original failure; a successful operation cannot hide client-cleanup failure.
Cancellation is cooperative, not a hard-real-time process kill. If cleanup cannot
complete by the deadline, its state is unconfirmed and the operation fails; no
claim is made that a server job has stopped solely because the client timed out.
There is one generation attempt, no retry, and no Sunburst or paid fallback.

This is still inactive source only: no ComfyUI installed/started, no model approved
or downloaded, and no visual calibration completed. A future local preview remains
PREVIEW_ONLY and does not establish full semantic QA or campaign approval.
