from __future__ import annotations

import io
import inspect
from pathlib import Path
import re
from types import SimpleNamespace

from PIL import Image
import pytest

from app.services import claims_audit
from app.services import orchestrator
from app.services import prompt_registry


def _finding(
    source_field: str,
    claim_text: str,
    *,
    category: str = "other factual claim",
):
    return claims_audit.ClaimFinding(
        claim_text=claim_text,
        claim_category=category,
        source_field=source_field,
        evidence_status="UNSUPPORTED",
        allowed_source="",
        reason="synthetic unsupported finding",
    )


@pytest.mark.parametrize(
    ("source_field", "claim_text"),
    [
        (
            "master_concept.hero_treatment",
            "Hero isolado em fundo editorial com bastante espaço negativo.",
        ),
        (
            "master_concept.composition",
            "Composição assimétrica, enquadramento limpo e luz lateral suave.",
        ),
        (
            "master_concept.lighting",
            "Iluminação suave, sombras controladas e atmosfera premium.",
        ),
        (
            "master_concept.story_arc",
            "Narrativa visual limpa, editorial e com hierarquia clara.",
        ),
        (
            "ai_extracted_candidate",
            "Fundo limpo, produto no centro e bastante espaço negativo.",
        ),
        (
            "master_concept.key_message",
            "Nada além do verificado, sem extrapolação.",
        ),
    ],
)
def test_v343_pure_art_direction_is_not_a_product_fact(
    source_field,
    claim_text,
):
    assert claims_audit._build6r_v35_nonfactual_visual_instruction(
        _finding(
            source_field,
            claim_text,
        )
    )


@pytest.mark.parametrize(
    ("source_field", "claim_text", "category"),
    [
        (
            "master_concept.composition",
            "Destacar 7 sheets e 150 mL no packshot.",
            "product_format_or_quantity",
        ),
        (
            "master_concept.hero_treatment",
            "Vitamina C reduz manchas em 24 horas.",
            "product benefits/effects",
        ),
        (
            "ai_extracted_candidate",
            "Fórmula sem álcool e sem fragrância.",
            "ingredients_or_composition",
        ),
        (
            "master_concept.proof_or_demo_strategy",
            "Usar de manhã ou à noite no lugar do tônico.",
            "usage_instructions",
        ),
        (
            "master_concept.visual_style",
            "Produto número 1 do Japão em fundo editorial.",
            "ranking_bestseller",
        ),
        (
            "master_concept.hero_treatment",
            "Nome completo do produto: Produto X.",
            "product_identity",
        ),
    ],
)
def test_v343_genuine_factual_claims_remain_fail_closed(
    source_field,
    claim_text,
    category,
):
    assert not claims_audit._build6r_v35_nonfactual_visual_instruction(
        _finding(
            source_field,
            claim_text,
            category=category,
        )
    )


def test_v343_v35_reconciler_drops_only_nonfactual_visual_instruction():
    visual = _finding(
        "master_concept.composition",
        "Composição editorial com fundo limpo e espaço negativo.",
    )
    factual = _finding(
        "master_concept.composition",
        "Destacar 7 sheets e 150 mL.",
        category="product_format_or_quantity",
    )

    result = claims_audit.ClaimAuditResult(
        findings=[
            visual,
            factual,
        ]
    )

    reconciled = (
        claims_audit._build6r_reconcile_generated_semantic_findings_v35(
            result,
            None,
        )
    )

    assert len(reconciled.findings) == 1
    assert reconciled.findings[0].claim_text == factual.claim_text
    assert reconciled.findings[0].evidence_status == "UNSUPPORTED"


def test_v343_semantic_boundary_helpers_are_zero_network():
    names = (
        "_build6r_v343_has_factual_product_signal",
        "_build6r_v343_nonfactual_art_direction",
        "_build6r_v35_nonfactual_visual_instruction",
    )

    source = "\n".join(
        inspect.getsource(
            getattr(
                claims_audit,
                name,
            )
        )
        for name in names
    )

    for forbidden in (
        "generate_structured",
        "generate_image",
        "edit_image",
        "httpx",
        "requests.",
        "socket.",
        "research_provider",
    ):
        assert forbidden not in source


def _png_bytes() -> bytes:
    handle = io.BytesIO()
    Image.new(
        "RGB",
        (8, 8),
        "white",
    ).save(
        handle,
        format="PNG",
    )
    return handle.getvalue()


@pytest.mark.asyncio
async def test_v343_explicit_art_direction_reference_uses_separate_locked_channel(
    monkeypatch,
):
    reference = Path("verified-reference.png")

    monkeypatch.setattr(
        orchestrator,
        "_resolve_visual_reference_paths",
        lambda *args, **kwargs: [reference],
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

    image = await orchestrator.generate_ai_background(
        SimpleNamespace(),
        image_provider=provider,
        brand=SimpleNamespace(
            id="brand-1",
            name="Hanna",
        ),
        model="gpt-image-1",
        width=1024,
        height=1536,
        visual_brief="premium editorial surface",
        quality="high",
        creative_direction=None,
        allow_reference_images=False,
        reference_art_direction_only=True,
    )

    assert image is not None
    assert len(provider.calls) == 1
    assert provider.calls[0]["reference_images"] == [reference]
    assert (
        "QUALITY_AND_COMPOSITION_REFERENCE_NOT_PRODUCT_FACT_EVIDENCE"
        in provider.calls[0]["prompt"]
    )
    assert "never evidence for product identity" in provider.calls[0]["prompt"]


@pytest.mark.asyncio
async def test_v343_v342_false_flag_still_sends_no_references(
    monkeypatch,
):
    def _unexpected_reference_lookup(*args, **kwargs):
        raise AssertionError(
            "Legacy V3.42 false flag must not resolve references."
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

    image = await orchestrator.generate_ai_background(
        SimpleNamespace(),
        image_provider=provider,
        brand=SimpleNamespace(
            id="brand-1",
            name="Hanna",
        ),
        model="gpt-image-1",
        width=1024,
        height=1536,
        visual_brief="premium editorial surface",
        quality="high",
        creative_direction=None,
        allow_reference_images=False,
    )

    assert image is not None
    assert len(provider.calls) == 1
    assert provider.calls[0]["reference_images"] is None


def test_v343_locked_visual_route_preserves_v342_gate_and_adds_art_direction_channel():
    source = inspect.getsource(
        orchestrator.run_visuals_stage
    )
    normalized = re.sub(
        r"\s+",
        "",
        source,
    )

    assert (
        "allow_reference_images=(locked_product_candidateisNone)"
        in normalized
    )
    assert (
        "reference_art_direction_only=(locked_product_candidateisnotNone)"
        in normalized
    )


def test_v343_scene_generation_recipe_version_bumped():
    source = Path(
        prompt_registry.__file__
    ).read_text(
        encoding="utf-8"
    )

    match = re.search(
        r'"scene_generation"\s*:\s*PromptSpec\(\s*'
        r'purpose\s*=\s*"scene_generation"\s*,\s*'
        r'version\s*=\s*"([^"]+)"',
        source,
        re.DOTALL,
    )

    assert match is not None
    assert match.group(1) == "1.2.0"
