"""Order offers and escalation – no urgent order is silently missed. No Streamlit imports.

When an order is assigned (or reassigned), the partner gets an offer that escalates until someone answers:

    0 min  Sent         in-app card with Accept / Can't take ("Seen" once the partner's app shows it)
    1 min  Ringing      loud sound + vibration in the partner app, repeated every 15 s
    3 min  Calling      AI voice call: Twilio when configured, else a simulated call in the app (Demo mode);
                        skipped for low-priority orders
    5 min  No response  red alert for the Branch Admin with the next-best partner and a Reassign button

Accept (app button or keypad 1) ends it. Can't take (app or keypad 2) puts the order back in the queue and alerts
the admin at once. tick() moves offers along; it may run from many places at the same time (admin pages, partner
app, API scheduler) because every step is claimed with one conditional UPDATE before anything happens.
Times use the real clock (the delivery ETAs use the demo's 09:00 clock).
"""
from datetime import datetime

from modules import store
from services import push, voice_call

LIVE = ("sent", "seen", "ringing", "calling")  # still waiting for the partner
NEEDS_ADMIN = ("no_response", "declined")
LABEL = {"sent": "Sent", "seen": "Seen", "ringing": "Ringing", "calling": "Calling", "accepted": "Accepted",
         "declined": "Declined", "no_response": "No response"}
STATE = {"sent": "available", "seen": "available", "ringing": "delayed", "calling": "delayed",
         "accepted": "normal", "declined": "critical", "no_response": "critical"}
EMOJI = {"sent": "📨", "seen": "👀", "ringing": "🔔", "calling": "📞", "accepted": "✅", "declined": "⛔",
         "no_response": "🚨"}
DECLINE_REASONS = ("Too far", "Vehicle issue", "On break", "Too much work", "Other")
DEFAULTS = {"ring_after_min": 1, "call_after_min": 3, "alert_after_min": 5,
            "no_call_priorities": "standard", "urgent_priorities": "medical,perishable,express"}
FMT = "%Y-%m-%d %H:%M:%S"


def now():
    """The current time (tests replace this with a fake clock)."""
    return datetime.now()


def _stamp(when=None):
    return (when or now()).strftime(FMT)


def _priorities(text):
    return {p.strip() for p in str(text or "").split(",") if p.strip()}


# ---------------------------------------------------------------- settings
def settings():
    """Escalation times (minutes) and priority lists, from the settings table with defaults."""
    saved = store.all_settings()
    out = {}
    for key, default in DEFAULTS.items():
        value = saved.get(key, default)
        out[key] = int(value) if isinstance(default, int) else str(value)
    return out


def save_settings(actor, ring_after_min, call_after_min, alert_after_min, no_call_priorities):
    """Change the escalation times (Super Admin). Times must go up: ring < call < alert."""
    if not actor or actor.get("role") != "super_admin":
        raise PermissionError("Super Admins only")
    ring, call, alert = int(ring_after_min), int(call_after_min), int(alert_after_min)
    if not 0 < ring < call < alert <= 60:
        raise ValueError("Times must go up: ring < call < alert (1–60 min).")
    values = {"ring_after_min": ring, "call_after_min": call, "alert_after_min": alert,
              "no_call_priorities": ",".join(sorted(_priorities(",".join(no_call_priorities))))}
    for key, value in values.items():
        store.set_setting(key, value, actor["user_id"])
    store.audit(actor["user_id"], "escalation_settings", "settings", values)
    return values


def is_urgent(priority, cfg=None):
    """True for priorities that get the full-screen card (medical, perishable, express by default)."""
    return priority in _priorities((cfg or settings())["urgent_priorities"])


# ---------------------------------------------------------------- log
def _log(conn, delivery_id, dp_id, level, channel, result, branch_id, details=None, when=None):
    conn.execute("INSERT INTO escalations(delivery_id, dp_id, level, channel, time, result, details, branch_id) "
                 "VALUES (?,?,?,?,?,?,?,?)", (delivery_id, dp_id, level, channel, _stamp(when), result, details,
                                              branch_id))
    # live feed: the partner's phone and the branch's screens hear about every offer step at once (WebSockets)
    store.emit(conn, "offer", branch_id, dp_id, delivery_id=delivery_id, level=level, channel=channel,
               result=result)


def log_step(delivery_id, dp_id, level, channel, result, branch_id, details=None):
    """Add one step to an order's offer timeline from outside a transaction (e.g. 'Push sent')."""
    with store.connect() as conn:
        _log(conn, delivery_id, dp_id, level, channel, result, branch_id, details)


def history(delivery_id, branch_id):
    """The offer timeline of one order, oldest first: [{time, dp_id, channel, result}]."""
    rows = store.escalations_df(delivery_id=delivery_id, branch_id=branch_id)
    return rows.iloc[::-1].to_dict("records")


# ---------------------------------------------------------------- offer lifecycle
def offer(conn, delivery_id, dp_id, branch_id, when=None):
    """Start an offer for a just-assigned order (called inside assign's transaction)."""
    conn.execute("UPDATE deliveries SET offer_status = 'sent', offered_at = ?, seen_at = NULL, escalation_level = 0 "
                 "WHERE delivery_id = ?", (_stamp(when), delivery_id))
    _log(conn, delivery_id, dp_id, 0, "app", "Sent", branch_id, when=when)
    # level 0 also pushes to the partner's phone (when Firebase is set up and a phone is registered) – after the
    # commit, so a rolled-back assignment never rings anyone
    store.after_commit(lambda: push.offer_sent(dp_id, delivery_id, branch_id))


def accepted(conn, delivery_id, dp_id, branch_id, channel="app"):
    """Record an acceptance (the delivery status itself is set by the caller)."""
    level = conn.execute("SELECT escalation_level FROM deliveries WHERE delivery_id = ?", (delivery_id,)).fetchone()
    conn.execute("UPDATE deliveries SET offer_status = 'accepted' WHERE delivery_id = ?", (delivery_id,))
    _log(conn, delivery_id, dp_id, level[0] if level else 0, channel, "Accepted", branch_id)


def clear(conn, delivery_id):
    """Forget the live offer (the admin took the order back)."""
    conn.execute("UPDATE deliveries SET offer_status = NULL, escalation_level = 0 WHERE delivery_id = ?",
                 (delivery_id,))


def _own(conn, dp_id, branch_id, delivery_id):
    row = conn.execute(
        "SELECT d.*, p.partner_id, p.name AS partner_name, p.phone AS partner_phone FROM deliveries d "
        "JOIN partners p ON p.vehicle_id = d.vehicle_id WHERE d.delivery_id = ? AND p.partner_id = ? "
        "AND d.branch_id = ? AND p.branch_id = ?", (delivery_id, dp_id, branch_id, branch_id)).fetchone()
    if row is None:
        raise PermissionError(f"Delivery {delivery_id} is not assigned to {dp_id}")
    return dict(row)


def mark_seen(dp_id, branch_id, delivery_ids):
    """The partner's app showed these offers: record the first view (Sent -> Seen; a ringing or calling offer
    keeps its stage). Returns how many changed."""
    changed = 0
    with store.transaction() as conn:
        for delivery_id in delivery_ids:
            row = _own(conn, dp_id, branch_id, delivery_id)
            if row["seen_at"] or row["offer_status"] not in (*LIVE, "no_response"):
                continue
            conn.execute("UPDATE deliveries SET seen_at = ?, offer_status = CASE offer_status WHEN 'sent' THEN 'seen' "
                         "ELSE offer_status END WHERE delivery_id = ?", (_stamp(), delivery_id))
            _log(conn, delivery_id, dp_id, row["escalation_level"] or 0, "app", "Seen", branch_id)
            changed += 1
        if changed:
            store._bump(conn)
    return changed


def respond(dp_id, branch_id, delivery_id, accept, reason="", channel="app"):
    """The partner answers an offer: accept (-> Accepted) or can't take (-> back to the queue, admin alerted).
    One transaction. PermissionError if the order isn't theirs, ValueError if it was already answered."""
    from modules import assign  # assign imports this module

    with store.transaction() as conn:
        row = _own(conn, dp_id, branch_id, delivery_id)
        if row["status"] != "assigned":
            raise ValueError(f"{delivery_id} is already {assign.STAGE.get(row['status'], row['status']).lower()}.")
        level = row["escalation_level"] or 0
        how = "on the call" if channel == "call" else "in the app"
        if accept:
            conn.execute("UPDATE deliveries SET status = 'accepted', accepted_at = ?, offer_status = 'accepted' "
                         "WHERE delivery_id = ?", (_stamp(), delivery_id))
            _log(conn, delivery_id, dp_id, level, channel, "Accepted", branch_id)
            store.log_event("delivery", f"{row['partner_name']} · {delivery_id} · Accepted {how}", branch_id=branch_id)
        else:
            reason = str(reason or "No reason").strip()[:80]
            conn.execute(
                "UPDATE deliveries SET vehicle_id = NULL, status = 'unassigned', planned_eta = NULL, stop_order = 0, "
                "assigned_at = NULL, assigned_by = NULL, accepted_at = NULL, offer_status = 'declined', "
                "escalation_level = 3 WHERE delivery_id = ?", (delivery_id,))
            assign._renumber(conn, row["vehicle_id"])
            conn.execute("INSERT INTO assignment_history(delivery_id, from_dp, to_dp, by_user, reason, time, branch_id)"
                         " VALUES (?,?,NULL,?,?,?,?)", (delivery_id, dp_id, dp_id, f"Can't take: {reason}", _stamp(),
                                                        branch_id))
            _log(conn, delivery_id, dp_id, 3, channel, f"Declined · {reason}", branch_id)
            store.log_event("delivery", f"{row['partner_name']} can't take {delivery_id} ({reason}) – back in the "
                            "queue", branch_id=branch_id)
        store._bump(conn)
    return "accepted" if accept else "declined"


def respond_by_call(delivery_id, dp_id, answer):
    """Keypad / speech answer from the voice call webhook ('accept' or 'decline'). Branch comes from the order."""
    with store.connect() as conn:
        row = conn.execute("SELECT branch_id FROM deliveries WHERE delivery_id = ?", (delivery_id,)).fetchone()
    if row is None:
        raise PermissionError(f"Unknown delivery {delivery_id}")
    return respond(dp_id, row["branch_id"], delivery_id, answer == "accept", reason="Declined on the call",
                   channel="call")


# ---------------------------------------------------------------- the timer
def _target_level(elapsed_min, cfg):
    if elapsed_min >= cfg["alert_after_min"]:
        return 3
    if elapsed_min >= cfg["call_after_min"]:
        return 2
    if elapsed_min >= cfg["ring_after_min"]:
        return 1
    return 0


def _claim(level, delivery_id):
    """Move one offer from level-1 to `level` unless someone else already did (or the partner answered)."""
    with store.connect() as conn:
        claimed = conn.execute(
            f"UPDATE deliveries SET escalation_level = ? WHERE delivery_id = ? AND escalation_level = ? "
            f"AND status = 'assigned' AND offer_status IN ({','.join('?' * len(LIVE))})",
            (level, delivery_id, level - 1, *LIVE)).rowcount
        if claimed:
            store._bump(conn)
    return bool(claimed)


def call_message(offer_row):
    """What the AI voice call says for one offer."""
    return voice_call.offer_message(str(offer_row["partner_name"]).split()[0], offer_row.get("category") or "Parcel",
                                    offer_row["customer"], offer_row["deadline"])


def _step(row, level, cfg, when):
    """Do one escalation step for an offer that was just claimed. Returns the new offer status."""
    did, dp, branch = row["delivery_id"], row["partner_id"], row["branch_id"]
    with store.transaction() as conn:
        if level == 1:
            conn.execute("UPDATE deliveries SET offer_status = 'ringing' WHERE delivery_id = ? "
                         "AND offer_status IN ('sent', 'seen')", (did,))
            _log(conn, did, dp, 1, "sound", "Ringing in the app", branch, when=when)
            return "ringing"
        if level == 2:
            if row["priority"] in _priorities(cfg["no_call_priorities"]):
                _log(conn, did, dp, 2, "call", f"Call skipped ({row['priority']} priority)", branch, when=when)
                return "ringing"
    if level == 2:
        result = voice_call.place_call(row["partner_phone"], did, dp, call_message(row))  # outside any transaction
        with store.transaction() as conn:
            conn.execute("UPDATE deliveries SET offer_status = 'calling' WHERE delivery_id = ? AND status = "
                         "'assigned' AND offer_status IN ('sent', 'seen', 'ringing')", (did,))
            _log(conn, did, dp, 2, "call", result["note"], branch, details=result.get("sid") or result["provider"],
                 when=when)
            store._bump(conn)
        return "calling"
    with store.transaction() as conn:  # level 3: nobody answered in time
        conn.execute("UPDATE deliveries SET offer_status = 'no_response' WHERE delivery_id = ?", (did,))
        _log(conn, did, dp, 3, "admin", f"No response in {cfg['alert_after_min']} min – admin alerted", branch,
             when=when)
        store.log_event("delivery", f"{row['partner_name']} didn't accept {did} in {cfg['alert_after_min']} min – "
                        "reassign?", branch_id=branch)
        store._bump(conn)
    return "no_response"


def tick(branch_id=None, dp_id=None, when=None):
    """Move every waiting offer to its next level (optionally one branch / one partner).
    Returns [(delivery_id, new offer status)] for what changed."""
    when = when or now()
    cfg = settings()
    clauses, params = ["d.status = 'assigned'", f"d.offer_status IN ({','.join('?' * len(LIVE))})"], list(LIVE)
    if branch_id:
        clauses.append("d.branch_id = ?")
        params.append(branch_id)
    if dp_id:
        clauses.append("p.partner_id = ?")
        params.append(dp_id)
    with store.connect() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT d.*, p.partner_id, p.name AS partner_name, p.phone AS partner_phone FROM deliveries d "
            "JOIN partners p ON p.vehicle_id = d.vehicle_id WHERE " + " AND ".join(clauses), params)]
    changes = []
    for row in rows:
        if not row["offered_at"]:
            continue
        elapsed = (when - datetime.strptime(row["offered_at"], FMT)).total_seconds() / 60
        target = _target_level(elapsed, cfg)
        for level in range(int(row["escalation_level"] or 0) + 1, target + 1):
            if not _claim(level, row["delivery_id"]):
                break
            changes.append((row["delivery_id"], _step(row, level, cfg, when)))
    return changes


# ---------------------------------------------------------------- reading offers
def partner_offers(dp_id, branch_id):
    """The partner's orders still waiting for an answer, most urgent first (with the last call note)."""
    with store.connect() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT d.*, p.name AS partner_name FROM deliveries d JOIN partners p ON p.vehicle_id = d.vehicle_id "
            "WHERE p.partner_id = ? AND d.branch_id = ? AND p.branch_id = ? AND d.status = 'assigned' "
            "AND d.offer_status IN ('sent', 'seen', 'ringing', 'calling', 'no_response') "
            "ORDER BY d.deadline, d.delivery_id", (dp_id, branch_id, branch_id))]
        for row in rows:
            call = conn.execute("SELECT result, details FROM escalations WHERE delivery_id = ? AND channel = 'call' "
                                "ORDER BY id DESC LIMIT 1", (row["delivery_id"],)).fetchone()
            row["call_note"] = call["result"] if call else ""
            row["demo_call"] = bool(call) and call["details"] == "demo"
    return rows


def call_offer(delivery_id, dp_id):
    """The offer a voice call is about, while it still waits for this partner – else None."""
    with store.connect() as conn:
        row = conn.execute(
            "SELECT d.*, p.partner_id, p.name AS partner_name FROM deliveries d JOIN partners p "
            "ON p.vehicle_id = d.vehicle_id WHERE d.delivery_id = ? AND p.partner_id = ? AND d.status = 'assigned' "
            "AND d.offer_status IN ('sent', 'seen', 'ringing', 'calling', 'no_response')",
            (delivery_id, dp_id)).fetchone()
    return dict(row) if row else None


def suggest(delivery_id, branch_id):
    """Next-best partner for an order that wasn't accepted – never someone who declined or didn't answer it."""
    from modules import assign  # assign imports this module

    with store.connect() as conn:
        tried = {r["dp_id"] for r in conn.execute(
            "SELECT dp_id FROM escalations WHERE delivery_id = ? AND (result LIKE 'Declined%' OR channel = 'admin')",
            (delivery_id,))}
        order = conn.execute("SELECT * FROM deliveries WHERE delivery_id = ? AND branch_id = ?",
                             (delivery_id, branch_id)).fetchone()
    if order is None:
        raise PermissionError(f"{delivery_id} is not an order of your branch")
    order = dict(order)
    found = [c for c in assign.candidates(order, branch_id)
             if c["partner_id"] not in tried and c["vehicle_id"] != order.get("vehicle_id")]
    return found[0] if found else None


def admin_alerts(branch_id):
    """Orders the admin must act on: no answer in time, or the partner can't take it. Newest first,
    each with who it was offered to, why it is here and the suggested partner."""
    with store.connect() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT d.*, (SELECT dp_id FROM escalations e WHERE e.delivery_id = d.delivery_id ORDER BY e.id DESC "
            "LIMIT 1) AS last_dp, (SELECT result FROM escalations e WHERE e.delivery_id = d.delivery_id "
            "ORDER BY e.id DESC LIMIT 1) AS last_result FROM deliveries d WHERE d.branch_id = ? AND "
            "((d.offer_status = 'no_response' AND d.status = 'assigned') OR "
            "(d.offer_status = 'declined' AND d.status = 'unassigned')) ORDER BY d.deadline", (branch_id,))]
    for row in rows:
        row["suggestion"] = suggest(row["delivery_id"], branch_id)
    return rows
