from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import secrets

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
from app.db.repositories.coupons import CouponRepository
from app.db.repositories.loyalty import LoyaltyRepository
from app.db.repositories.orders import OrderRepository
from app.db.repositories.payments import PaymentRepository
from app.services import user_events
from app.shared.audit import AuditContext, log_audit
from app.shared.exceptions import (
    AppException,
    BadRequestException,
    ConflictException,
    ForbiddenException,
    InsufficientStockException,
    InvalidOrderStateException,
    NotFoundException,
    UnprocessableException,
)
from app.domains.coupons.service import CouponService
from app.domains.shifts.drawer import (
    CASH, amount_due, attach_to_shift, current_shift, is_fully_paid, order_drawer, paid_net,
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
    #: Not yet paid: a parked (held) or ready order can be cancelled too (38b).
    CANCELLABLE_STATUSES = {"pending", "confirmed", "preparing", "held"}
    PAID_STATUSES = {"paid", "completed", "refunded"}

    @staticmethod
    def _validate_status(value: str) -> None:
        from app.shared.enums import OrderStatus

        if value not in {s.value for s in OrderStatus}:
            raise BadRequestException(
                detail=f"Invalid order status: '{value}'",
                code="VALIDATION_ERROR",
            )

    @staticmethod
    def _order_source_value(value) -> str:
        from app.shared.enums import OrderSource

        if isinstance(value, OrderSource):
            return value.value
        return value

    @staticmethod
    def _assert_transition(current: str, target: str) -> None:
        allowed = OrderService.VALID_TRANSITIONS.get(current, set())
        if target not in allowed:
            raise InvalidOrderStateException(
                detail=f"Cannot transition order status from '{current}' to '{target}'"
            )

    @staticmethod
    def generate_tracking_token() -> str:
        """Cryptographically unpredictable public tracking capability token."""
        return secrets.token_urlsafe(32)

    @staticmethod
    def hash_tracking_token(token: str) -> str:
        """SHA-256 digest of a tracking token; never the plaintext."""
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    @staticmethod
    def _check_discounts(data: dict, products_map: dict, can_discount: bool) -> None:
        """Typed-in discounts: only with orders.discount, never above the line
        (catalog price x quantity) or the bill (after the line discounts)."""
        item_discounts = [Decimal(str(i.get("discount_amount") or 0)) for i in data["items"]]
        order_discount = Decimal(str(data.get("discount_amount") or 0))
        if (order_discount > 0 or any(d > 0 for d in item_discounts)) and not can_discount:
            raise ForbiddenException(
                detail="Missing required permission: orders.discount", code="DISCOUNT_NOT_ALLOWED"
            )
        subtotal = Decimal("0")
        for item, discount in zip(data["items"], item_discounts):
            line = Decimal(str(products_map[item["product_id"]].selling_price)) * item["quantity"]
            if discount > line:
                raise AppException(
                    status_code=422,
                    detail=f"Discount {discount} is more than the line ({line})",
                    code="DISCOUNT_EXCEEDS_LINE",
                )
            subtotal += line - discount
        if order_discount > subtotal:
            raise AppException(
                status_code=422,
                detail=f"Discount {order_discount} is more than the order ({subtotal})",
                code="DISCOUNT_EXCEEDS_TOTAL",
            )

    @staticmethod
    def create_order(
        db: Session,
        org_id: int,
        branch_id: int,
        user_id: int,
        data: dict,
        request_id: str = "",
        can_discount: bool = False,
        audit: AuditContext | None = None,
    ) -> tuple[Order, str | None]:
        """``can_discount``: the caller holds orders.discount at the branch;
        a discount typed in by anyone else is 403 (``audit`` records each one)."""
        branch = OrderRepository.get_branch(db, org_id, branch_id)
        if not branch:
            raise NotFoundException(detail="Branch not found")

        product_ids = [item["product_id"] for item in data["items"]]
        products = OrderRepository.get_products_by_ids(db, org_id, product_ids)
        products_map = {p.id: p for p in products}

        missing = set(product_ids) - set(products_map.keys())
        if missing:
            raise BadRequestException(detail=f"Products not found or inactive: {missing}")

        order_source = OrderService._order_source_value(
            data.get("order_source", "pos")
        )
        # Every source sells at the catalog price. A unit_price sent by the
        # client is only checked against it, never used.
        for item_data in data["items"]:
            product = products_map[item_data["product_id"]]
            sent = item_data.get("unit_price")
            catalog_price = Decimal(str(product.selling_price))
            if sent is not None and Decimal(str(sent)) != catalog_price:
                raise AppException(
                    status_code=422,
                    detail=(
                        f"Price mismatch for product '{product.name}': "
                        f"expected {catalog_price}, received {Decimal(str(sent))}"
                    ),
                    code="PRICE_MISMATCH",
                )

        OrderService._check_discounts(data, products_map, can_discount)

        # A POS sale belongs to the drawer it is rung up at: the cashier's open
        # shift at the branch (or the register's), unless the client names one.
        # Its unpaid orders keep that shift from closing (38b).
        shift_id = data.get("shift_id")
        register_id = data.get("register_id")
        if shift_id is None and order_source == "pos":
            shift = current_shift(db, branch_id, user_id, register_id)
            if shift is not None:
                shift_id = shift.id
                # ... and to that shift's register (Phase 46).
                register_id = register_id if register_id is not None else shift.register_id

        order_number = generate_order_number(db, branch.code)

        order = Order(
            organization_id=org_id,
            branch_id=branch_id,
            order_number=order_number,
            status="pending",
            customer_id=data.get("customer_id"),
            user_id=user_id,
            shift_id=shift_id,
            register_id=register_id,
            discount_amount=Decimal(str(data.get("discount_amount", 0))),
            notes=data.get("notes"),
            order_source=order_source,
        )
        # Issue a public-tracking capability token at order creation. Only the
        # SHA-256 digest is stored; the plaintext is returned once in the
        # create response and is never persisted.
        tracking_token = OrderService.generate_tracking_token()
        order.tracking_token_hash = OrderService.hash_tracking_token(tracking_token)
        OrderRepository.add_order(db, order)

        subtotal = Decimal("0")
        order_items = []

        stations = OrderRepository.get_stations_for_products(
            db, org_id, product_ids
        )

        for item_data in data["items"]:
            product = products_map[item_data["product_id"]]
            quantity = item_data["quantity"]
            unit_price = Decimal(str(product.selling_price))
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
                station=stations.get(product.id, "none"),
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
        if data.get("coupon_code"):
            db.flush()
            CouponService.redeem(db, order, data["coupon_code"])

        item_discounts = [
            {"product_id": i.product_id, "discount_amount": str(i.discount_amount)}
            for i in order_items if i.discount_amount > 0
        ]
        if (discount > 0 or item_discounts) and audit is not None:
            log_audit(
                db=db,
                ctx=audit,
                action="ORDER.DISCOUNT",
                entity_type="order",
                entity_id=order.id,
                after_data={
                    "order_number": order.order_number,
                    "order_discount": str(discount),
                    "item_discounts": item_discounts,
                    "subtotal": str(subtotal),
                    "grand_total": str(grand_total),
                },
            )

        db.flush()
        db.commit()
        db.refresh(order)
        user_events.publish_user_event_sync(
            "order_created",
            user_id,
            request_id,
            {"order_id": order.id, "order_number": order.order_number},
        )
        return order, tracking_token

    @staticmethod
    def replace_tracking_token(
        db: Session,
        org_id: int,
        order_id: int,
    ) -> tuple[Order, str]:
        """Replace an order's public tracking token.

        Locks the target order row within the transaction (organization
        scoped) so concurrent replacements serialize. The stored hash is
        overwritten with the SHA-256 digest of a newly generated token, so
        the previous plaintext token is invalidated (last write wins). The new
        plaintext token is returned once and never persisted.
        """
        order = OrderRepository.get_org_order_for_update(db, org_id, order_id)
        if not order:
            raise NotFoundException(detail="Order not found")

        tracking_token = OrderService.generate_tracking_token()
        order.tracking_token_hash = OrderService.hash_tracking_token(tracking_token)

        db.flush()
        db.commit()
        db.refresh(order)
        return order, tracking_token

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
        date_field: str = "created_at",
        shift_id: int | str | None = None,
    ) -> dict:
        items, total = OrderRepository.list_orders(
            db, org_id, branch_id, page, per_page, status,
            date_from, date_to, customer_id, user_id, date_field, shift_id,
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
    def update_tracking(
        db: Session,
        org_id: int,
        order_id: int,
        tracking_number: str,
        fulfillment_status: str,
    ) -> Order:
        allowed_statuses = {
            "unfulfilled", "processing", "shipped", "delivered", "picked_up", "cancelled"
        }
        if fulfillment_status not in allowed_statuses:
            raise BadRequestException(detail="Invalid fulfillment status", code="VALIDATION_ERROR")

        order = OrderRepository.get_org_order(db, org_id, order_id)
        if not order:
            raise NotFoundException(detail="Order not found")

        tracking_number = tracking_number.strip()
        if not tracking_number:
            raise BadRequestException(detail="tracking_number cannot be blank", code="VALIDATION_ERROR")
        order.tracking_number = tracking_number
        order.fulfillment_status = fulfillment_status
        db.commit()
        db.refresh(order)
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
                "coupon_id": order.coupon_id,
                "coupon_discount": order.coupon_discount,
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
                    "tendered_amount": p.tendered_amount,
                    "status": p.status,
                    "external_reference": p.external_reference,
                    "provider": p.provider,
                    "created_at": p.created_at,
                }
                for p in payments
            ],
        }

    @staticmethod
    def cancel_order(
        db: Session,
        org_id: int,
        order_id: int,
        user_id: int,
        request_id: str = "",
        may_cancel_any: bool = True,
        reason: str | None = None,
        audit: AuditContext | None = None,
    ) -> Order:
        """Cancel an unpaid order and put its stock back (Phase 38b).

        ``may_cancel_any``: the caller holds orders.cancel at the order's
        branch; without it only the caller's own orders (403 ORDER_NOT_YOURS).
        An order with money on it is returned, not cancelled (400
        ORDER_ALREADY_PAID). The order row is locked, so a payment and a
        cancel of one order cannot both go through.

        A ``ready`` order (38c): only with orders.cancel (403
        ORDER_READY_NEEDS_MANAGER) and a ``reason`` (422
        CANCEL_REASON_REQUIRED); ``audit`` records who, why and from what."""
        order = OrderRepository.get_org_order_for_update(db, org_id, order_id)

        if not order:
            raise NotFoundException(detail="Order not found")
        if not may_cancel_any and order.user_id != user_id:
            raise ForbiddenException(
                detail="Only your own orders can be cancelled without orders.cancel",
                code="ORDER_NOT_YOURS",
            )
        if order.status in OrderService.PAID_STATUSES or paid_net(db, order.id) > 0:
            raise BadRequestException(
                detail="This order has been paid: return it (POST /returns/) instead of cancelling",
                code="ORDER_ALREADY_PAID",
            )
        was_ready = order.status == "ready"
        if was_ready:
            if not may_cancel_any:
                raise ForbiddenException(
                    detail="A ready order is cancelled by a Branch Admin (orders.cancel)",
                    code="ORDER_READY_NEEDS_MANAGER",
                )
            if not (reason or "").strip():
                raise UnprocessableException(
                    detail="Say why the ready order is cancelled", code="CANCEL_REASON_REQUIRED"
                )
        elif order.status not in OrderService.CANCELLABLE_STATUSES:
            raise InvalidOrderStateException(
                detail=f"Cannot cancel order in '{order.status}' status"
            )

        for item in order.items:
            product = OrderRepository.get_product(db, item.product_id)

            if product and product.track_inventory:
                on_hand_before = OrderRepository.lock_inventory_on_hand(
                    db, order.branch_id, item.product_id
                )
                if on_hand_before is None:
                    continue
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

        CouponService.release(db, order)
        order.status = "cancelled"
        order.cancelled_at = datetime.now(timezone.utc)
        if was_ready and audit is not None:
            log_audit(
                db=db,
                ctx=audit,
                action="ORDER.CANCEL_READY",
                entity_type="order",
                entity_id=order.id,
                before_data={"status": "ready", "grand_total": str(order.grand_total)},
                after_data={"status": "cancelled", "order_number": order.order_number, "reason": reason.strip()},
            )
        db.flush()
        db.commit()
        db.refresh(order)
        user_events.publish_user_event_sync(
            "order_cancelled",
            user_id,
            request_id,
            {"order_id": order.id},
        )
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
        request_id: str = "",
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

        # Row lock: a checkout and a POST /payments/ of one order are serialized,
        # so the second sees what the first settled (Phase 43).
        order = OrderRepository.get_org_order_for_update(db, org_id, order_id)
        if not order:
            raise NotFoundException(detail="Order not found")

        # Idempotency: an already-settled order is the success result of a
        # previous attempt, so return it unchanged instead of charging again.
        if idempotency_key and order.status in ("paid", "completed", "refunded"):
            return order

        # Cash with no open shift is 409 SHIFT_REQUIRED before the coupon
        # or the points are touched (Phase 46); an order that cannot be checked
        # out is left to settle_order's answer.
        if order.status in OrderService.CHECKOUTABLE_STATUSES:
            order_drawer(db, order, user_id, (p["payment_method"] for p in data.get("payments") or []))

        if data.get("coupon_code"):
            OrderService._coupon_at_checkout(db, order, data["coupon_code"])

        OrderService.settle_order(
            db,
            order,
            user_id,
            payments=data.get("payments") or [],
            redeem_points=int(data.get("redeem_points") or 0),
        )

        db.commit()
        db.refresh(order)
        user_events.publish_user_event_sync(
            "purchase_completed",
            user_id,
            request_id,
            {"order_id": order.id, "amount_paid": str(order.amount_paid)},
        )
        return order

    @staticmethod
    def _coupon_at_checkout(db: Session, order: Order, code: str) -> None:
        """A coupon given at checkout: the same one again changes nothing,
        another one is 409; none once money is on the order."""
        if order.coupon_id is not None:
            if CouponRepository.get_org_coupon(db, order.organization_id, order.coupon_id).code == code:
                return
            raise ConflictException(detail="The order already has a coupon", code="COUPON_ALREADY_APPLIED")
        if order.status not in OrderService.CHECKOUTABLE_STATUSES:
            return  # settle_order refuses it
        if paid_net(db, order.id) > 0:
            raise BadRequestException(
                detail="A coupon cannot be added once the order is partly paid", code="COUPON_AFTER_PAYMENT"
            )
        CouponService.redeem(db, order, code)

    @staticmethod
    def settle_order(
        db: Session,
        order: Order,
        user_id: int,
        payments: list[dict],
        redeem_points: int = 0,
    ) -> list[Payment]:
        """Record payments, apply/earn loyalty points and mark the order ``paid``.

        Shared by POS checkout and slip verification. Only flushes: the caller
        owns the transaction (commit) and any post-commit events.

        What completed payments (POST /payments/) already settled counts
        (Phase 43): points and payments cover only what is still due, and
        nothing is left to settle is 400 ORDER_ALREADY_PAID. Up to v0.1.16
        the whole grand_total was settled again on top of them.
        """
        if order.status not in OrderService.CHECKOUTABLE_STATUSES:
            raise InvalidOrderStateException(
                detail=f"Cannot checkout order in '{order.status}' status"
            )

        already = paid_net(db, order.id)
        if already > 0 and already >= amount_due(order):
            raise BadRequestException(
                detail=f"The order is already paid ({already} of {amount_due(order)})",
                code="ORDER_ALREADY_PAID",
            )

        # Before the points: cash with no open shift writes nothing (Phase 46).
        shift = order_drawer(db, order, user_id, (p["payment_method"] for p in payments))

        org_id = order.organization_id
        customer = None
        if order.customer_id is not None:
            customer = LoyaltyRepository.find_org_customer(db, org_id, order.customer_id)
            if customer is None:
                raise NotFoundException(detail="Customer not found")

        # ---- Loyalty redemption (points as discount) ----
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
            max_credit = int(Decimal(str(order.grand_total)) - already) // OrderService.POINTS_VALUE_PER_BAHT
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

        # What is still due: neither the points nor earlier payments are paid twice.
        due = Decimal(str(order.grand_total)) - Decimal(redeemed) - already

        # ---- Payments ----
        if not payments:
            raise BadRequestException(detail="At least one payment is required")

        handed = []
        for pay in payments:
            amount = Decimal(str(pay["amount"]))
            if amount <= 0:
                raise BadRequestException(detail="Payment amount must be positive")
            handed.append((pay, amount))
        paid_total = sum((a for _, a in handed), Decimal("0"))
        if paid_total < due:
            raise BadRequestException(
                detail=f"Payments ({paid_total}) less than amount due ({due})"
            )
        non_cash = sum((a for p, a in handed if p["payment_method"] != CASH), Decimal("0"))
        if non_cash > due:
            raise BadRequestException(
                detail=f"Non-cash payments ({non_cash}) exceed the amount due ({due}); only cash gives change",
                code="OVERPAYMENT",
            )

        # Change comes out of the cash, the last cash payment first; each
        # payment keeps what it settled (amount) and cash what was handed over.
        change = paid_total - due
        nets = [a for _, a in handed]
        for i in reversed(range(len(handed))):
            if change == 0:
                break
            if handed[i][0]["payment_method"] == CASH:
                take = min(change, nets[i])
                nets[i] -= take
                change -= take
        if any(n == 0 for n in nets):
            raise BadRequestException(
                detail="A payment would settle nothing: send only what is needed", code="OVERPAYMENT",
            )

        attach_to_shift(order, shift)
        recorded: list[Payment] = []
        for (pay, amount), net in zip(handed, nets):
            payment = Payment(
                order_id=order.id,
                payment_method=pay["payment_method"],
                amount=net,
                tendered_amount=amount if pay["payment_method"] == CASH else None,
                shift_id=shift.id if shift else None,
                status="completed",
                external_reference=pay.get("external_reference"),
                provider=pay.get("provider"),
                notes=pay.get("notes"),
                received_by=user_id,
            )
            PaymentRepository.add_payment(db, payment)
            recorded.append(payment)

        # Added to what earlier payments handed over, as POST /payments/ does.
        order.amount_paid = Decimal(str(order.amount_paid)) + paid_total
        order.change_amount = Decimal(str(order.change_amount)) + (paid_total - due)

        OrderService.award_points(db, order, user_id)

        order.status = "paid"
        order.paid_at = datetime.now(timezone.utc)

        db.flush()
        return recorded

    @staticmethod
    def award_points(db: Session, order: Order, user_id: int) -> int:
        """Loyalty points for a fully paid order, whichever way it was paid
        (checkout, POST /payments/, a slip): the whole order's net spend
        (grand_total less the points redeemed), once per order (Phase 43).

        The caller holds the order's row lock, so two payments that complete
        one order cannot both award. Returns the points awarded now (0 when the
        order has no customer or was awarded already). Only flushes.
        """
        if order.customer_id is None or order.loyalty_points_earned:
            return 0
        if LoyaltyRepository.earned_on_order(db, order.id):
            return 0
        spend_whole = int(amount_due(order))
        points = (
            spend_whole // OrderService.POINTS_EARN_PER_BAHT
            if OrderService.POINTS_EARN_PER_BAHT
            else spend_whole
        )
        if points <= 0:
            return 0
        customer = LoyaltyRepository.find_org_customer(db, order.organization_id, order.customer_id)
        if customer is None:
            return 0
        before = customer.loyalty_points_balance
        after = before + points
        LoyaltyRepository.add_transaction(
            db,
            LoyaltyTransaction(
                customer_id=order.customer_id,
                transaction_type="earn",
                points=points,
                points_before=before,
                points_after=after,
                reference_type="order",
                reference_id=order.id,
                notes="Points earned on the paid order",
                user_id=user_id,
            ),
        )
        customer.loyalty_points_balance = after
        order.loyalty_points_earned = points
        db.flush()
        return points

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
        if not is_fully_paid(db, order):
            raise BadRequestException(detail="Order is not fully paid", code="ORDER_NOT_FULLY_PAID")

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
            if not is_fully_paid(db, order):
                raise BadRequestException(detail="Order is not fully paid", code="ORDER_NOT_FULLY_PAID")
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
        """List the items of a station (kitchen/bar) of orders still on screen:
        not completed, cancelled or refunded."""
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
        orders: dict[int, dict] = {}
        for row_order, item in rows:
            bucket = orders.setdefault(row_order.id, {"order": row_order, "items": []})
            bucket["items"].append(item)
        # Each header comes from its own bucket (it used to come from the last
        # row of the loop above, so every order showed the last one's header).
        return {
            "orders": [
                {
                    "id": bucket["order"].id,
                    "order_id": bucket["order"].id,
                    "order_number": bucket["order"].order_number,
                    "branch_id": bucket["order"].branch_id,
                    "status": bucket["order"].status,
                    "notes": bucket["order"].notes,
                    "created_at": bucket["order"].created_at,
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
