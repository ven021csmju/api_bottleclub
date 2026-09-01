"""Permission naming normalization.

The API contract (PHASE_5 §27) uses dotted-uppercase identifiers
(e.g. ``USER.READ``) while the backend seed data and JWT payload use
lowercase module-based codes (e.g. ``users.read``).

This module provides an explicit mapping so ``require_permission`` accepts
both forms without touching the database seed or the token payload.
"""
from __future__ import annotations

CONTRACT_SYSTEM_PERMISSIONS: dict[str, str] = {
    "SYSTEM.AUDIT_LOG": "audit.read",
    "SYSTEM.READ": "settings.read",
    "SYSTEM.UPDATE": "settings.update",
}

CONTRACT_PERMISSIONS: dict[str, str] = {
    "USER.READ": "users.read",
    "USER.CREATE": "users.create",
    "USER.UPDATE": "users.update",
    "USER.DELETE": "users.delete",
    "USER.ASSIGN_ROLE": "users.assign_roles",
    "ROLE.READ": "roles.read",
    "ROLE.CREATE": "roles.create",
    "ROLE.UPDATE": "roles.update",
    "ROLE.DELETE": "roles.delete",
    "ROLE.ASSIGN_PERMISSION": "roles.update",
    "BRANCH.READ": "branches.read",
    "BRANCH.CREATE": "branches.create",
    "BRANCH.UPDATE": "branches.update",
    "REGISTER.READ": "registers.read",
    "REGISTER.CREATE": "registers.create",
    "REGISTER.UPDATE": "registers.update",
    "SHIFT.READ": "shifts.read",
    "SHIFT.OPEN": "shifts.open",
    "SHIFT.CLOSE": "shifts.close",
    "PRODUCT.READ": "catalog.read",
    "PRODUCT.CREATE": "catalog.create",
    "PRODUCT.UPDATE": "catalog.create",
    "PRODUCT.DELETE": "catalog.create",
    "CATEGORY.READ": "catalog.read",
    "CATEGORY.CREATE": "catalog.create",
    "CATEGORY.UPDATE": "catalog.create",
    "CATEGORY.DELETE": "catalog.create",
    "INVENTORY.READ": "inventory.read",
    "INVENTORY.ADJUST": "inventory.adjust",
    "SUPPLIER.READ": "catalog.read",
    "SUPPLIER.CREATE": "catalog.create",
    "SUPPLIER.UPDATE": "catalog.create",
    "PURCHASE.READ": "purchases.read",
    "PURCHASE.CREATE": "purchases.create",
    "PURCHASE.APPROVE": "purchases.approve",
    "PURCHASE.CANCEL": "purchases.create",
    "PURCHASE.RECEIVE": "purchases.receive",
    "TRANSFER.READ": "transfers.read",
    "TRANSFER.CREATE": "transfers.create",
    "TRANSFER.APPROVE": "transfers.approve",
    "TRANSFER.SHIP": "transfers.ship",
    "TRANSFER.RECEIVE": "transfers.receive",
    "ORDER.READ": "orders.read",
    "ORDER.CREATE": "orders.create",
    "ORDER.UPDATE": "orders.update",
    "ORDER.CANCEL": "orders.cancel",
    "KDS.KITCHEN.READ": "kds.kitchen.read",
    "KDS.KITCHEN.UPDATE": "kds.kitchen.update",
    "KDS.BAR.READ": "kds.bar.read",
    "KDS.BAR.UPDATE": "kds.bar.update",
    "PAYMENT.READ": "payments.read",
    "PAYMENT.CREATE": "payments.create",
    "PAYMENT.REFUND": "payments.refund",
    "REFUND.READ": "refunds.read",
    "RETURN.READ": "returns.read",
    "RETURN.CREATE": "returns.create",
    "RETURN.PROCESS": "returns.process",
    "CUSTOMER.READ": "customers.read",
    "CUSTOMER.CREATE": "customers.create",
    "CUSTOMER.UPDATE": "customers.update",
    "CUSTOMER.DELETE": "customers.delete",
    "LOYALTY.READ": "loyalty.read",
    "LOYALTY.ADJUST": "loyalty.earn",
    "PROMOTION.READ": "promotions.read",
    "PROMOTION.CREATE": "promotions.create",
    "PROMOTION.UPDATE": "promotions.update",
    "PROMOTION.DELETE": "promotions.delete",
    "COUPON.READ": "coupons.read",
    "COUPON.CREATE": "coupons.create",
    "COUPON.UPDATE": "coupons.update",
    "COUPON.DELETE": "coupons.delete",
    "REPORT.SALES": "reports.sales",
    "REPORT.INVENTORY": "reports.read",
    "REPORT.FINANCIAL": "reports.read",
    "REPORT.LOYALTY": "reports.read",
}

CONTRACT_PERMISSIONS.update(CONTRACT_SYSTEM_PERMISSIONS)

INTERNAL_TO_CONTRACT: dict[str, str] = {
    value: key for key, value in CONTRACT_PERMISSIONS.items()
}


def normalize_permission(code: str) -> str:
    """Resolve a contract ``USER.READ``-style code to its internal code."""
    resolved = CONTRACT_PERMISSIONS.get(code)
    if resolved is not None:
        return resolved
    return code.lower()


def contract_code(internal: str) -> str:
    """Resolve an internal code to its contract ``USER.READ``-style code."""
    return INTERNAL_TO_CONTRACT.get(internal, internal.upper())