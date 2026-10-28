"""V9 scene/style consumption: deterministic plans and non-destructive layers."""
from dataclasses import asdict, dataclass
import hashlib
import json
import math

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from .scene import DEPTH_ORDER
from .premium_design import rgb

VERSION = 'build6r-premium-render-v1'
ART_EXCLUSIONS = ('readable marketing text', 'Hanna logo', 'CTA text',
    'factual badges with text', 'real product packaging', 'substitute or fake product',
    'duplicate product', 'code-owned light arcs or editorial rules',
    'product contact shadow or product halo')


def image_digest(image):
    return hashlib.sha256(image.mode.encode()+str(image.size).encode()+image.tobytes()).hexdigest()


def crop_contract(native_size,canvas_size):
    if any(type(v) is not int or v<=0 for v in (*native_size,*canvas_size)):
        raise ValueError('Positive native/canvas dimensions required')
    sw,sh=native_size;w,h=canvas_size
    if sw*h>sh*w:
        cw=max(1,round(sh*w/h));left=(sw-cw)//2;box=(left,0,left+cw,sh)
    else:
        ch=max(1,round(sw*h/w));top=(sh-ch)//2;box=(0,top,sw,top+ch)
    return dict(native_size=list(native_size),crop_box=list(box),canvas_size=list(canvas_size),
        method='center_crop_then_uniform_fit',stretch=False)


@dataclass(frozen=True)
class PremiumRenderPlan:
    version: str
    scene_sha256: str
    style_sha256: str
    geometry_sha256: str
    scene_archetype: str
    canvas: dict
    art_layer_prompt_spec: dict
    product_geometry: dict
    grounding: dict
    lighting: dict
    depth_order: tuple[str,...]
    ownership: dict
    typography: tuple[dict,...]
    callout: dict
    cta: dict
    logo: dict
    crop: dict
    constraints: dict

    def to_dict(self):return asdict(self)

    @property
    def digest(self):
        return hashlib.sha256(json.dumps(self.to_dict(),sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest()

    def validate(self,scene,style):
        style.validate(scene);scene.validate_relationships()
        expected=build_premium_render_plan(scene,style,art_native_size=tuple(self.crop['native_size']),
            product_layer_sha256=self.product_geometry['layer_sha256'])
        if self.to_dict()!=expected.to_dict():raise ValueError('Stale or altered premium render plan')


def build_premium_render_plan(scene,style,*,art_native_size=None,product_layer_sha256=None):
    """All final layer owners, geometry and treatment decisions precede output."""
    style.validate(scene);scene.validate_relationships()
    max_support={'DIRECT_NEGATIVE_SPACE':0,'EDITORIAL_RULE':0,
                 'SOFT_TONAL_FIELD':.36,'TONAL_VEIL':.78}[style.treatments['text']]
    if (any(token['support_alpha']>max_support for token in style.typography)
            or style.cta['id']!=style.treatments['cta'] or style.callout['id']!=style.treatments['callout']):
        raise ValueError('Rendered treatment differs from selected design vocabulary')
    if product_layer_sha256 is not None and (len(product_layer_sha256)!=64 or
            any(c not in '0123456789abcdef' for c in product_layer_sha256)):
        raise ValueError('Canonical product layer digest required')
    w,h=scene.layout.width,scene.layout.height
    ownership={'environment':'ART_LAYER','surface_texture':'ART_LAYER',
        'contact_shadow':'MIDGROUND_SUPPORT_LAYER','ambient_shadow':'MIDGROUND_SUPPORT_LAYER',
        'tonal_halo':'MIDGROUND_SUPPORT_LAYER','grounding_plane':'MIDGROUND_SUPPORT_LAYER',
        'canonical_product':'PRODUCT_LAYER','typography':'TYPOGRAPHY_BRAND_LAYER',
        'callout':'TYPOGRAPHY_BRAND_LAYER','cta':'TYPOGRAPHY_BRAND_LAYER','logo':'TYPOGRAPHY_BRAND_LAYER'}
    for motif in style.motifs:
        ownership['motif.'+motif]=('ART_LAYER' if motif=='LACQUER_TEXTURE' else
            'MIDGROUND_SUPPORT_LAYER' if motif=='LIGHT_ARC' else 'FOREGROUND_ACCENT_LAYER')
    regions={r.key:dict(role=r.role,box=asdict(r.box)) for r in scene.layout.roles}
    regions.update(product=dict(role='canonical_product_reserved',box=asdict(scene.layout.product)),
        logo=dict(role='brand_reserved',box=asdict(scene.layout.logo)),
        cta_support=dict(role='cta_reserved',box=asdict(scene.layout.cta),active=scene.layout.cta_required))
    art_spec=dict(version='build6r-art-direction-v1',canvas=[w,h],regions=regions,
        palette_roles=style.palette,lighting=style.lighting,depth=style.depth,
        material_intent=style.resolved_vocabulary['surfaces'],
        generated_motifs=[m for m in style.motifs if ownership['motif.'+m]=='ART_LAYER'],
        excluded_code_owned_motifs=[m for m in style.motifs if ownership['motif.'+m]!='ART_LAYER'],
        negative_space=scene.composition['negative_space_zones'],
        relations=dict(flow=scene.composition['visual_flow'],anchors=[asdict(r) for r in scene.relationships],
            light_leads_to='canonical_product_reserved',depth_frames='product',
            surface_matches=style.grounding['surface'],text_support='controlled_low_detail_contrast_zones'),
        exclusions=list(ART_EXCLUSIONS),generative_text_allowed=False,generative_logo_allowed=False,
        generative_product_allowed=False,geometry_sha256=scene.layout.digest)
    return PremiumRenderPlan(VERSION,scene.digest,style.digest,scene.layout.digest,scene.archetype,
        dict(width=w,height=h,safe_area=scene.canvas['safe_area']),art_spec,
        dict(box=asdict(scene.layout.product),asset=asdict(scene.canonical_asset),preserve_pixels=True,
             layer_sha256=product_layer_sha256),
        dict(style.grounding,region=scene.product['grounding_region'],shadow_direction=scene.environment['shadow_direction']),
        dict(style.lighting),tuple(DEPTH_ORDER),ownership,style.typography,
        dict(style.callout,vocabulary=style.resolved_vocabulary['callout']),
        dict(style.cta,vocabulary=style.resolved_vocabulary['cta']),
        dict(style.logo,vocabulary=style.resolved_vocabulary['logo']),
        crop_contract(art_native_size or (w,h),(w,h)),
        dict(opaque_text_panel=False,white_logo_tile=False,raw_ungrounded_overlay=False,
            silent_legacy_fallback=False,product_redraw_allowed=False,visual_acceptance=False,
            duplicate_treatment_count=0,protect_text_zones=True,protect_all_product_alpha=True))


def fit_art_layer(plan,image):
    if list(image.size)!=plan.crop['native_size']:raise ValueError('Art native dimensions differ from plan')
    box=tuple(plan.crop['crop_box'])
    return image.convert('RGBA').crop(box).resize(tuple(plan.crop['canvas_size']),Image.Resampling.LANCZOS)


def _clear_reserved(layer,scene,product_alpha=None):
    mask=Image.new('L',layer.size,255);draw=ImageDraw.Draw(mask)
    for box in [r.box for r in scene.layout.roles]+[scene.layout.logo,scene.layout.quiet]:
        draw.rectangle((math.floor(box.x)-2,math.floor(box.y)-2,math.ceil(box.right)+2,math.ceil(box.bottom)+2),fill=0)
    if product_alpha is not None:
        mask=ImageChops.multiply(mask,product_alpha.point(lambda a:0 if a else 255))
    layer.putalpha(ImageChops.multiply(layer.getchannel('A'),mask))
    return layer


def composite_premium_layers(plan,scene,style,*,art,product_layer):
    """Effects never tint the product or paint over text/brand contrast zones."""
    plan.validate(scene,style)
    size=(scene.layout.width,scene.layout.height)
    if product_layer.mode!='RGBA' or product_layer.size!=size:
        raise ValueError('Separate canonical RGBA product layer required')
    before=image_digest(product_layer);alpha=product_layer.getchannel('A')
    if plan.product_geometry['layer_sha256']!=before:
        raise ValueError('Canonical product layer differs from render plan')
    if alpha.getbbox() is None:raise ValueError('Empty canonical product layer')
    # Prevent arbitrary pixels from entering outside the approved product box.
    p=scene.layout.product;b=alpha.getbbox()
    if b[0]<p.x-1 or b[1]<p.y-1 or b[2]>p.right+1 or b[3]>p.bottom+1:
        raise ValueError('Product layer differs from planned geometry')
    base=fit_art_layer(plan,art)
    mid=Image.new('RGBA',size);foreground=Image.new('RGBA',size)
    scale=size[0]/1080
    def color_layer(color,mask,opacity):
        layer=Image.new('RGBA',size,(*rgb(color),0))
        layer.putalpha(mask.point(lambda v:round(v*opacity)))
        return layer
    # The upper-left key implies a lower-right ambient shadow. No relighting of
    # the package itself occurs; every effect is a distinct supporting layer.
    shadow_mask=Image.new('L',size)
    shadow_mask.paste(alpha,(round(16*scale),round(12*scale)))
    ambient=shadow_mask.filter(ImageFilter.GaussianBlur(18*scale*style.lighting['shadow_softness']))
    mid.alpha_composite(color_layer(style.palette['charcoal'],ambient,.38))
    plane=Image.new('L',size);draw=ImageDraw.Draw(plane)
    draw.ellipse((p.x-.04*p.width,p.bottom-.025*p.height,p.right+.04*p.width,p.bottom+.025*p.height),fill=150)
    mid.alpha_composite(color_layer(style.palette['metallic_gold'],plane.filter(ImageFilter.GaussianBlur(7*scale)),.20))
    contact=Image.new('L',size);ImageDraw.Draw(contact).ellipse((p.x+.04*p.width,p.bottom-.012*p.height,p.right+.04*p.width,p.bottom+.018*p.height),fill=230)
    mid.alpha_composite(color_layer(style.palette['charcoal'],contact.filter(ImageFilter.GaussianBlur(5*scale)),.72))
    halo=alpha.filter(ImageFilter.GaussianBlur(22*scale))
    mid.alpha_composite(color_layer(style.palette['secondary_accent'],halo,.18 if style.grounding['id']=='SOFT_CONTACT' else .30))
    for motif in style.motifs:
        owner=plan.ownership['motif.'+motif]
        if owner=='ART_LAYER':continue
        layer=Image.new('RGBA',size);draw=ImageDraw.Draw(layer)
        color=(*rgb(style.palette['metallic_gold'] if motif=='EDITORIAL_LINE' else style.palette['secondary_accent']),110)
        if motif=='EDITORIAL_LINE':
            axis=scene.canvas['composition_axis']['story_x']
            draw.line((axis, p.bottom-.04*size[1],p.x-.025*size[0],p.bottom-.04*size[1]),fill=color,width=max(1,round(style.cohesion['stroke_width_px'])))
            foreground.alpha_composite(_clear_reserved(layer,scene,alpha))
        elif motif=='LIGHT_ARC':
            draw.arc((p.x-.10*p.width,p.y-.10*p.height,p.right+.10*p.width,p.bottom+.05*p.height),200,320,fill=color,width=max(1,round(2*scale)))
            mid.alpha_composite(layer)
        else:raise ValueError('Unowned deterministic motif')
    mid=_clear_reserved(mid,scene)
    base.alpha_composite(mid)
    base.alpha_composite(product_layer)
    foreground=_clear_reserved(foreground,scene,alpha)
    base.alpha_composite(foreground)
    if image_digest(product_layer)!=before:raise ValueError('Canonical product layer mutated')
    return base.convert('RGB'),dict(plan_sha256=plan.digest,product_layer_sha256=before,
        product_layer_unchanged=True,midground_sha256=image_digest(mid),foreground_sha256=image_digest(foreground),
        compositing_order=list(plan.depth_order),grounding_applied=True,
        applied_grounding=['ambient_shadow','contact_shadow','tonal_halo','grounding_plane'],
        code_motifs=[m for m in style.motifs if plan.ownership['motif.'+m]!='ART_LAYER'],
        art_motifs=[m for m in style.motifs if plan.ownership['motif.'+m]=='ART_LAYER'],
        visual_acceptance=False)


def premium_treatment_css(plan,scene,style):
    """Render the selected V9.2 vocabulary without changing measured geometry."""
    plan.validate(scene,style)
    gold=style.palette['metallic_gold'];stroke=style.cohesion['stroke_width_px']
    css='.canvas .premium-role{isolation:isolate}.canvas .premium-role.fact{border-left:0}'
    callout=style.treatments['callout']
    if callout=='EDITORIAL_FACT_RULE':css+=f'.canvas .premium-role.fact{{box-shadow:inset {stroke:g}px 0 {gold}}}'
    elif callout=='OUTLINE_BRACKET':css+=f'.canvas .premium-role.fact{{box-shadow:inset 0 {stroke:g}px {gold},inset {stroke:g}px 0 {gold}}}'
    elif callout=='LUMINOUS_INLINE':css+=f'.canvas .premium-role.fact{{box-shadow:inset 0 -{stroke:g}px {gold}}}'
    else:raise ValueError('Unsupported callout treatment')
    text=style.treatments['text']
    if text=='EDITORIAL_RULE':css+=f'.canvas .premium-role:not(.headline-role){{box-shadow:inset 0 -{stroke:g}px {gold}}}'
    elif text in ('SOFT_TONAL_FIELD','TONAL_VEIL'):
        css+='.canvas .premium-role{border-radius:3px}'
    elif text!='DIRECT_NEGATIVE_SPACE':raise ValueError('Unsupported text treatment')
    if scene.layout.cta_required:
        if style.treatments['cta']=='GOLD_EDITORIAL_BAND':
            # Approved CTA band, not a generic white contrast fallback. Both
            # its actual color and foreground are returned to the QA probe.
            css+=f'.canvas [data-composition-role="cta"]{{background-color:{gold}!important;color:{style.palette["cta_foreground"]}!important;box-shadow:inset 0 -{stroke:g}px {style.palette["cream"]}}}'
        elif style.treatments['cta']=='INLINE_ACCENT_RULE':
            css+=f'.canvas [data-composition-role="cta"]{{box-shadow:inset 0 -{stroke:g}px {gold}}}'
        else:raise ValueError('Unsupported CTA treatment')
    if not scene.layout.logo_required:
        return css
    logo=style.treatments['logo']
    if logo=='TONAL_BRAND_ZONE':
        alpha=max(.18,(style.logo['contrast'] or {}).get('support_alpha',0))
        css+=f'.canvas .premium-logo-zone{{background:rgba(24,23,22,{alpha});box-shadow:inset 0 -{stroke:g}px {gold}}}'
    elif logo=='EDITORIAL_CORNER':css+=f'.canvas .premium-logo-zone{{box-shadow:inset 0 -{stroke:g}px {gold}}}'
    elif logo!='TRANSPARENT_SIGNATURE':raise ValueError('Unsupported logo treatment')
    return css


def debug_premium_render(scene,style,plan):
    plan.validate(scene,style)
    return dict(UNIFIED_SCENE_SPEC=scene.to_dict(),RESOLVED_PREMIUM_SCENE_STYLE=style.to_dict(),
        ART_LAYER_PROMPT_SPEC=plan.art_layer_prompt_spec,PREMIUM_RENDER_PLAN=plan.to_dict(),
        COMPOSITING_ORDER=list(plan.depth_order),QA_GEOMETRY=scene.layout.to_dict(),visual_acceptance=False)
