"""Who is signed in, and what they may open.

- The browser holds only a random session token (st.session_state, plus a cookie for "Remember
  me"). Every run re-validates it against the database, so deactivated accounts, deactivated
  branches and revoked sessions stop working immediately.
- Role, branch_id and dp_id come ONLY from that validated session – never from widgets or URLs.
- Every page starts with require_role(...) / require_permission(...).
"""
import time

import streamlit as st

from modules import auth

COOKIE = "ripple_session"
SESSION_KEYS = ("authenticated", "token", "user", "role", "user_id", "display_name", "branch_id", "branch_name",
                "dp_id")

SUPER_PAGES = {
    "overview": "views/super/overview.py",
    "branches": "views/super/branches.py",
    "admins": "views/super/admins.py",
    "audit": "views/super/audit.py",
}
BRANCH_PAGES = {
    "command": "views/manager/command_center.py",
    "map": "views/manager/map_ops.py",
    "partners": "views/manager/partners.py",
    "deliveries": "views/manager/deliveries.py",
    "disruptions": "views/manager/disruptions.py",
    "history": "views/manager/history.py",
}
MANAGER_PAGES = BRANCH_PAGES  # the old manager pages are the branch admin pages now
PARTNER_PAGES = {
    "today": "views/partner/today.py",
    "deliveries": "views/partner/my_deliveries.py",
    "route": "views/partner/my_route.py",
    "report": "views/partner/report_issue.py",
    "history": "views/partner/my_history.py",
}


# ---------------------------------------------------------------- session
def _remember(user, token):
    st.session_state.update(authenticated=True, token=token, user=user, role=user["role"], user_id=user["user_id"],
                            display_name=user["display_name"], branch_id=user["branch_id"],
                            branch_name=user.get("branch_name"), dp_id=user.get("dp_id"))


def _forget():
    for key in list(st.session_state.keys()):
        if not key.startswith("_cookie"):
            del st.session_state[key]


def sign_in(user, remember=False):
    """Start a server-side session for an authenticated user."""
    token = auth.create_session(user["user_id"], remember_me=remember)
    _remember(user, token)
    if remember:
        st.session_state["_cookie_set"] = token  # written on the next run (see flush_cookie_ops)
    st.session_state["_welcome"] = f"Welcome, {str(user['display_name']).split()[0]} 👋"


def restore():
    """The signed-in user for this browser session, or None. Re-validated on every run."""
    token = st.session_state.get("token")
    if token:
        user = auth.validate_session(token)
        if user:
            _remember(user, token)
            return user
        _forget()
        st.session_state["_cookie_delete"] = True
        st.session_state["_cookie_rejected"] = True
        return None
    try:
        cookie = st.context.cookies.get(COOKIE)
    except Exception:  # no browser request (e.g. tests)
        cookie = None
    if isinstance(cookie, str) and cookie and not st.session_state.get("_cookie_rejected"):
        user = auth.validate_session(cookie)
        if user:  # "Remember me": back in without signing in again
            _remember(user, cookie)
            return user
        st.session_state["_cookie_rejected"] = True
        st.session_state["_cookie_delete"] = True
    return None


def logout():
    """Revoke the session, delete the cookie, forget everything, back to the sign-in page."""
    auth.revoke_session(st.session_state.get("token"))
    _forget()
    st.session_state["_cookie_delete"] = True
    st.session_state["_cookie_rejected"] = True
    st.query_params.clear()
    st.rerun()


def flush_cookie_ops():
    """Write or delete the Remember-me cookie in the browser (needs a run that is not cut short)."""
    secure = "; Secure" if st.context.url and st.context.url.startswith("https") else ""
    token = st.session_state.pop("_cookie_set", None)
    if token:
        st.html(f"<script>document.cookie = '{COOKIE}={token}; path=/; max-age={auth.REMEMBER_DAYS * 86400}; "
                f"SameSite=Lax{secure}';</script>", unsafe_allow_javascript=True)
    if st.session_state.pop("_cookie_delete", None):
        st.html(f"<script>document.cookie = '{COOKIE}=; path=/; max-age=0; SameSite=Lax{secure}';</script>",
                unsafe_allow_javascript=True)


# ---------------------------------------------------------------- guards
def current_user():
    return st.session_state.get("user") if st.session_state.get("authenticated") else None


def current_role():
    user = current_user()
    return user["role"] if user else None


def _deny():
    st.error("**Access denied** – this page isn't available for your account.", icon=":material/lock:")
    st.stop()


def require_login():
    if not current_user():
        _deny()
    return current_user()


def require_role(*roles):
    user = current_user()
    if not user or user["role"] not in roles:
        _deny()
    return user


def require_permission(code):
    user = require_login()
    if not auth.has_permission(user, code):
        _deny()
    return user


def branch_id():
    """The signed-in admin's or partner's branch – the ONLY source of branch_id for pages."""
    user = require_role("branch_admin", "partner")
    return user["branch_id"]


def dp_id():
    """The signed-in partner's ID – the ONLY source of dp_id for partner pages."""
    return require_role("partner")["dp_id"]


def resend_wait(key, seconds=30):
    """Seconds left before an OTP may be sent again (per sub-view)."""
    sent = st.session_state.get(key)
    return max(0, int(seconds - (time.time() - sent))) if sent else 0
