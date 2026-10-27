from typing import Literal, Optional

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.middleware.access import Access
from app.middleware.auth import (
    get_access,
    get_audit_context,
    get_current_branch,
    require_permission,
    require_station_item_permission,
)
from app.middleware.rate_limit import limiter
from app.db.models import Order, User
from app.config.settings import settings
from app.shared.audit import AuditContext
from app.shared.clock import StoreDateTime
from app.shared.exceptions import ForbiddenException, NotFoundException
from app.shared.idempotency import run_idempotent

from .schemas import (
    CheckoutRequest,
    CheckoutResponse,
    OrderCancel,
    OrderCreate,
    OrderCreationResponse,
    OrderListResponse,
    OrderResponse,
    OrderStatusUpdate,
    OrderTrackingTokenReplaceResponse,
    ReceiptResponse,
    OrderItemStatusUpdate,
    StationItemsListResponse,
    StationItemUpdateResponse,
    OrderTrackingUpdate,
)
from .service import OrderService

router = APIRouter()


#: Sees every order of a branch; without it, only one's own (orders.user_id).
READ_BRANCH = "orders.read_branch"


def _ensure_may_read(access: Access, order: Order) -> None:
    """orders.read at the order's branch, and either orders.read_branch there or
    the caller created the order; else 404."""
    access.ensure_at("orders.read", order.branch_id, "Order")
    if order.user_id != access.user_id and not access.can_at(READ_BRANCH, order.branch_id):
        raise NotFoundException(detail="Order not found")


def _scoped_order(db: Session, access: Access, reference: str | int, code: str) -> Order:
    """The order of the caller's organization, if ``code`` is held at its branch; else 404.
    Reading (``orders.read``) also needs the order to be the caller's, or READ_BRANCH."""
    order = OrderService.get_order_by_reference(db=db, org_id=access.org_id, reference=str(reference))
    if code == "orders.read":
        _ensure_may_read(access, order)
    else:
        access.ensure_at(code, order.branch_id, "Order")
    return order


@router.post("/", response_model=OrderCreationResponse)
def create_order(
    request: Request,
    body: OrderCreate,
    user: User = Depends(require_permission("orders.create")),
    branch_id: int = Depends(get_current_branch),
    access: Access = Depends(get_access),
    audit: AuditContext = Depends(get_audit_context),
    db: Session = Depends(get_db),
) -> OrderCreationResponse:
    """Needs an Idempotency-Key (app/shared/idempotency.py); a replay shows
    the tracking token as null (it is shown once)."""

    def run() -> OrderCreationResponse:
        order, tracking_token = OrderService.create_order(
            db=db,
            org_id=user.organization_id,
            branch_id=branch_id,
            user_id=user.id,
            data=body.model_dump(),
            request_id=getattr(request.state, "request_id", ""),
            can_discount=access.can_at("orders.discount", branch_id),
            audit=audit,
        )
        order_response = OrderResponse.model_validate(order)
        return OrderCreationResponse(
            **order_response.model_dump(), tracking_token=tracking_token
        )

    return run_idempotent(request, db, user.id, body, run, secret_fields=("tracking_token",))


@router.post(
    "/{order_id}/tracking-token",
    response_model=OrderTrackingTokenReplaceResponse,
)
def replace_order_tracking_token(
    order_id: int,
    user: User = Depends(require_permission("orders.update", scope="any")),
    access: Access = Depends(get_access),
    db: Session = Depends(get_db),
) -> OrderTrackingTokenReplaceResponse:
    """Replace an order's public tracking token (staff).

    Requires the ``orders.update`` permission and is organization scoped.
    The previous token hash is overwritten (last write wins); the new
    plaintext token is returned once and never persisted.
    """
    _scoped_order(db, access, order_id, "orders.update")
    order, tracking_token = OrderService.replace_tracking_token(
        db=db,
        org_id=user.organization_id,
        order_id=order_id,
    )
    return OrderTrackingTokenReplaceResponse(
        order_id=order.id,
        tracking_token=tracking_token,
    )


@router.get("/", response_model=OrderListResponse)
def list_orders(
    user: User = Depends(require_permission("orders.read")),
    branch_id: int = Depends(get_current_branch),
    access: Access = Depends(get_access),
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    status: Optional[str] = None,
    date_from: Optional[StoreDateTime] = None,
    date_to: Optional[StoreDateTime] = None,
    date_field: Literal["created_at", "paid_at"] = Query(
        "created_at", description="What date_from/date_to compare: when the order was made or paid"
    ),
    customer_id: Optional[int] = None,
    user_filter: Optional[int] = Query(None, alias="user_id"),
) -> OrderListResponse:
    if not access.can(READ_BRANCH, branch_id):
        if user_filter is not None and user_filter != user.id:
            raise ForbiddenException(detail=f"Missing required permission: {READ_BRANCH}")
        user_filter = user.id
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
        date_field=date_field,
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
    user: User = Depends(require_permission("orders.read", scope="any")),
    access: Access = Depends(get_access),
    db: Session = Depends(get_db),
) -> OrderResponse:
    """Get an order by its integer id or its alphanumeric order number."""
    order = _scoped_order(db, access, reference, "orders.read")
    return OrderResponse.model_validate(order)


@router.get("/{reference}/receipt", response_model=ReceiptResponse)
def get_order_receipt(
    reference: str,
    user: User = Depends(require_permission("orders.read", scope="any")),
    access: Access = Depends(get_access),
    db: Session = Depends(get_db),
) -> ReceiptResponse:
    order = _scoped_order(db, access, reference, "orders.read")
    receipt = OrderService.get_receipt(db=db, org_id=user.organization_id, order_id=order.id)
    return ReceiptResponse(**receipt)


@router.put("/{order_id}/status", response_model=OrderResponse)
def update_order_status(
    order_id: int,
    body: OrderStatusUpdate,
    user: User = Depends(require_permission("orders.update", scope="any")),
    access: Access = Depends(get_access),
    db: Session = Depends(get_db),
) -> OrderResponse:
    _scoped_order(db, access, order_id, "orders.update")
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
    request: Request,
    order_id: int,
    body: OrderCancel,
    user: User = Depends(require_permission(("orders.cancel", "orders.create"), scope="any")),
    access: Access = Depends(get_access),
    audit: AuditContext = Depends(get_audit_context),
    db: Session = Depends(get_db),
) -> OrderResponse:
    """orders.cancel at the order's branch: any unpaid order there, a ready
    one with a reason (38c). orders.create alone (a cashier): only the
    caller's own unpaid orders, not ready ones (Phase 38b)."""
    order = OrderService.get_order_by_reference(db=db, org_id=access.org_id, reference=str(order_id))
    may_cancel_any = access.can_at("orders.cancel", order.branch_id)
    if not may_cancel_any:
        access.ensure_at("orders.create", order.branch_id, "Order")
    order = OrderService.cancel_order(
        db=db,
        org_id=user.organization_id,
        order_id=order_id,
        user_id=user.id,
        request_id=getattr(request.state, "request_id", ""),
        may_cancel_any=may_cancel_any,
        reason=body.reason,
        audit=audit,
    )
    return OrderResponse.model_validate(order)


@router.put("/{order_id}/complete", response_model=OrderResponse)
def complete_order(
    order_id: int,
    user: User = Depends(require_permission("orders.complete", scope="any")),
    access: Access = Depends(get_access),
    db: Session = Depends(get_db),
) -> OrderResponse:
    _scoped_order(db, access, order_id, "orders.complete")
    order = OrderService.complete_order(
        db=db,
        org_id=user.organization_id,
        order_id=order_id,
    )
    return OrderResponse.model_validate(order)


@router.put("/{order_id}/tracking", response_model=OrderResponse)
def update_order_tracking(
    order_id: int,
    body: OrderTrackingUpdate,
    user: User = Depends(require_permission("orders.update", scope="any")),
    access: Access = Depends(get_access),
    db: Session = Depends(get_db),
) -> OrderResponse:
    _scoped_order(db, access, order_id, "orders.update")
    order = OrderService.update_tracking(
        db=db,
        org_id=user.organization_id,
        order_id=order_id,
        tracking_number=body.tracking_number,
        fulfillment_status=body.fulfillment_status,
    )
    return OrderResponse.model_validate(order)


@router.get("/track/{tracking_or_ref}")
@limiter.limit(settings.RATE_LIMIT_ORDER_TRACKING)
def track_order(
    request: Request,
    tracking_or_ref: str,
    user: User = Depends(require_permission("orders.read", scope="any")),
    access: Access = Depends(get_access),
    db: Session = Depends(get_db),
) -> dict:
    """Staff tracking: authenticated, scoped to the caller's organization."""
    from sqlalchemy import select

    from app.db.models import Order

    order = db.scalar(
        select(Order).where(
            Order.organization_id == user.organization_id,
            (Order.tracking_number == tracking_or_ref)
            | (Order.order_number == tracking_or_ref),
        )
    )
    if not order:
        raise NotFoundException(detail="Order not found")
    _ensure_may_read(access, order)

    return {
        "order_number": order.order_number,
        "status": order.status,
        "fulfillment_status": order.fulfillment_status,
        "tracking_number": order.tracking_number,
        "created_at": order.created_at,
        "completed_at": order.completed_at,
    }


@router.get("/track/public/{token}")
@limiter.limit(settings.RATE_LIMIT_ORDER_TRACKING)
def track_order_public(
    request: Request, token: str, db: Session = Depends(get_db)
) -> dict:
    """Public customer tracking by unguessable capability token. No auth."""
    from sqlalchemy import select

    from app.db.models import Order

    token_hash = OrderService.hash_tracking_token(token)
    order = db.scalar(
        select(Order).where(Order.tracking_token_hash == token_hash)
    )
    if not order:
        from app.shared.exceptions import NotFoundException
        raise NotFoundException(detail="Order not found")

    return {
        "order_number": order.order_number,
        "status": order.status,
        "fulfillment_status": order.fulfillment_status,
        "tracking_number": order.tracking_number,
        "created_at": order.created_at,
        "completed_at": order.completed_at,
    }


@router.post("/{order_id}/checkout", response_model=CheckoutResponse)
def checkout_order(
    request: Request,
    order_id: int,
    body: CheckoutRequest,
    user: User = Depends(require_permission("payments.create", scope="any")),
    access: Access = Depends(get_access),
    db: Session = Depends(get_db),
) -> CheckoutResponse:
    """Needs an Idempotency-Key (app/shared/idempotency.py)."""
    _scoped_order(db, access, order_id, "payments.create")

    def run() -> CheckoutResponse:
        order = OrderService.checkout_order(
            db=db,
            org_id=user.organization_id,
            order_id=order_id,
            user_id=user.id,
            data=body.model_dump(),
            request_id=getattr(request.state, "request_id", ""),
        )
        return CheckoutResponse.model_validate(order)

    return run_idempotent(request, db, user.id, body, run)


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
