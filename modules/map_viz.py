"""Live map of Coimbatore: roads, deliveries (coloured by risk), vehicles and the disruptions.

Uses Plotly's MapLibre map with the free OpenStreetMap style (no token needed).
"""
import plotly.graph_objects as go

from modules.data_loader import COIMBATORE_CENTER, road_midpoint
from modules.impact import as_list
from modules.risk import LABEL_COLORS, LABEL_ORDER

ROAD_COLOR = "#64748b"
BLOCKED_COLOR = "#dc2626"
ALT_COLOR = "#16a34a"
VEHICLE_COLOR = "#1d4ed8"
BACKUP_COLOR = "#a21caf"


def _ripple_point(disruption, roads, vehicles):
    """Where to draw a disruption: the broken vehicle, or the middle of the road."""
    if disruption.get("type") == "breakdown" and disruption.get("vehicle_id") in vehicles.index:
        v = vehicles.loc[disruption["vehicle_id"]]
        return v["current_lat"], v["current_lng"], f"{disruption['vehicle_id']} ({v['reg_no']})"
    if disruption.get("road_id") in roads.index:
        road = roads.loc[disruption["road_id"]]
        lat, lng = road_midpoint(road["points"])
        return lat, lng, road["name"]
    return None


def build_map(data, disruptions=None, risk_df=None, alt_road_ids=None, deliveries=None, height=520):
    """Return a Plotly map figure.

    disruptions:  one disruption dict or a list (optional)
    risk_df:      affected deliveries with risk_label (optional)
    alt_road_ids: road id or list of road ids used for rerouting, drawn in green (optional)
    deliveries:   override deliveries table (e.g. after applying the plan)
    """
    fig = go.Figure()
    roads = data["roads"]
    deliveries = data["deliveries"] if deliveries is None else deliveries
    disruptions = as_list(disruptions)
    # a breakdown stops one vehicle, not the road
    blocked = {d["road_id"] for d in disruptions if d.get("road_id") and d.get("type") != "breakdown"}
    alt_ids = set(as_list(alt_road_ids) if not isinstance(alt_road_ids, str) else [alt_road_ids])

    # ---- roads
    for _, road in roads.iterrows():
        is_blocked = road["road_id"] in blocked
        is_alt = road["road_id"] in alt_ids and not is_blocked
        color = BLOCKED_COLOR if is_blocked else ALT_COLOR if is_alt else ROAD_COLOR
        fig.add_trace(go.Scattermap(
            lat=[p[0] for p in road["points"]], lon=[p[1] for p in road["points"]], mode="lines",
            line=dict(width=9 if is_blocked else 6 if is_alt else 3, color=color),
            name=f"{road['name']}{' (blocked)' if is_blocked else ' (reroute)' if is_alt else ''}",
            hovertext=f"{road['name']} · {road['length_km']} km", hoverinfo="text",
            showlegend=bool(is_blocked or is_alt),
        ))

    # ---- deliveries, grouped by risk label for a clean legend
    labels = {}
    if risk_df is not None and not risk_df.empty:
        labels = dict(zip(risk_df["delivery_id"], risk_df["risk_label"]))
    shown = deliveries.assign(risk=deliveries["delivery_id"].map(labels).fillna("On track"))
    for label in LABEL_ORDER + ["On track"]:
        part = shown[shown["risk"] == label]
        if part.empty:
            continue
        fig.add_trace(go.Scattermap(
            lat=part["lat"], lon=part["lng"], mode="markers",
            marker=dict(size=15 if label != "On track" else 10, color=LABEL_COLORS[label]),
            name=f"{label} ({len(part)})",
            hovertext=[f"<b>{r.delivery_id}</b> {r.customer}<br>{r.address_area} · {r.priority}<br>"
                       f"Vehicle {r.vehicle_id} · ETA {r.planned_eta} · deadline {r.deadline}"
                       for r in part.itertuples()],
            hoverinfo="text",
        ))

    # ---- vehicles
    vehicles = data["vehicles"]
    for status, color, name in [("active", VEHICLE_COLOR, "Vehicles"), ("backup", BACKUP_COLOR, "Backup vehicle")]:
        part = vehicles[vehicles["status"] == status]
        if part.empty:
            continue
        fig.add_trace(go.Scattermap(
            lat=part["current_lat"], lon=part["current_lng"], mode="markers",
            marker=dict(size=20 if status == "backup" else 17, color=color),
            name=name,
            hovertext=[f"<b>{v.vehicle_id}</b> {v.reg_no}<br>{v.type} · {v.driver} · {v.status}"
                       for v in part.itertuples()],
            hoverinfo="text",
        ))

    # ---- disruption "ripple": concentric translucent circles around each disruption
    points = []
    for d in disruptions:
        found = _ripple_point(d, roads.set_index("road_id"), vehicles.set_index("vehicle_id"))
        if found:
            points.append((*found, d))
    for size, opacity in [(90, 0.12), (60, 0.2), (36, 0.35)]:
        if points:
            fig.add_trace(go.Scattermap(lat=[p[0] for p in points], lon=[p[1] for p in points], mode="markers",
                                        hoverinfo="skip", showlegend=False,
                                        marker=dict(size=size, color=BLOCKED_COLOR, opacity=opacity)))
    if points:
        fig.add_trace(go.Scattermap(
            lat=[p[0] for p in points], lon=[p[1] for p in points], mode="markers",
            marker=dict(size=18, color=BLOCKED_COLOR),
            name=f"Disruption{'s' if len(points) > 1 else ''} ({len(points)})",
            hovertext=[f"<b>{d.get('type', '').replace('_', ' ').title()}</b> · {where}<br>"
                       f"{d.get('severity')} · {d.get('duration_min')} min" for _, _, where, d in points],
            hoverinfo="text",
        ))

    fig.update_layout(
        map=dict(style="open-street-map", center=dict(lat=COIMBATORE_CENTER[0], lon=COIMBATORE_CENTER[1]), zoom=11.3),
        height=height,
        margin=dict(l=0, r=0, t=0, b=0),
        legend=dict(bgcolor="rgba(15,23,42,0.75)", font=dict(color="#e2e8f0", size=11), x=0.01, y=0.99),
        paper_bgcolor="rgba(0,0,0,0)",
    )
    return fig


if __name__ == "__main__":
    from modules.data_loader import load_all
    from modules.impact import compute_impact
    from modules.parser import parse_disruption
    from modules.risk import score_risk

    data = load_all()
    demo = parse_disruption("Accident near Avinashi Road, road blocked for 2 hours", data, use_llm=False)
    risk = score_risk(compute_impact(demo, data)[0], demo)
    fig = build_map(data, demo, risk, alt_road_ids="R9")
    print("traces:", len(fig.data))

    rain = parse_disruption("Heavy rain flooding at Trichy Road, 45 mins", data, use_llm=False)
    broken = parse_disruption("Murugan vandi breakdown aachu near Race Course", data, use_llm=False)
    fig = build_map(data, [demo, rain, broken], risk, alt_road_ids=["R9"])
    names = [t.name for t in fig.data if t.showlegend is not False and t.name]
    print("legend:", names)
    assert "Disruptions (3)" in names and "Race Course Road (blocked)" not in names
    print("map_viz OK")
