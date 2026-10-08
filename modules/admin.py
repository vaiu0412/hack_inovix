"""Super Admin and Branch Admin management. No Streamlit imports.

Every function takes the acting user (from the validated session) and checks permissions and
branch scope itself, so the UI and the API cannot bypass the rules:
- Super Admin: create/activate branches, create/activate branch admins, reset their passwords
- Branch Admin: add/activate delivery partners in THEIR OWN branch only (cannot create admins)
"""
import re
import secrets
import string

from modules import auth, store
from modules.security import hash_password


def generate_temp_password():
    """Readable temporary password that passes the strength rule, e.g. 'Rpl-kmtx-482'."""
    letters = "".join(secrets.choice(string.ascii_lowercase) for _ in range(4))
    digits = "".join(secrets.choice(string.digits) for _ in range(3))
    return f"Rpl-{letters}-{digits}"


def _require_super(actor):
    if not actor or actor["role"] != "super_admin":
        raise PermissionError("Super Admins only")


def _new_branch_id(conn, city, area):
    base = f"{city[:3]}-{re.sub(r'[^A-Za-z]', '', area)[:3]}".upper()
    branch_id, n = base, 2
    while conn.execute("SELECT 1 FROM branches WHERE branch_id = ?", (branch_id,)).fetchone():
        branch_id, n = f"{base}{n}", n + 1
    return branch_id


# ---------------------------------------------------------------- Super Admin
def create_branch(actor, name, city, area, address="", lat=None, lng=None):
    auth.require_permission(actor, "manage_branches")
    _require_super(actor)
    if not (name or "").strip() or not (city or "").strip() or not (area or "").strip():
        raise ValueError("Name, city and area are required")
    with store.connect() as conn:
        branch_id = _new_branch_id(conn, city.strip(), area.strip())
        conn.execute("INSERT INTO branches(branch_id, name, city, area, address, lat, lng, is_active, created_at) "
                     "VALUES (?,?,?,?,?,?,?,1,?)", (branch_id, name.strip(), city.strip(), area.strip(),
                                                    (address or "").strip(), lat, lng, store.now_iso()))
    store.audit(actor["user_id"], "branch_created", branch_id, {"name": name}, branch_id)
    return branch_id


def set_branch_active(actor, branch_id, active):
    auth.require_permission(actor, "manage_branches")
    with store.connect() as conn:
        if not conn.execute("UPDATE branches SET is_active = ? WHERE branch_id = ?", (int(active), branch_id)).rowcount:
            raise ValueError(f"Unknown branch {branch_id}")
    store.audit(actor["user_id"], "branch_activated" if active else "branch_deactivated", branch_id, branch_id=branch_id)


def branch_admins_df():
    return store._df("SELECT u.user_id, u.display_name, u.email, u.phone, u.branch_id, b.name AS branch, "
                     "u.is_active, u.last_login FROM users u LEFT JOIN branches b ON b.branch_id = u.branch_id "
                     "WHERE u.role_id = 'branch_admin' ORDER BY u.branch_id, u.display_name")


def create_branch_admin(actor, display_name, email, phone, branch_id, temp_password):
    auth.require_permission(actor, "manage_branch_admins")
    _require_super(actor)
    email = auth.normalize(email)
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise ValueError("Enter a valid email address")
    problem = auth.password_problem(temp_password)
    if problem:
        raise ValueError(problem)
    if not store.get_branch(branch_id):
        raise ValueError(f"Unknown branch {branch_id}")
    hash_hex, salt = hash_password(temp_password)
    user_id = email.split("@")[0]
    with store.connect() as conn:
        if conn.execute("SELECT 1 FROM users WHERE lower(email) = ? OR lower(user_id) = ?", (email, user_id)).fetchone():
            raise ValueError("An account with this email already exists")
        conn.execute("INSERT INTO users(user_id, email, phone, display_name, role_id, branch_id, password_hash, salt, "
                     "created_by, created_at) VALUES (?,?,?,?, 'branch_admin', ?,?,?,?,?)",
                     (user_id, email, phone, display_name.strip(), branch_id, hash_hex, salt, actor["user_id"],
                      store.now_iso()))
    store.audit(actor["user_id"], "branch_admin_created", user_id, {"branch": branch_id}, branch_id)
    return user_id


def set_user_active(actor, user_id, active):
    """Super Admin: any branch admin. Branch Admin: only partners of their own branch."""
    target = auth.get_user(user_id)
    if not target:
        raise ValueError(f"Unknown account {user_id}")
    if actor["role"] == "super_admin":
        if target["role"] != "branch_admin":
            raise PermissionError("Super Admins manage branch admin accounts here")
    elif actor["role"] == "branch_admin":
        if target["role"] != "partner" or target["branch_id"] != actor["branch_id"]:
            raise PermissionError("You can only manage delivery partners of your own branch")
    else:
        raise PermissionError("Not allowed")
    with store.connect() as conn:
        conn.execute("UPDATE users SET is_active = ? WHERE user_id = ?", (int(active), user_id))
        if not active:
            conn.execute("UPDATE sessions SET revoked = 1 WHERE user_id = ?", (user_id,))
    store.audit(actor["user_id"], "account_activated" if active else "account_deactivated", user_id,
                branch_id=target["branch_id"])


def reset_admin_password(actor, user_id, temp_password):
    auth.require_permission(actor, "manage_branch_admins")
    target = auth.get_user(user_id)
    if not target or target["role"] != "branch_admin":
        raise PermissionError("Only branch admin passwords can be reset here")
    auth.set_password(user_id, temp_password, actor_user_id=actor["user_id"])


# ---------------------------------------------------------------- Branch Admin
def free_vehicles(branch_id):
    """Vehicles of the branch nobody drives yet."""
    return store._df("SELECT v.vehicle_id, v.reg_no, v.type FROM vehicles v LEFT JOIN partners p "
                     "ON p.vehicle_id = v.vehicle_id WHERE v.branch_id = ? AND p.partner_id IS NULL "
                     "ORDER BY v.vehicle_id", (branch_id,))


def _next_dp_id(conn):
    numbers = [int(r[0][2:]) for r in conn.execute("SELECT partner_id FROM partners") if r[0][2:].isdigit()]
    return f"DP{max(numbers, default=100) + 1}"


def add_partner(actor, name, phone, email, vehicle_id, route_roads, shift_start="09:00", shift_end="18:00"):
    """Create a delivery partner in the actor's own branch. Returns (dp_id, temporary password)."""
    auth.require_permission(actor, "manage_partners")
    branch_id = actor["branch_id"]
    if actor["role"] != "branch_admin" or not branch_id:
        raise PermissionError("Only a branch admin can add delivery partners")
    if not (name or "").strip() or not (phone or "").strip():
        raise ValueError("Name and phone are required")
    if vehicle_id not in set(free_vehicles(branch_id)["vehicle_id"]):
        raise PermissionError("Choose a free vehicle of your own branch")
    email = auth.normalize(email) or None
    if email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise ValueError("Enter a valid email address")
    temp_password = generate_temp_password()
    hash_hex, salt = hash_password(temp_password)
    with store.connect() as conn:
        if email and conn.execute("SELECT 1 FROM users WHERE lower(email) = ?", (email,)).fetchone():
            raise ValueError("An account with this email already exists")
        dp_id = _next_dp_id(conn)
        conn.execute("INSERT INTO partners VALUES (?,?,?,?,?,?,?,?,?,?)",
                     (dp_id, name.strip(), phone.strip(), vehicle_id, shift_start, shift_end, "Tamil|English", 5.0,
                      "on_duty", branch_id))
        conn.execute("UPDATE vehicles SET status = 'active', route_roads = ? WHERE vehicle_id = ? AND branch_id = ?",
                     ("|".join(route_roads or []), vehicle_id, branch_id))
        conn.execute("INSERT INTO users(user_id, email, phone, display_name, role_id, branch_id, dp_id, password_hash, "
                     "salt, created_by, created_at) VALUES (?,?,?,?, 'partner', ?,?,?,?,?,?)",
                     (dp_id, email or f"{dp_id.lower()}@deport.in", phone.strip(), name.strip(), branch_id, dp_id,
                      hash_hex, salt, actor["user_id"], store.now_iso()))
        store._bump(conn)
    store.audit(actor["user_id"], "partner_created", dp_id, {"vehicle": vehicle_id}, branch_id)
    store.log_event("system", f"{name.strip()} ({dp_id}) joined the team", branch_id=branch_id)
    return dp_id, temp_password


def set_partner_email(actor, dp_id, email):
    """Branch Admin: set the email a partner signs in with (also used to match Google sign-in)."""
    if actor.get("role") != "branch_admin":
        raise PermissionError("Branch admins only")
    email = str(email or "").strip().lower()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[a-z]{2,}", email):
        raise ValueError("Enter a valid email.")
    with store.connect() as conn:
        target = conn.execute("SELECT user_id FROM users WHERE dp_id = ? AND branch_id = ? AND role_id = 'partner'",
                              (dp_id, actor["branch_id"])).fetchone()
        if target is None:
            raise PermissionError(f"{dp_id} is not a partner of your branch")
        taken = conn.execute("SELECT user_id FROM users WHERE lower(email) = ? AND user_id != ?",
                             (email, target["user_id"])).fetchone()
        if taken:
            raise ValueError("Email already used.")
        conn.execute("UPDATE users SET email = ? WHERE user_id = ?", (email, target["user_id"]))
    store.audit(actor["user_id"], "email_linked", dp_id, {"email": email}, actor["branch_id"])


def set_partner_active(actor, dp_id, active):
    set_user_active(actor, dp_id, active)


if __name__ == "__main__":
    import os
    import tempfile
    from pathlib import Path

    os.environ["RIPPLE_DB"] = str(Path(tempfile.mkdtemp()) / "admin.db")
    store.init_db()
    boss = auth.authenticate("superadmin@deport.in", "Super@123", "super")[0]
    west = create_branch(boss, "Coimbatore West – Vadavalli", "Coimbatore", "Vadavalli", "Thondamuthur Road")
    create_branch_admin(boss, "Kavya Nair", "west.admin@deport.in", "+91 90000 10004", west, "Welcome@1")
    west_admin = auth.authenticate("west.admin@deport.in", "Welcome@1")[0]
    print("new branch:", west, "| admin branch:", west_admin["branch_id"])
    east = auth.authenticate("east.admin@deport.in", "Admin@123")[0]
    dp_id, temp = add_partner(east, "Ravi", "+91 90000 20007", "", "V9", ["R9", "R1"])
    print("new partner:", dp_id, "| can log in:", bool(auth.authenticate(dp_id, temp)[0]))
    try:
        set_user_active(east, "DP104", False)  # Central branch partner
        raise AssertionError("cross-branch deactivation allowed")
    except PermissionError as error:
        print("blocked:", error)
    print("admin OK")
