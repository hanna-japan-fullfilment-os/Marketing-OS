from __future__ import annotations

from app.services.fingerprint import (
    NOVELTY_EXACT_REPEAT,
    NOVELTY_FRESH,
    NOVELTY_SIMILAR_BUT_ACCEPTABLE,
    NOVELTY_TOO_SIMILAR,
    classify_novelty,
    hamming_distance,
    jaccard_similarity,
    text_hash,
)


def test_text_hash_is_stable_and_case_insensitive():
    a = text_hash("3 motivos", "para experimentar")
    b = text_hash("3 MOTIVOS", "Para Experimentar")
    assert a == b


def test_text_hash_changes_with_content():
    a = text_hash("3 motivos para experimentar")
    b = text_hash("como funciona em 30 minutos")
    assert a != b


def test_jaccard_similarity_identical_text_is_1():
    assert jaccard_similarity("hello world", "hello world") == 1.0


def test_jaccard_similarity_disjoint_text_is_0():
    assert jaccard_similarity("sunscreen skincare", "car parts engine") == 0.0


def test_jaccard_similarity_partial_overlap():
    score = jaccard_similarity("new sunscreen for summer", "new sunscreen for winter")
    assert 0.3 < score < 0.8


def test_hamming_distance_identical_hashes_is_zero():
    assert hamming_distance("8000000000000000", "8000000000000000") == 0


def test_hamming_distance_different_hashes_positive():
    assert hamming_distance("8000000000000000", "0000000000000000") == 1


def test_classify_novelty_exact_repeat():
    prior = [{"campaign_id": "c1", "text_hash": text_hash("same copy"), "summary": "same copy"}]
    result = classify_novelty(
        candidate_text_hash=text_hash("same copy"),
        candidate_summary="same copy",
        prior_fingerprints=prior,
    )
    assert result.classification == NOVELTY_EXACT_REPEAT
    assert result.closest_campaign_id == "c1"


def test_classify_novelty_fresh_when_no_priors():
    result = classify_novelty(candidate_text_hash=text_hash("brand new"), candidate_summary="brand new", prior_fingerprints=[])
    assert result.classification == NOVELTY_FRESH


def test_classify_novelty_too_similar_above_threshold():
    prior = [{
        "campaign_id": "c1",
        "text_hash": text_hash("different hash"),
        "summary": "3 reasons to try our new sunscreen this summer",
    }]
    result = classify_novelty(
        candidate_text_hash=text_hash("candidate"),
        candidate_summary="3 reasons to try our new sunscreen this season",
        prior_fingerprints=prior,
        too_similar_threshold=50,
        acceptable_threshold=20,
    )
    assert result.classification in (NOVELTY_TOO_SIMILAR, NOVELTY_SIMILAR_BUT_ACCEPTABLE)
