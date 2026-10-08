"""The mobile API: token login, role checks, partner isolation, and the full report -> accept flow."""
import pytest
from fastapi.testclient import TestClient

from api.main import app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("RIPPLE_DB", str(tmp_path / "api.db"))
    with TestClient(app) as c:
        yield c


def token(client, role, user_id, password):
    reply = client.post("/login", json={"role": role, "user_id": user_id, "password": password})
    assert reply.status_code == 200, reply.text
    return {"Authorization": f"Bearer {reply.json()['token']}"}


@pytest.fixture()
def manager(client):
    return token(client, "manager", "manager", "ripple@123")


@pytest.fixture()
def karthik(client):
    return token(client, "partner", " dp102 ", "partner@123")


def test_login_errors(client):
    assert client.get("/health").json()["status"] == "ok"
    assert client.post("/login", json={"role": "manager", "user_id": "manager", "password": "x"}).status_code == 401
    assert client.post("/login", json={"role": "partner", "user_id": "manager",
                                       "password": "ripple@123"}).status_code == 403
    for _ in range(4):
        client.post("/login", json={"role": "partner", "user_id": "DP103", "password": "x"})
    assert client.post("/login", json={"role": "partner", "user_id": "DP103", "password": "x"}).status_code == 429


def test_tokens_are_required_and_checked(client, manager):
    assert client.get("/partners").status_code == 401
    assert client.get("/partners", headers={"Authorization": "Bearer nonsense"}).status_code == 401
    body, signature = manager["Authorization"].split(" ")[1].split(".")
    forged = {"Authorization": f"Bearer {body}.{'0' * len(signature)}"}
    assert client.get("/partners", headers=forged).status_code == 401


def test_manager_endpoints(client, manager):
    partners = client.get("/partners", headers=manager).json()
    assert len(partners) == 6 and partners[0]["partner_id"] == "DP101"
    assert len(client.get("/partners/DP101", headers=manager).json()["stops"]) == 6
    live = client.get("/map", headers=manager).json()
    assert len(live["partners"]) == 6 and len(live["deliveries"]) == 30 and len(live["roads"]) == 10
    assert client.get("/partners/DP999", headers=manager).status_code == 404


def test_partner_sees_only_own_data(client, karthik):
    me = client.get("/me", headers=karthik).json()
    assert me["profile"]["partner_id"] == "DP102" and me["profile"]["name"] == "Karthik"
    mine = client.get("/me/deliveries", headers=karthik).json()
    assert {d["vehicle_id"] for d in mine} == {"V2"} and len(mine) == 6
    for manager_only in ("/partners", "/kpis", "/map", "/deliveries", "/issues"):
        assert client.get(manager_only, headers=karthik).status_code == 403
    assert client.post("/me/deliveries/D25/delivered", headers=karthik).status_code == 403   # DP105's parcel
    assert client.post("/me/deliveries/D07/delivered", headers=karthik).json()["changed"] is True


def test_report_accept_and_inboxes(client, manager, karthik):
    preview = client.post("/me/issues/preview", data={"text": "avinasi rd accident 2 hours"}, headers=karthik).json()
    assert preview["problem"]["road_id"] == "R1"
    reply = client.post("/me/issues", json={"text": "avinasi rd accident, full block, 2 hours"}, headers=karthik)
    assert reply.status_code == 201 and reply.json()["status"] == "analysed" and "plan" not in reply.json()
    issue_id = reply.json()["issue_id"]
    issue = client.get(f"/issues/{issue_id}", headers=manager).json()
    assert issue["partner_id"] == "DP102" and issue["plan"]["before_after"]["misses_after"] == 0

    result = client.post(f"/issues/{issue_id}/accept", headers=manager).json()
    assert result["issue"]["status"] == "accepted" and result["kpis"]["deadlines_saved"] == 3
    assert client.post(f"/issues/{issue_id}/accept", headers=manager).status_code == 409
    assert any("avoid Avinashi Road" in m["text"] for m in client.get("/me/messages", headers=karthik).json())
    lakshmi = token(client, "partner", "DP106", "partner@123")
    assert any(d["delivery_id"] == "D06" for d in client.get("/me/deliveries", headers=lakshmi).json())
    assert client.post("/me/messages/read", headers=lakshmi).json()["ok"]
    assert client.get("/me", headers=lakshmi).json()["unread_messages"] == []


def test_needs_location_then_edit_then_reject(client, manager):
    issue = client.post("/issues", json={"partner_id": "DP102", "text": "accident somewhere ahead"},
                        headers=manager).json()
    assert issue["plan"]["kind"] == "needs_location"
    fixed = client.patch(f"/issues/{issue['issue_id']}", json={"road_id": "R8"}, headers=manager).json()
    assert fixed["status"] == "analysed" and fixed["problem"]["road_id"] == "R8"
    rejected = client.post(f"/issues/{issue['issue_id']}/reject", json={"reason": "Cleared already"},
                           headers=manager).json()
    assert rejected["status"] == "rejected"


def test_reset_is_manager_only(client, manager, karthik):
    assert client.post("/demo/reset", headers=karthik).status_code == 403
    assert client.post("/demo/reset", headers=manager).json()["ok"]
