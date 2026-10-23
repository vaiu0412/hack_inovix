"""Live positions. Partner phones share GPS every 30 s while on duty; in Demo mode vehicles can drive by themselves.
No Streamlit imports.

- record():   a partner's own position -> their vehicle's current spot + the location log (inside Coimbatore only,
              so a phone far away never teleports a van off the map)
- trails():   the last positions per vehicle (the map draws them); last_seen(): when each partner last reported
- simulate(): Demo mode – every on-duty vehicle drives toward its next open stop at city speed (off by default, so
              the demo numbers don't change unless an admin switches it on)
"""
from datetime import datetime, timedelta

from modules import geometry, store
from modules.data_loader import haversine_km

GPS_EVERY_S = 30
SIM_SPEED_KMPH = 22
SIMULATE_KEY = "simulate_movement"
FMT = "%Y-%m-%d %H:%M:%S"


def now():
    """The current time (tests replace this)."""
    return datetime.now()


def record(dp_id, branch_id, lat, lng, accuracy_m=None, source="gps"):
    """Store a position for the partner's own vehicle. False (nothing stored) outside Coimbatore."""
    lat, lng = float(lat), float(lng)
    if not geometry.in_coimbatore(lat, lng):
        return False
    with store.transaction() as conn:
        row = conn.execute("SELECT vehicle_id FROM partners WHERE partner_id = ? AND branch_id = ?",
                           (dp_id, branch_id)).fetchone()
        if row is None:
            raise PermissionError(f"{dp_id} is not a partner of this branch")
        _move(conn, branch_id, dp_id, row["vehicle_id"], lat, lng, accuracy_m, source)
    return True


def _move(conn, branch_id, dp_id, vehicle_id, lat, lng, accuracy_m, source):
    conn.execute("UPDATE vehicles SET current_lat = ?, current_lng = ? WHERE vehicle_id = ?", (lat, lng, vehicle_id))
    conn.execute("INSERT INTO location_log(time, branch_id, partner_id, vehicle_id, lat, lng, accuracy_m, source) "
                 "VALUES (?,?,?,?,?,?,?,?)", (now().strftime(FMT), branch_id, dp_id, vehicle_id, lat, lng,
                                              accuracy_m, source))
    store._bump(conn)


def trails(branch_id, minutes=30):
    """{vehicle_id: [[lat, lng], ...]} – the positions of the last `minutes`, oldest first."""
    since = (now() - timedelta(minutes=minutes)).strftime(FMT)
    with store.connect() as conn:
        rows = conn.execute("SELECT vehicle_id, lat, lng FROM location_log WHERE branch_id = ? AND time >= ? "
                            "ORDER BY id", (branch_id, since)).fetchall()
    out = {}
    for r in rows:
        out.setdefault(r["vehicle_id"], []).append([r["lat"], r["lng"]])
    return out


def last_seen(branch_id):
    """{partner_id: {time, age_s, source, accuracy_m}} – each partner's latest position report."""
    with store.connect() as conn:
        rows = conn.execute("SELECT partner_id, time, source, accuracy_m FROM location_log WHERE id IN "
                            "(SELECT MAX(id) FROM location_log WHERE branch_id = ? GROUP BY partner_id)",
                            (branch_id,)).fetchall()
    out = {}
    for r in rows:
        age = (now() - datetime.strptime(r["time"], FMT)).total_seconds()
        out[r["partner_id"]] = {"time": r["time"], "age_s": int(max(age, 0)), "source": r["source"],
                                "accuracy_m": r["accuracy_m"]}
    return out


def seen_text(seen):
    """'GPS 12 s ago · ±8 m', 'Simulated 2 min ago' or 'No live position'."""
    if not seen:
        return "No live position"
    age = seen["age_s"]
    ago = f"{age} s ago" if age < 90 else f"{age // 60} min ago" if age < 5400 else f"{age // 3600} h ago"
    what = "Simulated" if seen["source"] == "sim" else "GPS"
    accuracy = f" · ±{seen['accuracy_m']:.0f} m" if seen.get("accuracy_m") else ""
    return f"{what} {ago}{accuracy}"


# ---------------------------------------------------------------- Demo mode: vehicles drive by themselves
def simulation_on():
    """True when an admin switched on simulated movement (Demo mode)."""
    return store.get_setting(SIMULATE_KEY, "off") == "on"


def set_simulation(actor, on):
    """Branch or Super Admin switches simulated movement on or off (all branches)."""
    if not actor or actor.get("role") not in ("branch_admin", "super_admin"):
        raise PermissionError("Admins only")
    store.set_setting(SIMULATE_KEY, "on" if on else "off", actor["user_id"])
    store.set_setting("last_simulation", now().strftime(FMT), actor["user_id"])


def simulate(branch_id=None):
    """Move every on-duty vehicle toward its next open stop by the time since the last step (≤ 2 min) – except
    partners whose phone sent real GPS in the last 2 minutes. Returns how many vehicles moved (0 while off)."""
    if not simulation_on():
        return 0
    last = store.get_setting("last_simulation")
    current = now()
    seconds = (current - datetime.strptime(last, FMT)).total_seconds() if last else 30
    seconds = min(max(seconds, 0), 120)
    store.set_setting("last_simulation", current.strftime(FMT))
    step_km = SIM_SPEED_KMPH * seconds / 3600
    if step_km <= 0:
        return 0
    moved = 0
    live_since = (current - timedelta(minutes=2)).strftime(FMT)
    with store.transaction() as conn:
        live = {r[0] for r in conn.execute("SELECT DISTINCT partner_id FROM location_log WHERE source = 'gps' "
                                           "AND time >= ?", (live_since,))}
        rows = conn.execute(
            "SELECT p.partner_id, p.branch_id, v.vehicle_id, v.current_lat, v.current_lng FROM partners p "
            "JOIN vehicles v ON v.vehicle_id = p.vehicle_id WHERE p.status = 'on_duty'"
            + (" AND p.branch_id = ?" if branch_id else ""), (branch_id,) if branch_id else ()).fetchall()
        for r in rows:
            if r["partner_id"] in live:  # the real phone wins
                continue
            stop = conn.execute("SELECT lat, lng FROM deliveries WHERE vehicle_id = ? AND status NOT IN "
                                "('delivered', 'failed', 'unassigned') ORDER BY stop_order LIMIT 1",
                                (r["vehicle_id"],)).fetchone()
            if stop is None:
                continue
            here, there = (r["current_lat"], r["current_lng"]), (stop["lat"], stop["lng"])
            left = haversine_km(*here, *there)
            if left < 0.01:
                continue
            share = min(step_km / left, 1.0)
            lat = here[0] + (there[0] - here[0]) * share
            lng = here[1] + (there[1] - here[1]) * share
            _move(conn, r["branch_id"], r["partner_id"], r["vehicle_id"], lat, lng, None, "sim")
            moved += 1
    return moved
