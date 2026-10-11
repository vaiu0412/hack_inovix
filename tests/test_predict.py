"""Delay model: the committed model files load and behave sensibly, rules take over without them, the exported
trees match LightGBM, and the model feeds the impact engine (weather), the Likely late list and assignment."""
import pytest

from modules import assign, auth, predict, store
from modules.impact import compute_impact

RUSH = dict(road_id="R1", hour=9.2, weekday=2, rain_mm=0.0, distance_km=3.0, stops_before=3, vehicle_type="van",
            category="Parcel", experience_months=24, slack_min=20)


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("RIPPLE_DB", str(tmp_path / "predict.db"))
    store.init_db()


def test_committed_models_load_with_metadata():
    assert predict.available()
    meta = predict.metadata()
    assert meta["metrics"]["mae_min"] < meta["metrics"]["mae_plan_min"]           # better than "the plan is right"
    assert meta["metrics"]["roc_auc"] >= 0.9 and max(meta["export_max_abs_diff"].values()) < 1e-3
    assert predict.model(predict.REGRESSOR).features == predict.FEATURES


def test_predictions_follow_the_real_patterns():
    dry, wet = predict.predict_delay(RUSH), predict.predict_delay(dict(RUSH, rain_mm=12.0))
    assert dry["source"] == "model" and wet["delay_min"] > dry["delay_min"] + 3   # heavy rain costs minutes
    assert "Heavy rain" in wet["reasons"] and len(wet["reasons"]) <= 2
    bike = predict.predict_delay(dict(RUSH, vehicle_type="bike"))
    assert bike["delay_min"] < dry["delay_min"]                                  # bikes filter through traffic
    quiet = predict.predict_delay(dict(RUSH, road_id="R8", hour=11.5))
    assert quiet["delay_min"] < dry["delay_min"]                                 # off-peak, quieter road
    tight, loose = predict.predict_delay(dict(RUSH, slack_min=0)), predict.predict_delay(dict(RUSH, slack_min=90))
    assert tight["p_late"] > 0.5 > loose["p_late"] and "Tight deadline" in tight["reasons"]


def test_rules_take_over_without_model_files(tmp_path, monkeypatch):
    monkeypatch.setattr(predict, "MODEL_DIR", tmp_path)
    assert not predict.available() and predict.summary_line() == "Rules (no model file)"
    dry, wet = predict.predict_delay(RUSH), predict.predict_delay(dict(RUSH, rain_mm=12.0))
    assert dry["source"] == "rules" and wet["delay_min"] > dry["delay_min"]
    assert 0 <= dry["p_late"] <= 1 and dry["reasons"]


def test_broken_model_file_falls_back_to_rules(tmp_path, monkeypatch):
    (tmp_path / predict.REGRESSOR).write_text("{not json", encoding="utf-8")
    (tmp_path / predict.CLASSIFIER).write_text("{}", encoding="utf-8")
    monkeypatch.setattr(predict, "MODEL_DIR", tmp_path)
    assert predict.predict_delay(RUSH)["source"] == "rules"


def test_exported_trees_match_lightgbm():
    pytest.importorskip("lightgbm")
    import lightgbm as lgb
    import numpy as np

    from ml.generate_history import generate
    from ml.train_delay import export

    history = generate(days=6, per_day=150)
    x = np.array([predict.encode(r, with_slack=True) for r in history.to_dict("records")])
    for objective, target in (("regression", history["delay_min"]), ("binary", history["late"])):
        booster = lgb.train({"objective": objective, "num_leaves": 7, "verbose": -1, "seed": 1},
                            lgb.Dataset(x, target), num_boost_round=30)
        forest = predict.Forest(export(booster, predict.CLASSIFIER_FEATURES, objective))
        ours = np.array([forest.raw(list(row)) for row in x[:200]])
        assert np.abs(ours - booster.predict(x[:200], raw_score=True)).max() < 1e-4
        raw, groups = forest.contributions(list(x[0]))
        assert abs(raw - forest.raw(list(x[0]))) < 1e-6                           # reasons add up to the score


def test_dry_day_leaves_the_demo_impact_unchanged_and_rain_adds_delay(db):
    east = auth.get_user("east.admin")
    problem = {"type": "accident", "road_id": "R1", "road_name": "Avinashi Road", "severity": "critical",
               "duration_min": 120}
    impact_dry, summary_dry = compute_impact(problem, store.snapshot("CBE-E"))
    assert summary_dry["affected_deliveries"] == 9 and (impact_dry["weather_min"] == 0).all()
    predict.set_weather(east, "heavy_rain")
    impact_wet, summary_wet = compute_impact(problem, store.snapshot("CBE-E"))
    assert (impact_wet["weather_min"] > 0).any()
    assert summary_wet["total_delay_min"] > summary_dry["total_delay_min"]
    assert summary_wet["affected_deliveries"] == 9                                  # rain adds minutes, not stops


def test_likely_late_list_and_weather_permissions(db):
    karthik = auth.get_user("DP102")
    with pytest.raises(PermissionError):
        predict.set_weather(karthik, "heavy_rain")
    with pytest.raises(ValueError):
        predict.set_weather(auth.get_user("east.admin"), "snow")
    every = predict.likely_late("CBE-E", threshold=0)
    assert len(every) == len(predict.for_branch("CBE-E")) > 0
    assert list(every["p_late"]) == sorted(every["p_late"], reverse=True)
    assert set(every["branch_id"]) == {"CBE-E"}                                     # never another branch
    store.update_delivery("D06", deadline="10:50")                                   # a tight deadline now
    assert "D06" in set(predict.likely_late("CBE-E")["delivery_id"])


def test_assignment_uses_the_predicted_delay(db):
    east = auth.get_user("east.admin")
    order_id, _ = assign.create_order(east, "City Clinic", "+91 90000 30002", "Peelamedu", "Medicine", "medical",
                                      "16:00", "small")
    found = assign.candidates(store.deliveries_df().set_index("delivery_id").loc[order_id].to_dict()
                              | {"delivery_id": order_id}, "CBE-E")
    assert found and all("likely_delay_min" in c and 0 <= c["p_late"] <= 1 for c in found)
