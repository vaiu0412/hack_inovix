"""Work assignment for the Branch Admin – no Streamlit imports.

- create_order / import_orders: new orders (the area text goes through the fuzzy place resolver)
- candidates / best_match: rank the branch's partners for one order, with a short reason
  ("Arun · 1.2 km away · 3/8 load · 🚐 fits"). Scored by distance from the partner's position or
  stops (haversine), load vs. capacity, vehicle fits the package, partner status (never critical,
  on break or off), same-route bonus and whether the deadline can still be met.
- assign / reassign / unassign: ONE transaction each – vehicle, status, ETA and stop order
  (cheapest insertion), later stops' ETAs, partner notification, history, activity log.
- auto_assign_plan / apply_plan: every unassigned order, respecting capacity; applied in one go.
- advance: the partner's flow assigned -> accepted -> picked_up -> in_transit -> delivered (no skipping).

Everything is scoped to one branch; the branch always comes from the signed-in user.
"""
import re
from datetime import datetime

import pandas as pd

from modules import store
from modules.data_loader import NOW_MIN, haversine_km, hhmm_to_min, min_to_hhmm
from modules.places import find_area
from modules.recommender import DROP_MIN, travel_min

SIZES = ("small", "medium", "large")
FITS = {"bike": {"small"}, "car": {"small", "medium"}, "van": {"small", "medium", "large"},
        "truck": {"small", "medium", "large"}}
MAX_STOPS = {"bike": 8, "car": 10, "van": 12, "truck": 14}
VEHICLE_EMOJI = {"bike": "🏍️", "car": "🚗", "van": "🚐", "truck": "🚚"}
CATEGORIES = ("Parcel", "Food", "Medicine", "Groceries", "Documents", "Electronics")
PRIORITIES = ("medical", "perishable", "express", "standard")
REASONS = ("Partner busy", "Vehicle issue", "Closer partner", "Customer request", "Other")
FLOW = ("assigned", "accepted", "picked_up", "in_transit", "delivered")
NEXT = {"assigned": "accepted", "accepted": "picked_up", "picked_up": "in_transit", "in_transit": "delivered",
        "pending": "delivered", "delayed": "delivered", "rescheduled": "in_transit"}
ACTION = {"accepted": "Accept", "picked_up": "Picked up", "in_transit": "Start", "delivered": "Delivered"}
STAGE = {"unassigned": "Unassigned", "assigned": "New", "accepted": "Accepted", "picked_up": "Picked up",
         "in_transit": "On the way", "pending": "On the way", "delivered": "Delivered", "failed": "Failed",
         "delayed": "Delayed", "rescheduled": "Rescheduled"}
STAMP = {"accepted": "accepted_at", "picked_up": "picked_at", "delivered": "delivered_at"}
CSV_COLUMNS = ["customer", "phone", "area", "category", "priority", "deadline", "package_size", "notes"]
TIME_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _branch_admin(actor):
    if not actor or actor.get("role") != "branch_admin" or not actor.get("branch_id"):
        raise PermissionError("Branch admins only")
    return actor["branch_id"]


# ---------------------------------------------------------------- new orders
def resolve_area(text):
    """Area text (typos, Tamil, short forms) -> {place, road_id, road_name, lat, lng, score} or None."""
    return find_area(text)


def _next_id(conn):
    numbers = [int(m.group(1)) for (did,) in conn.execute("SELECT delivery_id FROM deliveries")
               if (m := re.fullmatch(r"D(\d+)", str(did)))]
    return f"D{max(numbers, default=0) + 1:02d}"


def check_order(customer, phone, area, category, priority, deadline, package_size):
    """Problems with an order (short messages), or [] when it can be saved. Also returns the place."""
    problems = []
    if not str(customer or "").strip():
        problems.append("Customer is missing.")
    if not re.sub(r"\D", "", str(phone or "")):
        problems.append("Phone is missing.")
    place = resolve_area(area)
    if not place:
        problems.append(f"Place not found: {area or '—'}.")
    if category not in CATEGORIES:
        problems.append(f"Unknown category: {category}.")
    if priority not in PRIORITIES:
        problems.append(f"Unknown priority: {priority}.")
    if not TIME_RE.match(str(deadline or "").strip()):
        problems.append(f"Deadline must be HH:MM: {deadline}.")
    if package_size not in SIZES:
        problems.append(f"Size must be small, medium or large: {package_size}.")
    return problems, place


def create_order(actor, customer, phone, area, category, priority, deadline, package_size, notes=""):
    """Save a new order as unassigned in the admin's branch. Returns (delivery_id, place)."""
    branch = _branch_admin(actor)
    deadline = str(deadline).strip()
    problems, place = check_order(customer, phone, area, category, priority, deadline, package_size)
    if problems:
        raise ValueError(" ".join(problems))
    deadline = min_to_hhmm(hhmm_to_min(deadline))
    with store.transaction() as conn:
        delivery_id = _next_id(conn)
        conn.execute(
            "INSERT INTO deliveries(delivery_id, customer, address_area, lat, lng, vehicle_id, road_id, stop_order, "
            "planned_eta, deadline, priority, customer_phone, status, original_vehicle, branch_id, created_by, "
            "created_at, package_size, category, notes) VALUES (?,?,?,?,?,NULL,?,0,NULL,?,?,?,'unassigned',NULL,?,?,?,?,?,?)",
            (delivery_id, str(customer).strip(), place["place"], place["lat"], place["lng"], place["road_id"], deadline,
             priority, str(phone).strip(), branch, actor["user_id"], _now(), package_size, category,
             str(notes or "").strip()))
        store.log_event("delivery", f"New order {delivery_id} · {place['place']} · by {deadline}", branch_id=branch)
        store.audit(actor["user_id"], "order_created", delivery_id, {"place": place["place"]}, branch)
    return delivery_id, place


def validate_rows(df):
    """CSV rows -> (good rows, [(row number, problem)]). Row numbers match the spreadsheet (header = 1)."""
    df = df.rename(columns=lambda c: str(c).strip().lower())
    missing = [c for c in CSV_COLUMNS[:7] if c not in df.columns]
    if missing:
        return [], [(1, f"Missing columns: {', '.join(missing)}.")]
    good, errors = [], []
    for i, row in enumerate(df.fillna("").to_dict("records"), start=2):
        row = {k: str(row.get(k, "")).strip() for k in CSV_COLUMNS}
        row["category"] = row["category"].capitalize() or "Parcel"
        row["priority"], row["package_size"] = row["priority"].lower() or "standard", row["package_size"].lower() or "small"
        problems, _ = check_order(row["customer"], row["phone"], row["area"], row["category"], row["priority"],
                                  row["deadline"], row["package_size"])
        if problems:
            errors.append((i, " ".join(problems)))
        else:
            good.append(row)
    return good, errors


def import_orders(actor, rows):
    return [create_order(actor, r["customer"], r["phone"], r["area"], r["category"], r["priority"], r["deadline"],
                         r["package_size"], r.get("notes", ""))[0] for r in rows]


def csv_template():
    return pd.DataFrame([
        {"customer": "Anand Stores", "phone": "+91 90000 30001", "area": "Gandhipuram", "category": "Groceries",
         "priority": "standard", "deadline": "14:30", "package_size": "medium", "notes": "Back gate"},
        {"customer": "City Clinic", "phone": "+91 90000 30002", "area": "RS Puram", "category": "Medicine",
         "priority": "medical", "deadline": "12:00", "package_size": "small", "notes": ""},
    ], columns=CSV_COLUMNS).to_csv(index=False)


# ---------------------------------------------------------------- scoring
def _critical_partners(branch):
    """Partners who reported an open alert or carry a Critical delivery: don't add work to them."""
    critical = set()
    vehicles_hit = set()
    for issue in store.list_issues(store.OPEN_ISSUE_STATUSES, branch_id=branch):
        critical.add(issue["partner_id"])
        vehicles_hit |= {r["vehicle_id"] for r in (issue.get("plan") or {}).get("risk", []) if r["risk_label"] == "Critical"}
    return critical, vehicles_hit


def _insertion(start, stops, point):
    """Cheapest place to insert `point` into start -> stops (each stop: lat, lng, eta_min).
    Returns (index in stops, new ETA in minutes, minutes added for the stops after it, km off the way)."""
    seq = [(start[0], start[1], NOW_MIN)] + [(s[0], s[1], s[2]) for s in stops]
    best = None
    for i in range(len(seq)):
        a = seq[i]
        to_new = haversine_km(a[0], a[1], *point)
        extra = to_new
        added = 0.0
        if i + 1 < len(seq):
            b = seq[i + 1]
            extra = to_new + haversine_km(*point, b[0], b[1]) - haversine_km(a[0], a[1], b[0], b[1])
            added = travel_min(to_new) + DROP_MIN + travel_min(haversine_km(*point, b[0], b[1])) \
                - travel_min(haversine_km(a[0], a[1], b[0], b[1]))
        eta = max(a[2], NOW_MIN) + travel_min(to_new) + DROP_MIN
        if best is None or extra < best[3]:
            best = (i, eta, max(added, 0.0), extra)
    return best


def _partner_rows(branch):
    partners = store.partners_df(branch)
    deliveries = store.deliveries_df(branch_id=branch, include_done=False)
    return partners, deliveries


def candidates(order, branch, extra_load=None, partners=None, deliveries=None):
    """All partners of the branch who could take `order` (a deliveries row as dict), best first."""
    extra_load = extra_load or {}
    if partners is None:
        partners, deliveries = _partner_rows(branch)
    critical, vehicles_hit = _critical_partners(branch)
    point = (float(order["lat"]), float(order["lng"]))
    deadline = hhmm_to_min(order["deadline"])
    out = []
    for p in partners.to_dict("records"):
        kind = p["vehicle_type"]
        if not p["account_active"] or p["status"] in ("on_break", "off_duty"):
            continue
        if p["partner_id"] in critical or p["vehicle_id"] in vehicles_hit:
            continue
        if order.get("package_size", "small") not in FITS.get(kind, {"small"}):
            continue
        own = deliveries[(deliveries["vehicle_id"] == p["vehicle_id"]) & (deliveries["delivery_id"] != order["delivery_id"])]
        own = own.sort_values("eta_min")
        load, limit = len(own) + extra_load.get(p["partner_id"], 0), MAX_STOPS.get(kind, 8)
        if load >= limit:
            continue
        stops = list(zip(own["lat"], own["lng"], own["eta_min"]))
        index, eta, added, _ = _insertion((p["lat"], p["lng"]), stops, point)
        near_km = min([haversine_km(p["lat"], p["lng"], *point)] + [haversine_km(s[0], s[1], *point) for s in stops])
        same_route = order.get("road_id") in str(p.get("route_roads") or "").split("|")
        feasible = eta <= deadline
        score = near_km + 2.5 * load / limit - (1.5 if same_route else 0) + (0 if feasible else 50)
        reason = (f"{p['name']} · {near_km:.1f} km away · {load}/{limit} load · {VEHICLE_EMOJI.get(kind, '')} fits"
                  + (" · same route" if same_route else "") + ("" if feasible else " · late"))
        out.append({"partner_id": p["partner_id"], "name": p["name"], "vehicle_id": p["vehicle_id"],
                    "vehicle_type": kind, "distance_km": round(near_km, 2), "load": load, "limit": limit,
                    "same_route": same_route, "feasible": feasible, "eta_min": int(round(eta)), "position": index,
                    "added_min": int(round(added)), "score": round(score, 3), "reason": reason})
    return sorted(out, key=lambda c: c["score"])


def _order(delivery_id, branch):
    with store.connect() as conn:  # inside a transaction this is the same connection
        row = conn.execute("SELECT * FROM deliveries WHERE delivery_id = ? AND branch_id = ?",
                           (delivery_id, branch)).fetchone()
    if row is None:
        raise PermissionError(f"{delivery_id} is not an order of your branch")
    return dict(row)


def best_match(delivery_id, branch):
    found = candidates(_order(delivery_id, branch), branch)
    return found[0] if found else None


# ---------------------------------------------------------------- assign / reassign / unassign
def _partner_of_vehicle(conn, vehicle_id, branch):
    row = conn.execute("SELECT partner_id, name, status FROM partners WHERE vehicle_id = ? AND branch_id = ?",
                       (vehicle_id, branch)).fetchone() if vehicle_id else None
    return dict(row) if row else None


def _renumber(conn, vehicle_id):
    """Stop order = delivered stops first (as they were), then the open stops by ETA."""
    rows = conn.execute("SELECT delivery_id, status, stop_order, planned_eta FROM deliveries WHERE vehicle_id = ?",
                        (vehicle_id,)).fetchall()
    done = sorted([r for r in rows if r["status"] in store.ACTIVE_DONE], key=lambda r: r["stop_order"])
    todo = sorted([r for r in rows if r["status"] not in store.ACTIVE_DONE],
                  key=lambda r: (hhmm_to_min(r["planned_eta"]) if r["planned_eta"] else 10 ** 6, r["stop_order"]))
    for number, r in enumerate(done + todo, start=1):
        conn.execute("UPDATE deliveries SET stop_order = ? WHERE delivery_id = ?", (number, r["delivery_id"]))


def assign(actor, delivery_id, dp_id, reason="Assigned", source="manual"):
    """Give an order to a partner of the same branch (also used to reassign). One transaction."""
    branch = _branch_admin(actor)
    with store.transaction() as conn:
        order = _order(delivery_id, branch)
        if order["status"] in store.ACTIVE_DONE:
            raise ValueError(f"{delivery_id} is already {order['status']}.")
        partner = conn.execute("SELECT p.*, v.type AS vehicle_type, v.current_lat AS lat, v.current_lng AS lng, "
                               "v.route_roads, COALESCE(u.is_active, 1) AS account_active FROM partners p JOIN vehicles v "
                               "ON v.vehicle_id = p.vehicle_id LEFT JOIN users u ON u.dp_id = p.partner_id "
                               "WHERE p.partner_id = ? AND p.branch_id = ?", (dp_id, branch)).fetchone()
        if partner is None:
            raise PermissionError(f"{dp_id} is not a partner of your branch")
        if not partner["account_active"]:
            raise ValueError(f"{dp_id} is inactive.")
        if order.get("package_size", "small") not in FITS.get(partner["vehicle_type"], {"small"}):
            raise ValueError(f"{order['package_size'].capitalize()} parcel doesn't fit a {partner['vehicle_type']}.")
        old = _partner_of_vehicle(conn, order["vehicle_id"], branch)
        if old and old["partner_id"] == dp_id:
            raise ValueError(f"{delivery_id} is already with {dp_id}.")

        others = pd.read_sql_query(
            "SELECT delivery_id, lat, lng, planned_eta FROM deliveries WHERE vehicle_id = ? AND delivery_id != ? "
            "AND status NOT IN ('delivered', 'failed') AND planned_eta IS NOT NULL", conn,
            params=(partner["vehicle_id"], delivery_id))
        others["eta_min"] = others["planned_eta"].apply(hhmm_to_min)
        others = others.sort_values("eta_min")
        index, eta, added, _ = _insertion((partner["lat"], partner["lng"]),
                                          list(zip(others["lat"], others["lng"], others["eta_min"])),
                                          (order["lat"], order["lng"]))
        for later in others.iloc[index:].itertuples():  # stops after the new one move by the detour
            conn.execute("UPDATE deliveries SET planned_eta = ? WHERE delivery_id = ?",
                         (min_to_hhmm(later.eta_min + added), later.delivery_id))
        now = _now()
        conn.execute("UPDATE deliveries SET vehicle_id = ?, status = 'assigned', planned_eta = ?, assigned_at = ?, "
                     "assigned_by = ?, accepted_at = NULL, picked_at = NULL, original_vehicle = COALESCE(original_vehicle, ?), "
                     "note = ? WHERE delivery_id = ?",
                     (partner["vehicle_id"], min_to_hhmm(eta), now, actor["user_id"], partner["vehicle_id"],
                      "reassigned" if old else "", delivery_id))
        _renumber(conn, partner["vehicle_id"])
        if old:
            _renumber(conn, order["vehicle_id"])
        if partner["status"] == "standby":
            conn.execute("UPDATE partners SET status = 'on_duty' WHERE partner_id = ?", (dp_id,))
        due = min_to_hhmm(hhmm_to_min(order["deadline"]))
        store.add_message(f"New delivery {delivery_id} · {order['address_area']} · by {due}", to_partner=dp_id,
                          branch_id=branch)
        if old:
            store.add_message(f"{delivery_id} moved to another partner. Skip it.", to_partner=old["partner_id"],
                              branch_id=branch)
        conn.execute("INSERT INTO assignment_history(delivery_id, from_dp, to_dp, by_user, reason, time, branch_id) "
                     "VALUES (?,?,?,?,?,?,?)", (delivery_id, old["partner_id"] if old else None, dp_id,
                                                actor["user_id"], reason, now, branch))
        verb = "reassigned" if old else "assigned"
        store.log_event("delivery", f"{delivery_id} {verb} to {dp_id} ({partner['name']}) · ETA {min_to_hhmm(eta)}",
                        branch_id=branch)
        store.audit(actor["user_id"], f"order_{verb}", delivery_id,
                    {"to": dp_id, "from": old["partner_id"] if old else None, "reason": reason, "via": source}, branch)
        store._bump(conn)
    return {"delivery_id": delivery_id, "partner_id": dp_id, "eta": min_to_hhmm(eta), "stop": index + 1,
            "from": old["partner_id"] if old else None}


def reassign(actor, delivery_id, dp_id, reason):
    return assign(actor, delivery_id, dp_id, reason=reason)


def unassign(actor, delivery_id, reason):
    """Back to the queue (not for delivered orders). One transaction."""
    branch = _branch_admin(actor)
    with store.transaction() as conn:
        order = _order(delivery_id, branch)
        if order["status"] in store.ACTIVE_DONE or not order["vehicle_id"]:
            raise ValueError(f"{delivery_id} can't be unassigned.")
        old = _partner_of_vehicle(conn, order["vehicle_id"], branch)
        conn.execute("UPDATE deliveries SET vehicle_id = NULL, status = 'unassigned', planned_eta = NULL, stop_order = 0, "
                     "assigned_at = NULL, assigned_by = NULL, accepted_at = NULL, picked_at = NULL WHERE delivery_id = ?",
                     (delivery_id,))
        _renumber(conn, order["vehicle_id"])
        if old:
            store.add_message(f"{delivery_id} removed from your list.", to_partner=old["partner_id"], branch_id=branch)
        conn.execute("INSERT INTO assignment_history(delivery_id, from_dp, to_dp, by_user, reason, time, branch_id) "
                     "VALUES (?,?,NULL,?,?,?,?)", (delivery_id, old["partner_id"] if old else None, actor["user_id"],
                                                   reason, _now(), branch))
        store.log_event("delivery", f"{delivery_id} unassigned ({reason})", branch_id=branch)
        store.audit(actor["user_id"], "order_unassigned", delivery_id, {"reason": reason}, branch)
        store._bump(conn)


def unassigned_orders(branch):
    df = store.deliveries_df(branch_id=branch)
    return df[df["status"] == "unassigned"].sort_values(["deadline_min", "delivery_id"])


def auto_assign_plan(branch):
    """Best partner for every unassigned order (most urgent first), never above a vehicle's capacity."""
    partners, deliveries = _partner_rows(branch)
    extra, plan = {}, []
    order_rank = {p: i for i, p in enumerate(PRIORITIES)}
    queue = unassigned_orders(branch)
    queue = queue.assign(rank=queue["priority"].map(order_rank)).sort_values(["deadline_min", "rank"])
    for order in queue.to_dict("records"):
        found = candidates(order, branch, extra, partners, deliveries)
        if found:
            best = found[0]
            extra[best["partner_id"]] = extra.get(best["partner_id"], 0) + 1
            plan.append({"delivery_id": order["delivery_id"], "customer": order["customer"],
                         "area": order["address_area"], "partner_id": best["partner_id"], "reason": best["reason"]})
        else:
            plan.append({"delivery_id": order["delivery_id"], "customer": order["customer"],
                         "area": order["address_area"], "partner_id": None, "reason": "No partner fits"})
    return plan


def apply_plan(actor, plan):
    """Assign every planned order in ONE transaction (all or nothing). Returns how many were assigned."""
    done = 0
    with store.transaction():
        for row in plan:
            if row["partner_id"]:
                assign(actor, row["delivery_id"], row["partner_id"], reason="Auto-assign", source="auto")
                done += 1
    return done


def workload(branch):
    """Open stops vs. capacity per partner (for the workload bars)."""
    partners, deliveries = _partner_rows(branch)
    rows = []
    for p in partners.to_dict("records"):
        open_stops = int((deliveries["vehicle_id"] == p["vehicle_id"]).sum())
        rows.append({"partner_id": p["partner_id"], "name": p["name"], "vehicle_type": p["vehicle_type"],
                     "open": open_stops, "limit": MAX_STOPS.get(p["vehicle_type"], 8), "status": p["status"]})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- partner flow
def advance(dp_id, branch_id, delivery_id, to_status, note=""):
    """Partner moves one of THEIR deliveries one step: Accept -> Picked up -> Start -> Delivered.
    PermissionError for someone else's delivery, ValueError for a skipped step."""
    with store.transaction() as conn:
        row = conn.execute("SELECT d.*, p.name AS partner_name FROM deliveries d JOIN partners p ON p.vehicle_id = "
                           "d.vehicle_id WHERE d.delivery_id = ? AND p.partner_id = ? AND d.branch_id = ? "
                           "AND p.branch_id = ?", (delivery_id, dp_id, branch_id, branch_id)).fetchone()
        if row is None:
            raise PermissionError(f"Delivery {delivery_id} is not assigned to {dp_id}")
        if row["status"] == to_status:
            return False
        expected = NEXT.get(row["status"])
        if expected != to_status:
            raise ValueError(f"Next step for {delivery_id}: {ACTION.get(expected, 'none')}.")
        fields = {"status": to_status}
        if to_status in STAMP:
            fields[STAMP[to_status]] = _now()
        if to_status == "delivered" and note:
            fields["proof_note"] = str(note).strip()[:200]
        sets = ", ".join(f"{k} = ?" for k in fields)
        conn.execute(f"UPDATE deliveries SET {sets} WHERE delivery_id = ?", (*fields.values(), delivery_id))
        store.log_event("delivery", f"{row['partner_name']} · {delivery_id} · {STAGE[to_status]}", branch_id=branch_id)
        store._bump(conn)
    return True
