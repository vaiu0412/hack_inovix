"""The mobile API: session login, 3 roles, branch scoping, partner isolation, report -> accept."""
import pytest
from fastapi.testclient import TestClient

from api.main import app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("RIPPLE_DB", str(tmp_path / "api.db"))
    with TestClient(app) as c:
        yield c


def token(client, identifier, password, super_console=False):
    reply = client.post("/login", json={"identifier": identifier, "password": password, "super_console": super_console})
    assert reply.status_code == 200, reply.text
    return {"Authorization": f"Bearer {reply.json()['token']}"}


@pytest.fixture()
def east(client):
    return token(client, "east.admin@ripple.in", "Admin@123")


@pytest.fixture()
def karthik(client):
    return token(client, " dp102 ", "Partner@123")


def test_login_errors_and_logout(client):
    assert client.get("/health").json()["status"] == "ok"
    assert client.post("/login", json={"identifier": "east.admin@ripple.in", "password": "x"}).status_code == 401
    assert client.post("/login", json={"identifier": "superadmin@ripple.in", "password": "Super@123"}).status_code == 403
    for _ in range(4):
        client.post("/login", json={"identifier": "DP103", "password": "x"})
    assert client.post("/login", json={"identifier": "DP103", "password": "x"}).status_code == 429
    headers = token(client, "dp101@ripple.in", "Partner@123")
    assert client.get("/me", headers=headers).status_code == 200
    assert client.post("/logout", headers=headers).json()["ok"]
    assert client.get("/me", headers=headers).status_code == 401          # revoked
    assert client.get("/partners").status_code == 401
    assert client.get("/partners", headers={"Authorization": "Bearer nonsense"}).status_code == 401


def test_super_admin_sees_summaries_only(client):
    boss = token(client, "superadmin@ripple.in", "Super@123", super_console=True)
    branches = client.get("/branches", headers=boss).json()
    assert {b["branch_id"] for b in branches} == {"CBE-E", "CBE-C", "CBE-S"}
    assert client.get("/partners", headers=boss).status_code == 403          # no day-to-day operations


def test_branch_admin_is_scoped(client, east):
    partners = client.get("/partners", headers=east).json()
    assert {p["partner_id"] for p in partners} == {"DP101", "DP102", "DP103", "DP106"}
    assert client.get("/partners/DP104", headers=east).status_code == 404     # Central's partner
    assert {d["branch_id"] for d in client.get("/deliveries", headers=east).json()} == {"CBE-E"}
    live = client.get("/map", headers=east).json()
    assert len(live["partners"]) == 4 and len(live["deliveries"]) == 18
    assert client.get("/branches", headers=east).status_code == 403


def test_partner_sees_only_own_data(client, karthik):
    me = client.get("/me", headers=karthik).json()
    assert me["profile"]["partner_id"] == "DP102" and me["profile"]["branch_id"] == "CBE-E"
    mine = client.get("/me/deliveries", headers=karthik).json()
    assert {d["vehicle_id"] for d in mine} == {"V2"} and len(mine) == 6
    for admin_only in ("/partners", "/kpis", "/map", "/deliveries", "/issues", "/branches"):
        assert client.get(admin_only, headers=karthik).status_code == 403
    assert client.post("/me/deliveries/D25/delivered", headers=karthik).status_code == 403   # DP105's parcel
    assert client.post("/me/deliveries/D07/delivered", headers=karthik).json()["changed"] is True


def test_report_accept_stays_in_branch(client, east, karthik):
    reply = client.post("/me/issues", json={"text": "avinasi rd accident, full block, 2 hours"}, headers=karthik)
    assert reply.status_code == 201 and reply.json()["status"] == "analysed" and "plan" not in reply.json()
    issue_id = reply.json()["issue_id"]
    central = token(client, "central.admin@ripple.in", "Admin@123")
    assert client.get(f"/issues/{issue_id}", headers=central).status_code == 404
    assert client.post(f"/issues/{issue_id}/accept", headers=central).status_code == 404
    result = client.post(f"/issues/{issue_id}/accept", headers=east).json()
    assert result["issue"]["status"] == "accepted" and result["kpis"]["deadlines_saved"] == 3
    assert any("avoid Avinashi Road" in m["text"] for m in client.get("/me/messages", headers=karthik).json())
    lakshmi = token(client, "DP106", "Partner@123")
    assert any(d["delivery_id"] == "D06" for d in client.get("/me/deliveries", headers=lakshmi).json())
    assert client.get("/kpis", headers=central).json()["deadlines_saved"] == 0


def test_needs_location_then_edit_then_reject(client, east):
    issue = client.post("/issues", json={"partner_id": "DP102", "text": "accident somewhere ahead"}, headers=east).json()
    assert issue["plan"]["kind"] == "needs_location"
    fixed = client.patch(f"/issues/{issue['issue_id']}", json={"road_id": "R8"}, headers=east).json()
    assert fixed["status"] == "analysed" and fixed["problem"]["road_id"] == "R8"
    assert client.post(f"/issues/{issue['issue_id']}/reject", json={"reason": "Cleared"}, headers=east).json()["status"] == "rejected"
    assert client.post("/issues", json={"partner_id": "DP104", "text": "x"}, headers=east).status_code == 403


def test_reset_is_super_admin_only(client, east):
    assert client.post("/demo/reset", headers=east).status_code == 403
    boss = token(client, "superadmin@ripple.in", "Super@123", super_console=True)
    assert client.post("/demo/reset", headers=boss).json()["ok"]
