"""Local geometry/alpha fixtures only; no scene provider is ever contacted."""
import hashlib
import io

import pytest
from PIL import Image, ImageChops, ImageDraw

from app.schemas.creative_bridge import HannaCreativePackage
from app.schemas.locked_scene import LockedSceneConfig, SceneEditAssets
from app.services.creative_delivery import prepare_delivery
from app.services.hanna_creative_package import image_record
from app.services.locked_scene import (canonical_product_layer, resolve_locked_delivery, scene_layers,
    write_scene_assets, validate_scene_assets, restore_after_crop, require_product_integrity, dilate)
from test_build6r_v101_creative_package import package


def scene_fixture(tmp_path, *,config=None):
    p=package(tmp_path)
    root=tmp_path/"approved_product_masters"
    root.mkdir()
    master=root/"canonical.png"
    image=Image.new("RGBA",(140,200))
    draw=ImageDraw.Draw(image)
    draw.polygon(((25,10),(115,10),(135,40),(125,185),(15,185),(5,40)),fill=(90,20,140,255))
    draw.ellipse((62,13,78,29),fill=(0,0,0,0))  # actual silhouette hole, not a rectangular mask
    draw.text((40,70),"EX / 7",fill="white")
    image.save(master)
    record=image_record(asset_id="master",role="product_master",path=master,
        expected_sha256=hashlib.sha256(master.read_bytes()).hexdigest(),authority="canonical owner-approved fixture",
        provenance={"source_asset_id":"source"})
    logo_path=tmp_path/"logo-alpha.png"
    logo=Image.new("RGBA",(200,100))
    draw=ImageDraw.Draw(logo)
    draw.ellipse((70,5,130,55),fill=(200,100,130,255))
    draw.text((30,65),"HANNA JAPAN",fill=(25,25,25,255))
    logo.save(logo_path)
    logo_record=image_record(asset_id="logo",role="logo",path=logo_path,
        expected_sha256=hashlib.sha256(logo_path.read_bytes()).hexdigest(),authority="canonical fixture logo",provenance={"brand_id":"brand"})
    p=HannaCreativePackage.model_validate({**p.model_dump(),"images":tuple(logo_record if a.role=="logo" else a for a in p.images)+(record,)})
    delivery=resolve_locked_delivery(prepare_delivery(p))
    plan,layer=canonical_product_layer(delivery,master_asset_id="master",config=config)
    assets=write_scene_assets(plan,layer,tmp_path)
    return assets,layer


def native_fixture(color=(24,23,22), *, size=(1024,1536)):
    buffer=io.BytesIO()
    Image.new("RGB",size,color).save(buffer,"PNG")
    return buffer.getvalue()


def test_precomputed_product_has_canonical_geometry_and_real_alpha(tmp_path):
    assets,layer=scene_fixture(tmp_path)
    plan=assets.plan
    assert layer.size==(1024,1536)
    assert plan.final_product_box[2]-plan.final_product_box[0]==471
    assert plan.native_product_box[1]==plan.final_product_box[1]+128
    assert plan.native_product_box[3]==plan.final_product_box[3]+128
    assert plan.final_product_box[3]==1140
    alpha=layer.getchannel("A")
    box=alpha.getbbox()
    assert alpha.crop(box).getextrema()==(0,255)  # silhouette/hole retained
    assert sum(alpha.histogram()[1:255])>0  # resampling alpha edges, no alpha-squared paste
    assert validate_scene_assets(assets)[0].tobytes()==layer.tobytes()


def test_protection_environment_mask_and_grounding_ring_are_distinct(tmp_path):
    assets,layer=scene_fixture(tmp_path)
    layers=scene_layers(assets.plan,layer)
    product=layer.getchannel("A").point(lambda n:255 if n else 0)
    protected=layers["protection-mask"]
    ring=layers["grounding-ring"]
    assert ring.getbbox() and ImageChops.multiply(product,ring).getbbox() is None
    assert layers["environment-mask"].getchannel("A").tobytes()==protected.tobytes()
    assert ImageChops.subtract(product,protected).getbbox() is None
    assert protected.getbbox()!=product.getbbox()
    assert layers["environment-mask"].getpixel((0,0))[3]==0


@pytest.mark.parametrize("radius",[0,1,2,4,7,10])
def test_exact_dilation_has_no_wraparound(radius):
    from PIL import ImageFilter
    image=Image.new("L",(40,40))
    image.putpixel((0,0),255)
    image.putpixel((20,20),255)
    expected=image.filter(ImageFilter.MaxFilter(radius*2+1)) if radius else image
    assert dilate(image,radius).tobytes()==expected.tobytes()


def test_restoration_ignores_changed_generated_product_and_preserves_ring(tmp_path):
    assets,layer=scene_fixture(tmp_path)
    scene,restored,final_layer,ring=restore_after_crop(assets,native_fixture((200,150,20)))
    assert restored.size==(1024,1280)
    assert require_product_integrity(restored,scene,final_layer,ring)["canonical_product_layer_integrity"]=="PASS"
    expected=Image.alpha_composite(scene,final_layer)
    assert restored.tobytes()==expected.tobytes()
    x,y=next((x,y) for y in range(1280) for x in range(1024) if ring.getpixel((x,y)))
    assert restored.getpixel((x,y))==scene.getpixel((x,y))


@pytest.mark.parametrize("kind",["product","ring"])
def test_pixel_integrity_and_grounding_tampering_fail(tmp_path,kind):
    assets,_=scene_fixture(tmp_path)
    scene,restored,layer,ring=restore_after_crop(assets,native_fixture())
    mask=layer.getchannel("A") if kind=="product" else ring
    x,y=next((x,y) for y in range(1280) for x in range(1024) if mask.getpixel((x,y))==255)
    restored.putpixel((x,y),(255,0,0,255))
    with pytest.raises(ValueError,match="integrity|ring"):
        require_product_integrity(restored,scene,layer,ring)


def test_changed_asset_bytes_fail_before_request(tmp_path):
    assets,_=scene_fixture(tmp_path)
    from pathlib import Path
    Path(assets.environment_mask.path).write_bytes(b"tampered")
    with pytest.raises(ValueError,match="changed"):
        validate_scene_assets(assets)


@pytest.mark.parametrize("config",[dict(protection_margin=-1),dict(grounding_width=0),dict(protection_margin=24,grounding_width=24)])
def test_unsafe_margin_configuration_fails(config):
    with pytest.raises(ValueError):
        LockedSceneConfig(**config)


def test_unknown_master_and_generated_text_mode_cannot_enter_v11(tmp_path):
    p=package(tmp_path)
    with pytest.raises(ValueError,match="deterministic"):
        resolve_locked_delivery(prepare_delivery(p,text_mode="model_integrated"))
    with pytest.raises(ValueError,match="canonical product master"):
        canonical_product_layer(resolve_locked_delivery(prepare_delivery(p)),master_asset_id="source")


def test_product_logo_and_text_all_survive_prepared_crop(tmp_path):
    assets,_=scene_fixture(tmp_path)
    guide=assets.plan.delivery.guide
    for l,t,r,b in [assets.plan.final_product_box,guide.logo_region,guide.headline_region,guide.cta_region]:
        assert 0<=l<r<=1024 and 0<=t<b<=1280
        assert 128<=t+128<b+128<=1408


def test_transparent_holes_and_every_exterior_pixel_retain_generated_scene(tmp_path):
    assets,_=scene_fixture(tmp_path)
    scene,restored,layer,ring=restore_after_crop(assets,native_fixture((33,88,144)))
    outside=layer.getchannel("A").point(lambda n:255 if n==0 else 0)
    diff=ImageChops.difference(scene.convert("RGB"),restored.convert("RGB"))
    assert all(ImageChops.multiply(channel,outside).getbbox() is None for channel in diff.split())
