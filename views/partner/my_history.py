"""History: my reports, messages from my branch and the deliveries I finished."""
from html import escape

import streamlit as st

from modules import guards, ui
from modules import partner_scope as scope
from modules.i18n import t

guards.require_role("partner")
dp_id = guards.dp_id()
branch = guards.branch_id()  # from the validated session only
ui.header(t("history_title"))

ui.section(t("reports"), "campaign")
reports = scope.get_partner_incidents(dp_id, branch)
with ui.card("reports"):
    if not reports:
        ui.empty_state("campaign", t("no_reports"))
    rows = []
    for r in reports:
        outcome = (t("handled", time=r["decided_at"]) if r["status"] == "accepted" else
                   t("reviewed", time=r["decided_at"], note=r["decision_note"]) if r["status"] == "rejected" else
                   t("sent_at", time=r["created_at"]))
        rows.append(f"<div class='dp-row'><div class='main'><b>#{r['issue_id']} · {escape(r['summary'] or '')}</b>"
                    f"<small>{escape(outcome)}</small></div><div class='end'>{ui.issue_pill(r['status'])}</div></div>")
    st.markdown("".join(rows), unsafe_allow_html=True)

ui.section(t("messages"), "notifications")
messages = scope.get_partner_notifications(dp_id, branch)
with ui.card("messages"):
    if not messages:
        ui.empty_state("notifications_none", t("no_messages"))
    st.markdown("".join(f"<div class='dp-row'><div class='main'>{escape(m['text'])}</div>"
                        f"<div class='end dp-small'>{escape(m['created_at'][-8:-3])}</div></div>" for m in messages),
                unsafe_allow_html=True)

ui.section(t("delivered_list"), "task_alt")
deliveries = scope.get_partner_deliveries(dp_id, branch)
done = deliveries[deliveries["status"] == "delivered"]
with ui.card("delivered"):
    if done.empty:
        ui.empty_state("package_2", t("nothing_delivered"))
    else:
        st.dataframe(done[["delivery_id", "customer", "address_area", "deadline"]].rename(
            columns={"delivery_id": t("col_order"), "customer": t("col_customer"), "address_area": t("col_area"),
                     "deadline": t("col_due")}),
            hide_index=True, width="stretch")
