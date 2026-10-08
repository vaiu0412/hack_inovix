"""The judges' demo, end to end on the core (no UI): DP102 reports by voice/text -> East's branch admin
sees the alert and accepts the plan -> deliveries, routes, KPIs, history and DP102's inbox all change,
and nothing leaks to the other branches. Run after every change: it must always pass."""
import pytest

from modules import auth, operations, partner_scope as scope, store


@pytest.fixture()
def demo(tmp_path, monkeypatch):
    monkeypatch.setenv("RIPPLE_DB", str(tmp_path / "demo.db"))
    store.init_db()


def report_accident():
    karthik, _ = auth.authenticate("DP102", "Partner@123")
    seen = scope.preview_issue("DP102", karthik["branch_id"], text="avinasi rd la accident, full block, rendu mani neram aagum")
    assert seen["problem"]["road_name"] == "Avinashi Road" and seen["problem"]["type"] == "accident"
    return scope.report_issue("DP102", karthik["branch_id"], seen["problem"], transcript=seen["transcript"])


def test_report_creates_alert_with_plan(demo):
    issue_id = report_accident()
    [alert] = store.list_issues(store.OPEN_ISSUE_STATUSES, branch_id="CBE-E")
    assert alert["issue_id"] == issue_id and alert["status"] == "analysed"
    plan = alert["plan"]
    assert plan["summary"]["affected_deliveries"] == 9
    assert (plan["before_after"]["misses_before"], plan["before_after"]["misses_after"]) == (3, 0)
    assert {a["action_type"] for a in plan["actions"]} >= {"reassign", "reroute"}
    assert all(a["title"] and a["why_short"] and a["impact_short"] for a in plan["actions"])
    assert store.list_issues(branch_id="CBE-C") == [] and store.list_issues(branch_id="CBE-S") == []


def test_accept_updates_everything(demo):
    issue_id = report_accident()
    east, _ = auth.authenticate("east.admin@deport.in", "Admin@123")
    before = operations.kpis("CBE-E")
    operations.accept(issue_id, east["display_name"], branch_id="CBE-E")

    deliveries = store.deliveries_df(branch_id="CBE-E").set_index("delivery_id")
    assert deliveries.loc["D06", "vehicle_id"] == "V6" and deliveries.loc["D10", "vehicle_id"] == "V6"  # backup van
    assert "R1" not in store.vehicles_df("CBE-E").set_index("vehicle_id").loc["V2", "route_roads"]  # rerouted
    assert store.get_issue(issue_id)["status"] == "accepted"
    after = operations.kpis("CBE-E")
    assert after["deadlines_saved"] == 3 and after["open_issues"] == before["open_issues"] - 1
    assert [d["road_id"] for d in store.active_disruptions("CBE-E")] == ["R1"]          # map shows the block
    assert any("accepted the plan" in e for e in store.events(branch_id="CBE-E")["text"])  # history
    inbox = scope.get_partner_notifications("DP102", "CBE-E", unread_only=True)
    assert any("avoid Avinashi Road" in m["text"] for m in inbox)                       # partner is told
    lakshmi = scope.get_partner_deliveries("DP106", "CBE-E")
    assert {"D06", "D10"} <= set(lakshmi["delivery_id"])
    assert operations.kpis("CBE-C")["deadlines_saved"] == 0 and store.active_disruptions("CBE-S") == []


def test_accept_is_one_transaction(demo, monkeypatch):
    """If anything fails half-way, nothing of the plan is applied."""
    issue_id = report_accident()
    snapshot = store.deliveries_df(branch_id="CBE-E").sort_values("delivery_id").reset_index(drop=True)

    def boom(*args, **kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(store, "log_event", boom)
    with pytest.raises(RuntimeError):
        operations.accept(issue_id, "Divya Raman", branch_id="CBE-E")
    assert store.get_issue(issue_id)["status"] == "analysed"
    assert store.deliveries_df(branch_id="CBE-E").sort_values("delivery_id").reset_index(drop=True).equals(snapshot)
    assert scope.get_partner_notifications("DP102", "CBE-E") == [] and store.active_disruptions("CBE-E") == []
