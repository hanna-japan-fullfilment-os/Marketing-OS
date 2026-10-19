from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import (
    Brand,
    Product,
    ProductClaimEvidence,
    ResearchInsight,
    ResearchRun,
    ResearchSource,
    VerifiedProductFact,
)
from app.schemas.claim_evidence import (
    ProductClaimEvidenceCreate,
    ProductClaimRejection,
    ProductClaimVerification,
)
from app.services.claim_evidence import (
    ClaimEvidenceError,
    create_claim_candidate,
    list_verified_marketing_claims,
    promote_verified_claim,
    reject_claim_evidence,
    verify_claim_evidence,
)


@pytest.fixture()
def session():
    engine = create_engine(
        "sqlite:///:memory:"
    )

    Base.metadata.create_all(
        bind=engine
    )

    SessionLocal = sessionmaker(
        bind=engine
    )

    db = SessionLocal()

    try:
        yield db
    finally:
        db.close()
        engine.dispose()


def _seed(session):
    brand = Brand(
        name="Hanna Japan",
        slug="hanna-japan-v345",
    )

    session.add(brand)
    session.flush()

    product = Product(
        brand_id=brand.id,
        name="LuLuLun Hydra EX",
        slug="lululun-hydra-ex-v345",
        notes="",
    )

    session.add(product)
    session.flush()

    run = ResearchRun(
        brand_id=brand.id,
        product_id=product.id,
        query_context={
            "purpose": "product_claim_verification"
        },
        ttl_kind="category",
    )

    session.add(run)
    session.flush()

    source = ResearchSource(
        research_run_id=run.id,
        url=(
            "https://example.invalid/"
            "official/lululun-hydra-ex"
        ),
        source_title="Official product evidence",
        publisher="Official manufacturer",
        query="LuLuLun Hydra EX",
        source_type="official",
        geography="Japan",
        relevance_score=1.0,
    )

    session.add(source)
    session.flush()

    insight = ResearchInsight(
        research_run_id=run.id,
        statement=(
            "The exact product page supports "
            "the candidate claim."
        ),
        source_ids=[source.id],
        confidence=1.0,
        freshness="current",
        category="product_fact",
        recommended_implication="",
    )

    session.add(insight)

    facts = VerifiedProductFact(
        product_id=product.id,
        verified_claims=[
            "Mﾃ｡scara facial 窶｢ 7 folhas"
        ],
        prohibited_claims=[],
        source_references=[
            "existing-canonical-source"
        ],
        confidence=1.0,
        provenance="existing_canonical_provenance",
    )

    session.add(facts)
    session.commit()

    return {
        "brand": brand,
        "product": product,
        "run": run,
        "source": source,
        "insight": insight,
        "facts": facts,
    }


def _candidate(
    seeded,
    *,
    claim_text="150 mL de essﾃｪncia",
    claim_type="feature",
    territory="",
    evidence_period="",
):
    return ProductClaimEvidenceCreate(
        product_id=(
            seeded["product"].id
        ),
        research_run_id=(
            seeded["run"].id
        ),
        research_insight_id=(
            seeded["insight"].id
        ),
        claim_text=claim_text,
        claim_type=claim_type,
        source_ids=[
            seeded["source"].id
        ],
        source_excerpt=(
            "The exact official source supports "
            "this exact product claim."
        ),
        source_scope={
            "exact_product_match": True,
            "claim_supported": True,
        },
        territory=territory,
        evidence_period=evidence_period,
    )


def _verification(
    seeded,
    *,
    strength="official_primary",
    marketing_eligible=True,
    source_ids=None,
    footnote="",
    expires_at=None,
):
    return ProductClaimVerification(
        evidence_strength=strength,
        marketing_eligible=marketing_eligible,
        source_ids=(
            source_ids
            if source_ids is not None
            else [
                seeded["source"].id
            ]
        ),
        source_excerpt=(
            "The exact official source supports "
            "this exact product claim."
        ),
        source_scope={
            "exact_product_match": True,
            "claim_supported": True,
        },
        footnote=footnote,
        verification_method=(
            "source-linked exact-product review"
        ),
        verifier="build6r-v345-test",
        expires_at=expires_at,
    )


def test_candidate_creation_is_scope_idempotent(
    session,
):
    seeded = _seed(session)

    payload = _candidate(
        seeded
    )

    first = create_claim_candidate(
        session,
        payload,
    )

    second = create_claim_candidate(
        session,
        payload,
    )

    assert first.id == second.id

    assert (
        session.query(
            ProductClaimEvidence
        ).count()
        == 1
    )

    assert first.status == "candidate"
    assert first.marketing_eligible is False


def test_claim_scope_changes_identity(
    session,
):
    seeded = _seed(session)

    japan = create_claim_candidate(
        session,
        _candidate(
            seeded,
            territory="Japan",
        ),
    )

    brazil = create_claim_candidate(
        session,
        _candidate(
            seeded,
            territory="Brazil",
        ),
    )

    assert japan.id != brazil.id
    assert japan.claim_key != brazil.claim_key


def test_candidate_cannot_be_promoted(
    session,
):
    seeded = _seed(session)

    evidence = create_claim_candidate(
        session,
        _candidate(seeded),
    )

    with pytest.raises(
        ClaimEvidenceError,
        match="VERIFIED",
    ):
        promote_verified_claim(
            session,
            evidence.id,
        )


def test_verified_marketing_claim_promotes_flat_string_once(
    session,
):
    seeded = _seed(session)

    evidence = create_claim_candidate(
        session,
        _candidate(seeded),
    )

    evidence = verify_claim_evidence(
        session,
        evidence.id,
        _verification(seeded),
    )

    assert evidence.status == "verified"
    assert evidence.marketing_eligible is True

    original_provenance = (
        seeded["facts"].provenance
    )

    promote_verified_claim(
        session,
        evidence.id,
    )

    promote_verified_claim(
        session,
        evidence.id,
    )

    session.flush()

    facts = (
        session.query(
            VerifiedProductFact
        )
        .filter(
            VerifiedProductFact.product_id
            == seeded["product"].id
        )
        .one()
    )

    assert all(
        isinstance(value, str)
        for value
        in facts.verified_claims
    )

    assert (
        facts.verified_claims.count(
            "150 mL de essﾃｪncia"
        )
        == 1
    )

    assert (
        "product_claim_evidence:"
        + evidence.id
        in facts.source_references
    )

    assert (
        facts.provenance
        == original_provenance
    )

    assert evidence.promoted_at is not None


def test_verification_rejects_source_from_other_run(
    session,
):
    seeded = _seed(session)

    other_run = ResearchRun(
        brand_id=seeded["brand"].id,
        product_id=seeded["product"].id,
        query_context={},
        ttl_kind="category",
    )

    session.add(other_run)
    session.flush()

    other_source = ResearchSource(
        research_run_id=other_run.id,
        url=(
            "https://example.invalid/"
            "other-source"
        ),
        source_title="Other source",
        publisher="Other publisher",
        query="other",
        source_type="official",
        geography="Japan",
        relevance_score=1.0,
    )

    session.add(other_source)
    session.flush()

    evidence = create_claim_candidate(
        session,
        _candidate(seeded),
    )

    with pytest.raises(
        ClaimEvidenceError,
        match="different research run",
    ):
        verify_claim_evidence(
            session,
            evidence.id,
            _verification(
                seeded,
                source_ids=[
                    other_source.id
                ],
            ),
        )


def test_sensitive_claim_requires_strong_evidence_and_footnote(
    session,
):
    seeded = _seed(session)

    evidence = create_claim_candidate(
        session,
        _candidate(
            seeded,
            claim_text=(
                "Nﾂｺ 1 em ranking do perﾃｭodo"
            ),
            claim_type="ranking",
            territory="Japan",
            evidence_period="2026",
        ),
    )

    with pytest.raises(
        ClaimEvidenceError,
        match="official_primary",
    ):
        verify_claim_evidence(
            session,
            evidence.id,
            _verification(
                seeded,
                strength="owner_confirmed",
                marketing_eligible=True,
                footnote="Ranking 2026.",
            ),
        )

    assert evidence.status == "candidate"
    assert evidence.evidence_strength == ""
    assert evidence.marketing_eligible is False
    assert evidence.footnote == ""
    assert evidence.verified_at is None
    assert (
        session.is_modified(
            evidence,
            include_collections=True,
        )
        is False
    )

    with pytest.raises(
        ClaimEvidenceError,
        match="footnote",
    ):
        verify_claim_evidence(
            session,
            evidence.id,
            _verification(
                seeded,
                strength="official_primary",
                marketing_eligible=True,
                footnote="",
            ),
        )

    assert evidence.status == "candidate"
    assert evidence.evidence_strength == ""
    assert evidence.marketing_eligible is False
    assert evidence.footnote == ""
    assert evidence.verified_at is None
    assert (
        session.is_modified(
            evidence,
            include_collections=True,
        )
        is False
    )


def test_rejected_claim_can_never_promote(
    session,
):
    seeded = _seed(session)

    evidence = create_claim_candidate(
        session,
        _candidate(seeded),
    )

    reject_claim_evidence(
        session,
        evidence.id,
        ProductClaimRejection(
            rejection_reason=(
                "Source does not support "
                "the marketing interpretation."
            ),
            verifier="build6r-v345-test",
        ),
    )

    assert evidence.status == "rejected"

    with pytest.raises(
        ClaimEvidenceError,
        match="VERIFIED",
    ):
        promote_verified_claim(
            session,
            evidence.id,
        )


def test_expired_evidence_fails_closed_and_listing_excludes_expired(
    session,
):
    seeded = _seed(session)

    expired_candidate = (
        create_claim_candidate(
            session,
            _candidate(
                seeded,
                claim_text="Claim with expired evidence",
            ),
        )
    )

    with pytest.raises(
        ClaimEvidenceError,
        match="Expired",
    ):
        verify_claim_evidence(
            session,
            expired_candidate.id,
            _verification(
                seeded,
                expires_at=(
                    datetime.now(
                        timezone.utc
                    )
                    - timedelta(days=1)
                ),
            ),
        )

    session.rollback()

    active = create_claim_candidate(
        session,
        _candidate(
            seeded,
            claim_text="Active verified claim",
        ),
    )

    active = verify_claim_evidence(
        session,
        active.id,
        _verification(seeded),
    )

    assert active in (
        list_verified_marketing_claims(
            session,
            product_id=(
                seeded["product"].id
            ),
        )
    )

    active.expires_at = (
        datetime.now(
            timezone.utc
        )
        - timedelta(days=1)
    )

    session.flush()

    assert active not in (
        list_verified_marketing_claims(
            session,
            product_id=(
                seeded["product"].id
            ),
        )
    )
