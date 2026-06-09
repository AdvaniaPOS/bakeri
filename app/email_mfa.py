"""
E-post-basert 2FA: utstedelse, sending og verifikasjon av engangskoder.

Designprinsipper:
* Koden lagres ALDRI i klartekst — kun SHA256-hash i `email_mfa_codes`.
* Hver ny kode invaliderer alle tidligere ubrukte koder for brukeren
  (forhindrer kode-overflod hvis bruker spammer "send på nytt").
* Maks 5 verifikasjons-forsøk per kode. Etter det må ny kode utstedes.
* Kode utløper etter `EMAIL_MFA_TTL_SECONDS` (default 600 = 10 min).
* Kode-lengde er 6 siffer (lett å skrive inn på mobil).
* Konstant-tids sammenligning ved verifisering (`hmac.compare_digest`).
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from .auth_models import EmailMfaCode, User
from .email_utils import send_email

logger = logging.getLogger(__name__)


def _ttl_seconds() -> int:
    try:
        return int(os.getenv("EMAIL_MFA_TTL_SECONDS", "600"))
    except ValueError:
        return 600


def _max_attempts() -> int:
    try:
        return int(os.getenv("EMAIL_MFA_MAX_ATTEMPTS", "5"))
    except ValueError:
        return 5


def _hash_code(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def _generate_code() -> str:
    """Generer 6-sifret kode med kryptografisk sterk RNG."""
    # secrets.randbelow er uniform i [0, n)
    return f"{secrets.randbelow(1_000_000):06d}"


def _invalidate_active_codes(db: Session, user_id: int) -> None:
    """Marker alle ubrukte/aktive koder for bruker som brukt (= ugyldige)."""
    now = datetime.utcnow()
    db.query(EmailMfaCode).filter(
        EmailMfaCode.user_id == user_id,
        EmailMfaCode.used_at.is_(None),
    ).update({"used_at": now}, synchronize_session=False)


def issue_and_send_code(
    db: Session,
    user: User,
    *,
    ip_address: Optional[str] = None,
    purpose: str = "innlogging",
) -> bool:
    """Generer ny kode, lagre hash, og send via e-post. Commit gjøres her.

    Returnerer True hvis e-posten ble sendt (eller logget i dev-modus).
    """
    # 1) Invalider eksisterende aktive koder
    _invalidate_active_codes(db, user.id)

    # 2) Generer + lagre
    code = _generate_code()
    row = EmailMfaCode(
        user_id=user.id,
        code_hash=_hash_code(code),
        expires_at=datetime.utcnow() + timedelta(seconds=_ttl_seconds()),
        attempts=0,
        ip_address=ip_address,
    )
    db.add(row)
    db.commit()

    # 3) Send e-post
    ttl_min = max(1, _ttl_seconds() // 60)
    subject = f"Innloggingskode: {code}"
    text = (
        f"Hei {user.first_name or ''},\n\n"
        f"Din engangskode for {purpose} er: {code}\n\n"
        f"Koden er gyldig i {ttl_min} minutter.\n\n"
        "Hvis du ikke ba om denne koden, ignorer denne e-posten og endre passordet ditt.\n\n"
        "— Advania Bakeri"
    )
    html = f"""
    <div style="font-family: -apple-system, Segoe UI, Roboto, sans-serif; max-width: 480px; margin: auto;">
      <h2 style="color: #1f2937;">Din engangskode</h2>
      <p>Hei {user.first_name or ''},</p>
      <p>Din kode for {purpose}:</p>
      <p style="font-size: 32px; letter-spacing: 8px; font-weight: 700;
                background: #f3f4f6; padding: 16px 24px; border-radius: 8px;
                text-align: center; color: #111827;">{code}</p>
      <p style="color: #6b7280;">Koden er gyldig i {ttl_min} minutter.</p>
      <p style="color: #6b7280; font-size: 13px;">
        Hvis du ikke ba om denne koden, ignorer denne e-posten og bytt
        passord umiddelbart.
      </p>
    </div>
    """.strip()

    try:
        sent = send_email(to=user.email, subject=subject, html=html, text=text)
        if not sent:
            logger.info("email_mfa: kode logget til konsoll (ingen RESEND_API_KEY)")
        return True
    except Exception as exc:  # pragma: no cover
        logger.error("email_mfa: kunne ikke sende e-post: %s", exc, exc_info=True)
        return False


def verify_code(db: Session, user: User, code: str) -> bool:
    """Verifiser engangskode for bruker. Inkrementerer forsøk; markerer brukt
    ved suksess. Returnerer True hvis gyldig.
    """
    if not code or not code.strip().isdigit():
        return False
    code = code.strip()

    now = datetime.utcnow()
    # Hent siste aktive kode for brukeren
    row: Optional[EmailMfaCode] = (
        db.query(EmailMfaCode)
        .filter(
            EmailMfaCode.user_id == user.id,
            EmailMfaCode.used_at.is_(None),
            EmailMfaCode.expires_at > now,
        )
        .order_by(EmailMfaCode.id.desc())
        .first()
    )
    if row is None:
        return False

    # Inkrementer forsøk uavhengig av resultat
    row.attempts = (row.attempts or 0) + 1
    if row.attempts > _max_attempts():
        row.used_at = now
        db.commit()
        return False

    expected = _hash_code(code)
    ok = hmac.compare_digest(expected, row.code_hash)
    if ok:
        row.used_at = now
    db.commit()
    return ok
