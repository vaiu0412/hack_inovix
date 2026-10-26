"""DEPORT – Disruption-Aware Logistics Decision Support System (Coimbatore).

Before sign-in only the sign-in page exists. After sign-in the navigation contains ONLY the pages
of the account's role – Super Admin, Branch Admin or Delivery Partner – and every page re-checks it.
The session is re-validated against the database on every run.

Run:  streamlit run app.py
"""
from pathlib import Path

import streamlit as st

from modules import escalation_ui, guards, i18n, live_ui, track_ui, ui
from modules.guards import BRANCH_PAGES as B
from modules.guards import CUSTOMER_PAGES as C
from modules.guards import PARTNER_PAGES as P
from modules.guards import SUPER_PAGES as S

ui.setup_store()
if track_ui.requested():  # a customer's tracking link: public, no sign-in, nothing else of the app
    track_ui.run()
    st.stop()
user = guards.restore()
role = user["role"] if user else None
ui.setup_page(layout="centered" if role in ("partner", "customer") else "wide", role=role)
guards.flush_cookie_ops()

def _to_sign_in():
    st.switch_page("views/login.py")


if user is None:
    # the admin console lives at /console (file stem = URL path); the public page never links to it.
    # Links to signed-in pages (e.g. after signing out on /map_ops) go to the sign-in page, not "Page not found".
    known = {Path(path).stem for path in (*S.values(), *B.values(), *P.values(), *C.values())}
    st.navigation([st.Page("views/login.py", title="Sign in", icon=":material/login:", default=True),
                   st.Page("views/console.py", title="Console", icon=":material/lock:")]
                  + [st.Page(_to_sign_in, title="Sign in", url_path=stem) for stem in sorted(known)],
                  position="hidden").run()
    st.stop()

if role == "super_admin":
    pages = [
        st.Page(S["overview"], title="Overview", icon=":material/insights:", default=True),
        st.Page(S["branches"], title="Branches", icon=":material/store:"),
        st.Page(S["admins"], title="Admins", icon=":material/admin_panel_settings:"),
        st.Page(S["audit"], title="Audit log", icon=":material/policy:"),
    ]
elif role == "branch_admin":
    pages = [
        st.Page(B["command"], title="Command Center", icon=":material/space_dashboard:", default=True),
        st.Page(B["map"], title="Live Map", icon=":material/map:"),
        st.Page(B["assign"], title="Assign Work", icon=":material/assignment:"),
        st.Page(B["partners"], title="Partners", icon=":material/groups:"),
        st.Page(B["deliveries"], title="Deliveries", icon=":material/package_2:"),
        st.Page(B["disruptions"], title="Alerts", icon=":material/notifications_active:"),
        st.Page(B["history"], title="History", icon=":material/history:"),
        st.Page(B["insights"], title="Insights", icon=":material/insights:"),
        st.Page(B["analytics"], title="Analytics", icon=":material/analytics:"),
    ]
elif role == "customer":
    pages = [st.Page(C["orders"], title="My orders", icon=":material/package_2:", default=True)]
else:
    i18n.load(user)  # Tamil or English, as the partner chose last time
    pages = [
        st.Page(P["today"], title=i18n.t("nav_today"), icon=":material/today:", default=True),
        st.Page(P["deliveries"], title=i18n.t("nav_deliveries"), icon=":material/package_2:"),
        st.Page(P["route"], title=i18n.t("nav_route"), icon=":material/route:"),
        st.Page(P["report"], title=i18n.t("nav_report"), icon=":material/campaign:"),
        st.Page(P["history"], title=i18n.t("nav_history"), icon=":material/history:"),
    ]

navigation = st.navigation(pages)
last_page = ui.sync_prefs(user, navigation.url_path)  # filters + last page are saved per user in SQLite
# back to the admin's last page only when they land on the home page (a direct link like /assign is kept);
# partners always open on Today
if last_page and role != "partner" and navigation.url_path == "" and last_page != navigation.url_path:
    target = next((p for p in pages if p.url_path == last_page), None)
    if target is not None:
        st.switch_page(target)
ui.sidebar_user()
ui.live_updates()  # one refresh watcher for every page, at a fixed place in the sidebar
escalation_ui.watcher(user)  # order offers: ring / call / alert timer (+ the partner's alarm), also in the sidebar
if "_welcome" in st.session_state:
    st.toast(st.session_state.pop("_welcome"))
if role == "partner":
    live_ui.share_location(user)  # GPS every 30 s while on duty
    escalation_ui.partner_overlay(user)  # full-screen card while an urgent order waits for Accept
navigation.run()
ui.mark_seen()  # this session's own writes don't trigger a refresh (one-time messages and passwords stay visible)
