import enum


class UserStatus(str, enum.Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"
    LOCKED = "locked"


class StockMovementType(str, enum.Enum):
    PURCHASE = "purchase"
    SALE = "sale"
    ADJUSTMENT = "adjustment"
    RETURN = "return"
    TRANSFER_IN = "transfer_in"
    TRANSFER_OUT = "transfer_out"
    DAMAGE = "damage"
    EXPIRY = "expiry"


class POStatus(str, enum.Enum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    APPROVED = "approved"
    PARTIALLY_RECEIVED = "partially_received"
    RECEIVED = "received"
    CANCELLED = "cancelled"


class ReceivingStatus(str, enum.Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    DISCREPANCY = "discrepancy"


class TransferStatus(str, enum.Enum):
    DRAFT = "draft"
    PENDING = "pending"
    IN_TRANSIT = "in_transit"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class OrderStatus(str, enum.Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    PREPARING = "preparing"
    READY = "ready"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    PAID = "paid"
    HELD = "held"
    REFUNDED = "refunded"


class StationType(str, enum.Enum):
    KITCHEN = "kitchen"
    BAR = "bar"


class ItemStatus(str, enum.Enum):
    PENDING = "pending"
    PREPARING = "preparing"
    READY = "ready"
    SERVED = "served"
    CANCELLED = "cancelled"


class PaymentMethod(str, enum.Enum):
    CASH = "cash"
    CREDIT_CARD = "credit_card"
    DEBIT_CARD = "debit_card"
    BANK_TRANSFER = "bank_transfer"
    E_WALLET = "e_wallet"
    QR_CODE = "qr_code"


class PaymentStatus(str, enum.Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    REFUNDED = "refunded"


class RefundStatus(str, enum.Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"


class ReturnStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    COMPLETED = "completed"


class ReturnReason(str, enum.Enum):
    DEFECTIVE = "defective"
    WRONG_ITEM = "wrong_item"
    NOT_AS_DESCRIBED = "not_as_described"
    BUYER_REMORSE = "buyer_remorse"
    DAMAGED_IN_TRANSIT = "damaged_in_transit"
    OTHER = "other"


class PromotionType(str, enum.Enum):
    PERCENTAGE_DISCOUNT = "percentage_discount"
    FIXED_DISCOUNT = "fixed_discount"
    BUY_X_GET_Y = "buy_x_get_y"
    BUNDLE = "bundle"
    LOYALTY_MULTIPLIER = "loyalty_multiplier"


class LoyaltyTransactionType(str, enum.Enum):
    EARN = "earn"
    REDEEM = "redeem"
    ADJUSTMENT = "adjustment"
    EXPIRY = "expiry"
    TRANSFER = "transfer"


class ShiftStatus(str, enum.Enum):
    OPEN = "open"
    CLOSED = "closed"
    RECONCILED = "reconciled"


class CashMovementType(str, enum.Enum):
    OPENING = "opening"
    CLOSING = "closing"
    CASH_IN = "cash_in"
    CASH_OUT = "cash_out"
    DROP = "drop"
    PICKUP = "pickup"


class AuditAction(str, enum.Enum):
    CREATE = "create"
    READ = "read"
    UPDATE = "update"
    DELETE = "delete"
    LOGIN = "login"
    LOGOUT = "logout"
    EXPORT = "export"
    APPROVE = "approve"
    REJECT = "reject"


class VerificationStatus(str, enum.Enum):
    PENDING = "pending"
    VERIFIED = "verified"
    REJECTED = "rejected"
    REVIEW = "review"
    AMOUNT_MISMATCH = "amount_mismatch"
    DUPLICATE_REFERENCE = "duplicate_reference"
    DUPLICATE_IMAGE = "duplicate_image"
    ORDER_NOT_FOUND = "order_not_found"
    ORDER_ALREADY_PAID = "order_already_paid"
    OCR_FAILED = "ocr_failed"
    RECEIVER_MISMATCH = "receiver_mismatch"
