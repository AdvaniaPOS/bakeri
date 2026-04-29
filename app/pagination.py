"""
Standardisert paginering for list-endepunkter.

Hindrer at API-et returnerer hundretusenvis av rader.
"""
from typing import Generic, List, TypeVar

from fastapi import Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

T = TypeVar("T")


class PaginationParams:
    """FastAPI-dependency for konsistent paginering."""

    def __init__(
        self,
        page: int = Query(1, ge=1, description="Sidenummer (1-basert)"),
        page_size: int = Query(50, ge=1, le=500, description="Antall per side (max 500)"),
    ):
        self.page = page
        self.page_size = page_size
        self.offset = (page - 1) * page_size
        self.limit = page_size


class Page(BaseModel, Generic[T]):
    """Generisk paginert respons."""

    items: List[T]
    total: int
    page: int
    page_size: int
    total_pages: int


def paginate(db: Session, query, params: PaginationParams):
    """
    Kjør pagineringsspørring. Returnerer (items, total).

    Bruker en separat count-spørring som er mer effektiv enn å materialisere
    hele subquery-en når antall rader er stort.
    """
    count_query = select(func.count()).select_from(query.subquery())
    total = db.execute(count_query).scalar() or 0

    items = db.execute(
        query.offset(params.offset).limit(params.limit)
    ).scalars().all()

    return items, total


def make_page(items, total: int, params: PaginationParams) -> dict:
    """Bygg paginert respons-dict."""
    total_pages = (total + params.page_size - 1) // params.page_size if total else 0
    return {
        "items": items,
        "total": total,
        "page": params.page,
        "page_size": params.page_size,
        "total_pages": total_pages,
    }
