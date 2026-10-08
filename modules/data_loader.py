"""Load the demo data (roads, vehicles, deliveries, partners, places) and shared helpers.

Times are handled as "minutes since midnight" so maths stays simple.
The app uses a FIXED simulated clock: now = 09:00 today.
No Streamlit in here, so the same code also powers the mobile API.
"""
import json
import math
from datetime import date
from functools import lru_cache
from pathlib import Path

import pandas as pd

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


def load_all():
    """Return {'roads', 'vehicles', 'deliveries'} DataFrames with parsed columns.

    Files are read once; every caller gets its own copy, so changing it is safe.
    """
    return {name: df.copy() for name, df in _read_csvs().items()}


@lru_cache(maxsize=1)
def _read_csvs():
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


@lru_cache(maxsize=1)
def _read_partners():
    return pd.read_csv(DATA_DIR / "partners.csv")


def load_partners():
    """Delivery partners: one per vehicle (the backup van's driver is on standby)."""
    return _read_partners().copy()


@lru_cache(maxsize=1)
def _read_branches():
    return pd.read_csv(DATA_DIR / "branches.csv")


def load_branches():
    """The demo branches (Coimbatore East / Central / South)."""
    return _read_branches().copy()


@lru_cache(maxsize=1)
def _read_places():
    places = pd.read_csv(DATA_DIR / "places.csv")
    places["aliases"] = places["aliases"].apply(lambda s: [a.lower() for a in _split_pipe(s)])
    return places


def load_places():
    """Canonical Coimbatore places (roads, areas, landmarks) with aliases and Tamil names."""
    return _read_places().copy()


def nearest_place(lat, lng, kinds=("area", "landmark")):
    """Name of the closest known area/landmark, e.g. for 'Murugan is near RS Puram'."""
    places = _read_places()
    places = places[places["kind"].isin(kinds)]
    distances = places.apply(lambda p: haversine_km(lat, lng, p["lat"], p["lng"]), axis=1)
    return places.loc[distances.idxmin(), "name"]


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
    partners, places = load_partners(), load_places()
    assert set(partners["vehicle_id"]) <= set(data["vehicles"]["vehicle_id"])  # spare vehicles have no partner
    assert set(partners["branch_id"]) == set(load_branches()["branch_id"])
    assert set(places["road_id"]) <= set(data["roads"]["road_id"])
    print(f"partners: {len(partners)} | places: {len(places)} | V1 is near:",
          nearest_place(11.0080, 76.9480))
    print("data_loader OK")
