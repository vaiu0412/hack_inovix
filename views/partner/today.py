"""Today: new instructions, my next stop and my progress – for the signed-in partner only (Tamil or English)."""
from html import escape

import streamlit as st

from modules import escalation, escalation_ui, guards, partner_ui, predict, ui
from modules import partner_scope as scope
from modules.i18n import t

guards.require_role("partner")
dp_id = guards.dp_id()  # from the validated session only
branch = guards.branch_id()
profile = scope.get_partner_profile(dp_id, branch)
ui.header(t("hi", name=profile["name"].split()[0]),
          f"{ui.VEHICLE_EMOJI.get(profile['vehicle_type'], '')} {profile['reg_no']} · {profile['shift']}")

deliveries = scope.get_partner_deliveries(dp_id, branch)
worst = next((r for r in ("Critical", "High", "Medium") if r in set(deliveries["risk"])), None)
with st.container(horizontal=True, vertical_alignment="center", gap="small"):
    state = ui.partner_state(profile["status"], worst)
    st.markdown(ui.pill_html(state, t(f"state_{state}")), unsafe_allow_html=True)
    choices = ["on_duty", "on_break"] + (["standby"] if profile["status"] == "standby" else [])
    status = st.segmented_control(
        "Status",
        choices,
        default=profile["status"] if profile["status"] in choices else None,
        format_func=lambda s: t(f"status_{s}"),
        label_visibility="collapsed",
        key="my_status",
    )
if status and status != profile["status"]:
    scope.set_status(dp_id, branch, status)
    st.rerun()

# ---------------------------------------------------------------- new instructions
unread = scope.get_partner_notifications(dp_id, branch, unread_only=True)
if unread:
    route_words = ("avoid", "take", "collect", "reroute", "route")
    title = t("route_changed") if any(w in m["text"].lower() for m in unread for w in route_words) \
        else t("new_message")
    with ui.card("inbox"):
        st.markdown(f"<p class='dp-h3' style='color:var(--dp-ink-critical)'>{ui.icon('notifications_active')} "
                    f"{title} · {len(unread)}</p>", unsafe_allow_html=True)
        for m in unread[:3]:
            st.markdown(f"<div class='dp-row'><div class='main'>{escape(m['text'])}</div>"
                        f"<div class='end dp-small'>{escape(m['created_at'][-8:-3])}</div></div>",
                        unsafe_allow_html=True)
        if st.button(t("got_it"), type="primary", icon=":material/done_all:", width="stretch"):
            scope.mark_notifications_read(dp_id, branch)
            st.rerun()

# ---------------------------------------------------------------- new work from the branch admin
new_work = deliveries[deliveries["status"] == "assigned"].sort_values("eta_min")
fresh = new_work[new_work["seen_at"].isna() & new_work["offer_status"].notna()]["delivery_id"].tolist()
if fresh:
    escalation.mark_seen(dp_id, branch, fresh)  # the partner has now seen these offers
if len(new_work):
    with ui.card("new_work"):
        st.markdown(f"<p class='dp-h3'>{ui.icon('assignment')} {t('new_work')} · {len(new_work)}</p>",
                    unsafe_allow_html=True)
        for d in new_work.to_dict("records"):
            size = t(f"size_{d.get('package_size') or 'small'}")
            st.markdown(
                f"<div class='dp-row'><div class='main'><b>{escape(d['delivery_id'])} · {escape(d['customer'])}</b>"
                f"<small>{escape(d['address_area'])} · {escape(size)} · {t('due_at', time=d['deadline'])}</small>"
                f"</div><div class='end'>{partner_ui.stage_pill(d['status'])} "
                f"{escalation_ui.offer_pill(d.get('offer_status'))}</div></div>",
                unsafe_allow_html=True,
            )
            partner_ui.step_buttons(dp_id, branch, d, key=f"new_{d['delivery_id']}")

# ---------------------------------------------------------------- next stop + progress
todo = deliveries[~deliveries["status"].isin(["delivered", "failed"])].sort_values("eta_min")
todo = todo[todo["status"] != "assigned"] if len(todo[todo["status"] != "assigned"]) else todo
done = int((deliveries["status"] == "delivered").sum())
if len(todo):
    nxt = todo.iloc[0]
    with ui.card("next_stop"):
        st.markdown(f"<p class='dp-small' style='font-weight:700;letter-spacing:.06em'>"
                    f"{t('next_stop', n=len(todo))}</p>"
                    f"<p style='font-size:22px;font-weight:750;margin:2px 0 4px;letter-spacing:-.01em'>"
                    f"{escape(nxt['customer'])}</p>", unsafe_allow_html=True)
        tags = ui.pill_html("critical" if nxt["priority"] == "medical" else "delayed" if nxt["priority"] == "perishable"
                            else "off", t(f"priority_{nxt['priority']}"))
        if nxt["risk"]:
            tags += " " + ui.pill_html(ui.risk_state(nxt["risk"]), t(f"risk_{nxt['risk']}"))
        if nxt["note"]:
            tags += " " + ui.pill_html("available", str(nxt["note"]).capitalize())
        tags += " " + partner_ui.stage_pill(nxt["status"])
        likely = predict.for_branch(branch).get(nxt["delivery_id"])  # only this partner's own stop is shown
        if likely and likely["p_late"] >= predict.LATE_AT:
            tags += "<br>" + ui.pill_html("critical", t("predicted_late", p=f"{likely['p_late']:.0%}")) + \
                f" <span class='dp-small'>{escape(' · '.join(likely['reasons']))}</span>"
        st.markdown(f"<p class='dp-sub'>{escape(nxt['address_area'])}</p><div style='margin:8px 0'>{tags}</div>"
                    + ui.kv([(t("due"), escape(nxt["deadline"])), (t("eta"), escape(nxt["planned_eta"])),
                             (t("order"), escape(nxt["delivery_id"]))]), unsafe_allow_html=True)
        nav, call = st.columns(2)
        nav.link_button(t("navigate"), f"https://www.google.com/maps/dir/?api=1&destination={nxt['lat']},{nxt['lng']}",
                        icon=":material/navigation:", width="stretch")
        call.link_button(t("call"), f"tel:{nxt['customer_phone']}", icon=":material/call:", width="stretch")
        partner_ui.step_buttons(dp_id, branch, nxt.to_dict(), key="next")
elif len(deliveries):
    with ui.card("all_done"):
        ui.empty_state("task_alt", t("all_done"))
else:
    with ui.card("no_work"):
        ui.empty_state("hourglass_empty", t("no_deliveries"))

if len(deliveries):
    with ui.card("progress"):
        st.markdown(ui.progress_ring(done, len(deliveries), of_text=t("delivered_of", done=done,
                                                                         total=len(deliveries)),
                                     word=t("delivered_word")), unsafe_allow_html=True)

# ---------------------------------------------------------------- my latest report
reports = scope.get_partner_incidents(dp_id, branch)
if reports:
    latest = reports[0]
    st.markdown(f"<p class='dp-small' style='margin-top:8px'>{t('last_report')}: {escape(latest['summary'] or '')} "
                f"{ui.issue_pill(latest['status'])}</p>", unsafe_allow_html=True)
