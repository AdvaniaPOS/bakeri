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


def parse_susoft_datetime(value) -> Optional[datetime]:
    """
    Parse en SuSoft datetime-verdi. SuSoft sender et zoo av formater:

    - int 8-sifret    `20260502`              -> yyyyMMdd
    - int 12-sifret   `202605040012`          -> yyyyMMddHHmm
    - int 14-sifret   `20260503223018`        -> yyyyMMddHHmmss
    - str             `"2026/05/08 00:12:00.000000"`  (mikrosekunder)
    - str             `"2026/05/08 00:12:00"`
    - str ISO         `"2026-05-08T00:12:00"`
    - str dato        `"2026-05-08"`

    Returnerer naive `datetime` (uten tz). None hvis verdien er falsy/ugyldig.
    """
    if value is None or value == "" or value == 0:
        return None

    # Numerisk
    if isinstance(value, (int, float)):
        s = str(int(value))
    else:
        s = str(value).strip()
        if not s:
            return None

    # Numerisk-streng (kun siffer) -> samme parsing som int
    if s.isdigit():
        try:
            if len(s) == 14:
                return datetime.strptime(s, "%Y%m%d%H%M%S")
            if len(s) == 12:
                return datetime.strptime(s, "%Y%m%d%H%M")
            if len(s) == 8:
                return datetime.strptime(s, "%Y%m%d")
        except ValueError:
            return None
        return None

    # String-formater
    fmts = (
        "%Y/%m/%d %H:%M:%S.%f",
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
    )
    # Strip evt. timezone-suffiks
    cleaned = s.replace("Z", "")
    for fmt in fmts:
        try:
            return datetime.strptime(cleaned, fmt)
        except ValueError:
            continue
    logger.debug("Klarte ikke parse SuSoft datetime: %r", value)
    return None


def pick_susoft_fulfillment(row: Dict[str, Any]) -> Tuple[Optional[datetime], str]:
    """
    Velg fulfillment for en SuSoft-ordrerad.

    Returnerer (dt, kind) hvor kind er "pickup", "delivery" eller "unknown".
    Foretrekker pickup hvis begge skulle finnes.
    """
    pickup = parse_susoft_datetime(row.get("pickupDate"))
    if pickup is not None:
        return pickup, "pickup"
    delivery = parse_susoft_datetime(row.get("deliveryDate"))
    if delivery is not None:
        return delivery, "delivery"
    return None, "unknown"


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

# Per-tenant admin-API JWT token cache (separat fra hoved-API):
# {tenant_id: (token, expires_at)}
_admin_token_cache: Dict[int, tuple] = {}

# Default-base for SuSoft admin-API ("API 2") - api.susoft.com uten port.
SUSOFT_ADMIN_BASE_URL_DEFAULT = os.getenv(
    "SUSOFT_ADMIN_BASE_URL", "https://api.susoft.com"
)


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
        # Admin-API ("API 2") - lazy konfig + egen httpx-klient.
        self._admin_cfg_loaded: bool = False
        self._admin_login: str = ""
        self._admin_password: str = ""
        self._admin_shop_key: str = ""
        self._admin_shop_id: Optional[int] = None
        self._admin_base_url: str = SUSOFT_ADMIN_BASE_URL_DEFAULT
        self._admin_client: Optional[httpx.Client] = None

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
        """Issue a request and transparently retry on transient failures.

        Retries on:
        - HTTP 429 (honours Retry-After header)
        - HTTP 5xx (server-side errors)
        - Network errors (ConnectError, ReadTimeout, RemoteProtocolError, etc.)

        Backoff schedule: 1s → 2s → 4s → 8s → 16s → 30s (capped).
        Total max wait ≈ 60s across 5 retries — covers brief outages without
        blocking workers too long.
        """
        delay = 1.0
        last_exc: Optional[Exception] = None
        for attempt in range(max_retries + 1):
            try:
                response = self.client.request(method, path, **kwargs)
                last_exc = None
            except (
                httpx.ConnectError,
                httpx.ConnectTimeout,
                httpx.ReadTimeout,
                httpx.WriteTimeout,
                httpx.PoolTimeout,
                httpx.RemoteProtocolError,
                httpx.NetworkError,
            ) as e:
                last_exc = e
                if attempt == max_retries:
                    logger.error(
                        "SuSoft network error on %s %s after %d attempts: %s",
                        method, path, attempt + 1, e,
                    )
                    self._update_tenant_status("failed", f"Network error: {e}")
                    raise SuSoftAPIError(f"Connection lost to SuSoft: {e}") from e
                wait = min(delay, 30.0)
                logger.warning(
                    "SuSoft network error on %s %s (attempt %d/%d): %s — retrying in %.1fs",
                    method, path, attempt + 1, max_retries, e, wait,
                )
                time.sleep(wait)
                delay = min(delay * 2, 30.0)
                continue

            # Retry on 429 / 5xx
            should_retry = response.status_code == 429 or 500 <= response.status_code < 600
            if not should_retry or attempt == max_retries:
                return response

            retry_after = response.headers.get("Retry-After")
            try:
                wait = float(retry_after) if retry_after else delay
            except ValueError:
                wait = delay
            wait = min(max(wait, 0.5), 30.0)
            logger.warning(
                "SuSoft returned %d for %s %s (attempt %d/%d); sleeping %.1fs",
                response.status_code, method, path, attempt + 1, max_retries, wait,
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
        """
        Hent alle produkter fra Susoft og merk hvert med korrekt aktiv-status.

        Susoft sitt `/product/search`-endepunkt returnerer ALLTID
        `"active": true` på hvert produkt uansett reell status (bekreftet via
        scripts/probe_susoft_active.py mai 2026). Eneste pålitelige
        diskriminator er hvilken liste produktet kommer fra:
            activityFlag=ACTIVE   -> reelt aktive
            activityFlag=INACTIVE -> reelt inaktive (skjult i Susoft-UI)

        Vi kjører derfor to kall og overstyrer `active`-feltet basert på
        hvilken bøtte produktet havnet i. Dedupe på `id` (en produkt kan i
        teorien dukke opp i begge — vi prioriterer ACTIVE da).
        """
        def _fetch_one_flag(flag: str) -> List[Dict[str, Any]]:
            collected: List[Dict[str, Any]] = []
            page = 0
            while True:
                endpoint = f"/product/search?page={page}&pageSize={page_size}&activityFlag={flag}"
                response = self._request_with_throttle_retry(
                    "POST",
                    endpoint,
                    json={"filterGroups": []},
                    headers=self._get_headers(),
                )
                if not response.is_success:
                    raise SuSoftAPIError(
                        f"Failed to fetch /product/search ({flag}): {response.status_code}",
                        response.status_code,
                        response.text,
                    )
                batch = response.json() or []
                if not isinstance(batch, list):
                    raise SuSoftAPIError(
                        f"Unexpected response type from /product/search ({flag}): {type(batch).__name__}"
                    )
                collected.extend(batch)
                if len(batch) < page_size:
                    break
                page += 1
            return collected

        active_items = _fetch_one_flag("ACTIVE")
        inactive_items = _fetch_one_flag("INACTIVE")

        seen_ids: set[str] = set()
        merged: List[Dict[str, Any]] = []

        # ACTIVE først — vinner ved duplikat
        for prod in active_items:
            pid = prod.get("id")
            if pid in (None, ""):
                continue
            pid_str = str(pid)
            if pid_str in seen_ids:
                continue
            seen_ids.add(pid_str)
            prod["active"] = True  # Tving korrekt verdi
            merged.append(prod)

        for prod in inactive_items:
            pid = prod.get("id")
            if pid in (None, ""):
                continue
            pid_str = str(pid)
            if pid_str in seen_ids:
                continue
            seen_ids.add(pid_str)
            prod["active"] = False  # Tving korrekt verdi (Susoft API lyver)
            merged.append(prod)

        logger.info(
            "Susoft /product/search: %d aktive + %d inaktive = %d totalt (deduped)",
            len(active_items), len(inactive_items), len(merged),
        )
        return merged

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

    def test_admin_connection(self) -> tuple[bool, Optional[str]]:
        """
        Test connection mot SuSoft Admin-API ("API 2") for aPOS-CART-er.
        Returnerer (success, error_message). Forsoker auth + et lett kall mot
        /admin/order/list for aa verifisere at admin-credentials og shop_id
        faktisk gir tilgang.
        """
        self._load_admin_config(force=True)
        self._invalidate_admin_token()

        if not self._admin_login or not self._admin_password:
            return False, "Mangler admin-login eller admin-passord"

        token = self._get_admin_token(force=True)
        if not token:
            return False, "Autentisering mot admin-API feilet (sjekk login/passord)"

        # Lett verifisering: prov et kort /admin/order/list-kall.
        # Hvis shop_id mangler vil dette feile - da returnerer vi en
        # informativ melding i stedet for raw stack-trace.
        if self._admin_shop_id is None:
            # Auth fungerte, men shop_id mangler for produksjonsbruk.
            return True, "Auth OK, men admin_shop_id mangler (kreves for /admin/order/list)"

        try:
            client = self._get_admin_client()
            headers = {"Authorization": f"Bearer {token}"}
            if self._admin_shop_key:
                headers["X-Shop-Url-Key"] = self._admin_shop_key
            # Kall med smal periode for aa minimere belastning.
            from datetime import timedelta as _td
            now = datetime.utcnow()
            params = {
                "fromDate": (now - _td(days=1)).strftime("%Y-%m-%dT00:00:00.000"),
                "toDate": now.strftime("%Y-%m-%dT00:00:00.000"),
                "shopId": self._admin_shop_id,
            }
            resp = client.get("/admin/order/list", headers=headers, params=params)
            if resp.status_code == 200:
                return True, None
            return False, f"/admin/order/list returnerte HTTP {resp.status_code}: {resp.text[:200]}"
        except Exception as e:
            return False, f"Admin-API kall feilet: {e}"

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

            # Auth-call: retry på nettverksfeil og 5xx (3 forsøk).
            # 429/Retry-After håndteres også. Bruker IKKE _request_with_throttle_retry
            # her fordi den oppdaterer tenant-status — vi gjør det selv nedenfor.
            delay = 1.0
            response = None
            for attempt in range(3):
                try:
                    response = self.client.post(
                        "/user/auth",
                        json={"login": self._cfg_login, "password": self._cfg_password},
                        headers=headers,
                    )
                except (
                    httpx.ConnectError,
                    httpx.ConnectTimeout,
                    httpx.ReadTimeout,
                    httpx.WriteTimeout,
                    httpx.PoolTimeout,
                    httpx.RemoteProtocolError,
                    httpx.NetworkError,
                ) as e:
                    if attempt == 2:
                        logger.error("SuSoft auth network error (tenant=%s): %s", self.tenant_id, e)
                        self._update_tenant_status("failed", f"Network error: {e}")
                        return None
                    logger.warning(
                        "SuSoft auth network error (attempt %d/3): %s — retrying in %.1fs",
                        attempt + 1, e, delay,
                    )
                    time.sleep(delay)
                    delay = min(delay * 2, 8.0)
                    continue

                if 500 <= response.status_code < 600 and attempt < 2:
                    logger.warning(
                        "SuSoft auth got %d (attempt %d/3) — retrying in %.1fs",
                        response.status_code, attempt + 1, delay,
                    )
                    time.sleep(delay)
                    delay = min(delay * 2, 8.0)
                    continue
                break

            if response is None:
                self._update_tenant_status("failed", "No response from SuSoft auth")
                return None

            if response.is_success:
                data = response.json()
                token = data.get("token")
                if token:
                    _token_cache[cache_key] = (token, datetime.utcnow() + timedelta(hours=23))
                    # Mark connection healthy on successful auth
                    self._update_tenant_status("ok", None)
                    return token
                logger.error("SuSoft auth ga 200 men ingen token: %s", response.text[:500])
                self._update_tenant_status("failed", "Auth 200 OK but no token in response")
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
    # SUSOFT ADMIN-API ("API 2") - henter CART-er fra aPOS-kassen
    # =========================================================================
    #
    # SuSoft har et separat admin-API på api.susoft.com (uten port) med egne
    # kredentialer. Dette er nødvendig for å hente CART-er (åpne handlekurver
    # fra aPOS) som ikke er tilgjengelige via det vanlige /order/list.
    #
    # Flyt:
    #   1. POST {admin_base}/user/auth        -> JWT for admin-API
    #   2. GET  {admin_base}/admin/order/list -> liste over CART-er (UTEN linjer)
    #   3. GET  {api_base}/shopping-cart/uuid -> linjer/priser/mva for én cart
    #      (NB: cart-detalj kjøres mot 4443-API-et, men med ADMIN-Bearer)

    def _load_admin_config(self, force: bool = False) -> None:
        """Last admin-API-konfig fra Tenant-tabellen. Cachet pr. service-instans."""
        if self._admin_cfg_loaded and not force:
            return

        login = ""
        password = ""
        shop_key = ""
        shop_id: Optional[int] = None
        base_url = SUSOFT_ADMIN_BASE_URL_DEFAULT

        if self.tenant_id is not None:
            try:
                from ..auth_models import Tenant
                from ..crypto_utils import decrypt_secret

                tenant = self.db.get(Tenant, self.tenant_id)
                if tenant:
                    if tenant.susoft_admin_login:
                        login = tenant.susoft_admin_login
                    decrypted = decrypt_secret(tenant.susoft_admin_password_encrypted)
                    if decrypted:
                        password = decrypted
                    if tenant.susoft_admin_shop_url_key:
                        shop_key = tenant.susoft_admin_shop_url_key
                    if tenant.susoft_admin_shop_id is not None:
                        shop_id = int(tenant.susoft_admin_shop_id)
                    if tenant.susoft_admin_api_url:
                        base_url = tenant.susoft_admin_api_url
            except Exception as e:
                logger.warning(
                    "Klarte ikke lese SuSoft admin-konfig fra tenant %s: %s",
                    self.tenant_id, e,
                )

        self._admin_login = login or ""
        self._admin_password = password or ""
        self._admin_shop_key = shop_key or ""
        self._admin_shop_id = shop_id
        if base_url and base_url != self._admin_base_url:
            if self._admin_client is not None:
                try:
                    self._admin_client.close()
                except Exception:
                    pass
                self._admin_client = None
            self._admin_base_url = base_url
        self._admin_cfg_loaded = True

    def _get_admin_client(self) -> httpx.Client:
        """Lazy-instansier httpx.Client for admin-API."""
        if self._admin_client is None:
            self._admin_client = httpx.Client(
                base_url=self._admin_base_url,
                timeout=SUSOFT_TIMEOUT,
            )
        return self._admin_client

    def _invalidate_admin_token(self) -> None:
        if self.tenant_id is not None:
            _admin_token_cache.pop(self.tenant_id, None)

    def _get_admin_token(self, force: bool = False) -> Optional[str]:
        """Hent JWT mot admin-API. Cachet pr. tenant_id."""
        self._load_admin_config()

        if not self._admin_login or not self._admin_password:
            logger.warning(
                "SuSoft admin-credentials mangler (tenant_id=%s)", self.tenant_id
            )
            return None

        cache_key = self.tenant_id if self.tenant_id is not None else 0
        if not force:
            cached = _admin_token_cache.get(cache_key)
            if cached:
                token, expires_at = cached
                if token and expires_at and datetime.utcnow() < expires_at:
                    return token

        headers = {"Content-Type": "application/json"}
        if self._admin_shop_key:
            headers["X-Shop-Url-Key"] = self._admin_shop_key

        client = self._get_admin_client()
        delay = 1.0
        response = None
        for attempt in range(3):
            try:
                response = client.post(
                    "/user/auth",
                    json={
                        "login": self._admin_login,
                        "password": self._admin_password,
                        "refreshToken": "string",
                    },
                    headers=headers,
                )
            except (
                httpx.ConnectError,
                httpx.ConnectTimeout,
                httpx.ReadTimeout,
                httpx.WriteTimeout,
                httpx.PoolTimeout,
                httpx.RemoteProtocolError,
                httpx.NetworkError,
            ) as e:
                if attempt == 2:
                    logger.error(
                        "SuSoft admin-auth network error (tenant=%s): %s",
                        self.tenant_id, e,
                    )
                    return None
                logger.warning(
                    "SuSoft admin-auth network error (attempt %d/3): %s — retry %.1fs",
                    attempt + 1, e, delay,
                )
                time.sleep(delay)
                delay = min(delay * 2, 8.0)
                continue
            if 500 <= response.status_code < 600 and attempt < 2:
                time.sleep(delay)
                delay = min(delay * 2, 8.0)
                continue
            break

        if response is None or not response.is_success:
            logger.error(
                "SuSoft admin-auth feilet (tenant=%s): %s body=%s",
                self.tenant_id,
                response.status_code if response is not None else "no response",
                response.text[:500] if response is not None else "",
            )
            return None

        data = response.json() or {}
        token = data.get("token")
        if not token:
            logger.error(
                "SuSoft admin-auth 200 OK uten token: %s", response.text[:300]
            )
            return None
        _admin_token_cache[cache_key] = (token, datetime.utcnow() + timedelta(hours=23))
        return token

    def _admin_headers(self, with_auth: bool = True) -> Dict[str, str]:
        self._load_admin_config()
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self._admin_shop_key:
            headers["X-Shop-Url-Key"] = self._admin_shop_key
        if with_auth:
            token = self._get_admin_token()
            if token:
                headers["Authorization"] = f"Bearer {token}"
        return headers

    def _admin_request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
        max_retries: int = 5,
    ) -> httpx.Response:
        """Forespørsel mot admin-API med 429/5xx/nettverks-retry. Re-auth ved 401."""
        client = self._get_admin_client()
        headers = self._admin_headers()

        delay = 1.0
        last_response: Optional[httpx.Response] = None
        for attempt in range(max_retries + 1):
            try:
                response = client.request(
                    method, path, params=params, json=json_body, headers=headers
                )
            except (
                httpx.ConnectError,
                httpx.ConnectTimeout,
                httpx.ReadTimeout,
                httpx.WriteTimeout,
                httpx.PoolTimeout,
                httpx.RemoteProtocolError,
                httpx.NetworkError,
            ) as e:
                if attempt == max_retries:
                    raise SuSoftAPIError(
                        f"Admin-API connection error: {e}"
                    ) from e
                wait = min(delay, 30.0)
                logger.warning(
                    "Admin-API network error %s %s (%d/%d): %s -- retry %.1fs",
                    method, path, attempt + 1, max_retries, e, wait,
                )
                time.sleep(wait)
                delay = min(delay * 2, 30.0)
                continue

            # Re-auth en gang ved 401
            if response.status_code == 401 and attempt == 0:
                logger.info("Admin-API 401 -- forsøker re-autentisering")
                self._invalidate_admin_token()
                new_token = self._get_admin_token(force=True)
                if new_token:
                    headers["Authorization"] = f"Bearer {new_token}"
                    continue

            should_retry = response.status_code == 429 or 500 <= response.status_code < 600
            if not should_retry or attempt == max_retries:
                return response

            retry_after = response.headers.get("Retry-After")
            try:
                wait = float(retry_after) if retry_after else delay
            except ValueError:
                wait = delay
            wait = min(max(wait, 0.5), 30.0)
            logger.warning(
                "Admin-API HTTP %d for %s %s (%d/%d) -- sleep %.1fs",
                response.status_code, method, path, attempt + 1, max_retries, wait,
            )
            time.sleep(wait)
            delay = min(delay * 2, 30.0)
            last_response = response
        return last_response  # type: ignore[return-value]

    def list_admin_carts(
        self,
        date_from: date,
        date_to: date,
        *,
        type_: str = "CART",
        status: str = "",
        source: str = "ANY",
        page_size: int = 100,
        shop_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Hent listen over CART-er fra `/admin/order/list`.

        Returnerer en flat liste med admin-rader (uten linjer). Hver rad har
        typisk feltene: uuid, orderNo, alternativeId, customer, orderDate,
        deliveryDate, type, status, amount, ...

        For å få linjer må `get_cart_detail(uuid)` kalles per rad.
        """
        self._ensure_tenant_available()
        self._load_admin_config()

        sid = shop_id if shop_id is not None else self._admin_shop_id
        if sid is None:
            raise SuSoftAPIError(
                "Mangler susoft_admin_shop_id på tenant for /admin/order/list"
            )

        params: Dict[str, Any] = {
            "pageSize": page_size,
            "term": "",
            "shopIds": sid,
            "type": type_,
            "source": source,
            "status": status,
            "fromDateTime": date_from.strftime("%Y%m%d000000"),
            "toDateTime": date_to.strftime("%Y%m%d235959"),
            "salespersonId": "",
            "deliveryId": "",
        }

        response = self._admin_request("GET", "/admin/order/list", params=params)
        if not response.is_success:
            raise SuSoftAPIError(
                f"/admin/order/list feilet: HTTP {response.status_code}",
                response.status_code,
                response.text,
            )

        body = response.json() or []
        if not isinstance(body, list):
            raise SuSoftAPIError(
                f"Uventet /admin/order/list-respons: {type(body).__name__}"
            )
        # Annoter shop-id for sporbarhet (likt list_orders-mønsteret)
        for row in body:
            if isinstance(row, dict):
                row.setdefault("_shopId", sid)
        logger.info(
            "SuSoft /admin/order/list type=%s %s..%s shop=%s -> %d rader",
            type_, date_from, date_to, sid, len(body),
        )
        return body

    def get_cart_detail(self, uuid: str) -> Optional[Dict[str, Any]]:
        """
        Hent full handlekurv-detalj (inkludert linjer) for en gitt cart-uuid.

        Bruker hoved-API-host (4443) men med admin-Bearer + admin-shop-key.
        Dette er bekreftet via probe (`probe_admin_carts.py`).
        """
        if not uuid:
            return None
        self._load_admin_config()
        token = self._get_admin_token()
        if not token:
            raise SuSoftAPIError("Ingen admin-token tilgjengelig for cart-detalj")

        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
        }
        if self._admin_shop_key:
            headers["X-Shop-Url-Key"] = self._admin_shop_key

        response = self._request_with_throttle_retry(
            "GET",
            "/shopping-cart/uuid",
            params={"uuid": uuid},
            headers=headers,
        )
        if response.status_code == 404:
            return None
        if not response.is_success:
            raise SuSoftAPIError(
                f"/shopping-cart/uuid feilet: HTTP {response.status_code}",
                response.status_code,
                response.text,
            )
        body = response.json()
        if not isinstance(body, dict):
            raise SuSoftAPIError(
                f"Uventet /shopping-cart/uuid-respons: {type(body).__name__}"
            )
        return body

    def list_admin_carts_with_details(
        self,
        date_from: date,
        date_to: date,
        *,
        type_: str = "CART",
        status: str = "",
        source: str = "ANY",
        page_size: int = 100,
        shop_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Two-step hent: liste + detalj per uuid. Detaljen merges inn på raden
        under nøkkelen `_detail`. Carts uten uuid eller med 404-detalj
        beholdes uendret (bare uten `_detail`).
        """
        rows = self.list_admin_carts(
            date_from, date_to,
            type_=type_, status=status, source=source,
            page_size=page_size, shop_id=shop_id,
        )
        for row in rows:
            uuid = row.get("uuid")
            if not uuid:
                continue
            detail: Optional[Dict[str, Any]] = None
            # Foretrekk /admin/order/uuid/{uuid} — denne returnerer alltid
            # full payload med linjer og er samme kilde som vi bygger
            # PUT/promote-payloaden fra. /shopping-cart/uuid har historisk
            # returnert tomme `lines` på enkelte carts.
            try:
                detail = self.get_admin_order_detail(uuid)
            except SuSoftAPIError as e:
                logger.warning(
                    "Klarte ikke hente admin-order-detalj for %s: %s", uuid, e
                )
            if not detail or not detail.get("lines"):
                try:
                    cart_detail = self.get_cart_detail(uuid)
                except SuSoftAPIError as e:
                    logger.warning(
                        "Klarte ikke hente cart-detalj for %s: %s", uuid, e
                    )
                    cart_detail = None
                if cart_detail is not None:
                    detail = cart_detail
            if detail is not None:
                row["_detail"] = detail
        return rows

    # =========================================================================
    # ADMIN-API: full cart-detalj og PUT-tilbake (to-veis sync)
    # Endepunktene under er ikke i den offentlige Swagger-spec'en, men er
    # bekreftet via SuSoft sin admin-webklient (advania.e-susoft.com).
    # =========================================================================

    def get_admin_order_detail(self, uuid: str) -> Optional[Dict[str, Any]]:
        """
        Hent FULL admin-cart-payload via `GET /admin/order/uuid/{uuid}`.

        Denne payloaden inneholder alle felt som trengs for å kunne
        gjøre en `PUT /admin/order/uuid/{uuid}` tilbake (kunde, lines med
        full nested `product`, dato, notater osv.). Bruker admin-host
        (api.susoft.com), ikke 4443-host.
        """
        if not uuid:
            return None
        path = f"/admin/order/uuid/{uuid}"
        response = self._admin_request("GET", path)
        if response.status_code == 404:
            return None
        if not response.is_success:
            raise SuSoftAPIError(
                f"GET {path} feilet: HTTP {response.status_code}",
                response.status_code,
                response.text,
            )
        body = response.json()
        if not isinstance(body, dict):
            raise SuSoftAPIError(
                f"Uventet {path}-respons: {type(body).__name__}"
            )
        return body

    def update_admin_order(
        self,
        uuid: str,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Push en FULL cart-payload tilbake til SuSoft via
        `PUT /admin/order/uuid/{uuid}`.

        Caller MÅ sende en komplett payload (ikke patch). Anbefalt mønster:
        1. Hent fersk admin-detalj via `get_admin_order_detail()`
        2. Patch inn dine endringer (lines, datoer, notater, ...)
        3. Send det tilbake hit.

        Returnerer SuSoft-response (typisk det oppdaterte cart-objektet).
        """
        if not uuid:
            raise SuSoftAPIError("update_admin_order krever uuid")
        if not isinstance(payload, dict):
            raise SuSoftAPIError("update_admin_order krever dict-payload")
        path = f"/admin/order/uuid/{uuid}"
        response = self._admin_request("PUT", path, json_body=payload)
        if not response.is_success:
            raise SuSoftAPIError(
                f"PUT {path} feilet: HTTP {response.status_code} body={response.text[:300]}",
                response.status_code,
                response.text,
            )
        body = response.json() if response.content else {}
        if not isinstance(body, dict):
            # Noen endepunkter returnerer 200 OK uten body — det er ok.
            body = {}
        # Debug: log responsen så vi kan se hva SuSoft faktisk returnerer
        # (er den oppdaterte cart-en, eller bare status?)
        try:
            resp_summary = {
                "keys": sorted(body.keys())[:20] if body else [],
                "lines_count": len(body.get("lines") or []) if body else 0,
                "raw_snippet": (response.text or "")[:200],
            }
            logger.info("PUT %s response: %s", path, resp_summary)
        except Exception:  # noqa: BLE001
            pass
        return body

    # =========================================================================
    # SUSOFT ORDER POLLING (innkommende ordrer FRA SuSoft)
    # =========================================================================

    def list_orders(
        self,
        date_from: date,
        date_to: date,
        shop_id: Optional[str] = None,
        mode: str = "FULL",
    ) -> List[Dict[str, Any]]:
        """
        Hent ordrer fra SuSoft via `GET /order/list`.

        SuSoft filtrerer på `orderDate` (ikke pickup/delivery), så kall denne
        med et bredt vindu og filtrer pickup/delivery klient-side om nødvendig.

        Returnerer en flat liste med ordre-rader (rows[]). Per-shop wrappers
        slås sammen, og hver rad annoteres med `_shopId` / `_shopName` for
        sporbarhet.
        """
        self._ensure_tenant_available()

        # SuSoft krever ISO-datetime: yyyy-MM-dd'T'HH:mm:ss.SSS (kort dato gir HTTP 400)
        params: Dict[str, Any] = {
            "fromDate": date_from.strftime("%Y-%m-%dT00:00:00.000"),
            "toDate": (date_to + timedelta(days=1)).strftime("%Y-%m-%dT00:00:00.000"),
            "mode": mode,
        }
        if shop_id:
            params["shopId"] = shop_id

        query = urlencode(params)
        path = f"/order/list?{query}"

        response = self._request_with_throttle_retry(
            "GET", path, headers=self._get_headers()
        )
        if not response.is_success:
            raise SuSoftAPIError(
                f"Failed to list orders: HTTP {response.status_code}",
                response.status_code,
                response.text,
            )

        body = response.json() or []
        if not isinstance(body, list):
            raise SuSoftAPIError(
                f"Unexpected /order/list response type: {type(body).__name__}"
            )

        flat: List[Dict[str, Any]] = []
        for entry in body:
            if not isinstance(entry, dict):
                continue
            # Format A: shop-wrapper {shopId, shopName, rows: [order, ...]}
            if "rows" in entry and isinstance(entry.get("rows"), list):
                sid = entry.get("shopId")
                sname = entry.get("shopName")
                for row in entry["rows"]:
                    if isinstance(row, dict):
                        row.setdefault("_shopId", sid)
                        row.setdefault("_shopName", sname)
                        flat.append(row)
            else:
                # Format B: flat order-objekt med shopId pa toppniva
                entry.setdefault("_shopId", entry.get("shopId"))
                entry.setdefault("_shopName", entry.get("shopName"))
                flat.append(entry)
        logger.info(
            "SuSoft /order/list %s..%s shop=%s -> %d rader",
            date_from, date_to, shop_id or "*", len(flat),
        )
        return flat
    
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

        # SuSoft tillater å referere eksisterende ordre med ett av:
        # uuid, orderNo eller alternativeId. Per spec er prioritet
        # `orderNo` > `uuid` > `alternativeId`.
        #
        # Prioritet vi bruker:
        #   1) `susoft_order_id` (orderNo) — den ekte ORDER-projeksjonen
        #      i SuSoft. For cart-imports er denne satt etter at
        #      `create_order` har opprettet en ORDER ved siden av cart'en
        #      (admin-cart finnes ikke i :4443/invoice-projeksjonen).
        #   2) Vår lokale `order.id` som alternativeId — `create_order`
        #      registrerer ordrer med denne altId-en, så den treffer
        #      ORDER-projeksjonen.
        #   3) `admin_alt_id` fra cart-payloaden (lang Sxxx-streng) —
        #      brukes kun som siste utvei. Treffer ofte cart-projeksjon
        #      som er linjeløs i :4443/invoice (HTTP 400 "Order has no
        #      lines").
        #   4) `uuid` — samme problem som admin_alt_id for cart-imports.
        order_ref: Dict[str, Any]
        susoft_order_no = getattr(order, "susoft_order_id", None) or getattr(
            order, "susoft_order_no", None
        )
        admin_alt_id = None
        if isinstance(order.susoft_admin_payload, dict):
            admin_alt_id = order.susoft_admin_payload.get("alternativeId")
        if not admin_alt_id and isinstance(order.susoft_raw_payload, dict):
            admin_alt_id = order.susoft_raw_payload.get("alternativeId")

        if susoft_order_no:
            try:
                order_ref = {"orderNo": int(susoft_order_no)}
            except (TypeError, ValueError):
                order_ref = {"orderNo": str(susoft_order_no)}
        elif order.susoft_order_id:
            # Vår lokale id matcher altId vi sendte i create_order
            order_ref = {"alternativeId": str(order.id)}
        elif admin_alt_id:
            order_ref = {"alternativeId": str(admin_alt_id)}
        elif order.susoft_uuid:
            order_ref = {"uuid": order.susoft_uuid}
        else:
            raise SuSoftAPIError(
                "Ordre må være opprettet i SuSoft (mangler både susoft_uuid "
                "og susoft_order_id) før den kan faktureres."
            )

        inv_date = invoiced_date or date.today()
        due_date = inv_date + timedelta(days=due_days)

        payload = {
            "invoicedDate": inv_date.strftime("%Y-%m-%d"),
            "dueDate": due_date.strftime("%Y-%m-%d"),
            "orders": [order_ref],
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

    def _refresh_local_totals_from_susoft(self, order: Order) -> bool:
        """
        Hent SuSoft sin versjon av ordren og oppdater lokale totalfelter
        (`total_amount_excl_vat`, `total_vat`, `total_amount_incl_vat`).

        SuSoft er autoritativ for MVA-beregning og prising etter at ordren
        er sendt. Lokal data kan ha vært beregnet med feil MVA-sats hvis
        produktet manglet `vatPercent` ved opprettelse — dette korrigerer det.

        Endrer ikke ordrelinjer (de beholder lokal `unit_price` / `vat_rate`).
        Returnerer True hvis totaler ble oppdatert, ellers False.
        """
        if not order.id:
            return False
        data: Optional[Dict[str, Any]] = None
        # Kun slå opp via altId hvis ordren faktisk er pushet til SuSoft.
        # Ellers risikerer vi å hente en ukoblet SuSoft-ordre med samme
        # alternativeId fra et annet miljø.
        if order.susoft_order_id:
            try:
                data = self.get_order_by_alt_id(str(order.id))
            except Exception as e:  # nosec
                logger.warning(
                    "Kunne ikke hente SuSoft-ordre %s for total-refresh (altId): %s",
                    order.id, e,
                )
                data = None

        # Fallback for cart-importer (har bare susoft_uuid, ingen susoft_order_id):
        # hent admin-cart-detalj via UUID. Cart-linjer bruker samme felt-navn
        # (netTotal/vatAmount/total) som ordre-linjer.
        if not data:
            uuid = getattr(order, "susoft_uuid", None)
            if uuid:
                try:
                    data = self.get_cart_detail(str(uuid))
                except Exception as e:
                    logger.warning(
                        "Kunne ikke hente SuSoft-cart %s for total-refresh: %s",
                        uuid, e,
                    )
                    data = None
        if not isinstance(data, dict):
            return False

        lines = data.get("lines") or []
        if not isinstance(lines, list) or not lines:
            return False

        from decimal import Decimal as _D

        def _dec(v: Any) -> _D:
            if v is None or v == "":
                return _D("0")
            try:
                return _D(str(v))
            except Exception:
                return _D("0")

        excl = _D("0")
        vat = _D("0")
        incl = _D("0")
        for ln in lines:
            if not isinstance(ln, dict):
                continue
            qty = _dec(ln.get("qty") or ln.get("qtyOrdered") or ln.get("quantity") or "1")

            # SuSoft har to skjemaer som varierer per endepunkt:
            #   admin /cart/{id}        : netTotal, vatAmount, total
            #   /shopping-cart/uuid     : (netTotal mangler), lineTaxAmount, lineTotal,
            #                              priceInclTax (per stk), price (per stk net)
            # Vi prioriterer eksplisitte felt for incl-totalen og MVA, og utleder
            # excl = incl - vat for å være konsistent.
            line_incl = _dec(
                ln.get("total")
                or ln.get("lineTotal")
                or (qty * _dec(ln.get("priceInclTax"))
                    if ln.get("priceInclTax") is not None else None)
            )
            line_vat = _dec(
                ln.get("vatAmount")
                or ln.get("lineTaxAmount")
            )
            line_excl_raw = _dec(ln.get("netTotal"))
            if line_incl == 0 and line_excl_raw == 0:
                # Siste fallback: qty * price (cart-skjema: price er ekskl. mva)
                if ln.get("price") is not None:
                    line_excl_raw = qty * _dec(ln.get("price"))
                    if line_vat == 0 and ln.get("lineTaxPercent") is not None:
                        line_vat = (line_excl_raw * _dec(ln.get("lineTaxPercent")) / _D("100"))
                    line_incl = line_excl_raw + line_vat

            if line_excl_raw != 0:
                line_excl = line_excl_raw
            else:
                line_excl = line_incl - line_vat

            excl += line_excl
            vat += line_vat
            incl += line_incl

        # Kvantiser til 2 desimaler (samme presisjon som DB-kolonner)
        excl = excl.quantize(_D("0.01"))
        vat = vat.quantize(_D("0.01"))
        incl = incl.quantize(_D("0.01"))

        if incl == 0 and excl == 0 and vat == 0:
            return False

        order.total_amount_excl_vat = excl
        order.total_vat = vat
        order.total_amount_incl_vat = incl
        logger.info(
            "Refreshed local totals from SuSoft for order %s: excl=%s vat=%s incl=%s",
            order.id, excl, vat, incl,
        )
        return True

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
            # Re-pull totaler fra SuSoft slik at lokale summer alltid speiler
            # SuSoft sin autoritative MVA-beregning (særlig viktig hvis lokal
            # ordre ble lagret med feil/manglende vat_rate på produktet).
            self._refresh_local_totals_from_susoft(order)
        else:
            # Ny ordre — opprett (idempotens-sjekk gjøres internt)
            susoft_id = self.create_order(order)
            order.susoft_order_id = susoft_id
            order.sync_status = SyncStatus.SYNCED
            if order.status == OrderStatus.CONFIRMED:
                order.status = OrderStatus.READY_FOR_DELIVERY
            # Hent SuSoft sin autoritative versjon av ordren og oppdater
            # lokale totaler (ekskl/MVA/inkl). SuSoft kan ha overstyrt MVA-sats
            # eller priser sammenlignet med våre lokale produktdata.
            self._refresh_local_totals_from_susoft(order)

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
                    # Refresh local totals fra SuSoft sin autoritative versjon
                    self._refresh_local_totals_from_susoft(order)
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
                # Always use the deepest (leaf) category to match what is shown in SuSoft.
                # category5 is the deepest level, walk backwards to find the first that is set.
                for key in ("category5", "category4", "category3", "category2", "category1"):
                    cid = prod.get(key)
                    if not cid:
                        continue
                    cid_str = str(cid)
                    leaf = category_names.get(cid_str)
                    if leaf:
                        return str(leaf)[:100]
                # Fallback: explicit categoryName from SuSoft (take leaf if it is a path)
                name = prod.get("categoryName")
                if name:
                    leaf = str(name).split("/")[-1].strip()
                    return leaf[:100] if leaf else None
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
                        # Aktiv-flagg fra Susoft:
                        #  - Hvis Susoft sier active=false  -> alltid skjul (Susoft er fasit
                        #    for "produktet finnes/er nedlagt"), selv om admin har overstyrt.
                        #  - Hvis Susoft sier active=true   -> respekter lokal overstyring
                        #    (admin kan ha skjult det manuelt for sortimentet).
                        susoft_active = bool(prod_data.get("active", True))
                        if not susoft_active:
                            existing.is_active = False
                            # Nullstill override-flagget slik at hvis Susoft senere
                            # re-aktiverer produktet, blir det automatisk synlig igjen.
                            existing.is_active_overridden = False
                        elif not getattr(existing, "is_active_overridden", False):
                            existing.is_active = True
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
