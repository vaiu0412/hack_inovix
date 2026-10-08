"""Tap-friendly live map (Leaflet via folium): partners, deliveries, blocked roads and detours.

Tapping a partner opens a popup with their details; the tooltip text ("Murugan · V1") is also
returned by streamlit-folium so the page can open the partner's detail panel.
"""
from html import escape

import folium

from modules.data_loader import COIMBATORE_CENTER, road_midpoint

STATUS_COLOURS = {"on_duty": "#16A34A", "standby": "#0F9488", "on_break": "#CA8A04", "off_duty": "#6B7280"}
STATUS_TEXT = {"on_duty": "On duty", "standby": "Standby", "on_break": "On break", "off_duty": "Off duty"}
RISK_COLOURS = {"Critical": "#DC2626", "High": "#EA580C", "Medium": "#CA8A04", "Low": "#16A34A"}
ESRI = "https://server.arcgisonline.com/ArcGIS/rest/services"
ON_TRACK, DONE, ROAD, BLOCKED, DETOUR = "#3B82F6", "#9CA3AF", "#94A3B8", "#DC2626", "#16A34A"

PULSE_CSS = """
<style>
.rp-pulse { position: relative; width: 22px; height: 22px; }
.rp-pulse span { position: absolute; inset: 5px; border-radius: 50%; background: #DC2626; border: 2px solid #fff; }
.rp-pulse::before { content: ""; position: absolute; inset: -14px; border-radius: 50%; background: rgba(220,38,38,.25);
  animation: rp-ring 1.8s ease-out infinite; }
@keyframes rp-ring { 0% { transform: scale(.4); opacity: 1; } 100% { transform: scale(1.4); opacity: 0; } }
.rp-pin { border-radius: 50%; color: #fff; font: 700 12px/1 Inter, Arial, sans-serif; display: flex; align-items: center;
  justify-content: center; border: 2px solid #fff; box-shadow: 0 1px 4px rgba(0,0,0,.35); }
.leaflet-popup-content { font: 13px/1.45 Inter, Arial, sans-serif; margin: 10px 12px; }
.leaflet-popup-content b { font-size: 14px; }
.rp-pop small { color: #6B7280; }
.leaflet-control-attribution { font-size: 9px !important; line-height: 1.3; opacity: .8; }
</style>
"""


def partner_tooltip(partner):
    return f"{partner['name']} · {partner['vehicle_id']}"


def _initials(name):
    return "".join(p[0] for p in str(name).split()[:2]).upper()


def _partner_popup(p):
    issue = f"<br><span style='color:#DC2626'>{p['open_issues']} open issue(s)</span>" if p["open_issues"] else ""
    return (f"<div class='rp-pop'><b>{escape(p['name'])}</b> · {STATUS_TEXT.get(p['status'], p['status'])}<br>"
            f"<small>{escape(p['vehicle_type'].title())} {escape(p['reg_no'])} · near {escape(p['area'])}</small><br>"
            f"<a href='tel:{escape(p['phone'])}'>{escape(p['phone'])}</a><br>"
            f"Deliveries: <b>{p['pending']}</b> pending · {p['delivered']} delivered<br>"
            f"Next: {escape(p['next_stop'])} ({escape(str(p['next_eta']))}){issue}</div>")


def _delivery_popup(d, label):
    return (f"<div class='rp-pop'><b>{escape(d['customer'])}</b><br><small>{escape(d['delivery_id'])} · "
            f"{escape(d['address_area'])} · {escape(d['priority'])}</small><br>"
            f"Vehicle {escape(d['vehicle_id'])} · ETA {escape(d['planned_eta'])} · due {escape(d['deadline'])}<br>"
            f"Status: {escape(label)}</div>")


def build(partners, deliveries, roads, disruptions=(), detour_roads=(), risk_labels=None, selected=None,
          dark=False, height_hint=None, center=None, zoom=12):
    """Return a folium.Map. risk_labels: {delivery_id: 'Critical'|...} for deliveries at risk."""
    risk_labels = risk_labels or {}
    blocked = {d.get("road_id") for d in disruptions if d.get("road_id") and d.get("type") != "breakdown"}
    # no scroll-wheel zoom: scrolling the page must not zoom the map (pinch, drag and +/- still work)
    m = folium.Map(location=center or COIMBATORE_CENTER, zoom_start=zoom, control_scale=True, tiles=None,
                   scrollWheelZoom=False)
    shade = "Dark" if dark else "Light"  # Esri grey canvas: clean, free, no API key
    for layer, overlay in (("Base", False), ("Reference", True)):
        folium.TileLayer(
            tiles=f"{ESRI}/Canvas/World_{shade}_Gray_{layer}/MapServer/tile/{{z}}/{{y}}/{{x}}",
            attr="Tiles © Esri — Esri, HERE, Garmin, © OpenStreetMap contributors",
            name=layer, overlay=overlay, control=False, max_native_zoom=16, max_zoom=18,
        ).add_to(m)
    m.get_root().header.add_child(folium.Element(PULSE_CSS))

    for road in roads.itertuples():
        is_blocked, is_detour = road.road_id in blocked, road.road_id in detour_roads
        folium.PolyLine(
            road.points, weight=7 if is_blocked else 6 if is_detour else 3,
            color=BLOCKED if is_blocked else DETOUR if is_detour else ROAD,
            opacity=0.9 if (is_blocked or is_detour) else 0.55, dash_array="10 8" if is_blocked else None,
            tooltip=f"{road.name}{' – blocked' if is_blocked else ' – detour' if is_detour else ''}",
        ).add_to(m)

    for d in deliveries.to_dict("records"):
        done = d["status"] in ("delivered", "failed")
        label = "Delivered" if d["status"] == "delivered" else risk_labels.get(d["delivery_id"], "On track")
        colour = DONE if done else RISK_COLOURS.get(label, ON_TRACK)
        folium.CircleMarker(
            (d["lat"], d["lng"]), radius=5 if label == "On track" or done else 7, color="#ffffff", weight=1.5,
            fill=True, fill_color=colour, fill_opacity=0.95,
            tooltip=f"{d['delivery_id']} · {d['customer']}",
            popup=folium.Popup(_delivery_popup(d, label), max_width=260),
        ).add_to(m)

    for d in disruptions:
        if d.get("road_id") in set(roads["road_id"]):
            points = roads.set_index("road_id").loc[d["road_id"], "points"]
            folium.Marker(road_midpoint(points), icon=folium.DivIcon(
                html="<div class='rp-pulse'><span></span></div>", icon_size=(22, 22), icon_anchor=(11, 11)),
                tooltip=f"{str(d.get('type', 'disruption')).replace('_', ' ').title()} on {d.get('road_name', '')}",
            ).add_to(m)

    for p in partners.to_dict("records"):
        size = 36 if p["partner_id"] == selected else 30
        colour = STATUS_COLOURS.get(p["status"], "#6B7280")
        ring = "box-shadow:0 0 0 4px rgba(15,118,110,.35);" if p["partner_id"] == selected else ""
        folium.Marker(
            (p["lat"], p["lng"]),
            icon=folium.DivIcon(
                html=f"<div class='rp-pin' style='width:{size}px;height:{size}px;background:{colour};{ring}'>"
                     f"{escape(_initials(p['name']))}</div>",
                icon_size=(size, size), icon_anchor=(size // 2, size // 2)),
            tooltip=partner_tooltip(p),
            popup=folium.Popup(_partner_popup(p), max_width=280),
            z_index_offset=1000,
        ).add_to(m)
    points = [(p["lat"], p["lng"]) for p in partners.to_dict("records")] + list(zip(deliveries["lat"], deliveries["lng"]))
    if points and center is None:
        lats, lngs = zip(*points)
        m.fit_bounds([(min(lats), min(lngs)), (max(lats), max(lngs))], padding=(20, 20))
    return m


if __name__ == "__main__":
    import os
    import tempfile
    from pathlib import Path

    from modules import store

    os.environ["RIPPLE_DB"] = str(Path(tempfile.mkdtemp()) / "map.db")
    store.init_db()
    from modules.data_loader import load_all

    m = build(store.partners_df(), store.deliveries_df(), load_all()["roads"],
              disruptions=[{"type": "accident", "road_id": "R1", "road_name": "Avinashi Road"}],
              detour_roads=["R9"], risk_labels={"D06": "Critical"}, selected="P1")
    html = m.get_root().render()
    assert "Murugan · V1" in html and "rp-pulse" in html
    print("map html:", len(html), "chars")
    print("live_map OK")
