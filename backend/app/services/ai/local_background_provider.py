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


class LocalBackgroundError(ValueError):
    """Local configuration/request/output failed; no fallback is authorized."""


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _hash(value) -> str:
    if not isinstance(value, str) or not _HASH.fullmatch(value) or len(set(value)) == 1:
        raise LocalBackgroundError("Missing or unverified SHA256")
    return value.lower()


def _url(value: str) -> str:
    parsed = urlsplit(value)
    if (parsed.scheme != "http" or parsed.hostname != "127.0.0.1"
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path not in ("", "/") or parsed.port is None):
        raise LocalBackgroundError("Explicit IPv4 loopback HTTP runtime URL required")
    return value.rstrip("/")


def verify_contract(manifest_path: Path, workflow_path: Path) -> tuple[dict, dict]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (manifest.get("version") != 1 or manifest.get("backend") != BACKEND
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
            raise LocalBackgroundError("Artifact hash/path mismatch: " + name)
    workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
    # An approved hash is necessary, never sufficient to authorize arbitrary nodes.
    if (set(workflow) != {str(i) for i in range(1, 12)}
            or any(node.get("class_type") not in _CLASSES for node in workflow.values())
            or workflow["11"]["class_type"] != "SaveImage"):
        raise LocalBackgroundError("Unapproved workflow node graph")
    latent, sample = workflow["4"]["inputs"], workflow["9"]["inputs"]
    if (latent != {"width": 1024, "height": 1280, "batch_size": 1}
            or sample.get("steps") != 30 or sample.get("denoise") != 1.0):
        raise LocalBackgroundError("Workflow execution bounds changed")
    return manifest, workflow


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
                 timeout_seconds: float = 180, transport=None):
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

    async def edit(self, **kwargs):
        raise LocalBackgroundError("Local backend is background-only; product editing prohibited")

    async def generate(self, *, prompt, size, model, reference_images=None, quality="high") -> bytes:
        if self._attempted:
            raise LocalBackgroundError("One local image attempt; no retry/fallback")
        if model != MODEL or size != "1024x1280" or quality != "high":
            raise LocalBackgroundError("Local model/dimensions/quality mismatch")
        if (not isinstance(prompt, str) or not prompt.startswith("BACKGROUND ONLY.")
                or len(prompt.encode("utf-8")) > 128000):
            raise LocalBackgroundError("Bounded background-only prompt required")
        if not reference_images or len(reference_images) != 1:
            raise LocalBackgroundError("One owner reference required")
        reference = Path(reference_images[0])
        if digest(reference) != self.reference_sha256 or reference.stat().st_size > 20 * 1024**2:
            raise LocalBackgroundError("Reference hash/size mismatch")
        with Image.open(reference) as image:
            if image.width > 2048 or image.height > 2048 or getattr(image, "n_frames", 1) != 1:
                raise LocalBackgroundError("Reference pixel bounds exceeded")
        if (digest(self.manifest_path) != self._manifest_hash
                or digest(self.workflow_path) != self._workflow_hash):
            raise LocalBackgroundError("Approved contract changed after selection")
        verify_contract(self.manifest_path, self.workflow_path)  # recheck at invocation
        self._attempted = True
        job = "mos-bg-" + uuid.uuid4().hex
        workflow = copy.deepcopy(self.workflow)
        for node, field, artifact in [("1", "ckpt_name", "checkpoint"),
                ("6", "clip_name", "clip_vision"), ("7", "ipadapter_file", "ip_adapter")]:
            workflow[node]["inputs"][field] = Path(self.manifest["artifacts"][artifact]["path"]).name
        workflow["2"]["inputs"]["text"] = prompt
        workflow["9"]["inputs"]["seed"] = self.seed
        workflow["11"]["inputs"]["filename_prefix"] = job
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.timeout_seconds
        work_deadline = deadline - min(5.0, self.timeout_seconds / 4)
        submitted = False
        client = httpx.AsyncClient(base_url=self.base_url, transport=self.transport,
            timeout=self.timeout_seconds, follow_redirects=False, trust_env=False)
        async def request(method, path, **kwargs):
            return await _bounded_response(client, method, path, deadline=work_deadline, **kwargs)

        async def work():
            nonlocal submitted
            info = (await request("GET", "/object_info")).json()
            if not isinstance(info, dict) or not _CLASSES.issubset(info):
                raise LocalBackgroundError("Pinned node runtime unavailable")
            upload = (await request("POST", "/upload/image", files={
                "image": (job + ".png", reference.read_bytes(), "image/png")},
                data={"type": "input", "overwrite": "false"})).json()
            if upload.get("name") != job + ".png" or upload.get("subfolder", "") != "":
                raise LocalBackgroundError("Unexpected reference upload identity")
            workflow["5"]["inputs"]["image"] = upload["name"]
            submitted = True  # timeout after send may still enqueue a job
            result = (await request("POST", "/prompt", json={"prompt": workflow, "client_id": job})).json()
            prompt_id = result.get("prompt_id")
            if (not isinstance(prompt_id, str) or not re.fullmatch(r"[a-zA-Z0-9-]{1,128}", prompt_id)
                    or result.get("node_errors")):
                raise LocalBackgroundError("Malformed ComfyUI submission")
            while True:
                history = (await request("GET", "/history/" + prompt_id)).json()
                if not isinstance(history, dict):
                    raise LocalBackgroundError("Malformed ComfyUI history")
                if prompt_id in history:
                    record = history[prompt_id]
                    status = record.get("status", {})
                    if status.get("status_str") != "success" or status.get("completed") is not True:
                        raise LocalBackgroundError("Local workflow failed or incomplete")
                    outputs = record.get("outputs", {}).get("11", {}).get("images", [])
                    if len(outputs) != 1:
                        raise LocalBackgroundError("Exactly one generated background required")
                    output = outputs[0]
                    filename, folder = output.get("filename", ""), output.get("subfolder", "")
                    if (not filename.startswith(job) or Path(filename).name != filename
                            or "\\" in filename or "/" in filename or folder
                            or output.get("type") != "output"):
                        raise LocalBackgroundError("Untrusted output identity/path")
                    raw = (await request("GET", "/view", params={"filename": filename,
                        "subfolder": "", "type": "output"}, limit=MAX_OUTPUT_BYTES)).content
                    with Image.open(io.BytesIO(raw)) as image:
                        if image.format != "PNG" or image.size != (1024, 1280) or getattr(image, "n_frames", 1) != 1:
                            raise LocalBackgroundError("Invalid background PNG/dimensions")
                        image.verify()
                    self.provenance = {"kind": "LOCAL_GENERATED_BACKGROUND", "role": "BACKGROUND_ONLY",
                        "backend": BACKEND, "model": MODEL, "seed": self.seed,
                        "workflow_sha256": digest(self.workflow_path),
                        "executed_workflow_sha256": hashlib.sha256(json.dumps(workflow, sort_keys=True).encode()).hexdigest(),
                        "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
                        "job_id": job, "runtime_prompt_id": prompt_id, "native_dimensions": [1024, 1280],
                        "manifest_sha256": digest(self.manifest_path), "reference_id": self.reference_id,
                        "reference_sha256": self.reference_sha256, "output_sha256": hashlib.sha256(raw).hexdigest(),
                        "artifact_sha256": {k: v["sha256"] for k, v in self.manifest["artifacts"].items()},
                        "claim_evidence": False, "product_provenance": False,
                        "provider_cost_usd": 0, "semantic_qa": "NOT_RUN", "campaign_approval": False}
                    return raw
                await asyncio.sleep(min(0.25, max(0, work_deadline - loop.time())))

        try:
            async with asyncio.timeout_at(deadline):
                try:
                    async with asyncio.timeout_at(work_deadline):
                        return await work()
                except BaseException as failure:
                    if submitted:
                        try:
                            async with asyncio.timeout_at(deadline):
                                await _bounded_response(client, "POST", "/interrupt", deadline=deadline)
                        except BaseException as cleanup_error:
                            failure.add_note("Local interrupt cleanup unconfirmed: " + type(cleanup_error).__name__)
                    raise
        finally:
            # Also bounded if an outer deadline has already expired. Never give
            # cleanup a fresh timeout or leave a shielded background cleanup task.
            failure = sys.exc_info()[1]
            try:
                async with asyncio.timeout_at(deadline):
                    await client.aclose()
            except BaseException as cleanup_error:
                if failure is None:
                    raise  # cleanup failure cannot turn into a successful generation
                failure.add_note("Local client cleanup unconfirmed: " + type(cleanup_error).__name__)

