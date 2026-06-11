"""
Reports & analytics endpoints. Tenant-scoped.
"""
import logging
from collections import defaultdict
from datetime import date, timedelta
from typing import List, Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..database import get_db
from ..dependencies import get_current_tenant
from ..auth_models import Tenant
from ..models import Order, OrderLine, Customer, Product, Route, OrderStatus
from ..tenant_scope import get_or_404
from ..services.pdf import render_pdf, tenant_header_context

logger = logging.getLogger(__name__)


def _pdf_response(pdf_bytes: bytes, filename: str) -> Response:
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


def _render_pdf_response(template_name: str, context: dict, filename: str) -> Response:
    try:
        pdf = render_pdf(template_name, context)
    except OSError as exc:
        logger.exception("PDF-generering utilgjengelig for %s", filename)
        raise HTTPException(
            status_code=503,
            detail=(
                "PDF-generering er ikke tilgjengelig på denne maskinen. "
                "Backend mangler WeasyPrint-systembiblioteker "
                "(for eksempel GTK/libgobject)."
            ),
        ) from exc
    except Exception as exc:
        logger.exception("PDF-generering feilet for %s", filename)
        raise HTTPException(
            status_code=500,
            detail=f"Klarte ikke generere PDF: {type(exc).__name__}: {exc}",
        ) from exc
    return _pdf_response(pdf, filename)


def _status_label(status: OrderStatus) -> str:
    return {
        OrderStatus.DRAFT: "Utkast",
        OrderStatus.CONFIRMED: "Bekreftet",
        OrderStatus.READY_FOR_DELIVERY: "Klar for levering",
        OrderStatus.IN_TRANSIT: "Under levering",
        OrderStatus.DELIVERED: "Levert",
        OrderStatus.CANCELLED: "Kansellert",
    }.get(status, str(status))

router = APIRouter(prefix="/reports", tags=["Reports"])

NORWEGIAN_DAYS = ["Mandag", "Tirsdag", "Onsdag", "Torsdag", "Fredag", "Lørdag", "Søndag"]


def _active_orders_query(tenant_id: int, target_date: date):
    return (
        select(Order)
        .where(
            Order.tenant_id == tenant_id,
            Order.delivery_date == target_date,
            Order.is_deleted == False,
            Order.status != OrderStatus.CANCELLED,
        )
        .options(
            selectinload(Order.customer),
            selectinload(Order.lines).selectinload(OrderLine.product),
        )
    )


@router.get("/production/{target_date}")
async def get_production_report(
    target_date: date,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    orders = db.execute(_active_orders_query(tenant.id, target_date)).scalars().all()

    products_agg = {}
    customers = set()
    for order in orders:
        customers.add(order.customer_id)
        for line in order.lines:
            p = line.product
            if not p:
                continue
            entry = products_agg.setdefault(p.id, {
                "product_id": p.id,
                "product_name": p.name,
                "category": p.category or "Annet",
                "unit": p.unit,
                "total_quantity": 0,
            })
            entry["total_quantity"] += line.quantity

    by_category = defaultdict(list)
    for entry in products_agg.values():
        by_category[entry["category"]].append(entry)
    for cat in by_category:
        by_category[cat].sort(key=lambda x: x["product_name"])

    return {
        "date": target_date,
        "total_orders": len(orders),
        "total_customers": len(customers),
        "total_products": len(products_agg),
        "products_by_category": dict(by_category),
    }


@router.get("/production-batches/{target_date}")
async def get_production_batches(
    target_date: date,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    """Produksjonsplan med batch-runding gruppert pr. produksjons-stasjon.

    For hvert produkt:
      - bestilt_antall  = sum av alle ordre-linjer
      - batch_size      = `Product.batch_size` (default 1)
      - batches         = ceil(bestilt / batch_size)
      - skal_bake       = batches * batch_size  (rundet opp)
      - overskudd       = skal_bake - bestilt   (til butikk/nettsalg)
      - estimert_tid    = batches * production_lead_minutes
    """
    import math

    orders = db.execute(_active_orders_query(tenant.id, target_date)).scalars().all()

    products_agg: dict[int, dict] = {}
    customers: set[int] = set()
    for order in orders:
        customers.add(order.customer_id)
        for line in order.lines:
            p = line.product
            if not p:
                continue
            entry = products_agg.setdefault(p.id, {
                "product_id": p.id,
                "product_name": p.name,
                "unit": p.unit,
                "category": p.category or "Annet",
                "production_step": p.production_step or "Uplassert",
                "batch_size": max(1, p.batch_size or 1),
                "lead_minutes": p.production_lead_minutes or 0,
                "ordered_quantity": 0,
            })
            entry["ordered_quantity"] += line.quantity

    # Rund opp til hele batches
    by_step: dict[str, list[dict]] = defaultdict(list)
    grand_total_minutes = 0
    grand_total_batches = 0
    for entry in products_agg.values():
        ordered = entry["ordered_quantity"]
        bs = entry["batch_size"]
        batches = math.ceil(ordered / bs) if ordered > 0 else 0
        bake = batches * bs
        entry["batches"] = batches
        entry["bake_quantity"] = bake
        entry["surplus"] = max(0, bake - ordered)
        entry["estimated_minutes"] = batches * entry["lead_minutes"]
        grand_total_minutes += entry["estimated_minutes"]
        grand_total_batches += batches
        by_step[entry["production_step"]].append(entry)

    # Sorter pr. stasjon: tyngste batches først
    steps = []
    for step_name, items in by_step.items():
        items.sort(key=lambda x: (-x["batches"], x["product_name"]))
        steps.append({
            "step": step_name,
            "items": items,
            "total_batches": sum(i["batches"] for i in items),
            "total_minutes": sum(i["estimated_minutes"] for i in items),
            "total_bake_quantity": sum(i["bake_quantity"] for i in items),
        })
    steps.sort(key=lambda s: (-s["total_batches"], s["step"]))

    return {
        "date": target_date,
        "total_orders": len(orders),
        "total_customers": len(customers),
        "total_products": len(products_agg),
        "total_batches": grand_total_batches,
        "total_minutes": grand_total_minutes,
        "steps": steps,
    }


@router.get("/production-week")
async def get_weekly_production_overview(
    start_date: date,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    days = []
    total_orders = 0
    total_customers = set()
    for i in range(7):
        d = start_date + timedelta(days=i)
        orders = db.execute(_active_orders_query(tenant.id, d)).scalars().all()
        cust_ids = {o.customer_id for o in orders}
        total_orders += len(orders)
        total_customers.update(cust_ids)
        days.append({
            "date": d,
            "day_name": NORWEGIAN_DAYS[d.weekday()],
            "order_count": len(orders),
            "customer_count": len(cust_ids),
        })

    return {
        "start_date": start_date,
        "end_date": start_date + timedelta(days=6),
        "days": days,
        "total_orders": total_orders,
        "total_customers": len(total_customers),
    }


def _build_stops(orders):
    stops = []
    total_items = 0
    for idx, order in enumerate(sorted(orders, key=lambda o: (o.route_position or 9999, o.customer.name if o.customer else ""))):
        cust = order.customer
        if not cust:
            continue
        addr = ", ".join(filter(None, [
            cust.street_address,
            f"{cust.postal_code or ''} {cust.city or ''}".strip(),
        ]))
        line_items = [
            {
                "product_name": line.product.name if line.product else "?",
                "quantity": line.quantity,
                "unit": line.product.unit if line.product else "",
            }
            for line in order.lines
        ]
        items_count = sum(l["quantity"] for l in line_items)
        total_items += items_count
        stops.append({
            "stop_number": idx + 1,
            "order_id": order.id,
            "customer_id": cust.id,
            "customer_name": cust.name,
            "company_name": cust.company_name,
            "address": addr,
            "phone": cust.phone,
            "delivery_instructions": cust.delivery_instructions,
            "delivery_window": {
                "start": cust.delivery_window_start.isoformat() if cust.delivery_window_start else None,
                "end": cust.delivery_window_end.isoformat() if cust.delivery_window_end else None,
            },
            "lines": line_items,
            "total_items": items_count,
        })
    return stops, total_items


@router.get("/delivery-list/{route_id}/{target_date}")
async def get_route_delivery_list(
    route_id: int,
    target_date: date,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    route = get_or_404(db, Route, route_id, tenant.id, "Route not found")

    orders = db.execute(
        _active_orders_query(tenant.id, target_date)
        .join(Customer, Customer.id == Order.customer_id)
        .where(Customer.route_id == route_id)
    ).scalars().all()

    stops, total_items = _build_stops(orders)
    return {
        "route_id": route.id,
        "route_name": route.name,
        "date": target_date,
        "stops": stops,
        "total_stops": len(stops),
        "total_items": total_items,
    }


@router.get("/delivery-list/{route_id}/{target_date}/google-maps-url")
async def get_google_maps_route_url(
    route_id: int,
    target_date: date,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    route = get_or_404(db, Route, route_id, tenant.id, "Route not found")

    orders = db.execute(
        _active_orders_query(tenant.id, target_date)
        .join(Customer, Customer.id == Order.customer_id)
        .where(Customer.route_id == route_id)
    ).scalars().all()

    addresses = []
    for order in sorted(orders, key=lambda o: o.route_position or 9999):
        cust = order.customer
        if not cust:
            continue
        addr = ", ".join(filter(None, [
            cust.street_address,
            f"{cust.postal_code or ''} {cust.city or ''}".strip(),
        ]))
        if addr:
            addresses.append(addr)

    # Fallback: hvis ingen ordrer for valgt dato, bruk rutens tilordnede kunder
    # (slik at brukeren kan se kartet for ruten selv om ingen leveringer er
    # planlagt akkurat den dagen).
    used_fallback = False
    if not addresses:
        used_fallback = True
        customers = db.execute(
            select(Customer).where(
                Customer.tenant_id == tenant.id,
                Customer.route_id == route_id,
                Customer.is_deleted == False,
                Customer.is_active == True,
            ).order_by(Customer.name)
        ).scalars().all()
        for cust in customers:
            addr = ", ".join(filter(None, [
                cust.street_address,
                f"{cust.postal_code or ''} {cust.city or ''}".strip(),
            ]))
            if addr:
                addresses.append(addr)

    if not addresses:
        raise HTTPException(
            status_code=404,
            detail="Ingen kunder med adresse paa denne ruten. Tilordne kunder med gateadresse forst."
        )

    if len(addresses) == 1:
        url = f"https://www.google.com/maps/search/?api=1&query={quote(addresses[0])}"
    else:
        origin = quote(addresses[0])
        destination = quote(addresses[-1])
        waypoints = "|".join(quote(a) for a in addresses[1:-1])
        url = f"https://www.google.com/maps/dir/?api=1&origin={origin}&destination={destination}"
        if waypoints:
            url += f"&waypoints={waypoints}"
        url += "&travelmode=driving"

    return {
        "url": url,
        "stops": len(addresses),
        "route_name": route.name,
        "fallback_used": used_fallback,
    }


@router.get("/delivery-summary/{target_date}")
async def get_all_routes_delivery_summary(
    target_date: date,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    routes = db.execute(
        select(Route).where(Route.tenant_id == tenant.id, Route.is_active == True)
    ).scalars().all()

    summaries = []
    for route in routes:
        orders = db.execute(
            _active_orders_query(tenant.id, target_date)
            .join(Customer, Customer.id == Order.customer_id)
            .where(Customer.route_id == route.id)
        ).scalars().all()
        total_items = sum(line.quantity for o in orders for line in o.lines)
        summaries.append({
            "route_id": route.id,
            "route_name": route.name,
            "stops": len(orders),
            "total_items": total_items,
        })

    return {"date": target_date, "routes": summaries}


@router.get("/packing-slip/{order_id}")
async def get_packing_slip(
    order_id: int,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    order = db.execute(
        select(Order)
        .where(Order.id == order_id, Order.tenant_id == tenant.id)
        .options(
            selectinload(Order.customer),
            selectinload(Order.lines).selectinload(OrderLine.product),
        )
    ).scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    cust = order.customer
    return {
        "order_id": order.id,
        "delivery_date": order.delivery_date,
        "customer": {
            "name": cust.name if cust else None,
            "company_name": cust.company_name if cust else None,
            "address": ", ".join(filter(None, [
                cust.street_address if cust else None,
                f"{cust.postal_code or ''} {cust.city or ''}".strip() if cust else None,
            ])),
            "phone": cust.phone if cust else None,
            "delivery_instructions": cust.delivery_instructions if cust else None,
        },
        "lines": [
            {
                "product_name": line.product.name if line.product else "?",
                "quantity": line.quantity,
                "unit": line.product.unit if line.product else "",
                "notes": line.notes,
            }
            for line in order.lines
        ],
        "total_amount_excl_vat": float(order.total_amount_excl_vat or 0),
        "total_vat": float(order.total_vat or 0),
        "total_amount_incl_vat": float(order.total_amount_incl_vat or 0),
        "notes": order.notes,
    }


@router.get("/route-packing-slips/{route_id}/{target_date}")
async def get_route_packing_slips(
    route_id: int,
    target_date: date,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    get_or_404(db, Route, route_id, tenant.id, "Route not found")

    orders = db.execute(
        _active_orders_query(tenant.id, target_date)
        .join(Customer, Customer.id == Order.customer_id)
        .where(Customer.route_id == route_id)
    ).scalars().all()

    return [
        await get_packing_slip(order.id, db, tenant)
        for order in sorted(orders, key=lambda o: o.route_position or 9999)
    ]


@router.get("/customer-history/{customer_id}")
async def get_customer_order_history(
    customer_id: int,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    limit: int = 100,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    get_or_404(db, Customer, customer_id, tenant.id, "Customer not found")

    query = (
        select(Order)
        .where(
            Order.tenant_id == tenant.id,
            Order.customer_id == customer_id,
            Order.is_deleted == False,
        )
        .options(selectinload(Order.lines).selectinload(OrderLine.product))
        .order_by(Order.delivery_date.desc())
        .limit(limit)
    )
    if from_date:
        query = query.where(Order.delivery_date >= from_date)
    if to_date:
        query = query.where(Order.delivery_date <= to_date)

    orders = db.execute(query).scalars().all()

    return [
        {
            "order_id": o.id,
            "delivery_date": o.delivery_date,
            "status": o.status.value,
            "total_amount_incl_vat": float(o.total_amount_incl_vat or 0),
            "lines_count": len(o.lines),
            "lines": [
                {
                    "product_name": l.product.name if l.product else "?",
                    "quantity": l.quantity,
                    "unit_price": float(l.unit_price),
                }
                for l in o.lines
            ],
        }
        for o in orders
    ]


# === PDF endepunkter ===


def _build_packing_list_data(tenant_id: int, target_date: date, db: Session) -> dict:
    """Henter alle ordre for dato gruppert pr kunde — for pakkeliste og etiketter."""
    orders = db.execute(_active_orders_query(tenant_id, target_date)).scalars().all()
    customers = []
    total_items = 0
    for order in sorted(orders, key=lambda o: (o.customer.name if o.customer else "")):
        cust = order.customer
        if not cust:
            continue
        addr = ", ".join(filter(None, [
            cust.street_address,
            f"{cust.postal_code or ''} {cust.city or ''}".strip(),
        ]))
        lines = [
            {
                "product_name": line.product.name if line.product else "?",
                "quantity": line.quantity,
                "unit": line.product.unit if line.product else "",
                "allergens": getattr(line.product, "allergens", None) if line.product else None,
            }
            for line in order.lines
        ]
        items_count = sum(l["quantity"] for l in lines)
        total_items += items_count
        # Aggreger unike allergener for hele kundens ordre
        allergen_set = set()
        for l in lines:
            if l.get("allergens"):
                for a in str(l["allergens"]).split(","):
                    a = a.strip()
                    if a:
                        allergen_set.add(a)
        customers.append({
            "customer_name": cust.name,
            "company_name": cust.company_name,
            "address": addr,
            "phone": cust.phone,
            "order_id": order.id,
            "order_no_display": order.order_no_display,
            "reference": order.reference,
            "delivery_date": order.delivery_date,
            "delivery_window_start": cust.delivery_window_start.isoformat() if cust.delivery_window_start else None,
            "delivery_window_end": cust.delivery_window_end.isoformat() if cust.delivery_window_end else None,
            "delivery_instructions": cust.delivery_instructions,
            "lines": lines,
            "allergens_summary": ", ".join(sorted(allergen_set)) if allergen_set else None,
        })
    return {"customers": customers, "total_items": total_items}


@router.get("/pdf/production/{target_date}")
async def production_report_pdf(
    target_date: date,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    data = await get_production_report(target_date, db, tenant)
    ctx = {
        **tenant_header_context(tenant),
        "target_date": target_date,
        "total_orders": data["total_orders"],
        "total_customers": data["total_customers"],
        "total_products": data["total_products"],
        "products_by_category": data["products_by_category"],
    }
    return _render_pdf_response(
        "production_report.html",
        ctx,
        f"produksjon-{target_date.isoformat()}.pdf",
    )


@router.get("/pdf/packing-list/{target_date}")
async def packing_list_pdf(
    target_date: date,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    data = _build_packing_list_data(tenant.id, target_date, db)
    ctx = {
        **tenant_header_context(tenant),
        "target_date": target_date,
        **data,
    }
    return _render_pdf_response(
        "packing_list.html",
        ctx,
        f"pakkeliste-{target_date.isoformat()}.pdf",
    )


@router.get("/pdf/order/{order_id}/confirmation")
async def order_confirmation_pdf(
    order_id: int,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    try:
        return _generate_order_confirmation_pdf(db, order_id, tenant)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "order_confirmation_pdf feilet for order_id=%s tenant_id=%s",
            order_id, tenant.id,
        )
        raise HTTPException(
            status_code=500,
            detail=f"Klarte ikke generere PDF: {type(exc).__name__}: {exc}",
        )


def _customer_context(cust) -> dict:
    """Komplett kunde-info for proff PDF-utseende."""
    if not cust:
        return {"name": "Ukjent kunde"}
    delivery_window = None
    ws, we = getattr(cust, "delivery_window_start", None), getattr(cust, "delivery_window_end", None)
    if ws and we:
        delivery_window = f"{ws.strftime('%H:%M')}–{we.strftime('%H:%M')}"
    elif ws:
        delivery_window = f"fra {ws.strftime('%H:%M')}"
    elif we:
        delivery_window = f"innen {we.strftime('%H:%M')}"
    return {
        "id": cust.id,
        "name": cust.name or "",
        "company_name": cust.company_name,
        "org_number": cust.org_number,
        "contact_person": cust.contact_person,
        "email": cust.email,
        "phone": cust.phone,
        "street_address": cust.street_address,
        "postal_code": cust.postal_code,
        "city": cust.city,
        "country": cust.country if cust.country and cust.country != "Norway" else None,
        "address": ", ".join(filter(None, [
            cust.street_address,
            f"{cust.postal_code or ''} {cust.city or ''}".strip(),
        ])),
        "delivery_instructions": cust.delivery_instructions,
        "delivery_window": delivery_window,
        "susoft_customer_id": getattr(cust, "susoft_customer_id", None),
    }


def _generate_order_confirmation_pdf(db: Session, order_id: int, tenant: Tenant) -> Response:
    order = db.execute(
        select(Order)
        .where(Order.id == order_id, Order.tenant_id == tenant.id)
        .options(
            selectinload(Order.customer),
            selectinload(Order.lines).selectinload(OrderLine.product),
        )
    ).scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    cust = order.customer
    lines = [
        {
            "product_name": l.product.name if l.product else "?",
            "quantity": l.quantity,
            "unit": l.product.unit if l.product else "",
            "unit_price": float(l.unit_price or 0),
            "vat_rate": float(l.vat_rate or 0),
            "line_amount_excl_vat": float((l.unit_price or 0) * l.quantity),
            "notes": l.notes,
            "allergens": getattr(l.product, "allergens", None) if l.product else None,
        }
        for l in order.lines
    ]
    allergen_set = set()
    for l in lines:
        if l.get("allergens"):
            for a in str(l["allergens"]).split(","):
                a = a.strip()
                if a:
                    allergen_set.add(a)
    allergens_summary = ", ".join(sorted(allergen_set)) if allergen_set else None
    ctx = {
        **tenant_header_context(tenant),
        "order": {
            "id": order.id,
            "delivery_date": order.delivery_date,
            "notes": order.customer_notes or order.internal_notes,
            "customer_notes": order.customer_notes,
            "internal_notes": order.internal_notes,
            "order_no_display": order.order_no_display,
            "reference": order.reference,
            "created_at": order.created_at,
            "susoft_pickup_at": order.susoft_pickup_at,
            "susoft_delivery_at": order.susoft_delivery_at,
        },
        "status_label": _status_label(order.status),
        "customer": _customer_context(cust),
        "lines": lines,
        "allergens_summary": allergens_summary,
        "totals": {
            "excl_vat": float(order.total_amount_excl_vat or 0),
            "vat": float(order.total_vat or 0),
            "incl_vat": float(order.total_amount_incl_vat or 0),
        },
    }
    pdf = render_pdf("order_confirmation.html", ctx)
    return _pdf_response(pdf, f"ordre-{order.id}-bekreftelse.pdf")
@router.get("/order/{order_id}/delivery.pdf")
async def delivery_confirmation_pdf(
    order_id: int,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    from ..models import OrderAmendment
    order = db.execute(
        select(Order)
        .where(Order.id == order_id, Order.tenant_id == tenant.id)
        .options(
            selectinload(Order.customer),
            selectinload(Order.lines).selectinload(OrderLine.product),
            selectinload(Order.amendments),
        )
    ).scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    cust = order.customer
    lines = [
        {
            "product_name": l.product.name if l.product else "?",
            "quantity": l.quantity,
            "unit": l.product.unit if l.product else "",
            "notes": l.notes,
            "allergens": getattr(l.product, "allergens", None) if l.product else None,
        }
        for l in order.lines
    ]
    allergen_set = set()
    for l in lines:
        if l.get("allergens"):
            for a in str(l["allergens"]).split(","):
                a = a.strip()
                if a:
                    allergen_set.add(a)
    allergens_summary = ", ".join(sorted(allergen_set)) if allergen_set else None

    ctx = {
        **tenant_header_context(tenant),
        "order": {
            "id": order.id,
            "order_no_display": order.order_no_display,
            "delivery_date": order.delivery_date,
            "reference": order.reference,
            "created_at": order.created_at,
            "customer_notes": order.customer_notes,
            "susoft_pickup_at": order.susoft_pickup_at,
            "susoft_delivery_at": order.susoft_delivery_at,
        },
        "customer": _customer_context(cust),
        "lines": lines,
        "allergens_summary": allergens_summary,
        "amendments": sorted(order.amendments, key=lambda a: a.amended_at),
    }
    pdf = render_pdf("delivery_confirmation.html", ctx)
    fname = order.order_no_display or f"ordre-{order.id}"
    return _pdf_response(pdf, f"{fname}-leveringsbekreftelse.pdf")


@router.get("/pdf/delivery-list/{route_id}/{target_date}")
async def delivery_list_pdf(
    route_id: int,
    target_date: date,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    """Pakkeliste pr kunde for én rute på én dato."""
    route = get_or_404(db, Route, route_id, tenant.id, "Route not found")

    orders = db.execute(
        _active_orders_query(tenant.id, target_date)
        .join(Customer, Customer.id == Order.customer_id)
        .where(Customer.route_id == route_id)
    ).scalars().all()

    customers = []
    total_items = 0
    for order in sorted(orders, key=lambda o: (o.route_position or 9999, o.customer.name if o.customer else "")):
        cust = order.customer
        if not cust:
            continue
        addr = ", ".join(filter(None, [
            cust.street_address,
            f"{cust.postal_code or ''} {cust.city or ''}".strip(),
        ]))
        lines = [
            {
                "product_name": line.product.name if line.product else "?",
                "quantity": line.quantity,
                "unit": line.product.unit if line.product else "",
            }
            for line in order.lines
        ]
        total_items += sum(l["quantity"] for l in lines)
        customers.append({
            "customer_name": cust.name,
            "company_name": cust.company_name,
            "address": addr,
            "phone": cust.phone,
            "order_id": order.id,
            "order_no_display": order.order_no_display,
            "reference": order.reference,
            "delivery_date": order.delivery_date,
            "delivery_window_start": cust.delivery_window_start.isoformat() if cust.delivery_window_start else None,
            "delivery_window_end": cust.delivery_window_end.isoformat() if cust.delivery_window_end else None,
            "delivery_instructions": cust.delivery_instructions,
            "lines": lines,
        })

    ctx = {
        **tenant_header_context(tenant),
        "target_date": target_date,
        "customers": customers,
        "total_items": total_items,
        "subtitle": f"Rute: {route.name}",
    }
    pdf = render_pdf("packing_list.html", ctx)
    return _pdf_response(pdf, f"leveringsliste-{route.name}-{target_date.isoformat()}.pdf")


@router.get("/pdf/labels/{target_date}")
async def labels_pdf(
    target_date: date,
    size: str = "ql570",
    route_id: Optional[int] = None,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    """
    Etiketter for alle leveringer på en dato.
    `size`: 'ql570' (Brother 62mm endeløs) eller 'zd421' (Zebra 102×152mm).
    Valgfritt `route_id` for å begrense til én rute.
    """
    if size not in ("ql570", "zd421"):
        raise HTTPException(status_code=400, detail="size must be 'ql570' or 'zd421'")

    query = _active_orders_query(tenant.id, target_date)
    if route_id is not None:
        get_or_404(db, Route, route_id, tenant.id, "Route not found")
        query = query.join(Customer, Customer.id == Order.customer_id).where(Customer.route_id == route_id)

    orders = db.execute(query).scalars().all()

    labels = []
    for order in sorted(orders, key=lambda o: (o.route_position or 9999, o.customer.name if o.customer else "")):
        cust = order.customer
        if not cust:
            continue
        addr = ", ".join(filter(None, [
            cust.street_address,
            f"{cust.postal_code or ''} {cust.city or ''}".strip(),
        ]))
        labels.append({
            "customer_name": cust.name,
            "company_name": cust.company_name,
            "address": addr,
            "phone": cust.phone,
            "delivery_window_start": cust.delivery_window_start.isoformat() if cust.delivery_window_start else None,
            "delivery_window_end": cust.delivery_window_end.isoformat() if cust.delivery_window_end else None,
            "delivery_instructions": cust.delivery_instructions,
            "order_id": order.id,
            "delivery_date": order.delivery_date,
            "lines": [
                {
                    "product_name": line.product.name if line.product else "?",
                    "quantity": line.quantity,
                    "unit": line.product.unit if line.product else "",
                }
                for line in order.lines
            ],
        })

    if not labels:
        raise HTTPException(status_code=404, detail="Ingen leveringer på denne datoen")

    settings = tenant.settings or {}
    ctx = {
        "labels": labels,
        "show_phone": bool(settings.get("labels_show_phone", True)),
        "show_window": bool(settings.get("labels_show_delivery_window", True)),
    }
    template_name = "labels_ql570.html" if size == "ql570" else "labels_zd421.html"
    pdf = render_pdf(template_name, ctx)
    return _pdf_response(pdf, f"etiketter-{size}-{target_date.isoformat()}.pdf")

