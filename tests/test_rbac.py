"""3-level access: Super Admin, Branch Admin, Delivery Partner – hashing, sessions, OTP and branch scoping."""
import sqlite3
import time

import pytest

from modules import admin, auth, operations, partner_scope as scope, store

DEMO_PASSWORDS = ["Super@123", "Admin@123", "Partner@123"]


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("RIPPLE_DB", str(tmp_path / "rbac.db"))
    store.init_db()
    return store


def login(identifier, password, portal="workspace"):
    return auth.authenticate(identifier, password, portal)


@pytest.fixture()
def boss(db):
    return login("superadmin@ripple.in", "Super@123", "super")[0]


@pytest.fixture()
def east(db):
    return login("east.admin@ripple.in", "Admin@123")[0]


# ---------------------------------------------------------------- hashing + login
def test_passwords_are_hashed_never_plain(db):
    with store.connect() as conn:
        rows = [dict(r) for r in conn.execute("SELECT * FROM users")]
    assert len(rows) == 10
    for row in rows:
        values = " ".join(str(v) for v in row.values())
        assert not any(pw in values for pw in DEMO_PASSWORDS)
        assert len(row["password_hash"]) == 64 and len(row["salt"]) == 32
    assert len({r["salt"] for r in rows}) == len(rows)


def test_correct_and_wrong_password(db):
    assert login("east.admin@ripple.in", "Admin@123")[0]["role"] == "branch_admin"
    assert login("east.admin@ripple.in", "admin@123") == (None, auth.MESSAGES["bad_credentials"])
    assert login("nobody@ripple.in", "Admin@123") == (None, auth.MESSAGES["bad_credentials"])


@pytest.mark.parametrize("identifier", ["DP102", "dp102", "  Dp102 ", "dp102@ripple.in", " DP102@Ripple.in "])
def test_login_by_email_or_partner_id(db, identifier):
    user, error = login(identifier, "Partner@123")
    assert error is None and user["dp_id"] == "DP102" and user["branch_id"] == "CBE-E"


def test_lockout_after_five_failures(db, monkeypatch):
    for _ in range(4):
        assert login("DP102", "wrong")[1] == auth.MESSAGES["bad_credentials"]
    assert login("DP102", "wrong")[1] == auth.MESSAGES["locked"]
    assert login("DP102", "Partner@123")[1] == auth.MESSAGES["locked"]      # even the right password waits
    later = time.time() + auth.LOCK_SECONDS + 1
    monkeypatch.setattr(auth.time, "time", lambda: later)
    assert login("DP102", "Partner@123")[0]["user_id"] == "DP102"


def test_super_admin_has_its_own_door(db):
    assert login("superadmin@ripple.in", "Super@123")[1] == auth.MESSAGES["use_super_portal"]
    assert login("superadmin@ripple.in", "Super@123", "super")[0]["role"] == "super_admin"
    assert login("east.admin@ripple.in", "Admin@123", "super")[1] == auth.MESSAGES["super_only"]
    assert login("DP102", "Partner@123", "super")[1] == auth.MESSAGES["super_only"]


def test_permissions(db, boss, east):
    partner = login("DP102", "Partner@123")[0]
    assert auth.has_permission(boss, "manage_branches") and not auth.has_permission(boss, "approve_recovery")
    assert auth.has_permission(east, "approve_recovery") and not auth.has_permission(east, "manage_branches")
    assert auth.has_permission(partner, "report_issue") and not auth.has_permission(partner, "view_branch_ops")
    assert auth.branch_scope(boss) is None and auth.branch_scope(east) == "CBE-E"


# ---------------------------------------------------------------- sessions
def test_sessions_remember_me_and_revoke(db, monkeypatch):
    short, long = auth.create_session("DP102"), auth.create_session("DP102", remember_me=True)
    assert auth.validate_session(short)["user_id"] == auth.validate_session(long)["user_id"] == "DP102"
    with store.connect() as conn:
        assert not conn.execute("SELECT 1 FROM sessions WHERE token_hash = ?", (short,)).fetchone()  # hash only
    in_two_days = time.time() + 2 * 86400
    monkeypatch.setattr(auth.time, "time", lambda: in_two_days)
    assert auth.validate_session(short) is None            # 8-hour session expired
    assert auth.validate_session(long)["dp_id"] == "DP102"  # remember-me lasts 7 days
    auth.revoke_session(long)
    assert auth.validate_session(long) is None


# ---------------------------------------------------------------- OTP + forgot password
def test_otp_login_is_single_use(db):
    code, message, ok = auth.request_otp("dp102@ripple.in", "login")
    assert ok and code and len(code) == 6 and "…0002" in message
    with store.connect() as conn:
        assert all(code not in str(dict(r)) for r in conn.execute("SELECT * FROM otp_codes"))  # hashed
    assert auth.verify_otp("DP102", code, "login")[0]["user_id"] == "DP102"
    assert auth.verify_otp("DP102", code, "login")[0] is None


def test_otp_expires_and_limits_attempts(db, monkeypatch):
    code, _, _ = auth.request_otp("DP102", "login")
    for _ in range(auth.OTP_TRIES):
        assert auth.verify_otp("DP102", "000000" if code != "000000" else "111111", "login")[0] is None
    assert auth.verify_otp("DP102", code, "login")[0] is None  # burned after 3 wrong tries
    code, _, _ = auth.request_otp("DP102", "login")
    later = time.time() + auth.OTP_MINUTES * 60 + 1
    monkeypatch.setattr(auth.time, "time", lambda: later)
    assert auth.verify_otp("DP102", code, "login")[0] is None


def test_forgot_password(db):
    code, _, ok = auth.request_otp("east.admin@ripple.in", "reset")
    assert ok
    assert auth.reset_password_with_otp("east.admin@ripple.in", code, "short") == (False, auth.MESSAGES["weak_password"])
    assert auth.reset_password_with_otp("east.admin@ripple.in", code, "NewPass2026") == (True, "Password reset successful")
    assert login("east.admin@ripple.in", "Admin@123")[0] is None
    assert login("east.admin@ripple.in", "NewPass2026")[0]["user_id"] == "east.admin"
    assert auth.reset_password_with_otp("east.admin@ripple.in", code, "Again2026x")[0] is False  # code used


# ---------------------------------------------------------------- Super Admin
def test_super_admin_creates_branch_and_admin(db, boss):
    branch = admin.create_branch(boss, "Coimbatore West – Vadavalli", "Coimbatore", "Vadavalli", "Thondamuthur Road")
    admin.create_branch_admin(boss, "Kavya Nair", "west.admin@ripple.in", "+91 90000 10004", branch, "Welcome@2026")
    west = login("west.admin@ripple.in", "Welcome@2026")[0]
    assert west["role"] == "branch_admin" and west["branch_id"] == branch
    assert store.partners_df(branch).empty and operations.kpis(branch)["deliveries"] == 0   # empty ops
    assert store.list_issues(branch_id=branch) == []


def test_branch_admin_cannot_manage_branches_or_admins(db, east):
    with pytest.raises(PermissionError):
        admin.create_branch(east, "X", "Coimbatore", "X")
    with pytest.raises(PermissionError):
        admin.create_branch_admin(east, "Y", "y@ripple.in", "", "CBE-E", "Welcome@2026")


# ---------------------------------------------------------------- branch scoping
def test_branch_admin_sees_only_own_branch(db, east):
    branch = auth.branch_scope(east)
    assert set(store.partners_df(branch)["partner_id"]) == {"DP101", "DP102", "DP103", "DP106"}
    assert set(store.deliveries_df(branch_id=branch)["branch_id"]) == {"CBE-E"}
    central_issue = scope.report_issue("DP104", "CBE-C", scope.preview_issue(
        "DP104", "CBE-C", text="Mettupalayam road accident 1 hour")["problem"])
    assert store.get_issue(central_issue, branch) is None
    assert all(i["branch_id"] == "CBE-E" for i in store.list_issues(branch_id=branch))
    with pytest.raises(PermissionError):
        operations.accept(central_issue, "Divya", branch_id=branch)
    with pytest.raises(PermissionError):
        store.update_delivery("D19", branch_id=branch, status="delivered")    # a Central delivery


def test_branch_admin_adds_partner_who_sees_only_own_data(db, east):
    dp_id, temp_password = admin.add_partner(east, "Ravi", "+91 90000 20007", "ravi@ripple.in", "V9", ["R9", "R1"])
    ravi = login(dp_id, temp_password)[0]
    assert ravi["dp_id"] == dp_id and ravi["branch_id"] == "CBE-E"
    assert scope.get_partner_deliveries(dp_id, "CBE-E").empty
    with pytest.raises(PermissionError):
        scope.mark_delivered(dp_id, "CBE-E", "D07")                 # Karthik's delivery
    with pytest.raises(PermissionError):
        scope.mark_delivered("DP102", "CBE-E", "D25")               # Arun's (South) delivery
    with pytest.raises(PermissionError):
        admin.add_partner(east, "Z", "+91 1", "", "V7", [])         # V7 belongs to Central
    store.init_db()                                                 # app restart keeps the new partner
    assert dp_id in set(store.partners_df("CBE-E")["partner_id"])


@pytest.mark.parametrize("who, password", [("east.admin@ripple.in", "Admin@123"), ("DP102", "Partner@123")])
def test_deactivated_accounts_cannot_sign_in(db, boss, east, who, password):
    token = auth.create_session(login(who, password)[0]["user_id"])
    if who.startswith("east"):
        admin.set_user_active(boss, "east.admin", False)
    else:
        admin.set_user_active(east, "DP102", False)
    assert login(who, password)[1] == auth.MESSAGES["inactive"]
    assert auth.validate_session(token) is None


def test_deactivated_branch_blocks_its_people(db, boss):
    token = auth.create_session("DP105")
    admin.set_branch_active(boss, "CBE-S", False)
    assert login("south.admin@ripple.in", "Admin@123")[1] == auth.MESSAGES["branch_inactive"]
    assert login("DP105", "Partner@123")[1] == auth.MESSAGES["branch_inactive"]
    assert auth.validate_session(token) is None
    assert login("DP102", "Partner@123")[0]  # other branches keep working


def test_demo_flow_stays_inside_the_branch(db, east):
    seen = scope.preview_issue("DP102", "CBE-E", text="Avinashi road la accident, full block, rendu mani neram")
    issue_id = scope.report_issue("DP102", "CBE-E", seen["problem"], transcript=seen["transcript"])
    assert operations.kpis("CBE-E")["at_risk"] >= 3 and operations.kpis("CBE-C")["at_risk"] == 0
    plan = store.get_issue(issue_id, "CBE-E")["plan"]
    assert {r["vehicle_id"] for r in plan["after"]} <= {"V1", "V2", "V3", "V6"}   # East vehicles only
    operations.accept(issue_id, east["display_name"], branch_id="CBE-E")
    assert store.deliveries_df().set_index("delivery_id").loc["D06", "vehicle_id"] == "V6"   # backup, same branch
    assert any("Avinashi" in m["text"] for m in scope.get_partner_notifications("DP102", "CBE-E"))
    assert store.list_issues(branch_id="CBE-C") == [] and operations.kpis("CBE-S")["deadlines_saved"] == 0


# ---------------------------------------------------------------- upgrade of an old database
def test_old_database_is_migrated_in_place(db, tmp_path):
    store.update_delivery("D01", status="delivered")
    path = store.db_path()
    conn = sqlite3.connect(path)
    for table in store.BRANCH_SCOPED:
        conn.execute(f"ALTER TABLE {table} DROP COLUMN branch_id")
    conn.execute("DROP TABLE users")
    conn.execute("CREATE TABLE users (user_id TEXT PRIMARY KEY, role TEXT, display_name TEXT, dp_id TEXT, "
                 "password_hash TEXT, salt TEXT, is_active INTEGER DEFAULT 1, last_login TEXT)")
    conn.execute("INSERT INTO users VALUES ('manager', 'manager', 'Operations Manager', NULL, 'x', 'y', 1, NULL)")
    conn.execute("DELETE FROM meta WHERE key = 'schema_version'")
    conn.commit()
    conn.close()

    store.init_db()
    assert store.deliveries_df().set_index("delivery_id").loc["D01", "status"] == "delivered"   # data kept
    assert set(store.partners_df("CBE-E")["partner_id"]) == {"DP101", "DP102", "DP103", "DP106"}
    assert login("east.admin@ripple.in", "Admin@123")[0]["branch_id"] == "CBE-E"
    assert login("manager", "ripple@123")[0] is None                                              # no duplicate role
    store.init_db()  # running again changes nothing
    assert store.partners_df()["branch_id"].notna().all()
