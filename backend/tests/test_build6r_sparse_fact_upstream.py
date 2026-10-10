import inspect

from app.services import orchestrator
from app.services.prompt_registry import PROMPT_VERSIONS


def test_sparse_fact_instruction_is_universal_and_fail_closed():
    text = (
        orchestrator
        ._sparse_fact_grounding_instruction()
        .lower()
    )

    required = [
        "verified product facts",
        "fields mean unknown",
        "never permission to infer",
        "identity/context only",
        "never factual evidence",
        "ai-generated upstream outputs",
        "visual_brief",
        "before/after",
        "stay sparse",
        "neutral or blank",
    ]

    for phrase in required:
        assert phrase in text

    assert "melano" not in text
    assert "hanna-prod" not in text


def test_run_copy_stage_applies_sparse_fact_boundary_to_all_versioned_upstream_prompts():
    source = inspect.getsource(
        orchestrator.run_copy_stage
    )

    # CreativeBrief: 1
    # MasterCampaignConcept: 1
    # CampaignCopy: 1
    # CarouselPlan: 2 branches
    assert (
        source.count(
            "_sparse_fact_grounding_instruction()"
        )
        == 5
    )

    forbidden_prompt_language = [
        "warranted by the research/strategy",
        "product/category info or research given",
        "niacinamida 10%",
    ]

    lowered = source.lower()

    for phrase in forbidden_prompt_language:
        assert phrase not in lowered


def test_discovery_carousel_receives_full_verified_fact_block_per_product():
    source = inspect.getsource(
        orchestrator.run_copy_stage
    )

    assert (
        "format_verified_facts_for_prompt"
        in source
    )

    assert (
        "resolve_verified_product_facts"
        in source
    )

    assert (
        "UNVERIFIED PRODUCT NOTES"
        in source
    )

    assert (
        "identity only, not factual evidence"
        in source
    )


def test_sparse_fact_prompt_versions_are_traceable():
    expected = {
        "campaign_copy": "1.6.0",
        "carousel_plan": "1.6.0",
        "master_campaign_concept": "1.7.0",
    }

    for purpose, version in expected.items():
        spec = PROMPT_VERSIONS[
            purpose
        ]

        assert spec.version == version

        assert (
            "verified_product_facts"
            in spec.variables
        )
