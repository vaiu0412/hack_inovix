"""Real-world data: GPS from partner phones (and simulated movement), live weather -> Weather risk alerts, live
traffic -> suggestions the admin confirms – all into the same impact -> plan -> approve flow. Network is mocked."""
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from api.main import app
from modules import auth, predict, realtime, store, tracking
from services import traffic, weather

T0 = datetime(2026, 10, 9, 9, 0, 0)
PEELAMEDU = (11.0262, 77.0047)


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("RIPPLE_DB", str(tmp_path / "realtime.db"))
    store.init_db()
    clock = {"now": T0}
    monkeypatch.setattr(tracking, "now", lambda: clock["now"])
    return clock


def position(vehicle_id):
    v = store.vehicles_df().set_index("vehicle_id").loc[vehicle_id]
    return float(v["current_lat"]), float(v["current_lng"])


class Reply:
    def __init__(self, data):
        self.data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self.data


# ---------------------------------------------------------------- GPS
def test_a_partner_phone_moves_only_its_own_vehicle(db):
    assert tracking.record("DP102", "CBE-E", *PEELAMEDU, accuracy_m=8)
    assert position("V2") == PEELAMEDU
    with pytest.raises(PermissionError):
        tracking.record("DP105", "CBE-E", *PEELAMEDU)                              # another branch's partner
    assert not tracking.record("DP102", "CBE-E", 13.0827, 80.2707)              # Chennai: not used
    assert position("V2") == PEELAMEDU
    db["now"] = T0 + timedelta(seconds=40)
    tracking.record("DP102", "CBE-E", 11.0270, 77.0060)
    assert tracking.trails("CBE-E")["V2"] == [[*PEELAMEDU], [11.0270, 77.0060]]
    seen = tracking.last_seen("CBE-E")["DP102"]
    assert seen["source"] == "gps" and tracking.seen_text(seen) == "GPS 0 s ago"
    assert tracking.seen_text(None) == "No live position"


def test_simulated_movement_drives_toward_the_next_stop(db):
    before = position("V2")
    assert tracking.simulate("CBE-E") == 0                                        # off by default
    tracking.set_simulation(auth.get_user("east.admin"), True)
    db["now"] = T0 + timedelta(seconds=60)
    assert tracking.simulate("CBE-E") >= 1
    after = position("V2")
    stop = store.deliveries_df(vehicle_id="V2").sort_values("stop_order").iloc[0]
    from modules.data_loader import haversine_km

    moved = haversine_km(*before, *after)
    assert 0 < moved <= tracking.SIM_SPEED_KMPH / 60 + 1e-6                        # one minute of city speed
    assert haversine_km(*after, stop["lat"], stop["lng"]) < haversine_km(*before, stop["lat"], stop["lng"])
    assert tracking.last_seen("CBE-E")["DP102"]["source"] == "sim"
    with pytest.raises(PermissionError):
        tracking.set_simulation(auth.get_user("DP102"), False)
    tracking.record("DP102", "CBE-E", *PEELAMEDU)                                # the real phone reports
    db["now"] = T0 + timedelta(seconds=120)
    tracking.simulate("CBE-E")
    assert position("V2") == PEELAMEDU                                            # simulation leaves it alone


# ---------------------------------------------------------------- weather
def test_weather_classes():
    assert weather.classify(0) == "clear" and weather.classify(2.0) == "light_rain"
    assert weather.classify(9.5) == "heavy_rain" and weather.classify(0, 211) == "heavy_rain"   # thunderstorm
    assert weather.classify(0, 500) == "light_rain" and weather.classify(0, 502) == "heavy_rain"


def test_heavy_rain_sets_the_weather_and_opens_one_weather_risk_alert(db, monkeypatch):
    monkeypatch.setenv("OWM_API_KEY", "test-key")
    monkeypatch.setattr(weather, "offline", lambda: False)
    calls = []

    def fake_get(url, params, timeout):
        calls.append(params)
        return Reply({"weather": [{"id": 502, "description": "heavy intensity rain"}], "rain": {"1h": 14.2},
                      "main": {"temp": 24.0}})

    monkeypatch.setattr(weather.httpx, "get", fake_get)
    done = realtime.poll()
    assert done["weather"]["weather"] == "heavy_rain" and predict.weather_now() == "heavy_rain"
    assert calls[0]["appid"] == "test-key" and realtime.weather_status()["rain_mm"] == 14.2
    risks = [i for i in store.list_issues(branch_id="CBE-E") if i["source"] == "auto-weather"]
    assert len(risks) == 1 and risks[0]["status"] == "analysed"                  # same flow: plan ready
    assert risks[0]["problem"]["type"] == "flood" and risks[0]["problem"]["road_id"] == "R1"
    assert risks[0]["plan"]["summary"]["affected_deliveries"] > 0
    db["now"] = T0 + timedelta(minutes=5)
    assert "weather" not in realtime.poll()                                       # every 10 min only
    db["now"] = T0 + timedelta(minutes=11)
    realtime.poll()
    assert len([i for i in store.list_issues(branch_id="CBE-E") if i["source"] == "auto-weather"]) == 1  # once a day


def test_no_keys_means_no_network_calls(db, monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("no network without keys")

    monkeypatch.setattr(weather.httpx, "get", boom)
    monkeypatch.setattr(traffic.httpx, "get", boom)
    assert not weather.configured() and not traffic.configured()
    assert realtime.poll("CBE-E") == {}


# ---------------------------------------------------------------- traffic
def test_live_traffic_jam_becomes_a_suggestion_the_admin_confirms(db, monkeypatch):
    monkeypatch.setenv("TOMTOM_API_KEY", "test-key")
    monkeypatch.setattr(traffic, "offline", lambda: False)

    def fake_get(url, params, timeout):
        lat = float(params["point"].split(",")[0])
        jammed = abs(lat - 11.0245) < 1e-6                                          # Avinashi Road's middle point
        return Reply({"flowSegmentData": {"currentSpeed": 8 if jammed else 30, "freeFlowSpeed": 38,
                                          "confidence": 0.9, "roadClosure": False}})

    monkeypatch.setattr(traffic.httpx, "get", fake_get)
    readings = realtime.check_traffic("CBE-E")
    assert readings["R1"]["level"] == "severe" and readings["R2"]["level"] == "normal"
    [suggestion] = realtime.suggestions("CBE-E")
    assert suggestion["road_id"] == "R1" and suggestion["source"] == "TomTom"
    realtime.check_traffic("CBE-E")
    assert len(realtime.suggestions("CBE-E")) == 1                                 # no duplicates the same day
    with pytest.raises(PermissionError):
        realtime.confirm(suggestion["suggestion_id"], auth.get_user("central.admin"))
    issue_id = realtime.confirm(suggestion["suggestion_id"], auth.get_user("east.admin"))
    issue = store.get_issue(issue_id)
    assert issue["status"] == "analysed" and issue["source"] == "auto-traffic"
    assert issue["problem"]["type"] == "traffic" and issue["problem"]["severity"] == "high"
    assert realtime.suggestions("CBE-E") == []
    with pytest.raises(ValueError):
        realtime.confirm(suggestion["suggestion_id"], auth.get_user("east.admin"))


def test_demo_traffic_check_plays_the_scripted_jam_and_can_be_dismissed(db):
    readings = realtime.check_traffic("CBE-E", demo=True)
    assert readings["R2"]["level"] == "heavy" and readings["R2"]["source"] == "Demo"
    [suggestion] = realtime.suggestions("CBE-E")
    realtime.dismiss(suggestion["suggestion_id"], auth.get_user("east.admin"))
    assert realtime.suggestions("CBE-E") == [] and store.list_issues(branch_id="CBE-E") == []
    status = realtime.status("CBE-E")
    assert status["traffic"]["checked_at"] and not status["traffic"]["live"] and status["gps"]["partners"] == 4


def test_the_mobile_api_reports_a_position(db):
    with TestClient(app) as client:
        token = client.post("/login", json={"identifier": "DP102", "password": "Partner@123"}).json()["token"]
        reply = client.post("/me/location", json={"lat": PEELAMEDU[0], "lng": PEELAMEDU[1], "accuracy_m": 6},
                            headers={"Authorization": f"Bearer {token}"}).json()
    assert reply == {"ok": True, "used": True} and position("V2") == PEELAMEDU
