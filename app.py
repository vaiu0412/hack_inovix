"""Ripple – disruption-aware delivery operations for Coimbatore.

Before login only the home/sign-in page exists. After login the navigation contains ONLY the
pages of the user's role (manager or delivery partner), and every page re-checks the role.

Run:  streamlit run app.py
"""
import streamlit as st

from modules import guards, ui
from modules.guards import MANAGER_PAGES as M
from modules.guards import PARTNER_PAGES as P

role = guards.current_role()
ui.setup_page(layout="centered" if role == "partner" else "wide")

if role is None:
    st.navigation([st.Page("views/home.py", title="Sign in", icon=":material/login:", default=True)],
                  position="hidden").run()
    st.stop()

if role == "manager":
    pages = [
        st.Page(M["command"], title="Command Center", icon=":material/space_dashboard:",
                default=True),
        st.Page(M["map"], title="Map & Operations", icon=":material/map:"),
        st.Page(M["partners"], title="Delivery Partners", icon=":material/groups:"),
        st.Page(M["deliveries"], title="Deliveries", icon=":material/package_2:"),
        st.Page(M["disruptions"], title="Disruptions & AI", icon=":material/psychology:"),
        st.Page(M["history"], title="History", icon=":material/history:"),
    ]
else:
    pages = [
        st.Page(P["today"], title="Today", icon=":material/today:", default=True),
        st.Page(P["deliveries"], title="My Deliveries", icon=":material/route:"),
        st.Page(P["report"], title="Report Issue", icon=":material/campaign:"),
        st.Page(P["history"], title="My History", icon=":material/history:"),
    ]

navigation = st.navigation(pages)
ui.sidebar_user()
if "_welcome" in st.session_state:
    st.toast(st.session_state.pop("_welcome"))
navigation.run()
