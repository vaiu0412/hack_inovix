"""The whole demo, end to end, in the order judges see it (Phase 10 walk-through):

sign in → assign an order → the partner ignores it → ring (sound) → AI call (simulated without Twilio) → keypad 1
accepts → the admin's live feed shows it → an accident is reported → predicted delays → optimised plan → accept →
the partner is told → the customer's tracking page shows the new ETA → analytics show it.
Runs on SQLite, and on PostgreSQL with TEST_DATABASE_URL."""
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from streamlit.testing.v1 import AppTest

from api.main import app
from modules import analytics, assign, auth, escalation, operations, predict, store
from modules import partner_scope as scope

T0 = datetime(2026, 10, 9, 10, 0, 0)


@pytest.fixture()
def demo(tmp_path, monkeypatch):
    monkeypatch.setenv("RIPPLE_DB", str(tmp_path / "full-demo.db"))
    clock = {"now": T0}
    monkeypatch.setattr(escalation, "now", lambda: clock["now"])
    with TestClient(app) as client:
        yield client, clock


def login(client, identifier, password):
    reply = client.post("/login", json={"identifier": identifier, "password": password})
    assert reply.status_code == 200, reply.text
    return {"Authorization": f"Bearer {reply.json()['token']}"}


def tracking_text(delivery_id):
    page = AppTest.from_file("views/track.py", default_timeout=60)
    page.query_params["code"] = store.track_code(delivery_id)
    page.run()
    assert not page.exception
    return " ".join(m.value for m in page.markdown)


def test_the_whole_demo(demo):
    client, clock = demo
    # 1. sign in (API, JWT) – the admin's and the partner's views
    east = login(client, "east.admin@deport.in", "Admin@123")
    karthik = login(client, "DP102", "Partner@123")
    admin = auth.authenticate("east.admin@deport.in", "Admin@123")[0]
    start = store.last_change_id()

    # 2. assign an urgent order to Karthik
    order_id, _ = assign.create_order(admin, "City Clinic", "+91 90000 30002", "Peelamedu", "Medicine", "medical",
                                      "16:00", "small")
    assign.assign(admin, order_id, "DP102")
    assert [o["delivery_id"] for o in client.get("/me/offers", headers=karthik).json()] == [order_id]

    # 3. he doesn't answer: ring at 1 min (the alarm sound), AI call at 3 min (simulated – no Twilio keys)
    clock["now"] = T0 + timedelta(minutes=1)
    assert escalation.tick("CBE-E") == [(order_id, "ringing")]
    clock["now"] = T0 + timedelta(minutes=3)
    assert escalation.tick("CBE-E") == [(order_id, "calling")]
    timeline = [s["result"] for s in escalation.history(order_id, "CBE-E")]
    assert timeline[:3] == ["Sent", "Ringing in the app", timeline[2]] and "Demo mode" in timeline[2]

    # 4. he presses 1 on the call -> accepted, and the admin's live feed has every step
    escalation.respond_by_call(order_id, "DP102", "accept")
    assert store.deliveries_df().set_index("delivery_id").loc[order_id, "status"] == "accepted"
    feed = store.changes_since(start, branch_id="CBE-E")
    results = [c["data"].get("result") for c in feed if c["kind"] == "offer" and c["data"]["delivery_id"] == order_id]
    assert results[0] == "Sent" and results[-1] == "Accepted"
    assert client.get("/escalations", headers=east).status_code == 200

    # 5. disruption: an accident on Avinashi Road, reported by voice/text from the road
    seen = scope.preview_issue("DP102", "CBE-E", text="avinasi rd la accident, full block, rendu mani neram aagum")
    issue_id = scope.report_issue("DP102", "CBE-E", seen["problem"], transcript=seen["transcript"])
    alert = store.get_issue(issue_id)
    assert alert["status"] == "analysed" and alert["plan"]["summary"]["affected_deliveries"] >= 9

    # 6. predicted delays for the branch's open stops (delay model) before anything changes
    likely = predict.for_branch("CBE-E")
    assert likely and all(0 <= p["p_late"] <= 1 for p in likely.values())

    # 7. the optimised plan (OR-Tools) is ready next to the rule-based one; the admin applies it (API)
    optimised = alert["plan"]["optimised"]
    assert optimised["status"] == "ok" and optimised["routes"]
    before = store.deliveries_df().set_index("delivery_id")["planned_eta"].to_dict()
    assert client.post(f"/issues/{issue_id}/accept", headers=east, params={"choice": "best"}).status_code == 422
    reply = client.post(f"/issues/{issue_id}/accept", headers=east, params={"choice": "optimised"})
    assert reply.status_code == 200, reply.text
    assert store.get_issue(issue_id)["plan"]["chosen"] == "optimised"

    # 8. partners are told (inbox + their live feed)
    inbox = client.get("/me/messages", headers=karthik).json()
    assert any("avoid" in m["text"].lower() or "route" in m["text"].lower() or "new" in m["text"].lower()
               for m in inbox)
    assert any(c["kind"] == "message" for c in store.changes_since(start, dp_id="DP102"))

    # 9. a customer whose ETA moved sees the new time on the public tracking page (no sign-in)
    after = store.deliveries_df().set_index("delivery_id")
    moved = [d for d, eta in before.items() if isinstance(eta, str) and isinstance(after.loc[d, "planned_eta"], str)
             and after.loc[d, "planned_eta"] != eta and after.loc[d, "status"] not in ("delivered", "failed")]
    assert moved, "the optimised plan changed someone's ETA"
    customer = moved[0]
    assert f"Expected by {after.loc[customer, 'planned_eta']}" in tracking_text(customer)

    # 10. analytics: the disruption is on the heatmap and the partner table is live
    roads = store.snapshot("CBE-E")["roads"]
    assert len(analytics.disruption_points("CBE-E", roads)) == 1
    perf = analytics.partner_performance("CBE-E").set_index("partner_id")
    assert perf.loc["DP102", "answered"] >= 1 and perf.loc["DP102", "answer_min"] >= 0
    assert operations.kpis("CBE-E")["deadlines_saved"] >= 1
