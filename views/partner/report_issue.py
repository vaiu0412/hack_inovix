"""Report: tap what happened, record or type, check, send."""
from html import escape

import streamlit as st

from modules import guards, partner_scope as scope, ui
from modules.report_ui import report_form

guards.require_role("partner")
dp_id = guards.dp_id()
branch = guards.branch_id()  # from the validated session only
ui.header("Report", "Say it in Tamil or English.")

reports = scope.get_partner_incidents(dp_id, branch)
if reports and st.session_state.get("last_sent_issue") == reports[0]["issue_id"]:
    latest = reports[0]
    st.markdown(f'<div class="dp-success">{ui.icon("check_circle")} Issue sent to admin.'
                f'<span style="margin-left:auto">{ui.issue_pill(latest["status"])}</span></div>'
                f'<p class="dp-sub" style="margin:-4px 0 12px">{escape(latest["summary"] or "")}</p>',
                unsafe_allow_html=True)

with ui.card("report"):
    issue_id = report_form(dp_id, branch, prefix=f"partner_{dp_id}", source="partner")
if issue_id:
    st.session_state["last_sent_issue"] = issue_id
    st.toast("Issue sent to admin.", icon=":material/send:")
    st.rerun()
