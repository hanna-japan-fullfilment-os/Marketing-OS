"""Bounded V11 locked-product edit contract; not a general renderer layout."""
from pydantic import Field, model_validator

from .creative_bridge import Contract, CreativeImage, CreativeReview
from .creative_delivery import PreparedDelivery


class LockedSceneConfig(Contract):
    protection_margin: int = Field(default=4, ge=0, le=32)
    grounding_width: int = Field(default=24, gt=0, le=96)
    light_direction: str = Field(default="upper-left key light, restrained violet rim", min_length=1, max_length=200)

    @model_validator(mode="after")
    def editable_ring(self):
        if self.grounding_width <= self.protection_margin:
            raise ValueError("Grounding ring must extend beyond protection margin")
        return self


class LockedScenePlan(Contract):
    delivery: PreparedDelivery
    master_asset_id: str
    master_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_alpha_bbox: tuple[int, int, int, int]
    final_product_box: tuple[int, int, int, int]
    native_product_box: tuple[int, int, int, int]
    canonical_layer_pixel_sha256: str
    alpha_pixel_sha256: str
    config: LockedSceneConfig = LockedSceneConfig()


class SceneEditAssets(Contract):
    plan: LockedScenePlan
    base: CreativeImage
    environment_mask: CreativeImage
    product_layer: CreativeImage
    protection_mask: CreativeImage
    grounding_ring: CreativeImage

    @model_validator(mode="after")
    def native(self):
        for asset in (self.base, self.environment_mask, self.product_layer,
                      self.protection_mask, self.grounding_ring):
            if (asset.width, asset.height) != (1024,1536) or asset.mime_type != "image/png":
                raise ValueError("Scene assets must match the native edit canvas")
        if self.base.role != "base" or self.environment_mask.role != "mask":
            raise ValueError("Base/mask roles must remain explicit")
        return self


class LockedSceneReview(Contract):
    creative_review: CreativeReview
    no_generated_product_outside_canonical_layer: bool
    no_generated_final_marketing_text: bool
    no_generated_logo_outside_canonical_layer: bool
    no_duplicate_product_shadows: bool
    postable: bool
