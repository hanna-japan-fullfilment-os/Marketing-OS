"""V11 geometry, alpha masks and canonical restore around the existing V10 handoff."""
import hashlib
import io
import json
from pathlib import Path

from PIL import Image, ImageChops

from ..schemas.creative_delivery import CompositionGuide, PreparedDelivery
from ..schemas.locked_scene import (LockedSceneConfig, LockedScenePlan, SceneEditAssets,
    NativePreparedDelivery, NativeCompositionGuide, NativeSunburstSettings)
from .hanna_creative_package import image_record, verified_image_bytes, canonical_json
from .locked_product_pipeline import inspect_locked_product_master_candidate


def pixel_digest(image):
    return hashlib.sha256(image.mode.encode()+str(image.size).encode()+image.tobytes()).hexdigest()


def dilate(mask,radius):
    """Exact square-margin dilation without wraparound or a huge 2-D kernel."""
    result=mask.copy()
    for axis in (0,1):
        remaining,stride=radius,1
        while remaining:
            step=min(stride,remaining)
            prior=result
            for sign in (-1,1):
                shifted=Image.new("L",mask.size)
                shifted.paste(prior,(sign*step if axis==0 else 0,sign*step if axis==1 else 0))
                result=ImageChops.lighter(result,shifted)
            remaining-=step
            stride*=2
    return result


def resolve_locked_delivery(delivery):
    """Use V10 text geometry, with a larger final-crop logo signature region."""
    if delivery.package.text_mode != "negative_space_overlay":
        raise ValueError("V11 final typography must be deterministic only")
    logo = (56,1176,300,1240)
    quiet = tuple(dict.fromkeys([*delivery.guide.quiet_zones, logo]))
    guide = CompositionGuide.model_validate({**delivery.guide.model_dump(), "logo_region": logo, "quiet_zones": quiet})
    return PreparedDelivery.model_validate({**delivery.model_dump(), "guide": guide})


def native_final_size_delivery(delivery):
    """Keep all final geometry; only remove the legacy generation/crop wrapper."""
    guide=NativeCompositionGuide.model_validate({**delivery.guide.model_dump(),
        "generation_size":"1024x1280","final_crop":None})
    return NativePreparedDelivery.model_validate({**delivery.model_dump(),"native_final_size":True,
        "guide":guide,"settings":NativeSunburstSettings()})


def final_plane(image,delivery):
    # Native mode performs no crop, remapping, resize or stretching.
    return image.copy() if isinstance(delivery,NativePreparedDelivery) else image.crop(delivery.guide.final_crop)


def canonical_product_layer(delivery, *, master_asset_id, config=None):
    """Only an existing approved RGBA master; no segmentation or reconstruction."""
    if delivery.package.text_mode!="negative_space_overlay":
        raise ValueError("V11 final typography must be deterministic only")
    config = config or LockedSceneConfig()
    masters = [a for a in delivery.package.images if a.asset_id == master_asset_id and a.role == "product_master"]
    if len(masters) != 1:
        raise ValueError("Explicit canonical product master required")
    asset = masters[0]
    verified_image_bytes(asset)
    validation = inspect_locked_product_master_candidate(Path(asset.path), expected_sha256=asset.sha256)
    if validation is None:
        raise ValueError("Canonical approved alpha master path required")
    with Image.open(asset.path) as source:
        bbox = tuple(validation["alpha_bbox"])
        cutout = source.convert("RGBA").crop(bbox)
    l,t,r,b = delivery.guide.product_region
    scale = min((r-l)/cutout.width, (b-t)/cutout.height)
    size = (max(1,round(cutout.width*scale)), max(1,round(cutout.height*scale)))
    cutout = cutout.resize(size, Image.Resampling.LANCZOS)
    x,y = r-size[0], b-size[1]
    final_box=(x,y,x+size[0],y+size[1])
    offset=0 if isinstance(delivery,NativePreparedDelivery) else delivery.guide.final_crop[1]
    native_box=(x,y+offset,x+size[0],y+size[1]+offset)
    layer=Image.new("RGBA",tuple(map(int,delivery.guide.generation_size.split("x"))))
    # Paste RGBA without applying alpha twice.
    layer.paste(cutout,(x,y+offset))
    plan=LockedScenePlan(delivery=delivery,master_asset_id=asset.asset_id, master_sha256=asset.sha256,
        source_alpha_bbox=bbox,final_product_box=final_box,native_product_box=native_box,
        canonical_layer_pixel_sha256=pixel_digest(layer), alpha_pixel_sha256=pixel_digest(layer.getchannel("A")), config=config)
    return plan,layer


def scene_layers(plan,layer):
    if pixel_digest(layer) != plan.canonical_layer_pixel_sha256:
        raise ValueError("Canonical geometry/layer changed")
    alpha=layer.getchannel("A")
    support=alpha.point(lambda n:255 if n else 0)
    margin=plan.config.protection_margin
    protected=dilate(support,margin)
    outer=dilate(support,plan.config.grounding_width)
    ring=ImageChops.subtract(outer,protected)
    base=Image.alpha_composite(Image.new("RGBA",layer.size,(24,23,22,255)),layer)
    mask=Image.new("RGBA",layer.size,(255,255,255,0))
    mask.putalpha(protected)  # opaque protects; transparent is editable
    # Fail before generation if any final deterministic region intersects alpha.
    final_protected=final_plane(ImageChops.lighter(protected,ring),plan.delivery)
    reserved=[r.box for r in plan.delivery.package.text_regions]+[plan.delivery.guide.logo_region]
    for index,box in enumerate(reserved):
        if final_protected.crop(box).getbbox():
            raise ValueError("Final text/logo region overlaps protected product")
        l,t,r,b=box
        for other in reserved[:index]:
            if l<other[2] and r>other[0] and t<other[3] and b>other[1]:
                raise ValueError("Final deterministic text/logo regions overlap")
    return {"locked-base":base,"canonical-product-layer":layer,"canonical-alpha":alpha,
            "protection-mask":protected,"environment-mask":mask,"grounding-ring":ring}


def write_scene_assets(plan,layer,directory):
    """Caller supplies an authorized output directory; every artifact is exclusive."""
    directory=Path(directory)
    if not directory.is_dir():
        raise ValueError("Existing authorized debug/output directory required")
    layers=scene_layers(plan,layer)
    records={}
    for name,image in layers.items():
        path=directory/(name+".png")
        with path.open("xb") as stream:
            image.save(stream,"PNG")
        records[name]=image_record(asset_id=plan.digest()+":"+name,
            role="base" if name=="locked-base" else "mask",path=path,
            expected_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),authority="deterministic canonical product geometry",
            provenance={"plan_sha256":plan.digest(),"canonical_master_sha256":plan.master_sha256})
    return SceneEditAssets(plan=plan,base=records["locked-base"],environment_mask=records["environment-mask"],
        product_layer=records["canonical-product-layer"],protection_mask=records["protection-mask"],grounding_ring=records["grounding-ring"])


def validate_scene_assets(assets):
    plan=assets.plan
    rebuilt,layer=canonical_product_layer(plan.delivery,master_asset_id=plan.master_asset_id,config=plan.config)
    if rebuilt != plan:
        raise ValueError("Stale canonical product restore plan")
    expected=scene_layers(plan,layer)
    for key,record in (("locked-base",assets.base),("environment-mask",assets.environment_mask),
            ("canonical-product-layer",assets.product_layer),("protection-mask",assets.protection_mask),("grounding-ring",assets.grounding_ring)):
        with Image.open(io.BytesIO(verified_image_bytes(record))) as image:
            if pixel_digest(image) != pixel_digest(expected[key]):
                raise ValueError("Scene geometry/mask artifact differs from canonical plan")
    return layer,expected


def locked_scene_instructions(assets):
    plan=assets.plan
    native=isinstance(plan.delivery,NativePreparedDelivery)
    stage="in native final coordinates; no crop or resize" if native else "AFTER the final crop"
    return ("\nV11 LOCKED-PRODUCT SCENE EDIT overrides generative ownership. The FIRST image is the locked base; "
        "the mask protects the actual product silhouette. The visible canonical product already occupies "
        "its exact final position. Design the complete environment AROUND that upright product, "
        "not a second package. Do not add, redraw, move, duplicate, recolor or relight the product. "
        "Product reference images are context, never authority for generated final product pixels. "
        "Create surface, cast/contact shadow, reflections, glow, framing and depth OUTSIDE the silhouette "
        "in its editable grounding ring. No generic extra drop shadow; no duplicate products/shadows. "
        "Illuminate the environment consistently with the existing real product: "+plan.config.light_direction+". "
        "Generate NO final headline, facts, CTA, brand emblem or logo wordmark. Text and logo are "
        "deterministic "+stage+". Keep their actual quiet regions useful, not empty UI cards. "
        "Masking is guidance only; canonical product pixels will be restored by alpha "+stage+". "
        "Do not fill silhouette holes or its transparent surroundings with replacement artwork. "
        +canonical_json({"final_product_box":plan.final_product_box,"native_product_box":plan.native_product_box,
            "native_product_dimensions":[plan.native_product_box[2]-plan.native_product_box[0],plan.native_product_box[3]-plan.native_product_box[1]],
            "orientation":"upright, no rotation", "protection_margin":plan.config.protection_margin,
            "grounding_width":plan.config.grounding_width,"final_crop":plan.delivery.guide.final_crop,
            "generation_size":plan.delivery.guide.generation_size,"coordinate_space":"FINAL_1024x1280" if native else "FINAL_WITH_PRECOMPUTED_NATIVE_OFFSET",
            "logo_region":plan.delivery.guide.logo_region,"text_regions":[r.model_dump() for r in plan.delivery.package.text_regions]}))


def restore_scene(assets,native_bytes):
    layer,layers=validate_scene_assets(assets)
    if not native_bytes or len(native_bytes)>32*1024*1024:
        raise ValueError("Invalid generated scene size")
    with Image.open(io.BytesIO(native_bytes)) as image:
        image.load()
        if image.size!=tuple(map(int,assets.plan.delivery.guide.generation_size.split("x"))) or image.format!="PNG":
            raise ValueError("Native scene dimensions/format mismatch")
        scene=final_plane(image.convert("RGBA"),assets.plan.delivery)
    final_layer=final_plane(layer,assets.plan.delivery)
    restored=Image.alpha_composite(scene,final_layer)
    return scene,restored,final_layer,final_plane(layers["grounding-ring"],assets.plan.delivery)


def restore_after_crop(assets,native_bytes):
    """Legacy/debug API retained; native delivery uses restore_scene directly."""
    return restore_scene(assets,native_bytes)


def require_product_integrity(final,scene,layer,ring):
    """Check all alpha-supported product pixels AND preserve the exterior ring."""
    expected=Image.alpha_composite(scene,layer)
    support=layer.getchannel("A").point(lambda n:255 if n else 0)
    diff=ImageChops.difference(final.convert("RGB"),expected.convert("RGB"))
    channels=diff.split()
    difference=ImageChops.lighter(ImageChops.lighter(channels[0],channels[1]),channels[2])
    if ImageChops.multiply(difference,support).getbbox():
        raise ValueError("Canonical product layer integrity failed")
    exterior_diff=ImageChops.difference(final.convert("RGB"),scene.convert("RGB"))
    channels=exterior_diff.split()
    difference=ImageChops.lighter(ImageChops.lighter(channels[0],channels[1]),channels[2])
    if ImageChops.multiply(difference,ring).getbbox():
        raise ValueError("Generated grounding ring was overwritten")
    return {"canonical_product_layer_integrity":"PASS","grounding_ring_preserved":True,
            "product_pixels_source":"CANONICAL_PRODUCT_ASSET","alpha_edge_rule":"canonical alpha composited over scene; opaque interiors exact"}


async def generate_locked_scene(assets,provider):
    validate_scene_assets(assets)
    return await provider.compose_direct_creative(delivery=assets.plan.delivery,scene_edit=assets)
