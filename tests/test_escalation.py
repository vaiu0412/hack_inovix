"""Order offers: Sent -> Seen -> Ringing -> Calling -> No response (fake clock), answers in the app or on the call,
the Twilio webhooks (signed) and Demo mode without keys."""
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from api.main import app
from modules import assign, auth, escalation, store
from modules import partner_scope as scope
from services import voice_call

T0 = datetime(2026, 10, 9, 10, 0, 0)
BASE = "https://deport.example"
TOKEN = "test-auth-token"


@pytest.fixture()
def east(tmp_path, monkeypatch):
    monkeypatch.setenv("RIPPLE_DB", str(tmp_path / "escalation.db"))
    store.init_db()
    clock = {"now": T0}
    monkeypatch.setattr(escalation, "now", lambda: clock["now"])
    return auth.authenticate("east.admin@deport.in", "Admin@123")[0], clock


def at(clock, minutes):
    clock["now"] = T0 + timedelta(minutes=minutes)
    return escalation.tick("CBE-E")


def new_offer(admin, priority="medical", dp_id="DP102"):
    order_id, _ = assign.create_order(admin, "City Clinic", "+91 90000 30002", "Peelamedu", "Medicine", priority,
                                      "16:00", "small")
    assign.assign(admin, order_id, dp_id)
    return order_id


def offer_of(order_id):
    row = store.deliveries_df().set_index("delivery_id").loc[order_id]
    return row["offer_status"], int(row["escalation_level"])


def steps(order_id):
    return [h["result"] for h in escalation.history(order_id, "CBE-E")]


def test_unanswered_offer_rings_calls_and_alerts_the_admin_on_time(east):
    admin, clock = east
    order_id = new_offer(admin)
    assert offer_of(order_id) == ("sent", 0) and steps(order_id) == ["Sent"]
    assert at(clock, 0.5) == []
    assert at(clock, 1) == [(order_id, "ringing")] and offer_of(order_id) == ("ringing", 1)
    assert at(clock, 2.9) == []
    assert at(clock, 3) == [(order_id, "calling")] and offer_of(order_id) == ("calling", 2)
    assert "Demo mode" in steps(order_id)[-1]                                  # no keys: simulated call
    assert at(clock, 5) == [(order_id, "no_response")] and offer_of(order_id) == ("no_response", 3)
    assert at(clock, 6) == [] and len(steps(order_id)) == 4                    # nothing happens twice
    alert = next(a for a in escalation.admin_alerts("CBE-E") if a["delivery_id"] == order_id)
    assert alert["last_dp"] == "DP102" and alert["suggestion"]["partner_id"] != "DP102"


def test_a_late_timer_catches_up_in_order(east):
    admin, clock = east
    order_id = new_offer(admin)
    assert at(clock, 7) == [(order_id, "ringing"), (order_id, "calling"), (order_id, "no_response")]
    escalation.mark_seen("DP102", "CBE-E", [order_id])                           # opened late: logged, stage kept
    assert offer_of(order_id)[0] == "no_response" and steps(order_id)[-1] == "Seen"


def test_low_priority_orders_ring_but_are_not_called(east):
    admin, clock = east
    order_id = new_offer(admin, priority="standard")
    at(clock, 1)
    assert at(clock, 3) == [(order_id, "ringing")] and offer_of(order_id) == ("ringing", 2)
    assert steps(order_id)[-1] == "Call skipped (standard priority)"
    assert at(clock, 5) == [(order_id, "no_response")]


def test_seen_then_accepted_in_the_app_stops_the_escalation(east):
    admin, clock = east
    order_id = new_offer(admin)
    assert escalation.mark_seen("DP102", "CBE-E", [order_id]) == 1 and offer_of(order_id)[0] == "seen"
    assert escalation.mark_seen("DP102", "CBE-E", [order_id]) == 0                 # only the first view counts
    at(clock, 1)
    scope.advance_delivery("DP102", "CBE-E", order_id, "accepted")            # the existing Accept step button
    assert offer_of(order_id)[0] == "accepted" and steps(order_id)[-1] == "Accepted"
    assert at(clock, 10) == [] and escalation.admin_alerts("CBE-E") == []
    second = new_offer(admin)
    assert escalation.respond("DP102", "CBE-E", second, True) == "accepted"
    with pytest.raises(ValueError, match="already accepted"):
        escalation.respond("DP102", "CBE-E", second, True)


def test_cant_take_puts_the_order_back_and_suggests_someone_else(east):
    admin, clock = east
    order_id = new_offer(admin)
    escalation.respond("DP102", "CBE-E", order_id, False, reason="Too far")
    order = store.deliveries_df().set_index("delivery_id").loc[order_id]
    assert order["status"] == "unassigned" and order["offer_status"] == "declined" and order["vehicle_id"] is None
    assert order_id in set(assign.unassigned_orders("CBE-E")["delivery_id"])
    alert = escalation.admin_alerts("CBE-E")[0]
    best = alert["suggestion"]["partner_id"]
    assert alert["delivery_id"] == order_id and best != "DP102" and "Too far" in alert["last_result"]
    assign.reassign(admin, order_id, best, reason="Declined by DP102")
    assert offer_of(order_id) == ("sent", 0) and escalation.admin_alerts("CBE-E") == []


def test_partners_answer_only_their_own_offers(east):
    admin, _ = east
    order_id = new_offer(admin)
    with pytest.raises(PermissionError):
        escalation.respond("DP101", "CBE-E", order_id, True)
    with pytest.raises(PermissionError):
        escalation.mark_seen("DP105", "CBE-S", [order_id])
    assert escalation.partner_offers("DP101", "CBE-E") == []
    assert [o["delivery_id"] for o in escalation.partner_offers("DP102", "CBE-E")] == [order_id]


def test_times_come_from_the_settings_table(east):
    admin, clock = east
    with pytest.raises(PermissionError):
        escalation.save_settings(admin, 2, 4, 6, ["standard"])
    boss = auth.authenticate("superadmin@deport.in", "Super@123", "super")[0]
    with pytest.raises(ValueError):
        escalation.save_settings(boss, 4, 2, 6, ["standard"])
    escalation.save_settings(boss, 2, 4, 6, ["standard", "express"])
    assert escalation.settings()["no_call_priorities"] == "express,standard"
    order_id = new_offer(admin)
    assert at(clock, 1.5) == [] and at(clock, 2) == [(order_id, "ringing")]


def test_twilio_is_used_when_its_keys_are_set(east, monkeypatch):
    admin, clock = east
    for key, value in {"TWILIO_ACCOUNT_SID": "AC123", "TWILIO_AUTH_TOKEN": TOKEN, "TWILIO_FROM_NUMBER": "+15550001111",
                       "PUBLIC_BASE_URL": BASE}.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(voice_call, "offline", lambda: False)
    sent = {}

    class Reply:
        def raise_for_status(self):
            pass

        def json(self):
            return {"sid": "CA999"}

    def fake_post(url, auth, data, timeout):
        sent.update(url=url, data=data)
        return Reply()

    monkeypatch.setattr(voice_call.httpx, "post", fake_post)
    assert voice_call.provider() == "twilio"
    order_id = new_offer(admin)
    at(clock, 3)
    assert sent["url"].endswith("/Accounts/AC123/Calls.json") and sent["data"]["To"] == "+91 90000 20002"
    assert sent["data"]["Url"] == f"{BASE}/twilio/voice?delivery_id={order_id}&dp_id=DP102"
    assert steps(order_id)[-1] == "Calling +91 90000 20002 via Twilio"


def test_no_keys_means_demo_mode():
    assert voice_call.provider() == "demo"
    assert voice_call.place_call("+91 1", "D1", "DP1", "hi")["demo"] is True


def test_keypad_and_speech_answers():
    assert voice_call.read_answer("1") == "accept" and voice_call.read_answer("2") == "decline"
    assert voice_call.read_answer("", "Yes sure") == "accept"
    assert voice_call.read_answer("", "no I cannot") == "decline"
    assert voice_call.read_answer("9", "hmm") is None


# ---------------------------------------------------------------- webhooks
@pytest.fixture()
def webhook(east, monkeypatch):
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", TOKEN)
    monkeypatch.setenv("PUBLIC_BASE_URL", BASE)
    with TestClient(app) as client:
        yield client, east[0]


def twilio_post(client, path, delivery_id, form, sign=True):
    query = f"delivery_id={delivery_id}&dp_id=DP102"
    signature = voice_call.signature(f"{BASE}{path}?{query}", form, TOKEN) if sign else "forged"
    return client.post(f"{path}?{query}", data=form, headers={"X-Twilio-Signature": signature})


def test_call_script_and_keypad_1_accepts(webhook):
    client, admin = webhook
    order_id = new_offer(admin)
    script = twilio_post(client, "/twilio/voice", order_id, {"CallSid": "CA1"})
    assert script.status_code == 200 and script.headers["content-type"].startswith("application/xml")
    assert "<Gather" in script.text and "Press 1 to accept" in script.text and "City Clinic" in script.text
    reply = twilio_post(client, "/twilio/gather", order_id, {"CallSid": "CA1", "Digits": "1"})
    assert "The order is yours" in reply.text
    assert offer_of(order_id)[0] == "accepted" and steps(order_id)[-1] == "Accepted"


def test_keypad_2_declines_and_the_admin_gets_a_suggestion(webhook):
    client, admin = webhook
    order_id = new_offer(admin)
    reply = twilio_post(client, "/twilio/gather", order_id, {"CallSid": "CA2", "Digits": "2"})
    assert "someone else" in reply.text and offer_of(order_id)[0] == "declined"
    assert escalation.admin_alerts("CBE-E")[0]["suggestion"]["partner_id"] != "DP102"


def test_webhooks_need_a_valid_twilio_signature(webhook):
    client, admin = webhook
    order_id = new_offer(admin)
    assert twilio_post(client, "/twilio/gather", order_id, {"Digits": "1"}, sign=False).status_code == 403
    tampered = voice_call.signature(f"{BASE}/twilio/gather?delivery_id={order_id}&dp_id=DP102", {"Digits": "2"},
                                    TOKEN)
    forged = client.post(f"/twilio/gather?delivery_id={order_id}&dp_id=DP102", data={"Digits": "1"},
                         headers={"X-Twilio-Signature": tampered})
    assert forged.status_code == 403 and offer_of(order_id)[0] == "sent"


def test_partner_api_lists_and_declines_offers(webhook):
    client, admin = webhook
    order_id = new_offer(admin)
    reply = client.post("/login", json={"identifier": "DP102", "password": "Partner@123"})
    headers = {"Authorization": f"Bearer {reply.json()['token']}"}
    assert [o["delivery_id"] for o in client.get("/me/offers", headers=headers).json()] == [order_id]
    assert client.post(f"/me/deliveries/{order_id}/decline", json={"reason": "Vehicle issue"},
                       headers=headers).json()["offer"] == "declined"
    east = client.post("/login", json={"identifier": "east.admin@deport.in", "password": "Admin@123"}).json()
    alerts = client.get("/escalations", headers={"Authorization": f"Bearer {east['token']}"}).json()
    assert alerts[0]["delivery_id"] == order_id and "Vehicle issue" in alerts[0]["last_result"]
