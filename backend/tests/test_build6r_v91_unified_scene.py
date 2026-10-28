"""Pure scene contracts; synthetic geometry is never visual acceptance."""
from dataclasses import replace
import json

import pytest

from app.services.creative.composition import Box, LayoutSpec, evaluate_composition
from app.services.creative.scene import (
    ARCHETYPES, DEPTH_ORDER, CanonicalSceneAsset, Relationship,
    compose_unified_scene, select_archetype,
)
from app.services.creative.templates import Feature, get_template
from test_build6r_v72_premium_composition import context


def asset():
    return CanonicalSceneAsset('canonical-fixture','a'*64,'fixture.png',(0,0,400,800))


def scene(ctx=None, product=None):
    return compose_unified_scene(ctx or context(), product or Box(551,648,497,662),
        canonical_asset=asset(), background_identity='fixture-background',
        product_safe=Box(30,280,1020,1030))


@pytest.mark.parametrize('product', [Box(551,648,497,662), Box(260,900,600,300),
                                   Box(600,850,400,400)])
@pytest.mark.parametrize('rich', [False, True])
def test_tall_wide_compact_sparse_and_rich_are_deterministic(product,rich):
    ctx=context(body='Informação aprovada' if rich else '',
                features=[Feature(title='Fato aprovado'),Feature(title='Outro fato')] if rich else [])
    a,b=scene(ctx,product),scene(ctx,product)
    assert a.to_dict()==b.to_dict() and a.digest==b.digest
    assert a.layout.product==product and a.canonical_asset==asset()
    assert a.product['width_fraction']==product.width/1080
    assert LayoutSpec.from_dict(json.loads(json.dumps(a.layout.to_dict()))).digest==a.layout.digest
    a.validate_relationships()
    assert a.composition['visual_acceptance'] is False


def test_required_domains_and_real_asset_are_separate():
    s=scene(context(features=[Feature(title='7 máscaras')],cta='Saiba mais'))
    assert set(s.to_dict())=={'version','archetype','layout','canonical_asset','relationships',
        'canvas','product','typography','brand','environment','composition','depth_layers','selection_inputs'}
    assert s.canvas['safe_area'] and s.canvas['composition_axis'] and s.canvas['focal_point']
    assert s.canonical_asset.sha256=='a'*64
    assert s.product['asset_policy']=='canonical_pixels_only'
    assert s.environment['background_layer']['identity']=='fixture-background'
    assert s.product['grounding_region'] and s.product['contact_shadow']['rendered'] is False
    assert s.product['ambient_shadow'] and s.product['halo'] and s.product['grounding_plane']
    assert tuple(d['name'] for d in s.depth_layers)==DEPTH_ORDER
    assert len(s.depth_layers)==5 and s.environment['shadow_direction']=='lower_right'
    assert s.environment['product_illumination_zone']==s.product['box']
    assert s.environment['text_contrast_zones'] and s.environment['background_falloff']
    assert {z['role'] for z in s.composition['negative_space_zones']}=={
        'headline','cta','logo','product_breathing_room'}
    assert len(s.composition['cohesion_links'])==6


@pytest.mark.parametrize('changes,expected', [
    ({'copy_characters':300},'EDITORIAL_HERO'),
    ({'callout_count':3},'EDITORIAL_HERO'),
    ({'aspect_ratio':2},'PRODUCT_SPOTLIGHT'),
    ({'slide_role':'feature_detail'},'DIAGONAL_FLOW'),
    ({},'ATMOSPHERIC_PRODUCT_STAGE'),
    ({'reference_depth':'flat'},'EDITORIAL_HERO'),
])
def test_reference_evidence_archetypes_are_bounded_and_selected_deterministically(changes,expected):
    inputs=dict(slide_role='cover',aspect_ratio=.6,copy_characters=40,callout_count=1,reference_depth='layered')
    inputs.update(changes)
    assert len(ARCHETYPES)==4
    assert select_archetype(**inputs)==select_archetype(**inputs)==expected


def test_relation_solver_tracks_changed_product_and_detects_stale_geometry():
    a=scene();b=scene(product=Box(520,650,480,630))
    assert a.layout.logo.x!=b.layout.logo.x
    assert a.relationships and any(r.anchor=='product' for r in a.relationships)
    stale=replace(a,layout=replace(a.layout,logo=Box(1,1,100,30)))
    with pytest.raises(ValueError,match='Unresolved'):stale.validate_relationships()
    with pytest.raises(ValueError):Relationship('logo','product','z','right',0).resolve({'product':a.layout.product})


def test_copy_fields_preserved_and_sparse_scene_does_not_fill_slots():
    ctx=context(headline='Água e atenção!',features=[Feature(title='7 máscaras')])
    s=scene(ctx)
    assert [(r.key,r.text,r.field_paths) for r in s.layout.roles]==[
        ('headline','Água e atenção!',('headline',)),
        ('feature_0','7 máscaras',('features[0].icon','features[0].title','features[0].subtitle'))]
    assert not s.layout.cta_required
    assert 'without_new_copy' in s.composition['sparse_strategy']
    assert s.typography['opaque_rectangular_panel_required'] is False
    assert s.brand['logo_treatment']['mode']!='white_tile'


def test_premium_template_consumes_same_scene_and_transparent_text_support():
    ctx=context(headline='<b>Água</b>')
    s=scene(ctx)
    html=get_template('feature_showcase').build_html(replace(ctx,composition_spec=s.layout,unified_scene=s))
    assert 'background-color:rgba(0,0,0,0)' in html
    assert 'id="unified-scene-spec"' in html and s.digest in html and s.layout.digest in html
    assert '&lt;b&gt;Água&lt;/b&gt;' in html
    with pytest.raises(ValueError,match='mismatch'):
        get_template('feature_showcase').build_html(replace(ctx,composition_spec=replace(s.layout,sparse=False),unified_scene=s))


def test_existing_qa_consumes_scene_geometry_without_weaker_policy():
    from test_build6r_v72_reference_style_qa import fixture
    old,obs,visual=fixture()
    s=scene(context(features=[Feature(title='7 máscaras')],cta='Saiba mais',logo_data_uri='fixture'),old.product)
    # Deliberately synthetic observations; actual renderer measurements remain mandatory.
    obs.update(spec_sha256=s.layout.digest,logo=s.layout.logo.__dict__)
    for o,r in zip(obs['roles'],s.layout.roles):
        o.update(box=r.box.__dict__,ink_boxes=[dict(x=r.box.x+4,y=r.box.y+4,width=200,height=r.font_px)])
    result=evaluate_composition(s.layout,obs,visual)
    assert result['passed'] and len(result['hard_checks'])==20 and not result['visual_acceptance']
    obs['roles'][0]['overflow']=True
    assert 'text_overflow' in evaluate_composition(s.layout,obs,visual)['hard_failures']
    obs['spec_sha256']='stale'
    assert not evaluate_composition(s.layout,obs,visual)['passed']


@pytest.mark.parametrize('change', [{'sha256':'bad'},{'asset_id':''},{'source_crop':(0,0,0,1)}])
def test_invalid_asset_identity_never_becomes_scene_authority(change):
    with pytest.raises(ValueError):replace(asset(),**change)


def test_provider_names_do_not_enter_scene_contract():
    raw=json.dumps(scene().to_dict()).lower()
    assert not any(p in raw for p in ('openai','comfyui','sunburst','flare','gpt-image'))
