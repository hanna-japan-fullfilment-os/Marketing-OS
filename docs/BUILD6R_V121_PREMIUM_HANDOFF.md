# Hanna premium creative production

## BUILD6R-EXEC-0002: current claim authority and factual purposes

Production export now requires `export_handoff(handoff, directory, db=db,
campaign=campaign)`. Import, review, readiness and revision resolve current
canonical authority even when a historical `handoff=` is explicitly supplied.
Missing canonical context fails closed before output/state writes. An unchanged
historical handoff digest does not establish current evidence or library approval.

`resolve_canonical_handoff` reuses the existing persisted creative plan loader,
package builder and database provenance checks. It requires a clean session,
reloads the campaign identity, and never binds claims, creates evidence or writes
campaign data. Cached session identities are expired before resolution so an
earlier export cannot conceal evidence revoked by another session.
`require_ready` compares the complete canonical slide set, exact
copy, purpose and source-package bindings, then applies the existing reviewed
claim, qualifier, library-approval and library-digest checks. There is no alternate
claim registry, caller-supplied purpose permission or cached authority token.

Benefit-free application/aftercare is supported only for independently resolved
canonical purposes and their exact reviewed factual claims: application or
application_action maps to ex-apply; routine_aftercare or
manufacturer_aftercare_guidance maps to ex-after. Purpose matching is
case-insensitive for policy selection, but the supplied role must still equal the
canonical role. Only FACT_ONLY / PRODUCT_FACT evidence qualifies, and its benefit
hierarchy must be empty. Other purposes retain the existing benefit requirements.
No Portuguese copy, claim approval or persisted campaign purpose is rewritten to
make a brief eligible. Pending whole-library approval still blocks production.

Legacy v1 serialization and digests are unchanged. Context-free production calls
are intentionally refused; old artifacts and review history remain preserved.
Version-2 draft preparation remains structural and in memory, while production
still requires exact-content owner plan approval and independent returned-artwork
review. This repair does not adopt v2 into an existing campaign, reopen frozen
artwork, activate an API/frontend, call a provider or authorize publication.

## BUILD6R-EXEC-0001: purpose-aware execution contract

New executions may explicitly adopt `PremiumExecutionHandoff` (version 2).
Existing version-1 handoffs, serialization, digests and reviews are unchanged;
the application does not silently upgrade campaigns or rewrite approved artwork.
This build provides a Python service contract, not a new frontend/API editor.

1. Keep the existing canonical claim-bound handoff as the authoritative brief.
2. Prepare one `CreativeExecutionPlan` per exact slide key. Use
   `campaign_creative_strategy.composition_for_purpose(role, primary_message)`
   for a purpose-based proposal. Fill the concrete camera/spatial relationship,
   product role, lighting/contact integration, campaign typography requirements,
   prohibited imagery and rationale for every supplied approved reference.
3. Bind `brief_sha256` to the unmodified version-1 slide brief's `digest()`.
   Reference IDs/hashes must match its actual approved reference assets. Only
   composition, lighting, palette, hierarchy and finish may transfer; never
   reference product identity, packaging, copy or claims.
4. Use `prepare_execution_handoff(handoff, plans)` to prepare the complete v2
   contract in memory. PENDING/REJECTED plans can be prepared for owner inspection,
   but production export refuses them. No canonical campaign/registry write occurs.
5. An explicitly named owner reviews the actual plan. Record APPROVED and bind
   `reviewed_content_sha256` to `plan.content_digest()`; any content/brief/reference
   change requires fresh review. These fields use the existing trusted-operator
   model, not authentication or cryptographic proof of a human identity.
6. `export_handoff` and ingestion boundaries revalidate the full v2 contract,
   including model-copy/construct inputs, before writing files or state.
   Service callers must explicitly supply this v2 handoff to export/import/review/
   readiness operations; existing routes continue their legacy behavior.

The supported families are existing product_hero, editorial_detail and
ritual_context. Unknown purposes fail rather than rotate by slide index.
Material/physical-layer demonstrations are not supplied by this contract. Human
context may be planned only without application/results demonstrations. The
required prohibitions protect against invented packaging, unsupported claims and
misleading demonstrations. Free-text requirements still need owner inspection;
structural validation cannot prove the truth or quality of an arbitrary sentence.

Execution approval is independent of returned-artwork approval. Import remains
PENDING_REVIEW; a named human must inspect product fidelity, exact visible copy
and visual quality. No numerical aesthetic score, automatic approval, image job,
retry, runtime activation or paid-provider permission is introduced.
Adopting a changed v2 handoff requires an explicit new export and fresh reviews;
preparing it alone leaves historical v1 approvals intact. Frozen assets must not
be exported/replaced as a side effect of adoption.

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

## EXEC-0003: separate ten-slide reconciliation (offline, opt-in)

`canonical_campaign_reconciliation` prepares typed plans in memory and validates
an exact owner-approved architecture against current claim-library wording and
the existing V3.45 evidence/provenance services. It creates no claim registry,
evidence rows, approvals, campaign records or artwork. `apply_campaign` is an
explicit disabled boundary in Phase 1: every call fails before writes. A Phase 2
data-operation authorization and reviewed execution adapter remain necessary.
There is no startup hook, API route, provider dispatch or automatic adoption.

The historical six-slide acceptance fixture is never migrated. A future separate
campaign uses ten independent slide plans and a `CampaignOutput` with kind
`campaign_reconciliation`. Its filename stem is the semantic manifest digest.
The manifest pins creative bytes, the approved external architecture and owner
approval, freeze evidence, fourteen product-evidence IDs, the reconstructed master,
original/display logo provenance and approved reference hashes. Editorial wording
uses the existing reviewed library; it does not create product-evidence records.
The eight missing exact product-evidence mappings and missing press-release source
representation must be reconciled through existing evidence services separately.
No evidence is verified or promoted by planning/export/intake.

Only live canonical reconciliation can establish the ten-slide factual/editorial
policy. Caller roles, flags, claim IDs or recomputed digests grant no eligibility.
Slides 2 and 5 retain benefit hierarchies. Other approved factual/editorial slides
require their exact purpose/claim sets and empty benefit hierarchies. Product-name
copy is bound to the current Product and approved architecture; it is not a global
neutral-copy exception. Whole-library approval, current eligible evidence, exact
Portuguese copy and qualifiers remain mandatory for production consumption.

Campaign-scoped reconstructed masters require the existing master contract and
exact source/owner provenance. The global selector excludes them. Campaign logo
bindings use `campaign:<campaign-id>:logo` labels, which the legacy global logo
resolver excludes. Existing master/logo records and bytes remain unchanged.

`ProductionScopeEnvelope(scope_version=1)` is separate from legacy handoff v1 and
execution handoff v2; neither existing model's serialized fields/digests change.
It binds the complete ten-slide canonical handoff, reconciliation digest, selected
structured execution plans and exact named owner review of the release scope.
Every canonical slide must occur once in the exhaustive disposition map:

| Slides | Disposition | Meaning |
| --- | --- | --- |
| 1–6 | FROZEN_EXTERNAL_REFERENCE | Preserve external hashes/classifications; no regenerated output or adopted approval |
| 7–8 | SELECTED_PENDING_OWNER_REVIEW | Selected output membership; plan/release approval remains independently required |
| 9–10 | DEFERRED_UNRENDERED | No output, import or revision permitted |

The selected disposition name is membership, not an approval verdict. Draft scope
and execution plans may remain pending. Production export requires approved exact
plans and release scope, then rechecks all current canonical claim/asset authority.
The ZIP lists only Slides 7–8 and contains frozen hashes/classifications as evidence,
not editable frozen artwork. Widening scope or exporting the complete reconciled
campaign fails closed. Frozen/deferred imports, reviews and revisions fail before
workflow state reads/writes. Legacy routes cannot silently reopen the campaign.

`SELECTED_RELEASE_COMPLETE` means the two selected outputs received independent
current artwork reviews. It always leaves `CAMPAIGN_CREATIVE_COMPLETE=false` and
cannot satisfy publication readiness. Frozen historical decisions are referenced,
never copied into new execution/artwork approvals. Rejected artwork stays rejected.

Future promotion of shared product facts or library approval can change recomputed
historical package digests. Preserve old artifacts/reviews; never automatically
re-export or rebind the six-slide fixture. Production data application, whole-library
approval, provider execution, publication and Git preservation require their own
authorization. Structural QA does not establish premium aesthetic acceptance.
