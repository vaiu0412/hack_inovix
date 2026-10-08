"""Partner report -> AI plan -> manager decision -> every screen updated."""
import pytest

from modules import issues, operations, store
from modules.voice import transcribe

ACCIDENT = "Avinashi road la accident, full block, rendu mani neram aagum"


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("RIPPLE_DB", str(tmp_path / "test.db"))
    store.init_db()
    return store


def report(partner_id, text, quick_type=None):
    seen = issues.preview(partner_id, text=text, quick_type=quick_type)
    return issues.submit(partner_id, seen["problem"], transcript=seen["transcript"], quick_type=quick_type)


def test_voice_without_engines_falls_back_to_typing(db):
    assert transcribe(None) is None
    assert transcribe(b"not really audio") is None
    seen = issues.preview("DP101", audio=b"not really audio")
    assert seen["engine"] == "not understood" and seen["problem"] is None


def test_report_is_understood_and_planned_immediately(db):
    issue = db.get_issue(report("DP101", ACCIDENT))
    assert issue["status"] == "analysed"
    assert issue["problem"]["road_id"] == "R1" and issue["problem"]["reported_by"] == "DP101"
    plan = issue["plan"]
    assert plan["summary"]["affected_deliveries"] == 9
    assert plan["before_after"]["misses_before"] == 3 and plan["before_after"]["misses_after"] == 0
    assert "KMCH" in plan["note"]
    assert operations.kpis()["open_issues"] == 1 and operations.kpis()["at_risk"] >= 3


def test_accept_updates_every_screen(db):
    issue_id = report("DP101", ACCIDENT)
    operations.accept(issue_id)
    deliveries = db.deliveries_df().set_index("delivery_id")
    assert deliveries.loc["D06", "vehicle_id"] == "V6"           # insulin moved to the backup van
    assert deliveries.loc["D06", "original_vehicle"] == "V1"
    assert db.get_partner("DP106")["status"] == "on_duty" and db.get_partner("DP106")["pending"] == 2
    assert any("D06" in m["text"] for m in db.messages_for("DP106"))  # backup driver told
    assert any("hand D06" in m["text"] for m in db.messages_for("DP101"))
    assert "R1" not in db.vehicles_df().set_index("vehicle_id").loc["V1", "route_roads"]
    assert len(db.customer_messages()) > 0
    assert db.active_disruptions()[0]["road_id"] == "R1"
    k = operations.kpis()
    assert k["open_issues"] == 0 and k["deadlines_saved"] == 3


def test_later_plans_never_detour_through_a_blocked_road(db):
    operations.accept(report("DP101", ACCIDENT))
    plan = db.get_issue(report("DP103", "Heavy rain flooding at Trichy Road, 45 mins"))["plan"]
    assert all("R1" not in a.get("via_roads", []) for a in plan["actions"])


def test_reject_tells_the_reporter(db):
    issue_id = report("DP102", "traffic jam on race course road 20 mins")
    operations.reject(issue_id, "Traffic is already clearing")
    assert db.get_issue(issue_id)["status"] == "rejected"
    assert any("already clearing" in m["text"] for m in db.messages_for("DP102"))


def test_unknown_place_asks_for_the_road_then_plans(db):
    issue_id = report("DP101", "International road accident")
    issue = db.get_issue(issue_id)
    assert issue["problem"]["needs_location"] and issue["plan"]["kind"] == "needs_location"
    plan = operations.edit_problem(issue_id, road_id="R1")
    assert plan["kind"] == "ripple" and db.get_issue(issue_id)["status"] == "analysed"


def test_customer_not_available_moves_the_stop_to_the_end(db):
    issue_id = report("DP101", "", quick_type="customer_unavailable")
    plan = db.get_issue(issue_id)["plan"]
    assert plan["kind"] == "single_stop" and plan["actions"][0]["deliveries_protected"] == ["D01"]
    operations.accept(issue_id)
    d01 = db.deliveries_df().set_index("delivery_id").loc["D01"]
    assert d01["stop_order"] == 7 and d01["note"] == "reattempt"


def test_mark_delivered(db):
    operations.mark_delivered("D01", "Murugan")
    assert db.get_partner("DP101")["delivered"] == 1 and db.get_partner("DP101")["pending"] == 5
