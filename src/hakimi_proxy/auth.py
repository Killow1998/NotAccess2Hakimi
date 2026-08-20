"""Bearer token authentication middleware."""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

PUBLIC_PATHS = {"/healthz", "/docs", "/openapi.json", "/redoc"}
UI_PATHS = {"/", "/ui", "/favicon.ico"}


class BearerAuthMiddleware(BaseHTTPMiddleware):
    """Reject requests without a valid Bearer token, except public paths."""

    def __init__(self, app, auth_token: str = "") -> None:
        super().__init__(app)
        self._auth_token = auth_token

    async def dispatch(self, request: Request, call_next):
        if not self._auth_token:
            return await call_next(request)

        path = request.url.path.rstrip("/") or "/"
        # UI pages and health checks are always public
        if path in PUBLIC_PATHS or path in UI_PATHS:
            return await call_next(request)

        # API endpoints under /api/ require bearer auth
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            if token == self._auth_token:
                return await call_next(request)

        return JSONResponse(status_code=401, content={"error": {"message": "Invalid or missing bearer token", "type": "auth_error"}})
