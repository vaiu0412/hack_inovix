"""Building blocks shared by the Branch Admin pages. Everything is scoped to the signed-in
admin's branch: ctx["branch_id"] comes from the validated session only."""
from html import escape

import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

from modules import admin, assign, guards, issues, live_map, operations, predict, store, tracking, ui
from modules.data_loader import load_all
from modules.graph_viz import build_graph, render_graph
from modules.parser import SEVERITIES, llm_status
from modules.report_ui import report_form


def context():
    """Data every branch admin page needs, read once per run – own branch only."""
    branch = guards.branch_id()
    roads = load_all()["roads"]
    partners = store.partners_df(branch)
    ctx = {
        "roads": roads, "road_names": dict(zip(roads["road_id"], roads["name"])), "partners": partners,
        "partner_names": dict(zip(partners["partner_id"], partners["name"])),
        "open_issues": store.list_issues(store.OPEN_ISSUE_STATUSES, branch_id=branch),
        "branch_id": branch, "actor": guards.current_user(),
    }
    ctx["states"] = partner_states(ctx)
    return ctx


def go(page_key):
    """Open another Branch Admin page by its key."""
    st.switch_page(guards.BRANCH_PAGES[page_key])


def short_road(name):
    """Shorter road name for tight spaces ('Avinashi Road' -> 'Avinashi Rd')."""
    return str(name or "").replace(" Road", " Rd").replace(" Stretch", "")


def risk_labels_now(open_issues):
    """Delivery -> risk label from every plan still waiting for a decision."""
    labels = {}
    for issue in open_issues:
        for row in (issue.get("plan") or {}).get("risk", []):
            labels.setdefault(row["delivery_id"], row["risk_label"])
    return labels


def kpi_tiles(ctx):
    """Six cards: Partners active, Deliveries, Delayed, Critical, Open alerts, Free vehicles."""
    k = operations.kpis(ctx["branch_id"])
    ui.kpi_cards([
        ("groups", k["on_duty"], "Partners active", f"of {k['partners']}", "navy"),
        ("package_2", k["deliveries"], "Deliveries", f"{k['delivered']} done"
         + (f" · {k['unassigned']} new" if k.get("unassigned") else ""), None),
        ("schedule", k["delayed"], "Delayed", "at risk now" if k["delayed"] else "on time", "delayed"),
        ("emergency", k["critical"], "Critical", "act now" if k["critical"] else
         f"{k['deadlines_saved']} saved today" if k["deadlines_saved"] else "none", "critical"),
        ("notifications_active", k["open_issues"], "Open alerts",
         "needs review" if k["open_issues"] else "all clear", "critical" if k["open_issues"] else "normal"),
        ("local_shipping", k["free_vehicles"], "Free vehicles", "ready", "normal"),
    ])


def alert_line(ctx, issue):
    """'DP102 · Accident · Avinashi Rd · 9 deliveries hit'"""
    problem, plan = issue.get("problem") or {}, issue.get("plan") or {}
    who = issue["partner_id"] if issue["partner_id"] in ctx["partner_names"] else "Desk"
    parts = [who, issues.type_label(problem.get("type"))]
    if problem.get("road_name"):
        parts.append(short_road(problem["road_name"]))
    hit = (plan.get("summary") or {}).get("affected_deliveries")
    if hit:
        parts.append(f"{hit} deliveries hit")
    elif plan.get("kind") == "needs_location":
        parts.append("needs place")
    return " · ".join(parts)


def alert_banner(ctx):
    """Only when an alert is open: red banner + Review."""
    open_issues = ctx["open_issues"]
    if not open_issues:
        return
    more = f'<span class="sep">·</span> +{len(open_issues) - 1} more' if len(open_issues) > 1 else ""
    with st.container(key="alert_banner", horizontal=True, vertical_alignment="center"):
        st.markdown(f'<div class="dp-alert">🔴 {escape(alert_line(ctx, open_issues[0]))} {more}</div>',
                    unsafe_allow_html=True)
        if st.button("Review", type="primary", key="alert_review", icon=":material/arrow_forward:"):
            go("disruptions")


def at_risk_rows(ctx, limit=5):
    """The most urgent at-risk deliveries for the 'At risk now' list."""
    rows = []
    drivers = dict(zip(ctx["partners"]["vehicle_id"], ctx["partners"]["partner_id"]))
    order = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
    for issue in ctx["open_issues"]:
        rows += (issue.get("plan") or {}).get("risk", [])
    rows = sorted({r["delivery_id"]: r for r in rows}.values(), key=lambda r: (order.get(r["risk_label"], 9),
                                                                               r["slack_min"]))
    html = []
    for r in rows[:limit]:
        timing = f"late {-r['slack_min']} min" if r["slack_min"] < 0 else f"{r['slack_min']} min left"
        html.append(f"<div class='dp-row'><div class='main'><b>{escape(r['customer'])}</b><small>"
                    f"{escape(r['priority'].capitalize())} · {drivers.get(r['vehicle_id'], r['vehicle_id'])} · "
                    f"due {r['deadline']}</small></div><div class='end'>{ui.risk_badge(r['risk_label'])}"
                    f"<br><small>{timing}</small></div></div>")
    return "".join(html)


def likely_late_card(ctx, limit=5):
    """Proactive list from the delay model – before anyone reports a problem – with today's weather switch
    (or the live OpenWeatherMap reading when a key is set)."""
    from modules import realtime
    from services import weather as weather_feed

    weather = predict.weather_now()
    live = realtime.weather_status() if weather_feed.configured() else None
    if live:
        st.caption(f":material/rainy: Live: {predict.WEATHER_LABEL[live['weather']]} · {live['rain_mm']} mm/h · "
                   f"OpenWeatherMap {live['updated_at'][11:16]}")
    else:
        pick = st.segmented_control("Weather", list(predict.WEATHER), default=weather, key="weather_pick",
                                    format_func=lambda w: {"clear": "☀️ Clear", "light_rain": "🌦️ Light rain",
                                                           "heavy_rain": "⛈️ Heavy rain"}[w],
                                    label_visibility="collapsed")
        if pick and pick != weather:
            predict.set_weather(ctx["actor"], pick)
            st.rerun()
    preds = predict.for_branch(ctx["branch_id"])
    deliveries = store.deliveries_df(branch_id=ctx["branch_id"]).set_index("delivery_id")
    drivers = dict(zip(ctx["partners"]["vehicle_id"], ctx["partners"]["partner_id"]))
    top = sorted(preds.items(), key=lambda kv: -kv[1]["p_late"])[:limit]
    late = sum(1 for p in preds.values() if p["p_late"] >= predict.LATE_AT)
    st.markdown(f"<p class='dp-small' style='margin:4px 0 6px'>{late} of {len(preds)} open stops likely late"
                f"</p>", unsafe_allow_html=True)
    rows = []
    for delivery_id, p in top:
        d = deliveries.loc[delivery_id]
        rows.append(f"<div class='dp-row'><div class='main'><b>{escape(delivery_id)} · {escape(d['customer'])}</b>"
                    f"<small>{drivers.get(d['vehicle_id'], d['vehicle_id'])} · ETA {d['planned_eta']} · due "
                    f"{d['deadline']} · +{max(p['delay_min'], 0):.0f} min</small><small>{ui.late_badge(p)}</small>"
                    f"</div></div>")
    st.markdown("".join(rows) or "<p class='dp-small'>No open stops.</p>", unsafe_allow_html=True)
    st.caption(f":material/model_training: {predict.summary_line()}"
               + ("" if live else " · weather is a demo setting"))


def ai_status_line():
    """One caption saying which AI engine is active, or rules mode without a key."""
    ai = llm_status()
    if not ai["available"]:
        st.caption(":material/smart_toy: AI: rules mode (no key).")
    elif ai["error"] and (not ai["ok_at"] or ai["error_at"] >= ai["ok_at"]):
        st.caption(f":material/smart_toy: AI: rules mode since {ai['error_at']}.")
    elif ai["ok_at"]:
        st.caption(f":material/smart_toy: AI: {ai['provider']} · last answer {ai['ok_at']}")
    else:
        st.caption(":material/smart_toy: AI: ready.")


# ---------------------------------------------------------------- map + partners
RISK_ORDER = {"Critical": 3, "High": 2, "Medium": 1, "Low": 0}


def partner_states(ctx):
    """partner_id -> normal / delayed / critical / available / break / off (same colours everywhere).
    Critical if they reported an open alert or carry a Critical delivery; Delayed for High/Medium risk."""
    worst = {}
    for issue in ctx["open_issues"]:
        for row in (issue.get("plan") or {}).get("risk", []):
            if RISK_ORDER.get(row["risk_label"], 0) > RISK_ORDER.get(worst.get(row["vehicle_id"]), -1):
                worst[row["vehicle_id"]] = row["risk_label"]
    reporters = {i["partner_id"] for i in ctx["open_issues"]}
    states = {}
    for p in ctx["partners"].to_dict("records"):
        state = ui.partner_state(p["status"], worst.get(p["vehicle_id"]))
        if p["partner_id"] in reporters and state in ("normal", "delayed"):
            state = "critical"
        states[p["partner_id"]] = state
    return states


def map_layers(ctx):
    """Blocked roads (open + accepted alerts), detours and risk labels for this branch."""
    branch, open_issues = ctx["branch_id"], ctx["open_issues"]
    plans = [i["plan"] for i in open_issues if i.get("plan")]
    disruptions = store.active_disruptions(branch) + [p["disruption"] for p in plans if p.get("disruption")]
    detours = {r for p in plans for r in p.get("via_roads", [])}
    detours |= {r for i in store.list_issues(("accepted",), branch_id=branch)
                for r in (i.get("plan") or {}).get("via_roads", [])}
    return disruptions, detours, risk_labels_now(open_issues)


def live_map_view(ctx, height=620, key="live_map", filters=True):
    """Filters above the map, a shimmer skeleton while it loads, click a vehicle -> selected partner."""
    partners = ctx["partners"]
    states = ctx.get("states") or partner_states(ctx)
    view = partners
    focus = False
    if filters:
        kinds = sorted(partners["vehicle_type"].unique())
        ui.restore_pref(f"{key}_status", ["normal", "delayed", "critical", "available", "break"], multi=True)
        ui.restore_pref(f"{key}_kind", kinds, multi=True)
        ui.restore_pref(f"{key}_road", [None] + list(ctx["road_names"]))
        ui.restore_pref(f"{key}_focus", [True, False])
        with st.container(horizontal=True, vertical_alignment="center", gap="small"):
            status_pick = st.pills("Status", ["normal", "delayed", "critical", "available", "break"],
                                   selection_mode="multi", format_func=ui.status_text, key=f"{key}_status",
                                   label_visibility="collapsed")
            kind_pick = st.pills("Vehicle", kinds, selection_mode="multi", key=f"{key}_kind",
                                 format_func=lambda k: f"{ui.VEHICLE_EMOJI.get(k, '')} {k.title()}",
                                 label_visibility="collapsed")
            names = ctx["road_names"]
            road_pick = st.selectbox("Route", [None] + list(names), key=f"{key}_road", label_visibility="collapsed",
                                     format_func=lambda r: "All routes" if r is None else names[r], width=200)
            if ctx["open_issues"]:  # only when there is something to focus on (no dead controls)
                focus = st.toggle("Focus alerts", key=f"{key}_focus")
        if status_pick:
            view = view[view["partner_id"].map(states).isin(status_pick)]
        if kind_pick:
            view = view[view["vehicle_type"].isin(kind_pick)]
        if road_pick:
            view = view[view["route_roads"].fillna("").str.split("|").apply(lambda rs: road_pick in rs)]
    deliveries = store.deliveries_df(branch_id=ctx["branch_id"])
    deliveries = deliveries[deliveries["vehicle_id"].isin(view["vehicle_id"]) | deliveries["vehicle_id"].isna()]
    disruptions, detours, risk = map_layers(ctx)

    holder = st.empty()
    holder.markdown(ui.skeleton(height), unsafe_allow_html=True)
    fmap = live_map.build(view, deliveries, ctx["roads"], disruptions, detours, risk,
                          selected=st.session_state.get("selected_partner"), states=states,
                          focus=True if focus else None, trails=tracking.trails(ctx["branch_id"]))
    with holder.container():
        out = st_folium(fmap, height=height, use_container_width=True, key=key,
                        returned_objects=["last_object_clicked_tooltip"])
    tip = (out or {}).get("last_object_clicked_tooltip")
    by_tip = {live_map.partner_tooltip(p, states.get(p["partner_id"])): p["partner_id"]
              for p in partners.to_dict("records")}
    if tip and tip != st.session_state.get(f"_last_tip_{key}"):
        st.session_state[f"_last_tip_{key}"] = tip
        if tip in by_tip and by_tip[tip] != st.session_state.get("selected_partner"):
            st.session_state["selected_partner"] = by_tip[tip]
            st.rerun()


def partner_picker(ctx):
    """Select box to focus the map and side panel on one partner."""
    partners = ctx["partners"]
    selected = st.session_state.get("selected_partner")
    options = partners["partner_id"].tolist()
    pick = st.selectbox("Find partner", options, index=options.index(selected) if selected in options else None,
                        format_func=lambda pid: f"{pid} · {ctx['partner_names'][pid]}",
                        placeholder="Find partner", label_visibility="collapsed")
    if pick and pick != selected:
        st.session_state["selected_partner"] = pick
        st.rerun()


def partner_panel(ctx, pid):
    """Right-side details for one partner: short labels, numbers, status colour."""
    p = store.get_partner(pid, ctx["branch_id"]) if pid else None
    if p is None:
        with ui.card("partner_panel"):
            ui.empty_state("touch_app", "Tap a vehicle on the map.")
        return
    states = ctx.get("states") or partner_states(ctx)
    state = states.get(pid, "normal")
    mine = [i for i in ctx["open_issues"] if i["partner_id"] == pid]
    route = " → ".join(ctx["road_names"].get(r, r) for r in str(p.get("route_roads") or "").split("|") if r)
    with ui.card("partner_panel"):
        st.markdown(ui.person(p["name"], f"{p['partner_id']} · {ui.VEHICLE_EMOJI.get(p['vehicle_type'], '')} "
                                         f"{p['vehicle_type'].title()}", ui.STATUS[state][2])
                    + f"<div style='margin-top:10px'>{ui.pill_html(state)}</div>", unsafe_allow_html=True)
        st.markdown(ui.kv([
            ("Vehicle", f"{escape(p['vehicle_id'])} · {escape(p['reg_no'])}"),
            ("Location", f"{escape(p['area'])}<br><small>"
                         f"{escape(tracking.seen_text(tracking.last_seen(ctx['branch_id']).get(pid)))}</small>"),
            ("Deliveries", f"{p['delivered']} done · {p['pending']} left"),
            ("Next ETA", escape(str(p["next_eta"]))),
            ("Route", escape(route or "—")),
            ("Issue", ui.pill_html("critical", f"#{mine[0]['issue_id']}") if mine else "None"),
        ]), unsafe_allow_html=True)
        call, review = st.columns(2)
        call.link_button("Call", f"tel:{p['phone']}", icon=":material/call:", width="stretch")
        if mine and review.button("Review", key=f"review_{pid}", icon=":material/report:", width="stretch",
                                  type="primary"):
            go("disruptions")
        with st.popover("Link Google", icon=":material/alternate_email:", width="stretch"), \
                st.form(f"link_google_{pid}", border=False):
            email = st.text_input("Email", value=p.get("email") or "", placeholder="name@gmail.com",
                                  help="Used for sign-in, OTP and Google")
            if st.form_submit_button("Save", type="primary", width="stretch"):
                try:
                    admin.set_partner_email(ctx["actor"], pid, email)
                    st.toast("Email saved.", icon=":material/check:")
                    st.rerun()
                except (ValueError, PermissionError) as error:
                    st.error(str(error))
        stops = store.deliveries_df(p["vehicle_id"], branch_id=ctx["branch_id"])
        if len(stops):
            risk = risk_labels_now(ctx["open_issues"])
            status = stops.apply(lambda d: ui.status_text("done") if d["status"] == "delivered"
                                 else ui.status_text(ui.risk_state(risk.get(d["delivery_id"], "Low"))), axis=1)
            view = stops.assign(Status=status)
            st.dataframe(view[["stop_order", "customer", "planned_eta", "deadline", "Status"]].rename(
                columns={"stop_order": "#", "customer": "Customer", "planned_eta": "ETA", "deadline": "Due"}),
                hide_index=True, width="stretch", height=min(36 * (len(view) + 1) + 3, 260))
        open_stops = stops[~stops["status"].isin(store.ACTIVE_DONE)] if len(stops) else stops
        if len(open_stops):
            move = st.selectbox("Move work", open_stops["delivery_id"].tolist(), key=f"move_{pid}", index=None,
                                placeholder="Move a delivery",
                                format_func=lambda d: f"{d} · {open_stops.set_index('delivery_id').loc[d, 'customer']}")
            if move:
                reassign_controls(ctx, open_stops.set_index("delivery_id").loc[move].to_dict() | {"delivery_id": move})
        active = st.toggle("Account active", value=bool(p["account_active"]), key=f"partner_active_{pid}")
        if active != bool(p["account_active"]):
            admin.set_partner_active(ctx["actor"], pid, active)
            st.toast(f"{p['name']} {'activated' if active else 'deactivated'}.")
            st.rerun()


def add_basemap(m):
    """Add the default basemap (no layer switcher) to a small map."""
    return live_map.add_tiles(m, switcher=False)


def order_card(ctx, order, found):
    """One unassigned order: what, where, by when – the best match with its reason, Assign best / Choose."""
    with ui.card(f"order_{order['delivery_id']}"):
        due = order["deadline"]
        st.markdown(f"<p class='dp-h3'>{escape(order['delivery_id'])} · {escape(order['customer'])}</p>"
                    f"<p class='dp-small'>{escape(order['address_area'])} · {escape(order['priority'].capitalize())} · "
                    f"{escape(str(order.get('package_size') or 'small').capitalize())} · due {due}</p>",
                    unsafe_allow_html=True)
        if order.get("offer_status") == "declined":
            st.markdown(f"{ui.pill_html('critical', 'Declined')} <span class='dp-small'>back from the partner – "
                        "pick someone else</span>", unsafe_allow_html=True)
        best = found[0] if found else None
        if best:
            st.markdown(
                f"<div style='margin:6px 0 10px'>{ui.pill_html('normal' if best['feasible'] else 'delayed', 'Best')}"
                f" <span class='dp-small'>{escape(best['reason'])}</span></div>",
                unsafe_allow_html=True,
            )
        else:
            st.markdown("<p class='dp-small'>No partner fits right now.</p>", unsafe_allow_html=True)
        go_col, pick_col = st.columns(2)
        if best and go_col.button("Assign best", type="primary", icon=":material/bolt:", width="stretch",
                                  key=f"best_{order['delivery_id']}"):
            result = assign.assign(ctx["actor"], order["delivery_id"], best["partner_id"], reason="Best match")
            st.session_state["assign_msg"] = f"{order['delivery_id']} → {best['partner_id']} · ETA {result['eta']}."
            st.rerun()
        with pick_col.popover("Choose partner", icon=":material/person_search:", width="stretch"):
            choose_partner_form(ctx, order, found, verb="Assign")


def choose_partner_form(ctx, order, found, verb="Assign"):
    """Form to pick a partner by hand for an order, with each option's reason."""
    options = [c for c in found if c["vehicle_id"] != order.get("vehicle_id")]
    if not options:
        st.caption("No other partner fits.")
        return
    reasons = {c["partner_id"]: c["reason"] for c in options}
    with st.form(f"choose_{verb}_{order['delivery_id']}", border=False):
        pick = st.selectbox("Partner", list(reasons), format_func=reasons.get)
        reason = st.selectbox("Reason", assign.REASONS) if verb != "Assign" else "Chosen by admin"
        if st.form_submit_button(verb, type="primary", width="stretch"):
            try:
                result = assign.assign(ctx["actor"], order["delivery_id"], pick, reason=reason)
                st.session_state["assign_msg"] = f"{order['delivery_id']} → {pick} · ETA {result['eta']}."
                st.toast(f"{order['delivery_id']} → {pick}.", icon=":material/check:")
                st.rerun()
            except (ValueError, PermissionError) as error:
                st.error(str(error))


def reassign_controls(ctx, delivery):
    """Reassign or unassign one open order (a reason is required)."""
    if delivery["status"] in store.ACTIVE_DONE:
        return
    found = assign.candidates(delivery, ctx["branch_id"])
    has_partner = isinstance(delivery.get("vehicle_id"), str) and bool(delivery.get("vehicle_id"))
    move_col, drop_col = st.columns(2)
    with move_col.popover("Reassign" if has_partner else "Assign", icon=":material/swap_horiz:", width="stretch"):
        choose_partner_form(ctx, delivery, found, verb="Reassign" if has_partner else "Assign")
    if has_partner:
        with drop_col.popover("Unassign", icon=":material/remove_circle:", width="stretch"), \
                st.form(f"unassign_{delivery['delivery_id']}", border=False):
            reason = st.selectbox("Reason", assign.REASONS)
            if st.form_submit_button("Unassign", width="stretch"):
                assign.unassign(ctx["actor"], delivery["delivery_id"], reason)
                st.toast(f"{delivery['delivery_id']} back in the queue.")
                st.rerun()


# ---------------------------------------------------------------- partners table
def team_table(ctx):
    """Short columns, coloured status, search + 3 filters; a selected row opens the side panel."""
    partners, states = ctx["partners"], ctx["states"]
    ui.restore_pref("team_status", ["normal", "delayed", "critical", "available", "break"], multi=True)
    ui.restore_pref("team_kind", sorted(partners["vehicle_type"].unique()), multi=True)
    ui.restore_pref("team_alerts", [True, False])
    with st.container(horizontal=True, vertical_alignment="center", gap="small"):
        query = st.text_input("Search", placeholder="Search name, ID, area", label_visibility="collapsed",
                              icon=":material/search:", width=260)
        status_pick = st.pills(
            "Status",
            ["normal", "delayed", "critical", "available", "break"],
            selection_mode="multi",
            format_func=ui.status_text,
            label_visibility="collapsed",
            key="team_status",
        )
        kind_pick = st.pills("Vehicle", sorted(partners["vehicle_type"].unique()), selection_mode="multi",
                             format_func=lambda k: f"{ui.VEHICLE_EMOJI.get(k, '')} {k.title()}",
                             label_visibility="collapsed", key="team_kind")
        alerts_only = st.toggle("Has alert", key="team_alerts")
    view = partners.assign(state=partners["partner_id"].map(states))
    if query:
        hay = (view["name"] + " " + view["partner_id"] + " " + view["vehicle_id"] + " " + view["area"]).str.lower()
        view = view[hay.str.contains(query.lower(), regex=False)]
    if status_pick:
        view = view[view["state"].isin(status_pick)]
    if kind_pick:
        view = view[view["vehicle_type"].isin(kind_pick)]
    if alerts_only:
        view = view[view["open_issues"] > 0]
    table = pd.DataFrame({
        "ID": view["partner_id"], "Name": view["name"], "Status": view["state"].map(ui.status_text),
        "Vehicle": view["vehicle_type"].map(ui.VEHICLE_EMOJI).fillna("") + " " + view["vehicle_id"],
        "Area": view["area"], "Done": view["delivered"], "Left": view["pending"], "Next ETA": view["next_eta"],
        "Phone": view["phone"],
    })
    event = st.dataframe(table, hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row",
                         key="team_table", height=min(38 * (len(table) + 1) + 3, 420))
    rows = event.selection.rows if event else []
    pid = view.iloc[rows[0]]["partner_id"] if rows else None
    if pid and pid != st.session_state.get("_last_table_pick"):
        st.session_state["_last_table_pick"] = pid
        if pid != st.session_state.get("selected_partner"):
            st.session_state["selected_partner"] = pid
            st.rerun()
    st.download_button("Download CSV", table.to_csv(index=False), "deport-partners.csv", "text/csv",
                       icon=":material/download:")


# ---------------------------------------------------------------- alerts
@st.dialog("Log issue", width="large")
def log_issue_dialog(ctx):
    """Dialog for an admin to log an issue for a partner or the operations desk."""
    reporter = st.selectbox(
        "For",
        ["OPS"] + ctx["partners"]["partner_id"].tolist(),
        format_func=lambda pid: "Ops desk" if pid == "OPS" else f"{pid} · {ctx['partner_names'][pid]}",
    )
    issue_id = report_form(reporter, ctx["branch_id"], prefix=f"mgr_{reporter}", source="manager")
    if issue_id:
        st.rerun()


def modify_form(ctx, issue, where="top"):
    """Correct what the AI understood, then the plan is rebuilt."""
    problem, road_names = issue["problem"], ctx["road_names"]
    types = list(issues.QUICK_TYPES) + ["protest"]
    with st.form(f"correct_{issue['issue_id']}_{where}", border=False):
        c1, c2 = st.columns(2)
        dtype = c1.selectbox("Type", types, index=types.index(problem["type"]) if problem["type"] in types else 0,
                             format_func=issues.type_label)
        road_ids = list(road_names)
        road = c2.selectbox("Road", road_ids,
                            index=road_ids.index(problem["road_id"]) if problem.get("road_id") in road_ids else None,
                            format_func=road_names.get, placeholder="Pick road")
        c3, c4 = st.columns(2)
        severity = c3.selectbox("Severity", SEVERITIES, index=SEVERITIES.index(problem.get("severity", "medium")),
                                format_func=str.capitalize)
        minutes = c4.number_input("Minutes", 0, 600, int(problem.get("duration_min") or 0), step=15)
        if st.form_submit_button("Save and re-plan", type="primary", width="stretch"):
            operations.edit_problem(issue["issue_id"], branch_id=ctx["branch_id"],
                                    decided_by=st.session_state.get("display_name", "Branch admin"),
                                    type=dtype, road_id=road, severity=severity, duration_min=int(minutes))
            st.rerun()


def before_after_rows(plan):
    """Before -> After numbers for the success strip (of the plan that was applied)."""
    ba = plan.get("before_after") or {}
    hit = max((plan.get("summary") or {}).get("affected_deliveries", 0), 1)
    comparison = (plan.get("optimised") or {}).get("comparison") or {}
    if plan.get("chosen") == "optimised" and comparison:
        before, after = comparison["before"], comparison["optimised"]
        return [("Missed deadlines", before["misses"], after["misses"]),
                ("Avg delay", f"+{round(before['delay'] / hit)} min", f"+{round(after['delay'] / hit)} min"),
                ("Total km", f"{before['km']:.0f}", f"{after['km']:.0f}")]
    if not ba:
        return []
    return [("Missed deadlines", ba["misses_before"], ba["misses_after"]),
            ("Avg delay", f"+{round(ba['delay_before'] / hit)} min", f"+{round(ba['delay_after'] / hit)} min"),
            ("Critical at risk", ba.get("critical_before", 0), ba.get("critical_after", 0))]


def applied_card(issue):
    """Green 'Plan applied.' card + Before -> After strip."""
    plan = issue.get("plan") or {}
    st.markdown(f'<div class="dp-success">{ui.icon("check_circle")} Plan applied.'
                f'<span class="dp-small" style="font-weight:500;margin-left:auto">#{issue["issue_id"]} · '
                f'{escape(issue.get("decided_at") or "")}</span></div>', unsafe_allow_html=True)
    rows = before_after_rows(plan)
    if rows:
        ui.before_after(rows)


def alert_steps(ctx, issue):
    """One alert in 3 steps: What changed · What's affected · What to do."""
    problem, plan = issue.get("problem") or {}, issue.get("plan") or {}
    who = ctx["partner_names"].get(issue["partner_id"])
    open_now = issue["status"] in store.OPEN_ISSUE_STATUSES

    ui.step(1, "What changed")
    said, understood = st.columns([1, 1.2], gap="medium")
    with said, ui.card(f"said_{issue['issue_id']}"):
        st.markdown(f"<p class='dp-h3'>{escape(who or 'Ops desk')} · {escape(issue['partner_id'])}</p>"
                    f"<p class='dp-small'>{escape(issue['created_at'])} · "
                    f"{'voice' if issue.get('audio') else 'typed' if issue.get('transcript') else 'quick tap'}</p>",
                    unsafe_allow_html=True)
        if issue.get("audio"):
            st.audio(issue["audio"], format="audio/wav")
        if issue.get("transcript"):
            st.markdown(f'<div class="dp-quote">“{escape(issue["transcript"])}”</div>', unsafe_allow_html=True)
    with understood, ui.card(f"understood_{issue['issue_id']}"):
        minutes = int(problem.get("duration_min") or 0)
        st.markdown(ui.kv([
            ("Type", escape(issues.type_label(problem.get("type")))),
            ("Road", escape(short_road(problem.get("road_name")) or "Not sure")),
            ("Severity", ui.severity_badge(problem.get("severity", "medium"))),
            ("Duration", f"{minutes // 60} h {minutes % 60} min".replace(" 0 min", "") if minutes >= 60
             else f"{minutes} min" if minutes else "—"),
            ("Confidence", f"{int(100 * float(problem.get('confidence', 0)))}%"),
            ("Status", ui.issue_pill(issue["status"])),
        ]), unsafe_allow_html=True)
        if open_now:
            with st.popover("Modify", icon=":material/edit:"):
                modify_form(ctx, issue)

    if plan.get("kind") == "needs_location":
        ui.step(2, "What's affected")
        st.warning("No place found. Tap Modify and pick the road.", icon=":material/location_off:")
        return
    summary = plan.get("summary") or {}
    risk = pd.DataFrame(plan.get("risk") or [])
    ba = plan.get("before_after") or {}

    ui.step(2, "What's affected")
    if plan.get("kind") == "ripple" and len(risk):
        ui.kpi_cards([
            ("package_2", int(summary.get("affected_deliveries", 0)), "Deliveries hit", None, "delayed"),
            ("local_shipping", len(summary.get("affected_vehicles", [])), "Vehicles", None, "navy"),
            ("emergency", int((risk["risk_label"] == "Critical").sum()), "Critical", None, "critical"),
            ("timer", int(ba.get("misses_before", 0)), "Will be late", "without a plan", "critical"),
        ])
        graph_col, map_col = st.columns([1.15, 1], gap="medium")
        with graph_col, ui.card(f"ripple_{issue['issue_id']}"):
            st.markdown("<p class='dp-h3'>Ripple Impact</p>", unsafe_allow_html=True)
            st.plotly_chart(render_graph(build_graph(plan["disruption"], risk, store.snapshot(ctx["branch_id"]))),
                            width="stretch", config={"displayModeBar": False}, key=f"graph_{issue['issue_id']}")
        with map_col, ui.card(f"minimap_{issue['issue_id']}"):
            small = live_map.build(ctx["partners"], store.deliveries_df(branch_id=ctx["branch_id"]), ctx["roads"],
                                   [plan["disruption"]], plan.get("via_roads", []),
                                   dict(zip(risk["delivery_id"], risk["risk_label"])), states=ctx["states"],
                                   focus=True)
            st_folium(small, height=380, use_container_width=True, key=f"issue_map_{issue['issue_id']}",
                      returned_objects=[])
        with st.expander(f"Deliveries at risk ({len(risk)})", icon=":material/list:"):
            show = risk.assign(Status=risk["risk_label"].map(lambda r: ui.status_text(ui.risk_state(r))))
            st.dataframe(show[["Status", "delivery_id", "customer", "priority", "vehicle_id", "planned_eta", "new_eta",
                               "deadline"]].rename(columns={"delivery_id": "ID", "customer": "Customer",
                                                            "priority": "Priority", "vehicle_id": "Vehicle",
                                                            "planned_eta": "Planned", "new_eta": "New ETA",
                                                            "deadline": "Due"}),
                         hide_index=True, width="stretch")
    else:
        st.markdown(f"<p class='dp-sub'>{escape(plan.get('headline', ''))}</p>", unsafe_allow_html=True)

    ui.step(3, "What to do")
    actions = plan.get("actions") or []
    if not actions:
        ui.empty_state("task_alt", "No action needed.")
    else:
        if plan.get("headline"):
            st.markdown(f"<p class='dp-sub' style='margin-bottom:8px'>{escape(plan['headline'])}</p>",
                        unsafe_allow_html=True)
        cols = st.columns(2, gap="small")
        can_skip = issue["status"] == "analysed" and plan.get("kind") == "ripple"
        for i, action in enumerate(actions[:6]):
            with cols[i % 2]:
                st.markdown(ui.rec_card(action), unsafe_allow_html=True)
                if can_skip:
                    seen, skip = st.columns([3, 1], vertical_alignment="center")
                    if action.get("p_source", "none") != "none":
                        seen.caption(f":material/thumb_up: Likely taken {action['p_accept']:.0%}")
                    if skip.button("Skip", key=f"skip_{issue['issue_id']}_{i}", type="tertiary",
                                   icon=":material/block:", help="Not this one – the plan is rebuilt without it"):
                        operations.skip_action(issue["issue_id"], action["action_id"],
                                               decided_by=st.session_state.get("display_name", "Branch admin"),
                                               branch_id=ctx["branch_id"])
                        st.rerun()
        if len(actions) > 6:
            with st.expander(f"All {len(actions)} actions"):
                st.markdown("".join(ui.rec_card(a) for a in actions[6:]), unsafe_allow_html=True)
        if plan.get("skipped"):
            note, undo = st.columns([3, 1], vertical_alignment="center")
            note.caption(f":material/block: {len(plan['skipped'])} skipped – the plan was rebuilt without them.")
            if issue["status"] == "analysed" and undo.button("Undo skips", key=f"unskip_{issue['issue_id']}",
                                                             type="tertiary", icon=":material/undo:"):
                operations.restore_skipped(issue["issue_id"], ctx["branch_id"])
                st.rerun()
        with st.expander("Messages to send", icon=":material/sms:"):
            for action in actions:
                for message in action.get("messages", []):
                    st.markdown(f"**To {escape(message['to'])}**")
                    st.code(message["text"], language=None, wrap_lines=True)
    choice = plan_choice(ctx, issue, plan) if actions and plan.get("kind") == "ripple" else "rules"
    if issue["status"] == "analysed":
        with st.container(horizontal=True, gap="small"):
            label = "Accept optimised plan" if choice == "optimised" else "Accept plan"
            if st.button(label, type="primary", key=f"accept_{issue['issue_id']}", icon=":material/check_circle:"):
                operations.accept(issue["issue_id"], decided_by=st.session_state.get("display_name", "Branch admin"),
                                  branch_id=ctx["branch_id"], choice=choice)
                st.session_state["last_applied"] = issue["issue_id"]
                st.toast("Optimised plan applied." if choice == "optimised" else "Plan applied.",
                         icon=":material/check_circle:")
                st.rerun()
            with st.popover("Modify", icon=":material/edit:"):
                modify_form(ctx, issue, where="actions")
            with st.popover("Reject", icon=":material/close:"), st.form(f"reject_{issue['issue_id']}", border=False):
                reason = st.text_input("Reason", key=f"why_{issue['issue_id']}", placeholder="Road clear")
                if st.form_submit_button("Reject alert", width="stretch"):  # Enter also submits
                    operations.reject(issue["issue_id"], reason or "Not needed",
                                      st.session_state.get("display_name", "Branch admin"), branch_id=ctx["branch_id"])
                    st.toast("Alert rejected.")
                    st.rerun()


def plan_choice(ctx, issue, plan):
    """Rule-based plan vs the OR-Tools optimised plan: the numbers side by side and which one to apply."""
    iid = issue["issue_id"]
    opt = plan.get("optimised") or {}
    if not opt.get("available"):
        st.caption(":material/route: Optimised plan: install OR-Tools to compare one. The rule-based plan stays.")
        return "rules"
    if opt.get("status") != "ok":
        st.caption(f":material/route: No optimised plan ({escape(str(opt.get('note') or opt.get('status')))}). "
                   "The rule-based plan stays.")
        return "rules"
    cmp = opt["comparison"]
    keys = ("misses", "delay", "km")
    better = tuple(cmp["optimised"][k] for k in keys) < tuple(cmp["rules"][k] for k in keys)
    with ui.card(f"compare_{iid}"):
        st.markdown("<p class='dp-h3'>Rule-based or optimised?</p>", unsafe_allow_html=True)
        head = "".join(f"<th>{h}</th>" for h in ("", "No action", "Rule plan", "Optimised"))
        body = ""
        for label, key, unit in (("Missed deadlines", "misses", ""), ("Total delay", "delay", " min"),
                                 ("Total km", "km", " km")):
            values = [cmp["before"][key], cmp["rules"][key], cmp["optimised"][key]]
            best = min(values[1:])
            cells = "".join(f"<td class='{'best' if i and v == best else ''}'>{v:g}{unit}</td>"
                            for i, v in enumerate(values))
            body += f"<tr><th>{label}</th>{cells}</tr>"
        st.markdown(f"<table class='dp-compare'><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>",
                    unsafe_allow_html=True)
        if better:
            rules, best = cmp["rules"], cmp["optimised"]
            gains = [text for gain, text in (
                (rules["misses"] - best["misses"], f"{rules['misses'] - best['misses']} fewer missed"),
                (rules["delay"] - best["delay"], f"{rules['delay'] - best['delay']:g} min less delay"),
                (rules["km"] - best["km"], f"{rules['km'] - best['km']:.0f} km less driving")) if gain > 0]
            st.caption(f":material/lightbulb: Optimised is better here: {', '.join(gains)}.")
        pick = st.segmented_control(  # the rule plan stays the default; the admin decides
            "Apply", ["rules", "optimised"], default="rules", key=f"choice_{iid}",
            format_func=lambda c: "Rule plan" if c == "rules" else "Optimised (OR-Tools)",
            label_visibility="collapsed")
        names = ctx["partner_names"]
        by_vehicle = dict(zip(ctx["partners"]["vehicle_id"], ctx["partners"]["partner_id"]))
        with st.expander("Optimised routes", icon=":material/route:"):
            for vehicle_id, stops in opt["routes"].items():
                if not stops:
                    continue
                who = names.get(by_vehicle.get(vehicle_id), vehicle_id)
                path = " → ".join(f"{s['delivery_id']} {s['eta']}" + (" ↩" if s["from"] != vehicle_id else "")
                                  for s in stops)
                st.markdown(f"**{escape(vehicle_id)} · {escape(who)}** <span class='dp-small'>{escape(path)}"
                            f"</span>", unsafe_allow_html=True)
            if opt.get("moves"):
                st.caption("↩ = parcel moved from another vehicle (handover).")
            if opt.get("dropped"):
                st.warning(f"Left out (back to the queue): {', '.join(opt['dropped'])}", icon=":material/warning:")
        search = "guided search" if opt.get("thorough") else "quick search"
        info, more = st.columns([3, 1.2], vertical_alignment="center")
        info.caption(f":material/memory: OR-Tools · {search} · {opt.get('seconds', 0):.2f} s · "
                     f"{len(opt.get('moves') or [])} parcels moved")
        if issue["status"] == "analysed" and not opt.get("thorough") and more.button(
                "Improve (5 s)", icon=":material/tune:", key=f"improve_{iid}", width="stretch"):
            with st.spinner("Searching for 5 seconds…"):
                operations.improve(iid, ctx["branch_id"])
            st.rerun()
    return pick or "rules"


# ---------------------------------------------------------------- history
def activity_feed(ctx, limit=60):
    """Latest issues, AI results, decisions and deliveries as a timeline."""
    icons = {"issue": "report", "ai": "psychology", "decision": "gavel", "delivery": "package_2", "edit": "edit",
             "system": "settings"}
    rows = [
        f"<div class='dp-row'><span class='dp-ico' style='color:var(--dp-muted)'>{icons.get(e['kind'], 'info')}"
        f"</span><div class='main'>{escape(e['text'])}</div><div class='end dp-small'>{escape(e['created_at'])}</div>"
        f"</div>"
        for e in store.events(limit, branch_id=ctx["branch_id"]).to_dict("records")
    ]
    st.markdown("".join(rows) or "<p class='dp-sub'>No activity yet.</p>", unsafe_allow_html=True)
