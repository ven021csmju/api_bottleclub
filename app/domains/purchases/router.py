from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.domains.purchases.schemas import (
    PurchaseOrderCreate,
    PurchaseOrderResponse,
    PurchaseOrderStatusUpdate,
    PurchaseOrderUpdate,
    PurchaseReceivingCreate,
    PurchaseReceivingResponse,
)
from app.domains.purchases.service import PurchaseService
from app.middleware.auth import require_permission
from app.db.models import User

router = APIRouter()


@router.get("", response_model=list[PurchaseOrderResponse])
def list_purchase_orders(
    page: int = 1,
    per_page: int = 20,
    status: Optional[str] = None,
    supplier_id: Optional[int] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("purchases.read")),
):
    result = PurchaseService.list_purchase_orders(
        db, user.organization_id, page, per_page, status, supplier_id, date_from, date_to
    )
    return result.purchase_orders


@router.get("/{po_id}", response_model=PurchaseOrderResponse)
def get_purchase_order(
    po_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("purchases.read")),
):
    po = PurchaseService.get_purchase_order(db, user.organization_id, po_id)
    return PurchaseService._build_po_response(po, db)


@router.post("", response_model=PurchaseOrderResponse, status_code=201)
def create_purchase_order(
    data: PurchaseOrderCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("purchases.create")),
):
    po = PurchaseService.create_purchase_order(
        db, user.organization_id, user.id, data
    )
    return PurchaseService._build_po_response(po, db)


@router.put("/{po_id}", response_model=PurchaseOrderResponse)
def update_purchase_order(
    po_id: int,
    data: PurchaseOrderUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("purchases.create")),
):
    po = PurchaseService.update_purchase_order(
        db, user.organization_id, po_id, data
    )
    return PurchaseService._build_po_response(po, db)


@router.post("/{po_id}/approve", response_model=PurchaseOrderResponse)
def approve_purchase_order(
    po_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("purchases.approve")),
):
    po = PurchaseService.approve_purchase_order(
        db, user.organization_id, po_id, user.id
    )
    return PurchaseService._build_po_response(po, db)


@router.post("/{po_id}/receive", response_model=PurchaseReceivingResponse)
def receive_purchase_order(
    po_id: int,
    data: PurchaseReceivingCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("purchases.receive")),
):
    po = PurchaseService.get_purchase_order(db, user.organization_id, po_id)
    receiving = PurchaseService.receive_purchase_order(
        db=db,
        org_id=user.organization_id,
        po_id=po_id,
        branch_id=po.branch_id,
        data=data,
        user_id=user.id,
    )
    return receiving


@router.post("/{po_id}/cancel", response_model=PurchaseOrderResponse)
def cancel_purchase_order(
    po_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("purchases.create")),
):
    po = PurchaseService.cancel_purchase_order(
        db, user.organization_id, po_id, user.id
    )
    return PurchaseService._build_po_response(po, db)
