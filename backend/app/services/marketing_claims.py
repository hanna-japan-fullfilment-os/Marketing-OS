"""Closed-vocabulary, exact-SKU claims/translation and benefit-brief gate."""
import json
from pathlib import Path
import re
import unicodedata
from ..schemas.marketing_claims import ClaimLibrary
from .product_creative_eligibility import require_creative_eligibility

RESEARCH_CATEGORIES = frozenset({"PRODUCT_POSITIONING", "FORMULA", "INGREDIENTS", "SENSORY_FEATURES",
    "MATERIAL/SHEET_TECHNOLOGY", "USAGE", "PACK_FACTS", "MANUFACTURER_BENEFITS",
    "WARNINGS/QUALIFIERS", "BRAZIL_CLAIM_RISK", "COMPARATIVE/STUDY_CLAIMS"})
CATALOG = Path(__file__).resolve().parents[1] / "data" / "LULULUN_HYDRA_EX_CLAIM_EVIDENCE_MATRIX.json"
USABLE = frozenset({"APPROVED_DIRECT", "APPROVED_WITH_QUALIFIER", "FACT_ONLY"})


def normalized(text):
    return " ".join(unicodedata.normalize("NFC", text).split()).casefold()


def load_library(product_id):
    library = ClaimLibrary.model_validate_json(CATALOG.read_text(encoding="utf-8"))
    if product_id != library.product_id:
        raise ValueError("No reviewed claim library for this exact product")
    if set(library.research_categories) != RESEARCH_CATEGORIES or not all(library.research_categories.values()):
        raise ValueError("Research completeness gate blocked")
    return library


def approved_library(library):
    """Exclude raw research and unresolved claims from creative-facing payloads."""
    groups = {}
    for claim in library.claims:
        if claim.claim_class in USABLE and claim.review_status == "APPROVED" and claim.language_review == "VERIFIED":
            groups.setdefault(claim.group, []).append(claim.model_dump(mode="json"))
    return groups


def guard_language(text, library):
    value = normalized(text)
    # This deny layer complements the exact approved wording allowlist. It is
    # not a semantic NLP classifier, and unknown paraphrases still fail closed.
    for phrase in library.prohibited_language:
        if normalized(phrase) in value:
            raise ValueError("Prohibited therapeutic/unsupported language")
    if re.search(r"\d+\s*%|n[º°o.]\s*1|bestseller|clinicamente|imediat|vezes\s+mais", value):
        raise ValueError("Comparative/statistical claim needs exact product/study context")


def resolve_copy(library, copy_fields):
    """Resolve only exact reviewed variants; never invent an evidence association."""
    bindings = {}
    for field in copy_fields:
        if field.key == "slide_marker":
            if not re.fullmatch(r"[1-9]\d*/[1-9]\d*", field.text):
                raise ValueError("Invalid structural slide marker")
            continue
        guard_language(field.text, library)
        matches = [c for c in library.claims if c.claim_class in USABLE and c.review_status == "APPROVED"
            and c.language_review == "VERIFIED"
            and normalized(field.text) in {normalized(w) for w in c.approved_pt_br_wording.values()}]
        if len(matches) != 1:
            raise ValueError(f"No unique approved claim ID / PT-BR wording for {field.key}")
        bindings[field.key] = matches[0].claim_id
    return bindings


def validate_brief(library, brief, *, canonical_brief=None):
    if brief.locale != "pt-BR":
        raise ValueError("Reviewed wording is pt-BR only; approve exact locale before handoff")
    if not brief.approved_claim_ids:
        raise ValueError("Creative brief lacks approved claim IDs")
    expected = resolve_copy(library, brief.approved_copy)
    if dict(brief.approved_claim_ids) != expected:
        raise ValueError("Claim ID / exact visible wording substitution")
    by_id = {c.claim_id: c for c in library.claims}
    selected = [by_id[key] for key in set(expected.values())]
    text = normalized(" ".join(c.text for c in brief.approved_copy))
    qualifiers = {}
    for claim in selected:
        if claim.mandatory_qualifier:
            if normalized(claim.mandatory_qualifier) not in text:
                raise ValueError("Mandatory qualification missing from visible copy")
            qualifiers[claim.claim_id] = claim.mandatory_qualifier
    if dict(brief.mandatory_qualifiers) != qualifiers:
        raise ValueError("Exported qualifier contract changed")
    benefits = [c for c in selected if c.evidence_scope == "PRODUCT_BENEFIT"]
    # A supplied role is never authority. Production callers obtain this brief
    # independently from the current persisted campaign and live provenance.
    factual_claim = {
        "application": "ex-apply", "application_action": "ex-apply",
        "routine_aftercare": "ex-after", "manufacturer_aftercare_guidance": "ex-after",
    }.get(canonical_brief.slide_role.casefold()) if canonical_brief is not None else None
    if factual_claim and not benefits:
        if (brief.slide_role != canonical_brief.slide_role
                or brief.approved_copy != canonical_brief.approved_copy
                or brief.canonical_package_sha256 != canonical_brief.canonical_package_sha256
                or set(expected.values()) != {factual_claim}
                or any(c.claim_class != "FACT_ONLY" or c.evidence_scope != "PRODUCT_FACT" for c in selected)
                or brief.benefit_hierarchy):
            raise ValueError("Canonical factual purpose / reviewed evidence mismatch")
        return selected
    available = any(c.claim_class in USABLE and c.evidence_scope == "PRODUCT_BENEFIT" for c in library.claims)
    if available and not benefits:
        raise ValueError("Premium brief is usage/fact-only despite approved benefits")
    if not brief.benefit_hierarchy or not set(brief.benefit_hierarchy).issubset({c.claim_id for c in benefits}):
        raise ValueError("Explicit primary/secondary benefit hierarchy required")
    return selected


def bind_handoff(handoff, *, db=None, campaign=None):
    require_creative_eligibility(handoff.product_id)
    library = load_library(handoff.product_id)
    if library.owner_library_review_status != "APPROVED":
        raise ValueError("Complete claim library awaits owner review; creative production remains paused")
    slides = []
    canonical = _canonical_briefs(handoff, db, campaign) if db is not None or campaign is not None else {}
    by_id = {c.claim_id: c for c in library.claims}
    for brief in handoff.slides:
        bindings = resolve_copy(library, brief.approved_copy)
        selected = [by_id[key] for key in dict.fromkeys(bindings.values())]
        hierarchy = tuple(c.claim_id for c in selected if c.evidence_scope == "PRODUCT_BENEFIT")
        qualifiers = {c.claim_id: c.mandatory_qualifier for c in selected if c.mandatory_qualifier}
        bound = brief.model_copy(update={"approved_claim_ids": bindings, "mandatory_qualifiers": qualifiers,
            "benefit_hierarchy": hierarchy, "prohibited_elements": tuple(dict.fromkeys((*brief.prohibited_elements, *library.prohibited_language))),
            "claim_library_sha256": library.digest(), "creative_brief_status": "CREATIVE_READY"})
        validate_brief(library, bound, canonical_brief=canonical.get(brief.key))
        slides.append(bound)
    return handoff.model_copy(update={"slides": tuple(slides)})


def _canonical_briefs(handoff, db, campaign):
    """Resolve authority, never accept a caller's replacement context/role flag."""
    if db is None or campaign is None:
        raise ValueError("Current canonical campaign context is required")
    from .premium_handoff import resolve_canonical_handoff
    current = resolve_canonical_handoff(db, campaign)
    if (handoff.campaign_id != campaign.id or current.campaign_id != handoff.campaign_id
            or current.product_id != handoff.product_id
            or current.expected_slide_count != handoff.expected_slide_count
            or len(handoff.slides) != handoff.expected_slide_count
            or len({b.key for b in handoff.slides}) != len(handoff.slides)
            or {b.key for b in current.slides} != {b.key for b in handoff.slides}):
        raise ValueError("Current canonical campaign / product / slide scope mismatch")
    if (len(handoff.assets) != len(current.assets)
            or len({a.asset_id for a in handoff.assets}) != len(handoff.assets)
            or {a.asset_id: a for a in handoff.assets} != {a.asset_id: a for a in current.assets}):
        raise ValueError("Current canonical asset authority changed")
    canonical = {b.key: b for b in current.slides}
    # Derived claim-ready fields differ legitimately from the unbound canonical
    # brief. Everything else, including exact copy, purpose and source-package
    # digest, must still match. Execution approval is checked independently.
    from ..schemas.premium_handoff import PremiumSlideBrief
    derived = {"approved_claim_ids", "mandatory_qualifiers", "benefit_hierarchy",
               "claim_library_sha256", "creative_brief_status", "prohibited_elements"}
    for brief in handoff.slides:
        supplied = PremiumSlideBrief.model_validate(brief.model_dump(exclude={"execution_plan"}))
        if supplied.model_dump(exclude=derived) != canonical[brief.key].model_dump(exclude=derived):
            raise ValueError("Current canonical purpose / copy / package binding changed")
    return canonical


def require_ready(handoff, *, db=None, campaign=None):
    require_creative_eligibility(handoff.product_id)
    library = load_library(handoff.product_id)
    if library.owner_library_review_status != "APPROVED":
        raise ValueError("Claim library owner approval is required before creative export")
    canonical = _canonical_briefs(handoff, db, campaign)
    for brief in handoff.slides:
        validate_brief(library, brief, canonical_brief=canonical[brief.key])
        if brief.creative_brief_status != "CREATIVE_READY" or brief.claim_library_sha256 != library.digest():
            raise ValueError("Creative gate stale/unreviewed library snapshot")
    return library


def proposed_content_plan(library):
    """Owner-review artifact only: no campaign data mutation or activation."""
    from ..schemas.creative_bridge import CopyField
    by_id = {c.claim_id: c for c in library.claims}
    def wording(key, strength="STANDARD"):
        return by_id[key].approved_pt_br_wording[strength]
    plans = [
        (2, "PRODUCT_BENEFITS_AND_FORMULA", {
            "headline": wording("ex-hydration-radiance-heading", "SHORT"),
            "hydration.title": wording("ex-hydration", "SHORT"), "hydration.body": wording("ex-hydration"),
            "softness.title": wording("ex-softness", "SHORT"), "softness.body": wording("ex-softness"),
            "radiance.title": wording("ex-radiance", "SHORT"), "radiance.body": wording("ex-radiance"),
            "formula.title": wording("editorial-7", "SHORT"), "formula.body": wording("ex-formula")}),
        (3, "SHEET_TECHNOLOGY_AND_SOFTNESS", {"headline": wording("ex-softness", "SHORT"),
            "body": wording("ex-softness"), "sheet": wording("ex-sheet"), "layers": wording("ex-sheet-layers")}),
        (4, "FORMULA_WITHOUT_EFFICACY_INFERENCE", {"headline": wording("editorial-7", "SHORT"),
            "benefit": wording("ex-hydration"), "formula": wording("ex-formula"),
            "vitamin_c": wording("ex-vitamin-c"), "hyaluronic": wording("ex-hyaluronic")}),
        (5, "MOISTURIZING_ROUTINE", {"headline": wording("ex-hydration", "SHORT"),
            "benefit": wording("ex-hydration"), "routine": wording("ex-daily"),
            "toner": wording("ex-toner"), "application": wording("ex-apply"), "after": wording("ex-after")}),
        (6, "BENEFIT_PACK_AND_BRAND_CLOSE", {"headline": wording("editorial-5", "SHORT"),
            "benefit": wording("ex-hydration"), "pack": wording("ex-pack"), "cta": wording("editorial-2", "SHORT")}),
    ]
    output = []
    for number, role, fields in plans:
        fields["slide_marker"] = f"{number}/6"
        copy_fields = tuple(CopyField(key=k, text=v) for k, v in fields.items())
        bindings = resolve_copy(library, copy_fields)
        selected = [by_id[k] for k in dict.fromkeys(bindings.values())]
        output.append({"slide_number": number, "proposed_role": role, "output_size": [1080, 1350],
            "approved_copy": fields, "approved_claim_ids": bindings,
            "mandatory_qualifiers": {c.claim_id: c.mandatory_qualifier for c in selected if c.mandatory_qualifier},
            "benefit_hierarchy": [{"claim_id": c.claim_id, "priority": c.benefit_priority} for c in selected if c.evidence_scope == "PRODUCT_BENEFIT"],
            "factual_support": [c.claim_id for c in selected if c.claim_class == "FACT_ONLY"],
            "prohibited_wording": list(library.prohibited_language),
            "owner_review_status": "PENDING", "campaign_data_mutated": False})
    return output
