"""History: my reports, messages from my branch and the deliveries I finished."""
from html import escape

import streamlit as st

from modules import guards, partner_scope as scope, ui

guards.require_role("partner")
dp_id = guards.dp_id()
branch = guards.branch_id()  # from the validated session only
ui.header("History")

ui.section("Reports", "campaign")
reports = scope.get_partner_incidents(dp_id, branch)
with ui.card("reports"):
    if not reports:
        ui.empty_state("campaign", "No reports today.")
    rows = []
    for r in reports:
        outcome = (f"Handled {r['decided_at']}" if r["status"] == "accepted" else
                   f"Reviewed {r['decided_at']}: {r['decision_note']}" if r["status"] == "rejected" else
                   f"Sent {r['created_at']}")
        rows.append(f"<div class='dp-row'><div class='main'><b>#{r['issue_id']} · {escape(r['summary'] or '')}</b>"
                    f"<small>{escape(outcome)}</small></div><div class='end'>{ui.issue_pill(r['status'])}</div></div>")
    st.markdown("".join(rows), unsafe_allow_html=True)

ui.section("Messages", "notifications")
messages = scope.get_partner_notifications(dp_id, branch)
with ui.card("messages"):
    if not messages:
        ui.empty_state("notifications_none", "No messages yet.")
    st.markdown("".join(f"<div class='dp-row'><div class='main'>{escape(m['text'])}</div>"
                        f"<div class='end dp-small'>{escape(m['created_at'][-8:-3])}</div></div>" for m in messages),
                unsafe_allow_html=True)

ui.section("Delivered", "task_alt")
deliveries = scope.get_partner_deliveries(dp_id, branch)
done = deliveries[deliveries["status"] == "delivered"]
with ui.card("delivered"):
    if done.empty:
        ui.empty_state("package_2", "Nothing delivered yet.")
    else:
        st.dataframe(done[["delivery_id", "customer", "address_area", "deadline"]].rename(
            columns={"delivery_id": "Order", "customer": "Customer", "address_area": "Area", "deadline": "Due"}),
            hide_index=True, width="stretch")
