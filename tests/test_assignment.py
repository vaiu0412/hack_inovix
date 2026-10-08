"""Work assignment: new order -> best match -> assign (one transaction) -> the partner's step-by-step flow."""
import pytest

from modules import assign, auth, partner_scope as scope, store


@pytest.fixture()
def east(tmp_path, monkeypatch):
    monkeypatch.setenv("RIPPLE_DB", str(tmp_path / "assign.db"))
    store.init_db()
    return auth.authenticate("east.admin@deport.in", "Admin@123")[0]


def new_order(east, area="Peelamedu", size="small", deadline="16:00", priority="standard"):
    order_id, place = assign.create_order(east, "Anand Stores", "+91 90000 30001", area, "Parcel", priority, deadline,
                                          size, "Back gate")
    return order_id, place


def test_new_order_is_unassigned_in_the_admins_branch(east):
    order_id, place = new_order(east, area="pelamedu")                    # misspelt on purpose
    order = store.deliveries_df(branch_id="CBE-E").set_index("delivery_id").loc[order_id]
    assert place["place"] == "Peelamedu" and order["status"] == "unassigned" and order["vehicle_id"] is None
    assert order["created_by"] == "east.admin" and order["package_size"] == "small"
    assert order_id == "D31"                                              # next free number after the demo's 30
    with pytest.raises(ValueError, match="Place not found"):
        new_order(east, area="qwertyuiop")
    with pytest.raises(PermissionError):
        assign.create_order(auth.get_user("DP102"), "x", "1", "Peelamedu", "Parcel", "standard", "12:00", "small")


def test_best_match_is_the_nearest_partner_whose_vehicle_fits(east):
    small, _ = new_order(east, area="Ukkadam", size="small")
    best = assign.best_match(small, "CBE-E")
    assert best["partner_id"] == "DP102" and "km away" in best["reason"] and "🏍️ fits" in best["reason"]
    large, _ = new_order(east, area="Ukkadam", size="large")
    found = assign.candidates(store.deliveries_df().set_index("delivery_id").loc[large].to_dict() | {"delivery_id": large},
                              "CBE-E")
    assert found and all(c["vehicle_type"] in ("van", "truck") for c in found)   # a bike can't take a large parcel
    with pytest.raises(ValueError, match="doesn't fit"):
        assign.assign(east, large, "DP102")


def test_assign_updates_route_eta_inbox_and_history(east):
    order_id, _ = new_order(east, area="Gandhipuram", deadline="17:00")
    result = assign.assign(east, order_id, "DP101", reason="Closer partner")
    row = store.deliveries_df(branch_id="CBE-E").set_index("delivery_id").loc[order_id]
    assert row["vehicle_id"] == "V1" and row["status"] == "assigned" and row["planned_eta"] == result["eta"]
    mine = scope.get_partner_deliveries("DP101", "CBE-E").sort_values("stop_order")
    assert order_id in set(mine["delivery_id"]) and list(mine["stop_order"]) == list(range(1, len(mine) + 1))
    inbox = scope.get_partner_notifications("DP101", "CBE-E", unread_only=True)
    assert any(m["text"].startswith(f"New delivery {order_id} · Gandhipuram · by 17:00") for m in inbox)
    history = store.assignment_history(order_id)
    assert list(history["to_dp"]) == ["DP101"] and history["reason"].iloc[0] == "Closer partner"
    assert store.partners_df("CBE-E").set_index("partner_id").loc["DP101", "assigned"] == 7

    assign.reassign(east, order_id, "DP106", "Partner busy")                 # backup van takes it
    assert scope.get_partner_deliveries("DP106", "CBE-E")["delivery_id"].eq(order_id).any()
    assert not scope.get_partner_deliveries("DP101", "CBE-E")["delivery_id"].eq(order_id).any()
    assert any(f"{order_id} moved" in m["text"] for m in scope.get_partner_notifications("DP101", "CBE-E"))
    assign.unassign(east, order_id, "Customer request")
    assert store.deliveries_df().set_index("delivery_id").loc[order_id, "status"] == "unassigned"
    assert list(store.assignment_history(order_id)["to_dp"].fillna("—")) == ["—", "DP106", "DP101"]


def test_partner_flow_in_order_and_only_own_deliveries(east):
    order_id, _ = new_order(east, area="Gandhipuram")
    assign.assign(east, order_id, "DP101")
    with pytest.raises(ValueError, match="Accept"):
        scope.mark_delivered("DP101", "CBE-E", order_id)                     # can't skip to Delivered
    with pytest.raises(PermissionError):
        scope.advance_delivery("DP102", "CBE-E", order_id, "accepted")       # someone else's delivery
    for step in ("accepted", "picked_up", "in_transit"):
        assert scope.advance_delivery("DP101", "CBE-E", order_id, step)
    assert scope.mark_delivered("DP101", "CBE-E", order_id, note="Left at reception")
    row = store.deliveries_df().set_index("delivery_id").loc[order_id]
    assert row["status"] == "delivered" and row["proof_note"] == "Left at reception"
    assert row["accepted_at"] and row["picked_at"] and row["delivered_at"]


def test_auto_assign_all_respects_capacity(east):
    ids = [new_order(east, area=area, deadline="18:00")[0] for area in
           ["Peelamedu", "Gandhipuram", "RS Puram", "Hope College", "Singanallur", "Race Course", "Ukkadam",
            "Avinashi Road", "Lakshmi Mills", "PSG Tech", "Town Hall", "Sungam"]]
    plan = assign.auto_assign_plan("CBE-E")
    assert {row["delivery_id"] for row in plan} == set(ids)
    assert assign.apply_plan(east, plan) == sum(1 for row in plan if row["partner_id"])
    load = assign.workload("CBE-E")
    assert (load["open"] <= load["limit"]).all()
    assert assign.unassigned_orders("CBE-E").empty or all(r["partner_id"] is None for r in plan
                                                          if r["delivery_id"] in set(assign.unassigned_orders("CBE-E")["delivery_id"]))


def test_csv_import_reports_bad_rows(east):
    import io

    import pandas as pd

    rows = pd.read_csv(io.StringIO(assign.csv_template() + "Bad Row,,nowhere-land,Parcel,urgent,25:00,huge,\n"))
    good, errors = assign.validate_rows(rows)
    assert len(good) == 2 and errors and errors[0][0] == 4
    assert "Phone is missing." in errors[0][1] and "Place not found" in errors[0][1]
    assert len(assign.import_orders(east, good)) == 2 and len(assign.unassigned_orders("CBE-E")) == 2


def test_new_orders_stay_out_of_the_ai_plan(east):
    new_order(east, area="Avinashi Road")
    assert store.snapshot("CBE-E")["deliveries"]["vehicle_id"].notna().all()
