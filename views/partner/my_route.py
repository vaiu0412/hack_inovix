"""My Route: my own roads on a map, what is blocked, and the ETA for each stop."""
from html import escape

import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

from modules import guards, live_map, partner_scope as scope, ui

guards.require_role("partner")
dp_id = guards.dp_id()
branch = guards.branch_id()
profile = scope.get_partner_profile(dp_id, branch)
ui.header("My Route", "Only your own route and stops are shown.")
ui.live_updates()

deliveries = scope.get_partner_deliveries(dp_id, branch)
route = scope.get_partner_route(dp_id, branch)
roads = pd.DataFrame(route, columns=["road_id", "name", "points", "blocked"])
blocked = [{"road_id": r["road_id"], "road_name": r["name"], "type": "closure"} for r in route if r["blocked"]]
fmap = live_map.build(pd.DataFrame([profile]), deliveries, roads, blocked, (),
                      dict(zip(deliveries["delivery_id"], deliveries["risk"])), selected=dp_id, dark=ui.is_dark())
st_folium(fmap, height=340, use_container_width=True, key="my_route_map", returned_objects=[])
if blocked:
    st.warning("Blocked on your route: " + ", ".join(b["road_name"] for b in blocked)
               + ". Follow the latest instruction under Notifications.", icon=":material/block:")

st.markdown("##### Roads in driving order")
if not route:
    st.caption("No route assigned yet.")
st.markdown(" → ".join(ui.badge(r["name"], "rp-critical" if r["blocked"] else "rp-neutral") for r in route),
            unsafe_allow_html=True)

st.markdown("##### ETA for each stop")
todo = deliveries[~deliveries["status"].isin(["delivered", "failed"])].sort_values("eta_min")
if todo.empty:
    st.caption("Nothing left to deliver.")
rows = []
for d in todo.to_dict("records"):
    slack = d["deadline_min"] - d["eta_min"]
    timing = ui.badge(f"{slack} min early", "rp-low") if slack >= 0 else ui.badge(f"{-slack} min late", "rp-critical")
    rows.append(f"<div class='rp-action'><span class='rp-dot' style='background:#2563EB'></span><div style='flex:1'>"
                f"<b>{d['planned_eta']}</b> · {escape(d['customer'])} &nbsp;{timing}<small>{escape(d['address_area'])}"
                f" · due {d['deadline']} · {escape(d['road_id'])}</small></div></div>")
st.markdown("".join(rows), unsafe_allow_html=True)
