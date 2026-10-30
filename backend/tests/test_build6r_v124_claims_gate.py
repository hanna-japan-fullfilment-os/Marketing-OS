"""Zero-provider claims, translation, qualification and real export-gate tests."""
import json
import zipfile
from types import SimpleNamespace
import pytest
from app.schemas.creative_bridge import CopyField
from app.schemas.marketing_claims import MarketingClaim, ClaimLibrary
from app.services import marketing_claims as gate
from app.services.premium_handoff import assemble_handoff, export_handoff
from test_build6r_v101_creative_package import package

PRODUCT = "a5ea2272a1f89d743c089461bb2fb50f"


@pytest.fixture
def library():
    return gate.load_library(PRODUCT)


@pytest.fixture
def owner_reviewed(monkeypatch, library):
    reviewed = library.model_copy(update={"owner_library_review_status": "APPROVED",
        "brazil_market_review_status": "CLEARED", "brazil_clearance_evidence": "Isolated test-only assessment fixture"})
    def exact(product_id):
        if product_id != PRODUCT:
            raise ValueError("Wrong product")
        return reviewed
    monkeypatch.setattr(gate, "load_library", exact)
    return reviewed


def draft(tmp_path, words=None):
    p = package(tmp_path, product_id=PRODUCT, product_name="LuLuLun Hydra EX Mask 7 Sheets",
        approved_copy=tuple(CopyField(key=k, text=v) for k, v in (words or {"headline": "Hidratação", "body": "Ajuda a manter a pele hidratada."}).items()), required_cta="")
    campaign = SimpleNamespace(id="campaign", objective="awareness", angle="", hook="", audience="Brazil")
    return assemble_handoff(campaign, [(1, p)])


def test_exact_sku_primary_provenance_and_research_complete(library):
    assert library.jan == "4580794010660" and "7 sheets" in library.variant and "EX 1FS" in library.variant
    assert set(library.research_categories) == gate.RESEARCH_CATEGORIES and all(library.research_categories.values())
    assert len(library.claims) == 64 and len({c.claim_id for c in library.claims}) == 64
    for c in library.claims:
        assert c.source_language_text_or_meaning and c.source_publisher and c.source_reference and c.notes
        assert c.benefit_priority in {"PRIMARY", "SECONDARY", "SUPPORTING"}
    assert len({i for c in library.claims for i in c.legacy_claim_ids}) == 8
    with pytest.raises(ValueError): gate.load_library("wrong-variant")


def test_strong_primary_evidence_and_pt_br_wording_allowed(library):
    result = gate.resolve_copy(library, (CopyField(key="body", text="Ajuda a manter a pele hidratada."),))
    assert result == {"body": "ex-hydration"}
    assert next(c for c in library.claims if c.claim_id == "ex-hydration").claim_class == "APPROVED_DIRECT"


@pytest.mark.parametrize("text", ["Hidratação total garantida", "Makes your skin white", "Ajuda a hidratar imediatamente.", "Pode ser usado como medicamento."])
def test_unapproved_translation_or_paraphrase_never_enters_copy(library, text):
    with pytest.raises(ValueError): gate.resolve_copy(library, (CopyField(key="body", text=text),))


@pytest.mark.parametrize("text", ["Regeneração celular", "Renovação celular", "Trata melasma", "Repara a barreira", "Clareia a pele", "Estimula produção de colágeno", "Whitening", "Cicatriza a pele", "Ação farmacológica"])
def test_therapeutic_and_unsupported_language_blocked(library, text):
    with pytest.raises(ValueError): gate.resolve_copy(library, (CopyField(key="body", text=text),))


@pytest.mark.parametrize("text", ["97% das usuárias", "Nº1", "Bestseller", "Clinicamente comprovado", "Efeito imediato", "3 vezes mais hidratação"])
def test_unsupported_statistic_and_comparison_blocked(library, text):
    with pytest.raises(ValueError): gate.resolve_copy(library, (CopyField(key="body", text=text),))


@pytest.mark.parametrize("text", ["Ceramidas reparam a barreira", "EGF regenera células", "Colágeno estimula a produção de colágeno"])
def test_ingredient_presence_does_not_prove_efficacy(library, text):
    with pytest.raises(ValueError): gate.resolve_copy(library, (CopyField(key="body", text=text),))
    assert next(c for c in library.claims if c.claim_id == "ex-collagen").claim_class == "FACT_ONLY"


def test_incomplete_provenance_or_review_cannot_be_approved(library):
    c = next(c for c in library.claims if c.claim_id == "ex-hydration")
    for changes in ({"source_reference": ""}, {"language_review": "PENDING"}, {"source_type": "REGULATOR"},
                    {"review_status": "NEEDS_REVIEW"}, {"approved_pt_br_wording": {}}):
        with pytest.raises(ValueError): MarketingClaim.model_validate({**c.model_dump(), **changes})


def test_library_filters_unresolved_research(library):
    approved = [c for group in gate.approved_library(library).values() for c in group]
    assert approved and all(c["claim_class"] in gate.USABLE for c in approved)
    assert not any(c["claim_id"].startswith(("review-", "blocked-")) for c in approved)
    assert any(c.claim_id == "review-elasticity" and c.claim_class == "NEEDS_REVIEW" for c in library.claims)


def test_owner_review_pending_blocks_creative_export(tmp_path, library):
    assert library.owner_library_review_status == "PENDING"
    with pytest.raises(ValueError, match="owner review"): gate.bind_handoff(draft(tmp_path))
    with pytest.raises(ValueError): export_handoff(draft(tmp_path), tmp_path / "not-authorized")
    assert not (tmp_path / "not-authorized").exists()


def test_owner_approval_alone_cannot_clear_product_regulatory_hold(tmp_path, library, monkeypatch):
    held = library.model_copy(update={"owner_library_review_status": "APPROVED"})
    monkeypatch.setattr(gate, "load_library", lambda product_id: held)
    with pytest.raises(ValueError, match="regulatory assessment"):
        gate.bind_handoff(draft(tmp_path))
    assert next(c for c in library.claims if c.claim_id == "ex-exosomes").claim_class == "NEEDS_REVIEW"


def test_market_clearance_without_assessment_evidence_is_invalid(library):
    with pytest.raises(ValueError, match="assessment"):
        ClaimLibrary.model_validate({**library.model_dump(), "brazil_market_review_status": "CLEARED"})


def test_missing_claim_ids_block_creative_gate(tmp_path, owner_reviewed):
    h = draft(tmp_path)
    with pytest.raises(ValueError, match="lacks approved claim IDs"):
        gate.validate_brief(owner_reviewed, h.slides[0])


def test_valid_benefit_brief_and_export_contract(tmp_path, owner_reviewed):
    h = gate.bind_handoff(draft(tmp_path))
    b = h.slides[0]
    assert b.creative_brief_status == "CREATIVE_READY" and b.benefit_hierarchy == ("ex-hydration",)
    assert b.approved_claim_ids == {"headline": "ex-hydration", "body": "ex-hydration"}
    archive = export_handoff(h, tmp_path / "export")
    with zipfile.ZipFile(archive) as z:
        public = json.loads(z.read("HANNA_CAMPAIGN_HANDOFF.json"))
        assert public["creative_model_claim_invention_allowed"] is False
        assert "regeneração celular" in public["slides"][0]["prohibited_elements"]
        assert public["slides"][0]["approved_claim_ids"] == dict(b.approved_claim_ids)
        assert "mandatory_qualifier" in z.read("CHATGPT_READY_INSTRUCTION.txt").decode()
        assert not any(c["claim_class"] == "NEEDS_REVIEW" for g in public["approved_claim_library"].values() for c in g)


def test_qualified_heading_cannot_drop_visible_qualifier(tmp_path, owner_reviewed):
    with pytest.raises(ValueError, match="qualification missing"):
        gate.bind_handoff(draft(tmp_path, {"headline": "Luminosidade"}))
    good = gate.bind_handoff(draft(tmp_path, {"headline": "Luminosidade", "body": "Ajuda a prevenir a aparência opaca causada pelo ressecamento."}))
    assert good.slides[0].mandatory_qualifiers == {"ex-radiance": "causada pelo ressecamento"}
    b = good.slides[0].model_copy(update={"mandatory_qualifiers": {}})
    with pytest.raises(ValueError): gate.validate_brief(owner_reviewed, b)


def test_usage_only_brief_fails_if_benefits_available(tmp_path, owner_reviewed):
    with pytest.raises(ValueError, match="usage/fact-only"):
        gate.bind_handoff(draft(tmp_path, {"headline": "Saiba mais", "body": "Pode ser usada pela manhã e à noite."}))


@pytest.mark.parametrize("change", ["binding", "hierarchy", "library_sha", "status"])
def test_forged_or_stale_ready_contract_fails(tmp_path, owner_reviewed, change):
    h = gate.bind_handoff(draft(tmp_path)); b = h.slides[0]
    updates = {"binding": {"approved_claim_ids": {"headline": "ex-collagen", "body": "ex-collagen"}},
        "hierarchy": {"benefit_hierarchy": ()}, "library_sha": {"claim_library_sha256": "changed"},
        "status": {"creative_brief_status": "DRAFT"}}[change]
    with pytest.raises(ValueError): gate.require_ready(h.model_copy(update={"slides": (b.model_copy(update=updates),)}))


def test_proposed_five_slide_plan_has_ids_qualifiers_and_hierarchy(library):
    plans = gate.proposed_content_plan(library)
    assert [p["slide_number"] for p in plans] == [2, 3, 4, 5, 6]
    for p in plans:
        assert p["owner_review_status"] == "PENDING" and not p["campaign_data_mutated"]
        assert p["approved_claim_ids"] and p["benefit_hierarchy"] and p["prohibited_wording"]
        assert gate.resolve_copy(library, tuple(CopyField(key=k, text=v) for k, v in p["approved_copy"].items())) == p["approved_claim_ids"]
    assert "causada pelo ressecamento" in plans[0]["approved_copy"]["radiance.body"]
