"""Direct delivery is verified offline. Fixtures are never visual acceptance."""
import base64
import hashlib
import io
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from app.schemas.creative_bridge import HannaCreativePackage
from app.schemas.creative_delivery import CompositionGuide, DirectEditSettings, PreparedDelivery, SelectedReference
from app.services.ai.openai_provider import (OpenAIProvider, HardBudgetExceededError,
    direct_images_edit_request, decode_direct_edit_response)
from app.services.creative_delivery import (prepare_delivery, select_references, direct_edit_prompt,
    crop_and_treat, deliver_candidate, accept_delivery)
from app.services.multimodal_cost import CostComponent, CostQuote, estimate_multimodal_cost, SunburstCostEstimator
from test_build6r_v101_creative_package import package, raster


def native():
    buffer = io.BytesIO()
    image = Image.new("RGB", (1024, 1536), "purple")
    # Exact coordinate-dependent pixels demonstrate a crop, not resize/stretch.
    image.putpixel((700, 128), (255, 0, 0))
    image.putpixel((700, 1407), (0, 255, 0))
    image.save(buffer, "PNG")
    return buffer.getvalue()


def test_direct_sdk_request_constructs_actual_multipart_inputs_and_labeled_roles(tmp_path):
    original = package(tmp_path)
    delivery = prepare_delivery(original)
    request = direct_images_edit_request(delivery)
    assert request["model"] == "gpt-image-2.5-sunburst-2026-09-08"
    assert request["n"] == 1 and request["size"] == "1024x1536" and request["quality"] == "high"
    assert request["background"] == "opaque" and request["partial_images"] == 0
    assert request["stream"] is False and request["output_format"] == "png"
    assert len(request["image"]) == 3  # source, composition, canonical brand logo
    assert request["image"][0][0] == "1_PRODUCT_REFERENCE.png"
    assert request["image"][1][0] == "2_STYLE_REFERENCE.png"
    for entry, selected in zip(request["image"], delivery.references):
        assert hashlib.sha256(entry[1]).hexdigest() == selected.asset.sha256
    assert "product_identity" in request["prompt"] and "composition_language" in request["prompt"]
    assert "brand_identity" in request["prompt"]
    assert original.width == 120  # only the ephemeral delivery package changes geometry
    assert delivery.package.approved_copy == original.approved_copy
    assert delivery.package.approved_facts_json == original.approved_facts_json


def test_deterministic_minimal_selection_independent_of_inventory_order(tmp_path):
    p = package(tmp_path)
    extras = (raster(tmp_path, "angle", "product_source"), raster(tmp_path, "style2", "visual_reference"))
    p = HannaCreativePackage.model_validate({**p.model_dump(), "images": (*p.images, *extras)})
    reversed_package = HannaCreativePackage.model_validate({**p.model_dump(), "images": tuple(reversed(p.images))})
    assert select_references(p) == select_references(reversed_package)
    assert len(select_references(p)) == 3
    selected = select_references(p)
    primary = next(r.asset.asset_id for r in selected if r.role == "PRODUCT_REFERENCE")
    extra_product = next(a.asset_id for a in p.images if a.role == "product_source" and a.asset_id != primary)
    reference = next(r.asset.asset_id for r in selected if r.purpose == "composition_language")
    extra_style = next(a.asset_id for a in p.images if a.role == "visual_reference" and a.asset_id != reference)
    delivery = prepare_delivery(p, alternate_product_ids=(extra_product,), additional_style_ids=(extra_style,))
    assert len(delivery.references) == 5
    request = direct_images_edit_request(delivery)
    assert len(request["image"]) == 5
    assert sum(r.role == "PRODUCT_REFERENCE" for r in delivery.references) == 2


@pytest.mark.parametrize("extras", [dict(alternate_product_ids=("missing",)),
    dict(alternate_product_ids=("reference",)), dict(additional_style_ids=("source",)),
    dict(additional_style_ids=("reference", "reference"))])
def test_untrusted_alternate_selection_rejected(tmp_path, extras):
    with pytest.raises(ValueError):
        prepare_delivery(package(tmp_path), **extras)


def test_count_limit_is_enforced_before_request(tmp_path):
    p = package(tmp_path)
    extras = tuple(raster(tmp_path, "extra"+str(i), "product_source") for i in range(4))
    p = HannaCreativePackage.model_validate({**p.model_dump(), "images": (*p.images, *extras)})
    with pytest.raises(ValueError, match="counts"):
        prepare_delivery(p, alternate_product_ids=tuple(a.asset_id for a in extras))


@pytest.mark.parametrize("role,purpose,asset_role", [("STYLE_REFERENCE", "product_identity", "product_source"),
    ("PRODUCT_REFERENCE", "composition_language", "visual_reference"),
    ("PRODUCT_REFERENCE", "product_identity", "logo")])
def test_semantic_role_escalation_rejected(tmp_path, role, purpose, asset_role):
    p = package(tmp_path)
    asset = next(a for a in p.images if a.role == asset_role)
    with pytest.raises(ValueError, match="role escalation"):
        SelectedReference(role=role, purpose=purpose, asset=asset)


def test_composition_is_precomputed_for_real_copy_and_native_crop(tmp_path):
    d = prepare_delivery(package(tmp_path))
    assert d.guide.final_crop == (0, 128, 1024, 1408)
    assert (d.package.width, d.package.height) == (1024, 1280)
    assert {r.key for r in d.package.text_regions} == {c.key for c in d.package.approved_copy}
    assert all(r.box in d.guide.quiet_zones for r in d.package.text_regions)
    prompt = direct_edit_prompt(d)
    for exact in ("ADD 128", "y=[128,1408)", "PRODUCT_REFERENCE", "STYLE_REFERENCE", "one coordinated",
                  "do not substitute", "invent physical", "packaging geometry", "no generic panel fallback",
                  "Emit no marketing text", "Hidratação", "Conheça"):
        assert exact in prompt
    assert "No invented clinical result" in prompt
    assert "final_crop" in prompt and "breathing_space" in prompt and "decorative_zones" in prompt


def test_model_integrated_mode_remains_explicit_and_supported(tmp_path):
    d = prepare_delivery(package(tmp_path), text_mode="model_integrated")
    assert d.package.text_regions == ()
    assert "Integrate all canonical copy verbatim" in direct_edit_prompt(d)
    assert "Emit no marketing text" not in direct_edit_prompt(d)


def test_exact_crop_preserves_pixels_without_stretching(tmp_path):
    d = prepare_delivery(package(tmp_path), text_mode="model_integrated")
    with Image.open(io.BytesIO(crop_and_treat(d, native()))) as final:
        assert final.size == (1024, 1280)
        assert final.getpixel((700, 0)) == (255, 0, 0)
        assert final.getpixel((700, 1279)) == (0, 255, 0)


def test_crop_and_canonical_transparent_text_only(tmp_path):
    d = prepare_delivery(package(tmp_path))
    fonts = {"hanna_headline": Path("C:/Windows/Fonts/arial.ttf"), "hanna_body": Path("C:/Windows/Fonts/arial.ttf")}
    result = crop_and_treat(d, native(), fonts=fonts)
    with Image.open(io.BytesIO(result)) as final:
        assert final.size == (1024, 1280)
        assert final.getpixel((700, 0))[:3] == (255, 0, 0)
        assert final.getpixel((56, 70))[:3] == (128, 0, 128)  # no rectangular panel
    with pytest.raises(ValueError, match="font"):
        crop_and_treat(d, native())


@pytest.mark.parametrize("change", [{"product_region": (-1, 0, 500, 1000)}, {"final_crop": (0, 0, 1024, 1280)}])
def test_unsafe_or_changed_crop_guide_rejected(tmp_path, change):
    d = prepare_delivery(package(tmp_path))
    with pytest.raises(ValueError):
        CompositionGuide.model_validate({**d.guide.model_dump(), **change})


def test_hash_changes_abort_before_request(tmp_path):
    d = prepare_delivery(package(tmp_path))
    Path(d.references[0].asset.path).write_bytes(b"changed")
    with pytest.raises(ValueError, match="changed"):
        direct_images_edit_request(d)


def test_only_one_decoded_direct_result_allowed():
    image = SimpleNamespace(b64_json=base64.b64encode(native()).decode())
    assert decode_direct_edit_response(SimpleNamespace(data=[image])) == native()
    for items in ([], [image, image], [SimpleNamespace(b64_json=None)]):
        with pytest.raises(ValueError):
            decode_direct_edit_response(SimpleNamespace(data=items))


@pytest.mark.parametrize("change", [{"model": "gpt-image-2"}, {"model": "auto"}, {"quality": "auto"},
    {"size": "auto"}, {"n": 2}, {"background": "auto"}, {"partial_images": 1}, {"stream": True}])
def test_explicit_governed_settings_cannot_expand(change):
    with pytest.raises(ValueError):
        DirectEditSettings.model_validate({**DirectEditSettings().model_dump(), **change})


def test_official_output_estimate_is_not_total_or_hard_maximum(tmp_path):
    d = prepare_delivery(package(tmp_path))
    q = estimate_multimodal_cost(direct_edit_prompt(d), d.references, d.settings)
    assert q.image_output.usd == Decimal("0.04116") and q.image_output.tokens == 1372
    assert q.image_output.status == "ESTIMATE"
    assert q.image_input.status == "UNRESOLVED" and q.image_input.usd is None
    assert q.total_request_max_cost is None
    with pytest.raises(ValueError, match="UNKNOWN_MULTIMODAL"):
        q.require_within(Decimal("0.50"))


@pytest.mark.parametrize("status,usd,tokens", [("UNRESOLVED", "0", None), ("UNRESOLVED", None, 0),
    ("BOUND", None, 1), ("ESTIMATE", "0.1", None), ("BOUND", "-1", 1)])
def test_cost_interface_cannot_misrepresent_unknown_as_zero(status, usd, tokens):
    with pytest.raises(ValueError):
        CostComponent(status=status, usd=usd, tokens=tokens, authority="fixture")


def test_future_supported_estimator_seam_is_independent_of_creative_architecture(tmp_path):
    class FutureSupportedEstimatorFixture:
        def estimate_text_input_cost(self, prompt, settings):
            return CostComponent(status="BOUND", usd="0.01", tokens=2000, authority="synthetic future contract test only")
        def estimate_image_input_cost(self, references, settings):
            return CostComponent(status="BOUND", usd="0.1", tokens=12500, authority="synthetic future contract test only")
        def estimate_image_output_cost(self, settings):
            return CostComponent(status="BOUND", usd="0.2", tokens=6667, authority="synthetic future contract test only")
    d = prepare_delivery(package(tmp_path))
    q = estimate_multimodal_cost("fixture", d.references, d.settings, estimator=FutureSupportedEstimatorFixture())
    assert q.total_request_max_cost == Decimal("0.31")
    q.require_within(Decimal("0.5"))
    with pytest.raises(ValueError, match="EXCEEDED"):
        q.require_within(Decimal("0.30"))


@pytest.mark.asyncio
@pytest.mark.parametrize("budget", [None, 0.5])
async def test_no_live_edit_even_with_nominal_budget(tmp_path, budget):
    provider = OpenAIProvider(api_key=None, hard_budget_usd=budget)
    with pytest.raises(HardBudgetExceededError, match="UNKNOWN_MULTIMODAL"):
        await deliver_candidate(prepare_delivery(package(tmp_path)), provider)
    assert provider._client is None


@pytest.mark.asyncio
async def test_one_direct_attempt_and_no_renderer_fallback(tmp_path):
    class Failure:
        count = 0
        async def compose_direct_creative(self, **kwargs):
            self.count += 1
            raise RuntimeError("single explicit failure")
    provider = Failure()
    with pytest.raises(RuntimeError, match="single explicit"):
        await deliver_candidate(prepare_delivery(package(tmp_path)), provider)
    assert provider.count == 1


def test_no_v9_selection_no_ui_panel_and_final_qa_still_mandatory(tmp_path):
    import inspect
    import app.services.creative_delivery as module
    source = inspect.getsource(module)
    assert "render_slide" not in source and "premium_render" not in source
    assert "Image.Resampling" not in source and ".resize(" not in source
    assert "draw.rectangle" not in source
    d = prepare_delivery(package(tmp_path), text_mode="model_integrated")
    with pytest.raises(AttributeError):
        accept_delivery(d, crop_and_treat(d, native()), None, tmp_path / "must-not-exist.png")
    assert not (tmp_path / "must-not-exist.png").exists()


@pytest.mark.asyncio
async def test_fake_sdk_edit_dispatch_translation_without_live_authorization(tmp_path, monkeypatch):
    # Only synthetic unit dependencies admit this fake target. Production's
    # estimator and ledger remain unresolved and are tested to deny dispatch.
    import app.services.multimodal_cost as costs
    calls = []
    class FakeImages:
        async def edit(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(data=[SimpleNamespace(b64_json=base64.b64encode(native()).decode())])
    class FakeQuote:
        def require_within(self, maximum):
            assert maximum == Decimal("0.50")
    monkeypatch.setattr(costs, "estimate_multimodal_cost", lambda *args: FakeQuote())
    provider = OpenAIProvider(api_key=None)
    provider._client = SimpleNamespace(images=FakeImages())
    monkeypatch.setattr(provider, "_require_creative_budget", lambda: None)
    result = await provider.compose_direct_creative(delivery=prepare_delivery(package(tmp_path)))
    assert result == native() and len(calls) == 1
    assert calls[0]["model"] == "gpt-image-2.5-sunburst-2026-09-08" and calls[0]["n"] == 1


def test_unknown_cost_strategy_cannot_become_an_output_bound():
    estimator = SunburstCostEstimator()
    unknown = SimpleNamespace(model="unknown", quality="high", size="1024x1536", n=1, partial_images=0, stream=False)
    assert estimator.estimate_image_output_cost(unknown).status == "UNRESOLVED"
    quote = CostQuote(text_input=CostComponent(status="BOUND", usd="0.1", tokens=20000, authority="fixture"),
        image_input=CostComponent(status="UNRESOLVED", authority="no supported input maximum"),
        image_output=CostComponent(status="BOUND", usd="0.1", tokens=3334, authority="fixture"))
    assert quote.total_request_max_cost is None
    with pytest.raises(ValueError, match="UNKNOWN"):
        quote.require_within(Decimal("0.5"))


def test_overlong_direct_prompt_rejected_without_truncating_facts(tmp_path):
    p = package(tmp_path)
    p = HannaCreativePackage.model_validate({**p.model_dump(), "brand_instructions": "x" * 32001})
    with pytest.raises(ValueError, match="32000-character"):
        direct_images_edit_request(prepare_delivery(p))
