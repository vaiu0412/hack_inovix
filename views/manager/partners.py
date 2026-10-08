"""Delivery Partners: the whole team as a spreadsheet, with details for the selected partner."""
import streamlit as st

from modules import guards, manager_ui as mui, ui

guards.require_role("manager")
ui.header("Delivery Partners", "Search, filter, select a row for details, or download the list.")
ui.live_updates()
ctx = mui.context()

mui.team_table(ctx)
st.markdown("##### Selected delivery partner")
mui.partner_panel(ctx, st.session_state.get("selected_partner"))
