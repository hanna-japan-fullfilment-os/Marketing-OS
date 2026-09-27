from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

RUNNER = ROOT / "scripts" / "run_live_acceptance.py"
QA = ROOT / "app" / "services" / "qa_engine.py"
ORCHESTRATOR = ROOT / "app" / "services" / "orchestrator.py"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_stage3d_modified_sources_parse() -> None:
    for path in (
        RUNNER,
        QA,
        ORCHESTRATOR,
    ):
        text = _read(path)
        ast.parse(
            text,
            filename=str(path),
        )


def test_premium_hero_cli_is_explicit_and_fail_closed() -> None:
    source = _read(RUNNER)

    assert '"--premium-hero-only"' in source

    assert (
        "--premium-hero-only requires --case PLATFORM:LANGUAGE."
        in source
    )

    assert (
        "--premium-hero-only cannot be combined with --smoke."
        in source
    )

    assert (
        "--premium-hero-only requires --quality-mode premium."
        in source
    )


def test_premium_hero_is_exactly_one_slide() -> None:
    source = _read(RUNNER)

    assert "config.max_slides = 1" in source

    assert (
        "target_slide_count=1 if args.premium_hero_only else None"
        in source
    )


def test_premium_hero_has_strict_first_image_qa() -> None:
    source = _read(RUNNER)

    assert '"qa_pass_threshold": 90' in source
    assert '"qa_max_retries": 0' in source
    assert '"qa_best_of_n": 1' in source

    assert (
        "config.require_ai_background_success = True"
        in source
    )


def test_normal_pipeline_does_not_require_ai_scene() -> None:
    source = _read(ORCHESTRATOR)

    assert (
        "require_ai_background_success: bool = False"
        in source
    )


def test_premium_acceptance_rejects_gradient_fallback() -> None:
    source = _read(ORCHESTRATOR)

    required = (
        "config.require_ai_background_success",
        "config.use_ai_background",
        "generated_background is None",
        "AI-generated background; deterministic gradient ",
        "fallback is not accepted.",
    )

    for fragment in required:
        assert fragment in source


def test_creative_qa_receives_verified_product_facts() -> None:
    source = _read(QA)

    assert (
        "verified_facts_text=verified_facts_note"
        in source
    )


def test_creative_qa_receives_brand_requirements() -> None:
    source = _read(QA)

    assert (
        "brand_requirements_text=brand_requirements_note"
        in source
    )

    for field_name in (
        "voice",
        "colors",
        "typography",
        "spacing",
        "visual_style",
        "forbidden_styles",
        "campaign_rules",
        "creative_instructions",
        "preferred_ctas",
        "disallowed_terms",
        "disclaimers",
    ):
        assert f'"{field_name}"' in source


def test_creative_qa_receives_real_product_photo() -> None:
    source = _read(QA)

    assert (
        "source_product_image_path: Path | None = None"
        in source
    )

    assert "product_id=product.id" in source

    assert (
        "source_image_path=source_product_image_path"
        in source
    )


def test_stage3d_does_not_enable_full_product_recreation() -> None:
    source = _read(RUNNER)

    assert (
        'use_ai_background=True, recreate_with_ai=False'
        in source
    )


def test_premium_hero_mode_is_recorded_in_acceptance_report() -> None:
    source = _read(RUNNER)

    assert (
        '"premium_hero_only": args.premium_hero_only'
        in source
    )