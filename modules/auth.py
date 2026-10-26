"""Authentication for Super Admins, Branch Admins, Delivery Partners and Customers. No Streamlit imports.

- sign in with email, user/partner ID or mobile number (case-insensitive, trimmed); role comes from the account
- customers sign in only with a one-time code to the mobile number or email on their orders (modules/customers)
- PBKDF2 password hashes (modules/security.py); 5 failed attempts lock the account for 2 minutes
- server-side sessions: random token for the browser, only its SHA-256 hash in the database;
  8 hours normally, 7 days with "Remember me"; logout revokes
- one-time codes (OTP) for passwordless login and password reset, by email (SMTP) or SMS (Twilio): 6 digits,
  hashed, 5 minutes, 3 tries, at most 3 codes per 10 minutes. Without a provider the code is returned so the
  screen can show it, labelled DEMO
- Super Admins sign in only through the Super Admin console, everyone else only through the
  normal form
"""
import hashlib
import hmac
import re
import secrets
import time

from modules import store
from modules.parser import setting
from modules.security import hash_password, verify_password

MAX_FAILURES = 5
LOCK_SECONDS = 120
SESSION_HOURS = 8
REMEMBER_DAYS = 7
OTP_MINUTES = 5
OTP_TRIES = 3
OTP_PER_10_MIN = 3
ROLE_LABELS = {"super_admin": "Super Admin", "branch_admin": "Branch Admin", "partner": "Delivery Partner",
               "customer": "Customer"}
NO_BRANCH = ("super_admin", "customer")  # roles not tied to one branch
VERIFY_MARK = "twilio-verify"  # otp_codes.code_hash when Twilio Verify holds the code

MESSAGES = {  # short, one sentence each (shown as-is on the sign-in page and by the API)
    "missing": "Enter your email or ID.",
    "missing_password": "Enter your password.",
    "bad_credentials": "Wrong ID or password.",
    "locked": "Too many tries. Wait 2 min.",
    "inactive": "Account inactive.",
    "branch_inactive": "Branch inactive.",
    "use_super_portal": "Use the admin console.",
    "super_only": "Super Admins only.",
    "weak_password": "Use 8+ characters with a letter and a number.",
    "otp_invalid": "Wrong or expired code.",
    "otp_unknown": "No active account found.",
    "reset_ok": "Password changed. Sign in now.",
    "google_unknown": "No DEPORT account for this email.",
    "send_failed": "Couldn't send the code. Try again.",
    "no_orders": "No orders found for this number or email.",
    "no_phone": "No mobile number on this account. Use email.",
    "no_email": "No email on this account. Use your mobile number.",
    "otp_rate": "Too many codes. Wait 10 min.",
    "use_code": "Customers sign in with a code.",
    "not_set_up": "Sign-in codes aren't set up yet (email / SMS).",
    "demo_off": "Demo access is off.",
}
DEMO_ACCOUNTS = {"branch_admin": "east.admin", "partner": "DP102", "super_admin": "superadmin"}
_DUMMY = hash_password("timing-equaliser")  # verify against something even for unknown IDs


def normalize(identifier):
    """Lower-case an email/ID and collapse spaces, so ' DP102 ' matches 'dp102'."""
    return " ".join(str(identifier or "").split()).lower()


def _sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def _find(conn, identifier):
    """The account for an email, ID or mobile number (staff before a customer with the same number)."""
    from services import sms

    key = normalize(identifier)
    if not key:
        return None
    phone = sms.normalize_phone(identifier) or "-"
    return conn.execute("SELECT u.*, b.is_active AS branch_active, b.name AS branch_name FROM users u "
                        "LEFT JOIN branches b ON b.branch_id = u.branch_id "
                        "WHERE lower(u.email) = ? OR lower(u.user_id) = ? OR lower(u.dp_id) = ? "
                        "OR REPLACE(REPLACE(u.phone, ' ', ''), '-', '') = ? "
                        "ORDER BY CASE WHEN u.role_id = 'customer' THEN 1 ELSE 0 END LIMIT 1",
                        (key, key, key, phone)).fetchone()


def public(row):
    """Account details safe to keep in a session (no hashes)."""
    user = {k: row[k] for k in ("user_id", "email", "phone", "display_name", "branch_id", "dp_id", "last_login")}
    user.update(role=row["role_id"], branch_name=row["branch_name"], is_active=bool(row["is_active"]))
    return user


def _status_problem(row, portal):
    """Why this (correctly authenticated) account may not sign in here, or None."""
    if not row["is_active"]:
        return MESSAGES["inactive"]
    if row["role_id"] not in NO_BRANCH and not row["branch_active"]:
        return MESSAGES["branch_inactive"]
    if portal == "super" and row["role_id"] != "super_admin":
        return MESSAGES["super_only"]
    if portal != "super" and row["role_id"] == "super_admin":
        return MESSAGES["use_super_portal"]
    return None


# ---------------------------------------------------------------- password sign-in
def authenticate(identifier, password, portal="workspace"):
    """Return (user, None) on success or (None, message). portal: 'workspace' or 'super'."""
    if not normalize(identifier):
        return None, MESSAGES["missing"]
    if not password:
        return None, MESSAGES["missing_password"]
    with store.connect() as conn:
        row = _find(conn, identifier)
        if row and row["role_id"] == "customer":
            return None, MESSAGES["use_code"]
        if row and (row["locked_until"] or 0) > time.time():
            return None, MESSAGES["locked"]
        hash_hex, salt = (row["password_hash"], row["salt"]) if row else _DUMMY
        if not (verify_password(password, hash_hex, salt) and row):
            if row:
                failures = (row["failed_attempts"] or 0) + 1
                locked = time.time() + LOCK_SECONDS if failures >= MAX_FAILURES else 0
                conn.execute("UPDATE users SET failed_attempts = ?, locked_until = ? WHERE user_id = ?",
                             (0 if locked else failures, locked, row["user_id"]))
                conn.execute("INSERT INTO audit_log(time, actor_user_id, action, target, details_json) VALUES "
                             "(?,?,?,?,?)", (store.now_iso(), row["user_id"], "login_failed", portal,
                                             '{"locked": %s}' % ("true" if locked else "false")))
                if locked:
                    return None, MESSAGES["locked"]
            return None, MESSAGES["bad_credentials"]
        problem = _status_problem(row, portal)
        if problem:
            return None, problem
        conn.execute("UPDATE users SET failed_attempts = 0, locked_until = 0, last_login = ? WHERE user_id = ?",
                     (store.now_iso(), row["user_id"]))
        user = public(row)
    store.audit(user["user_id"], "login", portal, {"method": "password"}, user["branch_id"])
    return user, None


def get_user(user_id):
    """One account with its branch name and status, or None."""
    with store.connect() as conn:
        row = conn.execute("SELECT u.*, b.is_active AS branch_active, b.name AS branch_name FROM users u "
                           "LEFT JOIN branches b ON b.branch_id = u.branch_id WHERE u.user_id = ?",
                           (user_id,)).fetchone()
    return public(row) if row else None


# ---------------------------------------------------------------- sessions
def create_session(user_id, remember_me=False):
    """New session; returns the token for the browser. Only its hash is stored."""
    token = secrets.token_urlsafe(32)
    lifetime = REMEMBER_DAYS * 86400 if remember_me else SESSION_HOURS * 3600
    with store.connect() as conn:
        conn.execute("INSERT INTO sessions(token_hash, user_id, created_at, expires_at, remember_me) VALUES "
                     "(?,?,?,?,?)", (_sha(token), user_id, time.time(), time.time() + lifetime, int(remember_me)))
    return token


def validate_session(token):
    """The signed-in user for a token, or None (unknown, expired, revoked, deactivated, branch off)."""
    if not isinstance(token, str) or not token:
        return None
    return validate_session_hash(_sha(token))


def session_hash(token):
    """What the database keeps of a session token (the API puts it in its JWTs, never the token itself)."""
    return _sha(token)


def session_expires_at(token_hash):
    """When a session ends (epoch seconds), or 0 when it doesn't exist."""
    with store.connect() as conn:
        row = conn.execute("SELECT expires_at FROM sessions WHERE token_hash = ?", (token_hash,)).fetchone()
    return float(row["expires_at"]) if row else 0.0


def validate_session_hash(token_hash):
    """Like validate_session, for a session known by its hash (a JWT's sid)."""
    if not isinstance(token_hash, str) or not token_hash:
        return None
    with store.connect() as conn:
        session = conn.execute("SELECT * FROM sessions WHERE token_hash = ?", (token_hash,)).fetchone()
        if not session or session["revoked"] or session["expires_at"] < time.time():
            return None
        row = conn.execute("SELECT u.*, b.is_active AS branch_active, b.name AS branch_name FROM users u "
                           "LEFT JOIN branches b ON b.branch_id = u.branch_id WHERE u.user_id = ?",
                           (session["user_id"],)).fetchone()
    if not row or not row["is_active"] or (row["role_id"] not in NO_BRANCH and not row["branch_active"]):
        return None
    return public(row)


def revoke_session(token):
    """End a session (sign out); the token stops working everywhere."""
    if token:
        revoke_session_hash(_sha(token))


def revoke_session_hash(token_hash):
    """End a session known by its hash (sign-out from the API with a JWT)."""
    if not token_hash:
        return
    with store.connect() as conn:
        row = conn.execute("SELECT user_id FROM sessions WHERE token_hash = ?", (token_hash,)).fetchone()
        conn.execute("UPDATE sessions SET revoked = 1 WHERE token_hash = ?", (token_hash,))
    if row:
        store.audit(row["user_id"], "logout")


# ---------------------------------------------------------------- one-time codes
def otp_by_email():
    """Real delivery when SMTP is configured (secrets SMTP_*); otherwise demo mode shows the code."""
    from modules import mailer

    return mailer.configured()


def demo_codes():
    """May a code be shown on screen when no email/SMS provider is set up? Only in a demo: DEMO_MODE or OTP_DEMO
    on (or offline test runs). On a real site without providers, code sign-in is off instead – otherwise anyone
    could sign in as anyone by typing their ID or mobile number."""
    from modules.parser import offline

    flag = str(setting("OTP_DEMO") or setting("DEMO_MODE") or "").strip().lower()
    return flag in ("1", "true", "yes", "on") or offline()


def _mask(email):
    name, _, domain = str(email or "").partition("@")
    return f"{name[:1]}***@{domain}" if domain else "your email"


def request_otp(identifier, purpose, channel=None):
    """Create and send a 6-digit code. Returns (demo_code_or_None, message, ok).

    channel: 'email', 'sms' or None (a typed mobile number -> SMS, anything else -> email).
    Customers: a mobile number or email that is on one of their orders makes their account the first time.
    Without a provider for the channel (Demo mode) the code is returned so the screen can show it, labelled DEMO.
    The database only ever holds a salted hash of the code – with Twilio Verify not even that.
    """
    from services import sms

    if purpose not in ("login", "reset"):
        raise ValueError("purpose must be 'login' or 'reset'")
    channel = channel or ("sms" if sms.looks_like_phone(identifier) else "email")
    if channel not in ("email", "sms"):
        raise ValueError("channel must be 'email' or 'sms'")
    with store.connect() as conn:
        row = _find(conn, identifier)
    if row is None and purpose == "login":
        from modules import customers

        if customers.account_for(identifier):
            with store.connect() as conn:
                row = _find(conn, identifier)
        elif sms.looks_like_phone(identifier) or "@" in str(identifier or ""):
            return None, MESSAGES["no_orders"], False
    if not row or not row["is_active"]:
        return None, MESSAGES["otp_unknown"], False
    if purpose == "login" and row["role_id"] == "super_admin":
        return None, MESSAGES["use_super_portal"], False
    if purpose == "reset" and row["role_id"] == "customer":
        return None, MESSAGES["use_code"], False
    phone = sms.normalize_phone(row["phone"]) if channel == "sms" else None
    email = row["email"] if channel == "email" else None
    if channel == "sms" and not phone:
        return None, MESSAGES["no_phone"], False
    if channel == "email" and not email:
        return None, MESSAGES["no_email"], False
    ready = sms.provider() != "demo" if channel == "sms" else otp_by_email()
    if not ready and not demo_codes():  # never hand out codes on screen on a real, public site
        return None, MESSAGES["not_set_up"], False
    via_verify = channel == "sms" and sms.provider() == "twilio_verify"
    code = None if via_verify else f"{secrets.randbelow(10 ** 6):06d}"
    with store.connect() as conn:
        recent = conn.execute("SELECT COUNT(*) FROM otp_codes WHERE user_id = ? AND created_at > ?",
                              (row["user_id"], time.time() - 600)).fetchone()[0]
        if recent >= OTP_PER_10_MIN:
            return None, MESSAGES["otp_rate"], False
        salt = secrets.token_hex(8)
        conn.execute("UPDATE otp_codes SET used = 1 WHERE user_id = ? AND purpose = ? AND used = 0",
                     (row["user_id"], purpose))
        conn.execute("INSERT INTO otp_codes(user_id, purpose, code_hash, salt, expires_at, created_at) VALUES "
                     "(?,?,?,?,?,?)", (row["user_id"], purpose, VERIFY_MARK if via_verify else _sha(salt + code),
                                       salt, time.time() + OTP_MINUTES * 60, time.time()))
    store.audit(row["user_id"], f"otp_requested_{purpose}", details={"channel": channel})
    if channel == "sms":
        provider = sms.provider()
        if provider == "demo":
            return code, "Demo mode: code shown on screen.", True
        sent = sms.start_verify(phone) if via_verify else sms.send_text(
            phone, f"Your DEPORT code is {code}. It expires in {OTP_MINUTES} minutes. Don't share it.")
        return (None, f"Code sent to {sms.mask(phone)}.", True) if sent else (None, MESSAGES["send_failed"], False)
    if otp_by_email():
        from modules import mailer

        if not mailer.send_code(email, code, purpose):
            return None, MESSAGES["send_failed"], False
        return None, f"Code sent to {_mask(email)}.", True
    return code, "Demo mode: code shown on screen.", True


def verify_otp(identifier, code, purpose):
    """Check a code. Returns (user, None) or (None, message). Codes are single-use (even when two tries race)."""
    with store.connect() as conn:
        row = _find(conn, identifier)
        if not row:
            return None, MESSAGES["otp_invalid"]
        otp = conn.execute("SELECT * FROM otp_codes WHERE user_id = ? AND purpose = ? AND used = 0 "
                           "ORDER BY id DESC LIMIT 1", (row["user_id"], purpose)).fetchone()
    if not otp or otp["expires_at"] < time.time() or otp["attempts"] >= OTP_TRIES:
        return None, MESSAGES["otp_invalid"]
    if otp["code_hash"] == VERIFY_MARK:  # Twilio Verify made and sent the code, so Twilio checks it (no DB open)
        from services import sms

        right = sms.check_verify(sms.normalize_phone(row["phone"]), code)
    else:
        right = hmac.compare_digest(_sha(otp["salt"] + str(code).strip()), otp["code_hash"])
    with store.connect() as conn:
        if not right:
            tries = otp["attempts"] + 1
            conn.execute("UPDATE otp_codes SET attempts = ?, used = ? WHERE id = ?",
                         (tries, int(tries >= OTP_TRIES), otp["id"]))
            return None, MESSAGES["otp_invalid"]
        if conn.execute("UPDATE otp_codes SET used = 1 WHERE id = ? AND used = 0", (otp["id"],)).rowcount != 1:
            return None, MESSAGES["otp_invalid"]  # someone else used this code a moment ago
        problem = _status_problem(row, "workspace" if purpose == "login" else
                                  ("super" if row["role_id"] == "super_admin" else "workspace"))
        if problem:
            return None, problem
        if purpose == "login":
            conn.execute("UPDATE users SET failed_attempts = 0, locked_until = 0, last_login = ? WHERE user_id = ?",
                         (store.now_iso(), row["user_id"]))
        user = public(row)
    store.audit(user["user_id"], f"otp_verified_{purpose}", details={}, branch_id=user["branch_id"])
    return user, None


def password_problem(password):
    """None if the password is strong enough, else a friendly message."""
    password = password or ""
    if len(password) < 8 or not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        return MESSAGES["weak_password"]
    return None


def set_password(user_id, new_password, actor_user_id=None):
    """Set a new password after checking its strength; signs the account out everywhere."""
    problem = password_problem(new_password)
    if problem:
        raise ValueError(problem)
    hash_hex, salt = hash_password(new_password)
    with store.connect() as conn:
        conn.execute("UPDATE users SET password_hash = ?, salt = ?, failed_attempts = 0, locked_until = 0 "
                     "WHERE user_id = ?", (hash_hex, salt, user_id))
        conn.execute("UPDATE sessions SET revoked = 1 WHERE user_id = ?", (user_id,))  # sign out everywhere
    store.audit(actor_user_id or user_id, "password_changed", user_id)


def reset_password_with_otp(identifier, code, new_password):
    """Forgot-password flow: check the reset code, then set the new password. Returns (ok, message)."""
    problem = password_problem(new_password)
    if problem:
        return False, problem
    user, error = verify_otp(identifier, code, "reset")
    if error:
        return False, error
    set_password(user["user_id"], new_password)
    return True, MESSAGES["reset_ok"]


# ---------------------------------------------------------------- permissions + scope
def has_permission(user, code):
    """True if the user's role has this permission code."""
    if not user:
        return False
    with store.connect() as conn:
        row = conn.execute("SELECT 1 FROM role_permissions rp JOIN permissions p ON p.perm_id = rp.perm_id "
                           "WHERE rp.role_id = ? AND p.code = ?", (user["role"], code)).fetchone()
    return row is not None


def require_permission(user, code):
    """Raise PermissionError unless the user's role has this permission code."""
    if not has_permission(user, code):
        raise PermissionError(f"{ROLE_LABELS.get((user or {}).get('role'), 'This account')} cannot {code}")


def branch_scope(user):
    """The only branch this user may touch (None = all branches, Super Admin summaries only)."""
    return None if user["role"] == "super_admin" else user["branch_id"]


# ---------------------------------------------------------------- Google
def user_for_google_email(email):
    """Map a verified Google email to an EXISTING active workspace account (never auto-creates)."""
    with store.connect() as conn:
        row = _find(conn, email)
        if not row or normalize(row["email"]) != normalize(email):
            return None, MESSAGES["google_unknown"]
        problem = _status_problem(row, "workspace")
        if problem:
            return None, problem
        conn.execute("UPDATE users SET last_login = ? WHERE user_id = ?", (store.now_iso(), row["user_id"]))
        user = public(row)
    store.audit(user["user_id"], "login", "workspace", {"method": "google"}, user["branch_id"])
    return user, None


def demo_mode():
    """Quick demo access for judges: only when DEMO_MODE=true in secrets or the environment (off by default)."""
    return str(setting("DEMO_MODE", "false")).strip().lower() in ("1", "true", "yes", "on")


def demo_sign_in(kind):
    """One-click sign-in to a seeded demo account ('branch_admin', 'partner', 'super_admin').
    Refused unless DEMO_MODE is on; inactive accounts/branches are still refused. Audited."""
    if not demo_mode():
        return None, MESSAGES["demo_off"]
    with store.connect() as conn:
        row = _find(conn, DEMO_ACCOUNTS[kind])
        if row is None:
            return None, MESSAGES["bad_credentials"]
        problem = _status_problem(row, "super" if kind == "super_admin" else "workspace")
        if problem:
            return None, problem
        conn.execute("UPDATE users SET last_login = ? WHERE user_id = ?", (store.now_iso(), row["user_id"]))
        user = public(row)
    store.audit(user["user_id"], "login", "demo", {"method": "quick demo access"}, user["branch_id"])
    return user, None


if __name__ == "__main__":
    import os
    import tempfile
    from pathlib import Path

    os.environ["RIPPLE_DB"] = str(Path(tempfile.mkdtemp()) / "auth.db")
    store.init_db()
    for ident, pw, portal in [
        ("east.admin@deport.in", "Admin@123", "workspace"),
        (" dp102 ", "Partner@123", "workspace"),
        ("superadmin@deport.in", "Super@123", "workspace"),
        ("superadmin@deport.in", "Super@123", "super"),
        ("dp102", "nope", "workspace"),
    ]:
        user, error = authenticate(ident, pw, portal)
        print(f"{ident:24} {portal:9} ->", (user["role"], user["branch_id"]) if user else error)
    token = create_session("DP102", remember_me=True)
    assert validate_session(token)["dp_id"] == "DP102"
    revoke_session(token)
    assert validate_session(token) is None
    code, message, ok = request_otp("dp102@deport.in", "login")
    print("OTP:", message, "| demo code shown:", bool(code))
    assert verify_otp("DP102", code, "login")[0]["user_id"] == "DP102"
    assert verify_otp("DP102", code, "login")[0] is None  # single use
    print("auth OK")
