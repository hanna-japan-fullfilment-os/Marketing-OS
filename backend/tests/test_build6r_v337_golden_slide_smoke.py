from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
from PIL import Image

BACKEND = Path(__file__).resolve().parents[1]
HARNESS_PATH = BACKEND / "scripts" / "run_golden_slide_smoke.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("build6r_v337_golden_slide_smoke", HARNESS_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _png(path: Path, value: int) -> str:
    image = Image.new("RGB", (32, 48), (value, value, value))
    image.save(path, format="PNG")
    import hashlib
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture_database(tmp_path: Path, monkeypatch):
    mod = _load_module()
    import sqlite3
    db = tmp_path / "app.db"
    source = tmp_path / "source.png"
    master = tmp_path / "master.png"
    source_sha = _png(source, 90)
    master_sha = _png(master, 180)
    monkeypatch.setattr(mod, "EXPECTED_SOURCE_SHA256", source_sha)
    monkeypatch.setattr(mod, "EXPECTED_MASTER_SHA256", master_sha)
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE brands (id TEXT PRIMARY KEY, slug TEXT NOT NULL, name TEXT NOT NULL);
        CREATE TABLE products (id TEXT PRIMARY KEY, brand_id TEXT NOT NULL, slug TEXT NOT NULL, name TEXT NOT NULL);
        CREATE TABLE verified_product_facts (
            product_id TEXT PRIMARY KEY, verified_description TEXT, verified_ingredients TEXT,
            verified_features TEXT, verified_benefits TEXT, verified_usage TEXT, verified_size TEXT,
            verified_variant TEXT, verified_price TEXT, verified_availability TEXT,
            verified_country_of_origin TEXT, verified_claims TEXT, prohibited_claims TEXT,
            source_asset_ids TEXT, source_references TEXT, confidence REAL, provenance TEXT
        );
        CREATE TABLE assets (
            id TEXT PRIMARY KEY, product_id TEXT, absolute_path TEXT, sha256 TEXT,
            image_role TEXT, is_active INTEGER, ai_metadata TEXT
        );
        CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT);
        """
    )
    conn.execute("INSERT INTO brands(id,slug,name) VALUES (?,?,?)", ("brand-1", mod.BRAND_SLUG, "Hanna Japan"))
    conn.execute(
        "INSERT INTO products(id,brand_id,slug,name) VALUES (?,?,?,?)",
        (mod.EXPECTED_PRODUCT_ID, "brand-1", mod.PRODUCT_SLUG, "LuLuLun Hydra EX Mask 7 Sheets"),
    )
    conn.execute(
        """
        INSERT INTO verified_product_facts(
            product_id,verified_description,verified_ingredients,verified_features,verified_benefits,
            verified_usage,verified_size,verified_variant,verified_price,verified_availability,
            verified_country_of_origin,verified_claims,prohibited_claims,source_asset_ids,
            source_references,confidence,provenance
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            mod.EXPECTED_PRODUCT_ID,
            "LuLuLun Hydra EX facial sheet mask, exact 7-sheet pouch variant. Manufacturer sales name: Face Mask LuLuLun EX 1FS.",
            "[]",
            json.dumps(["7-sheet pouch variant", "Contains 150 mL of essence"]),
            "[]", "", "7 sheets / essence 150 mL", "Face Mask LuLuLun EX 1FS - 7-sheet pouch",
            "", "", "", json.dumps(["7-sheet pouch containing 150 mL of essence"]), "[]",
            json.dumps([mod.EXPECTED_SOURCE_ASSET_ID]), "[]", 1.0, "manufacturer_official+owner_confirmed",
        ),
    )
    meta = {
        "ai_generated": True,
        "campaign_time_immutable": True,
        "human_review": {"status": "APPROVED"},
        "product_fidelity": {"overall_verdict": "PASS"},
        "full_reconstruction_exception": {"status": "APPROVED", "approved_sha256": master_sha},
        "source_asset_id": mod.EXPECTED_SOURCE_ASSET_ID,
        "source_sha256": source_sha,
    }
    conn.execute(
        "INSERT INTO assets(id,product_id,absolute_path,sha256,image_role,is_active,ai_metadata) VALUES (?,?,?,?,?,?,?)",
        (mod.EXPECTED_SOURCE_ASSET_ID, mod.EXPECTED_PRODUCT_ID, str(source), source_sha, "product", 1, json.dumps({"ai_generated": False})),
    )
    conn.execute(
        "INSERT INTO assets(id,product_id,absolute_path,sha256,image_role,is_active,ai_metadata) VALUES (?,?,?,?,?,?,?)",
        (mod.EXPECTED_MASTER_ASSET_ID, mod.EXPECTED_PRODUCT_ID, str(master), master_sha, "product_master_approved", 1, json.dumps(meta)),
    )
    conn.commit(); conn.close()
    return mod, db, source, master


def _patch_base(monkeypatch, model="gpt-image-2.5-sunburst-2026-09-08"):
    class Base:
        openai_api_key = ""
        openai_premium_image_model = model
        openai_project_id = ""
        openai_project_hard_limit_attested = False
        openai_max_image_calls = None
    import app.config
    monkeypatch.setattr(app.config, "get_settings", lambda: Base())


def test_frozen_copy_is_minimal_and_canonically_bounded():
    mod = _load_module()
    assert mod.FROZEN_HEADLINE == "LuLuLun Hydra EX"
    assert mod.FROZEN_SUPPORT == "Máscara facial • 7 folhas"
    assert mod.FROZEN_DETAIL == "150 mL de essência"
    blob = " ".join((mod.FROZEN_HEADLINE, mod.FROZEN_SUPPORT, mod.FROZEN_DETAIL)).casefold()
    for forbidden in ("japonesa", "preço", "estoque", "exossom"):
        assert forbidden not in blob


def test_harness_contains_no_autonomous_pipeline_call_surface():
    source = HARNESS_PATH.read_text(encoding="utf-8")
    for marker in (
        "run_research(", "run_strategy(", "run_master_campaign_concept(",
        "run_creative_brief(", "run_copy_stage(", "augment_with_ai_extraction(",
        "claims_audit.", "orchestrator.",
    ):
        assert marker not in source
    assert source.count("await provider.generate(") == 1


def test_prepare_request_resolves_exact_assets_and_copy(tmp_path, monkeypatch):
    mod, db, source, master = _fixture_database(tmp_path, monkeypatch)
    _patch_base(monkeypatch)
    payload = mod._prepare_request(db)
    assert payload["canonical_git_branch"] == "main"
    assert len(payload["canonical_git_commit"]) == 40
    assert len(payload["canonical_git_tree"]) == 40
    assert len(payload["v337_harness_sha256"]) == 64
    assert len(payload["v337_test_sha256"]) == 64
    assert payload["brand_slug"] == mod.BRAND_SLUG
    assert payload["product_slug"] == mod.PRODUCT_SLUG
    assert payload["headline"] == mod.FROZEN_HEADLINE
    assert payload["support_line"] == mod.FROZEN_SUPPORT
    assert payload["detail_line"] == mod.FROZEN_DETAIL
    assert payload["model"] == "gpt-image-2.5-sunburst-2026-09-08"
    assert payload["quality"] == "xhigh"
    assert payload["size"] == "1024x1536"
    assert payload["max_image_calls"] == 1
    assert payload["text_model_call_count_before_image"] == 0
    assert Path(payload["reference_images"][0]["path"]) == master.resolve()
    assert Path(payload["reference_images"][1]["path"]) == source.resolve()


def test_dry_run_writes_request_evidence_and_zero_usage(tmp_path, monkeypatch, capsys):
    mod, db, _, _ = _fixture_database(tmp_path, monkeypatch)
    _patch_base(monkeypatch)
    evidence = tmp_path / "evidence"
    rc = mod.main(["--database", str(db), "--evidence-dir", str(evidence), "--dry-run"])
    assert rc == 0
    output = capsys.readouterr().out
    for marker in (
        "GOLDEN_SLIDE_INPUT_VALID=TRUE", "CANONICAL_PRODUCT_RESOLVED=TRUE",
        "APPROVED_SOURCE_IMAGE_RESOLVED=TRUE", "FIXED_COPY_RESOLVED=TRUE",
        "VISUAL_PROMPT_CONSTRUCTED=TRUE", "TEXT_MODEL_CALL_COUNT=0",
        "IMAGE_CALL_COUNT=0", "PAID_CALLS=0", "READY_FOR_ONE_IMAGE_SMOKE_TEST=TRUE",
        "ATTEMPT12_AUTHORIZED=FALSE",
    ):
        assert marker in output
    request = json.loads((evidence / "golden_slide_request.json").read_text(encoding="utf-8"))
    assert request["text_model_call_count_before_image"] == 0
    assert request["max_image_calls"] == 1
    assert (evidence / "golden_slide_result.json").is_file()
    assert (evidence / "evidence_manifest.txt").is_file()


def test_prompt_requires_identity_preservation_and_exact_copy():
    mod = _load_module(); prompt = mod._visual_prompt()
    for value in (mod.FROZEN_HEADLINE, mod.FROZEN_SUPPORT, mod.FROZEN_DETAIL):
        assert value in prompt
    assert "Preserve the exact pouch identity" in prompt
    assert "Do not redesign" in prompt
    assert "no other external headline" in prompt
    assert "Do not invent a Hanna logo" in prompt


def test_live_execution_requires_separate_authorization(tmp_path, monkeypatch):
    mod = _load_module(); monkeypatch.delenv("BUILD6R_V337_IMAGE_SMOKE_AUTHORIZED", raising=False)
    with pytest.raises(RuntimeError, match="not authorized"):
        mod._assert_live_controls(tmp_path / "isolated.db", 0.50)


def test_live_execution_rejects_canonical_database(monkeypatch):
    mod = _load_module()
    monkeypatch.setenv("BUILD6R_V337_IMAGE_SMOKE_AUTHORIZED", "TRUE")
    for k, v in {
        "OPENAI_MAX_IMAGE_CALLS": "1", "OPENAI_SDK_MAX_RETRIES": "0",
        "OPENAI_REQUEST_TIMEOUT_SECONDS": "180", "QA_MAX_RETRIES": "0", "QA_BEST_OF_N": "1",
    }.items(): monkeypatch.setenv(k, v)
    with pytest.raises(RuntimeError, match="canonical SQLite"):
        mod._assert_live_controls(mod.CANONICAL_DB, 0.50)


def test_live_controls_are_fail_closed(tmp_path, monkeypatch):
    mod = _load_module(); isolated = tmp_path / "isolated.db"; isolated.write_bytes(b"x")
    monkeypatch.setenv("BUILD6R_V337_IMAGE_SMOKE_AUTHORIZED", "TRUE")
    monkeypatch.setenv("OPENAI_MAX_IMAGE_CALLS", "2")
    monkeypatch.setenv("OPENAI_SDK_MAX_RETRIES", "0")
    monkeypatch.setenv("OPENAI_REQUEST_TIMEOUT_SECONDS", "180")
    monkeypatch.setenv("QA_MAX_RETRIES", "0"); monkeypatch.setenv("QA_BEST_OF_N", "1")
    with pytest.raises(RuntimeError, match="OPENAI_MAX_IMAGE_CALLS"):
        mod._assert_live_controls(isolated, 0.50)


@pytest.mark.asyncio
async def test_execute_image_helper_calls_generate_exactly_once(tmp_path, monkeypatch):
    mod, db, source, master = _fixture_database(tmp_path, monkeypatch)
    payload = {
        "prompt": "golden", "size": "1024x1536", "model": "gpt-image-2.5-sunburst-2026-09-08",
        "quality": "xhigh", "reference_images": [{"path": str(master)}, {"path": str(source)}],
    }
    calls = []
    class FakeProvider:
        async def generate(self, **kwargs):
            calls.append(kwargs)
            path = tmp_path / "generated.png"; Image.new("RGB", (32, 48), (220, 220, 220)).save(path)
            return path.read_bytes()
        def drain_usage_events(self):
            return [{"provider":"openai","model":payload["model"],"input_tokens":0,"output_tokens":0,"image_count":1,"estimated_cost_usd":0.1}]
        def hard_budget_snapshot(self): return {"enabled": True, "spent_usd": 0.1}
    import app.services.ai.openai_provider as provider_module
    monkeypatch.setattr(provider_module, "openai_provider_from_effective_settings", lambda effective, hard_budget_usd: FakeProvider())
    class Base:
        openai_api_key = "sk-test"; openai_premium_image_model = payload["model"]
        openai_project_id = "proj_test"; openai_project_hard_limit_attested = True; openai_max_image_calls = 1
    import app.config
    monkeypatch.setattr(app.config, "get_settings", lambda: Base())
    image_bytes, events, budget = await mod._execute_image_once(payload=payload, database=db, max_budget_usd=0.50)
    assert image_bytes and len(calls) == 1
    assert calls[0]["reference_images"] == [master, source]
    assert sum(int(e["image_count"]) for e in events) == 1
    assert budget["enabled"] is True


def test_usage_validator_rejects_any_text_tokens():
    mod = _load_module()
    with pytest.raises(RuntimeError, match="text-model token usage"):
        mod._validate_live_usage([{"image_count":1,"input_tokens":1,"output_tokens":0,"estimated_cost_usd":0.1}])


def test_usage_validator_requires_exactly_one_image_call():
    mod = _load_module()
    with pytest.raises(RuntimeError, match="exactly one image call"):
        mod._validate_live_usage([{"image_count":0,"input_tokens":0,"output_tokens":0,"estimated_cost_usd":0.0}])