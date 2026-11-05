# Marketing OS — Engineering Governance

## Identity and scope

This repository is Marketing OS / BUILD6R.

Canonical repository:
C:\My Apps\marketing-os\marketing-os_4

Configured origin:
https://github.com/hanna-japan-fullfilment-os/Marketing-OS

Marketing OS is a local-first marketing application. Its verified architecture is:

- Backend: Python, FastAPI, Pydantic and SQLAlchemy.
- Database evolution: Alembic.
- Canonical database: backend/data/app.db, using SQLite.
- Documented database architecture: SQLite WAL on a local filesystem.
- Frontend: React, TypeScript and Vite.
- Creative rendering includes deterministic typography/compositing and separately
  authorized external creative workflows.
- Supabase is not the canonical Marketing OS database.

Do not introduce BJM marketplace, Stripe Connect, Supabase/PostgreSQL, Next.js,
payment, voucher or merchant requirements merely because they occur in the
imported historical BJM contract.

## Authority and provenance

Explicit owner instructions govern the authorized task and take precedence over
repository guidance.

This file defines repository engineering procedure. PROJECT_STATE.md records
verified snapshots and unresolved decisions; it is not an authorization token.

README.md, implementation documentation, source, tests, commits and hash-bound
evidence support factual claims within their respective scopes. A document title,
commit subject, test PASS or proposed roadmap does not authorize another build.

backend/CLAUDE.md points to this contract.

docs/governance/provenance/IMPORTED_BJM_CONTRACT.md is an inactive provenance
archive. Its instructions do not govern Marketing OS. Its presence does not
establish authority over any separate BJM project.

If current evidence contradicts a required lock or project identity, report the
discrepancy and stop the dependent mutation. Do not invent a replacement state.

## Build identity and authorization

Distinguish:

1. Implementation builds: bounded source, test or documentation changes.
2. External creative checkpoints: artwork, review and production evidence.
3. Runtime, database, deployment and publishing operations: separately scoped work.

External creative checkpoint numbers do not prove that a corresponding
implementation build was committed, tested, integrated or deployed.

Establish the exact build identifier, objective, allowed paths, prohibited actions,
validation plan and completion criteria before mutation.

A request explicitly authorizing implementation grants source-change authority
within its stated scope. It does not automatically authorize:

- Canonical database, settings-store or environment changes.
- Dependency installation, runtime activation or infrastructure changes.
- Provider calls, image generation or paid operations.
- Staging, commits, branch changes, merges, resets, rebases or pushes.
- Deployment, publication, scheduling or external-system mutations.

Each action class requires explicit authorization covering its scope. Existing
session authorization remains valid within its limits; do not repeatedly request
the same approval.

Do not expand scope or continue to a later build automatically.

## Mandatory pre-mutation reconciliation

Before modifying authorized files:

1. Read this contract, PROJECT_STATE.md and relevant scoped documentation.
2. Verify repository root, branch, HEAD, tree and staged/unstaged/untracked status.
3. Identify existing work and distinguish it from the authorized change.
4. Verify required source, database, environment and creative-asset locks.
5. Inspect existing functions, schemas, tests and migrations relevant to the task.
6. Confirm dependencies and required execution capabilities already exist.
7. Establish exact allowed paths and meaningful validation commands.
8. Reconcile required approvals and unresolved compatibility risks.

Do not require deletion or staging of unrelated untracked work to manufacture a
clean worktree. Stop on unexplained changes that affect the authorized operation.

Use read-only inspection until the required gates pass. Do not import/start the
application against the canonical database merely to inspect project state.

## Git and existing work

Preserve existing commits, branches, untracked assets and outputs.

Do not reset, clean, stash, switch branches, create a worktree, integrate or rewrite
history without authorization for that operation.

Branch names do not establish which builds their history contains. Inspect
ancestry and commit content.

When staging is authorized, stage explicit approved paths and verify staged
content and scope. Do not use broad staging that can capture unrelated work.

Commit, push and main integration are distinct authorization gates. Never force
push, create tags/releases or push main by implication.

Use raw committed blobs for canonical content locks where newline normalization
would make working-tree byte hashes platform-dependent. Record both forms when
relevant.

## Database, environment and source-asset protection

The canonical SQLite database, .env, settings_store and approved source assets
are protected.

Tests must use isolated temporary resources and must not mutate the canonical
database or load production settings in a way that causes side effects.

Canonical schema changes require reviewed, version-controlled migrations and
explicit execution authorization. Do not stamp over required migration lineage.

Backup, restore, downgrade, checkpoint and vacuum operations require authorization
when they affect canonical data.

Do not expose secret values. Hashes and sanitized target paths are sufficient for
routine evidence.

Do not move, rename, retouch or replace source imagery by implication.

## Creative truth, fidelity and approvals

Preserve exact product identity, variant, approved facts, Portuguese copy and
required qualifiers.

Generated imagery is not evidence for a product claim.

The owner-approved reconstructed product master must retain its reconstruction
provenance. Do not describe it as an original camera photograph or manufacturer
original.

For protected product layers, preserve the approved master hash and authorized
transformations. Package repainting, regenerated labels, synthetic reconstruction
or replacement masters require explicit owner authorization.

Track source-native resolution separately from platform working-copy resolution.
Platform downscaling alone does not fail a source-resolution requirement when
trusted source-native evidence is available.

Frozen artwork cannot be regenerated, edited, replaced, re-ingested as canonical
or reopened automatically. Preserve owner decisions and known accepted
limitations.

Technical QA, factual/copy QA and premium visual acceptance are independent.

A renderer success, valid dimensions, faithful product layer, numeric score or
legibility PASS does not establish premium quality or owner approval.

The owner's visual decision is authoritative. Preserve FAIL, rejected, passable,
near-target and premium-accepted classifications without promoting them.

Slides 1–6 and existing canonical approvals remain protected until explicitly
reopened. Preserve rejected candidates and their provenance.

Human/application imagery must not fabricate packaging, unsupported product
behavior, demonstrations, results or before/after claims.

The current creative-eligibility policy is documented in
docs/PRODUCT_CREATIVE_ELIGIBILITY_POLICY.md. Do not infer creative prohibition from
registration/import uncertainty alone, or infer sale/publication permission from
creative eligibility.

## Providers, budgets and runtime

Provider calls and image generation require authorization for the concrete
operation. Paid calls additionally require an approved budget and bounded
exposure.

Unknown paid exposure fails closed. Do not add automatic retries, best-of-N,
fallback providers or model substitutions without authorization.

Do not start ComfyUI, download models, change Windows configuration, activate
production routing or deploy merely to complete engineering QA.

Human approval and provider authorization are never manufactured by a test flag
or development bypass.

## Tests, regressions and compatibility

Use tests appropriate to the actual change.

Contract and workflow changes require positive, negative, fail-closed and
compatibility tests, including stale or altered authority where relevant.

Use mocks and isolated resources for zero-provider verification. Do not weaken
failing tests, skip cases, alter fixture expectations or hide failures to obtain a
PASS.

Separate new failures from reproduced baseline failures. Any baseline exception
must be explicitly owner-approved for the named build and retain exact failure
identities and reproduction evidence. It is not a permanent exemption.

Preserve historical handoff/import/review compatibility unless a separately
approved change explicitly alters it.

Changes to authority hashes or review contracts must not silently invalidate or
approve unrelated frozen campaign outputs.

Engineering tests do not establish runtime, visual, deployment or publishing
acceptance.

## Evidence and completion

Report:

- Exact build identifier and actual scope.
- Changed paths and function-level behavior.
- Validation commands, results and limitations.
- New versus pre-existing failures.
- Compatibility and protected-hash results.
- Git branch, HEAD and final status.
- Provider, database, environment and deployment actions actually performed.
- Remaining owner decisions and the next authorization boundary.

Never claim a check ran or passed without evidence.

PROJECT_STATE.md updates must be within the authorized mutation scope. Record
verified facts and evidence references, not speculative completion or diary
entries.

If state-file updates are outside scope, report the pending update rather than
modifying an additional file automatically.

After the authorized operation, stop at its stated boundary.
