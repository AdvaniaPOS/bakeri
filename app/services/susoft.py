"""
SuSoft POS API Integration Service.

Based on SuSoft REST API v3.1 Swagger specification.
API Host: api.susoft.com:4443

Handles:
- Order creation in SuSoft (POST /order)
- Order lookup by alternativeId (GET /order/altid)
- Invoice creation (POST /invoice) — fakturerer eksisterende ordre via alternativeId
- Customer synchronization (GET /customer/list, /customer/list/modified)
- Product synchronization (GET /product/list/modified)
- Retry logic for API failures
- Alert generation on persistent failures

VIKTIG: SuSoft REST API v3.1 har INGEN av følgende endepunkter:
- PUT /order/{id}     (ingen oppdatering av ordre)
- DELETE /order/{id}  (ingen sletting av ordre)
Ordrer er uforanderlige etter `POST /order`. Ved kansellering opprettes en
admin-alert for manuell håndtering. Endringer som må reflekteres i SuSoft må
gjøres manuelt der (ev. via kreditnota etter fakturering).

Orders without payments are created "ready for invoicing" (isForInvoicing=true).
Selve faktureringen skjer via separat `POST /invoice`-kall.
"""
import os
import time
from datetime import datetime, timedelta, date
from decimal import Decimal
from typing import Optional, List, Dict, Any, Tuple
import logging
from urllib.parse import urlencode

import httpx
from tenacity import (
    retry, stop_after_attempt, wait_exponential, 
    retry_if_exception_type, before_sleep_log
)
from sqlalchemy.orm import Session
from sqlalchemy import select

from ..models import (
    Order, OrderLine, Customer, Product, SyncLog, AdminAlert,
    SyncStatus, OrderStatus
)

logger = logging.getLogger(__name__)


def _format_allergens(raw) -> Optional[str]:
    """Konverter SuSoft allergen-array (liste av {id,name}) til komma-separert tekst."""
    if not raw or not isinstance(raw, list):
        return None
    names = []
    for item in raw:
        if isinstance(item, dict):
            n = item.get("name")
            if n:
                names.append(str(n).strip())
        elif isinstance(item, str):
            names.append(item.strip())
    if not names:
        return None
    # Dedupliser, behold rekkefølge
    seen = set()
    unique = [n for n in names if not (n in seen or seen.add(n))]
    result = ", ".join(unique)
    return result[:500]

# Configuration - SuSoft API base URL (port 4443 per spec)
SUSOFT_BASE_URL_DEFAULT = os.getenv("SUSOFT_BASE_URL", "https://api.susoft.com:4443")
SUSOFT_USERNAME_ENV = os.getenv("SUSOFT_USERNAME", "")
SUSOFT_PASSWORD_ENV = os.getenv("SUSOFT_PASSWORD", "")
SUSOFT_SHOP_URL_KEY_ENV = os.getenv("SUSOFT_SHOP_URL_KEY", "")
SUSOFT_TIMEOUT = int(os.getenv("SUSOFT_TIMEOUT", "30"))
MAX_RETRY_ATTEMPTS = 3
RETRY_INTERVAL_MINUTES = 60

# Per-tenant JWT token cache: {tenant_id: (token, expires_at)}
_token_cache: Dict[int, tuple] = {}


class SuSoftAPIError(Exception):
    """Exception for SuSoft API errors."""
    def __init__(self, message: str, status_code: Optional[int] = None, response_body: Optional[str] = None):
        self.message = message
        self.status_code = status_code
        self.response_body = response_body
        super().__init__(self.message)


class SuSoftService:
    """
    Service for interacting with SuSoft POS REST API v3.1.
    
    Key endpoints used:
    - POST /order - Create order (for invoicing)
    - GET /order/altid - Find order by alternativeId
    - POST /invoice - Lag faktura for eksisterende ordre
    - GET /customer/list/modified - Sync customers
    - GET /product/list/modified - Sync products
    - POST /user/auth - Authentication (JWT)
    
    Note: SuSoft API does NOT support order updates or deletions.
    For order changes, we need to work with invoicing workflow.
    """
    
    def __init__(self, db: Session, tenant_id: Optional[int] = None):
        self.db = db
        self.tenant_id = tenant_id or self._resolve_default_tenant_id()
        self._token: Optional[str] = None
        self._token_expires: Optional[datetime] = None
        # Last credentials/config snapshot from tenant (lazy loaded)
        self._cfg_loaded: bool = False
        self._cfg_login: str = ""
        self._cfg_password: str = ""
        self._cfg_shop_key: str = ""
        self._cfg_base_url: str = SUSOFT_BASE_URL_DEFAULT
        self.client = httpx.Client(
            base_url=self._cfg_base_url,
            timeout=SUSOFT_TIMEOUT,
        )

    def _resolve_default_tenant_id(self) -> Optional[int]:
        """
        Resolve tenant_id for background jobs/manual scripts.

        Priority:
        1. SUSOFT_SYNC_TENANT_ID env var
        2. First tenant in database
        """
        env_tenant_id = os.getenv("SUSOFT_SYNC_TENANT_ID")
        if env_tenant_id:
            try:
                return int(env_tenant_id)
            except ValueError:
                logger.warning("Invalid SUSOFT_SYNC_TENANT_ID value: %s", env_tenant_id)

        try:
            from ..auth_models import Tenant

            tenant = self.db.execute(select(Tenant).order_by(Tenant.id.asc())).scalars().first()
            return tenant.id if tenant else None
        except Exception as e:
            logger.warning("Could not resolve default tenant_id for SuSoft sync: %s", e)
            return None

    def _ensure_tenant_available(self):
        """Fail early if tenant_id is missing in a tenant-scoped schema."""
        if self.tenant_id is None:
            raise SuSoftAPIError(
                "Mangler tenant_id for SuSoft sync. Sett SUSOFT_SYNC_TENANT_ID i .env, "
                "eller kall service med tenant_id."
            )

    def _request_with_throttle_retry(
        self,
        method: str,
        path: str,
        max_retries: int = 5,
        **kwargs,
    ) -> httpx.Response:
        """Issue a request and transparently retry on HTTP 429 with exponential backoff.

        Honours the Retry-After header if present.
        """
        delay = 1.0
        for attempt in range(max_retries + 1):
            response = self.client.request(method, path, **kwargs)
            if response.status_code != 429 or attempt == max_retries:
                return response
            retry_after = response.headers.get("Retry-After")
            try:
                wait = float(retry_after) if retry_after else delay
            except ValueError:
                wait = delay
            wait = min(max(wait, 0.5), 30.0)
            logger.warning(
                "SuSoft returned 429 for %s %s (attempt %d/%d); sleeping %.1fs",
                method, path, attempt + 1, max_retries, wait,
            )
            time.sleep(wait)
            delay = min(delay * 2, 30.0)
        return response

    def _fetch_paginated_get(
        self,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        page_size: int = 200,
    ) -> List[Dict[str, Any]]:
        """Fetch all pages from a SuSoft GET endpoint with page/pageSize support."""
        items: List[Dict[str, Any]] = []
        page = 0

        while True:
            current_params = dict(params or {})
            current_params["page"] = page
            current_params["pageSize"] = page_size

            query = urlencode(current_params)
            path = f"{endpoint}?{query}" if query else endpoint
            response = self._request_with_throttle_retry(
                "GET", path, headers=self._get_headers()
            )

            if not response.is_success:
                raise SuSoftAPIError(
                    f"Failed to fetch {endpoint}: {response.status_code}",
                    response.status_code,
                    response.text,
                )

            batch = response.json() or []
            if not isinstance(batch, list):
                raise SuSoftAPIError(f"Unexpected response type from {endpoint}: {type(batch).__name__}")

            items.extend(batch)
            if len(batch) < page_size:
                break
            page += 1

        return items

    def _fetch_paginated_product_search(self, page_size: int = 200) -> List[Dict[str, Any]]:
        """Fetch products via /product/search as full-sync strategy."""
        items: List[Dict[str, Any]] = []
        page = 0

        while True:
            endpoint = f"/product/search?page={page}&pageSize={page_size}&activityFlag=ALL"
            response = self._request_with_throttle_retry(
                "POST",
                endpoint,
                json={"filterGroups": []},
                headers=self._get_headers(),
            )

            if not response.is_success:
                raise SuSoftAPIError(
                    f"Failed to fetch /product/search: {response.status_code}",
                    response.status_code,
                    response.text,
                )

            batch = response.json() or []
            if not isinstance(batch, list):
                raise SuSoftAPIError(f"Unexpected response type from /product/search: {type(batch).__name__}")

            items.extend(batch)
            if len(batch) < page_size:
                break
            page += 1

        return items

    def _fetch_category_name_map(self) -> Dict[str, str]:
        """Fetch the SuSoft product category tree and flatten to {id: name}.

        SuSoft returns a tree with `id`, `name`, `children` (dict keyed by id).
        Returns empty dict on failure (caller falls back to raw IDs).
        """
        try:
            response = self._request_with_throttle_retry(
                "GET", "/product/category/tree", headers=self._get_headers()
            )
            if not response.is_success:
                logger.warning(
                    "Failed to fetch product category tree: %s", response.status_code
                )
                return {}
            tree = response.json() or {}
        except Exception as e:
            logger.warning("Could not fetch product category tree: %s", e)
            return {}

        name_map: Dict[str, str] = {}

        def walk(node: Any) -> None:
            if not isinstance(node, dict):
                return
            node_id = node.get("id")
            node_name = node.get("name")
            if node_id is not None and node_name:
                name_map[str(node_id)] = str(node_name)
            children = node.get("children") or {}
            if isinstance(children, dict):
                for child in children.values():
                    walk(child)
            elif isinstance(children, list):
                for child in children:
                    walk(child)

        walk(tree)
        return name_map

    def _build_customer_name(self, cust_data: Dict[str, Any]) -> Tuple[str, Optional[str], Optional[str]]:
        """Build robust customer name fields from SuSoft payload."""
        first_name = (cust_data.get("firstName") or "").strip()
        last_name = (cust_data.get("lastName") or "").strip()
        display_name = (cust_data.get("displayName") or "").strip()
        is_company = bool(cust_data.get("isCompany"))

        if display_name:
            name = display_name
        elif first_name and last_name:
            name = f"{first_name} {last_name}"
        else:
            name = first_name or last_name or f"Kunde {cust_data.get('id', '')}"

        company_name = display_name if is_company and display_name else (last_name if is_company else None)
        contact_person = first_name or None
        return name[:255], company_name[:255] if company_name else None, contact_person[:255] if contact_person else None
    
    def _load_config(self, force: bool = False) -> None:
        """
        Last inn SuSoft-konfig fra Tenant-tabellen. Faller tilbake til ENV.
        Konfigurasjonen mellomlagres pr. service-instans.
        """
        if self._cfg_loaded and not force:
            return

        login = SUSOFT_USERNAME_ENV
        password = SUSOFT_PASSWORD_ENV
        shop_key = SUSOFT_SHOP_URL_KEY_ENV
        base_url = SUSOFT_BASE_URL_DEFAULT

        if self.tenant_id is not None:
            try:
                from ..auth_models import Tenant
                from ..crypto_utils import decrypt_secret

                tenant = self.db.get(Tenant, self.tenant_id)
                if tenant:
                    if tenant.susoft_login:
                        login = tenant.susoft_login
                    decrypted = decrypt_secret(tenant.susoft_password_encrypted)
                    if decrypted:
                        password = decrypted
                    if tenant.susoft_shop_url_key:
                        shop_key = tenant.susoft_shop_url_key
                    if tenant.susoft_api_url:
                        base_url = tenant.susoft_api_url
            except Exception as e:
                logger.warning("Klarte ikke lese SuSoft-konfig fra tenant %s: %s", self.tenant_id, e)

        self._cfg_login = login or ""
        self._cfg_password = password or ""
        self._cfg_shop_key = shop_key or ""
        if base_url and base_url != self._cfg_base_url:
            # Recreate client if base URL changed
            try:
                self.client.close()
            except Exception:
                pass
            self.client = httpx.Client(base_url=base_url, timeout=SUSOFT_TIMEOUT)
            self._cfg_base_url = base_url
        self._cfg_loaded = True

    def _get_headers(self, with_auth: bool = True) -> Dict[str, str]:
        """Build request headers with auth token."""
        self._load_config()
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self._cfg_shop_key:
            headers["X-Shop-Url-Key"] = self._cfg_shop_key
        if with_auth:
            token = self._get_auth_token()
            if token:
                headers["Authorization"] = f"Bearer {token}"
        return headers

    def _request_with_auth_retry(self, method: str, path: str, **kwargs) -> httpx.Response:
        """
        Wrapper rundt httpx-kall som auto-fornyer tokenet ved 401.
        """
        headers = kwargs.pop("headers", None) or self._get_headers()
        response = self.client.request(method, path, headers=headers, **kwargs)
        if response.status_code == 401:
            logger.info("SuSoft returnerte 401, prøver re-autentisering en gang")
            self._invalidate_token()
            new_token = self._get_auth_token(force=True)
            if new_token:
                headers["Authorization"] = f"Bearer {new_token}"
                response = self.client.request(method, path, headers=headers, **kwargs)
        return response

    def _invalidate_token(self) -> None:
        if self.tenant_id is not None:
            _token_cache.pop(self.tenant_id, None)
        self._token = None
        self._token_expires = None

    def test_connection(self) -> bool:
        """
        Test connection to SuSoft API. Returnerer True hvis vi kan autentisere.
        Oppdaterer tenant.susoft_connection_status.
        """
        self._load_config(force=True)
        self._invalidate_token()
        token = self._get_auth_token(force=True)
        ok = bool(token)
        try:
            self._update_tenant_status("ok" if ok else "failed", None if ok else "Autentisering feilet")
        except Exception:
            pass
        return ok

    def _update_tenant_status(self, status: str, error: Optional[str]) -> None:
        if self.tenant_id is None:
            return
        try:
            from ..auth_models import Tenant
            tenant = self.db.get(Tenant, self.tenant_id)
            if not tenant:
                return
            tenant.susoft_connection_status = status
            tenant.susoft_last_check_at = datetime.utcnow()
            tenant.susoft_last_error = (error or "")[:1000] if error else None
            self.db.commit()
        except Exception as e:
            logger.warning("Kunne ikke oppdatere tenant-status: %s", e)
            try:
                self.db.rollback()
            except Exception:
                pass

    def _get_auth_token(self, force: bool = False) -> Optional[str]:
        """
        Hent JWT-token fra SuSoft. Mellomlagrer pr. tenant_id.
        """
        self._load_config()

        if not self._cfg_login or not self._cfg_password:
            logger.warning("SuSoft-credentials mangler (tenant_id=%s)", self.tenant_id)
            return None

        cache_key = self.tenant_id if self.tenant_id is not None else 0
        if not force:
            cached = _token_cache.get(cache_key)
            if cached:
                token, expires_at = cached
                if token and expires_at and datetime.utcnow() < expires_at:
                    return token

        try:
            headers = {"Content-Type": "application/json"}
            if self._cfg_shop_key:
                headers["X-Shop-Url-Key"] = self._cfg_shop_key
            response = self.client.post(
                "/user/auth",
                json={"login": self._cfg_login, "password": self._cfg_password},
                headers=headers,
            )
            if response.is_success:
                data = response.json()
                token = data.get("token")
                if token:
                    _token_cache[cache_key] = (token, datetime.utcnow() + timedelta(hours=23))
                    return token
                logger.error("SuSoft auth ga 200 men ingen token: %s", response.text[:500])
                return None
            else:
                logger.error(
                    "SuSoft auth feilet (tenant=%s): %s - %s",
                    self.tenant_id, response.status_code, response.text[:500],
                )
                self._update_tenant_status(
                    "failed",
                    f"HTTP {response.status_code}: {response.text[:300]}",
                )
                return None
        except Exception as e:
            logger.error("SuSoft auth-feil: %s", e)
            self._update_tenant_status("failed", str(e))
            return None
    
    def _log_sync(
        self,
        sync_type: str,
        entity_type: str,
        entity_id: int,
        method: str,
        endpoint: str,
        request_payload: Optional[Dict] = None,
        response_status: Optional[int] = None,
        response_body: Optional[str] = None,
        success: bool = True,
        error_message: Optional[str] = None,
        attempt_number: int = 1
    ) -> SyncLog:
        """Log sync attempt to database."""
        self._ensure_tenant_available()

        log = SyncLog(
            tenant_id=self.tenant_id,
            sync_type=sync_type,
            entity_type=entity_type,
            entity_id=entity_id,
            http_method=method,
            endpoint=endpoint,
            request_payload=request_payload,
            response_status_code=response_status,
            response_body=response_body,
            was_successful=success,
            error_message=error_message,
            attempt_number=attempt_number,
            next_retry_at=datetime.utcnow() + timedelta(minutes=RETRY_INTERVAL_MINUTES) if not success else None
        )
        self.db.add(log)
        self.db.commit()
        return log
    
    def _create_alert(
        self,
        alert_type: str,
        severity: str,
        title: str,
        message: str,
        entity_type: Optional[str] = None,
        entity_id: Optional[int] = None
    ):
        """Create admin alert for failures."""
        self._ensure_tenant_available()

        alert = AdminAlert(
            tenant_id=self.tenant_id,
            alert_type=alert_type,
            severity=severity,
            title=title,
            message=message,
            related_entity_type=entity_type,
            related_entity_id=entity_id
        )
        self.db.add(alert)
        self.db.commit()
    
    # =========================================================================
    # ORDER OPERATIONS
    # =========================================================================
    
    @retry(
        stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
        wait=wait_exponential(multiplier=1, min=4, max=60),
        retry=retry_if_exception_type((httpx.HTTPError, SuSoftAPIError)),
        before_sleep=before_sleep_log(logger, logging.WARNING)
    )
    def create_order(self, order: Order) -> str:
        """
        Create an order in SuSoft using POST /order.
        
        IDEMPOTENT: Først sjekker vi om SuSoft allerede har en ordre med vår
        alternativeId. Hvis ja, returnerer vi den eksisterende ID-en uten å
        opprette en ny. Dette hindrer dobbel fakturering ved retry når SuSoft
        mottok forrige POST men svaret går tapt.

        Per SuSoft API spec:
        - Orders without payments are created "ready for invoicing"
        - We provide alternativeId to link back to our order
        - Returns the orderNo assigned by SuSoft
        
        Returns the susoft_order_id (orderNo) if successful.
        """
        if not order.customer.susoft_customer_id:
            raise SuSoftAPIError("Customer has no SuSoft ID")

        # IDEMPOTENS: Sjekk om SuSoft allerede har denne ordren
        # (kan skje ved retry hvis forrige POST kom frem men svaret gikk tapt)
        try:
            existing = self.get_order_by_alt_id(str(order.id))
            if existing:
                existing_id = str(
                    existing.get("orderNo")
                    or existing.get("uuid")
                    or existing.get("id")
                    or ""
                )
                if existing_id:
                    logger.warning(
                        "Idempotency hit: order %s eksisterer allerede i SuSoft som %s. "
                        "Hopper over POST for å unngå dobbel fakturering.",
                        order.id, existing_id,
                    )
                    self._log_sync(
                        sync_type="order_create_idempotent",
                        entity_type="order",
                        entity_id=order.id,
                        method="GET",
                        endpoint="/order/altid",
                        success=True,
                        error_message=f"Already exists in SuSoft as {existing_id}",
                    )
                    return existing_id
        except Exception as e:
            # Hvis idempotens-sjekken feiler, logger vi og fortsetter med POST.
            # Bedre å risikere duplikat (alarm) enn å stoppe sync helt.
            logger.warning("Idempotency check failed for order %s: %s", order.id, e)

        # Build order payload according to SuSoft Swagger spec
        # See /order POST endpoint definition
        payload = {
            # alternativeId links back to our system
            "alternativeId": str(order.id),
            # Customer reference (SuSoft Customer object with just id)
            "customer": {
                "id": order.customer.susoft_customer_id
            },
            # Delivery date (ISO format with time for SuSoft)
            "deliveryDate": order.delivery_date.strftime("%Y-%m-%dT00:00:00"),
            # Order lines array
            "lines": [
                {
                    "product": {
                        "id": line.product.susoft_product_id
                    },
                    "quantity": float(line.quantity),
                    # NET pris (eks. MVA). Norsk B2B-konvensjon.
                    "price": float(line.unit_price),
                    "unitPrice": float(line.unit_price),
                    "netPrice": float(line.unit_price),
                    # priceRef: 0 = RETAIL_PRICE (inkl. MVA), 1 = NET_PRICE (eks. MVA).
                    "priceRef": 1,
                    # MVA-info \u2014 n\u00f8dvendig for at SuSoft skal beregne fakturabel\u00f8p.
                    "vatPercent": float(line.vat_rate),
                    "vatAmount": float(line.line_vat),
                    # SuSoft sin "total" er brutto (inkl. MVA), tilsvarer netTotal+vatAmount.
                    "total": float(line.line_amount_incl_vat),
                    "note": line.notes or ""
                }
                for line in order.lines
                if line.product.susoft_product_id
            ],
            # Notes
            "note": order.customer_notes or "",
            # Mark as for invoicing (B2B orders)
            "isForInvoicing": True,
            # Customer reference for invoice
            "customerReference": f"Ordre #{order.id}"
        }
        
        # Add delivery address if available (use customer address if no specific delivery address)
        delivery_addr = getattr(order, 'delivery_address', None) or order.customer.street_address
        if delivery_addr:
            payload["deliveryAddress"] = {
                "addressLine1": delivery_addr,
                "city": order.customer.city or "",
                "zipCode": order.customer.postal_code or "",
                "name": order.customer.name
            }
        
        endpoint = "/order"
        
        # DEBUG: Logg n\u00f8kkelfelt fra payload slik at vi kan verifisere at
        # priser og MVA faktisk sendes til SuSoft.
        logger.info(
            "create_order payload: order_id=%s, lines=%s",
            order.id,
            [
                {
                    "product_id": ln.get("product", {}).get("id"),
                    "qty": ln.get("quantity"),
                    "price": ln.get("price"),
                    "unitPrice": ln.get("unitPrice"),
                    "vatPercent": ln.get("vatPercent"),
                    "vatAmount": ln.get("vatAmount"),
                    "total": ln.get("total"),
                    "priceRef": ln.get("priceRef"),
                }
                for ln in payload.get("lines", [])
            ],
        )
        
        try:
            response = self.client.post(
                endpoint, 
                json=payload,
                headers=self._get_headers()
            )
            
            # Log the attempt
            self._log_sync(
                sync_type="order_create",
                entity_type="order",
                entity_id=order.id,
                method="POST",
                endpoint=endpoint,
                request_payload=payload,
                response_status=response.status_code,
                response_body=response.text[:1000] if response.text else None,
                success=response.is_success
            )
            
            if response.status_code in (200, 201):
                data = response.json()
                # SuSoft returns Order object with orderNo
                return str(data.get("orderNo") or data.get("uuid") or data.get("alternativeId"))
            elif response.status_code == 404:
                # 404 typically means customer or product not found/allowed in SuSoft
                raise SuSoftAPIError(
                    f"Kunde eller produkt ikke funnet i SuSoft (kunde: {order.customer.susoft_customer_id})",
                    response.status_code,
                    response.text
                )
            elif response.status_code >= 500:
                raise SuSoftAPIError(
                    f"SuSoft server error: {response.status_code}",
                    response.status_code,
                    response.text
                )
            else:
                raise SuSoftAPIError(
                    f"SuSoft API error: {response.status_code} - {response.text}",
                    response.status_code,
                    response.text
                )
                
        except httpx.HTTPError as e:
            self._log_sync(
                sync_type="order_create",
                entity_type="order",
                entity_id=order.id,
                method="POST",
                endpoint=endpoint,
                request_payload=payload,
                success=False,
                error_message=str(e)
            )
            raise
    
    def update_order(self, order: Order) -> bool:
        """
        IKKE STØTTET: SuSoft REST API har INGEN `PUT /order/{id}`-endepunkt.

        En ordre er uforanderlig etter at den er opprettet via `POST /order`.
        Vi reiser eksplisitt feil her slik at kallere ikke stille feiler eller
        sender forespurt mot et endepunkt som ikke eksisterer.

        Håndtering av endringer i vårt system: cutoff-låsen (`ensure_editable`)
        sikrer at ordrer ikke kan endres etter at de er sendt til SuSoft.
        Hvis en endring må reflekteres i SuSoft, må dette gjøres manuelt der
        (eller via kreditnota når ordren er fakturert).
        """
        raise SuSoftAPIError(
            "SuSoft API støtter ikke oppdatering av ordrer (ingen PUT /order/{id}). "
            "Endringer i SuSoft må gjøres manuelt."
        )

    
    @retry(
        stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
        wait=wait_exponential(multiplier=1, min=4, max=60),
        # KUN retry p\u00e5 transport-feil. Ikke retry SuSoftAPIError her, ellers
        # risikerer vi duplikat-fakturaer hvis SuSoft mottok forrige POST men
        # vi ikke klarte \u00e5 parse svaret.
        retry=retry_if_exception_type(httpx.HTTPError),
        before_sleep=before_sleep_log(logger, logging.WARNING)
    )
    def create_invoice(
        self,
        order: Order,
        invoiced_date: Optional[date] = None,
        due_days: int = 14,
    ) -> str:
        """
        Lag faktura i SuSoft for en eksisterende ordre via POST /invoice.

        Forutsetter at `order.susoft_order_id` finnes (ordren må være sendt
        til SuSoft først via `create_order`). Vi refererer ordren via
        `alternativeId = str(order.id)` slik at vi ikke duplikat-sender linjer.

        IDEMPOTENS: Hvis ordren allerede har `susoft_invoice_no`, returner
        den uten ny POST.

        Returnerer fakturanr (string).
        """
        if order.susoft_invoice_no:
            logger.info(
                "Idempotency hit: ordre %s er allerede fakturert som %s",
                order.id, order.susoft_invoice_no,
            )
            return order.susoft_invoice_no

        if not order.susoft_order_id:
            raise SuSoftAPIError(
                "Ordre må være opprettet i SuSoft (har ingen susoft_order_id) "
                "før den kan faktureres."
            )

        inv_date = invoiced_date or date.today()
        due_date = inv_date + timedelta(days=due_days)

        # SuSoft tillater å referere eksisterende ordre med kun ett av:
        # orderNo, uuid, alternativeId. Vi bruker alternativeId (= vår order.id).
        payload = {
            "invoicedDate": inv_date.strftime("%Y-%m-%d"),
            "dueDate": due_date.strftime("%Y-%m-%d"),
            "orders": [
                {"alternativeId": str(order.id)}
            ],
        }

        endpoint = "/invoice"
        try:
            response = self.client.post(
                endpoint,
                json=payload,
                headers=self._get_headers(),
            )

            self._log_sync(
                sync_type="invoice_create",
                entity_type="order",
                entity_id=order.id,
                method="POST",
                endpoint=endpoint,
                request_payload=payload,
                response_status=response.status_code,
                response_body=response.text[:1000] if response.text else None,
                success=response.is_success,
            )

            if response.status_code in (200, 201):
                data = response.json() if response.text else {}
                invoice_no = (
                    data.get("invoiceNo")
                    or data.get("invoice_no")
                    or data.get("id")
                )
                if invoice_no is None:
                    raise SuSoftAPIError(
                        f"SuSoft returnerte ingen invoiceNo for ordre {order.id}",
                        response.status_code,
                        response.text,
                    )
                return str(invoice_no)
            elif response.status_code == 404:
                raise SuSoftAPIError(
                    f"Ordre ikke funnet i SuSoft (alternativeId={order.id}). "
                    "Send ordren først.",
                    response.status_code,
                    response.text,
                )
            elif response.status_code >= 500:
                raise SuSoftAPIError(
                    f"SuSoft server error: {response.status_code}",
                    response.status_code,
                    response.text,
                )
            else:
                raise SuSoftAPIError(
                    f"SuSoft API error: {response.status_code} - {response.text}",
                    response.status_code,
                    response.text,
                )
        except httpx.HTTPError as e:
            self._log_sync(
                sync_type="invoice_create",
                entity_type="order",
                entity_id=order.id,
                method="POST",
                endpoint=endpoint,
                request_payload=payload,
                success=False,
                error_message=str(e),
            )
            raise

    def get_order_by_alt_id(self, alt_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve order from SuSoft by alternativeId.
        Uses GET /order/altid?altId=
        """
        endpoint = f"/order/altid?altId={alt_id}"
        
        try:
            response = self.client.get(endpoint, headers=self._get_headers())
            
            if response.status_code == 200:
                return response.json()
            elif response.status_code == 404:
                return None
            else:
                logger.warning(f"Error fetching order {alt_id}: {response.status_code}")
                return None
                
        except Exception as e:
            logger.error(f"Error fetching order by altId: {e}")
            return None
    
    def get_order_by_uuid(self, uuid: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve order from SuSoft by UUID.
        Uses GET /order/uuid?uuid=
        """
        endpoint = f"/order/uuid?uuid={uuid}"
        
        try:
            response = self.client.get(endpoint, headers=self._get_headers())
            
            if response.status_code == 200:
                return response.json()
            elif response.status_code == 404:
                return None
            else:
                logger.warning(f"Error fetching order {uuid}: {response.status_code}")
                return None
                
        except Exception as e:
            logger.error(f"Error fetching order by uuid: {e}")
            return None
    
    @retry(
        stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
        wait=wait_exponential(multiplier=1, min=4, max=60),
        retry=retry_if_exception_type((httpx.HTTPError, SuSoftAPIError))
    )
    def cancel_order(self, order: Order) -> bool:
        """
        Handle order cancellation.
        
        NOTE: SuSoft API does NOT have a DELETE /order endpoint.
        Cancellation must be handled through the invoicing workflow
        or by creating a credit note.
        
        For now, we log the cancellation and mark it as handled locally.
        The actual cancellation in SuSoft may need manual intervention
        or a different workflow (e.g., invoice credit memo).
        """
        if not order.susoft_order_id:
            # Nothing to cancel in SuSoft
            return True
        
        # Log that we attempted cancellation
        self._log_sync(
            sync_type="order_cancel_request",
            entity_type="order",
            entity_id=order.id,
            method="MANUAL",
            endpoint="N/A - SuSoft has no cancel endpoint",
            success=True,
            error_message="Order cancellation logged. Manual action may be required in SuSoft."
        )
        
        # Create alert for manual handling
        self._create_alert(
            alert_type="order_cancellation",
            severity="warning",
            title=f"Order {order.id} cancelled - needs SuSoft attention",
            message=(
                f"Order {order.id} (SuSoft: {order.susoft_order_id}) was cancelled in our system. "
                f"SuSoft does not support order deletion via API. "
                f"Please handle this in SuSoft manually if needed."
            ),
            entity_type="order",
            entity_id=order.id
        )
        
        return True  # Mark as handled locally
    
    # =========================================================================
    # SYNC ORCHESTRATION
    # =========================================================================

    def sync_single_order(self, order: Order) -> str:
        """
        Synk en enkelt ordre til SuSoft. Brukes av `sync_order` Celery-tasken
        for umiddelbar synkronisering når en ordre bekreftes/låses.

        Returnerer susoft_order_id ved suksess. Kaster SuSoftAPIError ved feil
        (Celery-tasken håndterer backoff).
        """
        from ..models import OrderStatus
        from ..time_utils import now_utc, to_naive_utc

        if order.status == OrderStatus.CANCELLED:
            self.cancel_order(order)
            order.sync_status = SyncStatus.CANCELLED
            order.last_sync_attempt = to_naive_utc(now_utc())
            return order.susoft_order_id or ""

        if order.susoft_order_id:
            # Eksisterer allerede i SuSoft. SuSoft har ingen update-endepunkt,
            # så vi behandler dette som en no-op og markerer som synkronisert.
            order.sync_status = SyncStatus.SYNCED
        else:
            # Ny ordre — opprett (idempotens-sjekk gjøres internt)
            susoft_id = self.create_order(order)
            order.susoft_order_id = susoft_id
            order.sync_status = SyncStatus.SYNCED
            if order.status == OrderStatus.CONFIRMED:
                order.status = OrderStatus.READY_FOR_DELIVERY

        order.last_sync_attempt = to_naive_utc(now_utc())
        order.sync_error_message = None
        order.next_retry_at = None
        return order.susoft_order_id

    def sync_pending_orders(self) -> Dict[str, int]:
        """
        Sync orders that are waiting for retry (sweep-job).

        Plukker kun opp ordrer der `next_retry_at` er passert (eller NULL),
        slik at vi respekterer eksponentiell backoff fra Celery-tasken.

        Supports:
        - Creating new orders (POST /order, idempotent)
        - Cancellation logging (SuSoft har ikke DELETE /order — alert opprettes)

        MERK: SuSoft har ikke PUT /order/{id}. Ordrer som allerede er sendt
        (har `susoft_order_id`) hoppes over.
        """
        from ..time_utils import now_utc, to_naive_utc

        now_naive = to_naive_utc(now_utc())

        # Get orders needing sync
        query = select(Order).where(
            Order.is_deleted == False,
            Order.sync_status.in_([
                SyncStatus.PENDING,
                SyncStatus.RETRY_SCHEDULED,
                SyncStatus.FAILED,
            ]),
        )
        # Respekter backoff: kun ordrer der retry-tidspunkt er passert
        query = query.where(
            (Order.next_retry_at.is_(None)) | (Order.next_retry_at <= now_naive)
        )
        if self.tenant_id is not None:
            query = query.where(Order.tenant_id == self.tenant_id)

        orders = self.db.execute(query).scalars().all()

        results = {"synced": 0, "updated": 0, "failed": 0, "cancelled": 0, "skipped": 0}

        for order in orders:
            try:
                if order.status == OrderStatus.CANCELLED:
                    if self.cancel_order(order):
                        order.sync_status = SyncStatus.CANCELLED
                        results["cancelled"] += 1
                elif order.susoft_order_id:
                    # SuSoft har ingen update-endepunkt; ordren ligger
                    # allerede der. Marker som synkronisert og hopp over.
                    order.sync_status = SyncStatus.SYNCED
                    results["skipped"] += 1
                else:
                    # Bruk idempotent create_order
                    susoft_id = self.create_order(order)
                    order.susoft_order_id = susoft_id
                    order.sync_status = SyncStatus.SYNCED
                    if order.status == OrderStatus.CONFIRMED:
                        order.status = OrderStatus.READY_FOR_DELIVERY
                    results["synced"] += 1

                order.last_sync_attempt = now_naive
                order.sync_error_message = None
                order.next_retry_at = None

            except (SuSoftAPIError, httpx.HTTPError) as e:
                order.sync_status = SyncStatus.FAILED
                order.sync_retry_count = (order.sync_retry_count or 0) + 1
                order.last_sync_attempt = now_naive

                # Eksponentiell backoff: 1m, 2m, 4m, 8m, 16m, 32m, 60m (max)
                backoff_minutes = min(60, 2 ** min(order.sync_retry_count - 1, 6))
                order.next_retry_at = to_naive_utc(now_utc() + timedelta(minutes=backoff_minutes))
                order.sync_error_message = str(e)[:500]
                results["failed"] += 1

                # Create alert if max retries reached
                if order.sync_retry_count >= MAX_RETRY_ATTEMPTS * 3:
                    self._create_alert(
                        alert_type="sync_failure",
                        severity="error",
                        title=f"Order sync parkert: {order.id}",
                        message=(
                            f"Sync feilet etter {order.sync_retry_count} fors\u00f8k. "
                            f"Manuell intervensjon kreves. Siste feil: {str(e)[:200]}"
                        ),
                        entity_type="order",
                        entity_id=order.id
                    )

        self.db.commit()
        return results
    
    # =========================================================================
    # CUSTOMER/PRODUCT SYNC (FROM SUSOFT)
    # =========================================================================
    
    def sync_customers_from_susoft(self, modified_since: Optional[datetime] = None) -> Dict[str, int]:
        """
        Pull customer data from SuSoft and update local database.
        
        Uses:
        - GET /customer/list/modified?dateTime= (if modified_since provided)
        - GET /customer/list (paginated, for full sync)
        
        SuSoft Customer fields mapped:
        - id -> susoft_customer_id
        - lastName (company name for B2B)
        - firstName
        - address.addressLine1, city, zipCode
        - address.email, mobilePhone
        """
        self._ensure_tenant_available()
        results = {"created": 0, "updated": 0, "errors": 0, "fetched": 0}
        
        try:
            if modified_since:
                date_str = modified_since.strftime("%Y-%m-%dT%H:%M:%S.000")
                customers_data = self._fetch_paginated_get(
                    "/customer/list/modified",
                    params={"dateTime": date_str},
                )
            else:
                customers_data = self._fetch_paginated_get("/customer/list")

            results["fetched"] = len(customers_data)
            seen_ids: set[str] = set()

            for cust_data in customers_data:
                try:
                    susoft_id = cust_data.get("id")
                    if susoft_id is None or susoft_id == "":
                        continue
                    susoft_id = str(susoft_id)
                    if susoft_id in seen_ids:
                        # SuSoft pagination can repeat the same record across pages.
                        continue
                    seen_ids.add(susoft_id)

                    # Extract address info
                    address = cust_data.get("address", {}) or {}

                    existing = self.db.execute(
                        select(Customer).where(
                            Customer.tenant_id == self.tenant_id,
                            Customer.susoft_customer_id == susoft_id,
                        )
                    ).scalar_one_or_none()

                    name, company_name, contact_person = self._build_customer_name(cust_data)
                    street = (address.get("addressLine1") or address.get("addressLine2") or "")[:500] or None
                    
                    if existing:
                        # Update existing customer
                        existing.name = name
                        existing.company_name = company_name
                        existing.contact_person = contact_person
                        existing.email = (address.get("email") or "")[:255] or None
                        existing.phone = ((address.get("mobilePhone") or address.get("landLinePhone") or "")[:50]) or None
                        existing.street_address = street
                        existing.postal_code = (address.get("zipCode") or "")[:20] or None
                        existing.city = (address.get("city") or "")[:100] or None
                        existing.is_active = cust_data.get("isActive", True)
                        existing.susoft_last_synced_at = datetime.utcnow()
                        results["updated"] += 1
                    else:
                        # Create new customer
                        customer = Customer(
                            tenant_id=self.tenant_id,
                            susoft_customer_id=susoft_id,
                            name=name,
                            company_name=company_name,
                            contact_person=contact_person,
                            email=(address.get("email") or "")[:255] or None,
                            phone=((address.get("mobilePhone") or address.get("landLinePhone") or "")[:50]) or None,
                            street_address=street,
                            postal_code=(address.get("zipCode") or "")[:20] or None,
                            city=(address.get("city") or "")[:100] or None,
                            is_active=cust_data.get("isActive", True),
                            susoft_last_synced_at=datetime.utcnow()
                        )
                        self.db.add(customer)
                        results["created"] += 1
                        
                except Exception as e:
                    logger.error(f"Error syncing customer {cust_data.get('id')}: {e}")
                    results["errors"] += 1
            
            self.db.commit()
            
        except Exception as e:
            logger.error(f"Customer sync failed: {e}")
            self._create_alert(
                alert_type="sync_failure",
                severity="warning",
                title="Customer sync from SuSoft failed",
                message=str(e)
            )
            raise
        
        return results
    
    def sync_products_from_susoft(self, modified_since: Optional[datetime] = None) -> Dict[str, int]:
        """
        Pull product data from SuSoft and update local database.
        
        Uses GET /product/list/modified?dateTime= endpoint.
        
        SuSoft Product fields mapped:
        - id -> susoft_product_id
        - externalRefId -> sku
        - name
        - description
        - retailPrice -> default_price
        - category1 -> category
        - barcode
        - vatPercent
        """
        self._ensure_tenant_available()
        results = {"created": 0, "updated": 0, "errors": 0, "fetched": 0}
        
        try:
            if modified_since:
                date_str = modified_since.strftime("%Y-%m-%dT%H:%M:%S.000")
                products_data = self._fetch_paginated_get(
                    "/product/list/modified",
                    params={"dateTime": date_str, "withVariants": "true"},
                )
            else:
                # Prefer /product/search for full sync. Fallback to list/modified.
                try:
                    products_data = self._fetch_paginated_product_search()
                except Exception as e:
                    logger.warning("/product/search failed, fallback to /product/list/modified: %s", e)
                    products_data = self._fetch_paginated_get(
                        "/product/list/modified",
                        params={"withVariants": "true"},
                    )

            results["fetched"] = len(products_data)
            seen_ids: set[str] = set()

            # Resolve category IDs to human readable names once per sync
            category_names = self._fetch_category_name_map()

            def resolve_category(prod: Dict[str, Any]) -> Optional[str]:
                # Prefer the explicit name from SuSoft if present
                name = prod.get("categoryName")
                if name:
                    return str(name)[:100]
                # Otherwise build a path from category1..category5 using the tree
                parts: List[str] = []
                for key in ("category1", "category2", "category3", "category4", "category5"):
                    cid = prod.get(key)
                    if not cid:
                        continue
                    cid_str = str(cid)
                    parts.append(category_names.get(cid_str, cid_str))
                if parts:
                    return " / ".join(parts)[:100]
                return None

            for prod_data in products_data:
                try:
                    susoft_id = prod_data.get("id")
                    if susoft_id is None or susoft_id == "":
                        continue
                    susoft_id = str(susoft_id)
                    if susoft_id in seen_ids:
                        continue
                    seen_ids.add(susoft_id)

                    existing = self.db.execute(
                        select(Product).where(
                            Product.tenant_id == self.tenant_id,
                            Product.susoft_product_id == susoft_id,
                        )
                    ).scalar_one_or_none()
                    
                    if existing:
                        # Update existing product
                        existing.name = (prod_data.get("name") or existing.name or "Unknown")[:255]
                        existing.description = prod_data.get("description")
                        existing.default_price = Decimal(str(prod_data.get("retailPrice", 0)))
                        existing.category = resolve_category(prod_data)
                        existing.vat_rate = Decimal(str(prod_data.get("vatPercent", existing.vat_rate or 15)))
                        existing.unit = (prod_data.get("unit") or existing.unit or "stk")[:20]
                        existing.is_active = prod_data.get("active", True)
                        existing.allergens = _format_allergens(prod_data.get("allergens"))
                        existing.susoft_last_synced_at = datetime.utcnow()
                        results["updated"] += 1
                    else:
                        # Create new product
                        category_value = resolve_category(prod_data)
                        product = Product(
                            tenant_id=self.tenant_id,
                            susoft_product_id=susoft_id,
                            sku=prod_data.get("externalRefId") or prod_data.get("barcode") or f"SUSOFT-{susoft_id}",
                            name=(prod_data.get("name") or "Unknown")[:255],
                            description=prod_data.get("description"),
                            default_price=Decimal(str(prod_data.get("retailPrice", 0))),
                            category=category_value,
                            unit=(prod_data.get("unit") or "stk")[:20],
                            vat_rate=Decimal(str(prod_data.get("vatPercent", 15))),
                            is_active=prod_data.get("active", True),
                            allergens=_format_allergens(prod_data.get("allergens")),
                            susoft_last_synced_at=datetime.utcnow()
                        )
                        self.db.add(product)
                        results["created"] += 1
                        
                except Exception as e:
                    logger.error(f"Error syncing product {prod_data.get('id')}: {e}")
                    results["errors"] += 1
            
            self.db.commit()
            
        except Exception as e:
            logger.error(f"Product sync failed: {e}")
            self._create_alert(
                alert_type="sync_failure",
                severity="warning",
                title="Product sync from SuSoft failed",
                message=str(e)
            )
            raise
        
        return results
    
    # =========================================================================
    # UTILITY METHODS
    # =========================================================================
    
    def get_customer_by_external_id(self, external_id: str) -> Optional[Dict[str, Any]]:
        """
        Load customer from SuSoft by external ref ID.
        Uses GET /customer/alternative/id?id=
        """
        endpoint = f"/customer/alternative/id?id={external_id}"
        
        try:
            response = self.client.get(endpoint, headers=self._get_headers())
            
            if response.status_code == 200:
                return response.json()
            return None
            
        except Exception as e:
            logger.error(f"Error fetching customer by external ID: {e}")
            return None
    
    def get_product_by_id(self, product_id: str) -> Optional[Dict[str, Any]]:
        """
        Load product from SuSoft by ID.
        Uses GET /product/id?productId=
        """
        endpoint = f"/product/id?productId={product_id}"
        
        try:
            response = self.client.get(endpoint, headers=self._get_headers())
            
            if response.status_code == 200:
                return response.json()
            return None
            
        except Exception as e:
            logger.error(f"Error fetching product: {e}")
            return None
    
    def health_check(self) -> bool:
        """
        Check SuSoft API health.
        Uses GET /health endpoint.
        """
        try:
            response = self.client.get("/health", headers=self._get_headers())
            return response.status_code == 200
        except Exception:
            return False
