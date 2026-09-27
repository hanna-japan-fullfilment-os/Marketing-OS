"""Verified Product Facts endpoints (Build 1, Part A). Deliberately a separate
router from the `/api/products` list/create endpoints in `api/brands.py` (which
predate this and aren't being reorganized this round) — every route here is
scoped under an existing product id.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Product, VerifiedProductFact
from ..schemas.product_facts import VerifiedProductFactsOut, VerifiedProductFactsUpdate
from ..services.product_facts import get_or_none, resolve_verified_product_facts

router = APIRouter(prefix="/api/products", tags=["products"])


@router.get("/{product_id}/verified-facts", response_model=VerifiedProductFactsOut)
def get_verified_product_facts(product_id: str, db: Session = Depends(get_db)):
    product = db.get(Product, product_id)
    if product is None:
        raise HTTPException(404, "Product not found.")
    return resolve_verified_product_facts(db, product)


@router.put("/{product_id}/verified-facts", response_model=VerifiedProductFactsOut)
def update_verified_product_facts(
    product_id: str, payload: VerifiedProductFactsUpdate, db: Session = Depends(get_db)
):
    """Upserts the owner-editable row for this product. Only fields actually
    present in the request body are touched (`model_fields_set`), same
    partial-update discipline as `PATCH /api/brands/{id}` and `PATCH /api/
    campaigns/{id}` — a client updating just the price doesn't have to resend
    everything else.
    """
    product = db.get(Product, product_id)
    if product is None:
        raise HTTPException(404, "Product not found.")

    row = get_or_none(db, product_id)
    if row is None:
        row = VerifiedProductFact(product_id=product_id)
        db.add(row)

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(row, field, value)

    db.commit()
    db.refresh(row)
    return resolve_verified_product_facts(db, product)
