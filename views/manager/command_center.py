"""Command Center: the open alert, today's numbers, the map and what is at risk now."""
import streamlit as st

from modules import guards, manager_ui as mui, ui

guards.require_role("branch_admin")
ui.header("Command Center")
ctx = mui.context()

mui.alert_banner(ctx)
mui.kpi_tiles(ctx)

map_col, side_col = st.columns([1.6, 1], gap="medium")
with map_col:
    ui.section("Live map", "map")
    mui.live_map_view(ctx, height=430, key="cc_map", filters=False)
with side_col:
    ui.section("At risk now", "warning")
    with ui.card("at_risk"):
        rows = mui.at_risk_rows(ctx, limit=5)
        if rows:
            st.markdown(rows, unsafe_allow_html=True)
            if st.button("Review alerts", type="primary", icon=":material/arrow_forward:", width="stretch"):
                mui.go("disruptions")
        else:
            ui.empty_state("verified", "No alerts. All routes clear.")
    ui.section("Latest", "history")
    with ui.card("latest"):
        mui.activity_feed(ctx, limit=5)
mui.ai_status_line()
