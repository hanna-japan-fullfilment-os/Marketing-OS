# Marketing Operating System

A local-first Marketing Operating System: a real database of your product photos,
brand rules, campaigns, research, and posting opportunities — built to research,
strategize, produce, and track marketing campaigns without ever repeating itself, and
without ever touching your original source photos.

This replaces the earlier Streamlit prototype with the production architecture
described in `docs/architecture.md`. The prototype's `app.py`/`requirements.txt`/
scheduling scripts remain in this project's own history for reference; its
`modules/` package wasn't tracked as separate project files, so it isn't duplicated
into this repo — nothing from it was needed here since the new backend is a clean
rebuild, not a port.

## What's actually working right now (be precise about this)

This build implements **Phase 1 (Foundation), Phase 2 (Library), Phase 5 (research),
Phase 6 (the creative pipeline), Phase 7 (the Autopilot orchestrator) and its 7.5
advanced-mode split, Phase 8 (opportunity discovery), Phase 9 (calendar/analytics/
performance feedback loop), and the Strategy Library + Defense engine in full** —
every phase from the original build order is now implemented. Concretely, today
you can:

- Run the FastAPI backend and React frontend together.
- Create a brand workspace.
- Point it at a real Windows folder of your product photos (`SOURCE_ASSET_ROOT`).
- Scan that folder: every image gets hashed (SHA256 + perceptual hash), measured,
  categorized by its top-level folder, and indexed — without ever writing to, moving,
  or renaming a single source file (this is enforced by an automated test, not just a
  promise — see "Running tests" below).
- Browse the resulting asset library, filter by category / unused status.
- Configure OpenAI model names and repository paths from Settings (never hardcoded).
- Browse the **Strategy Library**: 64 campaign archetypes ("Campaign DNA" — objective,
  trigger, audience, psychology, offer, channels, content types, duration, budget
  notes, success metrics) organized into 8 families — Attack, Acquire, Convert,
  Retain, Brand, Hype, Community, Defense — and start a real campaign record against
  any of them.
- Use **Defense**: log a competitor's price change, promotion, launch, or press
  moment, and get a ranked, explainable recommendation for which Strategy Library
  response fits (e.g. a 25% competitor discount recommends a full counterattack; a
  12% one recommends a value bundle instead of matching price) — then turn that
  recommendation directly into a campaign.
- See real campaigns in the **Campaigns** page, each tracking its chosen strategy and
  lifecycle status. Open a campaign to reach the **Campaign Detail** page.
- Click **Run Autopilot** on a campaign in `IDEA`/`FAILED` status to run the full
  pipeline end to end: fresh cited research, 2-3 AI-generated strategy candidates
  (rejecting anything too similar to a past campaign in the same category), copy, a
  carousel plan, and a rendered creative for every planned slide — landing the
  campaign in `REVIEW`. Needs an OpenAI API key and Output root set in Settings.
  This now returns instantly and runs in the background — the page shows a live
  step/progress readout while it works, so you're never stuck staring at a frozen
  button (see "How Autopilot's background jobs work" below). **By default, each
  slide's photo is fully recreated by AI** — your real product photo (and any
  inspiration examples you've uploaded on the brand's page) sent to the image
  model so it reimagines the whole scene around your actual product, instead of
  just placing your photo on a background with text over it. Uncheck "Recreate
  each photo with AI" above the button to fall back to that simpler,
  deterministic behavior instead (see "How full AI recreation works" below).
- Or use **Advanced mode** on Campaign Detail to run just one stage at a time —
  Strategy only, Copy only, or Visuals only — instead of everything at once. Each
  stage picks up from the last one's saved output, so you can try a different
  angle before committing to copy, or re-render visuals after adding new photos
  without re-running research. Visuals only needs no OpenAI key at all. Every
  stage button is background-job-backed the same way Autopilot is.
- On Campaign Detail, **render a real creative**: pick one of your indexed photos, a
  template ("Premium Product Hero" today), a platform format (Instagram/Facebook
  feed square, Instagram/Facebook story, Facebook feed landscape), and write the
  eyebrow/headline/body/CTA text. Clicking "Render creative" runs the actual hybrid
  pipeline — optional background isolation, your real product photo composited onto
  a background, HTML/CSS text rendered pixel-exact via headless Chromium
  (Playwright), and an automated QA check (dimensions, file integrity, text
  overflow, logo presence) — and saves the PNG into your configured Output root. No
  OpenAI API key is needed for this step; the background is a deterministic
  brand-color gradient by default, or check "Use AI-generated background" to have
  it come from an AI-generated scene instead (needs a key — see below). Also check
  "Auto-detect product zone" to have a vision-model call pick the crop and anchor
  for *this specific photo* instead of always using the template's one fixed
  layout — useful when your product isn't centered the same way in every shot (see
  "How vision-model product-zone detection works" below; needs a key). Check
  "Recreate this photo with AI" instead to have the whole image — product
  included — reimagined by the image model rather than just its background (see
  "How full AI recreation works" below; also needs a key).
- Browse the **Asset Library** with real photo thumbnails (not just filenames).
- Click a brand on the **Brands** page to open **Brand Detail**: upload a logo
  (it now actually appears on rendered creatives — this had been a dead field in
  the database since the very first build), upload a few visual-reference photos
  (past ads you liked, inspiration shots — anything that captures the look you
  want), and click "Analyze visual style with AI" to get a proposed style guide
  (dominant colors, typography mood, photography style, voice) you can review and
  apply to the brand's voice/colors/visual-style fields. Those same reference
  photos guide the AI-generated background above when you turn it on. Colors are
  now a real key → swatch → hex editor (add/remove a named color, pick it with a
  native color picker) instead of typing comma-separated text, and visual-style/
  forbidden-style descriptors are chip-based tag editors — both save the exact
  keys/tags you set instead of silently renumbering them on every save. Also on
  Brand Detail: **Inspiration examples** — real ads, posts, or carousels you found
  and liked, from anyone, not just this brand. Upload them here (optionally
  scoped to one category, e.g. an inspiration ad that should only inform Skincare
  campaigns) and they're handed to the image model alongside your product photo
  whenever "Recreate with AI" is on, as creative-direction reference. This is
  different from visual references above, which describe *this brand's own*
  look — inspiration examples are outside references you want campaigns to draw
  from.
- Run real, cited **Research** on the Research Radar page: pick a brand (and
  optionally a category) and an objective, and it runs a live, web-search-grounded
  OpenAI call and shows you the resulting insights with clickable source links. If
  the model can't attach a real source URL to a claim, that claim is dropped —
  never shown as if it were grounded. Repeat runs for the same brand/category within
  the configured TTL return the cached run instead of billing a new call.

- Find real posting communities on the **Opportunities** page: pick a category and
  click "Discover opportunities" — it web-searches for actual Facebook Groups,
  subreddits, and forums where your audience gathers, and only shows ones it could
  verify with a real source link (nothing invented). Mark them favorite/joined/
  blocked, then attach one to a campaign from Campaign Detail to get a draft post
  tailored to that community's posting rules — copy it and post it yourself. No
  app, including this one, can auto-post into a Facebook Group it doesn't
  administer; that's a Meta platform rule, not a missing feature here.

- Approve a campaign in `REVIEW` (Campaign Detail's **Approve** button). From the
  **Publishing** panel you can then either click **Publish now** to actually post a
  rendered slide to your own Facebook Page or linked Instagram Business account via
  Meta's Graph API (real, not a draft — see "Facebook Page / Instagram auto-publish"
  below for the one-time token setup), or log a publication you made by hand (a
  Facebook Group post, or anything posted outside this app). Add performance
  snapshots by hand after checking the platform's own insights (impressions/reach/
  likes/comments/shares/saves/clicks/leads/bookings/sales/revenue), or — for a
  Facebook Page/Instagram publication you posted through this app — click **Sync
  from Meta** to pull impressions/reach/likes/comments/shares/saves straight from
  the Graph API's own Insights endpoint instead of retyping them (see "How Meta
  Insights sync works" below). Either way, nothing here is ever estimated or
  predicted — a synced metric is marked with a "synced" badge so you can always
  tell it apart from one you typed in.
- See the real feedback loop on the **Analytics** page: totals, an engagement-rate
  breakdown by Strategy Library type, and top campaigns by revenue — all straight
  sums/averages over the metrics you entered. That per-type engagement rate now
  actually feeds back into which Strategy Library type Autopilot reaches for next
  (a tie-breaker among equally-underused types — see `docs/architecture.md` section
  5f), closing the loop described in the brief's own diagram.
- See what went out and when on the **Calendar** page — a list of publications
  grouped by day for the month you're viewing.
- **Delete a campaign** you created by mistake or just don't want anymore — a
  Delete button on both the Campaigns list (each row) and Campaign Detail
  (header, next to the status badge). Permanent: it removes the campaign record,
  its rendered slides/copy/outputs, any publications and performance metrics
  logged against it, and its community-draft attachments, and best-effort
  deletes the actual image/output files those pointed at. It never touches your
  source photos — those are shared, reusable assets other campaigns may still
  reference. Refused (with a clear message) if a background job for that
  campaign is still running — see "How deleting a campaign works" below.

**Not yet built** (optional refinement, not a missing phase): a second
`PublishingProvider` connector beyond Facebook Page/Instagram (e.g. Pinterest) if
you ever want one — the Protocol and the `/publish` endpoint's shape already
generalize to more than one provider without a rewrite.

Read `docs/architecture.md` for the full design and the phase-by-phase status table.

## Repository layout

```
backend/     FastAPI + SQLAlchemy + Alembic + SQLite (WAL mode)
frontend/    React + TypeScript + Vite + Tailwind
docs/        architecture.md, data-model.md, campaign-pipeline.md
scripts/     setup.ps1, dev.ps1, test.ps1 (Windows PowerShell)
```

## Windows setup (PowerShell)

Requires Python 3.11+ and Node 20+.

```powershell
git clone <this repo>   # or just unzip it
cd marketing-os
.\scripts\setup.ps1
```

This creates the backend virtual environment, installs Python + npm dependencies,
installs Playwright's headless Chromium (used by the creative pipeline to render
campaign images — a one-time ~150MB download), copies `.env.example` → `.env` in
both `backend/` and `frontend/`, and runs the database migrations.

Then edit `backend\.env`:

```
OPENAI_API_KEY=sk-...
SOURCE_ASSET_ROOT=C:\Marketing\Source
OUTPUT_ROOT=C:\Marketing\Generated
```

(You can also set these later from the Settings page in the app instead of editing
`.env` directly — the app's `settings` table overrides `.env` at runtime.)

Start everything:

```powershell
.\scripts\dev.ps1
```

- Backend: http://127.0.0.1:8000 (interactive API docs at `/docs`)
- Frontend: http://127.0.0.1:5173

## First run

The fastest way to get going: open the frontend and click **Setup guide** in the
sidebar (or just go to the app with no brands yet — it redirects you there
automatically). It's a 4-step wizard that walks through exactly the steps below in
one guided flow and lands you back on the Overview page ready to go. You can
revisit it any time — e.g. to add a second brand, or point at a different photo
folder later.

The manual, page-by-page equivalent (what the wizard does under the hood):

1. Open the frontend, go to **Brands**, create a brand (e.g. "Hanna Japan Store").
2. Go to **Settings**, set `Source asset root` to your real photos folder (organize it
   as `Source\<category>\<product>\photo.jpg` — the scanner uses the first folder level
   as the category automatically) and `Output root` to wherever generated campaigns
   should be written later. Add your OpenAI API key and confirm the model names.
3. Go to **Library**, click **Scan now**. Your photos get indexed — nothing under
   `Source` is ever modified.
4. Browse/filter the library. That's the full working slice today; see
   `docs/campaign-pipeline.md` for what's next.

## Access it from your phone or another device

This app is local-first by design — it reads your actual product photos straight
off this PC's disk, so there's no cloud server involved and nothing about your
photo library ever leaves this machine. By default `.\scripts\dev.ps1` only
accepts connections from this PC itself (`127.0.0.1`), same as any other local
dev server. If you want to open the app from your phone, a laptop in another
room, or while you're out — without moving your photos anywhere or exposing
anything to the public internet — the recommended way is
**[Tailscale](https://tailscale.com)**: it's free for personal use, creates a
private network (a WireGuard VPN) between only the devices you sign in on, and
takes about five minutes to set up.

1. **Install Tailscale on this PC.** Download it from
   [tailscale.com/download](https://tailscale.com/download), install it, and
   sign in (a Google/Microsoft/GitHub/email account all work — this creates your
   personal "tailnet"). It'll show as connected in the system tray.
2. **Install Tailscale on your phone** (App Store / Google Play) and sign in
   with the *same* account. Do the same on any other device you want to use.
3. **Find this PC's Tailscale address.** Open the
   [Tailscale admin console](https://login.tailscale.com/admin/machines) in a
   browser — it lists every device on your tailnet with an address like
   `100.x.y.z`. Turning on **MagicDNS** there (Settings → DNS) gives you a
   friendly hostname (e.g. `your-pc-name`) instead of the raw IP, which is
   nicer to type on a phone.
4. **Point the frontend at that address.** In `frontend\.env`, set:
   ```
   VITE_API_BASE_URL=http://100.x.y.z:8000
   ```
   (or `http://your-pc-name:8000` with MagicDNS). This is read once when the
   dev server *starts*, so if it's already running, stop it first.
5. **Allow that origin through CORS.** In `backend\.env`, add the same
   address (with the frontend's port, 5173) to `CORS_ORIGINS` alongside the
   existing localhost entry:
   ```
   CORS_ORIGINS=http://localhost:5173,http://100.x.y.z:5173
   ```
6. **Start the app in remote mode:**
   ```powershell
   .\scripts\dev.ps1 -Remote
   ```
   This binds both servers to every network interface on this PC instead of
   just `127.0.0.1` (the plain `.\scripts\dev.ps1`, with no flag, is
   unchanged — local-only, exactly as before).
7. **Windows Firewall.** The first time you do this, Windows will likely pop
   up "Windows Defender Firewall has blocked some features of python.exe /
   node.exe" — click **Allow access**, keeping at least the **Private
   networks** box checked (Tailscale's virtual adapter registers as a private
   network). If your phone still can't connect, add explicit inbound rules for
   TCP ports 8000 and 5173 in Windows Defender Firewall with Advanced
   Security — scope them to Tailscale's address range (`100.64.0.0/10`)
   rather than "Any" so this PC isn't also newly reachable from your regular
   home Wi-Fi.
8. **Open it from your phone.** With Tailscale connected there too, browse to
   `http://100.x.y.z:5173` (or `http://your-pc-name:5173`) — that's this app,
   running on this PC, over your own private network only.

A few things worth knowing: this only works while the PC is on and
`.\scripts\dev.ps1 -Remote` is actually running (Windows' default sleep
settings will still put the PC to sleep — check Settings → System → Power if
you want it reachable overnight); Tailscale's free tier easily covers a
solo setup like this. If you'd rather share a one-off link with someone
without installing an app on their device (e.g. handing a link to a
collaborator briefly), a tunnel like `ngrok http 5173`/`ngrok http 8000` or a
[Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/)
does that instead, at the cost of a public (if hard-to-guess) URL rather than
a private network — the README's "Facebook Page / Instagram auto-publish"
section already uses `ngrok` for a related, narrower purpose (exposing just
one rendered image to Meta's servers), so you likely have it installed
already. And if you ever want the app running 24/7 independent of this PC
being on at all — a genuinely different, bigger change involving moving your
photo library and database off local disk — that's a separate, much larger
undertaking than what's described here; ask if that's ever actually what you
need.

## Facebook Page / Instagram auto-publish

This is optional — everything else in the app works without it, and you can always
log a publication by hand instead. Set this up when you want Campaign Detail's
**Publish now** button to actually post a rendered creative to your own Facebook
Page (and, optionally, its linked Instagram Business account) via Meta's Graph API.

Because this app only ever posts to *your own* Page/Instagram account — never
someone else's — Meta's **Standard Access in Development Mode is enough. You do
not need to submit your app for App Review**, which is normally the slow, heavyweight
part of integrating with Meta's API; App Review is only required to post on behalf
of *other* people's Pages. Standard Access works immediately for anyone with a role
(admin/developer/tester) on the app you create in the next step, and you're
automatically the admin of any app you create.

1. **Create a Meta developer app.** Go to
   [developers.facebook.com/apps](https://developers.facebook.com/apps), click
   **Create App**, choose the **Business** type, and give it any name (e.g. "Hanna
   Marketing OS"). You don't need to add any products to it for this to work — the
   Graph API Explorer (next step) already has access.

2. **Generate a User Access Token with the right permissions.** Open the
   [Graph API Explorer](https://developers.facebook.com/tools/explorer), select
   your new app from the dropdown, click **Get Token → Get User Access Token**, and
   check: `pages_show_list`, `pages_manage_posts`, `pages_read_engagement` — and if
   you also want Instagram, add `instagram_basic` and `instagram_content_publish`
   too. Generate the token.

3. **Exchange it for a long-lived token.** The token from step 2 expires in about
   an hour. Find your App ID and App Secret on your app's dashboard under
   **Settings → Basic**, then call (in a browser, or via `curl`):
   ```
   https://graph.facebook.com/v21.0/oauth/access_token?grant_type=fb_exchange_token&client_id=YOUR_APP_ID&client_secret=YOUR_APP_SECRET&fb_exchange_token=YOUR_SHORT_LIVED_TOKEN
   ```
   The response's `access_token` is your long-lived user token (~60 days). A **Page**
   access token derived from it in the next step effectively doesn't expire unless
   you remove the app's permissions, change your Facebook password, or the
   underlying user token is otherwise invalidated.

4. **Get your Page's access token and Page ID.** Call:
   ```
   https://graph.facebook.com/v21.0/me/accounts?access_token=YOUR_LONG_LIVED_USER_TOKEN
   ```
   This lists every Page you manage. Find yours in the response — its `id` is your
   **Facebook Page ID**, and its `access_token` is your **Facebook Page access
   token**. Paste both into this app's **Settings** page.

5. **(Instagram only) Get your Instagram Business Account ID.** Your Page must
   already have a linked Instagram professional account (Meta Business Suite →
   Settings → Linked accounts, if it doesn't yet). Then call:
   ```
   https://graph.facebook.com/v21.0/YOUR_PAGE_ID?fields=instagram_business_account&access_token=YOUR_PAGE_ACCESS_TOKEN
   ```
   The `instagram_business_account.id` in the response is your **Instagram Business
   Account ID** — paste it into Settings too.

6. **(Instagram only) Set a public base URL.** This is the one real asymmetry
   between the two platforms: a Facebook Page photo post accepts a direct file
   upload, so your locally rendered creative goes straight from this app to
   Facebook with nothing else needed. Instagram's API only accepts an `image_url`
   that *Meta's own servers fetch themselves* — it cannot take a direct upload —
   so a creative sitting on your own machine at `localhost` isn't reachable by
   Instagram unless you expose it. The simplest way is a tunnel:
   ```powershell
   ngrok http 8000
   ```
   (install ngrok, or any similar tunnel tool, separately) and paste the
   `https://....ngrok.app` URL it gives you into Settings as **Public base URL**.
   Facebook Page posting doesn't need this field at all.

7. **Use it.** Approve a campaign, open its Publishing panel, pick **Facebook
   Page** or **Instagram** and which rendered slide to post, and click **Publish
   now**. This is a real post — it isn't a preview or a draft. On success it also
   logs a `Publication` row and moves the campaign to `PUBLISHED`, same as logging
   one by hand. If it fails, the exact Graph API error message is shown (most
   commonly an expired/invalid token — regenerate from step 2) and nothing is
   recorded, since a failed attempt didn't actually post anything.

This does **not** change the Facebook Groups situation described above: no app can
auto-post into a Group it doesn't administer, by Meta's own design, regardless of
tokens or permissions. Group posting stays copy/paste from the drafted post on the
Opportunities page.

## Running tests

```powershell
.\scripts\test.ps1
```

This runs the full backend suite, including:

- Repository scanner correctness (discovery, hashing, categorization, idempotent
  re-scans, content-change detection).
- Duplicate/novelty fingerprinting utilities.
- **The source-asset immutability safety test** — snapshots SHA256 + mtime of every
  fixture file, runs a full scan (twice), and asserts every original file is
  byte-for-byte and timestamp-for-timestamp identical afterward. This is the one
  guarantee the app cannot ever regress on.
- Core API behavior (brand CRUD, settings round-trip incl. the API key never being
  echoed back, campaign lifecycle guard rails, campaign creation from a Strategy
  Library type, end-to-end creative slide rendering over real HTTP).
- Strategy Library seed completeness/idempotency (all 64 types carry full Campaign
  DNA, every family/secondary-family reference resolves) and its API.
- Defense's rule-based recommendation engine (severity thresholds, brand-specific vs.
  global playbook precedence, unmatched event types).
- The creative pipeline: compositor pixel behavior, template HTML escaping, the
  Playwright renderer (including real DOM text-overflow diagnostics), automated QA,
  and the full pipeline end to end — including a second source-immutability guard
  for this new code path.
- Research orchestration: TTL cache hits/misses/expiry, cache scoping (a different
  category never reuses another's cached run), source-URL dedup, and — the core
  no-fake-research guarantee — that an insight with no cited source is dropped
  before it can be persisted. All against a fake provider, so none of it needs a
  real OpenAI call to verify.
- The Autopilot orchestrator end to end (happy path, no-candidate-photos and
  all-candidates-rejected failures, the status guard, a manually-set strategy type
  being respected, a retry not duplicating slide rows) and opportunity discovery
  (uncited-recommendation drop, upsert-not-duplicate, the discover/attach/mark-posted
  flow) — both against fake providers, no real API key needed.
- The performance feedback loop: publication lifecycle (status guard, creation,
  the published-status campaign-bump side effect), metric add/list, the
  `performance_summary` aggregation math, the calendar endpoint, and a direct test
  proving the orchestrator's strategy-type tie-break actually changes its pick when
  one type has a recorded higher engagement rate than another with equal usage.
- The Campaign Builder advanced mode: each of the three stages (Strategy/Copy/
  Visuals) running standalone and reaching the same end state as running the full
  pipeline, the copy/visuals precondition guards raising a specific message when
  the prior stage hasn't run, and that re-running Copy after Visuals has already
  completed doesn't revert campaign status backward — plus an HTTP-level test
  calling all three endpoints in sequence, including Visuals succeeding with the
  OpenAI key removed entirely.
- Brand visual style & AI-generated backgrounds: direct unit tests of
  `OpenAIProvider` itself (the one module every other test avoids exercising
  directly) covering both branches of `generate()` — with and without reference
  images — and the multi-image request shape `analyze_visual_style()` sends;
  brand asset upload/list/image/delete over real HTTP, with the file actually
  checked on disk, not just the database row; the visual-style analyze endpoint's
  two guard paths (no key, no reference photo) and that it never writes to the
  brand itself; and the orchestrator actually calling the image provider once per
  slide with the brand's reference photos attached when `use_ai_background` is
  on, falling back to the gradient without failing the run when the image
  provider raises, and staying on the gradient by default when it's off.
- Facebook Page / Instagram auto-publish: direct unit tests of
  `MetaPublishingProvider` itself (the one module allowed to talk to Meta's Graph
  API) against a fake HTTP transport — a Facebook photo upload sends the real file
  bytes and caption, Instagram's container→publish two-step flow happens in order,
  a missing public image URL fails Instagram cleanly before any network call, and a
  Graph API error response becomes a clear failure rather than an exception. At the
  API level: publishing is rejected without an approved campaign, a configured
  token, and a rendered slide; a successful publish logs a `Publication` and moves
  the campaign to `PUBLISHED`; and a failed publish records nothing and leaves the
  campaign's status untouched.
- Vision-model product-zone detection: the crop-fraction-to-pixel-box math
  (including clamping at the image edges), a full render with detection overriding
  the template's anchor, a render with detection off reporting
  `product_zone_detected: False`, the orchestrator calling the vision model once
  per slide only when enabled, falling back to the template's fixed zone on any
  vision-call failure, and staying off by default — plus a direct `OpenAIProvider.
  detect_product_zone` unit test against a fake SDK client.
- Non-blocking Autopilot: all four `/generate*` endpoints now return
  `{job_id, job_status: "QUEUED"}` immediately rather than blocking until the
  pipeline finishes, with the prerequisite-stage checks (e.g. "run Strategy before
  Copy") still enforced synchronously as a 400 *before* the job is queued — tests
  poll `GET /api/jobs/{id}` until it reaches a terminal status, then assert on the
  campaign's state via a separate `GET`, rather than reading it off the original
  POST response.
- Meta Insights sync: `POST /api/publications/{id}/metrics/sync` pulling real
  impressions/reach/likes/comments/shares/saves from the Graph API's Insights
  endpoint via a fake HTTP transport, tagging the resulting `PerformanceMetric`
  with `source="meta_sync"`, and cleanly rejecting a sync attempt for a
  publication with no `external_post_id` or a non-Meta provider.

159 tests, all passing as of this build.

## How campaign memory + no-repeat works (today's slice)

Every indexed asset tracks `times_used` and `last_used_at`, so Autopilot always
reaches for your least-used photos first. The `campaign_fingerprints` table and
`app/services/fingerprint.py` implement the similarity math (exact-hash,
token-overlap text similarity) that `services/orchestrator.py` uses to classify each
strategy candidate as `EXACT_REPEAT`, `TOO_SIMILAR`, `SIMILAR_BUT_ACCEPTABLE`, or
`FRESH` against every prior campaign in the same category — rejecting the first two
outright rather than ever shipping a repeat. See `docs/data-model.md` section
"Duplicate detection data" and `docs/campaign-pipeline.md` for the full design.

## How research works

`ResearchProvider` (implemented against the OpenAI Responses API with web search in
`app/services/ai/openai_provider.py`) always returns a structured `ResearchResult`;
`app/services/research/openai_research.py` wraps it with TTL-based caching and
persists insights to `research_runs`/`research_sources`/`research_insights` — but
only the ones with a real source URL attached. Nothing in this codebase is allowed
to present a trend claim without a citation trail. This is real today: run it from
the Research Radar page, or `POST /api/research/run` directly; see
`docs/campaign-pipeline.md` for the full design.

## How opportunity discovery works

`ResearchProvider.discover_opportunities(...)` (same web-search-grounded pattern as
research) finds real Facebook Groups/subreddits/forums for your audience;
`app/services/opportunities.py` persists only the ones it could back with a source
URL, and upserts by (brand, platform, name) so re-running discovery refreshes what's
already known instead of piling up duplicates of the same group. This is real
today: run it from the Opportunities page, or `POST /api/opportunities/discover`
directly.

## How the performance feedback loop works

Approve a campaign, log a `Publication` for it (a real auto-publish via `POST /
{id}/publish` — see below — or a manual note that you posted it in a Group), and
add real `PerformanceMetric` snapshots by hand after checking the platform's own
numbers — `POST /api/publications/{id}/metrics`, or the Publishing panel on
Campaign Detail. `app/services/analytics.py` turns those into a plain engagement
rate (`(likes+comments+shares+saves)/reach`, never a fabricated composite score)
and the Analytics page's totals/strategy-type breakdown/top campaigns. The loop
actually closes: `average_engagement_rate_for_strategy_type(...)` feeds into
`services/orchestrator.py`'s underused-strategy-type selection as a tie-breaker, so
a Strategy Library type that's genuinely performed well for this brand gets a
nudge over one that hasn't — without letting performance override the
underused-count-first rule that keeps one family from dominating every campaign.
See `docs/campaign-pipeline.md` for the full design.

## How Facebook Page / Instagram auto-publish works

`POST /api/campaigns/{id}/publish` is the real implementation of the
`PublishingProvider` extension point that had existed as a documented-but-empty
Protocol (`app/services/ai/base.py`) since round 1 — `app/services/publishing/
meta_provider.py::MetaPublishingProvider` is the first concrete connector. It
takes a rendered slide's real file and the campaign's own generated caption/
hashtags (from the Copy stage, if it ran — never invented) and posts them for
real, branching on two genuinely different Graph API shapes: a Facebook Page
photo post is a direct multipart upload (`POST /{page-id}/photos`, no public
hosting needed — see `docs/architecture.md` for sources), while Instagram's
Content Publishing API is a two-step container→publish flow that only accepts an
`image_url` Meta's own servers fetch themselves, so it needs a `public_asset_url`
built from your configured `Public base URL` (typically a tunnel like ngrok — see
"Facebook Page / Instagram auto-publish" above for the full token/ID setup). A
missing public URL fails Instagram with that exact explanation before any network
call is made — never a confusing Graph API rejection. On success this creates a
`Publication` and moves the campaign to `PUBLISHED`, same as logging one by hand;
on failure nothing is recorded, and the real Graph API error message is surfaced
via a 502 rather than swallowed. Facebook Groups remain outside what any app can
auto-post into — that's Meta's own platform rule, not something this connector
works around.

## How the Campaign Builder advanced mode works

Autopilot (`run_autopilot`) is a thin wrapper around three independently callable
stages in `app/services/orchestrator.py`: `run_strategy_stage` (research + strategy
candidate + novelty check, ends `BRIEF_READY`), `run_copy_stage` (creative brief +
copy + carousel plan, ends `COPY_READY`), and `run_visuals_stage` (asset selection +
rendering + fingerprint, ends `REVIEW`). Each stage persists its structured output to
a JSON file under the same deterministic output folder as everything else
(`.../brief/strategy.json`, `copy.json`, `creative.json`), tracked by a
`CampaignOutput` row, so a later stage reads the prior stage's result back from disk
rather than needing to run in the same process — you can run Strategy now and Copy
tomorrow. Copy and Visuals each guard on the prior stage's output actually existing
(not on campaign status), so re-running Copy after Visuals already completed doesn't
revert anything backward. Visuals needs no OpenAI key at all — it only touches your
photo library and the render pipeline. All three are exposed as their own endpoints
(`POST /api/campaigns/{id}/generate/strategy|copy|visuals`) and as "Strategy only /
Copy only / Visuals only" buttons in the Advanced mode card on Campaign Detail,
alongside the existing one-click "Run Autopilot" button. See
`docs/architecture.md` section 5g for the full design.

## How brand visual style & AI-generated backgrounds work

Open **Brands** → click a brand → **Brand Detail**. Upload a logo there and it now
actually shows up on rendered creatives (`resolve_brand_logo_path` has looked for
one since the creative pipeline was built — there was just never a way to upload
one until now). Upload a few visual-reference photos — past ads you liked,
inspiration shots, anything that captures the look you want — and click "Analyze
visual style with AI": it shows every one of those photos to the vision model in
one call and proposes dominant colors, typography mood, photography style, and a
voice suggestion. That's a proposal only, shown in an editable form — nothing is
saved until you click "Apply to form below" and then "Save changes", same
human-approval-first pattern as everywhere else in this app.

Those same reference photos can also guide the AI-generated background itself:
check "Use AI-generated background" on Autopilot, "Visuals only", or the manual
"Render creative" panel, and each slide's background comes from an AI image call
instead of the deterministic gradient, with up to 3 of the brand's reference
photos attached as a live style guide. This needs an OpenAI key and is off by
default everywhere — including on "Visuals only", so its no-key property from the
Campaign Builder advanced mode is unchanged unless you opt in. See
`docs/architecture.md` section 5h for the full design.

## How full AI recreation works

"Use AI-generated background" above still only replaces the empty scene behind
your product — the actual product photo you shot is still pasted onto it
untouched, pixel for pixel. That's deliberate (it's the safest, most predictable
default: your real packaging, unaltered), but it also means the result is
sometimes just "a bit of text on my original photo with a nicer backdrop," which
isn't always what "recreate this for the campaign" means.

**Recreate each photo with AI** goes further: it sends your real product photo
itself — plus, when you've uploaded any, up to two Inspiration examples from
Brand Detail (scoped to this campaign's category if you scoped them, brand-wide
otherwise) — to the image model as reference images on an edit call, and asks it
to reimagine the *entire* scene: background, lighting, composition, mood, all of
it, while explicitly keeping the actual product (its packaging, shape, label,
colors) accurate to your photo rather than inventing a different one. The result
replaces the whole slide's base image; your headline/body/CTA/logo still render
on top afterward as real HTML/CSS text, exactly like every other path in this
app — never baked into the AI image itself.

This is **on by default for the main "Run Autopilot" button** — it's the direct
answer to "the app should recreate my photo so it fits the campaign, not just
paste a bit of text on it." It stays **off by default** for "Visuals only" and
the manual "Render a creative" panel, so their documented "no OpenAI key needed"
property is unaffected unless you opt in there too. Like every other AI
enhancement in this pipeline, a failure (bad key, rate limit, malformed response)
falls back silently to the deterministic gradient-plus-your-original-photo
pipeline rather than failing the render — see `docs/architecture.md` section 5o
for the full design.

## How vision-model product-zone detection works

By default, every template has one fixed "product zone" — a rectangle it always
composites the photo into, the same for every image. That's fine when your photos
are all framed the same way, but if the product sits in a different part of the
frame from shot to shot, a fixed zone can crop it awkwardly. Checking "Auto-detect
product zone" (on Autopilot, Visuals only, or the manual render panel) sends that
specific photo to the vision model (`AIProvider.detect_product_zone`, one call per
slide) and asks it to return a tight crop box (as fractions of the image, 0-1) and
an anchor (`center`/`bottom`/`top`) for *that* photo — `services/creative/
pipeline.py::render_slide` then crops to that box and overrides the template's
anchor before compositing, instead of always using the template's one fixed
rectangle. Like the AI-generated background, this is a best-effort enhancement:
any failure (bad key, malformed response, rate limit) falls back to the template's
default zone silently rather than failing the render, and it's off by default
everywhere, including "Visuals only", so its no-key property is unaffected unless
you opt in.

## How Autopilot's background jobs work

Every `/generate*` action (Autopilot and all three Advanced-mode stage buttons) now
returns `{job_id, job_status: "QUEUED"}` immediately instead of leaving the request
open until the whole pipeline finishes. The frontend polls `GET /api/jobs/{id}`
every 1.5s and shows a live "Researching trends... / Rendering slide 2 of 6..."
line (or the final error) right on Campaign Detail, then refreshes the campaign's
data once the job reaches a terminal state — so a long carousel render, or a slow
research call, no longer holds the button in a spinning state with no feedback,
and you're free to navigate away and come back. Validation that's cheap and local
(the campaign exists, is in the right status, the prior stage's output exists) still
happens synchronously and returns a normal `400` before the job is even queued —
only genuinely long-running work (the AI calls, the actual rendering) happens in
the background job, so a mistake like clicking "Copy only" before "Strategy only"
still fails immediately and clearly instead of silently queuing a job that's
guaranteed to fail a second later.

## How Meta Insights sync works

Rather than checking Facebook/Instagram's own analytics and typing numbers into
this app by hand every time, click **Sync from Meta** next to any publication that
was posted through this app's auto-publish (or logged by hand with a real
`external_post_id`) to pull real numbers straight from Meta's Graph API —
`POST /api/publications/{id}/metrics/sync`. `MetaPublishingProvider.fetch_metrics`
splits the read into two tiers on purpose: the post/media's own like/comment counts
(a long-stable part of the Graph API) fail the whole sync if they fail, while the
separate Insights edge (impressions/reach/saves/shares — a part of Meta's API that
has repeatedly renamed and deprecated metrics across versions) is fetched
best-effort, so a hiccup there doesn't take down the stable counts too. Only
numbers the platform actually returned are recorded — nothing is ever filled in as
a placeholder `0` for something that wasn't fetched — and the resulting
`PerformanceMetric` is tagged `source="meta_sync"`, shown with a "synced" badge on
Campaign Detail, so it's always visually distinguishable from a metric you typed in
by hand.

## How deleting a campaign works

`DELETE /api/campaigns/{id}` (Campaigns list and Campaign Detail both call it) is
a real, permanent delete — there's no trash/undo. It:

- Refuses with a `409` if a background job for that campaign is still `QUEUED`
  or `RUNNING`, so you can't pull a campaign out from under an in-flight
  Autopilot/stage run — finish or wait out the run first.
- Cascades at the database level to everything scoped to that campaign: its
  slides, saved copy/creative/QA outputs, novelty fingerprint, logged
  publications and their performance metrics, and community-draft attachments.
  This relies on SQLite foreign keys being enforced (`PRAGMA foreign_keys=ON`,
  set on every connection) plus `ondelete="CASCADE"` on each child table.
- Best-effort deletes the actual files those rows pointed at under your Output
  root (a locked or already-missing file doesn't block the delete — it's
  skipped, not fatal).
- Deliberately leaves your source photos under `SOURCE_ASSET_ROOT` completely
  untouched — those are shared, reusable assets other campaigns may still be
  using, not this campaign's to delete — and leaves any `Opportunity` (a
  discovered community) alone too, since it isn't scoped to one campaign.
- Logs an audit event and cleans up the campaign's own background-job history
  so nothing phantom is left behind.

Both the Campaigns list row and Campaign Detail's header ask for a plain
JavaScript confirmation ("Delete campaign HANNA-SKIN-000010? ...") before
calling it, and show the backend's exact error message if the delete is
refused.

## How outputs are saved

Deterministic per-campaign folders under `OUTPUT_ROOT`, e.g.:

```
Generated\hanna\skincare\2026\2026-09\HANNA-SKINC-000123\
  instagram_square\slide-01.png
  instagram_story\slide-01.png
  qa\slide-01.json
```

This part is real today — rendering a creative (by hand, or via Run Autopilot) writes
each slide's PNG and its QA report exactly here (see `services/creative/pipeline.py`'s
`build_slide_output_path`/`build_qa_report_path`). `campaign.json`/`research.json`/
`copy.json` alongside these, and a `community\facebook-groups.txt`, are a possible
future convenience — the database is the source of truth for application state today,
and the folder structure already makes rendered campaigns portable and browsable by
hand without them.

## Troubleshooting

- **`dev.ps1`/`setup.ps1` fails to parse with a "missing terminator" or similar error,
  especially on a non-English Windows install (e.g. a Japanese-locale message like
  `文字列に終端記号 " がありません`)**: this means the `.ps1` file lost its UTF-8 BOM
  somewhere along the way (a zip/unzip tool, an editor's "Save As", a git checkout with
  the wrong `core.autocrlf`/encoding settings, etc. can all strip it). Windows
  PowerShell 5.1 only auto-detects UTF-8 correctly when the file *has* a BOM; without
  one it falls back to the system's ANSI codepage, which garbles this script's em-dash
  characters and breaks the parser. Fix: re-download/re-unzip a fresh copy of the
  script rather than one that's been re-saved by another tool, or open it in an editor
  that lets you explicitly "Save with encoding: UTF-8 with BOM" (VS Code: bottom-right
  status bar → click the encoding → "Save with Encoding" → "UTF-8 with BOM").
- **`ModuleNotFoundError` running the backend**: make sure you activated the venv
  (`backend\.venv\Scripts\Activate.ps1`) or use `scripts\dev.ps1`, which does it for you.
- **CORS errors in the browser console**: confirm `CORS_ORIGINS` in `backend\.env`
  includes `http://localhost:5173` (the default already does).
- **Scan reports 0 files**: check `Source asset root` in Settings is an absolute
  Windows path that actually exists — `GET /api/repositories/test-path?path=...`
  (visible in `/docs`) will tell you if the path resolves.
- **OpenAI calls fail with "API key is not configured"**: set it in Settings, or in
  `backend\.env`, and restart the backend if you edited `.env` directly (Settings-UI
  changes take effect immediately, no restart needed).
- **Rendering a creative fails with a Playwright/"Executable doesn't exist" error**:
  run `backend\.venv\Scripts\playwright.exe install chromium` once (`setup.ps1` does
  this automatically, but a manually-created venv or an interrupted setup can miss
  it).
- **Rendering a creative fails with "OUTPUT_ROOT is not configured"**: set Output root
  in Settings to a real writable Windows folder first.
- **"Publish now" fails with "Invalid OAuth access token" (or similar)**: the Page
  access token has expired or been revoked — regenerate it following steps 2-4 of
  "Facebook Page / Instagram auto-publish" above and paste the new one into
  Settings.
- **"Publish now" for Instagram fails asking for a public URL**: expected — Meta's
  API fetches the image itself and can't reach `localhost`. Set `Public base URL`
  in Settings to a tunnel (e.g. `ngrok http 8000`) pointed at this backend; see
  step 6 of the same section.
- **Autopilot fails with a Playwright `NotImplementedError`**: this was a real bug
  (Playwright's async API needs Windows' Proactor event loop to launch Chromium;
  uvicorn needs the Selector loop for its own signal handling — mutually
  exclusive on the same loop) — fixed as of this build by running the renderer on
  its own dedicated thread. If you're on an older copy of the app and hit this, or
  a campaign got stuck showing `RESEARCHING`/`GENERATING` from before this fix,
  update to this version and click **Visuals only** in Advanced mode on that
  campaign — it has no status gate, so it retries in place.
- **Updating to a new build and something looks stale, or you see a database
  error mentioning a missing column**: the backend now applies any pending
  database migrations automatically the moment it starts up (`app/db.py`'s
  `init_db`) — you no longer need to separately run `alembic upgrade head` after
  replacing the app's files, and this stays true for every future update too. If
  you still see something stale after updating, it's almost always that the new
  files didn't actually land where the running backend is reading from — double
  check you extracted the new zip over (or fully replaced) the folder you're
  actually running `dev.ps1` from, not a second copy next to it, then restart the
  backend.

## Contributing to the next phase

Every phase from the original 68-section brief, its Strategy Library/Defense
addendum, and every item from the most recent five-item polish round (Meta
Insights sync, vision-model product-zone detection, non-blocking Autopilot, the
Brand style editor, and the onboarding wizard) is now built and tested. What's
left is genuinely optional: read `docs/campaign-pipeline.md`'s "What's left"
section for the short remaining list (mainly a second `PublishingProvider`
connector beyond Facebook/Instagram, should you ever want one). The schema in
`docs/data-model.md` is considered stable; new work should add tables/columns via
Alembic migrations, not modify existing tables destructively.
