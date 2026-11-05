"""Offline canonical handoff, actual bytes and production-routing contracts."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import zipfile

import pytest

from test_build6r_v101_creative_package import package
from app.services.premium_handoff import assemble_handoff, export_handoff, uses_premium_handoff
from app.services.marketing_claims import bind_handoff


def execution_handoff(tmp_path, *, approved=True, legacy=None):
    from app.schemas.premium_handoff import CreativeExecutionPlan
    from app.services.premium_handoff import prepare_execution_handoff
    from app.services.campaign_creative_strategy import composition_for_purpose
    h = legacy or handoff(tmp_path)
    # Mirror the real approved-reference label, without altering production data.
    h = h.model_copy(update={'assets': tuple(
        a.model_copy(update={'authority': 'owner-approved-target'}) if a.role == 'visual_reference' else a
        for a in h.assets)})
    plans = {}
    for slide in h.slides:
        proposal = composition_for_purpose(slide.slide_role, slide.primary_message)
        plan = CreativeExecutionPlan(
            slide_key=slide.key, brief_sha256=slide.digest(), **proposal,
            product_role='dominant_hero',
            references=tuple(dict(asset_id=a.asset_id, sha256=a.sha256,
                rationale='Use the reference light direction and focal hierarchy, never its product or claims',
                permitted_influences=('lighting', 'hierarchy')) for a in h.assets if a.role == 'visual_reference'),
            camera_relationship='Eye-level camera, full pouch visible and proportional',
            spatial_relationship='Pouch rests on the foreground surface; copy sits beside it without overlap',
            lighting_integration='Shared warm key light and contact shadow on the supporting surface',
            typography_requirements='Reuse approved campaign typefaces and hierarchy; exact copy, no new labels',
            prohibited_imagery=('invented packaging', 'unsupported claims', 'misleading demonstrations', 'physical layer diagrams'))
        if approved:
            plan = plan.model_copy(update={'owner_review_status': 'APPROVED', 'owner_reviewer': 'Test owner',
                'reviewed_content_sha256': plan.content_digest()})
        plans[slide.key] = plan
    return prepare_execution_handoff(h, plans)


def test_legacy_digest_and_serialization_unchanged(tmp_path):
    from app.schemas.premium_handoff import PremiumCreativeHandoff
    h = handoff(tmp_path)
    payload = h.model_dump(mode='json')
    assert all('execution_plan' not in s for s in payload['slides'])
    expected = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':'),
        ensure_ascii=False, allow_nan=False).encode()).hexdigest()
    assert PremiumCreativeHandoff.model_validate(payload).digest() == h.digest() == expected


def test_execution_export_keeps_full_plan_and_separate_approval(tmp_path):
    h = execution_handoff(tmp_path)
    archive = export_handoff(h, tmp_path / 'execution_export')
    with zipfile.ZipFile(archive) as z:
        data = json.loads(z.read('HANNA_CAMPAIGN_HANDOFF.json'))
        assert data['version'] == 2
        assert data['slides'][0]['execution_plan'] == h.slides[0].execution_plan.model_dump(mode='json')
        assert 'execution_plan' in z.read('HANNA_CAMPAIGN_HANDOFF.md').decode()
        assert 'not artwork acceptance' in z.read('CHATGPT_READY_INSTRUCTION.txt').decode()
        for asset, record in zip(h.assets, data['assets']):
            assert z.read(record['file']) == Path(asset.path).read_bytes()


def test_execution_revalidates_reference_bytes_before_export(tmp_path):
    h = execution_handoff(tmp_path)
    reference = next(a for a in h.assets if a.role == 'visual_reference')
    Path(reference.path).write_bytes(b'altered reference')
    target = tmp_path / 'no_export'
    with pytest.raises(ValueError, match='changed'):
        export_handoff(h, target)
    assert not target.exists()


@pytest.mark.parametrize('field', ['visual_mechanism', 'camera_relationship', 'spatial_relationship',
    'lighting_integration', 'typography_requirements', 'composition_rationale'])
def test_incomplete_execution_plan_fails(tmp_path, field):
    from app.schemas.premium_handoff import CreativeExecutionPlan
    plan = execution_handoff(tmp_path).slides[0].execution_plan.model_dump()
    plan[field] = ' '
    with pytest.raises(ValueError):
        CreativeExecutionPlan.model_validate(plan)


@pytest.mark.parametrize('case', ['pending', 'rejected', 'stale', 'wrong_brief', 'wrong_slide',
    'wrong_family', 'reference_hash', 'missing_reference', 'untrusted_reference', 'missing_product',
    'duplicate_reference', 'physical_demo', 'missing_prohibitions', 'blank_reviewer', 'version', 'copy_change', 'claim_transfer'])
def test_execution_failures_rejected_before_export_writes(tmp_path, case):
    h = execution_handoff(tmp_path)
    payload = h.model_dump(mode='json')
    plan = payload['slides'][0]['execution_plan']
    if case == 'pending': plan['owner_review_status'] = 'PENDING'
    elif case == 'rejected': plan['owner_review_status'] = 'REJECTED'
    elif case == 'stale': plan['lighting_integration'] = 'Changed lighting'
    elif case == 'wrong_brief': plan['brief_sha256'] = '0' * 64
    elif case == 'wrong_slide': plan['slide_key'] = 'other'
    elif case == 'wrong_family': plan['composition_family'] = 'ritual_context'
    elif case == 'reference_hash': plan['references'][0]['sha256'] = '0' * 64
    elif case == 'missing_reference': plan['references'] = []
    elif case == 'untrusted_reference':
        next(a for a in payload['assets'] if a['role'] == 'visual_reference')['authority'] = 'unapproved'
    elif case == 'missing_product': payload['slides'][0]['product_asset_ids'] = []
    elif case == 'duplicate_reference': plan['references'].append(plan['references'][0])
    elif case == 'physical_demo': plan['imagery_mode'] = 'application_demonstration'
    elif case == 'missing_prohibitions': plan['prohibited_imagery'] = ['random props']
    elif case == 'blank_reviewer': plan['owner_reviewer'] = ' '
    elif case == 'version': payload['version'] = 3
    elif case == 'copy_change': payload['slides'][0]['approved_copy'][0]['text'] = 'Unsupported stronger copy'
    elif case == 'claim_transfer': plan['references'][0]['permitted_influences'] = ['claims']
    # Re-sign structurally valid but scope-incompatible plans to prove the
    # service checks more than stale approval. This is isolated test authority.
    if case in ('wrong_brief', 'wrong_slide', 'wrong_family', 'reference_hash'):
        from app.schemas.premium_handoff import CreativeExecutionPlan
        pending = CreativeExecutionPlan.model_validate({**plan, 'owner_review_status': 'PENDING'})
        plan['reviewed_content_sha256'] = pending.content_digest()
    from app.schemas.premium_handoff import PremiumExecutionHandoff
    # Construct bypass demonstrates the service boundary also revalidates inputs.
    forged = PremiumExecutionHandoff.model_construct(**payload)
    target = tmp_path / 'must_not_exist'
    with pytest.raises(ValueError):
        export_handoff(forged, target)
    assert not target.exists()


def approved_fixture_library(monkeypatch):
    """Isolated reviewed catalog; never approves the production library."""
    from app.services import marketing_claims
    original = marketing_claims.load_library
    def reviewed(product_id):
        return original(product_id).model_copy(update={"owner_library_review_status": "APPROVED",
            "brazil_market_review_status": "CLEARED", "brazil_clearance_evidence": "Isolated test-only regulatory fixture; no production approval"})
    monkeypatch.setattr(marketing_claims, "load_library", reviewed)


@pytest.fixture(autouse=True)
def reviewed_catalog(monkeypatch):
    approved_fixture_library(monkeypatch)


def handoff(tmp_path, campaign=None):
    campaign = campaign or SimpleNamespace(id="campaign", objective="awareness", angle="Japan skincare", hook="", audience="Brazil")
    first = package(tmp_path, product_id="a5ea2272a1f89d743c089461bb2fb50f", product_name="LuLuLun Hydra EX Mask 7 Sheets")
    second = first.model_copy(update={"slide_id": "slide-2", "slide_role": "cta"})
    return bind_handoff(assemble_handoff(campaign, [(1, first), (2, second)]))


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
