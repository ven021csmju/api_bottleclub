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
    ) -> None:
        self.status_code = status_code
        self.detail = detail
        self.code = code
        super().__init__(self.detail)


class NotFoundException(AppException):
    def __init__(self, detail: str = "Resource not found", code: str | None = None) -> None:
        super().__init__(status_code=404, detail=detail, code=code)


class BadRequestException(AppException):
    def __init__(self, detail: str = "Bad request", code: str | None = None) -> None:
        super().__init__(status_code=400, detail=detail, code=code)


class ConflictException(AppException):
    def __init__(self, detail: str = "Conflict", code: str | None = None) -> None:
        super().__init__(status_code=409, detail=detail, code=code)


class ForbiddenException(AppException):
    def __init__(self, detail: str = "Forbidden", code: str | None = None) -> None:
        super().__init__(status_code=403, detail=detail, code=code)


class UnauthorizedException(AppException):
    def __init__(self, detail: str = "Unauthorized", code: str | None = None) -> None:
        super().__init__(status_code=401, detail=detail, code=code)


class InsufficientStockException(AppException):
    def __init__(self, detail: str = "Insufficient stock", code: str | None = "INSUFFICIENT_STOCK") -> None:
        super().__init__(status_code=400, detail=detail, code=code)


class InvalidOrderStateException(AppException):
    def __init__(self, detail: str = "Invalid order state transition", code: str | None = None) -> None:
        super().__init__(status_code=400, detail=detail, code=code)


class IdempotencyConflictException(AppException):
    def __init__(self, detail: str = "Idempotency key conflict", code: str | None = None) -> None:
        super().__init__(status_code=409, detail=detail, code=code)
