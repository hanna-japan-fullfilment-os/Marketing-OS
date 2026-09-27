# Campaign Pipeline — design + build order

## The loop (section 68 of the brief)

```
SOURCE LIBRARY → PRODUCT+BRAND INTELLIGENCE → CURRENT RESEARCH → CAMPAIGN MEMORY →
OPPORTUNITY IDENTIFICATION → STRATEGY → CREATIVE PRODUCTION → QUALITY CONTROL →
HUMAN APPROVAL → DISTRIBUTION TRACKING → PERFORMANCE → (feeds back into) STRATEGY
```

## Autopilot orchestration (target design, section 18)

`CampaignOrchestrator.run_autopilot(brand_id, category_id, objective, channels)`,
implemented as a `jobs` row of type `autopilot_campaign`, steps through:

1. Load brand rules (`brands` + `brand_assets`).
2. Load category/product context (`categories`/`products`, recent `campaigns` in scope).
3. Query `assets` for candidates: active, matching category/product, ranked by
   `times_used` ascending / `last_used_at` oldest-first.
4. Load recent `campaigns` + `campaign_fingerprints` for the category (last N).
5. Compute underused strategy types: count recent `campaigns.strategy_type_id` per
   category against the Strategy Library (`campaign_strategy_types`), weighted by
   family (don't let ATTACK dominate every campaign just because it converts well —
   see `docs/architecture.md` section 5a), and favor underused types with acceptable
   historical performance (`performance_insights`, once available). A manually chosen
   `strategy_type_id` (from the Strategy Library page) or a Defense recommendation
   (`triggered_by_event_id` set) skips this step and locks the type instead.
6. Check research freshness: does a non-expired `research_runs` row exist for this
   brand/category within `TREND_RESEARCH_TTL_HOURS`/`CATEGORY_RESEARCH_TTL_HOURS`? If
   not, run `ResearchProvider.research(...)` and persist `research_sources` +
   `research_insights`.
7. Generate 2-3 strategy candidates via `AIProvider.generate_structured(...,
   schema=CampaignStrategy)`, grounded in the research insights + brand rules.
8. For each candidate, compute a fingerprint against fingerprint history
   (`fingerprint.py`) and classify novelty; discard `EXACT_REPEAT`/`TOO_SIMILAR`.
9. Select the strongest `FRESH`/`SIMILAR_BUT_ACCEPTABLE` candidate (asking the user only
   if all candidates land below the acceptable threshold — surfaced as a job warning,
   not a silent failure).
10. Create the `CreativeBrief` (schema) from the chosen strategy.
11. Generate `CampaignCopy` (schema) — hook/headline/body/CTA/caption/hashtags/alt text,
    plus a community-native variant per targeted `opportunities` row.
12. Generate the `CarouselPlan`/`SlidePlan` (schema) — one slide row per
    `campaign_slides` entry.
13. Render creative per the hybrid pipeline below.
14. Run automated QA checks (section 22) — persist `campaign_outputs` kind=`qa_report`.
15. Persist everything; set campaign `status=REVIEW`.
16. Job marked `COMPLETED`; frontend shows the campaign in Review.

Every step writes an `audit_events` row and updates `jobs.progress`/`step` so the UI can
show "Researching trends... / Selecting assets... / Rendering slide 2 of 6...".

**Status in this repo:** done. `services/orchestrator.py`'s `run_autopilot(...)` wires
every numbered step above together end to end — steps 1-4 (load brand/category/
product/candidate assets), 5 (lock a Strategy Library type, respecting one already
set by a manual pick or a Defense recommendation), 6 (research, via `run_research`),
7-9 (strategy candidates, fingerprint/novelty filtering, selection), 10-12 (creative
brief, copy, carousel plan), 13-14 (render each slide + QA via the creative
pipeline), 15 (persist + set `REVIEW`), 16 (`Job` marked `COMPLETED`) — and is
exposed via `POST /api/campaigns/{id}/generate`, run synchronously within the
request through `services/jobs.run_job`. `tests/test_orchestrator.py` covers the
happy path, the no-candidate-photos and all-candidates-rejected failures, the
campaign-status guard, an existing `strategy_type_id` being respected rather than
overridden, and a retry after `FAILED` not duplicating slide rows — all against a
`FakeAutopilotProvider`, no real API key or network call needed. Both `POST
/api/research/run` and `POST /api/campaigns/{id}/slides/render` remain callable by
hand for manual, single-step use outside Autopilot.

## Research orchestration (section 5-6) — done

`services/research/openai_research.py`'s `run_research(...)` wraps
`ResearchProvider.research()` with TTL-based caching against `research_runs`
(`find_fresh_research_run` matches on exact brand/category/product scope — a
different category never reuses another category's cache — and respects
`TREND_RESEARCH_TTL_HOURS`/`CATEGORY_RESEARCH_TTL_HOURS`). The "no fake research"
rule is enforced structurally: any insight the model returns with zero
`source_urls` is dropped before it's ever written to `research_insights` — see
`_persist_result`. A `ResearchRun` row is still created even when everything gets
filtered out, so "we asked, nothing came back cited" is visible rather than the
research step silently not having happened.

Callable today via `POST /api/research/run` (`brand_id`, optional `category_id`/
`product_id`, `objective`, optional `geography`/`audience` overrides,
`force_refresh`) — see `backend/app/api/research.py` and the Research Radar page.
Requires an OpenAI API key (400 with a clear message otherwise — never silently
returns fabricated insights). `tests/test_research.py` covers the caching logic
end to end with a fake provider, so none of it needs a real API key or network
access to verify.

## Hybrid creative pipeline (section 8) — Phase 6, done

```
source image (original, untouched)
   │
   ▼
product/image analysis (vision model → what it is, role, salient region)
   │
   ▼
optional background isolation (rembg or similar, local, deterministic)
   │
   ▼
creative art-direction prompt (from CreativeBrief + brand visual style)
   │
   ▼
AI-generated scene/background (ImageProvider.generate, brand-styled)
   │
   ▼
original product compositing (Pillow: paste the real product onto the new background) —
   OR, when full AI recreation is used (round 15, on by default for Autopilot), the
   product photo itself is redrawn into a brand-new scene by the model in one step,
   skipping isolation/background/compositing entirely for that slide
   │
   ▼
HTML/SVG template render (Playwright: exact typography, logo, layout, at exact social
   dimensions — text and logo stay editable data, drawn as real HTML/CSS, UNLESS a full
   AI recreation was given text to bake in (round 16): then the AI designs the whole
   graphic including the marketing text, and this app's HTML layer draws only the logo,
   never both — see "AI-baked-in text + custom carousel length" below)
   │
   ▼
automated QA (dimensions, file integrity, text overflow, safe margins, logo presence,
   duplicate similarity; optional AI visual QA pass) → human approval (authoritative)
```

Status per step, this round:

- **Source image, read-only** — done (`pipeline.py` opens it exactly once, never writes).
- **Product/image analysis (vision model)** — **done, opt-in (round 11)**. See
  "Vision-model product-zone detection" below. By default the product zone still
  comes from the chosen template's fixed layout, not a per-photo analysis, unless
  `detect_product_zone=true` is passed.
- **Optional background isolation** — done (`background.py`: `NoOpBackgroundIsolator` by
  default, an opt-in `RembgBackgroundIsolator` when installed).
- **Creative art-direction prompt / AI-generated scene** — done, opt-in (see "Brand
  visual style & AI-generated backgrounds" below): `generate_ai_background(...)` in
  `services/orchestrator.py` builds the art-direction prompt from the brand's own
  configured voice/visual_style/colors and calls `ImageProvider.generate(...)`,
  style-guided by the brand's uploaded visual-reference photos when any exist. Off
  by default — the background stays the deterministic brand-color gradient
  (`compositor.make_background`) unless `use_ai_background=true` is passed.
- **Original product compositing** — done (`compositor.py`), used whenever full AI
  recreation isn't (see next bullet).
- **Full AI recreation** — **done, round 15**, on by default for `POST /generate`
  (Autopilot), off by default everywhere else. `recreate_creative_image(...)` in
  `services/orchestrator.py` sends the real source photo — plus up to two of the
  brand's Inspiration Library examples, when any are uploaded and scoped to the
  campaign's category — to `ImageProvider.generate(..., reference_images=[...])`,
  which routes to OpenAI's image-edit endpoint. The result replaces isolation,
  background generation, and compositing outright for that slide
  (`SlideCreativeInput.recreated_image`, handled in `render_slide()`); on any failure
  it's caught and the pipeline falls back to the ordinary gradient/AI-background path,
  same best-effort pattern as `generate_ai_background`. As of round 16, when the slide
  has real headline/body/CTA/eyebrow text, it's now passed into this same call and
  baked directly into the recreated graphic (with an explicit legibility/backing
  instruction) instead of being left for a separate HTML layer — see "Full AI
  recreation + Inspiration Library" and "AI-baked-in text + custom carousel length"
  below.
- **HTML/SVG template render** — done (`templates.py` + `renderer.py`, via Playwright).
  As of round 16, the `.text-block` (headline/body/CTA) and its background scrim are
  omitted entirely when a slide's text was baked into a recreated image instead —
  only the logo is drawn separately in that case.
- **Automated QA** — done (`qa.py`: file integrity, exact dimensions, text overflow via
  real DOM measurement, logo presence). As of round 16, a `text_expected` flag tells QA
  whether a missing `.text-block` is a real failure or the expected shape of a
  baked-in-text slide. Duplicate similarity is a campaign-level concern handled by
  `fingerprint.py`, not per-image QA, so it isn't repeated here.

By default, `/generate` (Autopilot) now fully recreates the product photo by AI
(round 15); the manual render endpoint and the "Visuals only" advanced-mode stage
still default to the deterministic brand-color gradient
(`compositor.make_background`), and the product zone still comes from the chosen
template rather than a vision-model analysis of the photo, unless explicitly turned
on — see `docs/architecture.md` section 5o and the brief's section 8/65 ("no images
with AI-generated malformed logos when exact logos exist locally").

## Vision-model product-zone detection (round 11) — done

The last unbuilt piece of the hybrid creative pipeline above. A template's product
zone is a single fixed rectangle used for every photo rendered against it — fine
when photos are framed consistently, but a poor fit when the product sits in a
different part of the frame from shot to shot. `detect_product_zone=true` (on
Autopilot, Visuals only, or the manual `/slides/render` endpoint) has
`AIProvider.detect_product_zone(image_path, model)` — implemented via
`responses.parse(text_format=ProductZoneDetection)`, the same structured-vision
pattern as `analyze_visual_style` — look at that specific photo and return a
tight crop box (`crop_left`/`crop_top`/`crop_width`/`crop_height`, all fractions
of the image in `[0,1]`) plus an `anchor` (`center`/`bottom`/`top`).
`services/creative/pipeline.py::render_slide` crops the isolated product to that
box (clamped at the image edges) and overrides the template's anchor via
`dataclasses.replace(zone, anchor=detection.anchor)` before compositing — nothing
else about the render changes. `services/orchestrator.py::detect_product_zone`
wraps the call in the same best-effort try/except pattern as
`generate_ai_background` (round 9): any failure returns `None`, and the caller
falls back to the template's fixed zone rather than failing the render. Off by
default everywhere, including Visuals-only, so its no-key property is unaffected
unless a user opts in. `SlideRenderResult.product_zone_detected: bool` reports
whether it actually ran, shown on Campaign Detail as "· product zone
auto-detected".

Tested in `tests/test_creative.py` (crop-math including edge clamping, a full
render with detection overriding the anchor, `product_zone_detected: False` when
not requested), `tests/test_orchestrator.py` (called once per slide when enabled,
graceful fallback on failure, off by default), `tests/test_api.py` (the manual
render endpoint's path), and `tests/test_openai_provider.py`
(`OpenAIProvider.detect_product_zone` against a fake SDK client).

## Brand visual style & AI-generated backgrounds (this round) — done

Two real, previously-missing pieces, built together because they share the same underlying
asset (a brand's own uploaded reference photos):

**Brand assets finally have endpoints.** `BrandAsset` (`kind`: logo/font/visual_reference) has
existed in the schema since round 1, but nothing ever exposed it over the API — a brand's logo
has never once appeared on a rendered creative in this app, despite `resolve_brand_logo_path`
looking for one on every render since round 3. `POST /api/brands/{id}/assets` (multipart:
`file`, `kind`, optional `label`) now writes the file under
`OUTPUT_ROOT/_brand_assets/<brand>/<kind>/` and creates the row; `GET .../assets` lists them
(optional `?kind=`); `GET .../assets/{asset_id}/file` streams a resized JPEG preview (same
pattern as `GET /api/assets/{id}/image`); `DELETE .../assets/{asset_id}` removes both the row
and the file. The Brand Detail page (`/brands/{id}`, new — click a brand card on the Brands
page) is the real UI: upload/replace a logo, upload/remove visual-reference photos, and edit
voice/colors/visual-style/forbidden-styles text fields.

**Visual-reference photos can now actually reach the AI**, two different ways:

1. **`POST /api/brands/{id}/visual-style/analyze`** — sends every uploaded `visual_reference`
   photo to the vision model in one call (`AIProvider.analyze_visual_style`, new) and asks it
   to describe the shared style: dominant colors, typography mood, photography style, visual
   descriptors, a voice suggestion. This is a proposal only — it never writes to the brand
   itself; the Brand Detail page shows it and an "Apply to form below" action copies it into
   the editable fields, which still need an explicit Save (`PATCH /api/brands/{id}`) before
   anything is persisted, keeping human approval authoritative over the brand's own style like
   everywhere else in this app.
2. **`use_ai_background=true`** on `POST /api/campaigns/{id}/generate`, `.../generate/visuals`,
   and `POST /api/campaigns/{id}/slides/render` — has each slide's background come from
   `services/orchestrator.py::generate_ai_background(...)` instead of the gradient. It builds a
   prompt from the brand's configured voice/visual_style/colors, then calls
   `ImageProvider.generate(..., reference_images=[...])` with up to 3 of the brand's
   visual-reference photos attached as a live style reference. This is also the fix for a real
   gap in `OpenAIProvider.generate()`: `reference_images` was declared on the `ImageProvider`
   Protocol since round 1 but the implementation silently never used it — passing it changed
   nothing about what got generated. It now routes to the Images **edit** endpoint (`images.edit`
   with `image=[...]` — gpt-image-1 accepts more than one reference image there) instead of
   plain `images.generate` whenever reference images are given.

Off by default everywhere it's exposed, so every existing behavior (including the "Visuals only
needs no OpenAI key" property from the Campaign Builder advanced-mode round) is unchanged unless
a user opts in. On any failure — bad key, rate limit, malformed response —
`generate_ai_background` returns `None` rather than raising, and the caller falls back to the
gradient; an AI-generated background is a nice-to-have layered on a pipeline that has always
worked without one, and a failure there must never take down a render that would otherwise have
succeeded.

Tested in `tests/test_openai_provider.py` (new — direct unit tests of `OpenAIProvider` against a
fake `AsyncOpenAI` double, since every other test in this suite uses a Fake provider instead:
`generate()`'s two branches, `analyze_visual_style()`'s multi-image request shape), new cases in
`tests/test_api.py` (brand asset upload/list/image/delete, the analyze endpoint's two guard
paths and its proposal-only behavior, the manual render endpoint's `use_ai_background` path),
and new cases in `tests/test_orchestrator.py` (`run_visuals_stage` actually calling the image
provider once per slide with the brand's reference photos attached when enabled, falling back to
the gradient without failing the run when the image provider raises, and the gradient staying
the default when the flag is off).

Callable today via `POST /api/campaigns/{id}/slides/render` (`asset_id`, `template_id`,
`platform_key`, `eyebrow`/`headline`/`body`/`cta`, `isolate_background`) — see
`backend/app/api/campaigns.py` and the Campaign Detail page's "Render a creative" panel.
`GET /api/campaigns/creative/templates` lists the templates (as of round 17: "Premium Product
Hero" and "Feature Showcase", the default — see round 17's section below) and the three
platform formats (`instagram_square` 1080×1080, `instagram_story` 1080×1920, `facebook_feed`
1200×630) available today; adding a template means one new entry in
`services/creative/templates.py`, nothing else changes.

## Non-blocking Autopilot (round 11) — done

All four `/generate*` endpoints (`/generate`, `.../generate/strategy`,
`.../generate/copy`, `.../generate/visuals`) now call
`services/jobs.run_job_in_background(...)` instead of the blocking `run_job(...)`
and return `{"job_id": ..., "job_status": "QUEUED"}` immediately — revisiting the
deliberate MVP trade-off noted below in "Job execution model" now that a local
user clicking these buttons often enough made a real polling UI worth building.

The one design wrinkle: a validation failure that used to be a synchronous `400`
inside the blocking call (e.g. "run Strategy before Copy") would otherwise have
silently become an asynchronous `Job.FAILED` returned *after* the endpoint had
already responded `200` — a real regression, caught by an existing test failing
during this round's own development. Fixed by extracting the cheap, local
"does the prior stage's output exist" check into two new synchronous functions —
`check_copy_stage_prerequisite(db, campaign_id)` and
`check_visuals_stage_prerequisite(db, campaign_id)` — called by the API layer
*before* `run_job_in_background` is invoked, so that specific validation still
400s immediately exactly as before this round. Only work that genuinely requires
running the pipeline (an AI call failing, a render failing) surfaces
asynchronously via `Job.status="FAILED"` + `Job.error`, which was already the
correct place for it.

Frontend: `useJob(jobId)` polls `GET /api/jobs/{id}` via TanStack Query's
`refetchInterval` callback (1500ms while non-terminal, `false` once terminal), and
`useInvalidateCampaignOnJobDone(job, campaignId)` refreshes the campaign's data
exactly once per terminal job. `JobStatusLine` on Campaign Detail shows the live
step/progress line while running and the outcome once done, shared by all four
generate actions via an extended `StageButton`.

Tested by rewriting the two full-pipeline tests in `tests/test_api.py` to assert
`job_status == "QUEUED"` on the initial response, poll a new `_wait_for_job`
helper until terminal, then read campaign state via a separate `GET` — proving
the endpoints are genuinely asynchronous now.

## Meta Insights connector (round 11) — done

The performance connector `docs/campaign-pipeline.md`'s own "What's left" list had
flagged since round 7: reading real engagement numbers back from the platform
instead of a human always typing them in. Genuinely separate from the Facebook
Page/Instagram *publishing* connector (round 10) — one posts, the other reads
analytics back for a post that already exists (through this app or logged by
hand with a real `external_post_id`).

`MetaPublishingProvider` (same class as round 10 — no new API-isolation boundary
needed) gained `fetch_metrics(*, provider, external_post_id) -> MetricsFetchResult`,
split into two tiers because they have genuinely different reliability: stable
like/comment counts via a plain `fields` expansion (a failure here fails the whole
sync), and the separate Insights edge for impressions/reach/saves/shares fetched
best-effort (Meta has repeatedly renamed/deprecated metrics on this specific edge
across API versions, so a failure there shouldn't discard the stable counts
already fetched). Only metrics the platform actually returned are recorded — never
a placeholder `0` for something not fetched, matching this app's "no fake output"
discipline everywhere else.

`POST /api/publications/{id}/metrics/sync` (`app/api/publishing.py`) calls this
and records the result as a `PerformanceMetric` with `source="meta_sync"`,
distinguishing it from `source="manual"` entries with no schema change (the
column existed for exactly this since round 1). Guarded to `facebook_page`/
`instagram` publications with a real `external_post_id` and a configured Page
access token. The Publishing panel on Campaign Detail gained a "Sync from Meta"
button per eligible publication and a "synced" badge on metric rows where
`source === 'meta_sync'`.

## Frontend-only polish (round 11) — done

Two of the five round-11 items touched no backend code at all:

- **Brand style editor.** `pages/BrandDetail.tsx`'s color/visual-style/
  forbidden-style fields were plain comma-separated text inputs, silently
  round-tripping through a dict in a way that renumbered any key the user hadn't
  named explicitly (`color_1, color_2...`) on every save. Replaced with a
  structured key→swatch→hex color editor (add/remove a named color, pick it with
  a native `<input type="color">`, normalized to `#rrggbb` since that's the only
  format the native picker accepts) and a reusable `TagEditor` chip component
  (add via Enter or a button, remove via an inline ×) for visual-style and
  forbidden-style descriptors — both now preserve exactly the keys/tags a user
  set instead of losing their identity on every save.
- **Onboarding wizard.** `pages/Onboarding.tsx` (new) is a 4-step guided flow —
  create/select a brand → set source/output folders + an OpenAI key → scan the
  library → done — built as a thin sequencing layer over hooks/endpoints that
  already existed (`useCreateBrand`, `useUpdateSettings`, `useScanRepository`)
  rather than new backend functionality. `Overview.tsx` redirects here
  automatically when no brand exists yet (`brands.length === 0`), and it's
  reachable any time from a permanent "Setup guide" sidebar link — not just on
  first run, since adding a second brand or repointing the source folder later is
  exactly the same flow.

## Delete a campaign (round 13) — done

User-requested: "I would like to have an option to be able to delete campaigns
in case i created it wrong or just want to delete a campaign for personal
reasons." `DELETE /api/campaigns/{id}` — a real, permanent delete, refused
(`409`) only while a background job for that campaign is still `QUEUED`/
`RUNNING`. Everything scoped to the campaign cascades at the DB level (slides,
outputs, fingerprint, publications + their metrics, community-draft
attachments); the endpoint separately best-effort-deletes the real files those
rows pointed at under Output root (never under Source root — source photos are
shared across campaigns) and cleans up the campaign's own `Job` history. Full
reasoning, the exact cascade mechanics, and the test-infrastructure gap this
surfaced (`conftest.py` was missing the `PRAGMA foreign_keys=ON` listener the
real app relies on) are in `docs/architecture.md` section 5m. Frontend: a
danger-styled Delete button on both the Campaigns list (per-row, via a new
`CampaignRow` subcomponent) and Campaign Detail's header, each behind a
`window.confirm()`. 146 tests total.

## Stale "not wired up" UI copy, and two real Autopilot bugs (round 14)

Three fixes, all triggered by the user actually using the app past round 13:

1. **Stale copy.** Two leftover messages from before Autopilot existed (round
   1-era) were still telling the user campaign generation "isn't wired up
   yet" — the Strategy Library's post-create banner and the Overview page's
   empty state. Both rewritten to reflect what's actually true today; the
   Strategy Library banner now links straight to the new campaign's detail
   page instead of pointing at the docs.
2. **`NotImplementedError` from Playwright, Windows only.** The user's first
   real Autopilot run on their own Windows machine failed inside
   `render_slide` → `renderer.render_png_with_diagnostics`. Root cause:
   Playwright's async API needs the Proactor event loop on Windows to launch
   Chromium as a subprocess; uvicorn needs the Selector event loop on Windows
   for its own signal handling. Both can't be true of the same loop, and
   uvicorn wins, so Playwright's subprocess launch raised. Fixed by running
   Chromium and all page operations on a dedicated background thread with its
   own (Proactor-on-Windows) event loop, bridged via
   `run_coroutine_threadsafe`. Undetectable on this project's Linux/Mac
   dev/test environment by construction — full detail, including why, is in
   `docs/architecture.md` section 5n.
3. **A failed stage could leave a campaign stuck with no way to retry.**
   Independent bug, found because of #2: `run_visuals_stage`/
   `run_strategy_stage` set `campaign.status` to `GENERATING`/`RESEARCHING`
   right before doing the real work, and an *unanticipated* exception (like
   #2's) left it there forever — Job.status correctly said FAILED, but the
   big "Run Autopilot" button stayed disabled since its guard only re-enables
   on IDEA/FAILED. Fixed once, generically, in `services/jobs.py`'s
   `_execute_job` (the single place that already handles failure for every
   job type) rather than in each stage function. New `tests/test_jobs.py`
   (4 tests) exercises this directly. **150 tests total.**

The user's own already-stuck campaign didn't need deleting — "Visuals only"
in Advanced mode has no status gate, so it retries in place and now succeeds
with #2 fixed.

## Full AI recreation + Inspiration Library (round 15)

Two features, both requested directly by the user after their first real
Autopilot runs: "the app did not create a new image, it simply added a little
text on the product picture" and "where is the examples of ads, posts and
carroussels that i want to be used as inspiration."

1. **Full AI recreation.** Every AI image call before this round only ever
   touched the backdrop behind the product photo — the product pixels
   themselves were always the untouched original, pasted as-is
   (`compositor.composite_product`). That's a real capability gap, not a bug:
   the pipeline had simply never been given a way to let the model redraw the
   product photo itself. Fixed by reusing the existing
   `ImageProvider.generate(..., reference_images=[...])` → OpenAI image-edit
   routing (built in an earlier round for brand visual-reference photos) and
   pointing it at the real source photo instead: new
   `recreate_creative_image(...)` in `services/orchestrator.py` sends the
   source photo, plus up to two of the brand's Inspiration Library examples
   (see below), to the model with a prompt that keeps the product accurate
   while reimagining everything else to fit the campaign's angle/promise. The
   result becomes `SlideCreativeInput.recreated_image`, and `render_slide()`
   uses it to replace isolation/background-generation/compositing outright for
   that slide. Best-effort, same pattern as every other AI enhancement in this
   app: any failure is caught and the pipeline falls back to the ordinary
   gradient/AI-background path, never a hard error.
   - **On by default, one deliberate exception to this app's "opt-in" rule**:
     `POST /generate` (the main "Run Autopilot" button) now defaults
     `recreate_with_ai=true`, because Autopilot already unconditionally
     requires an OpenAI key, so this adds no new precondition for that one
     entry point. The manual `/slides/render` endpoint and the "Visuals only"
     advanced-mode stage both keep their default `false`, preserving their
     documented "works with no OpenAI key" property. A checkbox on Campaign
     Detail lets the user turn full recreation off anywhere it's offered, and
     the "Latest render" panel now says "fully recreated by AI" instead of
     naming a background isolator when it was used.
2. **Inspiration Library.** `BrandAsset.kind` gained a new value,
   `"inspiration"` (alongside `logo`/`font`/`visual_reference`), plus a new
   nullable `category_id` FK so an example can be scoped to one category or
   left brand-wide. A new card on Brand Detail ("Inspiration examples") lets
   the user upload example ads/posts/carousels with an optional category
   scope, shown as thumbnails with a "Brand-wide" or category-name badge.
   `_resolve_inspiration_paths(...)` prefers category-scoped examples for the
   campaign at hand, then tops up with brand-wide ones (max 2 total, kept
   small since each is an extra reference image on the OpenAI call), and only
   returns files that still actually exist on disk.

Also fixed in this round, discovered while building the above: `init_db()`
had only ever called `Base.metadata.create_all(...)`, never Alembic, across
every prior round — harmless until now because every earlier schema change
was a brand-new table, which `create_all` handles automatically, but this
round's migration (adding `category_id` to the existing `brand_assets` table)
is the first `create_all` can't retrofit. Fixed by having `init_db()` run the
real Alembic migrations on startup, auto-detecting and correctly stamping
three distinct database shapes (brand-new, existing-but-never-tracked,
already-tracked) so this app's users get schema upgrades automatically on
their next restart rather than needing a manual step none of them know to
run. Full detail — including a stamping-heuristic bug found and fixed via two
rounds of full-suite failures — is in `docs/architecture.md` sections 5o/5p.
**159 tests total.**

## AI-baked-in text + custom carousel length (round 16)

Both features requested directly by the user after reviewing a real
generated slide: a screenshot showing the AI's own dramatic baked-in
headline sitting underneath this app's own separately-rendered HTML
headline/body/CTA (two competing text layers, cluttered and off-brand), plus
"i was supposed to get 4 slides, but it printed only 1... i also want the
option to add how many slides i want in my carousel."

1. **AI bakes in all the text, for a full recreation.** `recreate_creative_image`
   (round 15's full-photo-recreation call) gained `headline`/`body`/`cta`/
   `eyebrow` parameters. When any is set, the prompt tells the model the exact
   text to design directly into the graphic as real typography — with an
   explicit instruction to give it "proper contrast and a real backing... so
   every word stays fully legible," which is the direct fix for the clutter in
   the user's screenshot — instead of the old "no text at all" instruction.
   The brand logo is still never left to the AI either way; it's always
   composited afterward as real HTML/CSS. Whichever caller renders the slide
   (Autopilot, Campaign Builder's Visuals stage, or the manual per-slide
   render endpoint) treats `recreated_image is not None` as the single signal
   for "the AI already drew this slide's text" and empties out the HTML
   template's own headline/body/CTA/eyebrow inputs in that case, so the two
   layers are always mutually exclusive — never both, never neither when text
   exists. The real text always stays saved on the `CampaignSlide` database
   row regardless of how it was rendered, so it's still there to inspect or
   edit later even when the current render baked it into pixels. Caught and
   fixed before shipping (not user-reported): the template's new
   omit-the-text-block-when-empty behavior would have made the automated QA's
   existing "text block must be present" check wrongly flag every legitimate
   baked-in-text slide as a failure — fixed with a new `text_expected` flag on
   `run_creative_qa`, same pattern as its existing `logo_expected` check.
2. **Custom carousel length.** `Campaign` gained a nullable
   `target_slide_count` column, editable any time via a new `PATCH
   /api/campaigns/{id}` endpoint and a "Carousel length" control on Campaign
   Detail (1-10, or cleared back to "let the model decide"). Left unset, the
   carousel planner's prompt and slide-count cap are unchanged from before
   ("plan up to `config.max_slides`, your judgment"). Set, the prompt instead
   says "plan exactly N slides, no more and no fewer," and the cap applied to
   the model's returned slide list becomes N instead of `config.max_slides`.
   This is a deliberate, user-chosen campaign property, not a one-shot
   generation parameter, per the user's explicit answer to "should this live
   on the campaign, editable any time, or be set once at kickoff" — they chose
   the former.

Full detail, including the exact prompt wording and the mutual-exclusivity
rule's implementation, is in `docs/architecture.md` section 5q. Neither
feature is retroactive — only slides rendered or re-rendered after this round
pick up either behavior. **172 tests total.**

## Feature Showcase template + recreate_with_ai default flip (round 17)

The user reported, with 16 real generated images attached, that Autopilot's
default full-AI-recreation path (`recreate_with_ai`, on by default for
`POST /generate` since round 15) had fabricated a completely different,
wrongly-branded product with garbled on-package text instead of their real
product. They then uploaded 16 of their own professionally-styled reference
ads across many real products and asked the app to match that exact design
pattern — a consistent template shape (eyebrow/kicker + big headline, a
top-right badge ribbon, a short intro paragraph, a left-side vertical list of
icon+bold-title+short-subtitle feature bullets, an ingredients/results
callout box, a bottom icon-feature strip, and a bottom CTA bar with trust
badges) applied consistently across their whole catalog, with the real
product always accurate and every word of text always legible.

Two changes, both flowing from the same root cause:

1. **`recreate_with_ai` now defaults to `false` everywhere** (it defaulted to
   `true` on `POST /generate` since round 15 — see that round's section
   above). Full AI recreation genuinely can't be trusted to keep the real
   product accurate or render dense text legibly with today's image models —
   this was confirmed directly against the user's own bad outputs, not
   assumed. It stays in the codebase as an explicit opt-in (`recreate_with_ai=
   true`) for anyone who wants to experiment with it, unchanged otherwise. The
   deterministic pipeline — the real, untouched product photo composited onto
   a designed background with real HTML/CSS text on top — was already this
   app's fallback path since round 3; it just wasn't the *default* on the main
   one-click flow until now. That pipeline never redraws the product or the
   text, so both are now guaranteed pixel-accurate by construction, not by a
   prompt instruction the model might not follow.
2. **A new, much richer template — `feature_showcase` — is now the default**
   (`AutopilotConfig.template_id`, `SlideRenderRequest.template_id`), modeled
   directly on the user's own reference ads: eyebrow, headline, an intro
   paragraph, up to 5 icon+title+subtitle feature bullets over a left-to-right
   scrim, a top-right badge ribbon, an ingredients/results callout box, a
   bottom icon-feature strip, and a bottom CTA bar with trust badges — every
   section independently optional so a partially-filled AI copy response (or
   the round-16 "text baked into a recreated image" case) still renders
   correctly. `SlidePlan` (the carousel-planner's structured output schema)
   gained matching optional fields (`badge_text`, `intro`, `features`
   — icon/title/subtitle triples via a new `SlideFeature` schema —
   `callout_label`/`callout_value`, `bottom_features`, `trust_badges`), and
   `run_copy_stage`'s planner prompt now asks for them explicitly, grounded in
   the real product/research on file (never an invented claim or number) —
   per the user's explicit answer to "should this copy be AI-drafted and
   editable, or should you type it yourself": **AI-drafted, editable**. The
   original `premium_product_hero` template stays registered and selectable.
   A real layout bug was caught (not just assumed fixed) by a renderer-based
   test asserting no text overflow with the maximum 5 features + a callout —
   it failed on the first pass, and the fix was scaling feature-list
   typography/spacing down as the list grows, rather than a fixed size that
   only looked right at 2-3 items.

Both decisions were confirmed via two rounds of `AskUserQuestion` rather than
assumed, mirroring round 16's approach — the first round established the
architecture (keep full AI recreation in the code as an off-by-default
opt-in, versus removing it outright), the second established where the new
template's feature-bullet/callout copy comes from (AI-drafted and editable,
versus the user typing it by hand every time).

Full detail, including the exact template CSS and the layout-overflow test,
is in `docs/architecture.md` section 5r. Like round 16's changes, this is not
retroactive — only slides rendered or re-rendered after this round pick up
the new template and the new default. **177 tests total** (up from 172: three
new `feature_showcase` template tests, a renderer-based overflow test, and an
orchestrator-level test confirming the new `SlidePlan` fields reach the
render and round-trip through the persisted `creative` stage JSON; one
existing round-15 test was rewritten in place rather than added alongside,
since it was a direct regression test for the default this round
deliberately flips).

## Product-fidelity gate + commercial art direction + visual master (round 18)

Immediately after round 17 shipped, the user sent 6 real carousel slides
produced by their own custom ChatGPT/GPT-based system (a 4-agent setup:
Competitive Intelligence, Campaign Director, Content Reviewer, Creative
Studio) for a real product, plus the real product photo, saying they want
this app's creatives to look like that — dramatic, professionally
art-directed commercial photography (crystal platforms, water splashes, glow
effects, dimensional depth), not a photo pasted on a template. They also
uploaded the 8 markdown knowledge-base documents that actually govern that
GPT system (company/brand profile, canonical product catalog with
eligibility flags, claims-safety/brand-boundary rules, campaign
strategy/content rules, a content-and-creative review rubric, a creative
production/output contract, a "Creative Design Profiles" doc defining
`HSC-PROD-001` and a "Golden Reference Workflow"/"Campaign Visual Master"
concept, and a full campaign-strategy taxonomy) — now saved verbatim in the
Claude Project under `claude/hanna-gpt-system/` for any future round to
reference.

This created a direct tension with round 17's own fix: matching that bar
requires full AI recreation of the whole scene (product included) — the
exact `recreate_with_ai` path round 17 had just turned off by default because
it fabricated a wrong product. The user's own uploaded rubric shows the way
out: their GPT system doesn't avoid AI generation, it *reviews* it — rubric
item "H. Product fidelity" explicitly fails a creative that "replaces the
real product with a fictional lookalike or redesign." Two `AskUserQuestion`
rounds confirmed the plan before any code was written: (1) rebuild around AI
generation again, paired with a real fidelity-review gate, rather than stay
purely deterministic; (2) scope this round to visual production quality
only — the broader claims-safety/evidence-gate/campaign-taxonomy governance
system from the other 7 docs is deliberately deferred to a separate round.

What shipped:

1. **`ProductFidelityCheck` + `AIProvider.check_product_fidelity`**
   (`schemas/ai.py`, `services/ai/base.py`/`openai_provider.py`) — a
   structured vision-model call that looks at the real source photo AND an
   AI-recreated image side by side and judges, per concrete aspect (package
   shape, proportions, brand/logo, label structure, visible text,
   cap/closure, color, distinctive marks — the same list the user's rubric
   names), whether the product survived. `overall_verdict` defaults to
   `"FAIL"` at the schema level, so a degenerate/empty parse can never read
   as an accidental pass.
2. **`recreate_creative_image_with_fidelity_gate`** (`services/
   orchestrator.py`) — the new required entry point for full AI recreation:
   generate once, check it, and if it isn't a verified `PASS`, retry exactly
   once with a corrective prompt naming the specific mismatched aspects
   (`_mismatched_aspects_note`), then give up (`image=None`) if it still
   isn't verified. A check that errors (bad key, rate limit, malformed
   response) is treated exactly like a `FAIL` — fail-closed, per the user's
   own uploaded rule ("a blocker is better than invented content"). Every
   caller that wants recreation now needs BOTH `image_provider` and
   `ai_provider` — with only `image_provider`, recreation is skipped
   entirely rather than risk shipping an unverified image.
3. **Upgraded recreation prompt** (`recreate_creative_image`) — now asks
   explicitly for the `HSC-PROD-001` production level from the user's
   uploaded design-profile doc: real foreground/midground/background depth,
   polished lighting with shadows/reflections/glow/material detail, the
   product's own authentic packaging colors driving the palette rather than a
   forced brand-color scheme — while keeping (and sharpening) the "the
   product must stay accurate, never a redesigned lookalike" instruction.
4. **"Campaign Visual Master" cross-slide consistency** — once a slide's
   recreation is generated AND verified, its rendered PNG (already on disk —
   no extra file needed) is passed as one more reference image to later
   slides' recreation calls in the same carousel (`visual_master_path`), with
   an explicit instruction to match its lighting/palette/material/typography/
   finish without duplicating its exact composition — the same idea the
   user's uploaded doc describes.
5. **"N/total" slide-number marker** (`TemplateContext.slide_number`/
   `total_slides`, `templates.py::_slide_marker_html`) — real HTML/CSS on
   every template regardless of which generation path produced the slide,
   matching the "1/6, 2/6, 3/6" system the design-profile doc calls for. A
   real overlap bug was caught (not just assumed fixed) by rendering a
   preview during development — the marker's default top-left position
   collided with `feature_showcase`'s eyebrow text — fixed by pushing that
   template's text-block down whenever a marker will actually render.
6. **`recreate_with_ai` defaults to `true` again on `POST /generate`** (the
   main "Run Autopilot" flow) — reversing round 17's default specifically
   there, now that it's safe: the fabrication risk that justified turning it
   off is caught mechanically by the fidelity gate instead of trusted away.
   Visuals-only and the manual single-slide render endpoint stay
   off-by-default (opt-in), preserving their "no OpenAI key needed" property
   — the same asymmetric-default pattern established in round 15.

Every recreation attempt's outcome (attempted / verified / attempts /
notes) is recorded alongside the existing QA report — the mechanical
equivalent of the user's uploaded creative-handoff contract's
`PRODUCT_FIDELITY_CHECK` field — so a human reviewer can see exactly what
happened on a slide even when the gate fell back to the deterministic
pipeline.

**186 tests total** (up from 177: a fidelity-gate test suite covering
first-pass verified, retry-then-succeed, persistent-failure fallback, and
check-errors-treated-as-fail-closed; a fail-closed test for recreation
attempted with no `ai_provider` on hand; a cross-slide visual-master
reference test; two slide-marker rendering tests plus the text-block-offset
regression test; and one existing round-17 regression test rewritten in
place for the new default, same as round 17 did to round 15's).

Explicitly deferred to a later round, by the user's own choice: the
claims-safety/brand-boundary rules, the campaign-strategy taxonomy (7
strategic families with evidence gates), and the canonical product catalog's
eligibility flags from the other 7 uploaded docs — none of that is wired
into this app yet. `claude/hanna-gpt-system/` in the Claude Project has the
full source material whenever that round happens.

### Bug fix: carousel was silently capped to the number of source photos on file

The user tested round 18 by resending the same 7 reference images with:
*"right now it only added text to the picture i already gave. what i want my
marketing os to do is transform my uploaded picture 1 ... into the following
carrousel (next 6 pictures)"* — i.e. exactly the workflow round 18 was built
for (one real photo → a 6-slide, AI-recreated, fidelity-verified carousel)
wasn't happening.

Root cause, found by re-tracing `run_visuals_stage`: it computed
`usable_count = max(1, min(len(planned_slides), len(candidate_assets)))` and
sliced the carousel plan down to that count. Copy stage can plan a 6-slide
carousel just fine, but a brand/category with only **one** uploaded photo on
file has `len(candidate_assets) == 1` — so the carousel was silently
truncated to 1 rendered slide, no matter how many slides were planned and no
matter whether `recreate_with_ai` was on. This reproduces the user's report
exactly ("it only added text to the picture I already gave" — one output,
singular) and is independent of the round 15→17→18 `recreate_with_ai`
default history: even a user on the brand-new round-18 build with recreation
correctly defaulting to on would hit this the moment they had fewer source
photos than planned slides — the single-photo case being the most common one
for someone just starting out with this app.

Fix: the carousel is no longer sliced to the photo count. Every planned
slide renders; `candidate_assets` is cycled round-robin
(`candidate_assets[(i - 1) % len(candidate_assets)]`) whenever there are
fewer photos than slides, rather than the carousel being truncated down to
the photo count. With `recreate_with_ai` on this is precisely the intended
workflow — one real photo recreated into N different art-directed
compositions, each a distinct slide, exactly like the 6 reference slides the
user sent. With it off, slides still differ by their own headline/body/cta
even while reusing the same source photo, same as any ordinary multi-slide
carousel built from a single hero shot. `Asset.times_used`/`last_used_at`
bookkeeping increments once per slide as before, so a single photo used
across 6 slides in one run correctly shows `times_used += 6`.

New regression test:
`test_visuals_stage_renders_all_planned_slides_even_with_one_source_photo`
(one uploaded photo, a 6-slide plan, `target_slide_count=6`) asserts all 6
slides render with the right headlines, all 6 reference the same source
asset, and `times_used` lands on 6. **187 tests total** (up from 186).

Also worth doing on the user's end for the visual quality itself: upload the
6 reference carousel slides they've now shared twice into the Brand's
Inspiration Library (`BrandAsset kind="inspiration"`) if not already there —
`_resolve_inspiration_paths` is what feeds concrete style references into
the AI recreation prompt, and without it the fidelity gate has nothing to
compare "does this look like the target style" against, only "does this
still look like the real product."

## Discovery carousels + product auto-detection + 20-slide cap (round 19)

The user's own words, unprompted by any specific bug report this time — a
description of how they actually want to use the app going forward: *"there
are many types of campaigns. There are discoveries campaigns that should use
many different products and each product should be one slide, while other
campaigns it should [be] one product and transform into a 20 slide
carrousel[]."* Two genuinely different carousel shapes the app had only ever
supported one of (the second — round 18's whole fidelity-gated pipeline is
exactly "one product, many slides").

Before building anything, `AskUserQuestion` settled four design points: (1)
which of the two shapes a campaign uses follows entirely from what's already
picked (a specific Product → deep-dive; category-only → discovery) rather
than a new explicit toggle; (2) discovery products are hand-picked by the
user, not auto-selected; (3) the slide-count ceiling goes from 10 to 20; (4)
discovery slides get full AI recreation by default too, same as deep-dive
(already true — Autopilot's `recreate_with_ai` default applies uniformly).

**A real pre-existing gap surfaced during research, before any of the above
could actually work.** `Product` and `Asset.product_id` have existed in the
schema since round 1 and are used by `_select_candidate_assets`'
product-scoped filtering — but nothing anywhere, backend or frontend, had
ever populated `Asset.product_id`, and no frontend screen could create a
`Product` or set a campaign's `product_id` at all. Grepping the whole
frontend for `product_id` turned up exactly one match: the type definition.
Before building discovery mode, products had to become a real, populated
concept.

**Fix: the scanner auto-detects the product, the same way it already
auto-detects the category.** `_guess_product_slug` (`services/scanner.py`)
treats the *second* path component as the product
(`Source/skincare/product-a/photo.jpg` → category `skincare`, product
`product-a`) — exactly the two-level convention the brief's own scanner
docstring already described but never implemented past the first level.
`Product` rows are auto-created and cached the same way `Category` rows
already are; a flat `Source/skincare/photo.jpg` file (no second folder
level) is simply left product-less, not an error. Critically, the
fast "unchanged file" re-scan path — which previously skipped
category/product resolution entirely for a file whose mtime/size hadn't
changed — now backfills `category_id`/`product_id` whenever either is still
`NULL`, so a user's *existing*, already-scanned library gets tagged
correctly just by re-running the scan they already know how to run, with no
manual per-photo tagging UI needed at all. This is the same "retroactive
gap-fill, never overwrite what's already set" pattern round 15's Alembic
auto-migration used for schema, just applied to one row's data instead.

**The two carousel structures.** Both are computed the same way in three
places (`get_campaign`, `run_copy_stage`, `run_visuals_stage`) — a specific
`Campaign.product_id` means **deep-dive** (round 18's pipeline, unchanged: one
product, every slide a different AI-recreated composition of it, round-robin
across whatever photos exist); no `product_id` AND at least one hand-picked
`CampaignDiscoveryProduct` means **discovery** (below); no `product_id` and
nothing picked yet keeps the original single-photo-pool behavior byte-for-byte
— an existing category-only campaign is never silently reinterpreted.

1. **`CampaignDiscoveryProduct`** (new table, `campaign_id` + `product_id` +
   `sort_order`, unique per campaign+product) — the ordered, hand-picked
   product list. `PUT /api/campaigns/{id}/discovery-products` replaces it
   wholesale (list order = carousel order); rejects 400 on a
   product-scoped campaign (the two structures can never be ambiguous for
   one campaign), 400 on a duplicate id or more than 20, 404 on an unknown
   product.
2. **`run_copy_stage`'s discovery branch** — instead of the usual "up to N
   slides for one product" carousel-planning prompt, the model is given the
   picked products' names/notes in order and instructed to plan *exactly*
   one slide per product, same order, never combining or inventing products.
   Slide count in discovery mode is simply how many products were picked —
   `target_slide_count` doesn't apply here at all.
3. **`run_visuals_stage`'s discovery branch** — one asset per picked product,
   in pick order, via `_select_candidate_assets(product_id=...)` — this is
   deliberately NOT round-robin like deep-dive's asset selection; each slide
   must show a *different* product, never cycle back through one already
   used. A picked product with no active photo simply loses its slide
   (best-effort, same "a moved/deleted source file shouldn't fail the whole
   run" philosophy as everywhere else in this loop) rather than failing the
   whole campaign; if literally none of the picked products have a photo,
   the run fails with a clear message rather than silently rendering zero
   slides.
4. **Slide-count ceiling raised 10 → 20** (`PATCH /api/campaigns/{id}`
   validation, and the frontend's carousel-length input) — the deep-dive
   half of the user's own request, independent of discovery mode.

Frontend: campaign creation (Strategy Library) gained an optional Product
selector next to the existing Category one — leave it unset for a
category-wide campaign, set it for a deep-dive one. Campaign Detail gained a
"Discovery products" panel (add/remove/reorder, hidden on a
product-scoped campaign) and shows the effective carousel length either way
— the manual slide-count control when deep-dive, "N slides — one per product
picked below" when discovery.

New tests: 3 scanner tests (products auto-created from the second folder
level with correct category scoping; a flat file gets no product; an
existing unchanged asset gets backfilled on re-scan without re-hashing), 4
orchestrator tests (discovery carousel-plan prompt lists products in pick
order and uses discovery-specific language; slides render one per product in
pick order, not round-robin; a picked product with no active photo loses
only its own slide; the run fails clearly when no picked product has a
photo), and 8 API tests (`structure_mode` on GET for both shapes; the
discovery-products endpoint's replace/reorder/clear round-trip and all four
rejection cases; the raised slide-count ceiling). **201 tests total** (up
from 187).

## Defense → Campaign, today vs. later

Today: a user logs a `CompetitorEvent` in the Defense page, `recommend_response()`
matches it against `defense_playbooks` and returns ranked Strategy Library types with
a rationale, and clicking "Create campaign" on a recommendation creates a real
`Campaign` row (status `IDEA`, `strategy_type_id` + `triggered_by_event_id` set) —
see `app/api/defense.py` and `app/api/campaigns.py`. Nothing here is simulated: the
recommendation logic is a real, tested rule engine (`tests/test_defense.py`), and the
campaign it creates is a genuine database record, just not yet auto-generated content.

Later: once the orchestrator (below) exists, a `triggered_by_event_id` on a campaign
should make the orchestrator skip strategy-type selection (step 5) and weight research
step 6 toward the specific competitor context in `CompetitorEvent.details`. An
AI-assisted version of `recommend_response()` (weighing softer signals than the
if/else rules can capture — e.g. brand tone, current inventory) can replace the rule
engine later behind the same function signature; the `DefensePlaybook` rows would
become a fallback/explainability layer rather than the only mechanism.

## Opportunity discovery (section 46) — done

`services/opportunities.py`'s `run_opportunity_discovery(...)` calls a new
`ResearchProvider.discover_opportunities(query, model=...)` method (added to the
Protocol alongside `research()`, reusing `ResearchQuery` rather than a parallel
schema) — implemented in `OpenAIProvider` as a web-search-grounded call, same
pattern as `research()`. The "no fake research" rule applies identically: an
`OpportunityRecommendation` without a `source_urls` entry is dropped before it's
ever persisted — an invented Facebook Group is exactly the failure mode this
prevents. This answers the brief's "find me places to post like Facebook groups"
ask directly, within the real constraint that no third-party app (this one
included) can auto-post into a Group it doesn't administer — Meta's Graph API
disallows it structurally, so the feature stops at "find it, verify it, draft a
post for it" and leaves the actual posting to the human.

Unlike research (TTL-cached, append-only), discovery *upserts* — a repeat run
matches existing `Opportunity` rows by `(brand_id, platform, name)` and refreshes
them (relevance, posting rules, `last_checked_at`) rather than duplicating, since
re-discovering the same real group over and over would be noise, not new
information.

`POST /api/opportunities/discover` exposes this (400s without an OpenAI key, same
pattern as `/research/run`); `GET /api/opportunities` lists discovered communities
(excluding blocked ones); `PATCH /api/opportunities/{id}` tracks the manual
workflow — `joined_status` (not_joined/requested/joined/rejected), `favorite`,
`blocked`, `notes` — pure bookkeeping, no Meta API call involved. `POST /api/
campaigns/{id}/opportunities` attaches a discovered opportunity to a campaign (via
the pre-existing `CampaignOpportunity` join table) and generates a default draft
post from the campaign's hook/main_promise/CTA, noting when a community's
`promo_allowed` is `false` so the draft leads with value instead of a hard sell;
`PATCH .../{co_id}` edits that draft and marks it posted (bumping the
`Opportunity`'s `last_posted_at`). The Opportunities page and Campaign Detail's
"Community drafts" panel are the real UI for this, not stubs.

Tested end to end in `tests/test_opportunities.py` — uncited-recommendation drop,
upsert-not-duplicate on repeat discovery, the discover/list/update API endpoints,
and the campaign-attach → edit → mark-posted flow — against a
`FakeOpportunityProvider`, same fake-provider pattern as research and Autopilot.

## Calendar + analytics + performance feedback loop (sections 36-38) — done

This is the loop diagram's last arrow: `DISTRIBUTION TRACKING → PERFORMANCE →
(feeds back into) STRATEGY`. Three pieces, all real against the existing
`publications`/`performance_metrics`/`performance_insights` schema (nothing new
added to `data-model.md` — this phase only writes application code against tables
that were already there):

1. **Publications** — a manual record of "this campaign actually went out
   somewhere". `POST /api/campaigns/{id}/publications` (guarded: the campaign must
   be `APPROVED`/`EXPORTED`/`SCHEDULED`/`PUBLISHED` — you can't log a publication
   against a half-built `IDEA`) creates a `Publication` row; `GET
   /api/campaigns/{id}/publications` lists them. `api/publishing.py` owns the
   resource from there: `GET /api/publications` (brand-scoped, filterable by
   status/provider), `PATCH /api/publications/{id}` (update status/url/
   external_post_id — setting `status=published` also bumps the campaign to
   `PUBLISHED` and stamps `published_at` if not already set, so campaign status
   always reflects the most-advanced known reality).
2. **Performance metrics** — `POST /api/publications/{id}/metrics` adds a
   `PerformanceMetric` snapshot (impressions/reach/likes/comments/shares/saves/
   clicks/leads/bookings/sales/revenue), always `source="manual"` today since no
   ad-platform API integration exists yet. `GET /api/publications/{id}/metrics`
   lists them. Nothing here is estimated or predicted — every number is either
   typed in by a human who looked at the real platform insights, or (in a future
   connector) written by an actual API sync; the schema's `source` column is
   exactly the seam a future automated sync would use without changing anything
   else.
3. **The feedback loop math** — `services/analytics.py`. `engagement_rate(metric)`
   is `(likes+comments+shares+saves) / (reach or impressions)`, returning `None`
   (not `0`) when neither denominator was recorded — a plain, inspectable ratio,
   deliberately not a fabricated "virality score". `performance_summary(db,
   brand_id, days=90)` (exposed as `GET /api/analytics/performance`) aggregates
   totals, a per-strategy-type breakdown, and top campaigns by revenue — the data
   behind the Analytics page. `average_engagement_rate_for_strategy_type(db,
   brand_id, strategy_type_id)` is what actually closes the loop: `services/
   orchestrator.py`'s `_select_underused_strategy_type` uses it as a tie-breaker
   among equally-underused Strategy Library types (usage count is still the
   primary key — see architecture.md section 5a — so this never lets a
   well-performing type dominate every campaign; it only nudges among ties). A
   type with no recorded metrics yet contributes `0.0` and simply doesn't get a
   nudge either way, rather than being penalized relative to a measured one.
4. **Calendar** — `GET /api/analytics/calendar` (brand_id, year, month) lists
   campaigns with a `published_at` in that month, grouped by day. Deliberately a
   list-grouped-by-date rather than a calendar-grid widget — "what went out when"
   is the useful question, not a visual month grid — matching the Calendar page.

`Campaign Detail` gained an "Approve" button (calling the pre-existing `POST
/{id}/approve` endpoint, which had never been wired up in the UI before this
round) and a "Publishing" panel for `APPROVED`+ campaigns to log publications and
add metric snapshots inline. `tests/test_publishing.py` covers the status guard,
publication CRUD, the published-status campaign-bump side effect, metric add/
list, `performance_summary` aggregation, the calendar endpoint, and a direct unit
test proving `_select_underused_strategy_type` actually picks the
higher-engagement type when usage counts tie.

## Facebook Page / Instagram auto-publish (sections 47/48) — done

`PublishingProvider` (`app/services/ai/base.py`) — `provider: str`, `publish(*,
target: PublishTarget, assets: list[Path], copy: PublishCopy) -> PublishResult` —
had existed since round 1 as a documented extension point with the explicit note
"Not implemented in this MVP." This is the same shape of gap as `BrandAsset`'s
missing endpoints turned out to be (see "Brand visual style & AI-generated
backgrounds" above): a real seam sitting unused because nothing had built against
it yet. `app/services/publishing/meta_provider.py::MetaPublishingProvider` is now
the first concrete implementation, covering Facebook Page + Instagram via Meta's
Graph API — the only module in this codebase allowed to talk to that API directly,
matching the isolation `openai_provider.py` keeps for the `openai` SDK.

Two real constraints, verified against Meta's own developer docs, shape the
implementation and are genuinely different from each other:

- **Facebook Page photo post** (`POST /{page-id}/photos`) takes the image as a
  direct multipart file upload — a locally rendered creative goes straight from
  `OUTPUT_ROOT` to Meta's servers, no public hosting required.
- **Instagram's Content Publishing API** is a two-step flow (`POST /{ig-user-id}/
  media` to create a container, then `POST /{ig-user-id}/media_publish`) and only
  accepts an `image_url` that *Meta's own servers fetch themselves* — there's no
  file-upload option for a still image. A creative sitting on the user's own
  machine therefore needs a public URL before Instagram can see it at all.

`PublishTarget` gained an optional `public_asset_url` field for this. The new
`POST /api/campaigns/{id}/publish` endpoint (`app/api/campaigns.py`) builds that
URL — from a new `public_base_url` setting plus the existing `GET /{id}/slides/
{n}/image` endpoint's path — only for `provider="instagram"`; for
`"facebook_page"` it stays `None` and the file is uploaded directly. Without a
`public_base_url` configured, the Instagram branch fails with a specific,
actionable message *before making any network call*, rather than sending a
request Meta will reject in a more confusing way.

New runtime settings (`facebook_page_id`, `facebook_page_access_token` — never
echoed back, same as `openai_api_key` — `instagram_business_account_id`,
`public_base_url`) follow the existing `.env`-default + DB-override pattern. The
actual token/ID acquisition is a one-time manual flow against Meta's own developer
tools, documented step by step in the README — and because this app only ever
posts to the account owner's own Page/Instagram account, Meta's Standard Access in
Development Mode is sufficient; the heavier App Review process (required only to
post on behalf of *other* people's Pages) doesn't apply here.

On success, the endpoint creates a `Publication` row and bumps the campaign to
`PUBLISHED` — the identical side effect logging a publication by hand already had,
so Analytics/Calendar/the Publishing panel treat a real auto-publish and a manual
log entry identically. On failure, nothing is recorded (a failed post attempt
didn't happen) and the real Graph API error is surfaced via a 502 rather than
swallowed — consistent with this app's "no fake output" discipline everywhere else
(uncited research, uncited opportunities, hand-entered-only performance metrics).

This does not touch the Facebook Groups situation — no app can auto-post into a
Group it doesn't administer, by Meta's own platform design; that stays copy/paste
from the Opportunities page's drafted post, same as before this round.

Tested in a new `tests/test_meta_publisher.py` (`MetaPublishingProvider` against
an `httpx.MockTransport` fake — no real network call or token: the Facebook
branch's real file bytes and caption reaching the request, Instagram's two-step
container→publish call order, the pre-flight failure with no public URL
configured, and a Graph API error response turning into a clean `PublishResult`
failure) and new cases in `tests/test_api.py` (the endpoint's approval/credential/
rendered-slide guards, a successful publish via a monkeypatched fake creating a
`Publication` and bumping status, a failed publish recording nothing, and the
real, unmonkeypatched provider's Instagram-without-a-public-URL failure exercised
end to end).

## Campaign Builder advanced mode (Phase 10) — done

The last item from the original build order: splitting Autopilot's all-or-nothing
`/generate` into three independently runnable stages so a user can generate just a
strategy, just copy, or just visuals rather than always committing to the whole
pipeline in one shot.

`services/orchestrator.py`'s single 300-line `run_autopilot` was decomposed into
three functions — `run_strategy_stage` (steps 1-9, ends at `BRIEF_READY`),
`run_copy_stage` (steps 10-12, ends at `COPY_READY`), and `run_visuals_stage`
(steps 13-15, ends at `REVIEW`) — with `run_autopilot` now simply calling all three
back to back (a behavior-preserving refactor: every existing orchestrator/API test
passed unchanged before any new test was added, confirming "Everything" mode's
result is identical to before the split). Each stage persists its structured
output as a JSON file under `OUTPUT_ROOT/<brand>/<category>/<year>/<year-month>/
<campaign>/brief/{strategy,copy,creative}.json` (the same deterministic-folder
pattern already used for rendered slides and QA reports), tracked by a
`CampaignOutput` row per kind (`_save_stage_json`/`_load_stage_json`). That's the
actual mechanism that lets a later stage run standalone, in a completely separate
HTTP request — even a different day — picking up exactly where the prior one left
off instead of needing everything handed to it in memory:

- `run_strategy_stage` guards on campaign status (`IDEA`/`FAILED`, same as before)
  since re-picking a strategy after copy/visuals already committed to a different
  angle would orphan those artifacts.
- `run_copy_stage` and `run_visuals_stage` guard on the **prior stage's output
  existing** rather than a specific campaign status — so Copy can be regenerated
  later even after Visuals has already run (e.g. to try different copy without
  re-rendering), and Visuals can be re-run later without resetting anything else
  (e.g. after adding new photos to the category). Each 400s with a specific,
  actionable message ("Run the Strategy stage for this campaign before generating
  copy...") rather than guessing or silently doing nothing.
- `run_visuals_stage` needs **no OpenAI key at all** — it only reads back
  already-generated copy/carousel-plan JSON and composites real photos, exactly
  like the manual `/slides/render` endpoint. This is a genuine, useful property of
  the split: you can iterate on strategy/copy with an API key configured, then
  hand the campaign off to render without one.
- A new `COPY_READY` campaign status sits between `BRIEF_READY` and `GENERATING`
  (added to `CAMPAIGN_STATUSES` in `models/campaign.py` — a plain Python tuple,
  not a DB-level CHECK constraint, so this needed no migration).

Exposed as `POST /api/campaigns/{id}/generate/strategy`, `.../generate/copy`, and
`.../generate/visuals` (`app/api/campaigns.py`), each following the exact same
Job-creation/`OpenAIProvider`/error-handling pattern as the existing `/generate`
endpoint. `tests/test_orchestrator.py` adds direct tests of each stage running
standalone, the copy/visuals precondition guards, all three stages run as separate
calls reaching the same end state as `run_autopilot`, and that re-running Copy
after Visuals has already completed doesn't revert campaign status backward.
`tests/test_api.py` adds an HTTP-level test of the three endpoints called in
sequence, including proving Visuals succeeds with the OpenAI key removed entirely.

Frontend: Campaign Detail gained an "Advanced mode" card below the existing "Run
Autopilot" button, with three buttons (Strategy only / Copy only / Visuals only),
each showing its own pending/error/success state and surfacing the backend's exact
guard message on failure rather than trying to predict it client-side.

## AI-image resize was stretching, not covering, plus explicit image quality (round 20)

Found while comparing this app's output against several of the user's own custom
GPTs built for the same job (a "Hanna Creative Studio" image-generation GPT, a
general "Hanna Marketing Agent" content GPT, and two Facebook/Instagram-carousel
GPTs) — the user asked directly why a much simpler GPT prompt was producing
visibly higher-quality images than this app's longer, more constrained one.

The dominant cause turned out to have nothing to do with prompt wording: a real
bug in `services/creative/pipeline.py::render_slide`. The image-generation API
(`gpt-image-1`) only ever returns one of three fixed aspect ratios — square
(1024x1024), portrait 2:3 (1024x1536), or landscape 3:2 (1536x1024) — and none of
those match real platform slide shapes (Instagram's 4:5 portrait carousel is
1080x1350; a story is 9:16). `_nearest_ai_image_size` correctly picks the closest
of the three to generate at, but the pipeline then fit that image into the exact
platform canvas with a plain `Image.resize(...)` — a non-uniform stretch, not a
crop-to-fit. Every AI-recreated slide and every AI-generated background in a 4:5
or story-format carousel was therefore being squeezed to force the aspect ratio
to match, warping product shapes, labels, and reflections on every slide,
independent of how good the prompt was.

Fixed with a new `_resize_cover(image, width, height)` helper: scales the image
uniformly to *cover* the target box (never stretching), then center-crops the
overflow — the standard "cover" fit, same as CSS `object-fit: cover`. Replaces
both `resize` calls in `render_slide` (the `recreated_image` path and the
`generated_background` path). A same-size input is returned unchanged (no-op).
`tests/test_creative.py::test_resize_cover_fills_the_target_box_without_stretching`
proves the fix directly: draws a circle on a 2:3 source, fits it into a 4:5
target, and asserts the circle's bounding box stays square (width ≈ height)
rather than becoming an ellipse — a stretch bug would fail this by ~20%.

Also fixed as a secondary, cheaper-to-miss factor: `OpenAIProvider.generate`/
`edit` never set a `quality` parameter on the Images API calls at all, leaving it
at the API's own `"auto"` default — which can pick a cheaper/lower-fidelity
render than what ChatGPT's own product UI typically requests. Both endpoints now
explicitly pass `quality="high"`, since every image this app generates is a
finished marketing creative, never a throwaway draft.

Explicitly not resolved this round (deferred until the user finishes sharing the
rest of their custom GPT prompts): whether/how to fold each GPT's system-prompt
content into the app (a real "custom creative instructions" field is needed —
`Brand.campaign_rules` exists in the schema but is dead code, never read
anywhere); the conflict between the strict claim-safety rules in two of the
GPTs (never invent scarcity badges, review stars, bestseller badges, before/after
results, or competitor comparisons without real evidence) and the "aggressive"
15/10/6-slide conversion templates in the other two, which treat exactly those
elements as default, always-include content; the missing `product_scope`
(single/multi-product) signal on each of the 64 Strategy Library types; and
whether the canonical product catalog (`02-canonical-product-catalog.md`) should
replace the round-19 folder-name product auto-detection with real HANNA-PROD ID
verification. 203 tests total (up from 201).

## Brand creative instructions, claims-safety baseline, product_scope, and per-campaign platform picker (round 20 continued)

Picks up the items the previous round-20 section explicitly deferred, once the
user said to finish them rather than wait for the rest of their custom GPT
prompts, plus a new, separately-requested feature: choosing which social
platform/format a campaign renders at.

**`Brand.creative_instructions`** — a new free-text field (`Text`, default
`""`) that finally does what the dead `Brand.campaign_rules` JSON field never
did: holds the brand's own standing creative-direction text, in their own
words (the kind of thing that used to only live inside a custom GPT's system
prompt), and actually gets read. `_brand_creative_instructions_block(brand)`
in `services/orchestrator.py` returns `""` when unset, or a labeled block
when set; it's threaded into every AI call that shapes a campaign — strategy
candidate generation, the creative brief, campaign copy, both carousel-plan
calls (deep-dive and discovery), and the image-style notes used for
recreation — so a brand's own house rules apply everywhere, not just to
images. `campaign_rules` itself is untouched and still unused; this is a
separate, actually-wired field. Editable from Brand Detail's "Brand voice &
style" card, saved together with voice/colors/style tags.

**Baseline claims-safety instruction** — added unconditionally (not
gated by any brand setting) to `recreate_creative_image`'s image prompt and
to both carousel-plan copy prompts: never invent a scarcity/low-stock claim,
a countdown timer, a specific discount/price graphic, a review-star rating or
testimonial, a bestseller/rank badge, a clinical/safety seal, a before/after
result, or a competitor-comparison graphic, unless the brand's own data
actually supports it. This was modeled directly on the real conflict found
between two of the user's own GPTs (Creative Studio / Marketing Agent's
anti-fabrication rules) and the other two ("aggressive" carousel templates
that treat exactly those elements as mandatory, always-include content) —
resolved here in favor of the safer default everywhere in the app, since
fabricated claims are a real legal/trust risk regardless of which GPT a given
campaign's brief happened to be inspired by. The "aggressive" badge-driven
layouts themselves are not implemented — that's real new UI (an "attach
evidence" flow so a badge can be backed by something true) and stays future
work.

**`product_scope`** — a new `"single" | "multi" | "either"` field on every
Strategy Library type (`CampaignStrategyType.product_scope`, default
`"either"`), classified for all 64 existing types from their own
`example`/`objective`/`offer_types` (e.g. `fomo_campaign` → `"single"`,
`discovery_campaign` → `"multi"`, most Defense types → `"either"`). This is
informational only — shown on the Strategy Library card next to
Trigger/Duration/Audience/Budget notes — and deliberately does **not** gate or
auto-set a campaign's actual `structure_mode` (still purely a function of
whether a specific product / any discovery products are picked, per round
19). Surfacing it lets the user see which structure a strategy type
naturally fits before choosing, without forcing it.

**Per-campaign platform/format picker** — the new, explicitly requested
half of this round. `Campaign.platform_key` (nullable `String(50)`,
default `NULL`) records which `PLATFORM_FORMATS` key a specific campaign
renders at; `NULL` (every campaign before this feature, and any new one left
unset) falls back to `AutopilotConfig.platform_key`'s own account-wide
default (`instagram_square`), so nothing about existing behavior changed.
Settable at campaign creation (a new dropdown next to Category/Product on the
Strategy Library page) and editable any time afterward from Campaign Detail's
Autopilot card (a persistent selector, separate from the manual "Render a
creative" panel's own per-render format picker, which is unchanged). Inside
`run_visuals_stage`, one local — `effective_platform_key = campaign.platform_key
or config.platform_key` — replaces all six of the function's former direct
reads of `config.platform_key`, so a single run's output path, AI-recreation
canvas size, deterministic template render, and persisted QA/output records
all agree on the same platform for the whole campaign. Also added
`instagram_portrait` (1080x1350, the real Instagram 4:5 carousel shape) to
`PLATFORM_FORMATS` — prior rounds' docs referenced it as if it already
existed, but it had never actually been registered.

Migrations: `d4f6a1c8b9e2` (`campaigns.platform_key` +
`brands.creative_instructions`) → `e7b3c5a9d1f4`
(`campaign_strategy_types.product_scope`), both verified up/down/up.
215 tests total (up from 203).

Explicitly still not built, unchanged from the prior round-20 section: the
DESIGN_PROFILE_ID multi-profile system from Hanna Creative Studio's prompt;
real evidence-gated badge/testimonial rendering (needs a UI to attach the
evidence a badge would be backed by, not just a safer default prompt);
canonical product catalog ID verification against
`02-canonical-product-catalog.md`; and structured, content-type-specific
outputs for reels/email/blog posts (today everything shares the one
`CampaignCopy` shape).

## Build 1 — Verified Product Facts + Campaign Foundation (Multi-Platform + Bilingual Quality Recovery Program)

A formal, numbered specification (superseding all previous Marketing OS build
prompts) aimed at a recurring quality failure mode in generated campaigns:
copy that invents product facts, defaults silently to one language and one
platform, ships full AI image recreation when it shouldn't, and can't be
traced back to which prompt version produced it. Build 1 is the first of a
planned multi-build program and is scoped to nine parts (A-I), touching every
pipeline stage from research through render.

**Part A — Verified Product Fact Resolver.** A new `verified_product_facts`
table (one row per product) holds only facts that are actually backed by
something — the product's own catalog fields, brand-supplied asset
references, or the owner's own notes — never invented. `resolve_verified_product_facts()`
(`services/product_facts.py`) builds a `VerifiedProductFacts` object per
product: verified description, ingredients, features, benefits, usage, size,
variant, price, availability, country of origin, and claims, each either
populated from a real source or left explicitly absent (never guessed), plus
a `missing_information` list naming what's unverified and a `provenance`
string recording where each populated field came from. `format_verified_facts_for_prompt()`
turns this into a grounding block embedded in the Campaign Copy prompt (Part
E) — copy stops treating an empty spec sheet as license to invent one.
Exposed via `GET/PUT /api/products/{id}/verified-facts` and the
`useVerifiedProductFacts`/`useUpdateVerifiedProductFacts` hooks; no dedicated
editor page yet (see "Explicitly still not built" below).

**Parts B/C — Explicit language and platform targets.** `Campaign.languages`
(JSON list, e.g. `["pt-BR"]` or `["pt-BR", "en"]`) and
`Campaign.target_platforms` (JSON list from `instagram | facebook | tiktok |
youtube_shorts | pinterest | linkedin | x`) replace the implicit
"whatever `Campaign.language` happens to hold, always Instagram" assumption
baked into earlier rounds. `Campaign.language` (singular) is kept for
backward compatibility but is no longer authoritative — `languages` is.
`data/platform_capabilities.py` defines `SUPPORTED_LANGUAGES`,
`PLATFORM_CAPABILITIES` (content types + copy notes per platform), and
`validate_languages`/`validate_target_platforms`. New endpoint
`GET /api/campaigns/config/platform-capabilities` feeds both the Strategy
Library's campaign-creation checkboxes and Campaign Detail's editable
checkbox row (`usePlatformCapabilities`), each defaulting to `["pt-BR"]` /
`["instagram"]` so a brand that never touches these fields behaves exactly as
before Build 1.

**Part D — `recreate_with_ai` defaults to `false`.** The `/generate`
endpoint's Autopilot flip is reversed again: after round 17 turned full AI
image recreation on by default, Build 1 turns it back off as the normal-
production default everywhere in the app (endpoint default, docstring,
tests) — full recreation remains available, just opt-in
(`?recreate_with_ai=true`), consistent with the product-fidelity concerns
documented in round 18.

**Part E — Campaign Copy full grounding.** `run_copy_stage` (`services/orchestrator.py`)
now assembles, for every `CampaignCopy` and `CarouselPlan` call: the brand
voice/style/creative-instructions block (existing), verified product facts
(Part A, only when a specific product is set), the top research insights for
the campaign's research run (`_format_research_insights_for_prompt`, up to 6
by confidence), the selected strategy's objective/psychology/channels, the
target platform(s)' content types and copy notes (`_platform_requirements_note`,
Part C), and the language-specific style rules (Part F) — all embedded as
text in the `user`/`system` prompt strings, since `AIProvider.generate_structured`'s
signature is fixed. Nothing here was previously wired to research insights or
platform requirements at all; brand/strategy grounding already existed and is
preserved.

**Part F — Independently-native pt-BR and en copy.** `_language_style_rules(language)`
supplies each language its own instruction block naming concrete failure
modes to avoid (for pt-BR: Portugal-specific vocabulary/conjugations,
translated-sounding openers like "Descubra o poder de..."; for en: sentence
structures that read like a translated Portuguese original, equivalent
generic openers) rather than one generic "write naturally" instruction. When
a campaign targets both languages, `run_copy_stage` calls the model once per
language with its own grounding, producing genuinely independent copy per
language rather than one written then mechanically translated.

**Part G — Brand Style Resolver.** `services/creative/brand_style.py`'s
`resolve_brand_style(db, brand, logo_path=None)` centralizes what was
previously scattered, inconsistent, ad hoc reads of `Brand.colors`/`Brand.typography`
(both genuinely free-form JSON — the frontend's own color editor lets the
user type any key name) into one `ResolvedBrandStyle` dataclass: primary/accent/secondary/text
colors and primary/secondary fonts, each resolved by case-insensitive
named-key lookup (`primary`, `accent_color`, `heading_font`, etc.), falling
back to positional lookup among the brand's own color/font values, falling
back to hardcoded defaults only as a last resort — plus visual-reference
asset paths and a joined disclaimer-text string. Wired into both
`run_visuals_stage` and the manual `render_campaign_slide` endpoint, so
Autopilot and manual rendering resolve brand style identically.

**Part H — Deterministic typography for normal production.** Since
`recreate_with_ai` now defaults to `false` (Part D), the deterministic
template renderer (not an image model) is the normal path for baking in
exact text — brand-resolved colors/fonts (Part G) now flow into
`SlideCreativeInput`/`TemplateContext`'s `accent_color`, `text_color`,
`font_family`, and a new `disclaimer` field, which both templates
(`premium_product_hero`, `feature_showcase`) render as a distinct, small,
low-opacity strip, deliberately excluded from the QA report's `text_expected`
check (a disclaimer isn't the slide's primary copy).

**Part I — Campaign Copy prompt versioning.** `services/prompt_registry.py`
makes the previously-dead `PromptVersion` model (present in the schema since
round 1, never read or written) real: `PROMPT_VERSIONS` declares versioned
specs for `campaign_copy` and `carousel_plan` (currently `1.0.0` each),
`ensure_prompt_versions_seeded()` upserts them idempotently at seed time, and
`record_prompt_usage(db, campaign_id, purpose, language, platform)` writes an
`AuditEvent` after every copy/carousel-plan generation recording which prompt
version, language, and platform produced it — full traceability for any
future prompt-quality investigation.

**Persistence shape change.** `CampaignOutput` rows of kind `"copy"` and
`"creative"` moved from a flat per-campaign object to
`{"primary_language": ..., "languages": {"<lang>": {...}}}` (creative also
keeps a shared top-level `creative_brief`), so each targeted language's copy
and carousel plan persist independently. `_stage_language_variant(data, language)`
transparently reads either the new nested shape or the pre-Build-1 flat shape,
so `get_campaign_copy` (used by the publish endpoint) and `run_visuals_stage`
work unchanged against campaigns created before this build.

Migrations: `f4a8c2e6b1d9` (`verified_product_facts` table;
`campaigns.languages`/`campaigns.target_platforms`, backfilled row-by-row in
Python — not raw SQL `json_array()`, to avoid a SQLite JSON1 dependency —
then set `NOT NULL`), verified up/down/up and against real pre-existing data.
238 tests total (up from 215).

**Explicitly out of scope for Build 1** (not silently under-delivered — these
are the next build's territory): full per-platform pixel-rendering variants
(today `Campaign.platform_key`/`PLATFORM_FORMATS`, round 20's pixel-size
picker, is unchanged and stays a separate concept from the new marketing-platform
`target_platforms`); full multi-language *visual* rendering (`run_visuals_stage`
renders only the primary — first-selected — language's slides into images;
every other selected language's copy and carousel plan are generated and
persisted in full, just not rendered); a dedicated frontend page for editing
Verified Product Facts (the API and hooks are fully wired and tested, but
editing today means calling the endpoint directly); the DESIGN_PROFILE_ID
multi-profile system and real evidence-gated badge/testimonial rendering,
unchanged from round 20.

## Build 2 — Platform Adapter + Creative Director + Hybrid Visual Engine

The second build, resolving both limitations Build 1 explicitly carried
forward: only the primary (first-selected) language actually rendered into
slide images, and `target_platforms` had no formal relationship to
`platform_key`/`PLATFORM_FORMATS`. Scoped to twelve parts (A-L). 270 tests
total (up from 238) — every Build 1 test still passes unchanged, because the
primary (first-selected platform x first-selected language) combination
still renders through the exact unchanged pre-Build-2 code path in
`run_visuals_stage`'s own loop; the new multi-variant rendering is
additive on top of it.

**Parts A/B — `PlatformCreativeSpec`.** A new `data/platform_creative_specs.py`
registry resolves TARGET PLATFORM -> CONTENT TYPE -> RENDER FORMAT — the
missing middle layer between `PLATFORM_CAPABILITIES` (Build 1's marketing-
platform targeting) and `PLATFORM_FORMATS` (pre-Build-1's pixel-exact render
canvases). Every content type the app can genuinely support today is
catalogued per platform (Instagram, Facebook, TikTok, YouTube Shorts,
Pinterest, LinkedIn, X); video-oriented content types are represented
structurally but marked `supports_static=False` so nothing pretends they
render as an image.

**Part C — Brand Asset Validator.** `services/brand_assets_validator.py::
validate_brand_assets` checks a brand's real logo, fonts, palette, and
per-product photo coverage — purely deterministic, never invents a
placeholder for a brand with nothing uploaded. `GET /api/brands/{id}/
asset-validation`.

**Part D — Model role routing.** Ten configurable model roles
(`research_model`/`campaign_model` already existed; eight new:
`strategy_model`, `copy_model`, `platform_adapter_model`,
`creative_director_model`, `draft_image_model`, `premium_image_model`,
`creative_qa_model`, `revision_model`), each falling back to the legacy field
it replaces when unset, so nothing changes for an existing deployment that
hasn't touched Settings.

**Part E/F — Master Campaign Concept + Platform Adapter, the core fix.** One
`MasterCampaignConcept` per campaign (generated in `run_copy_stage`, held
constant across every adaptation); a `PlatformAdaptation` per (campaign,
platform) describing how the concept's story genuinely reshapes for that
platform's real conventions (never "just resize the same creative"); and,
the actual carry-forward deliverable, an independent `PlatformCampaignVariant`
row — its own rendered asset, copy-language reference, layout pass, status,
and QA report paths — for every (target_platform x language) combination a
campaign selects, beyond the one the legacy loop already renders. Instagram
+pt-BR, Instagram+en, Facebook+pt-BR, Facebook+en now really do become four
independently reviewable variants when those targets are selected. New model
`PlatformCampaignVariant` (deliberately not a repurposing of the pre-existing,
confirmed-dead `CampaignVariant` — an unrelated A/B-testing concept from
round 1). New endpoint `GET /api/campaigns/{id}/variants`.

**Cost discipline.** An AI-generated background is generated once per
(platform, slide index) and reused across that platform's other targeted
languages (the scene is language-independent); full AI recreation cannot be
shared this way, since the marketing text bakes directly into those pixels —
a real, documented cost tradeoff between the two modes, not an oversight.

**Part G/H — Creative Director + multi-language layout.** `CreativeDirection`
is generated once PER (platform, language, slide) — never shared across a
platform's languages — so typography/headline emphasis can genuinely differ
between pt-BR and en for the same slide, proved directly by a dedicated test.
AI-optional: a deterministic fallback (built only from already-known real
data, never a fabricated visual claim) is used whenever no AI provider is
available.

**Part I/J — Hybrid Renderer + scene-only background generation.** No new
rendering architecture was needed — the existing `render_slide()` pipeline
already implements the source-photo -> composite-product -> generate-scene ->
real-logo -> real-text -> export chain Build 2 asked for.
`generate_ai_background`'s prompt now explicitly names every element the AI
must never generate (exact label text, brand logo, headline/body/CTA copy,
price/discount graphic, legal text) — all of those stay real HTML/CSS or the
real product photo.

**Part K — Quality modes.** `draft`/`standard`/`premium`, each resolving to a
(model, Images-API-quality-tier) pair; `standard` (the default) is
byte-for-byte what every AI-image call always used before this existed.
Threaded from the `/generate` and `/generate/visuals` endpoints' new
`quality_mode` query parameter.

**Part L — Video-oriented output, never a fake video.** TikTok/YouTube
Shorts content types that can't render as a static image produce a
structured `VideoConcept` (hook/script/shot list/timing/on-screen text/
caption/cover brief) instead — `is_rendered_video` is fixed `False` by the
schema itself, not caller-settable. The variant's `status` is honest about
the outcome: `SCRIPT_ONLY` with a real script, or `SCRIPT_UNAVAILABLE`
(never a fabricated one) with no AI provider on hand.

**Traceability extension.** Build 1's `services/prompt_registry.py` (versioned
prompt specs + `record_prompt_usage`, logging purpose/version/language/
platform as an `AuditEvent`) gains four Build 2 entries — `master_campaign_concept`,
`platform_adaptation`, `creative_direction`, `video_concept` — all `version
="1.0.0"`, logged from the same call sites that generate each one, so a past
campaign's platform adaptation and per-language creative direction are just
as traceable as its copy always was.

Migration: `a1b2c3d4e5f6` (new `platform_campaign_variants` table,
down_revision `f4a8c2e6b1d9`), verified up/down/up and against a simulated
pre-Build-2 database.

**Explicitly out of scope for Build 2** (next build's territory): a
dedicated frontend surface for `PlatformCampaignVariant`s or the Brand Asset
Validator's result (both endpoints are fully wired and tested, no frontend
page consumes them yet); actual video file generation for TikTok/YouTube
Shorts (Part L stays structured script output only, by design); a UI picker
for `quality_mode`/`render_platform_variants` (both work end-to-end via the
API today); and, unchanged from Build 1, the DESIGN_PROFILE_ID multi-profile
system and real evidence-gated badge/testimonial rendering.

## Build 3 — Platform + Language Aware Multimodal QA

The third build: evaluates every already-rendered Build 2
`PlatformCampaignVariant` for visual quality, brand quality, product
fidelity, language quality, and platform fit, then applies ONE targeted,
minimal revision when something fails. 281 tests total (up from 270 at the
start) — every Build 1/2 test still passes unchanged, since the new QA stage
(`services/qa_engine.py::run_qa_stage`) is a separately-callable stage
(`AutopilotConfig.enable_qa_stage`, default `False`, never auto-invoked from
`run_autopilot`) rather than something bolted onto Visuals.

**Carried forward from Build 2, verified and fixed first.** Before adding
any new QA machinery, this build verified and closed a real gap in Build 2's
own cost discipline: a non-primary LANGUAGE of the PRIMARY platform (e.g.
Instagram+en when Instagram+pt-BR is primary) always regenerated its
AI-generated background from scratch, even though nothing about the scene
should differ — `run_visuals_stage`'s own primary-combo loop never handed
its already-generated backgrounds to `_render_additional_platform_variants`.
Fixed via a "scene signature" (the scene-relevant `CreativeDirection` fields
only, never the per-language typography fields) so reuse only happens when
two languages' resolved directions genuinely describe the same scene — never
force-shared when an AI-authored direction genuinely disagrees, and never
across platform/product/campaign boundaries. Also verified: QA state
attaches to the correct `PlatformCampaignVariant`, never only the parent
Campaign; a video-oriented (script-only) variant gets format-appropriate QA,
never static-image visual QA; and Build 2's "the hybrid renderer already
satisfies the architecture" claim was treated as something for the new
creative critic to verify, not an unquestioned assumption (it found no
actual defect, so no renderer code was rewritten).

**Part A — Technical QA (deterministic).** Dimensions, valid file, PNG
format, exact size vs. the variant's own `PlatformCreativeSpec`,
slide-count-vs-carousel-support, cover-required — folding in the per-slide
mechanical QA `services/creative/qa.py` already wrote at render time.

**Part B — the multimodal creative critic.** A new dedicated
`AIProvider.critique_creative` Protocol method (never a generic image param
bolted onto the existing structured-generation call, matching this
codebase's established pattern) scores every dimension the spec named:
overall quality, brand alignment, product fidelity/prominence, composition,
typography, readability, color harmony, hierarchy, clutter, copy/visual fit,
CTA visibility, mobile readability, originality, professional ad quality,
carousel consistency, platform fit, language naturalness — grounded in the
real VerifiedProductFacts, brand requirements, MasterCampaignConcept,
CreativeDirection, copy, locale, platform, and carousel context.
AI-optional: `None` (never a fabricated scorecard) with no key configured.

**Part C — language QA.** A deterministic check (byte-identical copy across
two declared languages is a real "likely untranslated" signal, no AI
needed) plus an AI critic covering the spec's six named hard-fail
conditions: wrong language, untranslated text remaining, accidental
PT-BR/English mixing, grammar broken badly enough to damage meaning, an
obvious literal translation, spelling corruption.

**Part D — platform hard fails (deterministic).** Wrong aspect ratio, a
video-oriented content type rendered as a static image (or falsely claimed
as a generated video file), a missing/corrupt asset, a carousel exceeding
platform constraints, a missing required cover.

**Part E — targeted revision, never a blind full regeneration.** Exactly
ONE fix per failing attempt, scoped to exactly one variant: a language issue
gets a copy-only rewrite ("English headline too long -> revise English copy
only"); a platform/technical issue gets a bare re-render with nothing else
touched ("Pinterest aspect problem -> rerender Pinterest variant"); only a
genuinely weak/wrong creative issue gets a real creative-direction revision
and a regenerated scene ("Instagram visual weak -> revise Instagram
CreativeDirection only"), optionally trying several candidates and keeping
the best (Part G).

**Part H — needs review, never a false pass.** Up to `qa_max_retries`
(default 2) targeted-revision rounds before a still-failing variant settles
at `qa_status="NEEDS_REVIEW"` — including the case where no AI provider is
configured at all, which deliberately scores `overall_quality = 0` (never a
passing-adjacent default) rather than a false PASS.

New endpoint: `POST /api/campaigns/{id}/generate/qa` (background job,
`qa_pass_threshold`/`qa_max_retries`/`qa_best_of_n`/`use_ai_background`
query params; 400s with a clear message if Visuals hasn't run yet).
`GET /api/campaigns/{id}/variants` now also returns `qa_status`, `qa_scores`,
`qa_hard_fails`, `qa_attempts`, `qa_evidence_paths`, `qa_versions`, and
`qa_notes` per variant. Migration `b2c3d4e5f6a7` (7 new columns on
`platform_campaign_variants`, down_revision `a1b2c3d4e5f6`), verified
up/down/up.

**Explicitly out of scope for Build 3** (next build's territory): a
dedicated frontend surface for reviewing QA results or triggering
`/generate/qa` (the API is fully wired and tested, no frontend page consumes
it yet); real video file rendering (script/storyboard-only QA stays exactly
that, by design, matching Build 2's Part L); and a real
`cover_creative_quality` score for a script-only variant (stays honestly
`None` — no cover image exists in this app's architecture yet).

## Build 4 — Human Approval + Platform/Language Feedback Learning

The fourth build: lets the owner APPROVE / REJECT / REQUEST_REVISION at
campaign, platform+language-variant, or individual asset-slide level,
records that decision with full traceability, applies a requested revision
by reusing Build 3's own targeted-revision machinery, and feeds selective,
bounded feedback back into generation without cloning past creative. 296
tests total (up from 281 at the start) — every Build 1-3 test still passes
unchanged, since prompt-grounding is additive text, `""` for an empty
`review_feedback` table.

**New table + columns.** `ReviewFeedback` (one append-only row per human
review action) plus `human_review_status` on both `Campaign` and
`PlatformCampaignVariant` — a genuinely third, independent axis alongside
`status` (production-pipeline stage) and Build 3's `qa_status` (automated
critic verdict). A variant can honestly be `qa_status=PASS` +
`human_review_status=REJECTED` at the same time; nothing collapses the two.

**Traceability + lineage.** Every review action snapshots exactly what was
reviewed (reviewed asset paths, video concept, copy, creative direction, QA
status/scores/hard-fails/attempts/evidence/versions, and a best-effort
prompt-version read-back) — frozen at review time, never a live reference,
so a later QA rerun or revision can never make a past decision ambiguous. A
`REQUEST_REVISION` action's own reviewed snapshot IS the permanent history;
the live variant row is free to change going forward, and a later review
action on the same variant auto-links back to it (`revision_of_feedback_id`)
with no extra parameter needed.

**Selective, bounded retrieval, no cloning.** Feedback scoped to a specific
platform/language that doesn't match the current generation context is
excluded outright (not just ranked lower) — repeated Instagram PT-BR "Too
much text" feedback never blindly affects Pinterest English creative.
Positive (approved) examples guide tone/density/CTA style/composition
tendencies via characterization only — reason + platform/language context —
NEVER the approved variant's literal headline/body/CTA text, so generation
is guided without being cloned. Capped at `AutopilotConfig.feedback_
examples_limit` (default 5) per side. Novelty detection
(`CampaignFingerprint`) is untouched entirely.

**Applying a revision reuses Build 3, never a second pipeline.** A
`REQUEST_REVISION`'s `reason_code` maps to one of four revision kinds (copy /
creative_direction / rerender / video_concept — `data/feedback_reasons.py`),
each dispatching to the SAME Build 3 QA-engine primitives `run_qa_stage`
itself already uses (`revise_copy_for_variant`, `revise_creative_direction_
for_variant`, `_regenerate_variant_render`, `_regenerate_with_best_of_n`,
`revise_video_concept`). A script-only (TikTok/Reels/Shorts) variant is only
ever revised as a script — `asset_ref` for that variant must be one of
hook/script/shot_list/timing/on_screen_text/caption/cover, never a
rendered-slide-style reference, so the API never implies a rendered video
file exists.

New endpoints: `POST /api/campaigns/{id}/review` (the one unified review
action for all three levels; a variant-scoped `REQUEST_REVISION` kicks off
the actual revision as a background job, mirroring `/generate/qa`'s shape),
`GET /api/campaigns/{id}/review-feedback` (full history, newest first,
lineage intact), `GET /api/campaigns/{id}/review-summary` (campaign-level
status plus a read-only per-variant rollup that never writes back — "parent
may aggregate, child truth is preserved"). `GET /api/campaigns/{id}/variants`
now also returns `human_review_status` per variant. Migration `c4d5e6f7a8b9`
(down_revision `b2c3d4e5f6a7`).

**Explicitly out of scope for Build 4** (next build's territory): a
dedicated frontend surface for submitting reviews or browsing feedback
history (the API is fully wired and tested, no frontend page consumes it
yet); feedback-grounding wired into `carousel_plan`/`video_concept`
generation (only campaign copy and per-slide creative direction get it this
build); a campaign-level `REQUEST_REVISION` automatically fanning out to
every platform/language variant (records the feedback only — the owner
follows up with variant-level requests for whichever executions need work);
and a computed diff API between a pre- and post-revision version (fully
answerable from the stored snapshot data, but no diff endpoint is built this
round).

## Build 4 carry-forward — feedback grounding completed for carousel/video/adaptation

The one Build 4 gap called out in item 9 below (as it stood before this
round) is now closed: `run_copy_stage`'s `CarouselPlan` calls (both the
discovery and non-discovery branches), `generate_video_concept`, and
`_resolve_platform_adaptation` all now receive the same selective, bounded
`feedback_note` `CampaignCopy`/`_generate_creative_direction` already got —
platform adaptation resolves it platform-only (shared across languages,
matching how one `PlatformAdaptation` covers every language a platform
targets); video-concept resolves it per (platform, language), so a TikTok/
pt-BR "weak hook" pattern grounds future TikTok/pt-BR scripts without
touching YouTube Shorts or a different language. Covered by 5 new tests in
`tests/test_build4_completion.py`. Full suite: 301 passed (296 + 5). See
`docs/architecture.md`'s "5z-2" section for the full writeup.

## Build 5 — Golden Benchmark + Prompt Registry + Multi-Platform Regression

A new `BenchmarkCase` (explicitly curated only — never automatic from a
plain review action) + `BenchmarkRun` (one real pipeline execution, frozen
prompt-version/model-role/cost/score snapshot) pair, plus a documented
per-platform scoring-weight table (`data/benchmark_scoring.py`) and a
regression-comparison service (`compare_runs`/`build_regression_report`)
that rolls results up by platform AND independently by language, so one
language improving never hides another regressing. Four test modes —
`OFFLINE` (a built-in zero-network stand-in provider, genuinely free),
`MOCK` (test-only fake provider), `LOW_COST_SMOKE` (real provider, cost-
limited config), `LIVE_FULL`. An owner-agreement report
(`compute_owner_agreement_report`) surfaces QA/owner calibration gaps
(false-positive creative pass, false-negative creative fail) as plain
counts, always with an explicit "not a statistically meaningful accuracy
percentage" caveat. New API surface under `/api/benchmarks/*`. Migration
`d5e6f7a8b9c0` (down_revision `c4d5e6f7a8b9`). Covered by 13 tests in
`tests/test_build5_benchmark.py`. Full suite: 314 passed. See
`docs/architecture.md`'s "6a" section for the full writeup.

## Build 5 repair — prompt + creative-system traceability

Accepted provisionally, with one real gap flagged before Build 6: scene/
image generation — the one major generation step — had no versioned recipe
(`IMAGE_PROMPT_VERSIONED=Not tracked` in the original completion packet).
Five targeted repairs, no benchmark-system redesign, no regression: (1) a
new `"scene_generation"` prompt-registry entry versions the RECIPE that
composes `generate_ai_background`/`recreate_creative_image`'s dynamic
prompt (which inputs feed it, what's structurally forbidden, how product
preservation is enforced) — not one frozen literal string, since the actual
text is still built per slide; recorded via `record_prompt_usage` at every
real call site that produced an image; (2) a new `BenchmarkRun.creative_
system_snapshot` JSON column (migration `e6f7a8b9c0d1`) gives a single,
complete, immutable answer to "what exact generation system produced this
run?" — nesting the per-purpose prompt-version snapshot alongside three new
version constants (`VERIFIED_PRODUCT_FACTS_RESOLVER_VERSION`,
`RENDERER_VERSION`, `TEMPLATE_REGISTRY_VERSION`) and the run's own platform/
language/content_type/quality_mode, deliberately not duplicating `model_
role_snapshot`'s own column; (3) those two new version constants are simple
strings, not a new framework; (4) a targeted revision's own effective prompt
version (e.g. `targeted_copy_revision`) was confirmed, via a new test, to
already surface as its own distinct key in a benchmark run's snapshot,
never overwriting the original purpose's version — no code change needed,
since Build 4's own most-recent-wins-per-purpose design already guaranteed
this; (5) the owner/QA agreement report's four-way classification (already
correct) got an exhaustive test checking every named field, not just the
aggregate count. A real, pre-existing (not repair-introduced) architectural
fact surfaced while testing: `CreativeDirection` is only ever AI-generated
on the additional-platform-variant path, so a `BenchmarkRun` — always
single-platform/single-language by design — currently never exercises that
path; proving it still works dynamically needed a direct `run_visuals_
stage` call against a real multi-language campaign instead. 10 new tests in
`tests/test_build5_repair.py`. Full suite: 324 passed (314 + 10). See
`docs/architecture.md`'s "6a-2" section for the full writeup.

## Build 6 — Production Integration + Multi-Platform Hanna Acceptance

Two real gaps closed: `AIUsage` (existed since round 1) finally gets
written to — `services/ai/openai_provider.py` accumulates real token/image
counts per real API call, `services/usage_tracking.py::record_stage_usage`
writes one `AIUsage` row per event at the same 19 call sites
`record_prompt_usage` already logs from, and `build_campaign_cost_report`
(what `benchmark_engine.py`'s cost helper now delegates to) adds
per-operation and per-variant cost breakdowns on top of the pre-existing
totals — and a genuine, real-Hanna-data acceptance suite
(`tests/test_build6_acceptance.py`, 5 tests) proves the pipeline works end
to end, not just piece by piece: a real cross-platform+bilingual campaign
(Instagram+Facebook x pt-BR+en) sharing one `MasterCampaignConcept`,
exercising `CreativeDirection`'s real AI-generation path (unreachable via
the benchmark system, per the Build 5 repair's own architectural finding)
and same-platform scene reuse through the real cache-matching logic; a
forced single-variant QA failure proving its siblings are completely
unaffected and the real outcome is reported honestly; live traceability via
`build_creative_system_snapshot` against a real (non-benchmark) run; a
TikTok variant proven script-only, never claiming rendered-video fidelity;
DRAFT/STANDARD/PREMIUM resolving to materially different image
model/quality; and the full human-review loop with complete history.
`VerifiedProductFact` fixtures use only what Hanna's own canonical product
catalog actually permits (identity/category/origin), with every forbidden-
to-invent field genuinely absent and reported as missing, never guessed.
New `scripts/run_live_acceptance.py` is the genuinely LIVE counterpart,
runnable only on the owner's own PC with their own OpenAI key — this
sandbox has neither, so every `LIVE_ACCEPTANCE` figure in the Build 6
completion packet says so plainly. Full suite: 337 passed (324 + 5 + 8 for
`tests/test_usage_tracking.py`). See `docs/architecture.md`'s "6a-3" section
and `docs/marketing-os-creative-quality-handoff.md` for the full writeup.

## What's left

Everything from the original 68-section brief's build order, the Strategy
Library/Defense addendum, the Facebook Page/Instagram auto-publish extension,
every item from the round-11 five-item polish list, Build 1's Verified
Product Facts + Campaign Foundation program, Build 2's Platform
Adapter + Creative Director + Hybrid Visual Engine program, Build 3's
Platform + Language Aware Multimodal QA program, Build 4's Human
Approval + Platform/Language Feedback Learning program (including its own
carry-forward completion above), Build 5's Golden Benchmark + Prompt
Registry + Multi-Platform Regression program (plus its repair round), and
Build 6's Production Integration + Multi-Platform Hanna Acceptance program
are now implemented. What remains is genuinely optional or explicitly
deferred to a later build, not a missing phase:

1. A dedicated frontend editor for Verified Product Facts (Build 1, Part A) —
   the API/hooks already exist; today editing means calling
   `PUT /api/products/{id}/verified-facts` directly.
2. A dedicated frontend surface for browsing `PlatformCampaignVariant` rows
   and their Build 3 QA results (`qa_status`/`qa_scores`/`qa_hard_fails`),
   for triggering `POST /{id}/generate/qa`, or for the Brand Asset
   Validator's result (Build 2, Part C) — `GET /api/campaigns/{id}/variants`,
   `POST /api/campaigns/{id}/generate/qa`, and `GET /api/brands/{id}/
   asset-validation` are all fully wired and tested; today reading/triggering
   any of them means calling the endpoint directly. Pixel format
   (`platform_key`) also still stays a separate picker from the
   marketing-platform `target_platforms` list, by design (Build 1's own
   explicit "do not collapse" requirement, carried forward unchanged through
   Build 2's `PlatformCreativeSpec` and Build 3's QA specs).
3. Actual video file generation for TikTok/YouTube Shorts (Build 2, Part L;
   Build 3 carry-forward requirement 3) — deliberately out of scope; those
   content types produce a structured `VideoConcept` (hook/script/shot list)
   for a human production team, evaluated by Build 3's own format-appropriate
   script/storyboard QA, never a rendered video or video-visual-fidelity
   claim, by design.
4. A UI picker for `quality_mode` (draft/standard/premium, Build 2, Part K),
   `render_platform_variants`, or Build 3's `qa_pass_threshold`/
   `qa_max_retries`/`qa_best_of_n` — all work end-to-end via the API with
   sane defaults today, just not yet exposed as Campaign Detail controls.
5. A real `cover_creative_quality` score for a script-only video variant
   (Build 3, Part B/L) — stays honestly `None`, since this app's architecture
   never produces a cover image for a video concept yet.
6. A second `PublishingProvider` connector (e.g. Pinterest) if the user ever wants
   one — the Protocol and the `POST /{id}/publish` endpoint's shape already
   generalize to more than one provider.
7. A second *performance*-read connector beyond Meta Insights (e.g. a Pinterest
   Analytics equivalent, if a second publishing connector is ever added) —
   `PerformanceMetric.source` already generalizes to more than one connector name.
8. A dedicated frontend surface for Build 4's review/feedback system —
   submitting APPROVE/REJECT/REQUEST_REVISION actions, browsing
   `ReviewFeedback` history with lineage, or viewing the campaign/variant
   review-status rollup — `POST /api/campaigns/{id}/review`, `GET
   /api/campaigns/{id}/review-feedback`, and `GET /api/campaigns/{id}/
   review-summary` are all fully wired and tested; today submitting/browsing
   any of them means calling the endpoint directly.
9. A campaign-level `REQUEST_REVISION` automatically revising every
   platform/language variant at once, rather than the owner following up per
   variant (Build 3's own "never a blind full-campaign regeneration"
   discipline, carried forward) — and a computed diff API between a pre- and
   post-revision version (fully answerable from Build 4's own stored
   snapshot data, no endpoint built yet). (`CampaignCopy`, per-slide
   `CreativeDirection`, `CarouselPlan`, `video_concept`, and platform
   adaptation generation all now consult past feedback — see the Build 4
   carry-forward section above; this item is only the two pieces that were
   never in scope for that fix.)
10. ~~`AIUsage` population at every real AI call site~~ — **done in Build 6**
    (`services/usage_tracking.py`, `OpenAIProvider.drain_usage_events`) —
    every real AI call, in every stage, at every call site, now records real
    cost/usage, attributed by campaign/operation/platform/language/
    content_type; `build_campaign_cost_report` exposes per-operation and
    per-variant breakdowns. What's still missing: a dedicated pre-flight
    "expected generation scope/cost" endpoint (`platforms x languages`
    multiplication is trivial to compute client-side today, but nothing
    surfaces it as a first-class API response yet), and `quality_mode=
    "premium"` does not automatically raise `qa_best_of_n`/`qa_max_retries`
    (the mechanism is fully wired; the auto-link isn't) — see
    `docs/marketing-os-creative-quality-handoff.md` §5/§11.
11. A dedicated frontend for Build 5's benchmark system — curating a
    `BenchmarkCase` from a review-feedback row, triggering a run, or viewing
    a regression report/owner-agreement report — `/api/benchmarks/*` (cases,
    runs, compare, regression-report, owner-agreement, prompt-registry) is
    fully wired and tested; today all of it means calling the endpoint
    directly.
12. Automatic CI-gate wiring for Build 5's regression reports (e.g. failing
    a build when `build_regression_report` shows a real regression) — the
    report itself is real and correct, just not yet hooked into any
    pass/fail gate outside a human reading it.
13. ~~Running `scripts/run_live_acceptance.py` (Build 6) against a real
    OpenAI key~~ — **done**: the owner ran it on their own machine
    (`data/live_acceptance/20260912T064017Z.json`, `LIVE_ACCEPTANCE=
    NEEDS_REVIEW`, $6.110996/89 calls). That real run surfaced seven
    critical defects the Build 6 REPAIR section below fixes — see that
    section for the full list. A fresh live run against the repaired
    pipeline has NOT been performed as part of the repair itself, per the
    owner's own explicit instruction not to re-run live network acceptance
    during this repair; see `claude/build-status.md`'s Build 6 REPAIR entry.
14. Any further UX refinement that comes from actually using the app day to
    day — there's no known gap left from the original brief, its follow-up
    asks, or Build 1/Build 2/Build 3/Build 4/Build 5/Build 6's own specs.

Each of these is additive against the schema in `data-model.md` — no migration in this
phase should need to be reverted by a later one.

## Build 6 REPAIR — targeted live-acceptance repair

A genuine live run of `scripts/run_live_acceptance.py` on the owner's own
machine (real OpenAI key, real cost, `LIVE_ACCEPTANCE=NEEDS_REVIEW`) found
seven concrete defects a fake-provider test suite alone could not catch.
This section is a targeted repair of those seven — never a Build 7, never a
frontend redesign, never a rewrite of working Build 1-6 features. No live
network acceptance was re-run as part of this repair (the owner's own
explicit instruction); every fix below is verified by the full backend test
suite (365 tests, up from 337) using deterministic fake providers only.

1. **Source-product identity gate (pre-generation).** A campaign for
   "Melano CC Essence" (a serum) rendered a package clearly labeled as a
   cleanser — the selected source photo was never actually of the named
   product, and nothing caught it before billed generation. New:
   `SourceProductIdentityCheck` (`schemas/ai.py`) — a three-way `MATCH` /
   `MISMATCH` / `UNVERIFIABLE` verdict, deliberately distinct from the
   existing post-generation `ProductFidelityCheck` (that one compares an
   AI-recreated image back against its own source photo; this one compares
   the source photo itself against the catalog's own product identity,
   before any generation spends money). `AIProvider.verify_source_product_
   identity` (Protocol + `OpenAIProvider` implementation) is the vision
   call; `services/orchestrator.py::_enforce_source_product_identity_gate`
   is the enforcement point, wired into `run_visuals_stage` right before
   `campaign.status = "GENERATING"` for both the discovery and deep-dive
   branches. `UNVERIFIABLE` is never silently treated as `MATCH` (fail-
   closed, mirroring round 18's own fidelity-gate discipline) — anything
   short of a confirmed `MATCH` raises `SourceProductIdentityMismatch`,
   failing the whole run (never a soft `NEEDS_REVIEW`), before a single
   image is generated. Skipped entirely (zero cost, zero risk) for a
   category-only campaign (no product to check), when no `ai_provider` is
   given, or when the given provider simply doesn't implement this vision
   check — that last case matters because every pre-repair test fake in
   this whole suite predates this capability, and without the duck-typed
   check it would fail every one of them outright (see `services/usage_
   tracking.py::drain_provider_usage_events` for the exact same pattern,
   applied here for the exact same reason). Deduped per asset (a photo
   reused across several slides is only checked/billed once).

2. **Claims-boundary grounding across the whole pipeline.** Despite
   `VerifiedProductFacts` being deliberately sparse for the live-run
   product (only `verified_country_of_origin` confirmed), the generated
   copy/concept asserted bestseller/"#1" status, before/after results, a
   VIP/restock/priority-shipping perk, a follower/community-size number,
   and other unsupported claims — and the acceptance runner's own
   `unsupported_claim_flags` came back empty. New: one shared
   `_claims_boundary_instruction()` (`services/orchestrator.py`), a strict
   four-way separation between (1) verified product facts — stateable as
   fact, (2) research insights — context/angle only, never a stated product
   fact or number, (3) owner-confirmed brand/program notes — usable as
   given, never extended with an invented extra, and (4) the model's own
   creative ideas — never phrased as a factual/operational claim. Wired
   into every relevant prompt: `creative_brief`, `master_campaign_concept`,
   `campaign_copy`, both `carousel_plan` branches, `generate_video_concept`,
   and the two targeted-revision prompts (`revise_copy_for_variant`,
   `revise_video_concept`) in `qa_engine.py`. Explicitly names the banned-
   without-verification list (bestseller/rank/#1, a customer/follower/
   community-size number, a before/after result, a restock/early-access/
   priority-shipping promise, a VIP/membership perk, a surprise gift/bonus,
   a discount/price, a star rating/testimonial, a clinical/scientific
   claim) and instructs that sparse facts should produce a simpler, honest
   concept rather than an invented one. Two pre-existing grounding gaps
   fixed along the way: `master_campaign_concept`'s prompt previously got
   ZERO verified-facts/research grounding at all (it now gets both, since
   its own `campaign_promise`/`key_message` become ground truth for every
   downstream stage); the discovery-mode `carousel_plan` branch's per-
   product lines previously carried only free-text `notes` (now each line
   also states that product's own `missing_information`, so a sparse/
   unverified product is told what it does NOT yet know, not left silent).
   The AI-recreation prompt's existing claims-safety instruction (round 20)
   was also extended to name a VIP/membership badge, a restock/early-
   access/priority-shipping graphic, a surprise-gift/bonus callout, and a
   customer/follower-count badge, alongside its pre-existing list.

3. **Duplicate/no-effect revision guard.** Manual SHA256 review of a real
   acceptance run's output found 27 of 54 rendered PNGs were byte-identical
   duplicates — revision rounds that re-spent render/AI work without
   changing the artifact (e.g. two Instagram revision rounds identical to
   the base render; a Facebook pt-BR revision round identical to its own
   prior attempt). New: `qa_engine.py::_hash_slide_files` (SHA256 of each
   rendered PNG's real bytes) is compared before/after every revision
   attempt inside `_qa_one_static_variant`'s retry loop. A revision whose
   output hashes identically to what was already there is never accepted —
   the variant settles at `qa_status="NEEDS_REVIEW"` with a
   `REVISION_NO_EFFECT` note right there, stopping retries immediately
   rather than repeating an already-paid-for, provably ineffective action.
   The freshly-rendered-but-discarded files from that ineffective attempt
   are deleted from disk (mirroring `_regenerate_with_best_of_n`'s own
   losing-candidate cleanup) rather than left as orphaned duplicates.

4. **Deterministic platform-aware text fitting.** A real Facebook pt-BR
   result hard-failed text overflow on 4 slides, and the automatic revision
   loop never resolved it — because the generic "platform issue" branch is
   a bare re-render that never touches the copy, so it reproduces the
   identical overflow every attempt. New: a text-overflow hard fail
   (detected from `TechnicalQAResult.issues` containing "overflow") is now
   its own priority branch, checked ahead of the generic platform-issue
   branch, that calls `qa_engine.py::_deterministic_shorten_copy` — pure
   word-boundary truncation (never a paraphrase/rewrite) keyed off the
   platform's own already-known `PlatformCreativeSpec.max_copy_density`
   ("low"/"medium"/"high" -> a per-field word budget) — before re-rendering.
   No AI call, no scene regeneration: a purely mechanical DOM-measurement
   fact gets a purely mechanical fix, per the repair's own "route
   deterministic problems deterministically" instruction. If the shortened
   copy still overflows (a genuine template/density mismatch, not a length
   problem), the hash guard above (item 3) or the retry limit correctly
   keeps surfacing that as a real, honest failure rather than masking it.

5. **TikTok/video-concept one retry.** A live run left TikTok/pt-BR at
   `status=SCRIPT_UNAVAILABLE`/`qa_status=PENDING` — plausibly a single
   transient API failure, since `generate_video_concept` had no retry at
   all (unlike `recreate_creative_image_with_fidelity_gate`'s established
   one-retry pattern). Fixed: one retry before giving up; a second
   consecutive failure still returns `None` and the caller still records
   `SCRIPT_UNAVAILABLE` — the "never fabricate a script" contract is
   unchanged, only the odds of an avoidable false failure are reduced.

6. **Exact acceptance matrix, never a Cartesian product.** The live run's
   own cost/output was inflated because `run_live_acceptance.py` built
   `campaign.languages`/`campaign.target_platforms` as independent
   deduplicated lists from its 5-pair matrix — and `run_visuals_stage`'s
   underlying architecture always expands `target_platforms x languages`
   for whatever campaign it's given (a real, load-bearing, per-campaign
   design, not a bug), so 4 platforms x 2 languages silently rendered and
   billed all 8 combinations, not just the 5 requested pairs (e.g.
   Facebook/en and Pinterest/pt-BR were never asked for but were produced
   anyway). Fixed entirely inside the script (no change to the shared
   pipeline architecture, per the "no broad unrelated refactor"
   instruction): `_group_matrix_by_platform` groups the matrix by platform,
   preserving matrix order, and the script now runs ONE single-platform-
   scoped campaign per platform group with `languages` limited to only that
   platform's own matrix-requested languages — one platform times its own
   N languages is just N pairs, never an uninvited combination. The script
   asserts this held (`exact_matrix_violation` in its report) rather than
   silently trusting it.

7. **Usage-scope attribution + cost preflight.** The live run cost
   $6.110996 over 89 calls, with some `AIUsage` rows carrying blank
   platform/language/content_type that were impossible to tell apart from
   a bug versus a genuinely campaign-wide call, and no way to cap spend
   before it happened. Fixed: a new `AIUsage.scope` column
   (`"campaign_global"` vs `"variant"`, migration `b6c7d8e9f0a1`, down-
   revision `f7a8b9c0d1e2`) makes the distinction explicit rather than
   inferred (see `data-model.md`); `build_campaign_cost_report`'s new
   `by_scope` breakdown aggregates on it. `run_live_acceptance.py` gained
   `--estimate-only` (prints a clearly-labeled ESTIMATE, makes zero API
   calls), `--max-budget-usd` (refuses to start if the estimate already
   exceeds it; stops between platform groups once the REAL accumulated
   cost would reach it), and `--smoke` (a reduced 2-case matrix — one
   static-image case, one script-only case — with `qa_max_retries=0`/
   `qa_best_of_n=1`, for cheaply validating the pipeline end to end before
   spending on the full run). The final report always separates
   `estimated_cost_usd` from `actual_cost_usd` — never one guaranteed
   figure standing in for the other.

See `claude/build-status.md` (Project docs) for the full numbered defect
list this maps to, the exact test coverage added (`tests/test_build6_
repair.py`, plus updates to `test_build3_qa_engine.py`, `test_usage_
tracking.py`, `test_db_migrations.py`), and the completion-packet fields
reported to the owner.
