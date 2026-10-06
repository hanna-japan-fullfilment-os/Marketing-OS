"""Build 6R-A universal creative intelligence tests."""

import inspect
from types import SimpleNamespace

from app.data.campaign_archetypes import (
    CAMPAIGN_ARCHETYPES,
    format_campaign_archetypes_for_prompt,
)
from app.schemas.creative_director import (
    CreativeDirection,
    MasterCampaignConcept,
)
from app.services.orchestrator import run_copy_stage
from app.services.product_facts import (
    format_verified_facts_for_prompt,
)
from app.services.prompt_registry import PROMPT_VERSIONS


def test_archetype_catalog_is_universal():
    expected = {
        "lifestyle_utility",
        "feature_demo",
        "how_it_works",
        "problem_solution",
        "routine_integration",
        "variant_choice",
        "technical_performance",
        "premium_discovery",
        "origin_story",
        "sensory_experience",
    }

    assert expected <= set(CAMPAIGN_ARCHETYPES)
    assert len(CAMPAIGN_ARCHETYPES) >= 10
    assert "beauty_editorial" not in CAMPAIGN_ARCHETYPES


def test_archetype_prompt_says_not_product_categories():
    text = format_campaign_archetypes_for_prompt().lower()

    assert "communication structures" in text
    assert "not product categories" in text


def test_old_master_concept_payload_is_compatible():
    concept = MasterCampaignConcept(
        concept_name="Existing",
        campaign_promise="Existing promise",
        key_message="Existing message",
        emotional_goal="Interest",
        audience="Customer",
        objective="Consideration",
        visual_identity="Existing visual identity",
        story_arc="Hook > explain > action",
        cta_intent="Learn more",
    )

    assert concept.product_category_context == ""
    assert concept.campaign_archetype == ""
    assert concept.archetype_reasoning == ""
    assert concept.visual_story_system == ""
    assert concept.hero_treatment == ""
    assert concept.proof_or_demo_strategy == ""
    assert concept.story_beats == []


def test_creative_direction_carries_selected_archetype():
    direction = CreativeDirection(
        product_category_context="Everyday utility",
        campaign_archetype="lifestyle_utility",
        archetype_reasoning="Practical purchase",
        visual_story_system="Daily-use progression",
        hero_treatment="Product in believable daylight",
        proof_or_demo_strategy="Verified utility only",
    )

    assert direction.campaign_archetype == "lifestyle_utility"
    assert direction.visual_story_system


def test_verified_facts_prompt_keeps_category():
    facts = SimpleNamespace(
        product_name="Foldable Umbrella",
        brand_name="Hanna Japan",
        category="Daily Goods",
        owner_notes="",
        verified_description="",
        verified_ingredients=[],
        verified_features=[],
        verified_benefits=[],
        verified_usage="",
        verified_size="",
        verified_variant="",
        verified_price="",
        verified_availability="",
        verified_country_of_origin="Japan",
        verified_claims=[],
        prohibited_claims=[],
        missing_information=[],
    )

    text = format_verified_facts_for_prompt(facts)

    assert "- Category: Daily Goods" in text
    assert "- Country of origin: Japan" in text


def test_run_copy_stage_contains_universal_archetype_decision():
    source = inspect.getsource(run_copy_stage)

    assert "campaign_archetype" in source
    assert "format_campaign_archetypes_for_prompt" in source
    assert "COMMUNICATION STRUCTURE" in source
    assert "Never infer unsupported facts" in source


def test_master_concept_prompt_version_is_bumped():
    spec = PROMPT_VERSIONS["master_campaign_concept"]

    assert spec.version == "1.5.0"
    assert "product_category_context" in spec.variables
    assert "campaign_archetype_catalog" in spec.variables
    assert "verified_product_facts" in spec.variables
