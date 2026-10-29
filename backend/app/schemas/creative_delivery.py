"""Provider-neutral precomputed delivery geometry and semantic image selection."""
from typing import Literal

from pydantic import Field, model_validator

from .creative_bridge import Contract, CreativeImage, HannaCreativePackage

Box = tuple[int, int, int, int]


class CompositionGuide(Contract):
    generation_size: Literal["1024x1536"] = "1024x1536"
    final_size: Literal["1024x1280"] = "1024x1280"
    # All other boxes use FINAL coordinates. Add crop.y to translate to native.
    final_crop: tuple[Literal[0], Literal[128], Literal[1024], Literal[1408]] = (0, 128, 1024, 1408)
    product_region: Box = (520, 350, 991, 1140)
    headline_region: Box = (56, 70, 480, 250)
    supporting_copy_region: Box = (56, 280, 480, 465)
    factual_callout_region: Box = (56, 495, 480, 790)
    cta_region: Box = (56, 1090, 480, 1170)
    logo_region: Box = (56, 1200, 300, 1240)
    breathing_space: tuple[Box, ...] = ((0, 0, 1024, 40), (0, 1248, 1024, 1280))
    quiet_zones: tuple[Box, ...]
    decorative_zones: tuple[Box, ...] = ((500, 70, 980, 300), (520, 1160, 980, 1220))

    @model_validator(mode="after")
    def valid_boxes(self):
        boxes = [self.product_region, self.headline_region, self.supporting_copy_region,
                 self.factual_callout_region, self.cta_region, self.logo_region,
                 *self.breathing_space, *self.quiet_zones, *self.decorative_zones]
        if any(not (0 <= l < r <= 1024 and 0 <= t < b <= 1280) for l, t, r, b in boxes):
            raise ValueError("Composition region outside retained final crop")
        return self


class SelectedReference(Contract):
    role: Literal["PRODUCT_REFERENCE", "STYLE_REFERENCE"]
    purpose: Literal["product_identity", "composition_language", "brand_identity"]
    asset: CreativeImage

    @model_validator(mode="after")
    def semantic_role(self):
        allowed = {"product_identity": ("PRODUCT_REFERENCE", ("product_source", "product_master")),
                   "composition_language": ("STYLE_REFERENCE", ("visual_reference",)),
                   "brand_identity": ("STYLE_REFERENCE", ("logo",))}
        role, assets = allowed[self.purpose]
        if self.role != role or self.asset.role not in assets:
            raise ValueError("Product/style image role escalation")
        return self


class DirectEditSettings(Contract):
    model: Literal["gpt-image-2.5-sunburst", "gpt-image-2.5-sunburst-2026-09-08"] = "gpt-image-2.5-sunburst-2026-09-08"
    quality: Literal["high"] = "high"
    size: Literal["1024x1536"] = "1024x1536"
    background: Literal["opaque"] = "opaque"
    n: Literal[1] = 1
    partial_images: Literal[0] = 0
    stream: Literal[False] = False
    output_format: Literal["png"] = "png"


class PreparedDelivery(Contract):
    original_package_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    package: HannaCreativePackage
    guide: CompositionGuide
    references: tuple[SelectedReference, ...] = Field(min_length=2, max_length=7)
    settings: DirectEditSettings = DirectEditSettings()

    @model_validator(mode="after")
    def bound_contract(self):
        products = [r for r in self.references if r.role == "PRODUCT_REFERENCE"]
        styles = [r for r in self.references if r.role == "STYLE_REFERENCE"]
        if not 1 <= len(products) <= 3 or not 1 <= len(styles) <= 4:
            raise ValueError("Product/style reference count outside governed limits")
        if not any(r.asset.role == "product_source" for r in products):
            raise ValueError("Actual source product photograph required")
        if not any(r.purpose == "composition_language" for r in styles):
            raise ValueError("Actual approved reference composition required")
        if len({r.asset.asset_id for r in self.references}) != len(self.references):
            raise ValueError("Duplicate selected reference")
        known = {a.asset_id: a for a in self.package.images}
        if any(known.get(r.asset.asset_id) != r.asset for r in self.references):
            raise ValueError("Selection differs from canonical package")
        if self.package.logo_required and sum(r.purpose == "brand_identity" for r in styles) != 1:
            raise ValueError("Canonical brand identity image missing")
        if (self.package.width, self.package.height) != (1024, 1280):
            raise ValueError("Delivery package must match final crop dimensions")
        for region in self.package.text_regions:
            if region.box not in self.guide.quiet_zones:
                raise ValueError("Text region lacks precomputed quiet-space instruction")
        return self
