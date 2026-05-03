"""
Susoft Sync API endpoints.

Provides manual triggers for synchronization operations:
- Sync customers from SuSoft
- Sync products from SuSoft
- Push/update orders to SuSoft
- View sync logs and status
"""
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Order, SyncLog, SyncStatus, OrderStatus
from ..services.susoft import SuSoftService, SuSoftAPIError
from ..services.susoft_ingest import ingest_susoft_orders_for_tenant
from ..dependencies import get_current_tenant
from ..auth_models import Tenant
from ..features import feature_required

router = APIRouter(
    prefix="/sync",
    tags=["Susoft Sync"],
    dependencies=[Depends(feature_required("susoft_sync"))],
)


# =============================================================================
# SYNC STATUS & LOGS
# =============================================================================

@router.get("/status")
async def get_sync_status(db: Session = Depends(get_db)):
    """
    Get overall sync status summary.
    
    Shows:
    - Connection status to SuSoft
    - Pending orders count
    - Failed sync count
    - Last successful sync times
    """
    service = SuSoftService(db)
    
    # Test connection
    connection_ok = service.test_connection()
    
    # Count orders by sync status
    pending_count = db.execute(
        select(func.count(Order.id))
        .where(Order.sync_status == SyncStatus.PENDING, Order.is_deleted == False)
    ).scalar() or 0
    
    failed_count = db.execute(
        select(func.count(Order.id))
        .where(Order.sync_status == SyncStatus.FAILED, Order.is_deleted == False)
    ).scalar() or 0
    
    retry_scheduled_count = db.execute(
        select(func.count(Order.id))
        .where(Order.sync_status == SyncStatus.RETRY_SCHEDULED, Order.is_deleted == False)
    ).scalar() or 0
    
    # Get last successful sync logs
    last_customer_sync = db.execute(
        select(SyncLog)
        .where(SyncLog.sync_type == "customer_sync", SyncLog.was_successful == True)
        .order_by(SyncLog.created_at.desc())
    ).scalars().first()
    
    last_product_sync = db.execute(
        select(SyncLog)
        .where(SyncLog.sync_type == "product_sync", SyncLog.was_successful == True)
        .order_by(SyncLog.created_at.desc())
    ).scalars().first()
    
    last_order_sync = db.execute(
        select(SyncLog)
        .where(SyncLog.sync_type.in_(["order_create", "order_update"]), SyncLog.was_successful == True)
        .order_by(SyncLog.created_at.desc())
    ).scalars().first()
    
    return {
        "susoft_connection": {
            "status": "connected" if connection_ok else "disconnected",
            "ok": connection_ok
        },
        "orders": {
            "pending_sync": pending_count,
            "failed_sync": failed_count,
            "retry_scheduled": retry_scheduled_count
        },
        "last_sync": {
            "customers": last_customer_sync.created_at if last_customer_sync else None,
            "products": last_product_sync.created_at if last_product_sync else None,
            "orders": last_order_sync.created_at if last_order_sync else None
        },
        "checked_at": datetime.utcnow()
    }


@router.get("/logs")
async def get_sync_logs(
    sync_type: Optional[str] = Query(None, description="Filter by sync type"),
    entity_type: Optional[str] = Query(None, description="Filter by entity type"),
    success_only: bool = False,
    failed_only: bool = False,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db)
):
    """
    Get sync logs with filtering.
    
    Useful for debugging sync issues and monitoring.
    """
    query = select(SyncLog).order_by(SyncLog.created_at.desc())
    
    if sync_type:
        query = query.where(SyncLog.sync_type == sync_type)
    if entity_type:
        query = query.where(SyncLog.entity_type == entity_type)
    if success_only:
        query = query.where(SyncLog.was_successful == True)
    if failed_only:
        query = query.where(SyncLog.was_successful == False)
    
    # Count total
    count_query = select(func.count()).select_from(query.subquery())
    total = db.execute(count_query).scalar() or 0
    
    # Get page
    logs = db.execute(
        query.offset((page - 1) * page_size).limit(page_size)
    ).scalars().all()
    
    return {
        "logs": [
            {
                "id": log.id,
                "sync_type": log.sync_type,
                "entity_type": log.entity_type,
                "entity_id": log.entity_id,
                "http_method": log.http_method,
                "endpoint": log.endpoint,
                "response_status_code": log.response_status_code,
                "was_successful": log.was_successful,
                "error_message": log.error_message,
                "attempt_number": log.attempt_number,
                "created_at": log.created_at
            }
            for log in logs
        ],
        "total": total,
        "page": page,
        "page_size": page_size
    }


# =============================================================================
# CUSTOMER/PRODUCT SYNC FROM SUSOFT
# =============================================================================


@router.post("/orders/ingest")
async def ingest_orders_from_susoft(
    days_back: int = Query(30, ge=1, le=365, description="Hvor mange dager bakover (orderDate) som skal pulles."),
    shop_id: Optional[str] = Query(None, description="Begrens til én shopId. Default: alle."),
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    """
    Manuell trigger: hent NYE ordrer FRA SuSoft for innlogget tenant.

    Normalt kjøres dette automatisk hvert 5. minutt via Celery beat
    (`app.tasks.ingest_susoft_orders`). Bruk dette for testing eller
    on-demand henting.
    """
    try:
        result = ingest_susoft_orders_for_tenant(
            db, tenant_id=tenant.id, days_back=days_back, shop_id=shop_id,
        )
        return {
            "status": "success",
            "tenant_id": tenant.id,
            **result,
            "ingested_at": datetime.utcnow(),
        }
    except SuSoftAPIError as e:
        raise HTTPException(status_code=502, detail=f"SuSoft API error: {e.message}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ingest failed: {str(e)}")


@router.post("/customers")
async def sync_customers_from_susoft(
    full_sync: bool = Query(False, description="If true, sync all customers. Otherwise, only modified since last sync."),
    db: Session = Depends(get_db)
):
    """
    Manually trigger customer sync from SuSoft.
    
    Pulls customer data from SuSoft API and updates local database.
    """
    service = SuSoftService(db)
    
    try:
        # Determine modified_since date
        modified_since = None
        if not full_sync:
            # Get last successful customer sync
            last_sync_query = select(SyncLog).where(
                SyncLog.sync_type == "customer_sync",
                SyncLog.was_successful == True
            )
            if service.tenant_id is not None:
                last_sync_query = last_sync_query.where(SyncLog.tenant_id == service.tenant_id)

            last_sync = db.execute(
                last_sync_query.order_by(SyncLog.created_at.desc())
            ).scalars().first()
            
            if last_sync:
                modified_since = last_sync.created_at
        
        results = service.sync_customers_from_susoft(modified_since)
        
        # Log the sync attempt
        log = SyncLog(
            tenant_id=service.tenant_id,
            sync_type="customer_sync",
            entity_type="customer",
            entity_id=0,  # Batch operation
            http_method="GET",
            endpoint="/customer/list" + ("/modified" if modified_since else ""),
            was_successful=True,
            attempt_number=1
        )
        db.add(log)
        db.commit()
        
        return {
            "status": "success",
            "results": results,
            "full_sync": full_sync,
            "synced_at": datetime.utcnow()
        }
        
    except SuSoftAPIError as e:
        raise HTTPException(status_code=502, detail=f"SuSoft API error: {e.message}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Sync failed: {str(e)}")


@router.post("/products")
async def sync_products_from_susoft(
    full_sync: bool = Query(False, description="If true, sync all products. Otherwise, only modified since last sync."),
    db: Session = Depends(get_db)
):
    """
    Manually trigger product sync from SuSoft.
    
    Pulls product data from SuSoft API and updates local database.
    """
    service = SuSoftService(db)
    
    try:
        # Determine modified_since date
        modified_since = None
        if not full_sync:
            last_sync_query = select(SyncLog).where(
                SyncLog.sync_type == "product_sync",
                SyncLog.was_successful == True
            )
            if service.tenant_id is not None:
                last_sync_query = last_sync_query.where(SyncLog.tenant_id == service.tenant_id)

            last_sync = db.execute(
                last_sync_query.order_by(SyncLog.created_at.desc())
            ).scalars().first()
            
            if last_sync:
                modified_since = last_sync.created_at
        
        results = service.sync_products_from_susoft(modified_since)
        
        # Log the sync attempt
        log = SyncLog(
            tenant_id=service.tenant_id,
            sync_type="product_sync",
            entity_type="product",
            entity_id=0,
            http_method="GET",
            endpoint="/product/list/modified",
            was_successful=True,
            attempt_number=1
        )
        db.add(log)
        db.commit()
        
        return {
            "status": "success",
            "results": results,
            "full_sync": full_sync,
            "synced_at": datetime.utcnow()
        }
        
    except SuSoftAPIError as e:
        raise HTTPException(status_code=502, detail=f"SuSoft API error: {e.message}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Sync failed: {str(e)}")


# =============================================================================
# ORDER SYNC TO SUSOFT
# =============================================================================

@router.post("/orders")
async def sync_orders_to_susoft(
    db: Session = Depends(get_db)
):
    """
    Manually trigger order sync to SuSoft.
    
    Syncs all pending/retry orders:
    - Creates new orders for those without susoft_order_id
    - Updates existing orders for those with susoft_order_id
    """
    service = SuSoftService(db)
    
    try:
        results = service.sync_pending_orders()
        
        return {
            "status": "success",
            "results": results,
            "synced_at": datetime.utcnow()
        }
        
    except SuSoftAPIError as e:
        raise HTTPException(status_code=502, detail=f"SuSoft API error: {e.message}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Sync failed: {str(e)}")


@router.post("/orders/{order_id}")
async def sync_single_order(
    order_id: int,
    db: Session = Depends(get_db)
):
    """
    Force sync a single order to SuSoft.
    
    Useful for retrying failed orders or pushing urgent changes.
    """
    order = db.get(Order, order_id)
    if not order or order.is_deleted:
        raise HTTPException(status_code=404, detail="Order not found")
    
    if order.status == OrderStatus.CANCELLED:
        raise HTTPException(status_code=400, detail="Cannot sync cancelled order")
    
    service = SuSoftService(db)
    
    try:
        if order.susoft_order_id:
            # Update existing
            success = service.update_order(order)
            action = "updated"
        else:
            # Create new
            susoft_id = service.create_order(order)
            order.susoft_order_id = susoft_id
            action = "created"
        
        order.sync_status = SyncStatus.SYNCED
        order.last_sync_attempt = datetime.utcnow()
        order.sync_error_message = None
        db.commit()
        
        return {
            "status": "success",
            "action": action,
            "order_id": order.id,
            "susoft_order_id": order.susoft_order_id,
            "synced_at": datetime.utcnow()
        }
        
    except SuSoftAPIError as e:
        order.sync_status = SyncStatus.FAILED
        order.sync_retry_count += 1
        order.last_sync_attempt = datetime.utcnow()
        order.sync_error_message = e.message
        db.commit()
        
        raise HTTPException(status_code=502, detail=f"SuSoft API error: {e.message}")


@router.post("/orders/{order_id}/retry")
async def retry_failed_order(
    order_id: int,
    db: Session = Depends(get_db)
):
    """
    Retry syncing a failed order.
    
    Resets retry count and schedules for immediate sync.
    """
    order = db.get(Order, order_id)
    if not order or order.is_deleted:
        raise HTTPException(status_code=404, detail="Order not found")
    
    if order.sync_status not in (SyncStatus.FAILED, SyncStatus.RETRY_SCHEDULED):
        raise HTTPException(
            status_code=400, 
            detail=f"Order is not in failed state (current: {order.sync_status.value})"
        )
    
    # Reset for retry
    order.sync_status = SyncStatus.PENDING
    order.sync_retry_count = 0
    order.sync_error_message = None
    db.commit()
    
    return {
        "status": "scheduled",
        "order_id": order.id,
        "message": "Order scheduled for sync retry"
    }


# =============================================================================
# FAILED ORDERS MANAGEMENT
# =============================================================================

@router.get("/orders/failed")
async def get_failed_orders(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db)
):
    """
    Get list of orders that failed to sync.
    
    Useful for admin dashboard to monitor and retry failed syncs.
    """
    query = (
        select(Order)
        .where(
            Order.sync_status.in_([SyncStatus.FAILED, SyncStatus.RETRY_SCHEDULED]),
            Order.is_deleted == False
        )
        .order_by(Order.last_sync_attempt.desc())
    )
    
    # Count
    count_query = select(func.count()).select_from(query.subquery())
    total = db.execute(count_query).scalar() or 0
    
    # Get page
    orders = db.execute(
        query.offset((page - 1) * page_size).limit(page_size)
    ).scalars().all()
    
    return {
        "orders": [
            {
                "id": o.id,
                "customer_id": o.customer_id,
                "delivery_date": o.delivery_date,
                "sync_status": o.sync_status.value,
                "sync_retry_count": o.sync_retry_count,
                "sync_error_message": o.sync_error_message,
                "last_sync_attempt": o.last_sync_attempt,
                "susoft_order_id": o.susoft_order_id
            }
            for o in orders
        ],
        "total": total,
        "page": page,
        "page_size": page_size
    }


@router.post("/orders/retry-all-failed")
async def retry_all_failed_orders(
    db: Session = Depends(get_db)
):
    """
    Reset all failed orders for retry.
    
    Use with caution - may trigger many API calls.
    """
    result = db.execute(
        select(Order)
        .where(
            Order.sync_status.in_([SyncStatus.FAILED, SyncStatus.RETRY_SCHEDULED]),
            Order.is_deleted == False
        )
    ).scalars().all()
    
    count = 0
    for order in result:
        order.sync_status = SyncStatus.PENDING
        order.sync_retry_count = 0
        count += 1
    
    db.commit()
    
    return {
        "status": "scheduled",
        "orders_reset": count,
        "message": f"{count} orders scheduled for retry"
    }
