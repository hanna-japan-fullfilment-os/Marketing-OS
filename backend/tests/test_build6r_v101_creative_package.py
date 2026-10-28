"""Offline package, real raster transport and controlled-edit contract tests."""
import base64
import hashlib
import io
import json

import pytest
from PIL import Image

from app.schemas.creative_bridge import CopyField, CreativeOptions, HannaCreativePackage, TextRegion
from app.services.hanna_creative_package import image_record, verified_image_bytes
from app.services.ai.openai_provider import creative_director_request


def raster(tmp_path, key, role, *, mode="RGBA", size=(120, 150)):
    path = tmp_path / (key + ".png")
    Image.new(mode, size, "purple").save(path)
    return image_record(asset_id=key, role=role, path=path,
        expected_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        authority="test existing approval", provenance={"existing_approval": key})


def package(tmp_path, **changes):
    data = dict(campaign_id="campaign", brand_id="brand", product_id="product",
        product_name="Exact variant 7 sheets", category="skincare", slide_id="slide-1", slide_role="cover",
        locale="pt-BR", channel="instagram", approved_facts_json='{"existing_claim_id":"seven-sheets"}',
        slide_contract_json='{"existing_plan":"immutable"}',
        approved_copy=(CopyField(key="headline", text="Hidratação"), CopyField(key="cta", text="Conheça")),
        prohibited_claims=("No invented clinical result",), brand_instructions="Premium Hanna restraint",
        visual_objective="Unified premium reference-directed artwork", width=120, height=150,
        aspect_ratio="120:150", required_cta="Conheça",
        images=tuple(raster(tmp_path, key, role) for key, role in
                     (("source", "product_source"), ("reference", "visual_reference"), ("logo", "logo"))))
    data.update(changes)
    return HannaCreativePackage(**data)


def options():
    return CreativeOptions(director_model="caller-configured-director", image_model="caller-configured-image",
                           image_size="1024x1280", max_output_tokens=2048)


def test_canonical_package_roundtrip_and_deterministic_provenance(tmp_path):
    p = package(tmp_path)
    assert HannaCreativePackage.model_validate_json(p.model_dump_json()) == p
    assert p.digest() == HannaCreativePackage.model_validate(p.model_dump()).digest()
    assert p.digest() != p.model_copy(update={"visual_objective": "changed"}).digest()
    with pytest.raises(Exception):
        p.product_id = "changed"


def test_real_images_facts_prohibitions_and_instructions_are_sent_together(tmp_path):
    p = package(tmp_path)
    request = creative_director_request(p, options())
    content = request["input"][0]["content"]
    blobs = [c["image_url"] for c in content if c["type"] == "input_image"]
    assert len(blobs) == 3
    assert [base64.b64decode(b.split(",", 1)[1]) for b in blobs] == [verified_image_bytes(a) for a in p.images]
    assert "seven-sheets" in content[0]["text"]
    assert "No invented clinical result" in content[0]["text"]
    assert "unified artwork" in request["instructions"]
    assert request["tools"][0]["model"] == options().image_model
    assert request["model"] == options().director_model
    assert request["max_tool_calls"] == 1 and not request["parallel_tool_calls"]
    assert request["store"] is False


def test_multiple_real_product_angles(tmp_path):
    p = package(tmp_path)
    second = raster(tmp_path, "side-angle", "product_source")
    p = HannaCreativePackage.model_validate({**p.model_dump(), "images": (*p.images, second)})
    assert sum(c["type"] == "input_image" for c in creative_director_request(p, options())["input"][0]["content"]) == 4


@pytest.mark.parametrize("missing", ["product_source", "visual_reference", "logo"])
def test_missing_authority_rejected(tmp_path, missing):
    p = package(tmp_path)
    with pytest.raises(ValueError):
        HannaCreativePackage.model_validate({**p.model_dump(), "images": [a for a in p.images if a.role != missing]})


@pytest.mark.parametrize("field,value", [("prohibited_claims", []), ("approved_facts_json", "{}"),
    ("slide_contract_json", "{}"), ("required_cta", "invented"), ("aspect_ratio", "4:5"),
    ("images", []), ("unknown", True)])
def test_incomplete_or_ambiguous_contract_rejected(tmp_path, field, value):
    p = package(tmp_path)
    with pytest.raises(ValueError):
        HannaCreativePackage.model_validate({**p.model_dump(), field: value})


def test_changed_raster_rejected_before_translation(tmp_path):
    p = package(tmp_path)
    from pathlib import Path
    Path(p.images[0].path).write_bytes(b"changed")
    with pytest.raises(ValueError, match="changed"):
        creative_director_request(p, options())


def test_mask_is_separate_and_base_is_first(tmp_path):
    p = package(tmp_path)
    base, mask = raster(tmp_path, "prepared-base", "base"), raster(tmp_path, "edit-mask", "mask")
    p = HannaCreativePackage.model_validate({**p.model_dump(), "images": (*p.images, mask, base)})
    request = creative_director_request(p, options())
    tool = request["tools"][0]
    assert tool["action"] == "edit"
    assert tool["input_image_mask"]["image_url"].startswith("data:image/png;base64,")
    labels = [c["text"] for c in request["input"][0]["content"] if c["type"] == "input_text"]
    assert json.loads(labels[1])["role"] == "base"
    assert sum(c["type"] == "input_image" for c in request["input"][0]["content"]) == 4
    assert "not proof" in request["instructions"]


@pytest.mark.parametrize("mode,size", [("RGB", (120, 150)), ("RGBA", (119, 150))])
def test_invalid_mask_fails_closed(tmp_path, mode, size):
    p = package(tmp_path)
    images = (*p.images, raster(tmp_path, "base", "base"), raster(tmp_path, "mask", "mask", mode=mode, size=size))
    p = HannaCreativePackage.model_validate({**p.model_dump(), "images": images})
    with pytest.raises(ValueError, match="Mask"):
        creative_director_request(p, options())


def test_overlay_requires_every_copy_field_exactly_once(tmp_path):
    p = package(tmp_path)
    with pytest.raises(ValueError, match="Every canonical"):
        HannaCreativePackage.model_validate({**p.model_dump(), "text_mode": "negative_space_overlay"})
    regions = tuple(TextRegion(key=c.key, box=(0, i*50, 120, i*50+40), font_id="approved", font_size=12,
                               color="#ffffff") for i, c in enumerate(p.approved_copy))
    overlay = HannaCreativePackage.model_validate({**p.model_dump(), "text_mode": "negative_space_overlay", "text_regions": regions})
    assert overlay.approved_copy == p.approved_copy
