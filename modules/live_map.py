"""Realistic live map (Leaflet via folium, no API key).

- Basemaps (all free, no key): Esri Dark Gray (default, matches the dark glass UI), Esri World Street Map,
  OpenStreetMap, Esri satellite. (CARTO Dark Matter / Voyager now require an API key, so they are not used.)
- Roads follow real streets: shapes come from the OSRM cache (store.route_geometry), never fetched here.
- Vehicles: white disc with a status-coloured ring and a vehicle icon; Critical ones pulse.
- Stops: small numbered pins coloured by risk. Disruptions: red radius + ⚠️, blocked road thick red dashed,
  alternate route green. The selected partner's path (current spot -> next stops) is blue, others fade.
- Clicking a vehicle returns its tooltip ("DP102 · Karthik · 🏍️ · Delayed"); the page opens the side panel.
"""
from html import escape

import folium
import xyzservices.providers as xyz
from branca.element import MacroElement, Template

from modules import geometry as geo
from modules import store
from modules.data_loader import COIMBATORE_CENTER, load_places, road_midpoint

STATE = {  # same status language as modules/ui.py (neon-soft on the dark map)
    "normal": ("Normal", "#22C55E"), "delayed": ("Delayed", "#FACC15"), "critical": ("Critical", "#F43F5E"),
    "available": ("Available", "#38BDF8"), "break": ("Break", "#94A3B8"), "off": ("Off", "#94A3B8"),
}
ESRI = "https://server.arcgisonline.com/ArcGIS/rest/services"
ESRI_ATTR = "Tiles © Esri — Esri, HERE, Garmin, © OpenStreetMap contributors"
RISK_STATE = {"Critical": "critical", "High": "delayed", "Medium": "delayed", "Low": "normal"}
VEHICLE_EMOJI = {"bike": "🏍️", "car": "🚗", "van": "🚐", "truck": "🚚"}
RADIUS_M = {"critical": 900, "high": 700, "medium": 500, "low": 350}
BLOCKED, DETOUR, SELECTED, ROUTE, DONE = "#F43F5E", "#22C55E", "#3B82F6", "#94A3B8", "#64748B"

MAP_CSS = """
<style>
.leaflet-container { background: #070B14; font-family: Inter, Arial, sans-serif; }
.dp-veh { position: relative; width: 34px; height: 34px; border-radius: 50%; background: rgba(15,23,42,.72);
  backdrop-filter: blur(6px); border: 3px solid var(--c); display: flex; align-items: center; justify-content: center;
  font-size: 17px; line-height: 1; box-shadow: 0 0 14px var(--c), 0 4px 14px rgba(0,0,0,.55); box-sizing: border-box; }
.dp-veh.sel { transform: scale(1.22); box-shadow: 0 0 0 5px rgba(59,130,246,.35), 0 0 22px var(--c); }
.dp-veh.fade { opacity: .42; }
.dp-veh.pulse::after { content: ""; position: absolute; inset: -9px; border-radius: 50%; border: 3px solid rgba(244,63,94,.65);
  animation: dp-ring 1.6s ease-out infinite; }
@keyframes dp-ring { 0% { transform: scale(.7); opacity: 1; } 100% { transform: scale(1.35); opacity: 0; } }
.dp-stop { width: 20px; height: 20px; border-radius: 50%; color: #0B1220; font: 800 11px/1 Inter, Arial, sans-serif;
  display: flex; align-items: center; justify-content: center; border: 2px solid rgba(255,255,255,.85); box-sizing: border-box;
  box-shadow: 0 0 10px rgba(0,0,0,.6); }
.dp-stop.fade { opacity: .35; }
.dp-warn { width: 34px; height: 34px; border-radius: 50%; background: rgba(15,23,42,.8); border: 3px solid #F43F5E; display: flex;
  align-items: center; justify-content: center; font-size: 17px; box-shadow: 0 0 18px rgba(244,63,94,.7); box-sizing: border-box; }
.dp-legend { background: rgba(15,23,42,.78); backdrop-filter: blur(8px); border: 1px solid rgba(255,255,255,.14);
  border-radius: 12px; padding: 8px 10px; font: 600 11px/1.5 Inter, Arial, sans-serif; color: #E2E8F0;
  box-shadow: 0 8px 24px rgba(0,0,0,.45); }
.dp-legend span { display: inline-flex; align-items: center; gap: 5px; margin-right: 8px; white-space: nowrap; }
.dp-legend i { width: 9px; height: 9px; border-radius: 50%; display: inline-block; }
.dp-legend b { width: 16px; height: 0; border-top: 3px solid; display: inline-block; }
.leaflet-tooltip { font: 600 12px/1.4 Inter, Arial, sans-serif; border-radius: 8px; background: rgba(15,23,42,.92);
  color: #F8FAFC; border: 1px solid rgba(255,255,255,.16); box-shadow: 0 6px 18px rgba(0,0,0,.45); }
.leaflet-tooltip-top:before, .leaflet-tooltip-bottom:before, .leaflet-tooltip-left:before, .leaflet-tooltip-right:before { display: none; }
.leaflet-popup-content-wrapper, .leaflet-popup-tip { background: rgba(15,23,42,.95); color: #E2E8F0; }
.leaflet-popup-content { font: 13px/1.45 Inter, Arial, sans-serif; margin: 10px 12px; }
.leaflet-popup-content b { font-size: 14px; color: #F8FAFC; }
.leaflet-control-layers, .leaflet-bar a { background: rgba(15,23,42,.85) !important; color: #E2E8F0 !important;
  border-color: rgba(255,255,255,.14) !important; }
.leaflet-control-attribution { font-size: 9px !important; opacity: .7; background: rgba(15,23,42,.6) !important; color: #94A3B8 !important; }
.leaflet-control-attribution a { color: #94A3B8 !important; }
@media (max-width: 640px) { .dp-legend { font-size: 10px; padding: 6px 8px; max-width: 220px; } }
@media (prefers-reduced-motion: reduce) { .dp-veh.pulse::after { animation: none; } }
</style>"""

LEGEND = ("<span><i style='background:#22C55E'></i>Normal</span><span><i style='background:#FACC15'></i>Delayed</span>"
          "<span><i style='background:#F43F5E'></i>Critical</span><span><i style='background:#38BDF8'></i>Available</span><br>"
          "<span><b style='border-color:#F43F5E;border-top-style:dashed'></b>Blocked</span>"
          "<span><b style='border-color:#22C55E'></b>Alternate</span><span><b style='border-color:#3B82F6'></b>Route</span>")


class Legend(MacroElement):
    """Compact legend, bottom-left."""
    _template = Template("""
        {% macro script(this, kwargs) %}
        var dpLegend = L.control({position: 'bottomleft'});
        dpLegend.onAdd = function () { var d = L.DomUtil.create('div', 'dp-legend'); d.innerHTML = {{ this.html|tojson }};
          return d; };
        dpLegend.addTo({{ this._parent.get_name() }});
        {% endmacro %}""")

    def __init__(self, html):
        super().__init__()
        self._name = "Legend"
        self.html = html


def partner_tooltip(partner, state):
    """'DP102 · Karthik · 🏍️ · Delayed' – also how a click on the map is matched back to the partner."""
    return (f"{partner['partner_id']} · {partner['name']} · {VEHICLE_EMOJI.get(partner['vehicle_type'], '🚚')} · "
            f"{STATE.get(state, STATE['off'])[0]}")


def _roads_list(value):
    if isinstance(value, str):
        return [r for r in value.split("|") if r]
    return list(value or [])


def road_points(road_id, roads, shapes):
    """Real street shape of a road (cache), else its stored waypoints."""
    cached = shapes.get(f"road:{road_id}")
    if cached:
        return cached
    row = roads[roads["road_id"] == road_id]
    return list(row["points"].iloc[0]) if len(row) else []


def path_points(start, stops, shapes):
    """Driving path start -> stop 1 -> stop 2 ... from cached legs; a missing leg is a straight line."""
    points, cached_all = [], True
    for a, b in zip([start] + stops, stops):
        leg = shapes.get(geo.leg_key(a, b))
        if not leg:
            cached_all = False
            leg = [list(a), list(b)]
        points += leg if not points else leg[1:]
    return points, cached_all


def disruption_point(d, roads, shapes):
    if d.get("lat") and d.get("lng"):
        return float(d["lat"]), float(d["lng"])
    place = str(d.get("place") or "").lower()
    if place and place != str(d.get("road_name") or "").lower():
        places = load_places()
        match = places[places["name"].str.lower() == place]
        if len(match):
            return float(match["lat"].iloc[0]), float(match["lng"].iloc[0])
    pts = road_points(d.get("road_id"), roads, shapes)
    return tuple(road_midpoint(pts)) if pts else None


def add_tiles(m, switcher=True):
    """Free, keyless basemaps; dark by default to match the glass UI. (CARTO Dark Matter / Voyager now need an
    API key, so Esri's Dark Gray canvas + labels is the default.)"""
    folium.TileLayer(f"{ESRI}/Canvas/World_Dark_Gray_Base/MapServer/tile/{{z}}/{{y}}/{{x}}", attr=ESRI_ATTR,
                     name="Dark", max_native_zoom=16, max_zoom=19).add_to(m)
    folium.TileLayer(f"{ESRI}/Canvas/World_Dark_Gray_Reference/MapServer/tile/{{z}}/{{y}}/{{x}}", attr=ESRI_ATTR,
                     name="Labels", overlay=True, control=False, max_native_zoom=16, max_zoom=19).add_to(m)
    if switcher:
        folium.TileLayer(xyz.Esri.WorldStreetMap, name="Street", show=False, max_zoom=19).add_to(m)
        folium.TileLayer(xyz.OpenStreetMap.Mapnik, name="OpenStreetMap", show=False).add_to(m)
        folium.TileLayer(xyz.Esri.WorldImagery, name="Satellite", show=False).add_to(m)
    return m


def build(partners, deliveries, roads, disruptions=(), detour_roads=(), risk_labels=None, selected=None,
          states=None, focus=None, dark=False, zoom=13):
    """folium.Map for one branch (or one partner).

    partners: DataFrame (partner_id, name, status, vehicle_type, vehicle_id, lat, lng, route_roads)
    states: {partner_id: 'normal'|'delayed'|'critical'|'available'|'break'|'off'}
    focus: list of (lat, lng) to zoom to (e.g. the alerts), else everything is fitted
    """
    risk_labels, states = risk_labels or {}, states or {}
    shapes = store.route_geometry()
    m = folium.Map(location=COIMBATORE_CENTER, zoom_start=zoom, tiles=None, control_scale=True, scrollWheelZoom=False)
    add_tiles(m)
    m.get_root().header.add_child(folium.Element(MAP_CSS))

    blocked = {d.get("road_id") for d in disruptions if d.get("road_id") and d.get("type") != "breakdown"}
    records = partners.to_dict("records")
    selected_row = next((p for p in records if p["partner_id"] == selected), None)
    selected_roads = set(_roads_list(selected_row.get("route_roads"))) if selected_row else set()

    # routes of the shown partners, faint; the selected partner's roads in blue
    route_ids = list(dict.fromkeys(r for p in records for r in _roads_list(p.get("route_roads"))))
    for road_id in route_ids:
        if road_id in blocked or road_id in detour_roads:
            continue
        mine = road_id in selected_roads
        folium.PolyLine(road_points(road_id, roads, shapes), color=SELECTED if mine else ROUTE,
                        weight=5 if mine else 3, opacity=0.55 if mine else (0.25 if selected else 0.5)).add_to(m)
    names = dict(zip(roads["road_id"], roads["name"]))
    for road_id in detour_roads:
        if road_id not in blocked:
            folium.PolyLine(road_points(road_id, roads, shapes), color=DETOUR, weight=7, opacity=0.9,
                            tooltip=f"Alternate · {names.get(road_id, road_id)}").add_to(m)
    for road_id in blocked:
        folium.PolyLine(road_points(road_id, roads, shapes), color=BLOCKED, weight=8, opacity=0.9, dash_array="12 10",
                        tooltip=f"Blocked · {names.get(road_id, road_id)}").add_to(m)

    # disruptions: affected radius + ⚠️
    alert_points = []
    for d in disruptions:
        point = disruption_point(d, roads, shapes)
        if not point:
            continue
        alert_points.append(point)
        label = f"{str(d.get('type', 'disruption')).replace('_', ' ').title()} · {d.get('road_name') or ''}"
        folium.Circle(point, radius=RADIUS_M.get(d.get("severity"), 600), color=BLOCKED, weight=1.5, fill=True,
                      fill_color=BLOCKED, fill_opacity=0.14, tooltip=label).add_to(m)
        folium.Marker(point, tooltip=label, z_index_offset=900, icon=folium.DivIcon(
            html="<div class='dp-warn'>⚠️</div>", icon_size=(34, 34), icon_anchor=(17, 17))).add_to(m)

    # selected partner: current spot (or last drop) -> pending stops, along cached real legs
    if selected_row is not None:
        own = deliveries[deliveries["vehicle_id"] == selected_row["vehicle_id"]].sort_values("eta_min")
        done = own[own["status"] == "delivered"]
        todo = own[~own["status"].isin(["delivered", "failed"])]
        start = ((done["lat"].iloc[-1], done["lng"].iloc[-1]) if len(done)
                 else (selected_row["lat"], selected_row["lng"]))
        if len(todo):
            points, real = path_points(start, list(zip(todo["lat"], todo["lng"])), shapes)
            folium.PolyLine(points, color="#1D4ED8", weight=5, opacity=0.95,
                            dash_array=None if real else "6 8", tooltip="Next stops").add_to(m)

    # delivery stops: numbered, coloured by risk
    for d in deliveries.to_dict("records"):
        if not isinstance(d.get("vehicle_id"), str) or not d.get("vehicle_id"):  # new order, no partner yet
            folium.Marker((d["lat"], d["lng"]), tooltip=f"{d['delivery_id']} · {d['customer']} · unassigned",
                          icon=folium.DivIcon(html="<div class='dp-stop' style='background:#64748B'>+</div>",
                                              icon_size=(20, 20), icon_anchor=(10, 10))).add_to(m)
            continue
        is_done = d["status"] in ("delivered", "failed")
        label = "Delivered" if d["status"] == "delivered" else risk_labels.get(d["delivery_id"], "")
        colour = DONE if is_done else STATE[RISK_STATE.get(label, "normal")][1]
        fade = " fade" if selected_row is not None and d["vehicle_id"] != selected_row["vehicle_id"] else ""
        folium.Marker(
            (d["lat"], d["lng"]),
            icon=folium.DivIcon(html=f"<div class='dp-stop{fade}' style='background:{colour}'>{int(d['stop_order'])}</div>",
                                icon_size=(20, 20), icon_anchor=(10, 10)),
            tooltip=f"{d['delivery_id']} · {d['customer']} · ETA {d['planned_eta']}",
            popup=folium.Popup(f"<b>{escape(d['customer'])}</b><br>{escape(d['address_area'])} · {escape(d['priority'])}"
                               f"<br>ETA {escape(d['planned_eta'])} · Due {escape(d['deadline'])}"
                               f"{'<br>' + escape(label) if label else ''}", max_width=240),
        ).add_to(m)

    # vehicles: white disc, status ring, vehicle icon; critical pulses; selected is larger, others fade
    for p in records:
        state = states.get(p["partner_id"], "normal")
        ring = STATE.get(state, STATE["off"])[1]
        snapped = shapes.get(f"snap:{p['vehicle_id']}")
        position = tuple(snapped[0]) if snapped else (p["lat"], p["lng"])
        css = "dp-veh" + (" pulse" if state == "critical" else "") + (
            " sel" if p["partner_id"] == selected else " fade" if selected else "")
        folium.Marker(position, z_index_offset=1000 if p["partner_id"] == selected else 500,
                      tooltip=partner_tooltip(p, state),
                      icon=folium.DivIcon(html=f"<div class='{css}' style='--c:{ring}'>"
                                               f"{VEHICLE_EMOJI.get(p['vehicle_type'], '🚚')}</div>",
                                          icon_size=(34, 34), icon_anchor=(17, 17))).add_to(m)

    Legend(LEGEND).add_to(m)
    folium.LayerControl(position="topright", collapsed=True).add_to(m)
    everything = [(p["lat"], p["lng"]) for p in records] + list(zip(deliveries["lat"], deliveries["lng"])) + alert_points
    points = (alert_points or everything) if focus is True else (list(focus) if focus else everything)
    if points:
        lats, lngs = zip(*points)
        pad = 0.012 if focus else 0.0
        m.fit_bounds([(min(lats) - pad, min(lngs) - pad), (max(lats) + pad, max(lngs) + pad)], padding=(24, 24))
    return m


if __name__ == "__main__":
    import os
    import tempfile
    from pathlib import Path

    os.environ["RIPPLE_DB"] = str(Path(tempfile.mkdtemp()) / "map.db")
    os.environ["RIPPLE_OFFLINE"] = "1"
    store.init_db()
    from modules.data_loader import load_all

    m = build(store.partners_df("CBE-E"), store.deliveries_df(branch_id="CBE-E"), load_all()["roads"],
              disruptions=[{"type": "accident", "road_id": "R1", "road_name": "Avinashi Road", "severity": "critical"}],
              detour_roads=["R9"], risk_labels={"D06": "Critical"}, selected="DP102",
              states={"DP102": "critical", "DP106": "available"})
    html = m.get_root().render()
    assert "DP102 · Karthik · 🏍️ · Critical" in html and "dp-legend" in html and "World_Dark_Gray_Base" in html
    print("map html:", len(html), "chars\nlive_map OK")
