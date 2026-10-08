"""Send one-time codes by email over SMTP (e.g. Gmail with an app password).

Configured only by secrets / environment variables – never hard-coded:
  SMTP_HOST (e.g. smtp.gmail.com) · SMTP_PORT (587 STARTTLS or 465 SSL, default 587) · SMTP_USER ·
  SMTP_PASSWORD (Gmail: an *app password*) · SMTP_FROM (optional, defaults to SMTP_USER)
Without them DEPORT runs in demo mode and shows the code on screen, labelled DEMO.
"""
import smtplib
import ssl
from email.message import EmailMessage

from modules.parser import setting


def configured():
    return bool(setting("SMTP_HOST") and setting("SMTP_USER") and setting("SMTP_PASSWORD"))


def send_code(to_email, code, purpose):
    """Email the code. Returns True when the SMTP server accepted it."""
    if not configured() or not to_email:
        return False
    message = EmailMessage()
    message["Subject"] = f"DEPORT {'sign-in' if purpose == 'login' else 'password reset'} code: {code}"
    message["From"] = setting("SMTP_FROM") or setting("SMTP_USER")
    message["To"] = to_email
    message.set_content(f"Your DEPORT code is {code}.\nIt expires in 5 minutes. If you didn't ask for it, ignore this email.")
    host, port = setting("SMTP_HOST"), int(setting("SMTP_PORT", 587))
    try:
        if port == 465:
            with smtplib.SMTP_SSL(host, port, context=ssl.create_default_context(), timeout=15) as server:
                server.login(setting("SMTP_USER"), setting("SMTP_PASSWORD"))
                server.send_message(message)
        else:
            with smtplib.SMTP(host, port, timeout=15) as server:
                server.starttls(context=ssl.create_default_context())
                server.login(setting("SMTP_USER"), setting("SMTP_PASSWORD"))
                server.send_message(message)
        return True
    except (OSError, smtplib.SMTPException):
        return False
