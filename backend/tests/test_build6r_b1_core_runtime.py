"""Build 6R-B1 core visual runtime tests."""

import inspect

from app.schemas.creative_director import (
    MasterCampaignConcept,
    PlatformAdaptation,
)
from app.services.orchestrator import (
    _deterministic_creative_direction,
    _generate_creative_direction,
    _render_additional_platform_variants,
    _resolve_platform_adaptation,
    generate_ai_background,
    recreate_creative_image,
    recreate_creative_image_with_fidelity_gate,
    run_visuals_stage,
)
from app.services.prompt_registry import PROMPT_VERSIONS


class _BrandStyle:
    palette = ["#111111", "#ffffff"]
    primary_font = "Inter"


def _concept():
    return MasterCampaignConcept(
        concept_name="Utility campaign",
        campaign_promise="Grounded discovery",
        key_message="Useful product",
        emotional_goal="Confidence",
        audience="Customer",
        objective="Consideration",
        visual_identity="Product-first",
        story_arc="Introduce > explain > act",
        cta_intent="Learn more",
        product_category_context="Everyday umbrella",
        campaign_archetype="lifestyle_utility",
        archetype_reasoning="Daily-use purchase",
        visual_story_system="Practical daily-life progression",
        hero_treatment="Bright daylight product hero",
        proof_or_demo_strategy="Verified utility only",
    )


def test_deterministic_direction_keeps_archetype():
    adaptation = PlatformAdaptation(
        platform="instagram",
        adaptation_strategy="carousel",
        narrative_shape="progressive",
        tone_adjustment="",
        content_type="carousel",
    )

    direction = _deterministic_creative_direction(
        master_concept=_concept(),
        adaptation=adaptation,
        platform="instagram",
        language="pt-BR",
        content_type="carousel",
        slide_role="hero",
        brand_style=_BrandStyle(),
    )

    assert direction.campaign_archetype == "lifestyle_utility"
    assert direction.product_category_context == "Everyday umbrella"
    assert direction.visual_story_system


def test_recreation_interfaces_accept_direction():
    raw = inspect.signature(
        recreate_creative_image
    )

    gate = inspect.signature(
        recreate_creative_image_with_fidelity_gate
    )

    assert "creative_direction" in raw.parameters
    assert "creative_direction" in gate.parameters

    assert (
        raw.parameters[
            "creative_direction"
        ].default
        is None
    )

    assert (
        gate.parameters[
            "creative_direction"
        ].default
        is None
    )


def test_scene_prompts_use_campaign_archetype():
    background = inspect.getsource(
        generate_ai_background
    )

    recreation = inspect.getsource(
        recreate_creative_image
    )

    assert "Campaign archetype" in background
    assert "campaign_archetype" in background

    assert (
        "CAMPAIGN-SPECIFIC ART DIRECTION"
        in recreation
    )

    assert "campaign_archetype" in recreation
    assert "generic product-ad aesthetic" in recreation


def test_platform_adapter_receives_archetype():
    source = inspect.getsource(
        _resolve_platform_adaptation
    )

    assert "Campaign archetype" in source
    assert "visual_story_system" in source
    assert "hero_treatment" in source


def test_creative_director_executes_archetype():
    source = inspect.getsource(
        _generate_creative_direction
    )

    assert "campaign_archetype" in source
    assert "visual_story_system" in source

    assert (
        "template never determines the product"
        in source
    )


def test_primary_path_has_creative_director():
    source = inspect.getsource(
        run_visuals_stage
    )

    assert (
        "primary_adaptation = await "
        "_resolve_platform_adaptation"
        in source
    )

    assert (
        "primary_creative_direction"
        in source
    )

    assert (
        "await _generate_creative_direction"
        in source
    )

    assert (
        "creative_direction="
        "primary_creative_direction"
        in source
    )


def test_secondary_recreation_receives_direction():
    source = inspect.getsource(
        _render_additional_platform_variants
    )

    assert (
        "creative_direction=creative_direction"
        in source
    )


def test_build6r_b1_prompt_versions():
    assert (
        PROMPT_VERSIONS[
            "master_campaign_concept"
        ].version
        == "1.6.0"
    )

    assert (
        PROMPT_VERSIONS[
            "platform_adaptation"
        ].version
        == '1.2.0'
    )

    assert (
        PROMPT_VERSIONS[
            "creative_direction"
        ].version
        == '1.2.0'
    )

    assert (
        PROMPT_VERSIONS[
            "scene_generation"
        ].version
        == "1.1.0"
    )

    # B2 owns QA-revision recipe changes, so B1 deliberately
    # does not assert that later stage's version.
