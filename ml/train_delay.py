"""Train the delay models with LightGBM and export them for the app.

- regressor:  minutes late vs plan (objective: regression)            -> models/delay_regressor.json
- classifier: misses the deadline yes/no (objective: binary, +slack)  -> models/late_classifier.json
- metadata:   data, split, parameters, metrics, feature importance     -> models/delay_model.meta.json

Train/test split by date: the last 12 days are the test set; the 7 days before them are used for early stopping.
Metrics: MAE (minutes) for the regressor, ROC-AUC for the classifier – each next to a simple baseline.
Importance: LightGBM gain and mean |SHAP| (TreeSHAP via pred_contrib), grouped like the app's reasons.
The export is checked against LightGBM's own predictions before it is saved.

Run:  pip install -r requirements-ml.txt
      python ml/generate_history.py && python ml/train_delay.py
"""
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ml.generate_history import OUT as HISTORY  # noqa: E402
from modules import predict  # noqa: E402

TEST_DAYS, VALID_DAYS, SEED = 12, 7, 7
PARAMS = {"num_leaves": 15, "learning_rate": 0.05, "min_data_in_leaf": 40, "feature_fraction": 0.9,
          "bagging_fraction": 0.9, "bagging_freq": 1, "lambda_l2": 1.0, "seed": SEED, "verbose": -1,
          "deterministic": True, "force_row_wise": True, "num_threads": 1}


# ---------------------------------------------------------------- export (LightGBM -> app JSON)
def export(booster, features, objective):
    """LightGBM booster -> {objective, features, trees}; each tree as flat lists for modules.predict.Forest.
    Internal node values are the count-weighted means of their leaves, so path contributions add up exactly."""
    trees = []
    for info in booster.dump_model()["tree_info"]:
        tree = {key: [] for key in "ftlrvd"}

        def add(node, tree=tree):
            i = len(tree["f"])
            for key in tree:
                tree[key].append(None)
            if "leaf_value" in node:
                value, count = float(node["leaf_value"]), max(int(node.get("leaf_count", 1)), 1)
                tree["f"][i], tree["t"][i], tree["l"][i], tree["r"][i] = -1, 0.0, -1, -1
                tree["d"][i], tree["v"][i] = False, value
                return value, count
            if node.get("decision_type", "<=") != "<=":
                raise ValueError(f"unsupported split {node.get('decision_type')}")
            tree["f"][i], tree["t"][i] = int(node["split_feature"]), float(node["threshold"])
            tree["d"][i] = bool(node.get("default_left", True))
            tree["l"][i] = len(tree["f"])
            left_value, left_count = add(node["left_child"])
            tree["r"][i] = len(tree["f"])
            right_value, right_count = add(node["right_child"])
            tree["v"][i] = (left_value * left_count + right_value * right_count) / (left_count + right_count)
            return tree["v"][i], left_count + right_count

        add(info["tree_structure"])
        tree["v"] = [float(f"{v:.7g}") for v in tree["v"]]
        trees.append(tree)
    return {"objective": objective, "features": list(features), "trees": trees}


# ---------------------------------------------------------------- metrics
def roc_auc(labels, scores):
    """Area under the ROC curve (rank formula, ties averaged)."""
    labels, scores = np.asarray(labels), np.asarray(scores)
    ranks = pd.Series(scores).rank(method="average").to_numpy()
    positives = labels == 1
    n_pos, n_neg = positives.sum(), (~positives).sum()
    return float((ranks[positives].sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg))


def _grouped(names, values):
    out = {}
    for name, value in zip(names, values):
        group = predict._group(name)
        out[group] = out.get(group, 0.0) + float(value)
    total = sum(out.values()) or 1.0
    return {g: round(v / total, 3) for g, v in sorted(out.items(), key=lambda kv: -kv[1])}


# ---------------------------------------------------------------- training
def split(history):
    last = date.fromisoformat(history["date"].max())
    test_from = (last - timedelta(days=TEST_DAYS - 1)).isoformat()
    valid_from = (last - timedelta(days=TEST_DAYS + VALID_DAYS - 1)).isoformat()
    train = history[history["date"] < valid_from]
    valid = history[(history["date"] >= valid_from) & (history["date"] < test_from)]
    test = history[history["date"] >= test_from]
    return train, valid, test


def matrix(rows, with_slack=False):
    return np.array([predict.encode(r, with_slack) for r in rows.to_dict("records")])


def fit(objective, features, train_x, train_y, valid_x, valid_y):
    params = dict(PARAMS, objective=objective, metric="l1" if objective == "regression" else "auc")
    data = lgb.Dataset(train_x, train_y, feature_name=list(features), free_raw_data=False)
    valid = lgb.Dataset(valid_x, valid_y, reference=data)
    return lgb.train(params, data, num_boost_round=800, valid_sets=[valid],
                     callbacks=[lgb.early_stopping(50, verbose=False)])


def check_export(spec, booster, x, tolerance):
    """The app's evaluator must give LightGBM's answers (raw scores; small rounding allowed)."""
    forest = predict.Forest(spec)
    ours = np.array([forest.raw(list(row)) for row in x])
    theirs = booster.predict(x, raw_score=True)
    worst = float(np.abs(ours - theirs).max())
    if worst > tolerance:
        raise AssertionError(f"export differs from LightGBM by {worst}")
    return worst


def main():
    history = pd.read_csv(HISTORY)
    train, valid, test = split(history)
    x_train, x_valid, x_test = matrix(train), matrix(valid), matrix(test)
    c_train, c_valid, c_test = matrix(train, True), matrix(valid, True), matrix(test, True)

    regressor = fit("regression", predict.FEATURES, x_train, train["delay_min"], x_valid, valid["delay_min"])
    classifier = fit("binary", predict.CLASSIFIER_FEATURES, c_train, train["late"], c_valid, valid["late"])

    delay_pred = regressor.predict(x_test, num_iteration=regressor.best_iteration)
    late_pred = classifier.predict(c_test, num_iteration=classifier.best_iteration)
    rules = [predict.rule_delay(r) for r in test.to_dict("records")]
    rule_delay = np.array([d for d, _ in rules])
    rule_p = 1 / (1 + np.exp(-(rule_delay - test["slack_min"].to_numpy()) / 6))
    metrics = {
        "mae_min": round(float(np.abs(delay_pred - test["delay_min"]).mean()), 2),
        "rmse_min": round(float(np.sqrt(((delay_pred - test["delay_min"]) ** 2).mean())), 2),
        "mae_rules_min": round(float(np.abs(rule_delay - test["delay_min"]).mean()), 2),
        "mae_plan_min": round(float(np.abs(test["delay_min"]).mean()), 2),
        "roc_auc": round(roc_auc(test["late"], late_pred), 3),
        "roc_auc_rules": round(roc_auc(test["late"], rule_p), 3),
        "late_rate_test": round(float(test["late"].mean()), 3),
        "accuracy_at_0_5": round(float(((late_pred >= 0.5) == test["late"]).mean()), 3),
    }

    # keep only the trees early stopping chose, then export and check against LightGBM
    regressor = lgb.Booster(model_str=regressor.model_to_string(num_iteration=regressor.best_iteration))
    classifier = lgb.Booster(model_str=classifier.model_to_string(num_iteration=classifier.best_iteration))
    reg_spec = export(regressor, predict.FEATURES, "regression")
    clf_spec = export(classifier, predict.CLASSIFIER_FEATURES, "binary")
    sample = slice(0, 400)
    parity = {"regressor": check_export(reg_spec, regressor, x_test[sample], 1e-3),
              "classifier": check_export(clf_spec, classifier, c_test[sample], 1e-3)}

    shap_reg = np.abs(regressor.predict(x_test, pred_contrib=True)[:, :-1]).mean(axis=0)
    shap_clf = np.abs(classifier.predict(c_test, pred_contrib=True)[:, :-1]).mean(axis=0)
    meta = {
        "trained_on": date.today().isoformat(),
        "lightgbm": lgb.__version__,
        "data": {"file": str(HISTORY.relative_to(ROOT)).replace("\\", "/"), "rows": len(history),
                 "days": int(history["date"].nunique()), "train_rows": len(train), "valid_rows": len(valid),
                 "test_rows": len(test), "test_from": test["date"].min(), "test_to": test["date"].max()},
        "params": PARAMS,
        "trees": {"regressor": regressor.num_trees(), "classifier": classifier.num_trees()},
        "metrics": metrics,
        "export_max_abs_diff": parity,
        "importance_gain": {"regressor": _grouped(predict.FEATURES, regressor.feature_importance("gain")),
                            "classifier": _grouped(predict.CLASSIFIER_FEATURES, classifier.feature_importance("gain"))},
        "mean_abs_shap": {"regressor": _grouped(predict.FEATURES, shap_reg),
                          "classifier": _grouped(predict.CLASSIFIER_FEATURES, shap_clf)},
    }
    predict.MODEL_DIR.mkdir(exist_ok=True)
    for name, spec in ((predict.REGRESSOR, reg_spec), (predict.CLASSIFIER, clf_spec)):
        (predict.MODEL_DIR / name).write_text(json.dumps(spec, separators=(",", ":")), encoding="utf-8")
    (predict.MODEL_DIR / predict.META).write_text(json.dumps(meta, indent=2), encoding="utf-8")

    print(f"train {len(train)} · valid {len(valid)} · test {len(test)} rows (test {meta['data']['test_from']} – "
          f"{meta['data']['test_to']})")
    print(f"regressor:  {regressor.num_trees()} trees · MAE {metrics['mae_min']} min "
          f"(rules {metrics['mae_rules_min']}, plan only {metrics['mae_plan_min']}) · RMSE {metrics['rmse_min']}")
    print(f"classifier: {classifier.num_trees()} trees · ROC-AUC {metrics['roc_auc']} "
          f"(rules {metrics['roc_auc_rules']}) · accuracy {metrics['accuracy_at_0_5']} "
          f"· late rate {metrics['late_rate_test']}")
    print("mean |SHAP|, regressor:", meta["mean_abs_shap"]["regressor"])
    print("mean |SHAP|, classifier:", meta["mean_abs_shap"]["classifier"])
    print(f"export matches LightGBM (max diff {max(parity.values()):.2e}); saved to {predict.MODEL_DIR.name}/")
    return meta


if __name__ == "__main__":
    main()
