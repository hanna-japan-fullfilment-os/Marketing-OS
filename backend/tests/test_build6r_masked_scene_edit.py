from __future__ import annotations

import asyncio
import hashlib
import inspect
import io
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from app.services import orchestrator
from app.services.creative import compositor
from app.services.creative import pipeline


ROOT = Path(__file__).resolve().parents[1]


def _sha256(path: Path) -> str:
    return hashlib.sha256(
        path.read_bytes()
    ).hexdigest()


def _make_source(path: Path) -> None:
    image = Image.new(
        "RGBA",
        (
            320,
            480,
        ),
        (
            0,
            0,
            0,
            0,
        ),
    )

    for y in range(
        35,
        445,
    ):
        for x in range(
            70,
            250,
        ):
            image.putpixel(
                (
                    x,
                    y,
                ),
                (
                    210,
                    45,
                    120,
                    255,
                ),
            )

    image.save(
        path,
        format="PNG",
    )


def _creative_input(
    source: Path,
) -> pipeline.SlideCreativeInput:

    return pipeline.SlideCreativeInput(
        source_image_path=source,
        template_id="feature_showcase",
        platform_key="instagram_square",
        headline="Deterministic headline",
        body="Deterministic body",
        cta="Deterministic CTA",
        brand_colors=[
            "#181716",
            "#F4EFE7",
        ],
        isolate_background=False,
        campaign_archetype="product_hero",
        slide_role="hero",
        hero_treatment="premium editorial",
        visual_style="premium product campaign",
        mood="refined",
        negative_space="intentional",
    )


def _config():
    return SimpleNamespace(
        use_masked_scene_edit=True,
        require_masked_scene_edit_success=True,
        use_ai_background=False,
        recreate_with_ai=False,
        quality_mode="premium",
        image_model="fake-standard-image",
        draft_image_model="fake-draft-image",
        premium_image_model="fake-premium-image",
    )


class FakeEditProvider:

    def __init__(
        self,
        *,
        fail: bool = False,
    ):
        self.fail = fail
        self.edit_calls = 0
        self.generate_calls = 0
        self.last_prompt = ""
        self.last_model = ""
        self.last_quality = ""
        self.base_size = None
        self.mask_size = None
        self.base_format = None
        self.mask_format = None
        self.mask_has_alpha = False

    async def generate(
        self,
        **kwargs,
    ):
        self.generate_calls += 1

        raise AssertionError(
            "Bounded masked scene path must never call generate()."
        )

    async def edit(
        self,
        *,
        base_image,
        prompt,
        model,
        mask=None,
        quality="high",
    ):
        self.edit_calls += 1
        self.last_prompt = prompt
        self.last_model = model
        self.last_quality = quality

        assert mask is not None

        with Image.open(
            base_image
        ) as base:
            self.base_size = base.size
            self.base_format = base.format

        with Image.open(
            mask
        ) as opened_mask:
            self.mask_size = opened_mask.size
            self.mask_format = opened_mask.format
            self.mask_has_alpha = (
                "A"
                in opened_mask.getbands()
            )

        if self.fail:
            raise RuntimeError(
                "synthetic masked edit failure"
            )

        result = Image.new(
            "RGB",
            self.base_size,
            (
                12,
                18,
                24,
            ),
        )

        buffer = io.BytesIO()

        result.save(
            buffer,
            format="PNG",
        )

        return buffer.getvalue()


def test_preparation_is_local_same_canvas_and_source_immutable(
    tmp_path,
):
    source = (
        tmp_path
        / "master.png"
    )

    _make_source(
        source
    )

    before = _sha256(
        source
    )

    prepared = (
        pipeline.prepare_masked_scene_edit_inputs(
            _creative_input(
                source
            )
        )
    )

    assert (
        prepared.base_image.size
        == prepared.mask_image.size
        == prepared.product_overlay.size
    )

    assert (
        "A"
        in prepared.mask_image.getbands()
    )

    assert (
        prepared.mask_image
        .getchannel(
            "A"
        )
        .getextrema()
        == (
            0,
            255,
        )
    )

    assert (
        prepared.product_overlay
        .getchannel(
            "A"
        )
        .getbbox()
        is not None
    )

    assert _sha256(
        source
    ) == before


def test_product_overlay_preserves_source_rgb_for_opaque_pixels(
    tmp_path,
):
    source = (
        tmp_path
        / "master.png"
    )

    _make_source(
        source
    )

    prepared = (
        pipeline.prepare_masked_scene_edit_inputs(
            _creative_input(
                source
            )
        )
    )

    bbox = (
        prepared.product_overlay
        .getchannel(
            "A"
        )
        .getbbox()
    )

    assert bbox is not None

    left, top, right, bottom = bbox

    point = (
        (
            left
            + right
        )
        // 2,
        (
            top
            + bottom
        )
        // 2,
    )

    pixel = prepared.product_overlay.getpixel(
        point
    )

    assert pixel[:3] == (
        210,
        45,
        120,
    )

    assert pixel[3] == 255


def test_exactly_one_edit_zero_generate_and_correct_mask_contract(
    tmp_path,
):
    source = (
        tmp_path
        / "master.png"
    )

    _make_source(
        source
    )

    provider = FakeEditProvider()

    result = asyncio.run(
        orchestrator.generate_masked_product_scene(
            image_provider=provider,
            creative_input=_creative_input(
                source
            ),
            config=_config(),
        )
    )

    assert result is not None

    assert provider.edit_calls == 1
    assert provider.generate_calls == 0

    assert (
        provider.base_size
        == provider.mask_size
    )

    assert provider.base_format == "PNG"
    assert provider.mask_format == "PNG"
    assert provider.mask_has_alpha is True

    assert (
        provider.last_model
        == "fake-premium-image"
    )

    assert provider.last_quality == "high"

    prompt = provider.last_prompt.lower()

    assert "do not redesign" in prompt

    assert (
        "deterministic html/css"
        in prompt
    )


def test_failure_makes_no_second_image_call(
    tmp_path,
):
    source = (
        tmp_path
        / "master.png"
    )

    _make_source(
        source
    )

    provider = FakeEditProvider(
        fail=True
    )

    result = asyncio.run(
        orchestrator.generate_masked_product_scene(
            image_provider=provider,
            creative_input=_creative_input(
                source
            ),
            config=_config(),
        )
    )

    assert result is None
    assert provider.edit_calls == 1
    assert provider.generate_calls == 0


def test_required_bridge_fails_closed_without_retry(
    tmp_path,
):
    source = (
        tmp_path
        / "master.png"
    )

    _make_source(
        source
    )

    provider = FakeEditProvider(
        fail=True
    )

    creative_input = _creative_input(
        source
    )

    try:
        asyncio.run(
            orchestrator._apply_masked_scene_edit_if_enabled(
                config=_config(),
                image_provider=provider,
                creative_input=creative_input,
            )
        )

    except RuntimeError as exc:
        assert (
            "No second image call"
            in str(exc)
        )

    else:
        raise AssertionError(
            "Required failed edit did not fail closed."
        )

    assert provider.edit_calls == 1
    assert provider.generate_calls == 0


def test_successful_bridge_sets_scene_for_final_deterministic_overlay(
    tmp_path,
):
    source = (
        tmp_path
        / "master.png"
    )

    _make_source(
        source
    )

    provider = FakeEditProvider()

    creative_input = _creative_input(
        source
    )

    applied = asyncio.run(
        orchestrator._apply_masked_scene_edit_if_enabled(
            config=_config(),
            image_provider=provider,
            creative_input=creative_input,
        )
    )

    assert applied is True

    assert (
        creative_input.generated_background
        is not None
    )

    assert (
        creative_input.masked_scene_background
        is True
    )

    assert provider.edit_calls == 1
    assert provider.generate_calls == 0


def test_generation_function_contains_one_edit_and_no_generate_fallback():
    source = inspect.getsource(
        orchestrator.generate_masked_product_scene
    )

    assert (
        source.count(
            "image_provider.edit("
        )
        == 1
    )

    assert (
        "image_provider.generate("
        not in source
    )


def test_pre_and_post_ai_paths_share_zone_and_placement_transform():
    prepare_source = inspect.getsource(
        pipeline.prepare_masked_scene_edit_inputs
    )

    render_source = inspect.getsource(
        pipeline.render_slide
    )

    composite_source = inspect.getsource(
        compositor.composite_product
    )

    assert (
        "_resolve_product_zone("
        in prepare_source
    )

    assert (
        "_resolve_product_zone("
        in render_source
    )

    assert (
        "_placed_product_rgba("
        in composite_source
    )

    assert (
        "shadow=not creative_input.masked_scene_background"
        in render_source
    )


def test_masked_mode_defaults_off_and_full_recreation_stays_off():
    source = inspect.getsource(
        orchestrator.AutopilotConfig
    )

    assert (
        "use_masked_scene_edit: bool = False"
        in source
    )

    assert (
        "require_masked_scene_edit_success: bool = False"
        in source
    )

    assert (
        "recreate_with_ai: bool = False"
        in source
    )


def test_both_production_render_calls_are_guarded_by_masked_bridge():
    source = (
        ROOT
        / "app"
        / "services"
        / "orchestrator.py"
    ).read_text(
        encoding="utf-8"
    )

    assert (
        source.count(
            "await _apply_masked_scene_edit_if_enabled("
        )
        == 2
    )

    assert (
        source.count(
            "result = await render_slide("
        )
        == 2
    )


def test_premium_acceptance_is_one_primary_masked_visual():
    source = (
        ROOT
        / "scripts"
        / "run_live_acceptance.py"
    ).read_text(
        encoding="utf-8"
    )

    required = [
        "config.max_slides = 1",
        "config.use_ai_background = False",
        "config.use_masked_scene_edit = True",
        "config.require_masked_scene_edit_success = True",
        "config.render_platform_variants = False",
    ]

    for value in required:
        assert value in source

    # Normal/non-premium constructor remains untouched for compatibility.
    assert (
        "use_ai_background=True, recreate_with_ai=False"
        in source
    )


def test_text_and_logo_remain_after_final_product_composite():
    source = inspect.getsource(
        pipeline.render_slide
    )

    composite_index = source.index(
        "composite_product("
    )

    context_index = source.index(
        "TemplateContext("
    )

    render_index = source.index(
        "render_png_with_diagnostics("
    )

    assert (
        composite_index
        < context_index
        < render_index
    )


def test_masked_scene_accounting_helper_uses_scene_generation_contract(
    monkeypatch,
):
    prompt_calls = []
    stage_calls = []

    def fake_record_prompt_usage(
        *args,
        **kwargs,
    ):
        prompt_calls.append(
            (
                args,
                kwargs,
            )
        )

    def fake_record_stage_usage(
        *args,
        **kwargs,
    ):
        stage_calls.append(
            (
                args,
                kwargs,
            )
        )

        return []

    monkeypatch.setattr(
        orchestrator,
        "record_prompt_usage",
        fake_record_prompt_usage,
    )

    monkeypatch.setattr(
        orchestrator,
        "record_stage_usage",
        fake_record_stage_usage,
    )

    db = object()
    provider = object()

    orchestrator._record_masked_scene_usage(
        db,
        campaign_id="campaign-1",
        image_provider=provider,
        platform="instagram",
        content_type="carousel",
    )

    assert len(prompt_calls) == 1
    assert len(stage_calls) == 1

    prompt_args, prompt_kwargs = (
        prompt_calls[0]
    )

    assert prompt_args == (
        db,
    )

    assert (
        prompt_kwargs["campaign_id"]
        == "campaign-1"
    )

    assert (
        prompt_kwargs["purpose"]
        == "scene_generation"
    )

    assert (
        prompt_kwargs["language"]
        == ""
    )

    assert (
        prompt_kwargs["platform"]
        == "instagram"
    )

    assert (
        prompt_kwargs["extra"]["mode"]
        == "masked_scene_edit"
    )

    assert (
        prompt_kwargs["extra"]["image_edit_calls"]
        == 1
    )

    assert (
        prompt_kwargs["extra"]["image_generate_calls"]
        == 0
    )

    stage_args, stage_kwargs = (
        stage_calls[0]
    )

    assert stage_args == (
        db,
    )

    assert (
        stage_kwargs["campaign_id"]
        == "campaign-1"
    )

    assert (
        stage_kwargs["operation"]
        == "scene_generation"
    )

    assert (
        stage_kwargs["providers"]
        == [
            provider
        ]
    )

    assert (
        stage_kwargs["platform"]
        == "instagram"
    )

    assert (
        stage_kwargs["language"]
        == ""
    )

    assert (
        stage_kwargs["content_type"]
        == "carousel"
    )


def test_masked_scene_usage_is_recorded_at_both_successful_bridge_callsites():
    source = inspect.getsource(
        orchestrator
    )

    assert (
        source.count(
            "masked_scene_applied = await _apply_masked_scene_edit_if_enabled("
        )
        == 2
    )

    assert (
        source.count(
            "_record_masked_scene_usage("
        )
        == 3
    )

    # One definition + two production callsites.
    assert (
        source.count(
            "if masked_scene_applied:"
        )
        == 2
    )


def test_masked_generator_still_contains_no_db_or_usage_accounting():
    source = inspect.getsource(
        orchestrator.generate_masked_product_scene
    )

    assert (
        "record_stage_usage("
        not in source
    )

    assert (
        "record_prompt_usage("
        not in source
    )

    assert (
        source.count(
            "image_provider.edit("
        )
        == 1
    )

    assert (
        "image_provider.generate("
        not in source
    )


def test_masked_accounting_helper_has_no_provider_call():
    source = inspect.getsource(
        orchestrator._record_masked_scene_usage
    )

    assert (
        "image_provider.edit("
        not in source
    )

    assert (
        "image_provider.generate("
        not in source
    )

    assert (
        "record_stage_usage("
        in source
    )

    assert (
        "record_prompt_usage("
        in source
    )

