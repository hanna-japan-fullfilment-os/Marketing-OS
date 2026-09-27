# Architecture — Marketing Operating System

## 0. Status of this document

This describes the target architecture for the full system in the project brief. The
codebase in this repo implements it incrementally, in the phase order below. See the
"Implementation status" table for exactly what is real code today vs. what is designed
but not yet built. Every phase not yet built has its database tables, service
interfaces, and API contracts already designed here so later phases plug in without a
rewrite.

## 1. Why this replaces the Streamlit app

The existing `app.py` + `modules/` Streamlit app (kept in this repo unmodified, see
`legacy/`) proved the core loop works: read a folder, don't repeat a photo, call
OpenAI for copy, call OpenAI for images, log the result. It has real limits that this
rebuild fixes:

- **No structured campaign memory.** History is a flat JSON log (`data/campaign_log.json`),
  not a relational model, so there's no way to query "which angle have I overused" or
  compare campaigns for similarity beyond "was this exact photo used."
- **No research provenance.** Trend claims come from model memory with no citations.
- **No brand workspace concept.** One `.env` = one brand.
- **No job/progress model.** A Streamlit script blocks synchronously; a 6-slide carousel
  either finishes or the whole request is lost.
- **No structured outputs.** AI responses are consumed as prose, not validated schemas.
- **Model names hardcoded in `modules/image_studio.py` and similar.** The brief requires
  every model name to be configuration, not code.

None of this is a criticism of the old app for what it was (a fast personal MVP) — it's
the reason a proper backend/frontend split with a real database is worth building now.

## 2. High-level shape

```
┌─────────────────────────────┐        ┌──────────────────────────────────┐
│   Frontend (React + Vite)    │◄──────►│   Backend (FastAPI, Python)       │
│   TS, Tailwind, TanStack      │  REST  │   SQLAlchemy + Alembic + SQLite   │
│   Query, RHF + Zod             │  JSON  │   (WAL mode)                      │
└─────────────────────────────┘        │                                    │
                                         │  ┌──────────────────────────────┐ │
                                         │  │ Services                     │ │
                                         │  │  - RepositoryScanner         │ │
                                         │  │  - FingerprintEngine         │ │
                                         │  │  - ResearchOrchestrator      │ │
                                         │  │  - CampaignOrchestrator       │ │
                                         │  │  - CreativePipeline (Pillow +│ │
                                         │  │    Playwright renderer)      │ │
                                         │  │  - JobRunner (async, DB-backed)│
                                         │  └──────────────────────────────┘ │
                                         │  ┌──────────────────────────────┐ │
                                         │  │ Provider abstraction          │ │
                                         │  │  AIProvider / ResearchProvider│ │
                                         │  │  / ImageProvider / Publishing │ │
                                         │  │  Provider — OpenAI impl. first│ │
                                         │  └──────────────────────────────┘ │
                                         └────────────────┬───────────────────┘
                                                            │
                                        reads only ─────────┼───── writes
                                                            ▼
                                  SOURCE_ASSET_ROOT (read-only)   OUTPUT_ROOT
                                  C:\Marketing\Source              C:\Marketing\Generated
```

Single-user, local-first, single SQLite file (`backend/data/app.db`, WAL mode). No
Redis/Kafka/Celery/microservices — a FastAPI process plus a Vite dev server (or a
built static bundle FastAPI serves) is the entire runtime.

## 3. Backend layout

```
backend/
  app/
    main.py                 FastAPI app, router registration, CORS, startup (DB init)
    config.py                Settings (pydantic-settings): paths, model names, thresholds
    db.py                    Engine/session factory, WAL pragmas
    models/                  SQLAlchemy ORM — one module per aggregate (see data-model.md)
    schemas/                 Pydantic schemas: API I/O + AI structured-output contracts
    services/
      scanner.py              Repository scanning, hashing, metadata extraction
      fingerprint.py           Perceptual-hash + text-similarity duplicate detection
      prompts.py               Prompt template loader/versioner (backend/app/prompts/*.md)
      jobs.py                   DB-backed async job runner
      ai/
        base.py                  AIProvider / ResearchProvider / ImageProvider Protocols
        openai_provider.py       OpenAI Responses API + image API implementation
      research/                (Phase 5 — done) research orchestration
        openai_research.py      TTL-cached wrapper around ResearchProvider.research();
                                 drops any insight with no source_urls before persisting
      creative/                (Phase 6 — done) hybrid creative pipeline
        background.py            Background isolation (NoOp always available; optional rembg)
        compositor.py            Pillow: brand-color gradient background + product compositing
        templates.py             Template registry (HTML/CSS builder) + platform pixel formats
        renderer.py              Playwright: renders a template to an exact-size PNG, plus
                                  real DOM diagnostics (text overflow) for QA
        qa.py                    Automated QA: file integrity, exact dimensions, text overflow,
                                  logo presence
        pipeline.py              render_slide(...) ties the above together; DB-agnostic, so
                                  it's callable today without an orchestrator or an API key
    api/
      routers: brands, categories, products, assets, repositories, research,
                campaigns, opportunities, jobs, analytics, settings, search
    prompts/                 Versioned prompt templates (see section 9)
  alembic/                  Migrations
  tests/
  requirements.txt
  .env.example
```

### Config — no hardcoded model names anywhere

`app/config.py` loads a single `Settings` object (pydantic-settings) from `.env`,
persisted/overridable from the Settings UI via the `settings` table (DB values win over
`.env` when present, so the UI can change them without restarting with new env vars).

```
OPENAI_API_KEY=
OPENAI_RESEARCH_MODEL=gpt-5.1
OPENAI_CAMPAIGN_MODEL=gpt-5.1
OPENAI_VISION_MODEL=gpt-5.1
OPENAI_IMAGE_MODEL=gpt-image-1
SOURCE_ASSET_ROOT=C:\Marketing\Source
OUTPUT_ROOT=C:\Marketing\Generated
DATABASE_URL=sqlite:///./data/app.db
TREND_RESEARCH_TTL_HOURS=24
CATEGORY_RESEARCH_TTL_HOURS=168
```

Service code never references a model string literal; every AI call reads
`settings.openai_campaign_model` etc. This is enforced by convention + a grep-based
lint check documented in `docs/campaign-pipeline.md`.

### Provider abstraction

```python
class AIProvider(Protocol):
    async def generate_structured(self, *, system: str, user: str, schema: type[BaseModel],
                                   model: str) -> BaseModel: ...
    async def vision_describe(self, *, image_path: Path, prompt: str, model: str) -> str: ...

class ResearchProvider(Protocol):
    async def research(self, query: ResearchQuery) -> ResearchResult: ...

class ImageProvider(Protocol):
    async def generate(self, *, prompt: str, size: str, reference_images: list[Path] | None,
                        model: str) -> bytes: ...
    async def edit(self, *, base_image: Path, mask: Path | None, prompt: str, model: str) -> bytes: ...

class PublishingProvider(Protocol):
    async def publish(self, *, target: PublishTarget, assets: list[Path], copy: PublishCopy) -> PublishResult: ...
```

`app/services/ai/openai_provider.py` implements the first three today using the OpenAI
Responses API (structured outputs via `response_format`/Pydantic schema) and the image
API. `PublishingProvider` (sections 47/48 of the brief) now has its first concrete
implementation too: `app/services/publishing/meta_provider.py::MetaPublishingProvider`,
covering Facebook Page + Instagram via Meta's Graph API — see section 5i below. A
second connector (Pinterest, etc.) can register against the same Protocol later
without touching campaign logic.

Business logic (services, API routes) only ever imports the Protocol types, never
`openai` directly — the OpenAI SDK is confined to `openai_provider.py`.

## 4. Frontend layout

```
frontend/
  src/
    api/            fetch client + TanStack Query hooks, one module per resource
    pages/          Overview, Library (real thumbnails), Settings, Brands,
                     StrategyLibrary, Defense, Campaigns, CampaignDetail (real
                     creative-render panel + Run Autopilot + community drafts),
                     Research (real, cited research runs), Opportunities (real,
                     cited community discovery), (stubs for Calendar/Analytics)
    components/     shared UI (Tailwind, lucide-react icons; shadcn-style primitives
                     hand-rolled to avoid a CLI dependency, same visual language)
    lib/            small utilities (formatting, query client)
    App.tsx         router
```

Desktop-first, minimum useful width ~1280px. No client-side business logic that
duplicates the backend (dedupe, fingerprinting, etc. always happen server-side).

## 5. Implementation status (update this table as phases land)

| Phase | Scope | Status |
|---|---|---|
| 1 — Foundation | DB schema (31 tables), config, FastAPI shell, settings API | **Done** |
| 2 — Library | Repository scanner, asset indexing, asset library API + UI | **Done** |
| 3 — Campaign memory | Campaign/fingerprint schema + similarity utilities | **Schema + utilities done; orchestrator not wired** |
| 3.5 — Strategy Library & Defense | 64 campaign archetypes across 8 families ("Campaign DNA"), rule-based competitor-response recommender | **Done** — full schema, seed data, API, and UI (Strategy Library + Defense pages) |
| 4 — AI | Provider abstraction + OpenAI implementation (structured outputs, vision) | **Interfaces + OpenAI implementation done; not yet called by an orchestrator** |
| 5 — Research | Research persistence models + live, cited research orchestration | **Done** — `services/research/openai_research.py`, TTL-cached, callable via `POST /api/research/run` and the Research Radar page. Only cited insights are ever persisted. |
| 6 — Creative engine | Templates, compositing, Playwright rendering, automated QA | **Done** — `services/creative/`, one template ("Premium Product Hero"), 3 platform formats, callable today via `POST /api/campaigns/{id}/slides/render` and a real Campaign Detail preview panel. AI-generated backgrounds are wired to `ImageProvider`, opt-in via `use_ai_background` — see section 5h below. Full photo recreation (the AI actually redraws the product photo into a new scene, not just the backdrop behind it) is now also wired, on by default for Autopilot — see section 5o. As of round 16, a full recreation now bakes the slide's actual marketing text into the graphic itself (matching the style of the user's own inspiration ads) instead of always drawing it as a separate HTML layer — see section 5q. |
| 7 — Autopilot | Orchestration, jobs, resume/retry | **Done** — `services/orchestrator.py`'s `run_autopilot(...)` runs research → strategy candidates → novelty filter → copy → carousel plan → creative render end to end for a real campaign, exposed via `POST /api/campaigns/{id}/generate`. See section 5d below. The carousel planner's slide count can now be pinned exactly via `Campaign.target_slide_count`, editable any time on Campaign Detail — see section 5q. |
| 7.5 — Campaign Builder advanced mode | Partial Autopilot runs (Strategy Only / Copy Only / Visuals Only) | **Done** — the same pipeline as Phase 7, decomposed into three independently callable stages (`run_strategy_stage`/`run_copy_stage`/`run_visuals_stage`), each resumable from the prior stage's persisted output. See section 5g below. |
| 8 — Opportunities | Discovery, community DB | **Done** — `services/opportunities.py`, web-search-grounded, only cited communities persisted, callable via `POST /api/opportunities/discover` and a real Opportunities page; manual campaign-community draft workflow on Campaign Detail. See section 5e below. |
| 9 — Performance | Calendar, publications, analytics, feedback loop | **Done** — `services/analytics.py` + `api/publishing.py`/`api/analytics.py`, publications and manually-entered metrics feed a real engagement-rate breakdown, top-campaigns ranking, and a calendar view, and close the loop back into Autopilot's strategy-type selection. See section 5f below. Metrics can now also sync automatically from Meta's own Insights API instead of always being typed in — see section 5l. |
| 10 — Polish | Onboarding, README, scripts, tests | **Done** — README/scripts/core tests, plus a real 4-step onboarding wizard (`pages/Onboarding.tsx`) and a structured Brand style editor (colors as key→swatch→hex, tag editors for visual-style/forbidden-style descriptors) replacing the earlier comma-separated text fields. |
| 47/48 — Publishing connectors | Real auto-posting to social platforms via `PublishingProvider` | **Done for Facebook Page + Instagram** — `services/publishing/meta_provider.py::MetaPublishingProvider`, callable via `POST /api/campaigns/{id}/publish`. See section 5i below. Facebook Groups remain manual by Meta's own platform rule, not a gap here. |

This is a genuinely large system (the brief itself lists 68 sections, plus a follow-up
campaign-strategy/defense addendum). Across sixteen build rounds this repo now delivers
Phase 1–2 in full, the complete Strategy Library and Defense engine (3.5), the
Phase 6 creative pipeline (including opt-in AI-generated backgrounds, per-photo
vision-model product-zone detection, full AI photo recreation plus a
brand-level Inspiration Library of example ads/posts/carousels, and now
AI-baked-in marketing text with a user-controlled carousel length, sections
5h/5j/5o/5q), Phase 5 research orchestration, the Phase 7 Autopilot orchestrator
(plus its 7.5 advanced-mode split, now background-job-backed and non-blocking
end to end — section 5k), Phase 8 opportunity discovery, the Phase 9
calendar/analytics/performance feedback loop (now with an automated Meta
Insights sync path alongside manual entry — section 5l), real Facebook
Page/Instagram auto-publish (sections 47/48, section 5i below), and
self-applying database migrations on startup (section 5p), on a schema built
for all these phases, so every later round has been additive rather than a
rewrite. Every phase from the original build order, plus every item from the
most recent five-item polish round, is now implemented — see
`docs/campaign-pipeline.md`'s "What's left" section for the short list of
genuinely optional work that remains (mainly a second `PublishingProvider`
connector beyond Facebook/Instagram).

## 5a. The Strategy Library and Defense engine

Two additions beyond the original 68-section brief, requested as a follow-up:

- **Strategy Library**: `backend/app/data/strategy_library.py` seeds 64 campaign
  archetypes ("Campaign DNA" — objective, trigger, audience, psychology, offer,
  channels, content types, duration, budget notes, success metrics) organized into 8
  families (ATTACK/ACQUIRE/CONVERT/RETAIN/BRAND/HYPE/COMMUNITY/DEFENSE). It's real,
  queryable data (`campaign_strategy_families`/`campaign_strategy_types` tables), not
  a hardcoded UI list — `app/services/seed.py` upserts it by key on every startup, so
  editing the data file updates the catalog without duplicating rows. The frontend's
  Strategy Library page browses it and can create a real (IDEA-status) campaign
  against a chosen type.
- **Defense engine**: `competitors`/`competitor_events`/`defense_playbooks` tables +
  `app/services/defense.py`'s `recommend_response()` — a deliberately plain,
  inspectable rule engine (not an AI call) that matches a logged competitor event
  against playbooks and returns ranked Strategy Library recommendations with a visible
  rationale. This is the "detect → analyze → recommend a specific response" mechanic
  from the brief's Defense-family addendum, distinguishing it from spontaneously
  launching an ATTACK campaign. See `docs/campaign-pipeline.md` for how this plugs into
  the future Autopilot orchestrator.

## 5b. The creative pipeline (Phase 6)

Built as a third round of work, after the Strategy Library/Defense addition. Lives
entirely under `backend/app/services/creative/` and is deliberately DB-agnostic — see
`docs/campaign-pipeline.md`'s "Hybrid creative pipeline" section for the step-by-step
design and `tests/test_creative.py` for the 21 tests covering it (compositor pixel
behavior, template HTML escaping, the Playwright renderer's real DOM overflow
diagnostics, automated QA, and the end-to-end pipeline including a source-immutability
guard identical in spirit to `test_source_immutability.py`).

What's real today: given a real product photo (an `Asset` row), brand colors, and
plain text fields, `render_slide(...)` produces a pixel-exact PNG at an Instagram/
Facebook format (1080×1080, 1080×1920, or 1200×630) with the actual product photo
composited onto a deterministic brand-color gradient by default (or an AI-generated
scene when `use_ai_background=true` — section 5h), real HTML/CSS text laid out by
a template and rendered via headless Chromium (Playwright), and an automated QA
report (file integrity, exact dimensions, text-overflow via real DOM measurement,
logo presence). None of this requires an OpenAI API key unless AI backgrounds are
explicitly turned on — the gradient path is untouched and still needs nothing.
As of round 15, there is a third option beyond "gradient" and "AI backdrop behind
the untouched photo": full AI recreation, where the product photo itself is
redrawn into a brand-new scene by the model. It is on by default for Autopilot
runs — see section 5o for why that image path exists and how it composes with
(and takes priority over) `use_ai_background`.

`POST /api/campaigns/{id}/slides/render` exposes this today as a manual, per-slide
action — pick a photo, write the text, render — from a real Campaign Detail page.
This is intentionally a different endpoint from `/generate` (see section 5d): `/generate`
is the Autopilot orchestrator's automatic research→strategy→copy→creative run, while
`/slides/render` is the lower-level creative-only capability that orchestrator calls
internally (both now share the same `resolve_brand_colors`/`resolve_brand_logo_path`
helpers, defined once in `services/orchestrator.py`, so the manual and automatic paths
can't drift). Also added in this round: a real `GET /api/assets/{id}/image` endpoint,
since the Library page had never actually rendered a preview of an indexed photo — it
now shows real thumbnails.

## 5c. Research orchestration (Phase 5)

Built as a fourth round of work, after the creative pipeline. `services/research/
openai_research.py`'s `run_research(...)` is a thin, DB-agnostic orchestration layer
around `ResearchProvider.research()`: it checks `find_fresh_research_run` for a
non-expired `ResearchRun` in the exact brand/category/product scope before calling
the provider at all (so repeat campaigns in the same category within
`TREND_RESEARCH_TTL_HOURS`/`CATEGORY_RESEARCH_TTL_HOURS` don't re-bill a research
call), and on a cache miss persists `ResearchSource` rows first, then
`ResearchInsight` rows — but only for insights the model attached at least one
source URL to. An uncited insight is dropped before it can ever become a
`research_insights` row; a `ResearchRun` is still recorded even if every insight
gets filtered out, so a "nothing came back cited" outcome is visible rather than
looking like the step never ran.

`POST /api/research/run` exposes this today from the Research Radar page — pick a
brand (and optionally a category/product), an objective, and it runs a real,
web-search-grounded OpenAI call and shows the cited insights with clickable source
links. It 400s with a clear message if no OpenAI key is configured, rather than
returning anything fabricated. `tests/test_research.py` verifies all of the caching
and no-fake-research logic against a `FakeResearchProvider` implementing the same
Protocol as `OpenAIProvider` — none of it needs a real network call or API key to
verify.

## 5d. The Autopilot orchestrator (Phase 7)

Built as a fifth round of work, after research orchestration. `services/
orchestrator.py`'s `run_autopilot(db, campaign_id=..., ai_provider=..., research_
provider=..., renderer=..., config=...)` is what makes `POST /api/campaigns/{id}
/generate` real — it ties together every piece built in prior rounds rather than
inventing new AI plumbing:

1. Loads the campaign/brand/category/product rows and rejects anything not in
   `IDEA`/`FAILED` status (a running or already-reviewed campaign can't be
   re-generated out from under itself).
2. Picks candidate source photos — active assets in scope, least-used first — and
   fails clearly (marking the campaign `FAILED`) if none exist, rather than
   generating a campaign with no real photo to render.
3. Locks a Strategy Library type: if the campaign already has one (a manual
   Strategy Library pick, or a Defense recommendation — see section 5a), that
   choice is respected and never overridden; otherwise it picks the type used
   least often for this brand/category scope.
4. Calls `run_research(...)` (section 5c, unchanged) — a fresh cache hit means no
   new billed call.
5. Generates 2-3 `CampaignStrategy` candidates in one `AIProvider.generate_
   structured` call (wrapped in a `CampaignStrategyCandidates` schema), grounded in
   the cited research insights and brand rules.
6. Fingerprints each candidate (`services/fingerprint.py`, unchanged) against every
   prior campaign in the same brand/category scope and discards anything
   `EXACT_REPEAT`/`TOO_SIMILAR`; if every candidate is rejected, the campaign is
   marked `FAILED` with a clear message instead of silently accepting a repeat.
7. Generates a `CreativeBrief`, then `CampaignCopy`, then a `CarouselPlan` from the
   accepted strategy.
8. Renders every planned slide through the existing `services/creative/pipeline.py`
   `render_slide(...)` (section 5b, unchanged) — clearing any slides/QA reports left
   over from a previous failed attempt first, so a retry never accumulates
   duplicates — and persists a `CampaignFingerprint` for future novelty checks
   (upserted, so a retry updates the one row rather than violating its
   `campaign_id` uniqueness constraint).
9. Sets the campaign to `REVIEW` and records `audit_events` at every major step.

Runs synchronously within the HTTP request via `services/jobs.py`'s `run_job(...)`
(awaited directly, not fire-and-forget) — a `Job` row is still created and its
`progress`/`step` updated throughout, so the job-tracking design doesn't need to
change if a future job type wants the fire-and-forget `run_job_in_background(...)`
path instead; a single local user watching a spinner for the run's duration was a
reasonable trade against building job-polling UI before anything needed it.

`tests/test_orchestrator.py` covers the happy path (reaching `REVIEW` with rendered
slides and a persisted fingerprint), the no-candidate-photos failure, the
all-candidates-rejected failure, the status guard, a `strategy_type_id` set by the
Strategy Library or Defense being respected rather than overridden, and a retry
after `FAILED` not duplicating slide rows — all against a `FakeAutopilotProvider`
implementing the same `AIProvider`/`ResearchProvider` Protocols as `OpenAIProvider`,
so none of it needs a real network call or API key. `tests/test_api.py` adds an
HTTP-level end-to-end test over the same fake, monkeypatched into `app.api.campaigns`.

The frontend's Campaign Detail page has a "Run Autopilot" action above the manual
render panel — enabled only when the campaign is `IDEA`/`FAILED`, and showing the
job's outcome (or error) once it returns.

## 5e. Opportunity discovery (Phase 8) — the "find me Facebook Groups" ask

Built as a sixth round of work, right after the Autopilot orchestrator. This is a
direct answer to the original brief's "find me places to post like Facebook
groups" — and to the platform reality that no third-party app, this one included,
can auto-post into a Facebook Group it doesn't administer (Meta's Graph API
structurally disallows it — this isn't a gap in the app, it's a Meta policy).
So the feature does the two things that actually are possible: find real,
verifiable communities, and draft a post tailored to each one, leaving the
human to actually post it.

`services/opportunities.py`'s `run_opportunity_discovery(...)` calls a new
`ResearchProvider.discover_opportunities(query, model=...)` method (added to the
Protocol alongside `research()`, reusing the `ResearchQuery` schema rather than
inventing a parallel one) — implemented in `OpenAIProvider` as a web-search-
grounded `responses.parse()` call, same pattern as `research()`. The "no fake
research" discipline applies identically here: an `OpportunityRecommendation`
without at least one `source_urls` entry is dropped before it's ever persisted —
an invented Facebook Group name is exactly the failure mode this exists to
prevent. Unlike `ResearchRun` (append-only, TTL-cached), opportunity discovery
*upserts*: a repeat discovery for the same brand/category matches existing
`Opportunity` rows by `(brand_id, platform, name)` and refreshes them (relevance,
posting rules, `last_checked_at`) instead of creating duplicates — so re-running
discovery doesn't pollute the list with the same group over and over.

`POST /api/opportunities/discover` exposes this (400s without an OpenAI key, same
pattern as `/research/run`); `GET /api/opportunities` lists discovered communities
(excluding blocked ones); `PATCH /api/opportunities/{id}` tracks the manual
workflow — `joined_status` (not_joined/requested/joined/rejected), `favorite`,
`blocked`, `notes` — entirely client-side bookkeeping, no Meta API involved. The
Opportunities page (no longer a stub) lets a user pick a category, discover, and
manage that list.

Tying it to campaigns: `POST /api/campaigns/{id}/opportunities` attaches a
discovered `Opportunity` to a `Campaign` (via the pre-existing `CampaignOpportunity`
join table) and generates a default draft post from the campaign's hook/main
promise/CTA — appending a note to lead with value instead of a hard sell when
`promo_allowed` is `false`. `PATCH /api/campaigns/{id}/opportunities/{co_id}`
lets the user edit that draft and mark it `posted` (bumping the `Opportunity`'s
`last_posted_at`). The Campaign Detail page's new "Community drafts" panel is the
UI for this — pick a discovered community, get an editable draft, copy/paste it
into the actual group yourself, mark it posted.

`tests/test_opportunities.py` covers the uncited-recommendation drop, the
upsert-not-duplicate behavior on repeat discovery, the discover/list/update API
endpoints (via a `FakeOpportunityProvider` implementing `discover_opportunities`,
same fake-provider pattern as research and Autopilot), and the campaign-attach ->
edit -> mark-posted flow end to end.

## 5f. Calendar, analytics, and the performance feedback loop (Phase 9)

Built as a seventh round of work, right after opportunity discovery — the last
unbuilt phase, closing the loop diagram's final arrow (`DISTRIBUTION TRACKING →
PERFORMANCE → (feeds back into) STRATEGY`, `docs/campaign-pipeline.md`'s "The
loop"). Nothing about the schema changed here: `publications`/`performance_
metrics`/`performance_insights` were already modeled in Phase 1; this round is
purely the application code and UI against tables that had sat unused.

**Publications.** `POST /api/campaigns/{id}/publications` (guarded to campaigns
already `APPROVED`/`EXPORTED`/`SCHEDULED`/`PUBLISHED` — logging a publication
against an unreviewed `IDEA` campaign is refused) creates a `Publication` row;
`GET /api/campaigns/{id}/publications` lists them for that campaign. From there,
`app/api/publishing.py` owns the resource: brand-scoped listing with status/
provider filters, and `PATCH /api/publications/{id}` to update status/url/
external_post_id — setting `status="published"` also bumps the parent `Campaign`
to `PUBLISHED` and stamps `published_at` (mirroring the same side effect the
campaign-scoped create endpoint applies when a publication is created already
`published`), so campaign status is always the most-advanced known reality
regardless of which endpoint touched it last.

**Performance metrics.** `POST /api/publications/{id}/metrics` adds a
`PerformanceMetric` snapshot; `source` is always `"manual"` today (no ad-platform
API integration exists), which is a deliberate, honest default rather than a
placeholder — see the build-order note below on where an automated connector
would plug in without any schema change.

**The math, `services/analytics.py`.** `engagement_rate(metric)` computes
`(likes+comments+shares+saves) / (reach or impressions)`, returning `None`
(never `0`) when neither denominator was recorded — a metric snapshot with no
reach data can't produce a rate, and treating that as zero would understate it
rather than admit it isn't computable. `performance_summary(db, brand_id,
days=90)` (exposed as `GET /api/analytics/performance`) aggregates totals, a
per-strategy-type breakdown (campaigns measured, average engagement rate, total
revenue/sales), and the top 5 campaigns by revenue — every number a straight
sum/average over rows a human actually entered, never modeled or predicted.
`average_engagement_rate_for_strategy_type(db, brand_id, strategy_type_id)` is
the piece that actually closes the loop: `services/orchestrator.py`'s
`_select_underused_strategy_type` (section 5d) now uses it as a tie-breaker among
equally-underused Strategy Library types — usage count is still the primary
sort key (so one family still can't dominate every campaign just because it
converts well, per section 5a), and a type with zero recorded metrics
contributes `0.0` rather than being penalized relative to a measured one.

**Calendar.** `GET /api/analytics/calendar` (brand_id, year, month) returns
campaigns with a `published_at` in that month, grouped by day — matching the
Calendar page's list-grouped-by-date view (a calendar-grid widget was considered
and deliberately skipped; "what went out when" is the useful question here, not
a visual grid).

**Frontend.** Campaign Detail gained an "Approve" button for `REVIEW`-status
campaigns (the backend `/approve` endpoint already existed from an earlier round
but had never been called from the UI — a real gap, now closed) and a
"Publishing" panel for `APPROVED`+ campaigns to log publications and attach
metric snapshots inline. `Analytics.tsx` and `Calendar.tsx` replace the earlier
`ComingSoon` stubs entirely (that component and its "Phase 9" nav badges are now
gone) with real pages against the endpoints above.

`tests/test_publishing.py` covers the publication-creation status guard, list/
create/patch over real HTTP, the published-status campaign-bump side effect,
metric add/list, `performance_summary` aggregation (totals, top campaigns), the
calendar endpoint's day-grouping, and — the piece that actually proves the loop
closes — a direct unit test of `_select_underused_strategy_type` showing it
picks the higher-recorded-engagement type when two Strategy Library types are
otherwise tied on usage count.

## 5g. Campaign Builder advanced mode (Phase 7.5)

Built as an eighth round of work — the last item from the original build order.
`POST /api/campaigns/{id}/generate` ("Everything") always ran the full pipeline in
one shot; this round splits it into three independently callable stages so a user
can generate just a strategy, just copy, or just visuals, matching the brief's own
"Generate Strategy Only / Copy / Visuals / Everything" framing.

`services/orchestrator.py`'s single `run_autopilot` function was decomposed into
`run_strategy_stage` (steps 1-9, ends at a new `BRIEF_READY`), `run_copy_stage`
(steps 10-12, ends at a new `COPY_READY`), and `run_visuals_stage` (steps 13-15,
ends at `REVIEW`) — a behavior-preserving refactor: `run_autopilot` now simply
calls the three in sequence, and every pre-existing orchestrator/API test passed
unchanged before a single new test was added, confirming "Everything" mode's
result is identical to before the split.

The mechanism that makes each stage independently callable — possibly in a
completely separate HTTP request, even a different day — is that each one
persists its structured output as a JSON file under `OUTPUT_ROOT/<brand>/
<category>/<year>/<year-month>/<campaign>/brief/{strategy,copy,creative}.json`
(the same deterministic-folder convention already used for rendered slides and QA
reports, just under a new `brief/` subfolder), tracked by a `CampaignOutput` row
per kind. A later stage reads the prior one's file back (`_load_stage_json`)
instead of needing the data handed to it directly, which is also what makes each
stage's precondition an artifact check rather than a status check:
`run_copy_stage` and `run_visuals_stage` 400 with a specific, actionable message
("Run the Strategy stage for this campaign before generating copy...") when the
prior stage's output doesn't exist yet, rather than gating on a specific campaign
status — so, notably, Copy can be regenerated later even after Visuals has
already produced a `REVIEW`-ready campaign (to try different copy without
re-rendering), and Visuals can be re-run later without resetting anything else
(e.g. after adding new photos). `run_strategy_stage` is the one exception, keeping
the original `IDEA`/`FAILED` status guard, since re-picking a strategy after
copy/visuals already committed to a different angle would orphan those artifacts.

One genuinely useful property falls out of the split: `run_visuals_stage` needs
**no OpenAI key at all** — it only reads back already-generated copy/carousel-plan
JSON and composites real photos, exactly like the manual `/slides/render`
endpoint. A user can spend AI budget iterating on strategy and copy, then render
without a key configured (or with the key removed entirely, which
`tests/test_api.py`'s advanced-mode test verifies directly).

Exposed as `POST /api/campaigns/{id}/generate/strategy`, `.../generate/copy`, and
`.../generate/visuals` in `app/api/campaigns.py`, each following the identical
Job-creation/`OpenAIProvider`-construction/error-handling pattern already
established by `/generate` (a small set of shared helpers —
`_require_campaign`/`_require_openai_key`/`_require_output_root`/
`_build_autopilot_config` — keep the four endpoints from duplicating that
boilerplate four times over). `tests/test_orchestrator.py` adds direct tests of
each stage running standalone, the copy/visuals precondition guards raising the
right message, all three stages run as separate calls reaching the same end state
as `run_autopilot`, and that re-running Copy after Visuals has already completed
doesn't revert campaign status backward. `tests/test_api.py` adds an HTTP-level
test calling all three endpoints in sequence.

The frontend's Campaign Detail page gained an "Advanced mode" card beneath the
existing "Run Autopilot" button, with three buttons (Strategy only / Copy only /
Visuals only) each showing its own pending/error/success state and surfacing the
backend's exact guard message on failure rather than trying to predict client-side
whether a prior stage has run.

## 5h. Brand visual style & AI-generated backgrounds (Phase 6 extension)

Two pieces built together in this round, because they share the same underlying
asset — a brand's own uploaded reference photos:

**Brand assets got real endpoints for the first time.** `BrandAsset` (kind: logo /
font / visual_reference) has existed in the schema since Phase 1, and
`resolve_brand_logo_path` has looked for a logo on every render since Phase 6, but
there was never a way to actually create one — a brand's logo has never once
appeared on a rendered creative in this app until now. `app/api/brands.py` gained
`POST /api/brands/{id}/assets` (multipart upload — file + kind + optional label,
written under `OUTPUT_ROOT/_brand_assets/<brand>/<kind>/`), `GET .../assets`
(optional `?kind=` filter), `GET .../assets/{asset_id}/file` (a resized JPEG
preview, same pattern as `GET /api/assets/{id}/image`), and `DELETE
.../assets/{asset_id}`. The frontend's new Brand Detail page (`/brands/{id}`) is
the real UI: upload/replace a logo, upload/remove visual-reference photos, and
edit the brand's voice/colors/visual-style/forbidden-styles text fields.

**Visual-reference photos can now reach the AI, two ways:**

1. `POST /api/brands/{id}/visual-style/analyze` — a new `AIProvider.
   analyze_visual_style(image_paths, brand_name, model)` method sends every
   uploaded reference photo to the vision model in one call and returns a
   structured `BrandVisualStyleAnalysis` (dominant colors, typography mood,
   photography style, descriptors, a voice suggestion). This is a proposal only —
   it never writes to the brand; Brand Detail shows it and an "Apply to form
   below" action copies it into the editable fields, which still need an explicit
   Save (`PATCH /api/brands/{id}`), keeping human approval authoritative over the
   brand's own style the same way it is over every other AI output in this app.
2. `use_ai_background=true` on `POST /api/campaigns/{id}/generate`,
   `.../generate/visuals`, and `POST /api/campaigns/{id}/slides/render` — routes
   each slide's background through the new `services/orchestrator.py::
   generate_ai_background(...)`, which builds a prompt from the brand's own
   configured style fields and calls `ImageProvider.generate(...,
   reference_images=[...])` with up to 3 of the brand's visual-reference photos
   attached as a live style reference. This also fixes a real, previously-silent
   gap: `reference_images` was declared on the `ImageProvider` Protocol since
   Phase 1 but `OpenAIProvider.generate()` never actually used it — passing it
   changed nothing about what got generated. It now routes to the Images **edit**
   endpoint (`images.edit` with `image=[...]`, which gpt-image-1 accepts more
   than one of) instead of plain `images.generate` whenever reference images are
   given.

Off by default everywhere it's exposed, so nothing about existing behavior changes
unless a user opts in — including the "Visuals only needs no OpenAI key" property
from section 5g. `generate_ai_background` returns `None` on any failure (bad key,
rate limit, malformed bytes) rather than raising, and every caller falls back to
the gradient — an AI-generated background is a nice-to-have layered on a pipeline
that has always worked without one, and its failure must never take down a render
that would otherwise have succeeded.

Tested in a new `tests/test_openai_provider.py` (direct unit tests of
`OpenAIProvider` against a fake `AsyncOpenAI` double — the one module in this
codebase every other test deliberately avoids exercising directly), new cases in
`tests/test_api.py` (brand asset CRUD, the analyze endpoint's guard paths and its
proposal-only behavior, the manual render endpoint's AI-background path), and new
cases in `tests/test_orchestrator.py` (the image provider getting called once per
slide with the right reference photos when enabled, a graceful fallback when it
raises, and the gradient staying the default when the flag is off).

## 5i. Facebook Page / Instagram auto-publish (sections 47/48)

`PublishingProvider` (`app/services/ai/base.py`) had existed since Phase 1 as an
explicitly documented extension point — "not implemented in this MVP" — the same
declared-but-empty shape as `BrandAsset`'s missing endpoints turned out to be in
section 5h. This round gave it its first concrete implementation:
`app/services/publishing/meta_provider.py::MetaPublishingProvider`, which is the
only module in the codebase allowed to talk to Meta's Graph API directly — the same
SDK/API isolation discipline `openai_provider.py` keeps for the `openai` package.

Two real, verified constraints from Meta's own developer documentation shape the
implementation, and they're genuinely different from each other:

- **Facebook Page photo post** (`POST /{page-id}/photos`) accepts the image as a
  direct multipart file upload. A locally rendered creative goes straight from
  `OUTPUT_ROOT` to Meta's servers — no public hosting needed.
- **Instagram's Content Publishing API** is a two-step flow (`POST /{ig-user-id}/
  media` to create a container with an `image_url`, then `POST /{ig-user-id}/
  media_publish` with the returned `creation_id`) and only accepts an `image_url`
  that *Meta's own servers fetch themselves* — there is no direct file-upload
  option for a still image. A locally rendered creative is therefore unreachable
  by Instagram unless it's exposed at a public URL first.

`PublishTarget` gained an optional `public_asset_url` field for exactly this case.
`app/api/campaigns.py`'s new `POST /{id}/publish` endpoint builds that URL (from a
newly-configurable `public_base_url` setting plus the existing `GET /{id}/slides/
{n}/image` endpoint's path) only when the provider is `instagram`; for
`facebook_page` it's left `None` and the concrete file is uploaded directly. When
Instagram is requested without a `public_base_url` configured, `_publish_
instagram_photo` returns a clear, actionable failure *before making any network
call* — never a confusing Graph API rejection.

New Settings fields (`facebook_page_id`, `facebook_page_access_token` — never
echoed back, same secrecy discipline as `openai_api_key` — `instagram_business_
account_id`, `public_base_url`) follow the existing runtime-settings pattern
(`.env` default in `config.py`, DB-overridable via `settings_store.py`). Getting
the actual token/IDs is a one-time manual setup against Meta's own developer
tools — documented step by step in the README's "Facebook Page / Instagram
auto-publish" section — and, because this app only ever posts to the account
owner's own assets, Meta's Standard Access in Development Mode is sufficient; the
heavier App Review process (required only to post on behalf of *other* people's
Pages) is not needed here.

On a successful publish, `POST /{id}/publish` creates a `Publication` row
(provider/external_post_id/url/status=published) and bumps the campaign to
`PUBLISHED` — the same side effect logging one manually already had, so the
Publishing panel and Analytics treat both paths identically. On failure, nothing
is recorded: a failed post attempt is not something that happened, and the real
Graph API error message is surfaced via a 502 rather than swallowed, mirroring
this app's consistent "no fake output" discipline elsewhere (uncited research
insights, uncited opportunity recommendations, manually-entered-only performance
metrics).

This does not change the Facebook Groups situation from section 5e — no app can
auto-post into a Group it doesn't administer, by Meta's own platform design, and
that stays a manual copy/paste from the drafted post on the Opportunities page.

Tested in a new `tests/test_meta_publisher.py` (direct unit tests of
`MetaPublishingProvider` against an `httpx.MockTransport` fake — no real network
call or token needed: the Facebook branch's real file bytes and caption, the
Instagram two-step flow's call order, the pre-flight failure when no public URL is
configured, and a Graph API error response becoming a clean `PublishResult`
failure) and new cases in `tests/test_api.py` (the endpoint's approval/
credential/rendered-slide guards, a successful publish creating a `Publication`
and bumping campaign status via a monkeypatched fake publisher, a failed publish
recording nothing, and the real `MetaPublishingProvider`'s Instagram-without-a-
public-URL failure exercised end to end with no monkeypatch).

## 5j. Vision-model product-zone detection (Phase 6 extension, round 11)

The one item from section 5b's "not built yet" list — a vision-model call to pick
the product zone per-photo instead of always using the template's fixed layout —
built as one piece of a five-item polish round the user explicitly asked for in
full (Meta Insights connector, this, non-blocking Autopilot, the Brand style
editor, and the onboarding wizard).

`schemas/ai.py` gained `ProductZoneDetection` (`crop_left`/`crop_top`/`crop_width`/
`crop_height` as fractions of the image in `[0,1]`, an `anchor: Literal["center",
"bottom", "top"]`, and a `reasoning` string), and `AIProvider` gained
`detect_product_zone(*, image_path, model) -> ProductZoneDetection`, implemented
in `OpenAIProvider` via `responses.parse(text_format=ProductZoneDetection)` with
the image sent as a base64 `input_image` block — the same structured-vision
pattern already used by `analyze_visual_style` (section 5h).

`services/creative/pipeline.py::render_slide` gained a `product_zone_detection:
ProductZoneDetection | None` field on `SlideCreativeInput`. When set, a new
`_crop_to_fraction_box(image, detection)` helper crops the isolated product image
to that fractional box (clamping at the image edges so a slightly-out-of-range
model response can't produce an empty or inverted crop), and the template's
`zone` is overridden via `dataclasses.replace(zone, anchor=detection.anchor)`
before compositing — everything else about the render (background, text layout,
QA) is unaffected. `SlideRenderResult.product_zone_detected: bool` reports whether
detection actually ran, shown on Campaign Detail as "· product zone auto-detected"
next to a render's info line.

`services/orchestrator.py` gained a standalone `detect_product_zone(*,
ai_provider, image_path, model)` wrapper following the exact same best-effort
pattern as `generate_ai_background` (section 5h) — it catches every exception and
returns `None` on any failure, so a bad key, malformed model response, or rate
limit falls back silently to the template's fixed zone rather than failing the
render. `AutopilotConfig` gained `detect_product_zone: bool = False` and
`vision_model: str = "gpt-5.1"`; `run_visuals_stage` calls the wrapper once per
slide, only when the flag is set and an `ai_provider` was passed in.

Exposed as a `detect_product_zone` query param on `POST /api/campaigns/{id}/
generate`, `.../generate/visuals`, and a same-named field on the manual `POST
/{id}/slides/render` request body — off by default everywhere, including on
Visuals-only, so its no-key property (section 5g) is unaffected unless a user
opts in. The frontend added matching checkboxes ("Auto-detect product zone") next
to the existing "Use AI-generated background" ones on Autopilot and the manual
render panel.

Tested in `tests/test_creative.py` (the crop-fraction math including edge
clamping, a full render with detection overriding the anchor, a render without
detection reporting `product_zone_detected: False`), `tests/test_orchestrator.py`
(`run_visuals_stage` calling the vision model once per slide when enabled,
falling back gracefully on failure, staying off by default), `tests/test_api.py`
(the manual render endpoint's `detect_product_zone` path), and
`tests/test_openai_provider.py` (`OpenAIProvider.detect_product_zone` against a
fake SDK client).

## 5k. Non-blocking Autopilot (Phase 7/7.5 extension, round 11)

Section 7's job engine had offered `run_job_in_background` since round 1, but
every `/generate*` endpoint used the blocking `run_job` instead — a deliberate
MVP trade-off (see section 7 and `docs/campaign-pipeline.md`'s "Job execution
model") that this round revisits now that Autopilot runs are long enough, and
frequent enough via the Advanced-mode stage buttons, to be worth a real polling
UI instead of a page that just spins.

`app/api/campaigns.py`'s four `/generate*` endpoints (`/generate`, `.../strategy`,
`.../copy`, `.../visuals`) now call `run_job_in_background(job.id, _job_fn)` and
return `{"job_id": job.id, "job_status": job.status}` immediately — the pipeline
itself (research, AI calls, rendering) now runs after the HTTP response has
already gone back, inside a fire-and-forget `asyncio.create_task`. This changes
error-surfacing semantics in one important way that had to be handled explicitly:
a validation failure that used to be a synchronous `400` inside the (now-removed)
blocking call would otherwise have silently become an asynchronous `Job.FAILED`
after the endpoint already returned `200` — a real UX regression, and one that
broke an existing test (`test_campaign_builder_advanced_mode_stage_endpoints`)
during this round's own development, which is exactly how it was caught.

The fix: `services/orchestrator.py` gained two small, synchronous, side-effect-free
functions — `check_copy_stage_prerequisite(db, campaign_id)` and
`check_visuals_stage_prerequisite(db, campaign_id)` — that do nothing but the
cheap, local "does the prior stage's output already exist" check `run_copy_stage`/
`run_visuals_stage` used to do inline, raising the identical `ValueError` message.
The API layer now calls these *before* queuing the job, so a mistake like clicking
"Copy only" before "Strategy only" still fails with an immediate `400`, exactly as
before this round — only work that genuinely can't be validated without actually
running the pipeline (an AI call failing, a render failing) surfaces
asynchronously via `Job.status="FAILED"` + `Job.error`, which is the correct place
for it regardless of blocking vs. background execution.

Frontend: `useJob(jobId)` (`api/hooks.ts`) polls `GET /api/jobs/{id}` via
TanStack Query's `refetchInterval` — a callback returning `1500` while the job's
status isn't terminal, and `false` (stop polling) once it is — and
`useInvalidateCampaignOnJobDone(job, campaignId)` invalidates the relevant
campaign/campaigns/assets/research-runs query keys exactly once per terminal job
via a `useEffect` + `useRef` dedup guard (TanStack Query v5 dropped `onSuccess`/
`onError` from `useQuery`, so this couldn't be done inline in the query itself).
`pages/CampaignDetail.tsx`'s `JobStatusLine` component renders the live step/
progress line while a job runs and the success/failure outcome once it's done,
shared by all four generate actions through an extended `StageButton` component.

Tested by rewriting `tests/test_api.py`'s two full-pipeline tests to assert
`job_status == "QUEUED"` on the initial response, poll a new `_wait_for_job`
helper until terminal, then fetch campaign state via a separate `GET` — proving
the endpoints are genuinely asynchronous now rather than just changing the
response shape while still blocking internally.

## 5l. Meta Insights connector (Phase 9 extension, round 11)

The performance connector explicitly deferred in section 5f and
`docs/campaign-pipeline.md`'s "What's left" list — `PerformanceMetric.source` had
existed as a column since Phase 1 specifically to support this, with every metric
so far written as `"manual"`. This is a read-back connector, genuinely separate
from the Facebook Page/Instagram *publishing* connector (section 5i): one posts
content, the other reads analytics back for content already posted (through this
app or otherwise, as long as a real `external_post_id` is on file).

`MetaPublishingProvider` (the same class from section 5i, so no new SDK/API
isolation boundary was needed) gained `fetch_metrics(*, provider, external_post_id)
-> MetricsFetchResult`, split into two tiers on purpose because they have
genuinely different reliability: the post/media's own like/comment counts via a
plain `fields` expansion (a long-stable part of the Graph API — a failure here
fails the whole sync), and the separate Insights edge for impressions/reach/
saves/shares (fetched best-effort, since Meta has repeatedly renamed and
deprecated metrics on this specific edge across API versions — a failure here
doesn't take down the stable counts already fetched). Only metrics the platform
actually returned end up in the result, matching this app's "no fake output"
discipline everywhere else — never filled in as `0` for something that wasn't
fetched.

`POST /api/publications/{id}/metrics/sync` (`app/api/publishing.py`) calls this
and writes a `PerformanceMetric` with `source="meta_sync"`. It's guarded to
`facebook_page`/`instagram` publications with a real `external_post_id` on file
(a manually-logged Group post has neither a supported provider nor a real post ID
to sync from) and a configured Page access token. The Publishing panel on
Campaign Detail gained a "Sync from Meta" button next to each eligible
publication's metrics list, and a "synced" badge on any metric row where
`source === 'meta_sync'`, so a synced number is always visually distinguishable
from one typed in by hand.

Tested with a fake HTTP transport in the existing `test_meta_publisher.py`-style
pattern plus new cases in `test_publishing.py`: a successful sync writing the
right fields with `source="meta_sync"`, the provider/external-post-id guards, and
the stable-fields-succeed-when-insights-fail split.

## 5m. Delete a campaign (round 13)

`DELETE /api/campaigns/{campaign_id}` (`app/api/campaigns.py`), returning `204`
on success. Requested directly by the user ("I would like to have an option to
be able to delete campaigns in case i created it wrong or just want to delete a
campaign for personal reasons") — the first destructive-by-design endpoint in
the app, so it got more deliberate treatment than an additive feature would:

- **409 guard against an in-flight job.** Before anything else, checks for a
  `Job` row for this campaign with `status` in `QUEUED`/`RUNNING` and refuses if
  one exists — deleting a campaign out from under a running Autopilot/stage job
  would just make that job fail confusingly trying to write to a campaign that
  no longer exists. Mirrors the synchronous-prerequisite-check pattern from
  section 5k (validate cheap local state before doing anything irreversible).
- **DB-level cascades do the heavy lifting.** Every table scoped to a campaign
  (`CampaignSlide`, `CampaignOutput`, `CampaignFingerprint`, `CampaignAsset`,
  `CampaignVariant`, `Publication` → transitively `PerformanceMetric`,
  `CampaignOpportunity`) already declares `ForeignKey("campaigns.id",
  ondelete="CASCADE")` or an ORM-level `relationship(..., cascade="all,
  delete-orphan")`; `db.delete(campaign)` triggers all of them in one commit.
  This only works because `app/db.py`'s engine already sets `PRAGMA
  foreign_keys=ON` on every connection — SQLite has FK enforcement off by
  default per-connection, and without that pragma the DB-level `ondelete`
  clauses would be silent no-ops (see the `conftest.py` fix below).
- **Real files aren't part of any cascade** — a deleted DB row doesn't delete
  the file it pointed at. The endpoint collects every `rendered_asset_path` /
  `generated_background_path` off the campaign's slides and every `file_path`
  off its outputs *before* deleting the rows, then best-effort
  `Path(...).unlink(missing_ok=True)`s each one wrapped in `try/except
  OSError: pass` — a locked or permission-denied file skips rather than
  blocking the DB delete, same discipline this app already applies elsewhere to
  "don't crash on a missing/locked file."
- **`SOURCE_ASSET_ROOT` is never touched.** The endpoint only ever deletes
  files under `OUTPUT_ROOT` (the campaign's own generated output) — never a
  source photo, which may be reused by other campaigns and is read-only by
  design everywhere else in this app (section 6).
- **`Job` rows for this campaign are cleaned up too**, even though
  `Job.campaign_id` is intentionally a plain `String`, not a real foreign key
  (see section on `platform.py` models / `docs/data-model.md`) — kept
  non-cascading elsewhere so job history can outlive a campaign for
  tidiness/debugging reasons, but a *deleted* campaign shouldn't leave a
  phantom job entry behind, so this endpoint deletes them explicitly.
  `Opportunity` rows are the opposite case: never touched, since a discovered
  community isn't scoped to any one campaign (only its `CampaignOpportunity`
  join-row is, and that cascades).
- **An `AuditEvent`** (`entity_type="campaign"`, `action="deleted"`) is written
  before the delete, using the generic `entity_type`/`entity_id` string columns
  that table already uses specifically so an audit trail survives deletion of
  its subject.
- Allowed from any campaign status, including `PUBLISHED` — this is a real
  action the user explicitly asked for with no ambiguity about wanting it to be
  permanent ("for personal reasons"); confirming intent is the frontend's job
  (a `window.confirm()` naming exactly what will be lost), not this endpoint's
  job to second-guess by restricting which statuses can be deleted.

**Frontend:** a `Trash2`-icon "danger"-variant `Button` (new `variant: 'danger'`
on the shared `Button` component) on both the Campaigns list — each row now
renders through a new `CampaignRow` subcomponent instead of an inline `.map()`,
because a per-row delete needs its own `useMutation` call and React's rules of
hooks don't allow a hook call site inside a callback whose invocation count
varies per render — and Campaign Detail's header, next to the status badge.
Both show a `window.confirm()` naming the campaign and warning the action is
permanent and includes rendered images/publication history; Campaign Detail
redirects to `/campaigns` (`useNavigate`) on success. `useDeleteCampaign()`
(`api/hooks.ts`) takes the campaign id as the mutate-time argument rather than
a hook-creation-time one, so the same hook definition serves both call sites.

**Testing caught a real gap, not just added coverage.** `tests/conftest.py`'s
`temp_db` fixture built its own SQLAlchemy engine for the test DB but never
attached the `PRAGMA foreign_keys=ON` connect-listener that the real app engine
has in `app/db.py` — meaning every DB-level `ondelete="CASCADE"` in this app
would have silently not fired in *any* test, ever, letting a real cascade bug
pass unnoticed. Fixed by adding the identical listener to `conftest.py`
(verified inert on its own — full suite still 143/143 before adding new tests),
then adding three tests in `test_api.py`: a full round-trip proving every
child table cascades and every recorded file disappears while a shared
`Opportunity` survives; a 404 for an unknown campaign id; and the 409 refusal
while a `Job` is `RUNNING`. **146 tests total, all passing.**

## 5n. First real Windows Autopilot run: two bugs, both fixed (round 14)

The user's first real end-to-end Autopilot run on their actual Windows machine
(after round 13's delete feature; the app hadn't been exercised this fully on
Windows before, since prior rounds' dev/test environment is Linux) surfaced
two genuine bugs — one specific to Playwright-on-Windows-under-uvicorn, one a
general robustness gap that any unexpected stage failure could have hit on
any platform.

**Bug 1 — `NotImplementedError` from Playwright, Windows only.** Traceback:
`services/jobs.py` → `run_autopilot` → `run_visuals_stage` → `render_slide` →
`renderer.render_png_with_diagnostics` → `NotImplementedError`, no further
detail. Root cause, verified against both asyncio's and uvicorn's own
behavior: Playwright's async API launches Chromium as a real OS subprocess,
which asyncio can only do on Windows via the **Proactor** event loop.
Uvicorn's own graceful-shutdown signal handling (`loop.add_signal_handler`,
for Ctrl+C) is, on Windows, only supported by the **Selector** event loop —
Proactor doesn't implement it. Both requirements apply to whichever event
loop the whole process is running on, they're mutually exclusive on Windows,
and uvicorn sets up its loop first — so the loop Autopilot's background job
runs on is Selector, and the moment Playwright tries to launch its subprocess
on it, asyncio raises `NotImplementedError` deep inside Playwright's own
subprocess-launch code. This can't reproduce on Linux/Mac (both platforms'
default loops support subprocesses fine, no Proactor/Selector split exists),
which is exactly why it shipped all the way through 13 rounds of Linux-based
dev/test without being caught.

**Fix**: `PlaywrightRenderer` (`services/creative/renderer.py`) now launches
Chromium and runs every page operation on a dedicated background thread with
its *own* event loop — forced to `WindowsProactorEventLoopPolicy` on Windows,
left as the platform default elsewhere — and bridges each render call onto it
via `asyncio.run_coroutine_threadsafe(...)` + `asyncio.wrap_future(...)`.
Uvicorn's own loop never touches Playwright directly, so each side gets the
loop type it actually needs; nothing about the public `render_png`/
`render_png_with_diagnostics`/`close()` API changed, so `pipeline.py` and
every caller needed zero changes. `_ensure_browser`'s lazy-launch lock is an
`asyncio.Lock` created and used only from coroutines already running on the
renderer thread (never from uvicorn's loop), and thread startup itself is
guarded by a plain `threading.Lock` since it can be triggered from uvicorn's
loop. `close()` (called from `app/main.py`'s lifespan shutdown) submits a
shutdown coroutine onto the renderer thread the same way, then stops that
thread's loop and joins the thread. All 146 pre-existing tests — several of
which directly exercise the real `PlaywrightRenderer`, not a fake — passed
unchanged against this refactor on Linux, confirming it's behavior-preserving
there; the fix specifically targets the Windows-only failure path this app's
own CI/dev environment structurally cannot exercise.

**Bug 2 — a failed stage could leave a campaign stuck with no way to retry.**
Independent of bug 1, but discovered because of it: `run_visuals_stage` sets
`campaign.status = "GENERATING"` and commits *before* its render loop runs
(same pattern in `run_strategy_stage`, which sets `RESEARCHING` before its
research + AI calls). Each stage already sets `campaign.status = "FAILED"`
itself for the specific failures it anticipates (no candidate photos, no
strategy candidates, everything rejected as too similar) — but the bug-1
`NotImplementedError` was an *unanticipated* exception, and nothing caught it
to reset campaign status. `services/jobs.py`'s `_execute_job` correctly
caught it and marked the `Job` row `FAILED` (that part always worked — the
frontend did show a real error message) but never touched the `Campaign`
row, so it stayed showing `GENERATING` — a status the big "Run Autopilot"
button's guard (`IDEA`/`FAILED` only) doesn't treat as retryable, and the
status badge never reflected that anything had failed at all.

**Fix**: `_execute_job`'s existing `except Exception` block (the one place
that already generically handles failure for every job type — Autopilot and
all three advanced-mode stages alike) now also resets `campaign.status` to
`FAILED` when it's `RESEARCHING` or `GENERATING` (`_STUCK_IF_JOB_FAILS`, a
small frozenset) — the two statuses the orchestrator only ever sets
*mid*-stage, immediately before doing real work, never a status a campaign is
meant to sit in between requests. Deliberately narrow: a campaign resting in
a stable, resumable status like `BRIEF_READY` (between Strategy and Copy) is
never touched by this backstop, since an unrelated job failure shouldn't
rewrite a status the user didn't ask to change. Fixed at the job-runner layer
rather than inside each orchestrator function specifically so it covers every
current and future stage function for free, rather than needing the same
try/except reset repeated in `run_strategy_stage`, `run_copy_stage`, and
`run_visuals_stage` individually. New `tests/test_jobs.py` (4 tests) exercises
`run_job`/`_execute_job` directly against a fake failing job function — no
real Autopilot run needed to prove the backstop fires — covering: a
`GENERATING` campaign flips to `FAILED`; a `RESEARCHING` campaign flips to
`FAILED`; a `BRIEF_READY` campaign is left alone; and a job with no
`campaign_id` at all doesn't crash the handler. **150 tests total.**

Practically: the user's own campaign that hit bug 1 (stuck in `GENERATING`
before this fix shipped) doesn't need to be deleted and recreated — the
"Visuals only" advanced-mode button has no status gate at all (see section
5g), so it retries directly and, with bug 1 fixed, now succeeds.

## 5o. Full AI recreation + Inspiration Library (round 15)

Two real gaps reported directly by the user, with no accompanying text — a
screenshot of Autopilot's first-run message (see round 14) followed later by
plain feedback in words: (1) nowhere in the app could they add "examples of
ads, posts and carousels" to be used as inspiration, and (2) Autopilot "did
not create a new image, it simply added a little text on the product picture"
— they expected the app to *recreate* the photo to fit the campaign, not just
place it on a new background with text over it.

**Root cause of (2), and why it wasn't a bug so much as a real missing
capability.** The hybrid creative pipeline (section 5b) has, by explicit
design since Phase 6, never redrawn the actual product pixels — even with
`use_ai_background=true` (section 5h), that flag only generates an empty
*backdrop* via `ImageProvider.generate(...)`; `compositor.py::
composite_product` then pastes the real, untouched product photo on top of
it. That's a deliberate, still-correct default (predictable, never distorts
real packaging), but it means the AI involvement in the "recreate" ask the
brief describes was never actually built — only the background half of it
was. Section 5b's own hybrid-pipeline docstring even names the missing piece
directly: "the product pixels the user shot are never redrawn by the model
*unless the user explicitly opts into full AI recreation*" — that opt-in
never existed until this round.

**The fix: `recreate_creative_image` (`services/orchestrator.py`), a new,
genuinely different pipeline path from `generate_ai_background`.** Rather
than generating an empty scene, it sends the **real source photo itself** —
plus, when the user has uploaded any, up to two Inspiration Library examples
(see below) — to `ImageProvider.generate(..., reference_images=[...])`,
which (per section 5h) already routes to the Images **edit** endpoint
whenever reference images are given. The prompt explicitly instructs the
model to keep the actual product (packaging, shape, label, colors) accurate
to the reference photo — this is a restyling of the scene *around* a real
product, never a hallucinated substitute for it — while reimagining
everything else (background, lighting, composition, mood) together as one
new image, grounded in the brand's own configured voice/visual-style/colors
and the campaign's own angle/main_promise. The result is treated completely
differently downstream from `generated_background`: it's assigned to a new
`SlideCreativeInput.recreated_image` field (`services/creative/
pipeline.py`), and when set, `render_slide` **skips background isolation,
gradient/AI-background generation, and product compositing entirely** —
those three steps have nothing left to do once the whole image already
exists — and just resizes the recreated image to the platform's exact
canvas. Text and the logo still render afterward as real HTML/CSS via the
existing template step, exactly like every other path — the "no AI-generated
text/logos baked into the image" rule (section 5b, brief sections 8/65) holds
identically either way. `SlideRenderResult.background_isolator_used` reports
`"ai_recreated"` for this path (shown on Campaign Detail as "fully recreated
by AI"), a natural extension of the same field's existing `"none"`/
`"rembg"` values rather than a new one bolted on beside it.

Same best-effort discipline as `generate_ai_background`/`detect_product_zone`
before it: any failure (bad key, rate limit, malformed image bytes) is caught
and returns `None`, and the caller falls back to the deterministic
gradient-plus-paste pipeline that has always worked — a bad AI response must
never take down a render that would otherwise have succeeded. When
`recreate_with_ai` is on and *succeeds* for a slide, `use_ai_background`/
`detect_product_zone` are skipped entirely for that slide (there's no
separate background or product-zone step left to run once the whole image
already came back) — they're retained purely as the fallback path for when
recreation is off or fails.

**The one deliberate default flip in this whole app.** Every other AI
enhancement in this pipeline (`use_ai_background`, `detect_product_zone`,
and `recreate_with_ai` itself on "Visuals only" and the manual `/slides/
render` endpoint) defaults to **off**, preserving the "needs no OpenAI key"
property those surfaces have always advertised. `POST /api/campaigns/{id}
/generate` — the main "Run Autopilot" button, and the literal answer to "the
app should do research... and recreate it so it fits the campaign type" —
defaults `recreate_with_ai` to **true** instead. This costs nothing new in
terms of what Autopilot already requires: it has needed an OpenAI key
unconditionally since Phase 7 (research/strategy/copy all need one
regardless of any image flag), so defaulting this one on doesn't add a new
precondition, only changes what a key-having user gets by default from the
button whose entire job is to produce a finished campaign. `run_autopilot`/
`AutopilotConfig` themselves keep `recreate_with_ai: bool = False` as their
own dataclass default (so every orchestrator-level test, and any future
direct caller, is unaffected) — the flip lives only in the `/generate`
endpoint's own parameter default, the narrowest place it could live.

**Inspiration Library — the direct answer to "examples of ads, posts and
carousels... used as inspiration."** `BrandAsset.kind` gains a fourth value,
`"inspiration"` (alongside `logo`/`font`/`visual_reference` since Phase 1),
distinct from `visual_reference` on purpose: a visual reference describes
*this brand's own* look (fed into `analyze_visual_style` and the AI
background), while an inspiration example is something the user found
*elsewhere* — a competitor's carousel, an ad they liked — that they want
campaigns to draw creative direction from, never something describing the
brand itself. `BrandAsset` also gains a nullable `category_id` (migration
`b94f4ec947d4`, this round's own — see below), so an inspiration example can
be scoped to one category (only informs that category's campaigns) or left
brand-wide (`category_id IS NULL`, applies everywhere) — matching how the
user actually organizes their source photos by category in the first place.
`_resolve_inspiration_paths` (`services/orchestrator.py`) prefers a
campaign's own category-scoped examples first, topping up any remaining
slots (capped at 2) with brand-wide ones, so a category with its own curated
inspiration never gets diluted by unrelated brand-wide examples once it has
enough of its own.

Uploads reuse the existing `POST /api/brands/{id}/assets` endpoint (Phase 6
extension, section 5h) rather than a new one — `kind=inspiration` plus an
optional `category_id` form field, validated against the brand (404 for a
category from a different brand or one that doesn't exist), with the same
`GET .../assets?kind=&category_id=` filtering `list_brand_assets` already
had a `kind` filter for. The Brand Detail page's new "Inspiration examples"
card mirrors the existing "Visual references" card's upload/thumbnail/delete
UI, plus a category-scope `<select>` for the next upload and a small badge
per thumbnail showing whether it's scoped or brand-wide.

Tested in `tests/test_creative.py` (a `recreated_image` render skips
isolation/background/compositing entirely, resizes to the exact platform
canvas, and reports `background_isolator_used="ai_recreated"`/
`product_zone_detected=False` even when a zone detection was also passed —
proving it's ignored once there's no compositor step left for it to
influence), `tests/test_orchestrator.py` (`recreate_with_ai` reaching
`recreate_creative_image` with the real source photo as the first reference
image and `use_ai_background` never also firing on top of it when
recreation succeeds; a failed recreation still producing a complete,
rendered campaign via the fallback path; `recreate_creative_image` as a
direct unit test proving category-scoped inspiration examples are preferred
over brand-wide ones and the prompt names the brand and the campaign's own
angle), and `tests/test_api.py` (inspiration upload/list/category-scoping/
rejection over real HTTP, and a dedicated regression test proving `POST
/generate` reaches the image provider by default with *no* `recreate_with_ai`
query param at all — the exact default-flip behavior described above).

## 5p. Migrations now apply themselves on startup (round 15)

A robustness fix prompted directly by building section 5o above: `BrandAsset`
gaining `category_id` is this app's **first ever migration that alters an
existing table** rather than only adding new ones. Every schema change
before this round — the Strategy Library's tables (section 5a), every table
in the original Phase 1 schema — was a brand-new table, and `app/db.py`'s
`init_db()` has only ever called `Base.metadata.create_all(bind=engine)`,
never Alembic itself. `create_all` is genuinely fine for a new table (it
creates whatever's missing), which is exactly why this gap never surfaced in
fourteen prior rounds — but it does **not** alter a table that already
exists, so on its own it would silently leave `brand_assets.category_id`
missing from every real install's existing database, crashing the first time
anything touched that column, with no indication to the user of what to do
about it beyond finding and running `alembic upgrade head` by hand — the
same class of "silent staleness after an update" problem as round 14's
stuck-campaign-status bug, just one layer lower, at the schema itself rather
than a job's side effect.

**Fix: `app/db.py::_run_migrations()`, called by `init_db()` before
`create_all`** (which now runs second, purely as a no-op safety net for a
schema Alembic already fully owns). Three real database shapes this needed
to stay correct against, all covered by `tests/test_db_migrations.py`
against the real Alembic config and migration files on disk (not mocked —
a migration bug is exactly the kind of thing a fake would hide):

1. **A brand-new, empty database.** No `alembic_version` table and no
   application tables either. `command.upgrade(cfg, "head")` runs every
   migration from scratch, building the complete schema in order — the
   `create_all` call afterward finds everything already present and does
   nothing.
2. **An existing install, never Alembic-tracked** (every real database this
   app has ever produced, until this round runs against it once) — has real
   tables and real data, but no `alembic_version` row, so blindly running
   `upgrade` from the beginning would crash trying to `CREATE TABLE` things
   that already exist. This is the case that actually matters here: before
   running `upgrade`, the database is `command.stamp`ped at whichever past
   revision its *actual* schema shape already matches — checked by
   inspecting real columns, not by assuming a table's existence implies a
   specific revision, since a database built via `create_all` against
   *current* models (every test's own `temp_db` fixture, or a fresh install
   on a version of the app already past this round) can already have
   `category_id` with zero Alembic involvement — stamping that case at the
   pre-round-15 revision would make `upgrade` try to add a column that's
   already there. Only after the stamp does `upgrade(cfg, "head")` run,
   applying just the genuinely new migration(s) on top.
3. **A database this function has already run against once** — a real
   `alembic_version` row exists from case 2's `upgrade` (or case 1's), so
   every future run just applies whatever's newly pending, the ordinary
   Alembic story with no special-casing needed at all.

Verified directly (not just inferred from reading the code) by simulating
case 2 exactly as a real pre-round-15 install would look: build the full
current schema via `create_all`, then drop `category_id` back off
`brand_assets` with raw DDL and insert a row, matching what every real
existing database actually is today — `init_db()` against that database adds
the column back and the pre-existing row survives untouched (`tests/
test_db_migrations.py::
test_init_db_on_an_existing_never_tracked_database_migrates_without_data_loss`).
Both `init_db()` calls in a row (case 1 and the general idempotency
property) don't crash either, confirmed directly in the same test file.

This isn't scoped narrowly to this round's one migration — it's a permanent
change to how `init_db()` behaves, so every future schema change (a new
column, a new table, a data-shape change) now reaches every existing
install automatically the next time its backend starts, with no separate
manual step for the user to remember or forget. A migration author adding a
future revision that alters an existing table should extend the same
"detect what's actually there before assuming a stamp revision" pattern in
`_run_migrations` rather than assuming a linear stamp is safe, per that
function's own inline comment.

## 5q. Baked-in AI text + custom carousel length (round 16)

Two fixes prompted directly by a real generated campaign the user flagged as
wrong on both counts: a screenshot showing a slide with the AI's own
dramatic baked-in headline text *and* this app's separately-rendered HTML
headline/body/CTA layered on top of it (double, competing text), and a
carousel that produced only 1 slide when the user expected 4 with no way to
ask for a specific count.

**Root cause 1 — double text layers.** `recreate_creative_image` (section
5o) has always told the image model *"do not render any text, words,
captions, or logos"*, on the theory that this app's own HTML/CSS layer would
draw the real headline/body/CTA afterward, cleanly, exactly as authored.
That instruction turns out to be unreliable in practice: image models are
inconsistent about obeying "no text" instructions, and become markedly
*less* likely to obey it the more the reference/inspiration images shown to
them already contain dramatic baked-in text (which real inspiration ads
almost always do) — so the model would render its own text anyway, and this
app's separate text layer would then draw a second, uncoordinated copy on
top of it, exactly what the user's screenshot showed.

**Root cause 2 — slide count.** `run_copy_stage`'s carousel-planning prompt
has always said *"plan up to `config.max_slides` slides, using your
judgment"* — a deliberate design (a strong single hero image is a valid
outcome for a concept that doesn't need a full carousel), but with no way
for the user to instead say "I want exactly N slides for this one," and no
UI surface for slide count at all.

Both fixes came from two rounds of direct clarification with the user
(not guessed) since either could reasonably have gone either way:

- **Text architecture** — asked whether to (a) tell the model even more
  forcefully to leave text out, or (b) let the AI bake in *all* the text
  and drop the separate HTML layer entirely for a full recreation. The user
  chose **(b)**, explicitly to match the look of the inspiration ads they'd
  shown as source material, with the one condition that whenever text is
  used it needs "a proper background" — i.e. real legibility, not text
  floating unsupported over a busy photo.
- **Slide count control** — asked whether the count should be set once at
  Autopilot-kickoff time, or live on the campaign itself, editable any time
  before or after a strategy is picked. The user chose **the campaign
  itself, editable any time** — so it isn't a one-shot generation parameter,
  it's a persistent, revisable property of the campaign.

**Implementation — text.** `recreate_creative_image` (`services/
orchestrator.py`) gained four new optional parameters: `headline`, `body`,
`cta`, `eyebrow`. When any is non-empty, the prompt switches from the old
"no text" instruction to one that (1) states the exact text verbatim so the
model can't invent its own slogans or numbers, (2) explicitly demands
"proper contrast and a real backing — a solid or gradient panel, a scrim, a
shape behind it — so every word stays fully legible," and (3) still tells
the model never to render the logo (the brand logo is never AI-generated,
per section 65 of the brief — it's always composited afterward as real
HTML/CSS, in both the old and new text modes). When no text is passed, the
original "no text, words, captions, or logos at all" instruction is
unchanged.

The three callers that invoke `recreate_creative_image` — `run_visuals_stage`
(Autopilot and Campaign Builder advanced mode), the manual per-slide
`POST /api/campaigns/{id}/slides/render` endpoint, and nowhere else — all
follow the same rule to keep the two text layers **mutually exclusive**:
`recreated_image is not None` is the single source of truth for "did the AI
bake the text in this time." When it did, the eyebrow/headline/body/CTA
passed into `SlideCreativeInput` (the HTML template's input) are emptied out
so `templates.py` renders no `.text-block`/scrim at all — the AI's own
baked-in text is the only text on the slide. When recreation is off, fails,
or no text was available to pass to it, `SlideCreativeInput` gets the real
text and the HTML layer draws it exactly as before. The underlying
`CampaignSlide.headline`/`body`/`cta`/`eyebrow` database columns always hold
the real text either way — baking text into pixels never costs the app its
ability to show, edit, or re-render that text later, it only changes how
that render currently chooses to display it.

`templates.py::_build_premium_product_hero` was updated to omit the
`.text-block` element (and its background scrim) entirely when no
eyebrow/headline/body/cta is given, rather than always rendering an empty
headline `<div>`. That in turn meant `run_creative_qa`'s existing "the
`.text-block` element must be present" check would incorrectly flag every
legitimate baked-in-text slide as a QA failure (nothing was wrong — nothing
was *supposed* to be there) — caught before shipping, not user-reported.
Fixed with a new `text_expected: bool` parameter on `run_creative_qa`,
threaded through from `render_slide()` based on whether any of
eyebrow/headline/body/cta were actually passed in, mirroring the existing
`logo_expected`/`logo_included` pattern already used for the same kind of
"was this element supposed to be here" check.

**Implementation — slide count.** `Campaign` gained a nullable
`target_slide_count` column (migration `f1882366252f`, chained after round
15's `b94f4ec947d4` — `app/db.py`'s stamping heuristic in `_run_migrations`
was extended with a third priority check, `target_slide_count` presence,
ahead of the existing `category_id` check, so an existing database missing
either or both new columns gets stamped at the right point and picks up
whichever migrations are actually pending). `None` (the default) preserves
the original "up to `config.max_slides`, model's judgment" behavior exactly;
setting it changes `run_copy_stage`'s carousel-planning prompt to "Plan
exactly N slide(s), no more and no fewer" and changes the slicing cap
applied to the model's returned `CarouselPlan.slides` from `config.max_slides`
to `target_slide_count`.

`PATCH /api/campaigns/{id}` is the new endpoint (`CampaignUpdate` schema,
`target_slide_count: int | None`) — it uses Pydantic's `model_fields_set` to
tell "field not sent" (leave unchanged) apart from "field explicitly sent as
`null`" (clear it back to model's-judgment), since a plain default can't
otherwise distinguish those two cases. Validated to 1–10 inclusive when set;
out-of-range values 400. Campaign Detail's Autopilot card gained a "Carousel
length" control (a number input + Set/Clear buttons, `useUpdateCampaign`
hook) shown above the existing recreate-with-AI checkboxes, editable at any
point in a campaign's lifecycle per the user's explicit choice, not gated to
before-strategy-is-picked.

Both features are covered end to end in `tests/test_creative.py` (template
omits/includes the text-block and scrim correctly; QA's `text_expected`
flag), `tests/test_orchestrator.py` (`recreate_creative_image`'s prompt
content with and without text; `run_visuals_stage` baking a real planned
slide's headline into the image-provider prompt while the DB row keeps the
real text; `run_copy_stage`'s prompt wording and slicing behavior with and
without `target_slide_count` set), and `tests/test_api.py` (`PATCH`
sets/clears/validates/404s). Neither feature is retroactive — only slides
rendered or re-rendered after this round pick up either behavior.

## 5r. Feature Showcase template + recreate_with_ai default flip (round 17)

Prompted by the user reporting, with real generated images attached, that
Autopilot's default full-AI-recreation path had fabricated a different,
wrongly-branded product with garbled on-package text — then uploading 16 of
their own professional reference ads and asking for the app's output to
follow that exact design pattern consistently, with the real product always
accurate and every word of text always legible.

**Root cause.** `recreate_creative_image` (section 5o) hands the real source
photo to an image-generation model and asks it to redraw the entire scene,
product included. That call already had an explicit "keep the product
accurate, don't invent a different one" instruction (section 5o) — the
user's actual bad outputs prove the model doesn't reliably follow it, the
same class of "an instruction to the model was systematically not obeyed"
problem section 5q's root cause already ran into once (there, "don't render
any text"). `POST /generate` — the main one-click Autopilot flow — had
defaulted `recreate_with_ai=true` since round 15, meaning every user's first,
most common path through the app used exactly this unreliable call.

**Decision, confirmed via two rounds of `AskUserQuestion` rather than
assumed.** First round: keep `recreate_with_ai` in the codebase as an
explicit, off-by-default opt-in, or remove the feature outright. The user
chose **keep it as an opt-in** — `AutopilotConfig.recreate_with_ai` and the
`POST /generate` endpoint's own parameter both flip their default from
`true` to `false`; `recreate_creative_image` itself, and every caller's
mutual-exclusivity handling around it (section 5q), are unchanged, since the
function still behaves exactly as designed when a user does opt in. Second
round: for the new template's richer copy (see below), whether the AI should
draft it (editable after) or the user should type it by hand every campaign.
The user chose **AI-drafted, editable**.

**Implementation — new default template.** `services/creative/templates.py`
gained `feature_showcase` (`_build_feature_showcase`), now
`AutopilotConfig.template_id`'s and `SlideRenderRequest.template_id`'s
default, modeled directly on the user's reference ads: an eyebrow/kicker line
and big headline over a left-to-right scrim (so text stays legible against
any photo without needing the AI to design a backing panel itself — the
scrim is deterministic CSS, not model-dependent), a top-right badge ribbon,
a short intro paragraph, up to 5 icon+bold-title+short-subtitle feature
bullets, an ingredients/results callout box, a bottom icon-feature strip, and
a bottom CTA bar with trust badges. Every section is independently optional
— rendered only when its fields are non-empty — so a plainer AI response, or
the round-16 "text baked into a recreated image" case (still fully
supported: recreation is opt-in, not removed), degrades gracefully to just
the photo and logo rather than empty boxes. `premium_product_hero` stays
registered and selectable; adding this template required no change to that
one or to the compositor/renderer/QA layers below it — exactly the
"nothing else changes" design section 5b already called out.

New optional fields on `SlidePlan` (`schemas/ai.py`) carry this content
end to end: `badge_text`, `intro`, `features` (a list of a new `SlideFeature`
schema — `icon` a single emoji, `title`, `subtitle`), `callout_label`/
`callout_value`, `bottom_features`, `trust_badges`. `run_copy_stage`'s
carousel-planning prompt (`services/orchestrator.py`) now asks the model for
all of these explicitly, grounded in the real product name/notes and the
strategy's research basis already on file, with an explicit "never invent
product claims, ingredients, or numbers that aren't grounded... leave a
field empty rather than guessing" instruction — the same anti-fabrication
posture as everywhere else in this app's AI copy, now extended to the new
fields. `run_visuals_stage` reads them back off the persisted carousel plan
(via `_slide_plan_to_dict`, which now includes them, so they round-trip
through the `creative` stage JSON output exactly like every other planned
field) and threads them into `SlideCreativeInput` → `TemplateContext`,
suppressed (same as eyebrow/headline/body/cta) whenever a recreation baked
its own text in, so the two layers stay mutually exclusive per section 5q's
existing rule — no new exception needed.

A real layout bug was caught by a new renderer-based test, not just assumed
away: a slide with the maximum 5 features plus a callout box genuinely
overflowed the template's text-safe area on the first render — the fix was
scaling feature-list font size/spacing down as the list grows (2 or fewer
features render at full size; 3-4 slightly tighter; 5 tighter still) rather
than a fixed size that only looked correct in a 2-3-feature test case. This
is exactly the kind of failure `run_creative_qa`'s real DOM-measured overflow
check (section 5b) exists to catch before a human ever reviews the slide.

**Implementation — default flip.** `AutopilotConfig.recreate_with_ai`,
`POST /api/campaigns/{id}/generate`'s `recreate_with_ai` query parameter, and
the Campaign Detail frontend's `recreateWithAi` checkbox state all changed
their default from `true`/on to `false`/off, with the checkbox's label text
rewritten to state plainly why (accurate product + legible text vs. an
experimental, occasionally-wrong AI recreation). The "Visuals only"
advanced-mode stage and the manual per-slide render endpoint already
defaulted to `false` since round 15 and are unchanged.

Covered in `tests/test_creative.py` (three new `feature_showcase` template
tests for text escaping/field inclusion, optional-section omission, and the
5-feature cap; a renderer-based test asserting no overflow at maximum
content — the one that caught the layout bug above), `tests/
test_orchestrator.py` (a new test confirming a carousel plan's badge/intro/
features/callout/bottom-features/trust-badges reach the actual render and
round-trip through the persisted `creative` JSON), and `tests/test_api.py`
(the round-15 regression test asserting the old `recreate_with_ai=true`
default was rewritten in place to assert the new `false` default — a direct
regression test for a default is expected to flip when the default does).
Neither change is retroactive — only campaigns generated or slides
re-rendered after this round pick up the new template and the new default.

## 5s. Product-fidelity gate, commercial art direction, visual master, slide marker (round 18)

Prompted by the user sharing 6 real carousel slides from their own
custom ChatGPT/GPT-based system (4 agents: Competitive Intelligence,
Campaign Director, Content Reviewer, Creative Studio) plus the real product
photo, asking this app's creatives to reach that same production level —
and uploading the 8 markdown documents that actually govern that GPT
system, now saved verbatim in the Claude Project under
`claude/hanna-gpt-system/`.

**The tension, named explicitly rather than resolved silently.** Matching
that bar requires full AI recreation of the whole scene — exactly the
`recreate_with_ai` path section 5r had just turned off by default because it
fabricated a wrong product. The user's own uploaded review rubric shows the
resolution: their GPT system doesn't avoid AI generation, it *reviews* every
generation against the real product before treating it as done (rubric item
"H. Product fidelity": "Fail if the creative replaces the real product with
a fictional lookalike or redesign"). Two `AskUserQuestion` rounds confirmed
this reading and the scope before any code was written — see docs/
campaign-pipeline.md's round-18 section for exactly what was asked and
chosen.

**Implementation — the fidelity gate.** `ProductFidelityCheck` (`schemas/
ai.py`) is a new structured-output schema: per-aspect `match`/`mismatch`/
`uncertain` judgments (package shape, proportions, brand/logo, label
structure, visible text, cap/closure, color, distinctive marks — the exact
list the user's rubric names) plus an `overall_verdict` that defaults to
`"FAIL"` at the schema level, so a malformed/empty parse can never
accidentally read as a pass. `AIProvider.check_product_fidelity`
(`services/ai/base.py`/`openai_provider.py`) implements it the same way
`detect_product_zone` (section 5j) does: a vision-model call shown the real
photo — here, both the real source photo AND the AI-recreated candidate,
side by side in one call, so the model compares them directly rather than
describing each in isolation.

`recreate_creative_image_with_fidelity_gate` (`services/orchestrator.py`) is
the new entry point every caller uses instead of calling
`recreate_creative_image` directly: generate once, save the candidate to a
temp PNG, run the fidelity check against it, and if the verdict isn't a
clean `PASS` — including a check that raised an exception, treated
identically to a `FAIL`, fail-closed — retry exactly once with a corrective
prompt built from `_mismatched_aspects_note` (names the specific aspects
that didn't match, plus the model's own reasoning), then give up
(`RecreationOutcome(image=None, ...)`) if the retry isn't verified either.
This never raises; every failure mode resolves to a `RecreationOutcome`,
matching every other best-effort AI hook in this module (`generate_ai_
background`, the original `recreate_creative_image`, `detect_product_zone`).
Crucially, a caller that has `image_provider` but no `ai_provider` gets
recreation skipped entirely — there is no path where an unverified image
can be produced and used; `run_visuals_stage` and both `/generate*`
endpoints in `api/campaigns.py` were updated so `ai_provider` is always
supplied whenever `recreate_with_ai` is requested (previously `/generate/
visuals` only wired `ai_provider` for `detect_product_zone`).

**Implementation — commercial art direction.** `recreate_creative_image`'s
prompt was rewritten to ask for the specific production level the user's
uploaded `HSC-PROD-001` design-profile doc describes — dimensional
foreground/midground/background depth, polished lighting with shadows/
reflections/glow/material detail, the product's own authentic packaging
colors driving the scene's palette rather than a forced brand-color
scheme — while sharpening (not loosening) the existing "the product must
stay accurate, never a redesigned lookalike" instruction, now stated as an
explicit tiebreaker ("when in doubt between a bolder reinterpretation and
product accuracy, always choose accuracy").

**Implementation — Campaign Visual Master (cross-slide consistency).** Once
a slide's recreation is generated AND verified, `run_visuals_stage` sets
`visual_master_path` to that slide's already-rendered PNG (no extra file
needed — it's already on disk from `render_slide`'s own write). Later
slides' `recreate_creative_image` calls receive it as one more reference
image, with an explicit instruction to match its lighting/palette/material/
typography/finish without duplicating its exact composition — the "Golden
Reference Workflow" concept from the user's uploaded doc, mechanically
wired up rather than left as a text-only convention.

**Implementation — slide-number marker.** `TemplateContext` gained
`slide_number`/`total_slides`; `templates.py::_slide_marker_html` (shared by
both templates, not duplicated) renders a small "N/total" pill via real
HTML/CSS whenever `total_slides > 1` — exact regardless of whether the
slide's image came from the deterministic pipeline or a full AI recreation,
matching the "1/6, 2/6, 3/6" system the design-profile doc calls for. A real
overlap was caught by rendering a preview during development (not just
assumed correct): the marker's top-left position collided with
`feature_showcase`'s eyebrow/headline text, which also starts top-left.
Fixed by pushing that template's `.text-block` down (`top: 13%` instead of
`6%`) whenever a marker will actually render — covered by a regression test
asserting the two `top` values directly in the rendered HTML, not just a
"looks fine" visual check.

**Implementation — `recreate_with_ai` default reconsidered.** `POST
/generate`'s `recreate_with_ai` parameter flips back to `true` (reversing
section 5r's change, specifically for this endpoint) — the fabrication risk
that justified turning it off is now caught mechanically by the fidelity
gate rather than trusted away, so the argument from section 5o/5r for
defaulting Autopilot's main flow to the richer path applies again. `AutopilotConfig`'s own dataclass default, the "Visuals only" advanced-mode
stage, and the manual per-slide render endpoint all stay `false`/opt-in,
preserving their "no OpenAI key needed unless you ask" property — the same
asymmetric-default pattern section 5o established and section 5r preserved.
The manual `/slides/render` endpoint was also switched from calling
`recreate_creative_image` directly to the new fidelity-gated wrapper, so
every recreation path in the app — Autopilot, Visuals-only, and manual —
now goes through the same verification, not just the automated ones.

Every recreation attempt's outcome (attempted/verified/attempts/notes) is
recorded in the same JSON file as the existing mechanical QA checks (section
5b), under a `product_fidelity` key — the mechanical equivalent of the
user's uploaded creative-handoff contract's `PRODUCT_FIDELITY_CHECK` field —
without adding it to `CreativeQAResult` itself, which stays pipeline.py's
plain DB-agnostic dataclass.

Covered by 9 new tests across `tests/test_orchestrator.py` (fail-closed with
no `ai_provider`; first-pass verified pass; retry-then-succeed, including
asserting the retry's prompt actually names the mismatched aspect and the
first attempt's prompt doesn't; persistent-failure fallback after exactly
one retry, never more; a check-error treated identically to a `FAIL`; and
the cross-slide visual-master reference actually reaching slide 2's call)
and `tests/test_creative.py` (the marker renders "2/6" on both templates
when `total_slides>1` and is absent when `total_slides<=1`; the text-block
offset regression test), plus one existing round-17 regression test in
`tests/test_api.py` rewritten in place for the new default (same as round
17 did to round 15's) — now also asserting the fidelity check itself gets
called. **186 tests total** (up from 177).

Explicitly out of scope this round, by the user's own choice: the
claims-safety/brand-boundary rules, the 7-family campaign-strategy taxonomy
with evidence gates, and the canonical product catalog's eligibility flags
from the other 7 uploaded docs. None of that governance is wired into this
app yet — `claude/hanna-gpt-system/` in the Claude Project has the full
source material for whenever that round happens.

**Bug fix, found by the user's very next test of this round.** They resent
the same 7 images with: *"right now it only added text to the picture i
already gave... transform my uploaded picture 1... into the following
carrousel (next 6 pictures)"*. Re-tracing `run_visuals_stage` found a real,
separate bug: `usable_count = max(1, min(len(planned_slides),
len(candidate_assets)))` sliced the rendered carousel down to however many
*distinct source photos* exist for the product/category, independent of how
many slides were planned or whether `recreate_with_ai` was on. A brand with
only one uploaded photo — the common case for someone just starting — could
therefore only ever get a 1-slide output, which is exactly the symptom
reported ("it only added text to the picture I already gave", singular,
when 6 were expected).

Fix: `run_visuals_stage` no longer slices `planned_slides` by photo count —
every planned slide renders. `candidate_assets` is instead indexed
round-robin, `candidate_assets[(i - 1) % len(candidate_assets)]`, cycling
back to the start whenever there are fewer photos than planned slides,
rather than truncating the carousel. This is exactly the workflow section
5s's recreation gate was built for: one real photo, recreated into N
distinct art-directed compositions, one per slide. With `recreate_with_ai`
off, slides reusing the same photo still differ by their own copy
(headline/body/cta), same as any ordinary multi-slide carousel built from
one hero shot. `Asset.times_used`/`last_used_at` bookkeeping is unaffected —
it already incremented once per loop iteration, so a photo reused across 6
slides in one run now correctly shows `times_used += 6`, reflecting real
usage rather than a proxy for "how many distinct photos exist."

New regression test in `tests/test_orchestrator.py`:
`test_visuals_stage_renders_all_planned_slides_even_with_one_source_photo` —
one uploaded photo, a `target_slide_count=6` plan, asserts all 6 slides
render with correct per-slide headlines, all 6 reference the single source
asset, and `times_used` lands on `6`. **187 tests total** (up from 186).

## 5t. Discovery carousels, product auto-detection, 20-slide cap (round 19)

The user described two campaign shapes the app had only ever built one of:
*"discoveries campaigns that should use many different products and each
product should be one slide, while other campaigns it should [be] one
product and transform into a 20 slide carrousel[]."* Round 18 already IS the
second shape end to end. This round builds the first, plus the parts of the
data model that turned out to be prerequisites nobody had actually wired up
yet.

**Prerequisite gap, found before any of the new feature could work at all.**
`Product` and `Asset.product_id` are round-1 schema — declared, and used by
`_select_candidate_assets`'s `product_id` filter — but never actually
populated by anything, and never reachable from any frontend screen
(`grep -rn product_id frontend/src` matched exactly one line: the TypeScript
type declaration). `Campaign.product_id` was accepted by the create endpoint
but no create form ever sent it. Before discovery mode (which depends on
picking real products) or even a working deep-dive campaign with a specific
product could mean anything in practice, products had to become real.

**Fix: extend the scanner's existing auto-detection one folder level
deeper**, rather than build a manual tagging UI. `_guess_category_slug`
already treats the first path component as the category
(`services/scanner.py`, since round 1); the brief's own scanner docstring
described a two-level convention
(`Source/skincare/product-a/photo.jpg`) that nothing had ever implemented
past level one. `_guess_product_slug` adds that second level, and
`_resolve_category_and_product` (a small helper factored out of the main
scan loop) auto-creates `Product` rows the same way `Category` rows are
already auto-created and cached — scoped by `(category_id, slug)` since the
same product-folder name could in principle exist under two categories. A
file with no second folder level (`Source/skincare/photo.jpg`) is left
product-less, not an error — plenty of real libraries aren't organized
per-product.

The retroactive part matters more than the forward-looking part: the fast
"unchanged file" re-scan path previously skipped category/product resolution
entirely (it only ever set those fields when an `Asset` row was first
created). That path now calls the same resolution helper and backfills
`category_id`/`product_id` whenever either is still `NULL` on an otherwise-
unchanged file — never overwriting a value already set, so this only ever
fills a gap. A user's existing, already-scanned library becomes
product-tagged just by re-running the same "Scan repository" action they
already know, with zero manual per-photo work. Same shape as round 15's
Alembic auto-migration ("stamp what's already true, only apply what's
genuinely new") — applied to one row's data instead of the schema.

**The two carousel structures, computed identically in three places**
(`get_campaign` in `api/campaigns.py`, and `run_copy_stage`/
`run_visuals_stage` in `services/orchestrator.py`) so the read side (what the
frontend shows) and the two write sides (what Copy plans, what Visuals
renders) can never disagree about which mode a campaign is in:

```
campaign.product_id set               -> "deep_dive"  (round 18, unchanged)
campaign.product_id unset AND
  len(campaign.discovery_products) > 0 -> "discovery"  (new, below)
campaign.product_id unset AND
  no discovery products picked yet     -> "deep_dive"  (original behavior, untouched)
```

The third row is deliberate: a category-only campaign that predates this
round, or one where the user simply hasn't picked anything yet, must keep
behaving exactly as it always did — nothing is silently reinterpreted.

**`CampaignDiscoveryProduct`** (new table + Alembic migration
`c3a1f9d2b6e4`) is the ordered, hand-picked product list: `campaign_id` +
`product_id` (unique together) + `sort_order`. `PUT /api/campaigns/{id}/
discovery-products` replaces it wholesale — list order becomes carousel
order — rather than exposing incremental add/remove endpoints, matching how
the frontend panel actually uses it (recompute the full list, send it).
Rejected 400 on a product-scoped campaign (the two structures must never be
ambiguous for one campaign — deep-dive and discovery are mutually
exclusive by construction, not just by convention), 400 on a duplicate
product id or more than 20 products, 404 on an unknown product id.

**`run_copy_stage`'s discovery branch** swaps the usual "plan up to N slides
for this one product" carousel-planning prompt for one that lists every
picked product's name and notes, in pick order, and instructs the model to
plan *exactly* one slide per product in that same order — never combining
two products into a slide, never skipping one, never inventing an extra
slide not on the list. `effective_max_slides` becomes `len(discovery_
products)` outright; `target_slide_count` is meaningless in this mode and is
simply not consulted.

**`run_visuals_stage`'s discovery branch** builds `slide_assets` by calling
`_select_candidate_assets(product_id=dp.product_id, limit=1)` once per
picked product, in order — the least-used active photo *of that specific
product*. This is the one place discovery deliberately does NOT share
deep-dive's round-robin-via-modulo logic (section 5s): each slide must show
a genuinely different product, never cycle back through one already shown.
A picked product with no active photo simply doesn't get a slide (the same
best-effort "a moved/deleted source file shouldn't fail the whole run"
philosophy the rest of this loop already uses for a missing file), with the
`(slide, product)` pairing built by filtering rather than by index so a gap
never shifts every later slide's product out of alignment; if literally none
of the picked products have a photo, the run fails with a message that says
so specifically, rather than silently producing a zero-slide campaign. Both
branches converge back into one shared `slide_assets` list before the
existing per-slide render loop, which is otherwise completely unchanged —
recreation, the fidelity gate, the visual-master mechanism, and the slide
marker all already work per-slide-per-asset and needed no discovery-specific
logic of their own.

**Slide-count ceiling raised 10 → 20** — `PATCH /api/campaigns/{id}`'s
validation and the frontend carousel-length `<Input max=20>` — independent
of discovery mode, the deep-dive half of the user's request ("transform into
a 20 slide carrousel").

**Frontend**: campaign creation (`StrategyLibrary.tsx`) gained an optional
Product `<select>` beside the existing Category one, scoped to the chosen
category via the new `useProducts` hook (`GET /api/products`, already
existed server-side since round 1, simply never called from the frontend).
Campaign Detail gained a "Discovery products" panel — add/remove/reorder
(swap-based "Move up"), hidden entirely on a product-scoped campaign — and
the carousel-length display now branches on `structure_mode`: the existing
manual control for deep-dive, a derived "N slides — one per product picked
below" line for discovery. `api/client.ts` gained a `put` method (the
discovery-products endpoint is the app's first `PUT`).

Covered by 3 new scanner tests (`tests/test_scanner.py`: products
auto-created from the second folder level, correctly scoped to the right
category; a flat file gets no product; an existing unchanged asset gets
backfilled with both category and product on re-scan without re-hashing), 4
new orchestrator tests (`tests/test_orchestrator.py`: the discovery
carousel-plan prompt lists every product in pick order and never leaks
deep-dive's "Plan up to"/"Plan exactly ... no more and no fewer" language;
slides render one per product in pick order, verified against each
product's own distinct asset, not round-robin; a picked product with no
active photo loses only its own slide, the rest stay correctly ordered; the
run fails with a specific message when none of the picked products have a
photo), and 8 new API tests (`tests/test_api.py`: `structure_mode` reported
correctly on GET for both a product-scoped and a category-only campaign; the
discovery-products endpoint's set/reorder-via-replace/clear round-trip and
all four rejection cases — product-scoped campaign, duplicate id, unknown
id, over 20; the raised slide-count ceiling accepts 20 and still rejects
21). One existing test (`test_init_db_on_an_existing_never_tracked_
database_migrates_without_data_loss`, round 15's) was extended to also drop
the new table when simulating a pre-round install, since `_run_migrations`'s
stamp-detection (`db.py`) needed a new branch for "the whole
`campaign_discovery_products` table already exists" alongside its two
existing column-presence checks. **201 tests total** (up from 187).

Explicitly not built this round: a manual product-creation/rename UI (the
scanner's auto-detection covers the documented folder convention; a user
whose library isn't organized that way has no way to create a `Product` by
hand yet), and drag-and-drop reordering for the discovery-products panel
(swap-with-neighbor "Move up" only).

## 5u. AI-image resize was stretching, not covering (round 20)

Surfaced by the user directly comparing this app's output against several of
their own custom GPT prompts (a "Hanna Creative Studio" image-generation GPT,
a "Hanna Marketing Agent" content GPT, and two Facebook/Instagram-carousel
GPTs — ROAS-focused and general "extreme conversion") and asking why a much
simpler prompt in those GPTs produced visibly better images than this app's
longer, more heavily constrained prompt in `recreate_creative_image`.

Root cause was architectural, not prompt wording: `_nearest_ai_image_size`
(orchestrator.py) correctly maps a platform format's exact pixel dimensions to
the nearest of the three fixed shapes `gpt-image-1` actually supports —
1024x1024 (square), 1024x1536 (portrait, ratio 0.667), 1536x1024 (landscape).
None of Instagram's or Facebook's real slide shapes match those exactly — a
4:5 portrait carousel slide (1080x1350) has ratio 0.8, a story (1080x1920) has
ratio 0.5625. The generated image is meant to be a *background* the pipeline
later fits to the platform's exact canvas (`render_slide` in
`services/creative/pipeline.py`), and that fitting step was a bare
`Image.resize((fmt.width, fmt.height), Image.LANCZOS)` — a non-uniform
stretch to the exact target dimensions, not a crop-to-fit. Concretely: a
1024x1536 AI image (ratio 0.667) landing in a 1080x1350 slot (ratio 0.8) was
being squeezed ~20% narrower relative to its height on every single portrait
or story slide, warping product packaging, labels, and reflections — visible
distortion baked into every AI-recreated slide and every AI-generated
background in any non-square format, regardless of prompt quality.

Fixed with a new helper, `_resize_cover(image, width, height)`: computes the
scale factor needed to make the source *cover* the target box uniformly
(`max` of the two per-axis scale factors, i.e. scale-to-fill by the shorter
excess dimension), resizes uniformly at that factor, then center-crops the
overflow — the same semantics as CSS `object-fit: cover`, and what almost
every real image-fitting pipeline does by default for exactly this reason.
Same-size input returns the original object unchanged (`is` identity,
verified by `test_resize_cover_is_a_noop_when_size_already_matches`) rather
than doing a pointless full resize/crop round-trip. Replaces both prior
`resize` call sites in `render_slide`: the `recreated_image` branch (round 18's
full-AI-recreation path) and the `generated_background` branch (round pre-18's
AI-background-only path) — both now call `_resize_cover(image, fmt.width,
fmt.height)` unconditionally, dropping the old `if size != (fmt.width,
fmt.height)` guard since the helper handles the no-op case itself.

`test_resize_cover_fills_the_target_box_without_stretching` proves the fix
mechanically rather than just checking output dimensions (which a stretch bug
would also satisfy): draws a circle on a 400x600 (2:3) source, fits it into a
480x600 (4:5) target via `_resize_cover`, and asserts the circle's pixel
bounding box stays within 2px of square — a stretch bug at this exact ratio
mismatch would skew it by roughly 20%, far outside that tolerance.

Second, independent fix in the same round: `OpenAIProvider.generate`/`edit`
(services/ai/openai_provider.py) never passed a `quality` parameter to either
`client.images.generate` or `client.images.edit`, leaving `gpt-image-1` at its
own `"auto"` default — which is permitted to render at a cheaper/lower-fidelity
tier than what ChatGPT's own product surface typically requests for a user
explicitly generating an image. Both endpoints (plus the separate `edit`
method) now pass `quality="high"` explicitly. This app has no draft/preview
mode — every generation is for a real campaign — so there's no case where the
lower-cost tier is actually wanted.

Explicitly deferred, pending the user finishing sharing the rest of their
custom GPT prompts (so the redesign happens once, against the full picture,
rather than twice): a real "custom creative instructions" field on `Brand`
(the existing `campaign_rules` JSON column is dead — defined in the model and
schema, read nowhere); reconciling the strict claim-safety rules in two of the
GPTs (never render scarcity badges, review stars, bestseller badges,
before/after results, or unverified competitor comparisons without real
evidence attached to that specific campaign) against the other two GPTs'
15/10/6-slide "aggressive conversion" templates, which specify exactly those
elements as default, always-on content (mandatory "Mais Vendido"/"Oferta
Relâmpago" badges, a competitor comparison table, a results-by-day timeline);
adding a `product_scope` (single / multi / either) field to each of the 64
`STRATEGY_TYPES` entries in `data/strategy_library.py`, since today nothing
ties a strategy type (e.g. FOMO, naturally single-product) to the round-19
deep-dive/discovery structure choice; and whether the round-19 scanner's
folder-name product auto-detection should be replaced or backed by real
`HANNA-PROD` catalog-ID verification against the user's uploaded canonical
product catalog, which isn't wired into the code at all yet. **203 tests
total** (up from 201).

## 5v. Brand creative instructions, claims-safety baseline, product_scope, per-campaign platform picker (round 20 continued)

Implements the items 5u explicitly deferred, once the user said to finish
them now rather than wait for the rest of their custom GPT prompts — plus a
new, separately-requested feature (the platform/format picker). All four
pieces are backend-complete, migrated, and tested (215 tests, up from 203),
with frontend wiring for all four.

**`Brand.creative_instructions`** (`Text`, default `""`, model:
`models/brand.py`) — the brand's own standing creative-direction text, in
its own words. `_brand_creative_instructions_block(brand)` in
`services/orchestrator.py` returns `""` when unset, else a labeled string.
Called from `_brand_style_prompt_notes` (feeds image-generation prompts) and
inserted directly into the `user=` prompt of `run_strategy_stage`'s
candidate-generation call, `run_copy_stage`'s creative-brief and
campaign-copy calls, and both of `run_copy_stage`'s carousel-plan calls
(discovery-mode and deep-dive-mode) — every AI call that shapes a campaign,
not just image style. `Brand.campaign_rules` (the pre-existing dead JSON
field) is untouched and still unused; this is a new, separate, actually-wired
field, exposed via `BrandUpdate.creative_instructions` /
`BrandOut.creative_instructions` and a textarea on Brand Detail's style card.

**Baseline claims-safety instruction** — a fixed, unconditional block
(not a brand setting) appended to `recreate_creative_image`'s image prompt
and to both carousel-plan `system=` prompts in `run_copy_stage`: never invent
a scarcity/low-stock claim, countdown timer, specific discount/price
graphic, review-star rating or testimonial, bestseller/rank badge,
clinical/safety seal, before/after result, or competitor-comparison graphic
without the brand's own data actually supporting it. This resolves — in
favor of the safer default, everywhere — the real conflict 5u found between
two of the user's GPTs (anti-fabrication rules) and the other two
("aggressive" carousel templates treating those exact elements as
mandatory). The aggressive templates' actual badge/testimonial rendering is
not implemented; that needs a real "attach evidence" UI so a badge can be
backed by something true, and stays future work.

**`CampaignStrategyType.product_scope`** — new column
(`String(10)`, default `"either"`, values `"single" | "multi" | "either"`)
on all 64 `STRATEGY_TYPES` entries in `data/strategy_library.py`, classified
per-type from each type's own `example`/`objective`/`offer_types` (e.g.
`fomo_campaign` → `"single"`, `discovery_campaign` → `"multi"`, most Defense
types → `"either"`). Exposed via `StrategyTypeOut.product_scope` and shown
on the Strategy Library card. Purely informational: it does not gate or
auto-set `Campaign.structure_mode`, which (per 5t) still follows entirely
from whether a specific `product_id` / any discovery products are picked.

**`Campaign.platform_key`** (nullable `String(50)`, default `NULL`) —
which `PLATFORM_FORMATS` key this campaign renders at. `NULL` (every
pre-round-20 campaign, and any new one left unset) falls back to
`AutopilotConfig.platform_key`'s account-wide default (`instagram_square`),
preserving all prior behavior exactly. Validated against the real
`PLATFORM_FORMATS` registry on both create (`POST /api/campaigns`) and
update (`PATCH /api/campaigns/{id}`), 400 on an unknown key. Inside
`run_visuals_stage`, a single local computed once near the top —
`effective_platform_key = campaign.platform_key or config.platform_key` —
replaces all six of that function's former direct reads of
`config.platform_key` (output path, AI-recreation canvas size, deterministic
template render, persisted QA/output records), so one run agrees on one
platform throughout rather than resolving the fallback separately at each
call site. Also registered `instagram_portrait` (1080x1350, real Instagram
4:5 carousel shape) in `PLATFORM_FORMATS` (`services/creative/templates.py`)
— prior rounds' docs referenced it as if it existed, but it was never
actually added. Frontend: a dropdown next to Category/Product at campaign
creation (Strategy Library page, backed by `useCreativeTemplates`'s
`platform_formats`) sets it at creation time; a persistent selector on
Campaign Detail's Autopilot card (distinct from the manual "Render a
creative" panel's own per-render `platform_key`, which is unchanged and
still a one-off override) edits it any time afterward via `PATCH`.

Migrations: `d4f6a1c8b9e2` (adds `campaigns.platform_key` +
`brands.creative_instructions`, down_revision `c3a1f9d2b6e4`) →
`e7b3c5a9d1f4` (adds `campaign_strategy_types.product_scope`, down_revision
`d4f6a1c8b9e2`). Both verified up/down/up (and two-level-deep down) against a
scratch SQLite DB; `db.py::_run_migrations`'s stamp-detection gained a
`strategy_type_columns` lookup and two new top-of-chain branches so a
never-Alembic-tracked existing database picks up all five pending migrations
(the three from 5t/5u plus these two) in one `init_db()` call.

Still explicitly not built, same as 5u: the DESIGN_PROFILE_ID multi-profile
system from Hanna Creative Studio's prompt; real evidence-gated badge/
testimonial rendering with a UI to attach the supporting evidence; canonical
product catalog ID verification against `02-canonical-product-catalog.md`;
and structured, content-type-specific outputs for reels/email/blog (today
everything still shares the one `CampaignCopy` schema).

## 5w. Build 1 — Verified Product Facts + Campaign Foundation (Multi-Platform + Bilingual Quality Recovery Program)

The first build of a new, explicitly-scoped multi-round program aimed at real
multi-platform, bilingual campaign quality — supersedes the informal
round-by-round framing above for everything going forward, though this
document keeps the round history intact rather than rewriting it. Build 1's
own spec authorized only itself; further builds (per-platform rendering
variants, per-language visual rendering, a DESIGN_PROFILE_ID-style system)
are deliberately out of scope here and listed below as what's still missing.
238 tests total (up from 215).

**Verified Product Facts** (Part A) — a new `verified_product_facts` table
(model: `models/product_facts.py`) holds the owner-editable half of one
canonical `VerifiedProductFacts` structure; `services/product_facts.py::
resolve_verified_product_facts` assembles the full thing (adding read-only
`product_name`/`category`/`brand_name`/`owner_notes` and a computed
`missing_information` list) and `format_verified_facts_for_prompt` turns it
into a prompt block that explicitly separates VERIFIED FACT from RESEARCH
INSIGHT from CREATIVE IDEA and lists what's still unverified rather than
letting the model infer absence. Exposed via `GET`/`PUT /api/products/{id}/
verified-facts` (`api/products.py`). Never invents ingredients, percentages,
certifications, rankings, medical benefits, prices, discounts, availability,
shipping guarantees, clinical claims, or awards.

**Languages and platform targets** (Parts B/C) — `data/platform_capabilities.py`
is the new single source of truth: `SUPPORTED_LANGUAGES = ("pt-BR", "en")` and
`PLATFORM_CAPABILITIES` (instagram/facebook/tiktok/youtube_shorts/pinterest/
linkedin/x, each with real content-type and copywriting-guidance data), plus
`validate_languages`/`validate_target_platforms`. `Campaign.languages`/
`Campaign.target_platforms` (both JSON lists, defaults `["pt-BR"]`/
`["instagram"]`) are the new canonical fields — the legacy `Campaign.language`
(singular) stays for backward compatibility but is no longer authoritative.
Validated on `POST /api/campaigns` and `PATCH /api/campaigns/{id}`; a new
`GET /api/campaigns/config/platform-capabilities` exposes the registry to the
frontend (distinct from the pre-existing `GET /api/campaigns/creative/
templates`'s `platform_formats`, which is pixel-rendering size, not marketing
platform). Frontend: language/platform checkboxes at campaign creation
(Strategy Library page) and on Campaign Detail's Autopilot card (editable any
time, same "takes effect on the next run" rule as `target_slide_count`/
`platform_key`).

**Full AI recreation OFF by default** (Part D) — `POST /api/campaigns/{id}/
generate`'s `recreate_with_ai` parameter flips back to `False` (it was `True`
as of round 18 — see that endpoint's docstring for the full 15→16→17→18
history). This was the one remaining place defaulting to `True`; Autopilot's
`AutopilotConfig`, the Visuals-only stage endpoint, and the manual per-slide
render endpoint already defaulted to `False`. Full recreation, still passing
through the same product-fidelity gate, remains fully available via explicit
`recreate_with_ai=true` — it's now an opt-in for campaigns that want a fully
art-directed look, not the everyday default. Frontend: `CampaignDetail.tsx`'s
Autopilot checkbox default flips to unchecked to match.

**Campaign Copy grounding** (Part E) — `run_copy_stage` (`services/
orchestrator.py`) now loops over `campaign.languages`, generating an
independent `CampaignCopy` + `CarouselPlan` per language (never one generated
then translated — see Part F below), while the `CreativeBrief` (design/visual
direction) stays one call per campaign, matching the "one campaign idea,
multiple executions" architecture. Each call is grounded in: brand (name,
voice, preferred CTAs, disallowed terms, disclaimers, target audiences,
target countries, `creative_instructions` — `campaign_rules`, the round-1
dead JSON field, is deliberately *not* resurrected; `creative_instructions`
is its already-wired round-20 replacement), verified product facts (deep-dive
campaigns only — a discovery campaign's facts stay per-product, grounded
per-slide as before), this campaign's own persisted research insights (via
`campaign.research_run_id` — previously generated in the Strategy stage and
never read again), strategy (now including `funnel_stage`/`insight`/
`reason_this_should_work`, not just `angle`/`key_message`), and the selected
target platform(s) (`_platform_requirements_note`, sourced from
`data/platform_capabilities.py`).

**Language quality rules** (Part F) — `_language_style_rules(language)` gives
pt-BR and en each their own concrete, named failure-modes-to-avoid instruction
block (not just "write naturally"): pt-BR avoids Portugal-specific
vocabulary/conjugations, overly formal business Portuguese, literal
translation-from-English structure, and named generic-AI phrases; en avoids
translated-Portuguese sentence structure, unnatural idioms, and its own named
generic-AI phrases. Folded into the `system` prompt of every per-language
CampaignCopy/CarouselPlan call.

**Brand Style Resolver** (Part G) — new `services/creative/brand_style.py::
resolve_brand_style` closes a real, confirmed gap: `SlideCreativeInput`/
`TemplateContext`'s `accent_color`/`text_color`/`font_family` were always the
same hardcoded defaults at both real call sites (`run_visuals_stage` and
`api/campaigns.py::render_campaign_slide`) — `brand.colors` was only ever
used for the gradient *background*, never on-slide text/badge/CTA color, and
`brand.typography` was never read by anything. Since `colors`/`typography`
are free-form dicts (no fixed key schema — the brand-detail UI lets an owner
type any key name), the resolver looks for common key spellings
case-insensitively, falls back to positional order among whatever colors
exist, then finally to the same hardcoded defaults the pipeline always used —
so an existing brand with colors already entered starts getting real brand
colors today, with zero behavior change for a brand with nothing entered.
Also resolves `disclaimer_text` (joined `Brand.disclaimers`) and
`visual_reference_paths` (approved brand assets).

**Deterministic typography** (Part H) — turned out to already be true by
construction for every other text field once Part D's default lands
(`run_visuals_stage`'s `text_baked_in` branch already renders eyebrow/
headline/body/cta/badge/features/callout/bottom_features/trust_badges as real
HTML/CSS whenever `recreate_with_ai=False`). The one genuine gap: no
`disclaimer` field existed anywhere, despite `Brand.disclaimers` already
existing and going unused in rendering. Added `disclaimer: str = ""` to
`SlideCreativeInput`/`TemplateContext`, auto-populated from
`resolve_brand_style(...).disclaimer_text`, rendered as real DOM text by both
templates (inside the flowing text-block for `premium_product_hero`; as its
own small strip stacked above the CTA bar/bottom strip for
`feature_showcase`, with the logo/text-block offsets adjusted to match) —
skipped entirely when empty, so every existing slide is byte-for-byte
unaffected.

**Campaign Copy prompt versioning** (Part I) — `services/prompt_registry.py`
finally uses the `PromptVersion` model (dead code since round 1): a small
`PROMPT_VERSIONS` registry for `campaign_copy`/`carousel_plan`,
`ensure_prompt_versions_seeded` (wired into `services/seed.py::seed_all`),
and `record_prompt_usage` logging every actual generation (purpose, version,
language, platform) to `audit_events`. See "9. Prompt management" above for
the full mechanism.

**Persistence shape change**: `copy`/`creative` `CampaignOutput` JSON is now
nested per language — `{"primary_language": ..., "languages": {"<lang>":
{...}}}` — instead of one flat object (`creative` additionally keeps a
top-level `creative_brief`, shared across languages). `get_campaign_copy(db,
campaign_id, language=None)` gained the `language` parameter (its one caller,
the publish endpoint, still passes none and gets the primary language) and,
along with `run_visuals_stage`, reads this back through a new
`_stage_language_variant` helper that also transparently handles the old flat
shape from a pre-Build-1 campaign.

Migration: `f4a8c2e6b1d9` (new `verified_product_facts` table +
`campaigns.languages`/`campaigns.target_platforms`, down_revision
`e7b3c5a9d1f4`) — backfills every existing campaign's `languages` from its
current `language` value (never silently changed) and `target_platforms` to
`["instagram"]` (matching every pre-Build-1 campaign's actual behavior),
row-by-row in Python rather than a raw SQL `json_array(...)` call, so it
doesn't depend on the SQLite build's JSON1 extension. Verified up/down/up and
against a simulated pre-existing (never-Alembic-tracked) database with real
data. `db.py::_run_migrations`'s stamp-detection gained a `languages`-based
top-of-chain branch.

**Explicitly out of scope for Build 1** (see the completion packet's
REMAINING_BLOCKERS for the authoritative list): full per-platform pixel-
rendering variants — a campaign can target multiple real platforms, but still
renders at one pixel format (`platform_key`/`PLATFORM_FORMATS`), same as
before; full multi-language *visual* rendering — every selected language's
copy/carousel-plan is generated and persisted in full, but only the primary
(first-selected) language's carousel actually renders into slide images in
`run_visuals_stage`; a dedicated frontend page for editing Verified Product
Facts (the API/hooks are fully wired and tested — `GET`/`PUT` — but no
product-detail page exists yet in this app to host the editing form); and,
unchanged from prior rounds, the DESIGN_PROFILE_ID multi-profile system and
real evidence-gated badge/testimonial rendering.

## 5x. Build 2 — Platform Adapter + Creative Director + Hybrid Visual Engine

The second build of the multi-build program, resolving the two limitations
Build 1 explicitly carried forward: only the primary (first-selected)
language actually rendered into slide images, and `target_platforms` (which
real marketing platforms a campaign targets) had no formal relationship to
`platform_key`/`PLATFORM_FORMATS` (which pixel canvas something renders at).
270 tests total (up from 238) — every Build 1 test still passes unchanged.

**Parts A/B — `PlatformCreativeSpec` (`data/platform_creative_specs.py`).** A
new, third registry — deliberately not collapsed into `PLATFORM_CAPABILITIES`
(marketing-platform targeting + copy notes, Build 1) or `PLATFORM_FORMATS`
(pixel-exact render canvases, pre-Build-1) — that resolves the missing middle
layer: for one (platform, content_type) pair, whether it's renderable as a
static image today, which `PLATFORM_FORMATS` key to render it at, and the
structural creative rules (copy density, safe zones, slide count, caption/CTA
style, cover/script requirements). Content types are catalogued per platform:
Instagram (feed_post, carousel, story, reel_cover, reel_script_caption),
Facebook (feed_post, multi_image_campaign, promotional_creative), TikTok
(short_video_concept, script, shot_list, cover, caption), YouTube Shorts
(short_video_concept, script, title, description, cover), Pinterest (pin,
vertical_creative, pin_title, pin_description — the first non-Instagram/
Facebook `PLATFORM_FORMATS` entry, `pinterest_vertical` at 1000x1500), LinkedIn
(image_post, educational_post, carousel_document_concept), X (image_post,
short_post, thread). Video-oriented content types are represented
structurally (`supports_static=False`, `script_required=True`) but never
claim a real render — see Part L. `resolve_platform_creative_spec(platform,
content_type)` and `default_content_type_for_platform(platform, slide_count=)`
are the two functions every other Build 2 piece reads from.

**Part C — Brand Asset Validator (`services/brand_assets_validator.py`).**
`validate_brand_assets(db, brand, product_id=None)` — purely deterministic,
never synthesizes a placeholder — checks the real logo `BrandAsset` row and
file, whether `brand.typography`/`brand.colors` are genuinely populated (not
just resolvable via `resolve_brand_style`'s own hardcoded fallback), and
every product's active-photo coverage, returning a structured
`BrandAssetValidationResult` with a plain-English `issues` list and an
overall `valid` bool. Exposed via `GET /api/brands/{id}/asset-validation`.

**Part D — Model role routing.** Eight new `AutopilotConfig` fields
(`strategy_model`, `copy_model`, `platform_adapter_model`,
`creative_director_model`, `draft_image_model`, `premium_image_model`,
`creative_qa_model`, `revision_model`), each falling back to the legacy field
it replaces (`campaign_model`/`image_model`/`vision_model`) via
`__post_init__` when left unset — so a config built with only the pre-Build-2
fields, or a deployment that hasn't touched Settings, gets byte-for-byte the
same models as before. Backed by 8 new `Settings` fields
(`openai_strategy_model` etc., all defaulting to `"gpt-5.1"`/`"gpt-image-1"`)
and threaded through `settings_store.py`/`schemas/settings.py`/
`api/settings_api.py`. No provider name is ever hardcoded in business logic —
every model-routing call site reads a role field, never a literal string.

**Part E — Master Campaign Concept (`schemas/creative_director.py::
MasterCampaignConcept`).** Generated once per campaign in `run_copy_stage`
(alongside `CreativeBrief`, using `creative_director_model`) and persisted as
a new `CampaignOutput(kind="master_concept")` row — the one consistent
campaign idea (concept_name, campaign_promise, key_message, emotional_goal,
audience, objective, visual_identity, story_arc, cta_intent, must_include,
must_avoid) that every platform/language adaptation below is told to adapt,
never to reinvent. Deliberately platform- and language-agnostic.

**Part F — Platform Adapter + the core fix.** `PlatformAdaptation`
(`_resolve_platform_adaptation`, `services/orchestrator.py`) adapts the
master concept to one platform's real conventions once per (campaign,
platform) — shared across that platform's targeted languages, since the
adaptation strategy (TikTok: hook + script + shot progression; Pinterest:
vertical discovery; Facebook: fuller promotional context; LinkedIn:
professional framing; X: short and concise) is a platform-level decision.
`_render_additional_platform_variants` is the actual carry-forward fix: for
every (target_platform x language) combination beyond the primary one
(`target_platforms[0]` x `languages[0]`, which `run_visuals_stage`'s own main
render loop still renders through the EXACT unchanged pre-Build-2 code path —
zero risk to the 238 Build 1 tests, all of which use single-platform/
single-language campaigns), an independent `PlatformCampaignVariant` row is
created with its own rendered asset, copy-language reference, layout pass
(`CreativeDirection`), status, and QA report paths. A platform this catalog
has no safe default content type for gets `status="SKIPPED_UNSUPPORTED"`
instead of being silently dropped. One variant's own failure (missing photo,
renderer error) is caught and recorded on that row (`status="FAILED"`) rather
than failing the whole Visuals stage. New model: `models/campaign.py::
PlatformCampaignVariant` (`uq_platform_variant` on campaign_id/
target_platform/language/content_type) — deliberately NOT a repurposing of
the pre-existing, confirmed-dead `CampaignVariant` model (an unrelated
A/B-testing concept from round 1 that has never been read or written by any
code path); migration `a1b2c3d4e5f6`. New endpoint:
`GET /api/campaigns/{id}/variants`.

**Cost discipline — do not regenerate expensive assets per language.** An
AI-generated background (`generate_ai_background`, gated by
`config.use_ai_background`) is generated once per (platform, slide index) and
reused across that platform's other targeted languages — a
`background_cache` dict scoped per platform inside
`_render_additional_platform_variants`'s own loop; the language-independent
scene/product composite is shared, only the deterministic per-language
typography layer differs. Full AI recreation (`config.recreate_with_ai`)
CANNOT be shared this way and isn't: the marketing text bakes directly into
those pixels, so every language genuinely needs its own recreation call —
documented as a real cost tradeoff, not an oversight.

**Part G/H — Creative Director + multi-language layout
(`CreativeDirection`).** The concrete visual/layout direction for ONE
rendered variant — one (platform, language, content_type) combination.
`_generate_creative_direction` calls the AI once PER (platform, language,
slide) — never shared across a platform's languages the way
`PlatformAdaptation` is — so `typography_direction`/`headline_emphasis` can
genuinely differ between e.g. pt-BR and en for the exact same slide (proved
directly in `tests/test_build2_platform_variants.py::
test_creative_direction_differs_between_english_and_portuguese`). AI-optional
throughout: `_deterministic_creative_direction` (no fabricated
visual/marketing claim, built only from the master concept, adaptation, and
already-resolved brand style) is the fallback when no AI provider is
available or the call fails — matching every other AI hook in this module.
`prohibited_elements` defaults to naming, by name, everything Part J says the
AI must never be asked for.

**Part I — Hybrid Renderer.** No new rendering architecture was needed — the
existing `render_slide()` pipeline (source photo -> validate -> composite
product -> generate/place scene -> real logo -> real HTML/CSS text -> export,
`services/creative/`) already implements the exact chain Build 2's spec asks
for; `_render_additional_platform_variants` reuses it unchanged for every
variant, passing `creative_direction` through to `generate_ai_background` for
the scene step. `recreate_creative_image`'s full-recreation path also reuses
the same product-fidelity gate as the primary render.

**Part J — Background generation stays scene-only.**
`generate_ai_background`'s prompt now explicitly enumerates every element the
AI must never be asked to generate: exact product label text, brand logo,
headline/body/CTA copy, a price/discount graphic, legal/disclaimer text — all
of those stay real HTML/CSS or the real, untouched product photo, never
pixels the scene-generation call produces. `CreativeDirection.prohibited_elements`
folds the same list into the AI-optional creative-direction call so both
layers agree.

**Part K — Quality modes.** `AutopilotConfig.quality_mode`
(`"draft"|"standard"|"premium"`, default `"standard"`) resolves via
`_resolve_image_model_and_quality` to a (model, Images-API-quality-tier)
pair: draft -> `draft_image_model` at `quality="low"`; premium ->
`premium_image_model` at `quality="high"`; standard -> `image_model` at
`quality="high"` — byte-for-byte what every AI-image call in this app always
used before Part K existed. `ImageProvider.generate`/`.edit` both gained a
`quality: str = "high"` parameter (was previously hardcoded inside
`OpenAIProvider`), passed through to the real OpenAI API calls. Threaded from
`api/campaigns.py`'s `/generate` and `/generate/visuals` endpoints
(`quality_mode` query param) down to both AI-image call sites in
`_render_additional_platform_variants`.

**Part L — Video-oriented platform output, never a fake video.** For
TikTok/YouTube Shorts content types that don't support a static render,
`generate_video_concept` produces a structured `VideoConcept` (hook, script,
shot_list, timing, visual_direction, on_screen_text, caption,
cover_creative_brief) — `is_rendered_video` is forced `False` unconditionally
by the schema's own `model_post_init`, not a caller-settable flag, so nothing
downstream can mistake this for a finished video file. The variant's own
`status` records the honest outcome: `"SCRIPT_ONLY"` when a real AI provider
produced a script, `"SCRIPT_UNAVAILABLE"` (never a fabricated script) when no
provider was available.

**Traceability extension (`services/prompt_registry.py`, Part I from Build
1).** Build 1's `PROMPT_VERSIONS` registry — versioned prompt specs plus
`record_prompt_usage`, logging a `campaign_prompt_usage` `AuditEvent` per
(purpose, version, language, platform) — gains four new Build 2 entries, all
`version="1.0.0"`: `master_campaign_concept` (logged from `run_copy_stage`,
once per campaign, language/platform taken from the primary combination),
`platform_adaptation` (logged from the outer per-platform loop in
`_render_additional_platform_variants`, once per targeted platform),
`creative_direction` (logged once per platform/language/slide — the same
granularity at which the direction itself is generated, so a past campaign's
per-language layout choices stay traceable), and `video_concept` (logged
once per video-oriented platform/language variant). No new call sites were
needed elsewhere; every AI-optional hook this build added already routes
through one designated call point per purpose. Covered by
`tests/test_orchestrator.py::test_prompt_versions_seeded_and_usage_recorded_per_language`
(the `master_campaign_concept` entry) and
`tests/test_build2_platform_variants.py::test_multi_variant_creative_director_calls_are_logged_for_traceability`
(the other three).

Migration: `a1b2c3d4e5f6` (new `platform_campaign_variants` table,
down_revision `f4a8c2e6b1d9`) — verified up/down/up and against a simulated
pre-Build-2 (never-Alembic-tracked) database with real rows still on the
`brand_assets` table. `db.py::_run_migrations`'s stamp-detection gained a
`platform_campaign_variants`-presence top-of-chain branch.

**Explicitly out of scope for Build 2** (not silently under-delivered — next
build's territory): a dedicated frontend surface for browsing
`PlatformCampaignVariant` rows or the Brand Asset Validator's result (both
API endpoints are fully wired and tested, `GET /api/campaigns/{id}/variants`
and `GET /api/brands/{id}/asset-validation`, but no frontend page consumes
them yet); actual video file generation for TikTok/YouTube Shorts (Part L is
explicit that this remains structured script output only); a
user-facing picker for `quality_mode`/`render_platform_variants` on Campaign
Detail (both are wired end-to-end through the API with sane defaults, just
not yet exposed as UI controls); and, unchanged from Build 1, the
DESIGN_PROFILE_ID multi-profile system and real evidence-gated
badge/testimonial rendering.

## 5y. Build 3 — Platform + Language Aware Multimodal QA

The third build of the multi-build program: evaluates every already-rendered
Build 2 `PlatformCampaignVariant` for visual quality, brand quality, product
fidelity, language quality, and platform fit, then applies ONE targeted,
minimal revision when something fails — never a blind full-campaign
regeneration. 281 tests total (up from 273 mid-build / 270 at the start) —
every Build 1/2 test still passes unchanged, since the new QA stage
(`services/qa_engine.py`) is opt-in (`AutopilotConfig.enable_qa_stage`,
default `False`) and never auto-invoked from `run_autopilot`.

**Carry-forward requirement 1 — the scene-reuse gap.** Build 2's own
cost-discipline `background_cache` (see 5x above) already shared an
AI-generated background across a platform's *non-primary* languages, but
never with the *primary* language, which `run_visuals_stage`'s own separate
legacy loop renders — so a non-primary language of the PRIMARY platform (e.g.
Instagram+en when Instagram+pt-BR is primary) always regenerated its
background from scratch even though nothing about the scene should differ.
Fixed via a new `_scene_signature(direction: CreativeDirection) -> tuple`
(the 11 scene-relevant `CreativeDirection` fields only — background_concept,
visual_style, mood, composition, product_position, product_scale, lighting,
depth, texture, palette, scene_generation_prompt — deliberately excluding
the per-language typography/copy fields) plus a `primary_generated_
backgrounds: dict[int, Image.Image]` handed from `run_visuals_stage`'s main
loop into `_render_additional_platform_variants`, which now seeds
`background_cache` for the primary platform with those images tagged under
the REAL computed deterministic-fallback signature (not a bare empty tuple —
a brand with a configured color palette would otherwise never match).
`background_cache`'s value type changed from one image per slide index to a
list of `(signature, image)` pairs, since a platform/slide can legitimately
end up with more than one distinct cached scene when different languages'
`CreativeDirection`s genuinely disagree (requirement 4) — reuse only happens
on an exact signature match, never a bare platform+slide-index match.
`shared_scene_source` (Build 2's own traceability field) now accumulates
every reused slide index via `shared_source_parts` (comma-joined) instead of
silently overwriting earlier slides' reuse info with only the last one — a
real, if minor, pre-existing Build 2 bug fixed along the way. Proven by
`tests/test_build3_scene_reuse.py`'s 3 tests covering all 5 of the carry-
forward spec's required properties (shared reuse; independent final renders;
separate per-language typography; no reuse when `CreativeDirection` genuinely
diverges; never crosses platform/product/campaign boundaries — the last one
true by construction, since `background_cache` is a local reset per platform).

**Carry-forward requirement 2 — QA state is per-variant.** Every QA field
(`qa_status`, `qa_scores`, `qa_hard_fails`, `qa_attempts`,
`qa_evidence_paths`, `qa_versions`, `qa_notes` — 7 new columns on
`platform_campaign_variants`, migration `b2c3d4e5f6a7`) lives on the
`PlatformCampaignVariant` row itself, never only aggregated onto the parent
Campaign — "Instagram/pt-BR = PASS, Instagram/en = NEEDS_REVIEW,
Pinterest/en = PASS" stays exactly representable, and `run_qa_stage`'s own
per-variant dispatch (`_qa_one_static_variant`/`_qa_one_video_variant`)
never touches any variant but the one it's currently evaluating.

**Carry-forward requirement 3 — format-appropriate video QA.** A
`SCRIPT_ONLY` variant (TikTok/Reels/YouTube Shorts) gets `run_video_qa`
(`schemas/qa.py::VideoQAResult` — hook_strength, script_coherence,
shot_list_completeness, timing_score, on_screen_text_suitability,
platform_fit, language_naturalness, factual_accuracy, brand_alignment,
cta_effectiveness, and an optional `cover_creative_quality` that stays
`None` since this app's architecture never produces a cover image yet) —
never the static-image Part A/B checks, and never a claim of video-visual
fidelity, since `VideoConcept.is_rendered_video` stays `False` throughout
(this app renders no video file). `_qa_one_video_variant` runs its own
independent retry/revision loop via `revise_video_concept`.

**Carry-forward requirement 4 — the hybrid-renderer assumption, verified not
rewritten.** Build 2's claim that `render_slide()` already satisfies the
hybrid-renderer architecture was treated as something for QA to verify, not
an unquestioned assumption — Part B's creative critic (`AIProvider.
critique_creative`) is what can actually detect "product appears pasted on",
bad shadow/light integration, wrong product scale, or a scene that conflicts
with the product. No renderer code was rewritten; QA found no evidence of an
actual defect to correct, per the spec's own "only correct renderer behavior
when QA exposes an actual defect" instruction.

**Part A — Technical QA (`run_technical_qa`, deterministic, no AI).**
Dimensions, valid file, PNG format, exact aspect-ratio-vs-`PlatformCreativeSpec`
match, slide-count-vs-carousel-support, cover-required, and folds in the
per-slide mechanical `CreativeQAResult` reports `services/creative/qa.py`
already wrote at render time (imported here as `MechanicalQAResult` to avoid
a name collision with Build 3's own `run_creative_qa`).

**Part B — the multimodal creative critic (`run_creative_qa` /
`AIProvider.critique_creative`, new dedicated Protocol method — never a
generic image param bolted onto `generate_structured`, matching this
codebase's established multimodal-call pattern).** `schemas/qa.py::
CreativeCritiqueResult` scores every dimension the spec named by name
(overall_quality, brand_alignment, product_fidelity, product_prominence,
composition, typography, readability, color_harmony, hierarchy, clutter,
copy_visual_fit, cta_visibility, mobile_readability, originality,
professional_ad_quality, carousel_consistency, platform_fit,
language_naturalness) plus `hard_fails`/`strengths`/`issues`/
`revision_targets`/`rationale`. `_build_creative_context` assembles every
input Part B named (VerifiedProductFacts, brand requirements,
MasterCampaignConcept, PlatformCampaignVariant fields, CampaignCopy,
CreativeDirection, locale, platform, carousel context) into one plain-text
bundle. AI-optional: `None` (never a fabricated scorecard) with no
`ai_provider`.

**Part C — language QA.** `detect_identical_copy_across_languages`
(deterministic — byte-identical copy across two declared languages, above an
8-character minimum so a short shared CTA like "Buy now" isn't flagged) plus
`run_language_qa` (AI, `schemas/qa.py::LanguageQAResult`) covering the six
named hard-fail conditions: wrong language, untranslated text remains,
accidental PT-BR/English mixing, grammar broken badly enough to damage
meaning, obvious literal translation, spelling corruption.

**Part D — platform hard fails (`detect_platform_hard_fails`,
deterministic).** Wrong aspect ratio/size, a video-oriented content type
incorrectly rendered as a static image (or incorrectly represented as a
generated video file), a missing/unreadable slide asset, carousel-exceeds-
platform-constraints, required cover missing.

**Part E — targeted revision, priority-ordered by Part E's own four worked
examples.** `_qa_one_static_variant`'s retry loop picks exactly ONE revision
per failing attempt: a language hard-fail always gets a cheap, targeted
COPY-ONLY revision first (`revise_copy_for_variant` -> `RevisedCopy`,
overwrites only that variant's own first-slide headline/body/cta, never the
shared `CampaignOutput(kind="copy")` row another platform/language reads
from); failing that, a platform/technical hard-fail gets a bare RE-RENDER
with no copy or creative-direction change at all ("Pinterest aspect problem
-> rerender Pinterest variant" — neither caused the problem); only once
neither applies does a genuinely weak/wrong creative issue get a full
`revise_creative_direction_for_variant` (-> fresh `CreativeDirection`,
falls back to the previous direction unchanged, never `None`, on no
provider/failed call) plus a regenerated scene, optionally Best-of-N (Part
G). All three revision paths funnel through the shared `_regenerate_variant_
render` (the same per-variant re-render mechanism, one call away from a bare
re-render by passing `creative_direction=None, copy_override=None`) — never
touches any other variant/platform/language.

**Part F — versioned QA + revision prompts.** Three new module constants
(`QA_PROMPT_VERSION`, `QA_RUBRIC_VERSION`, `REVISION_PROMPT_VERSION`, all
`"1.0.0"`), persisted per attempt on `variant.qa_versions`, plus 6 new
`prompt_registry.py::PROMPT_VERSIONS` entries (`creative_qa_critique`,
`language_qa_critique`, `video_qa_critique`, `targeted_copy_revision`,
`targeted_creative_direction_revision`, `targeted_video_revision`) logged via
`record_prompt_usage`'s new `extra: dict | None` parameter (merged into the
audit `detail`) — every QA/revision AI call site logs `rubric_version`,
`model_role`, and `variant_id` alongside the existing purpose/version/
language/platform fields.

**Part G — Best of N (`_regenerate_with_best_of_n`).** Only applied when
`config.qa_best_of_n > 1` AND the revision is a creative-direction one (a
copy-only or bare re-render would produce identical candidates — never
applied there). Renders N independent candidates, scores each via
`run_creative_qa`, keeps whichever has the highest `overall_quality`, deletes
the losing candidates' files from disk.

**Part H — needs review, and the "never fabricate a score" discipline.**
`AutopilotConfig.qa_max_retries` (default 2) caps how many targeted-revision
rounds a failing variant gets before settling at `qa_status="NEEDS_REVIEW"`
rather than looping forever or silently passing. `_creative_overall_and_fails`
explicitly scores `overall_quality = 0` (never a passing-adjacent middle
value) when no AI provider is available to score creative quality at all —
Pydantic's bare `0` field defaults on the QA score schemas exist ONLY to fail
a genuinely empty/degenerate parse closed, never read as a real "this
creative scored zero" verdict; the actual contract is that the whole result
is `None` when it can't be produced, forcing `NEEDS_REVIEW` over a false
PASS. Every one of the six new AI hooks (`run_language_qa`, `run_creative_qa`,
`run_video_qa`, `revise_copy_for_variant`, `revise_creative_direction_for_
variant`, `revise_video_concept`) follows this codebase's established
AI-optional pattern: `None` (or an unchanged `fallback`) on no provider or a
failed call, wrapped in try/except, never fabricated output.

**`run_qa_stage` — the top-level orchestrator (`services/qa_engine.py`,
new module, one-directional dependency on `orchestrator.py` — imports FROM
it, never the reverse, so there is zero import-cycle risk and Build 1/2's
own tested code paths stay completely untouched).** Iterates every
`PlatformCampaignVariant` a campaign has, skips anything not `RENDERED` or
`SCRIPT_ONLY` (nothing to QA), caches `PlatformAdaptation` per platform, and
dispatches each variant to `_qa_one_static_variant` or `_qa_one_video_variant`
depending on which kind of result it produced. New endpoint:
`POST /api/campaigns/{id}/generate/qa` (background job, mirrors `/generate/
visuals`'s shape — `qa_pass_threshold`/`qa_max_retries`/`qa_best_of_n`/
`use_ai_background` query params, 400s with a clear message if no variants
exist yet). `GET /api/campaigns/{id}/variants` now also returns all 7 new
`qa_*` fields per variant.

Migration: `b2c3d4e5f6a7` (7 new columns on `platform_campaign_variants`,
down_revision `a1b2c3d4e5f6`) — the 3 JSON-typed columns (`qa_hard_fails`,
`qa_evidence_paths`, `qa_versions`) are backfilled row-by-row in Python
rather than a raw-SQL JSON literal default, matching this project's own
established SQLite-JSON1-portability pattern (`f4a8c2e6b1d9`'s backfill is
the precedent) — verified up/down/up. `db.py::_run_migrations`'s
stamp-detection gained a `qa_status`-presence top-of-chain branch (checked
before the Build 2 `platform_campaign_variants`-presence branch, since a
fresh `create_all` build now has both).

Covered by `tests/test_build3_qa_engine.py` (8 tests: platform fit and
language naturalness are both scored; a technically-valid-but-ugly creative
still fails on the threshold alone with an empty hard-fail list; a
wrong-product creative hard-fail blocks PASS regardless of score; a targeted
language revision fixes and passes without ever touching the creative
direction; a targeted platform revision — a corrupted rendered file — is
fixed by a bare re-render without ever touching copy or creative direction;
the retry limit is honored and the variant settles at NEEDS_REVIEW,
persisted per-variant and re-readable from a fresh DB query, with one QA-
evidence JSON file on disk per attempt; plus 2 fast deterministic unit tests
for wrong-aspect-ratio and byte-identical-copy-across-languages) plus the
carry-forward fix's own `tests/test_build3_scene_reuse.py` (3 tests).

**Explicitly out of scope for Build 3** (not silently under-delivered —
next build's territory): a dedicated frontend surface for reviewing
`qa_status`/`qa_scores`/`qa_hard_fails` per variant or triggering
`/generate/qa` (the API is fully wired and tested, but no frontend page
consumes it yet); real video file rendering (carry-forward requirement 3 is
explicit that TikTok/Reels/YouTube Shorts QA stays script/storyboard-only,
matching Build 2's own Part L); and a real `cover_creative_quality` score
for a script-only variant (stays honestly `None` — this app's architecture
never produces a cover image for a video concept yet).

## 5z. Build 4 — Human Approval + Platform/Language Feedback Learning

The fourth build of the multi-build program: lets the owner APPROVE / REJECT
/ REQUEST_REVISION at campaign, platform+language-variant, or individual
asset-slide level, records that decision with full traceability, applies a
requested revision by reusing Build 3's own targeted-revision machinery, and
feeds selective, bounded, de-cloned feedback back into generation. 296 tests
total (up from 281 at the start) — every Build 1-3 test still passes
unchanged, since prompt-grounding is additive text that's `""` for an empty
`review_feedback` table (no new `enable_*` opt-in flag needed, unlike Build
3's `enable_qa_stage` — see "Always-on, not opt-in" below).

**Carry-forward requirement 1 — feedback attaches to the correct variant.**
`ReviewFeedback.level` is one of `CAMPAIGN` (spans every platform/language,
the only level that ever writes `Campaign.human_review_status`),
`PLATFORM_VARIANT`, or `ASSET` (both scoped to one `PlatformCampaignVariant`
row via `platform_campaign_variant_id`, writing ONLY that row's own
`human_review_status`). "Platform variant level" and "language variant
level" from the spec collapse into the single `PLATFORM_VARIANT` value
deliberately — `PlatformCampaignVariant` already keys on
`(target_platform, language, content_type)` jointly, so they're the same
granularity in this schema, not two different things. A feedback action on
Instagram/en therefore never touches Instagram/pt-BR or Pinterest/en by
construction: `record_review_feedback` only ever mutates the one `variant`
row it's given. Proven by `tests/test_build4_review_engine.py::
test_feedback_on_one_variant_does_not_mutate_sibling_variants`.

**Carry-forward requirement 2 — the traceability snapshot.** Every
`reviewed_*` column on `ReviewFeedback` (`reviewed_slide_asset_paths`,
`reviewed_video_concept`, `reviewed_copy_snapshot`, `reviewed_creative_
direction`, `reviewed_qa_status`, `reviewed_qa_scores`, `reviewed_qa_hard_
fails`, `reviewed_qa_attempts`, `reviewed_qa_evidence_paths`, `reviewed_qa_
versions`, `reviewed_prompt_versions`) is a frozen COPY captured at the
moment of the review action, not a live foreign key into mutable state —
because Build 3's own revision mechanism (`_regenerate_variant_render`
et al.) overwrites `PlatformCampaignVariant.slide_asset_paths`/
`creative_direction`/`qa_*` in place with no history of its own, a live
reference would make a past owner decision ambiguous the moment a later QA
rerun or revision touches the same row. `reviewed_prompt_versions` is a
best-effort read-back of the EXISTING `AuditEvent(entity_type=
"campaign_prompt_usage")` rows `record_prompt_usage` (Build 1/3) already
writes (`feedback_selector.py::snapshot_prompt_versions`) — never fabricated,
empty dict when nothing matches. Proven by `test_owner_feedback_references_
exact_reviewed_asset_and_qa_version` (the snapshot stays exactly what was
reviewed even after a later QA rerun mutates the live variant).

**Carry-forward requirement 3 — lineage, not overwritten history.**
`REQUEST_REVISION` never destroys the reviewed version: the ORIGINAL
feedback row's own `reviewed_*` snapshot is the permanent record of what was
rejected and why (requirement 2 above), `apply_requested_revision`
(`services/review_engine.py`) only ever mutates the LIVE `variant` row going
forward (exactly like every pre-Build-4 revision already did), and a later
review action on the same variant auto-links back to the most recent
still-unanswered `REQUEST_REVISION` via `revision_of_feedback_id` — no
explicit parameter needed; `record_review_feedback` finds it by walking this
variant's own feedback history for an unmatched `REQUEST_REVISION` action.
The full chain (reviewed version -> feedback -> requested revision ->
revised version -> new QA result -> new owner decision) is answerable by
walking `reviewed_*` snapshots alongside `revision_of_feedback_id`. Proven
end to end by `test_revision_preserves_reviewed_history_and_lineage` (a real
Strategy->Copy->Visuals pipeline run, a REQUEST_REVISION, an applied
revision that genuinely re-renders to a NEW asset path, and a follow-up
APPROVE that auto-links back).

**Carry-forward requirement 4 — human review overrides automated QA for
approval state, without collapsing into it.** `human_review_status`
(migration `c4d5e6f7a8b9`) is a NEW column on both `Campaign` and
`PlatformCampaignVariant`, genuinely independent of `qa_status` (Build 3) and
`status` (the production-pipeline stage) — three separate axes per row.
`QA_PASS + OWNER_REJECTED` and `QA_NEEDS_REVIEW + OWNER_APPROVED` are both
valid, real, representable states; `record_review_feedback` writes ONLY
`human_review_status`, never `qa_*`, on a plain APPROVE/REJECT (proven by
`test_approve_and_reject_never_mutate_qa_state`) — `qa_*` only ever changes
as the honest side effect of `apply_requested_revision` triggering a REAL
re-render + re-QA. `Campaign.human_review_status` is written ONLY by a
`level="CAMPAIGN"` action, never aggregated automatically from variant
activity — `GET /api/campaigns/{id}/review-summary` is the read-only rollup
across variants instead, computed fresh on every call, never written back.

**Carry-forward requirement 5 — selective, bounded feedback retrieval.** New
leaf module `services/feedback_selector.py` (no dependency on
`orchestrator.py`/`qa_engine.py` — this is what lets `orchestrator.py` itself
import it for prompt-grounding without an import cycle, since
`review_engine.py` separately imports FROM `orchestrator.py`).
`select_feedback_examples` FILTERS (not just ranks) by platform/language —
feedback scoped to a specific platform/language that doesn't match the
current generation context is excluded outright, never merely ranked lower
(the spec's own worked example: repeated Instagram PT-BR "Too much text"
must never blindly affect Pinterest English) — then ranks what survives by
how many of (platform, language, category, product, objective, content_type)
it shares, deduplicates by `reason_code` (keeping the most relevant/recent
instance of each), and caps at `AutopilotConfig.feedback_examples_limit`
(default 5) positive and `limit` negative examples. Proven by
`test_feedback_selector_is_selective_by_platform_and_language` and
`test_feedback_selector_result_count_is_bounded`.

**Carry-forward requirement 6 — feedback never becomes a product fact.**
`record_review_feedback` never touches `verified_product_facts` at all —
Build 1's VERIFIED PRODUCT FACT ≠ RESEARCH INSIGHT ≠ CREATIVE FEEDBACK
separation stays fully intact by construction, not by a guard that could be
bypassed. A rejected campaign's invented claim (`reason_code=
"inaccurate_claim"`) is stored as a negative creative/factual example on
`ReviewFeedback` itself, never written into `VerifiedProductFact`. Proven by
`test_feedback_never_mutates_verified_product_facts`.

**Carry-forward requirement 7 — positive examples guide without cloning.**
`feedback_selector.format_feedback_for_prompt` is deliberately
characterization-only for positive examples: platform/language context plus
the approved reason label, NEVER the reviewed variant's literal headline/
body/CTA text (which DOES live in `ReviewFeedback.reviewed_copy_snapshot`,
for traceability — it's simply never read back into the prompt-grounding
string). This is a structural guarantee, not a prompt instruction the model
could ignore. Novelty (`CampaignFingerprint`/`_compute_novelty`/
`too_similar_threshold`) is untouched entirely — Build 4 only adds text
elsewhere, never touches fingerprinting logic — so "NEW + GOOD + PLATFORM
APPROPRIATE" stays exactly as novel as before. Proven by
`test_positive_examples_work_without_verbatim_text` (a distinctive headline
is captured in the snapshot but never appears in the formatted prompt
string) and `test_novelty_remains_functional_with_feedback_present` (an
exact-repeat strategy is still correctly rejected as "too similar" with real
`ReviewFeedback` rows on file for the brand).

**Carry-forward requirement 8 — video-concept feedback stays format-aware.**
For a `SCRIPT_ONLY` variant, `level="ASSET"` feedback's `asset_ref` must be
one of `hook`/`script`/`shot_list`/`timing`/`on_screen_text`/`caption`/
`cover` (`review_engine.SCRIPT_ASSET_REFS`) — never a rendered-slide-style
reference (`_validate_asset_ref` raises `ValueError` otherwise), so the API
never exposes a control implying a rendered video file exists.
`apply_requested_revision` dispatches a `SCRIPT_ONLY` variant to `qa_engine.
revise_video_concept` exclusively, never attempts a render, and
`slide_asset_paths` stays `[]` throughout. Proven by
`test_script_only_variant_feedback_stays_distinct_from_rendered_asset_
feedback` and `test_script_only_revision_updates_only_the_video_concept`.

**Carry-forward requirement 9 — QA and human review stay separate in the
API.** Every `/review*` endpoint (below) writes/reads `ReviewFeedback` and
`human_review_status` only; none ever mutates `qa_scores`/`qa_hard_fails`/
`qa_evidence_paths`/`qa_versions`/`qa_notes` directly. The only path that
changes `qa_*` at all is `apply_requested_revision`'s real re-render calling
back into `qa_engine.py`'s own tested render primitives (the honest
consequence of actually fixing something), never the review-recording call
itself.

**Reason-code -> revision-kind mapping (`data/feedback_reasons.py`).** The
spec's 20 named reasons (plus `other`) each map to one of four revision
kinds — `copy` (`too_much_text`, `too_formal`, `unnatural_portuguese`,
`unnatural_english`, `cta_weak`, `inaccurate_claim`), `creative_direction`
(`too_generic`, `looks_ai_generated`, `poor_typography`, `product_too_
small`, `wrong_colors`, `does_not_match_brand`, `does_not_feel_japanese`,
`too_corporate`, `boring_concept`, `wrong_platform_style`, `pinterest_
creative_too_horizontal`, `too_similar_to_previous_campaign`),
`video_concept` (`content_unsuitable_for_tiktok`), or `rerender`
(`product_inaccurate` — a source-photo/compositing problem no amount of
re-prompted direction fixes automatically; `other` — a safe default that
never guesses). `apply_requested_revision` reuses Build 3's existing
`revise_copy_for_variant` / `revise_creative_direction_for_variant` /
`_regenerate_variant_render` / `_regenerate_with_best_of_n` /
`revise_video_concept` for the actual mechanics — never a second, parallel
revision pipeline.

**Always-on, not opt-in (unlike Build 3's `enable_qa_stage`).**
Feedback-grounding text injection into `run_copy_stage`'s per-language
`CampaignCopy` call and into `_generate_creative_direction`'s prompt is
always active, no new `AutopilotConfig.enable_*` flag — because unlike Build
3's QA stage (which needed a NEW `AIProvider.critique_creative` Protocol
method no existing fake test provider implements), feedback-grounding only
appends plain text to the SAME `user=` string already passed to the
already-used `generate_structured` method. An empty `review_feedback` table
produces `feedback_note = ""`, byte-for-byte identical to pre-Build-4
behavior — verified by the full 281-test Build 1-3 suite passing unchanged.
Deliberately scoped to just those two call sites — `carousel_plan`/
`video_concept` generation do NOT get feedback-grounding this build,
documented as explicitly out of scope below, not a silent gap.

**New API surface (`app/api/campaigns.py`).** `POST /api/campaigns/{id}/
review` — the one unified review action for all three levels (body: `level`,
`action`, `platform_campaign_variant_id`, `asset_ref`, `reason_code`,
`reason_text`, `use_ai_background`); a `REQUEST_REVISION` against a specific
variant additionally kicks off `apply_requested_revision` as a background job
(mirrors `/generate/qa`'s shape) — a campaign-level `REQUEST_REVISION`
records the feedback only, deliberately never auto-applying "revise
everything" across every platform/language at once (matches Build 3's own
"never a blind full-campaign regeneration" discipline). `GET /api/campaigns/
{id}/review-feedback` — every `ReviewFeedback` row, newest first, lineage
intact. `GET /api/campaigns/{id}/review-summary` — `campaign.human_review_
status` plus a read-only per-variant rollup, computed fresh, never written
back (requirement 4's "preserve child truth"). `GET /api/campaigns/{id}/
variants` now also returns `human_review_status` per variant.

Migration: `c4d5e6f7a8b9` (down_revision `b2c3d4e5f6a7`) — the new
`review_feedback` table (21 columns: level/asset_ref/action/reason_code/
reason_text, 7 denormalized filter/rank context columns, 11 `reviewed_*`
snapshot columns, `revision_of_feedback_id` lineage FK) plus
`campaigns.human_review_status`/`platform_campaign_variants.human_review_
status`. `db.py::_run_migrations`'s stamp-detection gained a
`review_feedback`-table-presence top-of-chain branch (checked before the
Build 3 `qa_status`-presence branch). `tests/test_db_migrations.py`'s
existing never-tracked-database test was extended to also strip Build 4's
new column/table before replaying migrations forward — the same trap every
earlier build's own addition to that test had to avoid (a `create_all`-built
fixture already has the CURRENT schema, so a stamp at an old revision plus a
forward replay would otherwise hit "duplicate column name").

Covered by `tests/test_build4_review_engine.py` (15 tests spanning every
BUILD 4 TESTS item 1-9 and every carry-forward requirement 10 test item
1-9; item 10 — "all existing 281 tests remain green" — verified by the full
suite, 296 passed).

**Explicitly out of scope for Build 4** (not silently under-delivered — next
build's territory): a dedicated frontend surface for submitting reviews or
browsing feedback history (the API is fully wired and tested, but no
frontend page consumes it yet); feedback-grounding wired into
`carousel_plan`/`video_concept` generation (only `CampaignCopy` and
`_generate_creative_direction` get it this build — see "Always-on, not
opt-in" above); a campaign-level `REQUEST_REVISION` automatically fanning out
revisions to every platform/language variant (records feedback only; the
owner is expected to follow up with variant-level requests); and any
computed "diff" API between a pre- and post-revision version (the snapshot
data makes this fully answerable from stored data, but no diff endpoint is
built this round).

## 5z-2. Build 4 carry-forward — feedback grounding completed for carousel/video/adaptation

Closes the one gap Build 4 itself left open ("Explicitly out of scope for
Build 4" above): `carousel_plan`, `generate_video_concept`, and
`_resolve_platform_adaptation` (`services/orchestrator.py`) now all receive
the same selective, bounded `feedback_note` (`services/feedback_selector.py`
— unchanged) that `CampaignCopy`/`_generate_creative_direction` already got.

- **Carousel planning**: the same `feedback_note` `run_copy_stage` already
  computed per-language for `CampaignCopy` is now also appended to both
  `CarouselPlan` prompts (discovery and non-discovery branches) — Instagram/
  pt-BR "too much text" feedback now reaches Instagram/pt-BR carousel
  planning, never Instagram/en's.
- **Video concepts**: `generate_video_concept` gained a `feedback_note`
  parameter, resolved by its one caller (`_render_additional_platform_
  variants`) per (platform, language) — e.g. repeated TikTok/pt-BR "weak
  hook" feedback now grounds future TikTok/pt-BR script generation, never a
  different platform (YouTube Shorts) or the same platform's other language.
- **Platform adaptation**: `_resolve_platform_adaptation` gained a `feedback_
  note` parameter, resolved PLATFORM-ONLY (`language=""`) since a
  `PlatformAdaptation` is generated once per platform and shared across every
  language that platform targets — a Pinterest-scoped feedback row reaches
  Pinterest's one `PlatformAdaptation` call regardless of which language it
  was originally filed under, but never Instagram's.

All three still go through the unchanged `format_feedback_for_prompt`
(characterization-only, never verbatim rejected/approved copy — carry-forward
requirement 2, still holds). Covered by `tests/test_build4_completion.py` (5
tests: matching-context grounding + cross-platform/cross-language exclusion
for each of the three call sites). Full suite: 301 passed (296 + 5).

## 6a. Build 5 — Golden Benchmark + Prompt Registry + Multi-Platform Regression

Objective: prevent a future prompt/model/code change from silently making
any platform or language worse, using real historical owner-feedback
evidence (Build 4) as the ground truth QA gets checked against.

**Part A — prompt registry completed.** `services/prompt_registry.py`
already existed (Build 1); `PromptSpec` gained `platform_applicability`
(`[]` = every platform), `language_applicability` (`[]` = every language),
and `active` (bool). `models/platform.py::PromptVersion` gained matching
columns. `video_concept`/`video_qa_critique`/`targeted_video_revision` are
the only purposes scoped to `["tiktok", "youtube_shorts"]` — every other
purpose applies everywhere, honestly reflecting this codebase's actual
architecture rather than a guessed scope. `GET /api/benchmarks/prompt-
registry` exposes the live registry.

**Part B — `BenchmarkCase`** (`models/benchmark.py`): brand/product/
category/platform/content_type/language/objective/audience identity, source
asset paths, a FROZEN `VerifiedProductFact` snapshot (never a live FK — a
case stays reproducible even if the real facts are edited later), expected
truths/prohibited claims/expected creative characteristics, a frozen
baseline-output snapshot, and an `owner_rating` — all copied once from a
specific `ReviewFeedback` row's own immutable snapshot when
`source_feedback_id` is given (`SET NULL` on delete, never mutating that
row). `services/benchmark_engine.py::curate_benchmark_case` is the ONE
function that ever inserts a row here — never automatic from a plain
APPROVE/REJECT action (carry-forward requirement 7 / Part G's own "explicit
membership" rule, proven by `test_benchmark_case_membership_is_explicit_
not_automatic`).

**Part C/F — `BenchmarkRun`**: one execution of the REAL pipeline (Strategy
-> Copy -> Visuals -> QA, via a throwaway `Campaign` — no second, parallel
generation path) against a case, freezing `prompt_versions_snapshot`,
`model_role_snapshot`, `qa_status` AND `human_review_status` as two SEPARATE
columns (carry-forward requirement 4 — a run can honestly be `QA_PASS` +
`human_review_status="REJECTED"`), the raw `qa_scores`, the platform-
weighted `weighted_score`, and a best-effort `cost_breakdown` (honestly
zero/empty when no `AIUsage` rows exist yet for that campaign — never a
fabricated estimate). Four `BENCHMARK_TEST_MODES`:

- `OFFLINE` — a built-in zero-network `_OfflineProvider` (NOT a bare `None`
  — `run_strategy_stage`/`run_copy_stage` always require a real `ai_provider.
  generate_structured` call with no deterministic fallback of their own,
  unlike Visuals/QA). Genuinely makes zero paid API calls regardless of what
  provider a caller passes in (proven by `test_offline_mode_never_calls_the_
  ai_provider`, which hands in a provider that raises on every method).
- `MOCK` — a caller-supplied fake provider (test-only; not exposed over the
  API, since it has no meaning as a JSON body).
- `LOW_COST_SMOKE` — a real provider, cost-limited config (one slide, no AI
  images/recreation, no QA retries).
- `LIVE_FULL` — a real provider, full config.

Re-running the SAME case repeatedly (the whole point of a regression
comparison) would otherwise trip the Strategy stage's own novelty/exact-
repeat guard against the case's OWN prior run — `run_benchmark_case` deletes
its own throwaway campaign's `CampaignFingerprint` immediately after Visuals
finishes, since a benchmark campaign was never real marketing history.

**Part D — platform-specific scoring** (`data/benchmark_scoring.py`):
documented, named weight tables (never opaque/computed) over the SAME
dimension names Build 3's QA engine already produces — Pinterest weights
composition/originality/platform_fit higher (discovery appeal), Instagram
weights composition/carousel_consistency/professional_ad_quality higher,
LinkedIn weights readability/professional_ad_quality higher, TikTok/YouTube
Shorts (video, via `VideoQAResult`) weight hook_strength/script_coherence
higher — every other platform gets a documented balanced default.
`compute_platform_weighted_score` normalizes by the weights actually
matched, so a partial scorecard never silently drags toward zero.

**Part E/G — regression reporting** (`compare_runs`/`build_regression_
report`): a pairwise diff read entirely from each run's own frozen columns,
rolled up overall AND independently by platform AND by language — proven by
`test_regression_report_tracks_platform_and_language_independently`, which
regresses PT-BR while improving English on the SAME platform and asserts
neither hides the other.

**Owner-agreement metrics** (carry-forward requirement 5):
`compute_owner_agreement_report` reads `ReviewFeedback.reviewed_qa_status`
(the frozen snapshot — never today's live `qa_status`, carry-forward
requirement 3's own discipline applied here) against `ReviewFeedback.action`
to report plain counts — owner approved/rejected, QA pass/fail, agreement/
disagreement, false-positive creative pass (QA PASS + owner REJECTED),
false-negative creative fail (QA FAIL/NEEDS_REVIEW + owner APPROVED) —
always with an explicit "descriptive counts only, never a statistically
meaningful accuracy percentage" caveat, regardless of sample size.

**Video benchmarks stay honest** (carry-forward requirement 9): the TikTok/
YouTube-Shorts weight tables only ever reference `VideoQAResult`'s real
dimensions (hook/script/shot-list/timing/on-screen-text/CTA/language/factual
accuracy) — never a "visual quality"/"motion quality" dimension implying a
rendered video file exists, since none ever does.

**Migration**: `d5e6f7a8b9c0` (down_revision `c4d5e6f7a8b9`) — `benchmark_
cases`/`benchmark_runs` tables plus `prompt_versions.platform_applicability`/
`language_applicability`/`active`. No backfill needed for the new
`prompt_versions` columns: that table is re-seeded from scratch (idempotent
upsert by `purpose`) on every app startup.

**API** (`api/benchmarks.py`): `POST/GET /api/benchmarks/cases`,
`GET /api/benchmarks/cases/{id}`, `POST /api/benchmarks/cases/{id}/runs`
(background job, `OFFLINE`/`LOW_COST_SMOKE`/`LIVE_FULL` only — `MOCK` is
test-only), `GET /api/benchmarks/cases/{id}/runs`, `GET /api/benchmarks/
runs/{id}`, `POST /api/benchmarks/compare`, `POST /api/benchmarks/regression-
report`, `GET /api/benchmarks/owner-agreement`, `GET /api/benchmarks/prompt-
registry`.

Covered by `tests/test_build5_benchmark.py` (13 tests spanning every BUILD 5
TESTS item 1-10 and carry-forward requirements 3-10's own remaining test
list items). Full suite: 314 passed (301 + 13).

**Explicitly out of scope for Build 5** (next build's territory): `AIUsage`
population at every real AI-provider call site (the model and the
`cost_breakdown` reader both exist and are honest about reporting zero until
this is wired in); a dedicated frontend surface for curating cases or
viewing regression reports (API-only this round); automatic CI-gate wiring
("fail the build on a detected regression" — the data and comparison logic
exist, but nothing calls them from a CI hook yet).

## 6a-2. Build 5 repair — prompt + creative-system traceability

The user accepted Build 5 provisionally but flagged one real gap before
authorizing Build 6: `IMAGE_PROMPT_VERSIONED=Not tracked` in the completion
packet was honest but incomplete — scene/image generation is the one major
generation step Build 5's own prompt registry (Part A) never versioned, and
a `BenchmarkRun`'s traceability, while real, wasn't yet a single complete
answer to "what exact generation system produced this?" without also
knowing which prompt-registry/renderer/template versions were live at the
time. Five repairs, all additive — no redesign of the benchmark system
itself, no regression against the 314 tests already passing.

**Repair 1 — a versioned scene-generation RECIPE, not a frozen literal
prompt.** The spec's own instruction was explicit: don't try to store every
fully-expanded per-slide dynamic prompt as one static string (impossible —
`generate_ai_background`/`recreate_creative_image`'s actual text is built
per slide from `CreativeDirection`, `MasterCampaignConcept`, brand style,
and the product-safety/claims-safety rules baked into those functions'
docstrings). Instead, `services/prompt_registry.py` gained a new
`"scene_generation"` `PromptSpec` (version `"1.0.0"`) that versions the
RECIPE — which inputs compose the prompt, what's structurally forbidden
(no product label/logo/copy text in `generate_ai_background`'s
backdrop-only call; the accuracy/no-fabricated-claims rules in
`recreate_creative_image`), how product-preservation is enforced. Bump this
version when that composition logic itself changes, never on a wording-only
tweak. Deliberately recorded with `language=""` (mirroring
`platform_adaptation`'s own precedent) — a scene's lighting/composition
never varies by copy language.

`record_prompt_usage(purpose="scene_generation", ...)` is called at every
real call site that actually produced an image (not on a cache-hit reuse,
which produced nothing new to attribute a version to): `run_visuals_stage`'s
primary-combo loop (both the full-recreation and background-only branches),
`_render_additional_platform_variants`'s per-slide loop (same two
branches), and the manual `/campaigns/{id}/slides/render` endpoint —
following the SAME established pattern as `platform_adaptation`/
`creative_direction` (recorded at the call site with campaign/platform/
language context in scope, never inside the low-level generation function
itself, which has neither `campaign_id` nor `db`-session-adjacent context
to record against). `extra={"mode": "full_recreation"|"background_only",
"verified": ...}` distinguishes which of the two scene-generation paths
actually ran and, for full recreation, whether the fidelity gate verified
it.

**Repair 2 — `BenchmarkRun.creative_system_snapshot`, a complete answer in
one field.** New JSON column (migration `e6f7a8b9c0d1`, down_revision
`d5e6f7a8b9c0`) alongside the pre-existing `prompt_versions_snapshot`/
`model_role_snapshot` — deliberately additive, not a replacement.
`services/benchmark_engine.py::build_creative_system_snapshot(db, *,
campaign_id, platform, language, content_type, quality_mode)` assembles:
a nested copy of `snapshot_prompt_versions`'s per-purpose dict (which
already includes `scene_generation` now, AND whichever targeted-revision
purpose actually fired for this run — see Repair 4), plus three version
identities that mechanism doesn't cover on its own —
`verified_product_facts_resolver_version` (new constant in
`services/product_facts.py`), `renderer_version` (new constant in
`services/creative/renderer.py`), `template_version` (new constant in
`services/creative/templates.py`) — plus this run's own platform/language/
content_type/quality_mode. Deliberately does NOT duplicate
`model_role_snapshot` (its own column already answers "which model per
role") — the repair spec's own "do not unnecessarily duplicate large blobs"
instruction, honored by keeping the new field to only what the other two
columns don't already cover.

**Repair 3 — renderer/template version identities, kept deliberately
small.** Per the repair's own "do not create a giant framework" — two plain
string constants, not a versioned sub-registry: `RENDERER_VERSION = "1.0.0"`
(`services/creative/renderer.py`, identifying the Playwright renderer's own
production mechanics — the dedicated-thread/Proactor bridge, exact-pixel
capture, the text-overflow probe) and `TEMPLATE_REGISTRY_VERSION = "1.0.0"`
(`services/creative/templates.py`, identifying the template/layout SYSTEM's
own composition mechanics — not a per-template version, since `template_id`
already identifies which template rendered a slide). Bump either when its
own mechanism changes in a way that could make an old benchmark baseline's
output not directly comparable to a new run's; never for an unrelated new
template or a one-off CSS tweak.

**Repair 4 — revision traceability, already structurally correct, now
proven by a test.** `qa_engine.py`'s targeted-revision calls
(`targeted_copy_revision`, `targeted_creative_direction_revision`,
`targeted_video_revision`) already called `record_prompt_usage` with their
OWN distinct purpose key (never overwriting `campaign_copy`/
`creative_direction`/`video_concept`'s own original-generation version) —
this was true before the repair, a direct consequence of `snapshot_prompt_
versions`'s most-recent-wins-PER-PURPOSE design (Build 4). The repair
verified this holds through a benchmark run specifically: `test_build5_
repair.py::test_revision_purpose_is_traced_in_the_benchmark_runs_snapshot`
forces one language-QA failure + revision cycle inside `run_benchmark_case`
and asserts BOTH `"campaign_copy"` and `"targeted_copy_revision"` land as
separate keys in the resulting run's `creative_system_snapshot["prompt_
versions"]` — no code change was needed here, only the proof.

**Repair 5 — owner/QA agreement, already correct, now proven exhaustively.**
`compute_owner_agreement_report` (Build 5) already distinguished all four
QA-status x owner-decision combinations as plain counts
(`agreement_count`/`false_positive_creative_pass`/`false_negative_creative_
fail`/`disagreement_count`) with the required non-statistical-significance
caveat. The repair added `test_owner_agreement_report_exposes_all_four_
classification_counts`, which — unlike the existing Build 5 test, which only
asserted the aggregate `agreement_count` — explicitly checks `owner_
approved`/`owner_rejected`/`qa_pass`/`qa_fail_or_needs_review` too, covering
every field the repair spec named by name. No production code change.

**A genuine architectural discovery made while writing Repair 1's own
test.** `CreativeDirection` is ONLY ever AI-generated on the
additional-platform-variant path (`_render_additional_platform_variants`)
— `run_visuals_stage`'s primary-combo loop never calls `_generate_creative_
direction` at all, it only ever passes `creative_direction=None` to
`generate_ai_background`. Since a `BenchmarkRun`'s throwaway campaign is
ALWAYS single-platform/single-language by design (Part H: "Instagram/pt-BR
and Instagram/en are separate executions"), a benchmark run's own
`PlatformCampaignVariant` is always the "primary combo, already rendered,
just record it" row (see `run_visuals_stage`'s own `if platform ==
primary_platform and language == primary_language` branch) — which never
sets `creative_direction` on that row at all (it stays the model's default
`{}`). This means `CreativeDirection` is currently NEVER AI-generated
during a benchmark run, only the deterministic-background/scene-generation-
only path is. This is not a bug this repair introduced or needed to fix —
it's a pre-existing, honest consequence of Build 5's own single-platform/
single-language design — but it's worth knowing for whichever future build
wants a benchmark case that exercises `CreativeDirection`'s AI path: today,
proving that requires calling `run_visuals_stage` directly against a real
multi-language/multi-platform campaign (as `test_dynamic_creative_
direction_content_is_unaffected` does), not `run_benchmark_case`.

Migration: `e6f7a8b9c0d1` (down_revision `d5e6f7a8b9c0`) — one new nullable
JSON column on `benchmark_runs`, no backfill (an existing run honestly shows
an empty `{}` snapshot rather than a fabricated one). `db.py::_run_
migrations`'s stamp-detection gained a `creative_system_snapshot`-column-
presence top-of-chain branch. `tests/test_db_migrations.py`'s existing
never-tracked-database test needed no new strip line (the whole
`benchmark_runs` table is already dropped and replayed forward by the
existing Build 5 strip block) but gained a post-migration assertion that
the new column exists after replay, proving the migration CHAIN — not just
its first link — replays correctly.

10 new tests in `tests/test_build5_repair.py`, covering the repair spec's
own numbered TEST REQUIREMENTS list end to end. Full suite: 324 passed (314
+ 10) — every Build 1-5 test still passes unchanged.

## 6a-3. Build 6 — Production Integration + Multi-Platform Hanna Acceptance

Two things Build 6 actually needed that nothing before it had wired up:
**real cost/usage capture** (`AIUsage` existed since round 1 but no code
path ever wrote a row to it), and **a genuine, real-Hanna-data acceptance
suite** proving the whole pipeline works end to end across platforms and
languages — not just that its individual pieces pass in isolation.

**Cost/usage capture (`services/usage_tracking.py`, new)** — `AIUsage`
gained `platform`/`language`/`content_type` columns (migration
`f7a8b9c0d1e2`, right after `e6f7a8b9c0d1`) so a usage row can be attributed
to a specific `PlatformCampaignVariant`, not just a campaign as a whole.
`services/ai/openai_provider.py::OpenAIProvider` — the only implementation
that ever makes a real network call — now accumulates one usage event
(real token counts straight from the Responses API's `usage` field for a
text call; an image count for an Images API call) per real call, drained via
a new `drain_usage_events()` method; approximate published per-model pricing
lives alongside it (`_TEXT_PRICING_USD_PER_1M_TOKENS`,
`_IMAGE_PRICING_USD_PER_IMAGE` — an unrecognized model prices at `$0`, never
a guess). `usage_tracking.record_stage_usage` is called at the SAME 19 call
sites `record_prompt_usage` already logs from (orchestrator.py x13,
qa_engine.py x6) — never inside a low-level generation helper — draining
whatever the provider(s) accumulated since the last drain and writing one
`AIUsage` row per real event. `build_campaign_cost_report` (what
`benchmark_engine.py`'s pre-existing `_cost_breakdown_for_campaign` now
delegates to, kept as a one-line wrapper for backward compatibility) adds
`by_operation` and `by_variant` breakdowns on top of the pre-existing
`total_usd`/`image_generation_usd`/`text_generation_usd`/`call_count`/
`usage_recorded` shape. A fake test provider never implements
`drain_usage_events` (or implements it returning `[]`), so every one of the
324 pre-Build-6 tests — and every Build 6 test using a fake provider —
correctly records zero cost; this is the honest result of never having made
a real call, not a bug. See `tests/test_usage_tracking.py` (8 tests, unit
coverage of the provider-side accumulation and the report aggregation) and
`scripts/run_live_acceptance.py` (new — the only thing that can produce a
REAL dollar figure, since this whole development sandbox has no OpenAI key
and no network path to the OpenAI API).

**Real Hanna acceptance (`tests/test_build6_acceptance.py`, new, 5 tests)**
— exercises the real Strategy -> Copy -> Visuals -> QA -> Review pipeline
(never a mocked-out shortcut) against Hanna's own real, canonical brand/
product identity (Hanna From Japan; Melano CC Essence, canonical ID
`HANNA-PROD-000006` — see `claude/hanna-gpt-system/01-company-and-service-
profile.md` / `02-canonical-product-catalog.md` in the Claude Project),
using a deterministic fake provider for the same reason every other test
file in this project does (no real network path from this sandbox). Covers:
`VerifiedProductFact` grounded in only what the canonical catalog actually
permits (identity/category/country-of-origin), with every formulation
field the catalog forbids inventing genuinely absent AND reported in
`missing_information`, never guessed; a real Instagram+Facebook x pt-BR+en
campaign sharing one `MasterCampaignConcept`, proving `CreativeDirection`'s
AI-generation path fires for every non-primary combo (the Build 5 repair's
own documented architectural fact — a benchmark campaign structurally can
never reach this path, so this test uses the real multi-platform pipeline
directly instead); same-platform pt-BR/en scene reuse
(`shared_scene_source`) via the real cache-matching logic, not a shortcut;
a forced first-attempt language-QA failure on exactly one variant (Facebook/
en), proving its three siblings' `qa_status`/`qa_scores` are completely
unaffected and that the real outcome (recovered to PASS, or genuinely
NEEDS_REVIEW with real `qa_hard_fails`) is reported honestly, never silently
smoothed over; `build_creative_system_snapshot` called directly against
this real (non-benchmark) campaign, proving POPULATED evidence from an
actual run, not merely that the database columns exist; a TikTok variant
proven `SCRIPT_ONLY`/`is_rendered_video=False` with QA scoring only the
structured text dimensions, never a rendered-video claim; DRAFT/STANDARD/
PREMIUM resolving to materially different `(model, quality_tier)` pairs
(config-level, per the spec's own explicit allowance); and the full human-
review loop (generation -> QA -> `REQUEST_REVISION` -> targeted revision ->
QA rerun -> `APPROVE`) with complete, inspectable history (old QA score, new
QA score, why the revision was requested, revision lineage, final approval).

**Honest, explicitly-documented gaps** (not silently glossed over — see
`docs/marketing-os-creative-quality-handoff.md` §11 for the full list): no
dedicated pre-flight generation-scope-estimate endpoint yet;
`quality_mode="premium"` does not automatically raise `qa_best_of_n`/
`qa_max_retries` (the mechanism exists, the auto-link doesn't);
`estimated_cost_usd` is best-effort against a hardcoded, point-in-time
pricing table (real token/image COUNTS are always exact); and — the
central honesty point of this whole build — this development sandbox
cannot execute `scripts/run_live_acceptance.py` itself, so every
`LIVE_ACCEPTANCE`-shaped figure in the Build 6 completion packet reflects
that plainly rather than fabricating a pass.

Full suite: 337 passed (324 + 5 acceptance + 8 usage-tracking) — every
Build 1-5 test still passes unchanged. New Codex handoff document:
`docs/marketing-os-creative-quality-handoff.md`.

## 6. Windows-first filesystem handling

All path handling goes through `pathlib.Path`; `SOURCE_ASSET_ROOT` and `OUTPUT_ROOT` are
read from config as raw strings and immediately wrapped in `Path(...)`, which handles
`C:\Marketing\Source`-style paths natively on Windows and POSIX paths in dev/test on
Linux/Mac. The scanner opens files read-only and never writes, moves, or deletes
anything under `SOURCE_ASSET_ROOT` — enforced by a dedicated test
(`tests/test_source_immutability.py`) that hashes every fixture before and after a full
simulated scan + campaign run and asserts byte-for-byte equality.

## 7. Job engine (MVP shape)

For a single local user, a full task queue is unnecessary infrastructure. `app/services/jobs.py`
persists a `jobs` row per long-running operation and offers two ways to run it:
`run_job(job_id, fn)`, awaited directly by the caller so the HTTP request itself
returns only once the job finishes; and `run_job_in_background(job_id, fn)`, which
schedules it as a fire-and-forget `asyncio.create_task` and returns immediately,
leaving the caller to poll `GET /api/jobs/{id}`. All four `/generate*` endpoints
(section 5k, round 11) now use the background path — the initial MVP trade-off of
blocking on `run_job` was revisited once Autopilot/Advanced-mode runs proved long
and frequent enough to be worth real polling UI instead of a spinner tying up the
whole request. Either way `status`/`progress`/`step` are updated on the same
`jobs` row as the job runs, so nothing about the job-tracking design itself needed
to change — only which of the two existing functions each endpoint calls, plus
moving the endpoints' own pre-job validation (section 5k) to run synchronously
*before* `run_job_in_background` is called, since a background job's failures
only ever surface asynchronously. This is intentionally simple per the brief's "no
Redis/Kafka/Celery" constraint; if concurrency needs grow, the same table/
interface supports swapping the runner for a real queue without changing callers.
As of round 14, `_execute_job`'s failure handling also resets a campaign stuck
in a mid-stage-only status (`RESEARCHING`/`GENERATING`) back to `FAILED` when
its job fails unexpectedly — see section 5n.

## 8. Security / secrets

`OPENAI_API_KEY` and any future publishing tokens live only in `.env` / the backend
process; the `/api/settings` endpoint returns a masked status (`configured: true/false`)
and never echoes the key back to the frontend. `.env` is gitignored; `.env.example`
ships with empty values and comments.

## 9. Prompt management

`backend/app/prompts/{research,vision}/v1.md` are early placeholder files from before
the orchestrator existed and are not actually loaded by anything — every real prompt
in this app (strategy, creative brief, campaign copy, carousel plan, image
recreation/background) is built as a plain Python `system`/`user` string inside
`services/orchestrator.py`, passed straight to `AIProvider.generate_structured`'s
fixed Protocol signature (`system: str, user: str, schema: type, model: str` — no room
for extra structured kwargs, see `services/ai/base.py`), not loaded from a file.

`prompt_versions` (the DB table) existed since round 1 but was genuinely dead code —
defined in the model and schema, never read or written — until Build 1 (Part I) made
it real: `services/prompt_registry.py` holds a small `PROMPT_VERSIONS` registry
(purpose → version/file_path/variables/change_notes, one entry per tracked prompt —
today `campaign_copy` and `carousel_plan`), `ensure_prompt_versions_seeded(db)` upserts
those into `prompt_versions` on every startup (wired into `services/seed.py::seed_all`,
same idempotent-upsert pattern as the Strategy Library), and `record_prompt_usage(db,
campaign_id, purpose, language, platform)` logs every actual generation to
`audit_events` (`entity_type="campaign_prompt_usage"`) so a campaign's copy can be
traced back to exactly which prompt version, in which language, for which platform,
produced it — without changing the AI-call signature itself.

## 10. Build 6 REPAIR — targeted live-acceptance repair

A real live-acceptance run (`scripts/run_live_acceptance.py`, on the owner's own
machine, real OpenAI key) surfaced seven concrete architectural gaps a fake-provider
test suite couldn't catch on its own. See `docs/campaign-pipeline.md`'s own "Build 6
REPAIR" section for the full per-defect writeup; in short, this added: a pre-generation
`SourceProductIdentityCheck` gate (`services/orchestrator.py::_enforce_source_product_
identity_gate`, wired into `run_visuals_stage`) distinct from the existing post-
generation `ProductFidelityCheck`; a shared `_claims_boundary_instruction()` threaded
into every copy/concept/revision prompt so research context can never silently become
a stated product fact; a SHA256-hash-based duplicate/no-effect revision guard and a
deterministic (no-AI) text-overflow copy-shortening path in `services/qa_engine.py::
_qa_one_static_variant`; one retry in `generate_video_concept` before `SCRIPT_
UNAVAILABLE`; an exact-acceptance-matrix fix confined entirely to `scripts/run_live_
acceptance.py` (one campaign per platform group, never a change to `run_visuals_
stage`'s own real `target_platforms x languages` cross-product architecture); and a new
`ai_usage.scope` column (`"campaign_global"` vs `"variant"`) plus `--estimate-only`/
`--max-budget-usd`/`--smoke` cost-preflight flags on the live-acceptance script.
