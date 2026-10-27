from typing import Any


class AppException(Exception):
    status_code: int
    detail: str
    code: str | None

    def __init__(
        self,
        status_code: int = 500,
        detail: str = "Internal server error",
        code: str | None = None,
        extra: dict | None = None,
    ) -> None:
        self.status_code = status_code
        self.detail = detail
        self.code = code
        #: More fields of the error body (e.g. the orders that block a shift close).
        self.extra = extra or {}
        super().__init__(self.detail)


class NotFoundException(AppException):
    def __init__(self, detail: str = "Resource not found", code: str | None = None) -> None:
        super().__init__(status_code=404, detail=detail, code=code or "NOT_FOUND")


class BadRequestException(AppException):
    def __init__(self, detail: str = "Bad request", code: str | None = None) -> None:
        super().__init__(status_code=400, detail=detail, code=code or "BAD_REQUEST")


class ConflictException(AppException):
    def __init__(self, detail: str = "Conflict", code: str | None = None) -> None:
        super().__init__(status_code=409, detail=detail, code=code or "CONFLICT")


class UnprocessableException(AppException):
    def __init__(self, detail: str = "Invalid input", code: str | None = None) -> None:
        super().__init__(status_code=422, detail=detail, code=code or "VALIDATION_ERROR")


class ForbiddenException(AppException):
    def __init__(self, detail: str = "Forbidden", code: str | None = None) -> None:
        super().__init__(status_code=403, detail=detail, code=code or "FORBIDDEN")


class UnauthorizedException(AppException):
    def __init__(self, detail: str = "Unauthorized", code: str | None = None) -> None:
        super().__init__(status_code=401, detail=detail, code=code or "UNAUTHORIZED")


class InsufficientStockException(AppException):
    def __init__(self, detail: str = "Insufficient stock", code: str | None = "INSUFFICIENT_STOCK") -> None:
        super().__init__(status_code=400, detail=detail, code=code)


class InvalidOrderStateException(AppException):
    def __init__(self, detail: str = "Invalid order state transition", code: str | None = None) -> None:
        super().__init__(status_code=400, detail=detail, code=code or "INVALID_ORDER_STATE")


class IdempotencyConflictException(AppException):
    def __init__(self, detail: str = "Idempotency key conflict", code: str | None = None) -> None:
        super().__init__(status_code=409, detail=detail, code=code or "IDEMPOTENCY_CONFLICT")


class DatabaseException(AppException):
    def __init__(self, detail: str = "Database operation failed") -> None:
        super().__init__(status_code=500, detail=detail, code="DATABASE_ERROR")
