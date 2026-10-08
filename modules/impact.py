"""WHAT IS AFFECTED? Find the deliveries hit by a disruption and their new ETAs.

Rules:
- Road disruption: every vehicle whose route uses the road is affected.
  Its deliveries on that road and on any LATER road in the route are affected
  (the delay cascades downstream).
- Vehicle breakdown: all remaining deliveries of that vehicle are affected.
- delay = min(duration, detour penalty for the severity) x severity factor
          + a small extra per later stop (cascade).
"""
import pandas as pd

from modules.data_loader import NOW_MIN, min_to_hhmm

DETOUR_PENALTY = {"low": 15, "medium": 30, "high": 60, "critical": 90}  # minutes
SEVERITY_FACTOR = {"low": 0.5, "medium": 0.75, "high": 1.0, "critical": 1.0}
CASCADE_STEP_MIN = 5  # extra minutes for every later affected stop

IMPACT_COLUMNS = [
    "delivery_id", "customer", "address_area", "priority", "vehicle_id", "road_id", "road_name",
    "stop_order", "cascade_index", "on_blocked_road", "planned_eta", "deadline", "delay_min",
    "new_eta", "slack_min", "will_miss", "eta_min", "deadline_min", "new_eta_min", "lat", "lng",
    "customer_phone",
]


def base_delay(disruption):
    severity = disruption.get("severity", "medium")
    duration = int(disruption.get("duration_min") or 0)
    if disruption.get("type") == "breakdown":
        # the vehicle waits for the repair, capped by the time to send help
        return round(min(duration, DETOUR_PENALTY["critical"]) * SEVERITY_FACTOR[severity])
    return round(min(duration, DETOUR_PENALTY[severity]) * SEVERITY_FACTOR[severity])


def find_affected(disruption, data):
    """Return a list of (delivery_row, cascade_index, on_blocked_road)."""
    deliveries = data["deliveries"]
    deliveries = deliveries[deliveries["eta_min"] >= NOW_MIN]  # only stops not yet done
    vehicles = data["vehicles"].set_index("vehicle_id")
    road_id = disruption.get("road_id")
    vehicle_id = disruption.get("vehicle_id")
    rows = []

    if disruption.get("type") == "breakdown" and vehicle_id in vehicles.index:
        own = deliveries[deliveries["vehicle_id"] == vehicle_id].sort_values("stop_order")
        for k, (_, d) in enumerate(own.iterrows()):
            rows.append((d, k, d["road_id"] == road_id))
        return rows

    if disruption.get("type") == "requirement_change" or not road_id:
        return rows

    for vid, vehicle in vehicles.iterrows():
        route = vehicle["route_roads"]
        if road_id not in route:
            continue
        block_index = route.index(road_id)
        own = deliveries[deliveries["vehicle_id"] == vid].sort_values("stop_order")
        downstream = own[own["road_id"].apply(lambda r: r in route and route.index(r) >= block_index)]
        for k, (_, d) in enumerate(downstream.iterrows()):
            rows.append((d, k, d["road_id"] == road_id))
    return rows


def compute_impact(disruption, data):
    """Return (impact DataFrame, summary dict)."""
    road_names = data["roads"].set_index("road_id")["name"]
    delay0 = base_delay(disruption)
    records = []
    for d, k, on_blocked in find_affected(disruption, data):
        delay = delay0 + k * CASCADE_STEP_MIN
        new_eta = int(d["eta_min"] + delay)
        records.append({
            **{c: d[c] for c in ["delivery_id", "customer", "address_area", "priority", "vehicle_id",
                                 "road_id", "stop_order", "planned_eta", "deadline", "eta_min",
                                 "deadline_min", "lat", "lng", "customer_phone"]},
            "road_name": road_names.get(d["road_id"], d["road_id"]),
            "cascade_index": k,
            "on_blocked_road": bool(on_blocked),
            "delay_min": delay,
            "new_eta_min": new_eta,
            "new_eta": min_to_hhmm(new_eta),
            "slack_min": int(d["deadline_min"] - new_eta),
            "will_miss": bool(d["deadline_min"] - new_eta < 0),
        })
    impact = pd.DataFrame(records, columns=IMPACT_COLUMNS)

    summary = {
        "affected_roads": [],
        "affected_vehicles": sorted(impact["vehicle_id"].unique().tolist()),
        "affected_deliveries": int(len(impact)),
        "total_delay_min": int(impact["delay_min"].sum()) if len(impact) else 0,
        "predicted_misses": int(impact["will_miss"].sum()) if len(impact) else 0,
        "base_delay_min": delay0,
        "message": "",
    }
    if disruption.get("road_id"):
        summary["affected_roads"] = [road_names.get(disruption["road_id"])]
    if impact.empty:
        if disruption.get("type") == "requirement_change":
            summary["message"] = "Requirement change only: no road or vehicle is blocked, so no ripple."
        elif not disruption.get("road_id") and not disruption.get("vehicle_id"):
            summary["message"] = "Couldn't match a known road or vehicle. Please pick the road manually."
        else:
            summary["message"] = "No impact: no planned delivery uses this road after now."
    return impact, summary


if __name__ == "__main__":
    from modules.data_loader import load_all
    from modules.parser import parse_disruption

    data = load_all()
    demo = parse_disruption("Accident near Avinashi Road, road blocked for 2 hours", data, use_llm=False)
    impact, summary = compute_impact(demo, data)
    print(impact[["delivery_id", "vehicle_id", "road_id", "priority", "cascade_index", "planned_eta",
                  "new_eta", "deadline", "slack_min", "will_miss"]].to_string(index=False))
    print(summary)
    assert summary["affected_vehicles"] == ["V1", "V2", "V3"]
    assert 8 <= summary["affected_deliveries"] <= 10

    breakdown = parse_disruption("Murugan vandi breakdown aachu near Race Course", data, use_llm=False)
    print("Breakdown:", compute_impact(breakdown, data)[1])
    unknown = parse_disruption("Something happened somewhere", data, use_llm=False)
    print("Unknown:", compute_impact(unknown, data)[1]["message"])
    print("impact OK")
