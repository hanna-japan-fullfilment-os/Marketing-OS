"""Offline canonical handoff, actual bytes and production-routing contracts."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import zipfile

import pytest

from test_build6r_v101_creative_package import package
from app.services.premium_handoff import assemble_handoff, export_handoff, uses_premium_handoff


def handoff(tmp_path, campaign=None):
    campaign = campaign or SimpleNamespace(id="campaign", objective="awareness", angle="Japan skincare", hook="", audience="Brazil")
    first = package(tmp_path)
    second = first.model_copy(update={"slide_id": "slide-2", "slide_role": "cta"})
    return assemble_handoff(campaign, [(1, first), (2, second)])


def test_full_campaign_and_individual_briefs_preserve_authority(tmp_path):
    h = handoff(tmp_path)
    assert h.expected_slide_count == 2
    assert [s.slide_number for s in h.slides] == [1, 2]
    assert [s.slide_role for s in h.slides] == ["cover", "cta"]
    for brief in h.slides:
        assert brief.primary_message == "Hidratação"
        assert brief.cta == "Conheça"
        assert brief.facts_allowed_json == h.approved_facts_json
        assert "seven-sheets" in brief.facts_allowed_json
        assert brief.product_asset_ids == ("source",)
        assert brief.reference_asset_ids == ("reference",)
        assert brief.output_size == (120, 150)
        assert {c.key: c.text for c in brief.approved_copy} == {"headline": "Hidratação", "cta": "Conheça"}
        assert brief.visual_intent and brief.required_elements and brief.prohibited_elements
    assert h.creative_source == "external_chatgpt_creative_workflow"
    assert h.production_mode == "EXTERNAL_PREMIUM_HANDOFF"


def test_export_contains_real_assets_manifest_copy_and_instruction(tmp_path):
    h = handoff(tmp_path)
    archive = export_handoff(h, tmp_path / "export")
    with zipfile.ZipFile(archive) as z:
        public = json.loads(z.read("HANNA_CAMPAIGN_HANDOFF.json"))
        manifest = json.loads(z.read("HANNA_CAMPAIGN_ASSETS.json"))
        assert manifest["handoff_sha256"] == h.digest() == public["handoff_sha256"]
        assert {a["role"] for a in manifest["assets"]} == {"product_source", "visual_reference", "logo"}
        for record, original in zip(manifest["assets"], h.assets):
            assert z.read(record["file"]) == Path(original.path).read_bytes()
            assert hashlib.sha256(z.read(record["file"])).hexdigest() == record["sha256"]
            assert record["authority"] and record["provenance_json"]
            assert "path" not in record
        instruction = z.read("CHATGPT_READY_INSTRUCTION.txt").decode()
        assert "CREATE THIS HANNA CAMPAIGN" in instruction
        assert "dashboard/UI" in instruction and "exact" in instruction and "cohesion" in instruction
        md = z.read("HANNA_CAMPAIGN_HANDOFF.md").decode()
        assert "Hidratação" in md and "Slide 2" in md
        assert "text_regions" not in public["slides"][0]
        assert "slide_contract_json" not in public["slides"][0]
    with pytest.raises(FileExistsError):
        export_handoff(h, tmp_path / "export")


def test_changed_asset_fails_before_export_can_be_trusted(tmp_path):
    h = handoff(tmp_path)
    Path(h.assets[0].path).write_bytes(b"changed")
    with pytest.raises(ValueError, match="changed"):
        export_handoff(h, tmp_path / "export")


@pytest.mark.parametrize("case", ["empty", "wrong_campaign", "wrong_product", "duplicate"])
def test_scope_and_slide_order_fail_closed(tmp_path, case):
    p = package(tmp_path)
    c = SimpleNamespace(id="campaign", objective="awareness", angle="", hook="", audience="")
    pairs = [] if case == "empty" else [(1, p)]
    if case == "wrong_campaign":
        pairs = [(1, p.model_copy(update={"campaign_id": "other"}))]
    if case == "wrong_product":
        pairs.append((2, p.model_copy(update={"product_id": "other"})))
    if case == "duplicate":
        pairs.append((1, p))
    with pytest.raises(ValueError):
        assemble_handoff(c, pairs)


def test_hanna_default_and_explicit_other_brand_opt_in():
    class DB:
        def __init__(self, brand): self.brand = brand
        def get(self, *args): return self.brand
    c = SimpleNamespace(brand_id="brand")
    assert uses_premium_handoff(DB(SimpleNamespace(slug="hanna-japan", campaign_rules={})), c)
    assert uses_premium_handoff(DB(SimpleNamespace(slug="other", campaign_rules={"premium_creative_workflow": "external_chatgpt"})), c)
    assert not uses_premium_handoff(DB(SimpleNamespace(slug="other", campaign_rules={})), c)


@pytest.mark.asyncio
async def test_premium_visuals_export_without_touching_renderer_or_image_provider(monkeypatch, tmp_path):
    from app.services import orchestrator, premium_ingestion
    from app.models import Brand
    brand = SimpleNamespace(slug="hanna-japan", campaign_rules={})
    campaign = SimpleNamespace(id="campaign", brand_id="brand")
    calls = []
    class DB:
        def get(self, model, key): return brand if model is Brand else campaign
        def commit(self): calls.append("commit")
    monkeypatch.setattr(premium_ingestion, "prepare_campaign_export", lambda db, c, root: calls.append("export"))
    class Forbidden:
        def __getattr__(self, key): raise AssertionError("Automated creative path touched")
    result = await orchestrator.run_visuals_stage(DB(), campaign_id="campaign", renderer=Forbidden(),
        image_provider=Forbidden(), ai_provider=Forbidden(), config=SimpleNamespace(output_root=str(tmp_path)))
    assert result is campaign and calls == ["export", "commit"]


@pytest.mark.asyncio
async def test_api_legacy_manual_and_qa_routes_block_premium(monkeypatch):
    from app.api import campaigns as api
    from app.services import premium_handoff
    from fastapi import HTTPException
    campaign = SimpleNamespace(id="campaign", brand_id="brand")
    db = SimpleNamespace(get=lambda *args: campaign)
    monkeypatch.setattr(premium_handoff, "uses_premium_handoff", lambda *args: True)
    monkeypatch.setattr(api, "local_routing_enabled", lambda: False)
    with pytest.raises(HTTPException) as exc:
        await api.render_campaign_slide("campaign", SimpleNamespace(use_ai_background=False, recreate_with_ai=False), db=db)
    assert exc.value.status_code == 409
    with pytest.raises(HTTPException) as exc:
        await api.generate_campaign_qa("campaign", use_ai_background=False, db=db)
    assert exc.value.status_code == 409


def test_api_approval_gate_uses_external_readiness(monkeypatch):
    from app.api import campaigns as api
    from app.services import premium_handoff, premium_ingestion
    from fastapi import HTTPException
    monkeypatch.setattr(premium_handoff, "uses_premium_handoff", lambda *args: True)
    def blocked(*args): raise ValueError("all imported slides need approval")
    monkeypatch.setattr(premium_ingestion, "require_publishing_ready", blocked)
    with pytest.raises(HTTPException) as exc:
        api._require_current_creative_qa(None, SimpleNamespace())
    assert exc.value.status_code == 409
