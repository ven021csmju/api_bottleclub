from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    Branch,
    LoyaltyTransaction,
    Order,
    OrderItem,
    Payment,
    StockMovement,
)
from app.db.repositories.loyalty import LoyaltyRepository
from app.db.repositories.orders import OrderRepository
from app.db.repositories.payments import PaymentRepository
from app.shared.exceptions import (
    BadRequestException,
    InsufficientStockException,
    InvalidOrderStateException,
    NotFoundException,
)
from app.shared.ordering import generate_order_number


class OrderService:
    #: Legal forward transitions for the order workflow / kitchen-bar queue.
    #: ``cancelled`` is handled separately (allowed from any non-terminal status).
    VALID_TRANSITIONS: dict[str, set[str]] = {
        "pending": {"confirmed"},
        "confirmed": {"preparing", "ready"},
        "preparing": {"ready"},
        "ready": {"completed"},
        "paid": {"completed"},
        "completed": set(),
        "cancelled": set(),
    }

    #: Statuses from which cancellation (with stock restore) is allowed.
    CANCELLABLE_STATUSES = {"pending", "confirmed", "preparing"}

    @staticmethod
    def _validate_status(value: str) -> None:
        from app.shared.enums import OrderStatus

        if value not in {s.value for s in OrderStatus}:
            raise BadRequestException(
                detail=f"Invalid order status: '{value}'",
                code="VALIDATION_ERROR",
            )

    @staticmethod
    def _assert_transition(current: str, target: str) -> None:
        allowed = OrderService.VALID_TRANSITIONS.get(current, set())
        if target not in allowed:
            raise InvalidOrderStateException(
                detail=f"Cannot transition order status from '{current}' to '{target}'"
            )

    @staticmethod
    def create_order(
        db: Session,
        org_id: int,
        branch_id: int,
        user_id: int,
        data: dict,
    ) -> Order:
        idempotency_key = data.get("idempotency_key")
        if idempotency_key:
            existing = OrderRepository.find_by_idempotency_key(
                db, org_id, idempotency_key
            )
            if existing:
                return existing

        branch = OrderRepository.get_branch(db, org_id, branch_id)
        if not branch:
            raise NotFoundException(detail="Branch not found")

        product_ids = [item["product_id"] for item in data["items"]]
        products = OrderRepository.get_products_by_ids(db, org_id, product_ids)
        products_map = {p.id: p for p in products}

        missing = set(product_ids) - set(products_map.keys())
        if missing:
            raise BadRequestException(detail=f"Products not found or inactive: {missing}")

        order_number = generate_order_number(db, branch.code)

        order = Order(
            organization_id=org_id,
            branch_id=branch_id,
            order_number=order_number,
            status="pending",
            customer_id=data.get("customer_id"),
            user_id=user_id,
            shift_id=data.get("shift_id"),
            register_id=data.get("register_id"),
            discount_amount=Decimal(str(data.get("discount_amount", 0))),
            notes=data.get("notes"),
            idempotency_key=idempotency_key,
        )
        OrderRepository.add_order(db, order)

        subtotal = Decimal("0")
        order_items = []

        stations = OrderRepository.get_stations_for_products(
            db, org_id, product_ids
        )

        for item_data in data["items"]:
            product = products_map[item_data["product_id"]]
            quantity = item_data["quantity"]
            unit_price = Decimal(str(item_data["unit_price"]))
            item_discount = Decimal(str(item_data.get("discount_amount", 0)))
            line_total = unit_price * quantity - item_discount

            order_item = OrderItem(
                order_id=order.id,
                product_id=product.id,
                product_name=product.name,
                product_sku=product.sku,
                quantity=quantity,
                unit_price=unit_price,
                cost_price=None,
                discount_amount=item_discount,
                tax_amount=Decimal("0"),
                line_total=line_total,
                station=stations.get(product.id, "kitchen"),
                item_status="pending",
            )
            order_items.append(order_item)
            OrderRepository.add_order_item(db, order_item)
            subtotal += line_total

            if product.track_inventory:
                on_hand_before = OrderRepository.get_inventory_on_hand(
                    db, branch_id, product.id
                )
                rowcount = OrderRepository.deduct_stock(
                    db, branch_id, product.id, quantity
                )
                if rowcount == 0:
                    raise InsufficientStockException(
                        detail=f"Insufficient stock for product '{product.name}' (id={product.id})"
                    )

                OrderRepository.add_stock_movement(
                    db,
                    StockMovement(
                        branch_id=branch_id,
                        product_id=product.id,
                        movement_type="sale",
                        quantity_change=-quantity,
                        quantity_before=on_hand_before,
                        quantity_after=on_hand_before - quantity,
                        reference_type="order",
                        reference_id=order.id,
                        user_id=user_id,
                    ),
                )

        discount = Decimal(str(data.get("discount_amount", 0)))
        grand_total = subtotal - discount

        order.subtotal = subtotal
        order.tax_amount = Decimal("0")
        order.grand_total = grand_total
        order.amount_paid = Decimal("0")
        order.change_amount = Decimal("0")

        db.flush()
        db.commit()
        db.refresh(order)
        return order

    @staticmethod
    def list_orders(
        db: Session,
        org_id: int,
        branch_id: int | None = None,
        page: int = 1,
        per_page: int = 20,
        status: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        customer_id: int | None = None,
        user_id: int | None = None,
    ) -> dict:
        items, total = OrderRepository.list_orders(
            db, org_id, branch_id, page, per_page, status,
            date_from, date_to, customer_id, user_id,
        )

        return {
            "orders": items,
            "total": total,
            "page": page,
            "per_page": per_page,
        }

    @staticmethod
    def get_order(db: Session, org_id: int, order_id: int) -> Order:
        order = OrderRepository.get_org_order(db, org_id, order_id)
        if not order:
            raise NotFoundException(detail="Order not found")
        return order

    @staticmethod
    def get_order_by_reference(db: Session, org_id: int, reference: str) -> Order:
        """Fetch an order by either its integer id or its alphanumeric number."""
        if reference.isdigit():
            order = OrderRepository.get_org_order(db, org_id, int(reference))
        else:
            order = OrderRepository.get_org_order_by_number(db, org_id, reference)
        if not order:
            raise NotFoundException(detail="Order not found")
        return order

    @staticmethod
    def get_receipt(db: Session, org_id: int, order_id: int) -> dict:
        order = OrderService.get_order(db, org_id, order_id)

        branch = db.execute(
            select(Branch).where(Branch.id == order.branch_id)
        ).scalar_one_or_none()

        payments = list(
            db.scalars(select(Payment).where(Payment.order_id == order.id))
        )

        return {
            "order": {
                "id": order.id,
                "order_number": order.order_number,
                "status": order.status,
                "created_at": order.created_at,
                "completed_at": order.completed_at,
                "branch_id": order.branch_id,
                "branch_name": branch.name if branch else None,
                "register_id": order.register_id,
                "shift_id": order.shift_id,
                "customer_id": order.customer_id,
                "subtotal": order.subtotal,
                "discount_amount": order.discount_amount,
                "tax_amount": order.tax_amount,
                "grand_total": order.grand_total,
                "amount_paid": order.amount_paid,
                "change_amount": order.change_amount,
                "loyalty_points_earned": order.loyalty_points_earned,
                "loyalty_points_redeemed": order.loyalty_points_redeemed,
                "items": [
                    {
                        "product_id": i.product_id,
                        "product_name": i.product_name,
                        "product_sku": i.product_sku,
                        "quantity": i.quantity,
                        "unit_price": i.unit_price,
                        "discount_amount": i.discount_amount,
                        "tax_amount": i.tax_amount,
                        "line_total": i.line_total,
                    }
                    for i in order.items
                ],
            },
            "payments": [
                {
                    "id": p.id,
                    "payment_method": p.payment_method,
                    "amount": p.amount,
                    "status": p.status,
                    "external_reference": p.external_reference,
                    "provider": p.provider,
                    "created_at": p.created_at,
                }
                for p in payments
            ],
        }

    @staticmethod
    def cancel_order(db: Session, org_id: int, order_id: int, user_id: int) -> Order:
        order = OrderRepository.get_org_order(db, org_id, order_id)

        if not order:
            raise NotFoundException(detail="Order not found")
        if order.status not in OrderService.CANCELLABLE_STATUSES:
            raise InvalidOrderStateException(
                detail=f"Cannot cancel order in '{order.status}' status"
            )

        for item in order.items:
            product = OrderRepository.get_product(db, item.product_id)

            if product and product.track_inventory:
                on_hand_before = OrderRepository.get_inventory_on_hand(
                    db, order.branch_id, item.product_id
                )
                OrderRepository.restore_stock(db, order.branch_id, item.product_id, item.quantity)

                OrderRepository.add_stock_movement(
                    db,
                    StockMovement(
                        branch_id=order.branch_id,
                        product_id=item.product_id,
                        movement_type="adjustment",
                        quantity_change=item.quantity,
                        quantity_before=on_hand_before,
                        quantity_after=on_hand_before + item.quantity,
                        reference_type="order",
                        reference_id=order.id,
                        notes="Order cancelled – stock restored",
                        user_id=user_id,
                    ),
                )

        order.status = "cancelled"
        order.cancelled_at = datetime.now(timezone.utc)
        db.flush()
        db.commit()
        db.refresh(order)
        return order

    #: Statuses from which checkout (settlement) is allowed.
    CHECKOUTABLE_STATUSES = {"pending", "confirmed", "preparing", "ready", "held"}

    #: 1 loyalty point = 1 Baht of credit applied toward the order total.
    POINTS_VALUE_PER_BAHT = 1
    #: Loyalty points earned per Baht of net spend at checkout.
    POINTS_EARN_PER_BAHT = 1

    @staticmethod
    def checkout_order(
        db: Session,
        org_id: int,
        order_id: int,
        user_id: int,
        data: dict,
    ) -> Order:
        """Settle an order in a single transaction.

        Applies optional loyalty-point redemption (as a discount), records
        payments, updates the order's paid/change amounts, awards loyalty
        points on the net spend and marks the order ``paid``. Everything is
        flushed once and committed atomically — either all of it persists or
        none of it does.

        Re-submitting with the same request for an already-settled order is a
        no-op (idempotent), so a client retry cannot double-charge.
        """
        idempotency_key = data.get("idempotency_key")

        order = OrderRepository.get_org_order(db, org_id, order_id)
        if not order:
            raise NotFoundException(detail="Order not found")

        # Idempotency: an already-settled order is the success result of a
        # previous attempt, so return it unchanged instead of charging again.
        if idempotency_key and order.status in ("paid", "completed", "refunded"):
            return order

        if order.status not in OrderService.CHECKOUTABLE_STATUSES:
            raise InvalidOrderStateException(
                detail=f"Cannot checkout order in '{order.status}' status"
            )

        customer = None
        if order.customer_id is not None:
            customer = LoyaltyRepository.find_org_customer(db, org_id, order.customer_id)
            if customer is None:
                raise NotFoundException(detail="Customer not found")

        # ---- Loyalty redemption (points as discount) ----
        redeem_points = int(data.get("redeem_points") or 0)
        redeemed = 0
        if redeem_points > 0:
            if customer is None:
                raise BadRequestException(
                    detail="Cannot redeem points without a customer on the order"
                )
            if customer.loyalty_points_balance < redeem_points:
                raise BadRequestException(
                    detail=(
                        f"Insufficient points. Available: "
                        f"{customer.loyalty_points_balance}, requested: {redeem_points}"
                    )
                )
            max_credit = int(order.grand_total) // OrderService.POINTS_VALUE_PER_BAHT
            redeemed = min(redeem_points, max_credit)
            if redeemed == 0:
                raise BadRequestException(detail="Points do not cover any amount due")

            before = customer.loyalty_points_balance
            after = before - redeemed
            LoyaltyRepository.add_transaction(
                db,
                LoyaltyTransaction(
                    customer_id=order.customer_id,
                    transaction_type="redeem",
                    points=-redeemed,
                    points_before=before,
                    points_after=after,
                    reference_type="order",
                    reference_id=order.id,
                    notes="Points redeemed at checkout",
                    user_id=user_id,
                ),
            )
            customer.loyalty_points_balance = after
            order.loyalty_points_redeemed = redeemed

        due = order.grand_total - Decimal(redeemed)

        # ---- Payments ----
        payments = data.get("payments") or []
        if not payments:
            raise BadRequestException(detail="At least one payment is required")

        paid_total = Decimal("0")
        for pay in payments:
            amount = Decimal(str(pay["amount"]))
            if amount <= 0:
                raise BadRequestException(detail="Payment amount must be positive")
            payment = Payment(
                order_id=order.id,
                payment_method=pay["payment_method"],
                amount=amount,
                status="completed",
                external_reference=pay.get("external_reference"),
                notes=pay.get("notes"),
                received_by=user_id,
            )
            PaymentRepository.add_payment(db, payment)
            paid_total += amount

        if paid_total < due:
            raise BadRequestException(
                detail=f"Payments ({paid_total}) less than amount due ({due})"
            )

        order.amount_paid = paid_total
        order.change_amount = paid_total - due

        # ---- Loyalty earn on net spend ----
        points_earned = 0
        if customer is not None and redeemed < int(order.grand_total):
            spend_whole = int(due)
            points_earned = (
                spend_whole // OrderService.POINTS_EARN_PER_BAHT
                if OrderService.POINTS_EARN_PER_BAHT
                else spend_whole
            )
            if points_earned > 0:
                before = customer.loyalty_points_balance
                after = before + points_earned
                LoyaltyRepository.add_transaction(
                    db,
                    LoyaltyTransaction(
                        customer_id=order.customer_id,
                        transaction_type="earn",
                        points=points_earned,
                        points_before=before,
                        points_after=after,
                        reference_type="order",
                        reference_id=order.id,
                        notes="Points earned at checkout",
                        user_id=user_id,
                    ),
                )
                customer.loyalty_points_balance = after
                order.loyalty_points_earned = points_earned

        order.status = "paid"

        db.flush()
        db.commit()
        db.refresh(order)
        return order

    @staticmethod
    def complete_order(db: Session, org_id: int, order_id: int) -> Order:
        order = OrderRepository.get_org_order(db, org_id, order_id)

        if not order:
            raise NotFoundException(detail="Order not found")
        # Backward-compatible: allow completing straight from pending (POS flow),
        # from the queue's ready state, or after checkout (paid).
        if order.status not in ("pending", "ready", "paid"):
            raise InvalidOrderStateException(
                detail=f"Cannot complete order in '{order.status}' status"
            )
        if order.amount_paid < order.grand_total:
            raise BadRequestException(
                detail="Order is not fully paid"
            )

        order.status = "completed"
        order.completed_at = datetime.now(timezone.utc)
        db.flush()
        db.commit()
        db.refresh(order)
        return order

    @staticmethod
    def update_status(
        db: Session,
        org_id: int,
        order_id: int,
        target_status: str,
        user_id: int | None = None,
    ) -> Order:
        """Advance an order through the workflow (pending -> ... -> completed).

        Cancellation must still go through ``cancel_order`` which restores stock.
        """
        OrderService._validate_status(target_status)
        order = OrderRepository.get_org_order(db, org_id, order_id)

        if not order:
            raise NotFoundException(detail="Order not found")
        if target_status == "cancelled":
            raise BadRequestException(
                detail="Use POST /orders/{id}/cancel to cancel an order (restores stock)"
            )

        OrderService._assert_transition(order.status, target_status)

        order.status = target_status
        if target_status == "completed":
            if order.amount_paid < order.grand_total:
                raise BadRequestException(detail="Order is not fully paid")
            order.completed_at = datetime.now(timezone.utc)
        db.flush()
        db.commit()
        db.refresh(order)
        return order

    # ------------------------------------------------------------------
    # Kitchen / Bar (KDS) — per-item station workflow
    # ------------------------------------------------------------------
    ITEM_STATUS_TRANSITIONS: dict[str, set[str]] = {
        "pending": {"preparing", "cancelled"},
        "preparing": {"ready", "cancelled"},
        "ready": {"served"},
        "served": set(),
        "cancelled": set(),
    }

    @staticmethod
    def _validate_item_status(value: str) -> None:
        from app.shared.enums import ItemStatus

        if value not in {s.value for s in ItemStatus}:
            raise BadRequestException(
                detail=f"Invalid item status: '{value}'",
                code="VALIDATION_ERROR",
            )

    @staticmethod
    def update_item_status(
        db: Session,
        org_id: int,
        order_id: int,
        run_id: int,
        target_status: str,
        user_id: int | None = None,
    ) -> OrderItem:
        """Advance a single item's status within a station workflow.

        ``run_id`` is the id of the :class:`OrderItem` being worked on by the
        kitchen or bar station.
        """
        OrderService._validate_item_status(target_status)
        order = OrderRepository.get_org_order(db, org_id, order_id)
        if not order:
            raise NotFoundException(detail="Order not found")

        item = next(
            (i for i in order.items if i.id == run_id),
            None,
        )
        if item is None:
            raise NotFoundException(detail="Order item not found")

        allowed = OrderService.ITEM_STATUS_TRANSITIONS.get(item.item_status, set())
        if target_status not in allowed:
            raise InvalidOrderStateException(
                detail=(
                    f"Cannot transition item '{item.id}' from "
                    f"'{item.item_status}' to '{target_status}'"
                )
            )

        item.item_status = target_status
        db.flush()
        db.commit()
        db.refresh(item)
        return item

    @staticmethod
    def list_station_items(
        db: Session,
        org_id: int,
        station: str,
        branch_id: int | None = None,
        item_status: str | None = None,
        page: int = 1,
        per_page: int = 20,
    ) -> tuple[list[tuple[Order, OrderItem]], int]:
        """List open orders' items that belong to a given station (kitchen/bar)."""
        return OrderRepository.list_station_items(
            db,
            org_id,
            station,
            branch_id=branch_id,
            item_status=item_status,
            page=page,
            per_page=per_page,
        )

    @staticmethod
    def _build_station_response(
        result: tuple[list[tuple[Order, OrderItem]], int],
        page: int,
        per_page: int,
    ) -> dict:
        rows, total = result
        orders = {}
        for order, item in rows:
            bucket = orders.setdefault(order.id, {"order": order, "items": []})
            bucket["items"].append(item)
        return {
            "orders": [
                {
                    "id": order.id,
                    "order_id": order.id,
                    "order_number": order.order_number,
                    "branch_id": order.branch_id,
                    "status": order.status,
                    "notes": order.notes,
                    "created_at": order.created_at,
                    "items": [
                        {
                            "id": it.id,
                            "product_id": it.product_id,
                            "product_name": it.product_name,
                            "product_sku": it.product_sku,
                            "quantity": it.quantity,
                            "station": it.station,
                            "item_status": it.item_status,
                            "line_total": it.line_total,
                        }
                        for it in bucket["items"]
                    ],
                }
                for bucket in orders.values()
            ],
            "total": total,
            "page": page,
            "per_page": per_page,
        }