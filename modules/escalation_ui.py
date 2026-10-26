"""Order offers on screen: the timer, the partner's alarm and full-screen urgent card, the admin's red alerts.
All logic lives in modules/escalation.py; this file only draws and calls it."""
import time
from html import escape
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

from modules import assign, escalation, ui
from modules.i18n import t

ALARM = Path(__file__).resolve().parent.parent / "assets" / "alert.wav"  # 15 s loop: beeps every 15 s


def offer_pill(status):
    """Coloured chip for an offer status: Sent, Seen, Ringing, Calling, Accepted, Declined, No response."""
    if not status:
        return ""
    return ui.pill_html(escalation.STATE.get(status, "off"), t(f"offer_{status}"))


def offer_text(status):
    """Offer status for tables (emoji + word)."""
    return f"{escalation.EMOJI.get(status, '')} {escalation.LABEL.get(status, status)}" if status else "—"


# ---------------------------------------------------------------- timer + alarm (sidebar, every page)
def watcher(user):
    """One timed check per signed-in admin or partner, at a fixed place in the sidebar (like ui.live_updates).
    Admins move their branch's offers along every 20 s; partners do it for their own offers every 15 s and get
    the alarm (looping sound + vibration) while an offer is still not accepted after the ring time."""
    role = user["role"]
    if role == "branch_admin":
        @st.fragment(run_every="20s")
        def _admin_timer():
            from modules import realtime  # weather / traffic / simulated movement, each at its own pace

            changed = escalation.tick(branch_id=user["branch_id"])
            realtime.poll(user["branch_id"])
            if changed:
                st.rerun(scope="app")

        with st.sidebar:
            _admin_timer()
    elif role == "partner":
        @st.fragment(run_every="15s")
        def _partner_timer():
            dp_id, branch = user["dp_id"], user["branch_id"]
            if escalation.tick(branch_id=branch, dp_id=dp_id):
                st.rerun(scope="app")
            loud = [o for o in escalation.partner_offers(dp_id, branch)
                    if o["offer_status"] in ("ringing", "calling", "no_response")]
            if loud:
                _alarm(len(loud))

        with st.sidebar:
            _partner_timer()


def _alarm(count):
    st.caption(f":material/notifications_active: {t('orders_waiting', n=count)}")
    st.audio(str(ALARM), format="audio/wav", autoplay=True, loop=True)
    # a new snippet every run, so the phone vibrates again every 15 s (Android; iPhones can't vibrate from a page)
    components.html(f"<script>/* {time.time()} */ try {{ const n = window.parent.navigator; "
                    "if (n.vibrate) n.vibrate([500, 200, 500, 200, 500]); } catch (e) {}</script>", height=0)


# ---------------------------------------------------------------- partner: full-screen card for urgent orders
def partner_overlay(user):
    """Full-screen card for the most urgent unaccepted urgent order (medical, perishable, express by default).
    During a simulated call (Demo mode) it shows the call screen with the same 1 / 2 choices."""
    dp_id, branch = user["dp_id"], user["branch_id"]
    cfg = escalation.settings()
    urgent = [o for o in escalation.partner_offers(dp_id, branch) if escalation.is_urgent(o["priority"], cfg)]
    if not urgent:
        return
    offer = urgent[0]
    did = offer["delivery_id"]
    if not offer["seen_at"]:
        escalation.mark_seen(dp_id, branch, [did])
    calling = offer["offer_status"] == "calling" and offer["demo_call"]
    with st.container(key="offer_overlay"):
        if calling:
            st.markdown(f"<div class='dp-offer'><div class='ring'>{ui.icon('call', 40)}</div>"
                        f"<p class='kicker'>{t('calling_demo')}</p>"
                        f"<p class='say'>“{escape(escalation.call_message(offer))}”</p></div>",
                        unsafe_allow_html=True)
        else:
            more = f" · {t('more', n=len(urgent) - 1)}" if len(urgent) > 1 else ""
            st.markdown(
                f"<div class='dp-offer'><div class='ring'>{ui.icon('emergency', 40)}</div>"
                f"<p class='kicker'>{t('urgent_order')}{more}</p>"
                f"<p class='title'>{escape(did)} · {escape(str(offer.get('category') or 'Parcel'))}</p>"
                f"<p class='who'>{escape(offer['customer'])}</p>"
                f"<p class='where'>{escape(offer['address_area'])} · {t('due_at', time=escape(offer['deadline']))} · "
                f"{escape(t('priority_' + str(offer.get('priority') or 'standard')))}</p>"
                f"<div class='chip'>{offer_pill(offer['offer_status'])}</div></div>",
                unsafe_allow_html=True)
        _answer_buttons(dp_id, branch, offer, channel="call" if calling else "app",
                        labels=(t("key_accept"), t("key_cant")) if calling else (t("accept"), t("cant_take")))


def _answer_buttons(dp_id, branch, offer, channel, labels):
    did = offer["delivery_id"]
    if st.session_state.get(f"decline_{did}"):
        reason = st.pills(t("why"), escalation.DECLINE_REASONS, key=f"decline_reason_{did}",
                          format_func=lambda r: t(f"reason_{r}"))
        send, back = st.columns(2)
        if send.button(t("send"), type="primary", icon=":material/send:", width="stretch", key=f"decline_send_{did}",
                       disabled=not reason):
            _answer(dp_id, branch, did, False, reason, channel)
        if back.button(t("back"), width="stretch", key=f"decline_back_{did}"):
            st.session_state.pop(f"decline_{did}", None)
            st.rerun()
        return
    if st.button(labels[0], type="primary", icon=":material/check_circle:", width="stretch", key=f"offer_yes_{did}"):
        _answer(dp_id, branch, did, True, "", channel)
    if st.button(labels[1], icon=":material/block:", width="stretch", key=f"offer_no_{did}"):
        st.session_state[f"decline_{did}"] = True
        st.rerun()


def _answer(dp_id, branch, delivery_id, accept, reason, channel):
    try:
        escalation.respond(dp_id, branch, delivery_id, accept, reason=reason, channel=channel)
        st.toast(t("is_yours", id=delivery_id) if accept else t("sent_reassign"),
                 icon=":material/check:" if accept else ":material/send:")
    except (ValueError, PermissionError) as error:
        st.toast(str(error), icon=":material/error:")
    st.session_state.pop(f"decline_{delivery_id}", None)
    st.rerun()


def cant_take(dp_id, branch, delivery, key):
    """'Can't take' with a reason, for an offered order on the partner's lists."""
    with st.popover(t("cant_take"), icon=":material/block:", width="stretch"):
        reason = st.pills(t("why"), escalation.DECLINE_REASONS, key=f"why_{key}",
                          format_func=lambda r: t(f"reason_{r}"))
        if st.button(t("send"), type="primary", width="stretch", key=f"cant_send_{key}", disabled=not reason):
            _answer(dp_id, branch, delivery["delivery_id"], False, reason, "app")


# ---------------------------------------------------------------- admin: red alerts with a one-click reassign
def admin_alerts(ctx):
    """Red cards for orders nobody accepted in time or a partner can't take – with the next-best partner."""
    alerts = escalation.admin_alerts(ctx["branch_id"])
    for alert in alerts:
        did = alert["delivery_id"]
        who = ctx["partner_names"].get(alert["last_dp"], alert["last_dp"] or "Partner")
        if alert["offer_status"] == "declined":
            why = f"{who} can't take it · {alert['last_result'].split('·', 1)[-1].strip()}"
        else:
            why = f"{who} didn't accept in {escalation.settings()['alert_after_min']} min"
        best = alert["suggestion"]
        with st.container(key=f"esc_alert_{did}"):
            st.markdown(f"<div class='dp-esc'><b>{ui.icon('emergency')} {escape(did)} · {escape(alert['customer'])}"
                        f"</b> <span class='dp-small'>{escape(str(alert.get('category') or 'Parcel'))} · due "
                        f"{escape(alert['deadline'])}</span><br>{escape(why)}"
                        + (f"<br><span class='dp-small'>Best now: {escape(best['reason'])}</span>" if best else
                           "<br><span class='dp-small'>No other partner fits right now.</span>") + "</div>",
                        unsafe_allow_html=True)
            go_col, pick_col = st.columns(2)
            if best and go_col.button(f"Reassign to {best['name']}", type="primary", icon=":material/swap_horiz:",
                                      width="stretch", key=f"esc_go_{did}"):
                reason = "Can't take" if alert["offer_status"] == "declined" else "No response"
                result = assign.assign(ctx["actor"], did, best["partner_id"], reason=reason)
                st.toast(f"{did} → {best['partner_id']} · ETA {result['eta']}.", icon=":material/check:")
                st.rerun()
            with pick_col.popover("Choose partner", icon=":material/person_search:", width="stretch"):
                from modules.manager_ui import choose_partner_form  # manager_ui imports this module

                order = dict(alert)
                found = [c for c in assign.candidates(order, ctx["branch_id"]) if c["partner_id"] != alert["last_dp"]]
                choose_partner_form(ctx, order, found, verb="Reassign" if order.get("vehicle_id") else "Assign")


def timeline(delivery_id, branch_id):
    """The offer steps of one order (Sent, Seen, Ringing, call, answer) as a compact list."""
    steps = escalation.history(delivery_id, branch_id)
    if not steps:
        return
    icons = {"app": "smartphone", "sound": "notifications_active", "call": "call", "admin": "emergency"}
    rows = "".join(f"<div class='dp-row'><div class='main'>{ui.icon(icons.get(s['channel'], 'circle'))} "
                   f"{escape(s['result'])} <small>{escape(s['dp_id'] or '')}</small></div>"
                   f"<div class='end dp-small'>{escape(s['time'][-8:])}</div></div>" for s in steps)
    st.markdown(f"<p class='dp-small' style='font-weight:700;margin:10px 0 4px'>OFFER</p>{rows}",
                unsafe_allow_html=True)


def settings_caption():
    """One line: when the app rings, calls and alerts."""
    cfg = escalation.settings()
    st.caption(f":material/timer: Not accepted → ring {cfg['ring_after_min']} min · call {cfg['call_after_min']} min"
               f" · alert you {cfg['alert_after_min']} min. No call for: {cfg['no_call_priorities'] or 'none'}.")
