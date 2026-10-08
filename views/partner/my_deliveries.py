"""Deliveries: all my stops in order, with Mark delivered."""
from html import escape

import streamlit as st

from modules import guards, partner_scope as scope, partner_ui, ui

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
        risk = ui.pill_html(ui.risk_state(d["risk"]), d["risk"]) + " " if d["risk"] and d["status"] != "delivered" else ""
        note = f" · {escape(str(d['note']).capitalize())}" if d["note"] else ""
        st.markdown(f"<div class='dp-row'><div class='main'><b>{d['stop_order']}. {escape(d['customer'])}</b>"
                    f"<small>{escape(d['delivery_id'])} · {escape(d['address_area'])} · "
                    f"{escape(d['priority'].capitalize())}{note}</small></div>"
                    f"<div class='end'>{d['planned_eta'] or '—'}<br>{risk}{partner_ui.stage_pill(d['status'])}</div></div>",
                    unsafe_allow_html=True)
        partner_ui.step_buttons(dp_id, branch, d, key=f"list_{d['delivery_id']}")
