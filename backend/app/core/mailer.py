from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from app.config import get_settings

log = logging.getLogger("app.mailer")

# Usado pelos testes para inspecionar mensagens enviadas.
OUTBOX: list[EmailMessage] = []


def send_email(to: str, subject: str, body: str) -> None:
    s = get_settings()
    msg = EmailMessage()
    msg["From"] = s.smtp_from
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)

    if s.app_env == "test":
        OUTBOX.append(msg)
        return
    if not s.smtp_host:
        if s.app_env == "development":
            # Somente em desenvolvimento e sem SMTP configurado: facilita testes locais.
            log.warning("smtp_not_configured_dev_email", extra={"to": to, "subject": subject, "body": body})
        else:
            log.error("smtp_not_configured", extra={"to": to, "subject": subject})
        return
    try:
        with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=15) as smtp:
            if s.smtp_starttls:
                smtp.starttls()
            if s.smtp_user and s.smtp_password:
                smtp.login(s.smtp_user, s.smtp_password)
            smtp.send_message(msg)
    except Exception:
        log.exception("email_send_failed", extra={"to": to, "subject": subject})
