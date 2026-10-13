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

from PIL import Image, ImageFont

from app.services.locked_product_compositor import (
    CANVAS_HEIGHT,
    CANVAS_WIDTH,
    FROZEN_DETAIL,
    FROZEN_HEADLINE,
    FROZEN_SUPPORT,
    build_locked_product_layer,
    compose_layers,
    render_text_layer,
    save_png,
    sha256_file,
)

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

EXPECTED_PRIMARY_FONT_STACK = "Georgia, 'Times New Roman', serif"
EXPECTED_SECONDARY_FONT_STACK = "'Helvetica Neue', Arial, sans-serif"

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

FORBIDDEN_BACKGROUND_CONTENT = (
    "product",
    "pouch",
    "package",
    "box",
    "bottle",
    "tube",
    "jar",
    "logo",
    "brand name",
    "letter",
    "word",
    "label",
    "japanese character",
    "portuguese text",
    "signage",
    "watermark",
    "person",
    "hand",
    "face",
)


def _sha256(path: Path) -> str:
    return sha256_file(path)


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


def _json_list(value: Any) -> list[Any]:
    if value in (None, ""):
        return []
    if isinstance(value, list):
        return value
    decoded = json.loads(str(value))
    if not isinstance(decoded, list):
        raise RuntimeError("Expected JSON list.")
    return decoded


def _json_dict(value: Any) -> dict[str, Any]:
    if value in (None, ""):
        return {}
    if isinstance(value, dict):
        return value
    decoded = json.loads(str(value))
    if not isinstance(decoded, dict):
        raise RuntimeError("Expected JSON object.")
    return decoded


def _normalize(value: Any) -> str:
    return " ".join(str(value or "").casefold().replace("-", " ").split())


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
    if int(brands[0]["is_active"] or 0) != 1:
        raise RuntimeError("Canonical Hanna Japan brand is not active.")
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
    master = conn.execute(
        "SELECT * FROM assets WHERE id=? AND product_id=? LIMIT 2",
        (EXPECTED_MASTER_ASSET_ID, EXPECTED_PRODUCT_ID),
    ).fetchall()
    if len(source) != 1:
        raise RuntimeError("Canonical source asset missing or duplicated.")
    if len(master) != 1:
        raise RuntimeError("Approved rendering master missing or duplicated.")
    return {
        "brand": brands[0],
        "product": products[0],
        "facts": facts[0],
        "source": source[0],
        "master": master[0],
    }


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


def _verify_asset(
    row: sqlite3.Row,
    *,
    expected_id: str,
    expected_sha: str,
    expected_role: str,
) -> Path:
    if str(row["id"]) != expected_id:
        raise RuntimeError("Asset identity mismatch.")
    if str(row["image_role"] or "") != expected_role:
        raise RuntimeError("Asset role mismatch.")
    if int(row["is_active"] or 0) != 1:
        raise RuntimeError("Required asset is not active.")
    if str(row["sha256"] or "").lower() != expected_sha.lower():
        raise RuntimeError("Registered asset SHA-256 mismatch.")
    path = Path(str(row["absolute_path"] or "")).expanduser().resolve()
    if not path.is_file():
        raise RuntimeError(f"Required image missing: {path}")
    if _sha256(path).lower() != expected_sha.lower():
        raise RuntimeError("Asset file SHA-256 mismatch.")
    return path


def _verify_master_metadata(master: sqlite3.Row) -> None:
    metadata = _json_dict(master["ai_metadata"])
    if metadata.get("campaign_time_immutable") is not True:
        raise RuntimeError("Approved rendering master is not campaign-time immutable.")
    if str((metadata.get("human_review") or {}).get("status") or "").upper() != "APPROVED":
        raise RuntimeError("Approved rendering master lacks owner approval.")
    if str((metadata.get("product_fidelity") or {}).get("overall_verdict") or "").upper() != "PASS":
        raise RuntimeError("Approved rendering master lacks fidelity PASS.")
    if str(metadata.get("source_asset_id") or "") != EXPECTED_SOURCE_ASSET_ID:
        raise RuntimeError("Approved master source asset identity mismatch.")
    if str(metadata.get("source_sha256") or "").lower() != EXPECTED_SOURCE_SHA256:
        raise RuntimeError("Approved master source SHA mismatch.")


def _verify_brand_typography(brand: sqlite3.Row) -> dict[str, str]:
    typography = _json_dict(brand["typography"])
    primary = str(typography.get("primary_font") or "").strip()
    secondary = str(typography.get("secondary_font") or "").strip()
    if primary != EXPECTED_PRIMARY_FONT_STACK:
        raise RuntimeError(f"Unexpected Hanna primary typography contract: {primary!r}")
    if secondary != EXPECTED_SECONDARY_FONT_STACK:
        raise RuntimeError(f"Unexpected Hanna secondary typography contract: {secondary!r}")
    return {"primary_font": primary, "secondary_font": secondary}


def _font_candidates_for_stack(stack: str) -> list[str]:
    families = [
        item.strip().strip("'").strip('"').casefold()
        for item in stack.split(",")
        if item.strip()
    ]
    mapping = {
        "georgia": ["georgia.ttf"],
        "times new roman": ["times.ttf"],
        "helvetica neue": ["HelveticaNeue.ttf", "helveticaneue.ttf"],
        "arial": ["arial.ttf"],
    }
    candidates: list[str] = []
    for family in families:
        candidates.extend(mapping.get(family, []))
    return candidates


def _resolve_font_file(stack: str) -> Path:
    windir = Path(os.environ.get("WINDIR") or r"C:\Windows")
    fonts_dir = windir / "Fonts"
    for filename in _font_candidates_for_stack(stack):
        candidate = fonts_dir / filename
        if not candidate.is_file():
            continue
        try:
            ImageFont.truetype(str(candidate), 20)
        except Exception:
            continue
        return candidate.resolve()
    raise RuntimeError(f"No installed font file could be resolved from configured Hanna stack: {stack!r}")


def _resolve_brand_font_files(typography: dict[str, str]) -> dict[str, Path]:
    return {
        "headline": _resolve_font_file(typography["primary_font"]),
        "support": _resolve_font_file(typography["secondary_font"]),
    }


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


def _background_prompt() -> str:
    return (
        "Create one premium portrait background plate for a luxury skincare advertising composition. "
        "Art direction: refined deep violet and luminous lilac editorial environment, realistic commercial-photography depth, polished reflective surface, restrained glass or crystal accents, controlled highlights, sophisticated negative space, subtle Japanese-beauty editorial sensibility, elegant studio lighting, premium and uncluttered. "
        "Reserve a large clean central-to-lower hero placement zone for a product that will be composited later, and reserve clean negative space across the upper portion for deterministic typography that will be added later. "
        "Do not render any product, pouch, package, box, bottle, tube, jar, cosmetic container, logo, brand name, label, badge, signage, letters, words, numbers, Japanese characters, Portuguese text, watermark, person, hand, face, or product-shaped placeholder. "
        "Do not imitate packaging or create fake printed surfaces. "
        "The output must be background/environment only, with no intentional text of any kind."
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
        source_path = _verify_asset(
            target["source"],
            expected_id=EXPECTED_SOURCE_ASSET_ID,
            expected_sha=EXPECTED_SOURCE_SHA256,
            expected_role="product",
        )
        master_path = _verify_asset(
            target["master"],
            expected_id=EXPECTED_MASTER_ASSET_ID,
            expected_sha=EXPECTED_MASTER_SHA256,
            expected_role="product_master_approved",
        )
        _verify_master_metadata(target["master"])
        typography = _verify_brand_typography(target["brand"])
        font_files = _resolve_brand_font_files(typography)
        effective = _base_effective_settings(conn)
        model = str(effective.get("openai_premium_image_model") or "").strip()
        if not model:
            raise RuntimeError("Premium image model is not configured.")
        prompt = _background_prompt()
        git_identity = _git_identity()
        return {
            "build": "BUILD6R V3.38",
            "mode": "locked_product_composite",
            "canonical_git_branch": git_identity["branch"],
            "canonical_git_commit": git_identity["commit"],
            "canonical_git_tree": git_identity["tree"],
            "brand_slug": BRAND_SLUG,
            "product_slug": PRODUCT_SLUG,
            "product_id": EXPECTED_PRODUCT_ID,
            "platform": PLATFORM,
            "language": LANGUAGE,
            "quality_mode": QUALITY_MODE,
            "headline": FROZEN_HEADLINE,
            "support_line": FROZEN_SUPPORT,
            "detail_line": FROZEN_DETAIL,
            "approved_master_asset_id": EXPECTED_MASTER_ASSET_ID,
            "approved_master_path": str(master_path),
            "approved_master_sha256": EXPECTED_MASTER_SHA256,
            "canonical_source_asset_id": EXPECTED_SOURCE_ASSET_ID,
            "canonical_source_path": str(source_path),
            "canonical_source_sha256": EXPECTED_SOURCE_SHA256,
            "typography": typography,
            "headline_font_path": str(font_files["headline"]),
            "headline_font_sha256": _sha256(font_files["headline"]),
            "support_font_path": str(font_files["support"]),
            "support_font_sha256": _sha256(font_files["support"]),
            "background_prompt": prompt,
            "background_prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            "size": IMAGE_SIZE,
            "quality": IMAGE_QUALITY,
            "model": model,
            "background_reference_images": [],
            "product_reference_images_sent_to_provider": 0,
            "max_image_calls": 1,
            "qa_max_retries": 0,
            "qa_best_of_n": 1,
            "sdk_retries": 0,
            "request_timeout_seconds": 180,
            "automatic_retry": False,
            "live_process_count": 1,
            "max_budget_usd": DEFAULT_MAX_BUDGET_USD,
            "text_model_call_count_before_image": 0,
            "ai_product_generation": False,
            "ai_product_editing": False,
            "ai_typography_generation": False,
        }
    finally:
        conn.close()


def _synthetic_background() -> Image.Image:
    image = Image.new("RGB", (CANVAS_WIDTH, CANVAS_HEIGHT))
    pixels = image.load()
    for y in range(CANVAS_HEIGHT):
        t = y / max(1, CANVAS_HEIGHT - 1)
        r = int(round(53 + (105 - 53) * t))
        g = int(round(34 + (70 - 34) * t))
        b = int(round(88 + (135 - 88) * t))
        for x in range(CANVAS_WIDTH):
            pixels[x, y] = (r, g, b)
    return image


def _render_local_outputs(
    *,
    payload: dict[str, Any],
    background: Image.Image,
    output_dir: Path,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    background_path = output_dir / "background-only.png"
    locked_layer_path = output_dir / "locked-product-layer.png"
    text_layer_path = output_dir / "text-layer.png"
    final_path = output_dir / "final-composite.png"

    save_png(background.convert("RGBA"), background_path)
    locked_layer, product_meta = build_locked_product_layer(
        Path(payload["approved_master_path"]),
        payload["approved_master_sha256"],
    )
    save_png(locked_layer, locked_layer_path)
    locked_sha_before = _sha256(locked_layer_path)

    text_layer, typography_meta = render_text_layer(
        headline_font_path=Path(payload["headline_font_path"]),
        support_font_path=Path(payload["support_font_path"]),
    )
    save_png(text_layer, text_layer_path)

    with Image.open(locked_layer_path) as exact_locked_layer:
        exact_locked_layer = exact_locked_layer.convert("RGBA")
        final = compose_layers(
            background=background,
            locked_product_layer=exact_locked_layer,
            text_layer=text_layer,
        )
    save_png(final, final_path)

    locked_sha_after = _sha256(locked_layer_path)
    if locked_sha_before != locked_sha_after:
        raise RuntimeError("Locked product layer changed during composition.")

    return {
        "background_only_path": str(background_path),
        "background_only_sha256": _sha256(background_path),
        "locked_product_layer_path": str(locked_layer_path),
        "locked_product_layer_sha256": locked_sha_after,
        "product_layer_used_sha256": locked_sha_before,
        "locked_product_layer_immutability": True,
        "text_layer_path": str(text_layer_path),
        "text_layer_sha256": _sha256(text_layer_path),
        "final_composite_path": str(final_path),
        "final_composite_sha256": _sha256(final_path),
        "final_width": CANVAS_WIDTH,
        "final_height": CANVAS_HEIGHT,
        "product_transform": product_meta,
        "typography_render": typography_meta,
    }


def _write_evidence(
    evidence_dir: Path,
    payload: dict[str, Any],
    *,
    mode: str,
    output: dict[str, Any],
    usage: dict[str, Any] | None = None,
    hard_budget_snapshot: dict[str, Any] | None = None,
) -> None:
    evidence_dir.mkdir(parents=True, exist_ok=True)
    request_path = evidence_dir / "v338_request.json"
    result_path = evidence_dir / "v338_result.json"
    request_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    result = {
        "mode": mode,
        "request_sha256": _sha256(request_path),
        "payload": payload,
        "output": output,
        "usage": usage or {},
        "hard_budget_snapshot": hard_budget_snapshot or {},
    }
    result_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    manifest_lines = []
    for path in sorted(evidence_dir.iterdir()):
        if path.is_file() and path.name != "evidence_manifest.txt":
            manifest_lines.append(f"{_sha256(path)}\t{path.stat().st_size}\t{path.name}")
    (evidence_dir / "evidence_manifest.txt").write_text(
        "\n".join(manifest_lines) + "\n",
        encoding="utf-8",
    )


def _assert_live_controls(database: Path, max_budget_usd: float) -> None:
    if os.environ.get("BUILD6R_V338_BACKGROUND_SMOKE_AUTHORIZED") != "TRUE":
        raise RuntimeError("V3.38 background execution is not authorized.")
    if database.resolve() == CANONICAL_DB:
        raise RuntimeError("Paid V3.38 background execution may not target canonical SQLite.")
    if max_budget_usd <= 0 or max_budget_usd > DEFAULT_MAX_BUDGET_USD:
        raise RuntimeError("V3.38 live budget is outside governed ceiling.")
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


async def _execute_background_once(
    *,
    payload: dict[str, Any],
    database: Path,
    max_budget_usd: float,
) -> tuple[bytes, list[dict[str, Any]], dict[str, Any]]:
    conn = _open_query_only(database)
    try:
        effective = _base_effective_settings(conn)
    finally:
        conn.close()
    effective["openai_max_image_calls"] = 1
    from app.services.ai.openai_provider import openai_provider_from_effective_settings
    provider = openai_provider_from_effective_settings(
        effective,
        hard_budget_usd=max_budget_usd,
    )
    image_bytes = await provider.generate(
        prompt=payload["background_prompt"],
        size=payload["size"],
        model=payload["model"],
        quality=payload["quality"],
    )
    return image_bytes, provider.drain_usage_events(), provider.hard_budget_snapshot()


def _validate_live_usage(events: list[dict[str, Any]]) -> dict[str, Any]:
    image_calls = sum(int(event.get("image_count", 0) or 0) for event in events)
    input_tokens = sum(int(event.get("input_tokens", 0) or 0) for event in events)
    output_tokens = sum(int(event.get("output_tokens", 0) or 0) for event in events)
    estimated_cost = sum(float(event.get("estimated_cost_usd", 0.0) or 0.0) for event in events)
    if image_calls != 1:
        raise RuntimeError(f"Expected exactly one background image call; observed {image_calls}.")
    if input_tokens != 0 or output_tokens != 0:
        raise RuntimeError("V3.38 path recorded text-model token usage.")
    return {
        "image_call_count": image_calls,
        "text_model_call_count": 0,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "local_estimated_cost_usd": estimated_cost,
        "usage_events": events,
    }


def _print_dry_markers(payload: dict[str, Any], output: dict[str, Any]) -> None:
    markers = (
        "BUILD6R_V338_MODE=DRY_RUN",
        "LOCKED_PRODUCT_INPUT_VALID=TRUE",
        "APPROVED_MASTER_RESOLVED=TRUE",
        "APPROVED_MASTER_SHA256_VALID=TRUE",
        "APPROVED_MASTER_RGBA_VALID=TRUE",
        "APPROVED_MASTER_ALPHA_VALID=TRUE",
        "BACKGROUND_PROMPT_CONSTRUCTED=TRUE",
        "BACKGROUND_PRODUCT_REFERENCE_COUNT=0",
        "FIXED_COPY_RESOLVED=TRUE",
        "DETERMINISTIC_TYPOGRAPHY_RESOLVED=TRUE",
        "LOCKED_PRODUCT_LAYER_RENDERED=TRUE",
        "LOCKED_PRODUCT_LAYER_IMMUTABILITY=PASS",
        "TEXT_MODEL_CALL_COUNT=0",
        "IMAGE_CALL_COUNT=0",
        "PAID_CALLS=0",
        "AI_PRODUCT_GENERATION=FALSE",
        "AI_PRODUCT_EDITING=FALSE",
        "AI_TYPOGRAPHY_GENERATION=FALSE",
        "READY_FOR_ONE_BACKGROUND_IMAGE_SMOKE_TEST=TRUE",
        "ATTEMPT12_AUTHORIZED=FALSE",
    )
    for marker in markers:
        print(marker)
    print(f"HEADLINE_FONT_PATH={payload['headline_font_path']}")
    print(f"HEADLINE_FONT_SHA256={payload['headline_font_sha256']}")
    print(f"SUPPORT_FONT_PATH={payload['support_font_path']}")
    print(f"SUPPORT_FONT_SHA256={payload['support_font_sha256']}")
    print(f"BACKGROUND_PROMPT_SHA256={payload['background_prompt_sha256']}")
    print(f"LOCKED_PRODUCT_LAYER_SHA256={output['locked_product_layer_sha256']}")
    print(f"FINAL_COMPOSITE_SHA256={output['final_composite_sha256']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="BUILD6R V3.38 locked-product composite smoke harness."
    )
    parser.add_argument("--database", type=Path, default=CANONICAL_DB)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--max-budget-usd", type=float, default=DEFAULT_MAX_BUDGET_USD)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--dry-run", action="store_true")
    modes.add_argument("--execute-background", action="store_true")
    args = parser.parse_args(argv)

    database = args.database.resolve()
    payload = _prepare_request(database)
    payload["max_budget_usd"] = float(args.max_budget_usd)

    if args.dry_run:
        background = _synthetic_background()
        output = _render_local_outputs(
            payload=payload,
            background=background,
            output_dir=args.output_dir,
        )
        _write_evidence(
            args.evidence_dir,
            payload,
            mode="dry_run",
            output=output,
        )
        _print_dry_markers(payload, output)
        return 0

    _assert_live_controls(database, float(args.max_budget_usd))
    background_bytes, events, hard_budget = asyncio.run(
        _execute_background_once(
            payload=payload,
            database=database,
            max_budget_usd=float(args.max_budget_usd),
        )
    )
    usage = _validate_live_usage(events)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    raw_background = args.output_dir / "background-provider-raw.png"
    raw_background.write_bytes(background_bytes)
    with Image.open(raw_background) as image:
        image.verify()
    with Image.open(raw_background) as image:
        background = image.convert("RGBA")
        if background.size != (CANVAS_WIDTH, CANVAS_HEIGHT):
            raise RuntimeError(
                f"Provider background dimensions mismatch: {background.size!r}"
            )
        background.load()
    output = _render_local_outputs(
        payload=payload,
        background=background,
        output_dir=args.output_dir,
    )
    output["provider_background_raw_path"] = str(raw_background)
    output["provider_background_raw_sha256"] = _sha256(raw_background)
    _write_evidence(
        args.evidence_dir,
        payload,
        mode="execute_background",
        output=output,
        usage=usage,
        hard_budget_snapshot=hard_budget,
    )
    print("BUILD6R_V338_BACKGROUND_SMOKE=PASS")
    print("TEXT_MODEL_CALL_COUNT=0")
    print("BACKGROUND_IMAGE_CALL_COUNT=1")
    print("PRODUCT_IMAGE_CALL_COUNT=0")
    print("REFERENCE_PRODUCT_IMAGES_SENT_TO_PROVIDER=0")
    print("LOCKED_PRODUCT_LAYER_IMMUTABILITY=PASS")
    print(f"FINAL_COMPOSITE={output['final_composite_path']}")
    print(f"FINAL_COMPOSITE_SHA256={output['final_composite_sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())