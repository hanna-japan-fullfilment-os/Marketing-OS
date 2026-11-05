"""External slide intake, explicit human review and readiness using existing outputs."""
from datetime import datetime,timezone
import hashlib
import io
import json
from pathlib import Path
from uuid import uuid4

from PIL import Image
from sqlalchemy import update

from ..models import CampaignOutput
from .multimodal_creative import normalize_copy
from .premium_handoff import build_campaign_handoff,export_handoff,validate_execution_handoff


def _read_state(db,campaign):
    row=db.query(CampaignOutput).filter_by(campaign_id=campaign.id,kind="premium_state").one_or_none()
    if row is None:
        return None,{"campaign_id":campaign.id,"version":0,"slides":{},"history":[]}
    path=Path(row.file_path)
    raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=path.stem.rsplit("-",1)[-1]:
        raise ValueError("Premium creative state bytes changed")
    data=json.loads(raw)
    if data["campaign_id"]!=campaign.id or data["version"]!=row.version:
        raise ValueError("Premium creative state identity/version mismatch")
    return row,data


def _save_state(db,campaign,data,root,row,*,expected_version):
    current=0 if row is None else row.version
    if current!=expected_version:
        raise ValueError("Creative state changed; refresh before editing")
    directory=Path(root)/"premium_workflow"/campaign.id
    directory.mkdir(parents=True,exist_ok=True)
    data={**data,"version":current+1}
    payload=json.dumps(data,ensure_ascii=False,indent=2).encode("utf-8")
    path=directory/(uuid4().hex+"-"+hashlib.sha256(payload).hexdigest()+".json")
    with path.open("xb") as stream:
        stream.write(payload)
    if row is None:
        if db.query(CampaignOutput).filter_by(campaign_id=campaign.id,kind="premium_state").count():
            raise ValueError("Creative state created concurrently; refresh")
        db.add(CampaignOutput(campaign_id=campaign.id,kind="premium_state",file_path=str(path),version=1))
    else:
        changed=db.execute(update(CampaignOutput).where(CampaignOutput.id==row.id,CampaignOutput.version==current)
            .values(file_path=str(path),version=current+1).execution_options(synchronize_session=False))
        if changed.rowcount!=1:
            raise ValueError("Concurrent creative-state update rejected")
        db.expire(row)
    # A changed creative bundle can never retain campaign-level approval.
    campaign.approved_at=None
    campaign.status="REVIEW"
    db.flush()
    return data


def prepare_campaign_export(db,campaign,root,*,handoff=None):
    handoff=handoff or build_campaign_handoff(db,campaign)
    handoff=validate_execution_handoff(handoff)
    row,state=_read_state(db,campaign)
    bundle=Path(root)/"premium_handoff"/campaign.id/uuid4().hex
    archive=export_handoff(handoff,bundle)
    changed=state.get("handoff_sha256")!=handoff.digest()
    if changed:
        state["history"].extend(state["slides"].values())
        state["slides"]={}
    state.update(handoff_sha256=handoff.digest(),export_directory=str(bundle),archive_path=str(archive),
                 workflow_status="CREATIVE_DRAFT" if changed else state.get("workflow_status","CREATIVE_DRAFT"))
    saved=_save_state(db,campaign,state,root,row,expected_version=state["version"])
    return archive,saved


def _current(handoff,state):
    validate_execution_handoff(handoff)
    if state.get("handoff_sha256")!=handoff.digest():
        raise ValueError("Canonical handoff changed; export a current package and re-review")


def import_slide(db,campaign,root,*,slide_key,filename,data,expected_version,handoff=None):
    handoff=handoff or build_campaign_handoff(db,campaign)
    row,state=_read_state(db,campaign)
    _current(handoff,state)
    slide=next((s for s in handoff.slides if s.key==slide_key),None)
    if slide is None:
        raise ValueError("Unexpected slide number/locale/channel/role")
    if not data or len(data)>20*1024*1024:
        raise ValueError("Slide file exceeds intake limit")
    digest=hashlib.sha256(data).hexdigest()
    known=[s["sha256"] for s in state["slides"].values()]+[s.get("sha256") for s in state["history"]]
    if digest in known:
        raise ValueError("Duplicate file/hash already imported")
    with Image.open(io.BytesIO(data)) as image:
        if image.width*image.height>16777216:
            raise ValueError("Slide exceeds pixel limit")
        image.load()
        size=image.size
        extension={"PNG":".png","JPEG":".jpg","WEBP":".webp"}.get(image.format)
    if extension is None or size!=slide.output_size:
        raise ValueError("Returned slide must match exact handoff dimensions and supported raster format")
    directory=Path(root)/"premium_imports"/campaign.id
    directory.mkdir(parents=True,exist_ok=True)
    path=directory/(uuid4().hex+extension)
    with path.open("xb") as stream:
        stream.write(data)
    if slide_key in state["slides"]:
        state["history"].append(state["slides"][slide_key])
    state["slides"][slide_key]={"campaign_id":campaign.id,"slide_key":slide_key,"slide_number":slide.slide_number,
        "role":slide.slide_role,"locale":slide.locale,"channel":slide.channel,"filename":Path(filename.replace('\\','/')).name,
        "file_path":str(path),"dimensions":list(size),"sha256":digest,"creation_source":"external_chatgpt_creative_workflow",
        "imported_at":datetime.now(timezone.utc).isoformat(),"approval_status":"PENDING_REVIEW",
        "qa_status":"NEEDS_HUMAN_REVIEW","qa":{"readable":True,"dimensions":"PASS","expected_role":"PASS",
            "product_visibility":"UNVERIFIED","canonical_copy":"UNVERIFIED"},"handoff_sha256":handoff.digest()}
    state["workflow_status"]="PENDING_REVIEW"
    return _save_state(db,campaign,state,root,row,expected_version=expected_version)


def review_slide(db,campaign,root,request,*,handoff=None):
    handoff=handoff or build_campaign_handoff(db,campaign)
    row,state=_read_state(db,campaign)
    _current(handoff,state)
    record=state["slides"].get(request.slide_key)
    slide=next((s for s in handoff.slides if s.key==request.slide_key),None)
    if record is None or slide is None:
        raise ValueError("Imported slide not found")
    if hashlib.sha256(Path(record["file_path"]).read_bytes()).hexdigest()!=record["sha256"]:
        raise ValueError("Imported image changed; prior QA cannot authorize it")
    if request.decision=="APPROVED":
        expected={c.key:normalize_copy(c.text) for c in slide.approved_copy}
        observed={k:normalize_copy(v) for k,v in request.observed_copy.items()}
        if expected!=observed or not request.product_visible or not request.product_fidelity_confirmed:
            raise ValueError("Explicit product visibility/fidelity and exact canonical-copy review required")
        record["qa_status"]="PASS"
        record["qa"].update(product_visibility="HUMAN_CONFIRMED",product_fidelity="HUMAN_CONFIRMED",canonical_copy="EXACT_HUMAN_TRANSCRIPTION_MATCH")
    else:
        if not request.feedback_codes or not request.feedback.strip():
            raise ValueError("Rejection requires structured reasons and actionable feedback")
        record["qa_status"]="NEEDS_REVISION"
    record.update(approval_status=request.decision,reviewer=request.reviewer,reviewed_at=datetime.now(timezone.utc).isoformat(),
        feedback_codes=list(request.feedback_codes),feedback=request.feedback,reviewed_sha256=record["sha256"],
        reviewed_handoff_sha256=handoff.digest())
    state["workflow_status"]="PENDING_REVIEW"
    return _save_state(db,campaign,state,root,row,expected_version=request.expected_version)


def readiness(db,campaign,*,handoff=None):
    handoff=handoff or build_campaign_handoff(db,campaign)
    handoff=validate_execution_handoff(handoff)
    _,state=_read_state(db,campaign)
    current=state.get("handoff_sha256")==handoff.digest()
    approved=0
    rejected=0
    missing=[]
    for slide in handoff.slides:
        record=state["slides"].get(slide.key)
        if record is None:
            missing.append(slide.key)
            continue
        rejected+=record["approval_status"]=="REJECTED"
        path=Path(record["file_path"])
        valid=path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest()==record["sha256"]
        approved+=bool(current and valid and record["approval_status"]=="APPROVED" and record["qa_status"]=="PASS"
            and record.get("reviewed_sha256")==record["sha256"] and record.get("reviewed_handoff_sha256")==handoff.digest())
    complete=approved==handoff.expected_slide_count and not missing
    return {"EXPECTED_SLIDE_COUNT":handoff.expected_slide_count,"IMPORTED_SLIDE_COUNT":len(state["slides"]),
        "APPROVED_SLIDE_COUNT":approved,"REJECTED_SLIDE_COUNT":rejected,"CAMPAIGN_CREATIVE_COMPLETE":complete,
        "status":"READY_TO_PUBLISH" if complete else state.get("workflow_status","CREATIVE_DRAFT"),
        "canonical_handoff_current":current,"missing_slides":missing,"version":state["version"],"slides":list(state["slides"].values())}


def require_publishing_ready(db,campaign):
    result=readiness(db,campaign)
    if not result["CAMPAIGN_CREATIVE_COMPLETE"]:
        raise ValueError("Every required external slide needs current human approval and product/copy QA")
    return result


def export_revision(db,campaign,root,slide_key,*,handoff=None):
    handoff=handoff or build_campaign_handoff(db,campaign)
    _,state=_read_state(db,campaign)
    _current(handoff,state)
    record=state["slides"].get(slide_key)
    if record is None or record["approval_status"]!="REJECTED":
        raise ValueError("Select a rejected slide for revision")
    data=Path(record["file_path"]).read_bytes()
    if hashlib.sha256(data).hexdigest()!=record["sha256"]:
        raise ValueError("Rejected slide bytes changed")
    directory=Path(root)/"premium_revisions"/campaign.id/uuid4().hex
    archive=export_handoff(handoff,directory,revision={"slide_key":slide_key,"feedback_codes":record["feedback_codes"],
        "requested_visual_changes":record["feedback"],"original_sha256":record["sha256"],"canonical_copy_unchanged":True})
    import zipfile
    with zipfile.ZipFile(archive,"a") as bundle:
        bundle.writestr("REJECTED_ORIGINAL"+Path(record["file_path"]).suffix,data)
    return archive
