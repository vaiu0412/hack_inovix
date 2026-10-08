"""Today: instructions from operations, the next stop and progress – for the logged-in partner only."""
from html import escape

import streamlit as st

from modules import guards, partner_scope as scope, ui

guards.require_role("partner")
dp_id = guards.dp_id()  # from the login session only
branch = guards.branch_id()  # from the validated session only
profile = scope.get_partner_profile(dp_id, branch)
ui.header(f"Hi {profile['name'].split()[0]} 👋", f"{profile['vehicle_type'].title()} {profile['reg_no']} · "
                                                 f"shift {profile['shift']}")
ui.live_updates()

choices = ["on_duty", "on_break"] + (["standby"] if profile["status"] == "standby" else [])
status = st.segmented_control("My status", choices, default=profile["status"] if profile["status"] in choices else None,
                              format_func=lambda s: ui.PARTNER_STATUS[s][0], label_visibility="collapsed",
                              width="stretch")
if status and status != profile["status"]:
    scope.set_status(dp_id, branch, status)
    st.rerun()

# ---------------------------------------------------------------- instructions from operations
unread = scope.get_partner_notifications(dp_id, branch, unread_only=True)
if unread:
    with st.container(border=True):
        st.markdown(f":material/notifications_active: **New instructions** · {len(unread)}")
        for m in unread[:4]:
            st.markdown(f"<small>{m['created_at']}</small><br>{escape(m['text'])}", unsafe_allow_html=True)
        if st.button("Got it", type="primary", icon=":material/done_all:", width="stretch"):
            scope.mark_notifications_read(dp_id, branch)
            st.rerun()

# ---------------------------------------------------------------- progress + next stop
deliveries = scope.get_partner_deliveries(dp_id, branch)
todo = deliveries[~deliveries["status"].isin(["delivered", "failed"])].sort_values("eta_min")
if len(deliveries):
    done = int((deliveries["status"] == "delivered").sum())
    st.progress(done / len(deliveries), text=f"{done} of {len(deliveries)} delivered")

if len(todo):
    nxt = todo.iloc[0]
    with st.container(border=True):
        st.caption(f"Next stop · {len(todo)} left")
        st.markdown(f"#### {nxt['customer']}")
        badges = ui.badge(nxt["priority"].capitalize(), "rp-critical" if nxt["priority"] == "medical"
                          else "rp-high" if nxt["priority"] == "perishable" else "rp-neutral")
        if nxt["note"]:
            badges += " " + ui.badge(str(nxt["note"]).capitalize(), "rp-brand")
        if nxt["risk"]:
            badges += " " + ui.risk_badge(nxt["risk"])
        st.markdown(f"{escape(nxt['address_area'])} &nbsp; {badges}", unsafe_allow_html=True)
        st.markdown(ui.kv([("ETA", nxt["planned_eta"]), ("Due by", nxt["deadline"]),
                           ("Order", escape(nxt["delivery_id"])),
                           ("Customer", f"<a href='tel:{escape(nxt['customer_phone'])}'>Call</a>")]),
                    unsafe_allow_html=True)
        done_col, problem_col = st.columns(2)
        if done_col.button("Delivered", type="primary", icon=":material/check:", width="stretch"):
            scope.mark_delivered(dp_id, branch, nxt["delivery_id"])
            st.toast(f"{nxt['customer']} marked delivered", icon=":material/check:")
            st.rerun()
        if problem_col.button("Report a problem", icon=":material/report:", width="stretch"):
            st.switch_page(guards.PARTNER_PAGES["report"])
else:
    with st.container(border=True):
        if len(deliveries):
            st.markdown(":material/task_alt: **All stops done.** Great work today.")
        else:
            st.markdown(":material/hourglass_empty: **No deliveries yet.** You're on standby – when operations "
                        "sends you work, it appears here with an instruction.")

# ---------------------------------------------------------------- latest report
reports = scope.get_partner_incidents(dp_id, branch)
if reports:
    latest = reports[0]
    with st.container(border=True):
        st.markdown(f"Your latest report: {escape(latest['summary'] or '')} &nbsp; {ui.issue_badge(latest['status'])}",
                    unsafe_allow_html=True)
        if latest["status"] == "accepted" and latest["headline"]:
            st.caption(f"Handled · {latest['headline']}")
