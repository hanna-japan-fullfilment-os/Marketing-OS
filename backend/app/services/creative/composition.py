"""Provider-free premium geometry and measured QA policy; no copy generation.

V7.1 intervals are reference-class candidates, not pixel matching or visual
acceptance. The authentic product box is observed, never moved by this solver.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from itertools import combinations

VERSION = "build6r-premium-composition-v1"
STYLE_WEIGHTS = dict(product=20, typography=20, alignment=15, density=15,
                     palette_contrast=10, brand_cta=10, art_separation=10)
STYLE_THRESHOLD = 85
SUBSCORE_MINIMUM = 70
HARD_RULES = (
    "canvas", "complete_measurements", "asset_readiness", "font_readiness",
    "role_inventory", "edge_bounds", "safe_margins", "zone_containment",
    "text_overflow", "line_count", "minimum_type", "hierarchy",
    "role_spacing", "product_bounds", "product_scale", "product_collision",
    "negative_space", "required_cta", "required_logo", "local_contrast",
)
PROFILES = {
    "hero": ("cover", "hero", "premium_hook", "product_introduction"),
    "feature": ("key_feature", "feature_detail", "sheet_differentiator"),
    "specification": ("proof", "specification", "formula_proof"),
    "context": ("problem_solution", "lifestyle", "use_case", "routine_context",
                "application_experience"),
    "close": ("cta", "final", "brand_close_cta"),
}


def uses_premium_composition(target):
    """Scope the V7.1 poster class without a hard-coded brand/product identity."""
    if target is None:
        return False
    raw = target.model_dump() if hasattr(target, "model_dump") else target
    grammar = raw.get("grammar", {}) if isinstance(raw, dict) else {}
    return (isinstance(grammar, dict) and grammar.get("background") == "dark_cinematic"
            and grammar.get("hierarchy") == "headline_hero_callouts")


@dataclass(frozen=True)
class Box:
    x: float
    y: float
    width: float
    height: float

    def __post_init__(self):
        if not all(math.isfinite(v) for v in asdict(self).values()):
            raise ValueError("Nonfinite composition geometry")
        if self.width <= 0 or self.height <= 0:
            raise ValueError("Empty composition geometry")

    @property
    def right(self):
        return self.x + self.width

    @property
    def bottom(self):
        return self.y + self.height

    @property
    def area(self):
        return self.width * self.height

    def contains(self, other, tolerance=1):
        return (other.x >= self.x - tolerance and other.y >= self.y - tolerance
                and other.right <= self.right + tolerance
                and other.bottom <= self.bottom + tolerance)

    def intersects(self, other, clearance=0):
        return (self.x < other.right + clearance and self.right + clearance > other.x
                and self.y < other.bottom + clearance and self.bottom + clearance > other.y)


@dataclass(frozen=True)
class MessageRole:
    key: str
    role: str
    text: str
    field_paths: tuple[str, ...]
    box: Box
    font_px: float
    min_font_px: float
    max_lines: int
    font_family: str = ""


@dataclass(frozen=True)
class LayoutSpec:
    version: str
    template: str
    width: int
    height: int
    reference_id: str
    reference_sha256: str
    product: Box
    roles: tuple[MessageRole, ...]
    logo: Box
    cta: Box
    quiet: Box
    margin: float
    sparse: bool
    logo_required: bool
    cta_required: bool
    reference_contract_sha256: str = ""

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, raw):
        data = dict(raw)
        data["roles"] = tuple(MessageRole(**{**r, "box": Box(**r["box"]),
                                            "field_paths": tuple(r["field_paths"])})
                              for r in data["roles"])
        for key in ("product", "logo", "cta", "quiet"):
            data[key] = Box(**data[key])
        return cls(**data)

    @property
    def digest(self):
        return hashlib.sha256(json.dumps(self.to_dict(), sort_keys=True,
                                        ensure_ascii=False).encode()).hexdigest()


def resolve_composition(ctx, product: Box) -> LayoutSpec:
    """Map existing fields to separate roles. Do not trim, rewrite or fill slots."""
    if ctx.reference_target is None:
        raise ValueError("Premium composition requires an explicit reference target")
    w, h = ctx.width, ctx.height
    if w <= 0 or h <= 0:
        raise ValueError("Invalid composition canvas")
    target = ctx.reference_target
    g = target.grammar
    profile = next((name for name, names in PROFILES.items() if ctx.slide_role in names), "hero")
    scale = w / 1080
    margin = .04 * w
    left = g.supporting_copy_position == "left_column"
    column_x = margin if left else .56 * w
    column_w = .40 * w
    head_x = margin if g.headline_position == "upper_left" else .52 * w
    headline_font = max(72 * scale, min(100 * scale, w * g.headline_scale))
    role_list = []

    def add(key, role, text, paths, box, font, lines):
        if text:
            family = ({"condensed": "Impact, 'Arial Narrow', sans-serif",
                       "serif": "Georgia, serif", "sans": "Arial, sans-serif"}[g.typography]
                      if role == "HEADLINE" else ctx.secondary_font_family or ctx.font_family)
            role_list.append(MessageRole(key, role, text, tuple(paths), box,
                                         font, font, lines, family))

    if ctx.total_slides > 1 and ctx.slide_number > 0:
        add("slide_marker", "STRUCTURAL", f"{ctx.slide_number}/{ctx.total_slides}",
            ["slide_number", "total_slides"], Box(margin, .035*h, .10*w, .03*h),
            24*scale, 1)

    add("eyebrow", "KICKER", ctx.eyebrow, ["eyebrow"],
        Box(head_x, .075*h, .44*w, .035*h), 24*scale, 1)
    head_y = (.12 if ctx.eyebrow else
              .10 if g.headline_position == "upper_right" else .08) * h
    estimated_lines = max(1, min(3, sum(max(1, math.ceil(len(s)/12))
                                       for s in ctx.headline.split("\n"))))
    # Include real descender clearance for pt-BR accents at tight display leading.
    head_h = headline_font * 1.06 * estimated_lines + 16*scale
    add("headline", "HEADLINE", ctx.headline, ["headline"],
        Box(head_x, head_y, .44*w, head_h), headline_font, 3)
    items = []
    for key, role in (("intro", "VALUE_PROPOSITION"), ("body", "SUPPORTING_COPY")):
        if getattr(ctx, key):
            items.append((key, role, getattr(ctx, key), [key]))
    for i, f in enumerate(ctx.features):
        if f.title or f.subtitle or f.icon:
            items.append((f"feature_{i}", "FACT_CALLOUT", "\n".join(
                s for s in (f.icon, f.title, f.subtitle) if s),
                [f"features[{i}].{key}" for key in ("icon", "title", "subtitle")]))
    for key, text, paths in (
        ("callout", "\n".join(s for s in (ctx.callout_label, ctx.callout_value) if s),
         ["callout_label", "callout_value"]),
        ("badge", ctx.badge_text, ["badge_text"]),
        ("bottom_features", "\n".join(ctx.bottom_features), ["bottom_features"]),
        ("trust_badges", "\n".join(ctx.trust_badges), ["trust_badges"]),
    ):
        if text:
            items.append((key, "FACT_CALLOUT", text, paths))
    sparse = len(items) <= 1
    if profile == "specification":
        items.sort(key=lambda item: item[1] != "FACT_CALLOUT")
    support_start = dict(hero=.34, feature=.32, specification=.36, context=.35, close=.40)
    support_y = max(.30*h if sparse else support_start[profile]*h,
                    head_y + head_h + .025*h)
    support_bottom = .85*h if ctx.cta else .93*h
    gap = .016*h
    weights = [max(2, math.ceil(len(text)/25)) for _, _, text, _ in items]
    available = max(1, support_bottom-support_y-gap*max(0, len(items)-1))
    for (key, role, text, paths), weight in zip(items, weights):
        size = (30 if sparse else 26) * scale
        height = available * weight / sum(weights)
        # Sparse facts keep a compact group; unused space stays explicitly quiet.
        height = min(height, max(size*1.3*weight + 16*scale, .06*h))
        add(key, role, text, paths, Box(column_x, support_y, column_w, height),
            size, max(2, math.floor(height/(size*1.25))))
        support_y += height + gap
    cta = Box(column_x, .86*h if profile == "close" else .88*h,
              column_w, .09*h if profile == "close" else .07*h)
    add("cta", "CTA", ctx.cta, ["cta"], cta, (36 if profile == "close" else 30)*scale, 2)
    add("disclaimer", "LEGAL", ctx.disclaimer, ["disclaimer"],
        Box(margin, .965*h, .92*w, .025*h), 16*scale, 2)
    # A narrow protected gutter separates the columns; no content is invented.
    gap_left = column_x + column_w if left else product.right
    gap_right = product.x if left else column_x
    if gap_right-gap_left >= .03*w:
        quiet = Box(gap_left+.01*w, .34*h, gap_right-gap_left-.02*w, .50*h)
    else:
        # An incompatible prepared product/copy arrangement must fail QA rather
        # than silently relocating either approved asset or reference column.
        quiet = Box(.48*w, .34*h, .02*w, .50*h)
    return LayoutSpec(VERSION, profile, w, h, target.reference_id, target.sha256,
                      product, tuple(role_list), Box(.80*w, .037*h, .16*w, .043*h),
                      cta, quiet, margin, sparse, bool(ctx.logo_data_uri),
                      profile == "close" or bool(ctx.cta), hashlib.sha256(json.dumps(
                          target.model_dump(), sort_keys=True).encode()).hexdigest())


def union_area(boxes):
    """Exact axis-aligned union, avoiding double-counted line/role envelopes."""
    xs = sorted({v for b in boxes for v in (b.x, b.right)})
    area = 0.0
    for a, b in zip(xs, xs[1:]):
        intervals = sorted((r.y, r.bottom) for r in boxes if r.x < b and r.right > a)
        end = -math.inf
        for lo, hi in intervals:
            area += (b-a) * max(0, hi-max(lo, end))
            end = max(end, hi)
    return area


def evaluate_composition(spec: LayoutSpec, measured: dict, visual: dict) -> dict:
    """All hard checks are independent of the seven weighted style subscores.

    Measurements come from the browser and source raster, not planned boxes
    passed off as observations. Missing/nonfinite measurements fail closed.
    """
    checks = dict.fromkeys(HARD_RULES, True)
    scores = {}
    try:
        if measured["spec_sha256"] != spec.digest:
            raise ValueError("Stale composition measurement")
        checks["canvas"] = measured["canvas"] == [spec.width, spec.height]
        checks["asset_readiness"] = measured["images_ready"] is True
        checks["font_readiness"] = measured["fonts_ready"] is True
        roles = {r.key: r for r in spec.roles}
        observed = measured["roles"]
        checks["role_inventory"] = (len(observed) == len(roles)
                                    and {o["key"] for o in observed} == set(roles))
        canvas = Box(0, 0, spec.width, spec.height)
        safe = Box(spec.margin, spec.margin, spec.width-2*spec.margin,
                   spec.height-2*spec.margin)
        boxes, ink = [], []
        max_delta = 0.0
        type_ratios = []
        for obs in observed:
            role = roles[obs["key"]]
            approved_faces = [f.strip().strip("'\"") for f in role.font_family.split(",")]
            checks["font_readiness"] &= obs.get("resolved_font") in approved_faces
            rect = Box(**obs["box"])
            boxes.append((role.key, rect))
            role_ink = [Box(**b) for b in obs["ink_boxes"]]
            ink.extend(role_ink)
            font = float(obs["font_px"])
            line_count = obs["lines"]
            if (not math.isfinite(font) or font <= 0 or not isinstance(line_count, int)
                    or line_count <= 0 or not obs["ink_boxes"]):
                raise ValueError("Missing typography measures")
            checks["edge_bounds"] &= canvas.contains(rect, tolerance=0)
            checks["safe_margins"] &= (safe.contains(rect) if role.role != "LEGAL"
                                        else canvas.contains(rect))
            checks["zone_containment"] &= role.box.contains(rect)
            checks["text_overflow"] &= obs["overflow"] is False and all(
                rect.contains(b) for b in role_ink)
            checks["line_count"] &= line_count <= role.max_lines
            checks["minimum_type"] &= font >= role.min_font_px - .1
            checks["product_collision"] &= not rect.intersects(spec.product, spec.width*.015)
            checks["negative_space"] &= not rect.intersects(spec.quiet)
            max_delta = max(max_delta, abs(rect.x-role.box.x)/spec.width,
                            abs(rect.y-role.box.y)/spec.height)
            if role.role not in ("HEADLINE", "LEGAL", "KICKER", "STRUCTURAL", "CTA"):
                type_ratios.append(font)
        for (_, a), (_, b) in combinations(boxes, 2):
            checks["role_spacing"] &= not a.intersects(b, spec.width*.008)
        logo = Box(**measured["logo"]) if measured["logo"] else None
        checks["required_logo"] = not spec.logo_required or logo is not None
        if logo:
            checks["zone_containment"] &= spec.logo.contains(logo)
            checks["edge_bounds"] &= canvas.contains(logo)
            checks["product_collision"] &= not logo.intersects(spec.product, spec.width*.015)
            checks["role_spacing"] &= all(not logo.intersects(b, spec.width*.008) for _, b in boxes)
            checks["negative_space"] &= not logo.intersects(spec.quiet)
        headline = next((r for r in observed if r["key"] == "headline"), None)
        checks["hierarchy"] = (not headline or not type_ratios
                                or headline["font_px"] >= 2.5*max(type_ratios))
        checks["product_bounds"] = safe.contains(spec.product)
        fraction = spec.product.width/spec.width
        checks["product_scale"] = .25 <= fraction <= .65
        checks["negative_space"] &= not spec.product.intersects(spec.quiet)
        checks["required_cta"] = not spec.cta_required or "cta" in {o["key"] for o in observed}
        contrast = float(visual["minimum_contrast"])
        dark = float(visual["dark_fraction"])
        separation = float(visual["product_separation"])
        if (not all(math.isfinite(x) for x in (contrast, dark, separation))
                or not 0 <= dark <= 1 or contrast < 1 or separation < 0):
            raise ValueError("Invalid raster measures")
        checks["local_contrast"] = contrast >= 4.5
        occupancy = union_area(ink)/(spec.width*spec.height)
        # Sparse approved content is a separate allowed reference-class variant.
        density_low, density_high = (.005, .18) if spec.sparse else (.025, .40)
        density_score = 100 if density_low <= occupancy <= density_high else 60
        scores = dict(
            product=100 if .40 <= fraction <= .55 else 65,
            typography=100 if all(checks[k] for k in
                                  ("hierarchy", "minimum_type", "line_count")) else 40,
            alignment=max(0, 100-round(max_delta*1000)),
            density=density_score,
            palette_contrast=100 if dark >= .60 and contrast >= 4.5 else 60,
            brand_cta=100 if checks["required_logo"] and checks["required_cta"] else 0,
            art_separation=min(100, round(separation/12*100)),
        )
        raw = dict(text_occupancy=occupancy, product_width_fraction=fraction,
                   alignment_delta=max_delta, minimum_contrast=contrast,
                   dark_fraction=dark, product_separation=separation)
    except (KeyError, TypeError, ValueError, OverflowError):
        checks["complete_measurements"] = False
        raw = {}
    hard = [k for k, ok in checks.items() if not ok]
    total = round(sum(scores[k]*v for k, v in STYLE_WEIGHTS.items())/100, 2) if scores else None
    soft = [k for k, v in scores.items() if v < SUBSCORE_MINIMUM]
    if total is not None and total < STYLE_THRESHOLD:
        soft.append("weighted_threshold")
    return dict(version=VERSION, spec_sha256=spec.digest, spec=spec.to_dict(),
                passed=not hard and not soft and total is not None,
                hard_checks=checks, hard_failures=hard, style_failures=soft,
                subscores=scores, score=total, threshold=STYLE_THRESHOLD,
                subscore_minimum=SUBSCORE_MINIMUM, measurements=measured,
                raw_metrics=raw, visual_acceptance=False)
