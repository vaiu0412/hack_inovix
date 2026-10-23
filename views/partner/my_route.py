"""Route: my own route on the map (nobody else's), what is blocked, and my stops in order."""
from html import escape

import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

from modules import guards, live_map, ui
from modules import partner_scope as scope
from modules.data_loader import load_all
from modules.i18n import t

guards.require_role("partner")
dp_id = guards.dp_id()
branch = guards.branch_id()  # from the validated session only
profile = scope.get_partner_profile(dp_id, branch)
ui.header(t("route_title"), t("stops_left", n=profile["pending"]))

deliveries = scope.get_partner_deliveries(dp_id, branch)
route = scope.get_partner_route(dp_id, branch)
blocked = [{"road_id": r["road_id"], "road_name": r["name"], "type": "closure", "severity": "high"}
           for r in route if r["blocked"]]
me = pd.DataFrame([{**profile, "route_roads": [r["road_id"] for r in route]}])
state = ui.partner_state(
    profile["status"], next((r for r in ("Critical", "High", "Medium") if r in set(deliveries["risk"])), None)
)

holder = st.empty()
holder.markdown(ui.skeleton(420), unsafe_allow_html=True)
fmap = live_map.build(
    me,
    deliveries,
    load_all()["roads"],
    blocked,
    (),
    dict(zip(deliveries["delivery_id"], deliveries["risk"])),
    selected=dp_id,
    states={dp_id: state},
)
with holder.container():
    st_folium(fmap, height=420, use_container_width=True, key="my_route_map", returned_objects=[])

if blocked:
    st.error(t("blocked_check", roads=", ".join(b["road_name"] for b in blocked)), icon=":material/block:")

todo = deliveries[~deliveries["status"].isin(["delivered", "failed"])].sort_values("eta_min")
ui.section(t("stops"), "pin_drop")
with ui.card("route_stops"):
    if todo.empty:
        ui.empty_state("task_alt", t("all_stops_done"))
    rows = []
    for d in todo.to_dict("records"):
        slack = d["deadline_min"] - d["eta_min"]
        timing = (
            ui.pill_html("normal", t("min_early", n=slack))
            if slack >= 0
            else ui.pill_html("critical", t("min_late", n=-slack))
        )
        rows.append(f"<div class='dp-row'><div class='main'><b>{d['stop_order']}. {escape(d['customer'])}</b>"
                    f"<small>{escape(d['address_area'])} · {t('due_at', time=d['deadline'])}</small></div>"
                    f"<div class='end'>{d['planned_eta']}<br>{timing}</div></div>")
    st.markdown("".join(rows), unsafe_allow_html=True)
