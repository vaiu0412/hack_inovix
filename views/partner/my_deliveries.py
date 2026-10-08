"""Deliveries: all my stops in order, with Mark delivered."""
from html import escape

import streamlit as st

from modules import guards, partner_scope as scope, ui

guards.require_role("partner")
dp_id = guards.dp_id()
branch = guards.branch_id()  # from the validated session only
profile = scope.get_partner_profile(dp_id, branch)
ui.header("Deliveries", f"{profile['pending']} left · {profile['delivered']} done")

deliveries = scope.get_partner_deliveries(dp_id, branch)
if deliveries.empty:
    with ui.card("none"):
        ui.empty_state("hourglass_empty", "No deliveries yet.")
for d in deliveries.sort_values("stop_order").to_dict("records"):
    with ui.card(f"stop_{d['delivery_id']}"):
        state = "done" if d["status"] == "delivered" else ui.risk_state(d["risk"]) if d["risk"] else "normal"
        note = f" · {escape(str(d['note']).capitalize())}" if d["note"] else ""
        st.markdown(f"<div class='dp-row'><div class='main'><b>{d['stop_order']}. {escape(d['customer'])}</b>"
                    f"<small>{escape(d['address_area'])} · {escape(d['priority'].capitalize())}{note}</small></div>"
                    f"<div class='end'>{d['planned_eta']}<br>{ui.pill_html(state, 'Done' if state == 'done' else None)}"
                    f"</div></div>", unsafe_allow_html=True)
        if d["status"] != "delivered" and st.button("Mark delivered", key=f"done_{d['delivery_id']}",
                                                     icon=":material/check:", width="stretch"):
            scope.mark_delivered(dp_id, branch, d["delivery_id"])
            st.toast("Delivered.", icon=":material/check:")
            st.rerun()
