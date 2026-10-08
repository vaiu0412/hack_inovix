"""A partner can only ever see and change their own data."""
import pytest

from modules import operations, partner_scope as scope, store


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("RIPPLE_DB", str(tmp_path / "scope.db"))
    store.init_db()
    return store


def test_deliveries_are_only_your_own(db):
    mine = scope.get_partner_deliveries("DP102", "CBE-E")
    assert len(mine) == 6 and set(mine["vehicle_id"]) == {"V2"}
    assert set(mine["delivery_id"]) == {"D07", "D08", "D09", "D10", "D11", "D12"}


def test_cannot_mark_another_partners_delivery(db):
    before = store.deliveries_df().set_index("delivery_id")["status"].to_dict()
    with pytest.raises(PermissionError):
        scope.mark_delivered("DP102", "CBE-E", "D25")  # D25 belongs to DP105 (V5)
    assert store.deliveries_df().set_index("delivery_id")["status"].to_dict() == before


def test_can_mark_own_delivery_once(db):
    assert scope.mark_delivered("DP102", "CBE-E", "D07") is True
    assert scope.mark_delivered("DP102", "CBE-E", "D07") is False  # already delivered, nothing changes
    assert scope.get_partner_profile("DP102", "CBE-E")["delivered"] == 1


def test_unknown_partner_is_refused(db):
    for call in (lambda: scope.get_partner_deliveries("DP999", "CBE-E"), lambda: scope.get_partner_profile("manager", "CBE-E"),
                 lambda: scope.mark_delivered("DP999", "CBE-E", "D01")):
        with pytest.raises(PermissionError):
            call()


def test_reports_are_filed_as_the_logged_in_partner(db):
    seen = scope.preview_issue("DP102", "CBE-E", text="avinasi rd accident full block 2 hours")
    forged = {**seen["problem"], "reported_by": "DP105", "reporter_name": "Arun"}
    issue_id = scope.report_issue("DP102", "CBE-E", forged, transcript=seen["transcript"])
    issue = store.get_issue(issue_id)
    assert issue["partner_id"] == "DP102" and issue["problem"]["reported_by"] == "DP102"


def test_breakdown_is_always_your_own_vehicle(db):
    seen = scope.preview_issue("DP102", "CBE-E", text="Arun vandi breakdown near Pollachi road")  # names another driver
    issue_id = scope.report_issue("DP102", "CBE-E", seen["problem"])
    assert store.get_issue(issue_id)["problem"]["vehicle_id"] == "V2"


def test_incidents_show_status_but_not_other_partners_details(db):
    seen = scope.preview_issue("DP102", "CBE-E", text="avinasi rd accident full block 2 hours")
    scope.report_issue("DP102", "CBE-E", seen["problem"])
    [incident] = scope.get_partner_incidents("DP102", "CBE-E")
    assert incident["status"] == "analysed" and "plan" not in incident and "audio" not in incident
    assert scope.get_partner_incidents("DP105", "CBE-S") == []
    with pytest.raises(PermissionError):
        scope.get_partner_incidents("DP102", "CBE-S")  # right partner, wrong branch


def test_reassigned_parcel_appears_only_for_the_new_partner(db):
    seen = scope.preview_issue("DP102", "CBE-E", text="avinasi rd accident full block 2 hours")
    operations.accept(scope.report_issue("DP102", "CBE-E", seen["problem"]))
    assert "D10" not in set(scope.get_partner_deliveries("DP102", "CBE-E")["delivery_id"])   # dairy moved away
    assert "D10" in set(scope.get_partner_deliveries("DP106", "CBE-E")["delivery_id"])       # to the backup van
    assert any("D10" in m["text"] for m in scope.get_partner_notifications("DP106", "CBE-E"))
    assert not any("D10" in m["text"] and "collect" in m["text"] for m in scope.get_partner_notifications("DP105", "CBE-S"))


def test_route_is_your_own(db):
    route = scope.get_partner_route("DP102", "CBE-E")
    assert [r["road_id"] for r in route] == ["R10", "R8", "R1", "R9"]
