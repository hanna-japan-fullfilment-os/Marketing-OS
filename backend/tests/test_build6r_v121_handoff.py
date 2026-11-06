"""Offline canonical handoff, actual bytes and production-routing contracts."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import zipfile

import pytest

from test_build6r_v101_creative_package import package
from app.services.premium_handoff import assemble_handoff, export_handoff as production_export, uses_premium_handoff
from app.services.marketing_claims import bind_handoff
from app.services.premium_handoff import resolve_canonical_handoff as real_canonical_resolver


# Unit fixtures model the independent persisted-campaign read boundary.
CANONICAL_FIXTURES = {}


def install_fixture_authority(monkeypatch):
    from app.services import premium_handoff
    CANONICAL_FIXTURES.clear()
    def current(db, campaign):
        if campaign.id not in CANONICAL_FIXTURES:
            raise ValueError('Missing isolated canonical campaign')
        return CANONICAL_FIXTURES[campaign.id]
    monkeypatch.setattr(premium_handoff, 'resolve_canonical_handoff', current)


def register_fixture(h):
    CANONICAL_FIXTURES[h.campaign_id] = h
    return h


def export_handoff(h, directory, **kwargs):
    return production_export(h, directory, db=object(),
                             campaign=SimpleNamespace(id=h.campaign_id), **kwargs)


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
    install_fixture_authority(monkeypatch)
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
    first = first.model_copy(update={'images': tuple(a.model_copy(update={'authority': 'owner-approved-target'})
        if a.role == 'visual_reference' else a for a in first.images)})
    second = first.model_copy(update={"slide_id": "slide-2", "slide_role": "cta"})
    return bind_handoff(register_fixture(assemble_handoff(campaign, [(1, first), (2, second)])))


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


@pytest.mark.parametrize('version', [1, 2])
@pytest.mark.parametrize('case', ['unknown', 'wrong', 'missing', 'additional', 'role', 'asset'])
def test_exec0002_rebound_handoff_cannot_create_claim_authority(tmp_path, version, case):
    from app.schemas.premium_handoff import PremiumSlideBrief, CreativeExecutionPlan
    legacy = handoff(tmp_path)
    h = execution_handoff(tmp_path, legacy=legacy) if version == 2 else legacy
    b = h.slides[0]
    ids = dict(b.approved_claim_ids)
    updates = {}
    if case == 'unknown': ids['headline'] = 'UNVERIFIED'
    elif case == 'wrong': ids['headline'] = 'ex-after'
    elif case == 'missing': ids.pop('headline')
    elif case == 'additional': ids['extra'] = 'ex-after'
    elif case == 'role': updates['slide_role'] = 'application'
    updates['approved_claim_ids'] = ids
    altered = b.model_copy(update=updates)
    if version == 2:
        base = PremiumSlideBrief.model_validate(altered.model_dump(exclude={'execution_plan'}))
        p = altered.execution_plan.model_copy(update={'brief_sha256': base.digest(),
            'composition_family': 'ritual_context' if case == 'role' else altered.execution_plan.composition_family,
            'owner_review_status': 'PENDING'})
        p = CreativeExecutionPlan.model_validate(p.model_dump())
        p = p.model_copy(update={'owner_review_status': 'APPROVED', 'reviewed_content_sha256': p.content_digest()})
        altered = altered.model_copy(update={'execution_plan': p})
    forged = h.model_copy(update={'slides': (altered, *h.slides[1:])})
    if case == 'asset':
        forged = forged.model_copy(update={'assets': tuple(a.model_copy(update={'authority': 'Forged product authority'})
            if a.role == 'product_source' else a for a in forged.assets)})
    target = tmp_path / 'forbidden_export'
    with pytest.raises(ValueError): export_handoff(forged, target)
    assert not target.exists()


def test_exec0002_context_free_production_export_fails_closed(tmp_path):
    h = handoff(tmp_path)
    target = tmp_path / 'context_free'
    with pytest.raises(ValueError, match='canonical campaign context'):
        production_export(h, target)
    assert not target.exists()


@pytest.fixture
def live_factual_campaign(temp_db, tmp_path, monkeypatch):
    """Real persisted plans and real DB evidence; no provenance mocks."""
    from test_build6r_v345_claim_evidence_foundation import _seed, _candidate, _verification
    from app.models import Asset, BrandAsset, Campaign, CampaignOutput
    from app.schemas.ai import SlidePlan
    from app.services import marketing_claims, premium_handoff, orchestrator
    from app.services.claim_evidence import create_claim_candidate, verify_claim_evidence, promote_verified_claim
    from app.services.creative.pipeline import canonical_slide_claim_bindings
    db = temp_db.SessionLocal()
    seeded = _seed(db)
    library = marketing_claims.load_library('a5ea2272a1f89d743c089461bb2fb50f')
    isolated_library = library.model_copy(update={'product_id': seeded['product'].id})
    monkeypatch.setattr(marketing_claims, 'load_library', lambda key: isolated_library if key == isolated_library.product_id else (_ for _ in ()).throw(ValueError('Wrong product')))
    monkeypatch.setattr(premium_handoff, 'resolve_canonical_handoff', real_canonical_resolver)
    assets = {a.asset_id: a for a in package(tmp_path).images}
    source = assets['source']
    asset = Asset(brand_id=seeded['brand'].id, product_id=seeded['product'].id,
        absolute_path=source.path, relative_path='source.png', filename='source.png', extension='.png',
        sha256=source.sha256, image_role='product', is_active=True)
    db.add(asset)
    for key, kind in [('reference', 'visual_reference'), ('logo', 'logo')]:
        db.add(BrandAsset(brand_id=seeded['brand'].id, kind=kind, file_path=assets[key].path,
                          label='owner-approved-target' if kind == 'visual_reference' else 'canonical logo'))
    c = Campaign(brand_id=seeded['brand'].id, product_id=seeded['product'].id,
        display_id='EXEC0002-FACTUAL', objective='education', language='pt-BR',
        target_slide_count=2, platform_key='instagram_portrait')
    db.add(c); db.commit()
    reference = db.query(BrandAsset).filter_by(brand_id=seeded['brand'].id, kind='visual_reference').one()
    plans = []; rows = []
    for number, role, cid in [(1, 'application', 'ex-apply'), (2, 'routine_aftercare', 'ex-after')]:
        claim = next(x for x in library.claims if x.claim_id == cid)
        words = claim.approved_pt_br_wording['STANDARD']
        row = create_claim_candidate(db, _candidate(seeded, claim_text=words))
        verify_claim_evidence(db, row.id, _verification(seeded))
        promote_verified_claim(db, row.id); db.commit()
        # Build persisted snapshots from SQLite's loaded representation, as a
        # later campaign request does (not transient timezone-aware ORM values).
        db.expire_all()
        p = SlidePlan(slide_number=number, purpose=role, headline=words, visual_brief='Factual routine guidance',
            slide_id=f'factual-{number}', verified_claim_ids=[row.id],
            evidence_references=[orchestrator._claim_reference(db, row.id, c.product_id)],
            product_asset=orchestrator._asset_reference(asset), selection_rationale='Exact isolated product',
            reference_asset_ids=[reference.id],
            reference_assets=[orchestrator._asset_reference(reference, reference=True)],
            disclaimer=orchestrator._current_brand_disclaimer(db, c))
        p = p.model_copy(update={'claim_bindings': canonical_slide_claim_bindings(p)})
        plans.append(p); rows.append(row)
    path = tmp_path / 'canonical_creative.json'
    path.write_text(json.dumps({'carousel_plan': {'slides': [p.model_dump() for p in plans]}}, ensure_ascii=False), encoding='utf-8')
    db.add(CampaignOutput(campaign_id=c.id, kind='creative', file_path=str(path)))
    db.commit()
    yield db, c, rows, path
    db.close()


@pytest.mark.parametrize('version', [1, 2])
def test_exec0002_real_canonical_application_aftercare_and_forged_role(live_factual_campaign, tmp_path, version):
    from app.services import premium_handoff, marketing_claims
    db, c, rows, path = live_factual_campaign
    h = premium_handoff.build_campaign_handoff(db, c)
    if version == 2:
        h = execution_handoff(tmp_path, legacy=h)
    assert [s.approved_claim_ids for s in h.slides] == [{'headline': 'ex-apply'}, {'headline': 'ex-after'}]
    assert all(s.benefit_hierarchy == () for s in h.slides)
    marketing_claims.require_ready(h, db=db, campaign=c)
    archive = production_export(h, tmp_path / 'real_factual_export', db=db, campaign=c)
    with zipfile.ZipFile(archive) as bundle:
        exported = json.loads(bundle.read('HANNA_CAMPAIGN_HANDOFF.json'))
        assert exported['version'] == version
        assert [s['approved_copy'] for s in exported['slides']] == [s.model_dump(mode='json')['approved_copy'] for s in h.slides]
    swapped = h.model_copy(update={'slides': (h.slides[0].model_copy(update={'slide_role': 'routine_aftercare'}), h.slides[1])})
    with pytest.raises(ValueError, match='canonical purpose'):
        marketing_claims.require_ready(swapped, db=db, campaign=c)


@pytest.mark.parametrize('case', ['revoked', 'ineligible', 'expired', 'source', 'snapshot', 'purpose', 'missing_plan'])
def test_exec0002_live_evidence_changes_block_export_before_writes(live_factual_campaign, tmp_path, case):
    from datetime import datetime, timezone, timedelta
    from app.services import premium_handoff
    db, c, rows, path = live_factual_campaign
    h = premium_handoff.build_campaign_handoff(db, c)
    row = rows[0]
    if case == 'revoked': row.status = 'rejected'
    elif case == 'ineligible': row.marketing_eligible = False
    elif case == 'expired': row.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
    elif case == 'source': row.source_ids = ['missing-source']
    elif case == 'snapshot': row.source_excerpt = 'Changed evidence excerpt'
    elif case == 'missing_plan': path.unlink()
    else:
        content = json.loads(path.read_text(encoding='utf-8'))
        content['carousel_plan']['slides'][0]['purpose'] = 'cover'
        path.write_text(json.dumps(content, ensure_ascii=False), encoding='utf-8')
    db.commit()
    target = tmp_path / 'must_not_write'
    with pytest.raises((ValueError, OSError)):
        production_export(h, target, db=db, campaign=c)
    assert not target.exists()


@pytest.mark.parametrize('operation', ['export', 'import', 'review', 'readiness', 'revision'])
@pytest.mark.parametrize('authority', ['revoked', 'dirty_session'])
def test_exec0002_live_consumers_reject_before_state_read_or_flush(live_factual_campaign, tmp_path,
                                                                 monkeypatch, operation, authority):
    from app.services import premium_handoff, premium_ingestion
    db, c, rows, path = live_factual_campaign
    h = premium_handoff.build_campaign_handoff(db, c)
    rows[0].marketing_eligible = False
    if authority == 'revoked': db.commit()
    def forbidden(*args, **kwargs): raise AssertionError('Invalid authority reached state read/write or flush')
    monkeypatch.setattr(premium_ingestion, '_read_state', forbidden)
    monkeypatch.setattr(db, 'flush', forbidden)
    actions = {
        'export': lambda: premium_ingestion.prepare_campaign_export(db, c, tmp_path/'out', handoff=h),
        'import': lambda: premium_ingestion.import_slide(db, c, tmp_path/'out', slide_key=h.slides[0].key,
            filename='unused.png', data=b'unused', expected_version=0, handoff=h),
        'review': lambda: premium_ingestion.review_slide(db, c, tmp_path/'out', None, handoff=h),
        'readiness': lambda: premium_ingestion.readiness(db, c, handoff=h),
        'revision': lambda: premium_ingestion.export_revision(db, c, tmp_path/'out', h.slides[0].key, handoff=h),
    }
    with pytest.raises(ValueError): actions[operation]()
    assert not (tmp_path/'out').exists()
    db.rollback()


def test_exec0002_separate_session_revocation_is_not_hidden_by_identity_map(live_factual_campaign):
    from sqlalchemy.orm import sessionmaker
    from app.models import ProductClaimEvidence
    from app.services import premium_handoff, marketing_claims
    db, c, rows, path = live_factual_campaign
    h = premium_handoff.build_campaign_handoff(db, c)
    row = rows[0]
    assert row.marketing_eligible
    other = sessionmaker(bind=db.get_bind())()
    try:
        current = other.get(ProductClaimEvidence, row.id)
        current.marketing_eligible = False
        other.commit()
    finally:
        other.close()
    assert row.marketing_eligible  # Cached historical evidence, before the gate.
    with pytest.raises(ValueError, match='current canonical marketing evidence'):
        marketing_claims.require_ready(h, db=db, campaign=c)
