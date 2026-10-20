# Managed Windows deployment foundation — BUILD6R V3.46

Implementation does not authorize deployment. No scheduled task, account, ACL,
firewall, Tailscale, Caddy acquisition, canonical migration or activation is
performed by installation of these source files. Every operational entry point
requires an explicit configuration and execution argument. Do not invoke it on
production until the corresponding operation is separately authorized.

## Architecture and persistent paths

Option B uses the existing Windows PC, local SQLite WAL, Uvicorn on
127.0.0.1:8000 (one worker, lifespan on, no reload), and private Caddy on port
8080. Caddy serves a Vite build and strips `/backend` before proxying to Uvicorn.
SPA routes fall back to index.html. There is no public binding, automatic public
TLS, Supabase, container, or paid service requirement.

Immutable releases live at `C:\MarketingOS\releases\<approved-commit>`.
`C:\MarketingOS\current` is a JSON file, not a directory/junction. It records
the release path, commit and approved release.json SHA256. Launchers resolve it.
Same-volume File.Replace retains a unique previous-pointer file. Initial
activation uses same-volume File.Move. Neither requires symlink privilege.
Atomic namespace replacement does not promise survival of arbitrary disk failure.

Persistent SQLite remains at
`C:\My Apps\marketing-os\marketing-os_4\backend\data\app.db`.
Launchers set an absolute DATABASE_URL; never reuse the relative development URL
after changing working directory. Keep the observed source and output roots:

* `C:\Users\wesle\OneDrive\Desktop\Marketing Pictures Input`
* `C:\Users\wesle\OneDrive\Desktop\Marketing Pictures Output`

Existing DB rows contain absolute paths. Do not migrate asset locations as part
of deployment. Confirm OneDrive files are locally available without interactive
sign-in. Output ACLs currently include a child-deletion deny; verify required
operations explicitly. Configuration validation rejects reparse traversal; cloud
placeholders/junctions that violate this policy remain a deployment gate.

## Approval inputs and secrets

Copy host-config.example.json into an operator-controlled location OUTSIDE the
release, fill only verified values, and protect configuration/evidence against
runtime modification. Do not treat example values as deployment approval.
All eight gates default false. Each requires an approved evidence file and its
SHA256. Attestations are operator assertions; hashes prove identity, not the truth
of their contents. Disk numbers, identities, versions, files and DB schema are
also checked programmatically. Do not approve evidence from an untrusted writer.

The preflight Implementation mode reports readiness without resolving host
gates. Deployment mode refuses unresolved values. Passing implementation QA
never makes the host deployment-ready. Evidence for PRODUCTION_ACCEPTANCE must
come from a separately authorized isolated candidate acceptance before the first
production activation; actual production acceptance must still run afterwards.
This prevents a circular requirement to start an unaccepted candidate publicly.

No secrets belong in host config, manifests, XML, logs, release source or command
arguments. Runtime provider secrets must be provisioned separately through the
approved account environment; `.env` is never copied. DB `settings` rows override
environment-backed source/output/provider settings. DATABASE_URL is not a DB
override. Confirm DB effective roots match the host contract before activation;
environment values alone cannot override settings_store. Release config and the
settings table are operator-controlled and must not change during release.

## Frozen runtime and immutable staging

The frozen requirements file records ALL observed installed distribution versions,
including test tooling, from the validated Python 3.14.6 AMD64 environment.
Versions are not artifact provenance. runtime-manifest.json intentionally says
artifactsApproved=false: interpreter distribution, wheels, Node/npm and browser
hash/provenance approvals are outstanding. No index access or package installation
is performed by QA or the staging tool.

After separately authorized provisioning, create the final release directory and
prepare its venv in place at backend/.venv and dependencies at frontend/node_modules.
Do not copy or move an existing venv: launchers and pyvenv.cfg may contain absolute
paths. New-Release requires these prepared directories, explicit approved commit,
clean source, runtime approval, -Stage and -BuildFrontend. It exports an allowlist
of committed text, rejects secret/data/photo/log/backup content, and performs the
frontend build with VITE_API_BASE_URL=/backend. It never installs dependencies.
Partial staging is retained on failure; do not reuse it without operator review.
An existing release.json is immutable and cannot be overwritten.

Release.json inventories every file, including prepared dependencies. Approval
of its hash is separate from creation. Read-Release rejects missing, changed,
extra and traversal artifacts. Filesystem permissions must enforce immutability;
a manifest alone cannot stop concurrent edits by a privileged writer. Release
paths and all parent directories must be local, canonical and non-reparse.
Production runtime writes logs outside the release and disables Python bytecode.

## Database lifecycle

Quiesce workflows and stop tasks before release/migration/rollback. Assert-Offline
requires stopped Backend/Frontend tasks and no backend listener. No script blindly
kills a PID from a stale file. A named per-DB mutex serializes governed operations;
the backend holds it during its owned runtime. An unrelated manual app process
must also be stopped. These controls do not protect against an administrator
writing SQLite through an independent tool.

Before app import, the guard requires an existing absolute canonical DB,
quick_check=ok, exactly one approved Alembic row, the exact schema fingerprint and
prerequisite tables, verified release files, and one exact migration head.
The fingerprint covers tables, columns, constraints, defaults and indexes through
sqlite_master SQL; it intentionally rejects even unapproved schema additions.
The app's automatic upgrade then has no revision to execute. Its SQLite WAL
initialization and seeding remain normal application writes, not a read-only
startup guarantee. There is no invented disable-migration environment flag.

The guard never imports app.db/main. Without a live WAL it uses an immutable
read-only connection; with a live WAL it uses SQLite mode=ro and requires existing
SHM. Normal live read locks may touch existing SHM infrastructure, never main DB
data. It refuses a live WAL lacking SHM rather than creating sidecars. Never use
immutable reads to ignore a nonempty WAL. Governed canonical QA runs only without
WAL/SHM and verifies file hashes before/after.

Invoke-GovernedMigration requires explicit authorization ID, from revision,
target, source DB hash, approved source schema contract and release identity.
It requires stopped processes, a verified SQLite API backup on independent
storage, unchanged source hash, and exactly ONE Alembic upgrade invocation.
No stamp, downgrade, automatic retry or restore exists. The target must equal
the approved release revision. Current V3.45 DB already equals e3f4a5c1d001;
no migration is needed and no-op migration requests are refused.

Failure preserves backup, authorization, attempt marker, native output and failure
evidence. KEEP THE APP OFFLINE. A timeout or partial DDL failure is not permission
to run again. Separate restoration authorization is mandatory. Assess transactional
and nontransactional effects, WAL state, and later writes before any recovery.

## Backups and retention

Backups use SQLite's backup API, never a live raw main-file copy. The helper checks
revision, quick_check, schema, row counts and sorted row digests before/after.
Changing data during copying fails verification and retains the file as evidence.
Backup operation is bounded. An exclusive destination prevents overwrite.
Source main-file SHA256 is recorded alongside the logical snapshot; in WAL mode
that SHA alone does not identify all committed data.

Production backup requires evidence and a different physical DiskNumber, then
verifies the independent copy hash and SQLite contract. Same-disk backups do not
provide disk-loss protection. No existing independent destination has been approved.
Daily backup is 02:00 JST and requires Windows Tokyo Standard Time; tooling never
changes the host timezone. Pre-release backup is explicit. Retention keeps the
union of 14 daily, 8 weekly and 12 monthly snapshots. Default is plan-only;
-ApplyRetention separately requests deletion of verified tool-owned copies and
manifests within approved roots. Unknown files and the preserved V3.45 backup are
never candidates. Test restoration to an isolated database under separate recovery
authorization; this tool has no restore operation.

## Tasks, account, logs and stopping

Tasks run as the approved existing account without highest privileges, even though
WESLEY\wesle has administrator membership. A dedicated account may be preferable
later, but does not currently have approved asset/browser access. Verify batch
logon rights, protected credential storage and unattended OneDrive availability.
Password-based task registration receives PSCredential in memory; it is never
serialized. Installer requires separate authorization and rejects existing tasks.
Partial task registration failures retain evidence and require operator review.

Backend/Frontend boot tasks use IgnoreNew, unlimited runtime, 60-second crash
restart interval and at most three Scheduler restart attempts. Preflight refusal
records evidence and exits zero to avoid retrying startup guards/migrations; a
zero task result alone is therefore NOT readiness. Reboot/manual starts recheck
all guards. The frontend requires verified private identity and bounded backend
health readiness (180 seconds), then launches only an approved Caddy binary.
The backup task runs daily, does not overlap, and has no restart policy.

Logs are per-run directories under logsRoot, with process identity, output,
exit/guard evidence. No arbitrary PID termination is used. To stop a managed
process, create stop.request in its exact active run directory after verifying
process.json identity. The supervisor offers CloseMainWindow then waits 15 seconds;
console processes may not support it, so an owned process-tree termination can
follow. An intentional stop returns success to suppress Scheduler crash restart;
evidence retains the actual child exit code and forced-termination status.
Quiesce workflows first. Do not claim a hard termination is graceful ASGI
shutdown. Verify no owned children/listeners remain; do not use Task Scheduler
force-end as routine lifecycle control. Graceful console signalling under the
chosen production account remains a production acceptance check.

## Activation, rollback and acceptance

Set-ActiveRelease requires the operator to STOP first, then validates release and
DB compatibility, creates/verifies the independent pre-release backup, atomically replaces the pointer, starts Backend then Frontend,
and runs acceptance. It never silently migrates or restores. A failed activation
does not auto-switch the pointer: stop processes, preserve evidence and decide.
Restore-PreviousRelease requires a hashed previous pointer and a configuration
explicitly approving the previous commit/tree and compatible schema. Code rollback
cannot repair an incompatible migrated DB. DB restore requires separate approval
and reconciliation of writes made after backup.

Acceptance uses only safe GETs: backend health, private proxy health, one approved
product's verified facts, frontend root/static asset and SPA deep link. It checks
release, DB, roots and hashed separately collected startup observation for the
same commit/manifest with real ASGI startup and zero provider calls. HTTP 200 alone
does not prove lifespan or provider non-use. No paid/provider workflow is invoked.
The observer artifact is a separate governed input; this build does not fabricate
it or start production to collect it. Provider-secret provisioning and any future
provider workflow approval are separate. Instagram public-media fetching is not
enabled by a private-only origin.

## Deployment blockers and focused QA

Outstanding gates: INDEPENDENT_BACKUP, APPROVED_CADDY, TAILSCALE_IDENTITY_ACL,
UNATTENDED_TASK_RIGHTS, FILESYSTEM_ACCESS, ONEDRIVE_AVAILABILITY,
VERIFIED_RUNTIME_ARTIFACTS, PRODUCTION_ACCEPTANCE. No MagicDNS name is assumed.
Acquire an explicitly approved official Caddy Windows AMD64 release only under
separate authorization; record version, provenance, license, SHA256 and modules.
No public Internet binding is acceptable by default. Validate operator-device ACL
in the tailnet and host interface without changing it in this build.

Run focused isolated QA from the repository:

```powershell
& .\backend\.venv\Scripts\python.exe -B -m unittest discover -s tests/production -p test_sqlite_guard.py -v
& .\tests\production\test_windows_tooling.ps1
```

In a restricted runner with an unusable redirected temporary directory, set
MARKETINGOS_TEST_TEMP for Python and pass -TemporaryRoot to the PowerShell test,
both pointing to an existing authorized writable QA root. These are fixture
locations, never production configuration or a reason to change Windows ACLs.

Tests use fresh temporary roots/databases only, parse PowerShell/XML and exercise
schema/revision failures, backup integrity, retention, immutable manifests, source
heads and pointer switches. They never register tasks, launch production, contact
providers or mutate canonical data. Production acceptance is still outstanding.
