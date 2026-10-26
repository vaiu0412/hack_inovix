"""The Flutter partner app (mobile/) and the API must agree. No Flutter SDK needed: the Dart sources are read as text
and checked against the real FastAPI routes and real responses – every endpoint and method the app calls, every
JSON field it reads, and the lists it shares with the server (decline reasons, issue types)."""
import re
from pathlib import Path

import pytest
from fastapi.routing import APIRoute, APIWebSocketRoute
from fastapi.testclient import TestClient

from api.main import app
from modules import assign, auth, escalation
from modules.parser import TYPE_KEYWORDS

MOBILE = Path(__file__).resolve().parent.parent / "mobile" / "lib"


def dart(path):
    return (MOBILE / path).read_text(encoding="utf-8")


def endpoints():
    """{name: (METHOD, /path)} from lib/api/endpoints.dart."""
    found = re.findall(r"static const (\w+) = '(\w+) (/[^']*)';", dart("api/endpoints.dart"))
    return {name: (method, path) for name, method, path in found}


def _pattern(path):
    return re.compile("^" + re.sub(r"\{[^}]+\}", r"[^/]+", path) + "$")


def _example(path):
    return re.sub(r"\{[^}]+\}", "X1", path)


def fields_read(class_name):
    """The JSON keys a model class in lib/api/models.dart reads (j['…'])."""
    source = dart("api/models.dart")
    start = source.index(f"class {class_name} ")
    end = source.find("\nclass ", start + 1)
    return set(re.findall(r"j\['(\w+)'\]", source[start:end if end > 0 else None]))


def test_every_call_the_app_makes_exists():
    calls = endpoints()
    assert len(calls) >= 20
    http_routes = [r for r in app.routes if isinstance(r, APIRoute)]
    ws_routes = {r.path for r in app.routes if isinstance(r, APIWebSocketRoute)}
    for name, (method, path) in calls.items():
        if method == "WS":
            assert path in ws_routes, name
            continue
        example = _example(path)
        assert any(method in r.methods and _pattern(r.path).match(example) for r in http_routes), \
            f"{name}: {method} {path} is not an API route"


def test_steps_and_shared_lists_match_the_server():
    steps = set(re.findall(r"=> \('(\w+)', '", dart("api/models.dart")))
    assert steps == {"accepted", "picked_up", "in_transit", "delivered"}
    config = dart("config.dart")
    reasons = re.findall(r"'([^']+)'", re.search(r"declineReasons = \[(.*?)\];", config, re.S).group(1))
    assert tuple(reasons) == escalation.DECLINE_REASONS
    types = set(re.findall(r"'(\w+)': '", re.search(r"issueTypes = \{(.*?)\};", config, re.S).group(1)))
    assert types == {t for t, _ in TYPE_KEYWORDS}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("RIPPLE_DB", str(tmp_path / "mobile.db"))
    with TestClient(app) as c:
        yield c


def test_every_field_the_app_reads_is_in_the_responses(client):
    login = client.post("/login", json={"identifier": "DP102", "password": "Partner@123"}).json()
    client_source = dart("api/api_client.dart")
    for key in re.findall(r"body\['(\w+)'\]", client_source):
        if key in ("demo_code", "used", "profile", "unread_messages", "detail", "message"):
            continue  # other responses, checked below
        assert key in login, key
    refused = client.post("/login", json={"identifier": "DP102", "password": "wrong"})
    assert refused.status_code == 401 and isinstance(refused.json()["detail"], str)  # the app shows this text
    assert fields_read("User") <= set(login["user"])
    headers = {"Authorization": f"Bearer {login['token']}"}

    me = client.get("/me", headers=headers).json()
    assert {"profile", "unread_messages"} <= set(me)
    assert fields_read("Profile") <= set(me["profile"])

    admin = auth.authenticate("east.admin@deport.in", "Admin@123")[0]
    order_id, _ = assign.create_order(admin, "City Clinic", "+91 90000 30002", "Peelamedu", "Medicine", "medical",
                                      "16:00", "small")
    assign.assign(admin, order_id, "DP102")
    deliveries = client.get("/me/deliveries", headers=headers).json()
    offers = client.get("/me/offers", headers=headers).json()
    wanted = fields_read("Delivery")
    # risk only comes with my deliveries, call_note only with offers – both optional in the app ('' by default)
    assert wanted - {"call_note"} <= set(deliveries[0]) and wanted - {"risk"} <= set(offers[0])
    assert client.post("/me/offers/seen", headers=headers, json={"delivery_ids": [order_id]}).json()["changed"] == 1
    assert client.post("/me/offers/seen", headers=headers, json={"delivery_ids": ["D25"]}).status_code == 403

    messages = client.get("/me/messages", headers=headers).json()
    assert messages and fields_read("Message") <= set(messages[0])
    report = client.post("/me/issues", headers=headers, json={"text": "", "quick_type": "breakdown"}).json()
    assert fields_read("Incident") - {"summary"} <= set(report)
    assert client.post("/me/location", headers=headers, json={"lat": 11.0, "lng": 76.96}).json()["used"] is True
    code = client.post("/me/deliveries/D07/pod/code", headers=headers).json()
    assert "demo_code" in code


def test_code_sign_in_and_customer_orders_match_the_app(client):
    sent = client.post("/otp/request", json={"identifier": "90000 10007"}).json()
    client_source = dart("api/api_client.dart")
    assert {"message", "demo_code"} <= set(sent) and "body['message']" in client_source
    login = client.post("/otp/verify", json={"identifier": "90000 10007", "code": sent["demo_code"]}).json()
    assert fields_read("User") <= set(login["user"]) and login["user"]["role"] == "customer"
    orders = client.get("/my/orders", headers={"Authorization": f"Bearer {login['token']}"}).json()
    assert orders and fields_read("CustomerOrder") <= set(orders[0])
