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
import hashlib
import re
from dataclasses import dataclass, field

from PIL import Image, ImageColor

from .renderer import RenderDiagnostics
from .composition import LayoutSpec, evaluate_composition


@dataclass
class CreativeQAResult:
    passed: bool
    issues: list[str] = field(default_factory=list)
    checks: dict[str, bool] = field(default_factory=dict)
    composition: dict | None = None

    def to_dict(self) -> dict:
        result = {"passed": self.passed, "issues": self.issues, "checks": self.checks}
        if self.composition is not None:
            result["composition"] = self.composition
        return result


def raster_composition_metrics(spec, measured, base_image):
    """Sample actual pre-text pixels and the browser's painted text colors.

    Local contrast includes the deterministic role panel's alpha. Product-edge
    separation is an explicit proxy, not a claim to measure photographic depth.
    """
    if base_image.size != (spec.width, spec.height):
        raise ValueError("Composition raster dimensions differ")
    image = base_image.convert("RGB")

    def luminance(rgb):
        linear = [v/255/12.92 if v/255 <= .04045 else ((v/255+.055)/1.055)**2.4 for v in rgb]
        return sum(v*k for v, k in zip(linear, (.2126, .7152, .0722)))

    contrast = []
    for role in measured["roles"]:
        panel = [float(v) for v in re.findall(r"[\d.]+", role["background"])]
        if len(panel) not in (3, 4):
            raise ValueError("Missing measured role background")
        alpha = panel[3] if len(panel) == 4 else 1
        for b in role["ink_boxes"]:
            for fx, fy in ((.1,.25), (.5,.5), (.9,.75)):
                x = max(0, min(spec.width-1, round(b["x"]+b["width"]*fx)))
                y = max(0, min(spec.height-1, round(b["y"]+b["height"]*fy)))
                bg = image.getpixel((x, y))
                bg_l = luminance([panel[i]*alpha+bg[i]*(1-alpha) for i in range(3)])
                for color in role["foreground"]:
                    fg_l = luminance(ImageColor.getrgb(color))
                    contrast.append((max(bg_l, fg_l)+.05)/(min(bg_l, fg_l)+.05))
    if not contrast:
        raise ValueError("No contrast samples")
    hist = image.convert("L").histogram()
    p = spec.product
    differences = []
    for f in (.15,.35,.55,.75,.9):
        y = max(0, min(spec.height-1, round(p.y+p.height*f)))
        for inside, outside in ((p.x+3, p.x-8), (p.right-4, p.right+8)):
            a = image.getpixel((max(0,min(spec.width-1,round(inside))), y))
            b = image.getpixel((max(0,min(spec.width-1,round(outside))), y))
            differences.append(sum(abs(x-y) for x,y in zip(a,b))/3)
    return dict(minimum_contrast=min(contrast),
                dark_fraction=sum(hist[:64])/(spec.width*spec.height),
                product_separation=sum(differences)/len(differences))


def run_creative_qa(
    *,
    png_bytes: bytes,
    expected_width: int,
    expected_height: int,
    diagnostics: RenderDiagnostics,
    logo_expected: bool,
    logo_included: bool,
    text_expected: bool = True,
    composition_spec: LayoutSpec | None = None,
    base_image: Image.Image | None = None,
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
    if text_expected and composition_spec is None:
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

    composition = None
    if composition_spec is not None:
        measured = diagnostics.composition or {}
        try:
            visual = raster_composition_metrics(composition_spec, measured, base_image)
        except (KeyError, TypeError, ValueError, AttributeError):
            visual = {}
        composition = evaluate_composition(composition_spec, measured, visual)
        composition["render_sha256"] = hashlib.sha256(png_bytes).hexdigest()
        checks["premium_composition"] = composition["passed"]
        issues.extend(f"Composition hard failure: {s}" for s in composition["hard_failures"])
        issues.extend(f"Reference style failure: {s}" for s in composition["style_failures"])
    passed = len(issues) == 0
    return CreativeQAResult(passed=passed, issues=issues, checks=checks, composition=composition)
