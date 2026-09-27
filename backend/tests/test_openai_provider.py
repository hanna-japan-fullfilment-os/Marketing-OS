"""Direct unit tests of `OpenAIProvider` — the one module allowed to import the
`openai` SDK. Every other test in this suite exercises a Fake provider instead
(so campaign/research/orchestrator logic never needs a real API key), which means
this module's own behavior — in particular, whether `generate()` actually does
something different when `reference_images` is passed — was previously untested.
None of this needs a real network call or API key: `OpenAIProvider._client` is a
real `AsyncOpenAI` instance, but we swap it for a small fake double that records
what it was called with, matching the SDK's async method shapes.
"""
from __future__ import annotations

import base64
from types import SimpleNamespace

import pytest

from app.schemas.ai import BrandVisualStyleAnalysis, ProductZoneDetection
from app.services.ai.openai_provider import OpenAIProvider



def _write_valid_test_image(
    path,
    image_format,
):
    from PIL import Image

    image = Image.new(
        "RGB",
        (8, 8),
        (32, 64, 96),
    )

    image.save(
        path,
        format=image_format,
    )


class _FakeImagesAPI:
    def __init__(self):
        self.generate_calls: list[dict] = []
        self.edit_calls: list[dict] = []

    async def generate(self, **kwargs):
        self.generate_calls.append(kwargs)
        return SimpleNamespace(data=[SimpleNamespace(b64_json=base64.b64encode(b"generated").decode())])

    async def edit(self, **kwargs):
        self.edit_calls.append(kwargs)
        return SimpleNamespace(data=[SimpleNamespace(b64_json=base64.b64encode(b"edited").decode())])


class _FakeResponsesAPI:
    def __init__(self, parsed=None):
        self.parsed = parsed
        self.parse_calls: list[dict] = []

    async def parse(self, **kwargs):
        self.parse_calls.append(kwargs)
        return SimpleNamespace(output_parsed=self.parsed)


class _FakeClient:
    def __init__(self, parsed=None):
        self.images = _FakeImagesAPI()
        self.responses = _FakeResponsesAPI(parsed)


def _provider_with_fake_client(parsed=None) -> tuple[OpenAIProvider, _FakeClient]:
    provider = OpenAIProvider("sk-fake")  # real key format so __init__ builds a real (unused) client
    fake = _FakeClient(parsed)
    provider._client = fake  # swap in the double before any call touches the network
    return provider, fake


@pytest.mark.asyncio
async def test_no_client_raises_clear_error():
    provider = OpenAIProvider("")  # empty key -> _client is None
    with pytest.raises(RuntimeError, match="OpenAI API key is not configured"):
        await provider.vision_describe(image_path=__file__, prompt="describe", model="gpt-5.1")  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_generate_without_reference_images_uses_generate_endpoint():
    provider, fake = _provider_with_fake_client()
    result = await provider.generate(prompt="a scene", size="1024x1024", model="gpt-image-1")
    assert result == b"generated"
    assert len(fake.images.generate_calls) == 1
    assert fake.images.edit_calls == []


@pytest.mark.asyncio
async def test_generate_with_reference_images_uses_edit_endpoint(tmp_path):
    """This is the fix: `reference_images` was declared on the ImageProvider
    protocol from round 1 but silently ignored by the implementation — passing it
    changed nothing about what got generated. Now it routes to `images.edit` with
    every reference image attached, so a brand's uploaded visual-reference photos
    genuinely act as a style reference.
    """
    ref1 = tmp_path / "ref1.png"
    ref2 = tmp_path / "ref2.png"
    _write_valid_test_image(ref1, "PNG")
    _write_valid_test_image(ref2, "PNG")

    provider, fake = _provider_with_fake_client()
    result = await provider.generate(
        prompt="a scene", size="1024x1024", model="gpt-image-1", reference_images=[ref1, ref2],
    )
    assert result == b"edited"
    assert fake.images.generate_calls == []
    assert len(fake.images.edit_calls) == 1
    call = fake.images.edit_calls[0]
    assert call["prompt"] == "a scene"
    assert len(call["image"]) == 2  # both reference images were attached



@pytest.mark.asyncio
async def test_analyze_visual_style_sends_every_image_and_returns_parsed_schema(tmp_path):
    ref = tmp_path / "ref.png"
    _write_valid_test_image(ref, "PNG")
    expected = BrandVisualStyleAnalysis(
        summary="Warm, editorial J-beauty flat-lays.",
        dominant_colors=["#f5e6d3", "#2b2b2b"],
        typography_mood="clean minimalist sans-serif",
        photography_style="soft natural light, flat-lay",
        visual_style_descriptors=["minimal", "warm neutrals"],
        voice_suggestion="warm, expert, unhurried",
    )
    provider, fake = _provider_with_fake_client(parsed=expected)

    result = await provider.analyze_visual_style(image_paths=[ref], brand_name="Hanna Japan Store", model="gpt-5.1")

    assert result is expected
    assert len(fake.responses.parse_calls) == 1
    call = fake.responses.parse_calls[0]
    assert call["text_format"] is BrandVisualStyleAnalysis
    content = call["input"][0]["content"]
    # One input_text block plus one input_image block per reference photo.
    assert content[0]["type"] == "input_text"
    assert sum(1 for block in content if block["type"] == "input_image") == 1



@pytest.mark.asyncio
async def test_analyze_visual_style_raises_when_model_returns_nothing(tmp_path):
    ref = tmp_path / "ref.png"
    _write_valid_test_image(ref, "PNG")
    provider, _fake = _provider_with_fake_client(parsed=None)
    with pytest.raises(ValueError, match="did not return a structured response"):
        await provider.analyze_visual_style(image_paths=[ref], brand_name="Hanna Japan Store", model="gpt-5.1")



@pytest.mark.asyncio
async def test_detect_product_zone_sends_the_real_photo_and_returns_parsed_schema(tmp_path):
    photo = tmp_path / "product.jpg"
    _write_valid_test_image(photo, "JPEG")
    expected = ProductZoneDetection(
        crop_left=0.15, crop_top=0.2, crop_width=0.6, crop_height=0.55, anchor="bottom",
        reasoning="Bottle stands on a table in the lower half of the frame.",
    )
    provider, fake = _provider_with_fake_client(parsed=expected)

    result = await provider.detect_product_zone(image_path=photo, model="gpt-5.1")

    assert result is expected
    assert len(fake.responses.parse_calls) == 1
    call = fake.responses.parse_calls[0]
    assert call["text_format"] is ProductZoneDetection
    content = call["input"][0]["content"]
    assert content[0]["type"] == "input_text"
    assert content[1]["type"] == "input_image"
    assert content[1]["image_url"].startswith("data:image/jpeg;base64,")




@pytest.mark.asyncio
async def test_detect_product_zone_raises_when_model_returns_nothing(tmp_path):
    photo = tmp_path / "product.jpg"
    _write_valid_test_image(photo, "JPEG")
    provider, _fake = _provider_with_fake_client(parsed=None)
    with pytest.raises(ValueError, match="did not return a structured response"):
        await provider.detect_product_zone(image_path=photo, model="gpt-5.1")

