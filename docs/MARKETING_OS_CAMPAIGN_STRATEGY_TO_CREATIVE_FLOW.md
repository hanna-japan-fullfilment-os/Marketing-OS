# Campaign strategy to premium creative — V12.8

## BUILD6R-EXEC-0001 opt-in planning

`plan_campaign(request, library, execution_contract=True)` adds purpose-aware
execution proposals while preserving exact approved copy, claims and qualifiers.
The default remains the legacy plan for backward compatibility. `validate_plan`
rebuilds the corresponding mode; altered proposals or unsupported versions fail.
The existing API/schema is unchanged; opt-in is an offline Python service call.

Composition families follow communication jobs, not slide number: product
recognition/benefits use product_hero; factual formula/construction information
uses editorial_detail without material diagrams; usage/routine uses ritual_context
with motivated lighting and a grounded product. Unknown jobs require preparation.
Legacy Reel/paid action text is not allowed to override the opt-in safe mechanism.
The existing format/copy/timing/coverage contracts remain authoritative.

These proposals are PENDING, planning-only and never production-ready themselves.
The operator supplies full camera, spatial, light, typography, product and approved
reference requirements through the version-2 handoff contract documented in
BUILD6R_V121_PREMIUM_HANDOFF.md. A nonblank benchmark string is not reference
approval. Exact actual asset hashes and owner-approved reference authority are
checked at the production-handoff boundary.

Structural completeness, plan owner review, image technical QA and final visual
owner acceptance are separate gates. No 9.0 aesthetic approval is inferred.
This implementation neither creates new reference approvals nor changes campaign
copy, artwork, renderer/typography capabilities, ComfyUI or paid-call guards.

## Entry points

`POST /api/strategy-library/premium-campaign-plan` accepts the typed
`CampaignCreativeStrategyRequest`; `plan_campaign(request, library)` is the same
offline service. It reuses the canonical strategy catalog/archetypes and V12.4
exact-product claims/language checks. No application startup, DB session, provider
or renderer is needed to generate the planning package.

`scripts/planning/build6r_v128_lululun_plans.py NEW_OUTPUT_DIRECTORY --benchmark SLIDE2_IMAGE` produces the
LuLuLun six-format owner-review package offline. It uses existing exact-product
research, not another SKU. No claim-library approval flags are changed.

## Flow and responsibility

1. Select the exact product/library. Research provenance and reviewed PT-BR
   wording remain authoritative; unresolved/prohibited records fail closed.
2. Resolve objective, audience, funnel, canonical tactic, angle, hook, primary
   and secondary messages, proof and CTA. Empty required strategy fields fail.
   Angle/audience/hypothesis strings are internal strategy, not advertising copy.
3. Declare product-information coverage with priority, evidence claim ID and
   tactic relevance. Out-of-scope information requires an omission rationale.
4. Rank existing tactic recommendations by objective, funnel, evidence, novelty,
   complexity, objections and supplied prior usage. The operator chooses; no
   random rotation or silent auto-selection. Unsupported offer/comparison tactics
   require appropriate operational evidence and an adapter before this export.
5. Adapt roles to each format and tactic. Five-slide and ten-slide sequences
   differ; expanded education gets more verified facts. Organic objectives and
   paid hypotheses remain explicit. Stories have tap progression, Reels have
   timed shots and exact-copy voiceover, statics carry one proposition.
6. Bind every visible string to exact approved claim IDs using V12.4 resolve_copy;
   preserve qualifiers and export prohibited wording. Manufacturer ingredient
   evidence is never independent clinical/testimonial proof. No invented prices,
   stock, shipping, country-of-origin story, treatment or comparative result.
7. Record actual per-asset assignments and usage, tactic/angle/hook/layout
   diversity and coverage denominator. Relevant omissions are deliberate density
   choices, not automatically failures. Irrelevant items do not enter the score.
8. `premium_handoff.export_strategy_planning_package` rebuild-validates the plan
   against the current library before writing the planning JSON/instructions.
   Mutated/stale copy, strategies, assignments or release flags are rejected.
9. Owner reviews strategy and exact copy. Only then can a separately authorized
   external creative run consume the strategy-derived briefs and actual assets.
   Planning files carry `planning_only=true`, `creative_release_allowed=false`
   and owner PENDING. There is no provider dispatch from this endpoint/export.
10. Future artwork must pass fidelity, typography, integration, brand cohesion,
    premium quality, postability and explicit human review. Structural checks
    are insufficient; no automatic campaign approval or artwork generation.

## Premium benchmark

The latest owner-designated Slide 2 is a quality-direction reference: lighting,
staging, typography, integration, finish and Hanna palette. It is not a layout
lock, an approved asset or exact product source. Its earlier failed QA remains
historical evidence; V12.8 does not relabel it PASS. Product identity comes from
canonical product assets. Future layouts vary with tactic/role while preserving
campaign identity. No generic panel fallback is introduced.

## ROAS matrix

Angle, hook and execution are independent axes. Given suitable evidence, the
LuLuLun example yields four angles × two exact approved hooks × two visual
executions = 16 planning hypotheses. Every row records audience/funnel, message,
proof scope, CTA and recommended placements. Outcomes require future attributable
measurement; ROAS is not guaranteed. No campaign is launched.

## Message history and coverage

The request accepts prior MessageUsage records (canonical tactic, hook claim,
angle, primary claim and layout family). The export returns usage snapshots for
reuse by the next request; it does not invent historical usage or write a second
campaign registry. Missing history is explicitly disclosed. Two or more repeated
dimensions produce diversification recommendations. This is advisory, not a claim
that canonical analytics were queried. Existing campaign selection/analytics and
its operational evidence guards remain intact.

Coverage is item-based, not character count or creative scoring: each relevant
declared information item counts once when its ID actually appears in an asset's
approved_copy binding. Both numerator and denominator are exported; unused items
retain their reason. The sample short and long education/consideration plans share
the declared relevant set for transparent comparison. A narrower future conversion
campaign should mark irrelevant educational facts accordingly before planning.

## Boundaries

Commercial-import research/checks are not part of this marketing planning path.
No AFE/CNPJ/importer inputs are required here, no commercial-clearance claim is
made and no earlier regulatory evidence is edited. Existing production handoff
and human approval controls are not silently bypassed by a planning-only export.
No source assets, claims, canonical database, settings, environment, existing
artwork, renderer, ComfyUI, local runtime, migrations or paid-call guard changes.

## Validation

### V12.10 bounded repair

The benefit-led five-slide sample now has five distinct primary information jobs:
tactile proposition, core benefits, sheet construction, formula/pack and routine
decision. Only the benefit slide leads on hydration. The ten-slide education plan
uses separate identity, hydration, qualified radiance, tactile experience,
construction, formula, formulation preference, application, routine/aftercare and
decision jobs. Each exports incremental value/reason and subordinate secondary
copy. High-priority coverage means the original PRIMARY + SECONDARY priorities;
these are never demoted to improve a score. All-relevant coverage remains separate.

Meta now uses four motivation families, two evidence-distinct hook entry points
each and concrete communication-mode concepts A/B. Reviewed CTA policies are
required for awareness, consideration and conversion; no stronger claims appear
down-funnel. Each row records motivation, stage, destination intent, test question,
production priority and initial-subset status. Actual URLs/media events still need
owner configuration; no live purchase availability is asserted. Hook/stage pairs
are intentional segments, not a causal hook A/B test. Compare execution A/B while
holding hook, stage, audience segment and approved visible copy fixed. Eight rows
(one hook and both executions per angle) are recommended initially; the other
eight remain ranked planning hypotheses, not automatic production jobs.

The Reel now plans a moving-sheet hook, product identity, hydration, tactile
handling, actual application and CTA across thirty seconds. Each scene has a
distinct action, purpose, product visibility, audio role and motivated transition;
voiceover timing is estimated from exact copy, not represented as a recorded read.
Stories/static roles and visible-copy bindings are preserved. Existing Slide2 is
classified HYBRID_BENEFIT_FORMULA_VISUAL and retained as QUALITY_REFERENCE_ONLY;
its content does not dictate new roles or imply new visual approval.

The targeted suite exercises the real API function, all seven format IDs, role
diversity, expanded coverage, ROAS axes, temporal video, static discipline,
qualifiers, claim revocation, stale/edited exports, canonical IDs and missing
operational/comparative evidence. Tests use isolated temporary paths and no
provider calls. Existing tests are not skipped or rewritten to hide regressions.
