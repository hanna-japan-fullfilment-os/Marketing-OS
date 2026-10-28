"""Zero-provider integrity, copy, visual acceptance and budget guard tests."""
import base64
import hashlib
import io
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from app.schemas.ai import ProductFidelityCheck
from app.schemas.creative_bridge import CopyField, CreativeReview, HannaCreativePackage, TextRegion
from app.services.ai.openai_provider import (OpenAIProvider, HardBudgetExceededError,
    _hard_budget_text_cost_upper_bound, creative_review_request, decode_creative_response)
from app.services.multimodal_creative import (compose_candidate, require_final_acceptance,
    overlay_canonical_copy, review_candidate, store_accepted_asset)
from test_build6r_v101_creative_package import package, options


def candidate():
    buffer = io.BytesIO()
    Image.new("RGB", (120, 150), "purple").save(buffer, "PNG")
    return buffer.getvalue()


def review(p, data):
    product = ProductFidelityCheck(**{key: "match" for key in ProductFidelityCheck.model_fields
                                      if key not in ("overall_verdict", "reasoning")},
                                   overall_verdict="PASS", reasoning="fixture only")
    return CreativeReview(package_sha256=p.digest(), candidate_sha256=hashlib.sha256(data).hexdigest(),
        product=product, major_elements="match", components="match", variant="match",
        observed_copy=p.approved_copy, unexpected_marketing_text=(), unsupported_claims=False,
        no_clipping=True, no_overlap=True, product_box=(60, 70, 115, 145),
        **{key: "PASS" for key in ("scene_cohesion", "product_integration", "reference_style",
            "no_disconnected_cards", "logo_integration", "typography_integration", "premium_polish")},
        reasoning="Synthetic complete QA fixture, never actual visual acceptance")


def test_complete_qa_can_store_once_with_bound_provenance(tmp_path):
    p, data = package(tmp_path), candidate()
    result = store_accepted_asset(p, data, review(p, data), tmp_path / "accepted.png")
    assert result["package_sha256"] == p.digest()
    assert result["sha256"] == hashlib.sha256(data).hexdigest()
    with pytest.raises(FileExistsError):
        store_accepted_asset(p, data, review(p, data), tmp_path / "accepted.png")


@pytest.mark.parametrize("field", [key for key in ProductFidelityCheck.model_fields if key not in ("overall_verdict", "reasoning")])
@pytest.mark.parametrize("verdict", ["mismatch", "uncertain"])
def test_every_product_identity_defect_or_uncertainty_rejects(tmp_path, field, verdict):
    p, data = package(tmp_path), candidate()
    r = review(p, data)
    r = r.model_copy(update={"product": r.product.model_copy(update={field: verdict})})
    with pytest.raises(ValueError, match="identity"):
        require_final_acceptance(p, data, r)


@pytest.mark.parametrize("field", ["major_elements", "components", "variant"])
@pytest.mark.parametrize("verdict", ["mismatch", "uncertain"])
def test_missing_elements_fabricated_components_and_wrong_variant_reject(tmp_path, field, verdict):
    p, data = package(tmp_path), candidate()
    with pytest.raises(ValueError, match="identity"):
        require_final_acceptance(p, data, review(p, data).model_copy(update={field: verdict}))


@pytest.mark.parametrize("field", ["scene_cohesion", "product_integration", "reference_style",
    "no_disconnected_cards", "logo_integration", "typography_integration", "premium_polish"])
@pytest.mark.parametrize("verdict", ["FAIL", "UNCERTAIN"])
def test_structural_success_never_overrides_visual_failure(tmp_path, field, verdict):
    p, data = package(tmp_path), candidate()
    with pytest.raises(ValueError, match="Visual QA"):
        require_final_acceptance(p, data, review(p, data).model_copy(update={field: verdict}))


@pytest.mark.parametrize("text", ["Hidratacao", "Hidratação 24h", "hidratação", "Hidrataçao"])
def test_copy_material_difference_is_not_silently_corrected(tmp_path, text):
    p, data = package(tmp_path), candidate()
    r = review(p, data).model_copy(update={"observed_copy": (CopyField(key="headline", text=text), p.approved_copy[1])})
    with pytest.raises(ValueError, match="copy"):
        require_final_acceptance(p, data, r)


@pytest.mark.parametrize("change", [{"observed_copy": ()}, {"unexpected_marketing_text": ("clinically proven",)},
    {"unsupported_claims": True}, {"no_clipping": False}, {"no_overlap": False},
    {"product_box": (0, 0, 121, 150)}, {"candidate_sha256": "stale"}, {"package_sha256": "stale"}])
def test_failed_missing_or_stale_qa_rejected(tmp_path, change):
    p, data = package(tmp_path), candidate()
    with pytest.raises(ValueError):
        require_final_acceptance(p, data, review(p, data).model_copy(update=change))


def test_no_qa_is_not_approval(tmp_path):
    p = package(tmp_path)
    with pytest.raises(AttributeError):
        require_final_acceptance(p, candidate(), None)


def test_review_sees_all_real_sources_and_candidate(tmp_path):
    p, data = package(tmp_path), candidate()
    request = creative_review_request(p, data, model="configured-vision")
    content = request["input"][0]["content"]
    assert len([c for c in content if c["type"] == "input_image"]) == 4
    assert p.digest() in content[0]["text"]
    assert hashlib.sha256(data).hexdigest() in content[0]["text"]
    assert request["text_format"] is CreativeReview


@pytest.mark.asyncio
@pytest.mark.parametrize("budget", [None, 0.5])
async def test_live_bridge_is_blocked_before_client_dispatch(tmp_path, budget):
    p = package(tmp_path)
    provider = OpenAIProvider(api_key=None, hard_budget_usd=budget)
    with pytest.raises(HardBudgetExceededError, match="HARD_BUDGET"):
        await compose_candidate(p, provider, options())
    with pytest.raises(HardBudgetExceededError, match="HARD_BUDGET"):
        await provider.review_creative(package=p, candidate=candidate(), model="configured-vision")
    assert provider._client is None


def test_existing_non_strict_ledger_cannot_underprice_image_generation_tools():
    with pytest.raises(HardBudgetExceededError, match="UNKNOWN_MULTIMODAL"):
        _hard_budget_text_cost_upper_bound(model="any", request_kwargs={"tools": [{"type": "image_generation"}]})


@pytest.mark.asyncio
async def test_one_attempt_no_retry_no_renderer_fallback(tmp_path):
    class FailedProvider:
        calls = 0
        async def compose_creative(self, **kwargs):
            self.calls += 1
            raise RuntimeError("explicit failure")
    provider = FailedProvider()
    with pytest.raises(RuntimeError, match="explicit failure"):
        await compose_candidate(package(tmp_path), provider, options())
    assert provider.calls == 1


def test_decoder_requires_one_complete_image():
    item = SimpleNamespace(type="image_generation_call", status="completed", result=base64.b64encode(candidate()).decode())
    assert decode_creative_response(SimpleNamespace(status="completed", output=[item])) == candidate()
    for status, items in (("incomplete", [item]), ("completed", []), ("completed", [item, item])):
        with pytest.raises(ValueError):
            decode_creative_response(SimpleNamespace(status=status, output=items))


def test_direct_overlay_has_no_panels_and_keeps_outside_pixels(tmp_path):
    p = package(tmp_path)
    regions = tuple(TextRegion(key=c.key, box=(0, i*40, 119, i*40+35), font_id="approved", font_size=12,
                               color="#ffffff") for i, c in enumerate(p.approved_copy))
    p = HannaCreativePackage.model_validate({**p.model_dump(), "text_mode": "negative_space_overlay", "text_regions": regions})
    font = Path("C:/Windows/Fonts/arial.ttf")
    result = overlay_canonical_copy(p, candidate(), fonts={"approved": font})
    with Image.open(io.BytesIO(result)) as image:
        assert image.getpixel((119, 149))[:3] == (128, 0, 128)
    assert result != candidate()
    # New pixels invalidate any old QA, even when the overlay uses canonical strings.
    with pytest.raises(ValueError, match="Stale"):
        require_final_acceptance(p, result, review(p, candidate()))
    with pytest.raises(ValueError, match="font"):
        overlay_canonical_copy(p, candidate(), fonts={})


def test_tiny_prepared_region_rejects_instead_of_shrinking_or_panel_fallback(tmp_path):
    p = package(tmp_path)
    regions = tuple(TextRegion(key=c.key, box=(0, i*20, 2, i*20+2), font_id="approved", font_size=12,
                               color="#ffffff") for i, c in enumerate(p.approved_copy))
    p = HannaCreativePackage.model_validate({**p.model_dump(), "text_mode": "negative_space_overlay", "text_regions": regions})
    with pytest.raises(ValueError, match="does not fit"):
        overlay_canonical_copy(p, candidate(), fonts={"approved": Path("C:/Windows/Fonts/arial.ttf")})


@pytest.mark.asyncio
async def test_unified_native_to_final_resampling_requires_matching_aspect(tmp_path):
    p = package(tmp_path)
    class FakeProvider:
        async def compose_creative(self, **kwargs):
            buffer = io.BytesIO()
            Image.new("RGB", (1088, 1360), "purple").save(buffer, "PNG")
            return buffer.getvalue()
    result = await compose_candidate(p, FakeProvider(), options().model_copy(update={"image_size": "1088x1360"}))
    with Image.open(io.BytesIO(result)) as image:
        assert image.size == (120, 150)
    with pytest.raises(ValueError, match="aspect"):
        await compose_candidate(p, FakeProvider(), options().model_copy(update={"image_size": "1024x1536"}))
    with pytest.raises(ValueError, match="native"):
        await compose_candidate(p, FakeProvider(), options().model_copy(update={"image_size": "120x150"}))


def test_no_v9_compositor_import_or_panel_drawing():
    import inspect
    from app.services import multimodal_creative
    source = inspect.getsource(multimodal_creative)
    for forbidden in ("render_slide", "premium_render", "render_premium", "draw.rectangle", "rounded_rectangle"):
        assert forbidden not in source
