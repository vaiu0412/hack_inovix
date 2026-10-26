"""Proof of delivery. No Streamlit imports.

Medical orders can only be marked Delivered with a photo AND the customer's 4-digit code or their signature (other
orders: optional). The code goes to the customer by WhatsApp when messaging is set up; otherwise the partner's
screen shows it as a DEMO code. Only a keyed hash of the code is stored (never sent anywhere); it lasts
15 minutes and allows 5 tries.
"""
import hashlib
import hmac
import secrets
import time

from modules import assign, escalation, store
from services import messaging

REQUIRED_FOR = assign.PROOF_FOR  # one list, also checked by assign.advance()
CODE_MINUTES = 15
MAX_TRIES = 5


def required(priority):
    """True when Delivered needs proof (medical orders)."""
    return priority in REQUIRED_FOR


def _hash(delivery_id, code):
    """Keyed hash (HMAC-SHA256 with a server secret): a 4-digit code can't be recovered from it."""
    key = store.app_secret("pod_secret").encode()
    return hmac.new(key, f"{delivery_id}:{code}".encode(), hashlib.sha256).hexdigest()


def send_code(dp_id, branch_id, delivery_id):
    """Make a 4-digit code for the customer and send it. Returns {status, provider, demo_code}
    (demo_code only when it could not be sent, so the partner can still finish in Demo mode)."""
    code = f"{secrets.randbelow(10000):04d}"
    with store.transaction() as conn:
        row = escalation._own(conn, dp_id, branch_id, delivery_id)
        conn.execute("UPDATE deliveries SET pod_code_hash = ?, pod_code_expires = ?, pod_code_attempts = 0 "
                     "WHERE delivery_id = ?", (_hash(delivery_id, code), time.time() + CODE_MINUTES * 60, delivery_id))
    text = (f"DEPORT: your delivery code for {delivery_id} is {code}. Give it to the driver only when you have the "
            "parcel.")
    message_id = store.add_message(f"Delivery code sent for {delivery_id} (hidden)", to_customer=row["customer"],
                                   to_phone=row["customer_phone"], channel="sms", branch_id=branch_id,
                                   delivery_id=delivery_id)
    result = messaging.send(row["customer_phone"], text)
    # not sent: the code is on the partner's screen instead – not a draft for the admin to send by hand
    store.set_message_status(message_id, "demo" if result["status"] == "draft" else result["status"],
                             result["provider"])
    return {**result, "demo_code": None if result["status"] == "sent" else code}


def check_code(dp_id, branch_id, delivery_id, code):
    """True if the code is right (and still valid). Every try counts, even a wrong one."""
    with store.transaction() as conn:
        row = escalation._own(conn, dp_id, branch_id, delivery_id)
        tries = int(row["pod_code_attempts"] or 0)
        if not row["pod_code_hash"] or tries >= MAX_TRIES or time.time() > float(row["pod_code_expires"] or 0):
            return False
        conn.execute("UPDATE deliveries SET pod_code_attempts = ? WHERE delivery_id = ?", (tries + 1, delivery_id))
    return hmac.compare_digest(_hash(delivery_id, str(code).strip()), row["pod_code_hash"])


def complete(dp_id, branch_id, delivery_id, photo=None, signature=None, code=None, note=""):
    """Deliver with proof: a photo (bytes) and the customer's code or signature (PNG bytes). One transaction.
    ValueError when something required is missing or the code is wrong."""
    if code and not check_code(dp_id, branch_id, delivery_id, code):
        raise ValueError("Wrong or expired code.")
    method = "code" if code else "signature" if signature else None
    with store.transaction() as conn:
        row = escalation._own(conn, dp_id, branch_id, delivery_id)
        if required(row["priority"]):
            if not photo:
                raise ValueError("Medical order: add a photo.")
            if not method:
                raise ValueError("Medical order: add the customer's code or signature.")
        photo_path = str(store.save_file("pod", delivery_id, photo)) if photo else None
        signature_path = str(store.save_file("pod", f"{delivery_id}-signature", signature)) if signature else None
        conn.execute("UPDATE deliveries SET pod_method = ?, pod_at = ?, pod_photo_path = ?, pod_signature_path = ?, "
                     "pod_code_hash = NULL WHERE delivery_id = ?",
                     (method or ("photo" if photo else None), store.now_iso(), photo_path, signature_path,
                      delivery_id))
        assign.advance(dp_id, branch_id, delivery_id, "delivered", note)  # same transaction
    return True
