"""
Tenant-scoped structured logging.

Sets up JSON-formatted logging with `tenant_id`, `user_id`, `request_id`
captured automatically from a contextvar set by the request middleware.

Usage:
    from app.logging_config import setup_logging, set_request_context
    setup_logging()  # call once at startup
    # In middleware:
    set_request_context(tenant_id=42, user_id=7, request_id="abc")
"""
from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from typing import Any, Optional

# Per-request context (populated by TenantLoggingMiddleware)
_tenant_id_var: ContextVar[Optional[int]] = ContextVar("tenant_id", default=None)
_user_id_var: ContextVar[Optional[int]] = ContextVar("user_id", default=None)
_request_id_var: ContextVar[Optional[str]] = ContextVar("request_id", default=None)


def set_request_context(
    *,
    tenant_id: Optional[int] = None,
    user_id: Optional[int] = None,
    request_id: Optional[str] = None,
) -> None:
    """Set the per-request logging context. Call from request middleware."""
    if tenant_id is not None:
        _tenant_id_var.set(tenant_id)
    if user_id is not None:
        _user_id_var.set(user_id)
    if request_id is not None:
        _request_id_var.set(request_id)


def reset_request_context() -> None:
    _tenant_id_var.set(None)
    _user_id_var.set(None)
    _request_id_var.set(None)


def get_tenant_id() -> Optional[int]:
    return _tenant_id_var.get()


class TenantContextFilter(logging.Filter):
    """Inject tenant/user/request ids into every LogRecord."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.tenant_id = _tenant_id_var.get()
        record.user_id = _user_id_var.get()
        record.request_id = _request_id_var.get()
        return True


class JsonFormatter(logging.Formatter):
    """Minimal structured JSON formatter."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "tenant_id": getattr(record, "tenant_id", None),
            "user_id": getattr(record, "user_id", None),
            "request_id": getattr(record, "request_id", None),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def setup_logging(level: str = "INFO", json_output: bool = False) -> None:
    """
    Configure root logger. Idempotent.

    json_output=True for production / log aggregators.
    json_output=False for human-readable dev output.
    """
    root = logging.getLogger()
    root.setLevel(level)

    # Remove existing handlers (avoid duplicates on uvicorn reload)
    for h in list(root.handlers):
        root.removeHandler(h)

    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(TenantContextFilter())

    if json_output:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)-7s [tenant=%(tenant_id)s user=%(user_id)s req=%(request_id)s] "
                "%(name)s: %(message)s",
                datefmt="%H:%M:%S",
            )
        )
    root.addHandler(handler)
