"""Report Issue: voice note, quick button or text -> operations gets the problem and an AI plan."""
from html import escape

import streamlit as st

from modules import guards, partner_scope as scope, ui
from modules.report_ui import report_form

guards.require_role("partner")
dp_id = guards.dp_id()
branch = guards.branch_id()  # from the validated session only
ui.header("Report an issue", "Say it in Tamil, English or both – we'll work out the rest.")
ui.live_updates()

with st.container(border=True):
    issue_id = report_form(dp_id, branch, prefix=f"partner_{dp_id}", source="partner")
if issue_id:
    st.session_state["last_sent_issue"] = issue_id
    st.toast("Sent to operations", icon=":material/send:")
    st.rerun()

reports = scope.get_partner_incidents(dp_id, branch)
if reports and st.session_state.get("last_sent_issue") == reports[0]["issue_id"]:
    latest = reports[0]
    with st.container(border=True):
        st.markdown(f":material/check_circle: **Sent** · {escape(latest['summary'] or '')} &nbsp;"
                    f"{ui.issue_badge(latest['status'])}", unsafe_allow_html=True)
        st.caption("Operations is reviewing it with an AI plan. New instructions will appear on Today.")
