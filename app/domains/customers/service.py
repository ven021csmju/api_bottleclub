from datetime import datetime, timezone

import hashlib
import logging

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session

from app.db.models import Customer, CustomerAccount, CustomerIdentity
from app.db.repositories.customers import CustomerRepository
from app.shared.exceptions import AppException, ConflictException, NotFoundException, UnprocessableException
from app.shared.pagination import paginate

logger = logging.getLogger(__name__)

#: Answered (409) when a service key creates a customer it could have found.
EXISTS_DETAIL = "A customer with this email or phone exists"

#: The one answer for no such customer.
LOOKUP_NOT_FOUND = "Customer not found"


def _lock_key(text: str) -> int:
    """A signed 64-bit pg_advisory_xact_lock key for ``text``."""
    return int.from_bytes(hashlib.sha256(text.encode()).digest()[:8], "big", signed=True)


def _normalized_phone():
    """customers.phone as OrderService.normalize_contact gives it: digits
    only, 66XXXXXXXXX as 0XXXXXXXXX."""
    digits = func.regexp_replace(func.coalesce(Customer.phone, ""), r"\D", "", "g")
    return case(
        (and_(digits.like("66%"), func.length(digits) == 11), func.concat("0", func.substr(digits, 3))),
        else_=digits,
    )


class CustomerService:
    @staticmethod
    def list(
        db: Session,
        organization_id: int,
        page: int = 1,
        per_page: int = 20,
    ) -> tuple[list[Customer], int]:
        stmt = CustomerRepository.list_query(db, organization_id)
        items, total, _, _ = paginate(db, stmt, page, per_page)
        return list(items), total

    @staticmethod
    def get(db: Session, organization_id: int, customer_id: int) -> Customer:
        customer = CustomerRepository.get_org_customer(db, organization_id, customer_id)
        if customer is None:
            raise NotFoundException(detail="Customer not found")
        return customer

    @staticmethod
    def create(db: Session, organization_id: int, **kwargs) -> Customer:
        phone = kwargs.get("phone")
        if phone:
            existing = CustomerRepository.find_by_phone(db, organization_id, phone)
            if existing:
                raise ConflictException(
                    detail=f"Customer with phone '{phone}' already exists"
                )

        customer = Customer(organization_id=organization_id, **kwargs)
        CustomerRepository.add_customer(db, customer)
        db.commit()
        db.refresh(customer)
        return customer

    @staticmethod
    def update(db: Session, organization_id: int, customer_id: int, **kwargs) -> Customer:
        customer = CustomerService.get(db, organization_id, customer_id)

        phone = kwargs.get("phone")
        if phone:
            existing = CustomerRepository.find_by_phone(
                db, organization_id, phone, exclude_customer_id=customer_id
            )
            if existing:
                raise ConflictException(
                    detail=f"Customer with phone '{phone}' already exists"
                )

        for key, value in kwargs.items():
            if value is not None:
                setattr(customer, key, value)

        db.commit()
        db.refresh(customer)
        return customer

    @staticmethod
    def soft_delete(db: Session, organization_id: int, customer_id: int) -> None:
        customer = CustomerService.get(db, organization_id, customer_id)
        customer.deleted_at = datetime.now(timezone.utc)
        db.commit()

    @staticmethod
    def lookup(
        db: Session,
        organization_id: int,
        *,
        line_sub: str | None = None,
        email: str | None = None,
        phone: str | None = None,
        service_key_id: int | None = None,
    ) -> Customer:
        """The one active customer of the organization that every identifier
        given names (exact, normalized). 404 none, 409 more than one: never a
        list. Logged with the key and the identifiers' names, never values."""
        stmt = select(Customer).where(
            Customer.organization_id == organization_id, Customer.deleted_at.is_(None)
        )
        if line_sub is not None:
            stmt = stmt.where(Customer.id.in_(
                select(CustomerAccount.customer_id)
                .join(CustomerIdentity, CustomerIdentity.customer_account_id == CustomerAccount.id)
                .where(
                    CustomerIdentity.provider == "line",
                    CustomerIdentity.provider_subject == line_sub,
                    CustomerAccount.organization_id == organization_id,
                    CustomerAccount.deleted_at.is_(None),
                )
            ))
        if email is not None:
            stmt = stmt.where(func.lower(func.trim(Customer.email)) == email)
        if phone is not None:
            stmt = stmt.where(_normalized_phone() == phone)
        found = db.scalars(stmt.order_by(Customer.id).limit(2)).all()
        by = ",".join(n for n, v in (("line_sub", line_sub), ("email", email), ("phone", phone)) if v is not None)
        result = {0: "not_found", 1: "found"}.get(len(found), "ambiguous")
        logger.info("customer lookup service_key=%s org=%s by=%s result=%s",
                    service_key_id, organization_id, by, result)
        if not found:
            raise NotFoundException(detail=LOOKUP_NOT_FOUND)
        if len(found) > 1:
            raise ConflictException(detail="More than one customer has these identifiers",
                                    code="CUSTOMER_AMBIGUOUS")
        return found[0]

    @staticmethod
    def create_for_service_key(db: Session, organization_id: int, service_key_id: int, **kwargs) -> Customer:
        """POST /customers/ with a key: never a second active customer with the
        same email (case aside) or phone (as POST /orders/track compares it) in
        the organization. The existing one is answered as 409 CUSTOMER_EXISTS
        with the lookup fields, so the storefront can go on with it.

        Two requests at once (a double click): each identifier is locked for
        the transaction (pg_advisory_xact_lock, in one order), so the second
        waits for the first's commit and then finds its customer."""
        from app.domains.customers.schemas import CustomerLookupResponse
        from app.domains.orders.service import OrderService

        email = kwargs.get("email")
        email = email.strip().lower() if email and email.strip() else None
        phone = kwargs.get("phone")
        digits = None
        if phone and phone.strip():
            digits = OrderService.normalize_contact(phone)
            if digits is None or "@" in digits:
                raise UnprocessableException(detail="phone must be a whole number")
        identifiers = sorted(f"{organization_id}:{kind}:{value}"
                             for kind, value in (("email", email), ("phone", digits)) if value)
        for name in identifiers:
            db.execute(select(func.pg_advisory_xact_lock(_lock_key(name))))
        if identifiers:
            matches = []
            if email:
                matches.append(func.lower(func.trim(Customer.email)) == email)
            if digits:
                matches.append(_normalized_phone() == digits)
            existing = db.scalars(
                select(Customer)
                .where(Customer.organization_id == organization_id, Customer.deleted_at.is_(None), or_(*matches))
                .order_by(Customer.id)
                .limit(1)
            ).first()
            if existing is not None:
                logger.info("customer create service_key=%s org=%s result=exists", service_key_id, organization_id)
                db.rollback()  # releases the locks
                raise AppException(
                    status_code=409, detail=EXISTS_DETAIL, code="CUSTOMER_EXISTS",
                    extra={"customer": CustomerLookupResponse.of(existing).model_dump()},
                )
        customer = CustomerService.create(db, organization_id, **kwargs)  # commits: releases the locks
        logger.info("customer create service_key=%s org=%s result=created", service_key_id, organization_id)
        return customer
