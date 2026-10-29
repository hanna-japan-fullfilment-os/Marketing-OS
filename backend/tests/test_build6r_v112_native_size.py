"""Exact native-size compatibility only; all live calls remain prohibited in tests."""
import io

import pytest
from PIL import Image

from app.schemas.locked_scene import NativeSunburstSettings, NativePreparedDelivery, SceneEditAssets
from app.services.locked_scene import (native_final_size_delivery,canonical_product_layer,
    write_scene_assets,restore_scene,require_product_integrity)
from app.services.locked_scene_overlay import finish_locked_scene
from app.services.ai.openai_provider import direct_images_edit_request,OpenAIProvider,HardBudgetExceededError
from test_build6r_v111_locked_scene import scene_fixture,native_fixture
from test_build6r_v111_locked_scene_delivery import FONTS


def native_assets(tmp_path):
    legacy,old_layer=scene_fixture(tmp_path)
    delivery=native_final_size_delivery(legacy.plan.delivery)
    plan,layer=canonical_product_layer(delivery,master_asset_id=legacy.plan.master_asset_id,config=legacy.plan.config)
    output=tmp_path/"native"
    output.mkdir()
    return write_scene_assets(plan,layer,output),legacy,layer,old_layer


@pytest.mark.parametrize("size",["1024x1280","1536x864","2048x1152","1024x1536"])
def test_official_arbitrary_size_strings_accepted(size):
    assert NativeSunburstSettings(size=size).size==size


@pytest.mark.parametrize("size",["1025x1280","1024x1279","256x1280","0x1280","auto","4000x1280","128x128"])
def test_invalid_divisibility_aspect_pixel_or_edge_limit_rejected(size):
    with pytest.raises(ValueError):
        NativeSunburstSettings(size=size)


def test_native_geometry_masks_and_request_have_no_crop_offset(tmp_path):
    assets,legacy,layer,old=native_assets(tmp_path)
    plan=assets.plan
    assert isinstance(plan.delivery,NativePreparedDelivery)
    assert plan.delivery.guide.final_crop is None
    assert plan.native_product_box==plan.final_product_box==legacy.plan.final_product_box
    assert layer.size==(1024,1280)
    assert layer.tobytes()==old.crop(legacy.plan.delivery.guide.final_crop).tobytes()
    for image in (assets.base,assets.environment_mask,assets.protection_mask,assets.grounding_ring):
        assert (image.width,image.height)==(1024,1280)
    request=direct_images_edit_request(plan.delivery,scene_edit=assets)
    assert request["size"]=="1024x1280"
    assert "1024x1536" not in request["prompt"] and "ADD 128" not in request["prompt"]
    assert "FINAL_1024x1280" in request["prompt"]
    assert len(request["image"])==4 and request["image"][0][0]=="0_LOCKED_PRODUCT_BASE.png"
    with Image.open(io.BytesIO(request["mask"][1])) as mask:
        assert mask.size==(1024,1280)
    assert SceneEditAssets.model_validate(assets.model_dump())==assets


def test_native_finalization_never_crops_or_resizes_output_canvas(tmp_path,monkeypatch):
    assets,_,_,_=native_assets(tmp_path)
    crop,resize=Image.Image.crop,Image.Image.resize
    def reject_canvas_crop(image,*args,**kwargs):
        if image.size==(1024,1280) and image.mode in ("RGB","RGBA"):
            raise AssertionError("native canvas must not be cropped")
        return crop(image,*args,**kwargs)
    def reject_canvas_resize(image,*args,**kwargs):
        if image.size==(1024,1280) and image.mode in ("RGB","RGBA"):
            raise AssertionError("native canvas must not be resized")
        return resize(image,*args,**kwargs)
    monkeypatch.setattr(Image.Image,"crop",reject_canvas_crop)
    monkeypatch.setattr(Image.Image,"resize",reject_canvas_resize)
    # L-mode mask inspections are not output reframing. Full-color native
    # output transforms are forbidden while the real finalizer runs.
    final,qa=finish_locked_scene(assets,native_fixture(size=(1024,1280)),fonts=FONTS)
    assert qa["compositing_order"][0]=="native_final_scene"
    with Image.open(io.BytesIO(final)) as image:
        assert image.size==(1024,1280)


def test_native_restore_and_all_precision_layers_pass_at_final_size(tmp_path):
    assets,_,_,_=native_assets(tmp_path)
    data=native_fixture((255,255,255),size=(1024,1280))
    final,qa=finish_locked_scene(assets,data,fonts=FONTS)
    with Image.open(io.BytesIO(final)) as image:
        assert image.size==(1024,1280)
        scene,_,layer,ring=restore_scene(assets,data)
        assert require_product_integrity(image.convert("RGBA"),scene,layer,ring)["grounding_ring_preserved"]
    assert qa["compositing_order"][0]=="native_final_scene"
    assert qa["logo"]["rendered_after_crop"] is False
    assert qa["logo"]["rendered_in_final_coordinates"]
    assert all(row["final_contrast"]>=4.5 for row in qa["text"])
    assert qa["text_product_overlap_count"]==0


@pytest.mark.asyncio
async def test_native_size_does_not_override_normal_cost_guard(tmp_path):
    assets,_,_,_=native_assets(tmp_path)
    provider=OpenAIProvider(api_key=None,hard_budget_usd=.5)
    with pytest.raises(HardBudgetExceededError,match="UNKNOWN_MULTIMODAL"):
        await provider.compose_direct_creative(delivery=assets.plan.delivery,scene_edit=assets)
    assert provider._client is None
