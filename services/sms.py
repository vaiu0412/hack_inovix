"""Text messages for one-time sign-in codes – optional, in this order:

1. Twilio Verify – TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_VERIFY_SID (a Verify "service").
   Twilio makes the code, sends it and checks it; DEPORT never sees the code. Recommended: Verify takes care of
   OTP sender rules in many countries (for India's DLT rules check Twilio's current guidance).
2. Twilio SMS – TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_SMS_FROM (a Twilio number or sender id).
   DEPORT makes the code (only its hash is stored) and Twilio delivers the text.
3. Demo – nothing is sent; the sign-in screen shows the code, labelled DEMO.

Numbers are E.164 (+919000010007). A 10-digit number gets the default country code SMS_DEFAULT_COUNTRY (91).
"""
import re

import httpx

from modules.parser import offline, setting

VERIFY_URL = "https://verify.twilio.com/v2/Services/{sid}/{what}"
MESSAGES_URL = "https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"


def normalize_phone(text):
    """'+91 90000 10007', '09000010007', '9000010007' -> '+919000010007'; None when it isn't a phone number."""
    raw = str(text or "").strip()
    if not raw or not re.fullmatch(r"[+\d\s\-().]{7,24}", raw):
        return None
    digits = re.sub(r"\D", "", raw)
    country = str(setting("SMS_DEFAULT_COUNTRY", "91")).lstrip("+")
    if raw.startswith("+") or raw.startswith("00"):
        digits = digits[2:] if raw.startswith("00") else digits
    elif len(digits) == 11 and digits.startswith("0"):
        digits = country + digits[1:]
    elif len(digits) == 10:
        digits = country + digits
    return f"+{digits}" if 10 <= len(digits) <= 15 else None


def looks_like_phone(text):
    """True for something typed as a phone number (not an email or an ID like DP102)."""
    return normalize_phone(text) is not None


def mask(phone):
    """'+919000010007' -> '+91 ••••• •0007' (for 'code sent to …')."""
    phone = str(phone or "")
    return f"{phone[:3]} ••••• •{phone[-4:]}" if len(phone) >= 8 else "your phone"


def provider():
    """'twilio_verify', 'twilio_sms' or 'demo'."""
    if offline() or not (setting("TWILIO_ACCOUNT_SID") and setting("TWILIO_AUTH_TOKEN")):
        return "demo"
    if setting("TWILIO_VERIFY_SID"):
        return "twilio_verify"
    if setting("TWILIO_SMS_FROM"):
        return "twilio_sms"
    return "demo"


def _auth():
    return setting("TWILIO_ACCOUNT_SID"), setting("TWILIO_AUTH_TOKEN")


def start_verify(phone, channel="sms"):
    """Twilio Verify: send a code to the phone (sms or whatsapp). True when Twilio accepted it."""
    try:
        reply = httpx.post(VERIFY_URL.format(sid=setting("TWILIO_VERIFY_SID"), what="Verifications"), auth=_auth(),
                           data={"To": phone, "Channel": channel}, timeout=15)
        return reply.is_success
    except httpx.HTTPError:
        return False


def check_verify(phone, code):
    """Twilio Verify: True when the code is right (Twilio counts the tries and the expiry)."""
    try:
        reply = httpx.post(VERIFY_URL.format(sid=setting("TWILIO_VERIFY_SID"), what="VerificationCheck"),
                           auth=_auth(), data={"To": phone, "Code": str(code).strip()}, timeout=15)
        return reply.is_success and reply.json().get("status") == "approved"
    except (httpx.HTTPError, ValueError):
        return False


def send_text(phone, text):
    """Twilio SMS: one text. True when Twilio accepted it."""
    try:
        reply = httpx.post(MESSAGES_URL.format(sid=setting("TWILIO_ACCOUNT_SID")), auth=_auth(),
                           data={"From": setting("TWILIO_SMS_FROM"), "To": phone, "Body": text}, timeout=15)
        return reply.is_success
    except httpx.HTTPError:
        return False
