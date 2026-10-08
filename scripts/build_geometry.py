"""Fetch real road shapes from the free OSRM server once and save them to data/route_geometry.json.

What gets cached (see modules/geometry.py):
  - every named road (data/roads.csv) routed through its waypoints along real streets
  - every vehicle's start position snapped onto the nearest road (display only)
  - driving legs for each vehicle's stop sequence, before AND after the demo plan is accepted
    (current spot -> stop 1 -> stop 2 ...), so the selected partner's route follows real roads

Run (needs internet; ~1 minute):  python scripts/build_geometry.py
The app and the tests never call OSRM themselves – they read this cache.
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["RIPPLE_OFFLINE"] = "1"  # the demo replay below must not call the LLM or OSRM through the seed
os.environ["RIPPLE_DB"] = str(Path(tempfile.mkdtemp()) / "geometry.db")

import json  # noqa: E402

from modules import geometry, operations, partner_scope, store  # noqa: E402
from modules.data_loader import load_all  # noqa: E402


def vehicle_legs(branch=None):
    """Legs (a, b) for every vehicle's stops in visiting order, starting at the vehicle."""
    legs = []
    vehicles = store.vehicles_df(branch)
    deliveries = store.deliveries_df(branch_id=branch, include_done=True)
    for v in vehicles.itertuples():
        stops = deliveries[deliveries["vehicle_id"] == v.vehicle_id].sort_values("eta_min")
        points = [(v.current_lat, v.current_lng)] + list(zip(stops["lat"], stops["lng"]))
        legs += list(zip(points, points[1:]))
    return legs


def main():
    data = load_all()
    cache = geometry.load_cache_file()
    wanted = {}
    for road in data["roads"].itertuples():
        wanted[f"road:{road.road_id}"] = ("route", [tuple(p) for p in road.points])
    for v in data["vehicles"].itertuples():
        wanted[f"snap:{v.vehicle_id}"] = ("nearest", (v.current_lat, v.current_lng))

    store.init_db()
    legs = vehicle_legs()
    # replay the demo (DP102 reports the Avinashi Road accident, East accepts) to cache the new legs too
    seen = partner_scope.preview_issue("DP102", "CBE-E", text="avinashi road accident, full block, 2 hours")
    issue_id = partner_scope.report_issue("DP102", "CBE-E", seen["problem"], transcript=seen["transcript"])
    operations.accept(issue_id, "build script", branch_id="CBE-E")
    legs += vehicle_legs()
    for a, b in legs:
        if geometry.point_key(*a) != geometry.point_key(*b):
            wanted[geometry.leg_key(a, b)] = ("route", [a, b])

    print(f"{len(wanted)} shapes wanted, {sum(k in cache for k in wanted)} already cached")
    geometry.fetch_missing(cache, wanted)
    for entry in cache.values():  # shapes fetched before loop removal existed
        if len(entry["points"]) > 2 and not entry.get("clean"):
            entry["points"], entry["clean"] = geometry.remove_loops(entry["points"]), True
    missing = [k for k in wanted if k not in cache]
    cache = {k: cache[k] for k in sorted(cache)}
    geometry.CACHE_FILE.write_text(json.dumps(cache, separators=(",", ":")), encoding="utf-8")
    moved = {k: (v.get("moved_m"), v.get("street")) for k, v in cache.items() if k.startswith("snap:")}
    print("snapped vehicles (metres moved, street):", moved)
    print(f"saved {len(cache)} shapes to {geometry.CACHE_FILE.name}; missing: {missing or 'none'}")


if __name__ == "__main__":
    main()
