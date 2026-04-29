"""
FastAPI dependencies for multi-tenant authentication and authorization.

Provides:
- JWT authentication dependencies
- Tenant isolation in database queries
- Role-based access control
- API key authentication for programmatic access
"""
from typing import Annotated, Optional
from datetime import datetime

from fastapi import Depends, HTTPException, status, Header, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from .database import get_db
from .auth import verify_access_token, verify_api_key, TokenData
from .auth_models import User, Tenant, TenantApiKey, UserRole, SubscriptionStatus

# =============================================================================
# SECURITY SCHEMES
# =============================================================================

# Bearer token authentication
bearer_scheme = HTTPBearer(auto_error=False)


# =============================================================================
# AUTHENTICATION DEPENDENCIES
# =============================================================================

async def get_current_user_optional(
    credentials: Annotated[Optional[HTTPAuthorizationCredentials], Depends(bearer_scheme)],
    db: Session = Depends(get_db)
) -> Optional[User]:
    """
    Get current user if authenticated, None otherwise.
    
    Use this for endpoints that can work with or without authentication.
    """
    if not credentials:
        return None
    
    token_data = verify_access_token(credentials.credentials)
    if not token_data:
        return None
    
    user = db.query(User).filter(
        User.id == token_data.user_id,
        User.is_active == True
    ).first()
    
    return user


async def get_current_user(
    credentials: Annotated[Optional[HTTPAuthorizationCredentials], Depends(bearer_scheme)],
    db: Session = Depends(get_db)
) -> User:
    """
    Get current authenticated user.
    
    Raises 401 Unauthorized if no valid authentication.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    if not credentials:
        raise credentials_exception
    
    token_data = verify_access_token(credentials.credentials)
    if not token_data:
        raise credentials_exception
    
    user = db.query(User).filter(
        User.id == token_data.user_id,
        User.is_active == True
    ).first()
    
    if not user:
        raise credentials_exception
    
    # Update last login
    user.last_login_at = datetime.utcnow()
    db.commit()
    
    return user


async def get_current_tenant(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Session = Depends(get_db)
) -> Tenant:
    """
    Get the tenant for the current user.
    
    Validates tenant is active and subscription is valid.
    """
    tenant = db.query(Tenant).filter(
        Tenant.id == current_user.tenant_id,
        Tenant.is_active == True
    ).first()
    
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tenant not found or inactive"
        )
    
    # Check subscription status
    if tenant.subscription_status not in [SubscriptionStatus.ACTIVE, SubscriptionStatus.TRIAL]:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=f"Subscription is {tenant.subscription_status.value}. Please update your subscription."
        )
    
    return tenant


# =============================================================================
# ROLE-BASED ACCESS CONTROL
# =============================================================================

def require_role(*allowed_roles: UserRole):
    """
    Dependency factory for role-based access control.
    
    Usage:
        @router.get("/admin-only")
        async def admin_endpoint(
            user: User = Depends(require_role(UserRole.TENANT_ADMIN, UserRole.SUPER_ADMIN))
        ):
            ...
    """
    async def role_checker(
        current_user: Annotated[User, Depends(get_current_user)]
    ) -> User:
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied. Required roles: {[r.value for r in allowed_roles]}"
            )
        return current_user
    
    return role_checker


# Convenience dependencies for common role checks
RequireSuperAdmin = Depends(require_role(UserRole.SUPER_ADMIN))
RequireTenantAdmin = Depends(require_role(UserRole.SUPER_ADMIN, UserRole.TENANT_ADMIN))
RequireManager = Depends(require_role(UserRole.SUPER_ADMIN, UserRole.TENANT_ADMIN, UserRole.MANAGER))
RequireDriver = Depends(require_role(UserRole.SUPER_ADMIN, UserRole.TENANT_ADMIN, UserRole.MANAGER, UserRole.DRIVER))
RequireViewer = Depends(require_role(UserRole.SUPER_ADMIN, UserRole.TENANT_ADMIN, UserRole.MANAGER, UserRole.DRIVER, UserRole.VIEWER))


# =============================================================================
# API KEY AUTHENTICATION
# =============================================================================

async def get_api_key_user(
    x_api_key: Annotated[Optional[str], Header()] = None,
    db: Session = Depends(get_db)
) -> Optional[User]:
    """
    Authenticate via API key in X-API-Key header.
    
    Returns the user associated with the API key's tenant.
    """
    if not x_api_key:
        return None
    
    # Extract key prefix for lookup (first 12 chars)
    key_prefix = x_api_key[:12] if len(x_api_key) >= 12 else x_api_key
    
    # Find potential matching API keys
    api_keys = db.query(TenantApiKey).filter(
        TenantApiKey.key_prefix == key_prefix,
        TenantApiKey.is_active == True
    ).all()
    
    # Verify the full key against each potential match
    matching_key = None
    for api_key in api_keys:
        if verify_api_key(x_api_key, api_key.key_hash):
            matching_key = api_key
            break
    
    if not matching_key:
        return None
    
    # Check expiration
    if matching_key.expires_at and matching_key.expires_at < datetime.utcnow():
        return None
    
    # Update last used
    matching_key.last_used_at = datetime.utcnow()
    db.commit()
    
    # Return a system user for API key access
    # API keys operate at tenant level, so return the tenant admin
    user = db.query(User).filter(
        User.tenant_id == matching_key.tenant_id,
        User.role == UserRole.TENANT_ADMIN,
        User.is_active == True
    ).first()
    
    return user


async def get_authenticated_user(
    bearer_user: Annotated[Optional[User], Depends(get_current_user_optional)],
    api_key_user: Annotated[Optional[User], Depends(get_api_key_user)]
) -> User:
    """
    Get authenticated user from either Bearer token or API key.
    
    Prefers Bearer token if both are provided.
    """
    user = bearer_user or api_key_user
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    return user


# =============================================================================
# TENANT-SCOPED DATABASE SESSION
# =============================================================================

class TenantScopedSession:
    """
    Database session wrapper that automatically filters queries by tenant.
    
    Usage:
        def get_customers(tenant_db: TenantScopedSession):
            return tenant_db.query(Customer).all()  # Auto-filtered by tenant_id
    """
    def __init__(self, db: Session, tenant_id: int):
        self.db = db
        self.tenant_id = tenant_id
    
    def query(self, model):
        """
        Create a query that's automatically filtered by tenant_id.
        
        Only applies to models that have a tenant_id column.
        """
        base_query = self.db.query(model)
        
        # Check if model has tenant_id
        if hasattr(model, 'tenant_id'):
            return base_query.filter(model.tenant_id == self.tenant_id)
        
        return base_query
    
    def add(self, obj):
        """Add an object, automatically setting tenant_id if applicable."""
        if hasattr(obj, 'tenant_id') and obj.tenant_id is None:
            obj.tenant_id = self.tenant_id
        self.db.add(obj)
    
    def commit(self):
        self.db.commit()
    
    def refresh(self, obj):
        self.db.refresh(obj)
    
    def delete(self, obj):
        self.db.delete(obj)
    
    def rollback(self):
        self.db.rollback()


async def get_tenant_db(
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant)
) -> TenantScopedSession:
    """
    Get a tenant-scoped database session.
    
    All queries through this session are automatically filtered by the
    current user's tenant_id.
    """
    return TenantScopedSession(db, tenant.id)


# =============================================================================
# REQUEST CONTEXT
# =============================================================================

class RequestContext:
    """
    Context object containing current user, tenant, and request info.
    
    Useful for audit logging and permission checks.
    """
    def __init__(
        self,
        user: User,
        tenant: Tenant,
        request: Request,
        db: Session
    ):
        self.user = user
        self.tenant = tenant
        self.request = request
        self.db = db
        self.tenant_db = TenantScopedSession(db, tenant.id)
    
    @property
    def user_id(self) -> int:
        return self.user.id
    
    @property
    def tenant_id(self) -> int:
        return self.tenant.id
    
    @property
    def user_role(self) -> UserRole:
        return self.user.role
    
    @property
    def client_ip(self) -> Optional[str]:
        return self.request.client.host if self.request.client else None
    
    def has_role(self, *roles: UserRole) -> bool:
        """Check if user has any of the specified roles."""
        return self.user.role in roles
    
    def is_admin(self) -> bool:
        """Check if user is a tenant admin or super admin."""
        return self.user.role in [UserRole.SUPER_ADMIN, UserRole.TENANT_ADMIN]
    
    def can_manage_users(self) -> bool:
        """Check if user can manage other users."""
        return self.user.role in [UserRole.SUPER_ADMIN, UserRole.TENANT_ADMIN]


async def get_request_context(
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    tenant: Annotated[Tenant, Depends(get_current_tenant)],
    db: Session = Depends(get_db)
) -> RequestContext:
    """
    Get full request context with user, tenant, and database access.
    """
    return RequestContext(
        user=current_user,
        tenant=tenant,
        request=request,
        db=db
    )


# =============================================================================
# TYPE ALIASES FOR DEPENDENCY INJECTION
# =============================================================================

# Common dependency types for use in endpoint signatures
CurrentUser = Annotated[User, Depends(get_current_user)]
CurrentTenant = Annotated[Tenant, Depends(get_current_tenant)]
TenantDB = Annotated[TenantScopedSession, Depends(get_tenant_db)]
Context = Annotated[RequestContext, Depends(get_request_context)]

# Optional authentication
OptionalUser = Annotated[Optional[User], Depends(get_current_user_optional)]
