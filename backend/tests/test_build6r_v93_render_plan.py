"""Synthetic render plans/effects only; no provider or visual acceptance."""
from copy import deepcopy
from dataclasses import replace
import json

from PIL import Image,ImageDraw
import pytest

from app.services.creative.premium_render import (build_premium_render_plan,
    composite_premium_layers,image_digest,fit_art_layer,premium_treatment_css,debug_premium_render)
from app.services.creative.art_layer_adapter import gpt_image_2_art_request
from test_build6r_v92_premium_design import fixture


def inputs(**kwargs):
    ctx,scene,style,_,art=fixture(**kwargs)
    product=Image.new('RGBA',art.size)
    p=scene.layout.product
    ImageDraw.Draw(product).rectangle((p.x,p.y,p.right-1,p.bottom-1),fill=(180,120,220,255))
    plan=build_premium_render_plan(scene,style,product_layer_sha256=image_digest(product))
    return ctx,scene,style,art,product,plan


def test_plan_is_complete_deterministic_and_preserves_v91_v92():
    _,scene,style,art,product,plan=inputs()
    before_scene=scene.digest;before_style=style.digest
    other=build_premium_render_plan(scene,style,product_layer_sha256=image_digest(product))
    assert plan.to_dict()==other.to_dict() and plan.digest==other.digest
    plan.validate(scene,style)
    assert scene.digest==before_scene and style.digest==before_style
    assert list(plan.depth_order)==['BACKGROUND_LAYER','MIDGROUND_SUPPORT_LAYER','PRODUCT_LAYER','FOREGROUND_ACCENT_LAYER','TYPOGRAPHY_BRAND_LAYER']
    assert plan.product_geometry['preserve_pixels']
    assert not any(plan.constraints[k] for k in ('opaque_text_panel','white_logo_tile','raw_ungrounded_overlay','silent_legacy_fallback','product_redraw_allowed','visual_acceptance'))
    assert not plan.constraints['duplicate_treatment_count']


def test_art_translation_excludes_copy_product_logo_and_code_owned_motifs():
    _,scene,style,_,_,_=inputs()
    plan=build_premium_render_plan(scene,style,art_native_size=(1024,1536))
    request=gpt_image_2_art_request(plan)
    assert request['model']=='gpt-image-2' and request['quality']=='high' and request['n']==1
    assert 'image' not in request and len(request['prompt'].encode())<=20000
    assert '7 máscaras' not in request['prompt'] and 'Conheça' not in request['prompt']
    assert plan.crop['crop_box']==[0,128,1024,1408]
    spec=plan.art_layer_prompt_spec
    assert not any(spec[k] for k in ('generative_text_allowed','generative_logo_allowed','generative_product_allowed'))
    assert {'product','headline','feature_0','logo','cta_support'}<=set(spec['regions'])
    assert spec['relations']['light_leads_to']=='canonical_product_reserved'
    assert spec['relations']['flow']==scene.composition['visual_flow']
    assert spec['relations']['anchors'] and spec['negative_space']
    assert not set(spec['generated_motifs']) & set(spec['excluded_code_owned_motifs'])
    assert set(spec['generated_motifs']+spec['excluded_code_owned_motifs'])==set(style.motifs)


@pytest.mark.parametrize('category',['beauty','electronics','lifestyle'])
@pytest.mark.parametrize('wide,rich',[(False,False),(True,True)])
def test_grounding_depth_and_opaque_product_pixels_are_real_not_metadata(category,wide,rich):
    _,scene,style,art,product,plan=inputs(category=category,wide=wide,rich=rich)
    before=image_digest(product);art_before=image_digest(art)
    actual,meta=composite_premium_layers(plan,scene,style,art=art,product_layer=product)
    assert image_digest(product)==before and image_digest(art)==art_before
    p=scene.layout.product
    assert actual.getpixel((round(p.x+p.width/2),round(p.y+p.height/2)))==(180,120,220)
    assert meta['grounding_applied'] and len(meta['applied_grounding'])==4
    assert image_digest(actual)!=image_digest(art)
    alpha=product.getchannel('A').tobytes();pixels=product.convert('RGB').tobytes();output=actual.tobytes()
    assert all(output[i*3:i*3+3]==pixels[i*3:i*3+3] for i,a in enumerate(alpha) if a==255)
    # Some genuine support pixels must differ outside the product.
    original=art.tobytes()
    assert any(output[i*3:i*3+3]!=original[i*3:i*3+3] for i,a in enumerate(alpha) if a==0)
    assert set(meta['code_motifs']).isdisjoint(meta['art_motifs'])
    assert not meta['visual_acceptance']


def test_effects_leave_real_text_and_logo_contrast_zones_untouched():
    _,scene,style,art,product,plan=inputs()
    actual,_=composite_premium_layers(plan,scene,style,art=art,product_layer=product)
    for box in [r.box for r in scene.layout.roles]+[scene.layout.logo]:
        xy=(round(box.x+box.width/2),round(box.y+box.height/2))
        assert actual.getpixel(xy)==art.getpixel(xy)


@pytest.mark.parametrize('mutation',['owner','geometry','style','constraints','layer'])
def test_altered_plan_or_product_layer_fails_closed(mutation):
    _,scene,style,art,product,plan=inputs();plan=deepcopy(plan)
    if mutation=='owner':plan.ownership['motif.LIGHT_ARC']='ART_LAYER'
    elif mutation=='geometry':plan.product_geometry['box']['x']=1
    elif mutation=='style':plan=replace(plan,style_sha256='0'*64)
    elif mutation=='constraints':plan.constraints['silent_legacy_fallback']=True
    else:product.putpixel((600,700),(0,255,0,255))
    with pytest.raises(ValueError):composite_premium_layers(plan,scene,style,art=art,product_layer=product)


def test_crop_contract_and_art_dimensions_fail_closed():
    _,scene,style,_,_,_=inputs()
    plan=build_premium_render_plan(scene,style,art_native_size=(1024,1536))
    art=Image.new('RGB',(1024,1536),'#14051F')
    assert fit_art_layer(plan,art).size==(1080,1350) and not plan.crop['stretch']
    with pytest.raises(ValueError):fit_art_layer(plan,Image.new('RGB',(1024,1280)))
    with pytest.raises(ValueError):gpt_image_2_art_request(build_premium_render_plan(scene,style))


def test_all_selected_treatment_ids_produce_code_and_debug_has_required_contracts():
    _,scene,style,_,_,plan=inputs(rich=True)
    css=premium_treatment_css(plan,scene,style)
    assert 'box-shadow' in css and 'white' not in css and '.premium-logo-zone' not in css # absent logo
    debug=debug_premium_render(scene,style,plan)
    assert {'UNIFIED_SCENE_SPEC','RESOLVED_PREMIUM_SCENE_STYLE','ART_LAYER_PROMPT_SPEC','PREMIUM_RENDER_PLAN','COMPOSITING_ORDER','QA_GEOMETRY'}<=set(debug)
    assert not debug['visual_acceptance'];json.dumps(debug,allow_nan=False)


@pytest.mark.parametrize('kind,archetype,choice,fragment',[
    ('callout','EDITORIAL_HERO','EDITORIAL_FACT_RULE','inset'),
    ('callout','DIAGONAL_FLOW','OUTLINE_BRACKET','inset 0'),
    ('callout','ATMOSPHERIC_PRODUCT_STAGE','LUMINOUS_INLINE','inset 0 -'),
    ('cta','ATMOSPHERIC_PRODUCT_STAGE','GOLD_EDITORIAL_BAND','background-color:#B99252'),
    ('cta','EDITORIAL_HERO','INLINE_ACCENT_RULE','data-composition-role="cta"'),
    ('logo','ATMOSPHERIC_PRODUCT_STAGE','TRANSPARENT_SIGNATURE','premium-role'),
    ('logo','ATMOSPHERIC_PRODUCT_STAGE','TONAL_BRAND_ZONE','background:rgba'),
    ('logo','EDITORIAL_HERO','EDITORIAL_CORNER','premium-logo-zone'),
])
def test_every_callout_cta_and_logo_renderer_consumes_compatible_vocabulary(kind,archetype,choice,fragment):
    from app.services.creative import premium_design as d
    _,scene,_,art,product,_=inputs(rich=True)
    scene=replace(scene,archetype=archetype,layout=replace(scene.layout,logo_required=True))
    style=d.resolve_premium_scene_style(scene,product_color=d.dominant_product_color(product),
        contrast_samples=d.scene_contrast_samples(scene,art))
    treatments=dict(style.treatments);treatments[kind]=choice
    kwargs={kind:dict(getattr(style,kind),id=choice),
            'treatments':treatments,'resolved_vocabulary':d._vocabulary(treatments,style.motifs,style.surfaces)}
    style=replace(style,**kwargs)
    plan=build_premium_render_plan(scene,style,product_layer_sha256=image_digest(product))
    assert fragment in premium_treatment_css(plan,scene,style)
