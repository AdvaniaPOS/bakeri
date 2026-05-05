"""
Celery tasks for scheduled jobs.

Tasks:
- Daily order generation from templates
- SuSoft sync (every 60 minutes or on failure retry)
- Cut-off time locking
- Alert email notifications
"""
import os
from datetime import date, datetime, timedelta, time
from celery import Celery
from celery.schedules import crontab

from .database import SessionLocal
from .models import Order, Customer, SyncStatus
from .time_utils import now_oslo, today_oslo, to_naive_utc, now_utc

# Configure Celery
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
celery_app = Celery("lampeland_bakeri", broker=REDIS_URL, backend=REDIS_URL)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Europe/Oslo",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=3600,  # 1 hour max per task
    worker_prefetch_multiplier=1,
)


# =============================================================================
# SCHEDULED TASKS
# =============================================================================

celery_app.conf.beat_schedule = {
    # Generate orders daily at 02:00
    "generate-daily-orders": {
        "task": "app.tasks.generate_orders_for_all_customers",
        "schedule": crontab(hour=2, minute=0),
    },
    # SWEEP: SuSoft-sync hver 5. minutt for å plukke opp ordrer som feilet
    # eller venter på retry. Den primære sync-mekanismen er nå immediate-sync
    # via sync_order.delay() ved confirm/lock.
    "sync-orders-to-susoft-sweep": {
        "task": "app.tasks.sync_pending_orders",
        "schedule": crontab(minute="*/5"),
    },
    # SWEEP: Cut-off-låsing er nå computed i koden (se app/cutoff.py).
    # Denne tasken setter bare locked_at-stempel for revisjon —
    # den er IKKE lønger autoritær for tilgangskontroll.
    "stamp-cutoff-locks": {
        "task": "app.tasks.apply_cutoff_locks",
        "schedule": crontab(hour=15, minute=0),
    },
    # Retry failed syncs at 06:00 (next morning fallback for ordrer som har
    # fått for mange retries og er parkert)
    "retry-failed-syncs": {
        "task": "app.tasks.retry_failed_syncs",
        "schedule": crontab(hour=6, minute=0),
    },
    # Sync customers/products from SuSoft daily at 01:00
    "sync-from-susoft": {
        "task": "app.tasks.sync_from_susoft",
        "schedule": crontab(hour=1, minute=0),
    },
    # POLL: hent NYE ordrer FRA SuSoft hver 5. minutt (motsatt vei av push).
    "ingest-orders-from-susoft": {
        "task": "app.tasks.ingest_susoft_orders",
        "schedule": crontab(minute="*/5"),
    },
    # POLL: hent CART-er fra SuSoft admin-API ("API 2") hver 5. minutt.
    "ingest-admin-carts-from-susoft": {
        "task": "app.tasks.ingest_susoft_admin_carts",
        "schedule": crontab(minute="*/5"),
    },
    # HEALTH-CHECK: stabil test mot SuSoft hvert 2. minutt.
    # Oppdaterer tenant.susoft_connection_status. Logger automatisk gjenoppretting.
    "susoft-health-check": {
        "task": "app.tasks.susoft_health_check",
        "schedule": crontab(minute="*/2"),
    },
    # Process scheduled price changes at 00:05
    "process-price-changes": {
        "task": "app.tasks.process_scheduled_price_changes",
        "schedule": crontab(hour=0, minute=5),
    },
}


# =============================================================================
# ORDER GENERATION
# =============================================================================

@celery_app.task(name="app.tasks.generate_orders_for_all_customers")
def generate_orders_for_all_customers():
    """
    Generate orders from templates for all active customers.
    
    Runs daily at 02:00.
    Generates orders for the configured lead time (14-30 days ahead).
    """
    from sqlalchemy import select
    from .models import MasterTemplate
    from .api.orders import generate_orders_from_template_sync
    
    db = SessionLocal()
    try:
        customers = db.execute(
            select(Customer).where(
                Customer.is_active == True,
                Customer.is_deleted == False
            )
        ).scalars().all()
        
        results = {"customers_processed": 0, "orders_created": 0, "errors": 0}
        
        for customer in customers:
            try:
                # Get active template
                template = db.execute(
                    select(MasterTemplate).where(
                        MasterTemplate.customer_id == customer.id,
                        MasterTemplate.is_active == True
                    )
                ).scalar_one_or_none()
                
                if not template:
                    continue
                
                # Calculate date range
                from_date = today_oslo()
                to_date = today_oslo() + timedelta(days=customer.order_lead_days)
                
                # Generate orders (using internal function)
                order_ids = _generate_orders_sync(
                    db, customer.id, template, from_date, to_date
                )
                
                results["orders_created"] += len(order_ids)
                results["customers_processed"] += 1
                
            except Exception as e:
                results["errors"] += 1
                # Log error but continue with other customers
                print(f"Error generating orders for customer {customer.id}: {e}")
        
        db.commit()
        return results
        
    finally:
        db.close()


def _generate_orders_sync(db, customer_id, template, from_date, to_date):
    """Internal sync function for order generation.

    Tar hensyn til kundens `delivers_on_holidays`-flagg slik at hoteller,
    sykehjem o.l. får levering også på helligdager.
    """
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    from .models import (
        Order, OrderLine, Product, OrderDateOverride, Customer,
        Holiday, CustomerBlockedDate, OrderStatus
    )
    from .api.pricing import get_effective_price
    from decimal import Decimal

    customer = db.get(Customer, customer_id)
    delivers_on_holidays = bool(customer and customer.delivers_on_holidays)

    # Hent tenant for ordrenr-allokering
    from .auth_models import Tenant as _Tenant
    from .services.order_numbering import allocate_order_no
    tenant_obj = db.get(_Tenant, customer.tenant_id) if customer else None

    orders_created = []
    current_date = from_date

    while current_date <= to_date:
        # Check public holiday (med mindre kunden leverer på helligdager)
        holiday = None
        if not delivers_on_holidays:
            holiday = db.execute(
                select(Holiday).where(Holiday.holiday_date == current_date)
            ).scalar_one_or_none()

        blocked = db.execute(
            select(CustomerBlockedDate).where(
                CustomerBlockedDate.customer_id == customer_id,
                CustomerBlockedDate.start_date <= current_date,
                CustomerBlockedDate.end_date >= current_date
            )
        ).scalar_one_or_none()

        if holiday or blocked:
            current_date += timedelta(days=1)
            continue
        
        # Check if order exists
        existing = db.execute(
            select(Order).where(
                Order.customer_id == customer_id,
                Order.delivery_date == current_date,
                Order.is_deleted == False
            )
        ).scalar_one_or_none()
        
        if existing:
            current_date += timedelta(days=1)
            continue
        
        # Get template items for this day
        day_of_week = current_date.isoweekday()
        items_for_day = [
            item for item in template.items
            if item.day_of_week == day_of_week and item.quantity > 0
        ]
        
        if not items_for_day:
            current_date += timedelta(days=1)
            continue
        
        # Create order
        order = Order(
            tenant_id=customer.tenant_id,
            customer_id=customer_id,
            delivery_date=current_date,
            status=OrderStatus.DRAFT,
            generated_from_template_id=template.id,
            reference=template.default_reference,
        )
        if tenant_obj:
            allocate_order_no(db, tenant_obj, order)
        db.add(order)
        db.flush()
        
        total_excl = Decimal("0")
        total_vat = Decimal("0")
        total_incl = Decimal("0")
        
        for item in items_for_day:
            product = db.get(Product, item.product_id)
            if not product or not product.is_available_for_order:
                continue
            
            unit_price, _, _ = get_effective_price(
                db, customer_id, item.product_id, current_date
            )
            
            excl_vat = unit_price * item.quantity
            vat = excl_vat * (product.vat_rate / 100)
            incl_vat = excl_vat + vat
            
            line = OrderLine(
                order_id=order.id,
                product_id=item.product_id,
                quantity=item.quantity,
                unit_price=unit_price,
                vat_rate=product.vat_rate,
                line_amount_excl_vat=excl_vat,
                line_vat=vat,
                line_amount_incl_vat=incl_vat
            )
            db.add(line)
            
            total_excl += excl_vat
            total_vat += vat
            total_incl += incl_vat
        
        order.total_amount_excl_vat = total_excl
        order.total_vat = total_vat
        order.total_amount_incl_vat = total_incl
        
        orders_created.append(order.id)
        current_date += timedelta(days=1)
    
    return orders_created


# =============================================================================
# SUSOFT SYNC
# =============================================================================

@celery_app.task(name="app.tasks.sync_pending_orders")
def sync_pending_orders():
    """
    Sweep-task: synker ordrer som er klare for retry (next_retry_at <= now).

    Køres hvert 5. minutt. Den primære sync-mekanismen er nå
    `sync_order.delay()` som trigges umiddelbart ved confirm/lock.
    """
    from .services.susoft import SuSoftService

    db = SessionLocal()
    try:
        service = SuSoftService(db)
        results = service.sync_pending_orders()
        return results
    finally:
        db.close()


@celery_app.task(
    name="app.tasks.sync_order",
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,           # Eksponentiell backoff: 1m, 2m, 4m, 8m...
    retry_backoff_max=3600,       # Maks 1 time mellom retries
    retry_jitter=True,            # Tilfeldig jitter for å unngå thundering herd
    max_retries=8,                # Etter 8 forsøk blir den parkert (~3 timer total)
    acks_late=True,               # Ack først etter ferdig prosessering
)
def sync_order(self, order_id: int):
    """
    Synk én spesifikk ordre til SuSoft. Trigges umiddelbart ved confirm/lock.

    Bruker eksponentiell backoff ved feil. Etter max_retries oppretter
    SuSoftService en AdminAlert slik at en menneskelig kan gripe inn.

    IDEMPOTENT: Hvis ordren allerede har susoft_order_id, eller hvis
    SuSoft har en ordre med vår alternativeId, oppdaterer vi i stedet for
    å opprette på nytt. Dette hindrer dobbel fakturering ved retry.
    """
    from sqlalchemy import select
    from .services.susoft import SuSoftService, SuSoftAPIError

    db = SessionLocal()
    try:
        order = db.execute(
            select(Order).where(Order.id == order_id, Order.is_deleted == False)
        ).scalar_one_or_none()

        if not order:
            return {"status": "skipped", "reason": "order not found"}

        if order.sync_status == SyncStatus.SYNCED and order.susoft_order_id:
            return {"status": "skipped", "reason": "already synced"}

        service = SuSoftService(db, tenant_id=order.tenant_id)
        try:
            service.sync_single_order(order)
            db.commit()
            return {"status": "synced", "order_id": order_id, "susoft_order_id": order.susoft_order_id}
        except (SuSoftAPIError, Exception) as exc:
            # Logg feilen i ordren før retry
            order.sync_status = SyncStatus.FAILED
            order.sync_retry_count = (order.sync_retry_count or 0) + 1
            order.last_sync_attempt = to_naive_utc(now_utc())
            order.sync_error_message = str(exc)[:500]
            db.commit()
            raise  # La Celery håndtere backoff
    finally:
        db.close()


@celery_app.task(name="app.tasks.retry_failed_syncs")
def retry_failed_syncs():
    """
    Retry failed syncs (morning fallback).

    K\u00f8res 06:00 for ordrer som er parkert (max retries n\u00e5dd) eller har v\u00e6rt
    i FAILED for lenge. Nullstiller `next_retry_at` slik at sweep-jobben
    plukker dem opp p\u00e5 nytt med en frisk backoff-syklus.
    """
    from sqlalchemy import select

    db = SessionLocal()
    try:
        failed_orders = db.execute(
            select(Order).where(
                Order.sync_status == SyncStatus.FAILED,
                Order.is_deleted == False
            )
        ).scalars().all()

        for order in failed_orders:
            order.sync_status = SyncStatus.RETRY_SCHEDULED
            order.sync_retry_count = 0  # Frisk backoff-syklus
            order.next_retry_at = None  # Sync n\u00e5

        db.commit()

        # Trigger umiddelbar sync
        return sync_pending_orders()

    finally:
        db.close()


@celery_app.task(name="app.tasks.sync_from_susoft")
def sync_from_susoft():
    """
    Pull customer and product data from SuSoft.
    
    Runs daily at 01:00.
    Uses incremental sync (modified since last 25 hours) to minimize data transfer.
    """
    from .services.susoft import SuSoftService
    
    db = SessionLocal()
    try:
        service = SuSoftService(db)
        
        # Incremental sync - get items modified in last 25 hours
        # (25h to account for timezone differences and ensure no gaps)
        modified_since = to_naive_utc(now_utc()) - timedelta(hours=25)
        
        customer_results = service.sync_customers_from_susoft(modified_since=modified_since)
        product_results = service.sync_products_from_susoft(modified_since=modified_since)
        
        return {
            "customers": customer_results,
            "products": product_results,
            "modified_since": modified_since.isoformat()
        }
    finally:
        db.close()


@celery_app.task(name="app.tasks.full_sync_from_susoft")
def full_sync_from_susoft():
    """
    Full sync of all customers and products from SuSoft.
    
    Should be run manually when needed, not as a scheduled task.
    """
    from .services.susoft import SuSoftService
    
    db = SessionLocal()
    try:
        service = SuSoftService(db)
        
        # Full sync - no modified_since filter
        customer_results = service.sync_customers_from_susoft()
        product_results = service.sync_products_from_susoft()
        
        return {
            "customers": customer_results,
            "products": product_results,
            "sync_type": "full"
        }
    finally:
        db.close()


@celery_app.task(name="app.tasks.ingest_susoft_orders")
def ingest_susoft_orders(days_back: int = 30):
    """
    Pull NYE ordrer FRA SuSoft for alle tenants (polling).

    Kjøres hvert 5. minutt. Dedupliserer mot `orders.susoft_uuid`.
    Ordrer uten lokal kunde-match opprettes mot 'Ukjent kunde'.
    `type=CART` opprettes som DRAFT.
    """
    from .services.susoft_ingest import ingest_susoft_orders_all_tenants
    return ingest_susoft_orders_all_tenants(days_back=days_back)


@celery_app.task(name="app.tasks.ingest_susoft_admin_carts")
def ingest_susoft_admin_carts(days_back: int = 30):
    """
    Pull aPOS CART-er FRA SuSoft admin-API ("API 2") for alle tenants.

    Kjøres hvert 5. minutt. Bruker tenant.susoft_admin_* kredentialer.
    Dedupliserer mot `orders.susoft_uuid` (samme nøkkel som /order/list).
    """
    from .services.susoft_ingest import ingest_susoft_admin_carts_all_tenants
    return ingest_susoft_admin_carts_all_tenants(days_back=days_back)


@celery_app.task(name="app.tasks.susoft_health_check")
def susoft_health_check():
    """
    Stabil helsetest mot SuSoft for alle tenants.

    Kjøres hvert 2. minutt. Oppdaterer `tenant.susoft_connection_status`.
    Hvis en tenant gjenopprettes (failed → ok), trigges umiddelbart
    `sync_pending_orders` og `ingest_susoft_orders` slik at handlinger
    som feilet under nedetiden blir fullført.
    """
    import logging
    from .auth_models import Tenant
    from .services.susoft import SuSoftService

    logger = logging.getLogger(__name__)
    db = SessionLocal()
    results = []
    recovered_any = False

    try:
        tenants = db.query(Tenant).all()
        for tenant in tenants:
            prev_status = tenant.susoft_connection_status or "unknown"
            try:
                service = SuSoftService(db, tenant_id=tenant.id)
                ok = service.test_connection()
            except Exception as e:
                logger.warning("Health-check exception for tenant %s: %s", tenant.id, e)
                ok = False

            new_status = "ok" if ok else "failed"
            results.append({"tenant_id": tenant.id, "status": new_status, "prev": prev_status})

            if ok and prev_status == "failed":
                logger.info(
                    "SuSoft connection RECOVERED for tenant %s — re-running pending sync + ingest",
                    tenant.id,
                )
                recovered_any = True

        # Hvis noen ble gjenopprettet, kjør pending-handlinger med en gang
        # så ingen blir værende i kø før neste vanlige tikk.
        if recovered_any:
            try:
                sync_pending_orders.delay()
            except Exception as e:
                logger.warning("Could not enqueue sync_pending_orders after recovery: %s", e)
            try:
                ingest_susoft_orders.delay()
            except Exception as e:
                logger.warning("Could not enqueue ingest_susoft_orders after recovery: %s", e)

        return {"results": results, "recovered": recovered_any}
    finally:
        db.close()


# =============================================================================
# CUT-OFF & LOCKING
# =============================================================================

@celery_app.task(name="app.tasks.apply_cutoff_locks")
def apply_cutoff_locks():
    """
    Stempler `locked_at` for ordrer hvis cut-off er passert.

    MERK: Denne tasken er IKKE lønger autoritær for tilgangskontroll!
    Sannheten ligger nå i `app/cutoff.py::is_order_locked()` som er computed.
    Denne tasken eksisterer kun for å sette et revisjons-stempel slik at
    DB-en viser når systemet første gang oppdaget at cut-off var passert.

    Selv om denne tasken aldri kjører, vil API-et fortsatt avvise endringer
    etter cut-off via `ensure_editable()`.
    """
    from sqlalchemy import select
    from .cutoff import is_order_locked

    db = SessionLocal()
    try:
        # Finn alle ordrer som ikke er stemplet, men der cut-off er passert.
        # Vi henter "i nær fremtid" (de neste 7 dagene) for å begrense scope.
        upper_bound = today_oslo() + timedelta(days=7)
        orders = db.execute(
            select(Order).where(
                Order.is_locked == False,
                Order.is_deleted == False,
                Order.delivery_date <= upper_bound,
            )
        ).scalars().all()

        locked_count = 0
        now_naive = to_naive_utc(now_utc())
        for order in orders:
            if is_order_locked(order):
                order.is_locked = True
                order.locked_at = now_naive
                locked_count += 1

        db.commit()
        return {"locked_orders": locked_count}

    finally:
        db.close()


# =============================================================================
# PRICE CHANGE PROCESSING
# =============================================================================

@celery_app.task(name="app.tasks.process_scheduled_price_changes")
def process_scheduled_price_changes():
    """
    Process price changes that have become effective.
    
    Runs at 00:05 daily.
    Updates orders with new prices and triggers SuSoft sync.
    """
    from sqlalchemy import select
    from .models import CustomerProductPrice
    from .api.pricing import propagate_price_change
    
    db = SessionLocal()
    try:
        # Find price entries effective from today that haven't been processed
        today = today_oslo()
        
        price_entries = db.execute(
            select(CustomerProductPrice).where(
                CustomerProductPrice.effective_from_date == today,
                CustomerProductPrice.orders_updated == False
            )
        ).scalars().all()
        
        processed = 0
        for entry in price_entries:
            # Run synchronously since we're in a Celery task
            _propagate_price_sync(
                db,
                entry.id,
                entry.customer_id,
                entry.product_id,
                entry.effective_from_date
            )
            processed += 1
        
        db.commit()
        return {"price_entries_processed": processed}
        
    finally:
        db.close()


def _propagate_price_sync(db, price_entry_id, customer_id, product_id, effective_from):
    """Sync version of price propagation for Celery tasks."""
    from sqlalchemy import select
    from .models import CustomerProductPrice, OrderLine, Order
    from .api.pricing import get_effective_price
    from decimal import Decimal
    
    price_entry = db.get(CustomerProductPrice, price_entry_id)
    if not price_entry:
        return
    
    affected_lines = db.execute(
        select(OrderLine)
        .join(Order)
        .where(
            Order.customer_id == customer_id,
            OrderLine.product_id == product_id,
            Order.delivery_date >= effective_from,
            Order.is_locked == False,
            Order.is_deleted == False
        )
    ).scalars().all()
    
    orders_to_update = set()
    
    for line in affected_lines:
        order = db.get(Order, line.order_id)
        new_price, _, _ = get_effective_price(
            db, customer_id, product_id, order.delivery_date
        )
        
        if line.unit_price != new_price:
            line.unit_price = new_price
            line.line_amount_excl_vat = new_price * line.quantity
            line.line_vat = line.line_amount_excl_vat * (line.vat_rate / 100)
            line.line_amount_incl_vat = line.line_amount_excl_vat + line.line_vat
            line.price_updated_at = to_naive_utc(now_utc())
            orders_to_update.add(order)
    
    for order in orders_to_update:
        order.total_amount_excl_vat = sum(
            line.line_amount_excl_vat for line in order.lines
        )
        order.total_vat = sum(line.line_vat for line in order.lines)
        order.total_amount_incl_vat = sum(
            line.line_amount_incl_vat for line in order.lines
        )
        
        if order.sync_status == SyncStatus.SYNCED:
            order.sync_status = SyncStatus.PENDING
    
    price_entry.orders_updated = True
    price_entry.susoft_sync_triggered = len(orders_to_update) > 0


# =============================================================================
# ALERT NOTIFICATIONS
# =============================================================================

@celery_app.task(name="app.tasks.send_alert_emails")
def send_alert_emails():
    """
    Send email notifications for unread alerts.
    
    Configurable: can run on schedule or be triggered immediately.
    """
    from sqlalchemy import select
    from .models import AdminAlert, User
    import smtplib
    from email.mime.text import MIMEText
    
    db = SessionLocal()
    try:
        # Get unsent critical/error alerts
        alerts = db.execute(
            select(AdminAlert).where(
                AdminAlert.email_sent == False,
                AdminAlert.severity.in_(["critical", "error"])
            )
        ).scalars().all()
        
        if not alerts:
            return {"emails_sent": 0}
        
        # Get admin users who should receive alerts
        admins = db.execute(
            select(User).where(
                User.role == "admin",
                User.receive_alerts == True,
                User.is_active == True
            )
        ).scalars().all()
        
        smtp_host = os.getenv("SMTP_HOST", "localhost")
        smtp_port = int(os.getenv("SMTP_PORT", "587"))
        smtp_user = os.getenv("SMTP_USER", "")
        smtp_pass = os.getenv("SMTP_PASS", "")
        from_email = os.getenv("ALERT_FROM_EMAIL", "alerts@advania-bakeri.no")
        
        sent_count = 0
        
        for alert in alerts:
            recipients = [
                admin.alert_email or admin.email 
                for admin in admins
            ]
            
            if not recipients:
                continue
            
            body = f"""
ADVANIA BAKERI - SYSTEM ALERT

Severity: {alert.severity.upper()}
Type: {alert.alert_type}

{alert.title}

{alert.message}

Time: {alert.created_at}

---
This is an automated alert from Advania Bakeri Ordresystem.
            """
            
            msg = MIMEText(body)
            msg["Subject"] = f"[{alert.severity.upper()}] {alert.title}"
            msg["From"] = from_email
            msg["To"] = ", ".join(recipients)
            
            try:
                if smtp_user:
                    server = smtplib.SMTP(smtp_host, smtp_port)
                    server.starttls()
                    server.login(smtp_user, smtp_pass)
                    server.sendmail(from_email, recipients, msg.as_string())
                    server.quit()
                
                alert.email_sent = True
                alert.email_sent_at = to_naive_utc(now_utc())
                alert.email_recipients = ", ".join(recipients)
                sent_count += 1
                
            except Exception as e:
                print(f"Failed to send alert email: {e}")
        
        db.commit()
        return {"emails_sent": sent_count}
        
    finally:
        db.close()
