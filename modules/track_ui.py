"""Public delivery tracking: /track?code=… – no sign-in. The unguessable code shows ONE delivery: its status, ETA,
the partner's first name and a small map. No phone numbers, no other stops, nothing else of the branch."""
from html import escape

import folium
import streamlit as st
from streamlit_folium import st_folium

from modules import live_map, store, ui

STEPS = [("received", "Order received"), ("assigned", "Partner assigned"), ("picked_up", "Picked up"),
         ("on_the_way", "On the way"), ("delivered", "Delivered")]
STEP_OF = {"unassigned": "received", "assigned": "assigned", "accepted": "assigned", "picked_up": "picked_up",
           "in_transit": "on_the_way", "pending": "on_the_way", "delayed": "on_the_way",
           "rescheduled": "on_the_way", "delivered": "delivered"}


def requested():
    """True for a customer's tracking link (/track?code=…). No other page uses a "code" query parameter."""
    return bool(st.query_params.get("code"))


def run():
    """A navigation with only the public page, so nothing of the signed-in app (or its sign-in) is ever shown.
    The default page catches /?code=…, the second one is the real /track URL."""
    st.navigation([st.Page(render, title="Track", default=True),
                   st.Page("views/track.py", title="Track", url_path="track")], position="hidden").run()


def render():
    """The whole public page."""
    ui.setup_page(layout="centered")
    st.markdown(f"<div class='dp-track-head'>{ui.MARK_SVG}<span>DEPORT</span></div>", unsafe_allow_html=True)
    code = st.query_params.get("code", "")
    if not store.delivery_by_code(code):
        with ui.card("track_missing"):
            ui.empty_state("link_off", "This tracking link is not valid.")
        return

    @st.fragment(run_every="30s")
    def _live():
        delivery = store.delivery_by_code(code)
        status_card(delivery)

    _live()


def status_card(d, key="track", with_map=True):
    """One delivery as the customer sees it (public tracking page and the customer portal): stage, ETA, steps,
    the partner's first name, and – while it is on its way – a small map. key keeps widgets apart when a page
    shows several deliveries."""
    step = STEP_OF.get(d["status"], "received")
    reached = [key for key, _ in STEPS][: [key for key, _ in STEPS].index(step) + 1]
    partner = _partner(d)
    with ui.card(f"{key}_status"):
        st.markdown(f"<p class='dp-small' style='font-weight:700;letter-spacing:.06em'>DELIVERY "
                    f"{escape(d['delivery_id'])}</p><p class='dp-h2' style='margin:2px 0 6px'>"
                    f"{escape(dict(STEPS)[step])}</p>",
                    unsafe_allow_html=True)
        if d["status"] == "delivered":
            when = (d.get("delivered_at") or "")[11:16]
            line = f"Delivered{' at ' + when if when else ''}" + (" · proof recorded" if d.get("pod_at") else "")
        elif d["status"] == "failed":
            line = "We could not deliver it. We will contact you."
        else:
            line = (f"Expected by {d['planned_eta']}" if d.get("planned_eta") else "We are planning your delivery") + \
                   f" · promised by {d['deadline']}"
        st.markdown(f"<p class='dp-sub'>{escape(line)}</p>", unsafe_allow_html=True)
        st.markdown("<div class='dp-steps'>" + "".join(
            f"<div class='{'on' if key in reached else ''}'><i></i><span>{escape(label)}</span></div>"
            for key, label in STEPS) + "</div>", unsafe_allow_html=True)
        if partner and d["status"] not in ("delivered", "failed", "unassigned"):
            st.markdown(ui.kv([("Your partner", escape(partner["first_name"])),
                               ("Vehicle", escape(partner["vehicle"].title()))]), unsafe_allow_html=True)
    if with_map and d["status"] not in ("delivered", "failed"):
        _map(d, partner, key)
    st.caption(f"Area: {d['address_area']} · updates every 30 s")


def _partner(d):
    if not d.get("vehicle_id"):
        return None
    with store.connect() as conn:
        row = conn.execute("SELECT p.name, v.type, v.current_lat, v.current_lng FROM vehicles v LEFT JOIN partners p "
                           "ON p.vehicle_id = v.vehicle_id WHERE v.vehicle_id = ?", (d["vehicle_id"],)).fetchone()
    if row is None:
        return None
    return {"first_name": str(row["name"] or "Our partner").split()[0], "vehicle": row["type"] or "vehicle",
            "lat": row["current_lat"], "lng": row["current_lng"]}


def _map(d, partner, key="track"):
    point = (float(d["lat"]), float(d["lng"]))
    m = folium.Map(location=point, zoom_start=14, tiles=None, scrollWheelZoom=False, zoom_control=False)
    m.get_root().header.add_child(folium.Element(live_map.MAP_CSS))
    live_map.add_tiles(m, switcher=False)
    folium.Marker(point, tooltip="Delivery here", icon=folium.Icon(color="blue", icon="home")).add_to(m)
    if partner and d["status"] in ("picked_up", "in_transit", "pending", "delayed", "rescheduled"):
        here = (float(partner["lat"]), float(partner["lng"]))
        folium.Marker(here, tooltip=f"{partner['first_name']} is here",
                      icon=folium.DivIcon(html=f"<div class='dp-veh' style='--c:#22C55E'>"
                                               f"{live_map.VEHICLE_EMOJI.get(partner['vehicle'], '🚚')}</div>",
                                          icon_size=(34, 34), icon_anchor=(17, 17))).add_to(m)
        m.fit_bounds([point, here], padding=(30, 30))
    st_folium(m, height=260, use_container_width=True, key=f"{key}_map", returned_objects=[])
