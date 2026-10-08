"""History: every decided alert (with its before -> after) and the day's activity."""
from html import escape

import streamlit as st

from modules import guards, manager_ui as mui, store, ui

guards.require_role("branch_admin")
ui.header("History")
ctx = mui.context()

closed = store.list_issues(("accepted", "rejected"), branch_id=ctx["branch_id"])
ui.section(f"Decided alerts ({len(closed)})", "gavel")
if not closed:
    with ui.card("no_history"):
        ui.empty_state("history", "No decisions yet.")
for issue in closed[:20]:
    word = ui.ISSUE_STATUS[issue["status"]][0]
    with st.expander(f"#{issue['issue_id']} · {mui.alert_line(ctx, issue)} · {word}"):
        if issue["status"] == "accepted":
            mui.applied_card(issue)
            st.markdown("".join(ui.rec_card(a) for a in (issue.get("plan") or {}).get("actions", [])[:4]),
                        unsafe_allow_html=True)
        else:
            st.markdown(f"<p class='dp-sub'>Rejected at {escape(issue.get('decided_at') or '')}: "
                        f"{escape(issue.get('decision_note') or '')}</p>", unsafe_allow_html=True)

ui.section("Activity", "history")
with ui.card("activity"):
    mui.activity_feed(ctx, limit=80)
mui.ai_status_line()
