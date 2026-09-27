"""Structured contracts for the BUILD 6 FINAL REPAIR unsupported-claim
ENFORCEMENT gate (`services/claims_audit.py`).

`ClaimFinding`/`ClaimAuditResult` are deliberately NOT the output of an AI
call the way `schemas/qa.py`'s dimensions are — the `evidence_status`/
`allowed_source` verdict on every finding is always computed by this app's
own code, comparing a detected claim against real persisted evidence
(`VerifiedProductFacts` + owner-confirmed brand notes). A model is never
trusted to self-report "yes, this is supported" — see `services/
claims_audit.py`'s module docstring for the concrete defect (the pre-repair
`scripts/run_live_acceptance.py::_check_unsupported_claims` only checked
`brand.disallowed_terms` and was handed rendered FILE PATHS, not real copy —
`unsupported_claim_flags=[]` on every real case despite fabricated claims
reaching the generated text) that made a real, code-enforced evidence check
necessary rather than another prompt instruction alone.

`CandidateClaimExtraction`/`CandidateClaimExtractionResult` ARE a real AI
Protocol response schema — the OPTIONAL recall-only augmentation pass that
finds candidate claim phrases the fixed pattern list might miss. Even its
output is independently evidence-checked by this app's own code before ever
becoming a `ClaimFinding` — a model can add recall, it can never itself grant
a pass.
"""
from __future__ import annotations

from pydantic import BaseModel


class ClaimFinding(BaseModel):
    claim_text: str
    claim_category: str
    source_field: str
    evidence_status: str  # "SUPPORTED" | "UNSUPPORTED"
    allowed_source: str  # "verified_product_facts" | "owner_confirmed_brand_facts" | "" (unsupported)
    reason: str


class ClaimAuditResult(BaseModel):
    findings: list[ClaimFinding] = []

    @property
    def unsupported_findings(self) -> list[ClaimFinding]:
        return [f for f in self.findings if f.evidence_status != "SUPPORTED"]

    @property
    def passed(self) -> bool:
        return not self.unsupported_findings


class CandidateClaimExtraction(BaseModel):
    """One AI-extracted candidate factual assertion — deliberately just the
    RAW phrase and the model's own best-guess category, never an evidence
    verdict (see this module's own docstring above).
    """

    claim_text: str
    claim_category: str = "other"


class CandidateClaimExtractionResult(BaseModel):
    claims: list[CandidateClaimExtraction] = []
