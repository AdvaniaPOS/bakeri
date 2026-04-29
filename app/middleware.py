"""
Request middleware: extract tenant/user from JWT and populate logging context.

Runs before rate-limit & route handlers so every log record emitted during
a request includes tenant_id, user_id, request_id automatically.
"""
from __future__ import annotations

import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from .auth import verify_access_token
from .logging_config import reset_request_context, set_request_context


class TenantContextMiddleware(BaseHTTPMiddleware):
    """Populate logging contextvars from incoming JWT (best-effort)."""

    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
        tenant_id = None
        user_id = None

        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            token_data = verify_access_token(auth.split(" ", 1)[1].strip())
            if token_data:
                tenant_id = token_data.tenant_id
                user_id = token_data.user_id

        set_request_context(
            tenant_id=tenant_id, user_id=user_id, request_id=request_id
        )
        try:
            response = await call_next(request)
        finally:
            reset_request_context()
        response.headers["X-Request-ID"] = request_id
        return response
