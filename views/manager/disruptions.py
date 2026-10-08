"""Alerts: what changed, what is affected, what to do – then one tap to apply the plan."""
import streamlit as st

from modules import guards, manager_ui as mui, store, ui

guards.require_role("branch_admin")
ctx = mui.context()
open_issues = ctx["open_issues"]
ui.header("Alerts", f"{len(open_issues)} open" if open_issues else "All clear")

applied = st.session_state.get("last_applied")
issue = store.get_issue(applied, ctx["branch_id"]) if applied else None
if issue and issue["status"] == "accepted":
    mui.applied_card(issue)
    if st.button("Hide", type="tertiary", key="hide_applied"):
        st.session_state.pop("last_applied", None)
        st.rerun()

if not open_issues:
    with ui.card("no_alerts"):
        if ui.empty_state("verified", "No alerts. All routes clear.", "Log issue", key="log_empty",
                          icon=":material/add:"):
            ui.pause_live_updates()
            mui.log_issue_dialog(ctx)
    st.stop()


def label(issue_id):
    alert = next(x for x in open_issues if x["issue_id"] == issue_id)
    return f"#{issue_id} · " + mui.alert_line(ctx, alert).split(" · ", 1)[1]


with st.container(horizontal=True, vertical_alignment="center"):
    ids = [i["issue_id"] for i in open_issues]
    pick = st.segmented_control("Alert", ids, default=ids[0], key="alert_pick", label_visibility="collapsed",
                                format_func=label)
    if st.button("Log issue", icon=":material/add:", key="log_top"):
        ui.pause_live_updates()
        mui.log_issue_dialog(ctx)
current = next((i for i in open_issues if i["issue_id"] == pick), open_issues[0])
mui.alert_steps(ctx, current)
