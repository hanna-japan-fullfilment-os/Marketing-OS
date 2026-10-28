"""Synthetic integration only: no campaign cover or provider execution."""
from dataclasses import replace
import base64
import io
import json

from PIL import Image,ImageDraw
import pytest

from app.services.creative import premium_design as design
from app.services.creative.templates import get_template,Feature
from app.services.creative.composition import Box
from app.services.creative.scene import compose_unified_scene,CanonicalSceneAsset
from test_build6r_v92_premium_design import fixture


def test_existing_pipeline_persists_styling_without_changing_contract(tmp_path,monkeypatch):
    from test_creative import _repair_plan,_repair_input,_repair_finish,_RepairRenderer
    from test_build6r_v72_premium_composition import context
    from app.services.creative.pipeline import render_slide,build_render_context_path,persist_render_context
    plan=_repair_plan(tmp_path);ref=plan.reference_assets[0]
    # Synthetic authority fixture only. The production reference gate is tested separately.
    monkeypatch.setattr(design,'REFERENCES',{ref.asset_id:ref.sha256})
    target=context().reference_target.model_copy(update={'reference_id':ref.asset_id,'sha256':ref.sha256})
    plan=plan.model_copy(update={'visual_brief':json.dumps({'REFERENCE_TARGET':target.model_dump()})})
    renderer=_RepairRenderer();out=tmp_path/'synthetic-only.png'
    result=_repair_finish(render_slide(replace(_repair_input(plan),reference_target=target,product_category='electronics'),output_path=out,renderer=renderer))
    assert not result.qa.passed # Fake observations cannot approve a render.
    payload=json.loads(build_render_context_path(out).read_text(encoding='utf-8'))
    assert payload['premium_scene_style']['geometry_sha256']==payload['composition_spec_sha256']
    assert payload['premium_scene_style']['scene_sha256']==payload['unified_scene_spec_sha256']
    assert payload['slide_contract']==plan.model_dump()
    assert 'id="premium-scene-style"' in renderer.html
    persist_render_context(slide_output_path=out,creative_direction={},visual_base=None,visual_base_kind='none')
    enriched=json.loads(build_render_context_path(out).read_text(encoding='utf-8'))
    assert enriched['premium_scene_style']==payload['premium_scene_style']
    assert enriched['premium_scene_style_sha256']==payload['premium_scene_style_sha256']


def test_template_rejects_styling_from_another_scene():
    ctx,scene,style,_,_=fixture()
    with pytest.raises(ValueError):
        get_template('feature_showcase').build_html(replace(ctx,composition_spec=scene.layout,unified_scene=scene,premium_style=replace(style,scene_sha256='0'*64)))


@pytest.mark.asyncio
@pytest.mark.parametrize('text,lines',[('7 máscaras',1),('Embalagem com 7 máscaras.',2),('Embalagem com 7 máscaras e 150 mL de essência.',3)])
async def test_styled_callout_1_2_3_lines_keep_frozen_measurement_rules(text,lines):
    from app.services.creative.renderer import PlaywrightRenderer
    from app.services.creative.qa import run_creative_qa
    ctx,_,_,_,_=fixture()
    im=Image.new('RGB',(1080,1350),'#14051F');ImageDraw.Draw(im).rectangle((551,648,1047,1309),fill='#cc88ff')
    buf=io.BytesIO();im.save(buf,format='PNG')
    ctx=replace(ctx,features=[Feature(title=text)],composited_image_data_uri='data:image/png;base64,'+base64.b64encode(buf.getvalue()).decode())
    scene=compose_unified_scene(ctx,Box(551,648,497,662),canonical_asset=CanonicalSceneAsset('p','a'*64,'fixture.png',(0,0,200,400)),background_identity='fixture',product_safe=Box(32,299,1016,1011))
    style=design.resolve_premium_scene_style(scene,product_color=design.dominant_product_color(Image.new('RGBA',(20,40),'#401060')),contrast_samples=design.scene_contrast_samples(scene,im))
    html=get_template('feature_showcase').build_html(replace(ctx,composition_spec=scene.layout,unified_scene=scene,premium_style=style))
    renderer=PlaywrightRenderer()
    try:png,diag=await renderer.render_png_with_diagnostics(html=html,width=1080,height=1350)
    finally:await renderer.close()
    observed=next(r for r in diag.composition['roles'] if r['key']=='feature_0')
    assert not observed['overflow'] and observed['lines']==lines
    mask=Image.new('L',im.size);ImageDraw.Draw(mask).rectangle((551,648,1047,1309),fill=255)
    result=run_creative_qa(png_bytes=png,expected_width=1080,expected_height=1350,diagnostics=diag,logo_expected=False,logo_included=False,composition_spec=scene.layout,base_image=im,product_alpha=mask)
    assert result.passed and all(result.composition['hard_checks'].values())
