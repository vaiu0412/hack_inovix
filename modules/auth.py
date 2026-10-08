"""Authentication for Super Admins, Branch Admins and Delivery Partners. No Streamlit imports.

- sign in with email OR user/partner ID (case-insensitive, trimmed); role comes from the account
- PBKDF2 password hashes (modules/security.py); 5 failed attempts lock the account for 2 minutes
- server-side sessions: random token for the browser, only its SHA-256 hash in the database;
  8 hours normally, 7 days with "Remember me"; logout revokes
- one-time codes (OTP) for passwordless login and password reset: 6 digits, hashed, 5 minutes,
  3 tries. Without SMS credentials the code is returned so the UI can show a "Demo SMS"
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
ROLE_LABELS = {"super_admin": "Super Admin", "branch_admin": "Branch Admin", "partner": "Delivery Partner"}

MESSAGES = {
    "missing": "Enter your email or ID and your password.",
    "bad_credentials": "Incorrect email/ID or password",
    "locked": "Too many attempts, try again in 2 minutes",
    "inactive": "Account deactivated — contact your branch admin",
    "branch_inactive": "Branch is inactive",
    "use_super_portal": "Super Admin accounts sign in through Super Admin access.",
    "super_only": "This console is for Super Admins only.",
    "weak_password": "Use at least 8 characters with a letter and a number.",
    "otp_invalid": "That code is wrong or has expired. Request a new one.",
    "otp_unknown": "We couldn't find an active account with that email or ID.",
}
_DUMMY = hash_password("timing-equaliser")  # verify against something even for unknown IDs


def normalize(identifier):
    return " ".join(str(identifier or "").split()).lower()


def _sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def _find(conn, identifier):
    key = normalize(identifier)
    if not key:
        return None
    return conn.execute("SELECT u.*, b.is_active AS branch_active, b.name AS branch_name FROM users u "
                        "LEFT JOIN branches b ON b.branch_id = u.branch_id "
                        "WHERE lower(u.email) = ? OR lower(u.user_id) = ? OR lower(u.dp_id) = ?",
                        (key, key, key)).fetchone()


def public(row):
    """Account details safe to keep in a session (no hashes)."""
    user = {k: row[k] for k in ("user_id", "email", "phone", "display_name", "branch_id", "dp_id", "last_login")}
    user.update(role=row["role_id"], branch_name=row["branch_name"], is_active=bool(row["is_active"]))
    return user


def _status_problem(row, portal):
    """Why this (correctly authenticated) account may not sign in here, or None."""
    if not row["is_active"]:
        return MESSAGES["inactive"]
    if row["role_id"] != "super_admin" and not row["branch_active"]:
        return MESSAGES["branch_inactive"]
    if portal == "super" and row["role_id"] != "super_admin":
        return MESSAGES["super_only"]
    if portal != "super" and row["role_id"] == "super_admin":
        return MESSAGES["use_super_portal"]
    return None


# ---------------------------------------------------------------- password sign-in
def authenticate(identifier, password, portal="workspace"):
    """Return (user, None) on success or (None, message). portal: 'workspace' or 'super'."""
    if not normalize(identifier) or not password:
        return None, MESSAGES["missing"]
    with store.connect() as conn:
        row = _find(conn, identifier)
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
    with store.connect() as conn:
        session = conn.execute("SELECT * FROM sessions WHERE token_hash = ?", (_sha(token),)).fetchone()
        if not session or session["revoked"] or session["expires_at"] < time.time():
            return None
        row = conn.execute("SELECT u.*, b.is_active AS branch_active, b.name AS branch_name FROM users u "
                           "LEFT JOIN branches b ON b.branch_id = u.branch_id WHERE u.user_id = ?",
                           (session["user_id"],)).fetchone()
    if not row or not row["is_active"] or (row["role_id"] != "super_admin" and not row["branch_active"]):
        return None
    return public(row)


def revoke_session(token):
    if not token:
        return
    with store.connect() as conn:
        row = conn.execute("SELECT user_id FROM sessions WHERE token_hash = ?", (_sha(token),)).fetchone()
        conn.execute("UPDATE sessions SET revoked = 1 WHERE token_hash = ?", (_sha(token),))
    if row:
        store.audit(row["user_id"], "logout")


# ---------------------------------------------------------------- one-time codes
def sms_configured():
    return bool(setting("SMS_API_KEY"))


def request_otp(identifier, purpose):
    """Create a 6-digit code. Returns (demo_code_or_None, message, ok).

    In demo mode (no SMS credentials) the code is returned so the UI can show it as a "Demo SMS".
    The database only ever holds a salted hash of the code.
    """
    if purpose not in ("login", "reset"):
        raise ValueError("purpose must be 'login' or 'reset'")
    with store.connect() as conn:
        row = _find(conn, identifier)
        if not row or not row["is_active"]:
            return None, MESSAGES["otp_unknown"], False
        if purpose == "login" and row["role_id"] == "super_admin":
            return None, MESSAGES["use_super_portal"], False
        code = f"{secrets.randbelow(10 ** 6):06d}"
        salt = secrets.token_hex(8)
        conn.execute("UPDATE otp_codes SET used = 1 WHERE user_id = ? AND purpose = ? AND used = 0",
                     (row["user_id"], purpose))
        conn.execute("INSERT INTO otp_codes(user_id, purpose, code_hash, salt, expires_at, created_at) VALUES "
                     "(?,?,?,?,?,?)", (row["user_id"], purpose, _sha(salt + code), salt,
                                       time.time() + OTP_MINUTES * 60, time.time()))
        phone = row["phone"] or ""
    store.audit(row["user_id"], f"otp_requested_{purpose}")
    hint = f"…{phone[-4:]}" if phone else "your phone"
    return (None if sms_configured() else code), f"We sent a 6-digit code to {hint}.", True


def verify_otp(identifier, code, purpose):
    """Check a code. Returns (user, None) or (None, message). Codes are single-use."""
    with store.connect() as conn:
        row = _find(conn, identifier)
        if not row:
            return None, MESSAGES["otp_invalid"]
        otp = conn.execute("SELECT * FROM otp_codes WHERE user_id = ? AND purpose = ? AND used = 0 "
                           "ORDER BY id DESC LIMIT 1", (row["user_id"], purpose)).fetchone()
        if not otp or otp["expires_at"] < time.time() or otp["attempts"] >= OTP_TRIES:
            return None, MESSAGES["otp_invalid"]
        if not hmac.compare_digest(_sha(otp["salt"] + str(code).strip()), otp["code_hash"]):
            tries = otp["attempts"] + 1
            conn.execute("UPDATE otp_codes SET attempts = ?, used = ? WHERE id = ?",
                         (tries, int(tries >= OTP_TRIES), otp["id"]))
            return None, MESSAGES["otp_invalid"]
        conn.execute("UPDATE otp_codes SET used = 1 WHERE id = ?", (otp["id"],))
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
    return True, "Password reset successful"


# ---------------------------------------------------------------- permissions + scope
def has_permission(user, code):
    if not user:
        return False
    with store.connect() as conn:
        row = conn.execute("SELECT 1 FROM role_permissions rp JOIN permissions p ON p.perm_id = rp.perm_id "
                           "WHERE rp.role_id = ? AND p.code = ?", (user["role"], code)).fetchone()
    return row is not None


def require_permission(user, code):
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
            return None, "No account uses this Google email."
        problem = _status_problem(row, "workspace")
        if problem:
            return None, problem
        conn.execute("UPDATE users SET last_login = ? WHERE user_id = ?", (store.now_iso(), row["user_id"]))
        user = public(row)
    store.audit(user["user_id"], "login", "workspace", {"method": "google"}, user["branch_id"])
    return user, None


def demo_google_accounts():
    """Seeded workspace emails for the demo Google chooser (Super Admin is not offered)."""
    with store.connect() as conn:
        rows = conn.execute("SELECT u.email, u.display_name, u.role_id, b.name AS branch FROM users u LEFT JOIN "
                            "branches b ON b.branch_id = u.branch_id WHERE u.is_active = 1 AND u.role_id != "
                            "'super_admin' AND u.created_by = 'system' ORDER BY u.role_id, u.user_id").fetchall()
    return [dict(r) for r in rows]


if __name__ == "__main__":
    import os
    import tempfile
    from pathlib import Path

    os.environ["RIPPLE_DB"] = str(Path(tempfile.mkdtemp()) / "auth.db")
    store.init_db()
    for ident, pw, portal in [("east.admin@deport.in", "Admin@123", "workspace"), (" dp102 ", "Partner@123", "workspace"),
                              ("superadmin@deport.in", "Super@123", "workspace"),
                              ("superadmin@deport.in", "Super@123", "super"), ("dp102", "nope", "workspace")]:
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
