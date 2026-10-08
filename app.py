"""Ripple – AI-powered disruption-aware logistics planning.

WHAT CHANGED?  ->  WHAT IS AFFECTED?  ->  WHAT SHOULD WE DO NEXT?
Run with:  streamlit run app.py
"""
from pathlib import Path

import pandas as pd
import streamlit as st

from modules.data_loader import load_all, min_to_hhmm, now_label
from modules.graph_viz import build_graph, render_graph
from modules.impact import compute_impact
from modules.map_viz import build_map
from modules.parser import BASE_SEVERITY, SEVERITIES, llm_available, parse_disruption
from modules.recommender import recommend
from modules.risk import LABEL_COLORS, score_risk

st.set_page_config(layout="wide", page_title="Ripple", page_icon="🌊")

PAGES = ["Dashboard", "Report Disruption", "Impact", "Recovery"]
DEMO_TEXT = "Accident near Avinashi Road, road blocked for 2 hours"
TYPES = [t for t in BASE_SEVERITY if t != "unknown"] + ["unknown"]
ACTION_TITLES = {"reassign": "🔁 Reassign to backup", "reroute": "🛣️ Reroute vehicle",
                 "resequence": "🔀 Resequence / prioritise", "reschedule_notify": "📩 Reschedule & notify"}

css = Path(__file__).parent / "assets" / "style.css"
st.markdown(f"<style>{css.read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)

data = load_all()
road_names = data["roads"].set_index("road_id")["name"].to_dict()
vehicle_ids = data["vehicles"]["vehicle_id"].tolist()


# ---------------------------------------------------------------- state
def init_state():
    defaults = {"page": "Dashboard", "report_text": "", "parsed": None, "parse_version": 0,
                "disruptions": [], "impact": None, "summary": None, "actions": [],
                "before_after": None, "after": None, "alt_road_ids": [], "applied": False}
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def reset_all():
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    init_state()


def load_demo():
    st.session_state.report_text = DEMO_TEXT
    st.session_state.parsed = parse_disruption(DEMO_TEXT, data)
    st.session_state.parse_version += 1
    st.session_state.page = "Report Disruption"


def go_to(page):
    st.session_state.page = page


def run_pipeline():
    """WHAT IS AFFECTED + WHAT NEXT for all active disruptions, stored in session_state."""
    disruptions = st.session_state.disruptions
    if not disruptions:
        st.session_state.update(impact=None, summary=None, actions=[], before_after=None, after=None,
                                alt_road_ids=[], applied=False)
        return
    impact, summary = compute_impact(disruptions, data)
    risk = score_risk(impact, disruptions)
    actions, before_after, after = recommend(risk, disruptions, data)
    alt_ids = list(dict.fromkeys(r for a in actions for r in a.get("via_roads", [])))
    st.session_state.update(impact=risk, summary=summary, actions=actions, before_after=before_after,
                            after=after, alt_road_ids=alt_ids, applied=False)


def same_disruption(a, b):
    return all(a.get(k) == b.get(k) for k in ("type", "road_id", "vehicle_id"))


def add_disruption(disruption):
    """Add a confirmed disruption. Confirming the same type + road + vehicle again updates it."""
    others = [d for d in st.session_state.disruptions if not same_disruption(d, disruption)]
    st.session_state.disruptions = others + [disruption]
    run_pipeline()


def remove_disruption(index):
    st.session_state.disruptions = [d for i, d in enumerate(st.session_state.disruptions) if i != index]
    run_pipeline()


def describe(disruption):
    """'Accident · Avinashi Road' or 'Breakdown · V1 near Race Course Road'."""
    kind = disruption["type"].replace("_", " ").title()
    where = road_names.get(disruption.get("road_id"), "")
    if disruption.get("type") == "breakdown" and disruption.get("vehicle_id"):
        where = disruption["vehicle_id"] + (f" near {where}" if where else "")
    return f"{kind} · {where or '—'}"


def current_deliveries():
    """Deliveries table, updated with the recovery plan once it is applied."""
    deliveries = data["deliveries"].copy()
    if st.session_state.applied and st.session_state.after is not None:
        after = st.session_state.after.set_index("delivery_id")
        mask = deliveries["delivery_id"].isin(after.index)
        ids = deliveries.loc[mask, "delivery_id"]
        deliveries.loc[mask, "vehicle_id"] = ids.map(after["vehicle_id"]).values
        deliveries.loc[mask, "planned_eta"] = ids.map(after["new_eta"]).values
        deliveries.loc[mask, "deadline"] = ids.map(after["deadline"]).values
    return deliveries


def current_risk():
    """Risk table to show: after-plan once applied, otherwise the raw impact."""
    if st.session_state.applied and st.session_state.after is not None:
        return st.session_state.after
    return st.session_state.impact


init_state()
# page changes requested after the sidebar radio was drawn are applied here, on the next run
if "goto" in st.session_state:
    st.session_state.page = st.session_state.pop("goto")


# ---------------------------------------------------------------- layout pieces
def header():
    st.markdown(f"""
    <div class="ripple-header">
      <div>
        <div class="ripple-logo">🌊 <span>Ripple</span></div>
        <div class="ripple-tagline">Every disruption creates a ripple. We show how far it spreads — and how to stop it.</div>
      </div>
      <div class="ripple-clock"><small>SIMULATED CLOCK</small>{now_label()}</div>
    </div>""", unsafe_allow_html=True)
    steps = [("Report Disruption", "① What changed?"), ("Impact", "② What is affected?"),
             ("Recovery", "③ What should we do next?")]
    html = "".join(f'<span class="ripple-step {"active" if st.session_state.page == p else ""}">{t}</span>'
                   for p, t in steps)
    st.markdown(f'<div class="ripple-steps">{html}</div>', unsafe_allow_html=True)


def kpi(label, value, sub="", tone=""):
    return f'<div class="kpi {tone}"><div class="label">{label}</div><div class="value">{value}</div><div class="sub">{sub}</div></div>'


def badge(label):
    return f'<span class="badge {label}">{label}</span>'


def color_label(value):
    color = LABEL_COLORS.get(value)
    if not color:
        return ""
    text = "white" if value == "Critical" else "#0b1120"
    return f"background-color: {color}; color: {text}; font-weight: 600"


def risk_table(df, extra_cols=()):
    cols = ["risk_label", "risk_score", "delivery_id", "customer", "priority", "vehicle_id", "road_name",
            "planned_eta", "new_eta", "deadline", "delay_min", "slack_min", *extra_cols, "reason"]
    view = df[[c for c in cols if c in df.columns]].rename(columns={
        "risk_label": "Risk", "risk_score": "Score", "delivery_id": "ID", "customer": "Customer",
        "priority": "Priority", "vehicle_id": "Vehicle", "road_name": "Road", "planned_eta": "Planned ETA",
        "new_eta": "New ETA", "deadline": "Deadline", "delay_min": "Delay (min)", "slack_min": "Slack (min)",
        "action": "Action", "reason": "Why"})
    styled = view.style.map(color_label, subset=["Risk"]).format({"Score": "{:.0f}"})
    st.dataframe(styled, hide_index=True, width="stretch")


def need_disruption():
    st.info("No confirmed disruption yet. Report one first, or load the demo scenario.")
    c1, c2 = st.columns([1, 4])
    c1.button("Report a disruption", on_click=go_to, args=("Report Disruption",), type="primary")
    c2.button("Load demo scenario", on_click=load_demo, key="demo_inline")


# ---------------------------------------------------------------- sidebar
with st.sidebar:
    st.markdown("## 🌊 Ripple")
    st.caption(f"🕘 {now_label()} (simulated)")
    st.radio("Navigate", PAGES, key="page")
    st.divider()
    st.button("▶ Load demo scenario", on_click=load_demo, type="primary")
    st.button("↺ Reset", on_click=reset_all)
    st.divider()
    if st.session_state.disruptions:
        st.markdown(f"**Active disruptions ({len(st.session_state.disruptions)})**")
        for i, d in enumerate(st.session_state.disruptions):
            text_col, button_col = st.columns([5, 1], vertical_alignment="center")
            text_col.markdown(f"{describe(d)}  \n<small>{d['severity']} · {d['duration_min']} min</small>",
                              unsafe_allow_html=True)
            button_col.button("✕", key=f"remove_{i}", on_click=remove_disruption, args=(i,),
                              help="Remove this disruption")
        if st.session_state.applied:
            st.success("Recovery plan applied")
    st.caption("🤖 LLM: " + ("connected" if llm_available() else "off — rule-based mode (works offline)"))

header()
page = st.session_state.page


# ---------------------------------------------------------------- 1. Dashboard
if page == "Dashboard":
    deliveries = current_deliveries()
    risk = current_risk()
    at_risk = critical = 0
    if risk is not None and not risk.empty:
        at_risk = int(risk["risk_label"].isin(["Critical", "High"]).sum())
        critical = int((risk["risk_label"] == "Critical").sum())
    active = data["vehicles"]["status"].eq("active").sum()
    n_disruptions = len(st.session_state.disruptions)
    st.markdown('<div class="kpi-grid">' + "".join([
        kpi("Total vehicles", len(data["vehicles"]), f"{active} active · {len(data['vehicles']) - active} backup"),
        kpi("Total deliveries", len(deliveries), "planned for today"),
        kpi("Active disruptions", n_disruptions, "reported & confirmed", "danger" if n_disruptions else "ok"),
        kpi("At-risk deliveries", at_risk, "Critical + High" + (" · after plan" if st.session_state.applied else ""),
            "warn" if at_risk else "ok"),
        kpi("Critical deliveries", critical, "need action now", "danger" if critical else "ok"),
    ]) + "</div>", unsafe_allow_html=True)

    st.subheader("Live map")
    st.plotly_chart(build_map(data, st.session_state.disruptions, risk,
                              st.session_state.alt_road_ids if st.session_state.applied else None, deliveries),
                    width="stretch", config={"scrollZoom": True})

    st.subheader("Deliveries")
    labels = {} if risk is None or risk.empty else dict(zip(risk["delivery_id"], risk["risk_label"]))
    table = deliveries.assign(status=deliveries["delivery_id"].map(labels).fillna("On track"))
    table = table[["status", "delivery_id", "customer", "address_area", "priority", "vehicle_id",
                   "stop_order", "planned_eta", "deadline", "customer_phone"]]
    table.columns = ["Status", "ID", "Customer", "Area", "Priority", "Vehicle", "Stop", "ETA", "Deadline", "Phone"]
    st.dataframe(table.style.map(color_label, subset=["Status"]), hide_index=True, width="stretch", height=420)


# ---------------------------------------------------------------- 2. Report
elif page == "Report Disruption":
    st.subheader("① What changed?")
    left, right = st.columns([3, 2], gap="large")
    with left:
        st.markdown("**Describe it in your own words** (English or Tanglish)")
        st.text_area("Disruption report", key="report_text", height=110, label_visibility="collapsed",
                     placeholder="e.g. Avinashi road la accident aachu, full ah block, 2 mani neram aagum")
        if st.button("🔍 Analyse", type="primary"):
            if st.session_state.report_text.strip():
                st.session_state.parsed = parse_disruption(st.session_state.report_text, data)
                st.session_state.parse_version += 1
            else:
                st.warning("Type a message first, or use the form on the right.")
        st.caption("Try: *Murugan vandi breakdown aachu near Race Course* · *Heavy rain flooding at Trichy Road, "
                   "45 mins* · *Protest at Town Hall for 1.5 hr*")
        if st.session_state.disruptions:
            n = len(st.session_state.disruptions)
            st.info(f"{n} disruption{'s are' if n > 1 else ' is'} already active. Confirming adds this one, "
                    "and Ripple combines their impact. Re-confirming the same type and road updates it.")
    with right:
        st.markdown("**…or fill the form**")
        with st.container(border=True):
            f_type = st.selectbox("Type", TYPES, key="f_type", format_func=lambda t: t.replace("_", " ").title())
            f_road = st.selectbox("Location / road", ["—"] + list(road_names), key="f_road", format_func=lambda r: road_names.get(r, "—"))
            f_sev = st.select_slider("Severity", SEVERITIES, value="high", key="f_sev")
            f_dur = st.number_input("Duration (min)", 0, 600, 60, step=15, key="f_dur")
            f_veh = st.selectbox("Vehicle (for breakdowns)", ["—"] + vehicle_ids, key="f_veh")
            if st.button("Use these details"):
                st.session_state.parsed = {
                    "type": f_type, "road_id": None if f_road == "—" else f_road,
                    "road_name": road_names.get(f_road), "location_text": road_names.get(f_road, ""),
                    "severity": f_sev, "duration_min": int(f_dur),
                    "vehicle_id": None if f_veh == "—" else f_veh, "confidence": 1.0, "method": "form",
                    "raw_text": "",
                }
                st.session_state.parse_version += 1

    parsed = st.session_state.parsed
    if parsed:
        st.divider()
        st.markdown("#### Review & confirm  <span class='badge neutral'>human-in-the-loop</span>", unsafe_allow_html=True)
        st.markdown(f"""<div class="card"><div class="parsed-grid">
            <div><small>Type</small>{parsed['type'].replace('_', ' ').title()}</div>
            <div><small>Road</small>{parsed.get('road_name') or '❓ not found'}</div>
            <div><small>Severity</small>{parsed['severity']}</div>
            <div><small>Duration</small>{parsed['duration_min']} min</div>
            <div><small>Vehicle</small>{parsed.get('vehicle_id') or '—'}</div>
            <div><small>Confidence</small>{int(parsed['confidence'] * 100)}% · {parsed['method']}</div>
        </div></div>""", unsafe_allow_html=True)
        if not parsed.get("road_id") and not parsed.get("vehicle_id"):
            st.warning("I couldn't match a known road or vehicle in that message. Please pick the road below.")

        v = st.session_state.parse_version
        c1, c2, c3, c4, c5 = st.columns(5)
        e_type = c1.selectbox("Type", TYPES, index=TYPES.index(parsed["type"]) if parsed["type"] in TYPES else 0,
                              key=f"e_type_{v}", format_func=lambda t: t.replace("_", " ").title())
        road_opts = ["—"] + list(road_names)
        e_road = c2.selectbox("Road", road_opts, index=road_opts.index(parsed["road_id"]) if parsed.get("road_id") else 0,
                              key=f"e_road_{v}", format_func=lambda r: road_names.get(r, "—"))
        e_sev = c3.selectbox("Severity", SEVERITIES, index=SEVERITIES.index(parsed["severity"]), key=f"e_sev_{v}")
        e_dur = c4.number_input("Duration (min)", 0, 600, int(parsed["duration_min"]), step=15, key=f"e_dur_{v}")
        veh_opts = ["—"] + vehicle_ids
        e_veh = c5.selectbox("Vehicle", veh_opts, index=veh_opts.index(parsed["vehicle_id"]) if parsed.get("vehicle_id") else 0,
                             key=f"e_veh_{v}")

        if st.button("✅ Confirm & analyse impact", type="primary"):
            if e_road == "—" and e_veh == "—":
                st.error("Pick a road (or a vehicle for breakdowns) so Ripple knows where the disruption is.")
            else:
                confirmed = {**parsed, "type": e_type, "road_id": None if e_road == "—" else e_road,
                             "road_name": road_names.get(e_road), "severity": e_sev, "duration_min": int(e_dur),
                             "vehicle_id": None if e_veh == "—" else e_veh}
                add_disruption(confirmed)
                st.session_state.goto = "Impact"
                st.rerun()


# ---------------------------------------------------------------- 3. Impact
elif page == "Impact":
    st.subheader("② What is affected?")
    if not st.session_state.disruptions:
        need_disruption()
    else:
        summary, risk = st.session_state.summary, st.session_state.impact
        st.markdown(" ".join(f"<span class='badge neutral'>⚠️ {describe(d)}</span>"
                             for d in st.session_state.disruptions), unsafe_allow_html=True)
        if risk.empty:
            st.success(f"✅ {summary['message']}")
        else:
            c = st.columns(5)
            roads = summary["affected_roads"]
            if len(roads) > 1:
                c[0].metric("Affected roads", len(roads), ", ".join(roads), delta_color="off", delta_arrow="off")
            else:
                c[0].metric("Affected roads", ", ".join(roads) or "—")
            c[1].metric("Vehicles hit", len(summary["affected_vehicles"]), ", ".join(summary["affected_vehicles"]),
                        delta_color="off", delta_arrow="off")
            c[2].metric("Deliveries hit", summary["affected_deliveries"])
            c[3].metric("Total delay", f"{summary['total_delay_min']} min")
            c[4].metric("Predicted missed deadlines", summary["predicted_misses"])

            counts = risk["risk_label"].value_counts()
            st.markdown(" ".join(f"{badge(l)} {counts.get(l, 0)}" for l in ["Critical", "High", "Medium", "Low"]),
                        unsafe_allow_html=True)
            risk_table(risk)

            tab_map, tab_graph = st.tabs(["🗺️ Ripple map", "🕸️ Dependency graph"])
            with tab_map:
                st.plotly_chart(build_map(data, st.session_state.disruptions, risk), width="stretch",
                                config={"scrollZoom": True})
            with tab_graph:
                st.plotly_chart(render_graph(build_graph(st.session_state.disruptions, risk, data)), width="stretch")
            st.button("③ See recovery plan →", on_click=go_to, args=("Recovery",), type="primary")


# ---------------------------------------------------------------- 4. Recovery
elif page == "Recovery":
    st.subheader("③ What should we do next?")
    if not st.session_state.disruptions:
        need_disruption()
    elif not st.session_state.actions:
        st.success("✅ Nothing to recover: " + (st.session_state.summary or {}).get("message", "no impact."))
    else:
        ba = st.session_state.before_after
        c1, c2, c3 = st.columns(3)
        for col, title, key in [(c1, "Missed deadlines", "misses"), (c2, "Critical deliveries", "critical"),
                                (c3, "Total delay (min)", "delay")]:
            col.markdown(f"**{title}**")
            col.markdown(f'<div class="ba"><span class="before">{ba[key + "_before"]}</span>'
                         f'<span class="arrow">→</span><span class="after">{ba[key + "_after"]}</span></div>',
                         unsafe_allow_html=True)
        st.caption("Before → after applying every recommended action.")

        if st.session_state.applied:
            st.success("✅ Plan applied: vehicles, ETAs, KPIs and the map are updated. Check the Dashboard.")
        elif st.button("🚀 Apply plan", type="primary"):
            st.session_state.applied = True
            st.toast("Recovery plan applied")
            st.rerun()

        st.markdown("#### Recommended actions")
        for i, a in enumerate(st.session_state.actions):
            st.markdown(f"""<div class="card {a['action_type']}">
                <h4>{ACTION_TITLES[a['action_type']]} {badge(a['risk_label'])}</h4>
                <div>{a['description']}</div>
                <div class="why">💡 {a['why']}</div>
                <div class="chips">
                  <span class="chip">⏱️ saves {a['expected_delay_saved_min']} min</span>
                  <span class="chip">🛣️ +{a['extra_km']} km</span>
                  <span class="chip">📦 protects {', '.join(a['deliveries_protected'])}</span>
                </div></div>""", unsafe_allow_html=True)
            with st.expander(f"✉️ Drafted messages ({len(a['messages'])})"):
                for m in a["messages"]:
                    st.markdown(f"**To:** {m['to']}")
                    st.code(m["text"], language=None, wrap_lines=True)

        st.markdown("#### After the plan")
        risk_table(st.session_state.after, extra_cols=("action",))
