"""Analytics: numbers for the branch Analytics page. No Streamlit here.

Two sources, never mixed:
- history (synthetic, 60 days): models/history_summary.json from ml/summarise_history.py – delays by road and
  hour, service level per day, how accurate the delay model was on the test days;
- live (this branch, from the database): partner performance, offer response times, where disruptions happened.
"""
import json
from datetime import datetime
from functools import lru_cache

import pandas as pd

from modules import live_map, predict, store

SUMMARY = predict.MODEL_DIR / "history_summary.json"
FMT = "%Y-%m-%d %H:%M:%S"
MIN_CELL = 20  # fewer deliveries than this in a road × hour cell: too noisy to show
ANSWERS = ("Accepted", "Declined")  # an escalation result that starts with one of these is the partner's answer


@lru_cache(maxsize=2)
def _summary(stamp):
    return json.loads(SUMMARY.read_text(encoding="utf-8"))


def history_summary():
    """The history summary, or {} when the file is missing or broken."""
    try:
        return _summary(SUMMARY.stat().st_mtime)
    except (OSError, ValueError):
        return {}


def road_name(road_id):
    """Short road name for charts (R1 -> Avinashi Rd)."""
    return predict.ROAD_SHORT.get(road_id, road_id)


def delay_matrix(summary):
    """Rows = roads (worst first), columns = hour of day, values = mean minutes late (cells under MIN_CELL left out)."""
    rows = pd.DataFrame(summary.get("delay_by_road_hour", []))
    if rows.empty:
        return rows
    rows = rows[rows["n"] >= MIN_CELL]
    grid = rows.pivot(index="road", columns="hour", values="delay_min")
    grid = grid.loc[grid.mean(axis=1).sort_values(ascending=False).index]
    grid.index = [road_name(r) for r in grid.index]
    return grid


def sla_trend(summary):
    """date, on-time share (0–1), deliveries – one row per day."""
    rows = pd.DataFrame(summary.get("sla_by_day", []))
    if not rows.empty:
        rows["date"] = pd.to_datetime(rows["date"])
    return rows


def accuracy(summary):
    """(MAE by road, reliability table) for the delay model on the test days."""
    acc = summary.get("accuracy", {})
    by_road = pd.DataFrame(acc.get("mae_by_road", []))
    if not by_road.empty:
        by_road = by_road.assign(road=by_road["road"].map(road_name)).sort_values("mae_min", ascending=False)
    return by_road, pd.DataFrame(acc.get("reliability", []))


# ---------------------------------------------------------------- live (database)
def _minutes(start, end):
    try:
        return (datetime.strptime(end, FMT) - datetime.strptime(start, FMT)).total_seconds() / 60
    except (TypeError, ValueError):
        return None


def response_times(branch_id):
    """One row per offer a partner answered: dp_id, delivery_id, minutes from offer to answer, accepted?"""
    steps = store.escalations_df(branch_id=branch_id, limit=5000)
    out = []
    if steps.empty:
        return pd.DataFrame(columns=["dp_id", "delivery_id", "minutes", "accepted"])
    sent = {}
    for step in steps.iloc[::-1].to_dict("records"):  # oldest first
        key = (step["delivery_id"], step["dp_id"])
        result = str(step["result"] or "")
        if result == "Sent":
            sent[key] = step["time"]
        elif result.startswith(ANSWERS) and key in sent:
            minutes = _minutes(sent.pop(key), step["time"])
            if minutes is not None:
                out.append({"dp_id": step["dp_id"], "delivery_id": step["delivery_id"],
                            "minutes": round(max(minutes, 0.0), 1), "accepted": result.startswith("Accepted")})
    return pd.DataFrame(out, columns=["dp_id", "delivery_id", "minutes", "accepted"])


def _on_time(d):
    """Delivered within the promised time. The demo runs on a simulated clock (09:00), so the stop's ETA when it was
    delivered is used; without an ETA, the real delivery time."""
    eta = d.get("planned_eta") if isinstance(d.get("planned_eta"), str) else str(d.get("delivered_at") or "")[11:16]
    return bool(eta) and eta <= str(d["deadline"])


def partner_performance(branch_id):
    """Per partner of the branch: delivered, on time %, open stops, offers answered, mean answer time, declined."""
    partners = store.partners_df(branch_id)
    deliveries = store.deliveries_df(branch_id=branch_id)
    answers = response_times(branch_id)
    rows = []
    for p in partners.to_dict("records"):
        mine = deliveries[deliveries["vehicle_id"] == p["vehicle_id"]]
        done = mine[mine["status"] == "delivered"]
        on_time = [_on_time(d) for d in done.to_dict("records")]
        theirs = answers[answers["dp_id"] == p["partner_id"]]
        rows.append({
            "partner_id": p["partner_id"], "name": p["name"],
            "delivered": len(done),
            "on_time": sum(on_time) / len(on_time) if on_time else None,
            "open": int((~mine["status"].isin(["delivered", "failed"])).sum()),
            "answered": len(theirs),
            "answer_min": float(theirs["minutes"].mean()) if len(theirs) else None,
            "declined": int((~theirs["accepted"]).sum()) if len(theirs) else 0,
        })
    return pd.DataFrame(rows, columns=["partner_id", "name", "delivered", "on_time", "open", "answered",
                                       "answer_min", "declined"])


def today_sla(branch_id):
    """(delivered, on time) for the branch's orders today."""
    perf = partner_performance(branch_id)
    delivered = int(perf["delivered"].sum()) if len(perf) else 0
    on_time = sum(int(round(r.on_time * r.delivered)) for r in perf.itertuples() if pd.notna(r.on_time))
    return delivered, on_time


def disruption_points(branch_id, roads):
    """[(lat, lng, weight)] for every disruption the branch has had (active or ended) – for a heatmap.
    Weight follows severity, so one critical closure counts more than a minor slowdown."""
    weight = {"critical": 1.0, "high": 0.8, "medium": 0.55, "low": 0.35}
    shapes = store.route_geometry()
    points = []
    for d in store.disruption_history(branch_id):
        point = live_map.disruption_point(d, roads, shapes)
        if point:
            points.append((point[0], point[1], weight.get(str(d.get("severity", "")).lower(), 0.5)))
    return points
