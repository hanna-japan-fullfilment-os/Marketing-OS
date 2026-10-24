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


@pytest.fixture
def owner_target(tmp_path):
    from app.schemas.creative_director import ReferenceTarget
    path = tmp_path / "owner-target.png"
    Image.new("RGB", (60, 80), "purple").save(path)
    target = ReferenceTarget.model_validate({
        "reference_id": "owner-target", "sha256": _sha256(path), "role": "TARGET",
        "source": "OWNER_APPROVED_TARGET", "grammar": {
            "typography": "condensed", "headline_scale": .09, "headline_position": "upper_left",
            "supporting_copy_position": "left_column", "callout_treatment": "gold", "density": "dense",
            "background": "dark_cinematic", "material": "glossy", "lighting": "dramatic_rim",
            "depth": "layered", "negative_space": "modular", "color_behavior": "high_contrast",
            "hierarchy": "headline_hero_callouts"}})
    ref = SimpleNamespace(asset_id=target.reference_id, path=str(path), sha256=target.sha256, role="visual_reference")
    return target, path, ref


def test_target_identity_rejects_wrong_or_missing_pixels(owner_target):
    from app.schemas.creative_director import validate_reference_target
    target, path, ref = owner_target
    assert validate_reference_target(target, [ref]) == path
    with pytest.raises(ValueError):
        validate_reference_target(target, [])
    with pytest.raises(ValueError):
        validate_reference_target(target.model_copy(update={"reference_id": "generic"}), [ref])
    path.write_bytes(b"changed")
    with pytest.raises(ValueError):
        validate_reference_target(target, [ref])


def test_target_role_cannot_be_inspiration(owner_target):
    from app.schemas.creative_director import ReferenceTarget
    target, _, _ = owner_target
    with pytest.raises(ValueError):
        ReferenceTarget.model_validate({**target.model_dump(), "role": "INSPIRATION"})


@pytest.mark.asyncio
async def test_target_grammar_direction_is_text_only(owner_target):
    import json
    from app.schemas.creative_director import CreativeDirection
    from app.services.ai.openai_provider import _response_has_image
    target, _, ref = owner_target
    calls = []
    class Provider:
        async def generate_structured(self, **kwargs):
            calls.append(kwargs)
            return CreativeDirection()
    slide = SimpleNamespace(visual_brief=json.dumps({"REFERENCE_TARGET": target.model_dump()}),
                            reference_assets=[ref], headline="Discover", purpose="hook")
    result = await orchestrator._generate_creative_direction(Provider(),
        master_concept=SimpleNamespace(concept_name="Test", campaign_promise="", product_category_context="",
            campaign_archetype="premium_discovery", archetype_reasoning="", visual_story_system="",
            hero_treatment="", proof_or_demo_strategy="", visual_identity=""),
        adaptation=SimpleNamespace(adaptation_strategy="", narrative_shape=""), platform="instagram",
        language="pt-BR", content_type="carousel", slide=slide, model="fake", fallback=CreativeDirection())
    assert result.reference_target == target
    assert target.reference_id in calls[0]["user"]
    assert '"typography":"condensed"' in calls[0]["user"]
    assert not _response_has_image(calls[0])


@pytest.mark.asyncio
async def test_target_background_excludes_conflicting_product_prose(owner_target, monkeypatch):
    from app.schemas.creative_director import CreativeDirection
    target, path, _ = owner_target
    monkeypatch.setattr(orchestrator, "_brand_style_prompt_notes", lambda brand: "Please generate a pouch")
    calls = []
    class Images:
        async def generate(self, **kwargs):
            calls.append(kwargs)
            return _png_bytes((1088, 1360))
    direction = CreativeDirection(reference_target=target, scene_generation_prompt="Show a giant branded bottle")
    result = await orchestrator.generate_ai_background(SimpleNamespace(), image_provider=Images(),
        brand=SimpleNamespace(name="Test"), model="fake", width=1080, height=1350,
        creative_direction=direction, visual_brief="Generate a pouch with label", selected_references=[path])
    assert result is not None
    assert calls[0]["reference_images"] == [path]
    assert "BACKGROUND ONLY" in calls[0]["prompt"] and "NO PRODUCT PACKAGING" in calls[0]["prompt"]
    assert "Show a giant" not in calls[0]["prompt"] and "Generate a pouch with" not in calls[0]["prompt"]
    assert target.reference_id in calls[0]["prompt"]


@pytest.mark.parametrize("template", ["feature_showcase", "premium_product_hero"])
def test_reference_renderer_grammar_overrides_generic_panel(owner_target, template):
    from app.services.creative.templates import TemplateContext, get_template
    target, _, _ = owner_target
    html = get_template(template).build_html(TemplateContext(width=1080, height=1350,
        composited_image_data_uri="data:image/png;base64,fixture", reference_target=target,
        headline="Discover", body="Details", layout_variant="hero_editorial"))
    assert "Impact" in html and "font-size:97px!important" in html
    assert "background:transparent!important" in html
    assert "border:1px solid #e5bd60!important" in html
    assert "left:4%!important" in html


def test_target_grammar_cannot_inject_copy_or_css(owner_target):
    from app.schemas.creative_director import ReferenceTarget
    target, _, _ = owner_target
    data = target.model_dump(); data["grammar"]["typography"] = "serif; content: 'fake claim'"
    with pytest.raises(ValueError):
        ReferenceTarget.model_validate(data)


@pytest.mark.parametrize("failure", ["missing_target", "metadata_only", "changed_background", "wrong_renderer_target"])
def test_final_qa_requires_same_target_pixels_and_native_background(owner_target, tmp_path, failure):
    import json
    from app.schemas.ai import SlidePlan
    from app.services.qa_engine import reference_qa_inputs
    from app.services.creative.pipeline import build_render_context_path
    target, path, ref = owner_target
    image = tmp_path / "final.png"; Image.new("RGB", (1080, 1350)).save(image)
    background = tmp_path / "background.png"; Image.new("RGB", (1088, 1360)).save(background)
    plan = SlidePlan(slide_number=1, purpose="hook", headline="Discover",
        visual_brief=json.dumps({"REFERENCE_TARGET": target.model_dump()}),
        reference_asset_ids=[target.reference_id], reference_assets=[vars(ref)])
    context = dict(slide_contract=plan.model_dump(), reference_target=target.model_dump(),
                   visual_base_path=str(background), visual_base_kind="generated_background",
                   visual_base_sha256=_sha256(background))
    ctx_path = build_render_context_path(image)
    ctx_path.write_text(json.dumps(context))
    resolved, refs, backgrounds = reference_qa_inputs([image])
    assert resolved == target and refs == [path] and backgrounds == [background]
    if failure == "missing_target":
        path.unlink()
    elif failure == "metadata_only":
        context.pop("reference_target")
    elif failure == "changed_background":
        background.write_bytes(b"changed")
    else:
        context["reference_target"]["reference_id"] = "generic-benchmark"
    ctx_path.write_text(json.dumps(context))
    with pytest.raises((ValueError, OSError, KeyError)):
        reference_qa_inputs([image])


@pytest.mark.asyncio
async def test_background_target_pixel_substitution_cannot_fallback(owner_target, monkeypatch):
    from app.schemas.creative_director import CreativeDirection
    target, path, _ = owner_target
    monkeypatch.setattr(orchestrator, "_brand_style_prompt_notes", lambda brand: "")
    class Images:
        async def generate(self, **kwargs):
            raise AssertionError("Provider must not be invoked")
    path.write_bytes(b"substituted")
    with pytest.raises(ValueError, match="target reference pixels mismatch"):
        await orchestrator.generate_ai_background(SimpleNamespace(), image_provider=Images(),
            brand=SimpleNamespace(name="Test"), model="fake", width=1080, height=1350,
            creative_direction=CreativeDirection(reference_target=target), selected_references=[path])


@pytest.mark.parametrize("variation", ["headline", "scale", "negative_space", "product_position", "product_scale",
                                      "identity", "typography", "lighting", "material", "unprepared"])
def test_campaign_reference_variation_requires_shared_language_and_prepared_contract(owner_target, tmp_path, variation):
    import json
    from app.schemas.ai import SlidePlan
    from app.schemas.creative_director import ReferenceTarget
    from app.services.qa_engine import reference_qa_inputs, reference_qa_manifest
    from app.services.creative.pipeline import build_render_context_path
    target, _, ref = owner_target
    images, plans = [], []
    for number in (1, 2):
        data = target.model_dump()
        brief = {"PRODUCT_PLACEMENT": "right lower half", "PRODUCT_SCALE": "46% canvas width"}
        if number == 2:
            if variation == "headline": data["grammar"].update(headline_position="upper_right", supporting_copy_position="right_column")
            if variation in {"scale", "unprepared"}: data["grammar"]["headline_scale"] = .08
            if variation == "negative_space": data["grammar"]["negative_space"] = "broad"
            if variation == "product_position": brief["PRODUCT_PLACEMENT"] = "left lower half"
            if variation == "product_scale": brief["PRODUCT_SCALE"] = "38% canvas width"
            if variation == "identity": data["reference_id"] = "other-owner"
            if variation == "typography": data["grammar"]["typography"] = "serif"
            if variation == "lighting": data["grammar"]["lighting"] = "high_key"
            if variation == "material": data["grammar"]["material"] = "stone"
        current = ReferenceTarget.model_validate(data)
        brief["REFERENCE_TARGET"] = current.model_dump()
        plan = SlidePlan(slide_number=number, slide_id=f"slide-{number}", purpose="hook", headline="Discover",
                         visual_brief=json.dumps(brief), reference_asset_ids=[current.reference_id],
                         reference_assets=[{**vars(ref), "asset_id": current.reference_id}])
        image = tmp_path / f"final-{number}.png"
        background = tmp_path / f"background-{number}.png"
        Image.new("RGB", (60, 80)).save(background)
        build_render_context_path(image).write_text(json.dumps(dict(slide_contract=plan.model_dump(),
            reference_target=current.model_dump(), visual_base_path=str(background),
            visual_base_kind="generated_background", visual_base_sha256=_sha256(background))))
        images.append(image); plans.append(plan)
    if variation == "unprepared":
        original = json.loads(plans[1].visual_brief)
        original["REFERENCE_TARGET"] = target.model_dump()
        plans[1] = plans[1].model_copy(update={"visual_brief": json.dumps(original)})
        with pytest.raises(ValueError, match="Unprepared"):
            reference_qa_manifest(images, plans)
    elif variation in {"identity", "typography", "lighting", "material"}:
        with pytest.raises(ValueError, match="QA target differs"):
            reference_qa_inputs(images)
    else:
        assert len(reference_qa_manifest(images, plans)) == 2
        assert reference_qa_inputs(images)[0].reference_id == target.reference_id


@pytest.mark.parametrize("field,value", [
    ("angle_degrees", -1), ("angle_degrees", 361), ("angle_degrees", float("nan")),
    ("angle_degrees", "90"), ("stroke_width_px", 3), ("shadow_blur_px", 13),
    ("shadow_offset_y_px", 5), ("stroke_color", "url(file:///secret)"),
    ("stops", []), ("stops", [{"offset": 0, "color": "#ffffff"}] * 9),
    ("stops", [{"offset": .1, "color": "#ffffff"}, {"offset": 1, "color": "#000000"}]),
    ("stops", [{"offset": 0, "color": "#ffffff"}, {"offset": 0, "color": "#000000"}, {"offset": 1, "color": "#ffffff"}]),
    ("stops", [{"offset": 0, "color": "#fff;xx"}, {"offset": 1, "color": "#ffffff"}]),
    ("kind", "radial_gradient"), ("extra_css", "content:fake"),
])
def test_headline_paint_rejects_invalid_values(field, value):
    from app.schemas.creative_director import HeadlinePaint
    data = dict(kind="linear_gradient", angle_degrees=90,
                stops=[dict(offset=0, color="#ff0000"), dict(offset=1, color="#0000ff")])
    data[field] = value
    with pytest.raises(ValueError): HeadlinePaint.model_validate(data)


@pytest.mark.parametrize("field,value", [
    ("glow_radius_px", 13), ("glow_radius_px", -1), ("glow_opacity", 1.1),
    ("glow_opacity", float("inf")), ("stroke_width_px", .4), ("ring_width_px", 3),
    ("size_scale", 1.6), ("size_scale", True), ("tint", "#ffffff\n"),
    ("glow_color", "red"), ("kind", "raw_svg"), ("path", "/secret.svg"),
])
def test_icon_paint_rejects_invalid_values(field, value):
    from app.schemas.creative_director import IconPaint
    data = dict(kind="luminous_vector", tint="#ffffff", glow_color="#8888ff", glow_radius_px=8,
                glow_opacity=.8, stroke_width_px=1, ring_width_px=1, size_scale=1)
    data[field] = value
    with pytest.raises(ValueError): IconPaint.model_validate(data)


def test_paint_absence_preserves_legacy_serialization_and_shared_language(owner_target):
    import json
    from app.schemas.creative_director import ReferenceTarget
    from app.services.qa_engine import campaign_reference_language
    target, _, _ = owner_target
    old = target.model_dump()
    assert "headline_paint" not in old["grammar"] and "icon_paint" not in old["grammar"]
    explicit = json.loads(target.model_dump_json())
    explicit["grammar"].update(headline_paint=None, icon_paint=None)
    assert ReferenceTarget.model_validate(explicit).model_dump() == old
    painted = json.loads(target.model_dump_json())
    painted["grammar"]["headline_paint"] = dict(kind="linear_gradient", angle_degrees=90,
        stops=[dict(offset=0, color="#ff0000"), dict(offset=1, color="#0000ff")])
    assert campaign_reference_language(ReferenceTarget.model_validate(painted)) != campaign_reference_language(target)


def test_paint_style_cannot_bypass_factual_icon_binding(owner_target):
    from app.schemas.ai import SlidePlan
    from app.services.creative.pipeline import canonical_slide_claim_bindings
    plan = SlidePlan(slide_number=1, purpose="hook", headline="Discover", visual_brief="",
                     features=[dict(icon="cure", title="Discover")])
    with pytest.raises(ValueError): canonical_slide_claim_bindings(plan)


@pytest.mark.parametrize("variation", [
    "same", "angle", "icon_scale", "unprepared_angle", "unprepared_icon_scale",
    "palette", "stops", "headline_stroke", "headline_stroke_color", "shadow_color",
    "shadow_blur", "shadow_offset", "glow_color", "glow_radius", "glow_opacity",
    "icon_stroke", "icon_tint", "icon_ring", "material", "identity", "paint_presence",
])
def test_paint_variation_preserves_shared_language_and_exact_prepared_values(owner_target, tmp_path, variation):
    import copy
    import json
    from app.schemas.ai import SlidePlan
    from app.schemas.creative_director import ReferenceTarget
    from app.services.qa_engine import reference_qa_inputs, reference_qa_manifest
    from app.services.creative.pipeline import build_render_context_path
    target, _, ref = owner_target
    data = target.model_dump()
    data["grammar"].update(
        headline_paint=dict(kind="linear_gradient", angle_degrees=90,
            stops=[dict(offset=0, color="#704394"), dict(offset=1, color="#E3C3F8")],
            stroke_width_px=.5, stroke_color="#2F133F", shadow_color="#14051F",
            shadow_blur_px=5, shadow_offset_y_px=2),
        icon_paint=dict(kind="luminous_vector", tint="#F3D9FF", glow_color="#A845FF",
            glow_radius_px=8, glow_opacity=.85, stroke_width_px=1.2, ring_width_px=1, size_scale=1.25))
    images, prepared = [], []
    shared_changes = {
        "palette": ("headline_paint", "stops", [dict(offset=0, color="#00FF00"), dict(offset=1, color="#E3C3F8")]),
        "stops": ("headline_paint", "stops", [dict(offset=0, color="#704394"), dict(offset=.5, color="#E3C3F8"), dict(offset=1, color="#E3C3F8")]),
        "headline_stroke": ("headline_paint", "stroke_width_px", 1),
        "headline_stroke_color": ("headline_paint", "stroke_color", "#FFFFFF"),
        "shadow_color": ("headline_paint", "shadow_color", "#FFFFFF"),
        "shadow_blur": ("headline_paint", "shadow_blur_px", 2),
        "shadow_offset": ("headline_paint", "shadow_offset_y_px", 3),
        "glow_color": ("icon_paint", "glow_color", "#00FF00"),
        "glow_radius": ("icon_paint", "glow_radius_px", 4),
        "glow_opacity": ("icon_paint", "glow_opacity", .3),
        "icon_stroke": ("icon_paint", "stroke_width_px", 2),
        "icon_tint": ("icon_paint", "tint", "#00FF00"),
        "icon_ring": ("icon_paint", "ring_width_px", 0),
    }
    for number in (1, 2):
        current = copy.deepcopy(data)
        if number == 2:
            if variation in {"angle", "unprepared_angle"}: current["grammar"]["headline_paint"]["angle_degrees"] = 85
            if variation in {"icon_scale", "unprepared_icon_scale"}: current["grammar"]["icon_paint"]["size_scale"] = 1.1
            if variation in shared_changes:
                paint, field, value = shared_changes[variation]
                current["grammar"][paint][field] = value
            if variation == "material": current["grammar"]["material"] = "stone"
            if variation == "identity": current["reference_id"] = "different-owner"
            if variation == "paint_presence": current["grammar"].pop("headline_paint")
        typed = ReferenceTarget.model_validate(current)
        plan = SlidePlan(slide_number=number, slide_id=f"paint-{number}", purpose="hook", headline="Discover",
            visual_brief=json.dumps({"REFERENCE_TARGET": typed.model_dump()}),
            reference_asset_ids=[typed.reference_id], reference_assets=[{**vars(ref), "asset_id": typed.reference_id}])
        image = tmp_path / f"final-{number}.png"
        background = tmp_path / f"background-{number}.png"
        Image.new("RGB", (60, 80)).save(background)
        build_render_context_path(image).write_text(json.dumps(dict(slide_contract=plan.model_dump(),
            reference_target=typed.model_dump(), visual_base_path=str(background),
            visual_base_kind="generated_background", visual_base_sha256=_sha256(background))))
        images.append(image)
        if number == 2 and variation.startswith("unprepared_"):
            plan = plan.model_copy(update={"visual_brief": json.dumps({"REFERENCE_TARGET": ReferenceTarget.model_validate(data).model_dump()})})
        prepared.append(plan)
    if variation.startswith("unprepared_"):
        with pytest.raises(ValueError, match="Unprepared"):
            reference_qa_manifest(images, prepared)
    elif variation in {"same", "angle", "icon_scale"}:
        manifest = reference_qa_manifest(images, prepared)
        assert len(manifest) == 2
        assert reference_qa_inputs(images)[0].reference_id == target.reference_id
        if variation != "same": assert manifest[0]["contract_sha256"] != manifest[1]["contract_sha256"]
    else:
        # Even explicitly prepared shared-language differences cannot pass campaign QA.
        assert len(reference_qa_manifest(images, prepared)) == 2
        with pytest.raises(ValueError, match="QA target differs"):
            reference_qa_inputs(images)
