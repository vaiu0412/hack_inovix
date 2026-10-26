"""OR-Tools re-optimisation: capacity is never exceeded, medical goes first when not everything fits, the time limit
holds, and the optimised plan sits next to the rule-based one – the admin picks, Accept applies it."""
import time

import pytest

from modules import auth, operations, optimizer, store
from modules import partner_scope as scope
from modules.data_loader import NOW_MIN
from modules.optimizer import Problem, Stop, Vehicle

pytestmark = pytest.mark.skipif(not optimizer.available(), reason="OR-Tools is not installed")
HUB = (11.0168, 76.9558)


def stop(i, priority="standard", deadline=12 * 60, size="small", owner="V1", lat=None, lng=None, **kw):
    return Stop(f"S{i}", lat or HUB[0] + 0.002 * (i % 7), lng or HUB[1] + 0.002 * (i // 7), deadline, NOW_MIN,
                priority, size, owner, **kw)


def served(result):
    return {s.delivery_id: vid for vid, visits in result["routes"].items() for s, _ in visits}


def test_capacity_is_never_exceeded():
    vehicles = [Vehicle("V1", "bike", *HUB, capacity=3), Vehicle("V2", "van", *HUB, capacity=3)]
    result = optimizer.solve(Problem(vehicles, [stop(i) for i in range(8)]), time_limit_s=2)
    assert all(len(visits) <= 3 for visits in result["routes"].values())
    assert len(served(result)) == 6 and len(result["dropped"]) == 2


def test_medical_is_served_first_when_not_everything_fits():
    vehicles = [Vehicle("V1", "van", *HUB, capacity=2), Vehicle("V2", "car", *HUB, capacity=2)]
    stops = [stop(0, "standard"), stop(1, "medical"), stop(2, "standard"), stop(3, "perishable"),
             stop(4, "medical"), stop(5, "express"), stop(6, "standard")]
    result = optimizer.solve(Problem(vehicles, stops), time_limit_s=2)
    kept = {s.priority for s in stops if s.delivery_id in served(result)}
    assert {"medical", "perishable"} <= kept and {s.priority for s in result["dropped"]} == {"standard"}


def test_medical_is_on_time_when_not_everyone_can_be():
    vehicles = [Vehicle("V1", "van", *HUB, capacity=10)]
    far = dict(lat=HUB[0] + 0.05, lng=HUB[1] + 0.05)          # ~9 km out: one of the two will be late
    stops = [stop(0, "standard", deadline=NOW_MIN + 25, **far),
             stop(1, "medical", deadline=NOW_MIN + 25, lat=HUB[0] - 0.05, lng=HUB[1] - 0.05)]
    result = optimizer.solve(Problem(vehicles, stops), time_limit_s=2)
    arrival = {s.delivery_id: t for s, t in result["routes"]["V1"]}
    assert arrival["S1"] <= NOW_MIN + 25 < arrival["S0"]


def test_parcels_fit_their_vehicle_and_pinned_stops_stay():
    vehicles = [Vehicle("V1", "bike", *HUB, capacity=8), Vehicle("V2", "van", *HUB, capacity=8)]
    stops = [stop(0, size="large", owner="V1"), stop(1, owner="V2", pinned=True), stop(2, owner="V1")]
    where = served(optimizer.solve(Problem(vehicles, stops), time_limit_s=2))
    assert where["S0"] == "V2" and where["S1"] == "V2"            # a bike can't take a large parcel


def test_the_time_limit_holds():
    vehicles = [Vehicle(f"V{i}", "van", HUB[0] + 0.01 * i, HUB[1], capacity=14) for i in range(5)]
    stops = [stop(i, ("medical", "express", "standard")[i % 3], deadline=NOW_MIN + 60 + i, owner=f"V{i % 5}")
             for i in range(60)]
    started = time.perf_counter()
    result = optimizer.solve(Problem(vehicles, stops), time_limit_s=1, thorough=True)
    assert time.perf_counter() - started < 3 and result["seconds"] <= 1.5 and result["status"] == "ok"


# ---------------------------------------------------------------- in the app
@pytest.fixture()
def alert(tmp_path, monkeypatch):
    monkeypatch.setenv("RIPPLE_DB", str(tmp_path / "optimizer.db"))
    store.init_db()
    seen = scope.preview_issue("DP102", "CBE-E", text="avinasi rd la accident, full block, rendu mani neram aagum")
    return scope.report_issue("DP102", "CBE-E", seen["problem"], transcript=seen["transcript"])


def test_the_alert_offers_an_optimised_plan_next_to_the_rule_plan(alert):
    plan = store.get_issue(alert)["plan"]
    opt = plan["optimised"]
    assert opt["status"] == "ok" and set(opt["comparison"]) == {"before", "rules", "optimised"}
    assert opt["comparison"]["rules"]["misses"] == plan["before_after"]["misses_after"]   # same numbers as the plan
    assert opt["comparison"]["optimised"]["misses"] == 0 and not opt["dropped"]
    planned = store.deliveries_df(branch_id="CBE-E").set_index("delivery_id")["eta_min"]
    assert all(s["eta_min"] >= planned[s["delivery_id"]] for stops in opt["routes"].values() for s in stops)
    assert set(opt["vehicles"]) <= set(store.vehicles_df("CBE-E")["vehicle_id"])         # this branch only


def test_accepting_the_optimised_plan_applies_its_routes(alert):
    east = auth.get_user("east.admin")
    opt = store.get_issue(alert)["plan"]["optimised"]
    operations.accept(alert, east["display_name"], branch_id="CBE-E", choice="optimised")
    deliveries = store.deliveries_df(branch_id="CBE-E").set_index("delivery_id")
    for vehicle_id, stops in opt["routes"].items():
        for s in stops:
            assert deliveries.loc[s["delivery_id"], "vehicle_id"] == vehicle_id
            assert deliveries.loc[s["delivery_id"], "planned_eta"] == s["eta"]
    issue = store.get_issue(alert)
    assert issue["status"] == "accepted" and "optimised" in issue["decision_note"] and issue["plan"]["chosen"] == \
        "optimised"
    routes = store.vehicles_df("CBE-E").set_index("vehicle_id")["route_roads"]
    assert all("R1" not in routes[v] for v in opt["routes"])                              # nobody uses the block
    for dp in ("DP101", "DP102", "DP103"):                                                # every hit partner is told
        assert any("new route (avoid Avinashi Road)" in m["text"] for m in scope.get_partner_notifications(dp, "CBE-E"))
    assert [d["road_id"] for d in store.active_disruptions("CBE-E")] == ["R1"]


def test_improve_searches_longer_within_the_limit(alert, monkeypatch):
    monkeypatch.setattr(optimizer, "TIME_LIMIT_S", 1)
    better = operations.improve(alert, "CBE-E")
    assert better["thorough"] and better["status"] == "ok" and better["seconds"] <= 1.5
    assert store.get_issue(alert)["plan"]["optimised"]["thorough"]
    with pytest.raises(PermissionError):
        operations.improve(alert, "CBE-C")                                                # other branches can't


def test_without_or_tools_the_rule_plan_stays(alert, monkeypatch):
    monkeypatch.setattr(optimizer, "pywrapcp", None)
    plan = operations.analyse(alert)
    assert plan["optimised"]["available"] is False and plan["actions"]
    east = auth.get_user("east.admin")
    with pytest.raises(ValueError, match="no optimised plan"):
        operations.accept(alert, east["display_name"], branch_id="CBE-E", choice="optimised")
    operations.accept(alert, east["display_name"], branch_id="CBE-E")
    assert store.get_issue(alert)["status"] == "accepted"
