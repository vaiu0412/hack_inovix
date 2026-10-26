"""Learning from decisions: every recommendation's fate is logged with context, Skip rebuilds the plan, a logistic
regression learns what admins take, plans are ranked by chance taken × impact, and Insights sums it up."""
import json
from datetime import datetime, timedelta

import numpy as np
import pytest
from fastapi.testclient import TestClient

from api.main import app
from modules import auth, learning, operations, store
from modules import partner_scope as scope


@pytest.fixture()
def alert(tmp_path, monkeypatch):
    monkeypatch.setenv("RIPPLE_DB", str(tmp_path / "learning.db"))
    store.init_db()
    seen = scope.preview_issue("DP102", "CBE-E", text="avinasi rd la accident, full block, rendu mani neram aagum")
    return scope.report_issue("DP102", "CBE-E", seen["problem"], transcript=seen["transcript"])


def log(issue_id=None):
    rows = store.decisions_df()
    return rows[rows["issue_id"] == issue_id] if issue_id else rows


def keys(issue_id):
    return [a["action_id"] for a in store.get_issue(issue_id)["plan"]["actions"]]


def test_skip_rebuilds_the_plan_without_that_recommendation(alert):
    assert "reassign|delivery D06" in keys(alert)
    plan = operations.skip_action(alert, "reassign|delivery D06", "Divya", "CBE-E")
    assert "reassign|delivery D06" not in keys(alert) and plan["skipped"] == ["reassign|delivery D06"]
    assert plan["before_after"]["misses_after"] >= 0 and plan["actions"]                 # still a full plan
    [row] = log(alert).to_dict("records")
    assert row["decision"] == "skipped" and row["action_type"] == "reassign" and row["decided_by"] == "Divya"
    assert json.loads(row["features"])["cause"] == "accident" and 0 < row["p_accept"] < 1
    operations.restore_skipped(alert, "CBE-E")
    assert "reassign|delivery D06" in keys(alert)
    with pytest.raises(PermissionError):
        operations.skip_action(alert, "reroute|vehicle V2", "x", "CBE-C")                 # not their branch


def test_accept_logs_every_recommendation(alert):
    operations.skip_action(alert, "reroute|vehicle V3", "Divya", "CBE-E")
    remaining = len(store.get_issue(alert)["plan"]["actions"])
    east = auth.get_user("east.admin")
    operations.accept(alert, east["display_name"], branch_id="CBE-E")
    decisions = log(alert)["decision"].value_counts().to_dict()
    assert decisions["skipped"] == 1 and decisions["accepted"] == remaining
    assert decisions.get("not_chosen", 0) <= 1                                         # the optimised alternative


def test_reject_and_modify_are_logged_but_only_reject_is_learned(alert):
    operations.edit_problem(alert, "CBE-E", decided_by="Divya", severity="high")
    modified = log(alert)
    assert set(modified["decision"]) == {"modified"} and "severity → high" in modified["reason"].iloc[0]
    operations.reject(alert, "Road already clear", "Divya", "CBE-E")
    rejected = log(alert)[lambda d: d["decision"] == "rejected"]
    assert len(rejected) and set(rejected["reason"]) == {"Road already clear"}
    assert learning.type_rates()["reroute"][0] == 0                                    # nothing accepted


def test_logistic_regression_learns_a_clear_pattern():
    rng = np.random.default_rng(1)
    x = rng.normal(size=(300, 3))
    y = (2.5 * x[:, 0] - 1.5 * x[:, 1] + rng.normal(scale=0.5, size=300) > 0).astype(int)
    w, b, mean, std = learning.fit(x, y)
    model = {"weights": w.tolist(), "bias": b, "mean": mean.tolist(), "std": std.tolist()}
    p = learning._predict(model, x)
    assert w[0] > 0 > w[1] and abs(w[2]) < 0.5 and ((p >= 0.5) == y).mean() > 0.9
    assert learning.roc_auc(y, p) > 0.95 and learning.roc_auc([1, 1], [0.2, 0.3]) is None


def test_cold_start_uses_smoothed_rates_then_the_model(alert):
    raw = learning.action_features(store.get_issue(alert)["plan"]["actions"][0], store.get_issue(alert)["plan"])
    assert learning.load_model() is None and learning.p_accept(raw) == pytest.approx(0.5)
    assert learning.train()["trained"] is False                                         # not enough data
    learning.sample_history("CBE-E", n=80)
    result = learning.train(auth.get_user("east.admin"))
    assert result["trained"] and result["rows"] == 80 and result["metrics"]["train_auc"] > 0.6
    medical_backup = dict(raw, action_type="reassign", medical=True, extra_km=1.0, saved_min=60, risk=3)
    long_reroute = dict(raw, action_type="reroute", medical=False, extra_km=9.0, saved_min=5, risk=1)
    assert learning.p_accept(medical_backup) > learning.p_accept(long_reroute)
    up, down = learning.drivers()
    assert up and down


def test_ranking_is_chance_taken_times_impact(alert):
    plan = store.get_issue(alert)["plan"]
    scores = [a["rank_score"] for a in plan["actions"]]
    assert scores == sorted(scores, reverse=True)
    assert all(a["rank_score"] == pytest.approx(a["p_accept"] * a["impact"], abs=0.1) for a in plan["actions"])
    assert all(a["p_source"] == "none" for a in plan["actions"])                         # no history yet


def test_retrain_runs_once_a_day_with_new_decisions(alert):
    learning.sample_history("CBE-E", n=40)
    assert learning.maybe_retrain()["trained"]                                           # no model yet -> train
    assert not learning.maybe_retrain()["trained"]                                       # fresh
    model = learning.load_model()
    model["trained_at"] = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S")
    store.set_setting(learning.MODEL_KEY, json.dumps(model))
    assert not learning.maybe_retrain()["trained"]                                       # old, but nothing new
    learning.sample_history("CBE-E", n=5, seed=9)
    assert learning.maybe_retrain()["trained"]


def test_insights_and_the_api(alert):
    operations.skip_action(alert, "reassign|delivery D06", "Divya", "CBE-E")
    operations.accept(alert, "Divya", branch_id="CBE-E")
    data = learning.insights("CBE-E")
    by_type = {t["action_type"]: t for t in data["by_type"]}
    assert by_type["reassign"]["skipped"] >= 1 and data["plans_accepted"] == 1
    assert any(r["decision"] == "skipped" for r in data["most_changed"])
    assert learning.insights("CBE-C")["decisions"] == 0                                 # own branch only
    with TestClient(app) as client:
        token = client.post("/login", json={"identifier": "east.admin@deport.in", "password": "Admin@123"}).json()
        reply = client.get("/insights", headers={"Authorization": f"Bearer {token['token']}"}).json()
        assert reply["decisions"] == data["decisions"] and reply["plans_accepted"] == 1
