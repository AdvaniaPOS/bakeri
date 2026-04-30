"""
PDF-generering via WeasyPrint + Jinja2.

Felles rammeverk for alle utskrifter:
- A4-rapporter: produksjonsrapport, pakkeliste, ordrebekreftelse, leveringsbekreftelse
- Etiketter: Brother QL-570 (62mm endeløs), Zebra ZD421 (102×152mm)

Templates ligger i `app/templates/pdf/`.
"""
from __future__ import annotations

import io
from datetime import date, datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

# WeasyPrint importeres lazy slik at ikke-installerte system-libs ikke
# krasjer hele appen ved oppstart (men /reports/*.pdf vil feile pent).
_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates" / "pdf"

_NORWEGIAN_MONTHS = [
    "januar", "februar", "mars", "april", "mai", "juni",
    "juli", "august", "september", "oktober", "november", "desember",
]
_NORWEGIAN_DAYS = [
    "mandag", "tirsdag", "onsdag", "torsdag", "fredag", "lørdag", "søndag",
]


def _format_date_no(d: date | datetime | None) -> str:
    if d is None:
        return ""
    if isinstance(d, datetime):
        d = d.date()
    return f"{_NORWEGIAN_DAYS[d.weekday()].capitalize()} {d.day}. {_NORWEGIAN_MONTHS[d.month - 1]} {d.year}"


def _format_date_short(d: date | datetime | None) -> str:
    if d is None:
        return ""
    if isinstance(d, datetime):
        d = d.date()
    return f"{d.day}.{d.month}.{d.year}"


def _format_money(value) -> str:
    if value is None:
        return "kr 0,00"
    try:
        n = float(value)
    except (TypeError, ValueError):
        return str(value)
    return f"kr {n:,.2f}".replace(",", " ").replace(".", ",").replace(" ", ".", 1) if False else f"kr {n:.2f}".replace(".", ",")


_jinja_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATES_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
    trim_blocks=True,
    lstrip_blocks=True,
)
_jinja_env.filters["date_no"] = _format_date_no
_jinja_env.filters["date_short"] = _format_date_short
_jinja_env.filters["money"] = _format_money


def render_html(template_name: str, context: dict[str, Any]) -> str:
    """Render et Jinja-template fra app/templates/pdf/ til HTML-streng."""
    template = _jinja_env.get_template(template_name)
    return template.render(**context)


def render_pdf(template_name: str, context: dict[str, Any]) -> bytes:
    """
    Render et Jinja-template til PDF-bytes via WeasyPrint.

    Krever at system-libs er installert (libpango, libcairo, libgdk-pixbuf).
    På Ubuntu: `sudo apt install -y libpango-1.0-0 libpangoft2-1.0-0`.
    """
    from weasyprint import HTML  # lazy import

    html_str = render_html(template_name, context)
    base_url = str(_TEMPLATES_DIR)
    pdf_buffer = io.BytesIO()
    HTML(string=html_str, base_url=base_url).write_pdf(target=pdf_buffer)
    return pdf_buffer.getvalue()


def tenant_header_context(tenant) -> dict[str, Any]:
    """Felles header-informasjon for alle PDF-er."""
    settings = tenant.settings or {}
    return {
        "tenant_name": tenant.name,
        "tenant_address": ", ".join(filter(None, [
            tenant.street_address,
            f"{tenant.postal_code or ''} {tenant.city or ''}".strip(),
        ])),
        "tenant_phone": tenant.phone,
        "tenant_email": tenant.email,
        "tenant_org_number": tenant.org_number,
        "subtitle": settings.get("pdf_header_subtitle") or "",
        "primary_color": tenant.primary_color or "#4F46E5",
        "generated_at": datetime.utcnow(),
    }
