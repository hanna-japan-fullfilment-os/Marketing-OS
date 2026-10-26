# Governed local ComfyUI background integration

The local adapter is installed but **inactive by default**. Implementation and
mock tests do not authorize host activation, provider switching or inference.
The server-owned `backend/config/image_backends/background_routing.json` ships
with `enabled: false`; the manifest template is `UNAPPROVED` with null paths and
no owner approval. Existing provider/model settings remain authoritative while
local routing is disabled. No new environment key or database migration exists.

## Host and process boundary

Locked host runtime: `C:\MarketingOS\runtimes\comfyui-v6`. ComfyUI 0.42.1,
standalone 0.42.1-env1, Python 3.13.12, Torch 2.12.1+cu130, driver 617.42,
RTX 3060, three pinned SDXL/IP-Adapter/CLIP-Vision artifacts.
An externally supervised process owns `127.0.0.1:8189`; Marketing OS uses HTTP
only. Never import ComfyUI/Torch into the web process or start a server from an
image request. The pinned Comfy CLI/cuda_malloc bootstrap must precede Torch and
establish cudaMallocAsync. No allocator-policy workaround is permitted.

Host approval must bind all runtime files (including all custom-node code,
license and metadata) through a SHA256-approved runtime-lock inventory. The
inventory lists every runtime file except itself and the three separately pinned
model files. It must include the Python executable and Comfy startup sources.
Model filenames and content hashes are fixed by the adapter. Writable state and
approved reference roots are explicit, private, existing directories; state must
be outside both repository and protected runtime. Do not put host paths/secrets
or approval data into the tracked template during implementation.

## Admission and execution

Concurrency is **1**. An endpoint-wide Windows Global-namespace named mutex and process lock hold
admission through terminal cleanup. Existing Job identity, attempt, campaign,
platform, language, slide contract, reference, workflow and seed produce a UUIDv5.
Job metadata and a durable create-exclusive intent correlate the operation.
The durable inflight fence survives process crashes. Unknown terminal state
blocks further admissions until an operator reconciles queue/history and the
recorded intent. Never delete a fence to manufacture readiness.

ComfyUI accepts caller-supplied UUID prompt IDs but does not deduplicate POSTs.
Mutex access denial across runtime accounts fails closed; the host account/ACL
gate must establish shared access, never substitute a session-local mutex.
There is no automatic generation retry or paid fallback. Lost acknowledgements,
malformed replies and timeouts must not resubmit `/prompt`. A new separately
authorized attempt needs a new application Job/attempt identity. Prepared
carousel slides may execute sequentially once per admitted slide/variant;
recreating an adapter is not permission to retry a failed identity.

The adapter uses readiness `/system_stats`, node/model discovery, controlled PNG
upload, one `/prompt`, UUID history polling and owned `/view`. Initial mode is
trusted-reference Instagram 4:5 background only, high tier; no product edit,
masked scene, low-tier draft, best-of-N or image-regenerating QA. Other paid
text/research/vision roles remain independent and require their own authorization.

The template has 42 frozen fields and four populated fields: positive prompt,
reference filename, controlled seed and output prefix. Negative prompt, model
identities, topology, 1024x1280 batch1, steps30, CFG6, dpmpp_2m/karras, denoise1
and IP-Adapter weight0.6/style-transfer settings remain fixed.

Reference transport verifies trusted root containment, ID/SHA, PNG decoding,
one frame, <=20MiB and each dimension<=2048, then uploads those unchanged bytes
under the owned UUID name. No caller filesystem path or arbitrary graph/model
is accepted. Outputs require the exact history UUID/client/graph, one node11
safe owned-prefix PNG, empty subfolder, correct type, bounded bytes, exact
1024x1280 decoding and SHA256. Existing compositor/renderer places real product
and text at the final platform dimensions; the adapter is not art direction.

## Bounds, cancellation and evidence

External startup readiness is bounded at180s by the supervisor. Adapter default
absolute budget is300s (maximum600); phase maxima health5, upload15, submit10,
history240, retrieval20, with up to10s of the same budget reserved for cleanup.
Admission waits at most5s. There are no fresh cleanup deadlines or indefinite
waits. Stream control responses are <=4MiB and outputs<=32MiB, incrementally.
Cooperative asynchronous I/O is the deadline/cleanup guarantee scope.
Content/inventory integrity preflight precedes the HTTP budget and has its own
300s cooperative filesystem-read/traversal ceiling. It does not start ComfyUI
or load weights; hashes read bytes only. Slow or blocked synchronous OS I/O is
not a hard real-time guarantee, just as non-cooperative asynchronous I/O is not.

Use targeted `/api/jobs/{owned UUID}/cancel`, then confirm terminal history.
Never send global `/interrupt` or clear another job's queue. Unknown cleanup
retains the durable fence. Job cancellation persists CANCELLED, not RUNNING.
Failures surface as sanitized local domain codes and Job error states; missing
artifacts, CUDA/allocator/node failures need operator action, not auto-repair.

Immutable background/evidence includes generation/Job/campaign/slide identity,
reference/prompt/workflow/artifact/output hashes, submitted graph, UUID history,
runtime identity, duration, error/terminal state and explicit provider cost0.00.
Native logs belong to the external supervisor and are correlated by UUID and
timestamps. Optional unavailable GPU metrics are stated as unavailable.
Do not require `model-loads.jsonl`: the native aimdo mmap loader bypasses those
Python tracing hooks. Do not claim per-file OS tracing that was not collected.
Never log credentials, tokens or raw environment values. Provider cost excludes
electricity/hardware depreciation. Only the trusted local provider/model pair
has known-zero pricing; unknown zero-valued paid calls remain unpriced.

Preserve immutable evidence before any narrowly authorized job-owned input/output
retention cleanup. No input-delete API is assumed. Cleanup of dedicated host
directories is a separate operator/supervisor responsibility; do not globally
clear files, delete evidence or mutate product/reference originals.

## Activation, shutdown and rollback gates

`HOST_ACTIVATION_GATE_SHUTDOWN_SIGNAL_UNRESOLVED=TRUE`.
Prior CTRL_BREAK shutdown attempts timed out and used the authorized exact-tree
termination fallback. Static source inspection does not prove Windows signal
delivery. HTTP interrupt/free endpoints are not process shutdown APIs. Do not
repair or experimentally investigate the host signal issue in implementation.

Before activation separately authorize account/ACL/state-root preparation,
external supervision, full artifact approval and shutdown validation, then one
bounded isolated Marketing OS result-path integration verification. Only a later
authorization may enable routing. Disable admissions and drain/reconcile owned
work before disabling local routing; restoring the prior provider selection is
an explicit operator action, never automatic failure fallback. Preserve unknown
intents/evidence and verify the prior provider behavior after rollback.

Supervisor stop policy: drain, archive evidence, supported graceful stop with15s
bound, then only verified owned PID/creation-time tree or supervisor Job Object
termination if required, and verify process/children/port absent. Adapter never
stops the server per request. No executable-name-wide process killing.

Mocks must prove frozen fields, path safety, correlation, cross-process
concurrency1, no duplicate submission/retry/fallback, bounded streaming and
cleanup, explicit zero cost, cancellation and unchanged inactive behavior.
Real runtime startup/model loading/inference are forbidden in implementation QA.
Infrastructure execution is not semantic QA, owner acceptance or campaign
approval. Full existing claim/reference/coherence and current-QA approval gates
remain mandatory. Host activation is not complete.
