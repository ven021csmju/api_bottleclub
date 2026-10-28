from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

#: Deprecated routes (still served) → their successor. Every answer of one,
#: errors too, carries ``Deprecation: true`` (RFC 9745) and a Link to the
#: successor (Phase 40).
DEPRECATED_PATHS = {
    "/api/v1/slip-verify/checkslip": "/api/v1/slip-verify/upload",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        successor = DEPRECATED_PATHS.get(request.url.path.rstrip("/"))
        if successor is not None:
            response.headers["Deprecation"] = "true"
            response.headers["Link"] = f'<{successor}>; rel="successor-version"'
        return response
