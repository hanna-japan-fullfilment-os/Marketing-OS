"""Hanna's reference-bound, provider-neutral premium visual vocabulary.

This companion styles an existing scene; it never replans geometry, generates
copy, grants reference approval or renders product/material pixels.
"""
from dataclasses import asdict, dataclass
from copy import deepcopy
import hashlib
import json
import math

from PIL import Image

VERSION = 'build6r-hanna-premium-design-v1'
# Preserved approved V7/V8 rasters: style authority, never factual evidence.
REFERENCES = {
    'c345e62bbb40498a94e9acff41abf340': '072e9126d5b9b45be8b8d2a0a6f1f9b666c32d0a20e5c4a3d61c2478ee9a9e94',
    'e753cff3954c4d71840a91225feac5f7': '2db6f2f169729c801790678b4e288cf733fe0194eab2f4bda11a77cd9041cdf7',
}
COLORS = dict(primary_brand_accent='#B99252', secondary_accent='#A845FF',
    cream='#F4EFE7', charcoal='#181716', metallic_gold='#B99252',
    foreground_light='#F6E4FF', foreground_dark='#181716', muted_text='#F4EFE7',
    surface_dark='#14051F', surface_violet='#2F133F', cta_foreground='#181716',
    cta_surface='#B99252', matcha_contextual=None)
TEXT_TREATMENTS = ('DIRECT_NEGATIVE_SPACE', 'EDITORIAL_RULE', 'SOFT_TONAL_FIELD', 'TONAL_VEIL')
LOGO_TREATMENTS = ('TRANSPARENT_SIGNATURE', 'TONAL_BRAND_ZONE', 'EDITORIAL_CORNER')
CTA_TREATMENTS = ('GOLD_EDITORIAL_BAND', 'INLINE_ACCENT_RULE')
CALLOUT_TREATMENTS = ('EDITORIAL_FACT_RULE', 'OUTLINE_BRACKET', 'LUMINOUS_INLINE')
MOTIFS = ('EDITORIAL_LINE', 'LIGHT_ARC', 'LACQUER_TEXTURE')
SURFACES = ('DARK_LACQUER', 'TRANSLUCENT_GLASS', 'TONAL_GRADIENT', 'METALLIC_ACCENT')
TEXT_RULES = {
    'DIRECT_NEGATIVE_SPACE': dict(surface='none',role='prepared_contrast_zone'),
    'EDITORIAL_RULE': dict(surface='none',stroke='metallic_gold',relationship='story_axis'),
    'SOFT_TONAL_FIELD': dict(surface='local_charcoal_translucency',opacity_max=.36),
    'TONAL_VEIL': dict(surface='local_charcoal_translucency',opacity_max=.78),
}
LOGO_RULES = {
    'TRANSPARENT_SIGNATURE': dict(surface='none',anchor='scene_brand_zone',recolor=False),
    'TONAL_BRAND_ZONE': dict(surface='scene_local_tonal_support',anchor='scene_brand_zone',recolor=False),
    'EDITORIAL_CORNER': dict(surface='none',anchor='product_facing_corner',recolor=False),
}
CTA_RULES = {
    'GOLD_EDITORIAL_BAND': dict(surface='METALLIC_ACCENT',foreground='cta_foreground',shape='scene_attached_band',anchor='visual_flow_terminal'),
    'INLINE_ACCENT_RULE': dict(surface='none',foreground='contrast_selected',shape='editorial_rule',anchor='visual_flow_terminal'),
}
CALLOUT_RULES = {
    'EDITORIAL_FACT_RULE': dict(surface='none',shape='shared_editorial_rule',stroke='metallic_gold'),
    'OUTLINE_BRACKET': dict(surface='none',shape='open_bracket',stroke='metallic_gold'),
    'LUMINOUS_INLINE': dict(surface='none',shape='inline_reference_icon',stroke='secondary_accent'),
}
MOTIF_RULES = {
    'EDITORIAL_LINE': dict(shape='open_line',anchor='story_axis',color_role='metallic_gold'),
    'LIGHT_ARC': dict(shape='restrained_arc',anchor='product_breathing_room',color_role='secondary_accent'),
    'LACQUER_TEXTURE': dict(shape='subtle_surface_texture',anchor='grounding_plane',color_role='surface_dark'),
}
MATERIALS = {
    'DARK_LACQUER': dict(finish='glossy',color_role='surface_dark',intent='grounding_plane'),
    'TRANSLUCENT_GLASS': dict(finish='optical_translucency',color_role='surface_violet',intent='midground_depth'),
    'TONAL_GRADIENT': dict(finish='soft_falloff',color_roles=['surface_dark','surface_violet'],intent='environment'),
    'METALLIC_ACCENT': dict(finish='restrained_specular',color_role='metallic_gold',intent='rule_or_band'),
}
GROUNDING = {
    'SOFT_CONTACT': dict(ambient_shadow='broad_soft', contact_shadow='narrow_soft', halo='restrained', surface='DARK_LACQUER', atmosphere='low'),
    'HALO_STAGE': dict(ambient_shadow='soft_falloff', contact_shadow='narrow_soft', halo='tonal_rim', surface='TRANSLUCENT_GLASS', atmosphere='restrained'),
    'ATMOSPHERIC_BASE': dict(ambient_shadow='diffuse', contact_shadow='narrow_soft', halo='soft_rim', surface='TONAL_GRADIENT', atmosphere='layered'),
}
LIGHTING = {
    'VIOLET_RIM_GOLD_KEY': dict(key_direction='upper_left', brightness_focus='product', shadow_softness=.75, background_falloff='away_from_product', product_separation='violet_rim', text_contrast_minimum=4.5),
    'WARM_GOLD_FOCUS': dict(key_direction='upper_left_diagonal', brightness_focus='product_story_axis', shadow_softness=.60, background_falloff='radial', product_separation='warm_specular', text_contrast_minimum=4.5),
    'SOFT_VIOLET_ATMOSPHERE': dict(key_direction='upper_left_diffuse', brightness_focus='product', shadow_softness=.90, background_falloff='layered_haze', product_separation='lavender_rim', text_contrast_minimum=4.5),
}
DEPTH = {
    'LAYERED_GLASS': dict(background_focus='soft', midground_focus='soft_glass', product_focus='sharp_immutable', foreground_framing='restrained_arc', atmosphere='low_density'),
    'EDITORIAL_LACQUER': dict(background_focus='soft', midground_focus='subdued_surface', product_focus='sharp_immutable', foreground_framing='editorial_rule', atmosphere='minimal'),
}
TYPOGRAPHY_ROLES = {
    'KICKER': dict(weight=500,line_height=1.25,tracking=0,relative_role='eyebrow'),
    'HEADLINE': dict(weight=900,line_height=1.06,tracking=-.022,relative_role='hero'),
    'SUPPORTING_COPY': dict(weight=500,line_height=1.25,tracking=0,relative_role='support'),
    'VALUE_PROPOSITION': dict(weight=500,line_height=1.25,tracking=0,relative_role='support'),
    'FACT_CALLOUT': dict(weight=500,line_height=1.25,tracking=0,relative_role='factual_callout'),
    'CTA': dict(weight=500,line_height=1.25,tracking=0,relative_role='flow_terminal'),
    'LEGAL': dict(weight=500,line_height=1.25,tracking=0,relative_role='microcopy'),
    'STRUCTURAL': dict(weight=500,line_height=1.25,tracking=0,relative_role='microcopy'),
    'LOGO_ADJACENT': dict(weight=500,line_height=1.25,tracking=0,relative_role='brand_signature_only_if_approved'),
}
# Allowed combinations, not a Cartesian-product template marketplace.
MATRIX = {
    'EDITORIAL_HERO': dict(lighting=('WARM_GOLD_FOCUS','VIOLET_RIM_GOLD_KEY'), text=('EDITORIAL_RULE','DIRECT_NEGATIVE_SPACE','SOFT_TONAL_FIELD','TONAL_VEIL'), logo=('EDITORIAL_CORNER','TONAL_BRAND_ZONE'), grounding=('SOFT_CONTACT',), cta=('INLINE_ACCENT_RULE',), callout=('EDITORIAL_FACT_RULE','OUTLINE_BRACKET'), motifs=('EDITORIAL_LINE','LACQUER_TEXTURE'), depth=('EDITORIAL_LACQUER',)),
    'PRODUCT_SPOTLIGHT': dict(lighting=('WARM_GOLD_FOCUS',), text=('DIRECT_NEGATIVE_SPACE','SOFT_TONAL_FIELD','TONAL_VEIL'), logo=('TRANSPARENT_SIGNATURE','TONAL_BRAND_ZONE'), grounding=('SOFT_CONTACT','HALO_STAGE'), cta=('GOLD_EDITORIAL_BAND','INLINE_ACCENT_RULE'), callout=('EDITORIAL_FACT_RULE',), motifs=('EDITORIAL_LINE','LIGHT_ARC'), depth=('EDITORIAL_LACQUER','LAYERED_GLASS')),
    'DIAGONAL_FLOW': dict(lighting=('VIOLET_RIM_GOLD_KEY','WARM_GOLD_FOCUS'), text=('EDITORIAL_RULE','DIRECT_NEGATIVE_SPACE','SOFT_TONAL_FIELD','TONAL_VEIL'), logo=('EDITORIAL_CORNER','TONAL_BRAND_ZONE'), grounding=('HALO_STAGE',), cta=('INLINE_ACCENT_RULE',), callout=('OUTLINE_BRACKET','LUMINOUS_INLINE'), motifs=('EDITORIAL_LINE','LIGHT_ARC'), depth=('LAYERED_GLASS',)),
    'ATMOSPHERIC_PRODUCT_STAGE': dict(lighting=('SOFT_VIOLET_ATMOSPHERE','VIOLET_RIM_GOLD_KEY'), text=('DIRECT_NEGATIVE_SPACE','SOFT_TONAL_FIELD','TONAL_VEIL'), logo=('TRANSPARENT_SIGNATURE','TONAL_BRAND_ZONE'), grounding=('ATMOSPHERIC_BASE','HALO_STAGE'), cta=('GOLD_EDITORIAL_BAND','INLINE_ACCENT_RULE'), callout=('LUMINOUS_INLINE','EDITORIAL_FACT_RULE'), motifs=('LIGHT_ARC','LACQUER_TEXTURE'), depth=('LAYERED_GLASS',)),
}
for _archetype,_options in MATRIX.items():
    _options['surfaces'] = (('DARK_LACQUER','TONAL_GRADIENT','METALLIC_ACCENT')
        if _archetype == 'EDITORIAL_HERO' else SURFACES)
CATEGORY_ADAPTATION = {
    'beauty': dict(material='TRANSLUCENT_GLASS', mood='luminous_restraint'),
    'electronics': dict(material='DARK_LACQUER', mood='precise_product_focus'),
    'lifestyle': dict(material='TONAL_GRADIENT', mood='soft_editorial'),
    'collectible': dict(material='TRANSLUCENT_GLASS', mood='controlled_focal_drama'),
    'automotive': dict(material='DARK_LACQUER', mood='directional_specular'),
    'food': dict(material='TONAL_GRADIENT', mood='warm_restrained'),
    'general': dict(material='TONAL_GRADIENT', mood='reference_core'),
}


def is_hanna_scene(scene):
    return REFERENCES.get(scene.layout.reference_id) == scene.layout.reference_sha256.lower()


def luminance(rgb):
    values=[v/255/12.92 if v/255 <= .04045 else ((v/255+.055)/1.055)**2.4 for v in rgb]
    return sum(v*k for v,k in zip(values,(.2126,.7152,.0722)))


def rgb(color):
    return tuple(int(color[i:i+2],16) for i in (1,3,5))


def dominant_product_color(image):
    """Bounded, deterministic opaque-pixel histogram; never modifies source."""
    sample=image.convert('RGBA').resize((64,64),Image.Resampling.NEAREST)
    bins={}
    pixels=sample.tobytes()
    for offset in range(0,len(pixels),4):
        r,g,b,a=pixels[offset:offset+4]
        if a < 128: continue
        key=(r//16*16,g//16*16,b//16*16)
        bins[key]=bins.get(key,0)+1
    if not bins: raise ValueError('No observable product pixels')
    color=min(bins,key=lambda key:(-bins[key],key))
    return dict(dominant_hex='#' + ''.join(f'{v:02X}' for v in color),
        luminance=luminance(color),method='64x64 nearest; alpha>=128; 16-level RGB histogram',
        source_pixels_modified=False)


def scene_contrast_samples(scene,image):
    if image.size != (scene.layout.width,scene.layout.height):
        raise ValueError('Contrast raster/scene dimensions differ')
    source=image.convert('RGB');result={}
    boxes={r.key:r.box for r in scene.layout.roles}
    if scene.layout.logo_required: boxes['logo']=scene.layout.logo
    for key,box in boxes.items():
        result[key]=tuple(source.getpixel((max(0,min(source.width-1,round(box.x+box.width*x))),
            max(0,min(source.height-1,round(box.y+box.height*y)))))
            for x in (.1,.5,.9) for y in (.15,.5,.85))
    return result


def _contrast_style(samples):
    if not samples or any(len(s)!=3 or any(type(v) is not int or not 0<=v<=255 for v in s) for s in samples):
        raise ValueError('Actual scene contrast samples required')
    candidates=[]
    for color in (COLORS['foreground_light'],COLORS['foreground_dark']):
        fg=luminance(rgb(color))
        ratios=[(max(fg,luminance(s))+.05)/(min(fg,luminance(s))+.05) for s in samples]
        candidates.append((min(ratios),color))
    ratio,color=max(candidates)
    if ratio>=4.5:return dict(foreground=color,background='rgba(0,0,0,0)',support_alpha=0.,minimum_sample_contrast=ratio,needs_support=False)
    # Bounded translucent tonal support, not an opaque white rectangle.
    for alpha in (.18,.36,.54,.68,.78):
        fg=luminance(rgb(COLORS['foreground_light']));panel=rgb(COLORS['charcoal'])
        ratios=[]
        for s in samples:
            bg=luminance(tuple(panel[i]*alpha+s[i]*(1-alpha) for i in range(3)))
            ratios.append((max(fg,bg)+.05)/(min(fg,bg)+.05))
        if min(ratios)>=4.5:
            return dict(foreground=COLORS['foreground_light'],background=f'rgba(24,23,22,{alpha})',support_alpha=alpha,minimum_sample_contrast=min(ratios),needs_support=True)
    raise ValueError('No approved contrast treatment fits scene')


@dataclass(frozen=True)
class ResolvedPremiumSceneStyle:
    version: str
    scene_sha256: str
    geometry_sha256: str
    archetype: str
    palette: dict
    typography: tuple[dict,...]
    treatments: dict
    lighting: dict
    grounding: dict
    depth: dict
    surfaces: tuple[str,...]
    motifs: tuple[str,...]
    logo: dict
    cta: dict
    callout: dict
    cohesion: dict
    limits: dict
    product_color: dict
    category: dict
    reference_authority: dict
    resolved_vocabulary: dict

    def to_dict(self):return asdict(self)

    @property
    def digest(self):
        return hashlib.sha256(json.dumps(self.to_dict(),sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest()

    def validate(self,scene):
        if not is_hanna_scene(scene) or self.version!=VERSION or self.scene_sha256!=scene.digest or self.geometry_sha256!=scene.layout.digest or self.archetype!=scene.archetype:
            raise ValueError('Stale or unapproved premium scene style')
        allowed=MATRIX[self.archetype]
        for kind,selection in self.treatments.items():
            if kind not in allowed or selection not in allowed[kind]:raise ValueError('Incompatible Hanna treatment')
        if set(self.treatments)!=set(allowed)-{'motifs','surfaces'}:raise ValueError('Incomplete style selection')
        expected_limits=dict(max_decorative_motif_count=2 if not scene.layout.sparse else 1,
            max_accent_color_count=2,max_surface_treatment_count=2)
        if self.limits != expected_limits:raise ValueError('Decoration limits cannot be raised')
        if (len(self.motifs)>self.limits['max_decorative_motif_count'] or len(set(self.motifs))!=len(self.motifs)
                or any(m not in allowed['motifs'] for m in self.motifs)
                or len(self.surfaces)>self.limits['max_surface_treatment_count']
                or any(s not in allowed['surfaces'] for s in self.surfaces)
                or self.palette!=COLORS or self.limits['max_accent_color_count']!=2):
            raise ValueError('Hanna palette/decorative density violation')
        if {r['key'] for r in self.typography}!={r.key for r in scene.layout.roles} or len(self.typography)!=len(scene.layout.roles):
            raise ValueError('Style cannot add or discard approved copy roles')
        for token,role in zip(self.typography,scene.layout.roles):
            rule=TYPOGRAPHY_ROLES[role.role]
            if (token['key']!=role.key or token['font_family']!=role.font_family or token['font_px']!=role.font_px
                    or token['max_lines']!=role.max_lines or token['support_alpha'] not in self.cohesion['opacity_steps']
                    or token['weight']!=rule['weight'] or token['line_height']!=rule['line_height']
                    or token['letter_spacing_em']!=rule['tracking']
                    or token['foreground'] not in (COLORS['foreground_light'],COLORS['foreground_dark'])
                    or token['background'] != ('rgba(0,0,0,0)' if token['support_alpha']==0 else f'rgba(24,23,22,{token["support_alpha"]})')
                    or not math.isfinite(token['minimum_sample_contrast']) or token['minimum_sample_contrast']<4.5):
                raise ValueError('Typography/contrast contract changed')
        if self.cohesion['opacity_steps'] != [0,.18,.36,.54,.68,.78]:
            raise ValueError('Unapproved opacity language')
        if self.lighting != dict(LIGHTING[self.treatments['lighting']],id=self.treatments['lighting']):
            raise ValueError('Lighting preset changed')
        if self.grounding != dict(GROUNDING[self.treatments['grounding']],
                id=self.treatments['grounding'],product_redraw_allowed=False,rendered=False):
            raise ValueError('Grounding cannot redraw product or change vocabulary')
        if self.depth != dict(DEPTH[self.treatments['depth']],id=self.treatments['depth'],
                layer_order=[d['name'] for d in scene.depth_layers]):
            raise ValueError('Depth vocabulary changed')
        if self.logo['white_tile'] is not False or self.logo['id']!=self.treatments['logo']:
            raise ValueError('Unapproved logo treatment')
        if self.resolved_vocabulary != _vocabulary(self.treatments,self.motifs,self.surfaces):
            raise ValueError('Unapproved premium vocabulary')


def _vocabulary(treatments,motifs,surfaces):
    return deepcopy(dict(text=TEXT_RULES[treatments['text']],logo=LOGO_RULES[treatments['logo']],
        cta=CTA_RULES[treatments['cta']],callout=CALLOUT_RULES[treatments['callout']],
        motifs={key:MOTIF_RULES[key] for key in motifs},surfaces={key:MATERIALS[key] for key in surfaces},
        typography_roles=TYPOGRAPHY_ROLES))


def resolve_premium_scene_style(scene,*,product_color,contrast_samples,product_category='general'):
    if not is_hanna_scene(scene):raise ValueError('Hanna styling requires an approved reference identity')
    if (set(product_color)!={'dominant_hex','luminance','method','source_pixels_modified'}
            or product_color['source_pixels_modified'] is not False
            or not math.isfinite(product_color['luminance']) or not 0<=product_color['luminance']<=1):
        raise ValueError('Observable product color signal required')
    category=product_category if product_category in CATEGORY_ADAPTATION else 'general'
    allowed=MATRIX[scene.archetype]
    treatments={k:v[0] for k,v in allowed.items() if k not in ('motifs','surfaces')}
    if category in ('electronics','automotive') and 'WARM_GOLD_FOCUS' in allowed['lighting']:
        treatments['lighting']='WARM_GOLD_FOCUS'
    if product_color['luminance']<.15 and 'HALO_STAGE' in allowed['grounding']:
        treatments['grounding']='HALO_STAGE'
    if scene.brand['logo_treatment']['mode']=='source_supported_brand_zone':treatments['logo']='TONAL_BRAND_ZONE'
    roles=[]
    for role in scene.layout.roles:
        contrast=_contrast_style(contrast_samples.get(role.key))
        rule=TYPOGRAPHY_ROLES[role.role]
        roles.append(dict(key=role.key,role=role.role,font_family=role.font_family,font_px=role.font_px,
            relative_scale=role.font_px/scene.layout.width,weight=rule['weight'],
            line_height=rule['line_height'],letter_spacing_em=rule['tracking'],
            max_lines=role.max_lines,relationship_to_product='shared_scene_story_axis',
            preserve_reference_headline_paint=role.role=='HEADLINE',**contrast))
    if any(r['needs_support'] for r in roles):
        treatments['text']='SOFT_TONAL_FIELD' if max(r['support_alpha'] for r in roles)<=.36 else 'TONAL_VEIL'
    rich=not scene.layout.sparse
    motifs=tuple(allowed['motifs'][:2 if rich else 1])
    material=CATEGORY_ADAPTATION[category]['material']
    if material not in allowed['surfaces']:material=allowed['surfaces'][0]
    surfaces=tuple(dict.fromkeys((GROUNDING[treatments['grounding']]['surface'],material)))
    logo_contrast=_contrast_style(contrast_samples['logo']) if scene.layout.logo_required else None
    cta_role=next((r for r in roles if r['role']=='CTA'),None)
    style=ResolvedPremiumSceneStyle(VERSION,scene.digest,scene.layout.digest,scene.archetype,dict(COLORS),tuple(roles),treatments,
        dict(LIGHTING[treatments['lighting']],id=treatments['lighting']),
        dict(GROUNDING[treatments['grounding']],id=treatments['grounding'],product_redraw_allowed=False,rendered=False),
        dict(DEPTH[treatments['depth']],id=treatments['depth'],layer_order=[d['name'] for d in scene.depth_layers]),
        surfaces,motifs,
        dict(id=treatments['logo'],contrast=logo_contrast,canonical_asset_policy='unchanged_source_and_rgb',location='scene_brand_zone',white_tile=False),
        dict(id=treatments['cta'],active=scene.layout.cta_required,typography=cta_role,spacing_unit=scene.layout.width*.008,
            surface='translucent_scene_support' if cta_role and cta_role['needs_support'] else 'direct',contrast_minimum=4.5,location_relationship='scene_visual_flow_terminal'),
        dict(id=treatments['callout'],max_lines_policy='unchanged_scene_geometry_including_three_lines',surface='direct_or_local_tonal_support',stroke_role='metallic_gold'),
        dict(shared_alignment_axes=scene.canvas['composition_axis'],radius_language='restrained_existing_geometry',shadow_vocabulary='soft_contact_and_ambient',
            stroke_width_px=2*scene.layout.width/1080,opacity_steps=[0,.18,.36,.54,.68,.78],logo_cta_relationship='shared_brand_accent_and_story_axis',typography_background_relationship='sampled_scene_contrast_zones'),
        dict(max_decorative_motif_count=2 if rich else 1,max_accent_color_count=2,max_surface_treatment_count=2),
        dict(product_color,background_relationship='rim_separation' if product_color['luminance']<.15 else 'dark_ground_contrast'),
        dict(id=category,**CATEGORY_ADAPTATION[category],brand_core='canonical_cream_charcoal_gold',matcha_active=False,matcha_reason='No approved matcha swatch in canonical palette'),
        dict(approved_rasters=dict(REFERENCES),scope='visual_rules_only_not_claim_authority',brand_palette_source='canonical_Hanna_brand_colors',material_rendering='intent_for_following_integration'),
        _vocabulary(treatments,motifs,surfaces))
    style.validate(scene)
    return style


def debug_premium_scene(scene,style):
    style.validate(scene)
    return dict(unified_scene_spec=scene.to_dict(),resolved_premium_scene_style=style.to_dict(),
                scene_sha256=scene.digest,style_sha256=style.digest,visual_acceptance=False)
