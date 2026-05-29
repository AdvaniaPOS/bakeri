from __future__ import annotations

from app import email_utils


class _FakeSMTP:
    def __init__(self, host, port, timeout):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.started_tls = False
        self.logged_in = None
        self.sent = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def starttls(self):
        self.started_tls = True

    def login(self, user, password):
        self.logged_in = (user, password)

    def send_message(self, msg, from_addr=None, to_addrs=None):
        self.sent = {
            "subject": msg["Subject"],
            "from": msg["From"],
            "to": list(to_addrs or []),
            "from_addr": from_addr,
            "has_html": any(part.get_content_type() == "text/html" for part in msg.walk()),
        }


def test_send_email_falls_back_to_smtp_when_resend_missing(monkeypatch):
    state = {}

    def _smtp_factory(host, port, timeout):
        state["smtp"] = _FakeSMTP(host, port, timeout)
        return state["smtp"]

    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    monkeypatch.setenv("SMTP_HOST", "smtp.example.test")
    monkeypatch.setenv("SMTP_PORT", "2525")
    monkeypatch.setenv("ALERT_FROM_EMAIL", "alerts@example.test")
    monkeypatch.setenv("RESEND_FROM_NAME", "Lampeland Bakeri")
    monkeypatch.setattr(email_utils.smtplib, "SMTP", _smtp_factory)

    ok = email_utils.send_email(
        to="kunde@example.test",
        subject="Nullstill passord",
        html="<p>Hei</p>",
        text="Hei",
    )

    assert ok is True
    smtp = state["smtp"]
    assert smtp.host == "smtp.example.test"
    assert smtp.port == 2525
    assert smtp.sent is not None
    assert smtp.sent["to"] == ["kunde@example.test"]
    assert smtp.sent["from_addr"] == "alerts@example.test"
    assert smtp.sent["has_html"] is True


def test_send_email_uses_starttls_when_smtp_user_is_configured(monkeypatch):
    state = {}

    def _smtp_factory(host, port, timeout):
        state["smtp"] = _FakeSMTP(host, port, timeout)
        return state["smtp"]

    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    monkeypatch.setenv("SMTP_HOST", "smtp.example.test")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_USER", "mailer")
    monkeypatch.setenv("SMTP_PASS", "secret")
    monkeypatch.setenv("ALERT_FROM_EMAIL", "alerts@example.test")
    monkeypatch.setattr(email_utils.smtplib, "SMTP", _smtp_factory)

    ok = email_utils.send_email(
        to="kunde@example.test",
        subject="Test",
        html="<p>Hei</p>",
    )

    assert ok is True
    smtp = state["smtp"]
    assert smtp.started_tls is True
    assert smtp.logged_in == ("mailer", "secret")
