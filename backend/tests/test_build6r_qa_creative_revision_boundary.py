import inspect

from app.services import qa_engine
from app.services.prompt_registry import PROMPT_VERSIONS


def test_targeted_creative_revision_has_full_grounding_stack():
    source = inspect.getsource(
        qa_engine.revise_creative_direction_for_variant
    )

    assert "_claims_boundary_instruction()" in source
    assert "_sparse_fact_grounding_instruction()" in source
    assert "verified_facts_note" in source


def test_targeted_creative_revision_prompt_version_is_traceable():
    spec = PROMPT_VERSIONS[
        "targeted_creative_direction_revision"
    ]

    assert spec.version == "1.3.0"
    assert "verified_product_facts" in spec.variables
