from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.middleware.auth import (
    get_current_branch,
    require_permission,
    require_station_item_permission,
)
from app.db.models import User

from .schemas import (
    CheckoutRequest,
    CheckoutResponse,
    OrderCancel,
    OrderCreate,
    OrderListResponse,
    OrderResponse,
    OrderStatusUpdate,
    ReceiptResponse,
    OrderItemStatusUpdate,
    StationItemsListResponse,
    StationItemUpdateResponse,
)
from .service import OrderService

router = APIRouter()


@router.post("/", response_model=OrderResponse)
def create_order(
    body: OrderCreate,
    user: User = Depends(require_permission("orders.create")),
    branch_id: int = Depends(get_current_branch),
    db: Session = Depends(get_db),
) -> OrderResponse:
    order = OrderService.create_order(
        db=db,
        org_id=user.organization_id,
        branch_id=branch_id,
        user_id=user.id,
        data=body.model_dump(),
    )
    return OrderResponse.model_validate(order)


@router.get("/", response_model=OrderListResponse)
def list_orders(
    user: User = Depends(require_permission("orders.read")),
    branch_id: int = Depends(get_current_branch),
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    status: Optional[str] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    customer_id: Optional[int] = None,
    user_filter: Optional[int] = Query(None, alias="user_id"),
) -> OrderListResponse:
    result = OrderService.list_orders(
        db=db,
        org_id=user.organization_id,
        branch_id=branch_id,
        page=page,
        per_page=per_page,
        status=status,
        date_from=date_from,
        date_to=date_to,
        customer_id=customer_id,
        user_id=user_filter,
    )
    return OrderListResponse(
        orders=[OrderResponse.model_validate(o) for o in result["orders"]],
        total=result["total"],
        page=result["page"],
        per_page=result["per_page"],
    )


@router.get("/{reference}", response_model=OrderResponse)
def get_order(
    reference: str,
    user: User = Depends(require_permission("orders.read")),
    db: Session = Depends(get_db),
) -> OrderResponse:
    """Get an order by its integer id or its alphanumeric order number."""
    order = OrderService.get_order_by_reference(
        db=db,
        org_id=user.organization_id,
        reference=reference,
    )
    return OrderResponse.model_validate(order)


@router.get("/{reference}/receipt", response_model=ReceiptResponse)
def get_order_receipt(
    reference: str,
    user: User = Depends(require_permission("orders.read")),
    db: Session = Depends(get_db),
) -> ReceiptResponse:
    order = OrderService.get_order_by_reference(
        db=db,
        org_id=user.organization_id,
        reference=reference,
    )
    receipt = OrderService.get_receipt(db=db, org_id=user.organization_id, order_id=order.id)
    return ReceiptResponse(**receipt)


@router.put("/{order_id}/status", response_model=OrderResponse)
def update_order_status(
    order_id: int,
    body: OrderStatusUpdate,
    user: User = Depends(require_permission("orders.update")),
    db: Session = Depends(get_db),
) -> OrderResponse:
    order = OrderService.update_status(
        db=db,
        org_id=user.organization_id,
        order_id=order_id,
        target_status=body.status,
        user_id=user.id,
    )
    return OrderResponse.model_validate(order)


@router.post("/{order_id}/cancel", response_model=OrderResponse)
def cancel_order(
    order_id: int,
    body: OrderCancel,
    user: User = Depends(require_permission("orders.cancel")),
    db: Session = Depends(get_db),
) -> OrderResponse:
    order = OrderService.cancel_order(
        db=db,
        org_id=user.organization_id,
        order_id=order_id,
        user_id=user.id,
    )
    return OrderResponse.model_validate(order)


@router.put("/{order_id}/complete", response_model=OrderResponse)
def complete_order(
    order_id: int,
    user: User = Depends(require_permission("orders.complete")),
    db: Session = Depends(get_db),
) -> OrderResponse:
    order = OrderService.complete_order(
        db=db,
        org_id=user.organization_id,
        order_id=order_id,
    )
    return OrderResponse.model_validate(order)


@router.post("/{order_id}/checkout", response_model=CheckoutResponse)
def checkout_order(
    order_id: int,
    body: CheckoutRequest,
    user: User = Depends(require_permission("payments.create")),
    db: Session = Depends(get_db),
) -> CheckoutResponse:
    order = OrderService.checkout_order(
        db=db,
        org_id=user.organization_id,
        order_id=order_id,
        user_id=user.id,
        data=body.model_dump(),
    )
    return CheckoutResponse.model_validate(order)


# ---------------------------------------------------------------------------
# Kitchen / Bar (KDS)
# ---------------------------------------------------------------------------
@router.get("/station/kitchen", response_model=StationItemsListResponse)
def list_kitchen_orders(
    user: User = Depends(require_permission("kds.kitchen.read")),
    branch_id: int = Depends(get_current_branch),
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    item_status: Optional[str] = None,
) -> StationItemsListResponse:
    result = OrderService.list_station_items(
        db, user.organization_id, "kitchen", branch_id=branch_id,
        item_status=item_status, page=page, per_page=per_page,
    )
    return OrderService._build_station_response(result, page, per_page)


@router.get("/station/bar", response_model=StationItemsListResponse)
def list_bar_orders(
    user: User = Depends(require_permission("kds.bar.read")),
    branch_id: int = Depends(get_current_branch),
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    item_status: Optional[str] = None,
) -> StationItemsListResponse:
    result = OrderService.list_station_items(
        db, user.organization_id, "bar", branch_id=branch_id,
        item_status=item_status, page=page, per_page=per_page,
    )
    return OrderService._build_station_response(result, page, per_page)


@router.patch("/{order_id}/station-items/{run_id}/status", response_model=StationItemUpdateResponse)
def update_station_item_status(
    order_id: int,
    run_id: int,
    body: OrderItemStatusUpdate,
    user: User = Depends(require_station_item_permission),
    db: Session = Depends(get_db),
) -> StationItemUpdateResponse:
    item = OrderService.update_item_status(
        db, user.organization_id, order_id, run_id, body.item_status, user.id,
    )
    return StationItemUpdateResponse.model_validate(item)
