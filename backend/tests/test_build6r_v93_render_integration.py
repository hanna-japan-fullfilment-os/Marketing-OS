"""Local synthetic PNG integration, explicitly not campaign acceptance."""
from dataclasses import replace
import hashlib
import json
import io
import base64

from PIL import Image,ImageDraw
import pytest

from app.services.creative import premium_design as design
from app.services.creative import pipeline
from app.services.creative.compositor import ProductZone
from app.services.creative.composition import Box
from test_build6r_v92_premium_design import fixture
from test_creative import _repair_plan,_repair_input,_RepairRenderer,_repair_finish


def setup(tmp_path,monkeypatch,*,cta=False,headline='Descubra'):
    plan=_repair_plan(tmp_path)
    # A complete opaque synthetic package, not a generated/approved real package.
    image=Image.new('RGBA',(600,800),(180,120,220,255));image.save(plan.product_asset.path)
    asset=plan.product_asset.model_copy(update={'sha256':hashlib.sha256(open(plan.product_asset.path,'rb').read()).hexdigest()})
    ref=plan.reference_assets[0];monkeypatch.setattr(design,'REFERENCES',{ref.asset_id:ref.sha256})
    ctx,_,_,_,_=fixture() # fixture now uses the synthetic reference authority
    target=ctx.reference_target.model_copy(update={'reference_id':ref.asset_id,'sha256':ref.sha256})
    target=target.model_copy(update={'grammar':target.grammar.model_copy(update={'typography':'condensed'})})
    from app.services.creative.background import NoOpBackgroundIsolator
    monkeypatch.setattr(pipeline,'get_isolator',lambda **kw:NoOpBackgroundIsolator())
    monkeypatch.setattr(pipeline,'_resolve_product_zone',lambda *a,**k:ProductZone(550,640,480,640))
    plan=plan.model_copy(update={'product_asset':asset,'visual_brief':json.dumps({'REFERENCE_TARGET':target.model_dump()}),
        'cta':'Saiba mais' if cta else '', 'headline':headline,
        'evidence_references':[r.model_copy(update={'claim_text':headline}) for r in plan.evidence_references]})
    plan=plan.model_copy(update={'claim_bindings':pipeline.canonical_slide_claim_bindings(plan)})
    art=Image.new('RGB',(1080,1350),'#14051F')
    logo=tmp_path/'logo.png';im=Image.new('RGBA',(80,30),(255,255,255,255));ImageDraw.Draw(im).ellipse((20,4,60,26),fill=(220,180,180,255));im.save(logo)
    inp=replace(_repair_input(plan),reference_target=target,premium_render_mode='v9',generated_background=art,
        logo_path=logo,slide_role='hero',brand_colors=['#14051F','#2F133F'])
    return inp,logo


def test_full_pipeline_persists_coordinated_plan_and_no_fallback(tmp_path,monkeypatch):
    inp,logo=setup(tmp_path,monkeypatch,cta=True);before=logo.read_bytes()
    renderer=_RepairRenderer();out=tmp_path/'synthetic.png'
    result=_repair_finish(pipeline.render_slide(inp,output_path=out,renderer=renderer))
    payload=json.loads(pipeline.build_render_context_path(out).read_text(encoding='utf-8'))
    assert 'id="premium-render-plan"' in renderer.html
    assert 'premium-logo-zone' in renderer.html and 'rgba(255,255,255' not in renderer.html
    assert payload['premium_layer_metadata']['grounding_applied']
    assert payload['premium_render_plan']['constraints']['raw_ungrounded_overlay'] is False
    assert payload['premium_render_plan']['geometry_sha256']==payload['composition_spec_sha256']
    assert payload['slide_contract']==inp.slide_plan.model_dump() and logo.read_bytes()==before
    assert not result.qa.passed # Synthetic fake renderer has no measured geometry.
    pipeline.persist_render_context(slide_output_path=out,creative_direction={},visual_base=None,visual_base_kind='none')
    assert json.loads(pipeline.build_render_context_path(out).read_text(encoding='utf-8'))['premium_render_plan_sha256']==payload['premium_render_plan_sha256']


def test_explicit_v9_reference_failure_never_calls_legacy_renderer(tmp_path):
    inp=_repair_input(_repair_plan(tmp_path));renderer=_RepairRenderer()
    with pytest.raises(ValueError,match='V9'):
        _repair_finish(pipeline.render_slide(replace(inp,premium_render_mode='v9'),output_path=tmp_path/'forbidden.png',renderer=renderer))
    assert not hasattr(renderer,'html')


def test_compositing_failure_propagates_without_legacy_retry(tmp_path,monkeypatch):
    inp,_=setup(tmp_path,monkeypatch);renderer=_RepairRenderer()
    def fail(*a,**k):raise ValueError('governed compositing failure')
    monkeypatch.setattr(pipeline,'composite_premium_layers',fail)
    with pytest.raises(ValueError,match='governed'):
        _repair_finish(pipeline.render_slide(inp,output_path=tmp_path/'forbidden.png',renderer=renderer))
    assert not hasattr(renderer,'html')


@pytest.mark.asyncio
@pytest.mark.parametrize('cta',[False,True])
async def test_actual_synthetic_png_flows_through_frozen_structural_qa(tmp_path,monkeypatch,cta):
    from app.services.creative.renderer import PlaywrightRenderer
    inp,logo=setup(tmp_path,monkeypatch,cta=cta);renderer=PlaywrightRenderer()
    try:result=await pipeline.render_slide(inp,output_path=tmp_path/'engineering-fixture.png',renderer=renderer)
    finally:await renderer.close()
    (tmp_path/'measured-qa.json').write_text(json.dumps(result.qa.to_dict()),encoding='utf-8')
    assert result.qa.passed,result.qa.to_dict()
    assert all(result.qa.composition['hard_checks'].values()) and len(result.qa.composition['hard_checks'])==20
    assert not result.qa.composition['visual_acceptance']
    actual=Image.open(result.output_path);assert actual.size==(1080,1350)
    assert actual.getpixel((750,900))==(180,120,220)


def test_nonpremium_keeps_legacy_path(tmp_path):
    inp=_repair_input(_repair_plan(tmp_path));renderer=_RepairRenderer()
    _repair_finish(pipeline.render_slide(inp,output_path=tmp_path/'legacy-fixture.png',renderer=renderer))
    assert 'id="premium-render-plan"' not in renderer.html


@pytest.mark.asyncio
async def test_v9_still_rejects_long_unbreakable_headline_without_shrinking(tmp_path,monkeypatch):
    from app.services.creative.renderer import PlaywrightRenderer
    inp,_=setup(tmp_path,monkeypatch,headline='Coleção'*30);renderer=PlaywrightRenderer()
    try:result=await pipeline.render_slide(inp,output_path=tmp_path/'expected-qa-failure.png',renderer=renderer)
    finally:await renderer.close()
    assert not result.qa.passed and 'text_overflow' in result.qa.composition['hard_failures']


@pytest.mark.asyncio
@pytest.mark.parametrize('text,lines',[('7 máscaras',1),('Embalagem com 7 máscaras.',2),('Embalagem com 7 máscaras e 150 mL de essência.',3)])
async def test_v9_rendered_callout_preserves_one_two_three_lines(text,lines):
    from app.services.creative.templates import Feature,get_template
    from app.services.creative.scene import compose_unified_scene
    from app.services.creative.premium_render import build_premium_render_plan,composite_premium_layers,image_digest
    from app.services.creative.renderer import PlaywrightRenderer
    from app.services.creative.qa import run_creative_qa
    ctx,old,_,_,art=fixture();ctx=replace(ctx,features=[Feature(title=text)])
    scene=compose_unified_scene(ctx,old.layout.product,canonical_asset=old.canonical_asset,
        background_identity='fixture',product_safe=Box(32,299,1016,1011))
    product=Image.new('RGBA',art.size);p=scene.layout.product
    ImageDraw.Draw(product).rectangle((p.x,p.y,p.right-1,p.bottom-1),fill=(180,120,220,255))
    style=design.resolve_premium_scene_style(scene,product_color=design.dominant_product_color(product),contrast_samples=design.scene_contrast_samples(scene,art))
    plan=build_premium_render_plan(scene,style,product_layer_sha256=image_digest(product))
    base,_=composite_premium_layers(plan,scene,style,art=art,product_layer=product)
    data=io.BytesIO();base.save(data,format='PNG')
    html=get_template('feature_showcase').build_html(replace(ctx,composition_spec=scene.layout,unified_scene=scene,premium_style=style,
        premium_render_plan=plan,composited_image_data_uri='data:image/png;base64,'+base64.b64encode(data.getvalue()).decode()))
    renderer=PlaywrightRenderer()
    try:png,diag=await renderer.render_png_with_diagnostics(html=html,width=1080,height=1350)
    finally:await renderer.close()
    fact=next(r for r in diag.composition['roles'] if r['key']=='feature_0')
    assert fact['lines']==lines and not fact['overflow']
    qa=run_creative_qa(png_bytes=png,expected_width=1080,expected_height=1350,diagnostics=diag,logo_expected=False,
        logo_included=False,composition_spec=scene.layout,base_image=base,product_alpha=product.getchannel('A'))
    assert qa.passed,qa.to_dict()
