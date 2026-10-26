"""Real-world feeds, into the SAME impact -> recommend -> approve flow as a partner's report. No Streamlit imports.

- Weather (OpenWeatherMap, every 10 min): sets today's weather for the delay model; heavy rain opens a "Weather
  risk" alert (flooding on the branch's most flood-prone road) – once per branch per day.
- Traffic (TomTom, every 10 min): heavy congestion or a closure on a road the branch's vehicles use becomes a
  suggestion; the Branch Admin confirms it (-> an alert with a plan) or dismisses it. Demo mode: a scripted event
  when an admin runs a traffic check.
- GPS (modules/tracking.py): partner phones every 30 s; Demo mode can simulate movement.

poll() is called by the admin pages (every 20 s) and the API (every minute); each feed keeps its own pace.
Without keys nothing is fetched: weather is set by hand and traffic checks are scripted (Demo mode).
"""
import json
from datetime import datetime

from modules import issues, store, tracking
from modules.data_loader import COIMBATORE_CENTER, load_all
from services import traffic, weather

WEATHER_EVERY_MIN = 10
TRAFFIC_EVERY_MIN = 10
# roads whose underpasses / low stretches flood first in heavy rain, most likely first
FLOOD_PRONE = ("R1", "R10", "R2", "R7")
SEVERITY = {"closed": "critical", "severe": "high", "heavy": "medium"}
FMT = "%Y-%m-%d %H:%M:%S"


def _now():
    return tracking.now()


def _due(key, minutes):
    """True (and the clock restarts) when `minutes` passed since the feed last ran."""
    last = store.get_setting(key)
    if last and (_now() - datetime.strptime(last, FMT)).total_seconds() < minutes * 60:
        return False
    store.set_setting(key, _now().strftime(FMT))
    return True


def _branch_roads(branch_id):
    """Roads the branch's vehicles use, most used first."""
    counts = {}
    for route in store.vehicles_df(branch_id)["route_roads"]:
        for road in route:
            counts[road] = counts.get(road, 0) + 1
    return sorted(counts, key=lambda r: -counts[r])


def _open_alert(branch_id, source=None, road_id=None):
    """An alert still open in this branch (from this feed / on this road) – no second one for the same thing."""
    for issue in store.list_issues(store.OPEN_ISSUE_STATUSES, branch_id=branch_id):
        same_road = road_id is None or (issue.get("problem") or {}).get("road_id") == road_id
        if same_road and (source is None or issue["source"] == source):
            return True
    return False


# ---------------------------------------------------------------- weather
def weather_status():
    """The last live reading {weather, rain_mm, description, temp_c, source, updated_at}, or None."""
    text = store.get_setting("weather_live")
    return json.loads(text) if text else None


def poll_weather():
    """Fetch the weather (with a key), set it for the delay model, raise Weather risk alerts in heavy rain."""
    if not weather.configured():
        return None
    branches = store.branches_df()
    active = branches[branches["is_active"] == 1]
    point = (active.iloc[0]["lat"], active.iloc[0]["lng"]) if len(active) else COIMBATORE_CENTER
    reading = weather.current(*point)
    if not reading:
        return None
    store.set_setting("weather_now", reading["weather"], "OpenWeatherMap")
    store.set_setting("weather_live", json.dumps({**reading, "updated_at": _now().strftime(FMT)}), "OpenWeatherMap")
    if reading["weather"] == "heavy_rain":
        for branch_id in active["branch_id"]:
            weather_risk(branch_id, reading)
    return reading


def weather_risk(branch_id, reading):
    """Open a 'Weather risk' alert (flooding on the branch's most flood-prone road), once per day. Returns its id."""
    today, key = _now().strftime("%Y-%m-%d"), f"weather_risk_day_{branch_id}"
    if store.get_setting(key) == today or _open_alert(branch_id, source="auto-weather"):
        return None
    used = _branch_roads(branch_id)
    road = next((r for r in FLOOD_PRONE if r in used), used[0] if used else None)
    if road is None:
        return None
    name = load_all()["roads"].set_index("road_id")["name"].get(road, road)
    problem = {"type": "flood", "road_id": road, "road_name": name, "place": name, "severity": "high",
               "duration_min": 60, "confidence": 0.6, "needs_location": False, "reporter_name": "Weather feed"}
    problem["summary"] = issues.summarize(problem)
    said = (f"Weather risk: {reading.get('description') or 'heavy rain'}, {reading.get('rain_mm', 0)} mm/h "
            f"({reading.get('source', 'weather feed')}) – {name} floods first.")
    store.set_setting(key, today, "weather feed")
    return issues.submit("OPS", problem, transcript=said, engine="weather feed", source="auto-weather",
                         branch_id=branch_id)


# ---------------------------------------------------------------- traffic
def check_traffic(branch_id, demo=False):
    """Read traffic on the branch's roads (TomTom, or the scripted Demo event); new suggestions for jams.
    Returns the readings {road_id: reading + level}."""
    roads = load_all()["roads"].set_index("road_id")
    readings = {}
    for road_id in _branch_roads(branch_id):
        if road_id not in roads.index:
            continue
        points = roads.loc[road_id, "points"]
        lat, lng = points[len(points) // 2]
        reading = traffic.demo_flow(road_id) if demo else traffic.flow(lat, lng)
        if not reading:
            continue
        reading["level"] = traffic.level(reading)
        readings[road_id] = reading
        if reading["level"] != "normal":
            _suggest(branch_id, road_id, reading)
    store.set_setting(f"traffic_checked_{branch_id}", _now().strftime(FMT))
    return readings


def _suggest(branch_id, road_id, reading):
    today = _now().strftime("%Y-%m-%d")
    with store.connect() as conn:
        exists = conn.execute("SELECT 1 FROM suggestions WHERE branch_id = ? AND road_id = ? AND kind = 'traffic' "
                              "AND time LIKE ?", (branch_id, road_id, f"{today}%")).fetchone()
    if exists or _open_alert(branch_id, road_id=road_id):
        return None
    with store.connect() as conn:
        cur = conn.execute("INSERT INTO suggestions(time, branch_id, kind, road_id, data) VALUES (?,?,?,?,?)",
                           (_now().strftime(FMT), branch_id, "traffic", road_id, json.dumps(reading)))
        store._bump(conn)
    store.log_event("system", f"Traffic feed: {reading['level']} traffic on {road_id} "
                    f"({reading['current_kmph']:.0f} km/h, usually {reading['free_kmph']:.0f})", branch_id=branch_id)
    return cur.lastrowid


def suggestions(branch_id, status="new"):
    """Traffic suggestions waiting for the admin: [{suggestion_id, road_id, road_name, level, ...}]."""
    names = load_all()["roads"].set_index("road_id")["name"]
    with store.connect() as conn:
        rows = conn.execute("SELECT * FROM suggestions WHERE branch_id = ? AND status = ? ORDER BY id DESC",
                            (branch_id, status)).fetchall()
    out = []
    for r in rows:
        data = json.loads(r["data"])
        out.append({"suggestion_id": r["id"], "time": r["time"], "road_id": r["road_id"],
                    "road_name": names.get(r["road_id"], r["road_id"]), **data})
    return out


def _suggestion(suggestion_id, branch_id):
    with store.connect() as conn:
        row = conn.execute("SELECT * FROM suggestions WHERE id = ? AND branch_id = ?",
                           (suggestion_id, branch_id)).fetchone()
    if row is None:
        raise PermissionError("Not a suggestion of your branch")
    if row["status"] != "new":
        raise ValueError("Already handled")
    return dict(row)


def confirm(suggestion_id, actor):
    """The admin agrees: an alert with a full plan (same flow as a partner's report). Returns the issue id."""
    branch_id = actor["branch_id"]
    row = _suggestion(suggestion_id, branch_id)
    reading = json.loads(row["data"])
    name = load_all()["roads"].set_index("road_id")["name"].get(row["road_id"], row["road_id"])
    kind = "closure" if reading["level"] == "closed" else "traffic"
    problem = {"type": kind, "road_id": row["road_id"], "road_name": name, "place": name,
               "severity": SEVERITY.get(reading["level"], "medium"), "duration_min": 45, "confidence": 0.8,
               "needs_location": False, "reporter_name": "Traffic feed"}
    problem["summary"] = issues.summarize(problem)
    said = (f"{reading.get('source', 'Traffic')} feed: {reading['current_kmph']:.0f} km/h on {name} "
            f"(usually {reading['free_kmph']:.0f}). Confirmed by {actor['display_name']}.")
    issue_id = issues.submit("OPS", problem, transcript=said, engine="traffic feed", source="auto-traffic",
                             branch_id=branch_id)
    _decide(suggestion_id, "confirmed", actor, issue_id)
    return issue_id


def dismiss(suggestion_id, actor):
    """The admin says it doesn't matter (no alert)."""
    _suggestion(suggestion_id, actor["branch_id"])
    _decide(suggestion_id, "dismissed", actor)


def _decide(suggestion_id, status, actor, issue_id=None):
    with store.connect() as conn:
        conn.execute("UPDATE suggestions SET status = ?, issue_id = ?, decided_by = ?, decided_at = ? WHERE id = ?",
                     (status, issue_id, actor["user_id"], _now().strftime(FMT), suggestion_id))
        store._bump(conn)
    store.audit(actor["user_id"], f"traffic_suggestion_{status}", str(suggestion_id), {"issue_id": issue_id},
                actor.get("branch_id"))


# ---------------------------------------------------------------- the timer
def poll(branch_id=None):
    """Run every feed that is due. branch_id: only that branch's traffic (admin pages); None: all (the API)."""
    done = {}
    if weather.configured() and _due("weather_polled_at", WEATHER_EVERY_MIN):
        done["weather"] = poll_weather()
    if traffic.configured():
        branches = [branch_id] if branch_id else list(store.branches_df()["branch_id"])
        for branch in branches:
            if _due(f"traffic_polled_{branch}", TRAFFIC_EVERY_MIN):
                done.setdefault("traffic", {})[branch] = check_traffic(branch)
    moved = tracking.simulate(branch_id)
    if moved:
        done["simulated"] = moved
    return done


def status(branch_id):
    """For the Live feeds card: weather, traffic and GPS – live or Demo mode – with their last update."""
    seen = tracking.last_seen(branch_id)
    partners = store.partners_df(branch_id)
    sharing = sum(1 for p in partners["partner_id"] if p in seen and seen[p]["source"] == "gps"
                  and seen[p]["age_s"] < 5 * 60)
    return {"weather": {"live": weather.configured(), "reading": weather_status()},
            "traffic": {"live": traffic.configured(), "checked_at": store.get_setting(f"traffic_checked_{branch_id}"),
                        "open": len(suggestions(branch_id))},
            "gps": {"sharing": sharing, "partners": int(len(partners)), "simulating": tracking.simulation_on()}}
