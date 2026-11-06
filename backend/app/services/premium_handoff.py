"""Canonical external-creative packages. No provider SDK, generation or renderer."""
import hashlib
import json
import re
from pathlib import Path
import zipfile

from ..schemas.premium_handoff import PremiumCreativeHandoff,PremiumSlideBrief
from .hanna_creative_package import verified_image_bytes


def validate_execution_handoff(handoff, *, require_approval=True):
    """Revalidate even model_copy/construct inputs before any file/state writes.

    V1 remains an explicitly legacy workflow, never implicitly upgraded.
    """
    from ..schemas.premium_handoff import PremiumExecutionHandoff, PremiumSlideBrief
    from .campaign_creative_strategy import composition_for_purpose
    if handoff.version == 1:
        return PremiumCreativeHandoff.model_validate(handoff.model_dump(mode="json"))
    if handoff.version != 2:
        raise ValueError("Unsupported premium execution handoff version")
    handoff = PremiumExecutionHandoff.model_validate(handoff.model_dump(mode="json"))
    if not handoff.slides or handoff.expected_slide_count != len(handoff.slides):
        raise ValueError("Complete execution slide set required")
    if len({s.key for s in handoff.slides}) != len(handoff.slides):
        raise ValueError("Duplicate execution slide")
    assets = {a.asset_id: a for a in handoff.assets}
    if len(assets) != len(handoff.assets):
        raise ValueError("Duplicate execution asset identity")
    for slide in handoff.slides:
        plan = slide.execution_plan
        brief = PremiumSlideBrief.model_validate(slide.model_dump(exclude={"execution_plan"}))
        if plan.slide_key != slide.key or plan.brief_sha256 != brief.digest():
            raise ValueError("Execution plan is stale or belongs to a different slide")
        expected = composition_for_purpose(slide.slide_role, slide.primary_message)
        if plan.composition_family != expected['composition_family']:
            raise ValueError("Composition family incompatible with communication purpose")
        if plan.communication_objective != slide.primary_message:
            raise ValueError("Execution objective must preserve the approved primary message")
        if {r.asset_id for r in plan.references} != set(slide.reference_asset_ids):
            raise ValueError("Every approved slide reference needs an execution rationale")
        for ref in plan.references:
            asset = assets.get(ref.asset_id)
            if (asset is None or asset.role != "visual_reference" or asset.sha256 != ref.sha256
                    or asset.authority not in ("owner-approved-target", "approved-custom-gpt-quality-benchmark")):
                raise ValueError("Execution reference lacks exact approved asset authority")
            verified_image_bytes(asset)
        products = [assets.get(key) for key in slide.product_asset_ids]
        if not products or any(a is None or a.role not in ("product_source", "product_master") for a in products):
            raise ValueError("Execution plan requires exact canonical product assets")
        for asset in products:
            verified_image_bytes(asset)
        if require_approval and plan.owner_review_status != "APPROVED":
            raise ValueError("Owner execution-plan approval required; structural validity is insufficient")
    return handoff


def prepare_execution_handoff(handoff, plans):
    """Explicit, in-memory v1 -> v2 adoption; never writes canonical campaign data.

    Draft plans may be prepared for owner review. Production export requires
    named owner approval of the exact content, using the existing operator trust model.
    """
    from ..schemas.premium_handoff import PremiumExecutionHandoff
    if handoff.version != 1 or set(plans) != {s.key for s in handoff.slides}:
        raise ValueError("Explicit legacy handoff and exact complete execution-plan keys required")
    payload = handoff.model_dump(mode="json")
    payload['version'] = 2
    for slide in payload['slides']:
        plan = plans[slide['key']]
        slide['execution_plan'] = plan.model_dump(mode="json") if hasattr(plan, 'model_dump') else plan
    result = PremiumExecutionHandoff.model_validate(payload)
    return validate_execution_handoff(result, require_approval=False)

CHATGPT_INSTRUCTION = """CREATE THIS HANNA CAMPAIGN FROM THE ATTACHED HANDOFF AND ASSETS.
Read HANNA_CAMPAIGN_HANDOFF.md and .json, and inspect the actual assets/ images.
Marketing OS owns product identity, facts, claims, exact copy, language, CTA and slide order.
Create each slide as a complete premium advertising artwork. Use the actual product
photography/cutouts for identity and approved Hanna visuals for art direction, never
for their depicted product or claims. Preserve the exact variant, packaging and labels.
Use natural Brazilian Portuguese for pt-BR while keeping approved copy verbatim.
Maintain campaign cohesion with deliberate per-slide variation. Integrate typography,
logo and CTA naturally; prioritize product storytelling, hierarchy and premium polish.
Avoid generic ecommerce layouts, dashboard/UI panels and random Japanese clichés.
Do not invent facts/claims or copy another product from a reference. Missing facts stay
unknown. No compositor coordinates, locked-base masks or old renderer assumptions apply.
Return exactly the listed slides in their specified size/order. Marketing OS import and
explicit human visual/product/copy review are required; do not assume publication approval."""


def uses_premium_handoff(db,campaign):
    from ..models import Brand
    brand=db.get(Brand,campaign.brand_id)
    return bool(brand and (brand.slug=="hanna-japan" or (brand.campaign_rules or {}).get("premium_creative_workflow")=="external_chatgpt"))


def export_strategy_planning_package(plan, library, directory):
    """Export reviewed strategy-derived briefs, never an executable image job.

    This planning export does not bypass production/human review on an existing
    handoff or assert commercial clearance. No production state is touched.
    """
    from .campaign_creative_strategy import validate_plan
    validate_plan(plan, library)
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    with (directory / 'CAMPAIGN_STRATEGY_CREATIVE_PLAN.json').open('x', encoding='utf-8') as stream:
        json.dump(plan, stream, ensure_ascii=False, indent=2)
    with (directory / 'PROPOSED_MESSAGE_USAGE.json').open('x', encoding='utf-8') as stream:
        json.dump({'usage': plan['message_usage_snapshot'], 'status': plan['message_usage_snapshot_status']},
                  stream, ensure_ascii=False, indent=2)
    instructions = (
        'PLANNING ONLY — OWNER REVIEW REQUIRED. Do not generate artwork from this export automatically.\n'
        'Only approved_copy is visible advertising text. Strategy metadata, hypotheses and visual intent are not copy.\n'
        'Keep exact claim bindings/qualifiers and prohibited wording. Never invent claims.\n'
        'Use the visual benchmark for quality, not its layout/product/claims; it is not approval evidence.\n'
        'All future images require product fidelity and explicit visual/human approval.\n'
    )
    if plan.get('execution_contract_version') == 1:
        instructions += (
            'Purpose-aware execution_proposal is a draft, not a complete execution plan.\n'
            'Before production, prepare the version-2 handoff with exact approved reference IDs/hashes, '
            'per-reference permitted influences and rationale, spatial/camera/light/type requirements '
            'and named owner review of the exact content. A benchmark string grants no authority.\n'
            'Approved references may guide composition as expressly prepared in that contract; '
            'never transfer their packaging, claims or visible copy.\n'
        )
    (directory / 'PREMIUM_CREATIVE_PLANNING_INSTRUCTION.txt').write_text(instructions, encoding='utf-8')
    return directory


def assemble_handoff(campaign,packages):
    if not packages:
        raise ValueError("Complete canonical slide plans required")
    first=packages[0][1]
    images={}
    briefs=[]
    for number,package in packages:
        if package.campaign_id!=campaign.id or package.product_id!=first.product_id:
            raise ValueError("Campaign/product handoff scope mismatch")
        for asset in package.images:
            verified_image_bytes(asset)
            if asset.asset_id in images and images[asset.asset_id]!=asset:
                raise ValueError("Asset provenance differs across slides")
            images[asset.asset_id]=asset
        briefs.append(PremiumSlideBrief(key=f"{package.locale}:{package.channel}:{number}",slide_number=number,
            slide_role=package.slide_role,primary_message=next((c.text for c in package.approved_copy if c.key=="headline"),""),
            approved_copy=package.approved_copy,facts_allowed_json=package.approved_facts_json,
            product_asset_ids=tuple(a.asset_id for a in package.images if a.role in ("product_source","product_master")),
            reference_asset_ids=tuple(a.asset_id for a in package.images if a.role=="visual_reference"),
            visual_intent=f"Complete premium artwork for {package.slide_role}; communicate the approved message within a cohesive campaign.",
            required_elements=("canonical product identity","canonical Hanna logo","exact approved copy","CTA when supplied"),
            prohibited_elements=tuple(package.prohibited_claims)+("unapproved claims","wrong product/variant","generic UI panels"),
            cta=package.required_cta,output_size=(package.width,package.height),locale=package.locale,channel=package.channel,
            canonical_package_sha256=package.digest()))
    if len({s.key for s in briefs})!=len(briefs):
        raise ValueError("Duplicate slide order/locale/channel")
    return PremiumCreativeHandoff(campaign_id=campaign.id,product_id=first.product_id,product_name=first.product_name,
        category=first.category,objective=campaign.objective,concept=campaign.angle or campaign.hook or "",
        audience=campaign.audience or "",brand_instructions=first.brand_instructions,approved_facts_json=first.approved_facts_json,
        prohibited_claims=first.prohibited_claims,expected_slide_count=len(briefs),slides=tuple(briefs),assets=tuple(images.values()))


def resolve_canonical_handoff(db,campaign):
    """Read current campaign plans and revalidate live evidence, without binding.

    Kept separate from claim readiness to avoid recursive authority resolution.
    This creates no alternate registry or campaign/state writes.
    """
    from ..models import Brand, Campaign, CampaignOutput
    from ..schemas.ai import SlidePlan
    from .hanna_creative_package import build_hanna_creative_package
    from .creative.templates import get_platform_format
    if db.new or db.dirty or db.deleted:
        raise ValueError("Canonical authority requires a clean read-only session")
    # A long-lived session may still hold evidence/campaign objects from the
    # historical export. Re-read them rather than trusting its identity map.
    db.expire_all()
    campaign = db.get(Campaign, campaign.id)
    if campaign is None:
        raise ValueError("Current canonical campaign is missing")
    if not campaign.product_id:
        raise ValueError("Select a canonical product before premium handoff")
    output=(db.query(CampaignOutput).filter_by(campaign_id=campaign.id,kind="creative")
            .order_by(CampaignOutput.created_at.desc()).first())
    if output is None:
        raise ValueError("Run canonical planning/copy before handoff")
    # Explicit UTF-8 is necessary on Windows: the legacy loader uses the ANSI
    # default, which can corrupt Portuguese evidence/copy before validation.
    creative=json.loads(Path(output.file_path).read_text(encoding="utf-8-sig"))
    brand=db.get(Brand,campaign.brand_id)
    fmt=get_platform_format(campaign.platform_key or "instagram_portrait")
    packages=[]
    for locale in (campaign.languages or [campaign.language or "pt-BR"]):
        if "languages" in creative:
            if locale not in creative["languages"]:
                raise ValueError("Missing exact canonical locale; translation/fallback is forbidden")
            variant=creative["languages"][locale]
        elif locale==campaign.language:
            variant=creative
        else:
            raise ValueError("Missing exact canonical locale")
        plans=[SlidePlan.model_validate(p) for p in variant.get("carousel_plan",{}).get("slides",[])]
        if not plans or (campaign.target_slide_count and len(plans)!=campaign.target_slide_count):
            raise ValueError("Canonical campaign slide count is incomplete")
        for channel in (campaign.target_platforms or campaign.channels or ["instagram"]):
            for index,plan in enumerate(plans,1):
                package=build_hanna_creative_package(db,campaign,plan,campaign_plans=plans,locale=locale,channel=channel,
                    brand_instructions=brand.creative_instructions or "Premium Hanna advertising: actual references guide complete artwork; preserve identity, facts and exact copy.",
                    prohibited_claims=tuple(brand.disallowed_terms or ())+("No unsupported product claims",),
                    visual_objective="External premium creative production",width=fmt.width,height=fmt.height)
                packages.append((index,package))
    return assemble_handoff(campaign,packages)


def build_campaign_handoff(db,campaign):
    from .marketing_claims import bind_handoff
    return bind_handoff(resolve_canonical_handoff(db,campaign), db=db, campaign=campaign)


def _public_asset(asset):
    if not re.fullmatch(r"[A-Za-z0-9_-]+",asset.asset_id):
        raise ValueError("Unsafe export asset identifier")
    extension={"image/png":".png","image/jpeg":".jpg","image/webp":".webp"}[asset.mime_type]
    return {"asset_id":asset.asset_id,"role":asset.role,"sha256":asset.sha256,"width":asset.width,"height":asset.height,
        "authority":asset.authority,"provenance_json":asset.provenance_json,
        "file":f"assets/{asset.asset_id}-{asset.sha256[:12]}{extension}"}


def export_handoff(handoff,directory,*,revision=None,db=None,campaign=None):
    """New bundle only. Asset bytes are copied, never altered; no registry writes."""
    handoff = validate_execution_handoff(handoff)
    from .marketing_claims import require_ready, approved_library
    library=require_ready(handoff, db=db, campaign=campaign)
    from .product_creative_eligibility import require_creative_eligibility
    eligibility=require_creative_eligibility(handoff.product_id)
    directory=Path(directory)
    directory.mkdir(parents=True,exist_ok=False)
    (directory/"assets").mkdir()
    manifest=[_public_asset(a) for a in handoff.assets]
    for asset,record in zip(handoff.assets,manifest):
        data=verified_image_bytes(asset)
        with (directory/record["file"]).open("xb") as stream:
            stream.write(data)
    public=handoff.model_dump(mode="json")
    public["assets"]=manifest
    public["handoff_sha256"]=handoff.digest()
    public["approved_claim_library"]=approved_library(library)
    public["creative_model_claim_invention_allowed"]=False
    public["creative_eligibility"]=eligibility
    if revision:
        public["revision"]=revision
    files={"HANNA_CAMPAIGN_HANDOFF.json":public,"HANNA_CAMPAIGN_ASSETS.json":{
        "handoff_sha256":handoff.digest(),"assets":manifest}}
    for name,payload in files.items():
        with (directory/name).open("x",encoding="utf-8") as stream:
            json.dump(payload,stream,ensure_ascii=False,indent=2)
    instruction=CHATGPT_INSTRUCTION+"\nUse only the approved_copy and approved_claim_ids. Keep every mandatory_qualifier in visible copy. Follow benefit_hierarchy and prohibited_elements. Never invent or strengthen a benefit."+("\nREVISION: change only the rejected slide according to the attached exact feedback. Facts/copy stay unchanged." if revision else "")
    if handoff.version == 2:
        instruction += (
            "\nFollow each owner-reviewed execution_plan: its concrete visual mechanism, product role, "
            "camera/spatial relationships, lighting integration and typography requirements. "
            "References guide only their listed permitted_influences; never transfer reference claims "
            "or packaging. Prohibited imagery is binding. Human context must not depict application "
            "or results. Plan approval is not artwork acceptance, publication or provider authorization. "
            "Structural completeness does not establish premium quality."
        )
    (directory/"CHATGPT_READY_INSTRUCTION.txt").write_text(instruction,encoding="utf-8")
    lines=["# Hanna premium campaign handoff",instruction,"## Campaign",json.dumps({k:v for k,v in public.items() if k not in ("slides","assets")},ensure_ascii=False,indent=2)]
    for slide in handoff.slides:
        lines.extend([f"## Slide {slide.slide_number} — {slide.locale} / {slide.channel}",
            "```json\n"+json.dumps(slide.model_dump(mode="json"),ensure_ascii=False,indent=2)+"\n```"])
    lines.append("## Attached assets\n"+json.dumps(manifest,ensure_ascii=False,indent=2))
    (directory/"HANNA_CAMPAIGN_HANDOFF.md").write_text("\n\n".join(lines),encoding="utf-8")
    archive=directory/"HANNA_PREMIUM_CREATIVE_HANDOFF.zip"
    with zipfile.ZipFile(archive,"x",compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(directory.rglob("*")):
            if path.is_file() and path!=archive:
                bundle.write(path,path.relative_to(directory).as_posix())
    return archive
