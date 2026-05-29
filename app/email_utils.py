"""
E-postutsendelse via Resend (https://resend.com).

Brukes for transactional e-post: invitasjoner, glemt passord,
ordrebekreftelser, varsler.

Hvis RESEND_API_KEY mangler, logges e-posten kun til konsoll
(praktisk i utvikling og test).

Miljovariabler:
  RESEND_API_KEY      - krevd for ekte sending (re_...)
  RESEND_FROM_EMAIL   - default: onboarding@resend.dev (kun dev)
  RESEND_FROM_NAME    - default: "Bakeri"
  PUBLIC_BASE_URL     - brukt i lenker i e-post

Dev-fallgruver:
  - Uten verifisert domene MA from vaere onboarding@resend.dev,
    og to MA vaere e-posten Resend-kontoen er registrert med.
  - Verifiser eget domene under https://resend.com/domains for produksjon.
"""
from __future__ import annotations

import logging
import os
import smtplib
import uuid
from email.message import EmailMessage
from email.utils import formataddr, parseaddr
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

RESEND_ENDPOINT = "https://api.resend.com/emails"


def _api_key() -> Optional[str]:
    return os.getenv("RESEND_API_KEY") or None


def _from_address() -> str:
    name = os.getenv("RESEND_FROM_NAME") or "Bakeri"
    email = os.getenv("RESEND_FROM_EMAIL") or "onboarding@resend.dev"
    return f"{name} <{email}>"


def _smtp_host() -> Optional[str]:
    host = (os.getenv("SMTP_HOST") or "").strip()
    return host or None


def _smtp_port() -> int:
    return int(os.getenv("SMTP_PORT") or "587")


def _smtp_user() -> str:
    return (os.getenv("SMTP_USER") or "").strip()


def _smtp_pass() -> str:
    return os.getenv("SMTP_PASS") or ""


def _smtp_from_header() -> str:
    name = os.getenv("RESEND_FROM_NAME") or "Bakeri"
    email = (
        os.getenv("ALERT_FROM_EMAIL")
        or os.getenv("RESEND_FROM_EMAIL")
        or "no-reply@localhost"
    )
    return formataddr((name, email))


def _smtp_from_email() -> str:
    _, address = parseaddr(_smtp_from_header())
    return address or "no-reply@localhost"


def _public_base_url() -> str:
    return (os.getenv("PUBLIC_BASE_URL") or "http://localhost:5173").rstrip("/")


def _send_email_via_smtp(
    recipients: list[str],
    subject: str,
    html: str,
    text: Optional[str] = None,
    reply_to: Optional[str] = None,
) -> bool:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = _smtp_from_header()
    msg["To"] = ", ".join(recipients)
    if reply_to:
        msg["Reply-To"] = reply_to

    msg.set_content(text or "Denne e-posten krever en HTML-kompatibel klient.")
    msg.add_alternative(html, subtype="html")

    try:
        with smtplib.SMTP(_smtp_host(), _smtp_port(), timeout=10) as server:
            smtp_user = _smtp_user()
            if smtp_user:
                server.starttls()
                server.login(smtp_user, _smtp_pass())
            server.send_message(msg, from_addr=_smtp_from_email(), to_addrs=recipients)
        logger.info("E-post sendt via SMTP til=%s emne=%r", recipients, subject)
        return True
    except Exception as e:
        logger.exception("SMTP exception til=%s: %s", recipients, e)
        return False


def _fallback_to_smtp_if_configured(
    recipients: list[str],
    subject: str,
    html: str,
    text: Optional[str] = None,
    reply_to: Optional[str] = None,
) -> bool:
    if not _smtp_host():
        return False

    logger.warning("Faller tilbake til SMTP for transactional e-post til=%s", recipients)
    return _send_email_via_smtp(
        recipients,
        subject,
        html,
        text=text,
        reply_to=reply_to,
    )


def send_email(
    to: str | list[str],
    subject: str,
    html: str,
    text: Optional[str] = None,
    reply_to: Optional[str] = None,
    idempotency_key: Optional[str] = None,
    tags: Optional[list[dict]] = None,
) -> bool:
    """
    Send e-post via Resend. Returnerer True ved suksess.

    Hvis RESEND_API_KEY ikke er satt, logges meldingen kun (dev-modus).
    Kaster aldri exception oppover - feil logges.
    """
    recipients = [to] if isinstance(to, str) else list(to)
    api_key = _api_key()

    if not api_key:
        if _fallback_to_smtp_if_configured(
            recipients,
            subject,
            html,
            text=text,
            reply_to=reply_to,
        ):
            return True
        logger.info(
            "E-POST (dev/no-key) til=%s emne=%r\n%s",
            recipients, subject, text or html,
        )
        return False

    payload: dict = {
        "from": _from_address(),
        "to": recipients,
        "subject": subject,
        "html": html,
    }
    if text:
        payload["text"] = text
    if reply_to:
        payload["reply_to"] = reply_to
    if tags:
        payload["tags"] = tags

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Idempotency-Key": idempotency_key or str(uuid.uuid4()),
    }

    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.post(RESEND_ENDPOINT, json=payload, headers=headers)
        if resp.status_code >= 400:
            logger.error(
                "Resend feilet (status=%d) til=%s: %s",
                resp.status_code, recipients, resp.text[:500],
            )
            if _fallback_to_smtp_if_configured(
                recipients,
                subject,
                html,
                text=text,
                reply_to=reply_to,
            ):
                return True
            return False
        logger.info("E-post sendt til=%s emne=%r", recipients, subject)
        return True
    except Exception as e:
        logger.exception("Resend exception til=%s: %s", recipients, e)
        if _fallback_to_smtp_if_configured(
            recipients,
            subject,
            html,
            text=text,
            reply_to=reply_to,
        ):
            return True
        return False


# =============================================================================
# Hoyere-niva sjablongen for vanlige e-poster
# =============================================================================

def _wrap_html(body: str, brand: str = "Advania Bakeri") -> str:
    return f"""\
<!DOCTYPE html>
<html lang="no">
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
             background:#f5f5f5;padding:24px;color:#111">
  <div style="max-width:560px;margin:0 auto;background:#fff;border-radius:8px;
              padding:32px;box-shadow:0 1px 3px rgba(0,0,0,0.08)">
    <h1 style="font-size:20px;margin:0 0 16px 0;color:#b45309">{brand}</h1>
    {body}
    <hr style="margin-top:32px;border:none;border-top:1px solid #eee">
    <p style="font-size:12px;color:#888;margin-top:16px">
      Denne e-posten er sendt automatisk fra {brand}-systemet.
      Ikke svar pa denne e-posten.
    </p>
  </div>
</body>
</html>
"""


def send_invitation(
    *,
    to_email: str,
    invite_token: str,
    tenant_name: str,
    inviter_name: Optional[str] = None,
) -> bool:
    """Invitasjon til ny bruker (med token-lenke for aa sette passord)."""
    link = f"{_public_base_url()}/aksepter-invitasjon?token={invite_token}"
    inviter = inviter_name or "En administrator"
    body = f"""
      <p>Hei,</p>
      <p>{inviter} har invitert deg til <strong>{tenant_name}</strong> sitt
         ordresystem.</p>
      <p style="margin:24px 0">
        <a href="{link}"
           style="background:#b45309;color:#fff;padding:12px 24px;
                  border-radius:6px;text-decoration:none;display:inline-block">
          Aksepter invitasjon
        </a>
      </p>
      <p style="font-size:13px;color:#555">
        Lenken er gyldig i 7 dager. Hvis knappen ikke virker, lim inn:<br>
        <span style="word-break:break-all">{link}</span>
      </p>
    """
    return send_email(
        to=to_email,
        subject=f"Invitasjon til {tenant_name}",
        html=_wrap_html(body, brand=tenant_name),
        text=f"{inviter} har invitert deg til {tenant_name}. Aksepter her: {link}",
    )


def send_password_reset(
    *,
    to_email: str,
    reset_token: str,
    tenant_name: str = "Bakeri",
) -> bool:
    """Glemt-passord-e-post."""
    link = f"{_public_base_url()}/nullstill-passord?token={reset_token}"
    body = f"""
      <p>Hei,</p>
      <p>Vi mottok en foresporsel om aa nullstille passordet ditt.</p>
      <p style="margin:24px 0">
        <a href="{link}"
           style="background:#b45309;color:#fff;padding:12px 24px;
                  border-radius:6px;text-decoration:none;display:inline-block">
          Nullstill passord
        </a>
      </p>
      <p style="font-size:13px;color:#555">
        Lenken er gyldig i 1 time. Hvis du ikke ba om dette, kan du
        ignorere denne e-posten.
      </p>
    """
    return send_email(
        to=to_email,
        subject=f"Nullstill passord - {tenant_name}",
        html=_wrap_html(body, brand=tenant_name),
        text=f"Nullstill passord her: {link} (gyldig 1 time)",
    )


def send_tenant_welcome(
    *,
    to_email: str,
    tenant_name: str,
    admin_email: str,
    temp_password: Optional[str] = None,
) -> bool:
    """Velkomst-e-post til ny tenant-admin."""
    base = _public_base_url()
    pw_block = ""
    if temp_password:
        pw_block = f"""
          <p>Midlertidig passord (endre umiddelbart etter forste innlogging):</p>
          <p style="font-family:monospace;background:#f5f5f5;padding:8px 12px;
                    border-radius:4px;display:inline-block">{temp_password}</p>
        """
    body = f"""
      <p>Velkommen til <strong>{tenant_name}</strong>!</p>
      <p>Din konto er klar.</p>
      <p>E-post: <strong>{admin_email}</strong></p>
      {pw_block}
      <p style="margin:24px 0">
        <a href="{base}/login"
           style="background:#b45309;color:#fff;padding:12px 24px;
                  border-radius:6px;text-decoration:none;display:inline-block">
          Logg inn
        </a>
      </p>
    """
    return send_email(
        to=to_email,
        subject=f"Velkommen til {tenant_name}",
        html=_wrap_html(body, brand=tenant_name),
    )
