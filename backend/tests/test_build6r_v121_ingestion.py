"""Isolated SQLite ingestion, human review, versioning and publishing gates."""
import io
import json
from pathlib import Path
import zipfile

import pytest
from PIL import Image

from app.models import Brand, Campaign
from app.schemas.premium_handoff import PremiumReviewRequest
from app.services import premium_ingestion as service
from test_build6r_v121_handoff import handoff


def image_bytes(color="purple", size=(120, 150)):
    stream = io.BytesIO()
    Image.new("RGB", size, color).save(stream, format="PNG")
    return stream.getvalue()


@pytest.fixture
def setup(temp_db, tmp_path):
    db = temp_db.SessionLocal()
    brand = Brand(id="brand", name="Hanna", slug="hanna-japan")
    campaign = Campaign(id="campaign", display_id="HANNA-TEST", brand_id="brand", objective="awareness", angle="", audience="", hook="")
    db.add(brand); db.flush(); db.add(campaign); db.commit()
    h = handoff(tmp_path, campaign)
    root = tmp_path / "output"
    service.prepare_campaign_export(db, campaign, root, handoff=h); db.commit()
    yield db, campaign, h, root
    db.close()


def ingest(setup, key=None, color="purple", data=None, version=None):
    db, c, h, root = setup
    v = service.readiness(db, c, handoff=h)["version"]
    result = service.import_slide(db, c, root, slide_key=key or h.slides[0].key, filename="../finished.png",
        data=data if data is not None else image_bytes(color), expected_version=v if version is None else version, handoff=h)
    db.commit()
    return result


def review(setup, key=None, **changes):
    db, c, h, root = setup
    slide = next(s for s in h.slides if s.key == (key or h.slides[0].key))
    data = dict(expected_version=service.readiness(db, c, handoff=h)["version"], slide_key=slide.key,
        decision="APPROVED", reviewer="Operator", product_visible=True, product_fidelity_confirmed=True,
        observed_copy={s.key: s.text for s in slide.approved_copy})
    data.update(changes)
    result = service.review_slide(db, c, root, PremiumReviewRequest(**data), handoff=h)
    db.commit()
    return result


def test_intake_preserves_provenance_and_never_auto_approves(setup):
    db, c, h, root = setup
    result = ingest(setup)
    record = result["slides"][h.slides[0].key]
    assert record["campaign_id"] == c.id and record["slide_number"] == 1 and record["role"] == "cover"
    assert record["filename"] == "finished.png" and record["dimensions"] == [120, 150]
    assert len(record["sha256"]) == 64 and record["imported_at"]
    assert record["creation_source"] == "external_chatgpt_creative_workflow"
    assert record["approval_status"] == "PENDING_REVIEW" and record["qa_status"] == "NEEDS_HUMAN_REVIEW"
    assert record["qa"]["product_visibility"] == "UNVERIFIED"
    assert not service.readiness(db, c, handoff=h)["CAMPAIGN_CREATIVE_COMPLETE"]
    assert c.approved_at is None and c.status == "REVIEW"


@pytest.mark.parametrize("case", ["duplicate", "dimensions", "corrupt", "key", "oversize", "stale_version"])
def test_intake_failure_paths(setup, case):
    db, c, h, root = setup
    ingest(setup)
    kwargs = {"color": "red"}
    if case == "duplicate": kwargs = {}
    if case == "dimensions": kwargs["data"] = image_bytes(size=(121, 150))
    if case == "corrupt": kwargs["data"] = b"not an image"
    if case == "key": kwargs["key"] = "pt-BR:instagram:99"
    if case == "oversize": kwargs["data"] = b"x" * (20 * 1024 * 1024 + 1)
    if case == "stale_version": kwargs["version"] = 1
    with pytest.raises((ValueError, OSError)):
        ingest(setup, **kwargs)
    db.rollback()
    assert service.readiness(db, c, handoff=h)["APPROVED_SLIDE_COUNT"] == 0


@pytest.mark.parametrize("changes", [dict(product_visible=False), dict(product_fidelity_confirmed=False),
    dict(observed_copy={}), dict(observed_copy={"headline": "Invented claim", "cta": "Conheça"}),
    dict(expected_version=1), dict(reviewer="   ")])
def test_approval_requires_current_product_and_exact_copy_review(setup, changes):
    ingest(setup)
    with pytest.raises(ValueError): review(setup, **changes)


def test_all_required_slides_and_current_qa_needed_for_publishing(setup, monkeypatch):
    db, c, h, root = setup
    monkeypatch.setattr(service, "build_campaign_handoff", lambda *args: h)
    with pytest.raises(ValueError): service.require_publishing_ready(db, c)
    ingest(setup); review(setup)
    first = service.readiness(db, c, handoff=h)
    assert first["APPROVED_SLIDE_COUNT"] == 1 and first["IMPORTED_SLIDE_COUNT"] == 1
    assert not first["CAMPAIGN_CREATIVE_COMPLETE"]
    key = h.slides[1].key
    ingest(setup, key=key, color="green"); review(setup, key=key)
    ready = service.require_publishing_ready(db, c)
    assert ready["status"] == "READY_TO_PUBLISH" and ready["CAMPAIGN_CREATIVE_COMPLETE"]
    assert ready["APPROVED_SLIDE_COUNT"] == 2 and ready["REJECTED_SLIDE_COUNT"] == 0
    # Replacement cannot inherit approval from a different file.
    ingest(setup, color="orange")
    assert service.readiness(db, c, handoff=h)["APPROVED_SLIDE_COUNT"] == 1
    with pytest.raises(ValueError): service.require_publishing_ready(db, c)


@pytest.mark.parametrize("changes", [dict(feedback=""), dict(feedback_codes=())])
def test_rejection_requires_actionable_structured_feedback(setup, changes):
    ingest(setup)
    fields = dict(decision="REJECTED", feedback_codes=("composition",), feedback="Integrate the product into the scene")
    fields.update(changes)
    with pytest.raises(ValueError): review(setup, **fields)


def test_rejection_and_single_slide_revision_keep_original_and_canonical_copy(setup):
    db, c, h, root = setup
    ingest(setup)
    review(setup, decision="REJECTED", feedback_codes=("composition", "hierarchy"), feedback="Integrate product and hierarchy")
    state = service.readiness(db, c, handoff=h)
    assert state["REJECTED_SLIDE_COUNT"] == 1 and state["APPROVED_SLIDE_COUNT"] == 0
    archive = service.export_revision(db, c, root, h.slides[0].key, handoff=h)
    with zipfile.ZipFile(archive) as z:
        public = json.loads(z.read("HANNA_CAMPAIGN_HANDOFF.json"))
        assert public["revision"]["slide_key"] == h.slides[0].key
        assert public["revision"]["requested_visual_changes"] == "Integrate product and hierarchy"
        assert public["slides"][0]["approved_copy"] == h.slides[0].model_dump(mode="json")["approved_copy"]
        assert public["approved_facts_json"] == h.approved_facts_json
        assert z.read("REJECTED_ORIGINAL.png") == image_bytes()
        assert "only the rejected slide" in z.read("CHATGPT_READY_INSTRUCTION.txt").decode()


def test_revision_requires_rejection(setup):
    db, c, h, root = setup
    ingest(setup)
    with pytest.raises(ValueError): service.export_revision(db, c, root, h.slides[0].key, handoff=h)


def test_changed_handoff_invalidates_qa_and_archives_prior_provenance(setup):
    db, c, h, root = setup
    ingest(setup); review(setup)
    changed = h.model_copy(update={"concept": "New approved theme"})
    assert service.readiness(db, c, handoff=changed)["APPROVED_SLIDE_COUNT"] == 0
    with pytest.raises(ValueError, match="changed"):
        service.import_slide(db, c, root, slide_key=h.slides[0].key, filename="x.png", data=image_bytes("red"), expected_version=3, handoff=changed)
    _, saved = service.prepare_campaign_export(db, c, root, handoff=changed)
    db.commit()
    assert not saved["slides"] and len(saved["history"]) == 1
    assert saved["history"][0]["reviewer"] == "Operator"


def test_imported_image_mutation_invalidates_current_review(setup):
    db, c, h, root = setup
    result = ingest(setup); review(setup)
    Path(result["slides"][h.slides[0].key]["file_path"]).write_bytes(image_bytes("red"))
    assert service.readiness(db, c, handoff=h)["APPROVED_SLIDE_COUNT"] == 0
    with pytest.raises(ValueError, match="changed"): review(setup)


def test_state_file_tampering_cannot_grant_approval(setup):
    db, c, h, root = setup
    ingest(setup)
    row, state = service._read_state(db, c)
    state["slides"][h.slides[0].key]["approval_status"] = "APPROVED"
    Path(row.file_path).write_text(json.dumps(state))
    with pytest.raises(ValueError, match="state bytes changed"):
        service.readiness(db, c, handoff=h)


def test_operator_api_exports_imports_previews_reviews_and_revisions(setup, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api import campaigns as api
    from app.services import premium_handoff
    db, c, h, root = setup
    monkeypatch.setattr(premium_handoff, "build_campaign_handoff", lambda *args: h)
    monkeypatch.setattr(service, "build_campaign_handoff", lambda *args: h)
    monkeypatch.setattr(api.settings_store, "get_effective_settings", lambda *args: {"output_root": str(root)})
    app = FastAPI(); app.include_router(api.router)
    app.dependency_overrides[api.get_db] = lambda: db
    base = "/api/campaigns/campaign/premium-creative"
    with TestClient(app) as client:
        response = client.post(base + "/export")
        assert response.status_code == 200 and zipfile.is_zipfile(io.BytesIO(response.content))
        state = client.get(base).json()
        assert state["enabled"] and len(state["briefs"]) == 2
        version = state["readiness"]["version"]
        response = client.post(base + "/import", data={"slide_key": h.slides[0].key, "expected_version": version},
                               files={"image": ("completed.png", image_bytes(), "image/png")})
        assert response.status_code == 200, response.text
        preview = client.get(base + "/preview", params={"slide_key": h.slides[0].key})
        assert preview.status_code == 200 and preview.content == image_bytes()
        version = response.json()["version"]
        request = dict(slide_key=h.slides[0].key, expected_version=version, reviewer="Operator", decision="APPROVED")
        assert client.post(base + "/review", json=request).status_code == 409
        request.update(decision="REJECTED", feedback_codes=["composition"], feedback="Improve hierarchy")
        assert client.post(base + "/review", json=request).status_code == 200
        revision = client.post(base + "/revision", params={"slide_key": h.slides[0].key})
        assert revision.status_code == 200 and zipfile.is_zipfile(io.BytesIO(revision.content))
        assert client.get(base).json()["readiness"]["REJECTED_SLIDE_COUNT"] == 1
