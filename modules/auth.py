"""Login for managers and delivery partners. No Streamlit here, so the API uses it too.

- IDs are case-insensitive and whitespace-trimmed: "dp102", " DP102 " -> DP102
- passwords are checked against PBKDF2 hashes (modules/security.py)
- 5 failed attempts on an ID -> that ID is locked for 60 seconds
- a correct password with the wrong role is refused with a hint, a wrong password never
  reveals whether the account exists
"""
import time
from datetime import datetime

from modules import store
from modules.security import hash_password, verify_password

ROLES = ("manager", "partner")
MAX_FAILURES = 5
LOCK_SECONDS = 60
ROLE_NAMES = {"manager": "Manager", "partner": "Delivery Partner"}

MESSAGES = {
    "choose_role": "Please choose your role.",
    "missing": "Enter your ID and password.",
    "bad_credentials": "Incorrect ID or password.",
    "wrong_role": "This account belongs to a {actual} — choose the {actual} role.",
    "locked": "Too many attempts. Please wait {seconds} s and try again.",
    "inactive": "This account is disabled. Contact your operations manager.",
}
_DUMMY_HASH = hash_password("timing-equaliser")  # verify against something even for unknown IDs


def normalize(user_id):
    return " ".join(str(user_id or "").split()).lower()


def _public(row):
    return {k: row[k] for k in ("user_id", "role", "display_name", "dp_id", "last_login")}


def get_user(user_id):
    """Account details without the password hash, or None."""
    with store.connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE lower(user_id) = ?", (normalize(user_id),)).fetchone()
    return _public(row) if row else None


def _lock_seconds_left(conn, key):
    row = conn.execute("SELECT locked_until FROM login_attempts WHERE login_key = ?", (key,)).fetchone()
    return max(0, int(round((row["locked_until"] or 0) - time.time()))) if row else 0


def _register_failure(conn, key):
    """Count a failed attempt; the 5th one locks the ID. Returns seconds locked (0 if not)."""
    conn.execute("INSERT INTO login_attempts(login_key, failures) VALUES (?, 1) "
                 "ON CONFLICT(login_key) DO UPDATE SET failures = failures + 1", (key,))
    failures = conn.execute("SELECT failures FROM login_attempts WHERE login_key = ?", (key,)).fetchone()[0]
    if failures >= MAX_FAILURES:
        conn.execute("UPDATE login_attempts SET failures = 0, locked_until = ? WHERE login_key = ?",
                     (time.time() + LOCK_SECONDS, key))
        return LOCK_SECONDS
    return 0


def login(role, user_id, password):
    """Return (user, None) on success or (None, message) explaining what to fix."""
    if role not in ROLES:
        return None, MESSAGES["choose_role"]
    key = normalize(user_id)
    if not key or not password:
        return None, MESSAGES["missing"]
    with store.connect() as conn:
        wait = _lock_seconds_left(conn, key)
        if wait:
            return None, MESSAGES["locked"].format(seconds=wait)
        row = conn.execute("SELECT * FROM users WHERE lower(user_id) = ?", (key,)).fetchone()
        hash_hex, salt = (row["password_hash"], row["salt"]) if row else _DUMMY_HASH
        password_ok = verify_password(password, hash_hex, salt) and row is not None
        if not password_ok:
            locked = _register_failure(conn, key)
            return None, MESSAGES["locked"].format(seconds=locked) if locked else MESSAGES["bad_credentials"]
        if not row["is_active"]:
            return None, MESSAGES["inactive"]
        if row["role"] != role:
            return None, MESSAGES["wrong_role"].format(actual=ROLE_NAMES[row["role"]])
        conn.execute("DELETE FROM login_attempts WHERE login_key = ?", (key,))
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        conn.execute("UPDATE users SET last_login = ? WHERE user_id = ?", (stamp, row["user_id"]))
        user = _public(row)
        user["last_login"] = stamp
    return user, None


def authenticate(role, user_id, password):
    """User dict when the role, ID and password are right; otherwise None."""
    user, _ = login(role, user_id, password)
    return user


def change_password(user_id, old_password, new_password):
    """Change a password after checking the old one. Returns True on success."""
    if len(new_password or "") < 8:
        raise ValueError("Use at least 8 characters")
    with store.connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE lower(user_id) = ?", (normalize(user_id),)).fetchone()
        if not row or not verify_password(old_password, row["password_hash"], row["salt"]):
            return False
        hash_hex, salt = hash_password(new_password)
        conn.execute("UPDATE users SET password_hash = ?, salt = ? WHERE user_id = ?", (hash_hex, salt, row["user_id"]))
    return True


if __name__ == "__main__":
    import os
    import tempfile
    from pathlib import Path

    os.environ["RIPPLE_DB"] = str(Path(tempfile.mkdtemp()) / "auth.db")
    store.init_db()
    print(login("manager", "Manager", "ripple@123")[0])
    print(login("partner", " dp102 ", "partner@123")[0])
    print(login("partner", "manager", "ripple@123")[1])
    print(login("manager", "manager", "nope")[1])
    print("auth OK")
