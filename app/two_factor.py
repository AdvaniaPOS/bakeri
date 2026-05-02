"""
2FA / TOTP-helpers.

TOTP-secrets lagres kryptert (encrypt_secret/decrypt_secret).
"""
from typing import Optional

import pyotp

from .crypto_utils import encrypt_secret, decrypt_secret


def generate_totp_secret() -> str:
    """Generer ny base32-secret."""
    return pyotp.random_base32()


def encrypt_totp_secret(secret: str) -> str:
    """Krypter for lagring."""
    return encrypt_secret(secret) or ""


def decrypt_totp_secret(stored: Optional[str]) -> Optional[str]:
    """Dekrypter fra lagring."""
    return decrypt_secret(stored)


def provisioning_uri(secret: str, account_name: str, issuer: str = "Advania Bakeri") -> str:
    """Bygg otpauth://-URI for Authenticator-app.

    `issuer` vises i autentiserings-appen — bruk tenant-navn for at sluttbruker
    skal kjenne igjen kontoen.
    """
    return pyotp.TOTP(secret).provisioning_uri(name=account_name, issuer_name=issuer)


def verify_totp(secret: str, code: str, valid_window: int = 1) -> bool:
    """Verifiser 6-sifret TOTP-kode."""
    if not secret or not code:
        return False
    try:
        return pyotp.TOTP(secret).verify(code.strip(), valid_window=valid_window)
    except Exception:
        return False
