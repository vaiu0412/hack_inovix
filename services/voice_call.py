"""AI voice calls for order offers – optional. No Streamlit imports.

Provider order:
1. Twilio Voice when TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER and PUBLIC_BASE_URL are set.
   Twilio fetches the call script (TwiML) from our API: POST /twilio/voice, answers come back on /twilio/gather.
2. Exotel / Plivo adapters – stubs for Indian numbers, not implemented yet (they fall back to Demo mode).
3. Demo mode – no call is placed; the partner app shows a simulated call screen with the same keypad choices.

Keys come from environment variables or .streamlit/secrets.toml (see .env.example). Never hard-coded.
"""
import base64
import hashlib
import hmac
from xml.sax.saxutils import escape, quoteattr

import httpx

from modules.parser import offline, setting

TWILIO_KEYS = ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM_NUMBER", "PUBLIC_BASE_URL")
STUB_KEYS = {"exotel": ("EXOTEL_SID", "EXOTEL_TOKEN"), "plivo": ("PLIVO_AUTH_ID", "PLIVO_AUTH_TOKEN")}
YES_WORDS = ("yes", "accept", "ok", "okay", "sure", "sari", "seri", "aam", "haan")
NO_WORDS = ("no", "cannot", "can't", "cant", "busy", "illa", "mudiyadhu", "mudiyathu", "nahi")


def provider():
    """'twilio', 'exotel', 'plivo' (stubs) or 'demo' – the first one whose keys are set."""
    if offline():
        return "demo"
    if all(setting(k) for k in TWILIO_KEYS):
        return "twilio"
    for name, keys in STUB_KEYS.items():
        if all(setting(k) for k in keys):
            return name
    return "demo"


def language():
    """Call language for <Say>/<Gather>, e.g. en-IN (default) or ta-IN."""
    return setting("CALL_LANGUAGE", "en-IN")


def offer_message(name, category, customer, deadline):
    """What the call says."""
    return (f"Hello {name}, this is DEPORT. New urgent delivery: {category} to {customer} by {deadline}. "
            "Press 1 to accept. Press 2 if you cannot.")


def place_call(to_phone, delivery_id, dp_id, message):
    """Ring the partner. Returns {provider, demo, sid, note}; never raises (falls back to Demo mode)."""
    name = provider()
    if name == "twilio":
        try:
            sid = _twilio_call(to_phone, delivery_id, dp_id)
            return {"provider": "twilio", "demo": False, "sid": sid, "note": f"Calling {to_phone} via Twilio"}
        except Exception as error:  # network, wrong number, trial limits …
            return {"provider": "demo", "demo": True, "sid": None,
                    "note": f"Twilio call failed ({str(error)[:80]}) – simulated call in the app"}
    if name in STUB_KEYS:
        return {"provider": "demo", "demo": True, "sid": None,
                "note": f"{name.capitalize()} adapter not ready yet – simulated call in the app"}
    return {"provider": "demo", "demo": True, "sid": None, "note": "Demo mode – simulated call in the app"}


def _base_url():
    return str(setting("PUBLIC_BASE_URL", "")).rstrip("/")


def webhook_url(path, delivery_id, dp_id):
    """Public URL Twilio calls back on, e.g. https://abc.ngrok.app/twilio/gather?delivery_id=D31&dp_id=DP102."""
    return f"{_base_url()}{path}?delivery_id={delivery_id}&dp_id={dp_id}"


def _twilio_call(to_phone, delivery_id, dp_id):
    sid, token = setting("TWILIO_ACCOUNT_SID"), setting("TWILIO_AUTH_TOKEN")
    response = httpx.post(
        f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Calls.json",
        auth=(sid, token),
        data={"To": to_phone, "From": setting("TWILIO_FROM_NUMBER"), "Method": "POST", "Timeout": "25",
              "Url": webhook_url("/twilio/voice", delivery_id, dp_id)},
        timeout=10,
    )
    response.raise_for_status()
    return response.json()["sid"]


# ---------------------------------------------------------------- TwiML
def twiml_offer(message, gather_url):
    """Say the offer and wait for one key (or a spoken yes/no)."""
    lang = quoteattr(language())
    voice = setting("CALL_VOICE")
    voice_attr = f" voice={quoteattr(voice)}" if voice else ""
    return ('<?xml version="1.0" encoding="UTF-8"?><Response>'
            f'<Gather input="dtmf speech" numDigits="1" timeout="8" action={quoteattr(gather_url)} method="POST" '
            f'language={lang} hints="yes, accept, no, cannot">'
            f"<Say language={lang}{voice_attr}>{escape(message)}</Say></Gather>"
            f"<Say language={lang}{voice_attr}>We did not get an answer. We will tell your branch. Goodbye.</Say>"
            "</Response>")


def twiml_say(text, redirect_url=None):
    """Say one thing, then hang up (or go back to the offer)."""
    lang = quoteattr(language())
    tail = f"<Redirect method=\"POST\">{escape(redirect_url)}</Redirect>" if redirect_url else "<Hangup/>"
    return f'<?xml version="1.0" encoding="UTF-8"?><Response><Say language={lang}>{escape(text)}</Say>{tail}</Response>'


def read_answer(digits="", speech=""):
    """'accept' (key 1 or yes), 'decline' (key 2 or no) or None."""
    digits = str(digits or "").strip()
    if digits == "1":
        return "accept"
    if digits == "2":
        return "decline"
    words = str(speech or "").lower().replace(".", " ").replace(",", " ").split()
    if any(w in words for w in NO_WORDS):  # "no I cannot" must not count as yes
        return "decline"
    if any(w in words for w in YES_WORDS):
        return "accept"
    return None


# ---------------------------------------------------------------- webhook security
def signature(url, params, token):
    """Twilio's X-Twilio-Signature: base64(HMAC-SHA1(auth token, full URL + sorted POST name/value pairs))."""
    payload = url + "".join(f"{k}{params[k]}" for k in sorted(params))
    return base64.b64encode(hmac.new(token.encode(), payload.encode(), hashlib.sha1).digest()).decode()


def valid_request(url, params, received):
    """True when the webhook really comes from Twilio (needs TWILIO_AUTH_TOKEN)."""
    token = setting("TWILIO_AUTH_TOKEN")
    if not token or not received:
        return False
    return hmac.compare_digest(signature(url, params, token), received)
