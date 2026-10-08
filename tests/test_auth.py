"""Login, password storage and lockout."""
import time

import pytest

from modules import auth, store


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("RIPPLE_DB", str(tmp_path / "auth.db"))
    store.init_db()
    return store


def test_manager_login_works(db):
    user, error = auth.login("manager", "manager", "ripple@123")
    assert error is None and user["role"] == "manager" and user["display_name"] == "Operations Manager"
    assert auth.get_user("manager")["last_login"]


def test_wrong_password_fails(db):
    user, error = auth.login("manager", "manager", "wrong-password")
    assert user is None and error == auth.MESSAGES["bad_credentials"]
    assert auth.authenticate("partner", "DP102", "ripple@123") is None


def test_manager_credentials_with_partner_role_fail(db):
    user, error = auth.login("partner", "manager", "ripple@123")
    assert user is None and "belongs to a Manager" in error
    user, error = auth.login("manager", "DP102", "partner@123")
    assert user is None and "belongs to a Delivery Partner" in error


def test_role_must_be_chosen(db):
    assert auth.login(None, "manager", "ripple@123") == (None, auth.MESSAGES["choose_role"])


@pytest.mark.parametrize("typed", ["DP102", "dp102", " DP102 ", "  dP102"])
def test_partner_id_is_case_and_space_insensitive(db, typed):
    user = auth.authenticate("partner", typed, "partner@123")
    assert user and user["user_id"] == "DP102" and user["dp_id"] == "DP102" and user["display_name"] == "Karthik"


def test_every_partner_has_a_login(db):
    for partner_id in store.partners_df()["partner_id"]:
        assert auth.authenticate("partner", partner_id, "partner@123")["dp_id"] == partner_id


def test_lockout_after_five_failures(db, monkeypatch):
    for _ in range(4):
        assert auth.login("partner", "DP102", "bad")[1] == auth.MESSAGES["bad_credentials"]
    user, error = auth.login("partner", "DP102", "bad")           # 5th failure locks
    assert user is None and "Too many attempts" in error
    user, error = auth.login("partner", "DP102", "partner@123")   # even the right password waits
    assert user is None and "Too many attempts" in error
    later = time.time() + auth.LOCK_SECONDS + 1
    monkeypatch.setattr(auth.time, "time", lambda: later)
    assert auth.authenticate("partner", "DP102", "partner@123")["user_id"] == "DP102"


def test_passwords_are_stored_hashed(db):
    with store.connect() as conn:
        rows = [dict(r) for r in conn.execute("SELECT * FROM users")]
    assert len(rows) == 7
    for row in rows:
        values = " ".join(str(v) for v in row.values())
        assert "ripple@123" not in values and "partner@123" not in values
        assert len(row["password_hash"]) == 64 and len(row["salt"]) == 32
    assert len({row["salt"] for row in rows}) == 7  # every account has its own salt


def test_reset_recreates_accounts(db):
    assert auth.change_password("DP102", "partner@123", "new-secret-1")
    assert auth.authenticate("partner", "DP102", "partner@123") is None
    store.reset_demo()
    assert auth.authenticate("partner", "DP102", "partner@123")["user_id"] == "DP102"


def test_old_database_gets_accounts_without_losing_data(db):
    store.update_delivery("D01", status="delivered")
    with store.connect() as conn:
        conn.execute("DELETE FROM users")
    store.init_db()
    assert auth.authenticate("manager", "manager", "ripple@123")
    assert store.deliveries_df().set_index("delivery_id").loc["D01", "status"] == "delivered"
