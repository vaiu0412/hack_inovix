"""Real-world feeds on screen: the partner's GPS sharing, the Live feeds card, traffic suggestions.
All logic is in modules/realtime.py and modules/tracking.py; this file only draws and calls them."""
from html import escape
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

from modules import predict, realtime, store, tracking, ui
from modules.i18n import t

_geolocation = components.declare_component(
    "deport_geolocation", path=str(Path(__file__).resolve().parent.parent / "components" / "geolocation"))


# ---------------------------------------------------------------- partner: share location while on duty
def share_location(user):
    """On duty: the phone sends its position every 30 s (the browser asks once). On break: nothing is shared."""
    dp_id, branch = user["dp_id"], user["branch_id"]

    @st.fragment
    def _gps():
        partner = store.get_partner(dp_id, branch) or {}
        if partner.get("status") != "on_duty":
            st.caption(f":material/location_off: {t('loc_off')}")
            return
        value = _geolocation(interval_s=tracking.GPS_EVERY_S, key="gps", default=None)
        if not value:
            st.caption(f":material/my_location: {t('loc_waiting')}")
            return
        if value.get("error"):
            st.caption(f":material/location_off: {t('loc_blocked')}")
            return
        if value.get("ts") != st.session_state.get("_gps_ts"):
            st.session_state["_gps_ts"] = value.get("ts")
            st.session_state["_gps_ok"] = tracking.record(dp_id, branch, value["lat"], value["lng"],
                                                          value.get("accuracy"))
        if st.session_state.get("_gps_ok", True):
            st.caption(f":material/my_location: {t('loc_sharing', n=tracking.GPS_EVERY_S)}")
        else:
            st.caption(f":material/location_off: {t('loc_outside')}")

    with st.sidebar:
        _gps()


# ---------------------------------------------------------------- admin: live feeds + suggestions
def feeds_card(ctx):
    """Weather, traffic and GPS – live or Demo mode – with the demo controls."""
    status = realtime.status(ctx["branch_id"])
    weather, traffic, gps = status["weather"], status["traffic"], status["gps"]
    reading = weather["reading"]
    if weather["live"] and reading:
        weather_text = (f"{predict.WEATHER_LABEL[reading['weather']]} · {reading['rain_mm']} mm/h · "
                        f"{escape(reading['description'])} · OpenWeatherMap {reading['updated_at'][11:16]}")
    else:
        weather_text = f"{predict.WEATHER_LABEL[predict.weather_now()]} · set by hand (Demo mode)"
    checked = traffic["checked_at"][11:16] if traffic["checked_at"] else "not yet"
    traffic_text = (f"{'TomTom' if traffic['live'] else 'Demo mode'} · checked {checked} · "
                    f"{traffic['open']} to confirm")
    gps_text = (f"{gps['sharing']} of {gps['partners']} partners sharing"
                + (" · simulated movement on" if gps["simulating"] else ""))
    st.markdown(ui.kv([("Weather", f"{ui.icon('rainy')} {weather_text}"), ("Traffic", f"{ui.icon('traffic')} "
                       f"{traffic_text}"), ("GPS", f"{ui.icon('my_location')} {gps_text}")]), unsafe_allow_html=True)
    check, simulate = st.columns(2)
    if check.button("Check traffic" if traffic["live"] else "Check traffic (demo)", icon=":material/traffic:",
                    width="stretch", key="check_traffic"):
        found = realtime.check_traffic(ctx["branch_id"], demo=not traffic["live"])
        jams = sum(1 for r in found.values() if r["level"] != "normal")
        st.toast(f"{len(found)} roads checked · {jams} jammed.", icon=":material/traffic:")
        st.rerun()
    on = simulate.toggle("Simulate movement", value=gps["simulating"], key="simulate_toggle",
                         help="Demo mode: vehicles drive toward their next stop by themselves")
    if on != gps["simulating"]:
        tracking.set_simulation(ctx["actor"], on)
        st.rerun()


def suggestion_cards(ctx):
    """Amber cards for traffic jams the feed found: Create alert (same flow as a report) or Dismiss."""
    for s in realtime.suggestions(ctx["branch_id"]):
        sid = s["suggestion_id"]
        with st.container(key=f"suggest_{sid}"):
            st.markdown(f"<div class='dp-esc'><b>{ui.icon('traffic')} {escape(s['level'].capitalize())} traffic on "
                        f"{escape(s['road_name'])}</b> <span class='dp-small'>{s['current_kmph']:.0f} km/h · usually "
                        f"{s['free_kmph']:.0f} · {escape(s.get('source', ''))} {escape(s['time'][11:16])}</span>"
                        "<br><span class='dp-small'>Create an alert to see who is hit and get a plan.</span></div>",
                        unsafe_allow_html=True)
            yes, no = st.columns(2)
            if yes.button("Create alert", type="primary", icon=":material/add_alert:", width="stretch",
                          key=f"suggest_yes_{sid}"):
                issue_id = realtime.confirm(sid, ctx["actor"])
                st.toast(f"Alert #{issue_id} created.", icon=":material/check:")
                st.rerun()
            if no.button("Dismiss", icon=":material/close:", width="stretch", key=f"suggest_no_{sid}"):
                realtime.dismiss(sid, ctx["actor"])
                st.rerun()
