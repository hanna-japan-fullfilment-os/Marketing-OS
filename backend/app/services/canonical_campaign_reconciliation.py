"""Explicit offline reconciliation. No startup hook, provider, or evidence promotion.

The constants lock an owner-approved import recipe, not a second claim registry.
Claims, translations and live evidence still come from their existing authorities.
"""
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit

from ..schemas.ai import SlidePlan
from ..schemas.premium_handoff import CanonicalCampaignReconciliation

PRODUCT_ID = "a5ea2272a1f89d743c089461bb2fb50f"
HISTORICAL_CAMPAIGN_ID = "7854f4183375461fb508fad2f0709df9"
ARCHITECTURE_SHA256 = "0717fc483a74fa24434a0547d722aa2aa25146fdf46903076dfe65588176f5c1"
APPROVAL_SHA256 = "b449843b8d1b420642d28c2f074bdd3e6a3478ac6cfd78f31636b39154ecc733"
FREEZE_SHA256 = "072c4541a533dc7348d3e95de458e3045490de263feba9722a81a20e99a910a8"
MASTER_SHA256 = "da2d4ea98e7d3549b65493ac0a93431c9a317383973fc8225a7943232e5417a1"
SOURCE_SHA256 = "94e7fb1436596f0566ddf0b83359cfff1c402bd36fc7435c5067243de1a591cb"
LOGO_SHA256 = "4cf095f0b446953147b33bc7668228c1e535f3d3814fb0ceb2e3e727e181b8c6"
SOURCE_LOGO_SHA256 = "3ac4671fa7109973214cbd2ebc45226cc8b547a56183150a3f12bac440bf72b9"
REFERENCE_HASHES = frozenset({
    "072e9126d5b9b45be8b8d2a0a6f1f9b666c32d0a20e5c4a3d61c2478ee9a9e94",
    "2db6f2f169729c801790678b4e288cf733fe0194eab2f4bda11a77cd9041cdf7",
    "322e3aa65357a4d805ddd9b732b62d643ff8b4ca68cb72329f7c5cc7eebd64e1",
})
PURPOSES = (
    ("product_identity", ("editorial-1", "ex-pack")),
    ("hydration", ("ex-hydration", "ex-radiance")),
    ("selected_formula", ("ex-formula",)),
    ("formula", ("ex-vitamin-c", "ex-hyaluronic")),
    ("sheet_detail", ("ex-softness", "ex-sheet", "ex-sheet-layers")),
    ("routine_fit", ("ex-daily", "ex-toner")),
    ("application", ("ex-apply",)),
    ("routine_aftercare", ("ex-after",)),
    ("formulation_choice", ("ex-free-fragrance",)),
    ("learning_cta", ("editorial-2",)),
)
FROZEN_CLASSIFICATIONS = (
    "PASSABLE_NEAR_TARGET_APPROVED", "PASSABLE_KEEP_APPROVED",
    "PASSABLE_BELOW_TARGET_APPROVED", "PASSABLE_NEAR_TARGET_APPROVED",
    "PASSABLE_NEAR_TARGET_APPROVED", "PREMIUM_TARGET_ACCEPTED",
)


def checked_bytes(evidence, expected=None):
    raw = Path(evidence.path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != evidence.sha256 or (expected and evidence.sha256 != expected):
        raise ValueError("Reconciliation evidence hash mismatch")
    return raw


def architecture(manifest):
    matrix = json.loads(checked_bytes(manifest.architecture, ARCHITECTURE_SHA256))
    approval = json.loads(checked_bytes(manifest.architecture_approval, APPROVAL_SHA256))
    if (approval.get("OWNER_ARCHITECTURE_DECISION") != "APPROVED"
            or not any(x["file"] == Path(manifest.architecture.path).name
                and x["sha256"].lower() == ARCHITECTURE_SHA256
                for x in approval.get("approved_deliverables", []))):
        raise ValueError("Exact architecture approval required")
    slides = matrix.get("slides", [])
    if [s["SLIDE_NUMBER"] for s in slides] != list(range(1, 11)):
        raise ValueError("Complete ordered ten-slide architecture required")
    for slide, (_, ids) in zip(slides, PURPOSES):
        if tuple(c["claim_id"] for c in slide["VERIFIED_FACTS_USED"]) != ids:
            raise ValueError("Approved architecture claim assignments changed")
    return matrix


def frozen_evidence(manifest):
    frozen = json.loads(checked_bytes(manifest.freeze, FREEZE_SHA256))
    files = frozen.get("canonical_files", {})
    if not frozen.get("SLIDES_1_6_FROZEN") or len(files) != 6:
        raise ValueError("Complete frozen evidence required")
    for path, digest in files.items():
        if hashlib.sha256(Path(path).read_bytes()).hexdigest() != digest.lower():
            raise ValueError("Frozen artwork bytes changed")
    return tuple({"slide_number": n, "sha256": sha.lower(), "classification": classification,
        "approval_adopted": False} for n, ((_, sha), classification)
        in enumerate(zip(files.items(), FROZEN_CLASSIFICATIONS), 1))


def _clean(db):
    if db.new or db.dirty or db.deleted:
        raise ValueError("Reconciliation authority requires a clean session")
    db.expire_all()


def load_reconciliation(db, campaign):
    """Only persisted, hash-addressed canonical outputs establish import context."""
    from ..models import CampaignOutput
    rows = db.query(CampaignOutput).filter_by(campaign_id=campaign.id, kind="campaign_reconciliation").all()
    if not rows:
        if campaign.campaign_family == "BUILD6R_EXEC0003":
            raise ValueError("Canonical reconciliation context is missing")
        return None
    if len(rows) != 1:
        raise ValueError("Ambiguous canonical reconciliation context")
    raw = Path(rows[0].file_path).read_bytes()
    manifest = CanonicalCampaignReconciliation.model_validate_json(raw)
    if Path(rows[0].file_path).stem != manifest.digest():
        raise ValueError("Canonical reconciliation output digest changed")
    return manifest


def _url(value):
    p = urlsplit(value)
    return (p.scheme, p.netloc, p.path.rstrip("/"))


def validate_reconciliation(db, campaign, manifest, creative):
    """Current evidence, exact approved recipe and canonical assets; no writes."""
    from ..models import Product, Asset, BrandAsset, ResearchSource
    from .marketing_claims import load_library, resolve_copy
    from ..schemas.creative_bridge import CopyField
    from .orchestrator import _claim_reference, _asset_reference
    from .hanna_creative_package import verified_image_bytes
    from .product_asset_selection import choose_approved_product_master
    _clean(db)
    manifest = CanonicalCampaignReconciliation.model_validate(manifest.model_dump(mode="json"))
    if (campaign.id == HISTORICAL_CAMPAIGN_ID or manifest.campaign_id != campaign.id
            or campaign.product_id != PRODUCT_ID or manifest.product_id != PRODUCT_ID
            or campaign.target_slide_count != 10 or campaign.languages != ["pt-BR"]
            or campaign.target_platforms != ["instagram"] or campaign.platform_key != "instagram_portrait"):
        raise ValueError("Separate exact ten-slide campaign identity required")
    matrix = architecture(manifest)
    if (campaign.objective != matrix.get('objective')
            or campaign.funnel_stage != matrix.get('funnel_stage')
            or campaign.audience != matrix.get('audience')):
        raise ValueError("Approved canonical campaign strategy changed")
    frozen_evidence(manifest)
    if hashlib.sha256(creative).hexdigest() != manifest.creative_sha256:
        raise ValueError("Canonical creative output changed")
    content = json.loads(creative)
    plans = [SlidePlan.model_validate(p) for p in content.get("carousel_plan", {}).get("slides", [])]
    if [p.slide_number for p in plans] != list(range(1, 11)) or len({p.slide_id for p in plans}) != 10 or any(not p.slide_id for p in plans):
        raise ValueError("Complete independent ten-slide coverage required")
    product = db.get(Product, PRODUCT_ID)
    if not product or product.brand_id != campaign.brand_id:
        raise ValueError("Canonical exact product identity missing")
    library = load_library(PRODUCT_ID)
    by_id = {c.claim_id: c for c in library.claims}
    if {key for _, ids in PURPOSES for key in ids} - set(by_id):
        raise ValueError("Reviewed canonical campaign claims are missing")
    product_ids = {key for _, ids in PURPOSES for key in ids if by_id[key].evidence_scope != "EDITORIAL"}
    if set(manifest.evidence_ids) != product_ids or len(set(manifest.evidence_ids.values())) != len(product_ids):
        raise ValueError("Exact fourteen product-evidence mappings required")
    for key, evidence_id in manifest.evidence_ids.items():
        current = _claim_reference(db, evidence_id, PRODUCT_ID)
        claim = by_id[key]
        if current.claim_text not in claim.approved_pt_br_wording.values():
            raise ValueError("Reviewed claim / canonical evidence wording mismatch")
        sources = [db.get(ResearchSource, sid) for sid in current.source_ids]
        if not any(s and _url(s.url) == _url(claim.source_reference) for s in sources):
            raise ValueError("Canonical evidence lacks the reviewed manufacturer source")
    master = db.get(Asset, manifest.master_asset_id)
    if (not master or master.sha256 != MASTER_SHA256
            or (master.ai_metadata or {}).get("source_sha256") != SOURCE_SHA256
            or (master.ai_metadata or {}).get("campaign_scope_id") != campaign.id
            or choose_approved_product_master([master], source_lookup=lambda key: db.get(Asset, key), campaign_id=campaign.id) is None):
        raise ValueError("Campaign-scoped reconstructed master authority required")
    logo_provenance = json.loads(manifest.logo.provenance_json)
    original_logo = db.get(BrandAsset, logo_provenance.get("source_asset_id", ""))
    if (logo_provenance.get("campaign_id") != campaign.id
            or logo_provenance.get("source_sha256") != SOURCE_LOGO_SHA256
            or not original_logo or original_logo.brand_id != campaign.brand_id or original_logo.kind != "logo"
            or original_logo.label.startswith("campaign:")
            or hashlib.sha256(Path(original_logo.file_path).read_bytes()).hexdigest() != SOURCE_LOGO_SHA256):
        raise ValueError("Original Hanna logo provenance required")
    if (manifest.logo.role != "logo" or manifest.logo.sha256 != LOGO_SHA256
            or not manifest.references or len({r.asset_id for r in manifest.references}) != len(manifest.references)
            or any(r.role != "visual_reference" or r.sha256 not in REFERENCE_HASHES for r in manifest.references)):
        raise ValueError("Explicit logo and unique reference bindings required")
    for image in (manifest.logo, *manifest.references):
        row = db.get(BrandAsset, image.asset_id)
        if (not row or row.brand_id != campaign.brand_id or row.kind != image.role
                or Path(row.file_path).resolve() != Path(image.path).resolve()
                or (image.role == "visual_reference" and row.label not in
                    ("owner-approved-target", "approved-custom-gpt-quality-benchmark"))
                or (image.role == "visual_reference" and image.authority != row.label)
                or (image.role == "logo" and row.label != "campaign:" + campaign.id + ":logo")):
            raise ValueError("Campaign asset identity / approval mismatch")
        verified_image_bytes(image)
    from .creative.pipeline import slide_visible_copy_fields
    for plan, approved, (purpose, ids) in zip(plans, matrix["slides"], PURPOSES):
        fields = slide_visible_copy_fields(plan)
        expected_copy = approved["EXACT_VISIBLE_COPY"]
        if (plan.purpose != purpose or list(fields.values()) != expected_copy
                or plan.headline != approved["KEY_MESSAGE"]):
            raise ValueError("Exact approved purpose / copy / line placement required")
        bindings = resolve_copy(library, tuple(CopyField(key=k, text=v) for k, v in fields.items()))
        if tuple(bindings.values()) != ids:
            raise ValueError("Exact slide claim coverage required")
        expected_ids = [manifest.evidence_ids[key] for key in ids if key in manifest.evidence_ids]
        if plan.verified_claim_ids != expected_ids:
            raise ValueError("Canonical slide evidence IDs changed")
        if plan.product_asset != _asset_reference(master):
            raise ValueError("Locked campaign master binding changed")
        references = {r.asset_id: r for r in manifest.references}
        if not plan.reference_asset_ids or set(plan.reference_asset_ids) - set(references):
            raise ValueError("Approved composition reference required")
        for ref in plan.reference_assets:
            if ref != _asset_reference(db.get(BrandAsset, ref.asset_id), reference=True):
                raise ValueError("Current reference provenance changed")
            if ref.sha256 != references[ref.asset_id].sha256:
                raise ValueError("Reference hash differs from canonical manifest")
    return manifest, plans, matrix


def current_reconciliation(db, campaign):
    from ..models import Campaign, CampaignOutput
    _clean(db)
    campaign = db.get(Campaign, campaign.id)
    if campaign is None:
        raise ValueError("Current canonical campaign missing")
    manifest = load_reconciliation(db, campaign)
    if manifest is None:
        return None
    output = db.query(CampaignOutput).filter_by(campaign_id=campaign.id, kind="creative").order_by(CampaignOutput.created_at.desc()).first()
    if output is None:
        raise ValueError("Reconciled canonical creative output missing")
    validate_reconciliation(db, campaign, manifest, Path(output.file_path).read_bytes())
    return manifest


def prepare_campaign(db, campaign, manifest, creative):
    """Validate a detached proposal; allocate no IDs, create no files or records."""
    manifest, plans, matrix = validate_reconciliation(db, campaign, manifest, creative)
    from .orchestrator import validate_slide_provenance
    # Validate against a persisted or detached campaign's exact identity; does not
    # approve artwork or evidence. All evidence must already exist independently.
    for plan in plans:
        validate_slide_provenance(db, campaign, plan)
    return {"campaign_id": campaign.id, "manifest_sha256": manifest.digest(),
        "creative_sha256": manifest.creative_sha256, "slide_count": len(plans),
        "status": "PENDING_OWNER_REVIEW", "objective": matrix["objective"],
        "campaign_record": {"id": campaign.id, "display_id": campaign.display_id,
            "brand_id": campaign.brand_id, "product_id": campaign.product_id,
            "category_id": campaign.category_id, "objective": matrix["objective"],
            "audience": matrix["audience"], "funnel_stage": matrix["funnel_stage"],
            "target_slide_count": 10, "language": "pt-BR", "languages": ["pt-BR"],
            "target_platforms": ["instagram"], "platform_key": "instagram_portrait",
            "campaign_family": "BUILD6R_EXEC0003", "status": "IDEA",
            "human_review_status": "PENDING", "approved_at": None, "published_at": None},
        "slide_records": [{"campaign_id": campaign.id, "slide_number": p.slide_number,
            "purpose": p.purpose, "eyebrow": p.eyebrow, "headline": p.headline,
            "body": p.body, "cta": p.cta, "visual_brief": p.visual_brief,
            "source_asset_id": manifest.master_asset_id, "rendered_asset_path": "",
            "generated_background_path": ""} for p in plans],
        "creative_output": {"kind": "creative", "sha256": manifest.creative_sha256},
        "reconciliation_output": {"kind": "campaign_reconciliation", "manifest": manifest.model_dump(mode="json")}}


def prepare_slide_plans(db, campaign, manifest):
    """Deterministic in-memory conversion; existing campaign/evidence IDs only.

    Product identity is added from the current Product by the package builder,
    not disguised as a claim or inserted into the renderer's neutral vocabulary.
    The caller must subsequently bind the resulting creative bytes and run
    prepare_campaign before any separately authorized application operation.
    """
    from ..models import Asset, BrandAsset
    from .orchestrator import _claim_reference, _asset_reference, _current_brand_disclaimer
    from .creative.pipeline import canonical_slide_claim_bindings
    _clean(db)
    if campaign.id == HISTORICAL_CAMPAIGN_ID or manifest.campaign_id != campaign.id:
        raise ValueError("Separate campaign identity required")
    approved = architecture(manifest)
    master = db.get(Asset, manifest.master_asset_id)
    if master is None:
        raise ValueError("Existing scoped master required before planning")
    refs = [_asset_reference(db.get(BrandAsset, r.asset_id), reference=True) for r in manifest.references]
    plans = []
    for n, (slide, (purpose, ids)) in enumerate(zip(approved['slides'], PURPOSES), 1):
        words = slide['EXACT_VISIBLE_COPY']
        if not 1 <= len(words) <= 3 or not slide.get('VISUAL_STORY', '').strip():
            raise ValueError("Approved text placement and visual direction required")
        selected = [manifest.evidence_ids[key] for key in ids if key in manifest.evidence_ids]
        plan = SlidePlan(slide_number=n, slide_id=f"{campaign.id}:pt-BR:instagram:{n}",
            purpose=purpose, headline=words[0], body=words[1] if len(words)>1 else '',
            callout_value=words[2] if len(words)>2 else '', visual_brief=slide['VISUAL_STORY'],
            disclaimer=_current_brand_disclaimer(db, campaign),
            product_asset=_asset_reference(master), reference_asset_ids=[r.asset_id for r in refs],
            reference_assets=refs, verified_claim_ids=selected,
            evidence_references=[_claim_reference(db, key, campaign.product_id) for key in selected],
            selection_rationale='Exact owner-approved architecture with existing canonical evidence and campaign-scoped assets')
        plans.append(plan.model_copy(update={'claim_bindings':canonical_slide_claim_bindings(plan)}))
    return tuple(plans)


def apply_campaign(db, campaign, manifest, creative, output_directory, *, owner_authorization):
    """Explicit draft-only application, with thirteen inserts and no approvals.

    owner_authorization is the ID of an independently persisted AuditEvent. This
    adapter never creates/changes that event or any evidence/asset prerequisite.
    The caller supplies a fresh dedicated Session; this operation owns its two
    transactions. There is no route, startup call, fallback or automatic retry.
    """
    from sqlalchemy import text
    from ..models import Campaign, CampaignSlide, CampaignOutput
    _application_entry(db, owner_authorization)
    manifest = CanonicalCampaignReconciliation.model_validate_json(manifest.model_dump_json())
    creative = bytes(creative)
    output_directory = Path(output_directory).resolve()
    try:
        preview, authorization = _authorized_application(db, campaign, manifest, creative,
            output_directory, owner_authorization)
    finally:
        db.rollback()  # End our read-only preflight, never a caller transaction.
    campaign = Campaign(**preview['campaign_record'])  # Private reviewed proposal, not a mutable caller alias.
    owned = []
    directory = Path(preview['output_directory']) / ('application-' + authorization.operation_id)
    directory_identity = None
    commit_attempted = False
    try:
        # Serialize collision/idempotency checks with inserts. Read authority
        # again after the lock, before mkdir, file publication or any DML.
        db.execute(text('BEGIN IMMEDIATE'))
        current, current_authorization = _authorized_application(db, campaign, manifest, creative,
            output_directory, owner_authorization)
        if current != preview or current_authorization != authorization:
            raise ValueError('Application authority changed after preflight')
        files = _application_files(directory, manifest, creative)
        intent = _application_intent(current, owner_authorization, authorization.operation_id, files)
        if _completed_application(db, current, files, intent):
            db.rollback()
            return _application_result('ALREADY_APPLIED', current, directory)
        if directory.exists():
            raise ApplicationRecoveryRequired('Existing operation files require explicit recovery review',
                _application_result('UNREFERENCED_OR_CONFLICTING_FILES', current, directory))
        directory.parent.mkdir(parents=True, exist_ok=True)
        directory.mkdir(exist_ok=False)
        stat = directory.stat()
        directory_identity = (stat.st_dev, stat.st_ino)
        _publish_application_file(directory/'intent.json', intent, owned)
        for path, raw in files.items():
            _publish_application_file(path, raw, owned)
        # Files/library can change independently of SQLite's write lock. Check
        # again after publication, while no canonical row has been inserted.
        final, final_authorization = _authorized_application(db, campaign, manifest, creative,
            output_directory, owner_authorization)
        if final != current or final_authorization != authorization:
            raise ValueError('Application authority changed before inserts')
        record = current['campaign_record']
        db.add(Campaign(**record))
        db.flush()
        for row in current['slide_records']:
            db.add(CampaignSlide(**row))
        for kind, path in zip(('creative', 'campaign_reconciliation'), files):
            db.add(CampaignOutput(campaign_id=campaign.id, kind=kind, platform='instagram',
                file_path=str(path), version=1))
        db.flush()
        if not _completed_application(db, current, files, intent):
            raise ValueError('Application read-back is incomplete')
        commit_attempted = True
        db.commit()
        return _application_result('APPLIED', current, directory)
    except BaseException as error:
        try:
            db.rollback()
        except Exception as rollback_error:
            raise ApplicationRecoveryRequired('Rollback outcome unknown; retain operation evidence',
                _application_result('ROLLBACK_OUTCOME_UNKNOWN', preview, directory)) from rollback_error
        if commit_attempted:
            # A commit error can mean failed commit OR lost acknowledgement.
            # Never delete referenced files on an uncertain outcome.
            from sqlalchemy.orm import Session
            try:
                with Session(db.get_bind()) as probe:
                    committed = _completed_application(probe, preview,
                        _application_files(directory, manifest, creative), intent)
            except Exception as probe_error:
                raise ApplicationRecoveryRequired('Commit outcome cannot be established; retain files',
                    _application_result('COMMIT_OUTCOME_UNKNOWN', preview, directory)) from probe_error
            if committed:
                return _application_result('APPLIED_COMMIT_CONFIRMED', preview, directory)
        retained = _cleanup_application_files(owned)
        if directory_identity is not None and not retained:
            try:
                stat = directory.stat()
                if (stat.st_dev, stat.st_ino) == directory_identity:
                    directory.rmdir()  # Empty, attempt-owned directory only.
            except OSError:
                retained = [str(directory)]
        if retained:
            evidence = _application_result('ROLLBACK_FILES_RETAINED', preview, directory)
            evidence['retained_paths'] = retained
            raise ApplicationRecoveryRequired('Rollback complete; retained files need explicit review', evidence) from error
        raise


class ApplicationRecoveryRequired(ValueError):
    def __init__(self, message, evidence):
        super().__init__(message)
        self.evidence = evidence


def _json_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def _application_entry(db, authorization_id):
    if not isinstance(authorization_id, str) or not authorization_id.strip():
        # Retains the original disabled-boundary rejection for boolean flags.
        raise ValueError('Canonical application is disabled in Phase 1 without independently recorded operator authorization')
    if db.new or db.dirty or db.deleted or db.in_transaction():
        raise ValueError('Application requires a fresh dedicated clean transaction')
    engine = db.get_bind()
    if (engine.dialect.name != 'sqlite' or not hasattr(engine, 'url')
            or not engine.url.database or engine.url.database == ':memory:'
            or str(engine.url.database).startswith('file:')
            or not Path(engine.url.database).is_file()):
        raise ValueError('Application requires a dedicated file-backed SQLite engine')


def describe_application(db, campaign, manifest, creative, output_directory):
    """Read-only package for independent operator review, never authorization."""
    from .marketing_claims import load_library
    from .product_asset_selection import resolve_authentic_package_mark_permission
    from .product_creative_eligibility import require_creative_eligibility
    _clean(db)
    if campaign.approved_at is not None or campaign.published_at is not None or campaign.human_review_status not in (None, 'PENDING'):
        raise ValueError('Only an unapproved canonical draft may be applied')
    content = json.loads(creative)
    if set(content) != {'carousel_plan'} or set(content['carousel_plan']) - {'slides', 'narrative_summary'}:
        raise ValueError('Only the complete single-locale canonical creative plan may be applied')
    report = prepare_campaign(db, campaign, manifest, creative)
    library = load_library(campaign.product_id)
    if library.owner_library_review_status != 'APPROVED':
        raise ValueError('Current whole-library authority is not approved')
    permission = resolve_authentic_package_mark_permission(db, campaign, manifest.master_asset_id)
    if permission is None or permission.status != 'APPROVED':
        raise ValueError('Exact current campaign-specific package-mark permission is required')
    engine = db.get_bind()
    database = str(Path(engine.url.database).resolve())
    record = report['campaign_record']
    record.update(channels=['instagram'], content_type='carousel', geography=campaign.geography or 'Brasil',
        angle='', hook='', main_promise='', cta='', template_id=None, strategy_type_id=None,
        triggered_by_event_id=None, research_run_id=None, notes='')
    for slide in report['slide_records']:
        slide['template_id'] = ''
    value = {'version': 1, 'operation': 'CREATE_CANONICAL_TEN_SLIDE_DRAFT',
        'database_identity_sha256': hashlib.sha256(database.encode('utf-8')).hexdigest(),
        'output_directory': str(Path(output_directory).resolve()),
        'campaign_record': record, 'slide_records': report['slide_records'],
        'manifest_sha256': manifest.digest(), 'creative_sha256': manifest.creative_sha256,
        'claim_library_sha256': library.digest(),
        'creative_eligibility': require_creative_eligibility(campaign.product_id),
        'permission_sha256': hashlib.sha256(_json_bytes(permission.model_dump(mode='json'))).hexdigest(),
        'dispositions': {f'pt-BR:instagram:{n}': ('FROZEN_EXTERNAL_REFERENCE' if n<=6 else
            'SELECTED_PENDING_OWNER_REVIEW' if n<=8 else 'DEFERRED_UNRENDERED') for n in range(1,11)}}
    return {**value, 'package_sha256': hashlib.sha256(_json_bytes(value)).hexdigest()}


def _authorized_application(db, campaign, manifest, creative, output_directory, authorization_id):
    from datetime import datetime, timezone
    from ..models import AuditEvent
    from ..schemas.premium_handoff import CanonicalApplicationAuthorization
    _clean(db)
    event = db.get(AuditEvent, authorization_id)
    if (event is None or event.entity_type != 'canonical_campaign_application'
            or event.entity_id != campaign.id or event.action != 'owner_authorized'):
        raise ValueError('Independent operator authorization event is missing or mismatched')
    authorization = CanonicalApplicationAuthorization.model_validate(event.detail)
    if authorization.status != 'AUTHORIZED' or authorization.expires_at <= datetime.now(timezone.utc):
        raise ValueError('Operator authorization is revoked or expired')
    revocations = db.query(AuditEvent).filter_by(entity_type=event.entity_type,
        entity_id=campaign.id, action='owner_authorization_revoked').all()
    if any((row.detail or {}).get('authorization_event_id') == authorization_id for row in revocations):
        raise ValueError('Operator authorization was independently revoked')
    preview = describe_application(db, campaign, manifest, creative, output_directory)
    if authorization.package_sha256 != preview['package_sha256']:
        raise ValueError('Reviewed operation/package authority changed')
    return preview, authorization


def _application_files(directory, manifest, creative):
    return {directory/('creative-'+manifest.creative_sha256+'.json'): creative,
        directory/(manifest.digest()+'.json'): manifest.model_dump_json().encode('utf-8')}


def _application_intent(preview, authorization_id, operation_id, files):
    return _json_bytes({'version': 1, 'state': 'PREPARED_NOT_PROOF_OF_COMMIT',
        'authorization_event_id': authorization_id, 'operation_id': operation_id,
        'package_sha256': preview['package_sha256'], 'campaign_id': preview['campaign_record']['id'],
        'files': {p.name: hashlib.sha256(raw).hexdigest() for p, raw in files.items()}})


def _completed_application(db, preview, files, intent):
    from sqlalchemy import func
    from ..models import Campaign, CampaignSlide, CampaignOutput
    record = preview['campaign_record']
    matches = db.query(Campaign).filter(func.lower(Campaign.display_id) == record['display_id'].lower()).all()
    campaign = db.get(Campaign, record['id'])
    if campaign is None and not matches:
        # Also reject dangling graph records in a database with FK checks disabled.
        if (db.query(CampaignSlide).filter_by(campaign_id=record['id']).count()
                or db.query(CampaignOutput).filter_by(campaign_id=record['id']).count()):
            raise ValueError('Conflicting partial application graph')
        return False
    if campaign is None or len(matches)!=1 or matches[0].id!=record['id']:
        raise ValueError('Campaign display/identity collision')
    if any(getattr(campaign,key)!=value for key,value in record.items()):
        raise ValueError('Existing campaign conflicts with reviewed application')
    slides = db.query(CampaignSlide).filter_by(campaign_id=record['id']).order_by(CampaignSlide.slide_number).all()
    outputs = db.query(CampaignOutput).filter_by(campaign_id=record['id']).all()
    if len(slides)!=10 or len(outputs)!=2:
        raise ValueError('Conflicting partial application graph')
    if any(any(getattr(row,key)!=value for key,value in wanted.items())
            for row,wanted in zip(slides,preview['slide_records'])):
        raise ValueError('Existing slide graph changed')
    paths = {kind:str(path) for kind,path in zip(('creative','campaign_reconciliation'),files)}
    if {o.kind:o.file_path for o in outputs} != paths or any(o.version!=1 or o.platform!='instagram' for o in outputs):
        raise ValueError('Existing output graph changed')
    for path, raw in files.items():
        if path.is_symlink() or path.parent.is_symlink() or path.read_bytes()!=raw:
            raise ValueError('Referenced application output changed')
    intent_path = next(iter(files)).parent/'intent.json'
    if intent_path.is_symlink() or intent_path.read_bytes()!=intent:
        raise ValueError('Application intent receipt changed')
    return True


def _publish_application_file(path, raw, owned):
    import os
    with path.open('xb') as stream:
        stat = os.fstat(stream.fileno())
        owned.append((path, stat.st_dev, stat.st_ino, raw))
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def _cleanup_application_files(owned):
    retained = []
    for path, device, inode, raw in reversed(owned):
        try:
            if not path.exists():
                continue
            stat = path.lstat()
            # Refuse replacement/symlink/tampered content. A failed partial write
            # can be removed only when it is an exact prefix in our original inode.
            if path.is_symlink() or (stat.st_dev,stat.st_ino)!=(device,inode) or not raw.startswith(path.read_bytes()):
                retained.append(str(path))
                continue
            path.unlink()
        except OSError:
            retained.append(str(path))
    return retained


def _application_result(status, preview, directory):
    return {'status':status, 'campaign_id':preview['campaign_record']['id'],
        'package_sha256':preview['package_sha256'], 'record_count':13,
        'operation_directory':str(directory), 'recovery_evidence_path':str(directory/'intent.json'),
        'approvals_adopted':False}


def inspect_application_recovery(db, campaign, manifest, creative, output_directory, *, owner_authorization):
    """Explicit read-only inspection. Never adopts or deletes orphaned files."""
    _application_entry(db, owner_authorization)
    try:
        preview, authorization = _authorized_application(db, campaign, manifest, creative,
            output_directory, owner_authorization)
        directory = Path(preview['output_directory'])/('application-'+authorization.operation_id)
        files = _application_files(directory,manifest,creative)
        complete = _completed_application(db, preview, files,
            _application_intent(preview,owner_authorization,authorization.operation_id,files))
        status = 'COMMITTED' if complete else 'UNREFERENCED_FILES' if directory.exists() else 'NOT_APPLIED'
        return _application_result(status, preview, directory)
    finally:
        db.rollback()


def factual_policy(db, campaign, brief):
    manifest = current_reconciliation(db, campaign)
    if manifest is None:
        return None
    index = brief.slide_number - 1
    if not 0 <= index < 10:
        raise ValueError("Unexpected reconciled slide")
    purpose, ids = PURPOSES[index]
    if brief.slide_role != purpose:
        raise ValueError("Canonical reconciled purpose changed")
    return ids


def require_selected_key(envelope, key):
    if key not in envelope.execution_plans:
        raise ValueError("Frozen or deferred slide is outside selected production scope")
