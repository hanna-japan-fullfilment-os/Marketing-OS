"""Synthetic files and HTTP mocks only: no model/runtime/provider execution."""
import copy
import io
import json
import re
from pathlib import Path

import httpx
import pytest
from PIL import Image

from app.services.ai import local_background_provider as local


@pytest.fixture
def approved_contract(tmp_path, monkeypatch):
    workflow = tmp_path / "workflow.json"
    workflow.write_bytes((Path(__file__).parents[1] / "config/image_backends/comfy_sdxl_background.workflow.json").read_bytes())
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    monkeypatch.setitem(globals(), "_mock_runtime_root", runtime)
    files = ["ComfyUI/main.py", "ComfyUI/server.py", "ComfyUI/cuda_malloc.py", "standalone-env/python.exe"]
    files += ["ComfyUI/custom_nodes/ComfyUI_IPAdapter_plus/" + n for n in
              ("__init__.py", "CrossAttentionPatch.py", "image_proj_models.py", "IPAdapterPlus.py", "utils.py", "LICENSE", "pyproject.toml")]
    for name in files:
        target = runtime / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(("SYNTHETIC CODE NOT EXECUTABLE " + name).encode())
    artifacts = {}
    pins = {}
    for name, (filename, _) in local.PINNED_MODEL_HASHES.items():
        artifact = runtime / filename
        artifact.write_bytes(("SYNTHETIC NOT MODEL BYTES " + name).encode())
        sha = local.digest(artifact)
        artifacts[name] = {"path": str(artifact), "sha256": sha, "license_approved": True}
        pins[name] = (filename, sha)
    # Synthetic content hashes are test doubles, never a production approval.
    monkeypatch.setattr(local, "PINNED_MODEL_HASHES", pins)
    node = runtime / "ComfyUI/custom_nodes/ComfyUI_IPAdapter_plus/IPAdapterPlus.py"
    artifacts["custom_node_code"] = {"path": str(node), "sha256": local.digest(node), "license_approved": True}
    inventory = runtime / "runtime-lock.json"
    inventory.write_text(json.dumps({"files": [{"path": name, "sha256": local.digest(runtime / name)} for name in files]}))
    artifacts["runtime_lock"] = {"path": str(inventory), "sha256": local.digest(inventory), "license_approved": True}
    state = tmp_path / "private-state"
    state.mkdir()
    manifest = tmp_path / "manifest.json"
    data = {"version": 2, "backend": local.BACKEND, "status": "APPROVED",
        "owner_approval": "SYNTHETIC TEST ONLY", "runtime_root": str(runtime),
        "runtime_identity_verified": True, "dedicated_single_job_runtime": True,
        "workflow_sha256": local.digest(workflow), "artifacts": artifacts,
        "state_root": str(state), "reference_roots": [str(tmp_path)]}
    manifest.write_text(json.dumps(data))
    reference = tmp_path / "reference.png"
    Image.new("RGB", (4, 5), "purple").save(reference)
    return {"base_url": "http://127.0.0.1:8189", "manifest_path": manifest,
        "workflow_path": workflow, "reference_id": "owner-target", "reference_sha256": local.digest(reference),
        "seed": 17}, reference


def provider(contract, transport=None):
    kwargs, _ = contract
    return local.select_background_backend(local.BACKEND, **kwargs, transport=transport)


def change_manifest(contract, change):
    path = contract[0]["manifest_path"]
    data = json.loads(path.read_text())
    change(data)
    path.write_text(json.dumps(data))


@pytest.mark.parametrize("url", ["https://127.0.0.1:8188", "http://example.com:8188",
    "http://localhost:8188", "http://127.0.0.1:8188/path", "http://u:p@127.0.0.1:8188",
    "http://127.0.0.1:8188?url=external", "http://127.0.0.1", ""])
def test_remote_or_implicit_runtime_rejected(approved_contract, url):
    approved_contract[0]["base_url"] = url
    with pytest.raises(ValueError):
        provider(approved_contract)


def test_explicit_selection_and_unknown_backend(approved_contract):
    assert isinstance(provider(approved_contract), local.LocalComfyBackgroundProvider)
    with pytest.raises(local.LocalBackgroundError, match="no paid fallback"):
        local.select_background_backend("sunburst", **approved_contract[0])


@pytest.mark.parametrize("change", [
    lambda m: m.update(status="UNAPPROVED"), lambda m: m.update(owner_approval=None),
    lambda m: m.update(workflow_sha256=None), lambda m: m.update(runtime_identity_verified=False),
    lambda m: m.update(dedicated_single_job_runtime=False), lambda m: m.update(artifacts={}),
    lambda m: m["artifacts"]["checkpoint"].update(sha256=None),
    lambda m: m["artifacts"]["checkpoint"].update(sha256="ab" * 32),
    lambda m: m["artifacts"]["checkpoint"].update(license_approved=False),
])
def test_missing_unverified_model_runtime_workflow_rejected(approved_contract, change):
    change_manifest(approved_contract, change)
    with pytest.raises(local.LocalBackgroundError):
        provider(approved_contract)


def test_bundled_manifest_cannot_activate():
    root = Path(__file__).parents[1] / "config/image_backends"
    with pytest.raises(local.LocalBackgroundError, match="approval missing"):
        local.verify_contract(root / "comfy_sdxl_background.manifest.json", root / "comfy_sdxl_background.workflow.json")


@pytest.mark.parametrize("change", [lambda w: w["1"].update(class_type="PaidCloudAPI"),
    lambda w: w["4"]["inputs"].update(batch_size=2),
    lambda w: w["9"]["inputs"].update(steps=300), lambda w: w.update({"12": w["1"]})])
def test_even_hash_approved_arbitrary_workflow_rejected(approved_contract, change):
    path = approved_contract[0]["workflow_path"]
    data = json.loads(path.read_text()); change(data); path.write_text(json.dumps(data))
    change_manifest(approved_contract, lambda m: m.update(workflow_sha256=local.digest(path)))
    with pytest.raises(local.LocalBackgroundError):
        provider(approved_contract)


def runtime_mock(mode="success"):
    calls, state = [], {}
    def handler(request):
        calls.append((request.method, request.url.path))
        assert request.url.host == "127.0.0.1"
        if request.url.path == "/system_stats":
            return httpx.Response(200, json={"system": {"comfyui_version": "0.42.1", "pytorch_version": "2.12.1+cu130",
                "python_version": "3.13.12 (synthetic)", "argv": [str(_mock_runtime_root / "ComfyUI/main.py")]},
                "devices": [{"type": "cuda", "name": "cuda:0 NVIDIA GeForce RTX 3060 : cudaMallocAsync"}]})
        if request.url.path == "/object_info":
            if mode == "timeout": raise httpx.ReadTimeout("mock timeout")
            if mode == "redirect": return httpx.Response(302, headers={"location": "https://paid.example"})
            return httpx.Response(200, json={key: {} for key in local._CLASSES})
        if request.url.path.startswith("/models/"):
            return httpx.Response(200, json=[v[0] for v in local.PINNED_MODEL_HASHES.values()])
        if request.url.path == "/queue":
            return httpx.Response(200, json={"queue_running": [], "queue_pending": []})
        if request.url.path == "/upload/image":
            state["name"] = re.search(rb'filename="(mos-bg-[a-f0-9-]+\.png)"', request.content).group(1).decode()
            return httpx.Response(200, json={"name": state["name"], "subfolder": "", "type": "input"})
        if request.url.path == "/prompt":
            payload = json.loads(request.content)
            assert payload["prompt"]["3"]["inputs"]["text"].startswith("product, package")
            assert payload["prompt"]["4"]["inputs"] == {"width": 1024, "height": 1280, "batch_size": 1}
            state.update(payload)
            state["prefix"] = payload["prompt"]["11"]["inputs"]["filename_prefix"]
            return httpx.Response(200, json={} if mode == "bad_submit" else {"prompt_id": payload["prompt_id"], "node_errors": {}})
        if request.url.path.startswith("/history/"):
            ident = state["prompt_id"]
            if mode == "pending" and not state.get("cancelled"):
                return httpx.Response(200, json={})
            images = [] if mode == "missing" else [{"filename": state["prefix"] + "_00001_.png", "subfolder": "", "type": "output"}]
            if mode == "traversal": images[0]["filename"] = "../secret.png"
            return httpx.Response(200, json={ident: {"status": {"status_str": "error" if state.get("cancelled") else "success", "completed": True},
                "prompt": [0, ident, state["prompt"], {"client_id": state["client_id"]}], "outputs": {"11": {"images": images}}}})
        if request.url.path == "/view":
            if mode == "invalid_png": return httpx.Response(200, content=b"not image bytes")
            buffer = io.BytesIO()
            Image.new("RGB", (1024, 1280) if mode != "size" else (16, 16), "black").save(buffer, format="PNG")
            return httpx.Response(200, content=buffer.getvalue())
        if request.url.path.startswith("/api/jobs/") and request.url.path.endswith("/cancel"):
            assert request.url.path == "/api/jobs/" + state["prompt_id"] + "/cancel"
            state["cancelled"] = True
            return httpx.Response(200, json={"cancelled": True})
        raise AssertionError("Unexpected endpoint")
    def streaming_handler(request):
        response = handler(request)
        return httpx.Response(response.status_code, headers=response.headers, stream=_Chunks([response.content]))
    return httpx.MockTransport(streaming_handler), calls


@pytest.mark.asyncio
async def test_mock_background_provenance_and_one_attempt(approved_contract):
    transport, calls = runtime_mock()
    adapter = provider(approved_contract, transport)
    result = await adapter.generate(prompt="BACKGROUND ONLY. cinematic empty environment", size="1024x1280",
        model=local.MODEL, reference_images=[approved_contract[1]])
    assert result.startswith(b"\x89PNG") and len(calls) == 10
    assert adapter.provenance["kind"] == "LOCAL_GENERATED_BACKGROUND"
    assert adapter.provenance["product_provenance"] is False
    assert adapter.provenance["claim_evidence"] is False
    assert adapter.provenance["semantic_qa"] == "NOT_RUN"
    assert adapter.provenance["reference_id"] == "owner-target"
    with pytest.raises(local.LocalBackgroundError, match="One local image attempt"):
        await adapter.generate(prompt="BACKGROUND ONLY.", size="1024x1280", model=local.MODEL)
    assert len(calls) == 10


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["timeout", "redirect", "bad_submit", "missing", "traversal", "invalid_png", "size"])
async def test_runtime_errors_never_fallback(approved_contract, mode):
    transport, calls = runtime_mock(mode)
    adapter = provider(approved_contract, transport)
    with pytest.raises((ValueError, httpx.TimeoutException, OSError)):
        await adapter.generate(prompt="BACKGROUND ONLY.", size="1024x1280", model=local.MODEL,
            reference_images=[approved_contract[1]])
    assert all(not path.startswith("/v1") for _, path in calls)
    assert sum(path == "/prompt" for _, path in calls) <= 1
    assert all(path != "/interrupt" for _, path in calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("override", [{"model": "gpt-image-2.5-sunburst-2026-09-08"},
    {"size": "1088x1360"}, {"prompt": "draw a product"}, {"quality": "xhigh"}, {"reference_images": []}])
async def test_invalid_request_does_not_contact_even_mock_runtime(approved_contract, override):
    transport, calls = runtime_mock()
    adapter = provider(approved_contract, transport)
    request = dict(prompt="BACKGROUND ONLY.", size="1024x1280", model=local.MODEL,
        reference_images=[approved_contract[1]])
    request.update(override)
    with pytest.raises(local.LocalBackgroundError): await adapter.generate(**request)
    assert calls == []


@pytest.mark.asyncio
async def test_changed_contract_and_reference_fail_before_http(approved_contract):
    transport, calls = runtime_mock()
    adapter = provider(approved_contract, transport)
    approved_contract[1].write_bytes(b"changed reference")
    with pytest.raises(local.LocalBackgroundError, match="Reference hash"):
        await adapter.generate(prompt="BACKGROUND ONLY.", size="1024x1280", model=local.MODEL,
            reference_images=[approved_contract[1]])
    assert calls == []


def test_preview_preserves_canonical_isolation_and_no_paid_clients():
    import inspect
    from scripts import run_v6_local_background_calibration as runner
    source = inspect.getsource(runner)
    assert "isolated_calibration_session" in source and "ai_provider=None" in source
    assert '"semantic_qa": "NOT_RUN"' in source and '"campaign_approval_created": False' in source
    assert "openai_provider_from_effective_settings" not in source and "run_qa_stage(" not in source


@pytest.mark.asyncio
async def test_unknown_preview_backend_fails_before_database(monkeypatch, tmp_path):
    from scripts import run_v6_local_background_calibration as runner
    def forbidden(*args, **kwargs): raise AssertionError("Canonical database touched")
    monkeypatch.setattr(runner, "isolated_calibration_session", forbidden)
    with pytest.raises(ValueError, match="no fallback"):
        await runner.preview(backend="unknown", manifest="none", workflow="none", runtime_url="none",
            database="none", database_sha256="none", campaign_id="none", output=tmp_path / "out", seed=17)


@pytest.mark.asyncio
async def test_manifest_replacement_after_constructor_fails_before_http(approved_contract):
    transport,calls=runtime_mock()
    adapter=provider(approved_contract,transport)
    change_manifest(approved_contract,lambda m:m.update(owner_approval="different approved state"))
    with pytest.raises(local.LocalBackgroundError,match="contract changed"):
        await adapter.generate(prompt="BACKGROUND ONLY.",size="1024x1280",model=local.MODEL,
            reference_images=[approved_contract[1]])
    assert calls==[]


@pytest.mark.asyncio
async def test_product_edit_is_never_a_local_background_operation(approved_contract):
    adapter=provider(approved_contract)
    with pytest.raises(local.LocalBackgroundError,match="product editing prohibited"):
        await adapter.edit(base_image=approved_contract[1],prompt="alter package")


@pytest.mark.parametrize("value",[0,-1,float("nan"),float("inf"),601])
def test_invalid_timeout_fails_before_client(approved_contract,value):
    with pytest.raises(local.LocalBackgroundError,match="timeout"):
        local.LocalComfyBackgroundProvider(**approved_contract[0],timeout_seconds=value)


def test_source_contract_has_no_installer_or_credential():
    import inspect
    source=inspect.getsource(local)
    assert "subprocess" not in source and "api.stability.ai" not in source
    assert "pip install" not in source and "api.openai.com" not in source
    assert "trust_env=False" in source and "follow_redirects=False" in source


# Socketless virtual clock: real asyncio timers/cancellation, no wall-clock sleep
# or loopback socket. BaseEventLoop schedules the actual production timeout_at.
import asyncio


class _VirtualLoop(asyncio.BaseEventLoop):
    def __init__(self):
        super().__init__()
        self.now = 0.0
        class Selector:
            def select(_self, timeout):
                if timeout is None:
                    raise AssertionError("Unexpected unscheduled asynchronous I/O")
                self.now += max(0, timeout)
                return []
        self._selector = Selector()
    def time(self): return self.now
    def _process_events(self, events): pass
    def _write_to_self(self): pass


def _run_virtual(coroutine):
    loop = _VirtualLoop()
    try:
        return loop.run_until_complete(coroutine)
    finally:
        pending = asyncio.all_tasks(loop)
        for task in pending: task.cancel()
        if pending: loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()


class _Chunks(httpx.AsyncByteStream):
    def __init__(self, chunks, delay=0, close_delay=0, error=None):
        self.chunks, self.delay, self.close_delay, self.error = chunks, delay, close_delay, error
        self.closed, self.consumed, self.close_started = False, 0, False
    async def __aiter__(self):
        for chunk in self.chunks:
            if self.delay: await asyncio.sleep(self.delay)
            self.consumed += 1
            yield chunk
        if self.error: raise self.error
    async def aclose(self):
        self.close_started = True
        if self.close_delay: await asyncio.sleep(self.close_delay)
        self.closed = True


@pytest.mark.parametrize("length", [0, 7, 8, 9])
def test_stream_repair_byte_limit_and_exact_boundary(length, monkeypatch):
    monkeypatch.setattr(local, "STREAM_CHUNK_BYTES", 1)
    stream = _Chunks([b"x"] * length + ([b"unread"] if length > 8 else []))
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, stream=stream)),
                base_url="http://127.0.0.1:8188") as client:
            async with asyncio.timeout_at(asyncio.get_running_loop().time()+1):
                if length > 8:
                    with pytest.raises(local.LocalBackgroundError, match="byte bounds"):
                        await local._bounded_response(client,"GET","/view",deadline=1,limit=8)
                else:
                    result=await local._bounded_response(client,"GET","/view",deadline=1,limit=8)
                    assert result.content == b"x" * length
    _run_virtual(scenario())
    assert stream.closed
    if length > 8: assert stream.consumed == 9  # no trailing data read


@pytest.mark.parametrize("headers", [{}, {"content-length":"1"}])
def test_stream_repair_untrusted_length_cannot_bypass_incremental_limit(headers, monkeypatch):
    monkeypatch.setattr(local,"STREAM_CHUNK_BYTES",1)
    stream=_Chunks([b"1234",b"5678",b"9",b"unread"])
    async def scenario():
        async with httpx.AsyncClient(base_url="http://127.0.0.1:8188",transport=httpx.MockTransport(
                lambda r:httpx.Response(200,stream=stream,headers=headers))) as client:
            with pytest.raises(local.LocalBackgroundError,match="byte bounds"):
                await local._bounded_response(client,"GET","/view",deadline=1,limit=8)
    _run_virtual(scenario());assert stream.closed and stream.consumed==3


@pytest.mark.parametrize("headers",[{"content-encoding":"gzip"},{"content-length":"-1"},
    {"content-length":"bogus"},{"content-length":"9"}])
def test_stream_repair_header_rejection_closes_unread_stream(headers):
    stream=_Chunks([b"unread"])
    async def scenario():
        async with httpx.AsyncClient(base_url="http://127.0.0.1:8188",transport=httpx.MockTransport(
                lambda r:httpx.Response(200,stream=stream,headers=headers))) as client:
            with pytest.raises(local.LocalBackgroundError):
                await local._bounded_response(client,"GET","/view",deadline=1,limit=8)
    _run_virtual(scenario());assert stream.closed and stream.consumed==0


@pytest.mark.parametrize("failure", ["continuous", "size", "read_error", "caller_cancel"])
def test_stream_repair_adapter_deadline_size_and_cleanup(approved_contract,monkeypatch,failure):
    monkeypatch.setattr(local,"STREAM_CHUNK_BYTES",1)
    monkeypatch.setattr(local,"MAX_OUTPUT_BYTES",8)
    base_transport, base_calls=runtime_mock()
    stream=_Chunks([b"x"]*100,delay=0.1) if failure=="continuous" else _Chunks(
        [b"x"]*20 if failure=="size" else [b"x"],
        delay=0.1 if failure=="caller_cancel" else 0,
        error=httpx.ReadError("midbody") if failure=="read_error" else None)
    streams=[];clients=[]
    class Client(httpx.AsyncClient):
        def __init__(self,**kwargs):super().__init__(**kwargs);clients.append(self)
    monkeypatch.setattr(local.httpx,"AsyncClient",Client)
    def handler(request):
        if request.url.path=="/view":
            streams.append(stream);return httpx.Response(200,stream=stream)
        return base_transport.handler(request)
    adapter=local.LocalComfyBackgroundProvider(**approved_contract[0],timeout_seconds=1,
        transport=httpx.MockTransport(handler))
    async def scenario():
        start=asyncio.get_running_loop().time()
        if failure=="caller_cancel":
            asyncio.get_running_loop().call_later(0.05,asyncio.current_task().cancel)
        with pytest.raises((TimeoutError,local.LocalBackgroundError,httpx.ReadError,asyncio.CancelledError)):
            await adapter.generate(prompt="BACKGROUND ONLY.",size="1024x1280",model=local.MODEL,
                reference_images=[approved_contract[1]])
        assert asyncio.get_running_loop().time()-start <= 1
        assert adapter.provenance is None
        with pytest.raises(local.LocalBackgroundError,match="One local image attempt"):
            await adapter.generate(prompt="BACKGROUND ONLY.",size="1024x1280",model=local.MODEL)
    _run_virtual(scenario())
    assert streams and stream.closed and clients[0].is_closed
    assert sum(path=="/prompt" for _,path in base_calls)==1
    assert sum(path=="/interrupt" for _,path in base_calls)==0  # History already terminal: no GPU job to interrupt.
    if failure=="continuous":assert stream.consumed < 10
    if failure=="size":assert stream.consumed==9


def test_stream_repair_cleanup_cannot_extend_total_deadline(approved_contract,monkeypatch):
    monkeypatch.setattr(local,"STREAM_CHUNK_BYTES",1)
    transport,calls=runtime_mock("pending");work=_Chunks([b"{}"],delay=2)
    cleanup=_Chunks([b"{}"],delay=10)
    def handler(request):
        if request.url.path.startswith("/history/"):return httpx.Response(200,stream=work)
        if request.url.path.endswith("/cancel"):
            calls.append(("POST",request.url.path));return httpx.Response(200,stream=cleanup)
        return transport.handler(request)
    adapter=local.LocalComfyBackgroundProvider(**approved_contract[0],timeout_seconds=1,transport=httpx.MockTransport(handler))
    async def scenario():
        with pytest.raises(local.LocalBackgroundError, match="TIMEOUT"):
            await adapter.generate(prompt="BACKGROUND ONLY.",size="1024x1280",model=local.MODEL,
                reference_images=[approved_contract[1]])
        assert asyncio.get_running_loop().time()<=1
    _run_virtual(scenario());assert work.closed and cleanup.closed
    assert sum(path.endswith("/cancel") for _,path in calls)==1


def test_stream_repair_shared_deadline_not_restarted(approved_contract,monkeypatch):
    transport,calls=runtime_mock();streams=[]
    async def handler(request):
        if request.url.path in ("/object_info","/upload/image","/prompt"):
            await asyncio.sleep(0.3)
        response=transport.handler(request)
        return response
    adapter=local.LocalComfyBackgroundProvider(**approved_contract[0],timeout_seconds=1,transport=httpx.MockTransport(handler))
    async def scenario():
        with pytest.raises(local.LocalBackgroundError, match="TIMEOUT"):
            await adapter.generate(prompt="BACKGROUND ONLY.",size="1024x1280",model=local.MODEL,
                reference_images=[approved_contract[1]])
        assert asyncio.get_running_loop().time()<=1
    _run_virtual(scenario());assert sum(path=="/prompt" for _,path in calls)==0



def test_stream_repair_normal_stream_completes_before_deadline():
    stream=_Chunks([b"a",b"b",b"c"],delay=0.1)
    async def scenario():
        async with httpx.AsyncClient(base_url="http://127.0.0.1:8188",transport=httpx.MockTransport(
                lambda r:httpx.Response(200,stream=stream))) as client:
            async with asyncio.timeout_at(1):
                result=await local._bounded_response(client,"GET","/view",deadline=1,limit=8)
                assert result.content==b"abc" and asyncio.get_running_loop().time()==pytest.approx(0.3)
        assert client.is_closed
    _run_virtual(scenario());assert stream.closed


def test_stream_repair_rejected_status_closes_response_without_body_read():
    stream=_Chunks([b"unread"])
    async def scenario():
        async with httpx.AsyncClient(base_url="http://127.0.0.1:8188",transport=httpx.MockTransport(
                lambda r:httpx.Response(500,stream=stream))) as client:
            with pytest.raises(local.LocalBackgroundError,match="request failed"):
                await local._bounded_response(client,"GET","/history/job",deadline=1)
        assert client.is_closed
    _run_virtual(scenario());assert stream.closed and stream.consumed==0



def test_stream_repair_buffered_continuous_chunks_cannot_starve_deadline():
    class BusyStream(_Chunks):
        async def __aiter__(self):
            for _ in range(100):
                asyncio.get_running_loop().now += 0.1
                self.consumed += 1
                yield b"x"
    stream=BusyStream([])
    async def scenario():
        async with httpx.AsyncClient(base_url="http://127.0.0.1:8188",transport=httpx.MockTransport(
                lambda r:httpx.Response(200,stream=stream))) as client:
            with pytest.raises(TimeoutError):
                async with asyncio.timeout_at(1):
                    await local._bounded_response(client,"GET","/view",deadline=1,limit=1000)
    _run_virtual(scenario());assert stream.closed and stream.consumed <= 11
