"""V10 failure-class guards and existing-adapter reuse, always zero-provider."""
import io
import json
from pathlib import Path

import pytest
from PIL import Image

from app.schemas.locked_scene import SceneEditAssets
from app.services.ai.openai_provider import OpenAIProvider, direct_images_edit_request, HardBudgetExceededError
from app.services.locked_scene import generate_locked_scene, validate_scene_assets, require_product_integrity, restore_after_crop
from app.services.locked_scene_overlay import finish_locked_scene
from test_build6r_v111_locked_scene import scene_fixture, native_fixture

FONTS={"hanna_headline":Path("C:/Windows/Fonts/arial.ttf"),"hanna_body":Path("C:/Windows/Fonts/arial.ttf")}


def test_existing_edit_adapter_receives_base_first_actual_mask_and_labeled_context(tmp_path):
    assets,_=scene_fixture(tmp_path)
    request=direct_images_edit_request(assets.plan.delivery,scene_edit=assets)
    assert request["image"][0][0]=="0_LOCKED_PRODUCT_BASE.png"
    assert request["mask"][0]=="environment-mask.png"
    assert len(request["image"])==4
    assert "LOCKED_PRODUCT_BASE" in request["prompt"] and "grounding_width" in request["prompt"]
    assert "Generate NO final headline" in request["prompt"]
    payload=json.loads(request["prompt"].rsplit("\n",1)[1])
    assert payload["image_roles"][0]["image_index"]==1
    assert payload["image_roles"][1]["image_index"]==2
    assert payload["image_roles"][1]["role"]=="PRODUCT_REFERENCE"
    with Image.open(io.BytesIO(request["mask"][1])) as image:
        assert image.mode=="RGBA" and image.size==(1024,1536)


@pytest.mark.parametrize("background",[(255,255,255),(24,23,22),(200,170,210)])
def test_final_contrast_uses_actual_scene_and_product_is_still_exact(tmp_path,background):
    assets,_=scene_fixture(tmp_path)
    native=native_fixture(background)
    data,qa=finish_locked_scene(assets,native,fonts=FONTS)
    with Image.open(io.BytesIO(data)) as image:
        assert image.size==(1024,1280)
        scene,_,layer,ring=restore_after_crop(assets,native)
        assert require_product_integrity(image.convert("RGBA"),scene,layer,ring)["grounding_ring_preserved"]
    assert all(t["final_contrast"]>=4.5 for t in qa["text"])
    assert all(t["tonal_fade_opacity"]==0 for t in qa["text"]) if background==(24,23,22) else True
    assert any(t["tonal_fade_opacity"]>0 for t in qa["text"]) if background==(255,255,255) else True
    assert qa["logo"]["rendered_after_crop"] and qa["logo"]["final_logo_box"][3]<=1240
    assert qa["compositing_order"]==["final_crop","canonical_product_restore","deterministic_text","deterministic_logo","canonical_cta","QA"]
    assert qa["text_product_overlap_count"]==0 and not qa["generic_rectangular_panel_fallback"]
    assert qa["deterministic_shadow_added"] is False


def test_v10_generated_product_and_cropped_logo_failures_do_not_control_final(tmp_path):
    assets,_=scene_fixture(tmp_path)
    # Deliberately wrong generated package (solid red everywhere), and a logo in
    # the region that will be discarded. Final product and logo come from assets.
    data,qa=finish_locked_scene(assets,native_fixture((255,0,0)),fonts=FONTS)
    assert qa["canonical_product_layer_integrity"]=="PASS"
    assert qa["logo"]["no_later_crop"] is True
    assert qa["logo"]["source_asset_id"]=="logo"
    assert all(t["canonical_text"] for t in qa["text"])


def test_missing_font_is_not_a_silent_typography_fallback(tmp_path):
    assets,_=scene_fixture(tmp_path)
    with pytest.raises(ValueError,match="font"):
        finish_locked_scene(assets,native_fixture(),fonts={})


def test_v10_text_overlap_is_rejected_before_generation(tmp_path):
    from app.schemas.creative_bridge import HannaCreativePackage
    from app.schemas.creative_delivery import PreparedDelivery
    from app.services.locked_scene import canonical_product_layer,scene_layers
    assets,_=scene_fixture(tmp_path)
    delivery=assets.plan.delivery
    regions=list(delivery.package.text_regions)
    regions[0]=regions[0].model_copy(update={"box":assets.plan.final_product_box})
    package=HannaCreativePackage.model_validate({**delivery.package.model_dump(),"text_regions":regions})
    guide=delivery.guide.model_copy(update={"quiet_zones":(*delivery.guide.quiet_zones,regions[0].box)})
    delivery=PreparedDelivery.model_validate({**delivery.model_dump(),"package":package,"guide":guide})
    plan,layer=canonical_product_layer(delivery,master_asset_id="master")
    with pytest.raises(ValueError,match="overlaps"):
        scene_layers(plan,layer)


@pytest.mark.asyncio
async def test_current_budget_guard_still_blocks_masked_scene_before_network(tmp_path):
    assets,_=scene_fixture(tmp_path)
    provider=OpenAIProvider(api_key=None,hard_budget_usd=.5)
    with pytest.raises(HardBudgetExceededError,match="UNKNOWN_MULTIMODAL"):
        await generate_locked_scene(assets,provider)
    assert provider._client is None


def test_no_renderer_or_generic_shadow_fallback_in_v11():
    import inspect
    import app.services.locked_scene as geometry
    import app.services.locked_scene_overlay as overlay
    source=inspect.getsource(geometry)+inspect.getsource(overlay)
    assert "render_slide" not in source and "premium_render" not in source
    assert "drop_shadow(" not in source
    assert "visual_acceptance" in source


@pytest.mark.parametrize("failed",["no_generated_product_outside_canonical_layer","no_generated_final_marketing_text",
    "no_generated_logo_outside_canonical_layer","no_duplicate_product_shadows","postable"])
def test_pixel_success_never_waives_scene_visual_qa(tmp_path,failed):
    from app.schemas.locked_scene import LockedSceneReview
    from app.services.locked_scene_overlay import require_locked_scene_acceptance
    from test_build6r_v101_multimodal_bridge import review
    assets,_=scene_fixture(tmp_path)
    native=native_fixture()
    data,_=finish_locked_scene(assets,native,fonts=FONTS)
    flags=dict(no_generated_product_outside_canonical_layer=True,no_generated_final_marketing_text=True,
        no_generated_logo_outside_canonical_layer=True,no_duplicate_product_shadows=True,postable=True)
    flags[failed]=False
    synthetic=LockedSceneReview(creative_review=review(assets.plan.delivery.package,data),**flags)
    with pytest.raises(ValueError,match="visual acceptance"):
        require_locked_scene_acceptance(assets,native,data,fonts=FONTS,review=synthetic)


def test_complete_synthetic_review_requires_the_exact_locked_product_position(tmp_path):
    from app.schemas.locked_scene import LockedSceneReview
    from app.services.locked_scene_overlay import require_locked_scene_acceptance
    from test_build6r_v101_multimodal_bridge import review
    assets,_=scene_fixture(tmp_path)
    native=native_fixture()
    data,_=finish_locked_scene(assets,native,fonts=FONTS)
    flags=dict(no_generated_product_outside_canonical_layer=True,no_generated_final_marketing_text=True,
        no_generated_logo_outside_canonical_layer=True,no_duplicate_product_shadows=True,postable=True)
    synthetic=LockedSceneReview(creative_review=review(assets.plan.delivery.package,data),**flags)
    with pytest.raises(ValueError,match="geometry"):
        require_locked_scene_acceptance(assets,native,data,fonts=FONTS,review=synthetic)
    synthetic=synthetic.model_copy(update={"creative_review":synthetic.creative_review.model_copy(
        update={"product_box":assets.plan.final_product_box})})
    require_locked_scene_acceptance(assets,native,data,fonts=FONTS,review=synthetic)
