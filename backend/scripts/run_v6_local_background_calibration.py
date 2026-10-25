"""Separately authorized local preview entrypoint; never a full-QA approval.

No paid provider is constructed. Source build does not invoke this command.
Runtime/model approval and actual preview execution require separate governance.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models import Campaign
from app.schemas.ai import SlidePlan
from app.schemas.creative_director import reference_target_from_brief
from app.services.ai.local_background_provider import BACKEND, MODEL, select_background_backend
from app.services.orchestrator import (
    _load_stage_json, _stage_language_variant, validate_slide_provenance, run_visuals_stage,
)
from app.services.settings_store import get_effective_settings
from app.api.campaigns import _build_autopilot_config
from scripts.run_live_acceptance import isolated_calibration_session


async def preview(*, backend, manifest, workflow, runtime_url, database, database_sha256,
                  campaign_id, output, seed):
    # Reject an unknown backend before source access; model/workflow validation
    # below still precedes HTTP construction and output creation.
    if backend != BACKEND:
        raise ValueError("Explicit local backend required; no fallback")
    output = Path(output).resolve()
    repo = Path(__file__).resolve().parents[2]
    if output.is_relative_to(repo) or output.exists():
        raise ValueError("New external preview output directory required")
    session = isolated_calibration_session(database, expected_sha256=database_sha256)
    try:
        campaign = session.get(Campaign, campaign_id)
        if (campaign is None or campaign.target_slide_count != 6
                or list(campaign.target_platforms) != ["instagram"] or list(campaign.languages) != ["pt-BR"]):
            raise ValueError("Six frozen Instagram/pt-BR plans required")
        creative = _stage_language_variant(_load_stage_json(session, campaign_id, "creative"), "pt-BR")
        plans = [SlidePlan.model_validate(raw) for raw in creative["carousel_plan"]["slides"]]
        if len(plans) != 6 or [p.slide_number for p in plans] != list(range(1, 7)):
            raise ValueError("Exact frozen six-slide scope required")
        for plan in plans:
            validate_slide_provenance(session, campaign, plan)
        target = reference_target_from_brief(plans[0].visual_brief)
        if target is None:
            raise ValueError("Owner reference contract required")
        provider = select_background_backend(backend, base_url=runtime_url,
            manifest_path=Path(manifest), workflow_path=Path(workflow),
            reference_id=target.reference_id, reference_sha256=target.sha256, seed=seed)
        settings = get_effective_settings(session)
        config = _build_autopilot_config(settings, str(output), use_ai_background=True,
            recreate_with_ai=False, detect_product_zone=False, quality_mode="premium",
            render_platform_variants=True, enable_qa_stage=False, qa_max_retries=0, qa_best_of_n=1)
        config.premium_image_model = MODEL
        config.max_slides = 6
        config.require_ai_background_success = True
        # No paid text/vision calls. Deterministic direction is resolved from the
        # same frozen grammar by the existing orchestrator, never a new proposal.
        output.mkdir(parents=True, exist_ok=False)
        from app.services.creative.renderer import PlaywrightRenderer
        await run_visuals_stage(session, campaign_id=campaign_id, renderer=PlaywrightRenderer(),
            config=config, image_provider=provider, ai_provider=None, calibration_slide1=True)
        if provider.provenance is None:
            raise ValueError("Missing local background provenance")
        report = {"status": "PREVIEW_ONLY", "campaign_id": campaign_id,
            "semantic_qa": "NOT_RUN", "owner_visual_acceptance": "PENDING",
            "campaign_approval_created": False, "full_qa_pass_claimed": False,
            "provider_calls": 0, "local_image_attempts": 1, "final_dimensions": [1080, 1350],
            "background_provenance": provider.provenance,
            "canonical_db_sha256": database_sha256.upper()}
        with (output / "v6-preview-evidence.json").open("x", encoding="utf-8") as stream:
            json.dump(report, stream, indent=2)
        return report
    finally:
        engine = session.bind
        session.close()
        engine.dispose()
        if hashlib.sha256(Path(database).read_bytes()).hexdigest().upper() != database_sha256.upper():
            raise ValueError("Canonical DB changed during preview; preserve all evidence")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("backend", "manifest", "workflow", "runtime-url", "database",
                 "database-sha256", "campaign-id", "output"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--seed", type=int, required=True)
    args = parser.parse_args()
    print(json.dumps(asyncio.run(preview(**vars(args))), indent=2))


if __name__ == "__main__":
    main()
