"""Messages to customers (delay notices, delivery codes) – optional providers, in this order:
1. WhatsApp via Twilio – TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_FROM (e.g. whatsapp:+14155238886)
2. WhatsApp Business Cloud API (Meta) – WHATSAPP_TOKEN, WHATSAPP_PHONE_ID
3. Draft – nothing is sent; the text is kept as an SMS draft the admin can see (and send by hand).
Business-initiated WhatsApp messages outside a 24-hour chat window need an approved template on the Cloud API."""
import re

import httpx

from modules.parser import offline, setting


def provider():
    """'twilio_whatsapp', 'whatsapp_cloud' or 'draft'."""
    if offline():
        return "draft"
    if setting("TWILIO_ACCOUNT_SID") and setting("TWILIO_AUTH_TOKEN") and setting("TWILIO_WHATSAPP_FROM"):
        return "twilio_whatsapp"
    if setting("WHATSAPP_TOKEN") and setting("WHATSAPP_PHONE_ID"):
        return "whatsapp_cloud"
    return "draft"


def _digits(phone):
    return re.sub(r"\D", "", str(phone or ""))


def send(phone, text):
    """Send one message. Returns {status: sent | failed | draft, provider, error?}; never raises."""
    name = provider()
    if name == "draft" or not _digits(phone):
        return {"status": "draft", "provider": "draft"}
    try:
        if name == "twilio_whatsapp":
            sid = setting("TWILIO_ACCOUNT_SID")
            reply = httpx.post(f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
                               auth=(sid, setting("TWILIO_AUTH_TOKEN")), timeout=10,
                               data={"From": setting("TWILIO_WHATSAPP_FROM"), "To": f"whatsapp:+{_digits(phone)}",
                                     "Body": text})
        else:
            reply = httpx.post(f"https://graph.facebook.com/v21.0/{setting('WHATSAPP_PHONE_ID')}/messages",
                               headers={"Authorization": f"Bearer {setting('WHATSAPP_TOKEN')}"}, timeout=10,
                               json={"messaging_product": "whatsapp", "to": _digits(phone), "type": "text",
                                     "text": {"body": text}})
        reply.raise_for_status()
        return {"status": "sent", "provider": name}
    except httpx.HTTPError as error:
        return {"status": "failed", "provider": name, "error": str(error)[:120]}


def label(status, provider_name):
    """Short text for the admin: 'Sent · WhatsApp', 'Draft (no provider)', 'Failed · WhatsApp'."""
    if status == "draft" or not status:
        return "Draft (no provider)"
    if status == "demo":
        return "Demo · shown to partner"
    return f"{status.capitalize()} · WhatsApp"
