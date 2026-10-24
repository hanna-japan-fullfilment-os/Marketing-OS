from __future__ import annotations

import hashlib
import inspect
import io
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from app.services import locked_product_pipeline as locked
from app.services import orchestrator


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_transparent_master(path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGBA", (360, 480), (0, 0, 0, 0))
    for x in range(70, 290):
        for y in range(45, 445):
            image.putpixel((x, y), (190, 170, 220, 255))
    image.save(path, format="PNG")
    return _sha256(path)


def _png_bytes(size=(64, 64)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, (18, 22, 34)).save(buffer, format="PNG")
    return buffer.getvalue()


def test_v342_strong_profile_is_canvas_relative_v339_strong():
    profile = locked.V339_STRONG_SHADOW_PROFILE
    assert profile.name == "strong"
    assert profile.horizontal_scale == pytest.approx(0.94)
    assert profile.height_ratio == pytest.approx(74 / 1536)
    assert profile.blur_radius_ratio == pytest.approx(24 / 1536)
    assert profile.opacity == pytest.approx(0.28)
    assert profile.y_offset_ratio == pytest.approx(12 / 1536)


def test_v342_transparent_master_is_validated_and_source_bytes_stay_immutable(tmp_path):
    master = tmp_path / "approved_product_masters" / "product" / "master.png"
    expected = _write_transparent_master(master)
    before = master.read_bytes()

    validation = locked.inspect_locked_product_master_candidate(
        master,
        expected_sha256=expected,
    )

    assert validation is not None
    assert validation["sha256"] == expected
    assert validation["approved_master_path"] is True
    assert master.read_bytes() == before


def test_v342_canonical_rgb_fallback_is_not_misclassified_as_locked_master(tmp_path):
    source = tmp_path / "source.jpg"
    Image.new("RGB", (100, 140), (20, 30, 40)).save(source, format="JPEG")

    validation = locked.inspect_locked_product_master_candidate(
        source,
        expected_sha256="sha-0",
    )

    assert validation is None


def test_v342_nonapproved_rgba_png_bypasses_locked_master_even_with_placeholder_hash(tmp_path):
    source = tmp_path / "ordinary-transparent.png"
    Image.new("RGBA", (100, 140), (10, 20, 30, 0)).save(
        source,
        format="PNG",
    )

    validation = locked.inspect_locked_product_master_candidate(
        source,
        expected_sha256="placeholder-not-canonical",
    )

    assert validation is None


def test_v342_approved_master_wrong_sha_fails_closed(tmp_path):
    master = (
        tmp_path
        / "approved_product_masters"
        / "product"
        / "master.png"
    )
    _write_transparent_master(master)

    with pytest.raises(
        RuntimeError,
        match="Approved product master SHA-256 mismatch",
    ):
        locked.inspect_locked_product_master_candidate(
            master,
            expected_sha256="0" * 64,
        )


def test_v342_claimed_approved_master_fails_closed_if_alpha_contract_is_invalid(tmp_path):
    master = tmp_path / "approved_product_masters" / "product" / "bad.png"
    master.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (120, 160), (255, 255, 255, 255)).save(master, format="PNG")

    with pytest.raises(RuntimeError, match="transparent and visible alpha"):
        locked.inspect_locked_product_master_candidate(
            master,
            expected_sha256=_sha256(master),
        )


def test_v342_builds_strong_shadow_locked_composite_without_mutating_master(tmp_path):
    master = tmp_path / "approved_product_masters" / "product" / "master.png"
    expected = _write_transparent_master(master)
    before_sha = _sha256(master)
    background = Image.new("RGB", (1088, 1360), (28, 25, 45))

    result = locked.build_locked_product_composite(
        background=background,
        master_path=master,
        expected_sha256=expected,
        canvas_size=(1080, 1350),
    )

    assert result.image.size == (1080, 1350)
    assert result.locked_product_layer.size == (1080, 1350)
    assert result.shadow_layer.size == (1080, 1350)
    assert result.shadow_layer.getchannel("A").getbbox() is not None
    assert result.metadata["shadow_profile"] == "strong"
    assert result.metadata["contact_shadow_generated"] is True
    assert result.metadata["product_pixel_mutation_count"] == 0
    assert result.metadata["ai_product_generation"] is False
    assert result.metadata["ai_product_editing"] is False
    assert result.metadata["product_reference_image_count"] == 0
    assert result.metadata["background_reference_image_count"] == 0
    assert result.metadata["source_master_immutability"] is True
    assert _sha256(master) == before_sha


def test_v342_locked_service_is_local_only_and_has_no_provider_surface():
    source = inspect.getsource(locked)
    for forbidden in (
        "openai",
        "httpx",
        "requests.",
        "provider.generate",
        "generate_structured",
        "AsyncOpenAI",
    ):
        assert forbidden not in source


def test_v342_background_generation_sends_no_references_when_locked(monkeypatch):
    def _unexpected_reference_lookup(*args, **kwargs):
        raise AssertionError(
            "Locked background route must not resolve reference images."
        )

    monkeypatch.setattr(
        orchestrator,
        "_resolve_visual_reference_paths",
        _unexpected_reference_lookup,
    )
    monkeypatch.setattr(
        orchestrator,
        "_brand_style_prompt_notes",
        lambda brand: "",
    )

    class FakeImageProvider:
        def __init__(self):
            self.calls = []

        async def generate(self, **kwargs):
            self.calls.append(kwargs)
            return _png_bytes()

    provider = FakeImageProvider()
    brand = SimpleNamespace(id="brand-1", name="Hanna")

    image = _complete_background_fake(orchestrator.generate_ai_background(
        SimpleNamespace(),
        image_provider=provider,
        brand=brand,
        model="gpt-image-1",
        width=1024,
        height=1536,
        visual_brief="premium editorial surface",
        quality="high",
        creative_direction=None,
        allow_reference_images=False,
    ))

    assert image is not None
    assert len(provider.calls) == 1
    assert provider.calls[0]["reference_images"] is None


def test_v342_orchestrator_wires_primary_and_variant_locked_routes():
    source = inspect.getsource(orchestrator)

    assert "from .locked_product_pipeline import (" in source
    assert "inspect_locked_product_master_candidate" in source
    assert "build_trusted_product_composite" in source

    assert source.count(
        "allow_reference_images=(\n"
        "                        locked_product_candidate is None\n"
        "                    ),"
    ) == 1
    assert source.count(
        "allow_reference_images=(\n"
        "                                    locked_product_candidate is None\n"
        "                                ),"
    ) == 1

    assert source.count("locked_product_composite=locked_result") == 2
    assert source.count('qa_dict["locked_product_pipeline"]') == 1
    assert source.count('qa_payload["locked_product_pipeline"]') == 1
    assert "BUILD6R_IMMUTABLE_PRODUCT_LAYER_RUN_VISUALS_GUARD" in source


def test_v342_existing_persistence_contract_remains_present():
    source = inspect.getsource(orchestrator.run_visuals_stage)

    for marker in (
        "CampaignSlide(",
        "CampaignAsset(",
        "CampaignOutput(",
        'kind="qa_report"',
        'campaign.status = "REVIEW"',
        "db.commit()",
    ):
        assert marker in source


def test_v342_existing_renderer_remains_deterministic_typography_owner():
    from app.services.creative import pipeline

    render_source = inspect.getsource(pipeline.render_slide)

    assert "recreated_image" in render_source
    assert "source_image_path" in render_source
    assert "headline" in render_source

    orchestrator_source = inspect.getsource(orchestrator)
    assert "text_baked_in = False" in orchestrator_source


def test_v342_full_ai_product_recreation_guard_is_preserved():
    source = inspect.getsource(orchestrator.run_visuals_stage)

    assert "Full AI product recreation is prohibited" in source
    assert "use_ai_background=True and recreate_with_ai=False" in source


def _complete_background_fake(coro):
    try:
        coro.send(None)
    except StopIteration as done:
        return done.value
    finally:
        coro.close()
    raise AssertionError("Fake background call yielded external work")


@pytest.mark.parametrize("with_reference", [False, True])
def test_repair_background_consumes_exact_selected_reference_set(tmp_path, monkeypatch, with_reference):
    def forbidden_lookup(*args, **kwargs):
        raise AssertionError("No latest-reference substitution allowed")
    monkeypatch.setattr(orchestrator, "_resolve_visual_reference_paths", forbidden_lookup)
    monkeypatch.setattr(orchestrator, "_brand_style_prompt_notes", lambda brand: "")
    reference = tmp_path / "selected.png"
    Image.new("RGB", (30, 30), "blue").save(reference)
    selected = [reference] if with_reference else []
    calls = []
    class FakeProvider:
        async def generate(self, **kwargs):
            calls.append(kwargs)
            return _png_bytes()
    result = _complete_background_fake(orchestrator.generate_ai_background(
        SimpleNamespace(), image_provider=FakeProvider(), brand=SimpleNamespace(id="brand", name="Brand"),
        model="fake", width=1080, height=1350, visual_brief="Editorial", selected_references=selected))
    assert result is not None
    assert calls[0]["reference_images"] == (selected or None)
    if selected:
        assert "QUALITY_AND_COMPOSITION_REFERENCE_NOT_PRODUCT_FACT_EVIDENCE" in calls[0]["prompt"]


@pytest.mark.parametrize("width,anchor", [(46, "right lower half"), (38, "left lower half"),
                                          (44, "center lower half"), (30, "upper-right")])
def test_prepared_geometry_controls_locked_compositor(tmp_path, width, anchor):
    import json
    master = tmp_path / "approved_product_masters" / "product" / "master.png"
    expected = _write_transparent_master(master)
    before = master.read_bytes()
    placement = locked.prepared_product_placement(json.dumps({
        "PRODUCT_SCALE": f"{width}% canvas width", "PRODUCT_PLACEMENT": anchor}))
    result = locked.build_locked_product_composite(
        background=Image.new("RGB", (1088, 1360), "navy"), master_path=master,
        expected_sha256=expected, canvas_size=(1080, 1350), placement=placement)
    geometry = result.metadata["placement"]
    assert abs(geometry["rendered_width"] - 1080 * width / 100) <= 0.5
    assert geometry["horizontal_anchor"] == placement.horizontal
    assert geometry["vertical_anchor"] == placement.vertical
    x, y = geometry["product_x"], geometry["product_y"]
    if placement.horizontal == "right":
        assert x > (1080 - geometry["rendered_width"]) / 2
    elif placement.horizontal == "left":
        assert x < (1080 - geometry["rendered_width"]) / 2
    else:
        assert abs(x + geometry["rendered_width"] / 2 - 540) <= 0.5
    if placement.vertical == "lower":
        assert y + geometry["rendered_height"] == geometry["product_bottom_y"]
    else:
        assert y == geometry["product_safe_top"]
    assert master.read_bytes() == before
    # The layer is exactly the authentic alpha-cropped master after one resize.
    with Image.open(master) as image:
        crop = image.convert("RGBA").crop(tuple(geometry["source_alpha_bbox"]))
    resized = crop.resize((geometry["rendered_width"], geometry["rendered_height"]), Image.Resampling.LANCZOS)
    assert result.locked_product_layer.crop((x, y, x + resized.width, y + resized.height)).tobytes() == resized.tobytes()
    assert result.image.size == (1080, 1350)
    assert result.metadata["product_pixel_mutation_count"] == 0


@pytest.mark.parametrize("brief", [
    '{', '{"PRODUCT_SCALE": "46% canvas width"}',
    '{"PRODUCT_SCALE": "NaN% canvas width", "PRODUCT_PLACEMENT": "lower-right"}',
    '{"PRODUCT_SCALE": "0% canvas width", "PRODUCT_PLACEMENT": "lower-right"}',
    '{"PRODUCT_SCALE": "101% canvas width", "PRODUCT_PLACEMENT": "lower-right"}',
    '{"PRODUCT_SCALE": "46% canvas width", "PRODUCT_PLACEMENT": "somewhere"}',
    '{"PRODUCT_SCALE": 46, "PRODUCT_PLACEMENT": "lower-right"}',
])
def test_malformed_prepared_geometry_fails_closed(brief):
    with pytest.raises(ValueError):
        locked.prepared_product_placement(brief)


def test_legacy_brief_keeps_existing_geometry():
    assert locked.prepared_product_placement("Hero product") is None
    assert locked.prepared_product_placement('{"BACKGROUND": "navy"}') is None


def test_prepared_geometry_that_cannot_fit_is_rejected(tmp_path):
    master = tmp_path / "approved_product_masters" / "p" / "m.png"
    sha = _write_transparent_master(master)
    with pytest.raises((ValueError, RuntimeError)):
        locked.build_locked_product_composite(
            background=Image.new("RGB", (1088, 1360)), master_path=master,
            expected_sha256=sha, canvas_size=(1080, 1350),
            placement=locked.ProductPlacement(0.95, "right", "lower"))


def test_adapter_and_both_orchestrator_paths_forward_placement():
    import ast
    from app.services.creative.pipeline import build_trusted_product_composite
    tree = ast.parse(inspect.getsource(orchestrator))
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Name) and n.func.id == "build_trusted_product_composite"]
    assert len(calls) == 2
    assert all(any(k.arg == "placement" and isinstance(k.value, ast.Name)
                   and k.value.id == "prepared_placement" for k in n.keywords) for n in calls)
    assert "placement=placement" in inspect.getsource(build_trusted_product_composite)


def test_two_stage_dimensions_remain_explicit():
    from app.services.creative.templates import get_platform_format
    fmt = get_platform_format("instagram_portrait")
    assert (fmt.width, fmt.height) == (1080, 1350)
    # Native background is fitted to the final platform canvas (covered above);
    # neither the final platform format nor the Sunburst request is changed.
    from app.services.ai import openai_provider
    source = inspect.getsource(openai_provider)
    assert "1088x1360" in source
