"""Customers: sign in with a one-time code sent to the mobile number or email on their orders, then see only their
own orders (any branch). No Streamlit.

- An account is made the first time a code is asked for a number or email that is on at least one order – so a
  stranger's number never gets a text (no cost, no spam) and there is nothing to register.
- A customer account has no usable password (sign-in is by code only), no branch and no partner.
- What a customer sees of an order: stage, ETA, promised time, area, the partner's first name and vehicle type,
  the tracking link, when it was delivered and whether proof was recorded. Never phone numbers, other stops or
  anything else of the branch.
"""
import hashlib
import secrets

from modules import store
from modules.security import hash_password
from services import sms

ROLE = "customer"
FINISHED = ("delivered", "failed")
STAGE = {"unassigned": "Order received", "assigned": "Partner assigned", "accepted": "Partner assigned",
         "picked_up": "Picked up", "in_transit": "On the way", "pending": "On the way", "delayed": "On the way",
         "rescheduled": "On the way", "delivered": "Delivered", "failed": "Not delivered"}
_DIGITS = ("REPLACE(REPLACE(REPLACE(REPLACE(REPLACE({col}, ' ', ''), '+', ''), '-', ''), '(', ''), ')', '')")


def _phone_keys(phone):
    """The forms a number may have on an order: with or without the country code."""
    digits = phone.lstrip("+")
    country = digits[:-10] if len(digits) > 10 else ""
    return [digits, digits[len(country):]]


def _order_filter(phone=None, email=None):
    clauses, params = [], []
    if phone:
        keys = _phone_keys(phone)
        clauses.append(f"{_DIGITS.format(col='d.customer_phone')} IN ({', '.join('?' * len(keys))})")
        params.extend(keys)
    if email:
        clauses.append("lower(d.customer_email) = ?")
        params.append(email.lower())
    return "(" + " OR ".join(clauses) + ")", params


def _identity(identifier):
    """(phone, email) for what the customer typed; (None, None) when it is neither."""
    text = str(identifier or "").strip()
    if "@" in text and "." in text.split("@")[-1]:
        return None, text.lower()
    return sms.normalize_phone(text), None


def has_orders(phone=None, email=None):
    """True when at least one order carries this number or email."""
    if not (phone or email):
        return False
    where, params = _order_filter(phone, email)
    with store.connect() as conn:
        return conn.execute(f"SELECT 1 FROM deliveries d WHERE {where} LIMIT 1", params).fetchone() is not None


def find(identifier):
    """The existing customer account for a number or email, or None (never creates one)."""
    phone, email = _identity(identifier)
    if not (phone or email):
        return None
    with store.connect() as conn:
        row = conn.execute("SELECT user_id FROM users WHERE role_id = ? AND (phone = ? OR lower(email) = ?)",
                           (ROLE, phone or "", email or "")).fetchone()
    return row["user_id"] if row else None


def account_for(identifier):
    """The customer's user id – made now if this number or email is on an order – or None."""
    existing = find(identifier)
    if existing:
        return existing
    phone, email = _identity(identifier)
    if not has_orders(phone, email):
        return None
    where, params = _order_filter(phone, email)
    with store.connect() as conn:
        latest = conn.execute(f"SELECT customer, customer_phone, customer_email FROM deliveries d WHERE {where} "
                              "ORDER BY created_at DESC, delivery_id DESC LIMIT 1", params).fetchone()
        email = email or (latest["customer_email"] or None)
        phone = phone or sms.normalize_phone(latest["customer_phone"])
        taken = conn.execute("SELECT 1 FROM users WHERE lower(email) = ?", ((email or "").lower(),)).fetchone()
        if taken:  # a staff account already uses this email: keep the customer account phone-only
            email = None
        user_id = ("C" + phone.lstrip("+")) if phone else "C-" + hashlib.sha1(email.encode()).hexdigest()[:12]
        hash_hex, salt = hash_password(secrets.token_urlsafe(32))  # nobody knows it: customers sign in by code
        conn.execute("INSERT INTO users(user_id, email, phone, display_name, role_id, branch_id, dp_id, password_hash, "
                     "salt, created_by, created_at) VALUES (?,?,?,?,?,NULL,NULL,?,?,?,?) ON CONFLICT DO NOTHING",
                     (user_id, email, phone, latest["customer"], ROLE, hash_hex, salt, "self (code)", store.now_iso()))
    store.audit(user_id, "customer_created", details={"by": "phone" if phone else "email"})
    return user_id


def _scope(user):
    if not user or user.get("role") != ROLE:
        raise PermissionError("Customers only")
    return _order_filter(user.get("phone"), user.get("email"))


def _public(row, track_url):
    d = dict(row)
    first = str(d.pop("partner_name") or "").split(" ")[0] or None
    return {
        "delivery_id": d["delivery_id"], "customer": d["customer"], "area": d["address_area"],
        "status": d["status"], "stage": STAGE.get(d["status"], d["status"]), "eta": d["planned_eta"],
        "deadline": d["deadline"], "priority": d["priority"], "partner_first_name": first,
        "vehicle": d["vehicle_type"], "delivered_at": d["delivered_at"], "proof": bool(d["pod_at"]),
        "branch": d["branch_name"], "lat": d["lat"], "lng": d["lng"], "track_code": d["track_code"],
        "track_url": track_url(d["delivery_id"]),
    }


def orders(user, track_url=None):
    """The customer's orders, open ones first (by ETA), then the delivered ones (newest first)."""
    where, params = _scope(user)
    track_url = track_url or (lambda _id: None)
    with store.connect() as conn:
        rows = conn.execute(
            "SELECT d.delivery_id, d.customer, d.address_area, d.status, d.planned_eta, d.deadline, d.priority, "
            "d.delivered_at, d.pod_at, d.lat, d.lng, d.track_code, p.name AS partner_name, v.type AS vehicle_type, "
            "b.name AS branch_name FROM deliveries d LEFT JOIN partners p ON p.vehicle_id = d.vehicle_id "
            "LEFT JOIN vehicles v ON v.vehicle_id = d.vehicle_id LEFT JOIN branches b ON b.branch_id = d.branch_id "
            f"WHERE {where}", params).fetchall()
    found = [_public(r, track_url) for r in rows]
    active = sorted((o for o in found if o["status"] not in FINISHED),
                    key=lambda o: (o["eta"] or "99:99", o["delivery_id"]))
    done = sorted((o for o in found if o["status"] in FINISHED), key=lambda o: o["delivered_at"] or "", reverse=True)
    return active + done


def order(user, delivery_id, track_url=None):
    """One of the customer's orders, or None when it isn't theirs."""
    return next((o for o in orders(user, track_url) if o["delivery_id"] == delivery_id), None)
