"""Shared live data in SQLite.

The manager's laptop and every partner's phone read and write the same database,
so an issue sent from a phone shows up on the manager screen, and an accepted plan
shows up on the phones. Static reference data (roads, places) stays in data/*.csv.

Set RIPPLE_DB to use another database file (the tests use a temporary one).
"""
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import pandas as pd

from modules.data_loader import DATA_DIR, NOW_MIN, hhmm_to_min, load_all, load_partners, nearest_place

SCHEMA = """
CREATE TABLE IF NOT EXISTS partners (
    partner_id TEXT PRIMARY KEY, name TEXT, phone TEXT, vehicle_id TEXT, shift_start TEXT,
    shift_end TEXT, languages TEXT, rating REAL, status TEXT);
CREATE TABLE IF NOT EXISTS vehicles (
    vehicle_id TEXT PRIMARY KEY, reg_no TEXT, type TEXT, status TEXT, current_lat REAL,
    current_lng REAL, route_roads TEXT, capacity INTEGER);
CREATE TABLE IF NOT EXISTS deliveries (
    delivery_id TEXT PRIMARY KEY, customer TEXT, address_area TEXT, lat REAL, lng REAL,
    vehicle_id TEXT, road_id TEXT, stop_order INTEGER, planned_eta TEXT, deadline TEXT,
    priority TEXT, customer_phone TEXT, status TEXT DEFAULT 'pending', original_vehicle TEXT,
    note TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS issues (
    issue_id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT, partner_id TEXT, source TEXT,
    quick_type TEXT, text TEXT, audio BLOB, transcript TEXT, transcript_engine TEXT,
    problem TEXT, summary TEXT, status TEXT, plan TEXT, decided_at TEXT, decision_note TEXT);
CREATE TABLE IF NOT EXISTS disruptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT, issue_id INTEGER, data TEXT, active INTEGER DEFAULT 1,
    created_at TEXT);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT, issue_id INTEGER, to_partner TEXT,
    to_customer TEXT, to_phone TEXT, channel TEXT, text TEXT, read INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT, kind TEXT, text TEXT, issue_id INTEGER);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""
TABLES = ["partners", "vehicles", "deliveries", "issues", "disruptions", "messages", "events", "meta"]
JSON_FIELDS = {"problem", "plan"}
OPEN_ISSUE_STATUSES = ("new", "analysed")


def db_path():
    return Path(os.getenv("RIPPLE_DB", DATA_DIR / "ripple.db"))


def now_stamp():
    """Wall-clock time for the activity log, e.g. '14:05:09'."""
    return datetime.now().strftime("%H:%M:%S")


@contextmanager
def connect():
    conn = sqlite3.connect(db_path(), timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _bump(conn):
    """Every write bumps a version number; screens poll it to know when to refresh."""
    conn.execute("INSERT INTO meta(key, value) VALUES('version', '1') "
                 "ON CONFLICT(key) DO UPDATE SET value = CAST(value AS INTEGER) + 1")


def version():
    with connect() as conn:
        row = conn.execute("SELECT value FROM meta WHERE key = 'version'").fetchone()
    return int(row["value"]) if row else 0


# ---------------------------------------------------------------- setup
def init_db():
    """Create the database on first use (and seed it with the demo data)."""
    with connect() as conn:
        conn.executescript(SCHEMA)
        seeded = conn.execute("SELECT COUNT(*) FROM partners").fetchone()[0]
    if not seeded:
        reset_demo()


def reset_demo():
    """Wipe everything and load the demo data again (09:00, no issues)."""
    data = load_all()
    partners = load_partners()
    with connect() as conn:
        for table in TABLES:
            conn.execute(f"DROP TABLE IF EXISTS {table}")
        conn.executescript(SCHEMA)
        conn.executemany("INSERT INTO partners VALUES (?,?,?,?,?,?,?,?,?)",
                         partners[["partner_id", "name", "phone", "vehicle_id", "shift_start", "shift_end",
                                   "languages", "rating", "status"]].values.tolist())
        vehicles = data["vehicles"]
        conn.executemany("INSERT INTO vehicles VALUES (?,?,?,?,?,?,?,?)", [
            (v.vehicle_id, v.reg_no, v.type, v.status, v.current_lat, v.current_lng,
             "|".join(v.route_roads), int(v.capacity)) for v in vehicles.itertuples()])
        conn.executemany(
            "INSERT INTO deliveries(delivery_id, customer, address_area, lat, lng, vehicle_id, road_id, "
            "stop_order, planned_eta, deadline, priority, customer_phone, status, original_vehicle) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'pending',?)",
            [(d.delivery_id, d.customer, d.address_area, d.lat, d.lng, d.vehicle_id, d.road_id,
              int(d.stop_order), d.planned_eta, d.deadline, d.priority, d.customer_phone, d.vehicle_id)
             for d in data["deliveries"].itertuples()])
        conn.execute("INSERT INTO events(created_at, kind, text) VALUES (?, 'system', ?)",
                     (now_stamp(), "Demo started: 6 partners, 30 deliveries, clock 09:00"))
        _bump(conn)


# ---------------------------------------------------------------- reads
def _df(sql, params=()):
    with connect() as conn:
        return pd.read_sql_query(sql, conn, params=params)


def deliveries_df(vehicle_id=None, include_done=True):
    sql = "SELECT * FROM deliveries"
    clauses, params = [], []
    if vehicle_id:
        clauses.append("vehicle_id = ?")
        params.append(vehicle_id)
    if not include_done:
        clauses.append("status NOT IN ('delivered', 'failed')")
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    df = _df(sql + " ORDER BY vehicle_id, stop_order", params)
    df["eta_min"] = df["planned_eta"].apply(hhmm_to_min)
    df["deadline_min"] = df["deadline"].apply(hhmm_to_min)
    return df


def vehicles_df():
    df = _df("SELECT v.*, p.name AS driver, p.partner_id FROM vehicles v "
             "LEFT JOIN partners p ON p.vehicle_id = v.vehicle_id ORDER BY v.vehicle_id")
    df["route_roads"] = df["route_roads"].fillna("").apply(lambda s: [r for r in s.split("|") if r])
    return df


def snapshot():
    """Current state in the same shape as data_loader.load_all(), for impact/risk/recommender.

    Only deliveries still to do are included.
    """
    return {"roads": load_all()["roads"], "vehicles": vehicles_df(),
            "deliveries": deliveries_df(include_done=False).reset_index(drop=True)}


def partners_df():
    """One row per partner with everything the manager needs to see."""
    partners = _df("SELECT p.*, v.reg_no, v.type AS vehicle_type, v.status AS vehicle_status, "
                   "v.current_lat AS lat, v.current_lng AS lng, v.route_roads FROM partners p "
                   "JOIN vehicles v ON v.vehicle_id = p.vehicle_id ORDER BY p.partner_id")
    deliveries = deliveries_df()
    open_issues = _df("SELECT partner_id, COUNT(*) AS n FROM issues WHERE status IN (?, ?) "
                      "GROUP BY partner_id", OPEN_ISSUE_STATUSES)
    open_by_partner = dict(zip(open_issues["partner_id"], open_issues["n"]))

    rows = []
    for p in partners.itertuples():
        own = deliveries[deliveries["vehicle_id"] == p.vehicle_id]
        todo = own[~own["status"].isin(["delivered", "failed"])].sort_values("eta_min")
        nxt = todo.iloc[0] if len(todo) else None
        rows.append({
            "partner_id": p.partner_id, "name": p.name, "phone": p.phone, "status": p.status,
            "vehicle_id": p.vehicle_id, "reg_no": p.reg_no, "vehicle_type": p.vehicle_type,
            "area": nearest_place(p.lat, p.lng), "lat": p.lat, "lng": p.lng,
            "assigned": len(own), "delivered": int((own["status"] == "delivered").sum()),
            "pending": len(todo),
            "urgent": int(todo["priority"].isin(["medical", "perishable"]).sum()),
            "next_stop": f"{nxt['customer']}, {nxt['address_area']}" if nxt is not None else "—",
            "next_eta": nxt["planned_eta"] if nxt is not None else "—",
            "next_road": nxt["road_id"] if nxt is not None else (p.route_roads.split("|")[0] if p.route_roads else None),
            "open_issues": int(open_by_partner.get(p.partner_id, 0)),
            "shift": f"{p.shift_start}–{p.shift_end}", "languages": p.languages.replace("|", ", "),
            "rating": p.rating,
        })
    return pd.DataFrame(rows)


def get_partner(partner_id):
    df = partners_df()
    match = df[df["partner_id"] == partner_id]
    return match.iloc[0].to_dict() if len(match) else None


def _decode_issue(row):
    issue = dict(row)
    for field in JSON_FIELDS:
        issue[field] = json.loads(issue[field]) if issue.get(field) else None
    return issue


def get_issue(issue_id):
    with connect() as conn:
        row = conn.execute("SELECT * FROM issues WHERE issue_id = ?", (issue_id,)).fetchone()
    return _decode_issue(row) if row else None


def list_issues(statuses=None, partner_id=None):
    sql, clauses, params = "SELECT * FROM issues", [], []
    if statuses:
        clauses.append(f"status IN ({','.join('?' * len(statuses))})")
        params += list(statuses)
    if partner_id:
        clauses.append("partner_id = ?")
        params.append(partner_id)
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    with connect() as conn:
        rows = conn.execute(sql + " ORDER BY issue_id DESC", params).fetchall()
    return [_decode_issue(r) for r in rows]


def active_disruptions():
    with connect() as conn:
        rows = conn.execute("SELECT data FROM disruptions WHERE active = 1 ORDER BY id").fetchall()
    return [json.loads(r["data"]) for r in rows]


def messages_for(partner_id, limit=20):
    with connect() as conn:
        rows = conn.execute("SELECT * FROM messages WHERE to_partner = ? ORDER BY id DESC LIMIT ?",
                            (partner_id, limit)).fetchall()
    return [dict(r) for r in rows]


def customer_messages(limit=50):
    return _df("SELECT created_at, issue_id, to_customer, to_phone, text FROM messages "
               "WHERE channel = 'sms' ORDER BY id DESC LIMIT ?", (limit,))


def events(limit=30):
    return _df("SELECT created_at, kind, text, issue_id FROM events ORDER BY id DESC LIMIT ?", (limit,))


# ---------------------------------------------------------------- writes
def add_issue(partner_id, text="", audio=None, quick_type=None, source="partner"):
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO issues(created_at, partner_id, source, quick_type, text, audio, status) "
            "VALUES (?,?,?,?,?,?, 'new')", (now_stamp(), partner_id, source, quick_type, text, audio))
        _bump(conn)
        return cur.lastrowid


def update_issue(issue_id, **fields):
    if not fields:
        return
    values = [json.dumps(v, default=str) if k in JSON_FIELDS and v is not None else v for k, v in fields.items()]
    with connect() as conn:
        conn.execute(f"UPDATE issues SET {', '.join(f'{k} = ?' for k in fields)} WHERE issue_id = ?",
                     values + [issue_id])
        _bump(conn)


def update_delivery(delivery_id, **fields):
    with connect() as conn:
        conn.execute(f"UPDATE deliveries SET {', '.join(f'{k} = ?' for k in fields)} WHERE delivery_id = ?",
                     list(fields.values()) + [delivery_id])
        _bump(conn)


def set_route(vehicle_id, road_ids):
    with connect() as conn:
        conn.execute("UPDATE vehicles SET route_roads = ? WHERE vehicle_id = ?", ("|".join(road_ids), vehicle_id))
        _bump(conn)


def set_partner_status(partner_id, status):
    with connect() as conn:
        conn.execute("UPDATE partners SET status = ? WHERE partner_id = ?", (status, partner_id))
        _bump(conn)


def add_disruption(issue_id, disruption):
    with connect() as conn:
        conn.execute("INSERT INTO disruptions(issue_id, data, created_at) VALUES (?,?,?)",
                     (issue_id, json.dumps(disruption, default=str), now_stamp()))
        _bump(conn)


def add_message(text, to_partner=None, to_customer=None, to_phone=None, channel="app", issue_id=None):
    with connect() as conn:
        conn.execute("INSERT INTO messages(created_at, issue_id, to_partner, to_customer, to_phone, channel, text) "
                     "VALUES (?,?,?,?,?,?,?)", (now_stamp(), issue_id, to_partner, to_customer, to_phone, channel, text))
        _bump(conn)


def mark_messages_read(partner_id):
    with connect() as conn:
        conn.execute("UPDATE messages SET read = 1 WHERE to_partner = ? AND read = 0", (partner_id,))
        _bump(conn)


def log_event(kind, text, issue_id=None):
    with connect() as conn:
        conn.execute("INSERT INTO events(created_at, kind, text, issue_id) VALUES (?,?,?,?)",
                     (now_stamp(), kind, text, issue_id))
        _bump(conn)


if __name__ == "__main__":
    import tempfile

    os.environ["RIPPLE_DB"] = str(Path(tempfile.mkdtemp()) / "selftest.db")
    init_db()
    partners = partners_df()
    print(partners[["partner_id", "name", "vehicle_id", "area", "assigned", "pending", "urgent", "next_stop",
                    "next_eta"]].to_string(index=False))
    snap = snapshot()
    print({k: len(v) for k, v in snap.items()}, "| version", version())
    issue_id = add_issue("P1", text="Avinashi road la accident")
    update_issue(issue_id, problem={"type": "accident"}, status="analysed")
    assert get_issue(issue_id)["problem"]["type"] == "accident"
    assert len(list_issues(OPEN_ISSUE_STATUSES)) == 1 and get_partner("P1")["open_issues"] == 1
    update_delivery("D01", status="delivered")
    assert get_partner("P1")["delivered"] == 1 and len(snapshot()["deliveries"]) == 29
    reset_demo()
    assert len(snapshot()["deliveries"]) == 30 and not list_issues()
    print("store OK")
