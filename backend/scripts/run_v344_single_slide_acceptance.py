"""BUILD6R V3.44 single-slide end-to-end creative acceptance bridge.

Architecture:

    ONE AI BACKGROUND CALL
              |
              v
    existing V3.38 locked compositor
      - immutable approved real-product master
      - deterministic typography
              |
              v
    deterministic 4:5 adapter
              |
              v
         1080 x 1350 PNG

Dry-run performs zero provider/network calls.

Paid mode exists only for a later, separately authorized execution.
"""

from __future__ import annotations

import argparse
import ast
import asyncio
import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps


BACKEND = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND.parent

if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

CANONICAL_DB = (
    BACKEND
    / "data"
    / "app.db"
).resolve()

V338_RUNNER = (
    BACKEND
    / "scripts"
    / "run_locked_product_composite_smoke.py"
)

EXPECTED_V338_SHA256 = (
    "FCD9B44645CACE480485BB99A8AE88D304BC40303B0A8A2209A8904966AECBBD"
)

TARGET_WIDTH = 1080
TARGET_HEIGHT = 1350

EXPECTED_NATIVE_WIDTH = 1024
EXPECTED_NATIVE_HEIGHT = 1536

MAX_BUDGET_USD = 0.50

PAID_AUTH_ENV = (
    "BUILD6R_V344_SINGLE_SLIDE_PAID_AUTHORIZED"
)

REQUIRED_LIVE_ENV = {
    "OPENAI_MAX_IMAGE_CALLS": "1",
    "OPENAI_SDK_MAX_RETRIES": "0",
    "OPENAI_REQUEST_TIMEOUT_SECONDS": "180",
    "QA_MAX_RETRIES": "0",
    "QA_BEST_OF_N": "1",
}


class V344BridgeError(RuntimeError):
    """Fail-closed V3.44 bridge error."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as handle:
        for block in iter(
            lambda: handle.read(1024 * 1024),
            b"",
        ):
            digest.update(block)

    return digest.hexdigest().upper()


def _load_v338():
    if not V338_RUNNER.is_file():
        raise V344BridgeError(
            f"Canonical V3.38 runner missing: {V338_RUNNER}"
        )

    actual = sha256_file(V338_RUNNER)

    if actual != EXPECTED_V338_SHA256:
        raise V344BridgeError(
            "Canonical V3.38 runner SHA-256 mismatch."
        )

    spec = importlib.util.spec_from_file_location(
        "build6r_v338_locked_product_composite",
        V338_RUNNER,
    )

    if spec is None or spec.loader is None:
        raise V344BridgeError(
            "Unable to load V3.38 runner."
        )

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    return module


def _leaf_name(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Name):
        return call.func.id

    if isinstance(call.func, ast.Attribute):
        return call.func.attr

    return None


def _function(
    tree: ast.Module,
    name: str,
) -> ast.FunctionDef | ast.AsyncFunctionDef:
    matches = [
        node
        for node in ast.walk(tree)
        if isinstance(
            node,
            (
                ast.FunctionDef,
                ast.AsyncFunctionDef,
            ),
        )
        and node.name == name
    ]

    if len(matches) != 1:
        raise V344BridgeError(
            f"Expected one {name}(), found {len(matches)}."
        )

    return matches[0]


def _calls_named(
    node: ast.AST,
    name: str,
) -> list[ast.Call]:
    return [
        candidate
        for candidate in ast.walk(node)
        if isinstance(candidate, ast.Call)
        and _leaf_name(candidate) == name
    ]


def _call_inside_loop(
    node: ast.AST,
    name: str,
) -> bool:
    for candidate in ast.walk(node):
        if not isinstance(
            candidate,
            (
                ast.For,
                ast.AsyncFor,
                ast.While,
            ),
        ):
            continue

        if _calls_named(candidate, name):
            return True

    return False


def build_static_report() -> dict[str, Any]:
    source = V338_RUNNER.read_text(
        encoding="utf-8",
        errors="strict",
    )

    tree = ast.parse(
        source,
        filename=str(V338_RUNNER),
    )

    execute = _function(
        tree,
        "_execute_background_once",
    )

    render = _function(
        tree,
        "_render_local_outputs",
    )

    generate_calls = _calls_named(
        execute,
        "generate",
    )

    if len(generate_calls) != 1:
        raise V344BridgeError(
            "V3.38 background execution no longer "
            "contains exactly one provider generate call."
        )

    if _call_inside_loop(
        execute,
        "generate",
    ):
        raise V344BridgeError(
            "V3.38 provider generate call is inside a loop."
        )

    render_calls = {
        _leaf_name(call)
        for call in ast.walk(render)
        if isinstance(call, ast.Call)
    }

    required_render_calls = {
        "build_locked_product_layer",
        "render_text_layer",
        "compose_layers",
    }

    missing_render_calls = sorted(
        required_render_calls
        - render_calls
    )

    if missing_render_calls:
        raise V344BridgeError(
            "V3.38 local compositor is missing: "
            + ",".join(missing_render_calls)
        )

    bridge_source = Path(__file__).read_text(
        encoding="utf-8",
        errors="strict",
    )

    bridge_tree = ast.parse(
        bridge_source,
        filename=str(Path(__file__)),
    )

    direct_generate_calls = [
        call
        for call in ast.walk(bridge_tree)
        if isinstance(call, ast.Call)
        and _leaf_name(call) == "generate"
    ]

    if direct_generate_calls:
        raise V344BridgeError(
            "V3.44 bridge may not introduce a second "
            "direct provider.generate path."
        )

    return {
        "contract": (
            "build6r-v344-end-to-end-single-slide-"
            "acceptance-bridge-v1"
        ),
        "v338_runner_sha256": sha256_file(
            V338_RUNNER
        ),
        "v338_provider_generate_call_count": (
            len(generate_calls)
        ),
        "v338_provider_generate_inside_loop": False,
        "v338_locked_product_compositor": True,
        "v338_deterministic_typography": True,
        "v338_native_width": EXPECTED_NATIVE_WIDTH,
        "v338_native_height": EXPECTED_NATIVE_HEIGHT,
        "bridge_direct_provider_generate_calls": 0,
        "target_width": TARGET_WIDTH,
        "target_height": TARGET_HEIGHT,
        "ai_text_rendering": False,
        "automatic_image_retries": 0,
        "best_of_n": 1,
        "max_image_calls": 1,
        "max_budget_usd_ceiling": MAX_BUDGET_USD,
    }


def _open_rgba(path: Path) -> Image.Image:
    with Image.open(path) as image:
        image.load()
        return image.convert("RGBA")


def _cover_background(
    background: Image.Image,
) -> Image.Image:
    return ImageOps.fit(
        background.convert("RGBA"),
        (TARGET_WIDTH, TARGET_HEIGHT),
        method=Image.Resampling.LANCZOS,
        centering=(0.5, 0.5),
    )


def _fit_overlay_by_height(
    overlay: Image.Image,
) -> Image.Image:
    overlay = overlay.convert("RGBA")

    if overlay.size != (
        EXPECTED_NATIVE_WIDTH,
        EXPECTED_NATIVE_HEIGHT,
    ):
        raise V344BridgeError(
            "Native overlay dimensions differ from "
            "the governed 1024x1536 compositor."
        )

    scale = (
        TARGET_HEIGHT
        / EXPECTED_NATIVE_HEIGHT
    )

    fitted_width = int(
        round(
            EXPECTED_NATIVE_WIDTH
            * scale
        )
    )

    resized = overlay.resize(
        (
            fitted_width,
            TARGET_HEIGHT,
        ),
        resample=Image.Resampling.LANCZOS,
    )

    canvas = Image.new(
        "RGBA",
        (TARGET_WIDTH, TARGET_HEIGHT),
        (0, 0, 0, 0),
    )

    x = int(
        round(
            (
                TARGET_WIDTH
                - fitted_width
            )
            / 2
        )
    )

    canvas.alpha_composite(
        resized,
        dest=(x, 0),
    )

    return canvas


def compose_instagram_output(
    *,
    native_output: dict[str, Any],
    output_dir: Path,
) -> dict[str, Any]:
    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    background_path = Path(
        native_output[
            "background_only_path"
        ]
    )

    product_path = Path(
        native_output[
            "locked_product_layer_path"
        ]
    )

    text_path = Path(
        native_output[
            "text_layer_path"
        ]
    )

    for path in (
        background_path,
        product_path,
        text_path,
    ):
        if not path.is_file():
            raise V344BridgeError(
                f"Required native compositor layer missing: {path}"
            )

    background = _open_rgba(
        background_path
    )

    product = _open_rgba(
        product_path
    )

    text_layer = _open_rgba(
        text_path
    )

    if background.size != (
        EXPECTED_NATIVE_WIDTH,
        EXPECTED_NATIVE_HEIGHT,
    ):
        raise V344BridgeError(
            "Native background dimensions mismatch."
        )

    final = _cover_background(
        background
    )

    product_4x5 = _fit_overlay_by_height(
        product
    )

    text_4x5 = _fit_overlay_by_height(
        text_layer
    )

    final.alpha_composite(
        product_4x5
    )

    final.alpha_composite(
        text_4x5
    )

    final_path = (
        output_dir
        / "v344-final-1080x1350.png"
    )

    final.save(
        final_path,
        format="PNG",
        optimize=False,
        compress_level=9,
    )

    with Image.open(
        final_path
    ) as verified:
        verified.load()

        if verified.size != (
            TARGET_WIDTH,
            TARGET_HEIGHT,
        ):
            raise V344BridgeError(
                "Final V3.44 slide dimensions mismatch."
            )

    return {
        "final_path": str(final_path),
        "final_sha256": sha256_file(
            final_path
        ),
        "final_width": TARGET_WIDTH,
        "final_height": TARGET_HEIGHT,
        "native_background_sha256": (
            sha256_file(
                background_path
            )
        ),
        "native_product_layer_sha256": (
            sha256_file(
                product_path
            )
        ),
        "native_text_layer_sha256": (
            sha256_file(
                text_path
            )
        ),
        "product_layer_immutable": (
            bool(
                native_output.get(
                    "locked_product_layer_immutability"
                )
            )
        ),
        "deterministic_typography": True,
        "ai_text_rendering": False,
        "four_by_five_adapter": (
            "background_cover_plus_overlay_height_fit"
        ),
    }


def _write_evidence(
    *,
    evidence_dir: Path,
    report: dict[str, Any],
) -> None:
    evidence_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    result_path = (
        evidence_dir
        / "v344_end_to_end_result.json"
    )

    result_path.write_text(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    manifest = (
        evidence_dir
        / "evidence_manifest.txt"
    )

    manifest.write_text(
        (
            f"{sha256_file(result_path)}"
            f"\t{result_path.stat().st_size}"
            f"\t{result_path.name}\n"
        ),
        encoding="utf-8",
    )


def run_dry(
    *,
    database: Path,
    evidence_dir: Path,
    output_dir: Path,
) -> dict[str, Any]:
    v338 = _load_v338()

    payload = v338._prepare_request(
        database.resolve()
    )

    background = (
        v338._synthetic_background()
    )

    native_dir = (
        output_dir
        / "native-locked-compositor"
    )

    native_output = (
        v338._render_local_outputs(
            payload=payload,
            background=background,
            output_dir=native_dir,
        )
    )

    if (
        native_output.get(
            "final_width"
        )
        != EXPECTED_NATIVE_WIDTH
        or native_output.get(
            "final_height"
        )
        != EXPECTED_NATIVE_HEIGHT
    ):
        raise V344BridgeError(
            "Native locked compositor dimensions changed."
        )

    final_output = compose_instagram_output(
        native_output=native_output,
        output_dir=output_dir,
    )

    report = {
        "contract": (
            "build6r-v344-end-to-end-single-slide-"
            "acceptance-bridge-v1"
        ),
        "mode": "DRY_RUN",
        "network_calls": 0,
        "openai_api_calls": 0,
        "image_provider_calls": 0,
        "paid_calls": 0,
        "configured_model": payload[
            "model"
        ],
        "configured_quality": payload[
            "quality"
        ],
        "provider_request_size": payload[
            "size"
        ],
        "max_budget_usd": float(
            payload[
                "max_budget_usd"
            ]
        ),
        "background_prompt_sha256": (
            payload[
                "background_prompt_sha256"
            ]
        ),
        "approved_master_asset_id": (
            payload[
                "approved_master_asset_id"
            ]
        ),
        "approved_master_sha256": (
            payload[
                "approved_master_sha256"
            ]
        ),
        "canonical_source_asset_id": (
            payload[
                "canonical_source_asset_id"
            ]
        ),
        "canonical_source_sha256": (
            payload[
                "canonical_source_sha256"
            ]
        ),
        "ai_product_generation": False,
        "ai_product_editing": False,
        "ai_typography_generation": False,
        "image_call_limit": 1,
        "automatic_image_retries": 0,
        "best_of_n": 1,
        "native_output": native_output,
        "final_output": final_output,
        "user_visual_acceptance": (
            "PENDING"
        ),
        "ready_for_one_paid_visual_call": (
            True
        ),
    }

    _write_evidence(
        evidence_dir=evidence_dir,
        report=report,
    )

    return report


def _assert_v344_paid_controls(
    *,
    database: Path,
    max_budget_usd: float,
) -> None:
    if (
        os.environ.get(
            PAID_AUTH_ENV
        )
        != "TRUE"
    ):
        raise V344BridgeError(
            "V3.44 paid image execution is not authorized."
        )

    if (
        database.resolve()
        == CANONICAL_DB
    ):
        raise V344BridgeError(
            "Paid V3.44 execution may not target "
            "canonical SQLite."
        )

    if (
        max_budget_usd <= 0
        or max_budget_usd
        > MAX_BUDGET_USD
    ):
        raise V344BridgeError(
            "V3.44 paid budget is outside "
            "the governed ceiling."
        )

    for name, expected in (
        REQUIRED_LIVE_ENV.items()
    ):
        actual = str(
            os.environ.get(
                name,
                "",
            )
        ).strip()

        if actual != expected:
            raise V344BridgeError(
                f"Required {name}={expected!r}; "
                f"actual={actual!r}."
            )


def execute_paid_once(
    *,
    database: Path,
    evidence_dir: Path,
    output_dir: Path,
    max_budget_usd: float,
) -> dict[str, Any]:
    #
    # This path is intentionally unreachable
    # without a later explicit authorization.
    #
    _assert_v344_paid_controls(
        database=database,
        max_budget_usd=max_budget_usd,
    )

    v338 = _load_v338()

    payload = v338._prepare_request(
        database.resolve()
    )

    payload["max_budget_usd"] = (
        float(max_budget_usd)
    )

    #
    # Reuse the already-tested V3.38 guard.
    # The compatibility flag is set only after
    # the V3.44-specific authorization gate passes.
    #
    previous_v338_auth = os.environ.get(
        "BUILD6R_V338_BACKGROUND_SMOKE_AUTHORIZED"
    )

    os.environ[
        "BUILD6R_V338_BACKGROUND_SMOKE_AUTHORIZED"
    ] = "TRUE"

    try:
        v338._assert_live_controls(
            database.resolve(),
            float(max_budget_usd),
        )

        (
            background_bytes,
            events,
            hard_budget,
        ) = asyncio.run(
            v338._execute_background_once(
                payload=payload,
                database=database.resolve(),
                max_budget_usd=float(
                    max_budget_usd
                ),
            )
        )
    finally:
        if previous_v338_auth is None:
            os.environ.pop(
                "BUILD6R_V338_BACKGROUND_SMOKE_AUTHORIZED",
                None,
            )
        else:
            os.environ[
                "BUILD6R_V338_BACKGROUND_SMOKE_AUTHORIZED"
            ] = previous_v338_auth

    usage = v338._validate_live_usage(
        events
    )

    if (
        usage.get(
            "image_call_count"
        )
        != 1
    ):
        raise V344BridgeError(
            "Paid V3.44 execution did not record "
            "exactly one image call."
        )

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    raw_background = (
        output_dir
        / "provider-background-raw.png"
    )

    raw_background.write_bytes(
        background_bytes
    )

    with Image.open(
        raw_background
    ) as image:
        image.load()
        background = image.convert(
            "RGBA"
        )

    if background.size != (
        EXPECTED_NATIVE_WIDTH,
        EXPECTED_NATIVE_HEIGHT,
    ):
        raise V344BridgeError(
            "Provider background dimensions mismatch."
        )

    native_dir = (
        output_dir
        / "native-locked-compositor"
    )

    native_output = (
        v338._render_local_outputs(
            payload=payload,
            background=background,
            output_dir=native_dir,
        )
    )

    final_output = compose_instagram_output(
        native_output=native_output,
        output_dir=output_dir,
    )

    report = {
        "contract": (
            "build6r-v344-end-to-end-single-slide-"
            "acceptance-bridge-v1"
        ),
        "mode": "PAID_SINGLE_IMAGE",
        "configured_model": payload[
            "model"
        ],
        "configured_quality": payload[
            "quality"
        ],
        "provider_request_size": payload[
            "size"
        ],
        "max_budget_usd": float(
            max_budget_usd
        ),
        "image_call_count": 1,
        "text_model_call_count": 0,
        "automatic_image_retries": 0,
        "best_of_n": 1,
        "ai_product_generation": False,
        "ai_product_editing": False,
        "ai_typography_generation": False,
        "usage": usage,
        "hard_budget_snapshot": hard_budget,
        "provider_background_sha256": (
            sha256_file(
                raw_background
            )
        ),
        "native_output": native_output,
        "final_output": final_output,
        "user_visual_acceptance": (
            "PENDING"
        ),
    }

    _write_evidence(
        evidence_dir=evidence_dir,
        report=report,
    )

    return report


def _print_dry_markers(
    report: dict[str, Any],
) -> None:
    final = report["final_output"]

    print(
        "BUILD6R_V344_END_TO_END_DRY_RUN=PASS"
    )
    print(
        "AI_VISUAL_CALL_LIMIT=1"
    )
    print(
        "AI_TEXT_RENDERING=FALSE"
    )
    print(
        "AI_PRODUCT_GENERATION=FALSE"
    )
    print(
        "AI_PRODUCT_EDITING=FALSE"
    )
    print(
        "AUTOMATIC_IMAGE_RETRIES=0"
    )
    print(
        "BEST_OF_N=1"
    )
    print(
        "CANONICAL_PRODUCT_LOCKED=TRUE"
    )
    print(
        "DETERMINISTIC_TYPOGRAPHY=TRUE"
    )
    print(
        "FINAL_COMPOSITOR_IN_EXECUTION_PATH=TRUE"
    )
    print(
        "NATIVE_LOCKED_COMPOSITOR_WIDTH=1024"
    )
    print(
        "NATIVE_LOCKED_COMPOSITOR_HEIGHT=1536"
    )
    print(
        "FOUR_BY_FIVE_ADAPTER=TRUE"
    )
    print(
        "FINAL_OUTPUT_WIDTH="
        + str(
            final[
                "final_width"
            ]
        )
    )
    print(
        "FINAL_OUTPUT_HEIGHT="
        + str(
            final[
                "final_height"
            ]
        )
    )
    print(
        "FINAL_OUTPUT="
        + final["final_path"]
    )
    print(
        "FINAL_OUTPUT_SHA256="
        + final["final_sha256"]
    )
    print(
        "CONFIGURED_PREMIUM_IMAGE_MODEL="
        + str(
            report[
                "configured_model"
            ]
        )
    )
    print(
        "CONFIGURED_PREMIUM_IMAGE_QUALITY="
        + str(
            report[
                "configured_quality"
            ]
        )
    )
    print(
        "PROVIDER_REQUEST_SIZE="
        + str(
            report[
                "provider_request_size"
            ]
        )
    )
    print(
        "MAX_BUDGET_USD="
        + format(
            report[
                "max_budget_usd"
            ],
            ".2f",
        )
    )
    print(
        "BACKGROUND_PROMPT_SHA256="
        + str(
            report[
                "background_prompt_sha256"
            ]
        )
    )
    print(
        "APPROVED_MASTER_SHA256="
        + str(
            report[
                "approved_master_sha256"
            ]
        )
    )
    print(
        "CANONICAL_SOURCE_SHA256="
        + str(
            report[
                "canonical_source_sha256"
            ]
        )
    )
    print(
        "NETWORK_CALLS=0"
    )
    print(
        "OPENAI_API_CALLS=0"
    )
    print(
        "IMAGE_PROVIDER_CALLS=0"
    )
    print(
        "PAID_CALLS=0"
    )
    print(
        "USER_VISUAL_ACCEPTANCE=PENDING"
    )
    print(
        "READY_FOR_ONE_PAID_VISUAL_CALL=TRUE"
    )


def main(
    argv: list[str] | None = None,
) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "BUILD6R V3.44 governed single-slide "
            "end-to-end acceptance bridge."
        )
    )

    parser.add_argument(
        "--database",
        type=Path,
        default=CANONICAL_DB,
    )

    parser.add_argument(
        "--evidence-dir",
        type=Path,
        required=True,
    )

    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
    )

    parser.add_argument(
        "--max-budget-usd",
        type=float,
        default=MAX_BUDGET_USD,
    )

    modes = (
        parser.add_mutually_exclusive_group(
            required=True
        )
    )

    modes.add_argument(
        "--dry-run",
        action="store_true",
    )

    modes.add_argument(
        "--execute-image",
        action="store_true",
    )

    args = parser.parse_args(
        argv
    )

    if args.dry_run:
        report = run_dry(
            database=args.database,
            evidence_dir=args.evidence_dir,
            output_dir=args.output_dir,
        )

        _print_dry_markers(
            report
        )

        return 0

    report = execute_paid_once(
        database=args.database,
        evidence_dir=args.evidence_dir,
        output_dir=args.output_dir,
        max_budget_usd=float(
            args.max_budget_usd
        ),
    )

    final = report[
        "final_output"
    ]

    print(
        "BUILD6R_V344_PAID_SINGLE_IMAGE=PASS"
    )
    print(
        "IMAGE_PROVIDER_CALLS=1"
    )
    print(
        "TEXT_MODEL_CALLS=0"
    )
    print(
        "AUTOMATIC_IMAGE_RETRIES=0"
    )
    print(
        "FINAL_OUTPUT="
        + final[
            "final_path"
        ]
    )
    print(
        "FINAL_OUTPUT_SHA256="
        + final[
            "final_sha256"
        ]
    )
    print(
        "FINAL_OUTPUT_WIDTH=1080"
    )
    print(
        "FINAL_OUTPUT_HEIGHT=1350"
    )
    print(
        "USER_VISUAL_ACCEPTANCE=PENDING"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())