"""Explicit, inactive-by-default local background adapter. No model installers.

The bundled manifest is UNAPPROVED. A separately governed, pinned runtime is
required before even constructing an HTTP client. Generated pixels are never
product/claim evidence, and this adapter cannot approve creative QA.
"""
from __future__ import annotations

import asyncio
import copy
import hashlib
import io
import json
import re
import sys
import uuid
import time
from contextvars import ContextVar
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from PIL import Image

BACKEND = "LOCAL_COMFY_SDXL"
MODEL = "local-sdxl-background-v1"
_HASH = re.compile(r"[a-fA-F0-9]{64}\Z")
_CLASSES = {
    "CheckpointLoaderSimple", "CLIPTextEncode", "EmptyLatentImage", "LoadImage",
    "CLIPVisionLoader", "IPAdapterModelLoader", "IPAdapterAdvanced", "KSampler",
    "VAEDecode", "SaveImage",
}
_ARTIFACTS = {"checkpoint", "clip_vision", "ip_adapter", "custom_node_code", "runtime_lock"}
_VALIDATION_DEADLINE = ContextVar("local_manifest_validation_deadline", default=None)


def _check_validation_deadline():
    deadline = _VALIDATION_DEADLINE.get()
    if deadline is not None and time.monotonic() >= deadline:
        raise LocalBackgroundError("TIMEOUT")


class LocalBackgroundError(ValueError):
    """Local configuration/request/output failed; no fallback is authorized."""

    def __init__(self, message, *, code=None):
        self.code = code or (message if re.fullmatch(r"[A-Z_]+", message) else "LOCAL_REQUEST_INVALID")
        super().__init__(message)


def digest(path: Path) -> str:
    _check_validation_deadline()
    hashed = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024**2), b""):
            _check_validation_deadline()
            hashed.update(block)
    return hashed.hexdigest()


def _hash(value) -> str:
    if not isinstance(value, str) or not _HASH.fullmatch(value) or len(set(value)) == 1:
        raise LocalBackgroundError("Missing or unverified SHA256")
    return value.lower()


def _url(value: str) -> str:
    parsed = urlsplit(value)
    if (parsed.scheme != "http" or parsed.hostname != "127.0.0.1"
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path not in ("", "/") or parsed.port != 8189):
        raise LocalBackgroundError("Explicit IPv4 loopback HTTP runtime URL required")
    return value.rstrip("/")


PINNED_MODEL_HASHES = {
    "checkpoint": ("sd_xl_base_1.0.safetensors", "31e35c80fc4829d14f90153f4c74cd59c90b779f6afe05a74cd6120b893f7e5b"),
    "ip_adapter": ("ip-adapter-plus_sdxl_vit-h.safetensors", "3f5062b8400c94b7159665b21ba5c62acdcd7682262743d7f2aefedef00e6581"),
    "clip_vision": ("CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors", "6ca9667da1ca9e0b0f75e46bb030f7e011f44f86cbfb8d5a36590fcd7507b030"),
}
# Independent closed graph, not a second caller-controlled JSON approval.
_FROZEN = {
    "1": ("CheckpointLoaderSimple", {"ckpt_name": "__CHECKPOINT__"}),
    "2": ("CLIPTextEncode", {"text": "__PROMPT__", "clip": ["1", 1]}),
    "3": ("CLIPTextEncode", {"text": "product, package, pouch, bottle, box, logo, label, text, letters, award, ranking, badge, person", "clip": ["1", 1]}),
    "4": ("EmptyLatentImage", {"width": 1024, "height": 1280, "batch_size": 1}),
    "5": ("LoadImage", {"image": "__REFERENCE__"}),
    "6": ("CLIPVisionLoader", {"clip_name": "__CLIP_VISION__"}),
    "7": ("IPAdapterModelLoader", {"ipadapter_file": "__IP_ADAPTER__"}),
    "8": ("IPAdapterAdvanced", {"model": ["1", 0], "ipadapter": ["7", 0], "image": ["5", 0],
        "clip_vision": ["6", 0], "weight": 0.6, "weight_type": "style transfer", "combine_embeds": "concat",
        "start_at": 0.0, "end_at": 1.0, "embeds_scaling": "V only"}),
    "9": ("KSampler", {"model": ["8", 0], "positive": ["2", 0], "negative": ["3", 0], "latent_image": ["4", 0],
        "seed": 0, "steps": 30, "cfg": 6.0, "sampler_name": "dpmpp_2m", "scheduler": "karras", "denoise": 1.0}),
    "10": ("VAEDecode", {"samples": ["9", 0], "vae": ["1", 2]}),
    "11": ("SaveImage", {"images": ["10", 0], "filename_prefix": "__OUTPUT__"}),
}


def _contained(path, root):
    path, root = Path(path), Path(root)
    if not path.is_absolute() or ".." in path.parts or path.is_symlink() or path.is_junction():
        raise LocalBackgroundError("PATH_NOT_APPROVED")
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(root.resolve(strict=True)):
        raise LocalBackgroundError("PATH_NOT_APPROVED")
    return resolved


def _verify_contract(manifest_path: Path, workflow_path: Path) -> tuple[dict, dict]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (manifest.get("version") != 2 or manifest.get("backend") != BACKEND
            or manifest.get("status") != "APPROVED" or not manifest.get("owner_approval")
            or manifest.get("runtime_identity_verified") is not True
            or manifest.get("dedicated_single_job_runtime") is not True):
        raise LocalBackgroundError("Runtime/model/workflow approval missing")
    if digest(workflow_path) != _hash(manifest.get("workflow_sha256")):
        raise LocalBackgroundError("Workflow hash mismatch")
    if not manifest.get("runtime_root") or not Path(manifest["runtime_root"]).is_absolute():
        raise LocalBackgroundError("Explicit local runtime root required")
    root = Path(manifest["runtime_root"]).resolve(strict=True)
    artifacts = manifest.get("artifacts", {})
    if set(artifacts) != _ARTIFACTS:
        raise LocalBackgroundError("Exact pinned artifact inventory required")
    for name, entry in artifacts.items():
        if not entry.get("path") or entry.get("license_approved") is not True:
            raise LocalBackgroundError("Missing model identity/license: " + name)
        path = Path(entry["path"]).resolve(strict=True)
        if not path.is_relative_to(root) or not path.is_file() or digest(path) != _hash(entry.get("sha256")):
            raise LocalBackgroundError("MODEL_HASH_MISMATCH" if name in PINNED_MODEL_HASHES else "RUNTIME_INVENTORY_INVALID")
        if name in PINNED_MODEL_HASHES:
            filename, sha = PINNED_MODEL_HASHES[name]
            if path.name != filename or digest(path) != sha:
                raise LocalBackgroundError("MODEL_HASH_MISMATCH")
    inventory = json.loads(Path(artifacts["runtime_lock"]["path"]).read_text(encoding="utf-8-sig"))
    rows = inventory.get("files", [])
    required = {"ComfyUI/main.py", "ComfyUI/server.py", "ComfyUI/cuda_malloc.py", "standalone-env/python.exe"}
    required |= {"ComfyUI/custom_nodes/ComfyUI_IPAdapter_plus/" + name for name in
                 ("__init__.py", "CrossAttentionPatch.py", "image_proj_models.py", "IPAdapterPlus.py", "utils.py", "LICENSE", "pyproject.toml")}
    listed = set()
    for row in rows:
        relative = Path(row["path"])
        if relative.is_absolute() or ".." in relative.parts or ":" in str(relative):
            raise LocalBackgroundError("RUNTIME_INVENTORY_INVALID")
        path = _contained(root / relative, root)
        if path in listed or digest(path) != _hash(row.get("sha256")):
            raise LocalBackgroundError("RUNTIME_INVENTORY_INVALID")
        listed.add(path)
    if not required <= {p.relative_to(root).as_posix() for p in listed}:
        raise LocalBackgroundError("RUNTIME_INVENTORY_INCOMPLETE")
    excluded = {Path(artifacts[n]["path"]).resolve() for n in ("checkpoint", "ip_adapter", "clip_vision", "runtime_lock")}
    actual = set()
    for candidate in root.rglob("*"):
        _check_validation_deadline()
        if candidate.is_file():
            actual.add(candidate.resolve())
    if actual != listed | excluded:
        raise LocalBackgroundError("RUNTIME_INVENTORY_INCOMPLETE")
    state = Path(manifest.get("state_root") or "")
    repository = Path(__file__).resolve().parents[4]
    if (not state.is_absolute() or not state.is_dir() or state.is_symlink() or state.is_junction()
            or state.resolve().is_relative_to(root) or state.resolve().is_relative_to(repository)):
        raise LocalBackgroundError("PRIVATE_STATE_ROOT_REQUIRED")
    roots = manifest.get("reference_roots")
    if not isinstance(roots, list) or not roots or any(not Path(p).is_absolute() or not Path(p).is_dir() for p in roots):
        raise LocalBackgroundError("REFERENCE_ROOT_APPROVAL_REQUIRED")
    workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
    expected = {key: {"class_type": kind, "inputs": inputs} for key, (kind, inputs) in _FROZEN.items()}
    if json.dumps(workflow, sort_keys=True) != json.dumps(expected, sort_keys=True):
        raise LocalBackgroundError("Unapproved workflow node graph")
    latent, sample = workflow["4"]["inputs"], workflow["9"]["inputs"]
    if (latent != {"width": 1024, "height": 1280, "batch_size": 1}
            or sample.get("steps") != 30 or sample.get("denoise") != 1.0):
        raise LocalBackgroundError("Workflow execution bounds changed")
    return manifest, workflow


def verify_contract(manifest_path: Path, workflow_path: Path) -> tuple[dict, dict]:
    # Integrity preflight is separate from the HTTP deadline, but is itself
    # cooperatively bounded; no unbounded model read or inventory traversal.
    token = _VALIDATION_DEADLINE.set(time.monotonic() + 300)
    try:
        return _verify_contract(manifest_path, workflow_path)
    except LocalBackgroundError:
        raise
    except OSError as exc:
        raise LocalBackgroundError("MODEL_MISSING") from exc
    except (ValueError, KeyError, TypeError) as exc:
        raise LocalBackgroundError("RUNTIME_INVENTORY_INVALID") from exc
    finally:
        _VALIDATION_DEADLINE.reset(token)


MAX_OUTPUT_BYTES = 32 * 1024**2
MAX_CONTROL_BYTES = 4 * 1024**2
STREAM_CHUNK_BYTES = 65536


async def _bounded_response(client, method, path, *, deadline, limit=MAX_CONTROL_BYTES, **kwargs):
    """Read raw identity bytes incrementally; response closes on every exit.

    The caller's asyncio timeout is the governing absolute deadline. HTTPX's
    phase timeouts remain secondary and are never treated as a total timer.
    """
    remaining = deadline - asyncio.get_running_loop().time()
    if remaining <= 0:
        raise TimeoutError("Local generation deadline exceeded")
    async with client.stream(method, path, timeout=remaining,
                             headers={"Accept-Encoding": "identity"}, **kwargs) as response:
        if response.status_code != 200:
            raise LocalBackgroundError("Local runtime request failed")
        if response.headers.get("content-encoding", "identity").lower() != "identity":
            raise LocalBackgroundError("Compressed runtime responses prohibited")
        declared = response.headers.get("content-length")
        if declared is not None:
            try:
                count = int(declared)
            except ValueError as exc:
                raise LocalBackgroundError("Invalid response length") from exc
            if count < 0 or count > limit:
                raise LocalBackgroundError("Response byte bounds exceeded")
        body = bytearray()
        async for raw_chunk in response.aiter_raw():
            if len(body) + len(raw_chunk) > limit:
                raise LocalBackgroundError("Response byte bounds exceeded")
            for offset in range(0, len(raw_chunk), STREAM_CHUNK_BYTES):
                if asyncio.get_running_loop().time() >= deadline:
                    raise TimeoutError("Local generation deadline exceeded")
                body.extend(raw_chunk[offset:offset + STREAM_CHUNK_BYTES])
            # Even a fully buffered/mock peer must yield to deadline cancellation.
            await asyncio.sleep(0)
        return httpx.Response(200, content=bytes(body), request=response.request)


def select_background_backend(name: str, **kwargs):
    if name != BACKEND:
        raise LocalBackgroundError("Unknown local backend; no paid fallback")
    return LocalComfyBackgroundProvider(**kwargs)


class LocalComfyBackgroundProvider:
    def __init__(self, *, base_url: str, manifest_path: Path, workflow_path: Path,
                 reference_id: str, reference_sha256: str, seed: int,
                 timeout_seconds: float = 300, transport=None, generation_id=None, context=None,
                 phase_timeouts=None, event_sink=None):
        self.base_url = _url(base_url)
        if not reference_id or type(seed) is not int or not 0 <= seed < 2**32:
            raise LocalBackgroundError("Explicit reference identity and seed required")
        if not 0 < timeout_seconds <= 600:
            raise LocalBackgroundError("Finite bounded timeout required")
        self.manifest, self.workflow = verify_contract(manifest_path, workflow_path)
        self.manifest_path, self.workflow_path = Path(manifest_path), Path(workflow_path)
        self._manifest_hash, self._workflow_hash = digest(self.manifest_path), digest(self.workflow_path)
        self.reference_id, self.reference_sha256 = reference_id, _hash(reference_sha256)
        self.seed, self.timeout_seconds, self.transport = seed, timeout_seconds, transport
        self._attempted = False
        self.provenance = None
        self.generation_id, self.context = generation_id, context or {}
        self._usage_events = []
        self.event_sink = event_sink
        self.phase_timeouts = phase_timeouts or {"health": 5, "upload": 15, "submit": 10, "generation": 240, "output": 20}
        if set(self.phase_timeouts) != {"health", "upload", "submit", "generation", "output"} or any(
                type(v) not in (int, float) or not 0 < v <= 300 for v in self.phase_timeouts.values()):
            raise LocalBackgroundError("TIMEOUT_POLICY_INVALID")

    def drain_usage_events(self):
        events, self._usage_events = self._usage_events, []
        return events

    async def edit(self, **kwargs):
        raise LocalBackgroundError("Local backend is background-only; product editing prohibited")

    async def generate(self, *, prompt, size, model, reference_images=None, quality="high") -> bytes:
        from .image_provider_factory import EndpointAdmission, NAMESPACE, canonical_json, write_json
        if self._attempted:
            raise LocalBackgroundError("One local image attempt; no retry/fallback")
        if model != MODEL or size != "1024x1280" or quality != "high":
            raise LocalBackgroundError("Local model/dimensions/quality mismatch")
        if not isinstance(prompt, str) or not prompt.startswith("BACKGROUND ONLY.") or len(prompt.encode()) > 128000:
            raise LocalBackgroundError("Bounded background-only prompt required")
        if not reference_images or len(reference_images) != 1:
            raise LocalBackgroundError("One owner reference required")
        reference = Path(reference_images[0])
        if (not reference.is_absolute() or any(c in reference.name for c in (":", "\\"))
                or reference.suffix.lower() != ".png"):
            raise LocalBackgroundError("PATH_NOT_APPROVED")
        if not any(reference.resolve().is_relative_to(Path(root).resolve()) for root in self.manifest["reference_roots"]):
            raise LocalBackgroundError("PATH_NOT_APPROVED")
        for root in self.manifest["reference_roots"]:
            if reference.resolve().is_relative_to(Path(root).resolve()):
                _contained(reference, Path(root))
                break
        if reference.stat().st_size > 20 * 1024**2:
            raise LocalBackgroundError("Reference hash/size mismatch")
        reference_bytes = reference.read_bytes()
        if hashlib.sha256(reference_bytes).hexdigest() != self.reference_sha256:
            raise LocalBackgroundError("Reference hash/size mismatch")
        with Image.open(io.BytesIO(reference_bytes)) as image:
            if image.format != "PNG" or image.width > 2048 or image.height > 2048 or getattr(image, "n_frames", 1) != 1:
                raise LocalBackgroundError("Reference pixel bounds exceeded")
            image.load()
        if digest(self.manifest_path) != self._manifest_hash or digest(self.workflow_path) != self._workflow_hash:
            raise LocalBackgroundError("Approved contract changed after selection")
        verify_contract(self.manifest_path, self.workflow_path)
        self._attempted = True
        identity = self.generation_id or str(uuid.uuid5(NAMESPACE, canonical_json({
            "reference": self.reference_id, "sha256": self.reference_sha256, "seed": self.seed,
            "workflow": self._workflow_hash, "prompt": hashlib.sha256(prompt.encode()).hexdigest()})))
        if str(uuid.UUID(identity)) != identity:
            raise LocalBackgroundError("GENERATION_IDENTITY_INVALID")
        job = "mos-bg-" + identity
        workflow = copy.deepcopy(self.workflow)
        for node, field, artifact in [("1", "ckpt_name", "checkpoint"),
                ("6", "clip_name", "clip_vision"), ("7", "ipadapter_file", "ip_adapter")]:
            workflow[node]["inputs"][field] = Path(self.manifest["artifacts"][artifact]["path"]).name
        workflow["2"]["inputs"]["text"] = prompt
        workflow["9"]["inputs"]["seed"] = self.seed
        workflow["5"]["inputs"]["image"] = job + ".png"
        workflow["11"]["inputs"]["filename_prefix"] = job
        request_hash = hashlib.sha256(canonical_json(workflow).encode()).hexdigest()
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.timeout_seconds
        work_deadline = deadline - min(10.0, self.timeout_seconds / 4)
        admission = EndpointAdmission(Path(self.manifest["state_root"]), self.base_url,
                                      wait_seconds=min(5.0, self.timeout_seconds / 4))
        client = None
        intent = None
        submitted = False
        terminal = False
        history = None
        began = time.monotonic()
        error_code = None
        async def request(method, path, *, phase="health", **kwargs):
            cap = min(work_deadline, loop.time() + self.phase_timeouts[phase])
            try:
                async with asyncio.timeout_at(cap):
                    response = await _bounded_response(client, method, path, deadline=cap, **kwargs)
            except LocalBackgroundError as exc:
                if str(exc) == "Local runtime request failed":
                    code = ("WORKFLOW_REJECTED" if path == "/prompt" else
                            "STARTUP_FAILED" if path == "/system_stats" else
                            "OUTPUT_MISSING" if path == "/view" else "RUNTIME_UNAVAILABLE")
                    raise LocalBackgroundError(code) from exc
                raise LocalBackgroundError("MALFORMED_RESPONSE") from exc
            return response
        def parsed(response):
            try:
                value = response.json()
            except (ValueError, UnicodeError) as exc:
                raise LocalBackgroundError("MALFORMED_RESPONSE") from exc
            if not isinstance(value, dict):
                raise LocalBackgroundError("MALFORMED_RESPONSE")
            return value
        async def work():
            nonlocal submitted, terminal, history
            stats = parsed(await request("GET", "/system_stats"))
            system = stats.get("system", {})
            devices = stats.get("devices", [])
            if system.get("comfyui_version") != "0.42.1" or system.get("pytorch_version") != "2.12.1+cu130":
                raise LocalBackgroundError("STARTUP_FAILED")
            argv = system.get("argv")
            if (not str(system.get("python_version", "")).startswith("3.13.12 ")
                    or not isinstance(argv, list) or not argv or not isinstance(argv[0], str)
                    or Path(argv[0]).resolve() != Path(self.manifest["runtime_root"]).resolve() / "ComfyUI/main.py"):
                raise LocalBackgroundError("STARTUP_FAILED")
            if not any(d.get("type") == "cuda" and "RTX 3060" in d.get("name", "")
                       and "cudaMallocAsync" in d.get("name", "") for d in devices):
                raise LocalBackgroundError("CUDA_UNAVAILABLE")
            info = parsed(await request("GET", "/object_info"))
            if not _CLASSES.issubset(info):
                raise LocalBackgroundError("CUSTOM_NODE_MISSING")
            for category, artifact in [("checkpoints", "checkpoint"), ("ipadapter", "ip_adapter"), ("clip_vision", "clip_vision")]:
                response = await request("GET", "/models/" + category)
                names = response.json()
                if not isinstance(names, list) or Path(self.manifest["artifacts"][artifact]["path"]).name not in names:
                    raise LocalBackgroundError("MODEL_MISSING")
            queue = parsed(await request("GET", "/queue"))
            if not all(isinstance(queue.get(k), list) for k in ("queue_running", "queue_pending")):
                raise LocalBackgroundError("MALFORMED_RESPONSE")
            if queue["queue_running"] or queue["queue_pending"]:
                raise LocalBackgroundError("BUSY")
            upload = parsed(await request("POST", "/upload/image", phase="upload", files={
                "image": (job + ".png", reference_bytes, "image/png")}, data={"type": "input", "overwrite": "false"}))
            if upload.get("name") != job + ".png" or upload.get("subfolder", "") != "" or upload.get("type") != "input":
                raise LocalBackgroundError("REFERENCE_UPLOAD_IDENTITY_MISMATCH")
            submitted = True  # A lost acknowledgement must never cause another POST.
            try:
                response = parsed(await request("POST", "/prompt", phase="submit",
                    json={"prompt": workflow, "client_id": job, "prompt_id": identity}))
            except LocalBackgroundError as exc:
                raise LocalBackgroundError("WORKFLOW_REJECTED") from exc
            if response.get("prompt_id") != identity or response.get("node_errors"):
                raise LocalBackgroundError("MALFORMED_RESPONSE")
            generation_deadline = min(work_deadline, loop.time() + self.phase_timeouts["generation"])
            while True:
                async with asyncio.timeout_at(generation_deadline):
                    records = parsed(await request("GET", "/history/" + identity))
                if identity in records:
                    history = records[identity]
                    if not isinstance(history, dict):
                        raise LocalBackgroundError("MALFORMED_RESPONSE")
                    actual_prompt = history.get("prompt")
                    if (not isinstance(actual_prompt, list) or len(actual_prompt) < 4
                            or actual_prompt[1] != identity or actual_prompt[2] != workflow
                            or actual_prompt[3].get("client_id") != job):
                        raise LocalBackgroundError("OUTPUT_CORRELATION_MISMATCH")
                    status = history.get("status", {})
                    terminal = status.get("completed") is True or status.get("status_str") == "error"
                    if status.get("status_str") != "success" or status.get("completed") is not True:
                        messages = canonical_json(status).lower()
                        raise LocalBackgroundError("CUDA_OOM" if "out of memory" in messages else "EXECUTION_FAILED")
                    outputs = history.get("outputs", {}).get("11", {}).get("images", [])
                    if not isinstance(outputs, list) or len(outputs) != 1:
                        raise LocalBackgroundError("OUTPUT_MISSING")
                    output = outputs[0]
                    filename = output.get("filename", "")
                    if (not isinstance(filename, str) or not re.fullmatch(re.escape(job) + r"_[0-9]+_\.png", filename)
                            or output.get("subfolder", "") != "" or output.get("type") != "output"):
                        raise LocalBackgroundError("OUTPUT_CORRELATION_MISMATCH")
                    raw = (await request("GET", "/view", phase="output", params={"filename": filename,
                        "subfolder": "", "type": "output"}, limit=MAX_OUTPUT_BYTES)).content
                    try:
                        with Image.open(io.BytesIO(raw)) as image:
                            if image.format != "PNG" or image.size != (1024, 1280) or getattr(image, "n_frames", 1) != 1:
                                raise ValueError("Invalid output dimensions")
                            image.load()
                    except (OSError, ValueError) as exc:
                        raise LocalBackgroundError("OUTPUT_CORRUPT") from exc
                    self.provenance = {"kind": "LOCAL_GENERATED_BACKGROUND", "role": "BACKGROUND_ONLY",
                        "backend": BACKEND, "model": MODEL, "seed": self.seed, "context": self.context,
                        "workflow_sha256": self._workflow_hash, "executed_workflow_sha256": request_hash,
                        "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
                        "negative_prompt_sha256": hashlib.sha256(workflow["3"]["inputs"]["text"].encode()).hexdigest(),
                        "job_id": job, "generation_id": identity, "runtime_prompt_id": identity,
                        "history": history, "submitted_workflow": workflow, "runtime_stats_before": stats,
                        "native_dimensions": [1024, 1280], "manifest_sha256": self._manifest_hash,
                        "reference_id": self.reference_id, "reference_sha256": self.reference_sha256,
                        "output_filename": filename, "output_sha256": hashlib.sha256(raw).hexdigest(),
                        "artifact_sha256": {k: v["sha256"] for k, v in self.manifest["artifacts"].items()},
                        "duration_ms": int((time.monotonic() - began) * 1000), "claim_evidence": False,
                        "product_provenance": False, "provider_cost_usd": 0.0, "cost_known": True,
                        "semantic_qa": "NOT_RUN", "campaign_approval": False,
                        "optional_gpu_metrics": "UNAVAILABLE", "native_log_capture": "EXTERNAL_SUPERVISOR"}
                    root = Path(self.manifest["state_root"])
                    output_path = root / (identity + ".background.png")
                    with output_path.open("xb") as stream:
                        stream.write(raw)
                    self.provenance["background_path"] = str(output_path)
                    write_json(root / (identity + ".evidence.json"), self.provenance)
                    self._usage_events.append({"provider": "local_comfyui", "model": MODEL, "image_count": 1,
                        "estimated_cost_usd": 0.0, "actual_provider_cost_usd": 0.0, "cost_known": True,
                        "duration_ms": self.provenance["duration_ms"]})
                    return raw
                if loop.time() >= generation_deadline:
                    raise TimeoutError("Local generation deadline exceeded")
                await asyncio.sleep(min(0.25, max(0, generation_deadline - loop.time())))
        try:
            async with asyncio.timeout_at(deadline):
                intent = await admission.acquire(identity, request_hash)
                if self.event_sink:
                    self.event_sink({"generation_id": identity, "status": "reserved", "workflow_sha256": self._workflow_hash,
                                     "reference_sha256": self.reference_sha256})
                client = httpx.AsyncClient(base_url=self.base_url, transport=self.transport,
                    timeout=self.timeout_seconds, follow_redirects=False, trust_env=False)
                async with asyncio.timeout_at(work_deadline):
                    return await work()
        except BaseException as failure:
            error_code = ("CANCELLED" if isinstance(failure, asyncio.CancelledError) else
                          "TIMEOUT" if isinstance(failure, (TimeoutError, httpx.TimeoutException)) else
                          ("PROCESS_CRASH" if submitted else "RUNTIME_UNAVAILABLE") if isinstance(failure, httpx.RequestError) else
                          failure.code if isinstance(failure, LocalBackgroundError) else "MALFORMED_RESPONSE")
            if submitted and not terminal and client is not None:
                try:
                    async with asyncio.timeout_at(deadline):
                        await _bounded_response(client, "POST", "/api/jobs/" + identity + "/cancel", deadline=deadline)
                        check = await _bounded_response(client, "GET", "/history/" + identity, deadline=deadline)
                        record = parsed(check).get(identity, {})
                        state = record.get("status", {})
                        proof = record.get("prompt")
                        owned = (isinstance(proof, list) and len(proof) >= 4 and proof[1] == identity
                                 and proof[2] == workflow and proof[3].get("client_id") == job)
                        terminal = owned and (state.get("completed") is True or state.get("status_str") == "error")
                except BaseException as cleanup_error:
                    failure.add_note("Local interrupt cleanup unconfirmed: " + type(cleanup_error).__name__)
            if isinstance(failure, asyncio.CancelledError):
                raise
            raise LocalBackgroundError(error_code) from failure
        finally:
            failure = sys.exc_info()[1]
            try:
                if client is not None:
                    try:
                        async with asyncio.timeout_at(deadline):
                            await client.aclose()
                    except BaseException as cleanup_error:
                        if failure is None:
                            error_code = "CLIENT_CLEANUP_UNCONFIRMED"
                            raise LocalBackgroundError("CLIENT_CLEANUP_UNCONFIRMED") from cleanup_error
                        failure.add_note("Local client cleanup unconfirmed: " + type(cleanup_error).__name__)
            finally:
                try:
                    if intent is not None:
                        admission.finish(intent, {"generation_id": identity, "request_sha256": request_hash,
                            "status": "completed" if self.provenance and error_code is None else error_code or "failed",
                            "submitted": submitted, "terminal_confirmed": terminal or not submitted,
                            "output_sha256": (self.provenance or {}).get("output_sha256"),
                            "provider_cost_usd": 0.0, "error_code": error_code,
                            "duration_ms": int((time.monotonic() - began) * 1000), "context": self.context,
                            "workflow_sha256": self._workflow_hash, "reference_sha256": self.reference_sha256},
                            terminal=terminal or not submitted)
                        if self.event_sink:
                            self.event_sink({**(self.provenance or {}), "generation_id": identity,
                                "provider_cost_usd": 0.0, "status": error_code or "completed",
                                "terminal_confirmed": terminal or not submitted})
                finally:
                    admission.release()
