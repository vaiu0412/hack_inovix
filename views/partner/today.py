"""Today: new instructions, my next stop and my progress – for the signed-in partner only."""
from html import escape

import streamlit as st

from modules import guards, partner_scope as scope, ui

guards.require_role("partner")
dp_id = guards.dp_id()  # from the validated session only
branch = guards.branch_id()
profile = scope.get_partner_profile(dp_id, branch)
ui.header(f"Hi {profile['name'].split()[0]} 👋",
          f"{ui.VEHICLE_EMOJI.get(profile['vehicle_type'], '')} {profile['reg_no']} · {profile['shift']}")

deliveries = scope.get_partner_deliveries(dp_id, branch)
worst = next((r for r in ("Critical", "High", "Medium") if r in set(deliveries["risk"])), None)
with st.container(horizontal=True, vertical_alignment="center", gap="small"):
    st.markdown(ui.pill_html(ui.partner_state(profile["status"], worst)), unsafe_allow_html=True)
    choices = ["on_duty", "on_break"] + (["standby"] if profile["status"] == "standby" else [])
    status = st.segmented_control("Status", choices, default=profile["status"] if profile["status"] in choices else None,
                                  format_func=lambda s: ui.PARTNER_STATUS[s][0], label_visibility="collapsed",
                                  key="my_status")
if status and status != profile["status"]:
    scope.set_status(dp_id, branch, status)
    st.rerun()

# ---------------------------------------------------------------- new instructions
unread = scope.get_partner_notifications(dp_id, branch, unread_only=True)
if unread:
    route_words = ("avoid", "take", "collect", "reroute", "route")
    title = "Route changed" if any(w in m["text"].lower() for m in unread for w in route_words) else "New message"
    with ui.card("inbox"):
        st.markdown(f"<p class='dp-h3' style='color:var(--dp-ink-critical)'>{ui.icon('notifications_active')} "
                    f"{title} · {len(unread)}</p>", unsafe_allow_html=True)
        for m in unread[:3]:
            st.markdown(f"<div class='dp-row'><div class='main'>{escape(m['text'])}</div>"
                        f"<div class='end dp-small'>{escape(m['created_at'][-8:-3])}</div></div>",
                        unsafe_allow_html=True)
        if st.button("Got it", type="primary", icon=":material/done_all:", width="stretch"):
            scope.mark_notifications_read(dp_id, branch)
            st.rerun()

# ---------------------------------------------------------------- next stop + progress
todo = deliveries[~deliveries["status"].isin(["delivered", "failed"])].sort_values("eta_min")
done = int((deliveries["status"] == "delivered").sum())
if len(todo):
    nxt = todo.iloc[0]
    with ui.card("next_stop"):
        st.markdown(f"<p class='dp-small' style='font-weight:700;letter-spacing:.06em'>NEXT STOP · {len(todo)} LEFT</p>"
                    f"<p style='font-size:22px;font-weight:750;margin:2px 0 4px;letter-spacing:-.01em'>"
                    f"{escape(nxt['customer'])}</p>", unsafe_allow_html=True)
        tags = ui.pill_html("critical" if nxt["priority"] == "medical" else "delayed" if nxt["priority"] == "perishable"
                            else "off", nxt["priority"].capitalize())
        if nxt["risk"]:
            tags += " " + ui.risk_badge(nxt["risk"])
        if nxt["note"]:
            tags += " " + ui.pill_html("available", str(nxt["note"]).capitalize())
        st.markdown(f"<p class='dp-sub'>{escape(nxt['address_area'])}</p><div style='margin:8px 0'>{tags}</div>"
                    + ui.kv([("Due", escape(nxt["deadline"])), ("ETA", escape(nxt["planned_eta"])),
                             ("Order", escape(nxt["delivery_id"]))]), unsafe_allow_html=True)
        nav, call = st.columns(2)
        nav.link_button("Navigate", f"https://www.google.com/maps/dir/?api=1&destination={nxt['lat']},{nxt['lng']}",
                        icon=":material/navigation:", width="stretch")
        call.link_button("Call", f"tel:{nxt['customer_phone']}", icon=":material/call:", width="stretch")
        if st.button("Mark delivered", type="primary", icon=":material/check:", width="stretch", key="deliver_next"):
            scope.mark_delivered(dp_id, branch, nxt["delivery_id"])
            st.toast("Delivered.", icon=":material/check:")
            st.rerun()
        if st.button("Report issue", icon=":material/campaign:", width="stretch", key="report_from_today"):
            st.switch_page(guards.PARTNER_PAGES["report"])
elif len(deliveries):
    with ui.card("all_done"):
        ui.empty_state("task_alt", "All stops done. Great work.")
else:
    with ui.card("no_work"):
        ui.empty_state("hourglass_empty", "No deliveries yet.")

if len(deliveries):
    with ui.card("progress"):
        st.markdown(ui.progress_ring(done, len(deliveries)), unsafe_allow_html=True)

# ---------------------------------------------------------------- my latest report
reports = scope.get_partner_incidents(dp_id, branch)
if reports:
    latest = reports[0]
    st.markdown(f"<p class='dp-small' style='margin-top:8px'>Last report: {escape(latest['summary'] or '')} "
                f"{ui.issue_pill(latest['status'])}</p>", unsafe_allow_html=True)
