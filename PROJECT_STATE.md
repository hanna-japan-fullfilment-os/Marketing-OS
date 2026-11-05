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
