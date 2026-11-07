"""Isolated persisted authority, real evidence services, no providers or approvals.

Archive hash constants are replaced only by fixed fixture archive hashes. The
production owner archives/DB are never read or modified by these tests.
"""
import hashlib
import json
from pathlib import Path

import pytest
from PIL import Image

from app.models import Asset, BrandAsset, Campaign, CampaignSlide, CampaignOutput, ResearchSource, Product
from app.schemas.ai import SlidePlan
from app.schemas.premium_handoff import CanonicalCampaignReconciliation, ReconciliationEvidence
from app.services import canonical_campaign_reconciliation as reconcile
from app.services import marketing_claims, premium_handoff, premium_ingestion, orchestrator
from app.services.hanna_creative_package import image_record
from app.services.creative.pipeline import canonical_slide_claim_bindings


def write_json(path, content):
    raw = json.dumps(content, ensure_ascii=False).encode("utf-8")
    path.write_bytes(raw)
    return ReconciliationEvidence(path=str(path), sha256=hashlib.sha256(raw).hexdigest())


@pytest.fixture
def reconciled(temp_db, tmp_path, monkeypatch):
    from test_build6r_v345_claim_evidence_foundation import _seed, _candidate, _verification
    from test_build6r_product_master_selection import approved_master
    from app.services.claim_evidence import create_claim_candidate, verify_claim_evidence, promote_verified_claim
    db = temp_db.SessionLocal()
    seed = _seed(db)
    library = marketing_claims.load_library(reconcile.PRODUCT_ID)
    seed['product'].name = 'LuLuLun Hydra EX Mask 7 Sheets'
    reviewed = library.model_copy(update={'product_id': seed['product'].id, 'owner_library_review_status': 'APPROVED'})
    monkeypatch.setattr(marketing_claims, 'load_library', lambda key: reviewed if key == seed['product'].id else (_ for _ in ()).throw(ValueError('Wrong product')))
    monkeypatch.setattr(reconcile, 'PRODUCT_ID', seed['product'].id)
    historical = Campaign(id=reconcile.HISTORICAL_CAMPAIGN_ID, display_id='SIX-ACCEPTANCE',
        brand_id=seed['brand'].id, product_id=seed['product'].id, target_slide_count=6,
        status='COPY_READY', notes='Protected isolated historical fixture')
    c = Campaign(display_id='TEN-INDEPENDENT', brand_id=seed['brand'].id, product_id=seed['product'].id,
        target_slide_count=10, objective='education', audience='Approved audience', funnel_stage='consideration',
        languages=['pt-BR'], language='pt-BR', target_platforms=['instagram'], platform_key='instagram_portrait',
        campaign_family='BUILD6R_EXEC0003')
    db.add_all([historical, c]); db.commit()
    for n in range(1,7):
        db.add(CampaignSlide(campaign_id=historical.id,slide_number=n,purpose='historical-fixture',headline='Historical '+str(n)))
    old_output=tmp_path/'six-historical.json';old_output.write_text('{"historical":true}',encoding='utf8')
    db.add(CampaignOutput(campaign_id=historical.id,kind='creative',file_path=str(old_output)))
    db.commit()
    by_id = {v.claim_id: v for v in reviewed.claims}
    evidence = {}; rows = []; source_by_url = {}
    for _, ids in reconcile.PURPOSES:
        for cid in ids:
            claim = by_id[cid]
            if claim.evidence_scope == 'EDITORIAL': continue
            if claim.source_reference not in source_by_url:
                source = ResearchSource(research_run_id=seed['run'].id, url=claim.source_reference,
                    source_title='Isolated manufacturer source', publisher='Manufacturer', source_type='official')
                db.add(source); db.flush(); source_by_url[claim.source_reference] = source
            source = source_by_url[claim.source_reference]
            seed['insight'].source_ids = [s.id for s in source_by_url.values()]
            db.flush()
            candidate = _candidate(seed, claim_text=claim.approved_pt_br_wording['STANDARD']).model_copy(update={'source_ids': [source.id]})
            row = create_claim_candidate(db, candidate)
            verification = _verification(seed).model_copy(update={'source_ids': [source.id]})
            verify_claim_evidence(db, row.id, verification)
            promote_verified_claim(db, row.id)
            evidence[cid] = row.id; rows.append(row)
    db.commit(); db.expire_all()
    def raster(key, color):
        path = tmp_path / (key + '.png'); Image.new('RGB', (120, 150), color).save(path)
        return path, hashlib.sha256(path.read_bytes()).hexdigest()
    source_path, source_sha = raster('source', 'white')
    source = Asset(brand_id=c.brand_id, product_id=c.product_id, absolute_path=str(source_path),
        relative_path='source.png', filename='source.png', extension='.png', sha256=source_sha,
        image_role='product', is_active=True, ai_metadata={'ai_generated': False})
    db.add(source); db.flush()
    master_path, master_sha = raster('master', 'purple')
    metadata = approved_master().ai_metadata
    metadata.update(source_asset_id=source.id, source_sha256=source_sha, campaign_scope_id=c.id)
    master = Asset(brand_id=c.brand_id, product_id=c.product_id, absolute_path=str(master_path),
        relative_path='master.png', filename='master.png', extension='.png', sha256=master_sha,
        image_role='product_master_approved', is_active=True, ai_metadata=metadata)
    db.add(master)
    logo_path, logo_sha = raster('logo', 'black')
    ref_path, ref_sha = raster('reference', 'blue')
    logo = BrandAsset(brand_id=c.brand_id, kind='logo', file_path=str(logo_path), label='campaign:'+c.id+':logo')
    global_logo = BrandAsset(brand_id=c.brand_id, kind='logo', file_path=str(source_path), label='Original logo')
    ref = BrandAsset(brand_id=c.brand_id, kind='visual_reference', file_path=str(ref_path), label='owner-approved-target')
    db.add_all([logo, global_logo, ref]); db.commit(); db.expire_all()
    monkeypatch.setattr(reconcile, 'MASTER_SHA256', master_sha)
    monkeypatch.setattr(reconcile, 'SOURCE_SHA256', source_sha)
    monkeypatch.setattr(reconcile, 'LOGO_SHA256', logo_sha)
    monkeypatch.setattr(reconcile, 'SOURCE_LOGO_SHA256', source_sha)
    monkeypatch.setattr(reconcile, 'REFERENCE_HASHES', frozenset({ref_sha}))
    matrix_slides = []; plans = []
    for n, (purpose, ids) in enumerate(reconcile.PURPOSES, 1):
        words = [by_id[key].approved_pt_br_wording.get('STANDARD', next(iter(by_id[key].approved_pt_br_wording.values()))) for key in ids]
        matrix_slides.append({'SLIDE_NUMBER': n, 'KEY_MESSAGE': words[0], 'EXACT_VISIBLE_COPY': words,
            'VERIFIED_FACTS_USED': [{'claim_id': key} for key in ids], 'VISUAL_STORY':'Approved isolated composition',
            **({'PRODUCT_IDENTITY_COPY': seed['product'].name} if n in (1, 10) else {})})
        selected_ids = [evidence[key] for key in ids if key in evidence]
        # Visible fields preserve reading order; the third fact is not a CTA.
        p = SlidePlan(slide_number=n, slide_id='ten-'+str(n), purpose=purpose,
            headline=words[0], body=words[1] if len(words)>1 else '', callout_value=words[2] if len(words)>2 else '',
            visual_brief='Approved isolated composition', selection_rationale='Exact canonical fixture provenance',
            verified_claim_ids=selected_ids, evidence_references=[orchestrator._claim_reference(db, key, c.product_id) for key in selected_ids],
            product_asset=orchestrator._asset_reference(master), reference_asset_ids=[ref.id],
            reference_assets=[orchestrator._asset_reference(ref, reference=True)])
        p = p.model_copy(update={'claim_bindings': canonical_slide_claim_bindings(p)})
        plans.append(p)
    arch = write_json(tmp_path/'matrix.json', {'objective':'education', 'funnel_stage':'consideration',
        'audience':'Approved audience', 'slides':matrix_slides})
    approval = write_json(tmp_path/'approval.json', {'OWNER_ARCHITECTURE_DECISION':'APPROVED',
        'approved_deliverables':[{'file':'matrix.json','sha256':arch.sha256}]})
    frozen = {}
    for n in range(1, 7):
        path, sha = raster('frozen'+str(n), (n, n, n)); frozen[str(path)] = sha
    freeze = write_json(tmp_path/'freeze.json', {'SLIDES_1_6_FROZEN':True,'canonical_files':frozen})
    monkeypatch.setattr(reconcile, 'ARCHITECTURE_SHA256', arch.sha256)
    monkeypatch.setattr(reconcile, 'APPROVAL_SHA256', approval.sha256)
    monkeypatch.setattr(reconcile, 'FREEZE_SHA256', freeze.sha256)
    creative_path = tmp_path/'creative.json'
    creative = write_json(creative_path, {'carousel_plan':{'slides':[p.model_dump(mode='json') for p in plans]}})
    manifest = CanonicalCampaignReconciliation(campaign_id=c.id, product_id=c.product_id,
        architecture=arch, architecture_approval=approval, freeze=freeze, creative_sha256=creative.sha256,
        evidence_ids=evidence, master_asset_id=master.id,
        logo=image_record(asset_id=logo.id, role='logo', path=logo_path, expected_sha256=logo_sha,
            authority='Canonical campaign logo', provenance={'campaign_id':c.id,
                'source_asset_id':global_logo.id, 'source_sha256':source_sha}),
        references=(image_record(asset_id=ref.id, role='visual_reference', path=ref_path, expected_sha256=ref_sha,
            authority=ref.label, provenance={'approval':'isolated owner reference'}),))
    manifest_path = tmp_path/(manifest.digest()+'.json'); manifest_path.write_text(manifest.model_dump_json(), encoding='utf8')
    db.add_all([CampaignOutput(campaign_id=c.id, kind='creative', file_path=str(creative_path)),
        CampaignOutput(campaign_id=c.id, kind='campaign_reconciliation',file_path=str(manifest_path))]); db.commit()
    yield dict(db=db, campaign=c, historical=historical, manifest=manifest, plans=plans, rows=rows,
        creative_path=creative_path, manifest_path=manifest_path, master=master, source=source, library=reviewed,
        frozen=frozen, global_logo=global_logo, tmp=tmp_path)
    db.close()


def selected_scope(f, *, approved=False):
    from app.schemas.premium_handoff import CreativeExecutionPlan, ExecutionReference
    h = premium_handoff.build_campaign_handoff(f['db'], f['campaign'])
    assets = {a.asset_id:a for a in h.assets}; plans={}
    for slide in h.slides[6:8]:
        p = CreativeExecutionPlan(slide_key=slide.key, brief_sha256=slide.digest(),
            communication_objective=slide.primary_message, visual_mechanism='Exact factual guidance in integrated ritual scene',
            product_role='contextual_hero', composition_family='ritual_context', composition_rationale='Purpose-specific factual routine',
            references=tuple(ExecutionReference(asset_id=key, sha256=assets[key].sha256, rationale='Approved light and hierarchy',
                permitted_influences=('lighting','hierarchy')) for key in slide.reference_asset_ids),
            camera_relationship='Eye-level pouch on supporting surface', spatial_relationship='Copy follows pouch placement',
            lighting_integration='Shared soft key and grounded contact shadow', typography_requirements='Exact copy and approved hierarchy',
            prohibited_imagery=('invented packaging','unsupported claims','misleading demonstrations'))
        if approved:
            p=p.model_copy(update={'owner_review_status':'APPROVED','owner_reviewer':'Isolated owner', 'reviewed_content_sha256':p.content_digest()})
        plans[slide.key]=p
    scope=premium_handoff.prepare_production_scope(f['db'],f['campaign'],plans)
    if approved:
        scope=scope.model_copy(update={'owner_review_status':'APPROVED','owner_reviewer':'Isolated owner',
            'reviewed_content_sha256':scope.content_digest()})
    return scope


def test_separate_identity_complete_authority_and_pending_preparation(reconciled):
    f=reconciled; db=f['db']; old=f['historical']; before={col.name:getattr(old,col.name) for col in old.__table__.columns}
    report=reconcile.prepare_campaign(db,f['campaign'],f['manifest'],f['creative_path'].read_bytes())
    h=premium_handoff.build_campaign_handoff(db,f['campaign'])
    assert report['status']=='PENDING_OWNER_REVIEW' and report['slide_count']==10
    assert report['campaign_record']['id']!=old.id
    assert report['campaign_record']['human_review_status']=='PENDING' and report['campaign_record']['approved_at'] is None
    assert len(report['slide_records'])==10 and all(not p['rendered_asset_path'] for p in report['slide_records'])
    assert h.campaign_id != old.id and h.expected_slide_count==10
    assert sum(len(s.approved_claim_ids) for s in h.slides)==16
    assert all(not s.benefit_hierarchy for i,s in enumerate(h.slides) if i not in (1,4))
    assert h.slides[1].mandatory_qualifiers['ex-radiance']=='causada pelo ressecamento'
    assert [x.text for x in h.slides[0].approved_copy if x.key=='product_identity']==['LuLuLun Hydra EX Mask 7 Sheets']
    assert before=={col.name:getattr(old,col.name) for col in old.__table__.columns}
    assert not db.new and not db.dirty
    assert db.query(Campaign).count()==2
    assert db.query(CampaignSlide).filter_by(campaign_id=old.id).count()==6
    assert json.loads((f['tmp']/'six-historical.json').read_bytes())=={'historical':True}
    prepared=reconcile.prepare_slide_plans(db,f['campaign'],f['manifest'])
    assert len(prepared)==10 and prepared[4].cta==''
    assert prepared[4].callout_value=='Tecido com estrutura em três camadas.'
    raw=json.dumps({'carousel_plan':{'slides':[p.model_dump(mode='json') for p in prepared]}},ensure_ascii=False).encode('utf8')
    bound=f['manifest'].model_copy(update={'creative_sha256':hashlib.sha256(raw).hexdigest()})
    assert reconcile.prepare_campaign(db,f['campaign'],bound,raw)['status']=='PENDING_OWNER_REVIEW'


@pytest.mark.parametrize('case',['purpose','claim','missing','extra','wrong_product','rebound','source','pending','revoked','library_changed','missing_manifest','frozen_bytes'])
def test_current_authority_attacks_fail_before_output(reconciled,case,monkeypatch):
    f=reconciled; db=f['db']; c=f['campaign']; h=selected_scope(f,approved=True)
    if case in ('purpose','claim','missing','extra','rebound'):
        payload=json.loads(f['creative_path'].read_bytes()); slides=payload['carousel_plan']['slides']
        if case=='purpose': slides[2]['purpose']='hydration'
        elif case=='claim': slides[2]['verified_claim_ids']=[f['rows'][0].id]
        elif case=='missing': slides.pop()
        elif case=='extra': slides.append(slides[-1])
        else: slides[2]['headline']='Invented claim'
        changed=write_json(f['creative_path'],payload)
        # Rebound both file and manifest digests still cannot create copy/purpose authority.
        manifest=f['manifest'].model_copy(update={'creative_sha256':changed.sha256})
        path=f['tmp']/(manifest.digest()+'.json');path.write_text(manifest.model_dump_json(),encoding='utf8')
        row=db.query(CampaignOutput).filter_by(campaign_id=c.id,kind='campaign_reconciliation').one();row.file_path=str(path)
    elif case=='wrong_product': c.product_id=f['historical'].brand_id
    elif case=='source': f['rows'][0].source_ids=[f['rows'][2].source_ids[0]]
    elif case=='revoked': f['rows'][0].status='rejected'
    elif case=='pending': monkeypatch.setattr(marketing_claims,'load_library',lambda _:f['library'].model_copy(update={'owner_library_review_status':'PENDING'}))
    elif case=='library_changed': monkeypatch.setattr(marketing_claims,'load_library',lambda _:f['library'].model_copy(update={'reviewed_by':'Changed reviewed authority'}))
    elif case=='missing_manifest': db.delete(db.query(CampaignOutput).filter_by(campaign_id=c.id,kind='campaign_reconciliation').one())
    else: Path(next(iter(f['frozen']))).write_bytes(b'changed')
    if case!='wrong_product': db.commit()
    target=f['tmp']/'must_not_write'
    with pytest.raises((ValueError,OSError)):
        premium_handoff.export_handoff(h,target,db=db,campaign=c)
    assert not target.exists()


def test_selected_export_excludes_frozen_art_and_full_export_fails(reconciled):
    import zipfile
    f=reconciled; scope=selected_scope(f,approved=True)
    with pytest.raises(ValueError,match='selected production-scope'):
        premium_handoff.export_handoff(scope.canonical_handoff,f['tmp']/'full',db=f['db'],campaign=f['campaign'])
    archive=premium_handoff.export_handoff(scope,f['tmp']/'selected',db=f['db'],campaign=f['campaign'])
    with zipfile.ZipFile(archive) as z:
        data=json.loads(z.read('HANNA_CAMPAIGN_HANDOFF.json'))
        assert [s['slide_number'] for s in data['slides']]==[7,8]
        assert data['production_scope']['historical_approvals_adopted'] is False
        assert 'SELECTED OUTPUT ONLY' in z.read('CHATGPT_READY_INSTRUCTION.txt').decode()
        frozen_bytes=[Path(path).read_bytes() for path in f['frozen']]
        assert all(z.read(name) not in frozen_bytes for name in z.namelist())
    assert not (f['tmp']/'full').exists()


@pytest.mark.parametrize('case',['frozen','deferred','missing','additional','plan','approval','scope_approval'])
def test_scope_widening_and_owner_boundary_fail_closed(reconciled,case):
    f=reconciled;scope=selected_scope(f,approved=True);d=dict(scope.dispositions);p=dict(scope.execution_plans)
    keys=list(d)
    if case=='frozen': d[keys[0]]='SELECTED_PENDING_OWNER_REVIEW'
    elif case=='deferred': d[keys[9]]='SELECTED_PENDING_OWNER_REVIEW'
    elif case=='missing': d.pop(keys[0])
    elif case=='additional': d['extra']='DEFERRED_UNRENDERED'
    elif case=='plan': p[keys[0]]=next(iter(p.values()))
    elif case=='approval': p[keys[6]]=p[keys[6]].model_copy(update={'lighting_integration':'Changed light'})
    else: scope=scope.model_copy(update={'owner_review_status':'PENDING'})
    scope=scope.model_copy(update={'dispositions':d,'execution_plans':p})
    with pytest.raises(ValueError): premium_handoff.export_handoff(scope,f['tmp']/'denied',db=f['db'],campaign=f['campaign'])
    assert not (f['tmp']/'denied').exists()


@pytest.mark.parametrize('operation',['import','review','revision'])
@pytest.mark.parametrize('number',[1,6,9,10])
def test_frozen_deferred_intake_rejected_before_state_read(reconciled,monkeypatch,operation,number):
    from types import SimpleNamespace
    f=reconciled;scope=selected_scope(f,approved=True);key=scope.canonical_handoff.slides[number-1].key
    def forbidden(*a,**k): raise AssertionError('Protected slide reached workflow state')
    monkeypatch.setattr(premium_ingestion,'_read_state',forbidden)
    actions={
        'import':lambda:premium_ingestion.import_slide(f['db'],f['campaign'],f['tmp']/'out',slide_key=key,filename='x.png',data=b'x',expected_version=0,handoff=scope),
        'review':lambda:premium_ingestion.review_slide(f['db'],f['campaign'],f['tmp']/'out',SimpleNamespace(slide_key=key),handoff=scope),
        'revision':lambda:premium_ingestion.export_revision(f['db'],f['campaign'],f['tmp']/'out',key,handoff=scope)}
    with pytest.raises(ValueError,match='outside selected'):actions[operation]()
    assert not (f['tmp']/'out').exists()


def test_application_boundary_is_disabled_before_any_write(reconciled,monkeypatch):
    f=reconciled
    def forbidden(*a,**k):raise AssertionError('Phase 1 reached canonical writes')
    monkeypatch.setattr(f['db'],'flush',forbidden)
    with pytest.raises(ValueError,match='disabled in Phase 1'):
        reconcile.apply_campaign(f['db'],f['campaign'],f['manifest'],f['creative_path'].read_bytes(),f['tmp']/'out',owner_authorization=True)
    assert not (f['tmp']/'out').exists()


def test_global_master_and_logo_selection_unchanged(reconciled):
    from app.services.product_asset_selection import select_render_assets
    f=reconciled
    selected=select_render_assets(f['db'],brand_id=f['campaign'].brand_id,product_id=f['campaign'].product_id,category_id=None,limit=1)
    assert selected==[f['source']]
    assert orchestrator.resolve_brand_logo_path(f['db'],f['campaign'].brand_id)==Path(f['global_logo'].file_path)


@pytest.mark.parametrize('case',['master_bytes','master_scope','master_review','reference_bytes','reference_approval','logo_bytes','logo_scope','original_logo','identity','qualifier','evidence_missing','evidence_extra'])
def test_asset_identity_and_binding_attacks(reconciled,case):
    f=reconciled;db=f['db'];scope=selected_scope(f,approved=True)
    if case=='master_bytes': Path(f['master'].absolute_path).write_bytes(b'changed')
    elif case=='master_scope':f['master'].ai_metadata={**f['master'].ai_metadata,'campaign_scope_id':f['historical'].id}
    elif case=='master_review':f['master'].ai_metadata={**f['master'].ai_metadata,'human_review':{'status':'PENDING'}}
    elif case=='reference_bytes':Path(f['manifest'].references[0].path).write_bytes(b'changed')
    elif case=='reference_approval':db.get(BrandAsset,f['manifest'].references[0].asset_id).label='unapproved'
    elif case=='logo_bytes':Path(f['manifest'].logo.path).write_bytes(b'changed')
    elif case=='logo_scope':db.get(BrandAsset,f['manifest'].logo.asset_id).label='campaign:another:logo'
    elif case=='original_logo':Path(f['global_logo'].file_path).write_bytes(b'changed')
    elif case=='identity':db.get(Product,f['campaign'].product_id).name='Another variant'
    else:
        if case=='qualifier':
            content=json.loads(f['creative_path'].read_bytes());content['carousel_plan']['slides'][1]['body']='Ajuda a prevenir a aparência opaca.'
            write_json(f['creative_path'],content)
        else:
            mapping=dict(f['manifest'].evidence_ids)
            if case=='evidence_missing':mapping.pop('ex-apply')
            else:mapping['unknown-claim']=f['rows'][0].id
            changed=f['manifest'].model_copy(update={'evidence_ids':mapping})
            path=f['tmp']/(changed.digest()+'.json');path.write_text(changed.model_dump_json(),encoding='utf8')
            db.query(CampaignOutput).filter_by(campaign_id=f['campaign'].id,kind='campaign_reconciliation').one().file_path=str(path)
    db.commit()
    with pytest.raises((ValueError,OSError)):
        premium_handoff.export_handoff(scope,f['tmp']/'denied',db=db,campaign=f['campaign'])
    assert not (f['tmp']/'denied').exists()


def test_selected_intake_review_is_independent_and_never_campaign_ready(reconciled):
    import io
    from app.schemas.premium_handoff import PremiumReviewRequest
    f=reconciled;db=f['db'];c=f['campaign'];scope=selected_scope(f,approved=True);root=f['tmp']/'intake'
    premium_ingestion.prepare_campaign_export(db,c,root,handoff=scope);db.commit()
    for slide,color in zip(scope.slides,['red','green']):
        before=premium_ingestion.readiness(db,c,handoff=scope)
        stream=io.BytesIO();Image.new('RGB',slide.output_size,color).save(stream,format='PNG')
        result=premium_ingestion.import_slide(db,c,root,slide_key=slide.key,filename='candidate.png',data=stream.getvalue(),expected_version=before['version'],handoff=scope);db.commit()
        assert result['slides'][slide.key]['approval_status']=='PENDING_REVIEW'
        req=PremiumReviewRequest(expected_version=result['version'],slide_key=slide.key,decision='APPROVED',reviewer='Isolated human review',
            product_visible=True,product_fidelity_confirmed=True,observed_copy={v.key:v.text for v in slide.approved_copy})
        premium_ingestion.review_slide(db,c,root,req,handoff=scope);db.commit()
    final=premium_ingestion.readiness(db,c,handoff=scope)
    assert final['SELECTED_RELEASE_COMPLETE'] and not final['CAMPAIGN_CREATIVE_COMPLETE']
    assert final['APPROVED_SLIDE_COUNT']==2 and final['CANONICAL_CAMPAIGN_SLIDE_COUNT']==10
    assert final['status']=='SELECTED_RELEASE_COMPLETE' and not final['HISTORICAL_APPROVALS_ADOPTED']
    assert c.approved_at is None and c.human_review_status=='PENDING'
    with pytest.raises(ValueError):premium_ingestion.require_publishing_ready(db,c)


@pytest.mark.parametrize('case',['purpose','claim_id','copy','identity'])
def test_rebound_supplied_historical_handoff_cannot_create_authority(reconciled,case):
    f=reconciled;scope=selected_scope(f,approved=True);base=scope.canonical_handoff
    slides=list(base.slides);target=slides[2]
    if case=='purpose':target=target.model_copy(update={'slide_role':'hydration'})
    elif case=='claim_id':target=target.model_copy(update={'approved_claim_ids':{'headline':'unknown'}})
    elif case=='copy':target=target.model_copy(update={'approved_copy':(target.approved_copy[0].model_copy(update={'text':'Invented benefit'}),)})
    else:
        target=slides[0];copy=tuple(v.model_copy(update={'text':'Another product'}) if v.key=='product_identity' else v for v in target.approved_copy)
        slides[0]=target.model_copy(update={'approved_copy':copy})
    if case!='identity':slides[2]=target
    scope=scope.model_copy(update={'canonical_handoff':base.model_copy(update={'slides':tuple(slides)})})
    scope=scope.model_copy(update={'reviewed_content_sha256':scope.content_digest()})
    with pytest.raises(ValueError):premium_handoff.export_handoff(scope,f['tmp']/'forged',db=f['db'],campaign=f['campaign'])
    assert not (f['tmp']/'forged').exists()


@pytest.mark.parametrize('operation',['export','import','review','readiness','revision'])
def test_scoped_cross_session_revocation_precedes_state_and_writes(reconciled,monkeypatch,operation):
    from sqlalchemy.orm import sessionmaker
    from app.models import ProductClaimEvidence
    f=reconciled;scope=selected_scope(f,approved=True);db=f['db'];c=f['campaign'];key=scope.slides[0].key
    other=sessionmaker(bind=db.get_bind())()
    try:
        row=other.get(ProductClaimEvidence,f['rows'][0].id);row.marketing_eligible=False;other.commit()
    finally:other.close()
    assert f['rows'][0].marketing_eligible
    def forbidden(*a,**k):raise AssertionError('Stale scoped authority reached workflow state/write')
    monkeypatch.setattr(premium_ingestion,'_read_state',forbidden)
    monkeypatch.setattr(db,'flush',forbidden)
    root=f['tmp']/'stale'
    actions={
        'export':lambda:premium_ingestion.prepare_campaign_export(db,c,root,handoff=scope),
        'import':lambda:premium_ingestion.import_slide(db,c,root,slide_key=key,filename='x.png',data=b'x',expected_version=0,handoff=scope),
        'review':lambda:premium_ingestion.review_slide(db,c,root,None,handoff=scope),
        'readiness':lambda:premium_ingestion.readiness(db,c,handoff=scope),
        'revision':lambda:premium_ingestion.export_revision(db,c,root,key,handoff=scope)}
    with pytest.raises(ValueError,match='current canonical marketing evidence'):actions[operation]()
    assert not root.exists()
