
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config.settings import settings
from app.middleware.correlation import CorrelationMiddleware
from app.middleware.envelope import ResponseEnvelopeMiddleware
from app.middleware.rate_limit import limiter
from app.middleware.security_headers import SecurityHeadersMiddleware
from app.shared.exceptions import AppException


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "")


def create_app() -> FastAPI:
    app = FastAPI(
        title="The Bottle Club",
        description="POS System API for The Bottle Club",
        version="1.0.0",
    )
    app.state.limiter = limiter

    # --- Middleware (order matters: first added = outermost) ---
    app.add_middleware(ResponseEnvelopeMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    if settings.RATE_LIMIT_ENABLED:
        app.add_middleware(SlowAPIMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(CorrelationMiddleware)

    # --- Exception handlers (single source of truth for the error contract) ---
    @app.exception_handler(AppException)
    async def app_exception_handler(
        request: Request,
        exc: AppException,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "detail": exc.detail,
                "code": exc.code,
                "request_id": _request_id(request),
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "detail": "; ".join(err.get("msg", "Invalid input") for err in exc.errors()),
                "code": "VALIDATION_ERROR",
                "request_id": _request_id(request),
            },
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        request: Request,
        exc: StarletteHTTPException,
    ) -> JSONResponse:
        status_code = exc.status_code
        error_code = {
            401: "UNAUTHORIZED",
            403: "FORBIDDEN",
            404: "NOT_FOUND",
            405: "METHOD_NOT_ALLOWED",
            409: "CONFLICT",
            429: "TOO_MANY_REQUESTS",
        }.get(status_code, str(exc.detail))
        return JSONResponse(
            status_code=status_code,
            content={
                "detail": str(exc.detail),
                "code": error_code,
                "request_id": _request_id(request),
            },
        )

    @app.exception_handler(RateLimitExceeded)
    async def rate_limit_exceeded_handler(
        request: Request,
        exc: RateLimitExceeded,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=429,
            content={
                "detail": "Rate limit exceeded",
                "code": "RATE_LIMIT_EXCEEDED",
                "request_id": _request_id(request),
            },
        )

    # --- Health check ---
    @app.get("/health", tags=["Health"])
    def health_check() -> dict[str, str]:
        return {"status": "healthy"}

    # --- Domain routers ---
    from app.domains.auth.router import router as auth_router
    from app.domains.users.router import router as users_router
    from app.domains.branches.router import router as branches_router
    from app.domains.roles.router import router as roles_router
    from app.domains.catalog.router import router as catalog_router
    from app.domains.inventory.router import router as inventory_router
    from app.domains.orders.router import router as orders_router
    from app.domains.payments.router import router as payments_router
    from app.domains.purchases.router import router as purchases_router
    from app.domains.suppliers.router import router as suppliers_router
    from app.domains.transfers.router import router as transfers_router
    from app.domains.returns.router import router as returns_router
    from app.domains.refunds.router import router as refunds_router
    from app.domains.promotions.router import router as promotions_router
    from app.domains.coupons.router import router as coupons_router
    from app.domains.customers.router import router as customers_router
    from app.domains.loyalty.router import router as loyalty_router
    from app.domains.shifts.router import router as shifts_router
    from app.domains.settings.router import router as settings_router
    from app.domains.reports.router import router as reports_router
    from app.domains.audit.router import router as audit_router
    from app.domains.slip_verify.router import router as slip_verify_router

    app.include_router(
        auth_router,
        prefix="/api/v1/auth",
        tags=["Auth"],
    )

    app.include_router(
        users_router,
        prefix="/api/v1/users",
        tags=["Users"],
    )

    app.include_router(
        branches_router,
        prefix="/api/v1/branches",
        tags=["Branches"],
    )

    app.include_router(
        roles_router,
        prefix="/api/v1/roles",
        tags=["Roles"],
    )

    app.include_router(
        catalog_router,
        prefix="/api/v1/catalog",
        tags=["Catalog"],
    )

    app.include_router(
        inventory_router,
        prefix="/api/v1/inventory",
        tags=["Inventory"],
    )

    app.include_router(
        orders_router,
        prefix="/api/v1/orders",
        tags=["Orders"],
    )

    app.include_router(
        payments_router,
        prefix="/api/v1/payments",
        tags=["Payments"],
    )

    app.include_router(
        purchases_router,
        prefix="/api/v1/purchases",
        tags=["Purchases"],
    )

    app.include_router(
        suppliers_router,
        prefix="/api/v1/suppliers",
        tags=["Suppliers"],
    )

    app.include_router(
        transfers_router,
        prefix="/api/v1/transfers",
        tags=["Transfers"],
    )

    app.include_router(
        returns_router,
        prefix="/api/v1/returns",
        tags=["Returns"],
    )

    app.include_router(
        refunds_router,
        prefix="/api/v1/refunds",
        tags=["Refunds"],
    )

    app.include_router(
        promotions_router,
        prefix="/api/v1/promotions",
        tags=["Promotions"],
    )

    app.include_router(
        coupons_router,
        prefix="/api/v1/coupons",
        tags=["Coupons"],
    )

    app.include_router(
        customers_router,
        prefix="/api/v1/customers",
        tags=["Customers"],
    )

    app.include_router(
        loyalty_router,
        prefix="/api/v1/loyalty",
        tags=["Loyalty"],
    )

    app.include_router(
        shifts_router,
        prefix="/api/v1/shifts",
        tags=["Shifts"],
    )

    app.include_router(
        settings_router,
        prefix="/api/v1/settings",
        tags=["Settings"],
    )

    app.include_router(
        reports_router,
        prefix="/api/v1/reports",
        tags=["Reports"],
    )

    app.include_router(
        audit_router,
        prefix="/api/v1/audit",
        tags=["Audit"],
    )

    app.include_router(
        slip_verify_router,
        prefix="/api/v1/slip-verify",
        tags=["Slip Verification"],
    )

    return app


app = create_app()

