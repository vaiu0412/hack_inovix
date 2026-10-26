"""Platform: one schema for SQLite and PostgreSQL, the SQL translation, JWT access tokens, push to registered phones,
the change feed and its WebSockets, photo reports and nearest vehicles over the API. Runs on SQLite by default and
on PostgreSQL with TEST_DATABASE_URL (the PostgreSQL-only checks skip otherwise)."""
import sqlite3
import time

import jwt
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from api.main import app
from modules import assign, auth, db, schema, store, tokens
from services import push

PNG = b"\x89PNG\r\n\x1a\n" + bytes(64)
PUSH_TOKEN = "fcm-token-" + "x" * 40


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("RIPPLE_DB", str(tmp_path / "platform.db"))
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def fresh(tmp_path, monkeypatch):
    monkeypatch.setenv("RIPPLE_DB", str(tmp_path / "platform.db"))
    store.init_db()


def login(client, identifier, password="Partner@123"):
    reply = client.post("/login", json={"identifier": identifier, "password": password})
    assert reply.status_code == 200, reply.text
    return reply.json()


def bearer(body):
    return {"Authorization": f"Bearer {body['token']}"}


def east():
    return auth.authenticate("east.admin@deport.in", "Admin@123")[0]


def offer_to_karthik():
    admin = east()
    order_id, _ = assign.create_order(admin, "City Clinic", "+91 90000 30002", "Peelamedu", "Medicine", "medical",
                                      "16:00", "small")
    assign.assign(admin, order_id, "DP102")
    return order_id


# ---------------------------------------------------------------- schema + SQL translation
@pytest.mark.sqlite_only
def test_a_fresh_sqlite_file_has_exactly_the_schema(fresh):
    with sqlite3.connect(store.db_path()) as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' "
                                             "AND name NOT LIKE 'sqlite_%'")}
        assert tables == set(schema.metadata.tables)
        for name, table in schema.metadata.tables.items():
            assert [r[1] for r in conn.execute(f"PRAGMA table_info({name})")] == [c.name for c in table.columns]
        indexes = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'index' "
                                              "AND name LIKE 'ix_%'")}
        assert indexes == {i.name for t in schema.metadata.tables.values() for i in t.indexes}


def test_sqlite_sql_becomes_postgresql():
    assert db.translate("SELECT * FROM users WHERE email LIKE '%?%' AND id = ?") == \
        ("SELECT * FROM users WHERE email LIKE '%%?%%' AND id = %s", False)
    assert db.translate("INSERT OR IGNORE INTO roles(role_id, name) VALUES (?, ?)") == \
        ("INSERT INTO roles(role_id, name) VALUES (%s, %s) ON CONFLICT DO NOTHING", False)
    statement, _ = db.translate("INSERT OR REPLACE INTO route_geometry(key, points, source, meta) VALUES (?,?,?,?)",
                                many=True)
    assert statement.endswith("ON CONFLICT (key) DO UPDATE SET points = EXCLUDED.points, source = EXCLUDED.source, "
                              "meta = EXCLUDED.meta")
    assert db.translate("INSERT INTO messages(text) VALUES (?)") == \
        ("INSERT INTO messages(text) VALUES (%s) RETURNING id", True)          # cursor.lastrowid works
    assert db.translate("INSERT INTO issues(text) VALUES (?)")[0].endswith("RETURNING issue_id")
    assert db.translate("INSERT INTO meta(key, value) VALUES (?, ?)")[1] is False  # no auto-numbered key
    assert db.translate("PRAGMA foreign_keys = ON") == (None, False)
    assert db.translate("BEGIN IMMEDIATE") == (None, False)
    assert db.translate("SELECT IFNULL(a, 0) FROM t")[0] == "SELECT COALESCE(a, 0) FROM t"


def test_same_answers_on_either_database(fresh):
    assert store.version() > 0 and len(store.partners_df()) == 6 and len(store.deliveries_df()) == 30
    message_id = store.add_message("Hello", to_partner="DP102", branch_id="CBE-E")
    assert isinstance(message_id, int) and message_id > 0
    with store.connect() as conn:
        row = conn.execute("SELECT * FROM messages WHERE id = ?", (message_id,)).fetchone()
    assert row["text"] == "Hello" and row[0] == message_id and dict(row)["to_partner"] == "DP102"


@pytest.mark.skipif(not db.is_postgres(), reason="PostgreSQL only (TEST_DATABASE_URL)")
def test_postgresql_is_migrated_by_alembic(fresh):
    from sqlalchemy import inspect

    with db.engine().connect() as conn:
        version = conn.exec_driver_sql("SELECT version_num FROM alembic_version").scalar()
        found = inspect(conn)
        tables = set(found.get_table_names())
        assert set(schema.metadata.tables) <= tables
        for name, table in schema.metadata.tables.items():
            assert [c["name"] for c in found.get_columns(name)] == [c.name for c in table.columns], name
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    config = Config()
    config.set_main_option("script_location", str(db.MIGRATIONS))
    assert version == ScriptDirectory.from_config(config).get_current_head()  # migrated to the newest revision


# ---------------------------------------------------------------- after commit
def test_after_commit_runs_only_for_committed_writes(fresh):
    ran = []
    with pytest.raises(RuntimeError):
        with store.transaction():
            store.after_commit(lambda: ran.append("rolled back"))
            raise RuntimeError("boom")
    with store.transaction():
        store.after_commit(lambda: ran.append("committed"))
        assert ran == []  # not inside the transaction
    assert ran == ["committed"]
    store.after_commit(lambda: ran.append("now"))  # no transaction: right away
    assert ran == ["committed", "now"]


# ---------------------------------------------------------------- JWT
def test_login_gives_a_jwt_tied_to_the_session(client):
    body = login(client, "DP102")
    claims = jwt.decode(body["token"], options={"verify_signature": False})
    assert claims["sub"] == "DP102" and claims["role"] == "partner" and claims["dp"] == "DP102"
    assert claims["sid"] == auth.session_hash(body["refresh_token"]) and 0 < body["expires_in"] <= 3600
    assert body["refresh_token"] not in body["token"]                              # the session token stays secret
    assert client.get("/me", headers=bearer(body)).status_code == 200
    forged = jwt.encode({**claims, "role": "super_admin"}, "guessed-secret", algorithm="HS256")
    assert client.get("/me", headers={"Authorization": f"Bearer {forged}"}).status_code == 401
    assert client.get("/me", headers={"Authorization": f"Bearer {body['refresh_token']}"}).status_code == 200


def test_expired_token_refresh_and_logout(client):
    body = login(client, "DP102")
    user = auth.validate_session(body["refresh_token"])
    old, _ = tokens.issue(user, auth.session_hash(body["refresh_token"]), time.time() - 5)
    assert client.get("/me", headers={"Authorization": f"Bearer {old}"}).status_code == 401    # expired
    again = client.post("/token/refresh", json={"refresh_token": body["refresh_token"]}).json()
    assert client.get("/me", headers=bearer(again)).status_code == 200
    assert client.post("/logout", headers=bearer(again)).json()["ok"]
    for token in (body["token"], again["token"], body["refresh_token"]):            # the whole session ends
        assert client.get("/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401
    assert client.post("/token/refresh", json={"refresh_token": body["refresh_token"]}).status_code == 401


def test_jwt_secret_is_never_hardcoded(fresh, monkeypatch):
    monkeypatch.delenv("JWT_SECRET", raising=False)
    first = tokens._secret()
    assert len(first) >= 40 and tokens._secret() == first == store.get_setting("jwt_secret")  # made once, shared
    monkeypatch.setenv("JWT_SECRET", "from-the-environment-" + "y" * 30)
    assert tokens._secret().startswith("from-the-environment-")


# ---------------------------------------------------------------- push
def test_devices_and_push_on_a_new_offer(client, monkeypatch):
    body = login(client, "DP102")
    assert client.post("/me/devices", headers=bearer(body), json={"token": "short"}).status_code == 422
    assert client.post("/me/devices", headers=bearer(body), json={"token": PUSH_TOKEN}).json()["devices"] == 1
    assert store.device_tokens("DP102") == [PUSH_TOKEN]

    order_id = offer_to_karthik()                                                     # Demo mode: no Firebase keys
    assert not any(s["channel"] == "push" for s in store.escalations_df(delivery_id=order_id).to_dict("records"))

    sent = []
    monkeypatch.setattr(push, "configured", lambda: True)
    monkeypatch.setattr(push, "send", lambda token, title, text, data=None: sent.append((token, data)) or "sent")
    order_id = offer_to_karthik()
    assert sent == [(PUSH_TOKEN, {"type": "offer", "delivery_id": order_id})]
    results = store.escalations_df(delivery_id=order_id)["result"].tolist()
    assert "Push sent to 1 phone(s)" in results

    monkeypatch.setattr(push, "send", lambda *args, **kwargs: "invalid")             # the phone's token is gone
    offer_to_karthik()
    assert store.device_tokens("DP102") == []
    assert client.request("DELETE", "/me/devices", headers=bearer(body), json={"token": PUSH_TOKEN}).json()["ok"]


def test_no_push_when_the_assignment_rolls_back(fresh, monkeypatch):
    store.register_device({"user_id": "DP102", "dp_id": "DP102"}, PUSH_TOKEN)
    sent = []
    monkeypatch.setattr(push, "configured", lambda: True)
    monkeypatch.setattr(push, "send", lambda *args, **kwargs: sent.append(1) or "sent")
    admin = east()
    order_id, _ = assign.create_order(admin, "City Clinic", "+91 90000 30002", "Peelamedu", "Medicine", "medical",
                                      "16:00", "small")
    original = store.log_event

    def broken(*args, **kwargs):
        raise RuntimeError("database went away")

    monkeypatch.setattr(store, "log_event", broken)
    with pytest.raises(RuntimeError):
        assign.assign(admin, order_id, "DP102")
    monkeypatch.setattr(store, "log_event", original)
    assert sent == [] and store.deliveries_df().set_index("delivery_id").loc[order_id, "status"] == "unassigned"


# ---------------------------------------------------------------- change feed + WebSockets
def test_change_feed_is_scoped(fresh):
    start = store.last_change_id()
    order_id = offer_to_karthik()
    mine = store.changes_since(start, dp_id="DP102")
    assert any(c["kind"] == "offer" and c["data"]["delivery_id"] == order_id and c["data"]["result"] == "Sent"
               for c in mine)
    assert store.changes_since(start, dp_id="DP101") == []
    assert all(c["branch_id"] == "CBE-E" for c in store.changes_since(start, branch_id="CBE-E"))
    assert store.changes_since(start, branch_id="CBE-C") == []


def _next_change(ws, kind, tries=20):
    for _ in range(tries):
        message = ws.receive_json()
        if message["type"] == "change" and message["kind"] == kind:
            return message
    raise AssertionError(f"no {kind} change")


def test_partner_websocket_gets_their_new_offer(client):
    body = login(client, "DP102")
    with client.websocket_connect(f"/ws/partner?token={body['token']}") as ws:
        hello = ws.receive_json()
        assert hello["type"] == "hello" and hello["role"] == "partner"
        ws.send_text("ping")
        assert ws.receive_json() == {"type": "pong"}
        order_id = offer_to_karthik()
        change = _next_change(ws, "offer")
        assert change["data"]["delivery_id"] == order_id and change["dp_id"] == "DP102"


def test_admin_websocket_and_catch_up(client):
    start = store.last_change_id() if store.db_path().exists() else 0
    admin = login(client, "east.admin@deport.in", "Admin@123")
    order_id = offer_to_karthik()                                                     # happens while offline
    with client.websocket_connect(f"/ws/admin?token={admin['token']}&since={start}") as ws:
        assert ws.receive_json()["type"] == "hello"
        change = _next_change(ws, "offer")                                           # replayed
        assert change["data"]["delivery_id"] == order_id and change["branch_id"] == "CBE-E"


def test_websockets_need_the_right_token_and_role(client):
    partner = login(client, "DP102")
    for path, code in ((f"/ws/admin?token={partner['token']}", 4403), ("/ws/partner?token=nonsense", 4401),
                       ("/ws/partner", 4401)):
        with pytest.raises(WebSocketDisconnect) as closed:
            with client.websocket_connect(path) as ws:
                ws.receive_json()
        assert closed.value.code == code


# ---------------------------------------------------------------- photo report + nearest vehicles (API)
def test_photo_report_over_the_api(client):
    body = login(client, "DP102")
    photo = {"photo": ("road.png", PNG, "image/png")}
    assert client.post("/me/issues/photo", headers=bearer(body), files=photo).status_code == 422  # no vision key
    reply = client.post("/me/issues/photo", headers=bearer(body), files=photo,
                        data={"quick_type": "breakdown", "text": "tyre burst"})
    assert reply.status_code == 201
    assert store.get_issue(reply.json()["issue_id"])["photo_path"].endswith(".png")


def test_nearest_vehicles(client):
    admin = login(client, "east.admin@deport.in", "Admin@123")
    reply = client.get("/vehicles/nearest", params={"lat": 11.02, "lng": 76.96, "limit": 3}, headers=bearer(admin))
    found = reply.json()
    assert reply.status_code == 200 and len(found) == 3 and [v["km"] for v in found] == sorted(v["km"] for v in found)
    assert {v["vehicle_id"] for v in found} <= set(store.vehicles_df("CBE-E")["vehicle_id"])  # own branch only
    assert found[0]["vehicle_id"] == "V1" and abs(found[0]["km"] - 1.87) < 0.05
    partner = login(client, "DP102")
    assert client.get("/vehicles/nearest", params={"lat": 11, "lng": 77}, headers=bearer(partner)).status_code == 403
    assert client.get("/health").json()["database"] in ("SQLite", "PostgreSQL", "PostgreSQL + PostGIS")
