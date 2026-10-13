from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from PIL import Image

BACKEND = Path(__file__).resolve().parents[1]
SERVICE_PATH = BACKEND / "app" / "services" / "product_integration_polish.py"
HARNESS_PATH = BACKEND / "scripts" / "run_product_integration_polish.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
        return module
    except Exception:
        sys.modules.pop(name, None)
        raise


def _product_layer(path: Path) -> None:
    image = Image.new("RGBA", (1024, 1536), (0, 0, 0, 0))
    for y in range(420, 1450):
        for x in range(180, 844):
            image.putpixel((x, y), (85, 35, 135, 255))
    image.save(path)


def test_service_has_no_ai_or_provider_dependency():
    source = SERVICE_PATH.read_text(encoding="utf-8").casefold()
    for forbidden in (
        "openai",
        "provider.generate",
        "image_gen",
        "reference_images",
        "requests.",
        "httpx",
    ):
        assert forbidden not in source


def test_harness_has_no_ai_or_provider_dependency():
    source = HARNESS_PATH.read_text(encoding="utf-8").casefold()
    for forbidden in (
        "openai",
        "provider.generate",
        "image_gen",
        "run_live_acceptance",
    ):
        assert forbidden not in source


def test_three_deterministic_shadow_profiles():
    mod = _load(SERVICE_PATH, "v339_profiles")
    assert [item.name for item in mod.SHADOW_PROFILES] == [
        "subtle",
        "balanced",
        "strong",
    ]
    assert mod.RECOMMENDED_PROFILE == "balanced"


def test_profiles_within_governed_ranges():
    mod = _load(SERVICE_PATH, "v339_ranges")
    for profile in mod.SHADOW_PROFILES:
        assert 0.90 <= profile.horizontal_scale <= 0.94
        assert 58 <= profile.height_px <= 74
        assert 24.0 <= profile.blur_radius <= 30.0
        assert 0.20 <= profile.opacity <= 0.28
        assert 8 <= profile.y_offset <= 12


def test_contact_shadow_is_alpha_derived(tmp_path):
    mod = _load(SERVICE_PATH, "v339_alpha")
    product = tmp_path / "product.png"
    _product_layer(product)
    with Image.open(product) as image:
        layer = image.convert("RGBA")
    shadow, meta = mod.build_contact_shadow(layer, mod.SHADOW_PROFILES[1])
    assert shadow.size == mod.CANVAS_SIZE
    assert meta["source"] == "locked_product_alpha_mask"
    assert meta["ai_generated"] is False
    assert meta["product_pixels_modified"] is False
    assert shadow.getchannel("A").getbbox() is not None


def test_contact_shadow_does_not_mutate_input_image(tmp_path):
    mod = _load(SERVICE_PATH, "v339_no_mutate")
    product = tmp_path / "product.png"
    _product_layer(product)
    with Image.open(product) as image:
        layer = image.convert("RGBA")
    before = layer.tobytes()
    mod.build_contact_shadow(layer, mod.SHADOW_PROFILES[1])
    after = layer.tobytes()
    assert before == after


def test_render_profile_preserves_product_file_bytes(tmp_path):
    mod = _load(SERVICE_PATH, "v339_file_immutable")
    background = tmp_path / "background.png"
    product = tmp_path / "product.png"
    text = tmp_path / "text.png"
    output = tmp_path / "output"
    Image.new("RGBA", (1024, 1536), (65, 35, 100, 255)).save(background)
    _product_layer(product)
    Image.new("RGBA", (1024, 1536), (0, 0, 0, 0)).save(text)
    before = mod.sha256_file(product)
    result = mod.render_profile(
        background_path=background,
        locked_product_path=product,
        text_layer_path=text,
        background_sha256=mod.sha256_file(background),
        locked_product_sha256=before,
        text_layer_sha256=mod.sha256_file(text),
        profile=mod.SHADOW_PROFILES[1],
        output_dir=output,
    )
    after = mod.sha256_file(product)
    assert before == after
    assert result["locked_product_layer_immutability"] is True
    assert result["product_pixel_mutation_count"] == 0
    assert result["reflection_enabled"] is False


def test_composition_order_keeps_product_above_shadow(tmp_path):
    mod = _load(SERVICE_PATH, "v339_order")
    background = Image.new("RGBA", (1024, 1536), (255, 255, 255, 255))
    shadow = Image.new("RGBA", (1024, 1536), (0, 0, 0, 0))
    product = Image.new("RGBA", (1024, 1536), (0, 0, 0, 0))
    text = Image.new("RGBA", (1024, 1536), (0, 0, 0, 0))
    shadow.putpixel((500, 1400), (0, 0, 0, 200))
    product.putpixel((500, 1400), (100, 50, 150, 255))
    final = mod.compose_polished(
        background=background,
        shadow_layer=shadow,
        locked_product_layer=product,
        text_layer=text,
    )
    assert final.getpixel((500, 1400))[:3] == (100, 50, 150)


def test_text_layer_is_composited_last():
    source = SERVICE_PATH.read_text(encoding="utf-8")
    shadow_index = source.index("final.alpha_composite(shadow_layer.convert")
    product_index = source.index("final.alpha_composite(locked_product_layer.convert")
    text_index = source.index("final.alpha_composite(text_layer.convert")
    assert shadow_index < product_index < text_index


def test_reflection_is_not_enabled_by_default():
    source = HARNESS_PATH.read_text(encoding="utf-8")
    assert '"reflection_enabled": False' in source


def test_source_validation_fails_closed_on_hash_mismatch(tmp_path):
    mod = _load(SERVICE_PATH, "v339_hash")
    image = tmp_path / "layer.png"
    Image.new("RGBA", (1024, 1536), (0, 0, 0, 0)).save(image)
    with pytest.raises(RuntimeError, match="SHA-256 mismatch"):
        mod.validate_layer(image, "0" * 64)


def test_source_validation_fails_closed_on_dimensions(tmp_path):
    mod = _load(SERVICE_PATH, "v339_dims")
    image = tmp_path / "layer.png"
    Image.new("RGBA", (100, 100), (0, 0, 0, 0)).save(image)
    sha = mod.sha256_file(image)
    with pytest.raises(RuntimeError, match="dimensions"):
        mod.validate_layer(image, sha)


def test_product_layer_requires_rgba(tmp_path):
    mod = _load(SERVICE_PATH, "v339_mode")
    image = tmp_path / "product.png"
    Image.new("RGB", (1024, 1536), (0, 0, 0)).save(image)
    sha = mod.sha256_file(image)
    with pytest.raises(RuntimeError, match="mode"):
        mod.validate_layer(image, sha, required_mode="RGBA")


def test_harness_reuses_exact_v338_artifact_hashes():
    mod = _load(HARNESS_PATH, "v339_harness_hashes")
    assert mod.EXPECTED_BACKGROUND_SHA256 == (
        "e217b89868314f44164954b9f75f980aa3a377272ca9f3bfc1baa9e6d7a5b6c4"
    )
    assert mod.EXPECTED_LOCKED_PRODUCT_SHA256 == (
        "b3fc6e513fcdf94a80af385d9bc7ad75b3d53ac811b9aa982f8142bc2c90d09b"
    )
    assert mod.EXPECTED_TEXT_LAYER_SHA256 == (
        "f52358cb59993b01c0480e99f09a9514fc03d8d0a552c8f28d632b2a54f8df22"
    )
    assert mod.EXPECTED_V338_FINAL_SHA256 == (
        "9de5d934ea1c3ac7bbc4d6b1cc961031b3a83fce098edcca57ae04f214cf8315"
    )


def test_no_product_geometry_transform_surface():
    source = SERVICE_PATH.read_text(encoding="utf-8").casefold()
    for forbidden in (
        ".rotate(",
        ".transform(",
        "perspective",
        "warp",
        "inpaint",
        "outpaint",
        "sharpen",
    ):
        assert forbidden not in source