from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sqlite3
import subprocess
from pathlib import Path
from typing import Any

from PIL import Image

BACKEND = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND.parent
CANONICAL_DB = (BACKEND / "data" / "app.db").resolve()

BRAND_SLUG = "hanna-japan"
PRODUCT_SLUG = "lululun-hydra-ex-mask-7-sheets"
PLATFORM = "instagram"
LANGUAGE = "pt-BR"
QUALITY_MODE = "premium"

EXPECTED_PRODUCT_ID = "a5ea2272a1f89d743c089461bb2fb50f"
EXPECTED_SOURCE_ASSET_ID = "f253e2586a4f979c34942e16a9d70518"
EXPECTED_SOURCE_SHA256 = "94e7fb1436596f0566ddf0b83359cfff1c402bd36fc7435c5067243de1a591cb"
EXPECTED_MASTER_ASSET_ID = "b18fb565179753b2a34fd9c7dba2a94a"
EXPECTED_MASTER_SHA256 = "747df22f2a227a5705f2fff9a831f9a334ec17f1973953ccd9f86d17216992bc"

FROZEN_HEADLINE = "LuLuLun Hydra EX"
FROZEN_SUPPORT = "Máscara facial • 7 folhas"
FROZEN_DETAIL = "150 mL de essência"

IMAGE_SIZE = "1024x1536"
IMAGE_QUALITY = "xhigh"
DEFAULT_MAX_BUDGET_USD = 0.50

FORBIDDEN_AUTONOMOUS_OPERATIONS = (
    "research",
    "strategy",
    "master_campaign_concept",
    "creative_brief",
    "campaign_copy",
    "claims_audit_extraction",
)

FORBIDDEN_SMOKE_COPY_TERMS = (
    "exossom", "células-tronco", "celulas-tronco", "sem fragrância",
    "sem fragrancia", "sem álcool", "sem alcool", "óleo mineral",
    "oleo mineral", "corante", "melty feel", "clare", "anti-aging",
    "antienvelhecimento", "resultado", "preço", "preco", "estoque",
    "bestseller", "ranking", "viral",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()



def _git_identity() -> dict[str, str]:
    def run(*args: str) -> str:
        completed = subprocess.run(
            ["git", "-C", str(REPO_ROOT), *args],
            check=True,
            capture_output=True,
            text=True,
        )
        return completed.stdout.strip()

    return {
        "branch": run("branch", "--show-current"),
        "commit": run("rev-parse", "HEAD"),
        "tree": run("show", "-s", "--format=%T", "HEAD"),
    }

def _normalize(value: Any) -> str:
    return " ".join(str(value or "").casefold().replace("-", " ").split())


def _json_list(value: Any) -> list[Any]:
    if value in (None, ""):
        return []
    if isinstance(value, list):
        return value
    decoded = json.loads(str(value))
    if isinstance(decoded, list):
        return decoded
    raise RuntimeError("Expected JSON list.")


def _json_dict(value: Any) -> dict[str, Any]:
    if value in (None, ""):
        return {}
    if isinstance(value, dict):
        return value
    decoded = json.loads(str(value))
    if isinstance(decoded, dict):
        return decoded
    raise RuntimeError("Expected JSON object.")


def _open_query_only(database: Path) -> sqlite3.Connection:
    database = database.resolve()
    if not database.is_file():
        raise RuntimeError(f"Database not found: {database}")
    conn = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    if int(conn.execute("PRAGMA query_only").fetchone()[0] or 0) != 1:
        conn.close()
        raise RuntimeError("SQLite query_only could not be enabled.")
    return conn


def _resolve_target(conn: sqlite3.Connection) -> dict[str, sqlite3.Row]:
    brands = conn.execute("SELECT * FROM brands WHERE slug=? LIMIT 2", (BRAND_SLUG,)).fetchall()
    if len(brands) != 1:
        raise RuntimeError(f"Expected exactly one brand {BRAND_SLUG!r}; found {len(brands)}.")
    products = conn.execute(
        "SELECT * FROM products WHERE brand_id=? AND slug=? LIMIT 2",
        (brands[0]["id"], PRODUCT_SLUG),
    ).fetchall()
    if len(products) != 1:
        raise RuntimeError(f"Expected exactly one product {PRODUCT_SLUG!r}; found {len(products)}.")
    if str(products[0]["id"]) != EXPECTED_PRODUCT_ID:
        raise RuntimeError("Canonical product id mismatch.")
    facts = conn.execute(
        "SELECT * FROM verified_product_facts WHERE product_id=? LIMIT 2",
        (EXPECTED_PRODUCT_ID,),
    ).fetchall()
    if len(facts) != 1:
        raise RuntimeError(f"Expected exactly one canonical VerifiedProductFacts row; found {len(facts)}.")
    source = conn.execute(
        "SELECT * FROM assets WHERE id=? AND product_id=? LIMIT 2",
        (EXPECTED_SOURCE_ASSET_ID, EXPECTED_PRODUCT_ID),
    ).fetchall()
    if len(source) != 1:
        raise RuntimeError("Canonical source asset missing or duplicated.")
    master = conn.execute(
        "SELECT * FROM assets WHERE id=? AND product_id=? LIMIT 2",
        (EXPECTED_MASTER_ASSET_ID, EXPECTED_PRODUCT_ID),
    ).fetchall()
    if len(master) != 1:
        raise RuntimeError("Approved rendering master missing or duplicated.")
    return {"brand": brands[0], "product": products[0], "facts": facts[0], "source": source[0], "master": master[0]}


def _verify_frozen_copy(facts: sqlite3.Row) -> None:
    description = _normalize(facts["verified_description"])
    size = _normalize(facts["verified_size"])
    variant = _normalize(facts["verified_variant"])
    features = " ".join(_normalize(v) for v in _json_list(facts["verified_features"]))
    if "facial sheet mask" not in description:
        raise RuntimeError("Frozen 'Máscara facial' copy lacks canonical support.")
    if not ("7 sheet" in size or "7 sheet" in variant or "7 sheet" in features):
        raise RuntimeError("Frozen '7 folhas' copy lacks canonical support.")
    if "150 ml" not in size and "150 ml" not in features:
        raise RuntimeError("Frozen '150 mL de essência' copy lacks canonical support.")
    frozen_blob = " ".join((FROZEN_HEADLINE, FROZEN_SUPPORT, FROZEN_DETAIL)).casefold()
    if any(term in frozen_blob for term in ("japonesa", "japonês", "japones")):
        raise RuntimeError("Golden Slide copy may not assert Japanese origin.")
    for term in FORBIDDEN_SMOKE_COPY_TERMS:
        if term.casefold() in frozen_blob:
            raise RuntimeError(f"Forbidden Golden Slide copy term present: {term}")


def _verify_asset(row: sqlite3.Row, *, expected_id: str, expected_sha: str, expected_role: str) -> Path:
    if str(row["id"]) != expected_id:
        raise RuntimeError("Asset identity mismatch.")
    if str(row["image_role"] or "") != expected_role:
        raise RuntimeError(f"Asset role mismatch: expected {expected_role!r}, actual {row['image_role']!r}.")
    if int(row["is_active"] or 0) != 1:
        raise RuntimeError("Required Golden Slide asset is not active.")
    if str(row["sha256"] or "").lower() != expected_sha.lower():
        raise RuntimeError("Registered asset SHA-256 mismatch.")
    path = Path(str(row["absolute_path"] or "")).expanduser().resolve()
    if not path.is_file():
        raise RuntimeError(f"Required Golden Slide image missing: {path}")
    if _sha256(path) != expected_sha.lower():
        raise RuntimeError("Golden Slide image file SHA-256 mismatch.")
    with Image.open(path) as image:
        image.verify()
    return path


def _verify_master_metadata(master: sqlite3.Row) -> None:
    metadata = _json_dict(master["ai_metadata"])
    if metadata.get("ai_generated") is not True:
        raise RuntimeError("Approved rendering master provenance mismatch.")
    if metadata.get("campaign_time_immutable") is not True:
        raise RuntimeError("Approved rendering master is not campaign-time immutable.")
    if str((metadata.get("human_review") or {}).get("status") or "").upper() != "APPROVED":
        raise RuntimeError("Approved rendering master lacks owner approval.")
    if str((metadata.get("product_fidelity") or {}).get("overall_verdict") or "").upper() != "PASS":
        raise RuntimeError("Approved rendering master lacks fidelity PASS.")
    exc = metadata.get("full_reconstruction_exception") or {}
    if str(exc.get("status") or "").upper() != "APPROVED":
        raise RuntimeError("Approved full-reconstruction exception missing.")
    if str(exc.get("approved_sha256") or "").lower() != EXPECTED_MASTER_SHA256:
        raise RuntimeError("Approved master metadata SHA mismatch.")
    if str(metadata.get("source_asset_id") or "") != EXPECTED_SOURCE_ASSET_ID:
        raise RuntimeError("Approved master source asset identity mismatch.")
    if str(metadata.get("source_sha256") or "").lower() != EXPECTED_SOURCE_SHA256:
        raise RuntimeError("Approved master source SHA mismatch.")


def _base_effective_settings(conn: sqlite3.Connection) -> dict[str, Any]:
    from app.config import get_settings
    base = get_settings()
    effective = {
        "openai_api_key": base.openai_api_key,
        "openai_premium_image_model": base.openai_premium_image_model,
        "openai_project_id": base.openai_project_id,
        "openai_project_hard_limit_attested": base.openai_project_hard_limit_attested,
        "openai_max_image_calls": base.openai_max_image_calls,
    }
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(settings)").fetchall()}
    if {"key", "value"}.issubset(cols):
        rows = conn.execute(
            "SELECT key,value FROM settings WHERE key IN ('openai_api_key','openai_premium_image_model')"
        ).fetchall()
        for row in rows:
            raw = row["value"]
            try:
                decoded = json.loads(str(raw))
            except Exception:
                decoded = raw
            if isinstance(decoded, dict) and "v" in decoded:
                decoded = decoded["v"]
            effective[str(row["key"])] = decoded
    return effective


def _visual_prompt() -> str:
    return (
        "Create one finished premium portrait Instagram product-ad slide for Hanna Japan. "
        "Use the supplied reference images as strict product-identity references. "
        "Reference image 1 is the owner-approved immutable rendering master for the exact LuLuLun Hydra EX Mask 7 Sheets / 150 mL pouch. "
        "Reference image 2 is the canonical real in-store product photograph and is the final factual/fidelity authority. "
        "Preserve the exact pouch identity: package shape, proportions, color, LuLuLun branding, label structure, Japanese package printing, visible package text, and product geometry. "
        "Do not redesign, replace, simplify, distort, crop away, or invent any package element. If the two references differ, use the canonical real photograph to resolve fidelity. "
        "Art direction: premium Japanese-beauty editorial advertising, refined luminous skincare photography, elegant depth, controlled highlights, subtle tactile materials, polished studio lighting, sophisticated negative space, premium but restrained styling. "
        "Composition: portrait layout optimized for Instagram; product is the clear hero, with strong hierarchy and generous safe spacing around all overlay copy. Do not place overlay copy on top of the package. "
        "Keep the layout clean and commercially art-directed rather than looking like a generic template. "
        "Render exactly these three external copy lines, spelled exactly as written, with no other external headline, body copy, CTA, badge, claim, certification, price, discount, logo, decorative word, watermark, or invented text:\n"
        f"1. {FROZEN_HEADLINE}\n2. {FROZEN_SUPPORT}\n3. {FROZEN_DETAIL}\n"
        "The three copy lines must be crisp, readable, correctly accented Portuguese, and visually separate from the product package. "
        "Do not add ingredients, efficacy language, medical language, free-from claims, popularity claims, price, availability, scarcity, rankings, endorsements, certifications, or promotional promises. "
        "Do not add people or additional products. Do not invent a Hanna logo; express Hanna Japan branding through the refined visual system only. Output one cohesive premium hero slide."
    )


def _prepare_request(database: Path) -> dict[str, Any]:
    conn = _open_query_only(database)
    try:
        target = _resolve_target(conn)
        facts = target["facts"]
        _verify_frozen_copy(facts)
        if "manufacturer_official" not in str(facts["provenance"] or ""):
            raise RuntimeError("Canonical product provenance is not manufacturer-official.")
        if float(facts["confidence"] or 0.0) != 1.0:
            raise RuntimeError("Canonical product facts confidence is not 1.0.")
        source_path = _verify_asset(target["source"], expected_id=EXPECTED_SOURCE_ASSET_ID, expected_sha=EXPECTED_SOURCE_SHA256, expected_role="product")
        master_path = _verify_asset(target["master"], expected_id=EXPECTED_MASTER_ASSET_ID, expected_sha=EXPECTED_MASTER_SHA256, expected_role="product_master_approved")
        _verify_master_metadata(target["master"])
        effective = _base_effective_settings(conn)
        model = str(effective.get("openai_premium_image_model") or "").strip()
        if not model:
            raise RuntimeError("Premium image model is not configured.")
        prompt = _visual_prompt()
        git_identity = _git_identity()
        harness_path = Path(__file__).resolve()
        test_path = BACKEND / "tests" / "test_build6r_v337_golden_slide_smoke.py"
        return {
            "build": "BUILD6R V3.37",
            "canonical_git_branch": git_identity["branch"],
            "canonical_git_commit": git_identity["commit"],
            "canonical_git_tree": git_identity["tree"],
            "v337_harness_sha256": _sha256(harness_path),
            "v337_test_sha256": (_sha256(test_path) if test_path.is_file() else "MISSING"),
            "mode": "golden_slide_visual_smoke",
            "brand_slug": BRAND_SLUG,
            "product_slug": PRODUCT_SLUG,
            "product_id": EXPECTED_PRODUCT_ID,
            "platform": PLATFORM,
            "language": LANGUAGE,
            "quality_mode": QUALITY_MODE,
            "headline": FROZEN_HEADLINE,
            "support_line": FROZEN_SUPPORT,
            "detail_line": FROZEN_DETAIL,
            "prompt": prompt,
            "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            "size": IMAGE_SIZE,
            "quality": IMAGE_QUALITY,
            "model": model,
            "reference_images": [
                {"role": "owner_approved_rendering_master", "asset_id": EXPECTED_MASTER_ASSET_ID, "path": str(master_path), "sha256": EXPECTED_MASTER_SHA256},
                {"role": "canonical_real_product_fidelity_authority", "asset_id": EXPECTED_SOURCE_ASSET_ID, "path": str(source_path), "sha256": EXPECTED_SOURCE_SHA256},
            ],
            "max_image_calls": 1,
            "qa_max_retries": 0,
            "qa_best_of_n": 1,
            "sdk_retries": 0,
            "request_timeout_seconds": 180,
            "automatic_retry": False,
            "live_process_count": 1,
            "max_budget_usd": DEFAULT_MAX_BUDGET_USD,
            "text_model_call_count_before_image": 0,
        }
    finally:
        conn.close()


def _write_evidence(evidence_dir: Path, payload: dict[str, Any], *, mode: str, output: dict[str, Any] | None = None) -> None:
    evidence_dir.mkdir(parents=True, exist_ok=True)
    req = evidence_dir / "golden_slide_request.json"
    req.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    result = {"mode": mode, "request_sha256": _sha256(req), "payload": payload, "output": output or {}}
    res = evidence_dir / "golden_slide_result.json"
    res.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    lines = []
    for path in sorted(evidence_dir.iterdir()):
        if path.is_file() and path.name != "evidence_manifest.txt":
            lines.append(f"{_sha256(path)}\t{path.stat().st_size}\t{path.name}")
    (evidence_dir / "evidence_manifest.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _assert_live_controls(database: Path, max_budget_usd: float) -> None:
    if os.environ.get("BUILD6R_V337_IMAGE_SMOKE_AUTHORIZED") != "TRUE":
        raise RuntimeError("Golden Slide image execution is not authorized. A separate governed live authorization is required.")
    if database.resolve() == CANONICAL_DB:
        raise RuntimeError("Paid Golden Slide execution may not target canonical SQLite.")
    if max_budget_usd <= 0 or max_budget_usd > DEFAULT_MAX_BUDGET_USD:
        raise RuntimeError("Golden Slide live budget is outside the governed ceiling.")
    required = {
        "OPENAI_MAX_IMAGE_CALLS": "1",
        "OPENAI_SDK_MAX_RETRIES": "0",
        "OPENAI_REQUEST_TIMEOUT_SECONDS": "180",
        "QA_MAX_RETRIES": "0",
        "QA_BEST_OF_N": "1",
    }
    for name, expected in required.items():
        actual = str(os.environ.get(name, "")).strip()
        if actual != expected:
            raise RuntimeError(f"Required live control {name}={expected!r}; actual={actual!r}.")


async def _execute_image_once(*, payload: dict[str, Any], database: Path, max_budget_usd: float) -> tuple[bytes, list[dict[str, Any]], dict[str, Any]]:
    conn = _open_query_only(database)
    try:
        effective = _base_effective_settings(conn)
    finally:
        conn.close()
    effective["openai_max_image_calls"] = 1
    from app.services.ai.openai_provider import openai_provider_from_effective_settings
    provider = openai_provider_from_effective_settings(effective, hard_budget_usd=max_budget_usd)
    refs = [Path(item["path"]) for item in payload["reference_images"]]
    image_bytes = await provider.generate(
        prompt=payload["prompt"], size=payload["size"], model=payload["model"], reference_images=refs, quality=payload["quality"]
    )
    return image_bytes, provider.drain_usage_events(), provider.hard_budget_snapshot()


def _validate_live_usage(events: list[dict[str, Any]]) -> dict[str, Any]:
    image_calls = sum(int(e.get("image_count", 0) or 0) for e in events)
    input_tokens = sum(int(e.get("input_tokens", 0) or 0) for e in events)
    output_tokens = sum(int(e.get("output_tokens", 0) or 0) for e in events)
    estimated_cost = sum(float(e.get("estimated_cost_usd", 0.0) or 0.0) for e in events)
    if image_calls != 1:
        raise RuntimeError(f"Expected exactly one image call; observed {image_calls}.")
    if input_tokens != 0 or output_tokens != 0:
        raise RuntimeError("Golden Slide path recorded text-model token usage.")
    return {"image_call_count": image_calls, "text_model_call_count": 0, "input_tokens": input_tokens, "output_tokens": output_tokens, "local_estimated_cost_usd": estimated_cost, "usage_events": events}


def _print_dry_run_markers(payload: dict[str, Any], evidence_dir: Path) -> None:
    markers = [
        "BUILD6R_V337_MODE=DRY_RUN",
        "GOLDEN_SLIDE_INPUT_VALID=TRUE",
        "CANONICAL_PRODUCT_RESOLVED=TRUE",
        "APPROVED_SOURCE_IMAGE_RESOLVED=TRUE",
        "FIXED_COPY_RESOLVED=TRUE",
        "VISUAL_PROMPT_CONSTRUCTED=TRUE",
        "TEXT_MODEL_CALL_COUNT=0",
        "IMAGE_CALL_COUNT=0",
        "PAID_CALLS=0",
        "LIVE_ACCEPTANCE_RUN=FALSE",
        "READY_FOR_ONE_IMAGE_SMOKE_TEST=TRUE",
        "ATTEMPT11_RERUN_ALLOWED=FALSE",
        "ATTEMPT12_AUTHORIZED=FALSE",
    ]
    for marker in markers:
        print(marker)
    print(f"TARGET_BRAND={payload['brand_slug']}")
    print(f"TARGET_PRODUCT={payload['product_slug']}")
    print(f"TARGET_PLATFORM={payload['platform']}")
    print(f"TARGET_LANGUAGE={payload['language']}")
    print(f"FROZEN_HEADLINE={payload['headline']}")
    print(f"FROZEN_SUPPORT={payload['support_line']}")
    print(f"FROZEN_DETAIL={payload['detail_line']}")
    print(f"CONFIGURED_PREMIUM_IMAGE_MODEL={payload['model']}")
    print(f"CONFIGURED_PREMIUM_IMAGE_QUALITY={payload['quality']}")
    print(f"IMAGE_SIZE={payload['size']}")
    print(f"MAX_IMAGE_CALLS={payload['max_image_calls']}")
    print(f"MAX_BUDGET_USD={payload['max_budget_usd']:.2f}")
    print(f"PROMPT_SHA256={payload['prompt_sha256']}")
    print(f"EVIDENCE_DIR={evidence_dir}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="BUILD6R V3.37 deterministic Golden Slide smoke-test harness.")
    parser.add_argument("--database", type=Path, default=CANONICAL_DB)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--max-budget-usd", type=float, default=DEFAULT_MAX_BUDGET_USD)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--dry-run", action="store_true")
    modes.add_argument("--execute-image", action="store_true")
    args = parser.parse_args(argv)
    database = args.database.resolve()
    payload = _prepare_request(database)
    payload["max_budget_usd"] = float(args.max_budget_usd)
    if args.dry_run:
        _write_evidence(args.evidence_dir, payload, mode="dry_run")
        _print_dry_run_markers(payload, args.evidence_dir)
        return 0
    _assert_live_controls(database, float(args.max_budget_usd))
    if args.output_dir is None:
        raise RuntimeError("--output-dir is required for --execute-image.")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    image_bytes, events, budget = asyncio.run(_execute_image_once(payload=payload, database=database, max_budget_usd=float(args.max_budget_usd)))
    usage = _validate_live_usage(events)
    output_path = args.output_dir / "golden-slide-v337.png"
    output_path.write_bytes(image_bytes)
    with Image.open(output_path) as image:
        width, height = image.size
        image.verify()
    output = {
        "generated_asset": str(output_path),
        "generated_asset_sha256": _sha256(output_path),
        "width": width,
        "height": height,
        "provider": "openai",
        "model": payload["model"],
        "quality": payload["quality"],
        "source_master_asset_id": EXPECTED_MASTER_ASSET_ID,
        "source_master_sha256": EXPECTED_MASTER_SHA256,
        "canonical_source_asset_id": EXPECTED_SOURCE_ASSET_ID,
        "canonical_source_sha256": EXPECTED_SOURCE_SHA256,
        "usage": usage,
        "hard_budget_snapshot": budget,
    }
    _write_evidence(args.evidence_dir, payload, mode="execute_image", output=output)
    print("GOLDEN_SLIDE_IMAGE_CALL_COUNT=1")
    print("GOLDEN_SLIDE_GENERATED_ASSET_COUNT=1")
    print("TEXT_MODEL_CALL_COUNT=0")
    print(f"GENERATED_ASSET={output_path}")
    print(f"GENERATED_ASSET_SHA256={output['generated_asset_sha256']}")
    print(f"GENERATED_ASSET_WIDTH={width}")
    print(f"GENERATED_ASSET_HEIGHT={height}")
    print(f"LOCAL_ESTIMATED_COST_USD={usage['local_estimated_cost_usd']:.9f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())