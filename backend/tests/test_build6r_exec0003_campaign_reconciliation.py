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
    product_id = seed['product'].id  # Immutable fixture identity; never share an ORM loader across worker Sessions.
    reviewed = library.model_copy(update={'product_id': product_id, 'owner_library_review_status': 'APPROVED'})
    monkeypatch.setattr(marketing_claims, 'load_library', lambda key: reviewed if key == product_id else (_ for _ in ()).throw(ValueError('Wrong product')))
    monkeypatch.setattr(reconcile, 'PRODUCT_ID', product_id)
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


@pytest.fixture
def application(reconciled):
    """Synthetic approved prerequisites; application itself adds only 13 rows.

    Authorization is seeded independently in the existing audit table. No helper
    in the production adapter creates approvals or evidence.
    """
    from datetime import datetime, timedelta, timezone
    from app.models import AuditEvent
    f = reconciled; db = f['db']; c = f['campaign']
    values = {column.name:getattr(c,column.name) for column in c.__table__.columns}
    db.delete(c); db.commit()
    f['campaign'] = Campaign(**values)
    source = f['source']; master = f['master']
    permission = dict(version=1,status='APPROVED',authority='OWNER',approved_at='2026-01-01T00:00:00Z',
        campaign_id=c.id,brand_id=master.brand_id,product_id=master.product_id,
        source_asset_id=source.id,render_asset_id=master.id,source_sha256=source.sha256,render_sha256=master.sha256,
        owner_decision_sha256='a'*64,use='PHYSICAL_PACKAGE_DEPICTION_ONLY',
        allowed_marks=[dict(mark_id='fixture-seal',kind='award',visible_text=['Physical fixture seal'])])
    source.ai_metadata = {**source.ai_metadata,'authentic_package_mark_permissions':[permission]}
    db.commit()
    root = f['tmp']/'application-output'
    preview = reconcile.describe_application(db,f['campaign'],f['manifest'],f['creative_path'].read_bytes(),root)
    db.rollback()
    event = AuditEvent(entity_type='canonical_campaign_application',entity_id=c.id,action='owner_authorized',detail={
        'version':1,'operation':'CREATE_CANONICAL_TEN_SLIDE_DRAFT','status':'AUTHORIZED','authority':'OWNER',
        'operator':'Isolated owner/operator','operation_id':'fixture-operation',
        'package_sha256':preview['package_sha256'],'expires_at':(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()})
    db.add(event);db.commit()
    f.update(root=root,authorization=event.id,preview=preview)
    return f


def apply_fixture(f, **changes):
    args=dict(db=f['db'],campaign=f['campaign'],manifest=f['manifest'],creative=f['creative_path'].read_bytes(),
        output_directory=f['root'],owner_authorization=f['authorization'])
    args.update(changes)
    return reconcile.apply_campaign(**args)


def test_application_creates_only_thirteen_pending_records_and_is_idempotent(application):
    from app.models import AuditEvent, ProductClaimEvidence
    f=application;db=f['db']
    # Exact historical graph and all pre-existing prerequisites stay unchanged.
    def snapshot():
        return {table.name:[tuple(row) for row in db.execute(table.select()).all()]
            for table in [AuditEvent.__table__,Asset.__table__,BrandAsset.__table__,ProductClaimEvidence.__table__]}
    before=snapshot();old=[tuple(row) for row in db.execute(Campaign.__table__.select()).all()];db.rollback()
    result=apply_fixture(f)
    assert result['status']=='APPLIED' and result['record_count']==13
    assert not result['approvals_adopted']
    assert apply_fixture(f)['status']=='ALREADY_APPLIED'
    assert snapshot()==before
    assert [tuple(row) for row in db.execute(Campaign.__table__.select().where(Campaign.id==reconcile.HISTORICAL_CAMPAIGN_ID)).all()]==old
    assert db.query(Campaign).count()==2
    assert db.query(CampaignSlide).filter_by(campaign_id=f['campaign'].id).count()==10
    assert db.query(CampaignOutput).filter_by(campaign_id=f['campaign'].id).count()==2
    actual=db.get(Campaign,f['campaign'].id)
    assert actual.status=='IDEA' and actual.human_review_status=='PENDING' and actual.approved_at is None
    assert all(not s.rendered_asset_path for s in db.query(CampaignSlide).filter_by(campaign_id=actual.id))
    db.rollback()
    assert reconcile.inspect_application_recovery(db,f['campaign'],f['manifest'],f['creative_path'].read_bytes(),f['root'],owner_authorization=f['authorization'])['status']=='COMMITTED'
    assert len(list(f['root'].rglob('*.json')))==3  # Intent plus two referenced outputs.


@pytest.mark.parametrize('authorization',[None,True,False,'',{},'caller-digest-does-not-authorize'])
def test_application_missing_authority_never_reaches_mutation(application,monkeypatch,authorization):
    f=application
    def forbidden(*a,**k):raise AssertionError('Unauthorized application reached DML')
    monkeypatch.setattr(f['db'],'add',forbidden);monkeypatch.setattr(f['db'],'flush',forbidden)
    with pytest.raises(ValueError):apply_fixture(f,owner_authorization=authorization)
    assert not f['root'].exists()


@pytest.mark.parametrize('fault',['revoked','expired','package','campaign','operation','operator','revocation_event',
    'product','master','permission','permission_revoked','claim_revoked','library','output'])
def test_application_rejects_wrong_or_stale_prerequisites_before_writes(application,monkeypatch,fault):
    from datetime import datetime,timedelta,timezone
    from app.models import AuditEvent
    f=application;db=f['db'];kwargs={}
    event=db.get(AuditEvent,f['authorization']);detail=dict(event.detail)
    if fault=='revoked':detail['status']='REVOKED'
    elif fault=='expired':detail['expires_at']=(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()
    elif fault=='package':detail['package_sha256']='f'*64
    elif fault=='campaign':event.entity_id='unrelated'
    elif fault=='operation':detail['operation']='APPROVE_ARTWORK'
    elif fault=='operator':detail['operator']=' '
    elif fault=='revocation_event':db.add(AuditEvent(entity_type=event.entity_type,entity_id=event.entity_id,
        action='owner_authorization_revoked',detail={'authorization_event_id':event.id}))
    elif fault=='product':kwargs['campaign']=Campaign(**{**f['preview']['campaign_record'],'product_id':'wrong'})
    elif fault=='master':kwargs['manifest']=f['manifest'].model_copy(update={'master_asset_id':f['source'].id})
    elif fault in ('permission','permission_revoked'):
        metadata=dict(f['source'].ai_metadata);entries=[dict(v) for v in metadata['authentic_package_mark_permissions']]
        entries[0]['campaign_id']='other' if fault=='permission' else entries[0]['campaign_id']
        if fault=='permission_revoked':entries[0]['status']='REVOKED'
        f['source'].ai_metadata={**metadata,'authentic_package_mark_permissions':entries}
    elif fault=='claim_revoked':f['rows'][0].marketing_eligible=False
    elif fault=='library':monkeypatch.setattr(marketing_claims,'load_library',lambda _:f['library'].model_copy(update={'owner_library_review_status':'PENDING'}))
    else:kwargs['output_directory']=f['tmp']/'another-root'
    event.detail=detail;db.commit()
    def forbidden(*a,**k):raise AssertionError('Invalid authority reached insert/flush')
    monkeypatch.setattr(db,'add',forbidden);monkeypatch.setattr(db,'flush',forbidden)
    with pytest.raises(ValueError):apply_fixture(f,**kwargs)
    assert not f['root'].exists()


def test_application_revalidates_after_write_lock(application,monkeypatch):
    f=application;original=reconcile._authorized_application;calls=[]
    def changed(*a,**k):
        preview,auth=original(*a,**k);calls.append(1)
        if len(calls)==2:preview={**preview,'package_sha256':'f'*64}
        return preview,auth
    monkeypatch.setattr(reconcile,'_authorized_application',changed)
    with pytest.raises(ValueError,match='after preflight'):apply_fixture(f)
    assert len(calls)==2 and not f['root'].exists()


@pytest.mark.parametrize('fault',['intent','creative','manifest','open','partial','fsync','flush','commit'])
def test_application_failure_rolls_back_only_its_files_and_records(application,monkeypatch,fault):
    f=application;db=f['db'];unrelated=f['tmp']/'keep.json';unrelated.write_text('protected unrelated output')
    publish=reconcile._publish_application_file
    def failing_publish(path,raw,owned):
        if fault=='open':raise OSError('Injected exclusive-open failure')
        if fault=='partial':
            import os
            with path.open('xb') as stream:
                stat=os.fstat(stream.fileno());owned.append((path,stat.st_dev,stat.st_ino,raw))
                stream.write(raw[:10])
            raise OSError('Injected partial-write failure')
        publish(path,raw,owned)
        if (fault=='intent' and path.name=='intent.json' or fault=='creative' and path.name.startswith('creative-')
                or fault=='manifest' and path.name==f['manifest'].digest()+'.json'):
            raise OSError('Injected publication failure')
    monkeypatch.setattr(reconcile,'_publish_application_file',failing_publish)
    if fault=='fsync':
        import os
        def no_sync(*a):raise OSError('Injected fsync failure')
        monkeypatch.setattr(os,'fsync',no_sync)
    if fault in ('flush','commit'):
        def fail(*a,**k):raise OSError('Injected database failure')
        monkeypatch.setattr(db,fault,fail)
    with pytest.raises(OSError,match='Injected'):apply_fixture(f)
    assert db.get(Campaign,f['campaign'].id) is None
    assert db.query(CampaignSlide).filter_by(campaign_id=f['campaign'].id).count()==0
    assert db.query(CampaignOutput).filter_by(campaign_id=f['campaign'].id).count()==0
    assert not list(f['root'].rglob('*.json'))
    assert unrelated.read_text()=='protected unrelated output'


def test_commit_acknowledgement_failure_retains_committed_files(application,monkeypatch):
    f=application;commit=f['db'].commit
    def lost_ack():commit();raise OSError('Lost commit acknowledgement')
    monkeypatch.setattr(f['db'],'commit',lost_ack)
    result=apply_fixture(f)
    assert result['status']=='APPLIED_COMMIT_CONFIRMED'
    assert len(list(f['root'].rglob('*.json')))==3
    assert apply_fixture(f)['status']=='ALREADY_APPLIED'


def test_interrupted_files_are_reported_and_never_adopted(application):
    f=application;directory=f['root']/'application-fixture-operation';directory.mkdir(parents=True)
    orphan=directory/'intent.json';orphan.write_text('Interrupted operation evidence')
    with pytest.raises(reconcile.ApplicationRecoveryRequired) as error:apply_fixture(f)
    assert error.value.evidence['status']=='UNREFERENCED_OR_CONFLICTING_FILES'
    assert orphan.read_text()=='Interrupted operation evidence'
    result=reconcile.inspect_application_recovery(f['db'],f['campaign'],f['manifest'],f['creative_path'].read_bytes(),f['root'],owner_authorization=f['authorization'])
    assert result['status']=='UNREFERENCED_FILES'


@pytest.mark.parametrize('fault',['display','partial','changed_output','changed_intent','evolved','concept','template'])
def test_application_collisions_and_partial_state_are_not_repaired(application,fault):
    f=application;db=f['db']
    if fault in ('changed_output','changed_intent','evolved','concept','template'):
        apply_fixture(f)
        if fault=='evolved':
            row=db.get(Campaign,f['campaign'].id);row.status='REVIEW';db.commit()
        elif fault=='concept':
            row=db.get(Campaign,f['campaign'].id);row.angle='Different concept';db.commit()
        elif fault=='template':
            row=db.query(CampaignSlide).filter_by(campaign_id=f['campaign'].id,slide_number=1).one()
            row.template_id='different-template';db.commit()
        else:
            pattern='creative-*.json' if fault=='changed_output' else 'intent.json'
            path=next(f['root'].rglob(pattern));path.write_text('Changed by another actor')
    else:
        values=dict(f['preview']['campaign_record'])
        if fault=='display':values['id']='another-campaign'
        db.add(Campaign(**values));db.commit()
    with pytest.raises(ValueError):apply_fixture(f)


def test_concurrent_identical_applications_serialize(application):
    from concurrent.futures import ThreadPoolExecutor
    from sqlalchemy.orm import sessionmaker
    f=application;factory=sessionmaker(bind=f['db'].get_bind(),autoflush=False)
    def run():
        with factory() as db:
            return apply_fixture(f,db=db)['status']
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:run(),range(2)))
    assert sorted(results)==['ALREADY_APPLIED','APPLIED']


def test_actual_revocation_between_preflight_and_lock_is_reloaded(application,monkeypatch):
    from sqlalchemy.orm import sessionmaker
    from app.models import ProductClaimEvidence
    f=application;original=reconcile._authorized_application;calls=[]
    def revoke(*a,**k):
        result=original(*a,**k);calls.append(1)
        if len(calls)==1:
            with sessionmaker(bind=f['db'].get_bind())() as other:
                row=other.get(ProductClaimEvidence,f['rows'][0].id);row.marketing_eligible=False;other.commit()
        return result
    monkeypatch.setattr(reconcile,'_authorized_application',revoke)
    with pytest.raises(ValueError,match='current canonical marketing evidence'):apply_fixture(f)
    assert not f['root'].exists()


def test_unknown_commit_outcome_preserves_evidence_for_explicit_inspection(application,monkeypatch):
    f=application;original=reconcile._completed_application
    def uncertain(db,*a):
        if db is not f['db']:raise OSError('Probe unavailable')
        return original(db,*a)
    def fail_commit():raise OSError('Commit failed')
    with monkeypatch.context() as m:
        m.setattr(reconcile,'_completed_application',uncertain);m.setattr(f['db'],'commit',fail_commit)
        with pytest.raises(reconcile.ApplicationRecoveryRequired) as error:apply_fixture(f)
        assert error.value.evidence['status']=='COMMIT_OUTCOME_UNKNOWN'
        assert len(list(f['root'].rglob('*.json')))==3
    result=reconcile.inspect_application_recovery(f['db'],f['campaign'],f['manifest'],f['creative_path'].read_bytes(),f['root'],owner_authorization=f['authorization'])
    assert result['status']=='UNREFERENCED_FILES'
    with pytest.raises(reconcile.ApplicationRecoveryRequired):apply_fixture(f)


def test_cleanup_never_deletes_a_tampered_attempt_file(application,monkeypatch):
    f=application;publish=reconcile._publish_application_file
    def tamper(path,raw,owned):
        publish(path,raw,owned)
        if path.name.startswith('creative-'):
            path.write_bytes(b'Other actor data');raise OSError('Injected concurrent change')
    monkeypatch.setattr(reconcile,'_publish_application_file',tamper)
    with pytest.raises(reconcile.ApplicationRecoveryRequired) as error:apply_fixture(f)
    assert error.value.evidence['status']=='ROLLBACK_FILES_RETAINED'
    assert next(f['root'].rglob('creative-*.json')).read_bytes()==b'Other actor data'
    assert f['db'].get(Campaign,f['campaign'].id) is None


def test_application_snapshots_mutable_caller_inputs(application,monkeypatch):
    f=application;publish=reconcile._publish_application_file
    mapping=dict(f['manifest'].evidence_ids);display=f['campaign'].display_id
    def mutate(path,raw,owned):
        publish(path,raw,owned)
        if path.name=='intent.json':
            f['manifest'].evidence_ids['ex-apply']='caller-mutated'
            f['campaign'].display_id='caller-mutated'
    monkeypatch.setattr(reconcile,'_publish_application_file',mutate)
    try:
        assert apply_fixture(f)['status']=='APPLIED'
        actual=f['db'].get(Campaign,f['campaign'].id)
        assert actual.display_id==display
        row=f['db'].query(CampaignOutput).filter_by(campaign_id=actual.id,kind='campaign_reconciliation').one()
        assert json.loads(Path(row.file_path).read_bytes())['evidence_ids']==mapping
    finally:
        f['manifest'].evidence_ids.clear();f['manifest'].evidence_ids.update(mapping)
        f['campaign'].display_id=display


@pytest.mark.parametrize('target',['missing','memory_uri'])
def test_application_entry_never_creates_a_database(tmp_path,target):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    missing=tmp_path/'unregistered.db'
    url='sqlite:///'+str(missing) if target=='missing' else 'sqlite:///file:unregistered?mode=memory&uri=true'
    engine=create_engine(url)
    try:
        with Session(engine) as db:
            with pytest.raises(ValueError,match='file-backed'):
                reconcile.apply_campaign(db,None,None,b'',tmp_path/'out',owner_authorization='untrusted-reference')
        assert not missing.exists() and not (tmp_path/'out').exists()
    finally:engine.dispose()
