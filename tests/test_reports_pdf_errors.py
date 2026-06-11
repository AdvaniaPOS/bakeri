import asyncio
from datetime import date

import pytest
from fastapi import HTTPException

from app.api.reports import production_report_pdf


def test_production_report_pdf_returns_503_for_missing_weasyprint_libs(
    db_session,
    tenant,
    monkeypatch,
):
    def fake_render_pdf(template_name, context):
        raise OSError("cannot load library 'libgobject-2.0-0'")

    monkeypatch.setattr("app.api.reports.render_pdf", fake_render_pdf)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(production_report_pdf(date(2026, 6, 12), db=db_session, tenant=tenant))

    assert exc_info.value.status_code == 503
    assert "WeasyPrint-systembiblioteker" in exc_info.value.detail


def test_production_report_pdf_returns_500_for_other_render_errors(
    db_session,
    tenant,
    monkeypatch,
):
    def fake_render_pdf(template_name, context):
        raise RuntimeError("boom")

    monkeypatch.setattr("app.api.reports.render_pdf", fake_render_pdf)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(production_report_pdf(date(2026, 6, 12), db=db_session, tenant=tenant))

    assert exc_info.value.status_code == 500
    assert "RuntimeError: boom" in exc_info.value.detail