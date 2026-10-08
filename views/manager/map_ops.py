"""Map & Operations: where every delivery partner is; tap one for details."""
import streamlit as st

from modules import guards, manager_ui as mui, ui

guards.require_role("manager")
ui.header("Map & Operations", "Tap a delivery partner on the map to see their deliveries.")
ui.live_updates()
ctx = mui.context()
mui.alert_banner(ctx)

map_col, side_col = st.columns([2.1, 1], gap="medium")
with map_col:
    mui.live_map_view(ctx)
with side_col:
    mui.partner_picker(ctx)
    mui.partner_panel(ctx, st.session_state.get("selected_partner"))
