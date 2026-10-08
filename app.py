"""Ripple – disruption-aware delivery operations for Coimbatore.

Two roles, one live database:
  Operations  – the manager's console: live map, team, issues with AI plans
  Partner app – the delivery partner's phone screen: stops, voice-note problem reports

Run:  streamlit run app.py
Deep link for a partner's phone:  /partner?id=P1
"""
import streamlit as st

from modules import ui

ui.setup_page()

pages = [
    st.Page("views/home.py", title="Home", icon=":material/home:", default=True),
    st.Page("views/manager.py", title="Operations", icon=":material/monitoring:", url_path="manager"),
    st.Page("views/partner.py", title="Partner app", icon=":material/two_wheeler:", url_path="partner"),
]
st.navigation(pages, position="top").run()
