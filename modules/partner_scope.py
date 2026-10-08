"""Everything a delivery partner may see or do – and nothing more.

Every function takes the logged-in partner's dp_id (from the session or API token, never from
a form, URL or selectbox) and only touches that partner's own rows. Writes check ownership in
SQL (`... AND vehicle_id = <the partner's vehicle>`) and raise PermissionError otherwise.
Partner screens import this module only – never the manager-wide store/operations functions.
"""
from modules import issues, store
from modules.data_loader import load_all, nearest_place

PARTNER_STATUSES = ("on_duty", "on_break", "standby")
PROFILE_FIELDS = ["partner_id", "name", "phone", "status", "vehicle_id", "reg_no", "vehicle_type", "area", "assigned",
                  "delivered", "pending", "urgent", "next_stop", "next_eta", "shift", "languages", "rating"]


def _own(dp_id):
    """(partner row, vehicle row) for this dp_id, or PermissionError for unknown IDs."""
    with store.connect() as conn:
        partner = conn.execute("SELECT * FROM partners WHERE partner_id = ?", (dp_id,)).fetchone()
        vehicle = conn.execute("SELECT * FROM vehicles WHERE vehicle_id = ?",
                               (partner["vehicle_id"],)).fetchone() if partner else None
    if partner is None or vehicle is None:
        raise PermissionError("Unknown delivery partner")
    return dict(partner), dict(vehicle)


# ---------------------------------------------------------------- reads (own rows only)
def get_partner_profile(dp_id):
    partner, vehicle = _own(dp_id)
    deliveries = get_partner_deliveries(dp_id)
    todo = deliveries[~deliveries["status"].isin(["delivered", "failed"])].sort_values("eta_min")
    nxt = todo.iloc[0] if len(todo) else None
    return {
        "partner_id": dp_id, "name": partner["name"], "phone": partner["phone"], "status": partner["status"],
        "vehicle_id": vehicle["vehicle_id"], "reg_no": vehicle["reg_no"], "vehicle_type": vehicle["type"],
        "area": nearest_place(vehicle["current_lat"], vehicle["current_lng"]),
        "assigned": len(deliveries), "delivered": int((deliveries["status"] == "delivered").sum()),
        "pending": len(todo), "urgent": int(todo["priority"].isin(["medical", "perishable"]).sum()),
        "next_stop": f"{nxt['customer']}, {nxt['address_area']}" if nxt is not None else "—",
        "next_eta": nxt["planned_eta"] if nxt is not None else "—",
        "shift": f"{partner['shift_start']}–{partner['shift_end']}",
        "languages": partner["languages"].replace("|", ", "), "rating": partner["rating"],
    }


def get_partner_deliveries(dp_id):
    """This partner's deliveries (incl. ones reassigned to them), with a risk label for their own stops."""
    _own(dp_id)
    df = store._df("SELECT d.* FROM deliveries d JOIN partners p ON p.vehicle_id = d.vehicle_id "
                   "WHERE p.partner_id = ? ORDER BY d.stop_order", (dp_id,))
    df["eta_min"] = df["planned_eta"].apply(store.hhmm_to_min)
    df["deadline_min"] = df["deadline"].apply(store.hhmm_to_min)
    own_ids = set(df["delivery_id"])
    risk = {}
    for issue in store.list_issues(store.OPEN_ISSUE_STATUSES):
        for row in (issue.get("plan") or {}).get("risk", []):
            if row["delivery_id"] in own_ids:  # never expose other partners' stops
                risk.setdefault(row["delivery_id"], row["risk_label"])
    df["risk"] = df["delivery_id"].map(risk).fillna("")
    return df


def get_partner_route(dp_id):
    """Own roads in driving order, which of them are blocked, and own detour roads."""
    _, vehicle = _own(dp_id)
    roads = load_all()["roads"].set_index("road_id")
    route = [r for r in (vehicle["route_roads"] or "").split("|") if r]
    blocked = {d.get("road_id") for d in store.active_disruptions()}
    for issue in store.list_issues(store.OPEN_ISSUE_STATUSES):
        disruption = (issue.get("plan") or {}).get("disruption") or {}
        if disruption.get("type") != "breakdown":
            blocked.add(disruption.get("road_id"))
    return [{"road_id": r, "name": roads.loc[r, "name"], "points": roads.loc[r, "points"],
             "blocked": r in blocked} for r in route if r in roads.index]


def get_partner_notifications(dp_id, unread_only=False):
    _own(dp_id)
    messages = store.messages_for(dp_id, limit=50)
    return [m for m in messages if not m["read"]] if unread_only else messages


def get_partner_incidents(dp_id):
    """This partner's own reports: status and outcome only (no other partners' plan details)."""
    _own(dp_id)
    out = []
    for issue in store.list_issues(partner_id=dp_id):
        plan = issue.get("plan") or {}
        out.append({"issue_id": issue["issue_id"], "created_at": issue["created_at"], "summary": issue["summary"],
                    "status": issue["status"], "decided_at": issue.get("decided_at"),
                    "decision_note": issue.get("decision_note"), "headline": plan.get("headline", ""),
                    "transcript": issue.get("transcript")})
    return out


def route_road_options(dp_id):
    """Roads to tap when a report has no place: own roads first, then the rest of the city."""
    _, vehicle = _own(dp_id)
    roads = load_all()["roads"]
    names = dict(zip(roads["road_id"], roads["name"]))
    own = [r for r in (vehicle["route_roads"] or "").split("|") if r in names]
    return [(r, names[r]) for r in own + [r for r in names if r not in own]]


# ---------------------------------------------------------------- writes (ownership checked)
def mark_delivered(dp_id, delivery_id):
    """Mark one of the partner's own deliveries as delivered. PermissionError for anyone else's."""
    partner, _ = _own(dp_id)
    with store.connect() as conn:
        updated = conn.execute(
            "UPDATE deliveries SET status = 'delivered' WHERE delivery_id = ? AND status != 'delivered' "
            "AND vehicle_id = (SELECT vehicle_id FROM partners WHERE partner_id = ?)", (delivery_id, dp_id)).rowcount
        owned = conn.execute(
            "SELECT 1 FROM deliveries WHERE delivery_id = ? AND vehicle_id = "
            "(SELECT vehicle_id FROM partners WHERE partner_id = ?)", (delivery_id, dp_id)).fetchone()
    if not owned:
        raise PermissionError(f"Delivery {delivery_id} is not assigned to {dp_id}")
    if updated:
        store.log_event("delivery", f"{partner['name']} delivered {delivery_id}")
    return bool(updated)


def mark_notifications_read(dp_id):
    _own(dp_id)
    store.mark_messages_read(dp_id)


def set_status(dp_id, status):
    partner, _ = _own(dp_id)
    if status not in PARTNER_STATUSES:
        raise ValueError(f"Unknown status {status}")
    store.set_partner_status(dp_id, status)
    store.log_event("system", f"{partner['name']} is now {status.replace('_', ' ')}")


def preview_issue(dp_id, text="", audio=None, quick_type=None):
    """What we understood from the partner's report (nothing is saved)."""
    _own(dp_id)
    return issues.preview(dp_id, text=text, audio=audio, quick_type=quick_type)


def report_issue(dp_id, problem, transcript="", engine="typed", audio=None, quick_type=None):
    """Send the partner's report to operations. The reporter is always the logged-in partner."""
    partner, vehicle = _own(dp_id)
    problem = {**problem, "reported_by": dp_id, "reporter_name": partner["name"]}
    if problem.get("type") == "breakdown":
        problem["vehicle_id"] = vehicle["vehicle_id"]  # a partner can only report their own vehicle
    if problem.get("type") == "customer_unavailable" and problem.get("delivery_id"):
        own = set(get_partner_deliveries(dp_id)["delivery_id"])
        if problem["delivery_id"] not in own:
            raise PermissionError(f"Delivery {problem['delivery_id']} is not assigned to {dp_id}")
    return issues.submit(dp_id, problem, transcript=transcript, engine=engine, audio=audio,
                         quick_type=quick_type, source="partner")
