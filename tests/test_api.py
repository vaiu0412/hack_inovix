"""The mobile API runs the same flow as the app: report -> plan -> accept -> everyone updated."""
import pytest
from fastapi.testclient import TestClient

from api.main import app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("RIPPLE_DB", str(tmp_path / "api.db"))
    with TestClient(app) as c:
        yield c


def test_partners_and_map(client):
    assert client.get("/health").json()["status"] == "ok"
    partners = client.get("/partners").json()
    assert len(partners) == 6 and partners[0]["name"] == "Murugan"
    detail = client.get("/partners/DP101").json()
    assert len(detail["stops"]) == 6 and detail["partner"]["vehicle_id"] == "V1"
    live = client.get("/map").json()
    assert len(live["partners"]) == 6 and len(live["deliveries"]) == 30 and len(live["roads"]) == 10
    assert client.get("/partners/P99").status_code == 404


def test_report_accept_and_inboxes(client):
    preview = client.post("/issues/preview", data={"partner_id": "DP101", "text": "avinasi rd accident 2 hours"}).json()
    assert preview["problem"]["road_id"] == "R1"
    issue = client.post("/issues", json={"partner_id": "DP101", "text": "avinasi rd accident, full block, 2 hours"})
    assert issue.status_code == 201
    issue = issue.json()
    assert issue["status"] == "analysed" and issue["plan"]["before_after"]["misses_after"] == 0
    assert client.get("/kpis").json()["open_issues"] == 1
    assert len(client.get("/issues", params={"open": True}).json()) == 1

    result = client.post(f"/issues/{issue['issue_id']}/accept").json()
    assert result["issue"]["status"] == "accepted" and result["kpis"]["deadlines_saved"] == 3
    lakshmi = client.get("/partners/DP106").json()
    assert any("D06" in m["text"] for m in lakshmi["unread_messages"])
    assert client.post(f"/issues/{issue['issue_id']}/accept").status_code == 409  # already decided
    assert client.post("/partners/DP106/messages/read").json()["ok"]
    assert client.get("/partners/DP106").json()["unread_messages"] == []


def test_needs_location_then_edit_then_reject(client):
    issue = client.post("/issues", json={"partner_id": "DP102", "text": "accident somewhere ahead"}).json()
    assert issue["plan"]["kind"] == "needs_location"
    fixed = client.patch(f"/issues/{issue['issue_id']}", json={"road_id": "R8"}).json()
    assert fixed["status"] == "analysed" and fixed["problem"]["road_id"] == "R8"
    rejected = client.post(f"/issues/{issue['issue_id']}/reject", json={"reason": "Cleared already"}).json()
    assert rejected["status"] == "rejected"


def test_mark_delivered_and_reset(client):
    assert client.post("/deliveries/D01/delivered").json()["ok"]
    assert client.get("/partners/DP101").json()["partner"]["delivered"] == 1
    assert client.post("/deliveries/NOPE/delivered").status_code == 404
    client.post("/demo/reset")
    assert client.get("/partners/DP101").json()["partner"]["delivered"] == 0
