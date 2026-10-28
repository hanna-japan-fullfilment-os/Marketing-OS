"""Provider-free Hanna vocabulary/selection contracts, not visual acceptance."""
from dataclasses import replace
from copy import deepcopy
import json

from PIL import Image
import pytest

from app.services.creative import premium_design as design
from app.services.creative.composition import Box
from app.services.creative.scene import CanonicalSceneAsset,compose_unified_scene,ARCHETYPES
from app.services.creative.templates import Feature
from test_build6r_v72_premium_composition import context


def fixture(*,category='beauty',product_color='#401060',wide=False,rich=False,background='#14051F'):
    ctx=context(features=[Feature(title='7 máscaras')],body='Informação aprovada' if rich else '',cta='Saiba mais' if rich else '')
    key=next(iter(design.REFERENCES))
    target=ctx.reference_target.model_copy(update={'reference_id':key,'sha256':design.REFERENCES[key]})
    # The approved Hanna class uses a luminous vector icon, not a fallback text
    # glyph (which is itself another measured text line).
    raw=target.model_dump()
    raw['grammar']['icon_paint']=dict(kind='luminous_vector',tint='#F3D9FF',glow_color='#A845FF',
        glow_opacity=.85,glow_radius_px=8,stroke_width_px=1.2,ring_width_px=1,size_scale=1.25)
    target=type(target).model_validate(raw)
    ctx=replace(ctx,reference_target=target)
    scene=compose_unified_scene(ctx,Box(260,900,600,300) if wide else Box(551,648,497,662),
        canonical_asset=CanonicalSceneAsset('product','a'*64,'fixture.png',(0,0,200,400)),background_identity='synthetic')
    product=Image.new('RGBA',(40,80),product_color)
    color=design.dominant_product_color(product)
    image=Image.new('RGB',(1080,1350),background)
    samples=design.scene_contrast_samples(scene,image)
    style=design.resolve_premium_scene_style(scene,product_color=color,contrast_samples=samples,product_category=category)
    return ctx,scene,style,product,image


@pytest.mark.parametrize('category',['beauty','electronics','lifestyle','collectible','automotive','food'])
@pytest.mark.parametrize('product_color',['#F4EFE7','#181716'])
@pytest.mark.parametrize('wide,rich',[(False,False),(True,True)])
def test_categories_shapes_copy_and_product_tones_preserve_one_brand_core(category,product_color,wide,rich):
    ctx,scene,a,product,image=fixture(category=category,product_color=product_color,wide=wide,rich=rich)
    before=product.tobytes();geometry=scene.layout.digest;scene_hash=scene.digest
    b=design.resolve_premium_scene_style(scene,product_color=design.dominant_product_color(product),
        contrast_samples=design.scene_contrast_samples(scene,image),product_category=category)
    assert a.to_dict()==b.to_dict() and a.digest==b.digest
    a.validate(scene)
    assert scene.layout.digest==geometry and scene.digest==scene_hash and product.tobytes()==before
    assert a.palette==design.COLORS
    assert a.palette['primary_brand_accent']=='#B99252' and a.palette['cream']=='#F4EFE7'
    assert a.palette['matcha_contextual'] is None and not a.category['matcha_active']
    assert a.category['id']==category and a.grounding['product_redraw_allowed'] is False
    assert not a.logo['white_tile'] and len(a.motifs)<=a.limits['max_decorative_motif_count']
    assert len(a.surfaces)<=2 and a.limits['max_accent_color_count']==2
    assert a.depth['layer_order']==[d['name'] for d in scene.depth_layers]


def test_catalog_counts_and_complete_selected_vocabulary():
    _,scene,s,_,_=fixture()
    assert set(design.MATRIX)==set(ARCHETYPES)
    assert len(design.TEXT_TREATMENTS)==4 and len(design.LOGO_TREATMENTS)==3
    assert len(design.LIGHTING)==3 and len(design.CTA_TREATMENTS)==2 and len(design.CALLOUT_TREATMENTS)==3
    assert set(s.resolved_vocabulary)=={'text','logo','cta','callout','motifs','surfaces','typography_roles'}
    assert {'KICKER','HEADLINE','SUPPORTING_COPY','FACT_CALLOUT','CTA','LEGAL','LOGO_ADJACENT'}<=set(design.TYPOGRAPHY_ROLES)
    assert s.lighting['text_contrast_minimum']==4.5 and s.grounding['rendered'] is False
    assert not any(word in json.dumps(s.to_dict()).lower() for word in ('torii','cherry blossom','kanji','comfyui','sunburst','gpt-image'))


@pytest.mark.parametrize('background,expected',[('#FFFFFF','foreground_dark'),('#14051F','foreground_light')])
def test_contrast_selects_foreground_from_actual_zones(background,expected):
    _,_,s,_,_=fixture(background=background)
    assert all(t['foreground']==design.COLORS[expected] for t in s.typography)
    assert all(t['support_alpha']==0 for t in s.typography)


def test_mixed_zone_uses_bounded_translucent_charcoal_not_white_panel():
    _,scene,s,p,im=fixture()
    samples={r.key:((0,0,0),(255,255,255),(120,120,120)) for r in scene.layout.roles}
    result=design.resolve_premium_scene_style(scene,product_color=design.dominant_product_color(p),contrast_samples=samples)
    assert result.treatments['text']=='TONAL_VEIL'
    assert all(0<t['support_alpha']<1 and t['background'].startswith('rgba(24,23,22,') for t in result.typography)
    assert all(t['minimum_sample_contrast']>=4.5 for t in result.typography)


@pytest.mark.parametrize('mutation',['identity','palette','limits','motifs','lighting','typography','opacity','vocabulary','grounding','depth','logo','scene'])
def test_style_corruption_fails_closed(mutation):
    _,scene,s,_,_=fixture();s=deepcopy(s)
    if mutation=='identity':s=replace(s,scene_sha256='0'*64)
    elif mutation=='palette':s.palette['primary_brand_accent']='#00FF00'
    elif mutation=='limits':s.limits['max_decorative_motif_count']=100
    elif mutation=='motifs':s=replace(s,motifs=('UNAPPROVED',))
    elif mutation=='lighting':s.lighting['shadow_softness']=100
    elif mutation=='typography':s.typography[0]['font_family']='Invented'
    elif mutation=='opacity':s.typography[0]['support_alpha']=1
    elif mutation=='vocabulary':s.resolved_vocabulary['logo']['recolor']=True
    elif mutation=='grounding':s.grounding['product_redraw_allowed']=True
    elif mutation=='depth':s.depth['layer_order'].reverse()
    elif mutation=='logo':s.logo['white_tile']=True
    else:scene=replace(scene,layout=replace(scene.layout,margin=40))
    with pytest.raises(ValueError):s.validate(scene)


def test_different_reference_identity_is_not_hanna_style_authority():
    _,scene,s,p,im=fixture()
    bad=replace(scene,layout=replace(scene.layout,reference_id='different'))
    assert not design.is_hanna_scene(bad)
    with pytest.raises(ValueError):design.resolve_premium_scene_style(bad,product_color=design.dominant_product_color(p),contrast_samples={})


def test_opaque_only_product_color_signal_and_no_source_mutation():
    p=Image.new('RGBA',(64,64),(255,0,0,0));p.putpixel((32,32),(0,0,80,255));before=p.tobytes()
    signal=design.dominant_product_color(p)
    assert signal['dominant_hex']=='#000050' and p.tobytes()==before
    with pytest.raises(ValueError):design.dominant_product_color(Image.new('RGBA',(20,20),(1,2,3,0)))


def test_debug_output_contains_full_scene_treatments_and_preserves_geometry():
    _,scene,s,_,_=fixture()
    debug=design.debug_premium_scene(scene,s)
    assert debug['unified_scene_spec']['layout']==scene.layout.to_dict()
    assert debug['resolved_premium_scene_style']['treatments']==s.treatments
    assert not debug['visual_acceptance']
    json.loads(json.dumps(debug,allow_nan=False))


def test_missing_or_nonfinite_observations_do_not_get_free_contrast():
    _,scene,s,p,im=fixture()
    with pytest.raises(ValueError):design.resolve_premium_scene_style(scene,product_color=design.dominant_product_color(p),contrast_samples={})
    signal=design.dominant_product_color(p);signal['luminance']=float('nan')
    with pytest.raises(ValueError):design.resolve_premium_scene_style(scene,product_color=signal,contrast_samples={})


@pytest.mark.parametrize('archetype',design.MATRIX)
def test_every_scene_archetype_selects_only_compatible_vocabulary(archetype):
    _,scene,_,product,image=fixture()
    scene=replace(scene,archetype=archetype)
    style=design.resolve_premium_scene_style(scene,product_color=design.dominant_product_color(product),contrast_samples=design.scene_contrast_samples(scene,image))
    style.validate(scene)
    for name,choice in style.treatments.items():assert choice in design.MATRIX[archetype][name]


def test_medium_tone_and_missing_category_use_bounded_core_rules():
    _,_,style,_,_=fixture(background='#777777',category='unknown_category')
    assert style.treatments['text']=='SOFT_TONAL_FIELD'
    assert style.category['id']=='general'
    assert all(0<t['support_alpha']<=.36 for t in style.typography)
