"""My Deliveries: all my stops, with Done buttons."""
from html import escape

import streamlit as st

from modules import guards, partner_scope as scope, ui

guards.require_role("partner")
dp_id = guards.dp_id()
branch = guards.branch_id()  # from the validated session only
profile = scope.get_partner_profile(dp_id, branch)
ui.header("My Deliveries", f"{profile['pending']} to go · {profile['delivered']} delivered")
ui.live_updates()

deliveries = scope.get_partner_deliveries(dp_id, branch)
if deliveries.empty:
    st.info("No deliveries assigned yet. New work appears here with an instruction under Notifications.",
            icon=":material/hourglass_empty:")
for d in deliveries.sort_values("stop_order").to_dict("records"):
    with st.container(border=True):
        info, action = st.columns([4, 1.3], vertical_alignment="center")
        if d["status"] == "delivered":
            tag = ui.badge("Delivered", "rp-low")
        elif d["risk"]:
            tag = ui.risk_badge(d["risk"])
        else:
            tag = ui.badge("Pending", "rp-neutral")
        extra = f" · {escape(str(d['note']))}" if d["note"] else ""
        info.markdown(f"**{d['stop_order']}. {escape(d['customer'])}** &nbsp;{tag}<br><small>"
                      f"{escape(d['address_area'])} · ETA {d['planned_eta']} · due {d['deadline']} · "
                      f"{d['priority']}{extra}</small>", unsafe_allow_html=True)
        if d["status"] != "delivered" and action.button("Done", key=f"done_{d['delivery_id']}",
                                                         icon=":material/check:", width="stretch"):
            scope.mark_delivered(dp_id, branch, d["delivery_id"])
            st.toast(f"{d['customer']} marked delivered", icon=":material/check:")
            st.rerun()
