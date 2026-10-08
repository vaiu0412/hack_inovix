"""DEPORT – Disruption-Aware Logistics Decision Support System (Coimbatore).

Before sign-in only the sign-in page exists. After sign-in the navigation contains ONLY the pages
of the account's role – Super Admin, Branch Admin or Delivery Partner – and every page re-checks it.
The session is re-validated against the database on every run.

Run:  streamlit run app.py
"""
import streamlit as st

from modules import guards, ui
from modules.guards import BRANCH_PAGES as B
from modules.guards import PARTNER_PAGES as P
from modules.guards import SUPER_PAGES as S

ui.setup_store()
user = guards.restore()
role = user["role"] if user else None
ui.setup_page(layout="centered" if role == "partner" else "wide")
guards.flush_cookie_ops()

if user is None:
    st.navigation([st.Page("views/login.py", title="Sign in", icon=":material/login:", default=True)],
                  position="hidden").run()
    st.stop()

if role == "super_admin":
    pages = [
        st.Page(S["overview"], title="Overview", icon=":material/insights:", default=True),
        st.Page(S["branches"], title="Branches", icon=":material/store:"),
        st.Page(S["admins"], title="Branch Admins", icon=":material/admin_panel_settings:"),
        st.Page(S["audit"], title="Audit Log", icon=":material/policy:"),
    ]
elif role == "branch_admin":
    pages = [
        st.Page(B["command"], title="Command Center", icon=":material/space_dashboard:", default=True),
        st.Page(B["map"], title="Map & Operations", icon=":material/map:"),
        st.Page(B["partners"], title="Delivery Partners", icon=":material/groups:"),
        st.Page(B["deliveries"], title="Deliveries", icon=":material/package_2:"),
        st.Page(B["disruptions"], title="Disruptions & AI", icon=":material/psychology:"),
        st.Page(B["history"], title="History", icon=":material/history:"),
    ]
else:
    pages = [
        st.Page(P["today"], title="Today", icon=":material/today:", default=True),
        st.Page(P["deliveries"], title="My Deliveries", icon=":material/package_2:"),
        st.Page(P["route"], title="My Route", icon=":material/route:"),
        st.Page(P["report"], title="Report Issue", icon=":material/campaign:"),
        st.Page(P["history"], title="My History", icon=":material/history:"),
        st.Page(P["notifications"], title="Notifications", icon=":material/notifications:"),
    ]

navigation = st.navigation(pages)
ui.sidebar_user()
if "_welcome" in st.session_state:
    st.toast(st.session_state.pop("_welcome"))
navigation.run()
