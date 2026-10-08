"""Sign-in options: real Google (email -> existing active account only), Link Google, OTP by email,
Quick demo access – and no dead buttons when something isn't configured."""
import pytest
from streamlit.testing.v1 import AppTest

from modules import admin, auth, login_ui, mailer, store


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("RIPPLE_DB", str(tmp_path / "google.db"))
    monkeypatch.delenv("DEMO_MODE", raising=False)
    store.init_db()


def login_page():
    return AppTest.from_file("views/login.py", default_timeout=60).run()


# ---------------------------------------------------------------- email -> user mapping
def test_google_email_maps_to_an_existing_active_user(db):
    user, error = login_ui.handle_google("East.Admin@Deport.in")
    assert error is None and user["user_id"] == "east.admin" and user["branch_id"] == "CBE-E"
    assert login_ui.handle_google("stranger@gmail.com") == (None, "No DEPORT account for this email.")
    assert login_ui.handle_google("superadmin@deport.in") == (None, "No DEPORT account for this email.")
    east = auth.authenticate("east.admin@deport.in", "Admin@123")[0]
    admin.set_partner_active(east, "DP103", False)
    assert login_ui.handle_google("dp103@deport.in") == (None, auth.MESSAGES["inactive"])
    assert store.audit_df(50)["action"].eq("login").any()                  # Google sign-ins are audited


def test_link_google_email_for_a_partner(db):
    east = auth.authenticate("east.admin@deport.in", "Admin@123")[0]
    admin.set_partner_email(east, "DP102", "Karthik.Delivers@Gmail.com")
    user, _ = login_ui.handle_google("karthik.delivers@gmail.com")
    assert user["dp_id"] == "DP102"
    with pytest.raises(ValueError, match="valid email"):
        admin.set_partner_email(east, "DP102", "not-an-email")
    with pytest.raises(ValueError, match="already used"):
        admin.set_partner_email(east, "DP101", "karthik.delivers@gmail.com")
    with pytest.raises(PermissionError):
        admin.set_partner_email(east, "DP104", "priya@gmail.com")            # Central's partner


# ---------------------------------------------------------------- the sign-in page
def test_google_button_only_when_configured(db, monkeypatch):
    at = login_page()
    assert not [b for b in at.button if "Google" in (b.label or "")]        # hidden, not a dead button
    monkeypatch.setattr(login_ui, "google_configured", lambda: True)
    assert [b for b in login_page().button if b.label == "Continue with Google"]


def test_google_return_signs_in_or_explains(db, monkeypatch):
    monkeypatch.setattr(login_ui, "google_configured", lambda: True)
    monkeypatch.setattr(login_ui, "google_email", lambda: "dp102@deport.in")
    at = login_page()
    assert at.session_state["role"] == "partner" and at.session_state["dp_id"] == "DP102"

    monkeypatch.setattr(login_ui, "google_email", lambda: "stranger@gmail.com")
    at = login_page()
    assert "authenticated" not in at.session_state
    assert at.error[0].value == "No DEPORT account for this email."
    assert [b for b in at.button if b.label == "Use another account"]


def test_quick_demo_access_only_in_demo_mode(db, monkeypatch):
    assert auth.demo_sign_in("partner") == (None, "Demo access is off.")
    monkeypatch.setenv("DEMO_MODE", "true")
    at = login_page()
    chips = {b.label for b in at.button if (b.key or "").startswith("demo_")}
    assert chips == {"Branch Admin", "Delivery Partner (DP102)"}             # Super Admin only on /console
    [chip] = [b for b in at.button if b.label == "Branch Admin"]
    chip.click().run()
    assert at.session_state["role"] == "branch_admin" and at.session_state["branch_id"] == "CBE-E"
    console = AppTest.from_file("views/console.py", default_timeout=60).run()
    assert [b.label for b in console.button if (b.key or "").startswith("demo_")] == ["Super Admin"]


# ---------------------------------------------------------------- OTP by email
def test_otp_by_email_when_smtp_is_set(db, monkeypatch):
    sent = []
    monkeypatch.setattr(mailer, "configured", lambda: True)
    monkeypatch.setattr(mailer, "send_code", lambda to, code, purpose: sent.append((to, code, purpose)) or True)
    code, message, ok = auth.request_otp("DP102", "login")
    assert ok and code is None and message == "Code sent to d***@deport.in."   # never shown on screen
    to, real_code, _ = sent[0]
    assert to == "dp102@deport.in" and auth.verify_otp("DP102", real_code, "login")[0]["dp_id"] == "DP102"
    monkeypatch.setattr(mailer, "send_code", lambda *args: False)
    assert auth.request_otp("DP102", "login") == (None, "Couldn't send the code. Try again.", False)


def test_demo_otp_without_smtp(db):
    code, message, ok = auth.request_otp("east.admin@deport.in", "reset")
    assert ok and len(code) == 6 and "Demo" in message
