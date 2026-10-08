"""Real road shapes for the map, from the free OSRM server – fetched once, cached, never at demo time.

Keys in the cache (data/route_geometry.json, loaded into the SQLite table route_geometry at seed):
  road:R1                 the named road, following real streets through its waypoints
  snap:V1                 the vehicle's start position snapped onto the nearest road (display only)
  leg:11.00800,76.94800>11.00860,76.95050   driving path between two points (current spot -> next stop)

The map reads only the cache. If a shape is missing (OSRM unreachable when seeding), it falls back to
the stored waypoints / a straight line, so the demo never waits on the network.
"""
import json
import os
import time
import urllib.request
from pathlib import Path

OSRM = "https://router.project-osrm.org"
CACHE_FILE = Path(__file__).resolve().parent.parent / "data" / "route_geometry.json"
USER_AGENT = "DEPORT/2.0 (+https://github.com/vaiu0412/hack_inovix)"
COIMBATORE_BOUNDS = ((10.85, 76.85), (11.15, 77.10))  # (min lat, min lng), (max lat, max lng)


def point_key(lat, lng):
    return f"{float(lat):.5f},{float(lng):.5f}"


def leg_key(a, b):
    return f"leg:{point_key(*a)}>{point_key(*b)}"


def in_coimbatore(lat, lng):
    (lat0, lng0), (lat1, lng1) = COIMBATORE_BOUNDS
    return lat0 <= float(lat) <= lat1 and lng0 <= float(lng) <= lng1


# ---------------------------------------------------------------- OSRM (used only by the seed/build script)
def online():
    return os.getenv("RIPPLE_OFFLINE") != "1"


def _get(url, timeout=8):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as reply:
        return json.loads(reply.read().decode("utf-8"))


def osrm_route(points, timeout=8):
    """Driving path through [(lat, lng), ...] in order -> [[lat, lng], ...] or None."""
    coords = ";".join(f"{lng:.6f},{lat:.6f}" for lat, lng in points)
    try:
        data = _get(f"{OSRM}/route/v1/driving/{coords}?overview=full&geometries=geojson", timeout)
    except Exception:
        return None
    if data.get("code") != "Ok" or not data.get("routes"):
        return None
    return [[round(lat, 5), round(lng, 5)] for lng, lat in data["routes"][0]["geometry"]["coordinates"]]


def osrm_nearest(lat, lng, timeout=8):
    """Nearest point on a road -> ([lat, lng], metres moved, street name) or None."""
    try:
        data = _get(f"{OSRM}/nearest/v1/driving/{lng:.6f},{lat:.6f}?number=1", timeout)
    except Exception:
        return None
    if data.get("code") != "Ok" or not data.get("waypoints"):
        return None
    wp = data["waypoints"][0]
    return [round(wp["location"][1], 5), round(wp["location"][0], 5)], round(wp.get("distance", 0)), wp.get("name", "")


def remove_loops(points, close_m=35, min_loop_m=120):
    """Cut U-turn spurs and loops from a routed shape: when the path comes back within close_m of an
    earlier point after travelling at least min_loop_m, jump to the later point. (Routing through
    hand-placed waypoints forces such detours when a point sits on the far side of a divided road.)"""
    from modules.data_loader import haversine_km

    cum = [0.0]
    for a, b in zip(points, points[1:]):
        cum.append(cum[-1] + haversine_km(a[0], a[1], b[0], b[1]) * 1000)
    out, i, n = [], 0, len(points)
    while i < n:
        out.append(points[i])
        jump = next((j for j in range(n - 1, i + 1, -1) if cum[j] - cum[i] >= min_loop_m
                     and haversine_km(points[i][0], points[i][1], points[j][0], points[j][1]) * 1000 <= close_m), None)
        i = jump if jump else i + 1
    return out


def cache_stamp():
    """Changes whenever data/route_geometry.json changes (size + modified time)."""
    try:
        info = CACHE_FILE.stat()
        return f"{info.st_size}-{int(info.st_mtime)}"
    except OSError:
        return "none"


def load_cache_file():
    try:
        return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def fetch_missing(cache, wanted, pause=0.35, log=print):
    """Fill cache entries that are missing. wanted: {key: ("route", points) | ("nearest", (lat, lng))}."""
    fetched = 0
    for key, (kind, arg) in wanted.items():
        if key in cache:
            continue
        if kind == "route":
            result = osrm_route(arg)
            if result:
                cache[key] = {"points": remove_loops(result), "source": "osrm", "clean": True}
        else:
            result = osrm_nearest(*arg)
            if result:
                point, moved, street = result
                cache[key] = {"points": [point], "source": "osrm", "moved_m": moved, "street": street}
        fetched += 1
        log(f"{'ok ' if key in cache else 'MISS'} {key}")
        time.sleep(pause)  # be polite to the free demo server
    return fetched
