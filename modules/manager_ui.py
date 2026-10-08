"""Building blocks shared by the Branch Admin pages. Everything is scoped to the signed-in
admin's branch: ctx["branch_id"] comes from the validated session only."""
from html import escape

import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

from modules import admin, guards, issues, live_map, operations, store, ui
from modules.data_loader import load_all
from modules.graph_viz import build_graph, render_graph
from modules.parser import SEVERITIES, llm_status
from modules.report_ui import report_form


def context():
    """Data every branch admin page needs, read once per run – own branch only."""
    branch = guards.branch_id()
    roads = load_all()["roads"]
    partners = store.partners_df(branch)
    return {
        "roads": roads, "road_names": dict(zip(roads["road_id"], roads["name"])), "partners": partners,
        "partner_names": dict(zip(partners["partner_id"], partners["name"])),
        "open_issues": store.list_issues(store.OPEN_ISSUE_STATUSES, branch_id=branch),
        "branch_id": branch, "actor": guards.current_user(),
    }


def go(page_key):
    st.switch_page(guards.BRANCH_PAGES[page_key])


def risk_labels_now(open_issues):
    """Delivery -> risk label from every plan still waiting for a decision."""
    labels = {}
    for issue in open_issues:
        for row in (issue.get("plan") or {}).get("risk", []):
            labels.setdefault(row["delivery_id"], row["risk_label"])
    return labels


def kpi_tiles(ctx):
    kpi = operations.kpis(ctx["branch_id"])
    ui.kpi_row([
        ("Partners on duty", f"{kpi['on_duty']} / {kpi['partners']}", None),
        ("Deliveries today", kpi["deliveries"], f"{kpi['delivered']} delivered"),
        ("At risk now", kpi["at_risk"], None),
        ("Open issues", kpi["open_issues"], None),
        ("Deadlines saved", kpi["deadlines_saved"], "today"),
    ])


def alert_banner(ctx):
    open_issues = ctx["open_issues"]
    if not open_issues:
        return
    newest = open_issues[0]
    who = ctx["partner_names"].get(newest["partner_id"], "Operations desk")
    with st.container(border=True):
        text_col, button_col = st.columns([4, 1], vertical_alignment="center")
        text_col.markdown(f":material/error: **{len(open_issues)} issue{'s' if len(open_issues) > 1 else ''} "
                          f"waiting for your decision** · latest from {who}: {newest['summary']}")
        if button_col.button("Review", type="primary", width="stretch", key="alert_review"):
            go("disruptions")


def ai_status_line():
    ai = llm_status()
    if not ai["available"]:
        st.caption(":material/smart_toy: AI: no key set – rule-based mode (everything still works).")
    elif ai["error"] and (not ai["ok_at"] or ai["error_at"] >= ai["ok_at"]):
        wait = f" for about {ai['paused_sec'] // 60 + 1} more min" if ai["paused_sec"] else ""
        st.caption(f":material/smart_toy: AI: last call failed at {ai['error_at']} – using rules{wait}. "
                   f"Reason: {ai['error']}")
    elif ai["ok_at"]:
        st.caption(f":material/smart_toy: AI: {ai['provider']} · {ai['model']} · last answer at {ai['ok_at']}")
    else:
        st.caption(":material/smart_toy: AI: key found, not used yet in this session of the server.")


# ---------------------------------------------------------------- map + partners
def live_map_view(ctx, height=500, key="live_map"):
    partners, open_issues = ctx["partners"], ctx["open_issues"]
    plans = [i["plan"] for i in open_issues if i.get("plan")]
    branch = ctx["branch_id"]
    disruptions = store.active_disruptions(branch) + [p["disruption"] for p in plans if p.get("disruption")]
    detours = {r for p in plans for r in p.get("via_roads", [])}
    detours |= {r for i in store.list_issues(("accepted",), branch_id=branch)
                for r in (i.get("plan") or {}).get("via_roads", [])}
    fmap = live_map.build(partners, store.deliveries_df(branch_id=branch), ctx["roads"], disruptions, detours,
                          risk_labels_now(open_issues), selected=st.session_state.get("selected_partner"),
                          dark=ui.is_dark())
    out = st_folium(fmap, height=height, use_container_width=True, key=key,
                    returned_objects=["last_object_clicked_tooltip"])
    tip = (out or {}).get("last_object_clicked_tooltip")
    by_tip = {live_map.partner_tooltip(p): p["partner_id"] for p in partners.to_dict("records")}
    if tip and tip != st.session_state.get(f"_last_tip_{key}"):
        st.session_state[f"_last_tip_{key}"] = tip
        if tip in by_tip and by_tip[tip] != st.session_state.get("selected_partner"):
            st.session_state["selected_partner"] = by_tip[tip]
            st.rerun()
    st.caption("Tap a partner (initials) for details. Red dashed = blocked road · green = detour · "
               "coloured dots = deliveries at risk.")


def partner_picker(ctx):
    partners = ctx["partners"]
    selected = st.session_state.get("selected_partner")
    options = partners["partner_id"].tolist()
    vehicles = dict(zip(partners["partner_id"], partners["vehicle_id"]))
    pick = st.selectbox("Delivery Partner", options, index=options.index(selected) if selected in options else None,
                        format_func=lambda pid: f"{ctx['partner_names'][pid]} · {pid} · {vehicles[pid]}",
                        placeholder="Choose a delivery partner", label_visibility="collapsed")
    if pick and pick != selected:
        st.session_state["selected_partner"] = pick
        st.rerun()


def partner_panel(ctx, pid):
    p = store.get_partner(pid, ctx["branch_id"]) if pid else None
    if p is None:
        st.info("Tap a delivery partner on the map or in the table.", icon=":material/touch_app:")
        return
    with st.container(border=True):
        st.markdown(ui.person(p["name"], f"{p['partner_id']} · {p['vehicle_type'].title()} · {p['reg_no']} · "
                                         f"near {p['area']}", ui.STATUS[ui.partner_state(p["status"])][2]),
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
        stops = store.deliveries_df(p["vehicle_id"], branch_id=ctx["branch_id"])
        if len(stops):
            view = stops[["stop_order", "customer", "address_area", "priority", "planned_eta", "deadline", "status"]]
            st.dataframe(view.rename(columns={"stop_order": "#", "customer": "Customer", "address_area": "Area",
                                              "priority": "Priority", "planned_eta": "ETA", "deadline": "Due",
                                              "status": "Status"}),
                         hide_index=True, width="stretch", height=min(38 * (len(view) + 1) + 3, 280))
        else:
            st.caption("No deliveries assigned.")
        mine = [i for i in ctx["open_issues"] if i["partner_id"] == pid]
        if mine and st.button(f"Review issue #{mine[0]['issue_id']}", key=f"review_{pid}",
                              icon=":material/report:", width="stretch"):
            go("disruptions")
        active = st.toggle("Account active", value=bool(p["account_active"]), key=f"partner_active_{pid}",
                           help="A deactivated delivery partner is signed out and cannot sign in.")
        if active != bool(p["account_active"]):
            admin.set_partner_active(ctx["actor"], pid, active)
            st.toast(f"{p['name']} {'activated' if active else 'deactivated'}")
            st.rerun()


def team_table(ctx):
    partners = ctx["partners"]
    search_col, status_col = st.columns([2, 3], vertical_alignment="bottom")
    query = search_col.text_input("Search", placeholder="Search name, ID, vehicle or area",
                                  label_visibility="collapsed")
    statuses = status_col.pills("Status", list(ui.PARTNER_STATUS), selection_mode="multi",
                                format_func=lambda s: ui.PARTNER_STATUS[s][0], label_visibility="collapsed")
    view = partners.copy()
    if query:
        hay = (view["name"] + " " + view["partner_id"] + " " + view["vehicle_id"] + " " + view["reg_no"] + " "
               + view["area"]).str.lower()
        view = view[hay.str.contains(query.lower(), regex=False)]
    if statuses:
        view = view[view["status"].isin(statuses)]
    view = view.assign(status_text=view["status"].map(lambda s: ui.PARTNER_STATUS.get(s, (s,))[0]),
                       progress=(view["delivered"] / view["assigned"].where(view["assigned"] > 0)).fillna(0))
    columns = {"partner_id": "Partner ID", "name": "Name", "status_text": "Status", "vehicle_id": "Vehicle",
               "reg_no": "Reg. no", "vehicle_type": "Type", "area": "Near", "assigned": "Assigned",
               "delivered": "Delivered", "pending": "Pending", "progress": "Progress", "urgent": "Urgent",
               "next_stop": "Next stop", "next_eta": "Next ETA", "open_issues": "Open issues", "phone": "Phone",
               "shift": "Shift", "rating": "Rating"}
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
    st.download_button("Download delivery partners (CSV)",
                       view[list(columns)].rename(columns=columns).to_csv(index=False),
                       "ripple-delivery-partners.csv", "text/csv", icon=":material/download:")


# ---------------------------------------------------------------- disruptions
@st.dialog("Log an issue", width="large")
def log_issue_dialog(ctx):
    st.caption("For problems you hear about by phone or see yourself. Pick who is affected, or Operations desk.")
    reporter = st.selectbox("Reported by", ["OPS"] + ctx["partners"]["partner_id"].tolist(),
                            format_func=lambda pid: "Operations desk" if pid == "OPS"
                            else f"{ctx['partner_names'][pid]} · {pid}")
    issue_id = report_form(reporter, ctx["branch_id"], prefix=f"mgr_{reporter}", source="manager")
    if issue_id:
        st.rerun()


def correct_issue(ctx, issue):
    problem, road_names = issue["problem"], ctx["road_names"]
    types = list(issues.QUICK_TYPES) + ["protest"]
    with st.form(f"correct_{issue['issue_id']}", border=False):
        c1, c2 = st.columns(2)
        dtype = c1.selectbox("Type", types, index=types.index(problem["type"]) if problem["type"] in types else 0,
                             format_func=issues.type_label)
        road_ids = list(road_names)
        road = c2.selectbox("Road", road_ids,
                            index=road_ids.index(problem["road_id"]) if problem.get("road_id") in road_ids else None,
                            format_func=road_names.get, placeholder="Choose the road")
        c3, c4 = st.columns(2)
        severity = c3.selectbox("Severity", SEVERITIES, index=SEVERITIES.index(problem.get("severity", "medium")))
        minutes = c4.number_input("Duration (min)", 0, 600, int(problem.get("duration_min") or 0), step=15)
        if st.form_submit_button("Save and re-plan", type="primary", width="stretch"):
            operations.edit_problem(issue["issue_id"], branch_id=ctx["branch_id"], type=dtype, road_id=road,
                                    severity=severity, duration_min=int(minutes))
            st.rerun()


def issue_card(ctx, issue, compact=False):
    """compact=True: no inner expanders/maps (used inside expanders)."""
    problem, plan = issue["problem"] or {}, issue.get("plan") or {}
    who = ctx["partner_names"].get(issue["partner_id"], "Operations desk")
    if issue["partner_id"] in ctx["partner_names"]:
        who = f"{who} ({issue['partner_id']})"
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
                ("Where", escape(problem.get("road_name") or "not sure")
                 + (f"<br><small>near {escape(place)}</small>" if place else "")),
                ("How long", f"{minutes} min" if minutes else "—"),
                ("Confidence", f"{int(100 * float(problem.get('confidence', 0)))}%"),
            ]), unsafe_allow_html=True)
            if issue["status"] in store.OPEN_ISSUE_STATUSES:
                with st.popover("Correct it", icon=":material/edit:", width="stretch"):
                    correct_issue(ctx, issue)

        with plan_col:
            if plan.get("kind") == "needs_location":
                st.warning("The report doesn't say where. Use **Correct it** to pick the road; the plan appears "
                           "right away.", icon=":material/location_off:")
            elif plan:
                st.markdown(f"**Impact** · {plan.get('headline', '')}")
                ba = plan.get("before_after") or {}
                if ba:
                    ui.before_after([("Missed deadlines", ba["misses_before"], ba["misses_after"]),
                                     ("Delay (min)", ba["delay_before"], ba["delay_after"])])
                if plan.get("actions"):
                    st.markdown("".join(ui.rec_card(a) for a in plan["actions"][:5]), unsafe_allow_html=True)
                if issue["status"] == "analysed":
                    accept_col, reject_col = st.columns([2, 1])
                    if accept_col.button("Accept plan", type="primary", key=f"accept_{issue['issue_id']}",
                                         icon=":material/check_circle:", width="stretch"):
                        st.toast(operations.accept(issue["issue_id"], decided_by=st.session_state.get(
                            "display_name", "Branch admin"), branch_id=ctx["branch_id"]), icon=":material/check_circle:")
                        st.rerun()
                    with reject_col.popover("Reject", width="stretch"):
                        reason = st.text_input("Why?", key=f"why_{issue['issue_id']}",
                                               placeholder="e.g. Road already clear")
                        if st.button("Reject issue", key=f"reject_{issue['issue_id']}", width="stretch"):
                            operations.reject(issue["issue_id"], reason or "Not needed",
                                              st.session_state.get("display_name", "Branch admin"),
                                              branch_id=ctx["branch_id"])
                            st.rerun()
                elif issue.get("decision_note"):
                    st.caption(f"{issue['decision_note']} at {issue.get('decided_at', '')}")

        if plan.get("risk") and not compact:
            with st.expander("Deliveries at risk, map and how the delay spreads"):
                risk = pd.DataFrame(plan["risk"])
                show = risk[["risk_label", "delivery_id", "customer", "priority", "vehicle_id", "planned_eta",
                             "new_eta", "deadline", "slack_min", "reason"]]
                st.dataframe(show.rename(columns={"risk_label": "Risk", "delivery_id": "ID", "customer": "Customer",
                                                  "priority": "Priority", "vehicle_id": "Vehicle",
                                                  "planned_eta": "Planned", "new_eta": "New ETA", "deadline": "Due",
                                                  "slack_min": "Slack (min)", "reason": "Why"})
                             .style.map(lambda v: f"color: {ui.RISK_HEX.get(v, 'inherit')}; font-weight: 600",
                                        subset=["Risk"]),
                             hide_index=True, width="stretch")
                small_map = live_map.build(ctx["partners"], store.deliveries_df(branch_id=ctx["branch_id"]),
                                           ctx["roads"], [plan["disruption"]],
                                           plan.get("via_roads", []),
                                           dict(zip(risk["delivery_id"], risk["risk_label"])), dark=ui.is_dark())
                st_folium(small_map, height=360, use_container_width=True, key=f"issue_map_{issue['issue_id']}",
                          returned_objects=[])
                st.plotly_chart(render_graph(build_graph(plan["disruption"], risk, store.snapshot(ctx["branch_id"]))),
                                width="stretch")
        if plan.get("actions") and not compact:
            with st.expander("Messages that will be sent" if issue["status"] == "analysed" else "Messages sent"):
                for action in plan["actions"]:
                    for message in action.get("messages", []):
                        st.markdown(f"**To {message['to']}**")
                        st.code(message["text"], language=None, wrap_lines=True)


def activity_feed(ctx, limit=60):
    icons = {"issue": ":material/report:", "ai": ":material/psychology:", "decision": ":material/gavel:",
             "delivery": ":material/package_2:", "edit": ":material/edit:", "system": ":material/settings:"}
    for event in store.events(limit, branch_id=ctx["branch_id"]).to_dict("records"):
        st.markdown(f"{icons.get(event['kind'], ':material/info:')} `{event['created_at']}` {event['text']}")
