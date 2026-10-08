"""Live map of Coimbatore: roads, deliveries (coloured by risk), vehicles and the disruption.

Uses Plotly's MapLibre map with the free OpenStreetMap style (no token needed).
"""
import plotly.graph_objects as go

from modules.data_loader import COIMBATORE_CENTER, road_midpoint
from modules.risk import LABEL_COLORS, LABEL_ORDER

ROAD_COLOR = "#64748b"
BLOCKED_COLOR = "#dc2626"
ALT_COLOR = "#16a34a"
VEHICLE_COLOR = "#1d4ed8"
BACKUP_COLOR = "#a21caf"


def build_map(data, disruption=None, risk_df=None, alt_road_id=None, deliveries=None, height=520):
    """Return a Plotly map figure.

    risk_df:     affected deliveries with risk_label (optional)
    alt_road_id: road used for rerouting, drawn in green (optional)
    deliveries:  override deliveries table (e.g. after applying the plan)
    """
    fig = go.Figure()
    roads = data["roads"]
    deliveries = data["deliveries"] if deliveries is None else deliveries
    blocked = (disruption or {}).get("road_id")

    # ---- roads
    for _, road in roads.iterrows():
        is_blocked = road["road_id"] == blocked
        is_alt = road["road_id"] == alt_road_id
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

    # ---- disruption "ripple": concentric translucent circles
    if blocked:
        road = roads.set_index("road_id").loc[blocked]
        lat, lng = road_midpoint(road["points"])
        for size, opacity in [(90, 0.12), (60, 0.2), (36, 0.35)]:
            fig.add_trace(go.Scattermap(lat=[lat], lon=[lng], mode="markers", hoverinfo="skip",
                                        marker=dict(size=size, color=BLOCKED_COLOR, opacity=opacity),
                                        showlegend=False))
        fig.add_trace(go.Scattermap(
            lat=[lat], lon=[lng], mode="markers", marker=dict(size=18, color=BLOCKED_COLOR),
            name="Disruption",
            hovertext=f"<b>{disruption.get('type', '').title()}</b> on {road['name']}<br>"
                      f"{disruption.get('severity')} · {disruption.get('duration_min')} min",
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
    fig = build_map(data, demo, risk, alt_road_id="R9")
    print("traces:", len(fig.data))
    print("map_viz OK")
