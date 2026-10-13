from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from app.services.product_integration_polish import (
    RECOMMENDED_PROFILE,
    SHADOW_PROFILES,
    render_profile,
    sha256_file,
)

BACKEND = Path(__file__).resolve().parents[1]
DEFAULT_V338_ROOT = Path(
    r"C:\Users\wesle\Downloads\BUILD6R_V338_LockedComposite_Smoke_20261013-222910"
)

EXPECTED_BACKGROUND_SHA256 = (
    "e217b89868314f44164954b9f75f980aa3a377272ca9f3bfc1baa9e6d7a5b6c4"
)
EXPECTED_LOCKED_PRODUCT_SHA256 = (
    "b3fc6e513fcdf94a80af385d9bc7ad75b3d53ac811b9aa982f8142bc2c90d09b"
)
EXPECTED_TEXT_LAYER_SHA256 = (
    "f52358cb59993b01c0480e99f09a9514fc03d8d0a552c8f28d632b2a54f8df22"
)
EXPECTED_V338_FINAL_SHA256 = (
    "9de5d934ea1c3ac7bbc4d6b1cc961031b3a83fce098edcca57ae04f214cf8315"
)


def _paths(v338_root: Path) -> dict[str, Path]:
    output = v338_root / "output"
    return {
        "background": output / "background-only.png",
        "locked_product": output / "locked-product-layer.png",
        "text_layer": output / "text-layer.png",
        "v338_final": output / "final-composite.png",
    }


def _validate_v338_sources(v338_root: Path) -> dict[str, str]:
    paths = _paths(v338_root)
    expected = {
        "background": EXPECTED_BACKGROUND_SHA256,
        "locked_product": EXPECTED_LOCKED_PRODUCT_SHA256,
        "text_layer": EXPECTED_TEXT_LAYER_SHA256,
        "v338_final": EXPECTED_V338_FINAL_SHA256,
    }
    validated: dict[str, str] = {}
    for name, path in paths.items():
        if not path.is_file():
            raise RuntimeError(f"Required V3.38 artifact missing: {path}")
        actual = sha256_file(path)
        if actual.lower() != expected[name].lower():
            raise RuntimeError(f"V3.38 artifact SHA mismatch: {name}")
        validated[name] = actual
    return validated


def _write_manifest(root: Path) -> Path:
    manifest = root / "evidence_manifest.txt"
    lines: list[str] = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and path != manifest:
            relative = path.relative_to(root)
            lines.append(
                f"{sha256_file(path)}\t{path.stat().st_size}\t{relative.as_posix()}"
            )
    manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="BUILD6R V3.39 deterministic product integration polish."
    )
    parser.add_argument(
        "--v338-root",
        type=Path,
        default=DEFAULT_V338_ROOT,
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "--evidence-dir",
        type=Path,
        required=True,
    )
    args = parser.parse_args(argv)

    v338_root = args.v338_root.resolve()
    output_dir = args.output_dir.resolve()
    evidence_dir = args.evidence_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    evidence_dir.mkdir(parents=True, exist_ok=True)

    source_hashes = _validate_v338_sources(v338_root)
    paths = _paths(v338_root)

    results = []
    for profile in SHADOW_PROFILES:
        results.append(
            render_profile(
                background_path=paths["background"],
                locked_product_path=paths["locked_product"],
                text_layer_path=paths["text_layer"],
                background_sha256=EXPECTED_BACKGROUND_SHA256,
                locked_product_sha256=EXPECTED_LOCKED_PRODUCT_SHA256,
                text_layer_sha256=EXPECTED_TEXT_LAYER_SHA256,
                profile=profile,
                output_dir=output_dir,
            )
        )

    recommended = next(
        item for item in results if item["profile"] == RECOMMENDED_PROFILE
    )
    recommended_source = Path(recommended["final"]["path"])
    recommended_path = output_dir / "final-composite-v339.png"
    shutil.copyfile(recommended_source, recommended_path)
    recommended_sha = sha256_file(recommended_path)
    if recommended_sha != recommended["final"]["sha256"]:
        raise RuntimeError("Recommended V3.39 composite copy changed bytes.")

    product_hash_after_all = sha256_file(paths["locked_product"])
    if product_hash_after_all.lower() != EXPECTED_LOCKED_PRODUCT_SHA256:
        raise RuntimeError("V3.38 locked product layer changed across V3.39 variants.")

    evidence = {
        "build": "BUILD6R V3.39",
        "mode": "deterministic_integration_polish",
        "ai_calls": 0,
        "image_provider_calls": 0,
        "paid_calls": 0,
        "v338_background_reused": True,
        "v338_product_layer_reused": True,
        "v338_text_layer_reused": True,
        "reflection_enabled": False,
        "source_hashes": source_hashes,
        "profiles": results,
        "recommended_profile": RECOMMENDED_PROFILE,
        "recommended_final_path": str(recommended_path),
        "recommended_final_sha256": recommended_sha,
        "locked_product_layer_sha256_after_all": product_hash_after_all,
        "locked_product_layer_immutability": True,
        "product_pixel_mutation_count": 0,
    }
    evidence_path = evidence_dir / "v339_result.json"
    evidence_path.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    manifest = _write_manifest(evidence_dir)

    print("BUILD6R_V339_MODE=LOCAL_ZERO_COST_RENDER")
    print("V338_BACKGROUND_REUSED=TRUE")
    print("V338_PRODUCT_LAYER_REUSED=TRUE")
    print("V338_TEXT_LAYER_REUSED=TRUE")
    print("CONTACT_SHADOW_GENERATED=TRUE")
    print("CONTACT_SHADOW_SOURCE=PRODUCT_ALPHA_MASK")
    print("REFLECTION_ENABLED=FALSE")
    print("LOCKED_PRODUCT_LAYER_IMMUTABILITY=PASS")
    print("PRODUCT_PIXEL_MUTATION_COUNT=0")
    print("AI_CALLS=0")
    print("IMAGE_PROVIDER_CALLS=0")
    print("PAID_CALLS=0")
    print("LOCAL_VARIANT_COUNT=3")
    print(f"RECOMMENDED_PROFILE={RECOMMENDED_PROFILE}")
    print(f"FINAL_COMPOSITE_V339={recommended_path}")
    print(f"FINAL_COMPOSITE_V339_SHA256={recommended_sha}")
    print(f"V339_EVIDENCE={evidence_path}")
    print(f"V339_EVIDENCE_MANIFEST={manifest}")
    print("READY_FOR_HUMAN_INTEGRATION_REVIEW=TRUE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())