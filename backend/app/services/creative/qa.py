"""Automated creative QA (brief section 22, campaign-pipeline.md hybrid pipeline
step 8).

Every check here is real: it either inspects the actual PNG bytes that were
produced, or the real DOM measurements `renderer.py` took during the render (see
`RenderDiagnostics`). Nothing is a hardcoded "passed": true placeholder. This is
deliberately *not* the whole QA story — cross-campaign duplicate-similarity is a
different concern, already implemented in `services/fingerprint.py` against
campaign history, not against a single image, so it isn't repeated here.

Human approval remains authoritative regardless of what this reports (per the
pipeline design) — this exists to catch mechanical failures before a human ever
looks at the output, not to replace their judgment.
"""
from __future__ import annotations

import io
from dataclasses import dataclass, field

from PIL import Image

from .renderer import RenderDiagnostics


@dataclass
class CreativeQAResult:
    passed: bool
    issues: list[str] = field(default_factory=list)
    checks: dict[str, bool] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"passed": self.passed, "issues": self.issues, "checks": self.checks}


def run_creative_qa(
    *,
    png_bytes: bytes,
    expected_width: int,
    expected_height: int,
    diagnostics: RenderDiagnostics,
    logo_expected: bool,
    logo_included: bool,
    text_expected: bool = True,
) -> CreativeQAResult:
    issues: list[str] = []
    checks: dict[str, bool] = {}

    # 1. File integrity — the bytes must actually decode as a valid image.
    try:
        with Image.open(io.BytesIO(png_bytes)) as img:
            img.load()
            actual_width, actual_height = img.size
            actual_format = img.format
        checks["file_integrity"] = True
    except Exception as exc:  # noqa: BLE001 - we want to report any decode failure as a QA issue
        checks["file_integrity"] = False
        issues.append(f"Output could not be read back as a valid image: {exc}")
        return CreativeQAResult(passed=False, issues=issues, checks=checks)

    if actual_format != "PNG":
        checks["format_png"] = False
        issues.append(f"Expected PNG output, got {actual_format}.")
    else:
        checks["format_png"] = True

    # 2. Exact dimensions — the whole point of the platform-format system is that the
    #    output matches the platform's real pixel spec exactly.
    dims_ok = actual_width == expected_width and actual_height == expected_height
    checks["exact_dimensions"] = dims_ok
    if not dims_ok:
        issues.append(
            f"Expected {expected_width}x{expected_height}px, got {actual_width}x{actual_height}px."
        )

    # 3. Text overflow / safe margins — from real DOM measurement at render time.
    # Only flagged when text was actually expected: a slide with no eyebrow/
    # headline/body/CTA at all (e.g. a full AI recreation baked its own text
    # directly into the image — see templates.py's `_build_premium_product_hero`
    # and orchestrator.py's `recreate_creative_image`) deliberately renders no
    # `.text-block` at all, which is correct, not a QA failure — mirrors the
    # logo_expected/logo_included pattern below.
    if text_expected:
        if not diagnostics.text_block_present:
            checks["text_block_present"] = False
            issues.append("Template did not render a `.text-block` element to measure.")
        else:
            checks["text_block_present"] = True
            checks["text_within_safe_margins"] = not diagnostics.text_overflowed
            if diagnostics.text_overflowed:
                issues.append(
                    "Text content overflowed its safe-margin box — shorten the copy or "
                    "the template needs a smaller font scale for this length."
                )
    else:
        checks["text_block_present"] = True  # nothing was expected, nothing to flag

    # 4. Logo presence — checked against what the pipeline actually attempted to
    #    include, not inferred by scanning pixels (that would be a fragile heuristic
    #    dressed up as a real check).
    if logo_expected:
        checks["logo_present"] = logo_included
        if not logo_included:
            issues.append("Brand has a logo asset configured, but it was not included in this render.")
    else:
        checks["logo_present"] = True  # nothing was expected, nothing to flag

    passed = len(issues) == 0
    return CreativeQAResult(passed=passed, issues=issues, checks=checks)
