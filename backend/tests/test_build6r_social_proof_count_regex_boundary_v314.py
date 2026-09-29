"""BUILD6R_SOCIAL_PROOF_COUNT_REGEX_BOUNDARY_V3_14.

Deterministic regression coverage for the V3.14 invariant repair.

The social-proof detector is for numeric proof such as
"10,000 customers" or "50k followers". Punctuation alone must
never satisfy the numeric prefix.

No network, provider, database, image, or live dependency exists here.
"""

from pathlib import Path

import pytest

from app.services import claims_audit as claims_audit_module


NEGATIVE_CASES = (
    "editorial, review",
    "layout. reviews",
    "neutral, customers",
    "composition. followers",
)

POSITIVE_CASES = (
    ("10,000 customers", "10,000 customers"),
    ("50k followers", "50k followers"),
    ("1,200 reviews", "1,200 reviews"),
    ("250 users", "250 users"),
)


@pytest.mark.parametrize("text", NEGATIVE_CASES)
def test_v314_punctuation_only_prefix_is_not_social_proof_count(
    text: str,
) -> None:
    match = (
        claims_audit_module
        ._SOCIAL_PROOF_COUNT_RE
        .search(text)
    )

    assert match is None


@pytest.mark.parametrize(
    ("text", "expected"),
    POSITIVE_CASES,
)
def test_v314_genuine_numeric_social_proof_is_still_detected(
    text: str,
    expected: str,
) -> None:
    match = (
        claims_audit_module
        ._SOCIAL_PROOF_COUNT_RE
        .search(text)
    )

    assert match is not None
    assert match.group(0) == expected


def test_v314_regex_contract_requires_leading_digit() -> None:
    pattern = (
        claims_audit_module
        ._SOCIAL_PROOF_COUNT_RE
        .pattern
    )

    assert r"\b\d[\d,.]{0,8}" in pattern
    assert r"\b[\d,.]{1,9}" not in pattern


def test_v314_claims_source_has_no_live_phrase_whitelist() -> None:
    source_path = Path(
        claims_audit_module.__file__
    )

    source = source_path.read_text(
        encoding="utf-8",
    )

    for phrase in NEGATIVE_CASES:
        assert phrase not in source


def test_v314_genuine_numeric_social_proof_still_fails_closed_without_evidence() -> None:
    finding = claims_audit_module._evaluate(
        claim_text="10,000 customers",
        claim_category="social_proof_count",
        source_field="v314.test",
        verified_text="",
        brand_text="",
    )

    status = getattr(
        finding,
        "evidence_status",
        None,
    )

    status_value = getattr(
        status,
        "value",
        status,
    )

    assert (
        str(status_value)
        .strip()
        .upper()
        .endswith("UNSUPPORTED")
    )
