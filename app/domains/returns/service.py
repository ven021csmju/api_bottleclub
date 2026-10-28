from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.orm import Session

from app.db.models import Inventory, Order, Refund, Return, ReturnItem, StockMovement
from app.db.repositories.returns import ReturnRepository
from app.domains.shifts.drawer import current_shift, paid_net, payment_methods, refunded
from app.services import user_events
from app.shared.exceptions import (
    BadRequestException,
    InvalidOrderStateException,
    NotFoundException,
)
from app.shared.money import CENT, prorate
from app.shared.ordering import generate_refund_number, generate_return_number

#: Orders whose money has been taken; only these can be returned.
PAID_STATUSES = ("paid", "completed")


def _ensure_paid(order: Order) -> None:
    if order.status not in PAID_STATUSES:
        raise BadRequestException(
            detail=f"Only a paid order can be returned (this one is '{order.status}')", code="ORDER_NOT_PAID"
        )


def _check_quantities(items: list[tuple[int, int]], order_items: dict, returned: dict[int, int]) -> None:
    """``items``: (order_item_id, quantity) of one return, against what is left to return."""
    wanted: dict[int, int] = {}
    for item_id, qty in items:
        wanted[item_id] = wanted.get(item_id, 0) + qty
    for item_id, qty in wanted.items():
        left = order_items[item_id].quantity - returned.get(item_id, 0)
        if qty > left:
            raise BadRequestException(
                detail=f"Order item {item_id}: {qty} to return, {left} left to return",
                code="RETURN_QUANTITY_EXCEEDED",
            )


class ReturnService:
    @staticmethod
    def create_return(
        db: Session,
        org_id: int,
        branch_id: int,
        user_id: int,
        data: dict,
        request_id: str = "",
    ) -> Return:
        """A return waiting for approval: nothing is refunded or restocked yet
        (see ``process_return``)."""
        order = ReturnRepository.get_org_order(db, org_id, data["order_id"])

        if not order:
            raise NotFoundException(detail="Order not found")
        _ensure_paid(order)

        order_items = {oi.id: oi for oi in ReturnRepository.list_order_items(db, order.id)}
        for item_data in data["items"]:
            order_item = order_items.get(item_data["order_item_id"])
            if not order_item:
                raise NotFoundException(
                    detail=f"Order item {item_data['order_item_id']} not found"
                )
            if order_item.product_id != item_data["product_id"]:
                raise BadRequestException(
                    detail="Product id does not match order item"
                )
        _check_quantities([(i["order_item_id"], i["quantity"]) for i in data["items"]], order_items,
                          ReturnRepository.returned_quantities(db, order.id))

        # What one unit refunds: what its line was really paid (the order's
        # payments spread over the lines, as the reports spread discounts),
        # divided by the line's quantity.
        line_paid = dict(zip(order_items, prorate(
            paid_net(db, order.id), [oi.line_total for oi in order_items.values()])))

        ret = Return(
            organization_id=org_id,
            order_id=order.id,
            branch_id=branch_id,
            return_number=generate_return_number(db),
            status="pending",
            processed_by=user_id,
            reason=data.get("reason"),
        )
        ReturnRepository.add_return(db, ret)
        for item_data in data["items"]:
            order_item = order_items[item_data["order_item_id"]]
            unit = (line_paid[order_item.id] / order_item.quantity).quantize(CENT, rounding=ROUND_HALF_UP)
            ReturnRepository.add_return_item(db, ReturnItem(
                return_id=ret.id,
                order_item_id=order_item.id,
                product_id=item_data["product_id"],
                quantity=item_data["quantity"],
                return_reason=item_data.get("return_reason"),
                restock=item_data.get("restock", False),
                unit_price=unit,
            ))

        db.flush()
        db.commit()
        db.refresh(ret)
        # Emitted after the transaction committed; never raises.
        user_events.publish_user_event_sync(
            "return_created",
            user_id,
            request_id,
            {"order_id": order.id, "return_id": ret.id},
        )
        return ret

    @staticmethod
    def list_returns(
        db: Session,
        org_id: int,
        branch_id: int | None = None,
        page: int = 1,
        per_page: int = 20,
    ) -> dict:
        items, total = ReturnRepository.list_returns(
            db, org_id, branch_id, page, per_page
        )

        return {
            "returns": items,
            "total": total,
            "page": page,
            "per_page": per_page,
        }

    @staticmethod
    def get_return(db: Session, return_id: int) -> Return:
        ret = ReturnRepository.get_return(db, return_id)

        if not ret:
            raise NotFoundException(detail="Return not found")
        return ret

    @staticmethod
    def process_return(
        db: Session,
        return_id: int,
        user_id: int,
        refund_method: str = "original",
    ) -> Return:
        """Approve a pending return: restock and refund, all at once.

        The order is locked first, so two returns (or a return and a refund)
        of one order are processed one after the other and each sees what the
        other already returned and refunded."""
        ret = ReturnRepository.get_return(db, return_id)

        if not ret:
            raise NotFoundException(detail="Return not found")
        order = ReturnRepository.lock_org_order(db, ret.organization_id, ret.order_id)
        db.refresh(ret)

        if ret.status != "pending":
            raise InvalidOrderStateException(
                detail=f"Cannot process return in '{ret.status}' status"
            )
        _ensure_paid(order)
        order_items = {oi.id: oi for oi in ReturnRepository.list_order_items(db, order.id)}
        _check_quantities([(i.order_item_id, i.quantity) for i in ret.items], order_items,
                          ReturnRepository.returned_quantities(db, order.id))

        amount = sum((Decimal(str(i.unit_price)) * i.quantity for i in ret.items), Decimal("0"))
        left = paid_net(db, order.id) - refunded(db, order.id)
        if amount > 0 and left <= 0:
            raise BadRequestException(detail="The order has been refunded in full", code="REFUND_EXCEEDS_PAID")
        amount = min(amount, left)  # rounding of the unit shares

        if amount > 0 and refund_method == "original":
            methods = payment_methods(db, order.id)
            if len(methods) != 1:
                raise BadRequestException(
                    detail=f"The order was paid by {sorted(methods)}: send refund_method",
                    code="REFUND_METHOD_REQUIRED",
                )
            refund_method = methods.pop()

        for item in ret.items:
            if not item.restock:
                continue
            inv = ReturnRepository.get_inventory(db, ret.branch_id, item.product_id)
            on_hand_before = inv.on_hand if inv else 0
            if inv:
                inv.on_hand += item.quantity
            else:
                ReturnRepository.add_inventory(db, Inventory(
                    branch_id=ret.branch_id, product_id=item.product_id, on_hand=item.quantity, reserved=0))
            ReturnRepository.add_stock_movement(db, StockMovement(
                branch_id=ret.branch_id,
                product_id=item.product_id,
                movement_type="return",
                quantity_change=item.quantity,
                quantity_before=on_hand_before,
                quantity_after=on_hand_before + item.quantity,
                reference_type="return",
                reference_id=ret.id,
                user_id=user_id,
            ))

        if amount > 0:
            shift = current_shift(db, ret.branch_id, user_id, order.register_id, order.shift_id)
            refund = Refund(
                order_id=order.id,
                refund_number=generate_refund_number(db),
                refund_amount=amount,
                refund_method=refund_method,
                status="completed",
                processed_by=user_id,
                reason=ret.reason,
                shift_id=shift.id if shift else None,
            )
            ReturnRepository.add_refund(db, refund)
            ret.refund_id = refund.id

        ret.status = "completed"
        ret.processed_by = user_id
        db.flush()
        db.commit()
        db.refresh(ret)
        return ret
