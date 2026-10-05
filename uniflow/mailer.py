"""Outgoing email.

Backends (config MAIL_BACKEND):
  smtp    - real email through MAIL_SERVER (Gmail, Outlook, Mailtrap, ...)
  console - the email is printed to the server log (local development without SMTP)
  memory  - the email is appended to app.extensions["mail_outbox"] (tests)
"""
import smtplib
import ssl
from email.message import EmailMessage

from flask import current_app


class MailError(Exception):
    """The email could not be sent."""


def send_mail(to, subject, body, meta=None):
    cfg = current_app.config
    backend = cfg.get("MAIL_BACKEND", "console")

    if backend == "memory":
        current_app.extensions.setdefault("mail_outbox", []).append(
            {"to": to, "subject": subject, "body": body, **(meta or {})})
        return

    if backend == "console":
        print("\n" + "=" * 60
              + "\n EMAIL (console backend - not really sent)"
              + f"\n To: {to}\n Subject: {subject}\n\n{body}\n"
              + "=" * 60 + "\n", flush=True)
        return

    if backend != "smtp":
        raise MailError(f"Unknown MAIL_BACKEND '{backend}'.")
    if not cfg.get("MAIL_SERVER"):
        current_app.logger.error("MAIL_SERVER is not configured; cannot send email to %s", to)
        raise MailError("MAIL_SERVER is not configured.")

    msg = EmailMessage()
    msg["From"] = cfg["MAIL_FROM"]
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)

    host, port = cfg["MAIL_SERVER"], cfg["MAIL_PORT"]
    context = ssl.create_default_context()
    try:
        if cfg.get("MAIL_USE_SSL"):
            smtp = smtplib.SMTP_SSL(host, port, timeout=15, context=context)
        else:
            smtp = smtplib.SMTP(host, port, timeout=15)
        with smtp:
            if not cfg.get("MAIL_USE_SSL") and cfg.get("MAIL_USE_TLS"):
                smtp.starttls(context=context)
            if cfg.get("MAIL_USERNAME"):
                smtp.login(cfg["MAIL_USERNAME"], cfg.get("MAIL_PASSWORD") or "")
            smtp.send_message(msg)
    except (smtplib.SMTPException, OSError) as exc:
        current_app.logger.exception("Sending email to %s failed", to)
        raise MailError(str(exc)) from exc
