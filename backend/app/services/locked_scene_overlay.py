"""Deterministic post-crop typography/logo/CTA with measured local contrast."""
import base64
import io
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

from .hanna_creative_package import verified_image_bytes
from .locked_scene import pixel_digest, restore_scene, require_product_integrity


def luminance(rgb):
    def linear(value):
        n=value/255
        return n/12.92 if n<=0.04045 else ((n+0.055)/1.055)**2.4
    r,g,b=map(linear,rgb[:3])
    return .2126*r+.7152*g+.0722*b


def minimum_contrast(background,mask,color):
    bbox=mask.getbbox()
    if bbox is None:
        raise ValueError("Empty final typography ink")
    foreground=luminance(color)
    result=100.0
    for y in range(bbox[1],bbox[3]):
        for x in range(bbox[0],bbox[2]):
            if mask.getpixel((x,y))>=220:
                value=luminance(background.getpixel((x,y)))
                result=min(result,(max(foreground,value)+.05)/(min(foreground,value)+.05))
    if result==100.0:
        raise ValueError("No verifiable opaque text ink")
    return result


def typography_ink(package,region,fonts):
    if region.font_id not in fonts:
        raise ValueError("Approved final font unavailable")
    text=next(c.text for c in package.approved_copy if c.key==region.key)
    font=ImageFont.truetype(str(fonts[region.font_id]),region.font_size)
    mask=Image.new("L",(1024,1280))
    draw=ImageDraw.Draw(mask)
    l,t,r,b=draw.multiline_textbbox((0,0),text,font=font)
    x,y,right,bottom=region.box
    if not (0<=x<right<=1024 and 0<=y<bottom<=1280) or r-l>right-x or b-t>bottom-y:
        raise ValueError("Final canonical copy does not fit; no shortening/panel fallback")
    draw.multiline_text((x-l,y-t),text,font=font,fill=255)
    color=tuple(int(region.color[i:i+2],16) for i in (1,3,5))
    return mask,color


def render_text(canvas,package,region,fonts,exclusion):
    mask,color=typography_ink(package,region,fonts)
    if ImageChops.multiply(mask,exclusion).getbbox():
        raise ValueError("Final text/product overlap")
    initial=minimum_contrast(canvas,mask,color)
    background=canvas
    chosen=0.0
    # A small glyph-local tonal fade is activated ONLY when real contrast fails.
    # Never fill a whole reserved region, add a card or shrink canonical copy.
    ink=mask.getbbox()
    fade=Image.new("L",canvas.size)
    ImageDraw.Draw(fade).rectangle((max(0,ink[0]-20),max(0,ink[1]-20),min(1023,ink[2]+19),min(1279,ink[3]+19)),fill=255)
    fade=fade.filter(ImageFilter.GaussianBlur(5))
    allowed=Image.new("L",canvas.size)
    ImageDraw.Draw(allowed).rectangle((region.box[0],region.box[1],region.box[2]-1,region.box[3]-1),fill=255)
    fade=ImageChops.multiply(fade,allowed)
    fade=ImageChops.multiply(fade,ImageChops.invert(exclusion))
    for opacity in (0.0,.15,.30,.45,.60,.72):
        if opacity:
            tone=(0,0,0) if luminance(color)>.5 else (255,255,255)
            background=Image.composite(Image.new("RGB",canvas.size,tone),canvas.convert("RGB"),fade.point(lambda n:round(n*opacity))).convert("RGBA")
        contrast=minimum_contrast(background,mask,color)
        if contrast>=4.5:
            chosen=opacity
            break
    else:
        raise ValueError("Actual background text contrast fails bounded tonal treatment")
    result=Image.composite(Image.new("RGBA",canvas.size,(*color,255)),background,mask)
    return result,{"field":region.key,"canonical_text":next(c.text for c in package.approved_copy if c.key==region.key),
        "initial_contrast":initial,"final_contrast":contrast,"tonal_fade_opacity":chosen,"ink_box":ink,
        "text_clipping_pixels":0,"text_overflow_count":0,"panel_fallback":False}


def canonical_logo_layer(package,guide):
    assets=[a for a in package.images if a.role=="logo"]
    if len(assets)!=1:
        raise ValueError("Canonical Hanna logo required")
    asset=assets[0]
    verified_image_bytes(asset)
    # Reuse approved non-destructive V9 matte extraction, NOT its compositor.
    from .creative.pipeline import _scene_logo
    uri,provenance=_scene_logo(Path(asset.path))
    with Image.open(io.BytesIO(base64.b64decode(uri.split(",",1)[1]))) as source:
        image=source.convert("RGBA")
    bbox=image.getchannel("A").getbbox()
    if not bbox or image.getchannel("A").getextrema()==(255,255):
        raise ValueError("Canonical logo lacks safe transparency; no white-tile fallback")
    image=image.crop(bbox)
    l,t,r,b=guide.logo_region
    image.thumbnail((r-l,b-t),Image.Resampling.LANCZOS)
    layer=Image.new("RGBA",(1024,1280))
    layer.paste(image,(l,t+(b-t-image.height)//2))
    return layer,{**provenance,"source_asset_id":asset.asset_id,"canonical_asset_sha256":asset.sha256,
        "final_logo_box":layer.getchannel("A").getbbox(),"logo_layer_pixel_sha256":pixel_digest(layer),
        "rendered_after_crop":guide.final_crop is not None,"rendered_in_final_coordinates":True,"no_later_crop":True}


def finish_locked_scene(assets,native_bytes,*,fonts):
    scene,canvas,product,ring=restore_scene(assets,native_bytes)
    package=assets.plan.delivery.package
    exclusion=product.getchannel("A").point(lambda n:255 if n else 0)
    exclusion=ImageChops.lighter(exclusion,ring)  # preserve environmental grounding too
    audits=[]
    occupied=Image.new("L",canvas.size)
    for region in package.text_regions:
        ink,_=typography_ink(package,region,fonts)
        if ImageChops.multiply(occupied,ink).getbbox():
            raise ValueError("Final text/text overlap")
        occupied=ImageChops.lighter(occupied,ink)
    # Required order: crop -> restore -> text -> logo -> CTA -> QA.
    for region in package.text_regions:
        if region.key!="cta":
            canvas,audit=render_text(canvas,package,region,fonts,exclusion)
            audits.append(audit)
    logo,logo_audit=canonical_logo_layer(package,assets.plan.delivery.guide)
    if ImageChops.multiply(logo.getchannel("A"),ImageChops.lighter(exclusion,occupied)).getbbox():
        raise ValueError("Final logo/product/text overlap")
    canvas=Image.alpha_composite(canvas,logo)
    for region in package.text_regions:
        if region.key=="cta":
            canvas,audit=render_text(canvas,package,region,fonts,ImageChops.lighter(exclusion,logo.getchannel("A")))
            audits.append(audit)
    integrity=require_product_integrity(canvas,scene,product,ring)
    buffer=io.BytesIO()
    canvas.save(buffer,"PNG")
    return buffer.getvalue(),{**integrity,"text":audits,"logo":logo_audit,"final_size":[1024,1280],
        "compositing_order":["native_final_scene" if assets.plan.delivery.guide.final_crop is None else "final_crop",
            "canonical_product_restore","deterministic_text","deterministic_logo","canonical_cta","QA"],
        "text_product_overlap_count":0,"edge_violation_count":0,"generic_rectangular_panel_fallback":False,
        "deterministic_shadow_added":False,"visual_acceptance":"NOT_ESTABLISHED_BY_PIXEL_QA"}


def require_locked_scene_acceptance(assets,native_bytes,final_bytes,*,fonts,review):
    """Technical proof plus existing V10 visual/copy QA; no auto-publish."""
    from ..schemas.locked_scene import LockedSceneReview
    from .multimodal_creative import require_final_acceptance
    review=LockedSceneReview.model_validate(review.model_dump())
    expected,_=finish_locked_scene(assets,native_bytes,fonts=fonts)
    with Image.open(io.BytesIO(expected)) as left,Image.open(io.BytesIO(final_bytes)) as right:
        if pixel_digest(left.convert("RGBA"))!=pixel_digest(right.convert("RGBA")):
            raise ValueError("Final output differs from canonical locked delivery")
    for key in ("no_generated_product_outside_canonical_layer","no_generated_final_marketing_text",
                "no_generated_logo_outside_canonical_layer","no_duplicate_product_shadows","postable"):
        if getattr(review,key) is not True:
            raise ValueError("Locked scene visual acceptance failed: "+key)
    if review.creative_review.product_box!=assets.plan.final_product_box:
        raise ValueError("Product review geometry differs from canonical locked position")
    require_final_acceptance(assets.plan.delivery.package,final_bytes,review.creative_review)
