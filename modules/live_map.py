"""Realistic live map (Leaflet via folium, no API key).

- Basemaps (all free, no key): Esri World Street Map (default, Google-Maps-like), OpenStreetMap, Esri light grey,
  Esri satellite. (CARTO Voyager/Positron now require an API key, so they are not used.)
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

STATE = {  # same status language as modules/ui.py
    "normal": ("Normal", "#16A34A"), "delayed": ("Delayed", "#EAB308"), "critical": ("Critical", "#DC2626"),
    "available": ("Available", "#2563EB"), "break": ("Break", "#94A3B8"), "off": ("Off", "#94A3B8"),
}
RISK_STATE = {"Critical": "critical", "High": "delayed", "Medium": "delayed", "Low": "normal"}
VEHICLE_EMOJI = {"bike": "🏍️", "car": "🚗", "van": "🚐", "truck": "🚚"}
RADIUS_M = {"critical": 900, "high": 700, "medium": 500, "low": 350}
BLOCKED, DETOUR, SELECTED, ROUTE, DONE = "#DC2626", "#16A34A", "#2563EB", "#94A3B8", "#9CA3AF"

MAP_CSS = """
<style>
.dp-veh { position: relative; width: 34px; height: 34px; border-radius: 50%; background: #fff; border: 4px solid var(--c);
  display: flex; align-items: center; justify-content: center; font-size: 17px; line-height: 1;
  box-shadow: 0 2px 8px rgba(15,23,42,.35); box-sizing: border-box; }
.dp-veh.sel { transform: scale(1.22); box-shadow: 0 0 0 5px rgba(37,99,235,.30), 0 2px 10px rgba(15,23,42,.4); }
.dp-veh.fade { opacity: .45; }
.dp-veh.pulse::after { content: ""; position: absolute; inset: -9px; border-radius: 50%; border: 3px solid rgba(220,38,38,.6);
  animation: dp-ring 1.6s ease-out infinite; }
@keyframes dp-ring { 0% { transform: scale(.7); opacity: 1; } 100% { transform: scale(1.35); opacity: 0; } }
.dp-stop { width: 20px; height: 20px; border-radius: 50%; color: #fff; font: 700 11px/1 Inter, Arial, sans-serif;
  display: flex; align-items: center; justify-content: center; border: 2px solid #fff; box-sizing: border-box;
  box-shadow: 0 1px 4px rgba(0,0,0,.35); }
.dp-stop.fade { opacity: .4; }
.dp-warn { width: 34px; height: 34px; border-radius: 50%; background: #fff; border: 3px solid #DC2626; display: flex;
  align-items: center; justify-content: center; font-size: 17px; box-shadow: 0 2px 10px rgba(220,38,38,.45); box-sizing: border-box; }
.dp-legend { background: rgba(255,255,255,.95); border-radius: 10px; padding: 8px 10px; font: 600 11px/1.5 Inter, Arial, sans-serif;
  color: #0F172A; box-shadow: 0 2px 10px rgba(15,23,42,.18); }
.dp-legend span { display: inline-flex; align-items: center; gap: 5px; margin-right: 8px; white-space: nowrap; }
.dp-legend i { width: 9px; height: 9px; border-radius: 50%; display: inline-block; }
.dp-legend b { width: 16px; height: 0; border-top: 3px solid; display: inline-block; }
.leaflet-tooltip { font: 600 12px/1.4 Inter, Arial, sans-serif; border-radius: 8px; }
.leaflet-popup-content { font: 13px/1.45 Inter, Arial, sans-serif; margin: 10px 12px; }
.leaflet-control-attribution { font-size: 9px !important; opacity: .8; }
@media (max-width: 640px) { .dp-legend { font-size: 10px; padding: 6px 8px; max-width: 220px; } }
@media (prefers-reduced-motion: reduce) { .dp-veh.pulse::after { animation: none; } }
</style>"""

LEGEND = ("<span><i style='background:#16A34A'></i>Normal</span><span><i style='background:#EAB308'></i>Delayed</span>"
          "<span><i style='background:#DC2626'></i>Critical</span><span><i style='background:#2563EB'></i>Available</span><br>"
          "<span><b style='border-color:#DC2626;border-top-style:dashed'></b>Blocked</span>"
          "<span><b style='border-color:#16A34A'></b>Alternate</span><span><b style='border-color:#2563EB'></b>Route</span>")


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
    # CARTO basemaps (Voyager/Positron) now need an API key, so the keyless Esri street map is the default
    folium.TileLayer(xyz.Esri.WorldStreetMap, name="Map", max_zoom=19).add_to(m)
    folium.TileLayer(xyz.OpenStreetMap.Mapnik, name="Street", show=False).add_to(m)
    folium.TileLayer(xyz.Esri.WorldGrayCanvas, name="Light", show=False).add_to(m)
    folium.TileLayer(xyz.Esri.WorldImagery, name="Satellite", show=False).add_to(m)
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
    assert "DP102 · Karthik · 🏍️ · Critical" in html and "dp-legend" in html and "World_Street_Map" in html
    print("map html:", len(html), "chars\nlive_map OK")
