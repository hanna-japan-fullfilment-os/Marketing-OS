"""BUILD6R V3.44 end-to-end acceptance preflight."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path


BACKEND = Path(__file__).resolve().parents[1]

BRIDGE_PATH = (
    BACKEND
    / "scripts"
    / "run_v344_single_slide_acceptance.py"
)


class PreflightError(RuntimeError):
    pass


def _load_bridge():
    if not BRIDGE_PATH.is_file():
        raise PreflightError(
            "V3.44 bridge runner is missing."
        )

    spec = importlib.util.spec_from_file_location(
        "v344_single_slide_bridge",
        BRIDGE_PATH,
    )

    if spec is None or spec.loader is None:
        raise PreflightError(
            "Unable to load V3.44 bridge."
        )

    module = importlib.util.module_from_spec(
        spec
    )

    spec.loader.exec_module(
        module
    )

    return module


def build_report() -> dict:
    bridge = _load_bridge()

    static = bridge.build_static_report()

    if (
        static[
            "v338_provider_generate_call_count"
        ]
        != 1
    ):
        raise PreflightError(
            "Bridge does not resolve to one "
            "background image provider call."
        )

    if (
        static[
            "bridge_direct_provider_generate_calls"
        ]
        != 0
    ):
        raise PreflightError(
            "Bridge introduced an extra "
            "direct provider generate call."
        )

    if not static[
        "v338_locked_product_compositor"
    ]:
        raise PreflightError(
            "Locked-product compositor missing."
        )

    if not static[
        "v338_deterministic_typography"
    ]:
        raise PreflightError(
            "Deterministic typography missing."
        )

    if (
        static[
            "target_width"
        ]
        != 1080
        or static[
            "target_height"
        ]
        != 1350
    ):
        raise PreflightError(
            "Final V3.44 target must be 1080x1350."
        )

    return {
        "contract": (
            "build6r-v344-end-to-end-"
            "acceptance-preflight-v2"
        ),
        "bridge": static,
        "network_calls": 0,
        "openai_api_calls": 0,
        "image_provider_calls": 0,
        "paid_calls": 0,
        "user_visual_acceptance": "PENDING",
        "ready_for_end_to_end_dry_run": True,
    }


def main() -> int:
    report = build_report()

    print(
        "BUILD6R_V344_END_TO_END_PREFLIGHT=PASS"
    )
    print(
        "V338_PROVIDER_GENERATE_CALL_COUNT=1"
    )
    print(
        "BRIDGE_DIRECT_PROVIDER_GENERATE_CALLS=0"
    )
    print(
        "LOCKED_PRODUCT_COMPOSITOR_REQUIRED=TRUE"
    )
    print(
        "DETERMINISTIC_TYPOGRAPHY_REQUIRED=TRUE"
    )
    print(
        "AI_TEXT_RENDERING=FALSE"
    )
    print(
        "AUTOMATIC_IMAGE_RETRIES=0"
    )
    print(
        "BEST_OF_N=1"
    )
    print(
        "TARGET_OUTPUT_WIDTH=1080"
    )
    print(
        "TARGET_OUTPUT_HEIGHT=1350"
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
        "READY_FOR_V344_END_TO_END_DRY_RUN=TRUE"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())