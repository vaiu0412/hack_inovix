"""My Deliveries: my own route on a map and all my stops."""
from html import escape

import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

from modules import guards, live_map, partner_scope as scope, ui

guards.require_role("partner")
dp_id = guards.dp_id()
profile = scope.get_partner_profile(dp_id)
ui.header("My Deliveries", f"{profile['pending']} to go · {profile['delivered']} delivered")
ui.live_updates()

deliveries = scope.get_partner_deliveries(dp_id)
route = scope.get_partner_route(dp_id)

# ---------------------------------------------------------------- my route only
roads = pd.DataFrame(route, columns=["road_id", "name", "points", "blocked"])
blocked = [{"road_id": r["road_id"], "road_name": r["name"], "type": "closure"} for r in route if r["blocked"]]
me = pd.DataFrame([profile])
fmap = live_map.build(me, deliveries, roads, blocked, (), dict(zip(deliveries["delivery_id"], deliveries["risk"])),
                      selected=dp_id, dark=ui.is_dark())
st_folium(fmap, height=340, use_container_width=True, key="my_route_map", returned_objects=[])
if blocked:
    st.warning("Blocked on your route: " + ", ".join(b["road_name"] for b in blocked)
               + ". Follow the instructions on Today.", icon=":material/block:")
st.caption("Only your own route and stops are shown.")

# ---------------------------------------------------------------- my stops
st.markdown("##### My stops")
if deliveries.empty:
    st.info("No deliveries assigned yet.", icon=":material/hourglass_empty:")
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
            scope.mark_delivered(dp_id, d["delivery_id"])
            st.toast(f"{d['customer']} marked delivered", icon=":material/check:")
            st.rerun()
