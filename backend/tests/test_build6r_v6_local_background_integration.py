"""Synthetic artifacts, memory databases and HTTP doubles; never a GPU runtime."""
import asyncio
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from app.services.ai import image_provider_factory as factory
from app.services.ai import local_background_provider as local
from test_build6r_v6_local_background_provider import approved_contract, provider, runtime_mock, change_manifest, _Chunks
from test_build6r_v342_locked_product_pipeline_integration import owner_target


FIELDS = [(key, field) for key, (_, inputs) in local._FROZEN.items() for field in ["class_type", *inputs]
          if (key, field) not in {("2", "text"), ("5", "image"), ("9", "seed"), ("11", "filename_prefix")}]


@pytest.mark.parametrize("node,field", FIELDS)
def test_every_frozen_field_is_protected_even_with_new_approved_hash(approved_contract, node, field):
    path = approved_contract[0]["workflow_path"]
    graph = json.loads(path.read_text())
    target = graph[node] if field == "class_type" else graph[node]["inputs"]
    old = target[field]
    target[field] = "injected" if isinstance(old, str) else ["11", 0] if isinstance(old, list) else 999
    path.write_text(json.dumps(graph))
    change_manifest(approved_contract, lambda m: m.update(workflow_sha256=local.digest(path)))
    with pytest.raises(local.LocalBackgroundError, match="workflow"):
        provider(approved_contract)


def test_boolean_cannot_replace_frozen_float(approved_contract):
    path = approved_contract[0]["workflow_path"]
    graph = json.loads(path.read_text())
    graph["8"]["inputs"]["end_at"] = True
    path.write_text(json.dumps(graph))
    change_manifest(approved_contract, lambda m: m.update(workflow_sha256=local.digest(path)))
    with pytest.raises(local.LocalBackgroundError):
        provider(approved_contract)


def test_integrity_preflight_has_a_cooperative_deadline(approved_contract, monkeypatch):
    times = iter([0, 301])
    monkeypatch.setattr(local.time, "monotonic", lambda: next(times))
    with pytest.raises(local.LocalBackgroundError, match="TIMEOUT"):
        provider(approved_contract)


@pytest.mark.parametrize("fault", ["missing_code", "extra_file", "code_hash", "state_in_runtime", "reference_roots"])
def test_complete_inventory_and_private_roots_are_required(approved_contract, fault):
    data = json.loads(approved_contract[0]["manifest_path"].read_text())
    runtime = Path(data["runtime_root"])
    if fault == "missing_code": (runtime / "ComfyUI/server.py").unlink()
    if fault == "extra_file": (runtime / "unapproved.py").write_bytes(b"extra")
    if fault == "code_hash": (runtime / "ComfyUI/main.py").write_bytes(b"changed")
    if fault == "state_in_runtime": change_manifest(approved_contract, lambda m: m.update(state_root=str(runtime)))
    if fault == "reference_roots": change_manifest(approved_contract, lambda m: m.update(reference_roots=[]))
    with pytest.raises(local.LocalBackgroundError):
        provider(approved_contract)


def test_inactive_routing_preserves_legacy_factory_and_config():
    config = SimpleNamespace(image_model="existing", premium_image_model="existing")
    calls = []
    expected = object()
    actual = factory.resolve_image_provider({}, legacy_factory=lambda e: calls.append(e) or expected,
        config=config, job_id="job", campaign_id="campaign")
    assert actual is expected and calls == [{}] and vars(config) == {"image_model": "existing", "premium_image_model": "existing"}
    assert factory.local_routing_enabled() is False


def test_invalid_local_configuration_never_constructs_paid_client(monkeypatch):
    monkeypatch.setattr(factory, "read_routing", lambda: {"enabled": True, "manifest_path": None})
    config = SimpleNamespace(use_ai_background=True, recreate_with_ai=False, use_masked_scene_edit=False,
        quality_mode="premium", enable_qa_stage=False, qa_max_retries=0, qa_best_of_n=1)
    def paid(_): raise AssertionError("Paid factory invoked")
    with pytest.raises(local.LocalBackgroundError, match="approval missing"):
        factory.resolve_image_provider({}, legacy_factory=paid, config=config, job_id="job", campaign_id="campaign")


def context(**updates):
    value = dict(job_id="job", job_attempt=1, campaign_id="campaign", platform="instagram", language="pt-BR",
        slide_number=1, slide_contract_sha256="a" * 64, reference_id="target", reference_sha256="b" * 64,
        workflow_sha256="c" * 64, seed=0)
    value.update(updates)
    return value


def test_generation_identity_is_deterministic_and_attempt_specific():
    assert factory.generation_id(context()) == factory.generation_id(dict(reversed(list(context().items()))))
    assert factory.generation_id(context()) != factory.generation_id(context(job_attempt=2))
    assert factory.generation_id(context()) != factory.generation_id(context(slide_number=2))
    with pytest.raises(local.LocalBackgroundError): factory.generation_id(context(seed=-1))


@pytest.mark.parametrize("key", ["job_id", "campaign_id", "platform", "language", "reference_id"])
def test_generation_identity_rejects_truthy_nonstring_identifiers(key):
    with pytest.raises(local.LocalBackgroundError, match="GENERATION_IDENTITY_INVALID"):
        factory.generation_id(context(**{key: True}))


@pytest.mark.asyncio
async def test_concurrent_objects_admit_only_one_and_duplicate_never_replays(tmp_path):
    first = factory.EndpointAdmission(tmp_path, "http://127.0.0.1:8189", wait_seconds=.02)
    second = factory.EndpointAdmission(tmp_path, "http://127.0.0.1:8189", wait_seconds=.02)
    ident = factory.generation_id(context())
    intent = await first.acquire(ident, "hash")
    try:
        with pytest.raises(local.LocalBackgroundError, match="BUSY"):
            await second.acquire(factory.generation_id(context(slide_number=2)), "hash")
        first.finish(intent, {"status": "completed"}, terminal=True)
    finally:
        first.release()
    with pytest.raises(local.LocalBackgroundError, match="DUPLICATE"):
        await second.acquire(ident, "hash")


@pytest.mark.asyncio
async def test_unknown_terminal_state_quarantines_next_job(tmp_path):
    first = factory.EndpointAdmission(tmp_path, "http://127.0.0.1:8189", wait_seconds=.01)
    ident = factory.generation_id(context())
    intent = await first.acquire(ident, "hash")
    first.finish(intent, {"status": "unknown"}, terminal=False)
    first.release()
    with pytest.raises(local.LocalBackgroundError, match="TERMINAL_STATE_UNCONFIRMED"):
        await factory.EndpointAdmission(tmp_path, "http://127.0.0.1:8189").acquire(
            factory.generation_id(context(slide_number=2)), "hash")


@pytest.mark.asyncio
async def test_os_mutex_blocks_another_process(tmp_path):
    first = factory.EndpointAdmission(tmp_path, "http://127.0.0.1:8189")
    ident = factory.generation_id(context())
    intent = await first.acquire(ident, "hash")
    program = '''import asyncio,sys
from pathlib import Path
from app.services.ai.image_provider_factory import EndpointAdmission
from app.services.ai.local_background_provider import LocalBackgroundError
async def check():
 try: await EndpointAdmission(Path(sys.argv[1]),"http://127.0.0.1:8189",wait_seconds=.03).acquire(sys.argv[2],"hash")
 except LocalBackgroundError as e:
  assert e.code=="BUSY",str(e)
 else: raise AssertionError("Two processes acquired GPU admission")
asyncio.run(check())'''
    try:
        child = await asyncio.to_thread(subprocess.run, [sys.executable, "-B", "-c", program,
            str(tmp_path), factory.generation_id(context(slide_number=2))], cwd=Path(__file__).parents[1],
            capture_output=True, text=True, timeout=15)
        assert child.returncode == 0, child.stderr
        first.finish(intent, {"status": "completed"}, terminal=True)
    finally:
        first.release()


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["../outside.png", "folder/../reference.png", "relative.png", "C:/not-approved/private.png"])
async def test_hostile_reference_paths_never_contact_http(approved_contract, path):
    transport, calls = runtime_mock()
    value = approved_contract[1].parent / path if path.startswith(("..", "folder")) else Path(path)
    adapter = provider(approved_contract, transport)
    with pytest.raises(local.LocalBackgroundError):
        await adapter.generate(prompt="BACKGROUND ONLY.", size="1024x1280", model=local.MODEL, reference_images=[value])
    assert calls == []


@pytest.mark.asyncio
async def test_result_archival_is_correlated_and_never_requires_optional_trace(approved_contract):
    transport, calls = runtime_mock()
    adapter = provider(approved_contract, transport)
    await adapter.generate(prompt="BACKGROUND ONLY.", size="1024x1280", model=local.MODEL, reference_images=[approved_contract[1]])
    result = adapter.provenance
    assert result["runtime_prompt_id"] == result["generation_id"]
    assert local.digest(Path(result["background_path"])) == result["output_sha256"]
    assert result["history"]["prompt"][2] == result["submitted_workflow"]
    assert result["provider_cost_usd"] == 0 and result["cost_known"] is True
    assert len(adapter.drain_usage_events()) == 1 and adapter.drain_usage_events() == []
    assert not list(Path(result["background_path"]).parent.glob("model-loads.jsonl"))
    assert sum(path == "/prompt" for _, path in calls) == 1


@pytest.mark.asyncio
async def test_client_cleanup_failure_cannot_report_completed_request(approved_contract, monkeypatch):
    real_client = httpx.AsyncClient
    class ClosingFailure(real_client):
        async def aclose(self):
            await super().aclose()
            raise RuntimeError("synthetic cleanup failure")
    monkeypatch.setattr(httpx, "AsyncClient", ClosingFailure)
    transport, calls = runtime_mock()
    adapter = provider(approved_contract, transport)
    with pytest.raises(local.LocalBackgroundError, match="CLIENT_CLEANUP_UNCONFIRMED"):
        await adapter.generate(prompt="BACKGROUND ONLY.", size="1024x1280", model=local.MODEL,
                               reference_images=[approved_contract[1]])
    state = Path(adapter.manifest["state_root"])
    intent = json.loads(next(state.glob("*.intent.json")).read_text())
    assert intent["status"] == "CLIENT_CLEANUP_UNCONFIRMED" and intent["provider_cost_usd"] == 0.0
    assert intent["terminal_confirmed"] is True and sum(path == "/prompt" for _, path in calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("fault,code", [("health", "STARTUP_FAILED"), ("python", "STARTUP_FAILED"),
    ("wrong_runtime", "STARTUP_FAILED"), ("cuda", "CUDA_UNAVAILABLE"),
    ("unavailable", "RUNTIME_UNAVAILABLE"), ("crash", "PROCESS_CRASH"), ("node", "CUSTOM_NODE_MISSING"),
    ("model", "MODEL_MISSING"), ("reject", "WORKFLOW_REJECTED"), ("oom", "CUDA_OOM"),
    ("history", "OUTPUT_CORRELATION_MISMATCH"), ("foreign", "OUTPUT_CORRELATION_MISMATCH")])
async def test_domain_errors_no_resubmission_or_paid_fallback(approved_contract, fault, code):
    base, calls = runtime_mock()
    def handle(request):
        response = base.handler(request)
        if fault == "health" and request.url.path == "/system_stats": return httpx.Response(200, json={})
        if fault == "cuda" and request.url.path == "/system_stats":
            data = json.loads(response.stream.chunks[0])
            data["devices"] = []
            return httpx.Response(200, json=data)
        if fault in ("python", "wrong_runtime") and request.url.path == "/system_stats":
            data = json.loads(response.stream.chunks[0])
            if fault == "python": data["system"]["python_version"] = "3.12.0 (wrong runtime)"
            else: data["system"]["argv"] = ["C:/unapproved/ComfyUI/main.py"]
            return httpx.Response(200, json=data)
        if (fault == "unavailable" and request.url.path == "/system_stats"
                or fault == "crash" and request.url.path.startswith("/history/")):
            raise httpx.ConnectError("synthetic service unavailable", request=request)
        if fault == "node" and request.url.path == "/object_info": return httpx.Response(200, json={})
        if fault == "model" and request.url.path.startswith("/models/"): return httpx.Response(200, json=[])
        if fault == "reject" and request.url.path == "/prompt": return httpx.Response(400, json={"error": "invalid", "node_errors": {}})
        if request.url.path.startswith("/history/") and fault in ("oom", "history", "foreign"):
            # Mock streams are synchronous fixtures; decode their one chunk.
            data = json.loads(response.stream.chunks[0])
            record = next(iter(data.values()))
            if fault == "oom": record["status"] = {"completed": True, "status_str": "error", "messages": ["CUDA out of memory"]}
            if fault == "history": record["prompt"][3]["client_id"] = "another-request"
            if fault == "foreign": record["outputs"]["11"]["images"][0]["filename"] = "foreign_00001_.png"
            return httpx.Response(200, json=data)
        return response
    def streaming(request):
        response = handle(request)
        if response.is_stream_consumed:
            return httpx.Response(response.status_code, headers=response.headers, stream=_Chunks([response.content]))
        return response
    adapter = provider(approved_contract, httpx.MockTransport(streaming))
    with pytest.raises(local.LocalBackgroundError) as error:
        await adapter.generate(prompt="BACKGROUND ONLY.", size="1024x1280", model=local.MODEL, reference_images=[approved_contract[1]])
    assert error.value.code == code
    assert sum(path == "/prompt" for _, path in calls) <= 1
    assert all(path != "/interrupt" and not path.startswith("/v1") for _, path in calls)


@pytest.mark.asyncio
async def test_prepared_session_admits_only_finite_unique_slide_contracts(approved_contract, owner_target):
    from app.schemas.ai import SlidePlan
    target, reference, ref = owner_target
    plan = SlidePlan(slide_number=1, purpose="hook", headline="Discover",
        visual_brief=json.dumps({"REFERENCE_TARGET": target.model_dump()}),
        reference_asset_ids=[target.reference_id], reference_assets=[vars(ref)])
    options = {k: v for k, v in approved_contract[0].items() if k not in ("reference_id", "reference_sha256", "seed")}
    transport, calls = runtime_mock()
    session = factory.LocalProviderSession(job_id="isolated-job", campaign_id="isolated-campaign", seed=17,
                                          transport=transport, **options)
    with pytest.raises(local.LocalBackgroundError, match="UNPREPARED"):
        session.for_slide(plan=plan, platform="instagram", language="pt-BR")
    session.prepare(plans=[plan], platforms=["instagram"], languages=["pt-BR"])
    child = session.for_slide(plan=plan, platform="instagram", language="pt-BR")
    await child.generate(prompt="BACKGROUND ONLY.", size="1024x1280", model=local.MODEL, reference_images=[reference])
    with pytest.raises(local.LocalBackgroundError, match="DUPLICATE"):
        session.for_slide(plan=plan, platform="instagram", language="pt-BR")
    assert len(session.drain_usage_events()) == 1 and session.drain_usage_events() == []
    assert sum(path == "/prompt" for _, path in calls) == 1


@pytest.mark.asyncio
async def test_pending_timeout_targets_only_own_uuid_and_never_resubmits(approved_contract):
    transport, calls = runtime_mock("pending")
    adapter = local.LocalComfyBackgroundProvider(**approved_contract[0], transport=transport,
        timeout_seconds=.2, phase_timeouts=dict(health=.1, upload=.1, submit=.1, generation=.02, output=.1))
    with pytest.raises(local.LocalBackgroundError) as error:
        await adapter.generate(prompt="BACKGROUND ONLY.", size="1024x1280", model=local.MODEL, reference_images=[approved_contract[1]])
    assert error.value.code == "TIMEOUT"
    assert sum(path == "/prompt" for _, path in calls) == 1
    assert sum(path.endswith("/cancel") for _, path in calls) == 1
    assert all(path != "/interrupt" for _, path in calls)


@pytest.mark.asyncio
async def test_job_cancellation_is_persisted(temp_db):
    from app.services import jobs
    db = temp_db.SessionLocal()
    job = jobs.create_job(db, type_="isolated_local_test")
    async def cancelled(_): raise asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError): await jobs.run_job(job.id, cancelled)
    db.refresh(job)
    assert job.status == "CANCELLED" and job.error == "CANCELLED"
    db.close()


@pytest.mark.asyncio
async def test_local_visuals_api_does_not_require_or_construct_paid_image_client(temp_db, monkeypatch, tmp_path):
    from app.api import campaigns as api
    from app.models import Brand, Campaign
    db = temp_db.SessionLocal()
    brand = Brand(name="Synthetic", slug="synthetic")
    db.add(brand); db.flush()
    campaign = Campaign(display_id="TEST-LOCAL", brand_id=brand.id, objective="awareness", status="COPY_READY")
    db.add(campaign); db.commit()
    marker = SimpleNamespace(is_local_background=True)
    monkeypatch.setattr(api, "local_routing_enabled", lambda: True)
    monkeypatch.setattr(api, "check_visuals_stage_prerequisite", lambda *a: None)
    monkeypatch.setattr(api.settings_store, "get_effective_settings", lambda db: {"output_root": str(tmp_path)})
    monkeypatch.setattr(api, "resolve_image_provider", lambda *a, **k: marker)
    def forbidden(*a, **k): raise AssertionError("Paid provider constructed")
    monkeypatch.setattr(api, "openai_provider_from_effective_settings", forbidden)
    pending = []
    monkeypatch.setattr(api, "run_job_in_background", lambda ident, fn: pending.append((ident, fn)))
    seen = []
    async def visuals(*a, **k): seen.append(k)
    monkeypatch.setattr(api, "run_visuals_stage", visuals)
    response = await api.generate_campaign_visuals(campaign.id, use_ai_background=True,
        detect_product_zone=False, recreate_with_ai=False, quality_mode="premium", render_platform_variants=True, db=db)
    await pending[0][1](SimpleNamespace(job_id=response["job_id"]))
    assert seen[0]["image_provider"] is marker and seen[0]["ai_provider"] is None
    assert seen[0]["config"].qa_max_retries == 0
    db.close()
