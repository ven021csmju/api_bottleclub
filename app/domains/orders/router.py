from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from database.database import get_db
from app.middleware.auth import get_current_branch, require_permission
from database.models import User

from .schemas import (
    OrderCreate,
    OrderListResponse,
    OrderResponse,
    OrderStatusUpdate,
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


@router.get("/{order_id}", response_model=OrderResponse)
def get_order(
    order_id: int,
    user: User = Depends(require_permission("orders.read")),
    db: Session = Depends(get_db),
) -> OrderResponse:
    order = OrderService.get_order(
        db=db,
        org_id=user.organization_id,
        order_id=order_id,
    )
    return OrderResponse.model_validate(order)


@router.put("/{order_id}/status", response_model=OrderResponse)
def cancel_order(
    order_id: int,
    body: OrderStatusUpdate,
    user: User = Depends(require_permission("orders.cancel")),
    db: Session = Depends(get_db),
) -> OrderResponse:
    if body.status != "cancelled":
        from app.shared.exceptions import BadRequestException
        raise BadRequestException(detail="Only cancellation is supported via this endpoint")
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
