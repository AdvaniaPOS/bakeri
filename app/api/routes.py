"""
Route management API endpoints. Tenant-scoped.
"""
from datetime import date
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..database import get_db
from ..dependencies import get_current_tenant
from ..auth_models import Tenant
from ..models import Route, Customer, Order, OrderLine, OrderStatus, RoutePostalRule
from ..schemas import (
    RouteCreate, RouteUpdate, RouteResponse, RouteWithCustomers,
    RouteListResponse, RoutePostalRuleCreate, RoutePostalRuleResponse,
    RoutePostalAutoAssignPreview,
)
from ..tenant_scope import get_or_404
from ..features import feature_required

router = APIRouter(
    prefix="/routes",
    tags=["Routes"],
    dependencies=[Depends(feature_required("routes"))],
)


@router.get("", response_model=RouteListResponse)
async def list_routes(
    include_inactive: bool = False,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    query = select(Route).where(Route.tenant_id == tenant.id).order_by(Route.sort_order, Route.name)
    if not include_inactive:
        query = query.where(Route.is_active == True)
    routes = db.execute(query).scalars().all()
    return {"items": routes, "total": len(routes)}


@router.post("", response_model=RouteResponse, status_code=status.HTTP_201_CREATED)
async def create_route(
    route_data: RouteCreate,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    existing = db.execute(
        select(Route).where(Route.tenant_id == tenant.id, Route.name == route_data.name)
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=400, detail=f"Route with name '{route_data.name}' already exists")

    route = Route(tenant_id=tenant.id, **route_data.model_dump())
    db.add(route)
    db.commit()
    db.refresh(route)
    return route


@router.get("/{route_id}", response_model=RouteWithCustomers)
async def get_route(
    route_id: int,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    route = db.execute(
        select(Route)
        .where(Route.id == route_id, Route.tenant_id == tenant.id)
        .options(selectinload(Route.customers))
    ).scalar_one_or_none()
    if not route:
        raise HTTPException(status_code=404, detail="Route not found")

    return {
        "id": route.id,
        "name": route.name,
        "description": route.description,
        "delivery_days": route.delivery_days,
        "default_start_time": route.default_start_time,
        "is_active": route.is_active,
        "sort_order": route.sort_order,
        "created_at": route.created_at,
        "updated_at": route.updated_at,
        "customers": route.customers,
        "customer_count": len(route.customers) if route.customers else 0,
    }


@router.put("/{route_id}", response_model=RouteResponse)
async def update_route(
    route_id: int,
    route_data: RouteUpdate,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    route = get_or_404(db, Route, route_id, tenant.id, "Route not found")

    if route_data.name and route_data.name != route.name:
        existing = db.execute(
            select(Route).where(Route.tenant_id == tenant.id, Route.name == route_data.name)
        ).scalar_one_or_none()
        if existing:
            raise HTTPException(status_code=400, detail=f"Route with name '{route_data.name}' already exists")

    for key, value in route_data.model_dump(exclude_unset=True).items():
        setattr(route, key, value)

    db.commit()
    db.refresh(route)
    return route


@router.delete("/{route_id}")
async def delete_route(
    route_id: int,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    route = get_or_404(db, Route, route_id, tenant.id, "Route not found")
    customer_count = len(route.customers) if route.customers else 0
    db.delete(route)
    db.commit()
    return {"message": f"Route '{route.name}' deleted", "customers_unassigned": customer_count}


@router.post("/{route_id}/assign-customers")
async def assign_customers_to_route(
    route_id: int,
    customer_ids: List[int],
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    route = get_or_404(db, Route, route_id, tenant.id, "Route not found")

    customers = db.execute(
        select(Customer).where(
            Customer.tenant_id == tenant.id,
            Customer.id.in_(customer_ids),
        )
    ).scalars().all()

    for customer in customers:
        customer.route_id = route_id

    db.commit()
    return {"route_id": route_id, "route_name": route.name, "customers_assigned": len(customers)}


@router.post("/{route_id}/remove-customer/{customer_id}")
async def remove_customer_from_route(
    route_id: int,
    customer_id: int,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    customer = db.execute(
        select(Customer).where(
            Customer.tenant_id == tenant.id,
            Customer.id == customer_id,
            Customer.route_id == route_id,
        )
    ).scalar_one_or_none()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found or not on this route")
    customer.route_id = None
    db.commit()
    return {"message": f"Customer '{customer.name}' removed from route"}


@router.get("/{route_id}/orders/{delivery_date}")
async def get_route_orders(
    route_id: int,
    delivery_date: date,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    route = get_or_404(db, Route, route_id, tenant.id, "Route not found")

    orders = db.execute(
        select(Order)
        .join(Customer)
        .where(
            Order.tenant_id == tenant.id,
            Customer.route_id == route_id,
            Order.delivery_date == delivery_date,
            Order.is_deleted == False,
            Order.status != OrderStatus.CANCELLED,
        )
        .options(
            selectinload(Order.customer),
            selectinload(Order.lines).selectinload(OrderLine.product),
        )
        .order_by(Order.route_position.nullslast(), Customer.name)
    ).scalars().all()

    return {
        "route_id": route_id,
        "route_name": route.name,
        "delivery_date": delivery_date,
        "orders": [
            {
                "order_id": order.id,
                "customer_id": order.customer_id,
                "customer_name": order.customer.name,
                "company_name": order.customer.company_name,
                "address": f"{order.customer.street_address}, {order.customer.postal_code} {order.customer.city}",
                "phone": order.customer.phone,
                "status": order.status.value,
                "route_position": order.route_position,
                "lines": [
                    {"product_name": line.product.name, "quantity": line.quantity, "unit": line.product.unit}
                    for line in order.lines
                ],
            }
            for order in orders
        ],
        "total_orders": len(orders),
    }


@router.put("/{route_id}/reorder")
async def reorder_route_customers(
    route_id: int,
    customer_order: List[int],
    target_date: date,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    get_or_404(db, Route, route_id, tenant.id, "Route not found")

    for position, customer_id in enumerate(customer_order):
        order = db.execute(
            select(Order).where(
                Order.tenant_id == tenant.id,
                Order.customer_id == customer_id,
                Order.delivery_date == target_date,
                Order.is_deleted == False,
            )
        ).scalar_one_or_none()
        if order:
            order.route_position = position + 1

    db.commit()
    return {"message": f"Reordered {len(customer_order)} stops for {target_date}"}


# =============================================================================
# POSTAL CODE RULES
# =============================================================================

@router.get("/{route_id}/postal-rules", response_model=List[RoutePostalRuleResponse])
async def list_postal_rules(
    route_id: int,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    get_or_404(db, Route, route_id, tenant.id, "Route not found")
    rules = db.execute(
        select(RoutePostalRule).where(
            RoutePostalRule.tenant_id == tenant.id,
            RoutePostalRule.route_id == route_id,
        ).order_by(RoutePostalRule.from_code)
    ).scalars().all()
    return rules


@router.post("/{route_id}/postal-rules", response_model=RoutePostalRuleResponse, status_code=status.HTTP_201_CREATED)
async def add_postal_rule(
    route_id: int,
    payload: RoutePostalRuleCreate,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    get_or_404(db, Route, route_id, tenant.id, "Route not found")
    if payload.from_code > payload.to_code:
        raise HTTPException(status_code=400, detail="from_code maa vaere mindre eller lik to_code")
    rule = RoutePostalRule(
        tenant_id=tenant.id,
        route_id=route_id,
        from_code=payload.from_code,
        to_code=payload.to_code,
        label=payload.label,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


@router.delete("/{route_id}/postal-rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_postal_rule(
    route_id: int,
    rule_id: int,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    rule = db.execute(
        select(RoutePostalRule).where(
            RoutePostalRule.id == rule_id,
            RoutePostalRule.route_id == route_id,
            RoutePostalRule.tenant_id == tenant.id,
        )
    ).scalar_one_or_none()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    db.delete(rule)
    db.commit()


def _find_matching_customers(db: Session, tenant_id: int, route_id: int):
    rules = db.execute(
        select(RoutePostalRule).where(
            RoutePostalRule.tenant_id == tenant_id,
            RoutePostalRule.route_id == route_id,
        )
    ).scalars().all()
    if not rules:
        return [], rules
    from sqlalchemy import or_, and_
    conditions = [
        and_(Customer.postal_code >= r.from_code, Customer.postal_code <= r.to_code)
        for r in rules
    ]
    customers = db.execute(
        select(Customer).where(
            Customer.tenant_id == tenant_id,
            Customer.is_deleted == False,
            Customer.is_active == True,
            Customer.postal_code.isnot(None),
            Customer.postal_code != '',
            or_(*conditions),
        )
    ).scalars().all()
    return customers, rules


@router.get("/{route_id}/auto-assign-preview", response_model=RoutePostalAutoAssignPreview)
async def auto_assign_preview(
    route_id: int,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    get_or_404(db, Route, route_id, tenant.id, "Route not found")
    customers, rules = _find_matching_customers(db, tenant.id, route_id)
    if not rules:
        raise HTTPException(status_code=400, detail="Ingen postnummer-regler definert for denne ruten")
    new_assign = []
    already = 0
    conflicts = []
    for c in customers:
        if c.route_id == route_id:
            already += 1
        elif c.route_id is None:
            new_assign.append(c.id)
        else:
            conflicts.append({"customer_id": c.id, "name": c.name, "current_route_id": c.route_id, "postal_code": c.postal_code})
    return RoutePostalAutoAssignPreview(
        matched_customers=len(customers),
        new_assignments=len(new_assign),
        already_on_route=already,
        conflicts=len(conflicts),
        customer_ids_to_assign=new_assign,
        conflict_examples=conflicts[:10],
    )


@router.post("/{route_id}/auto-assign-commit")
async def auto_assign_commit(
    route_id: int,
    overwrite_conflicts: bool = False,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    get_or_404(db, Route, route_id, tenant.id, "Route not found")
    customers, rules = _find_matching_customers(db, tenant.id, route_id)
    if not rules:
        raise HTTPException(status_code=400, detail="Ingen postnummer-regler definert for denne ruten")
    assigned = 0
    for c in customers:
        if c.route_id is None or (overwrite_conflicts and c.route_id != route_id):
            c.route_id = route_id
            assigned += 1
    db.commit()
    return {"assigned": assigned, "matched": len(customers)}
