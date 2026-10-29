"""Canonical external-creative packages. No provider SDK, generation or renderer."""
import hashlib
import json
import re
from pathlib import Path
import zipfile

from ..schemas.premium_handoff import PremiumCreativeHandoff,PremiumSlideBrief
from .hanna_creative_package import verified_image_bytes

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


def build_campaign_handoff(db,campaign):
    from ..models import Brand, CampaignOutput
    from ..schemas.ai import SlidePlan
    from .hanna_creative_package import build_hanna_creative_package
    from .creative.templates import get_platform_format
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


def _public_asset(asset):
    if not re.fullmatch(r"[A-Za-z0-9_-]+",asset.asset_id):
        raise ValueError("Unsafe export asset identifier")
    extension={"image/png":".png","image/jpeg":".jpg","image/webp":".webp"}[asset.mime_type]
    return {"asset_id":asset.asset_id,"role":asset.role,"sha256":asset.sha256,"width":asset.width,"height":asset.height,
        "authority":asset.authority,"provenance_json":asset.provenance_json,
        "file":f"assets/{asset.asset_id}-{asset.sha256[:12]}{extension}"}


def export_handoff(handoff,directory,*,revision=None):
    """New bundle only. Asset bytes are copied, never altered; no registry writes."""
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
    if revision:
        public["revision"]=revision
    files={"HANNA_CAMPAIGN_HANDOFF.json":public,"HANNA_CAMPAIGN_ASSETS.json":{
        "handoff_sha256":handoff.digest(),"assets":manifest}}
    for name,payload in files.items():
        with (directory/name).open("x",encoding="utf-8") as stream:
            json.dump(payload,stream,ensure_ascii=False,indent=2)
    instruction=CHATGPT_INSTRUCTION+("\nREVISION: change only the rejected slide according to the attached exact feedback. Facts/copy stay unchanged." if revision else "")
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
