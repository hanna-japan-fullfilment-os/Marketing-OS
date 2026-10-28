"""Synthetic adapters only: no Chromium, provider, or campaign cover render."""
import base64
from dataclasses import replace
import hashlib
import io
import json

from PIL import Image
import pytest

from app.services.creative.pipeline import _scene_logo


@pytest.mark.parametrize('transparent,uniform',[(False,True),(True,True),(False,False)])
def test_source_supported_logo_has_no_default_white_tile(tmp_path,transparent,uniform):
    source=tmp_path/'logo.png'
    image=Image.new('RGBA',(20,20),(255,255,255,0 if transparent else 255))
    image.putpixel((10,10),(120,30,40,255))
    if not uniform:image.putpixel((0,0),(10,20,30,255))
    image.save(source);before=source.read_bytes()
    uri,meta=_scene_logo(source)
    derived=Image.open(io.BytesIO(base64.b64decode(uri.split(',')[1])))
    assert source.read_bytes()==before
    assert meta['source_sha256']==hashlib.sha256(before).hexdigest()
    assert derived.getpixel((10,10))==(120,30,40,255)
    assert derived.convert('RGB').tobytes()==image.convert('RGB').tobytes()
    assert meta['mode']!='white_tile'
    if uniform:assert derived.getpixel((0,0))[3]==0
    else:assert derived.tobytes()==image.tobytes()


def test_primary_premium_pipeline_persists_one_scene_and_legacy_qa(tmp_path):
    from test_creative import _repair_plan,_repair_input,_repair_finish,_RepairRenderer
    from test_build6r_v72_premium_composition import context
    from app.services.creative.pipeline import render_slide,build_render_context_path,persist_render_context
    plan=_repair_plan(tmp_path);ref=plan.reference_assets[0]
    target=context().reference_target.model_copy(update={'reference_id':ref.asset_id,'sha256':ref.sha256})
    plan=plan.model_copy(update={'visual_brief':json.dumps({'REFERENCE_TARGET':target.model_dump()})})
    inp=replace(_repair_input(plan),reference_target=target)
    renderer=_RepairRenderer();output=tmp_path/'synthetic-only.png'
    result=_repair_finish(render_slide(inp,output_path=output,renderer=renderer))
    assert 'id="unified-scene-spec"' in renderer.html
    assert 'background-color:rgba(0,0,0,0)' in renderer.html
    assert not result.qa.passed # A fake image has no observed geometry and cannot pass.
    before=json.loads(build_render_context_path(output).read_text(encoding='utf-8'))
    assert before['unified_scene_spec']['layout']==before['composition_spec']
    assert before['unified_scene_spec']['canonical_asset']['sha256']==plan.product_asset.sha256
    assert before['slide_contract']==plan.model_dump()
    persist_render_context(slide_output_path=output,creative_direction={},visual_base=None,visual_base_kind='none')
    after=json.loads(build_render_context_path(output).read_text(encoding='utf-8'))
    assert after['unified_scene_spec']==before['unified_scene_spec']
    assert after['unified_scene_spec_sha256']==before['unified_scene_spec_sha256']


def test_no_reference_class_keeps_legacy_template_path():
    from test_build6r_v72_premium_composition import context
    from app.services.creative.templates import get_template
    html=get_template('feature_showcase').build_html(context(reference_target=None))
    assert 'unified-scene-spec' not in html and 'Conheça' in html


def test_compressed_near_white_matte_preserves_ink_and_enclosed_whites(tmp_path):
    from PIL import ImageDraw
    image=Image.new('RGBA',(30,30),(253,254,255,255))
    ImageDraw.Draw(image).rectangle((8,8,22,22),outline=(120,30,40,255),width=2)
    image.putpixel((15,15),(255,255,255,255))
    path=tmp_path/'compressed-logo.png';image.save(path)
    uri,meta=_scene_logo(path)
    derived=Image.open(io.BytesIO(base64.b64decode(uri.split(',')[1])))
    assert meta['connected_border_matte_removed']
    assert derived.getpixel((0,0))[3]==0
    assert derived.getpixel((15,15))==(255,255,255,255)
    assert derived.getpixel((8,8))==(120,30,40,255)
    assert derived.convert('RGB').tobytes()==image.convert('RGB').tobytes()
