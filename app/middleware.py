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


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Setter sikkerhets-headers på alle HTTP-responser.

    Defensiv hardening på applikasjonsnivå (i tillegg til evt. nginx-config).
    Headers kan justeres via env:
      * SECURITY_CSP                — full CSP-policy (default: streng API-only)
      * SECURITY_HSTS_MAX_AGE       — sekunder (default: 31536000 = 1 år).
                                      Sett til 0 for å deaktivere HSTS.
      * SECURITY_FRAME_OPTIONS      — DENY (default) | SAMEORIGIN
      * SECURITY_REFERRER_POLICY    — default: strict-origin-when-cross-origin
      * SECURITY_PERMISSIONS_POLICY — default: camera=(), microphone=(), geolocation=()
    """

    def __init__(self, app, *, csp: str | None = None) -> None:  # type: ignore[override]
        super().__init__(app)
        import os as _os

        self._csp = csp if csp is not None else _os.getenv(
            "SECURITY_CSP",
            # API svarer aldri med HTML som skal kjøre script — default-src 'none'
            # er trygt og blokkerer alt. Frontend (statisk fra nginx) får sin egen
            # CSP der. Hvis du senere serverer FastAPI docs (Swagger) via samme
            # origin må du justere.
            "default-src 'none'; frame-ancestors 'none'; base-uri 'none'",
        )
        try:
            self._hsts_max_age = int(_os.getenv("SECURITY_HSTS_MAX_AGE", "31536000"))
        except ValueError:
            self._hsts_max_age = 31536000
        self._frame_options = _os.getenv("SECURITY_FRAME_OPTIONS", "DENY")
        self._referrer = _os.getenv(
            "SECURITY_REFERRER_POLICY", "strict-origin-when-cross-origin"
        )
        self._permissions = _os.getenv(
            "SECURITY_PERMISSIONS_POLICY",
            "camera=(), microphone=(), geolocation=(), payment=()",
        )

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        h = response.headers
        # Anti-MIME-sniffing
        h.setdefault("X-Content-Type-Options", "nosniff")
        # Clickjacking-beskyttelse
        h.setdefault("X-Frame-Options", self._frame_options)
        # Referrer-lekkasje
        h.setdefault("Referrer-Policy", self._referrer)
        # Begrens browser-APIer
        h.setdefault("Permissions-Policy", self._permissions)
        # CSP — primært relevant for HTML-responser, men trygt å sette generelt
        h.setdefault("Content-Security-Policy", self._csp)
        # HSTS kun når forespørselen kommer over HTTPS (eller via reverse proxy
        # som setter X-Forwarded-Proto=https). Aldri på vanlig HTTP for å
        # unngå at lokale dev-oppsett blir låst inne.
        if self._hsts_max_age > 0:
            scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
            if scheme == "https":
                h.setdefault(
                    "Strict-Transport-Security",
                    f"max-age={self._hsts_max_age}; includeSubDomains",
                )
        return response


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
