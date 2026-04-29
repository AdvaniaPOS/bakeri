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
from ..models import Route, Customer, Order, OrderLine, OrderStatus
from ..schemas import (
    RouteCreate, RouteUpdate, RouteResponse, RouteWithCustomers,
    RouteListResponse
)
from ..tenant_scope import get_or_404

router = APIRouter(prefix="/routes", tags=["Routes"])


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
