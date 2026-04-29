"""
Symmetric encryption helpers for storing tenant secrets at rest.

Bruker Fernet (cryptography) med en nøkkel utledet fra JWT_SECRET_KEY.
Dette er ikke maskinvare-HSM-kvalitet, men hindrer at SuSoft-passord
ligger i klartekst i databasen.
"""
from __future__ import annotations

import base64
import hashlib
import os
from functools import lru_cache
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken


def _derive_key() -> bytes:
    secret = os.getenv("APP_ENCRYPTION_KEY") or os.getenv("JWT_SECRET_KEY")
    if not secret:
        env = os.getenv("APP_ENV", "development").lower()
        if env in ("production", "prod", "staging"):
            raise RuntimeError(
                "APP_ENCRYPTION_KEY (or JWT_SECRET_KEY) is required in production for "
                "encrypting tenant secrets at rest."
            )
        # Dev only: use a documented marker so this can never be confused with
        # a real key. Logged as a warning by the importer.
        import logging
        logging.getLogger(__name__).warning(
            "APP_ENCRYPTION_KEY not set; using insecure dev fallback. "
            "DO NOT USE IN PRODUCTION."
        )
        secret = "dev-fallback-key-not-for-production-use"
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    return Fernet(_derive_key())


def encrypt_secret(plaintext: Optional[str]) -> Optional[str]:
    """Krypter en streng. Returnerer None for None/tom input."""
    if not plaintext:
        return None
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_secret(ciphertext: Optional[str]) -> Optional[str]:
    """Dekrypter en streng. Returnerer None ved feil eller tom input."""
    if not ciphertext:
        return None
    try:
        return _fernet().decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except (InvalidToken, ValueError):
        return None
