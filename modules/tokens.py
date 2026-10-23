"""JWT access tokens for the mobile API. No Streamlit.

A token is signed (HS256) with JWT_SECRET – or, when that is not set, a random secret made once and kept in the
settings table, so every process (app, API) shares it and tokens survive restarts. Never hardcoded.
Claims: sub (user id), role, branch, dp, sid (the hash of a server-side session) and exp. The API checks the
signature AND that the session is still valid, so signing out, deactivating a user or switching off a branch stops
a token at once – a JWT alone is never trusted for longer than its session.
"""
import secrets
import time

import jwt

from modules import store
from modules.parser import setting

ALGORITHM = "HS256"
ISSUER = "deport"
ACCESS_MINUTES = 60


def _secret():
    configured = setting("JWT_SECRET")
    if configured:
        return str(configured)
    saved = store.get_setting("jwt_secret")
    if saved:
        return saved
    store.set_setting("jwt_secret", secrets.token_urlsafe(48), "system")  # Demo mode: made once, then shared
    return store.get_setting("jwt_secret")


def issue(user, session_hash, session_expires_at, minutes=ACCESS_MINUTES):
    """A signed access token for a signed-in user; it never outlives the session behind it.
    Returns (token, seconds until it expires)."""
    now = int(time.time())
    expires = int(min(now + minutes * 60, session_expires_at))
    claims = {"iss": ISSUER, "sub": user["user_id"], "role": user["role"], "branch": user.get("branch_id"),
              "dp": user.get("dp_id"), "sid": session_hash, "iat": now, "exp": expires}
    return jwt.encode(claims, _secret(), algorithm=ALGORITHM), max(expires - now, 0)


def read(token):
    """The claims of a valid, unexpired token from this server, or None."""
    try:
        return jwt.decode(token, _secret(), algorithms=[ALGORITHM], issuer=ISSUER,
                          options={"require": ["exp", "sub", "sid"]})
    except jwt.PyJWTError:
        return None


def looks_like_jwt(token):
    """JWTs have three dot-separated parts; the app's session tokens have none."""
    return isinstance(token, str) and token.count(".") == 2
