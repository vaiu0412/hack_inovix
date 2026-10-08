"""Command Center: today's numbers, what needs a decision now, and what just happened."""
import streamlit as st

from modules import guards, manager_ui as mui, ui

guards.require_role("branch_admin")
ui.header("Command Center", "Everything that needs your attention, in one place.")
ui.live_updates()
ctx = mui.context()

mui.kpi_tiles(ctx)
mui.alert_banner(ctx)

left, right = st.columns([1.4, 1], gap="medium")
with left:
    st.markdown("##### At risk right now")
    at_risk = []
    for issue in ctx["open_issues"]:
        at_risk += [r for r in (issue.get("plan") or {}).get("risk", []) if r["risk_label"] in ("Critical", "High")]
    if at_risk:
        drivers = dict(zip(ctx["partners"]["vehicle_id"], ctx["partners"]["name"]))
        rows = []
        for r in at_risk[:8]:
            late = f"late by {-r['slack_min']} min" if r["slack_min"] < 0 else f"{r['slack_min']} min slack"
            rows.append(f"<div class='rp-action'><span class='rp-dot' style='background:"
                        f"{ui.RISK_HEX[r['risk_label']]}'></span><div><b>{r['customer']}</b> &nbsp;"
                        f"{ui.risk_badge(r['risk_label'])}<small>{r['delivery_id']} · {r['priority']} · "
                        f"{drivers.get(r['vehicle_id'], r['vehicle_id'])} · due {r['deadline']} · {late}</small>"
                        f"</div></div>")
        with st.container(border=True):
            st.markdown("".join(rows), unsafe_allow_html=True)
        if st.button("Open Disruptions & AI", icon=":material/psychology:", key="cc_open_disruptions"):
            mui.go("disruptions")
    else:
        with st.container(border=True):
            st.markdown(":material/check_circle: **All clear.** No delivery is at risk. When a delivery partner "
                        "reports a problem, it appears here within seconds with an AI recovery plan.")
with right:
    st.markdown("##### Delivery partners")
    with st.container(border=True):
        rows = [f"<div class='rp-action'><span class='rp-dot' style='background:"
                f"{ui.PARTNER_STATUS.get(p['status'], ('', '', '#6B7280'))[2]}'></span><div><b>{p['name']}</b> · "
                f"{p['partner_id']} &nbsp;{ui.partner_badge(p['status'])}<small>{p['vehicle_id']} · near "
                f"{p['area']} · {p['pending']} pending · {p['delivered']} done</small></div></div>"
                for p in ctx["partners"].to_dict("records")]
        st.markdown("".join(rows), unsafe_allow_html=True)
    if st.button("Open map", icon=":material/map:", key="cc_open_map"):
        mui.go("map")

st.markdown("##### Latest activity")
with st.container(border=True):
    mui.activity_feed(ctx, limit=6)
mui.ai_status_line()
