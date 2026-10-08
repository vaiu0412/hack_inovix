"""Delivery partner app – designed for a phone held in one hand."""
from html import escape

import streamlit as st

from modules import operations, store, ui
from modules.report_ui import report_form

st.set_page_config(page_title="Ripple · Partner", page_icon=":material/two_wheeler:", layout="centered")

partners = store.partners_df()
ids = partners["partner_id"].tolist()
pid = st.query_params.get("id")
if pid not in ids:
    pid = st.session_state.get("partner_id")


# ---------------------------------------------------------------- who are you?
if pid not in ids:
    ui.header("Partner app", "Who's driving today?", live=False)
    for p in partners.to_dict("records"):
        with st.container(border=True):
            info, pick = st.columns([3, 1], vertical_alignment="center")
            info.markdown(ui.person(p["name"], f"{p['vehicle_type'].title()} · {p['reg_no']}", p["status"]),
                          unsafe_allow_html=True)
            if pick.button("This is me", key=f"me_{p['partner_id']}", width="stretch"):
                st.session_state["partner_id"] = p["partner_id"]
                st.query_params["id"] = p["partner_id"]
                st.rerun()
    st.caption("Tip: each partner can bookmark their own link, for example …/partner?id=P1")
    st.stop()

st.session_state["partner_id"] = pid
st.query_params["id"] = pid
ui.live_updates()
p = store.get_partner(pid)


# ---------------------------------------------------------------- header + status
with st.container(horizontal=True, vertical_alignment="center"):
    st.markdown(ui.person(p["name"], f"{p['vehicle_type'].title()} {p['reg_no']} · shift {p['shift']}", p["status"]),
                unsafe_allow_html=True, width="stretch")
    switch = st.button("Switch", icon=":material/swap_horiz:", type="tertiary", width="content")
if switch:
    st.session_state.pop("partner_id", None)
    st.query_params.clear()
    st.rerun()

choices = ["on_duty", "on_break"] + (["standby"] if p["status"] == "standby" or p["vehicle_id"] == "V6" else [])
status = st.segmented_control("My status", choices, default=p["status"] if p["status"] in choices else None,
                              format_func=lambda s: ui.PARTNER_STATUS[s][0], label_visibility="collapsed",
                              width="stretch")
if status and status != p["status"]:
    store.set_partner_status(pid, status)
    store.log_event("system", f"{p['name']} is now {ui.PARTNER_STATUS[status][0].lower()}")
    st.rerun()


# ---------------------------------------------------------------- messages from operations
messages = store.messages_for(pid)
unread = [m for m in messages if not m["read"]]
if unread:
    with st.container(border=True):
        st.markdown(f":material/notifications_active: **From operations** · {len(unread)} new")
        for m in unread[:4]:
            st.markdown(f"<small>{m['created_at']}</small><br>{escape(m['text'])}", unsafe_allow_html=True)
        if st.button("Got it", type="primary", icon=":material/done_all:", width="stretch"):
            store.mark_messages_read(pid)
            st.rerun()


# ---------------------------------------------------------------- next stop
stops = store.deliveries_df(p["vehicle_id"]).sort_values(["status", "eta_min"])
todo = stops[~stops["status"].isin(["delivered", "failed"])].sort_values("eta_min")
risk = {}
for issue in store.list_issues(store.OPEN_ISSUE_STATUSES):
    for row in (issue.get("plan") or {}).get("risk", []):
        risk.setdefault(row["delivery_id"], row["risk_label"])

reporting = st.session_state.get("reporting", False)
if len(todo):
    nxt = todo.iloc[0]
    with st.container(border=True):
        st.caption(f"Next stop · {len(todo)} left")
        st.markdown(f"#### {nxt['customer']}")
        badges = ui.badge(nxt["priority"].capitalize(), "rp-critical" if nxt["priority"] == "medical"
                          else "rp-high" if nxt["priority"] == "perishable" else "rp-neutral")
        if nxt["note"]:
            badges += " " + ui.badge(str(nxt["note"]).capitalize(), "rp-brand")
        if nxt["delivery_id"] in risk:
            badges += " " + ui.risk_badge(risk[nxt["delivery_id"]])
        st.markdown(f"{escape(nxt['address_area'])} &nbsp; {badges}", unsafe_allow_html=True)
        st.markdown(ui.kv([("ETA", nxt["planned_eta"]), ("Due by", nxt["deadline"]),
                           ("Order", escape(nxt["delivery_id"])),
                           ("Customer", f"<a href='tel:{escape(nxt['customer_phone'])}'>Call</a>")]),
                    unsafe_allow_html=True)
        done_col, problem_col = st.columns(2)
        if done_col.button("Delivered", type="primary", icon=":material/check:", width="stretch"):
            operations.mark_delivered(nxt["delivery_id"], p["name"])
            st.toast(f"{nxt['customer']} marked delivered", icon=":material/check:")
            st.rerun()
        if problem_col.button("Report a problem", icon=":material/report:", width="stretch", disabled=reporting):
            st.session_state["reporting"] = True
            ui.pause_live_updates()
            st.rerun()
else:
    with st.container(border=True):
        if len(stops):
            st.markdown(":material/task_alt: **All stops done.** Great work today.")
        else:
            st.markdown(":material/hourglass_empty: **No deliveries yet.** You're on standby – when operations "
                        "sends you work, it appears here with a message.")
    if not reporting and st.button("Report a problem", icon=":material/report:", width="stretch"):
        st.session_state["reporting"] = True
        ui.pause_live_updates()
        st.rerun()


# ---------------------------------------------------------------- report a problem
if reporting:
    with st.container(border=True):
        st.markdown("#### Report a problem")
        issue_id = report_form(pid, prefix=f"partner_{pid}")
        if issue_id:
            st.session_state["reporting"] = False
            st.toast("Sent to operations", icon=":material/send:")
            st.rerun()
        if st.button("Cancel", width="stretch", key="cancel_report"):
            st.session_state["reporting"] = False
            ui.resume_live_updates()
            st.rerun()


# ---------------------------------------------------------------- my reports
mine = store.list_issues(partner_id=pid)[:3]
if mine:
    st.markdown("##### My reports")
    for issue in mine:
        with st.container(border=True):
            st.markdown(f"{escape(issue['summary'] or '')} &nbsp; {ui.issue_badge(issue['status'])}",
                        unsafe_allow_html=True)
            plan = issue.get("plan") or {}
            if issue["status"] == "analysed":
                st.caption(f"Sent {issue['created_at']} · operations is reviewing the AI plan")
            elif issue["status"] == "accepted":
                st.caption(f"Handled at {issue.get('decided_at', '')} · {plan.get('headline', '')}")
            elif issue["status"] == "rejected":
                st.caption(f"Reviewed: {issue.get('decision_note', '')}")
            else:
                st.caption("Operations will confirm the place")


# ---------------------------------------------------------------- my stops
st.markdown(f"##### My stops")
rows = []
for d in stops.sort_values("stop_order").to_dict("records"):
    if d["status"] == "delivered":
        tag = ui.badge("Delivered", "rp-low")
    elif d["delivery_id"] in risk:
        tag = ui.risk_badge(risk[d["delivery_id"]])
    else:
        tag = ui.badge("Pending", "rp-neutral")
    faded = " style='opacity:.55'" if d["status"] == "delivered" else ""
    rows.append(f"<div class='rp-action'{faded}><span class='rp-dot' style='background:"
                f"{'#DC2626' if d['priority'] == 'medical' else '#EA580C' if d['priority'] == 'perishable' else '#94A3B8'}'>"
                f"</span><div style='flex:1'><b>{d['stop_order']}. {escape(d['customer'])}</b> &nbsp;{tag}"
                f"<small>{escape(d['address_area'])} · ETA {d['planned_eta']} · due {d['deadline']} · {escape(d['priority'])}"
                f"</small></div></div>")
st.markdown("".join(rows) or "<small>No stops assigned.</small>", unsafe_allow_html=True)

if len(messages) > len(unread):
    with st.expander("Earlier messages"):
        for m in messages:
            if m["read"]:
                st.markdown(f"<small>{m['created_at']}</small> {escape(m['text'])}", unsafe_allow_html=True)
