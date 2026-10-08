"""Disruptions & AI: reported problems, the AI's plan for each, and your decision."""
import streamlit as st

from modules import guards, manager_ui as mui, ui

guards.require_role("branch_admin")
ui.header("Disruptions & AI", "Review what delivery partners reported and approve the AI recovery plan.")
ui.live_updates()
ctx = mui.context()

top_left, top_right = st.columns([3, 1], vertical_alignment="center")
top_left.markdown(f"##### Open issues ({len(ctx['open_issues'])})")
if top_right.button("Log an issue", icon=":material/add:", width="stretch"):
    ui.pause_live_updates()
    mui.log_issue_dialog(ctx)
if not ctx["open_issues"]:
    with st.container(border=True):
        st.markdown(":material/check_circle: **All clear.** Problems reported by delivery partners appear here "
                    "within seconds, with an AI plan ready to approve.")
for issue in ctx["open_issues"]:
    mui.issue_card(ctx, issue)
st.caption("Decided issues are listed under History.")
