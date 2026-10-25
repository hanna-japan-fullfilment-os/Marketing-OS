"""Governed source-vs-render product asset selection."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from ..models.asset import Asset
from .product_master_contract import (
    APPROVED_PRODUCT_MASTER_ROLE,
    CANDIDATE_PRODUCT_MASTER_ROLE,
    evaluate_reconstructed_product_master,
)


RECONSTRUCTED_MASTER_ROLES = (
    CANDIDATE_PRODUCT_MASTER_ROLE,
    APPROVED_PRODUCT_MASTER_ROLE,
)


def _scope_query(
    db: Session,
    *,
    brand_id: str,
    category_id: str | None,
    product_id: str | None,
):
    query = db.query(
        Asset
    ).filter(
        Asset.brand_id == brand_id,
        Asset.is_active.is_(True),
    )

    if product_id:
        query = query.filter(
            Asset.product_id == product_id
        )
    elif category_id:
        query = query.filter(
            Asset.category_id == category_id
        )

    return query


def select_source_assets(
    db: Session,
    *,
    brand_id: str,
    category_id: str | None,
    product_id: str | None,
    limit: int,
) -> list[Asset]:
    """Source-truth assets only; reconstructed master roles are excluded."""

    if limit <= 0:
        return []

    query = _scope_query(
        db,
        brand_id=brand_id,
        category_id=category_id,
        product_id=product_id,
    )

    query = query.filter(
        Asset.image_role.notin_(
            RECONSTRUCTED_MASTER_ROLES
        )
    )

    query = query.order_by(
        Asset.times_used.asc(),
        Asset.last_used_at.asc(),
    )

    return query.limit(
        limit
    ).all()


def choose_approved_product_master(
    candidates: list[Any],
    *,
    source_lookup: Callable[
        [str],
        Any | None,
    ],
) -> Any | None:
    """Return the first master that passes the complete fail-closed contract."""

    for candidate in candidates:

        if (
            getattr(
                candidate,
                "image_role",
                "",
            )
            != APPROVED_PRODUCT_MASTER_ROLE
        ):
            continue

        metadata = getattr(
            candidate,
            "ai_metadata",
            None,
        )

        if not isinstance(
            metadata,
            dict,
        ):
            continue

        source_asset_id = str(
            metadata.get(
                "source_asset_id"
            )
            or ""
        ).strip()

        if not source_asset_id:
            continue

        source = source_lookup(
            source_asset_id
        )

        if source is None:
            continue

        result = (
            evaluate_reconstructed_product_master(
                candidate=candidate,
                source=source,
            )
        )

        if result.eligible:
            return candidate

    return None


def select_render_assets(
    db: Session,
    *,
    brand_id: str,
    category_id: str | None,
    product_id: str | None,
    limit: int,
) -> list[Asset]:
    """Approved master first for one product; canonical source otherwise."""

    if limit <= 0:
        return []

    if not product_id:
        return select_source_assets(
            db,
            brand_id=brand_id,
            category_id=category_id,
            product_id=None,
            limit=limit,
        )

    approved_candidates = (
        _scope_query(
            db,
            brand_id=brand_id,
            category_id=None,
            product_id=product_id,
        )
        .filter(
            Asset.image_role
            == APPROVED_PRODUCT_MASTER_ROLE
        )
        .order_by(
            Asset.updated_at.desc(),
            Asset.created_at.desc(),
            Asset.id.asc(),
        )
        .all()
    )

    approved = choose_approved_product_master(
        approved_candidates,
        source_lookup=lambda asset_id: db.get(
            Asset,
            asset_id,
        ),
    )

    if approved is not None:
        return [
            approved
        ]

    return select_source_assets(
        db,
        brand_id=brand_id,
        category_id=category_id,
        product_id=product_id,
        limit=limit,
    )


def resolve_authentic_package_mark_permission(db, campaign, render_asset_id):
    """Read an exact approval from the real source; never infer inheritance."""
    import hashlib
    from pathlib import Path
    from ..schemas.qa import AuthenticPackageMarkPermission
    render = db.get(Asset, render_asset_id, populate_existing=True)
    if render is None:
        raise ValueError("Package-mark render asset missing")
    metadata = render.ai_metadata or {}
    source = (db.get(Asset, metadata.get("source_asset_id"), populate_existing=True)
              if render.image_role == APPROVED_PRODUCT_MASTER_ROLE else render)
    if source is None:
        raise ValueError("Package-mark source missing")
    source_metadata = source.ai_metadata or {}
    if "authentic_package_mark_permissions" not in source_metadata:
        return None
    raw = source_metadata["authentic_package_mark_permissions"]
    if not isinstance(raw, list) or len(raw) > 100:
        raise ValueError("Malformed package-mark permission list")
    entries = [AuthenticPackageMarkPermission.model_validate(p) for p in raw]
    keys = [(p.campaign_id, p.render_asset_id) for p in entries]
    if len(set(keys)) != len(keys):
        raise ValueError("Duplicate package-mark approval scope")
    matching = [p for p in entries if p.campaign_id == campaign.id and p.render_asset_id == render.id]
    if not matching:
        return None
    permission = matching[0]
    if (permission.brand_id != campaign.brand_id or permission.product_id != campaign.product_id
            or render.brand_id != campaign.brand_id or render.product_id != campaign.product_id
            or source.brand_id != render.brand_id or source.product_id != render.product_id
            or permission.source_asset_id != source.id or permission.source_sha256 != source.sha256
            or permission.render_sha256 != render.sha256 or not source.is_active or not render.is_active
            or source.image_role != "product" or source_metadata.get("ai_generated") is not False):
        raise ValueError("Package-mark identity/authenticity mismatch")
    if render is not source and choose_approved_product_master([render], source_lookup=lambda key: db.get(Asset, key)) is None:
        raise ValueError("Package-mark master approval missing")
    if render is source and render.image_role != "product":
        raise ValueError("Package-mark product role mismatch")
    for asset in (source, render):
        if hashlib.sha256(Path(asset.absolute_path).read_bytes()).hexdigest() != asset.sha256:
            raise ValueError("Package-mark asset bytes changed")
    return permission if permission.status == "APPROVED" else None
