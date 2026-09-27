"""Build 6R-C1 deterministic text ownership."""

import ast
import inspect
from pathlib import Path

from app.services.creative.pipeline import (
    SlideCreativeInput,
    render_slide,
)
from app.services.creative.templates import (
    get_platform_format,
)
from app.services.orchestrator import (
    recreate_creative_image,
    run_visuals_stage,
    _render_additional_platform_variants,
)


ROOT = Path(__file__).resolve().parents[1]


def _call_name(call):
    if isinstance(call.func, ast.Name):
        return call.func.id

    if isinstance(call.func, ast.Attribute):
        return call.func.attr

    return ""


def _assert_fidelity_calls_have_blank_copy(path):
    text = path.read_text(
        encoding="utf-8"
    )

    tree = ast.parse(text)

    calls = []

    for node in ast.walk(tree):
        if not isinstance(
            node,
            ast.Call,
        ):
            continue

        if (
            _call_name(node)
            ==
            "recreate_creative_image_with_fidelity_gate"
        ):
            calls.append(node)

    assert calls

    for call in calls:
        keywords = {
            keyword.arg: keyword.value
            for keyword in call.keywords
            if keyword.arg
        }

        for name in (
            "eyebrow",
            "headline",
            "body",
            "cta",
        ):
            assert name in keywords

            value = keywords[name]

            assert isinstance(
                value,
                ast.Constant,
            )

            assert value.value == ""


def test_orchestrator_ai_recreation_gets_no_campaign_copy():
    _assert_fidelity_calls_have_blank_copy(
        ROOT
        / "app"
        / "services"
        / "orchestrator.py"
    )


def test_manual_ai_recreation_gets_no_campaign_copy():
    _assert_fidelity_calls_have_blank_copy(
        ROOT
        / "app"
        / "api"
        / "campaigns.py"
    )


def test_primary_path_does_not_suppress_exact_text_after_recreation():
    source = inspect.getsource(
        run_visuals_stage
    )

    assert (
        "text_baked_in = recreated_image is not None"
        not in source
    )

    assert (
        "text_baked_in = False"
        in source
    )

    assert (
        'eyebrow="" if text_baked_in else slide_eyebrow'
        in source
    )

    assert (
        'headline="" if text_baked_in else slide_headline'
        in source
    )


def test_secondary_path_does_not_suppress_exact_text_after_recreation():
    source = inspect.getsource(
        _render_additional_platform_variants
    )

    assert (
        "text_baked_in = recreated_image is not None"
        not in source
    )

    assert (
        "text_baked_in = False"
        in source
    )


def test_recreation_prompt_forbids_overlay_marketing_text():
    source = inspect.getsource(
        recreate_creative_image
    )

    assert (
        "DETERMINISTIC TEXT OWNERSHIP"
        in source
    )

    assert (
        "Do not ADD any"
        in source
    )

    assert (
        "campaign eyebrow"
        in source
    )

    assert (
        "deterministic HTML/CSS composition layer"
        in source
    )


def test_recreation_prompt_preserves_real_package_typography():
    source = inspect.getsource(
        recreate_creative_image
    )

    assert (
        "physically printed on the real source product/package"
        in source
    )

    assert (
        "never erase, translate, rewrite, redesign or"
        in source
    )


def test_renderer_remains_authoritative_for_exact_marketing_elements():
    fields = (
        SlideCreativeInput.__dataclass_fields__
    )

    for field in (
        "eyebrow",
        "headline",
        "body",
        "cta",
        "badge_text",
        "intro",
        "features",
        "callout_label",
        "callout_value",
        "bottom_features",
        "trust_badges",
        "disclaimer",
    ):
        assert field in fields

    source = inspect.getsource(
        render_slide
    )

    assert "TemplateContext(" in source

    assert (
        "headline=creative_input.headline"
        in source
    )

    assert (
        "body=creative_input.body"
        in source
    )

    assert (
        "cta=creative_input.cta"
        in source
    )

    assert (
        "logo_data_uri=logo_data_uri"
        in source
    )

    assert (
        "features=creative_input.features"
        in source
    )


def test_instagram_portrait_remains_exact_4_by_5():
    fmt = get_platform_format(
        "instagram_portrait"
    )

    assert fmt.width == 1080
    assert fmt.height == 1350
