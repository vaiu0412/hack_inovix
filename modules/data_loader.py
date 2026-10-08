"""Load the demo data (roads, vehicles, deliveries) and shared helpers.

Times are handled as "minutes since midnight" so maths stays simple.
The app uses a FIXED simulated clock: now = 09:00 today.
"""
import json
import math
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

NOW_MIN = 9 * 60  # simulated clock: 09:00
COIMBATORE_CENTER = (11.0168, 76.9800)


def hhmm_to_min(text):
    """'10:30' -> 630"""
    hours, minutes = str(text).strip().split(":")
    return int(hours) * 60 + int(minutes)


def min_to_hhmm(minutes):
    """630 -> '10:30'"""
    minutes = int(round(minutes))
    return f"{(minutes // 60) % 24:02d}:{minutes % 60:02d}"


def now_label():
    """Text for the simulated clock, e.g. 'Thu 08 Oct 2026 · 09:00'."""
    return f"{date.today().strftime('%a %d %b %Y')} · {min_to_hhmm(NOW_MIN)}"


def haversine_km(lat1, lng1, lat2, lng2):
    """Straight-line distance between two points in km."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def road_length_km(points):
    """Length of a polyline given as [[lat, lng], ...]."""
    return sum(haversine_km(*a, *b) for a, b in zip(points, points[1:]))


def road_midpoint(points):
    """Middle point of a road polyline (good enough for markers)."""
    return points[len(points) // 2]


def _split_pipe(text):
    if not isinstance(text, str):
        return []
    return [part.strip() for part in text.split("|") if part.strip()]


@st.cache_data
def load_all():
    """Return {'roads', 'vehicles', 'deliveries'} DataFrames with parsed columns."""
    roads = pd.read_csv(DATA_DIR / "roads.csv")
    roads["aliases"] = roads["aliases"].apply(lambda s: [a.lower() for a in _split_pipe(s)])
    roads["points"] = roads["points"].apply(json.loads)
    roads["length_km"] = roads["points"].apply(road_length_km).round(2)

    vehicles = pd.read_csv(DATA_DIR / "vehicles.csv")
    vehicles["route_roads"] = vehicles["route_roads"].apply(_split_pipe)

    deliveries = pd.read_csv(DATA_DIR / "deliveries.csv")
    deliveries["eta_min"] = deliveries["planned_eta"].apply(hhmm_to_min)
    deliveries["deadline_min"] = deliveries["deadline"].apply(hhmm_to_min)
    deliveries = deliveries.sort_values(["vehicle_id", "stop_order"]).reset_index(drop=True)

    return {"roads": roads, "vehicles": vehicles, "deliveries": deliveries}


if __name__ == "__main__":
    data = load_all()
    for name, df in data.items():
        print(f"{name}: {len(df)} rows")
    on_avinashi = data["vehicles"][data["vehicles"]["route_roads"].apply(lambda r: "R1" in r)]
    print("Vehicles using Avinashi Road (R1):", list(on_avinashi["vehicle_id"]))
    assert len(on_avinashi) == 3, "demo tuning: Avinashi must be in exactly 3 routes"
    # every delivery's road must be on its vehicle's route
    routes = data["vehicles"].set_index("vehicle_id")["route_roads"]
    for _, d in data["deliveries"].iterrows():
        assert d["road_id"] in routes[d["vehicle_id"]], d["delivery_id"]
    print("Road lengths (km):", dict(zip(data["roads"]["road_id"], data["roads"]["length_km"])))
    print("Clock:", now_label())
    print("data_loader OK")
