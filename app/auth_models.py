"""
Multi-tenant authentication and user management.

This module provides:
- Tenant (Organization) model - each bakery chain
- User model with role-based access
- JWT token authentication
- Password hashing
"""
from datetime import datetime, timedelta
from typing import Optional, List
from enum import Enum as PyEnum
import secrets
import hashlib

from sqlalchemy import (
    String, Integer, Boolean, DateTime, Text, ForeignKey, 
    Enum, Index, UniqueConstraint, JSON
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base
from .models import TimestampMixin, SoftDeleteMixin


# =============================================================================
# ENUMS
# =============================================================================

class UserRole(str, PyEnum):
    """User roles with different access levels."""
    SUPER_ADMIN = "super_admin"      # Platform admin - can access all tenants
    TENANT_ADMIN = "tenant_admin"    # Full access to own tenant
    MANAGER = "manager"              # Can manage orders, customers, products
    DRIVER = "driver"                # Can view deliveries, mark as complete
    VIEWER = "viewer"                # Read-only access
    CUSTOMER_PORTAL = "customer_portal"  # Sluttkunde — ser kun egne ordrer (linket via User.customer_id)


class SubscriptionPlan(str, PyEnum):
    """Subscription tiers for tenants."""
    FREE_TRIAL = "free_trial"
    BASIC = "basic"
    PROFESSIONAL = "professional"
    ENTERPRISE = "enterprise"


class SubscriptionStatus(str, PyEnum):
    """Subscription status."""
    ACTIVE = "active"
    TRIAL = "trial"
    PAST_DUE = "past_due"
    CANCELLED = "cancelled"
    SUSPENDED = "suspended"


class InvitationStatus(str, PyEnum):
    """Invitation status."""
    PENDING = "pending"
    ACCEPTED = "accepted"
    REVOKED = "revoked"
    EXPIRED = "expired"


# =============================================================================
# TENANT MODEL (Organization/Bakery Chain)
# =============================================================================

class Tenant(Base, TimestampMixin, SoftDeleteMixin):
    """
    Tenant represents a bakery chain/business using the platform.
    
    All data (customers, products, orders) is scoped to a tenant.
    This enables multi-tenancy where multiple bakeries can use the same system.
    """
    __tablename__ = "tenants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    
    # Unique identifier for the tenant (used in URLs, API keys)
    slug: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False, index=True,
        comment="Unique URL-friendly identifier (e.g., 'lampeland-bakeri')"
    )
    
    # Business info
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    legal_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    org_number: Mapped[Optional[str]] = mapped_column(
        String(50), unique=True, nullable=True,
        comment="Norwegian organization number"
    )
    
    # Contact
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    
    # Address
    street_address: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    postal_code: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    city: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    country: Mapped[str] = mapped_column(String(100), default="Norway", nullable=False)
    
    # Branding
    logo_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    primary_color: Mapped[Optional[str]] = mapped_column(
        String(7), nullable=True, default="#4F46E5",
        comment="Hex color for branding"
    )
    
    # SuSoft integration (per-tenant)
    susoft_api_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    susoft_api_key: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    susoft_company_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    susoft_login: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True,
        comment="SuSoft API innloggingsbruker (epost)"
    )
    susoft_password_encrypted: Mapped[Optional[str]] = mapped_column(
        String(500), nullable=True,
        comment="Fernet-kryptert SuSoft API-passord"
    )
    susoft_shop_url_key: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True,
        comment="X-Shop-Url-Key header verdi (butikknøkkel)"
    )
    susoft_connection_status: Mapped[Optional[str]] = mapped_column(
        String(20), nullable=True,
        comment="Sist kjente status: ok, failed, unknown"
    )
    susoft_last_check_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True,
        comment="Tidspunkt for siste tilkoblingstest"
    )
    susoft_last_error: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True,
        comment="Siste feilmelding fra SuSoft"
    )
    susoft_config_locked: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, server_default="true",
        comment="Hvis True kan kun SUPER_ADMIN endre Susoft-konfig (TENANT_ADMIN ser kun les)"
    )

    # Periodeplan-horisont (auto-fyll av ordrer fra maler)
    last_horizon_check_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True,
        comment="Sist gang ensure-horizon ble kjørt (idempotent per dag)"
    )

    # Subscription
    subscription_plan: Mapped[SubscriptionPlan] = mapped_column(
        Enum(SubscriptionPlan), default=SubscriptionPlan.FREE_TRIAL, nullable=False
    )
    subscription_status: Mapped[SubscriptionStatus] = mapped_column(
        Enum(SubscriptionStatus), default=SubscriptionStatus.TRIAL, nullable=False
    )
    trial_ends_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    subscription_ends_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    
    # Limits (based on subscription)
    max_users: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    max_customers: Mapped[int] = mapped_column(Integer, default=50, nullable=False)
    max_products: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    
    # Settings (JSON for flexibility)
    settings: Mapped[Optional[dict]] = mapped_column(
        JSON, nullable=True, default=dict,
        comment="Tenant-specific settings: timezone, locale, cut-off time, etc."
    )
    
    # Feature flags
    features_enabled: Mapped[Optional[dict]] = mapped_column(
        JSON, nullable=True, default=dict,
        comment="Feature flags: route_optimization, sms_notifications, etc."
    )
    
    # Activation
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    activated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    
    # Relationships
    users: Mapped[List["User"]] = relationship(back_populates="tenant", cascade="all, delete-orphan")
    api_keys: Mapped[List["TenantApiKey"]] = relationship(back_populates="tenant", cascade="all, delete-orphan")
    
    __table_args__ = (
        Index("ix_tenants_active", "is_active", "subscription_status"),
    )
    
    def get_setting(self, key: str, default=None):
        """Get a tenant setting with optional default."""
        if self.settings is None:
            return default
        return self.settings.get(key, default)
    
    def has_feature(self, feature: str) -> bool:
        """Check if a feature is enabled for this tenant."""
        if self.features_enabled is None:
            return False
        return self.features_enabled.get(feature, False)


# =============================================================================
# USER MODEL
# =============================================================================

class User(Base, TimestampMixin, SoftDeleteMixin):
    """
    User account for authentication and authorization.
    
    Users belong to a tenant (except super_admins who can access all).
    Role-based access control determines what they can do.
    """
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    
    # Tenant association (null for super_admin)
    tenant_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("tenants.id", ondelete="CASCADE"), 
        nullable=True, index=True
    )
    
    # Authentication
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    
    # Profile
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    avatar_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    
    # Role
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole), default=UserRole.VIEWER, nullable=False
    )
    
    # Account status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    email_verification_token: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    
    # Password reset
    password_reset_token: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    password_reset_expires: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    
    # Login tracking
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_login_ip: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    failed_login_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked_until: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    
    # Preferences (JSON)
    preferences: Mapped[Optional[dict]] = mapped_column(
        JSON, nullable=True, default=dict,
        comment="User preferences: language, notifications, etc."
    )

    # Customer-portal binding: hvis satt, er denne brukeren en sluttkunde
    # som kun har tilgang til ordrer for den linkede kunden.
    customer_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("customers.id", ondelete="SET NULL"),
        nullable=True, index=True,
        comment="Sluttkunde-link (kun for role=CUSTOMER_PORTAL)."
    )
    
    # Relationships
    tenant: Mapped[Optional["Tenant"]] = relationship(back_populates="users")
    refresh_tokens: Mapped[List["RefreshToken"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    
    __table_args__ = (
        Index("ix_users_tenant_active", "tenant_id", "is_active"),
    )
    
    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"
    
    def can_access_tenant(self, tenant_id: int) -> bool:
        """Check if user can access a specific tenant."""
        if self.role == UserRole.SUPER_ADMIN:
            return True
        return self.tenant_id == tenant_id
    
    def has_permission(self, permission: str) -> bool:
        """Check if user has a specific permission based on role."""
        permissions = {
            UserRole.SUPER_ADMIN: ["*"],  # All permissions
            UserRole.TENANT_ADMIN: [
                "manage_users", "manage_customers", "manage_products", 
                "manage_orders", "manage_templates", "manage_routes",
                "view_reports", "manage_settings"
            ],
            UserRole.MANAGER: [
                "manage_customers", "manage_products", "manage_orders",
                "manage_templates", "view_reports"
            ],
            UserRole.DRIVER: ["view_deliveries", "update_delivery_status"],
            UserRole.VIEWER: ["view_customers", "view_products", "view_orders"],
            UserRole.CUSTOMER_PORTAL: ["view_own_orders", "adjust_own_orders", "manage_own_holidays"],
        }
        
        role_permissions = permissions.get(self.role, [])
        return "*" in role_permissions or permission in role_permissions


# =============================================================================
# AUTHENTICATION TOKENS
# =============================================================================

class RefreshToken(Base, TimestampMixin):
    """
    Refresh token for JWT authentication.
    Allows users to get new access tokens without re-authenticating.
    """
    __tablename__ = "refresh_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    
    token: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    
    # Device/session info
    device_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    
    # Revocation
    is_revoked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    
    # Relationships
    user: Mapped["User"] = relationship(back_populates="refresh_tokens")
    
    __table_args__ = (
        Index("ix_refresh_tokens_user", "user_id", "is_revoked"),
    )
    
    @property
    def is_valid(self) -> bool:
        return not self.is_revoked and self.expires_at > datetime.utcnow()


class TenantApiKey(Base, TimestampMixin):
    """
    API keys for programmatic access to tenant data.
    Used for integrations, webhooks, etc.
    """
    __tablename__ = "tenant_api_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    
    tenant_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # The actual key (hashed for storage)
    key_prefix: Mapped[str] = mapped_column(
        String(10), nullable=False,
        comment="First 8 chars for identification (e.g., 'lbk_a1b2...')"
    )
    key_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    
    # Permissions
    scopes: Mapped[Optional[dict]] = mapped_column(
        JSON, nullable=True, default=list,
        comment="List of allowed scopes: ['read:orders', 'write:orders', ...]"
    )
    
    # Limits
    rate_limit: Mapped[int] = mapped_column(
        Integer, default=1000, nullable=False,
        comment="Max requests per hour"
    )
    
    # Status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    
    # Usage tracking
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    total_requests: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    
    # Who created it
    created_by_user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    
    # Relationships
    tenant: Mapped["Tenant"] = relationship(back_populates="api_keys")
    
    __table_args__ = (
        Index("ix_api_keys_tenant", "tenant_id", "is_active"),
        Index("ix_api_keys_prefix", "key_prefix"),
    )
    
    @classmethod
    def generate_key(cls) -> tuple[str, str]:
        """Generate a new API key. Returns (full_key, hash)."""
        key = f"lbk_{secrets.token_urlsafe(32)}"
        key_hash = hashlib.sha256(key.encode()).hexdigest()
        return key, key_hash


# =============================================================================
# INVITATION
# =============================================================================

class UserInvitation(Base, TimestampMixin):
    """
    Invitation for new users to join a tenant.
    """
    __tablename__ = "user_invitations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    
    tenant_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), default=UserRole.VIEWER, nullable=False)
    
    invitation_token: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    
    invited_by_user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    
    # Status
    is_accepted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    accepted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    accepted_user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    
    __table_args__ = (
        Index("ix_invitations_token", "invitation_token"),
        Index("ix_invitations_email", "email", "tenant_id"),
    )
