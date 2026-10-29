# Hanna premium creative production

Automated premium image generation is stopped. V11 final acceptance remains FAIL;
V11.3 is not authorized. V12.1 introduces no image model, provider, Custom GPT API,
renderer redesign, migration or environment key.

Hanna Japan campaigns (`hanna-japan`) default to external creative production.
Other brands can opt in through the existing `campaign_rules` value
`premium_creative_workflow: external_chatgpt`. Historical rendering remains for
other brands/research. Hanna's visual stage and Autopilot terminate with a handoff;
manual rendering, legacy QA regeneration and legacy revision rendering are blocked.
Research, planning and copy stages retain their existing provider authorization.
The handoff/import/review operations themselves make no provider requests.

## Operator flow

1. Complete canonical product selection, research, planning, verified claims and
   copy. Supply the exact target slide count, locale/channel, approved product
   master, approved references and canonical logo. Missing authority/assets fail
   closed. Export never creates reference approval or edits facts/copy.
2. Open the campaign's **Premium creative production** panel. Export the campaign
   ZIP. It includes `HANNA_CAMPAIGN_HANDOFF.md`, `.json`,
   `HANNA_CAMPAIGN_ASSETS.json`, `CHATGPT_READY_INSTRUCTION.txt` and actual asset
   bytes with SHA256/approval provenance. Multi-locale/channel campaigns have a
   separate ordered brief for every required output.
3. Upload the whole bundle to the external ChatGPT creative workflow and paste
   the instruction. Each slide is a complete artwork guided by approved Hanna
   examples. Marketing OS retains authority over identity, variant, facts, exact
   copy, CTA, language and slide order. Old compositor coordinates/masks are not
   part of the creative brief. No programmatic Custom GPT invocation occurs.
4. Select the matching slide/locale/channel and import the returned PNG/JPEG/WebP.
   Exact dimensions, raster readability, role mapping and duplicate hashes are
   checked. Files above 20 MiB or 16 megapixels fail. Imported bytes are never
   cropped, enhanced or rewritten. Source is
   `external_chatgpt_creative_workflow`, never the Marketing OS renderer.
5. Open the actual imported artwork. Enter your reviewer name; explicitly confirm
   the expected product is visible and faithful to canonical assets. Transcribe
   visible copy into the displayed JSON keys. Normalized transcription must
   exactly match approved copy. This is explicit human evidence, not OCR or an
   automated claim of product recognition. Inspect aesthetics, language and brand
   fidelity yourself. Existing V9 aesthetic scores do not gate these imports.
6. Approve, or reject with a structured reason and actionable visual feedback.
   Export a rejected slide's revision ZIP. It contains the exact rejected image,
   rejection reasons, references and unchanged campaign facts/copy; instructions
   request changes to that slide only. Import the revision as a new file and
   review it again. Previous versions retain provenance in history.
7. `READY_TO_PUBLISH` is computed only when every expected output has current human
   approval, product/copy QA and unchanged file/authority hashes. Importing or
   changing creative clears campaign-level approval. Canonical fact/copy/asset or
   reference-approval changes require a new export and fresh reviews. The normal
   campaign approval/publishing gate uses this readiness; published image paths
   resolve to the approved external image. Ambiguous multi-locale/channel slide
   selection fails closed. Publishing itself remains separately authorized.

## Persistence and API

Existing `CampaignOutput(kind="premium_state")` points to a versioned, SHA-bound
JSON state file under `OUTPUT_ROOT/premium_workflow/<campaign>`; no schema change.
Uploaded files live under `premium_imports`; export/revision bundles live under
`premium_handoff` and `premium_revisions`. Preserve these folders alongside the
existing DB/output backup procedures. File writes are exclusive; state transitions
use optimistic version checks. A failed concurrent operation may leave an orphan
bundle/image; it cannot grant approval. A missing/modified state file fails closed.
Only the trusted operator with existing application access may provide approval;
this does not add an authentication or cryptographic identity system.

Endpoints below are relative to `/api/campaigns/{id}`:

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/premium-creative` | Current canonical briefs, counts and readiness |
| POST | `/premium-creative/export` | Snapshot and download complete campaign ZIP |
| POST | `/premium-creative/import` | Multipart `image`, `slide_key`, `expected_version` |
| POST | `/premium-creative/review` | Explicit versioned product/copy review and decision |
| POST | `/premium-creative/revision?slide_key=...` | Rejected slide revision ZIP |
| GET | `/premium-creative/preview?slide_key=...` | Verified imported image for review |

Imports/reviews never silently mark a campaign approved. Stale versions return
409. Product visibility and copy legibility require a human: deterministic checks
cannot establish advertising quality from image bytes. Failed exports/imports do
not authorize fallback generation or a provider retry.

V12.1 validation uses isolated databases and produces a read-only canonical
campaign demonstration outside the repository. It does not import, approve,
publish or mutate the canonical acceptance campaign. No follow-up is automatic.
