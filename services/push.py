"""Push notifications to the partner's phone – optional. Firebase Cloud Messaging (HTTP v1):

    FCM_PROJECT_ID         your Firebase project id
    FCM_SERVICE_ACCOUNT    the service account key: the JSON itself, or the path to the .json file

Used at escalation level 0: when an order is offered and the partner has a phone registered (POST /me/devices),
a high-priority push goes out right after the database commit. Without the keys (or without a phone) nothing is
sent and nothing changes – the in-app ring, call and admin alert still follow (Demo mode).
"""
import json
import time
from pathlib import Path

import httpx
import jwt

from modules import store
from modules.parser import offline, setting

SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
_token = {"value": None, "expires": 0.0}


def configured():
    """True when the Firebase keys are set (and the app is not offline)."""
    return not offline() and bool(setting("FCM_PROJECT_ID") and setting("FCM_SERVICE_ACCOUNT"))


def _account():
    raw = str(setting("FCM_SERVICE_ACCOUNT") or "").strip()
    if raw.startswith("{"):
        return json.loads(raw)
    return json.loads(Path(raw).read_text(encoding="utf-8"))


def _access_token():
    """A short-lived Google OAuth token from the service account (signed JWT -> token), cached until it ends."""
    if _token["value"] and _token["expires"] > time.time() + 60:
        return _token["value"]
    account = _account()
    now = int(time.time())
    assertion = jwt.encode({"iss": account["client_email"], "scope": SCOPE, "aud": account["token_uri"],
                            "iat": now, "exp": now + 3600}, account["private_key"], algorithm="RS256")
    reply = httpx.post(account["token_uri"], timeout=10,
                       data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": assertion})
    reply.raise_for_status()
    body = reply.json()
    _token.update(value=body["access_token"], expires=now + int(body.get("expires_in", 3600)))
    return _token["value"]


def send(token, title, body, data=None):
    """One push. Returns 'sent', 'invalid' (the phone's token is gone – forget it) or 'failed'."""
    message = {"message": {"token": token, "notification": {"title": title, "body": body},
                           "data": {k: str(v) for k, v in (data or {}).items()},
                           "android": {"priority": "high", "notification": {"channel_id": "offers"}}}}
    try:
        reply = httpx.post(f"https://fcm.googleapis.com/v1/projects/{setting('FCM_PROJECT_ID')}/messages:send",
                           headers={"Authorization": f"Bearer {_access_token()}"}, json=message, timeout=10)
    except (httpx.HTTPError, ValueError, KeyError, OSError):
        return "failed"
    if reply.status_code == 404 or (reply.status_code == 400 and "UNREGISTERED" in reply.text):
        return "invalid"
    return "sent" if reply.is_success else "failed"


def offer_sent(dp_id, delivery_id, branch_id):
    """Escalation level 0: tell the partner's phones about a new order offer. Returns how many got it."""
    if not configured():
        return 0
    tokens = store.device_tokens(dp_id)
    if not tokens:
        return 0
    delivered = 0
    for token in tokens:
        result = send(token, "New order", f"{delivery_id}: accept or say you can't take it.",
                      {"type": "offer", "delivery_id": delivery_id})
        if result == "invalid":
            store.remove_device(token)
        delivered += result == "sent"
    from modules import escalation

    escalation.log_step(delivery_id, dp_id, 0, "push",
                        f"Push sent to {delivered} phone(s)" if delivered else "Push failed", branch_id)
    return delivered
