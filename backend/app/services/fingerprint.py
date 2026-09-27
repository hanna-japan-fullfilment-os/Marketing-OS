"""Duplicate / novelty detection utilities (brief sections 16, 50, 51).

Kept dependency-light and deterministic on purpose: no external vector DB, no network
calls. Everything here operates on data already in the database.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

NOVELTY_EXACT_REPEAT = "EXACT_REPEAT"
NOVELTY_TOO_SIMILAR = "TOO_SIMILAR"
NOVELTY_SIMILAR_BUT_ACCEPTABLE = "SIMILAR_BUT_ACCEPTABLE"
NOVELTY_FRESH = "FRESH"

_WORD_RE = re.compile(r"[a-zA-ZÀ-ÿ0-9']+")


def normalize_text(*parts: str) -> str:
    joined = " ".join(p.strip().lower() for p in parts if p)
    joined = re.sub(r"\s+", " ", joined)
    return joined.strip()


def text_hash(*parts: str) -> str:
    return hashlib.sha256(normalize_text(*parts).encode("utf-8")).hexdigest()


def tokenize(text: str) -> set[str]:
    return set(_WORD_RE.findall(text.lower()))


def jaccard_similarity(a: str, b: str) -> float:
    """0..1 token-set similarity. Cheap, deterministic, no embeddings dependency."""
    tokens_a, tokens_b = tokenize(a), tokenize(b)
    if not tokens_a and not tokens_b:
        return 1.0
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = len(tokens_a & tokens_b)
    union = len(tokens_a | tokens_b)
    return intersection / union if union else 0.0


def hamming_distance(hex_a: str, hex_b: str) -> int:
    """Hamming distance between two equal-length perceptual hashes (hex strings)."""
    if not hex_a or not hex_b or len(hex_a) != len(hex_b):
        return max(len(hex_a or ""), len(hex_b or "")) * 4  # treat as maximally different
    int_a, int_b = int(hex_a, 16), int(hex_b, 16)
    return bin(int_a ^ int_b).count("1")


@dataclass
class NoveltyResult:
    classification: str
    similarity_score: float  # 0-100, higher = more similar to the closest prior campaign
    closest_campaign_id: str | None
    explanation: str


def classify_novelty(
    *,
    candidate_text_hash: str,
    candidate_summary: str,
    prior_fingerprints: list[dict],
    too_similar_threshold: int = 75,
    acceptable_threshold: int = 45,
) -> NoveltyResult:
    """prior_fingerprints: list of {"campaign_id", "text_hash", "summary"} dicts for the
    same category/product scope. Pure function — no DB access — so it's trivially
    testable and reusable from the orchestrator.
    """
    best_score = 0.0
    best_id: str | None = None
    for prior in prior_fingerprints:
        if prior["text_hash"] == candidate_text_hash:
            return NoveltyResult(
                classification=NOVELTY_EXACT_REPEAT,
                similarity_score=100.0,
                closest_campaign_id=prior["campaign_id"],
                explanation="Identical normalized copy to a previous campaign.",
            )
        score = jaccard_similarity(candidate_summary, prior.get("summary", "")) * 100
        if score > best_score:
            best_score = score
            best_id = prior["campaign_id"]

    if best_score >= too_similar_threshold:
        classification = NOVELTY_TOO_SIMILAR
    elif best_score >= acceptable_threshold:
        classification = NOVELTY_SIMILAR_BUT_ACCEPTABLE
    else:
        classification = NOVELTY_FRESH

    explanation = (
        f"Similarity {best_score:.0f}% to closest prior campaign."
        if best_id
        else "No prior campaigns to compare against in this scope."
    )
    return NoveltyResult(
        classification=classification,
        similarity_score=round(best_score, 1),
        closest_campaign_id=best_id,
        explanation=explanation,
    )
