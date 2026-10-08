"""Shared live data in SQLite – the single source of truth for every screen and the API.

Every operational row (partners, vehicles, deliveries, issues, disruptions, messages, events) carries
a branch_id, and every read/write function here takes a branch_id to scope by (None = all branches,
used only by internal jobs and the Super Admin summaries).

Set RIPPLE_DB to use another database file (the tests use a temporary one).
"""
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import pandas as pd

from modules.data_loader import (DATA_DIR, NOW_MIN, hhmm_to_min, load_all, load_branches, load_partners,
                                 nearest_place)
from modules.security import demo_hash

SCHEMA_VERSION = 3
SCHEMA = """
CREATE TABLE IF NOT EXISTS branches (
    branch_id TEXT PRIMARY KEY, name TEXT NOT NULL, city TEXT, area TEXT, address TEXT, lat REAL, lng REAL,
    is_active INTEGER DEFAULT 1, created_at TEXT);
CREATE TABLE IF NOT EXISTS roles (role_id TEXT PRIMARY KEY, name TEXT UNIQUE NOT NULL);
CREATE TABLE IF NOT EXISTS permissions (perm_id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT UNIQUE NOT NULL);
CREATE TABLE IF NOT EXISTS role_permissions (role_id TEXT, perm_id INTEGER, PRIMARY KEY (role_id, perm_id));
CREATE TABLE IF NOT EXISTS partners (
    partner_id TEXT PRIMARY KEY, name TEXT, phone TEXT, vehicle_id TEXT, shift_start TEXT,
    shift_end TEXT, languages TEXT, rating REAL, status TEXT, branch_id TEXT);
CREATE TABLE IF NOT EXISTS vehicles (
    vehicle_id TEXT PRIMARY KEY, reg_no TEXT, type TEXT, status TEXT, current_lat REAL,
    current_lng REAL, route_roads TEXT, capacity INTEGER, branch_id TEXT);
CREATE TABLE IF NOT EXISTS deliveries (
    delivery_id TEXT PRIMARY KEY, customer TEXT, address_area TEXT, lat REAL, lng REAL,
    vehicle_id TEXT, road_id TEXT, stop_order INTEGER, planned_eta TEXT, deadline TEXT,
    priority TEXT, customer_phone TEXT, status TEXT DEFAULT 'pending', original_vehicle TEXT,
    note TEXT DEFAULT '', branch_id TEXT);
CREATE TABLE IF NOT EXISTS issues (
    issue_id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT, partner_id TEXT, source TEXT,
    quick_type TEXT, text TEXT, audio BLOB, transcript TEXT, transcript_engine TEXT,
    problem TEXT, summary TEXT, status TEXT, plan TEXT, decided_at TEXT, decision_note TEXT, branch_id TEXT);
CREATE TABLE IF NOT EXISTS disruptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT, issue_id INTEGER, data TEXT, active INTEGER DEFAULT 1,
    created_at TEXT, branch_id TEXT);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT, issue_id INTEGER, to_partner TEXT,
    to_customer TEXT, to_phone TEXT, channel TEXT, text TEXT, read INTEGER DEFAULT 0, branch_id TEXT);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT, kind TEXT, text TEXT, issue_id INTEGER, branch_id TEXT);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY, email TEXT UNIQUE, phone TEXT, display_name TEXT,
    role_id TEXT NOT NULL REFERENCES roles(role_id), branch_id TEXT NULL REFERENCES branches(branch_id),
    dp_id TEXT NULL REFERENCES partners(partner_id), password_hash TEXT NOT NULL, salt TEXT NOT NULL,
    is_active INTEGER DEFAULT 1, failed_attempts INTEGER DEFAULT 0, locked_until REAL DEFAULT 0,
    last_login TEXT, created_by TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL, created_at REAL, expires_at REAL,
    remember_me INTEGER DEFAULT 0, revoked INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS otp_codes (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL, purpose TEXT NOT NULL, code_hash TEXT NOT NULL,
    salt TEXT NOT NULL, expires_at REAL, used INTEGER DEFAULT 0, attempts INTEGER DEFAULT 0, created_at REAL);
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT, time TEXT, actor_user_id TEXT, action TEXT, target TEXT,
    details_json TEXT, branch_id TEXT);
"""
TABLES = ["branches", "roles", "permissions", "role_permissions", "partners", "vehicles", "deliveries", "issues",
          "disruptions", "messages", "events", "meta", "users", "sessions", "otp_codes", "audit_log",
          "login_attempts"]
BRANCH_SCOPED = ["partners", "vehicles", "deliveries", "issues", "disruptions", "messages", "events"]
JSON_FIELDS = {"problem", "plan"}
OPEN_ISSUE_STATUSES = ("new", "analysed")

ROLES = ("super_admin", "branch_admin", "partner")
ROLE_PERMISSIONS = {
    "super_admin": ["manage_branches", "manage_branch_admins", "view_all_branches", "view_audit_log", "reset_demo"],
    "branch_admin": ["manage_partners", "view_branch_ops", "approve_recovery", "log_issue"],
    "partner": ["report_issue", "view_own_deliveries"],
}
# Demo accounts (also listed in the README; never shown in the app).
DEMO_ADMINS = [
    {"user_id": "superadmin", "email": "superadmin@ripple.in", "display_name": "Super Admin", "role": "super_admin",
     "branch_id": None, "phone": "+91 90000 10000", "password": "Super@123"},
    {"user_id": "east.admin", "email": "east.admin@ripple.in", "display_name": "Divya Raman", "role": "branch_admin",
     "branch_id": "CBE-E", "phone": "+91 90000 10001", "password": "Admin@123"},
    {"user_id": "central.admin", "email": "central.admin@ripple.in", "display_name": "Suresh Kumar",
     "role": "branch_admin", "branch_id": "CBE-C", "phone": "+91 90000 10002", "password": "Admin@123"},
    {"user_id": "south.admin", "email": "south.admin@ripple.in", "display_name": "Meena Sundar",
     "role": "branch_admin", "branch_id": "CBE-S", "phone": "+91 90000 10003", "password": "Admin@123"},
]
DEMO_PARTNER_PASSWORD = "Partner@123"


def db_path():
    return Path(os.getenv("RIPPLE_DB", DATA_DIR / "ripple.db"))


def now_stamp():
    """Wall-clock time for the activity log, e.g. '14:05:09'."""
    return datetime.now().strftime("%H:%M:%S")


def now_iso():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


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


def _columns(conn, table):
    return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}


def _where(clauses):
    return (" WHERE " + " AND ".join(clauses)) if clauses else ""


# ---------------------------------------------------------------- setup, migration, seed
def init_db():
    """Create the database on first use, upgrade older databases in place, seed demo data."""
    with connect() as conn:
        conn.executescript(SCHEMA)
        ids = {r[0] for r in conn.execute("SELECT partner_id FROM partners")}
    # empty, or the old P1-P6 partner IDs (partners added later by branch admins, e.g. DP107, are kept)
    if not ids or any(not str(i).startswith("DP") for i in ids):
        reset_demo()
        return
    with connect() as conn:
        row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
        current = int(row["value"]) if row else 0
        if current < SCHEMA_VERSION:
            _migrate_v3(conn)


def _seed_reference(conn):
    """Branches, roles, permissions (INSERT OR IGNORE, so it is safe to run again)."""
    for b in load_branches().itertuples():
        conn.execute("INSERT OR IGNORE INTO branches(branch_id, name, city, area, address, lat, lng, is_active, "
                     "created_at) VALUES (?,?,?,?,?,?,?,1,?)",
                     (b.branch_id, b.name, b.city, b.area, b.address, b.lat, b.lng, now_iso()))
    for role in ROLES:
        conn.execute("INSERT OR IGNORE INTO roles(role_id, name) VALUES (?, ?)", (role, role))
    for role, codes in ROLE_PERMISSIONS.items():
        for code in codes:
            conn.execute("INSERT OR IGNORE INTO permissions(code) VALUES (?)", (code,))
            perm_id = conn.execute("SELECT perm_id FROM permissions WHERE code = ?", (code,)).fetchone()[0]
            conn.execute("INSERT OR IGNORE INTO role_permissions(role_id, perm_id) VALUES (?, ?)", (role, perm_id))


def _seed_users(conn):
    """Super admin, one branch admin per branch, one login per partner. Hashes only, never passwords."""
    conn.execute("DELETE FROM users")
    rows = []
    for a in DEMO_ADMINS:
        hash_hex, salt = demo_hash(a["user_id"], a["password"])
        rows.append((a["user_id"], a["email"], a["phone"], a["display_name"], a["role"], a["branch_id"], None,
                     hash_hex, salt, "system"))
    for p in conn.execute("SELECT partner_id, name, phone, branch_id FROM partners ORDER BY partner_id"):
        hash_hex, salt = demo_hash(p["partner_id"], DEMO_PARTNER_PASSWORD)
        rows.append((p["partner_id"], f"{p['partner_id'].lower()}@ripple.in", p["phone"], p["name"], "partner",
                     p["branch_id"], p["partner_id"], hash_hex, salt, "system"))
    conn.executemany("INSERT INTO users(user_id, email, phone, display_name, role_id, branch_id, dp_id, "
                     "password_hash, salt, created_by, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                     [r + (now_iso(),) for r in rows])


def _migrate_v3(conn):
    """Upgrade a v2 database (manager/partner logins, no branches) in place. Idempotent."""
    for table in BRANCH_SCOPED:
        if "branch_id" not in _columns(conn, table):
            conn.execute(f"ALTER TABLE {table} ADD COLUMN branch_id TEXT")
    _seed_reference(conn)
    partner_branch = dict(zip(load_partners()["partner_id"], load_partners()["branch_id"]))
    vehicles = load_all()["vehicles"]
    for partner_id, branch in partner_branch.items():
        conn.execute("UPDATE partners SET branch_id = ? WHERE partner_id = ? AND branch_id IS NULL", (branch, partner_id))
    for v in vehicles.itertuples():
        conn.execute("INSERT OR IGNORE INTO vehicles VALUES (?,?,?,?,?,?,?,?,?)",
                     (v.vehicle_id, v.reg_no, v.type, v.status, v.current_lat, v.current_lng,
                      "|".join(v.route_roads), int(v.capacity), v.branch_id))
        conn.execute("UPDATE vehicles SET branch_id = ? WHERE vehicle_id = ? AND branch_id IS NULL",
                     (v.branch_id, v.vehicle_id))
    conn.execute("UPDATE deliveries SET branch_id = (SELECT branch_id FROM vehicles v "
                 "WHERE v.vehicle_id = deliveries.vehicle_id) WHERE branch_id IS NULL")
    conn.execute("UPDATE issues SET branch_id = COALESCE((SELECT branch_id FROM partners p "
                 "WHERE p.partner_id = issues.partner_id), 'CBE-E') WHERE branch_id IS NULL")
    for table in ("disruptions", "events"):
        conn.execute(f"UPDATE {table} SET branch_id = (SELECT branch_id FROM issues i "
                     f"WHERE i.issue_id = {table}.issue_id) WHERE branch_id IS NULL AND issue_id IS NOT NULL")
    conn.execute("UPDATE messages SET branch_id = COALESCE((SELECT branch_id FROM partners p WHERE "
                 "p.partner_id = messages.to_partner), (SELECT branch_id FROM issues i WHERE "
                 "i.issue_id = messages.issue_id)) WHERE branch_id IS NULL")
    if "role_id" not in _columns(conn, "users"):  # old manager/partner accounts -> new account model
        conn.execute("DROP TABLE users")
        conn.execute("DROP TABLE IF EXISTS login_attempts")
        conn.executescript(SCHEMA)
        _seed_users(conn)  # the old 'manager' becomes east.admin@ripple.in (no duplicate manager role)
    conn.execute("INSERT INTO meta(key, value) VALUES ('schema_version', ?) ON CONFLICT(key) DO UPDATE "
                 "SET value = excluded.value", (str(SCHEMA_VERSION),))
    conn.execute("INSERT INTO audit_log(time, actor_user_id, action, target, details_json) VALUES (?,?,?,?,?)",
                 (now_iso(), "system", "migrate", "database", json.dumps({"to_version": SCHEMA_VERSION})))
    _bump(conn)


def reset_demo():
    """Wipe everything and load the demo data again (09:00, no issues, demo accounts restored)."""
    data = load_all()
    partners = load_partners()
    with connect() as conn:
        for table in TABLES:
            conn.execute(f"DROP TABLE IF EXISTS {table}")
        conn.executescript(SCHEMA)
        _seed_reference(conn)
        conn.executemany("INSERT INTO partners VALUES (?,?,?,?,?,?,?,?,?,?)",
                         partners[["partner_id", "name", "phone", "vehicle_id", "shift_start", "shift_end",
                                   "languages", "rating", "status", "branch_id"]].values.tolist())
        vehicles = data["vehicles"]
        conn.executemany("INSERT INTO vehicles VALUES (?,?,?,?,?,?,?,?,?)", [
            (v.vehicle_id, v.reg_no, v.type, v.status, v.current_lat, v.current_lng,
             "|".join(v.route_roads), int(v.capacity), v.branch_id) for v in vehicles.itertuples()])
        branch_of = dict(zip(vehicles["vehicle_id"], vehicles["branch_id"]))
        conn.executemany(
            "INSERT INTO deliveries(delivery_id, customer, address_area, lat, lng, vehicle_id, road_id, "
            "stop_order, planned_eta, deadline, priority, customer_phone, status, original_vehicle, branch_id) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'pending',?,?)",
            [(d.delivery_id, d.customer, d.address_area, d.lat, d.lng, d.vehicle_id, d.road_id,
              int(d.stop_order), d.planned_eta, d.deadline, d.priority, d.customer_phone, d.vehicle_id,
              branch_of[d.vehicle_id]) for d in data["deliveries"].itertuples()])
        _seed_users(conn)
        for branch_id in partners["branch_id"].unique():
            conn.execute("INSERT INTO events(created_at, kind, text, branch_id) VALUES (?, 'system', ?, ?)",
                         (now_stamp(), "Day started at 09:00", branch_id))
        conn.execute("INSERT INTO meta(key, value) VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))
        conn.execute("INSERT INTO audit_log(time, actor_user_id, action, target, details_json) VALUES (?,?,?,?,?)",
                     (now_iso(), "system", "reset_demo", "all branches", "{}"))
        _bump(conn)


# ---------------------------------------------------------------- reads
def _df(sql, params=()):
    with connect() as conn:
        return pd.read_sql_query(sql, conn, params=params)


def branches_df():
    return _df("SELECT * FROM branches ORDER BY branch_id")


def get_branch(branch_id):
    with connect() as conn:
        row = conn.execute("SELECT * FROM branches WHERE branch_id = ?", (branch_id,)).fetchone()
    return dict(row) if row else None


def deliveries_df(vehicle_id=None, include_done=True, branch_id=None):
    clauses, params = [], []
    if vehicle_id:
        clauses.append("vehicle_id = ?")
        params.append(vehicle_id)
    if branch_id:
        clauses.append("branch_id = ?")
        params.append(branch_id)
    if not include_done:
        clauses.append("status NOT IN ('delivered', 'failed')")
    df = _df("SELECT * FROM deliveries" + _where(clauses) + " ORDER BY vehicle_id, stop_order", params)
    df["eta_min"] = df["planned_eta"].apply(hhmm_to_min)
    df["deadline_min"] = df["deadline"].apply(hhmm_to_min)
    return df


def vehicles_df(branch_id=None):
    df = _df("SELECT v.*, p.name AS driver, p.partner_id FROM vehicles v "
             "LEFT JOIN partners p ON p.vehicle_id = v.vehicle_id"
             + (" WHERE v.branch_id = ?" if branch_id else "") + " ORDER BY v.vehicle_id",
             (branch_id,) if branch_id else ())
    df["route_roads"] = df["route_roads"].fillna("").apply(lambda s: [r for r in s.split("|") if r])
    return df


def snapshot(branch_id=None):
    """Current state in the same shape as data_loader.load_all(), for impact/risk/recommender.

    With a branch_id, ONLY that branch's vehicles and deliveries are included, so the impact engine
    and the recommender never touch another branch's routes, partners or backup vehicles.
    """
    return {"roads": load_all()["roads"], "vehicles": vehicles_df(branch_id),
            "deliveries": deliveries_df(include_done=False, branch_id=branch_id).reset_index(drop=True)}


def partners_df(branch_id=None):
    """One row per delivery partner with everything the branch admin needs to see."""
    partners = _df("SELECT p.*, v.reg_no, v.type AS vehicle_type, v.status AS vehicle_status, "
                   "v.current_lat AS lat, v.current_lng AS lng, v.route_roads, "
                   "COALESCE(u.is_active, 1) AS account_active, u.email FROM partners p "
                   "JOIN vehicles v ON v.vehicle_id = p.vehicle_id "
                   "LEFT JOIN users u ON u.dp_id = p.partner_id"
                   + (" WHERE p.branch_id = ?" if branch_id else "") + " ORDER BY p.partner_id",
                   (branch_id,) if branch_id else ())
    deliveries = deliveries_df(branch_id=branch_id)
    open_issues = _df("SELECT partner_id, COUNT(*) AS n FROM issues WHERE status IN (?, ?) GROUP BY partner_id",
                      OPEN_ISSUE_STATUSES)
    open_by_partner = dict(zip(open_issues["partner_id"], open_issues["n"]))

    rows = []
    for p in partners.itertuples():
        own = deliveries[deliveries["vehicle_id"] == p.vehicle_id]
        todo = own[~own["status"].isin(["delivered", "failed"])].sort_values("eta_min")
        nxt = todo.iloc[0] if len(todo) else None
        rows.append({
            "partner_id": p.partner_id, "name": p.name, "phone": p.phone, "email": p.email,
            "status": p.status if p.account_active else "off_duty", "account_active": bool(p.account_active),
            "branch_id": p.branch_id, "vehicle_id": p.vehicle_id, "reg_no": p.reg_no,
            "vehicle_type": p.vehicle_type, "area": nearest_place(p.lat, p.lng), "lat": p.lat, "lng": p.lng,
            "assigned": len(own), "delivered": int((own["status"] == "delivered").sum()),
            "pending": len(todo),
            "urgent": int(todo["priority"].isin(["medical", "perishable"]).sum()),
            "next_stop": f"{nxt['customer']}, {nxt['address_area']}" if nxt is not None else "—",
            "next_eta": nxt["planned_eta"] if nxt is not None else "—",
            "next_road": nxt["road_id"] if nxt is not None else (p.route_roads.split("|")[0] if p.route_roads else None),
            "open_issues": int(open_by_partner.get(p.partner_id, 0)),
            "shift": f"{p.shift_start}–{p.shift_end}", "languages": (p.languages or "").replace("|", ", "),
            "rating": p.rating,
        })
    columns = ["partner_id", "name", "phone", "email", "status", "account_active", "branch_id", "vehicle_id", "reg_no",
               "vehicle_type", "area", "lat", "lng", "assigned", "delivered", "pending", "urgent", "next_stop",
               "next_eta", "next_road", "open_issues", "shift", "languages", "rating"]
    return pd.DataFrame(rows, columns=columns)


def get_partner(partner_id, branch_id=None):
    """A partner's row, or None (also None when the partner is not in the given branch)."""
    df = partners_df(branch_id)
    match = df[df["partner_id"] == partner_id]
    return match.iloc[0].to_dict() if len(match) else None


def _decode_issue(row):
    issue = dict(row)
    for field in JSON_FIELDS:
        issue[field] = json.loads(issue[field]) if issue.get(field) else None
    return issue


def get_issue(issue_id, branch_id=None):
    with connect() as conn:
        row = conn.execute("SELECT * FROM issues WHERE issue_id = ?" + (" AND branch_id = ?" if branch_id else ""),
                           (issue_id, branch_id) if branch_id else (issue_id,)).fetchone()
    return _decode_issue(row) if row else None


def list_issues(statuses=None, partner_id=None, branch_id=None):
    clauses, params = [], []
    if statuses:
        clauses.append(f"status IN ({','.join('?' * len(statuses))})")
        params += list(statuses)
    if partner_id:
        clauses.append("partner_id = ?")
        params.append(partner_id)
    if branch_id:
        clauses.append("branch_id = ?")
        params.append(branch_id)
    with connect() as conn:
        rows = conn.execute("SELECT * FROM issues" + _where(clauses) + " ORDER BY issue_id DESC", params).fetchall()
    return [_decode_issue(r) for r in rows]


def active_disruptions(branch_id=None):
    with connect() as conn:
        rows = conn.execute("SELECT data FROM disruptions WHERE active = 1" + (" AND branch_id = ?" if branch_id else "")
                            + " ORDER BY id", (branch_id,) if branch_id else ()).fetchall()
    return [json.loads(r["data"]) for r in rows]


def messages_for(partner_id, limit=20):
    with connect() as conn:
        rows = conn.execute("SELECT * FROM messages WHERE to_partner = ? ORDER BY id DESC LIMIT ?",
                            (partner_id, limit)).fetchall()
    return [dict(r) for r in rows]


def customer_messages(limit=50, branch_id=None):
    return _df("SELECT created_at, issue_id, to_customer, to_phone, text FROM messages WHERE channel = 'sms'"
               + (" AND branch_id = ?" if branch_id else "") + " ORDER BY id DESC LIMIT ?",
               ((branch_id,) if branch_id else ()) + (limit,))


def events(limit=30, branch_id=None):
    return _df("SELECT created_at, kind, text, issue_id FROM events" + (" WHERE branch_id = ?" if branch_id else "")
               + " ORDER BY id DESC LIMIT ?", ((branch_id,) if branch_id else ()) + (limit,))


def audit_df(limit=200):
    return _df("SELECT a.time, COALESCE(u.display_name, a.actor_user_id) AS actor, a.actor_user_id, a.action, "
               "a.target, a.details_json, a.branch_id FROM audit_log a LEFT JOIN users u ON u.user_id = a.actor_user_id "
               "ORDER BY a.id DESC LIMIT ?", (limit,))


def branch_summaries():
    """Super Admin view: one summary row per branch (counts only, no operational detail)."""
    rows = []
    admins = _df("SELECT branch_id, display_name, is_active FROM users WHERE role_id = 'branch_admin'")
    for b in branches_df().itertuples():
        partners = _df("SELECT COUNT(*) AS n FROM partners WHERE branch_id = ?", (b.branch_id,))["n"][0]
        deliveries = deliveries_df(branch_id=b.branch_id)
        open_issues = list_issues(OPEN_ISSUE_STATUSES, branch_id=b.branch_id)
        risk = [r for i in open_issues for r in (i.get("plan") or {}).get("risk", [])]
        names = admins[(admins["branch_id"] == b.branch_id) & (admins["is_active"] == 1)]["display_name"].tolist()
        rows.append({"branch_id": b.branch_id, "name": b.name, "area": b.area, "is_active": bool(b.is_active),
                     "admin": ", ".join(names) or "—", "partners": int(partners), "deliveries": len(deliveries),
                     "delivered": int((deliveries["status"] == "delivered").sum()),
                     "delayed": sum(1 for r in risk if r["delay_min"] > 0),
                     "critical": sum(1 for r in risk if r["risk_label"] == "Critical"),
                     "open_issues": len(open_issues)})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- writes
def add_issue(partner_id, text="", audio=None, quick_type=None, source="partner", branch_id=None):
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO issues(created_at, partner_id, source, quick_type, text, audio, status, branch_id) "
            "VALUES (?,?,?,?,?,?, 'new', ?)", (now_stamp(), partner_id, source, quick_type, text, audio, branch_id))
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


def update_delivery(delivery_id, branch_id=None, **fields):
    """Change one delivery. With a branch_id, a delivery of another branch raises PermissionError."""
    with connect() as conn:
        sql = f"UPDATE deliveries SET {', '.join(f'{k} = ?' for k in fields)} WHERE delivery_id = ?"
        params = list(fields.values()) + [delivery_id]
        if branch_id:
            sql += " AND branch_id = ?"
            params.append(branch_id)
        if conn.execute(sql, params).rowcount == 0 and branch_id:
            raise PermissionError(f"Delivery {delivery_id} is not in branch {branch_id}")
        _bump(conn)


def set_route(vehicle_id, road_ids, branch_id=None):
    with connect() as conn:
        sql, params = "UPDATE vehicles SET route_roads = ? WHERE vehicle_id = ?", ["|".join(road_ids), vehicle_id]
        if branch_id:
            sql += " AND branch_id = ?"
            params.append(branch_id)
        if conn.execute(sql, params).rowcount == 0 and branch_id:
            raise PermissionError(f"Vehicle {vehicle_id} is not in branch {branch_id}")
        _bump(conn)


def set_partner_status(partner_id, status):
    with connect() as conn:
        conn.execute("UPDATE partners SET status = ? WHERE partner_id = ?", (status, partner_id))
        _bump(conn)


def add_disruption(issue_id, disruption, branch_id=None):
    with connect() as conn:
        conn.execute("INSERT INTO disruptions(issue_id, data, created_at, branch_id) VALUES (?,?,?,?)",
                     (issue_id, json.dumps(disruption, default=str), now_stamp(), branch_id))
        _bump(conn)


def add_message(text, to_partner=None, to_customer=None, to_phone=None, channel="app", issue_id=None, branch_id=None):
    with connect() as conn:
        conn.execute("INSERT INTO messages(created_at, issue_id, to_partner, to_customer, to_phone, channel, text, "
                     "branch_id) VALUES (?,?,?,?,?,?,?,?)",
                     (now_stamp(), issue_id, to_partner, to_customer, to_phone, channel, text, branch_id))
        _bump(conn)


def mark_messages_read(partner_id):
    with connect() as conn:
        conn.execute("UPDATE messages SET read = 1 WHERE to_partner = ? AND read = 0", (partner_id,))
        _bump(conn)


def log_event(kind, text, issue_id=None, branch_id=None):
    with connect() as conn:
        conn.execute("INSERT INTO events(created_at, kind, text, issue_id, branch_id) VALUES (?,?,?,?,?)",
                     (now_stamp(), kind, text, issue_id, branch_id))
        _bump(conn)


def audit(actor_user_id, action, target="", details=None, branch_id=None):
    """Who did what, when. Never pass passwords or one-time codes in details."""
    with connect() as conn:
        conn.execute("INSERT INTO audit_log(time, actor_user_id, action, target, details_json, branch_id) "
                     "VALUES (?,?,?,?,?,?)", (now_iso(), actor_user_id, action, target,
                                              json.dumps(details or {}, default=str), branch_id))


if __name__ == "__main__":
    import tempfile

    os.environ["RIPPLE_DB"] = str(Path(tempfile.mkdtemp()) / "selftest.db")
    init_db()
    print(branch_summaries().to_string(index=False))
    east = partners_df("CBE-E")
    assert set(east["partner_id"]) == {"DP101", "DP102", "DP103", "DP106"}
    assert set(snapshot("CBE-C")["vehicles"]["vehicle_id"]) == {"V4", "V7"}
    assert len(snapshot()["deliveries"]) == 30 and len(snapshot("CBE-E")["deliveries"]) == 18
    issue_id = add_issue("DP101", text="Avinashi road la accident", branch_id="CBE-E")
    assert get_issue(issue_id, "CBE-C") is None and get_issue(issue_id, "CBE-E")
    try:
        update_delivery("D01", branch_id="CBE-C", status="delivered")
        raise AssertionError("cross-branch write allowed")
    except PermissionError:
        pass
    update_delivery("D01", branch_id="CBE-E", status="delivered")
    assert get_partner("DP101")["delivered"] == 1 and get_partner("DP101", "CBE-S") is None
    reset_demo()
    assert len(snapshot()["deliveries"]) == 30 and not list_issues()
    print("store OK")
