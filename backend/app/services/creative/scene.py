"""Provider-neutral unified premium scene planning. No pixels or copy generated.

Prepared product placement is an input constraint, not permission to move or
redraw the package. LayoutSpec remains the geometry interface to frozen QA.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import hashlib
import json

from .composition import Box, LayoutSpec, resolve_composition

SCENE_VERSION = "build6r-unified-scene-v1"
ARCHETYPES = ("EDITORIAL_HERO", "PRODUCT_SPOTLIGHT", "DIAGONAL_FLOW",
              "ATMOSPHERIC_PRODUCT_STAGE")
DEPTH_ORDER = ("BACKGROUND_LAYER", "MIDGROUND_SUPPORT_LAYER", "PRODUCT_LAYER",
               "FOREGROUND_ACCENT_LAYER", "TYPOGRAPHY_BRAND_LAYER")


@dataclass(frozen=True)
class CanonicalSceneAsset:
    asset_id: str
    sha256: str
    path: str
    source_crop: tuple[int, int, int, int]

    def __post_init__(self):
        if (not self.asset_id or not self.path or len(self.sha256) != 64
                or any(c not in "0123456789abcdefABCDEF" for c in self.sha256)
                or len(self.source_crop) != 4
                or any(type(n) is not int for n in self.source_crop)
                or self.source_crop[0] < 0 or self.source_crop[1] < 0
                or self.source_crop[2] <= self.source_crop[0]
                or self.source_crop[3] <= self.source_crop[1]):
            raise ValueError("Canonical scene asset identity/crop required")


@dataclass(frozen=True)
class Relationship:
    element: str
    anchor: str
    axis: str
    anchor_edge: str
    offset: float

    def resolve(self, anchors: dict[str, Box]) -> float:
        if self.axis not in ("x", "y") or self.anchor_edge not in (
                ("x", "right") if self.axis == "x" else ("y", "bottom")):
            raise ValueError("Unsupported scene relationship")
        return getattr(anchors[self.anchor], self.anchor_edge) + self.offset


@dataclass(frozen=True)
class UnifiedSceneSpec:
    version: str
    archetype: str
    layout: LayoutSpec
    canonical_asset: CanonicalSceneAsset
    relationships: tuple[Relationship, ...]
    canvas: dict
    product: dict
    typography: dict
    brand: dict
    environment: dict
    composition: dict
    depth_layers: tuple[dict, ...]
    selection_inputs: dict

    def to_dict(self):
        return asdict(self)

    @property
    def digest(self):
        return hashlib.sha256(json.dumps(self.to_dict(), sort_keys=True,
            ensure_ascii=False, allow_nan=False).encode()).hexdigest()

    def validate_relationships(self):
        anchors = {"canvas": Box(0, 0, self.layout.width, self.layout.height),
                   "safe": Box(self.layout.margin, self.layout.margin,
                       self.layout.width-2*self.layout.margin,
                       self.layout.height-2*self.layout.margin),
                   "product": self.layout.product, "logo": self.layout.logo,
                   "cta_zone": self.layout.cta,
                   **{r.key: r.box for r in self.layout.roles}}
        for relation in self.relationships:
            if abs(getattr(anchors[relation.element], relation.axis)
                   - relation.resolve(anchors)) > .001:
                raise ValueError("Unresolved scene relationship: " + relation.element)


def select_archetype(*, slide_role, aspect_ratio, copy_characters, callout_count,
                     reference_depth):
    if aspect_ratio <= 0 or copy_characters < 0 or callout_count < 0:
        raise ValueError("Invalid scene selection inputs")
    if copy_characters > 240 or callout_count > 2:
        return "EDITORIAL_HERO"
    if aspect_ratio >= 1.25:
        return "PRODUCT_SPOTLIGHT"
    if slide_role in ("feature_detail", "key_feature", "application_experience"):
        return "DIAGONAL_FLOW"
    if reference_depth == "layered" and copy_characters <= 160:
        return "ATMOSPHERIC_PRODUCT_STAGE"
    return "EDITORIAL_HERO"


def compose_unified_scene(ctx, product: Box, *, canonical_asset: CanonicalSceneAsset,
                          product_safe: Box | None = None, background_identity: str,
                          logo_treatment: dict | None = None) -> UnifiedSceneSpec:
    """Resolve roles from shared anchors, then expose one complete scene.

    Typography/content extraction, type minima and hard QA remain in the
    established composer. Impossible prepared geometry is never blessed here;
    its actual render must still pass all existing QA rules.
    """
    base = resolve_composition(ctx, product, product_safe=product_safe)
    w, h, margin = base.width, base.height, base.margin
    g = ctx.reference_target.grammar
    copy_count = sum(len(r.text) for r in base.roles if r.role != "STRUCTURAL")
    callouts = sum(r.role == "FACT_CALLOUT" for r in base.roles)
    selection = dict(slide_role=ctx.slide_role, aspect_ratio=product.width/product.height,
                     copy_characters=copy_count, callout_count=callouts,
                     reference_depth=g.depth)
    archetype = select_archetype(**selection)
    left = g.supporting_copy_position == "left_column"
    gap = .025*w
    available = product.x-gap-margin if left else w-margin-product.right-gap
    # Prepared product has priority. A wide product uses the upper storytelling
    # band; otherwise a shared text axis faces the product across a gutter.
    upper_band = available < .28*w
    column_x = margin if left or upper_band else product.right+gap
    column_width = min(.44*w, available) if not upper_band else .44*w
    anchors = {"canvas": Box(0, 0, w, h), "safe": Box(margin, margin, w-2*margin, h-2*margin),
               "product": product}
    relationships = []
    resolved = []
    previous = None
    # Preserve every approved field; constrain sequential roles as one story.
    # Legal/counter/CTA retain dedicated canvas flow anchors.
    for role in base.roles:
        box = role.box
        if role.role not in ("STRUCTURAL", "LEGAL", "CTA"):
            if role.role in ("HEADLINE", "KICKER"):
                head_left = g.headline_position == "upper_left"
                x_anchor = "safe" if head_left else "product"
                edge = "x" if head_left else "right"
                offset = 0 if head_left else gap
                x = getattr(anchors[x_anchor], edge)+offset
            else:
                x_anchor = "safe" if left or upper_band else "product"
                edge = "x" if left or upper_band else "right"
                offset = 0 if left or upper_band else gap
                x = getattr(anchors[x_anchor], edge)+offset
            y = box.y
            if previous is not None and role.role != "KICKER":
                y = max(y, anchors[previous].bottom+.016*h)
                relationships.append(Relationship(role.key, previous, "y", "bottom", y-anchors[previous].bottom))
            box = Box(x, y, min(box.width, column_width), box.height)
            relationships.append(Relationship(role.key, x_anchor, "x", edge, offset))
            previous = role.key
        elif role.role == "CTA":
            box = Box(column_x, base.cta.y, min(base.cta.width, column_width), base.cta.height)
            relationships.append(Relationship(role.key, 'safe', 'y', 'bottom', box.y-anchors['safe'].bottom))
            relationships.append(Relationship(role.key, 'safe', 'x', 'x', box.x-margin))
        anchors[role.key] = box
        resolved.append(replace(role, box=box))
    # Brand zone uses the same product-facing edge rather than a floating tile.
    logo_right = min(w-margin, product.right)
    logo = Box(logo_right-base.logo.width, margin, base.logo.width, base.logo.height)
    anchors['logo'] = logo
    relationships.append(Relationship('logo','product','x','right',logo.x-product.right))
    cta = next((r.box for r in resolved if r.role == 'CTA'),
               Box(column_x, base.cta.y, min(base.cta.width,column_width), base.cta.height))
    layout = replace(base, roles=tuple(resolved), logo=logo, cta=cta)
    # Typed bounds are consumed by existing QA; intent is not perceptual proof.
    grounding = Box(product.x, product.bottom-.02*h, product.width,
                    min(.04*h, h-(product.bottom-.02*h)))
    breathing = Box(max(0,product.x-.015*w),max(0,product.y-.015*w),
        min(w,product.right+.015*w)-max(0,product.x-.015*w),
        min(h,product.bottom+.015*w)-max(0,product.y-.015*w))
    zones = tuple(dict(role=name, box=asdict(box), active=active) for name,box,active in (
        ('headline', next((r.box for r in resolved if r.role=='HEADLINE'), base.quiet), any(r.role=='HEADLINE' for r in resolved)),
        ('cta', cta, base.cta_required), ('logo',logo,base.logo_required),
        ('product_breathing_room',breathing,True)))
    typography = dict(roles=[asdict(r) for r in resolved],
        support_copy_regions=[asdict(r.box) for r in resolved if r.role in ('SUPPORTING_COPY','VALUE_PROPOSITION')],
        factual_callout_regions=[asdict(r.box) for r in resolved if r.role=='FACT_CALLOUT'],
        cta_region=asdict(cta), alignment='shared_story_axis', hierarchy='approved_role_type_minima',
        foreground_treatment='reference_paint_with_local_contrast',
        support_surface='transparent', opaque_rectangular_panel_required=False)
    scene = UnifiedSceneSpec(SCENE_VERSION,archetype,layout,canonical_asset,tuple(relationships),
        canvas=dict(width=w,height=h,safe_area=asdict(anchors['safe']),
            composition_axis=dict(story_x=column_x,product_x=product.x+product.width/2),
            focal_point=[(product.x+product.width/2)/w,(product.y+product.height/2)/h]),
        product=dict(box=asdict(product),width_fraction=product.width/w,visual_weight='primary' if base.sparse else 'balanced',
            crop=canonical_asset.source_crop,asset_policy='canonical_pixels_only',grounding_region=asdict(grounding),
            contact_shadow=dict(anchor='product.bottom',direction='opposite_key',treatment='soft_contact',rendered=False),
            ambient_shadow=dict(treatment='broad_soft',rendered=False),grounding_plane='product_base_plane',
            halo=dict(treatment='reference_palette_separation',rendered=False),background_relationship='shared_palette_and_base_plane'),
        typography=typography,
        brand=dict(logo_zone=asdict(logo),logo_treatment=logo_treatment or dict(mode='source_supported_brand_zone'),
            accent=ctx.accent_color,palette_roles=dict(text=ctx.text_color,accent=ctx.accent_color,palette=list(ctx.direction_palette)),
            decorative_motif_role='frame_story_to_product_without_claims'),
        environment=dict(background_layer=dict(identity=background_identity,role='environment_only'),
            light_direction='upper_left_to_product',brightness_focus='product',product_illumination_zone=asdict(product),
            text_contrast_zones=[asdict(r.box) for r in resolved],shadow_direction='lower_right',
            background_falloff='away_from_product_and_story_axis',depth='layered',
            tonal_zones=zones,product_separation='reference_palette_rim',visual_framing=archetype),
        composition=dict(negative_space_zones=zones,alignment_relationships='resolved_relationships',
            intentional_overlaps=[],visual_flow=['headline','callout','product','cta'],
            cohesion_links=[['product','background'],['product','headline'],['headline','callout'],
                            ['logo','composition'],['cta','visual_flow'],['light','product']],
            sparse_strategy='atmosphere_and_product_prominence_without_new_copy' if base.sparse else 'editorial_story_stack',
            visual_acceptance=False),
        depth_layers=tuple(dict(name=name,z_index=i,active=name in ('BACKGROUND_LAYER','PRODUCT_LAYER','TYPOGRAPHY_BRAND_LAYER'),
            rendering_scope='existing_pixels' if name in ('BACKGROUND_LAYER','PRODUCT_LAYER') else 'planned_intent')
            for i,name in enumerate(DEPTH_ORDER)),selection_inputs=selection)
    scene.validate_relationships()
    return scene
