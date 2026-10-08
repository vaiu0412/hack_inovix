"""Who is logged in, and which pages they may open.

Every page file starts with require_role("manager") or require_role("partner"). Even if a page
is reached directly, the wrong role (or no login) gets "Access denied" and nothing else runs.
"""
import streamlit as st

SESSION_KEYS = ("authenticated", "role", "user_id", "display_name", "dp_id")

# page files, used for navigation and switch_page
MANAGER_PAGES = {
    "command": "views/manager/command_center.py",
    "map": "views/manager/map_ops.py",
    "partners": "views/manager/partners.py",
    "deliveries": "views/manager/deliveries.py",
    "disruptions": "views/manager/disruptions.py",
    "history": "views/manager/history.py",
}
PARTNER_PAGES = {
    "today": "views/partner/today.py",
    "deliveries": "views/partner/my_deliveries.py",
    "report": "views/partner/report_issue.py",
    "history": "views/partner/my_history.py",
}


def sign_in(user):
    st.session_state.update(authenticated=True, role=user["role"], user_id=user["user_id"],
                            display_name=user["display_name"], dp_id=user.get("dp_id"))
    first = str(user["display_name"]).split()[0]
    st.session_state["_welcome"] = f"Welcome, {first} 👋"


def logout():
    """Forget everything about this browser session and go back to the home page."""
    st.session_state.clear()
    st.query_params.clear()
    st.rerun()


def is_authenticated():
    return bool(st.session_state.get("authenticated")) and st.session_state.get("role") in ("manager", "partner")


def current_role():
    return st.session_state.get("role") if is_authenticated() else None


def require_role(role):
    """Stop the page unless the logged-in user has this role."""
    if current_role() != role:
        st.error("Access denied", icon=":material/lock:")
        st.stop()


def dp_id():
    """The logged-in partner's ID – the ONLY source of dp_id for partner pages."""
    require_role("partner")
    return st.session_state["dp_id"]
