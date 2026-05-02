"""
FastAPI authentication endpoints (HTTP-laget).

Wrapper rundt `app.auth` (kjerne-utilities for hashing/JWT) og eksponerer:
- User registration and login
- Token refresh
- Password reset
- User invitation management
"""
from datetime import datetime, timedelta
from typing import Optional

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
    }


# =============================================================================
# REQUEST/RESPONSE SCHEMAS
# =============================================================================

class LoginRequest(BaseModel):
    """Login request with SuSoft login (email or username) and password."""
    email: str = Field(..., min_length=1)
    password: str
    totp_code: Optional[str] = Field(default=None, min_length=6, max_length=8)


class LoginResponse(BaseModel):
    """Login response with tokens and user info."""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: dict
    tenant: dict


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
    """Be om e-post med nullstillings-lenke."""
    email: EmailStr


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
            tenant = local_user.tenant or db.query(Tenant).filter(Tenant.id == local_user.tenant_id).first()
            if not tenant:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Tenant not found")

            # 2FA: hvis aktivert, krev gyldig TOTP-kode
            if local_user.totp_enabled and local_user.totp_secret:
                if not request.totp_code:
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="2FA-kode kreves",
                        headers={"X-2FA-Required": "true"},
                    )
                from ..two_factor import decrypt_totp_secret, verify_totp
                secret = decrypt_totp_secret(local_user.totp_secret)
                if not secret or not verify_totp(secret, request.totp_code):
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Ugyldig 2FA-kode",
                    )

            token_pair = create_token_pair(
                user_id=local_user.id,
                tenant_id=local_user.tenant_id,
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
                tenant=_tenant_to_dict(tenant),
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
    Logout user by invalidating all refresh tokens.
    """
    db.query(RefreshToken).filter(
        RefreshToken.user_id == current_user.id,
        RefreshToken.is_revoked == False
    ).update({"is_revoked": True, "revoked_at": datetime.utcnow()})
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

    email = request.email.lower().strip()
    user = db.query(User).filter(User.email == email).first()

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

    return {"message": "Hvis e-posten finnes i systemet, har vi sendt en lenke for nullstilling."}


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
    db.commit()
    return {"enabled": True}


@router.post("/2fa/disable")
async def two_factor_disable(
    payload: TwoFactorDisableRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Slå av 2FA. Krever passord-bekreftelse."""
    if not current_user.password_hash or current_user.password_hash == "__susoft__":
        raise HTTPException(status_code=400, detail="Ikke tilgjengelig for SuSoft-brukere")
    if not verify_password(payload.password, current_user.password_hash):
        raise HTTPException(status_code=401, detail="Feil passord")
    current_user.totp_enabled = False
    current_user.totp_secret = None
    db.commit()
    return {"enabled": False}


@router.get("/2fa/status")
async def two_factor_status(current_user: User = Depends(get_current_user)):
    """Returner om 2FA er aktivert for innlogget bruker."""
    return {"enabled": bool(current_user.totp_enabled)}
