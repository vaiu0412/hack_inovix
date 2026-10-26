"""Customer portal and one-time codes by email or SMS: accounts from the number/email on orders, only own orders,
Twilio Verify / Twilio SMS / email (faked), no codes on screen outside demo mode, rate limits, the API and the web
sign-in. Tests run offline, so codes are shown (DEMO) unless a test switches that off."""
import pytest
from fastapi.testclient import TestClient
from streamlit.testing.v1 import AppTest

from api.main import app
from modules import assign, auth, customers, guards, mailer, parser, store
from services import sms

D07_PHONE = "90000 10007"  # Ukkadam Wholesale Traders (D07, East)


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("RIPPLE_DB", str(tmp_path / "customers.db"))
    store.init_db()


def sign_in(identifier, channel=None):
    code, message, ok = auth.request_otp(identifier, "login", channel=channel)
    assert ok, message
    user, error = auth.verify_otp(identifier, code, "login")
    assert error is None, error
    return user


# ---------------------------------------------------------------- phone numbers
def test_phone_numbers_are_normalised():
    assert sms.normalize_phone("+91 90000 10007") == "+919000010007"
    assert sms.normalize_phone("9000010007") == "+919000010007"
    assert sms.normalize_phone("09000010007") == "+919000010007"
    assert sms.normalize_phone("0091 90000 10007") == "+919000010007"
    assert sms.normalize_phone("+1 (415) 555-0100") == "+14155550100"
    for not_a_phone in ("DP102", "dp102@deport.in", "", "12345"):
        assert sms.normalize_phone(not_a_phone) is None
    assert sms.mask("+919000010007") == "+91 ••••• •0007"


# ---------------------------------------------------------------- accounts + scope
def test_a_customer_account_is_made_only_for_numbers_on_orders(db):
    assert auth.request_otp("98765 43210", "login") == (None, auth.MESSAGES["no_orders"], False)  # no text sent
    user = sign_in(D07_PHONE)
    assert user["role"] == "customer" and user["user_id"] == "C919000010007"
    assert user["display_name"] == "Ukkadam Wholesale Traders" and user["branch_id"] is None
    assert customers.find("+91 90000 10007") == "C919000010007"
    assert auth.authenticate(D07_PHONE, "anything")[1] == auth.MESSAGES["use_code"]          # no passwords
    assert auth.request_otp(D07_PHONE, "reset")[1] == auth.MESSAGES["use_code"]


def test_customers_see_only_their_orders(db):
    user = sign_in(D07_PHONE)
    mine = customers.orders(user)
    assert [o["delivery_id"] for o in mine] == ["D07"]
    order = mine[0]
    assert order["stage"] == "On the way" and order["partner_first_name"] == "Karthik" and order["eta"]
    assert "phone" not in str(order).lower() and "customer_phone" not in order                 # no phone numbers
    assert customers.order(user, "D01") is None
    with pytest.raises(PermissionError):
        customers.orders(auth.get_user("DP102"))


def test_email_sign_in_after_an_order_with_email(db):
    admin = auth.authenticate("east.admin@deport.in", "Admin@123")[0]
    with pytest.raises(ValueError, match="Email"):
        assign.create_order(admin, "Asha", "+91 90000 55555", "Gandhipuram", "Parcel", "standard", "17:00", "small",
                            email="not-an-email")
    order_id, _ = assign.create_order(admin, "Asha", "+91 90000 55555", "Gandhipuram", "Parcel", "standard", "17:00",
                                      "small", email="Asha@Example.com")
    user = sign_in("asha@example.com")
    assert user["role"] == "customer" and user["phone"] == "+919000055555"                  # phone from the order
    assert [o["delivery_id"] for o in customers.orders(user)] == [order_id]
    assert sign_in("90000 55555")["user_id"] == user["user_id"]                             # same account by phone


def test_customer_sessions_have_no_branch_but_stay_valid(db):
    user = sign_in(D07_PHONE)
    token = auth.create_session(user["user_id"])
    assert auth.validate_session(token)["role"] == "customer"


# ---------------------------------------------------------------- channels
def test_twilio_verify_holds_the_code(db, monkeypatch):
    calls = []
    monkeypatch.setattr(sms, "provider", lambda: "twilio_verify")
    monkeypatch.setattr(sms, "start_verify", lambda phone, channel="sms": calls.append(("start", phone)) or True)
    monkeypatch.setattr(sms, "check_verify",
                        lambda phone, code: calls.append(("check", phone, code)) or code == "424242")
    code, message, ok = auth.request_otp(D07_PHONE, "login")
    assert ok and code is None and message == "Code sent to +91 ••••• •0007."
    with store.connect() as conn:
        assert conn.execute("SELECT code_hash FROM otp_codes ORDER BY id DESC").fetchone()[0] == auth.VERIFY_MARK
    assert auth.verify_otp(D07_PHONE, "111111", "login")[1] == auth.MESSAGES["otp_invalid"]
    assert auth.verify_otp(D07_PHONE, "424242", "login")[0]["role"] == "customer"
    assert calls[0] == ("start", "+919000010007") and calls[-1] == ("check", "+919000010007", "424242")


def test_twilio_sms_and_email_deliver_a_hashed_code(db, monkeypatch):
    texts, mails = [], []
    monkeypatch.setattr(sms, "provider", lambda: "twilio_sms")
    monkeypatch.setattr(sms, "send_text", lambda phone, text: texts.append((phone, text)) or True)
    code, message, ok = auth.request_otp("DP102", "login", channel="sms")                     # staff, by SMS
    assert ok and code is None and texts[0][0] == "+919000020002" and "Your DEPORT code is" in texts[0][1]
    sent = texts[0][1].split("is ")[1][:6]
    assert auth.verify_otp("DP102", sent, "login")[0]["dp_id"] == "DP102"
    assert auth.request_otp("+91 90000 20002", "login")[2]                                   # staff by mobile number
    assert texts[1][0] == "+919000020002"
    assert auth.verify_otp("+91 90000 20002", texts[1][1].split("is ")[1][:6], "login")[0]["dp_id"] == "DP102"

    monkeypatch.setattr(auth, "otp_by_email", lambda: True)
    monkeypatch.setattr(mailer, "send_code", lambda to, code, purpose: mails.append((to, code)) or True)
    code, message, ok = auth.request_otp("east.admin@deport.in", "login")
    assert ok and code is None and mails[0][0] == "east.admin@deport.in" and message.startswith("Code sent to e***")
    with store.connect() as conn:
        stored = [r[0] for r in conn.execute("SELECT code_hash FROM otp_codes")]
    assert mails[0][1] not in " ".join(stored)                                                 # only hashes kept


def test_no_codes_on_screen_on_a_real_site(db, monkeypatch):
    monkeypatch.setattr(parser, "offline", lambda: False)
    monkeypatch.setattr(sms, "offline", lambda: False)
    monkeypatch.delenv("DEMO_MODE", raising=False)
    monkeypatch.delenv("OTP_DEMO", raising=False)
    assert auth.request_otp(D07_PHONE, "login") == (None, auth.MESSAGES["not_set_up"], False)
    assert auth.request_otp("DP102", "login")[1] == auth.MESSAGES["not_set_up"]
    monkeypatch.setenv("OTP_DEMO", "true")                                                     # an explicit demo
    assert auth.request_otp(D07_PHONE, "login")[2] is True


def test_codes_are_rate_limited(db):
    for _ in range(auth.OTP_PER_10_MIN):
        assert auth.request_otp(D07_PHONE, "login")[2]
    assert auth.request_otp(D07_PHONE, "login") == (None, auth.MESSAGES["otp_rate"], False)


def test_a_code_works_once(db):
    code, _, _ = auth.request_otp(D07_PHONE, "login")
    assert auth.verify_otp(D07_PHONE, code, "login")[0]
    assert auth.verify_otp(D07_PHONE, code, "login")[1] == auth.MESSAGES["otp_invalid"]


# ---------------------------------------------------------------- API
@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("RIPPLE_DB", str(tmp_path / "customers-api.db"))
    with TestClient(app) as c:
        yield c


def test_customer_api(client):
    assert client.post("/otp/request", json={"identifier": "98765 43210"}).status_code == 404
    assert client.post("/otp/request", json={"identifier": D07_PHONE, "channel": "fax"}).status_code == 422
    sent = client.post("/otp/request", json={"identifier": D07_PHONE}).json()
    assert sent["ok"] and len(sent["demo_code"]) == 6
    assert client.post("/otp/verify", json={"identifier": D07_PHONE, "code": "000000"}).status_code == 401
    login = client.post("/otp/verify", json={"identifier": D07_PHONE, "code": sent["demo_code"]}).json()
    assert login["user"]["role"] == "customer"
    headers = {"Authorization": f"Bearer {login['token']}"}
    orders = client.get("/my/orders", headers=headers).json()
    assert [o["delivery_id"] for o in orders] == ["D07"] and orders[0]["track_url"].endswith(orders[0]["track_code"])
    assert client.get("/my/orders/D07", headers=headers).json()["stage"] == "On the way"
    assert client.get("/my/orders/D01", headers=headers).status_code == 404
    for path in ("/me", "/kpis", "/partners", "/branches"):
        assert client.get(path, headers=headers).status_code == 403                          # nothing else
    partner = client.post("/login", json={"identifier": "DP102", "password": "Partner@123"}).json()
    assert client.get("/my/orders", headers={"Authorization": f"Bearer {partner['token']}"}).status_code == 403
    boss = client.post("/otp/request", json={"identifier": "superadmin@deport.in"})
    assert boss.status_code == 404 and "console" not in boss.text.lower()                     # not advertised


# ---------------------------------------------------------------- web
def test_customer_signs_in_on_the_web_and_sees_their_orders(db):
    at = AppTest.from_file("app.py", default_timeout=90).run()
    [button] = [b for b in at.button if b.label == "Customer? Track your orders"]
    button.click().run()
    at.text_input(key="otp_id").set_value(D07_PHONE)
    [send] = [b for b in at.button if b.label == "Send code"]
    send.click().run()
    assert "DEMO" in " ".join(i.value for i in at.info)
    at.text_input(key="otp_code").set_value(at.session_state["otp_demo"])
    [verify] = [b for b in at.button if b.label == "Sign in"]
    verify.click().run()
    assert at.session_state["role"] == "customer"
    page = AppTest.from_file("app.py", default_timeout=90)
    for key in guards.SESSION_KEYS:
        if key in at.session_state:
            page.session_state[key] = at.session_state[key]
    page.run()
    assert not page.exception
    text = " ".join(m.value for m in page.markdown if not m.value.lstrip().startswith("<style>"))
    assert "DELIVERY D07" in text and "Hi Ukkadam" in text and "D01" not in text
    assert page.code and "/track?code=" in page.code[0].value
    denied = AppTest.from_file(guards.BRANCH_PAGES["command"], default_timeout=60)
    for key in guards.SESSION_KEYS:
        if key in at.session_state:
            denied.session_state[key] = at.session_state[key]
    assert denied.run().error[0].value.startswith("**Access denied**")
