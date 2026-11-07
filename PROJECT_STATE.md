# Marketing OS — Verified Project-State Snapshot

## Record identity

PROJECT=Marketing OS
ENGINEERING_HISTORY=BUILD6R
STATE_KIND=VERIFIED_PRE_GOVERNANCE_INITIALIZATION_SNAPSHOT
VERIFIED_DATE=2026-11-04
DATE_TIMEZONE=Asia/Tokyo

GOVERNANCE_PREPARATION_BUILD=BUILD6R-GOV-0001
GOVERNANCE_PREPARATION_STATUS=DRAFT_FOR_OWNER_REVIEW
GOVERNANCE_INITIALIZATION_EXECUTED_AT_SNAPSHOT=FALSE

This record captures the baseline verified while preparing the governance
initialization. It does not claim that the proposed files were applied, committed,
integrated or deployed.

Reverify current reality before a later mutation. Snapshot hashes are not promises
that future authorized changes leave every recorded value unchanged.

## Repository snapshot

REPOSITORY=C:\My Apps\marketing-os\marketing-os_4
ORIGIN=https://github.com/hanna-japan-fullfilment-os/Marketing-OS
BRANCH=feature/build6r-v6-local-sdxl-comfyui-backend
HEAD=fb93bcb72f1240db23c1ca50e293c0d6565f12f5
TREE=ba7eaf9a988ab7b9658a7f35c2c080a2a7b1e39c
HEAD_PARENT=205da267e34fe7055818bd3a19c6aae5bdad5a39

HEAD_SUBJECT=Marketing OS: narrow product creative eligibility to confirmed prohibitions

LOCAL_MAIN=73e3ae84255b32eca46e93e0370c5f1a55b244de
CACHED_ORIGIN_MAIN=73e3ae84255b32eca46e93e0370c5f1a55b244de
REMOTE_MAIN_LAST_VERIFIED_IN_PROVENANCE_AUDIT=73e3ae84255b32eca46e93e0370c5f1a55b244de
REMOTE_FEATURE_LAST_VERIFIED_IN_PROVENANCE_AUDIT=73e3ae84255b32eca46e93e0370c5f1a55b244de

LOCAL_COMMITS_AHEAD_OF_CACHED_ORIGIN_MAIN=15
LOCAL_COMMITS_BEHIND_CACHED_ORIGIN_MAIN=0
TRACKED_CHANGES_AT_SNAPSHOT=0
STAGED_CHANGES_AT_SNAPSHOT=0
WORKTREE_FULLY_CLEAN=FALSE
EXISTING_UNTRACKED_DIRECTORIES=assets/,output/

Preserve all 15 local commits and existing untracked work. The current branch name
does not describe all later implementation work it contains.

No branch replacement, integration, reset, history rewrite or push is authorized
by this state record.

## Existing untracked work

assets/:
- 6 files.
- Instrument typography assets and licenses.
- Inventory digest:
  A7A2770E66DF4C9A72D6B53FDA0B86CB5E04DA0F638A150F137AAA0025A9B86C

output/:
- 86 files.
- Existing creative outputs, including two recomposition images under imagegen/.
- Inventory digest:
  8B31E3D3A26CF60BC8FC6778EB7EDEA0CC901BBA22D0ABC3906A6959233A9FE3

Inventory algorithm: sort existing file Paths under each directory; for each,
append UTF-8 str(path) followed by its binary SHA256 digest to an aggregate
SHA256. These are environment-specific inventory locks, not portable ZIP hashes.

Do not clean, stage, delete or relocate these directories by implication.

## Verified architecture

Backend: Python / FastAPI / Pydantic / SQLAlchemy.
Migrations: Alembic.
Database architecture: SQLite WAL, local filesystem.
Frontend: React / TypeScript / Vite.
Canonical database: backend/data/app.db.
SUPABASE_DATABASE=NONE

Sources:
- README.md, repository structure.
- docs/architecture.md.
- backend/requirements.txt.
- frontend/package.json.

No runtime was started and no new runtime/deployment acceptance was performed
during governance preparation.

## Protected canonical files

backend/data/app.db SHA256:
8ED3A33D0E77E1EB17AA96329E19FBCB4F1148AD2A87644241B803A7E068ADB9

backend/.env SHA256:
FCA76AB11BD09A28CB3442BCE7DBB35708D8DF9E6E70F0FE0A587CDB0167FB32

Database revision and runtime journal mode were not re-queried during this
preparation. Do not present historical revision information as a new live query.

Do not expose .env contents or mutate these files.

## Implementation and external-checkpoint distinction

LATEST_LOCAL_COMMIT:
fb93bcb72f1240db23c1ca50e293c0d6565f12f5
Marketing OS: narrow product creative eligibility to confirmed prohibitions

LATEST_BUILD6R_LABELLED_IMPLEMENTATION_COMMIT:
205da267e34fe7055818bd3a19c6aae5bdad5a39
BUILD6R V12.10 repair campaign architecture and format strategy

REMOTE_CHECKPOINT_LAST_VERIFIED:
73e3ae84255b32eca46e93e0370c5f1a55b244de
BUILD6R: add governed local ComfyUI background backend

V12.85 identifies external creative/audit checkpoints in this work history.
No corresponding V12.85 implementation commit was found in available Git history.

Do not infer implementation completion, integration, deployment or visual approval
from external checkpoint numbering.

## Hanna creative workflow

The repository documents an external premium handoff/import/human-review workflow
for Hanna Japan in docs/BUILD6R_V121_PREMIUM_HANDOFF.md.

Technical QA, exact-copy/product checks and owner visual acceptance remain
independent.

Purpose-Aware Premium Creative Execution Contract:
- Preparation was conditionally authorized in the owner conversation.
- Implementation did not begin.
- Canonical implementation build identifier remains unassigned.
- Governance reconciliation must complete before implementation is resumed.
- This snapshot authorizes no source implementation or creative generation.

## Protected creative evidence root

ARTIFACT_ROOT:
C:\Users\wesle\.codex\visualizations\2026\10\19\01a153bb-7fc6-78a1-8807-237d1af269c6

The following paths are relative to ARTIFACT_ROOT.

PRODUCT_MASTER:
HANNA_SLIDE5_EXTERNAL_PREMIUM_HANDOFF/assets/LOCKED_PRODUCT_MASTER.png

PRODUCT_MASTER_SHA256:
DA2D4EA98E7D3549B65493AC0A93431C9A317383973FC8225A7943232E5417A1

PRODUCT_MASTER_TYPE:
OWNER_APPROVED_RECONSTRUCTED_CAMPAIGN_ASSET

This master has reconstruction provenance. It is not an original camera
photograph or manufacturer-original packshot.

HANNA_LOGO:
HANNA_SLIDE5_EXTERNAL_PREMIUM_HANDOFF/assets/HANNA_LOGO_DISPLAY.png

HANNA_LOGO_SHA256:
4CF095F0B446953147B33BC7668228C1E535F3D3814FB0CEB2E3E727E181B8C6

## Frozen Slides 1–6

Freeze manifest:
BUILD6R_V1277_BATCH04_SLIDES_7_8/CANONICAL_SLIDES_1_6_FREEZE.json

Freeze manifest SHA256:
072C4541A533DC7348D3E95DE458E3045490DE263FEBA9722A81A20E99A910A8

All six artwork hashes matched this manifest during preparation.

Slide 1:
BUILD6R_V1263_SLIDE1_PACK_SPEC_CONTRAST/HANNA_10_SLIDE_1_PACK_SPEC_CONTRAST_FINAL_1080x1350.png
303D83562F0AD2D11D60DEC5224655E175F06CA661BC6A3B92812A95C1A6D66A

Slide 2:
BUILD6R_V1257_BATCH01_SLIDES_1_2/HANNA_10_SLIDE_2_FINAL_1080x1350.png
8BF7F9ABB4B147483AFFB392C92658AC033EAAF5B5FEC0537F5052D917D27AED

Slide 3:
BUILD6R_V1265_BATCH02_VERTICAL_BALANCE/HANNA_10_SLIDE_3_FINAL_1080x1350.png
B435A26CB05854C2CFDF0974056EF0CB94FA35E18E88A0B75C940267F41FF4FB

Slide 4:
BUILD6R_V1273_SLIDE4_TYPEFACE_CHARACTER/HANNA_10_SLIDE_4_FINAL_1080x1350.png
F5E296CF9ABEE7DB5B2026409D93A50D94D371023BE81D5EBBC02D69E6D7468E

Slide 5:
BUILD6R_V1276_BATCH03_POLISH_ROUTINE/HANNA_10_SLIDE_5_FINAL_1080x1350.png
D3452BA176D87E4C9154156CB8670A22433C8F826E7256963D7E52834F8D4D27

Slide 6:
BUILD6R_V1276_BATCH03_POLISH_ROUTINE/HANNA_10_SLIDE_6_FINAL_1080x1350.png
A859A2D42720E1CAE6037A721A17D1322766FE34CE2804A538E00AFE1A9D0C37

The freeze manifest records:
- Slide 5: PASSABLE_NEAR_TARGET_APPROVED.
- Slide 6: PREMIUM_TARGET_ACCEPTED.

Freezing does not promote every slide to premium-target acceptance.
Preserve earlier owner decisions and accepted limitations.
Do not modify or regenerate these artworks automatically.

## Latest rejected Slides 7–8

Evidence:
SLIDES_7_8_PREMIUM_EDITORIAL_RECOMPOSITION/RECOMPOSITION_CLOSEOUT_EVIDENCE.json

Evidence SHA256:
C0F9763FD55D7CA693CCE153F9CC88F0D1CF258C1706BEFF51786214493348E5

Slide 7:
SLIDES_7_8_PREMIUM_EDITORIAL_RECOMPOSITION/HANNA_SLIDE_7_EDITORIAL_RECOMPOSITION_1080x1350.png
742D49D06EC6954CE86FDD24B9873BB3D7C13D82B182E1ADEFD4314EC4893679

Slide 8:
SLIDES_7_8_PREMIUM_EDITORIAL_RECOMPOSITION/HANNA_SLIDE_8_EDITORIAL_RECOMPOSITION_1080x1350.png
EE5DC44B981CF06890E33564C6D7AE1AD1E35204A995EEBABC61DC8E4D2F45D4

Both evidence decisions are FAIL.
Internal premium-feel assessments were 7.5 and 7.7, below the owner's 9.0 bar.
Those numbers are subjective assessments, not calibrated automated measurements.

The output hashes matched during preparation.
No canonical replacement or owner approval is inferred.
Slides 9–10 remain unrendered in the active ten-slide production sequence.
No automatic retry is authorized.

## Governance provenance

Imported file at baseline:
backend/CLAUDE.md

Introducing/root commit:
7f5c874187fad46d143728571d385f6f8bdad987

Commit subject:
chore: establish Marketing OS Build 6R V3.12 baseline

Git blob:
97c6742839fb105cce2ef82b371238536c93e80a

Raw committed blob SHA256:
0932A50B5D2DD3472F27ABF91B672E3743E5C232B802772079FF6DA3A38186B4

Pre-replacement working-tree SHA256:
54DF08FA99C477A42352C039716445797D07ADA786374BD45FD78459965D22BD

The original file already identified BJM in the root commit.
The same blob was found across all 69 refs inspected in the provenance audit.
No earlier Marketing OS contract or PROJECT_STATE.md was recovered.
Accidental copying versus intentional inclusion remains undocumented.

The archive is to preserve the raw committed blob without editorial additions.
The original working-tree bytes are exactly recoverable by converting the pinned
blob's LF line endings to CRLF; this equality was verified before initialization.

## Unresolved owner decisions

- Approval and application of the four-file governance initialization.
- Subsequent branch/integration/commit/push disposition.
- Exact identifier and bounded authorization for the proposed creative execution
  implementation after governance reconciliation.
- Visual approval of future Slides 7 and 8.
- Any later runtime activation, provider execution, publication or deployment.

No tests were executed during this read-only governance preparation.
Historical tests and scoped baseline exceptions are not re-certified here.

## BUILD6R-EXEC-0001 implementation record — 2026-11-05

This appended record does not rewrite the pre-initialization snapshot above.

BUILD=BUILD6R-EXEC-0001
TITLE=Purpose-Aware Premium Creative Execution Contract
AUTHORITY=Explicit owner implementation authorization in this conversation
BASE_HEAD=16df113739cc11d963e67e85d336652ed34bb107
BASE_TREE=8789c1487f2c6ae997e2437ede05de290c878dcd
BRANCH=feature/build6r-v6-local-sdxl-comfyui-backend
IMPLEMENTATION_STATUS=IMPLEMENTED_LOCALLY_NOT_COMMITTED

Scope: four source files, three existing test files, two existing workflow docs
and this state record. No additional repository files are authorized.

The opt-in offline strategy service produces purpose-based execution proposals.
Explicit version-2 handoff adoption requires complete structured requirements,
exact brief/reference bindings and named owner approval before production export.
Import technical validation remains separate from human artwork acceptance.
Legacy v1 serialization/digests/reviews remain compatible; no automatic campaign
upgrade, canonical artwork replacement or historical approval mutation occurred.
The existing frontend/API continues its legacy path; no v2 editor or provider
dispatch is included. Free-text plan quality requires human review and cannot be
certified by schema validation or a numeric aesthetic score.

QA: 117 focused tests and 80 directly dependent regression tests passed, zero
failures/skips. The final six-file suite produced 195 passes; two subsequently
added write-boundary tests produced two more passes. No baseline exception used.
External socket attempts in the complete suite: zero. Windows in-process HTTP
tests required loopback outside the filesystem/network sandbox; external sockets
remained denied and DATABASE_URL was isolated before imports.

Evidence relative to the protected artifact root above:
- BUILD6R_EXEC_0001_FINAL_TESTS.xml (195 passing tests)
- BUILD6R_EXEC_0001_BOUNDARY_TESTS.xml (2 passing tests)
- BUILD6R_EXEC_0001_COMPLETION_EVIDENCE.json (final scope/hash verification)

Canonical DB, .env, product master, logo, frozen Slides 1–6, rejected Slides 7–8
and existing untracked assets/output inventories were protected by hash locks.
No canonical DB/environment writes, provider calls, image generation, runtime
activation, deployment, staging, commit, push or branch change was authorized or
performed. Source remains uncommitted for owner review; no creative run follows
automatically. No premium visual acceptance is claimed by these engineering tests.

## BUILD6R-EXEC-0002 implementation record — 2026-11-07

BUILD=BUILD6R-EXEC-0002
TITLE=Claim Authority Freshness & Purpose-Aware Factual Validation
AUTHORITY=Explicit bounded owner implementation authorization in this conversation
BASE_HEAD=2441d58553965bd0549a43e9fbf813311709f11d
BASE_TREE=35298e66463eac84113a638cd441eaa100b68222
BRANCH=feature/build6r-v6-local-sdxl-comfyui-backend
IMPLEMENTATION_STATUS=IMPLEMENTED_LOCALLY_NOT_COMMITTED

Scope: marketing_claims.py, premium_handoff.py and premium_ingestion.py; existing
v124_claims_gate, v121_handoff and v121_ingestion tests; the premium handoff
workflow document; and this state record. No schema, catalog, migration, frontend
or route changes. No new claim registry.

Production export/import/review/readiness/revision now require current canonical
campaign context and recheck the existing claim library and live database
provenance. Canonical resolution rejects dirty sessions before queries, expires
cached identities, and reloads persisted campaign plans and current evidence.
Supplied historical handoffs cannot replace canonical purpose/copy/package/asset
bindings. Missing context fails closed before production output/state writes.

Benefit-free application/aftercare requires the independently resolved canonical
purpose, exact ex-apply/ex-after factual wording and evidence, current library
approval, qualifiers and an empty benefit hierarchy. Benefit-oriented and generic
usage briefs retain their previous benefit requirements. Legacy v1 serialization
and digests, v2 owner plan approval and independent artwork review are preserved.
No existing campaign was upgraded, re-exported, imported, approved or rewritten.

QA: pristine committed baseline focused suite: 101 passes, zero failures/skips.
Final source suite: 213 focused plus 104 dependent regression passes = 317 passes,
zero failures/skips. No baseline exception. Development failures in new fixtures
(missing selected reference, then transient versus SQLite-loaded timestamp
snapshots) were corrected without weakening assertions or production validation.
The final tests include real isolated persisted campaign/evidence integration,
cross-session revocation, v1/v2 factual exports, forged purpose/rebound digests,
historical injection and rejection before state reads/flushes. Existing warnings
were also present in the baseline. External socket attempts: zero.

Tests configured isolated SQLite/output paths before application imports, disabled
production dotenv loading and denied repository writes/nonisolated SQLite opens.
Windows in-process HTTP tests used bounded loopback access; no application server,
frontend or production API runtime was activated. No dependency installation.

Evidence root (noncanonical):
C:\Users\wesle\.codex\visualizations\2026\11\06\01a1b125-e0e5-7413-9c61-5d0f354500f1
- EXEC0002_QA/baseline_full.xml
- EXEC0002_QA/verified_final.xml
- EXEC0002_QA/verified_final_network.json
- BUILD6R_EXEC_0002_COMPLETION_EVIDENCE.json

All 46 prior protected locks matched preflight and completion, including canonical
DB, .env, claim matrix, reconstructed master, logos, references, frozen Slides
1–6 and rejected Slides 7–8. Existing assets/output inventories were preserved.
Canonical database/environment/settings/claim approval/campaign/artwork mutations,
provider/image/paid calls, runtime activation, deployment, staging, commits and
pushes: zero. Only isolated fixture data and noncanonical QA artifacts were written.

Engineering implementation PASS does not establish current campaign readiness.
Whole-library owner approval remains PENDING; live canonical ten-slide purpose/
evidence compatibility and later v2 adoption were not activated or certified.
Slides 7–8 plans and artwork remain unapproved. Owner review and explicit Git
preservation authorization are the next boundaries; no automatic next build.

## BUILD6R-EXEC-0003 Phase 1 implementation record — 2026-11-07

BUILD=BUILD6R-EXEC-0003
TITLE=Canonical Ten-Slide Campaign & Premium Handoff Reconciliation
AUTHORITY=Explicit owner Phase 1 implementation authorization attached in this conversation
BASE_HEAD=1d881105b93e6870727302773c5e56be3198873d
BASE_TREE=a29ff1ee99cdfbd564f2403d296449816fbcde20
BRANCH=feature/build6r-v6-local-sdxl-comfyui-backend
IMPLEMENTATION_STATUS=IMPLEMENTED_LOCALLY_NOT_COMMITTED

Eight source paths: new canonical_campaign_reconciliation service; premium handoff
schema, marketing claims, Hanna package, handoff, ingestion, product asset selection
and orchestrator. Tests: new exec0003_campaign_reconciliation plus the existing
product_master_selection file. Documentation: premium handoff workflow and this
record. Other authorized existing test files were exercised without modification.
No additional repository paths, migrations, routes or frontend changes.

Deterministic in-memory preparation produces complete ten-slide plans and proposed
campaign/slide/output records, preserving exact approved copy and reviewed claim
assignments. Current V3.45 evidence and source relationships remain authoritative.
The approved architecture/approval/freeze, source/master/logo and approved reference
hashes are locked. Product identity is checked against the current canonical Product.
Factual/editorial exceptions require independently resolved canonical reconciliation;
benefit slides retain benefit hierarchies and the library freshness gate is unchanged.

The separate versioned production-scope envelope binds all ten canonical briefs,
frozen/deferred exclusions, only Slides 7–8 execution plans and exact named owner
release approval. Full export and frozen/deferred intake/revision are rejected.
Selected-release completion never establishes whole-campaign or publishing readiness.
Historical artwork classifications remain references, not adopted approvals.
Campaign-scoped masters/logos cannot become global defaults. Legacy v1 serialization
and existing v2 execution/artwork approval boundaries remain unchanged.

Canonical application is deliberately disabled in Phase 1: apply_campaign rejects
all calls before writes, including boolean authorization flags. A separately
authorized Phase 2 data-operation adapter is still required. No campaign, evidence,
asset registration or approval was created in the canonical database. The historical
six-slide acceptance fixture was not migrated or repurposed. No production activation.

QA evidence (noncanonical):
C:\Users\wesle\.codex\visualizations\2026\11\06\01a1b125-e0e5-7413-9c61-5d0f354500f1\EXEC0003_QA
- baseline_verified.xml: 239 committed-baseline passes.
- focused_final.xml: 52 new reconciliation cases passed.
- boundary_final.xml: 5 additional cross-session consumer cases passed.
- record_payload_final.xml: updated prepared-record assertions passed.
- regression_verified.xml: final dependent/compatibility regression evidence.
- BUILD6R_EXEC_0003_COMPLETION_EVIDENCE.json: completion scope, hashes and counts.

The accepted coverage is 297 focused plus 140 dependent cases = 437 distinct cases,
zero failures/errors/skips; the record-payload rerun repeats one accepted case.
No baseline exception. An early new-fixture error assumed editorial wording had a
STANDARD variant; corrected to use its existing reviewed variant without changing
approved wording or weakening assertions. The first sandboxed HTTP run was interrupted;
the same committed baseline passed with bounded local loopback access. Existing
Pydantic/testclient warnings also occur in the baseline.

All test resources were isolated before application imports; production dotenv reads,
repository test writes, nonisolated SQLite opens and external network connections
were denied. Provider/image/paid calls: zero. No application server or runtime was
activated. Pillow created isolated test fixtures only, not campaign artwork.

The 46 protected hashes and existing assets/output inventories matched preflight
and completion. Canonical DB, environment, claim-library approval, campaign data,
protected artwork, staging, commits, pushes, integration and deployment unchanged.
Live ten-slide reconciliation remains unactivated; eight exact evidence mappings,
press-release source representation, campaign-scoped metadata and independent owner
decisions remain Phase 2 work. Whole-library approval is still PENDING. No automatic
next phase, export, ingestion, provider operation or Git preservation is authorized.


## BUILD6R-EXEC-0003 — Guarded application adapter (isolated QA only)

Implemented against HEAD fab045f1edd8a4a4047705febe2eb0292a92f054,
tree 62d972e233846f5db90e11926ce0882ccc031d3c. Scope: three source files,
three existing test files, premium handoff workflow documentation and this state file.
This checkpoint supersedes the Phase 1 disabled-adapter implementation description;
it does not authorize or record canonical application.

Product selection now forwards canonical campaign identity to the existing approved
master selector; global defaults and independent campaign permission requirements
remain intact. A separate typed authorization payload leaves existing v1/v2 schema
classes unchanged. The adapter requires an independently persisted owner authorization
AuditEvent, current evidence/library approval, exact campaign/product/master/permission
bindings, reviewed package identity and complete ten-slide dispositions. Caller flags
or supplied digests cannot establish authority. No authorization event is created by
application; a trusted, separately authorized operator must establish that prerequisite.

Application validates before mutation, obtains BEGIN IMMEDIATE, revalidates authority
under the lock and again after file publication, and commits exactly thirteen new
draft records in one database transaction. Exclusive files and an immutable intent
record support owned-file cleanup and read-only recovery inspection. Filesystem and
SQLite publication are not a single atomic operation: ambiguous commit outcomes,
changed files and interrupted/orphaned state fail closed for explicit recovery.
Identical completed applications are recognized without adopting approvals or orphans.
Historical six-slide records and frozen artwork remain preserved.

Final isolated QA: 259 focused plus 371 dependent tests = 630 passed, zero failures,
errors or skips (18 warnings). Committed baseline: 207 passed. One development
concurrency fixture failure was corrected by capturing its immutable product ID before
worker threads; concurrency assertions were retained. No baseline exception.
Tests include authorization/staleness, lock-time revocation, collisions, concurrent
attempts, file publication/fsync/flush/commit faults, lost commit acknowledgement,
unknown outcomes, interrupted recovery, scoped/global selection and v1/v2 compatibility.
All six source/test hashes remained identical throughout the accepted final run.

Noncanonical evidence directory:
C:\Users\wesle\.codex\visualizations\2026\11\06\01a1b125-e0e5-7413-9c61-5d0f354500f1\EXEC0003_ADAPTER_QA
Accepted evidence: baseline_verified.xml; verified_final.xml;
verified_final_network.json; verified_final_source_hashes.json;
BUILD6R_EXEC_0003_ADAPTER_COMPLETION_EVIDENCE.json.
Production dotenv reads, repository test writes, nonisolated SQLite access and external
socket connections were denied; bounded loopback supported isolated test clients.

No canonical database, evidence, approval, campaign, environment or artwork mutation;
no provider, image-generation or paid call; no runtime activation or deployment.
Protected hashes and untracked inventories are reverified in the completion manifest.
No staging, commit, push or main integration. Git preservation requires separate
explicit authorization. Canonical operation remains blocked on reviewed evidence and
source registration, truthful reconstructed-master provenance, campaign-specific
permission, library/owner decisions and independently authorized concrete application.
No prerequisite registration, Phase 3 or subsequent build is implied.
