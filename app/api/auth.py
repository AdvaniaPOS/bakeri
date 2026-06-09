"""
FastAPI authentication endpoints (HTTP-laget).

Wrapper rundt `app.auth` (kjerne-utilities for hashing/JWT) og eksponerer:
- User registration and login
- Token refresh
- Password reset
- User invitation management
"""
from datetime import datetime, timedelta
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks, Request
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr, Field

from ..database import get_db
from ..rate_limit import check_login_rate_limit
from ..auth import (
    get_password_hash, 
    verify_password, 
    create_token_pair, 
    refresh_tokens,
    validate_password_strength,
    create_invitation_token,
    verify_invitation_token,
    TokenPair
)
from ..auth_models import (
    User, Tenant, RefreshToken, UserInvitation,
    UserRole, SubscriptionPlan, SubscriptionStatus, InvitationStatus
)
from ..dependencies import (
    get_current_user, get_current_tenant, 
    CurrentUser, CurrentTenant, TenantDB,
    require_role
)

router = APIRouter(prefix="/auth", tags=["Authentication"])


# =============================================================================
# HELPERS
# =============================================================================

def _tenant_to_dict(tenant) -> dict:
    """Bygger tenant-payload for login/register-respons med branding."""
    from ..features import merged_features
    return {
        "id": tenant.id,
        "name": tenant.name,
        "slug": tenant.slug,
        "subscription_plan": tenant.subscription_plan.value if tenant.subscription_plan else None,
        "logo_url": getattr(tenant, "logo_url", None),
        "primary_color": getattr(tenant, "primary_color", None),
        "features_enabled": merged_features(tenant),
        "settings": getattr(tenant, "settings", None) or {},
        # Firmaopplysninger (vises i UI + brukes i PDF-rapporter)
        "legal_name": getattr(tenant, "legal_name", None),
        "org_number": getattr(tenant, "org_number", None),
        "email": getattr(tenant, "email", None),
        "phone": getattr(tenant, "phone", None),
        "street_address": getattr(tenant, "street_address", None),
        "postal_code": getattr(tenant, "postal_code", None),
        "city": getattr(tenant, "city", None),
        "country": getattr(tenant, "country", None),
    }


# =============================================================================
# REQUEST/RESPONSE SCHEMAS
# =============================================================================

class LoginRequest(BaseModel):
    """Login request with SuSoft login (email or username) and password."""
    email: str = Field(..., min_length=1)
    password: str
    # MFA-kode (6-8 siffer/tegn). Brukes for både e-post-engangskode og TOTP
    # fra autentiserings-app. `totp_code` beholdes som alias for
    # bakoverkompatibilitet med eldre frontend-versjoner.
    mfa_code: Optional[str] = Field(default=None, min_length=6, max_length=8)
    totp_code: Optional[str] = Field(default=None, min_length=6, max_length=8)


class LoginResponse(BaseModel):
    """Login response with tokens and user info."""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: dict
    tenant: Optional[dict] = None
    # True dersom brukeren MÅ sette opp 2FA før de får full tilgang
    # (gjelder admin-roller). Frontend skal da vise tvunget oppsett-skjerm.
    must_setup_mfa: bool = False


class RegisterTenantRequest(BaseModel):
    """Request to register a new tenant (bakery)."""
    # Tenant info
    tenant_name: str = Field(..., min_length=2, max_length=255)
    tenant_slug: str = Field(..., min_length=2, max_length=100, pattern=r"^[a-z0-9-]+$")
    
    # First admin user
    admin_email: EmailStr
    admin_password: str = Field(..., min_length=8)
    admin_name: str = Field(..., min_length=2, max_length=255)
    
    # Optional
    phone: Optional[str] = None


class RefreshTokenRequest(BaseModel):
    """Request to refresh access token."""
    refresh_token: str


class InviteUserRequest(BaseModel):
    """Request to invite a new user to the tenant."""
    email: EmailStr
    role: UserRole = UserRole.VIEWER
    name: Optional[str] = None


class AcceptInvitationRequest(BaseModel):
    """Request to accept a user invitation."""
    token: str
    password: str = Field(..., min_length=8)
    name: str = Field(..., min_length=2, max_length=255)


class ChangePasswordRequest(BaseModel):
    """Request to change password."""
    current_password: str
    new_password: str = Field(..., min_length=8)


class ForgotPasswordRequest(BaseModel):
    """Be om nullstillings-lenke med e-post eller brukernavn."""
    email: str = Field(..., min_length=1, max_length=255)


class ResetPasswordRequest(BaseModel):
    """Sett nytt passord vha token fra e-post."""
    token: str = Field(..., min_length=10)
    new_password: str = Field(..., min_length=8)


class UserResponse(BaseModel):
    """User information response."""
    id: int
    email: str
    name: str
    role: str
    tenant_id: int
    is_active: bool
    last_login_at: Optional[datetime] = None


class TenantResponse(BaseModel):
    """Tenant information response."""
    id: int
    name: str
    slug: str
    subscription_plan: str
    subscription_status: str
    is_active: bool
    logo_url: Optional[str] = None
    primary_color: Optional[str] = None
    features_enabled: Optional[dict] = None
    settings: Optional[dict] = None
    # Firmaopplysninger
    legal_name: Optional[str] = None
    org_number: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    street_address: Optional[str] = None
    postal_code: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None


class TenantInfoUpdateRequest(BaseModel):
    """Felter en TENANT_ADMIN/SUPER_ADMIN kan oppdatere paa egen tenant."""
    name: Optional[str] = Field(default=None, min_length=2, max_length=255)
    legal_name: Optional[str] = Field(default=None, max_length=255)
    org_number: Optional[str] = Field(default=None, max_length=50)
    email: Optional[EmailStr] = None
    phone: Optional[str] = Field(default=None, max_length=50)
    street_address: Optional[str] = Field(default=None, max_length=500)
    postal_code: Optional[str] = Field(default=None, max_length=20)
    city: Optional[str] = Field(default=None, max_length=100)
    country: Optional[str] = Field(default=None, max_length=100)


# =============================================================================
# 2FA-HJELPERE
# =============================================================================

# Roller som TVINGES til å ha 2FA aktivert (e-post eller TOTP).
# Andre roller kan velge selv via Innstillinger.
MFA_REQUIRED_ROLES: tuple[UserRole, ...] = (
    UserRole.SUPER_ADMIN,
    UserRole.TENANT_ADMIN,
)


def _user_has_mfa(user: User) -> bool:
    """True hvis brukeren har en aktiv 2FA-metode."""
    method = (user.mfa_method or "none").lower()
    if method == "email":
        return True
    if method == "totp" and bool(user.totp_enabled) and bool(user.totp_secret):
        return True
    # Bakoverkompat: hvis totp_enabled er satt fra før uten mfa_method
    if bool(user.totp_enabled) and bool(user.totp_secret):
        return True
    return False


def _must_setup_mfa(user: User) -> bool:
    """True hvis brukeren MÅ sette opp 2FA før de får full tilgang."""
    if user.role not in MFA_REQUIRED_ROLES:
        return False
    return not _user_has_mfa(user)


def _verify_mfa_for_login(
    db: Session,
    user: User,
    submitted_code: Optional[str],
    *,
    ip_address: Optional[str] = None,
) -> None:
    """Håndter 2FA-trinn av innloggingen for en lokal bruker.

    * Hvis bruker ikke har MFA aktiv → no-op.
    * Hvis MFA er TOTP → krev gyldig kode.
    * Hvis MFA er e-post → hvis ingen kode oppgitt: send kode + 401.
                          Hvis kode oppgitt: verifiser.

    Kaster `HTTPException(401)` med headers `X-2FA-Required: true` og
    `X-2FA-Method: email|totp` når mer info trengs.
    """
    method = (user.mfa_method or "none").lower()
    # Bakoverkompat: hvis ingen metode satt men TOTP er aktiv → behandle som TOTP
    if method == "none" and user.totp_enabled and user.totp_secret:
        method = "totp"

    if method == "none":
        return

    code = (submitted_code or "").strip() or None

    if method == "totp":
        if not code:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="2FA-kode kreves",
                headers={"X-2FA-Required": "true", "X-2FA-Method": "totp"},
            )
        from ..two_factor import decrypt_totp_secret, verify_totp
        secret = decrypt_totp_secret(user.totp_secret)
        if not secret or not verify_totp(secret, code):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Ugyldig 2FA-kode",
                headers={"X-2FA-Method": "totp"},
            )
        return

    if method == "email":
        from ..email_mfa import issue_and_send_code, verify_code as verify_email_code
        if not code:
            # Send ny kode (invaliderer evt. tidligere)
            issue_and_send_code(db, user, ip_address=ip_address)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="2FA-kode sendt på e-post",
                headers={"X-2FA-Required": "true", "X-2FA-Method": "email"},
            )
        if not verify_email_code(db, user, code):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Ugyldig eller utløpt 2FA-kode",
                headers={"X-2FA-Method": "email"},
            )
        return

    # Ukjent metode → fail-closed
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Ukjent 2FA-metode konfigurert",
    )


# =============================================================================
# AUTHENTICATION ENDPOINTS
# =============================================================================

@router.post("/login", response_model=LoginResponse)
async def login(
    request: LoginRequest,
    http_request: Request,
    db: Session = Depends(get_db)
):
    """
    Authenticate user via local password or SuSoft employee credentials.

    First tries local database (for demo/test users).
    Then forwards to SuSoft /user/auth for production users.
    """
    # Brute-force-beskyttelse per IP (10 forsøk / 5 min default).
    check_login_rate_limit(http_request)

    import httpx
    import os

    login_value = request.email.strip()
    user_email_normalized = login_value.lower() if "@" in login_value else f"{login_value.lower()}@bakeri.local"

    # --- Try local database first (demo users, test accounts) ---
    local_user = db.query(User).filter(User.email == user_email_normalized).first()
    if local_user and local_user.password_hash and local_user.password_hash != "__susoft__":
        # Password-protected local account exists
        if verify_password(request.password, local_user.password_hash):
            # SUPER_ADMIN kan logge inn uten tenant (platform-bruker).
            from ..auth_models import UserRole as _UserRole
            is_super_admin = local_user.role == _UserRole.SUPER_ADMIN
            if local_user.tenant_id is not None:
                tenant = local_user.tenant or db.query(Tenant).filter(Tenant.id == local_user.tenant_id).first()
            else:
                tenant = None
            if not tenant and not is_super_admin:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Tenant not found")

            # 2FA: e-post-kode eller TOTP — håndteres av felles helper
            client_ip = http_request.client.host if http_request.client else None
            _verify_mfa_for_login(
                db,
                local_user,
                request.mfa_code or request.totp_code,
                ip_address=client_ip,
            )

            token_pair = create_token_pair(
                user_id=local_user.id,
                tenant_id=local_user.tenant_id if local_user.tenant_id is not None else 0,
                role=local_user.role.value,
                email=local_user.email,
            )
            local_user.last_login_at = datetime.utcnow()
            db.commit()

            return LoginResponse(
                access_token=token_pair.access_token,
                refresh_token=token_pair.refresh_token,
                token_type=token_pair.token_type,
                expires_in=token_pair.expires_in,
                user={
                    "id": local_user.id,
                    "email": local_user.email,
                    "name": local_user.full_name,
                    "role": local_user.role.value,
                },
                tenant=_tenant_to_dict(tenant) if tenant else None,
                must_setup_mfa=_must_setup_mfa(local_user),
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect email or password"
            )

    # --- Authenticate against SuSoft ---
    susoft_base = os.getenv("SUSOFT_BASE_URL", "https://api.susoft.com:4443")
    shop_key = os.getenv("SUSOFT_SHOP_URL_KEY", "")
    susoft_user_email = login_value.lower() if "@" in login_value else f"{login_value.lower()}@susoft.local"

    try:
        async with httpx.AsyncClient(timeout=10, verify=False) as client:
            resp = await client.post(
                f"{susoft_base}/user/auth",
                json={"login": login_value, "password": request.password},
                headers={"X-Shop-Url-Key": shop_key},
            )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Could not reach SuSoft: {exc}"
        )

    try:
        auth_payload = resp.json()
    except ValueError:
        auth_payload = {}

    # SuSoft can return both 401 and 500 for bad credentials. Normalize both to 401.
    upstream_error = str(auth_payload.get("error", ""))
    if resp.status_code != 200 or not auth_payload.get("success"):
        if "Bad credentials" in upstream_error or "User not found" in upstream_error:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect email or password"
            )
        if resp.status_code >= 500:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Authentication service is temporarily unavailable"
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password"
        )

    susoft_token = auth_payload.get("token")
    if not susoft_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service returned an invalid response"
        )

    # --- Fetch employee profile from SuSoft ---
    employee_name = login_value
    try:
        async with httpx.AsyncClient(timeout=10, verify=False) as client:
            me_resp = await client.get(
                f"{susoft_base}/user/me",
                headers={
                    "Authorization": f"Bearer {susoft_token}",
                    "X-Shop-Url-Key": shop_key,
                },
            )
        if me_resp.status_code == 200:
            me = me_resp.json()
            employee_name = me.get("name") or login_value
    except Exception:
        pass  # Profile lookup is best-effort

    # --- Ensure tenant row exists ---
    tenant = db.query(Tenant).filter(Tenant.slug == shop_key).first()
    if not tenant:
        # Bruk shop_key som default navn — kan endres av admin senere
        default_name = shop_key.replace("-", " ").replace("_", " ").title() if shop_key else "Bakeri"
        tenant = Tenant(
            name=default_name,
            slug=shop_key,
            email=susoft_user_email,
            country="NO",
            subscription_plan=SubscriptionPlan.FREE_TRIAL,
            subscription_status=SubscriptionStatus.TRIAL,
            is_active=True,
        )
        db.add(tenant)
        db.flush()

    # --- Ensure local user row exists ---
    user = db.query(User).filter(User.email == susoft_user_email).first()
    if not user:
        user = User(
            email=susoft_user_email,
            password_hash="__susoft__",  # Not used — auth is via SuSoft
            first_name=employee_name.split()[0] if employee_name else "Bruker",
            last_name=" ".join(employee_name.split()[1:]) if len(employee_name.split()) > 1 else "",
            tenant_id=tenant.id,
            role=UserRole.TENANT_ADMIN,
            is_active=True,
            email_verified=True,
        )
        db.add(user)
        db.flush()
    else:
        # Keep name in sync
        parts = employee_name.split()
        user.first_name = parts[0] if parts else user.first_name
        user.last_name = " ".join(parts[1:]) if len(parts) > 1 else user.last_name
        if user.tenant_id is None:
            user.tenant_id = tenant.id

    # Sørg for at brukeren er flushet/oppdatert før MFA-sjekk
    db.flush()

    # 2FA — gjelder også SuSoft-baserte brukere så snart de har valgt metode
    client_ip = http_request.client.host if http_request.client else None
    _verify_mfa_for_login(
        db,
        user,
        request.mfa_code or request.totp_code,
        ip_address=client_ip,
    )

    # --- Create local JWT pair ---
    token_pair = create_token_pair(
        user_id=user.id,
        tenant_id=user.tenant_id,
        role=user.role.value,
        email=user.email,
    )

    user.last_login_at = datetime.utcnow()
    db.commit()

    return LoginResponse(
        access_token=token_pair.access_token,
        refresh_token=token_pair.refresh_token,
        token_type=token_pair.token_type,
        expires_in=token_pair.expires_in,
        user={
            "id": user.id,
            "email": user.email,
            "name": user.full_name,
            "role": user.role.value,
        },
        tenant=_tenant_to_dict(tenant),
        must_setup_mfa=_must_setup_mfa(user),
    )


@router.post("/refresh", response_model=TokenPair)
async def refresh_access_token(
    request: RefreshTokenRequest,
    db: Session = Depends(get_db)
):
    """
    Refresh access token using refresh token.
    
    Returns new access token and refresh token pair.
    """
    new_tokens = refresh_tokens(request.refresh_token)
    
    if not new_tokens:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token"
        )
    
    return new_tokens


@router.post("/logout")
async def logout(
    current_user: CurrentUser,
    db: Session = Depends(get_db)
):
    """
    Logout user by invalidating all refresh tokens AND access tokens.

    Setter `tokens_invalidated_at = now` p\u00e5 brukeren slik at alle JWT-tokens
    utstedt f\u00f8r dette tidspunktet (b\u00e5de access og refresh) avvises av
    `get_current_user`. Dette gir en ekte server-side logout selv om vi har
    stateless JWTs.
    """
    now = datetime.utcnow()
    db.query(RefreshToken).filter(
        RefreshToken.user_id == current_user.id,
        RefreshToken.is_revoked == False
    ).update({"is_revoked": True, "revoked_at": now})

    # Trekk en fersk DB-instans for \u00e5 unng\u00e5 \u00e5 trampe p\u00e5 expunged kopier
    # (f.eks. ved SUPER_ADMIN-impersonering).
    fresh = db.get(User, current_user.id)
    if fresh is not None:
        fresh.tokens_invalidated_at = now

    db.commit()

    return {"message": "Successfully logged out"}


# =============================================================================
# REGISTRATION ENDPOINTS
# =============================================================================

@router.post("/register", response_model=LoginResponse, status_code=status.HTTP_201_CREATED)
async def register_tenant(
    request: RegisterTenantRequest,
    db: Session = Depends(get_db)
):
    """
    Register a new tenant (bakery) with admin user.
    
    Creates:
    - New tenant with trial subscription
    - Admin user for the tenant
    - Returns login tokens
    """
    # Check if slug is available
    existing_tenant = db.query(Tenant).filter(Tenant.slug == request.tenant_slug).first()
    if existing_tenant:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tenant slug already exists"
        )
    
    # Check if email is available
    existing_user = db.query(User).filter(User.email == request.admin_email.lower()).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )
    
    # Validate password strength
    is_valid, error_msg = validate_password_strength(request.admin_password)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_msg
        )
    
    # Create tenant
    tenant = Tenant(
        name=request.tenant_name,
        slug=request.tenant_slug,
        subscription_plan=SubscriptionPlan.TRIAL,
        subscription_status=SubscriptionStatus.TRIAL,
        is_active=True
    )
    db.add(tenant)
    db.flush()  # Get tenant ID
    
    # Create admin user
    user = User(
        tenant_id=tenant.id,
        email=request.admin_email.lower(),
        password_hash=get_password_hash(request.admin_password),
        name=request.admin_name,
        phone=request.phone,
        role=UserRole.TENANT_ADMIN,
        is_active=True,
        email_verified=False  # Should verify email in production
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    db.refresh(tenant)
    
    # Create tokens
    token_pair = create_token_pair(
        user_id=user.id,
        tenant_id=tenant.id,
        role=user.role.value,
        email=user.email
    )
    
    return LoginResponse(
        access_token=token_pair.access_token,
        refresh_token=token_pair.refresh_token,
        token_type=token_pair.token_type,
        expires_in=token_pair.expires_in,
        user={
            "id": user.id,
            "email": user.email,
            "name": user.name,
            "role": user.role.value
        },
        tenant=_tenant_to_dict(tenant)
    )


# =============================================================================
# USER MANAGEMENT ENDPOINTS
# =============================================================================

@router.get("/me", response_model=UserResponse)
async def get_current_user_info(current_user: CurrentUser):
    """Get current user's information."""
    return UserResponse(
        id=current_user.id,
        email=current_user.email,
        name=current_user.name,
        role=current_user.role.value,
        tenant_id=current_user.tenant_id,
        is_active=current_user.is_active,
        last_login_at=current_user.last_login_at
    )


@router.get("/tenant", response_model=TenantResponse)
async def get_current_tenant_info(tenant: CurrentTenant):
    """Get current tenant's information."""
    from ..features import merged_features
    return TenantResponse(
        id=tenant.id,
        name=tenant.name,
        slug=tenant.slug,
        subscription_plan=tenant.subscription_plan.value,
        subscription_status=tenant.subscription_status.value,
        is_active=tenant.is_active,
        logo_url=tenant.logo_url,
        primary_color=tenant.primary_color,
        features_enabled=merged_features(tenant),
        settings=tenant.settings or {},
        legal_name=tenant.legal_name,
        org_number=tenant.org_number,
        email=tenant.email,
        phone=tenant.phone,
        street_address=tenant.street_address,
        postal_code=tenant.postal_code,
        city=tenant.city,
        country=tenant.country,
    )


@router.patch("/tenant", response_model=TenantResponse)
async def update_current_tenant_info(
    payload: TenantInfoUpdateRequest,
    current_user: CurrentUser,
    tenant: CurrentTenant,
    db: Session = Depends(get_db),
):
    """Oppdater firmaopplysninger paa egen tenant (admin only).

    Brukes paa rapporter (navn, org.nr, adresse) og som mottaker for e-post-rapporter.
    """
    if current_user.role not in (UserRole.SUPER_ADMIN, UserRole.TENANT_ADMIN):
        raise HTTPException(status_code=403, detail="Kun administratorer kan endre firmaopplysninger")

    # Sjekk org.nr unik (om endret)
    if payload.org_number is not None and payload.org_number != (tenant.org_number or ""):
        existing = db.query(Tenant).filter(
            Tenant.org_number == payload.org_number,
            Tenant.id != tenant.id,
        ).first()
        if existing:
            raise HTTPException(status_code=409, detail="Org.nr er allerede registrert paa annen tenant")

    for field in ("name", "legal_name", "org_number", "email", "phone",
                  "street_address", "postal_code", "city", "country"):
        value = getattr(payload, field)
        if value is not None:
            setattr(tenant, field, value or None)

    db.commit()
    db.refresh(tenant)
    return TenantResponse(
        id=tenant.id,
        name=tenant.name,
        slug=tenant.slug,
        subscription_plan=tenant.subscription_plan.value,
        subscription_status=tenant.subscription_status.value,
        is_active=tenant.is_active,
        logo_url=tenant.logo_url,
        primary_color=tenant.primary_color,
        features_enabled=tenant.features_enabled or {},
        settings=tenant.settings or {},
        legal_name=tenant.legal_name,
        org_number=tenant.org_number,
        email=tenant.email,
        phone=tenant.phone,
        street_address=tenant.street_address,
        postal_code=tenant.postal_code,
        city=tenant.city,
        country=tenant.country,
    )


@router.post("/change-password")
async def change_password(
    request: ChangePasswordRequest,
    current_user: CurrentUser,
    db: Session = Depends(get_db)
):
    """Change current user's password."""
    # Verify current password
    if not verify_password(request.current_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect"
        )
    
    # Validate new password strength
    is_valid, error_msg = validate_password_strength(request.new_password)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_msg
        )
    
    # Update password
    current_user.password_hash = get_password_hash(request.new_password)
    current_user.password_changed_at = datetime.utcnow()
    
    # Revoke all refresh tokens (force re-login on other devices)
    db.query(RefreshToken).filter(
        RefreshToken.user_id == current_user.id,
        RefreshToken.is_revoked == False
    ).update({"is_revoked": True, "revoked_at": datetime.utcnow()})
    
    db.commit()
    
    return {"message": "Password changed successfully"}


# =============================================================================
# GLEMT PASSORD / NULLSTILL PASSORD
# =============================================================================

@router.post("/forgot-password", status_code=status.HTTP_202_ACCEPTED)
async def forgot_password(
    request: ForgotPasswordRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Be om e-post med lenke for å nullstille passord.

    Returnerer alltid 202 — vi avslører ikke om e-posten finnes eller ikke
    (motvirker enumerering av brukere).
    """
    import secrets as _secrets
    from ..email_utils import send_password_reset

    login_value = request.email.lower().strip()
    candidate_emails = [login_value]
    if "@" not in login_value:
        candidate_emails.extend([
            f"{login_value}@bakeri.local",
            f"{login_value}@susoft.local",
        ])

    user = None
    for candidate in dict.fromkeys(candidate_emails):
        user = db.query(User).filter(User.email == candidate).first()
        if user:
            break

    # Bare reelle, lokale, aktive brukere får e-post.
    # SuSoft-brukere (password_hash == "__susoft__") må nullstille i SuSoft.
    if user and user.is_active and user.password_hash and user.password_hash != "__susoft__":
        token = _secrets.token_urlsafe(32)
        user.password_reset_token = token
        user.password_reset_expires = datetime.utcnow() + timedelta(hours=1)
        db.commit()

        tenant = user.tenant or db.query(Tenant).filter(Tenant.id == user.tenant_id).first()
        background_tasks.add_task(
            send_password_reset,
            to_email=user.email,
            reset_token=token,
            tenant_name=tenant.name if tenant else "Bakeri",
        )

    return {
        "message": (
            "Hvis innloggingen din er lokal, har vi sendt en lenke for nullstilling. "
            "Hvis du logger inn via SuSoft, må passordet endres der eller av administrator."
        )
    }


@router.post("/reset-password")
async def reset_password(
    request: ResetPasswordRequest,
    db: Session = Depends(get_db),
):
    """
    Sett nytt passord ved hjelp av token mottatt på e-post.
    Tokenet er gyldig i 1 time og kan bare brukes én gang.
    """
    user = db.query(User).filter(
        User.password_reset_token == request.token
    ).first()

    if not user or not user.password_reset_expires or user.password_reset_expires < datetime.utcnow():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ugyldig eller utløpt nullstillings-token",
        )

    is_valid, error_msg = validate_password_strength(request.new_password)
    if not is_valid:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=error_msg)

    user.password_hash = get_password_hash(request.new_password)
    user.password_reset_token = None
    user.password_reset_expires = None

    # Logg ut alle eksisterende sesjoner
    db.query(RefreshToken).filter(
        RefreshToken.user_id == user.id,
        RefreshToken.is_revoked == False,
    ).update({"is_revoked": True, "revoked_at": datetime.utcnow()})

    db.commit()
    return {"message": "Passordet er oppdatert. Du kan nå logge inn."}


# =============================================================================
# USER INVITATION ENDPOINTS
# =============================================================================

@router.post("/invite", status_code=status.HTTP_201_CREATED)
async def invite_user(
    request: InviteUserRequest,
    current_user: CurrentUser,
    tenant: CurrentTenant,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """
    Invite a new user to the tenant.
    
    Requires TENANT_ADMIN or higher role.
    """
    # Check permission
    if current_user.role not in [UserRole.SUPER_ADMIN, UserRole.TENANT_ADMIN]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can invite users"
        )
    
    # Check if email already exists
    existing_user = db.query(User).filter(User.email == request.email.lower()).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )
    
    # Check for existing pending invitation
    existing_invitation = db.query(UserInvitation).filter(
        UserInvitation.email == request.email.lower(),
        UserInvitation.tenant_id == tenant.id,
        UserInvitation.status == InvitationStatus.PENDING
    ).first()
    
    if existing_invitation:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invitation already sent to this email"
        )
    
    # Create invitation
    invitation = UserInvitation(
        tenant_id=tenant.id,
        email=request.email.lower(),
        role=request.role,
        invited_by_user_id=current_user.id
    )
    db.add(invitation)
    db.flush()
    
    # Generate invitation token
    token = create_invitation_token(invitation.id, request.email.lower(), tenant.id)
    invitation.token = token
    db.commit()
    
    # Send invitasjons-e-post i bakgrunnen (faller tilbake til logging hvis RESEND_API_KEY mangler)
    from ..email_utils import send_invitation
    background_tasks.add_task(
        send_invitation,
        to_email=request.email.lower(),
        invite_token=token,
        tenant_name=tenant.name,
        inviter_name=current_user.full_name,
    )

    return {
        "message": f"Invitation sent to {request.email}",
        "invitation_id": invitation.id,
    }


@router.post("/accept-invitation", response_model=LoginResponse)
async def accept_invitation(
    request: AcceptInvitationRequest,
    db: Session = Depends(get_db)
):
    """
    Accept a user invitation and create account.
    
    Returns login tokens for the new user.
    """
    # Verify token
    token_data = verify_invitation_token(request.token)
    if not token_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired invitation token"
        )
    
    # Find invitation
    invitation = db.query(UserInvitation).filter(
        UserInvitation.id == token_data["invitation_id"],
        UserInvitation.status == InvitationStatus.PENDING
    ).first()
    
    if not invitation:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invitation not found or already used"
        )
    
    # Validate password
    is_valid, error_msg = validate_password_strength(request.password)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_msg
        )
    
    # Get tenant
    tenant = db.query(Tenant).filter(Tenant.id == invitation.tenant_id).first()
    if not tenant or not tenant.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tenant is no longer active"
        )
    
    # Create user
    user = User(
        tenant_id=invitation.tenant_id,
        email=invitation.email,
        password_hash=get_password_hash(request.password),
        name=request.name,
        role=invitation.role,
        is_active=True,
        email_verified=True  # Verified via invitation email
    )
    db.add(user)
    
    # Update invitation
    invitation.status = InvitationStatus.ACCEPTED
    invitation.accepted_at = datetime.utcnow()
    
    db.commit()
    db.refresh(user)
    
    # Create tokens
    token_pair = create_token_pair(
        user_id=user.id,
        tenant_id=tenant.id,
        role=user.role.value,
        email=user.email
    )
    
    return LoginResponse(
        access_token=token_pair.access_token,
        refresh_token=token_pair.refresh_token,
        token_type=token_pair.token_type,
        expires_in=token_pair.expires_in,
        user={
            "id": user.id,
            "email": user.email,
            "name": user.name,
            "role": user.role.value
        },
        tenant=_tenant_to_dict(tenant)
    )


@router.get("/invitations")
async def list_invitations(
    current_user: CurrentUser,
    tenant: CurrentTenant,
    db: Session = Depends(get_db)
):
    """
    List all invitations for the tenant.
    
    Requires TENANT_ADMIN or higher role.
    """
    if current_user.role not in [UserRole.SUPER_ADMIN, UserRole.TENANT_ADMIN]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can view invitations"
        )
    
    invitations = db.query(UserInvitation).filter(
        UserInvitation.tenant_id == tenant.id
    ).order_by(UserInvitation.created_at.desc()).all()
    
    return [
        {
            "id": inv.id,
            "email": inv.email,
            "role": inv.role.value,
            "status": inv.status.value,
            "created_at": inv.created_at,
            "expires_at": inv.expires_at,
            "accepted_at": inv.accepted_at
        }
        for inv in invitations
    ]


@router.delete("/invitations/{invitation_id}")
async def revoke_invitation(
    invitation_id: int,
    current_user: CurrentUser,
    tenant: CurrentTenant,
    db: Session = Depends(get_db)
):
    """
    Revoke a pending invitation.
    
    Requires TENANT_ADMIN or higher role.
    """
    if current_user.role not in [UserRole.SUPER_ADMIN, UserRole.TENANT_ADMIN]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can revoke invitations"
        )
    
    invitation = db.query(UserInvitation).filter(
        UserInvitation.id == invitation_id,
        UserInvitation.tenant_id == tenant.id,
        UserInvitation.status == InvitationStatus.PENDING
    ).first()
    
    if not invitation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invitation not found"
        )
    
    invitation.status = InvitationStatus.REVOKED
    db.commit()
    
    return {"message": "Invitation revoked"}


# =============================================================================
# USER MANAGEMENT (per tenant) - kun TENANT_ADMIN/SUPER_ADMIN
# =============================================================================


class UserSummary(BaseModel):
    id: int
    email: str
    first_name: str
    last_name: str
    role: str
    is_active: bool
    email_verified: bool
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class UserUpdateRequest(BaseModel):
    role: Optional[UserRole] = None
    is_active: Optional[bool] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None


def _require_tenant_admin(current_user: User) -> None:
    if current_user.role not in (UserRole.SUPER_ADMIN, UserRole.TENANT_ADMIN):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Kun administratorer kan administrere brukere",
        )


@router.get("/users", response_model=List[UserSummary])
async def list_tenant_users(
    current_user: CurrentUser,
    tenant: CurrentTenant,
    db: Session = Depends(get_db),
):
    """List alle brukere i den aktive tenanten. Krever TENANT_ADMIN+."""
    _require_tenant_admin(current_user)
    users = (
        db.query(User)
        .filter(User.tenant_id == tenant.id, User.is_deleted == False)
        .order_by(User.created_at.desc())
        .all()
    )
    return [
        UserSummary(
            id=u.id,
            email=u.email,
            first_name=u.first_name,
            last_name=u.last_name,
            role=u.role.value,
            is_active=u.is_active,
            email_verified=u.email_verified,
            created_at=u.created_at,
        )
        for u in users
    ]


@router.patch("/users/{user_id}", response_model=UserSummary)
async def update_tenant_user(
    user_id: int,
    payload: UserUpdateRequest,
    current_user: CurrentUser,
    tenant: CurrentTenant,
    db: Session = Depends(get_db),
):
    """Endre rolle / aktiv-status / navn for bruker i samme tenant."""
    _require_tenant_admin(current_user)

    target = db.query(User).filter(
        User.id == user_id,
        User.tenant_id == tenant.id,
        User.is_deleted == False,
    ).first()
    if not target:
        raise HTTPException(status_code=404, detail="Bruker ikke funnet")

    if target.id == current_user.id and payload.is_active is False:
        raise HTTPException(status_code=400, detail="Du kan ikke deaktivere deg selv")

    if payload.role is not None:
        # Bare SUPER_ADMIN kan opprette nye SUPER_ADMIN via dette endepunktet
        if payload.role == UserRole.SUPER_ADMIN and current_user.role != UserRole.SUPER_ADMIN:
            raise HTTPException(status_code=403, detail="Kun SUPER_ADMIN kan tildele super-admin-rolle")
        # Tenant-admin kan ikke degradere/promotere super-admin
        if target.role == UserRole.SUPER_ADMIN and current_user.role != UserRole.SUPER_ADMIN:
            raise HTTPException(status_code=403, detail="Kan ikke endre rolle pa super-admin")
        target.role = payload.role
    if payload.is_active is not None:
        target.is_active = payload.is_active
    if payload.first_name is not None:
        target.first_name = payload.first_name.strip() or target.first_name
    if payload.last_name is not None:
        target.last_name = payload.last_name.strip() or target.last_name

    db.commit()
    db.refresh(target)
    return UserSummary(
        id=target.id,
        email=target.email,
        first_name=target.first_name,
        last_name=target.last_name,
        role=target.role.value,
        is_active=target.is_active,
        email_verified=target.email_verified,
        created_at=target.created_at,
    )


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_tenant_user(
    user_id: int,
    current_user: CurrentUser,
    tenant: CurrentTenant,
    db: Session = Depends(get_db),
):
    """
    Deaktiverer (soft-delete) en bruker. Returnerer 204.

    Sletter ogsa alle aktive refresh-tokens slik at brukeren logges ut.
    """
    _require_tenant_admin(current_user)
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Du kan ikke slette deg selv")

    target = db.query(User).filter(
        User.id == user_id,
        User.tenant_id == tenant.id,
        User.is_deleted == False,
    ).first()
    if not target:
        raise HTTPException(status_code=404, detail="Bruker ikke funnet")

    if target.role == UserRole.SUPER_ADMIN and current_user.role != UserRole.SUPER_ADMIN:
        raise HTTPException(status_code=403, detail="Kan ikke slette super-admin")

    target.is_active = False
    target.is_deleted = True
    target.deleted_at = datetime.utcnow()

    db.query(RefreshToken).filter(
        RefreshToken.user_id == target.id,
        RefreshToken.is_revoked == False,
    ).update({"is_revoked": True, "revoked_at": datetime.utcnow()})
    db.commit()
    return None


# =============================================================================
# 2FA / TOTP
# =============================================================================

class TwoFactorEnableRequest(BaseModel):
    code: str = Field(..., min_length=6, max_length=8)


class TwoFactorDisableRequest(BaseModel):
    password: str = Field(..., min_length=1)


@router.post("/2fa/setup")
async def two_factor_setup(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Start 2FA-oppsett: generer ny secret og returner provisioning-URI.
    Secret lagres kryptert, men ikke aktivert (totp_enabled=False)
    før brukeren bekrefter med /2fa/enable.
    """
    from ..two_factor import generate_totp_secret, encrypt_totp_secret, provisioning_uri

    secret = generate_totp_secret()
    current_user.totp_secret = encrypt_totp_secret(secret)
    current_user.totp_enabled = False
    db.commit()

    uri = provisioning_uri(
        secret,
        account_name=current_user.email,
        issuer=(current_user.tenant.name if current_user.tenant else "Advania Bakeri"),
    )
    return {"secret": secret, "otpauth_uri": uri}


@router.post("/2fa/enable")
async def two_factor_enable(
    payload: TwoFactorEnableRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Bekreft 2FA-oppsett ved å sende inn gyldig kode."""
    from ..two_factor import decrypt_totp_secret, verify_totp

    if not current_user.totp_secret:
        raise HTTPException(status_code=400, detail="2FA-oppsett ikke startet")
    secret = decrypt_totp_secret(current_user.totp_secret)
    if not secret or not verify_totp(secret, payload.code):
        raise HTTPException(status_code=400, detail="Ugyldig kode")
    current_user.totp_enabled = True
    current_user.mfa_method = "totp"
    db.commit()
    return {"enabled": True, "mfa_method": "totp"}


@router.post("/2fa/disable")
async def two_factor_disable(
    payload: TwoFactorDisableRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Slå av 2FA. Krever passord-bekreftelse.

    Admin-roller (SUPER_ADMIN/TENANT_ADMIN) kan IKKE slå av 2FA helt — de må
    bytte til en annen metode (e-post eller TOTP).
    """
    if not current_user.password_hash or current_user.password_hash == "__susoft__":
        raise HTTPException(status_code=400, detail="Ikke tilgjengelig for SuSoft-brukere")
    if not verify_password(payload.password, current_user.password_hash):
        raise HTTPException(status_code=401, detail="Feil passord")
    if current_user.role in MFA_REQUIRED_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin-roller må ha 2FA aktivert. Bytt metode i stedet.",
        )
    current_user.totp_enabled = False
    current_user.totp_secret = None
    current_user.mfa_method = "none"
    db.commit()
    return {"enabled": False, "mfa_method": "none"}


@router.get("/2fa/status")
async def two_factor_status(current_user: User = Depends(get_current_user)):
    """Returner 2FA-status og aktiv metode for innlogget bruker."""
    return {
        "enabled": _user_has_mfa(current_user),
        "mfa_method": (current_user.mfa_method or "none"),
        "totp_enabled": bool(current_user.totp_enabled),
        "must_setup": _must_setup_mfa(current_user),
        "required": current_user.role in MFA_REQUIRED_ROLES,
    }


# -----------------------------------------------------------------------------
# 2FA / E-POST (engangskode)
# -----------------------------------------------------------------------------

class EmailMfaSetupVerifyRequest(BaseModel):
    code: str = Field(..., min_length=6, max_length=8)


class EmailMfaResendRequest(BaseModel):
    """Be om ny e-post-kode under pågående innlogging.

    Krever passord for å hindre e-post-spam mot vilkårlige adresser.
    """
    email: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


@router.post("/2fa/email/setup")
async def email_mfa_setup(
    http_request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Start e-post-MFA: send en bekreftelseskode til brukerens e-post.

    Brukeren må kalle `/2fa/email/verify-setup` med koden for å aktivere.
    """
    if not current_user.email:
        raise HTTPException(status_code=400, detail="Brukeren mangler e-postadresse")
    from ..email_mfa import issue_and_send_code
    client_ip = http_request.client.host if http_request.client else None
    issue_and_send_code(
        db, current_user, ip_address=client_ip, purpose="aktivering av 2FA på e-post"
    )
    return {"sent_to": current_user.email}


@router.post("/2fa/email/verify-setup")
async def email_mfa_verify_setup(
    payload: EmailMfaSetupVerifyRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Bekreft e-post-MFA-oppsett ved å oppgi koden som ble sendt."""
    from ..email_mfa import verify_code as verify_email_code
    if not verify_email_code(db, current_user, payload.code):
        raise HTTPException(status_code=400, detail="Ugyldig eller utløpt kode")
    current_user.mfa_method = "email"
    db.commit()
    return {"enabled": True, "mfa_method": "email"}


@router.post("/2fa/email/resend", status_code=status.HTTP_202_ACCEPTED)
async def email_mfa_resend_during_login(
    payload: EmailMfaResendRequest,
    http_request: Request,
    db: Session = Depends(get_db),
):
    """Send ny e-post-kode i forbindelse med pågående innlogging.

    Krever korrekt passord for å hindre at angripere spammer e-post mot
    vilkårlige kontoer. Alltid 202 (samme respons om bruker finnes eller
    ikke) for å unngå konto-enumerering.
    """
    check_login_rate_limit(http_request)

    login_value = payload.email.strip()
    user_email_normalized = (
        login_value.lower() if "@" in login_value else f"{login_value.lower()}@bakeri.local"
    )
    user = db.query(User).filter(User.email == user_email_normalized).first()
    if (
        user
        and user.password_hash
        and user.password_hash != "__susoft__"
        and verify_password(payload.password, user.password_hash)
        and (user.mfa_method or "none") == "email"
    ):
        from ..email_mfa import issue_and_send_code
        client_ip = http_request.client.host if http_request.client else None
        issue_and_send_code(db, user, ip_address=client_ip)
    return {"status": "sent"}

