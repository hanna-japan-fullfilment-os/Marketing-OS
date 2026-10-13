from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest
from PIL import Image

BACKEND = Path(__file__).resolve().parents[1]
COMPOSITOR_PATH = BACKEND / "app" / "services" / "locked_product_compositor.py"
HARNESS_PATH = BACKEND / "scripts" / "run_locked_product_composite_smoke.py"


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _make_master(path: Path) -> None:
    image = Image.new("RGBA", (180, 240), (0, 0, 0, 0))
    for y in range(15, 225):
        for x in range(20, 160):
            image.putpixel((x, y), (72, 30, 120, 255))
    image.save(path)


def _make_source(path: Path) -> None:
    Image.new("RGB", (180, 240), (80, 40, 120)).save(path)


def test_compositor_has_no_ai_provider_dependency():
    source = COMPOSITOR_PATH.read_text(encoding="utf-8")
    for forbidden in ("openai", "provider.generate", "reference_images"):
        assert forbidden not in source.casefold()


def test_locked_product_transform_contract_is_narrow():
    source = COMPOSITOR_PATH.read_text(encoding="utf-8")
    assert "Image.Resampling.LANCZOS" in source
    for forbidden in (".rotate(", ".transform(", "perspective", "inpaint", "outpaint"):
        if forbidden == "perspective":
            assert '"perspective_transform": False' in source
        else:
            assert forbidden not in source.casefold()


def test_background_provider_call_is_exactly_one_and_has_no_reference_images():
    tree = ast.parse(HARNESS_PATH.read_text(encoding="utf-8"))
    calls = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Await) and isinstance(node.value, ast.Call):
            call = node.value
            if isinstance(call.func, ast.Attribute) and call.func.attr == "generate":
                calls.append(call)
    assert len(calls) == 1
    keyword_names = {kw.arg for kw in calls[0].keywords}
    assert "reference_images" not in keyword_names


def test_harness_bypasses_autonomous_pipeline():
    source = HARNESS_PATH.read_text(encoding="utf-8")
    for marker in (
        "run_research(",
        "run_strategy(",
        "run_master_campaign_concept(",
        "run_creative_brief(",
        "run_copy_stage(",
        "augment_with_ai_extraction(",
        "claims_audit.",
        "orchestrator.",
    ):
        assert marker not in source


def test_frozen_copy_exact_unicode():
    comp = _load_module(COMPOSITOR_PATH, "v338_comp_copy")
    assert comp.FROZEN_HEADLINE == "LuLuLun Hydra EX"
    assert comp.FROZEN_SUPPORT == "Máscara facial • 7 folhas"
    assert comp.FROZEN_DETAIL == "150 mL de essência"


def test_master_hash_and_rgba_are_required(tmp_path):
    comp = _load_module(COMPOSITOR_PATH, "v338_comp_validate")
    master = tmp_path / "master.png"
    _make_master(master)
    correct = _sha(master)
    validation = comp.validate_locked_master(master, correct)
    assert validation["mode"] == "RGBA"
    assert validation["alpha_bbox"]
    with pytest.raises(RuntimeError, match="SHA-256 mismatch"):
        comp.validate_locked_master(master, "0" * 64)


def test_fully_opaque_master_is_rejected(tmp_path):
    comp = _load_module(COMPOSITOR_PATH, "v338_comp_opaque")
    master = tmp_path / "opaque.png"
    Image.new("RGBA", (100, 100), (20, 30, 40, 255)).save(master)
    with pytest.raises(RuntimeError, match="transparent alpha"):
        comp.validate_locked_master(master, _sha(master))


def test_locked_product_layer_is_deterministic(tmp_path):
    comp = _load_module(COMPOSITOR_PATH, "v338_comp_deterministic")
    master = tmp_path / "master.png"
    _make_master(master)
    sha = _sha(master)
    first, first_meta = comp.build_locked_product_layer(master, sha)
    second, second_meta = comp.build_locked_product_layer(master, sha)
    first_path = tmp_path / "first.png"
    second_path = tmp_path / "second.png"
    comp.save_png(first, first_path)
    comp.save_png(second, second_path)
    assert _sha(first_path) == _sha(second_path)
    assert first_meta == second_meta
    assert first_meta["rotation_degrees"] == 0
    assert first_meta["perspective_transform"] is False
    assert first_meta["resampling_method"] == "LANCZOS"


def test_locked_layer_remains_immutable_during_composition(tmp_path):
    comp = _load_module(COMPOSITOR_PATH, "v338_comp_immutable")
    master = tmp_path / "master.png"
    _make_master(master)
    layer, _ = comp.build_locked_product_layer(master, _sha(master))
    layer_path = tmp_path / "locked.png"
    comp.save_png(layer, layer_path)
    before = _sha(layer_path)
    background = Image.new("RGBA", (comp.CANVAS_WIDTH, comp.CANVAS_HEIGHT), (60, 30, 90, 255))
    text_layer = Image.new("RGBA", background.size, (0, 0, 0, 0))
    result = comp.compose_layers(
        background=background,
        locked_product_layer=layer,
        text_layer=text_layer,
    )
    assert result.size == background.size
    assert _sha(layer_path) == before


def test_background_prompt_prohibits_product_and_text():
    mod = _load_module(HARNESS_PATH, "v338_harness_prompt")
    prompt = mod._background_prompt().casefold()
    for term in (
        "do not render any product",
        "pouch",
        "package",
        "logo",
        "letters",
        "japanese characters",
        "no intentional text",
    ):
        assert term in prompt


def test_brand_typography_contract_is_exact():
    mod = _load_module(HARNESS_PATH, "v338_harness_typography")
    assert mod.EXPECTED_PRIMARY_FONT_STACK == "Georgia, 'Times New Roman', serif"
    assert mod.EXPECTED_SECONDARY_FONT_STACK == "'Helvetica Neue', Arial, sans-serif"


def test_font_candidates_only_come_from_configured_stack():
    mod = _load_module(HARNESS_PATH, "v338_harness_fonts")
    primary = mod._font_candidates_for_stack(mod.EXPECTED_PRIMARY_FONT_STACK)
    secondary = mod._font_candidates_for_stack(mod.EXPECTED_SECONDARY_FONT_STACK)
    assert "georgia.ttf" in primary
    assert "arial.ttf" in secondary
    assert "comic.ttf" not in primary + secondary


def test_live_execution_requires_separate_authorization(tmp_path, monkeypatch):
    mod = _load_module(HARNESS_PATH, "v338_harness_auth")
    monkeypatch.delenv("BUILD6R_V338_BACKGROUND_SMOKE_AUTHORIZED", raising=False)
    with pytest.raises(RuntimeError, match="not authorized"):
        mod._assert_live_controls(tmp_path / "isolated.db", 0.50)


def test_live_execution_rejects_canonical_database(monkeypatch):
    mod = _load_module(HARNESS_PATH, "v338_harness_canonical")
    monkeypatch.setenv("BUILD6R_V338_BACKGROUND_SMOKE_AUTHORIZED", "TRUE")
    for key, value in {
        "OPENAI_MAX_IMAGE_CALLS": "1",
        "OPENAI_SDK_MAX_RETRIES": "0",
        "OPENAI_REQUEST_TIMEOUT_SECONDS": "180",
        "QA_MAX_RETRIES": "0",
        "QA_BEST_OF_N": "1",
    }.items():
        monkeypatch.setenv(key, value)
    with pytest.raises(RuntimeError, match="canonical SQLite"):
        mod._assert_live_controls(mod.CANONICAL_DB, 0.50)


def test_live_controls_reject_more_than_one_image_call(tmp_path, monkeypatch):
    mod = _load_module(HARNESS_PATH, "v338_harness_controls")
    isolated = tmp_path / "isolated.db"
    isolated.write_bytes(b"x")
    monkeypatch.setenv("BUILD6R_V338_BACKGROUND_SMOKE_AUTHORIZED", "TRUE")
    monkeypatch.setenv("OPENAI_MAX_IMAGE_CALLS", "2")
    monkeypatch.setenv("OPENAI_SDK_MAX_RETRIES", "0")
    monkeypatch.setenv("OPENAI_REQUEST_TIMEOUT_SECONDS", "180")
    monkeypatch.setenv("QA_MAX_RETRIES", "0")
    monkeypatch.setenv("QA_BEST_OF_N", "1")
    with pytest.raises(RuntimeError, match="OPENAI_MAX_IMAGE_CALLS"):
        mod._assert_live_controls(isolated, 0.50)


@pytest.mark.asyncio
async def test_execute_background_calls_provider_once_without_product_refs(tmp_path, monkeypatch):
    mod = _load_module(HARNESS_PATH, "v338_harness_provider")
    db = tmp_path / "isolated.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE settings(key TEXT,value TEXT)")
    conn.commit()
    conn.close()

    calls = []

    class FakeProvider:
        async def generate(self, **kwargs):
            calls.append(kwargs)
            image = Image.new("RGB", (1024, 1536), (70, 45, 110))
            path = tmp_path / "bg.png"
            image.save(path)
            return path.read_bytes()

        def drain_usage_events(self):
            return [{
                "provider": "openai",
                "model": "gpt-image-2.5-sunburst-2026-09-08",
                "input_tokens": 0,
                "output_tokens": 0,
                "image_count": 1,
                "estimated_cost_usd": 0.1,
            }]

        def hard_budget_snapshot(self):
            return {"enabled": True, "spent_usd": 0.1}

    import app.services.ai.openai_provider as provider_module
    monkeypatch.setattr(
        provider_module,
        "openai_provider_from_effective_settings",
        lambda effective, hard_budget_usd: FakeProvider(),
    )

    class Base:
        openai_api_key = "sk-test"
        openai_premium_image_model = "gpt-image-2.5-sunburst-2026-09-08"
        openai_project_id = "proj_test"
        openai_project_hard_limit_attested = True
        openai_max_image_calls = 1

    import app.config
    monkeypatch.setattr(app.config, "get_settings", lambda: Base())

    payload = {
        "background_prompt": "background only",
        "size": "1024x1536",
        "model": "gpt-image-2.5-sunburst-2026-09-08",
        "quality": "xhigh",
    }

    image_bytes, events, budget = await mod._execute_background_once(
        payload=payload,
        database=db,
        max_budget_usd=0.50,
    )

    assert image_bytes
    assert len(calls) == 1
    assert "reference_images" not in calls[0]
    assert sum(int(item["image_count"]) for item in events) == 1
    assert budget["enabled"] is True


def test_usage_validator_rejects_text_tokens():
    mod = _load_module(HARNESS_PATH, "v338_harness_usage_text")
    with pytest.raises(RuntimeError, match="text-model token usage"):
        mod._validate_live_usage([{
            "image_count": 1,
            "input_tokens": 1,
            "output_tokens": 0,
            "estimated_cost_usd": 0.1,
        }])


def test_usage_validator_requires_exactly_one_background_call():
    mod = _load_module(HARNESS_PATH, "v338_harness_usage_count")
    with pytest.raises(RuntimeError, match="exactly one background image call"):
        mod._validate_live_usage([{
            "image_count": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "estimated_cost_usd": 0.0,
        }])