"""Operations console for the manager: live map, team, issues with AI plans, deliveries, activity."""
from html import escape

import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

from modules import issues, live_map, operations, store, ui
from modules.data_loader import load_all
from modules.graph_viz import build_graph, render_graph
from modules.parser import SEVERITIES
from modules.report_ui import report_form

SECTIONS = ["Live map", "Issues", "Deliveries", "Activity"]
SECTION_ICONS = {"Live map": ":material/map:", "Issues": ":material/report:", "Deliveries": ":material/package_2:",
                 "Activity": ":material/history:"}

ui.header("Operations", "Every partner, delivery and reported problem – live.")
ui.live_updates()
if "goto_section" in st.session_state:  # requested by a dialog after the switcher was drawn
    st.session_state["section"] = st.session_state.pop("goto_section")
st.session_state.setdefault("section", "Live map")

roads = load_all()["roads"]
road_names = dict(zip(roads["road_id"], roads["name"]))
partners = store.partners_df()
partner_names = dict(zip(partners["partner_id"], partners["name"]))
open_issues = store.list_issues(store.OPEN_ISSUE_STATUSES)
kpi = operations.kpis()


def risk_labels_now():
    """Delivery -> risk label from every plan still waiting for a decision."""
    labels = {}
    for issue in open_issues:
        for row in (issue.get("plan") or {}).get("risk", []):
            labels.setdefault(row["delivery_id"], row["risk_label"])
    return labels


def go(section):
    st.session_state["section"] = section


# ---------------------------------------------------------------- KPIs + alert
ui.kpi_row([
    ("Partners on duty", f"{kpi['on_duty']} / {kpi['partners']}", None),
    ("Deliveries today", kpi["deliveries"], f"{kpi['delivered']} delivered"),
    ("At risk now", kpi["at_risk"], None),
    ("Open issues", kpi["open_issues"], None),
    ("Deadlines saved", kpi["deadlines_saved"], "today"),
])

if open_issues:
    newest = open_issues[0]
    who = partner_names.get(newest["partner_id"], "Operations desk")
    with st.container(border=True):
        text_col, button_col = st.columns([4, 1], vertical_alignment="center")
        text_col.markdown(f":material/error: **{len(open_issues)} issue{'s' if len(open_issues) > 1 else ''} "
                          f"waiting for your decision** · latest from {who}: {newest['summary']}")
        button_col.button("Review", type="primary", width="stretch", on_click=go, args=("Issues",))

section = st.segmented_control(
    "Section", SECTIONS, key="section", label_visibility="collapsed",
    format_func=lambda s: f"{SECTION_ICONS[s]} {s}" + (f" ({len(open_issues)})" if s == "Issues" and open_issues else ""),
) or "Live map"


# ---------------------------------------------------------------- live map + team
def partner_panel(pid):
    p = store.get_partner(pid)
    if p is None:
        st.info("Tap a partner on the map or in the table.")
        return
    with st.container(border=True):
        st.markdown(ui.person(p["name"], f"{p['vehicle_type'].title()} · {p['reg_no']} · near {p['area']}", p["status"]),
                    unsafe_allow_html=True)
        st.markdown(ui.kv([
            ("Status", ui.partner_badge(p["status"])),
            ("Phone", f"<a href='tel:{escape(p['phone'])}'>{escape(p['phone'])}</a>"),
            ("Deliveries", f"{p['pending']} pending · {p['delivered']} done"),
            ("Urgent", f"{p['urgent']} medical/perishable"),
            ("Shift", escape(p["shift"])),
            ("Rating", f"{p['rating']:.1f} / 5"),
        ]), unsafe_allow_html=True)
        st.caption(f"Next stop: {p['next_stop']} · ETA {p['next_eta']} · speaks {p['languages']}")
        stops = store.deliveries_df(p["vehicle_id"])
        if len(stops):
            view = stops[["stop_order", "customer", "address_area", "priority", "planned_eta", "deadline", "status"]]
            st.dataframe(view.rename(columns={"stop_order": "#", "customer": "Customer", "address_area": "Area",
                                              "priority": "Priority", "planned_eta": "ETA", "deadline": "Due",
                                              "status": "Status"}),
                         hide_index=True, width="stretch", height=min(38 * (len(view) + 1) + 3, 280))
        else:
            st.caption("No deliveries assigned.")
        mine = [i for i in open_issues if i["partner_id"] == pid]
        if mine:
            st.button(f"Review issue #{mine[0]['issue_id']}", key=f"review_{pid}", on_click=go, args=("Issues",),
                      icon=":material/report:", width="stretch")


def team_table():
    st.markdown("##### Delivery team")
    search_col, status_col = st.columns([2, 3], vertical_alignment="bottom")
    query = search_col.text_input("Search", placeholder="Search name, vehicle or area", label_visibility="collapsed")
    statuses = status_col.pills("Status", list(ui.PARTNER_STATUS), selection_mode="multi",
                                format_func=lambda s: ui.PARTNER_STATUS[s][0], label_visibility="collapsed")
    view = partners.copy()
    if query:
        hay = (view["name"] + " " + view["vehicle_id"] + " " + view["reg_no"] + " " + view["area"]).str.lower()
        view = view[hay.str.contains(query.lower(), regex=False)]
    if statuses:
        view = view[view["status"].isin(statuses)]
    view = view.assign(status_text=view["status"].map(lambda s: ui.PARTNER_STATUS.get(s, (s,))[0]),
                       progress=(view["delivered"] / view["assigned"].where(view["assigned"] > 0)).fillna(0))
    columns = {"name": "Name", "status_text": "Status", "vehicle_id": "Vehicle", "reg_no": "Reg. no",
               "vehicle_type": "Type", "area": "Near", "assigned": "Assigned", "delivered": "Delivered",
               "pending": "Pending", "progress": "Progress", "urgent": "Urgent", "next_stop": "Next stop",
               "next_eta": "Next ETA", "open_issues": "Open issues", "phone": "Phone", "shift": "Shift",
               "rating": "Rating"}
    event = st.dataframe(
        view[list(columns)].rename(columns=columns), hide_index=True, width="stretch",
        on_select="rerun", selection_mode="single-row", key="team_table",
        column_config={"Progress": st.column_config.ProgressColumn(format="percent", min_value=0, max_value=1),
                       "Rating": st.column_config.NumberColumn(format="%.1f")},
    )
    rows = event.selection.rows if event else []
    pid = view.iloc[rows[0]]["partner_id"] if rows else None
    if pid and pid != st.session_state.get("_last_table_pick"):
        st.session_state["_last_table_pick"] = pid
        if pid != st.session_state.get("selected_partner"):
            st.session_state["selected_partner"] = pid
            st.rerun()
    st.download_button("Download team (CSV)", view[list(columns)].rename(columns=columns).to_csv(index=False),
                       "ripple-team.csv", "text/csv", icon=":material/download:")


if section == "Live map":
    selected = st.session_state.get("selected_partner")
    map_col, side_col = st.columns([2.1, 1], gap="medium")
    with map_col:
        plans = [i["plan"] for i in open_issues if i.get("plan")]
        disruptions = store.active_disruptions() + [p["disruption"] for p in plans if p.get("disruption")]
        detours = {r for p in plans for r in p.get("via_roads", [])}
        detours |= {r for i in store.list_issues(("accepted",)) for r in (i.get("plan") or {}).get("via_roads", [])}
        fmap = live_map.build(partners, store.deliveries_df(), roads, disruptions, detours, risk_labels_now(),
                              selected=selected, dark=ui.is_dark())
        out = st_folium(fmap, height=500, use_container_width=True, key="live_map",
                        returned_objects=["last_object_clicked_tooltip"])
        tip = (out or {}).get("last_object_clicked_tooltip")
        by_tip = {live_map.partner_tooltip(p): p["partner_id"] for p in partners.to_dict("records")}
        if tip and tip != st.session_state.get("_last_tip"):
            st.session_state["_last_tip"] = tip
            if tip in by_tip:
                st.session_state["selected_partner"] = by_tip[tip]
                st.rerun()
        st.caption("Tap a partner (initials) for details. Red dashed = blocked road · green = detour · "
                   "coloured dots = deliveries at risk.")
    with side_col:
        options = partners["partner_id"].tolist()
        pick = st.selectbox("Partner", options, index=options.index(selected) if selected in options else None,
                            format_func=lambda pid: f"{partner_names[pid]} · "
                                                    f"{partners.set_index('partner_id').loc[pid, 'vehicle_id']}",
                            placeholder="Choose a partner", label_visibility="collapsed")
        if pick and pick != selected:
            st.session_state["selected_partner"] = pick
            st.rerun()
        partner_panel(selected)
    team_table()


# ---------------------------------------------------------------- issues
@st.dialog("Log an issue", width="large")
def log_issue_dialog():
    st.caption("For problems you hear about by phone or see yourself. Pick who is affected, or Operations desk.")
    reporter = st.selectbox("Reported by", ["OPS"] + partners["partner_id"].tolist(),
                            format_func=lambda pid: "Operations desk" if pid == "OPS" else partner_names[pid])
    issue_id = report_form(reporter, prefix=f"mgr_{reporter}", source="manager")
    if issue_id:
        st.session_state["goto_section"] = "Issues"
        st.rerun()


def correct_issue(issue):
    problem = issue["problem"]
    types = list(issues.QUICK_TYPES) + ["protest"]
    with st.form(f"correct_{issue['issue_id']}", border=False):
        c1, c2 = st.columns(2)
        dtype = c1.selectbox("Type", types, index=types.index(problem["type"]) if problem["type"] in types else 0,
                             format_func=issues.type_label)
        road_ids = list(road_names)
        road = c2.selectbox("Road", road_ids, index=road_ids.index(problem["road_id"]) if problem.get("road_id") in road_ids else None,
                            format_func=road_names.get, placeholder="Choose the road")
        c3, c4 = st.columns(2)
        severity = c3.selectbox("Severity", SEVERITIES, index=SEVERITIES.index(problem.get("severity", "medium")))
        minutes = c4.number_input("Duration (min)", 0, 600, int(problem.get("duration_min") or 0), step=15)
        if st.form_submit_button("Save and re-plan", type="primary", width="stretch"):
            operations.edit_problem(issue["issue_id"], type=dtype, road_id=road, severity=severity,
                                    duration_min=int(minutes))
            st.rerun()


def issue_card(issue, compact=False):
    """compact=True: no inner expanders/maps (used inside the 'Decided' list)."""
    problem, plan = issue["problem"] or {}, issue.get("plan") or {}
    who = partner_names.get(issue["partner_id"], "Operations desk")
    with st.container(border=True):
        title = f"#{issue['issue_id']} · {issues.type_label(problem.get('type'))}"
        if problem.get("road_name"):
            title += f" · {problem['road_name']}"
        st.markdown(f"**{escape(title)}** &nbsp; {ui.severity_badge(problem.get('severity', 'medium'))} "
                    f"{ui.issue_badge(issue['status'])}", unsafe_allow_html=True)
        st.caption(f"Reported by {who} at {issue['created_at']} · "
                   f"{'voice note' if issue.get('audio') else 'typed' if issue.get('transcript') else 'quick button'}"
                   f"{' via ' + issue['transcript_engine'] if issue.get('audio') and issue.get('transcript_engine') else ''}")

        said, plan_col = st.columns([1, 1.5], gap="medium")
        with said:
            st.markdown("**What was reported**")
            if issue.get("audio"):
                st.audio(issue["audio"], format="audio/wav")
            if issue.get("transcript"):
                st.markdown(f'<div class="rp-quote">“{escape(issue["transcript"])}”</div>', unsafe_allow_html=True)
            st.markdown("**AI understood**")
            place = problem.get("place") if problem.get("place") != problem.get("road_name") else None
            minutes = int(problem.get("duration_min") or 0)
            st.markdown(ui.kv([
                ("Problem", escape(issues.type_label(problem.get("type")))),
                ("Where", escape(problem.get("road_name") or "not sure") + (f"<br><small>near {escape(place)}</small>" if place else "")),
                ("How long", f"{minutes} min" if minutes else "—"),
                ("Confidence", f"{int(100 * float(problem.get('confidence', 0)))}%"),
            ]), unsafe_allow_html=True)
            if issue["status"] in store.OPEN_ISSUE_STATUSES:
                with st.popover("Correct it", icon=":material/edit:", width="stretch"):
                    correct_issue(issue)

        with plan_col:
            if plan.get("kind") == "needs_location":
                st.warning("The report doesn't say where. Use **Correct it** to pick the road; the plan appears "
                           "right away.", icon=":material/location_off:")
            elif plan:
                st.markdown(f"**Impact** · {plan.get('headline', '')}")
                ba = plan.get("before_after") or {}
                if ba:
                    m1, m2, m3 = st.columns(3)
                    m1.markdown(f"<small>Deliveries hit</small><br><span class='rp-ba'>{plan['summary']['affected_deliveries']}</span>",
                                unsafe_allow_html=True)
                    m2.markdown(f"<small>Missed deadlines</small><br>{ui.before_after(ba['misses_before'], ba['misses_after'])}",
                                unsafe_allow_html=True)
                    m3.markdown(f"<small>Delay (min)</small><br>{ui.before_after(ba['delay_before'], ba['delay_after'])}",
                                unsafe_allow_html=True)
                ui.ai_note(plan.get("note", ""))
                if plan.get("actions"):
                    st.markdown("**Recommended actions**")
                    ui.actions_list(plan["actions"][:5])
                    if len(plan["actions"]) > 5:
                        with st.expander(f"All {len(plan['actions'])} actions"):
                            ui.actions_list(plan["actions"][5:])
                if issue["status"] == "analysed":
                    accept_col, reject_col = st.columns([2, 1])
                    if accept_col.button("Accept plan", type="primary", key=f"accept_{issue['issue_id']}",
                                         icon=":material/check_circle:", width="stretch"):
                        st.toast(operations.accept(issue["issue_id"]), icon=":material/check_circle:")
                        st.rerun()
                    with reject_col.popover("Reject", width="stretch"):
                        reason = st.text_input("Why?", key=f"why_{issue['issue_id']}", placeholder="e.g. Road already clear")
                        if st.button("Reject issue", key=f"reject_{issue['issue_id']}", width="stretch"):
                            operations.reject(issue["issue_id"], reason or "Not needed")
                            st.rerun()
                elif issue.get("decision_note"):
                    st.caption(f"{issue['decision_note']} at {issue.get('decided_at', '')}")

        if plan.get("risk") and not compact:
            with st.expander("Deliveries at risk, map and how the delay spreads"):
                risk = pd.DataFrame(plan["risk"])
                show = risk[["risk_label", "delivery_id", "customer", "priority", "vehicle_id", "planned_eta", "new_eta",
                             "deadline", "slack_min", "reason"]]
                st.dataframe(show.rename(columns={"risk_label": "Risk", "delivery_id": "ID", "customer": "Customer",
                                                  "priority": "Priority", "vehicle_id": "Vehicle",
                                                  "planned_eta": "Planned", "new_eta": "New ETA", "deadline": "Due",
                                                  "slack_min": "Slack (min)", "reason": "Why"})
                             .style.map(lambda v: f"color: {ui.RISK_HEX.get(v, 'inherit')}; font-weight: 600",
                                        subset=["Risk"]),
                             hide_index=True, width="stretch")
                small_map = live_map.build(partners, store.deliveries_df(), roads, [plan["disruption"]],
                                           plan.get("via_roads", []), dict(zip(risk["delivery_id"], risk["risk_label"])),
                                           dark=ui.is_dark())
                st_folium(small_map, height=360, use_container_width=True, key=f"issue_map_{issue['issue_id']}",
                          returned_objects=[])
                st.plotly_chart(render_graph(build_graph(plan["disruption"], risk, store.snapshot())),
                                width="stretch")
        if plan.get("actions") and not compact:
            with st.expander("Messages that will be sent" if issue["status"] == "analysed" else "Messages sent"):
                for action in plan["actions"]:
                    for message in action.get("messages", []):
                        st.markdown(f"**To {message['to']}**")
                        st.code(message["text"], language=None, wrap_lines=True)


if section == "Issues":
    top_left, top_right = st.columns([3, 1], vertical_alignment="center")
    top_left.markdown(f"##### Open issues ({len(open_issues)})")
    if top_right.button("Log an issue", icon=":material/add:", width="stretch"):
        ui.pause_live_updates()
        log_issue_dialog()
    if not open_issues:
        with st.container(border=True):
            st.markdown(":material/check_circle: **All clear.** Problems reported by partners appear here within "
                        "seconds, with an AI plan ready to approve.")
    for issue in open_issues:
        issue_card(issue)
    closed = store.list_issues(("accepted", "rejected"))
    if closed:
        st.markdown(f"##### Decided ({len(closed)})")
        for issue in closed[:10]:
            with st.expander(f"#{issue['issue_id']} · {issue['summary']} · {ui.ISSUE_STATUS[issue['status']][0]}"):
                issue_card(issue, compact=True)


# ---------------------------------------------------------------- deliveries
if section == "Deliveries":
    deliveries = store.deliveries_df()
    labels = risk_labels_now()
    deliveries["risk"] = deliveries["delivery_id"].map(labels).fillna("")
    deliveries["driver"] = deliveries["vehicle_id"].map(dict(zip(partners["vehicle_id"], partners["name"])))
    f1, f2 = st.columns([2, 3], vertical_alignment="bottom")
    query = f1.text_input("Search deliveries", placeholder="Customer, area or ID", label_visibility="collapsed")
    status_filter = f2.pills("Delivery status", ["pending", "delivered"], selection_mode="multi",
                             format_func=str.capitalize, label_visibility="collapsed")
    view = deliveries
    if query:
        hay = (view["customer"] + " " + view["address_area"] + " " + view["delivery_id"]).str.lower()
        view = view[hay.str.contains(query.lower(), regex=False)]
    if status_filter:
        view = view[view["status"].isin(status_filter)]
    columns = {"delivery_id": "ID", "customer": "Customer", "address_area": "Area", "priority": "Priority",
               "driver": "Partner", "vehicle_id": "Vehicle", "stop_order": "Stop", "planned_eta": "ETA",
               "deadline": "Due", "status": "Status", "risk": "Risk", "note": "Change", "customer_phone": "Phone"}
    st.dataframe(view[list(columns)].rename(columns=columns)
                 .style.map(lambda v: f"color: {ui.RISK_HEX.get(v, 'inherit')}; font-weight: 600", subset=["Risk"]),
                 hide_index=True, width="stretch", height=460)
    st.download_button("Download deliveries (CSV)", view[list(columns)].rename(columns=columns).to_csv(index=False),
                       "ripple-deliveries.csv", "text/csv", icon=":material/download:")
    sms = store.customer_messages()
    st.markdown(f"##### Customer messages ({len(sms)})")
    if len(sms):
        st.dataframe(sms.rename(columns={"created_at": "Time", "issue_id": "Issue", "to_customer": "Customer",
                                         "to_phone": "Phone", "text": "Message"}), hide_index=True,
                     width="stretch")
    else:
        st.caption("Messages to customers appear here when a plan is accepted.")


# ---------------------------------------------------------------- activity
if section == "Activity":
    st.markdown("##### Activity")
    log = store.events(60)
    icons = {"issue": ":material/report:", "ai": ":material/psychology:", "decision": ":material/gavel:",
             "delivery": ":material/package_2:", "edit": ":material/edit:", "system": ":material/settings:"}
    for event in log.to_dict("records"):
        st.markdown(f"{icons.get(event['kind'], ':material/info:')} `{event['created_at']}` {event['text']}")
    st.divider()
    with st.popover("Reset demo", icon=":material/restart_alt:"):
        st.write("Back to 09:00 with no issues. Everyone using the app sees the reset.")
        if st.button("Reset everything", type="primary"):
            store.reset_demo()
            st.session_state.clear()
            st.rerun()
