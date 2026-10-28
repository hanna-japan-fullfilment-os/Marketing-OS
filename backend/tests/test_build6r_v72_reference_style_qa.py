"""Policy mutations use synthetic observations; no visual-acceptance claim."""
import copy
import base64
from dataclasses import replace
import hashlib
import io
import json

from PIL import Image, ImageDraw
import pytest

from test_build6r_v72_premium_composition import context, product
from app.services.creative.composition import (
    Box, HARD_RULES, STYLE_WEIGHTS, evaluate_composition, resolve_composition,
)
from app.services.creative.qa import run_creative_qa, raster_composition_metrics
from app.services.creative.renderer import RenderDiagnostics
from app.services.creative.templates import Feature


def fixture():
    spec = resolve_composition(context(features=[Feature(title="7 máscaras")], cta="Saiba mais",
                                      logo_data_uri="data:image/png;base64,fixture"), product())
    observed = dict(spec_sha256=spec.digest, canvas=[1080,1350], images_ready=True, fonts_ready=True,
                    logo=spec.logo.__dict__, roles=[])
    for r in spec.roles:
        observed["roles"].append(dict(key=r.key, box=r.box.__dict__, font_px=r.font_px,
            lines=1, overflow=False, resolved_font="Arial",
            ink_boxes=[dict(x=r.box.x+4,y=r.box.y+4,width=200,height=r.font_px)],
            foreground=["#ffffff"], background="rgba(10, 5, 20, 0.82)"))
    visual = dict(minimum_contrast=10, dark_fraction=.75, product_separation=20)
    return spec, observed, visual


def product_mask(spec):
    mask = Image.new("L", (spec.width,spec.height))
    p = spec.product
    ImageDraw.Draw(mask).rectangle((p.x,p.y,p.right-1,p.bottom-1),fill=255)
    return mask


def test_complete_synthetic_measurements_pass_and_weights_match_audit():
    spec, obs, visual = fixture()
    result = evaluate_composition(spec, obs, visual)
    assert result["passed"] and result["score"] == 100
    assert result["threshold"] == 85 and result["subscore_minimum"] == 70
    assert STYLE_WEIGHTS == dict(product=20, typography=20, alignment=15, density=15,
                                 palette_contrast=10, brand_cta=10, art_separation=10)
    assert len(HARD_RULES) == 20 and not result["visual_acceptance"]


@pytest.mark.parametrize("field,value,rule", [
    ("overflow",True,"text_overflow"), ("font_px",10,"minimum_type"),
    ("lines",100,"line_count"), ("lines",0,"complete_measurements"),
    ("font_px",float('nan'),"complete_measurements"),
])
def test_bad_typography_is_hard_failure(field, value, rule):
    spec, obs, visual = fixture()
    obs["roles"][0][field] = value
    result = evaluate_composition(spec, obs, visual)
    assert not result["passed"] and rule in result["hard_failures"]


@pytest.mark.parametrize("key,value,rule", [
    ("images_ready",False,"asset_readiness"), ("fonts_ready",False,"font_readiness"),
    ("canvas",[1,1],"canvas"), ("roles",[],"role_inventory"),
    ("logo",None,"required_logo"), ("spec_sha256","stale","complete_measurements"),
])
def test_missing_or_stale_observations_fail_closed(key,value,rule):
    spec, obs, visual = fixture()
    obs[key] = value
    assert rule in evaluate_composition(spec, obs, visual)["hard_failures"]


@pytest.mark.parametrize("box,rule", [
    (Box(-1,100,200,100),"edge_bounds"), (Box(1,100,200,100),"safe_margins"),
    (Box(600,700,200,100),"product_collision"), (Box(500,500,30,100),"negative_space"),
])
def test_spacing_and_product_exclusions(box,rule):
    spec, obs, visual = fixture()
    obs["roles"][0]["box"] = box.__dict__
    assert rule in evaluate_composition(spec,obs,visual)["hard_failures"]


def test_cta_logo_text_overlap_and_crowding_rejected():
    spec, obs, visual = fixture()
    obs["roles"][-1]["box"] = obs["logo"]
    assert "role_spacing" in evaluate_composition(spec,obs,visual)["hard_failures"]
    spec, obs, visual = fixture()
    obs["roles"][-1]["box"] = obs["roles"][0]["box"]
    assert "role_spacing" in evaluate_composition(spec,obs,visual)["hard_failures"]


@pytest.mark.parametrize("p,rule", [(Box(600,650,20,600),"product_scale"),
                                    (Box(600,650,500,800),"product_bounds"),
                                    (Box(40,800,460,480),"product_collision")])
def test_product_scale_crop_and_collision(p,rule):
    spec, obs, visual = fixture()
    spec = replace(spec,product=p)
    obs["spec_sha256"] = spec.digest
    assert rule in evaluate_composition(spec,obs,visual)["hard_failures"]


def test_missing_cta_and_weak_hierarchy_fail():
    spec, obs, visual = fixture()
    obs["roles"] = [o for o in obs["roles"] if o["key"] != "cta"]
    assert "required_cta" in evaluate_composition(spec,obs,visual)["hard_failures"]
    spec, obs, visual = fixture()
    obs["roles"][0]["font_px"] = 40
    assert "hierarchy" in evaluate_composition(spec,obs,visual)["hard_failures"]


def test_soft_failures_cannot_be_averaged_into_pass():
    spec, obs, visual = fixture()
    visual["product_separation"] = 8  # 67, below required subscore70 despite total>85.
    result = evaluate_composition(spec,obs,visual)
    assert not result["hard_failures"] and result["score"] > 85
    assert result["style_failures"] == ["art_separation"] and not result["passed"]


@pytest.mark.parametrize("separation,passed", [(8.4,True),(8.28,False)])
def test_style_subscore_boundary_is_inclusive(separation,passed):
    spec, obs, visual = fixture()
    visual["product_separation"] = separation
    assert evaluate_composition(spec,obs,visual)["passed"] is passed


def test_reported_overflow_false_cannot_hide_glyph_outside_box():
    spec, obs, visual = fixture()
    obs["roles"][0]["ink_boxes"][0]["x"] = -50
    assert "text_overflow" in evaluate_composition(spec,obs,visual)["hard_failures"]


def test_resolved_unapproved_font_fails_even_if_fonts_ready():
    spec, obs, visual = fixture()
    obs["roles"][0]["resolved_font"] = "Unknown substitution"
    assert "font_readiness" in evaluate_composition(spec,obs,visual)["hard_failures"]


def test_governed_technical_qa_cannot_skip_missing_report(tmp_path):
    from types import SimpleNamespace
    from app.services.creative.pipeline import build_render_context_path
    from app.services.qa_engine import run_technical_qa
    from app.data.platform_creative_specs import resolve_platform_creative_spec
    path = tmp_path/"synthetic.png"
    Image.new("RGB",(1080,1350)).save(path)
    build_render_context_path(path).write_text(json.dumps({
        "reference_target":context().reference_target.model_dump()}),encoding="utf-8")
    variant = SimpleNamespace(slide_asset_paths=[str(path)],qa_report_paths=[],creative_direction={})
    platform = resolve_platform_creative_spec("instagram","carousel")
    result = run_technical_qa(variant,platform)
    assert not result.passed and result.checks["slide_1_premium_composition"] is False


@pytest.mark.parametrize("metric,value", [("minimum_contrast",float('nan')),
                                         ("dark_fraction",2), ("product_separation",-1)])
def test_invalid_raster_measurements_fail_closed(metric,value):
    spec, obs, visual = fixture()
    visual[metric] = value
    assert "complete_measurements" in evaluate_composition(spec,obs,visual)["hard_failures"]


def test_local_contrast_and_palette_are_measured_not_inferred_from_spec():
    spec, obs, _ = fixture()
    image = Image.new("RGB", (1080,1350), "#100820")
    ImageDraw.Draw(image).rectangle((572,650,1036,1279), fill="#cc88ff")
    metrics = raster_composition_metrics(spec,obs,image,product_mask(spec))
    assert metrics["minimum_contrast"] > 4.5 and metrics["product_separation"] > 12
    obs["roles"][0]["foreground"] = ["#100820"]
    assert raster_composition_metrics(spec,obs,image,product_mask(spec))["minimum_contrast"] < 4.5


def test_missing_diagnostics_cannot_pass_mechanical_qa():
    spec, _, _ = fixture()
    out = io.BytesIO(); Image.new("RGB",(1080,1350)).save(out,format="PNG")
    result = run_creative_qa(png_bytes=out.getvalue(),expected_width=1080,expected_height=1350,
        diagnostics=RenderDiagnostics(False,False),logo_expected=False,logo_included=False,
        composition_spec=spec,base_image=Image.new("RGB",(1080,1350)))
    assert not result.passed and result.composition["score"] is None


def test_report_validation_recomputes_policy_and_binds_actual_render():
    from app.services.qa_engine import validate_premium_composition_report
    spec, obs, visual = fixture()
    result = evaluate_composition(spec,obs,visual)
    result["render_sha256"] = "b"*64
    data = dict(passed=True,composition=result)
    ctx = dict(composition_spec=spec.to_dict(),composition_spec_sha256=spec.digest,
               reference_target=context().reference_target.model_dump(),
               render_sha256="b"*64)
    # JSON serialization normalizes tuples before persisted reports are checked.
    data, ctx = json.loads(json.dumps(data)), json.loads(json.dumps(ctx))
    validate_premium_composition_report(data,ctx,"b"*64,required=True)
    for change in ("score","render_sha256","spec_sha256","version"):
        bad = copy.deepcopy(data); bad["composition"][change] = "invalid"
        with pytest.raises(ValueError,match="premium composition"):
            validate_premium_composition_report(bad,ctx,"b"*64,required=True)
    with pytest.raises(ValueError):
        validate_premium_composition_report({}, {}, "b"*64, required=True)
    validate_premium_composition_report({}, {}, "b"*64)  # Legacy non-reference report.


@pytest.mark.asyncio
@pytest.mark.parametrize("long_copy", [False, True])
async def test_real_browser_measurements_on_synthetic_local_fixture(long_copy):
    """Exercise actual layout/raster diagnostics, never a campaign/provider run."""
    from app.services.creative.renderer import PlaywrightRenderer
    from app.services.creative.templates import get_template
    image = Image.new("RGB", (1080,1350), "#100820")
    ImageDraw.Draw(image).rectangle((572,650,1036,1279), fill="#cc88ff")

    def uri(im):
        out = io.BytesIO(); im.save(out,format="PNG")
        return "data:image/png;base64," + base64.b64encode(out.getvalue()).decode()

    ctx = context(features=[Feature(title="7 máscaras")], cta="Saiba mais",
                  composited_image_data_uri=uri(image), logo_data_uri=uri(Image.new("RGB",(30,10),"white")),
                  headline="Informação e atenção: " * 40 if long_copy else "Conheça")
    spec = resolve_composition(ctx, product())
    html = get_template("feature_showcase").build_html(replace(ctx,composition_spec=spec))
    renderer = PlaywrightRenderer()
    try:
        png, diag = await renderer.render_png_with_diagnostics(html=html,width=1080,height=1350)
    finally:
        await renderer.close()
    assert diag.composition and diag.composition["images_ready"]
    assert diag.composition["fonts_ready"]
    result = run_creative_qa(png_bytes=png,expected_width=1080,expected_height=1350,
        diagnostics=diag,logo_expected=True,logo_included=True,composition_spec=spec,base_image=image,
        product_alpha=product_mask(spec))
    if long_copy:
        assert not result.passed
        assert "text_overflow" in result.composition["hard_failures"]
    else:
        assert result.passed, json.dumps([r for r in diag.composition["roles"] if r["overflow"]])


def test_v74_separation_samples_opaque_silhouette_not_transparent_envelope():
    spec, obs, _ = fixture()
    image = Image.new("RGB",(1080,1350),"#100820")
    mask = Image.new("L",image.size)
    # Deliberately transparent margins inside the declared product envelope.
    actual = (600,680,1010,1250)
    ImageDraw.Draw(image).rectangle(actual,fill="#cc88ff")
    ImageDraw.Draw(mask).rectangle(actual,fill=255)
    result = raster_composition_metrics(spec,obs,image,mask)
    assert result["product_separation"] > 12
    assert len(result["edge_samples"]) == 10
    assert all(s["alpha"] >= 128 for s in result["edge_samples"])
    with pytest.raises(ValueError,match="alpha"):
        raster_composition_metrics(spec,obs,image)
    with pytest.raises(ValueError,match="opaque"):
        raster_composition_metrics(spec,obs,image,Image.new("L",image.size))


def test_v74_safe_product_envelope_does_not_waive_collisions():
    spec, obs, visual = fixture()
    p = Box(551,648,497,662)
    spec = resolve_composition(context(features=[Feature(title="7 máscaras")],cta="Saiba mais",
        logo_data_uri="data:image/png;base64,fixture"),p,product_safe=Box(32,299,1016,1011))
    obs["spec_sha256"] = spec.digest
    assert evaluate_composition(spec,obs,visual)["passed"]
    obs["roles"][1]["box"] = Box(600,700,300,100).__dict__
    assert "product_collision" in evaluate_composition(spec,obs,visual)["hard_failures"]
    spec, obs, visual = fixture()
    spec = replace(spec,product=p)  # No locked envelope: old generic inset still fails.
    obs["spec_sha256"] = spec.digest
    assert "product_bounds" in evaluate_composition(spec,obs,visual)["hard_failures"]


@pytest.mark.asyncio
@pytest.mark.parametrize("fact,lines", [
    ("Embalagem com 7 máscaras.",2),
    ("Embalagem com 7 máscaras e 150 mL de essência.",3),
])
async def test_v74_real_wrapping_and_palette_keyline(fact,lines):
    from app.schemas.creative_director import ReferenceTarget
    from app.services.creative.templates import get_template
    from app.services.creative.renderer import PlaywrightRenderer
    image = Image.new("RGB",(1080,1350),"#14051F")
    ImageDraw.Draw(image).rectangle((572,650,1036,1279),fill="#cc88ff")
    data=io.BytesIO();image.save(data,format="PNG")
    ctx=context(features=[Feature(title=fact)],composited_image_data_uri=
        "data:image/png;base64,"+base64.b64encode(data.getvalue()).decode())
    raw=ctx.reference_target.model_dump()
    raw['grammar']['typography']='condensed'
    raw['grammar']['headline_paint']=dict(kind="linear_gradient",angle_degrees=90,
        stops=[dict(offset=0,color="#704394"),dict(offset=.5,color="#F6E4FF"),dict(offset=1,color="#7F36AF")],
        stroke_color="#2F133F",stroke_width_px=.5,shadow_color="#14051F",shadow_blur_px=5,
        shadow_offset_y_px=2)
    raw['grammar']['icon_paint']=dict(kind="luminous_vector",tint="#F3D9FF",glow_color="#A845FF",
        glow_opacity=.85,glow_radius_px=8,stroke_width_px=1.2,ring_width_px=1,size_scale=1.25)
    ctx=replace(ctx,reference_target=ReferenceTarget.model_validate(raw))
    spec=resolve_composition(ctx,product())
    html=get_template('feature_showcase').build_html(replace(ctx,composition_spec=spec))
    assert '::before' in html and 'data-ink="Conheça"' in html
    renderer=PlaywrightRenderer()
    try:
        png,diag=await renderer.render_png_with_diagnostics(html=html,width=1080,height=1350)
    finally:
        await renderer.close()
    observed=next(r for r in diag.composition['roles'] if r['key']=='feature_0')
    assert observed['lines']==lines and not observed['overflow']
    result=run_creative_qa(png_bytes=png,expected_width=1080,expected_height=1350,
        diagnostics=diag,logo_expected=False,logo_included=False,composition_spec=spec,
        base_image=image,product_alpha=product_mask(spec))
    assert result.passed,result.to_dict()
    assert result.composition['threshold']==85 and result.composition['score']>=85
    # Removing the physically rendered keyline from its observation cannot earn
    # a contrast pass. Neither the 4.5 contrast rule nor weights are lowered.
    plain=copy.deepcopy(diag.composition)
    head=next(r for r in plain['roles'] if r['key']=='headline')
    assert head['foreground']['outline']['color']=='#F6E4FF'
    head['foreground']=head['foreground']['fills']
    assert raster_composition_metrics(spec,plain,image,product_mask(spec))['minimum_contrast']<4.5
    pixels=Image.open(io.BytesIO(png)).convert('RGB').crop((40,100,520,250)).tobytes()
    assert sum(1 for i in range(0,len(pixels),3) if pixels[i]>220 and pixels[i+1]>190 and pixels[i+2]>230)>20
