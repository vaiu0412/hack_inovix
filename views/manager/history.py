"""History: decided issues and the full activity log."""
import streamlit as st

from modules import guards, manager_ui as mui, store, ui

guards.require_role("manager")
ui.header("History", "Every decision and event since the start of the day.")
ui.live_updates()
ctx = mui.context()

closed = store.list_issues(("accepted", "rejected"))
st.markdown(f"##### Decided issues ({len(closed)})")
if not closed:
    st.caption("Accepted and rejected issues appear here.")
for issue in closed[:20]:
    with st.expander(f"#{issue['issue_id']} · {issue['summary']} · {ui.ISSUE_STATUS[issue['status']][0]}"):
        mui.issue_card(ctx, issue, compact=True)

st.markdown("##### Activity log")
with st.container(border=True):
    mui.activity_feed(limit=80)
mui.ai_status_line()
