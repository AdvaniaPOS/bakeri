"""
Core authentication utilities (NOT HTTP endpoints).

For HTTP endpoints (login, register, refresh osv.), se `app.api.auth`.
Denne modulen er rammeverk-uavhengig og kan brukes fra API, CLI, tester og services.

Provides:
- Password hashing with bcrypt
- JWT token creation and verification
- Token refresh logic
"""
import logging
import os
import secrets
from datetime import datetime, timedelta
from typing import Optional, Tuple

import bcrypt
from jose import JWTError, jwt
from pydantic import BaseModel

_logger = logging.getLogger(__name__)

# =============================================================================
# CONFIGURATION
# =============================================================================

def _load_jwt_secret() -> str:
    """Load JWT secret. Hard fail in production; warn in dev with stable per-process key."""
    key = os.getenv("JWT_SECRET_KEY", "").strip()
    env = os.getenv("APP_ENV", "development").lower()
    if not key:
        if env in ("production", "prod", "staging"):
            raise RuntimeError(
                "JWT_SECRET_KEY environment variable is required in production. "
                "Generate one with: python -c 'import secrets; print(secrets.token_urlsafe(64))'"
            )
        # Dev fallback: stable for the lifetime of this process so refresh works,
        # but logs a clear warning so it's never confused with prod config.
        key = secrets.token_urlsafe(32)
        _logger.warning(
            "JWT_SECRET_KEY not set; using ephemeral dev key. Tokens will be "
            "invalidated on every restart. DO NOT USE IN PRODUCTION."
        )
    elif len(key) < 32:
        raise RuntimeError(
            f"JWT_SECRET_KEY is too short ({len(key)} chars). Use at least 32 characters."
        )
    return key


SECRET_KEY = _load_jwt_secret()
ALGORITHM = "HS256"

# Token expiration times
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7"))


# =============================================================================
# PASSWORD HASHING
# =============================================================================

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain password against a bcrypt hash.
    Uses bcrypt directly to avoid passlib's compatibility issues with bcrypt 5.0+.
    """
    try:
        password_bytes = plain_password.encode("utf-8")
        hashed_bytes = hashed_password.encode("utf-8") if isinstance(hashed_password, str) else hashed_password
        return bcrypt.checkpw(password_bytes, hashed_bytes)
    except Exception:
        return False


def get_password_hash(password: str) -> str:
    """Hash a password using bcrypt directly (passlib has bcrypt 5.0+ incompatibility)."""
    password_bytes = password.encode("utf-8")
    hashed = bcrypt.hashpw(password_bytes, bcrypt.gensalt(rounds=4))
    return hashed.decode("utf-8")


# =============================================================================
# JWT TOKEN MODELS
# =============================================================================

class TokenPayload(BaseModel):
    """JWT token payload structure."""
    sub: str  # User ID
    tenant_id: int
    role: str
    email: str
    exp: datetime
    iat: datetime
    type: str = "access"  # "access" or "refresh"


class TokenPair(BaseModel):
    """Access and refresh token pair."""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds until access token expiry


class TokenData(BaseModel):
    """Extracted token data for request context."""
    user_id: int
    tenant_id: int
    role: str
    email: str


# =============================================================================
# TOKEN CREATION
# =============================================================================

def create_access_token(
    user_id: int,
    tenant_id: int,
    role: str,
    email: str,
    expires_delta: Optional[timedelta] = None
) -> str:
    """
    Create a JWT access token.
    
    Args:
        user_id: The user's database ID
        tenant_id: The tenant's database ID
        role: User's role (SUPER_ADMIN, TENANT_ADMIN, MANAGER, DRIVER, VIEWER)
        email: User's email address
        expires_delta: Optional custom expiration time
    
    Returns:
        Encoded JWT access token
    """
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    
    payload = {
        "sub": str(user_id),
        "tenant_id": tenant_id,
        "role": role,
        "email": email,
        "exp": expire,
        "iat": datetime.utcnow(),
        "type": "access"
    }
    
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def create_refresh_token(
    user_id: int,
    tenant_id: int,
    role: str,
    email: str,
    expires_delta: Optional[timedelta] = None
) -> str:
    """
    Create a JWT refresh token.
    
    Refresh tokens have longer expiration and are used to get new access tokens.
    
    Args:
        user_id: The user's database ID
        tenant_id: The tenant's database ID
        role: User's role
        email: User's email address
        expires_delta: Optional custom expiration time
    
    Returns:
        Encoded JWT refresh token
    """
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    
    payload = {
        "sub": str(user_id),
        "tenant_id": tenant_id,
        "role": role,
        "email": email,
        "exp": expire,
        "iat": datetime.utcnow(),
        "type": "refresh"
    }
    
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def create_token_pair(
    user_id: int,
    tenant_id: int,
    role: str,
    email: str
) -> TokenPair:
    """
    Create both access and refresh tokens.
    
    Returns:
        TokenPair with both tokens and metadata
    """
    access_token = create_access_token(user_id, tenant_id, role, email)
    refresh_token = create_refresh_token(user_id, tenant_id, role, email)
    
    return TokenPair(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60
    )


# =============================================================================
# TOKEN VERIFICATION
# =============================================================================

def decode_token(token: str, expected_type: str = "access") -> Optional[TokenData]:
    """
    Decode and validate a JWT token.
    
    Args:
        token: The JWT token string
        expected_type: Expected token type ("access" or "refresh")
    
    Returns:
        TokenData if valid, None if invalid
    
    Raises:
        JWTError: If token is malformed or expired
    """
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        
        # Validate token type
        token_type = payload.get("type", "access")
        if token_type != expected_type:
            return None
        
        # Extract user data
        user_id = int(payload.get("sub"))
        tenant_id = payload.get("tenant_id")
        role = payload.get("role")
        email = payload.get("email")
        
        # NB: tenant_id kan vaere 0 (SUPER_ADMIN uten tenant), saa
        # bruk eksplisitt None-sjekk istedenfor `not all([...])`.
        if user_id is None or tenant_id is None or not role or not email:
            return None
        
        return TokenData(
            user_id=user_id,
            tenant_id=tenant_id,
            role=role,
            email=email
        )
        
    except (JWTError, ValueError, TypeError):
        return None


def verify_access_token(token: str) -> Optional[TokenData]:
    """Verify an access token and return extracted data."""
    return decode_token(token, expected_type="access")


def verify_refresh_token(token: str) -> Optional[TokenData]:
    """Verify a refresh token and return extracted data."""
    return decode_token(token, expected_type="refresh")


# =============================================================================
# TOKEN REFRESH
# =============================================================================

def refresh_tokens(refresh_token: str) -> Optional[TokenPair]:
    """
    Use a refresh token to get new access and refresh tokens.
    
    Args:
        refresh_token: A valid refresh token
    
    Returns:
        New TokenPair if refresh token is valid, None otherwise
    """
    token_data = verify_refresh_token(refresh_token)
    
    if not token_data:
        return None
    
    # Create new token pair
    return create_token_pair(
        user_id=token_data.user_id,
        tenant_id=token_data.tenant_id,
        role=token_data.role,
        email=token_data.email
    )


# =============================================================================
# API KEY UTILITIES
# =============================================================================

def generate_api_key() -> Tuple[str, str]:
    """
    Generate a new API key pair.
    
    Returns:
        Tuple of (key_prefix, full_key)
        - key_prefix: First 8 chars for display/lookup (e.g., "bkry_abcd")
        - full_key: Complete key to give to user (only shown once)
    """
    # Generate a secure random key
    random_part = secrets.token_urlsafe(32)
    full_key = f"bkry_{random_part}"
    key_prefix = full_key[:12]  # "bkry_" + first 7 chars
    
    return key_prefix, full_key


def hash_api_key(api_key: str) -> str:
    """Hash an API key for storage."""
    return pwd_context.hash(api_key)


def verify_api_key(plain_key: str, hashed_key: str) -> bool:
    """Verify an API key against its hash."""
    return pwd_context.verify(plain_key, hashed_key)


# =============================================================================
# PASSWORD VALIDATION
# =============================================================================

def validate_password_strength(password: str) -> Tuple[bool, str]:
    """
    Validate password meets security requirements.
    
    Requirements:
    - Minimum 8 characters
    - At least one uppercase letter
    - At least one lowercase letter
    - At least one digit
    - At least one special character
    
    Returns:
        Tuple of (is_valid, error_message)
    """
    if len(password) < 8:
        return False, "Password must be at least 8 characters long"
    
    if not any(c.isupper() for c in password):
        return False, "Password must contain at least one uppercase letter"
    
    if not any(c.islower() for c in password):
        return False, "Password must contain at least one lowercase letter"
    
    if not any(c.isdigit() for c in password):
        return False, "Password must contain at least one digit"
    
    special_chars = "!@#$%^&*()_+-=[]{}|;:,.<>?"
    if not any(c in special_chars for c in password):
        return False, f"Password must contain at least one special character ({special_chars})"
    
    return True, ""


# =============================================================================
# INVITATION TOKEN
# =============================================================================

def create_invitation_token(invitation_id: int, email: str, tenant_id: int) -> str:
    """
    Create a token for user invitation emails.
    
    Valid for 7 days.
    """
    expire = datetime.utcnow() + timedelta(days=7)
    
    payload = {
        "sub": str(invitation_id),
        "email": email,
        "tenant_id": tenant_id,
        "exp": expire,
        "iat": datetime.utcnow(),
        "type": "invitation"
    }
    
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def verify_invitation_token(token: str) -> Optional[dict]:
    """
    Verify an invitation token.
    
    Returns:
        Dict with invitation_id, email, tenant_id if valid
    """
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        
        if payload.get("type") != "invitation":
            return None
        
        return {
            "invitation_id": int(payload.get("sub")),
            "email": payload.get("email"),
            "tenant_id": payload.get("tenant_id")
        }
        
    except (JWTError, ValueError, TypeError):
        return None
