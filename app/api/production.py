"""
Faktisk produksjon + svinn-registrering.

For hver dato vises alle produkter som har planlagt produksjon (sum av
alle ordrelinjer for den datoen), og bakeren kan registrere:
- actual_qty (faktisk produsert)
- waste_returned / waste_burnt / waste_quality / waste_other
- notes

Endpoints:
- GET  /production/{log_date}            henter rader (planlagt + faktisk)
- PUT  /production/{log_date}            upsert flere rader pa en gang
- GET  /production/summary/range         aggregert oversikt for periode
"""
from datetime import date, datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.orm import Session, selectinload

from ..database import get_db
from ..dependencies import get_current_tenant, get_current_user
from ..auth_models import Tenant, User
from ..models import (
    ProductionLog, Product, Order, OrderLine, OrderStatus,
)
from ..services.pdf import render_pdf, tenant_header_context

router = APIRouter(prefix="/production", tags=["Production"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class ProductionLogRow(BaseModel):
    """En rad pr produkt for en gitt dato."""
    product_id: int
    product_name: str
    unit: str
    planned_qty: int
    actual_qty: int = 0
    waste_returned: int = 0
    waste_burnt: int = 0
    waste_quality: int = 0
    waste_other: int = 0
    total_waste: int = 0
    sold_qty: int = 0  # actual - total_waste
    waste_pct: float = 0.0  # av actual
    notes: Optional[str] = None
    log_id: Optional[int] = None  # null hvis ikke registrert ennaa


class ProductionDayResponse(BaseModel):
    log_date: date
    rows: List[ProductionLogRow]
    total_planned: int
    total_actual: int
    total_waste: int
    total_sold: int


class ProductionLogUpsert(BaseModel):
    product_id: int
    actual_qty: int = Field(0, ge=0)
    waste_returned: int = Field(0, ge=0)
    waste_burnt: int = Field(0, ge=0)
    waste_quality: int = Field(0, ge=0)
    waste_other: int = Field(0, ge=0)
    notes: Optional[str] = Field(None, max_length=2000)


class ProductionDayUpsertRequest(BaseModel):
    rows: List[ProductionLogUpsert]


class ProductionRangeRow(BaseModel):
    product_id: int
    product_name: str
    total_planned: int
    total_actual: int
    total_waste: int
    waste_pct: float


class ProductionRangeResponse(BaseModel):
    from_date: date
    to_date: date
    rows: List[ProductionRangeRow]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _planned_per_product(db: Session, tenant_id: int, target_date: date) -> dict:
    """Sum av alle ordrelinjer pr produkt for datoen (aktive ordrer)."""
    rows = db.execute(
        select(OrderLine.product_id, func.sum(OrderLine.quantity).label("qty"))
        .join(Order, Order.id == OrderLine.order_id)
        .where(
            Order.tenant_id == tenant_id,
            Order.delivery_date == target_date,
            Order.is_deleted == False,
            Order.status != OrderStatus.CANCELLED,
        )
        .group_by(OrderLine.product_id)
    ).all()
    return {r.product_id: int(r.qty or 0) for r in rows}


def _row_from(product: Product, planned: int, log: Optional[ProductionLog]) -> ProductionLogRow:
    actual = log.actual_qty if log else 0
    wr = log.waste_returned if log else 0
    wb = log.waste_burnt if log else 0
    wq = log.waste_quality if log else 0
    wo = log.waste_other if log else 0
    total_waste = wr + wb + wq + wo
    sold = max(actual - total_waste, 0)
    pct = round((total_waste / actual * 100), 1) if actual > 0 else 0.0
    return ProductionLogRow(
        product_id=product.id,
        product_name=product.name,
        unit=product.unit or "stk",
        planned_qty=planned,
        actual_qty=actual,
        waste_returned=wr,
        waste_burnt=wb,
        waste_quality=wq,
        waste_other=wo,
        total_waste=total_waste,
        sold_qty=sold,
        waste_pct=pct,
        notes=log.notes if log else None,
        log_id=log.id if log else None,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/{log_date}", response_model=ProductionDayResponse)
async def get_day(
    log_date: date,
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    """
    Henter produksjonsdata for en dato.

    Kilden er sammenstilt:
    - Planlagt = sum av OrderLine.quantity for datoen
    - Eksisterende ProductionLog-rader (faktisk + svinn)
    - Inkluderer ogsa produkter som har logg men ikke planlagt (f.eks. ad-hoc baking)
    """
    planned = _planned_per_product(db, tenant.id, log_date)

    logs = db.execute(
        select(ProductionLog).where(
            ProductionLog.tenant_id == tenant.id,
            ProductionLog.log_date == log_date,
        )
    ).scalars().all()
    logs_by_pid = {l.product_id: l for l in logs}

    # Foren product_ids fra begge kilder
    all_pids = set(planned.keys()) | set(logs_by_pid.keys())
    if not all_pids:
        return ProductionDayResponse(
            log_date=log_date, rows=[], total_planned=0,
            total_actual=0, total_waste=0, total_sold=0,
        )

    products = db.execute(
        select(Product).where(
            Product.tenant_id == tenant.id,
            Product.id.in_(all_pids),
        )
    ).scalars().all()
    products_by_id = {p.id: p for p in products}

    rows = []
    for pid in sorted(all_pids, key=lambda x: products_by_id[x].name if x in products_by_id else ""):
        prod = products_by_id.get(pid)
        if not prod:
            continue
        rows.append(_row_from(prod, planned.get(pid, 0), logs_by_pid.get(pid)))

    return ProductionDayResponse(
        log_date=log_date,
        rows=rows,
        total_planned=sum(r.planned_qty for r in rows),
        total_actual=sum(r.actual_qty for r in rows),
        total_waste=sum(r.total_waste for r in rows),
        total_sold=sum(r.sold_qty for r in rows),
    )


@router.put("/{log_date}", response_model=ProductionDayResponse)
async def upsert_day(
    log_date: date,
    payload: ProductionDayUpsertRequest,
    tenant: Tenant = Depends(get_current_tenant),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Upsert flere rader pa en gang (lagre hele skjemaet).

    Eksisterende rader oppdateres, nye lages. Rader som ikke er med i payload
    rores ikke (sa du kan lagre delvis uten a slette tidligere arbeid).
    """
    planned = _planned_per_product(db, tenant.id, log_date)

    # Hent produkter for validering
    pids = [r.product_id for r in payload.rows]
    if pids:
        products = db.execute(
            select(Product).where(
                Product.tenant_id == tenant.id,
                Product.id.in_(pids),
            )
        ).scalars().all()
        products_by_id = {p.id: p for p in products}
    else:
        products_by_id = {}

    for row in payload.rows:
        if row.product_id not in products_by_id:
            raise HTTPException(404, f"Produkt {row.product_id} finnes ikke")

        existing = db.execute(
            select(ProductionLog).where(
                ProductionLog.tenant_id == tenant.id,
                ProductionLog.log_date == log_date,
                ProductionLog.product_id == row.product_id,
            )
        ).scalar_one_or_none()

        if existing:
            existing.actual_qty = row.actual_qty
            existing.waste_returned = row.waste_returned
            existing.waste_burnt = row.waste_burnt
            existing.waste_quality = row.waste_quality
            existing.waste_other = row.waste_other
            existing.notes = row.notes
            existing.logged_by_user_id = user.id
        else:
            db.add(ProductionLog(
                tenant_id=tenant.id,
                log_date=log_date,
                product_id=row.product_id,
                planned_qty=planned.get(row.product_id, 0),
                actual_qty=row.actual_qty,
                waste_returned=row.waste_returned,
                waste_burnt=row.waste_burnt,
                waste_quality=row.waste_quality,
                waste_other=row.waste_other,
                notes=row.notes,
                logged_by_user_id=user.id,
            ))

    db.commit()
    return await get_day(log_date, tenant=tenant, db=db)


@router.get("/summary/range", response_model=ProductionRangeResponse)
async def range_summary(
    from_date: date = Query(...),
    to_date: date = Query(...),
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    """Aggregert svinn-rapport for en periode (siste 7/30 dager osv.)."""
    if to_date < from_date:
        raise HTTPException(400, "to_date maa vaere >= from_date")
    if (to_date - from_date) > timedelta(days=400):
        raise HTTPException(400, "Maks 400 dagers periode")

    rows = db.execute(
        select(
            ProductionLog.product_id,
            Product.name,
            func.sum(ProductionLog.planned_qty).label("planned"),
            func.sum(ProductionLog.actual_qty).label("actual"),
            func.sum(
                ProductionLog.waste_returned + ProductionLog.waste_burnt
                + ProductionLog.waste_quality + ProductionLog.waste_other
            ).label("waste"),
        )
        .join(Product, Product.id == ProductionLog.product_id)
        .where(
            ProductionLog.tenant_id == tenant.id,
            ProductionLog.log_date >= from_date,
            ProductionLog.log_date <= to_date,
        )
        .group_by(ProductionLog.product_id, Product.name)
        .order_by(Product.name)
    ).all()

    out = []
    for r in rows:
        actual = int(r.actual or 0)
        waste = int(r.waste or 0)
        pct = round((waste / actual * 100), 1) if actual > 0 else 0.0
        out.append(ProductionRangeRow(
            product_id=r.product_id,
            product_name=r.name,
            total_planned=int(r.planned or 0),
            total_actual=actual,
            total_waste=waste,
            waste_pct=pct,
        ))

    return ProductionRangeResponse(
        from_date=from_date, to_date=to_date, rows=out,
    )


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------

@router.get("/pdf/waste")
async def waste_report_pdf(
    from_date: date = Query(...),
    to_date: date = Query(...),
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    """Svinnrapport som PDF for valgt periode."""
    data = await range_summary(from_date=from_date, to_date=to_date, tenant=tenant, db=db)

    total_planned = sum(r.total_planned for r in data.rows)
    total_actual = sum(r.total_actual for r in data.rows)
    total_waste = sum(r.total_waste for r in data.rows)
    total_pct = round((total_waste / total_actual * 100), 1) if total_actual > 0 else 0.0

    ctx = {
        **tenant_header_context(tenant),
        "from_date": from_date,
        "to_date": to_date,
        "rows": [r.model_dump() for r in data.rows],
        "total_planned": total_planned,
        "total_actual": total_actual,
        "total_waste": total_waste,
        "total_waste_pct": total_pct,
        "generated_at": datetime.now(),
    }
    pdf = render_pdf("waste_report.html", ctx)
    filename = f"svinn-{from_date.isoformat()}-{to_date.isoformat()}.pdf"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )
