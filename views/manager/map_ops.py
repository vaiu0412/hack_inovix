"""Live Map: every partner, stop and alert on real roads. Tap a vehicle for details."""
import streamlit as st

from modules import guards, manager_ui as mui, ui

guards.require_role("branch_admin")
ui.header("Live Map", "Tap a vehicle for details.")
ctx = mui.context()
mui.alert_banner(ctx)

map_col, side_col = st.columns([2.3, 1], gap="medium")
with map_col:
    mui.live_map_view(ctx)
with side_col:
    mui.partner_picker(ctx)
    mui.partner_panel(ctx, st.session_state.get("selected_partner"))
