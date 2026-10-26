"""Inactive routing and durable, single-job admission for the local HTTP adapter.

No runtime launcher, accelerator import, environment override, or paid fallback.
Host approval and routing activation are separate operator actions.
"""
from __future__ import annotations

import asyncio
import ctypes
import hashlib
import json
import os
import threading
import uuid
from pathlib import Path

from .local_background_provider import BACKEND, MODEL, LocalBackgroundError

ROUTING_PATH = Path(__file__).resolve().parents[3] / "config/image_backends/background_routing.json"
NAMESPACE = uuid.UUID("71287ce2-9b62-54dc-9b12-958af4048bc1")
_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def canonical_json(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def generation_id(context: dict) -> str:
    required = {"job_id", "job_attempt", "campaign_id", "platform", "language", "slide_number",
                "slide_contract_sha256", "reference_id", "reference_sha256", "workflow_sha256", "seed"}
    if set(context) != required or any(context[k] in (None, "") for k in required):
        raise LocalBackgroundError("GENERATION_IDENTITY_INVALID")
    for key in ("job_id", "campaign_id", "platform", "language", "reference_id"):
        if not isinstance(context[key], str) or not context[key].strip() or len(context[key]) > 200:
            raise LocalBackgroundError("GENERATION_IDENTITY_INVALID")
    for k in ("job_attempt", "slide_number"):
        if type(context[k]) is not int or context[k] < 1:
            raise LocalBackgroundError("GENERATION_IDENTITY_INVALID")
    if type(context["seed"]) is not int or not 0 <= context["seed"] < 2**32:
        raise LocalBackgroundError("GENERATION_IDENTITY_INVALID")
    for k in ("slide_contract_sha256", "reference_sha256", "workflow_sha256"):
        value = context[k]
        if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdefABCDEF" for c in value):
            raise LocalBackgroundError("GENERATION_IDENTITY_INVALID")
    return str(uuid.uuid5(NAMESPACE, canonical_json(context)))


def write_json(path: Path, data: dict) -> None:
    """Atomic replacement only within an operator-approved private state root."""
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            stream.write(canonical_json(data))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class EndpointAdmission:
    """One endpoint-wide OS mutex plus durable intent and ambiguous-work fence.

    Mutex acquisition/release stays on the same event-loop thread. A process
    lock also prevents Windows mutex recursion from admitting a second task.
    """

    def __init__(self, root: Path, endpoint: str, *, wait_seconds: float = 5):
        self.root, self.endpoint = Path(root), endpoint
        self.wait_seconds = wait_seconds
        self.name = hashlib.sha256(endpoint.encode()).hexdigest()
        self.fence = self.root / (self.name + ".inflight.json")
        self.handle = None
        self.kernel = None
        self.file = None
        self.locked = False
        with _locks_guard:
            self.process_lock = _locks.setdefault(self.name, threading.Lock())

    def _try_os_lock(self) -> bool:
        if os.name == "nt":
            if self.handle is None:
                self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
                self.kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
                self.kernel.CreateMutexW.restype = ctypes.c_void_p
                self.kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
                self.kernel.ReleaseMutex.argtypes = [ctypes.c_void_p]
                self.kernel.CloseHandle.argtypes = [ctypes.c_void_p]
                self.handle = self.kernel.CreateMutexW(None, False, "Global\\MarketingOS-ComfyUI-" + self.name)
                if not self.handle:
                    raise LocalBackgroundError("ADMISSION_UNAVAILABLE")
            status = self.kernel.WaitForSingleObject(self.handle, 0)
            if status not in (0, 128, 258):
                raise LocalBackgroundError("ADMISSION_UNAVAILABLE")
            return status in (0, 128)
        import fcntl
        self.file = (self.root / (self.name + ".lock")).open("a+b")
        try:
            fcntl.flock(self.file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except BlockingIOError:
            self.file.close()
            self.file = None
            return False

    async def acquire(self, ident: str, request_digest: str) -> Path:
        if str(uuid.UUID(ident)) != ident:
            raise LocalBackgroundError("GENERATION_IDENTITY_INVALID")
        deadline = asyncio.get_running_loop().time() + self.wait_seconds
        try:
            while True:
                if self.process_lock.acquire(False):
                    try:
                        if self._try_os_lock():
                            self.locked = True
                            break
                    except BaseException:
                        self.process_lock.release()
                        raise
                    self.process_lock.release()
                if asyncio.get_running_loop().time() >= deadline:
                    raise LocalBackgroundError("BUSY")
                await asyncio.sleep(min(0.02, max(0, deadline - asyncio.get_running_loop().time())))
            if self.fence.exists():
                raise LocalBackgroundError("TERMINAL_STATE_UNCONFIRMED")
            intent = self.root / (ident + ".intent.json")
            try:
                with intent.open("x", encoding="utf-8") as stream:
                    json.dump({"generation_id": ident, "request_sha256": request_digest, "status": "reserved"}, stream)
                    stream.flush()
                    os.fsync(stream.fileno())
            except FileExistsError as exc:
                raise LocalBackgroundError("DUPLICATE_GENERATION_ATTEMPT") from exc
            write_json(self.fence, {"generation_id": ident, "request_sha256": request_digest})
            return intent
        except BaseException:
            self.release()
            raise

    def finish(self, intent: Path, evidence: dict, *, terminal: bool) -> None:
        write_json(intent, evidence)
        if terminal:
            self.fence.unlink(missing_ok=True)

    def release(self) -> None:
        if self.locked:
            if self.kernel:
                self.kernel.ReleaseMutex(self.handle)
            elif self.file:
                import fcntl
                fcntl.flock(self.file, fcntl.LOCK_UN)
            self.process_lock.release()
            self.locked = False
        if self.file:
            self.file.close()
            self.file = None
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


def read_routing(path: Path | None = None) -> dict:
    try:
        routing = json.loads((path or ROUTING_PATH).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise LocalBackgroundError("ROUTING_INVALID") from exc
    if not isinstance(routing, dict) or routing.get("version") != 1 or type(routing.get("enabled")) is not bool:
        raise LocalBackgroundError("ROUTING_INVALID")
    if routing.get("backend") != BACKEND or routing.get("base_url") != "http://127.0.0.1:8189":
        raise LocalBackgroundError("ROUTING_INVALID")
    return routing


def local_routing_enabled() -> bool:
    return read_routing()["enabled"]


def reject_unsupported_local(reason: str) -> None:
    if local_routing_enabled():
        raise LocalBackgroundError("LOCAL_MODE_UNSUPPORTED: " + reason)


class LocalProviderSession:
    """A finite set of prepared slide identities, each with a one-shot adapter."""

    is_local_background = True

    def __init__(self, *, job_id, campaign_id, job_attempt=1, seed=0, event_sink=None, **adapter_options):
        if not job_id or not campaign_id:
            raise LocalBackgroundError("GENERATION_IDENTITY_INVALID")
        self.job_id, self.campaign_id, self.job_attempt = job_id, campaign_id, job_attempt
        self.seed, self.options = seed, adapter_options
        self.children = {}
        self.provenance = None
        self.event_sink = event_sink
        self.allowed = None
        self.used = set()

    def prepare(self, *, plans, platforms, languages):
        if self.allowed is not None:
            raise LocalBackgroundError("PREPARED_SCOPE_ALREADY_BOUND")
        self.allowed = {(p.slide_number, platform, language) for p in plans for platform in platforms for language in languages}
        if not self.allowed:
            raise LocalBackgroundError("PREPARED_SLIDE_CONTEXT_REQUIRED")

    def for_slide(self, *, plan, platform, language):
        from ...schemas.creative_director import reference_target_from_brief
        from ..creative.pipeline import slide_contract_digest
        from .local_background_provider import LocalComfyBackgroundProvider, digest
        target = reference_target_from_brief(plan.visual_brief)
        if target is None:
            raise LocalBackgroundError("TRUSTED_REFERENCE_REQUIRED")
        key = (plan.slide_number, platform, language)
        if self.allowed is None or key not in self.allowed or key in self.used:
            raise LocalBackgroundError("UNPREPARED_OR_DUPLICATE_SLIDE")
        context = dict(job_id=self.job_id, job_attempt=self.job_attempt, campaign_id=self.campaign_id,
                       platform=platform, language=language, slide_number=plan.slide_number,
                       slide_contract_sha256=slide_contract_digest(plan), reference_id=target.reference_id,
                       reference_sha256=target.sha256, workflow_sha256=digest(self.options["workflow_path"]), seed=self.seed)
        ident = generation_id(context)
        if ident in self.children:
            raise LocalBackgroundError("DUPLICATE_GENERATION_ATTEMPT")
        child = LocalComfyBackgroundProvider(**self.options, reference_id=target.reference_id,
            reference_sha256=target.sha256, seed=self.seed, generation_id=ident, context=context,
            event_sink=self.event_sink)
        self.used.add(key)
        self.children[ident] = child
        return child

    async def generate(self, **kwargs):
        raise LocalBackgroundError("PREPARED_SLIDE_CONTEXT_REQUIRED")

    async def edit(self, **kwargs):
        raise LocalBackgroundError("Local backend is background-only; product editing prohibited")

    def drain_usage_events(self):
        return [event for child in self.children.values() for event in child.drain_usage_events()]


def resolve_image_provider(effective, *, legacy_factory, config, job_id, campaign_id, job_attempt=1):
    routing = read_routing()
    if not routing["enabled"]:
        return legacy_factory(effective)
    if (not config.use_ai_background or config.recreate_with_ai or config.use_masked_scene_edit
            or config.quality_mode == "draft" or config.enable_qa_stage
            or config.qa_max_retries != 0 or config.qa_best_of_n != 1):
        raise LocalBackgroundError("LOCAL_MODE_UNSUPPORTED")
    manifest = routing.get("manifest_path")
    if not manifest or not Path(manifest).is_absolute():
        raise LocalBackgroundError("Runtime/model/workflow approval missing")
    from .local_background_provider import verify_contract
    workflow = ROUTING_PATH.with_name("comfy_sdxl_background.workflow.json")
    verify_contract(Path(manifest), workflow)
    for name in ("image_model", "premium_image_model", "revision_model"):
        setattr(config, name, MODEL)
    config.require_ai_background_success = True
    from ..jobs import JobContext
    return LocalProviderSession(job_id=job_id, campaign_id=campaign_id, job_attempt=job_attempt,
        seed=routing.get("seed", 0), base_url=routing["base_url"], manifest_path=Path(manifest),
        workflow_path=workflow, timeout_seconds=300, event_sink=JobContext(job_id).record_local_generation)
