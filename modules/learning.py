"""Learning from decisions – which recommendations do admins actually take? No Streamlit imports.

Every recommendation and what the admin did with it is logged (decisions table):
  accepted  – applied with the plan                      (learned as 1)
  skipped   – turned down before accepting (Skip)        (learned as 0)
  rejected  – the whole plan was rejected, with a reason (learned as 0)
  modified  – the admin corrected the AI's understanding first (logged only)
  replaced  – the optimised plan was chosen instead       (logged only)
Each row keeps its context: action type, risk, deliveries protected, minutes saved, extra km, disruption type /
severity / duration and the weather.

A logistic regression (numpy, L2 = 10 – strong, because a branch makes few decisions – Newton steps) learns
P(accept | action, context). Recommendations
are ranked by P(accept) × impact, so what admins take and what matters most comes first. Until there are
20 learnable decisions with both outcomes, a smoothed acceptance rate per action type is used instead.
The model lives in the settings table (it survives a demo reset). Retrain from Insights, with
scripts/retrain_acceptance.py (cron, nightly) or automatically once a day by the API.
"""
import json
import math
from datetime import datetime, timedelta

import numpy as np

from modules import store

ACTION_TYPES = ("reassign", "reroute", "resequence", "reschedule_notify")
ACTION_LABEL = {"reassign": "Backup vehicle", "reroute": "Reroute", "resequence": "Prioritise",
                "reschedule_notify": "Notify customer", "optimised_plan": "Optimised plan"}
DISRUPTION_TYPES = ("accident", "closure", "flood", "traffic", "breakdown", "protest")
RISK_RANK = {"Low": 0, "Medium": 1, "High": 2, "Critical": 3}
SEVERITY_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}
LABEL = {"accepted": 1, "skipped": 0, "rejected": 0}
MIN_ROWS = 20
MODEL_KEY = "acceptance_model"
FEATURES = [*(f"type_{t}" for t in ACTION_TYPES), "risk", "protected", "saved_h", "extra_km10", "medical",
            *(f"cause_{t}" for t in DISRUPTION_TYPES), "cause_other", "severity", "duration_h", "rain"]
FEATURE_LABEL = {"type_reassign": "Backup vehicle", "type_reroute": "Reroute", "type_resequence": "Prioritise",
                 "type_reschedule_notify": "Notify customer", "risk": "Higher risk", "protected": "More deliveries",
                 "saved_h": "More minutes saved", "extra_km10": "More extra km", "medical": "Medical parcel",
                 "severity": "More severe", "duration_h": "Longer disruption", "rain": "Rain",
                 "cause_other": "Other cause", **{f"cause_{t}": t.capitalize() for t in DISRUPTION_TYPES}}


# ---------------------------------------------------------------- features
def context(plan):
    """What the decision was about: the disruption and today's weather."""
    from modules import predict

    disruption = plan.get("disruption") or {}
    return {"cause": disruption.get("type") or "unknown", "severity": disruption.get("severity") or "medium",
            "duration_min": int(disruption.get("duration_min") or 0), "rain": predict.weather_now() != "clear",
            "affected": int((plan.get("summary") or {}).get("affected_deliveries", 0))}


def action_features(action, plan):
    """Raw features of one recommendation in its plan."""
    priority = {r["delivery_id"]: r.get("priority") for r in plan.get("risk") or []}
    risk = {r["delivery_id"]: r.get("risk_label") for r in plan.get("risk") or []}
    protected = action.get("deliveries_protected") or []
    worst = max((RISK_RANK.get(risk.get(d) or action.get("risk_label"), 0) for d in protected),
                default=RISK_RANK.get(action.get("risk_label"), 0))
    return {"action_type": action["action_type"], "risk": worst, "protected": len(protected),
            "saved_min": float(action.get("expected_delay_saved_min") or 0),
            "extra_km": float(action.get("extra_km") or 0),
            "medical": any(priority.get(d) == "medical" for d in protected), **context(plan)}


def vector(raw):
    """Model inputs in FEATURES order."""
    cause = raw.get("cause")
    x = [float(raw["action_type"] == t) for t in ACTION_TYPES]
    x += [raw["risk"] / 3, math.log1p(raw["protected"]), raw["saved_min"] / 60, raw["extra_km"] / 10,
          float(raw["medical"])]
    x += [float(cause == t) for t in DISRUPTION_TYPES] + [float(cause not in DISRUPTION_TYPES)]
    x += [SEVERITY_RANK.get(raw.get("severity"), 1) / 3, raw.get("duration_min", 0) / 240, float(raw.get("rain"))]
    return x


def impact(action):
    """How much an action matters: minutes saved plus 10 per delivery it protects."""
    return float(action.get("expected_delay_saved_min") or 0) + 10 * len(action.get("deliveries_protected") or [])


# ---------------------------------------------------------------- the model
def _sigmoid(z):
    return 1 / (1 + np.exp(-np.clip(z, -30, 30)))


def fit(x, y, l2=10.0, iterations=50):
    """Logistic regression by Newton's method on standardised features. Returns (weights, bias, mean, std)."""
    x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    mean, std = x.mean(axis=0), x.std(axis=0)
    std[std == 0] = 1.0
    z = np.hstack([(x - mean) / std, np.ones((len(x), 1))])
    w = np.zeros(z.shape[1])
    penalty = np.eye(z.shape[1]) * l2
    penalty[-1, -1] = 0.0  # no penalty on the bias
    for _ in range(iterations):
        p = _sigmoid(z @ w)
        hessian = z.T @ (z * (p * (1 - p))[:, None]) + penalty
        step = np.linalg.solve(hessian, z.T @ (p - y) + penalty @ w)
        w -= step
        if np.abs(step).max() < 1e-7:
            break
    return w[:-1], float(w[-1]), mean, std


def _predict(model, x):
    z = (np.asarray(x, dtype=float) - np.asarray(model["mean"])) / np.asarray(model["std"])
    return _sigmoid(z @ np.asarray(model["weights"]) + model["bias"])


def roc_auc(labels, scores):
    """Area under the ROC curve (rank formula, ties averaged); None with one class only."""
    labels, scores = np.asarray(labels), np.asarray(scores, dtype=float)
    order = scores.argsort()
    ranks = np.empty(len(scores))
    ranks[order] = np.arange(1, len(scores) + 1)
    for value in np.unique(scores):  # average ranks of ties
        tied = scores == value
        ranks[tied] = ranks[tied].mean()
    pos, neg = (labels == 1).sum(), (labels == 0).sum()
    if not pos or not neg:
        return None
    return float((ranks[labels == 1].sum() - pos * (pos + 1) / 2) / (pos * neg))


def load_model():
    """The trained model (dict) or None."""
    text = store.get_setting(MODEL_KEY)
    try:
        model = json.loads(text) if text else None
    except ValueError:
        return None
    return model if model and model.get("features") == FEATURES else None


def _learnable(branch_id=None):
    log = store.decisions_df(branch_id)
    log = log[log["decision"].isin(list(LABEL)) & log["action_type"].isin(ACTION_TYPES)]
    return log.iloc[::-1]  # oldest first


def type_rates():
    """{action type: (accepted, decided)} over all learnable decisions."""
    log = _learnable()
    return {t: (int((log[log["action_type"] == t]["decision"] == "accepted").sum()),
                int((log["action_type"] == t).sum())) for t in ACTION_TYPES}


def p_accept(raw, model=None, rates=None):
    """Probability the admin takes this recommendation: the model, or the smoothed rate of its action type."""
    model = model if model is not None else load_model()
    if model:
        return float(_predict(model, [vector(raw)])[0])
    accepted, decided = (rates if rates is not None else type_rates()).get(raw["action_type"], (0, 0))
    return (accepted + 1) / (decided + 2)


def rank(actions, plan):
    """Add p_accept, impact and rank_score (= p_accept × impact) to each action; best first (stable)."""
    model, rates = load_model(), type_rates()
    for action in actions:
        p = p_accept(action_features(action, plan), model, rates) if action["action_type"] in ACTION_TYPES else 0.5
        action["p_accept"] = round(p, 3)
        action["p_source"] = "model" if model else "history" if rates.get(action["action_type"], (0, 0))[1] else "none"
        action["impact"] = round(impact(action), 1)
        action["rank_score"] = round(p * action["impact"], 1)
    return sorted(actions, key=lambda a: -a["rank_score"])


def train(actor=None, min_rows=MIN_ROWS):
    """Fit on every learnable decision (all branches), save to settings. Returns what happened."""
    log = _learnable()
    y = (log["decision"] == "accepted").astype(int).to_numpy()
    if len(log) < min_rows or len(set(y)) < 2:
        return {"trained": False, "rows": int(len(log)),
                "reason": f"Needs {min_rows} decisions with both accepted and turned-down ones ({len(log)} so far)."}
    x = np.array([vector(json.loads(f)) for f in log["features"]])
    metrics = {}
    cut = int(len(log) * 0.8)
    if len(log) >= 30 and len(set(y[:cut])) == 2 and len(set(y[cut:])) == 2:  # time-ordered holdout: last 20 %
        w, b, mean, std = fit(x[:cut], y[:cut])
        held = _predict({"weights": w.tolist(), "bias": b, "mean": mean.tolist(), "std": std.tolist()}, x[cut:])
        metrics = {"holdout_rows": int(len(y) - cut), "holdout_accuracy": round(float(((held >= 0.5) == y[cut:])
                                                                                     .mean()), 3),
                   "holdout_auc": roc_auc(y[cut:], held)}
    w, b, mean, std = fit(x, y)
    model = {"features": FEATURES, "weights": [round(v, 6) for v in w.tolist()], "bias": round(b, 6),
             "mean": mean.tolist(), "std": std.tolist(), "rows": int(len(y)), "accepted": int(y.sum()),
             "trained_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "metrics": metrics}
    train_p = _predict(model, x)
    model["metrics"].update({"train_accuracy": round(float(((train_p >= 0.5) == y).mean()), 3),
                             "train_auc": roc_auc(y, train_p)})
    store.set_setting(MODEL_KEY, json.dumps(model), (actor or {}).get("user_id", "system"))
    store.audit((actor or {}).get("user_id", "system"), "acceptance_model_trained", "learning",
                {"rows": model["rows"], **model["metrics"]})
    return {"trained": True, **{k: model[k] for k in ("rows", "accepted", "trained_at", "metrics")}}


def maybe_retrain(max_age_hours=24):
    """Nightly job: retrain when the model is older than a day and new decisions came in."""
    model = load_model()
    log = _learnable()
    if model:
        age = datetime.now() - datetime.strptime(model["trained_at"], "%Y-%m-%d %H:%M:%S")
        if age < timedelta(hours=max_age_hours) or len(log) <= model["rows"]:
            return {"trained": False, "reason": "Model is fresh or there is nothing new."}
    return train()


def drivers(model=None, top=3):
    """What pushes admins to accept (+) or turn down (−): the strongest standardised weights, labelled."""
    model = model or load_model()
    if not model:
        return [], []
    pairs = sorted(zip(model["weights"], model["features"]), reverse=True)
    up = [(FEATURE_LABEL.get(f, f), round(w, 2)) for w, f in pairs[:top] if w > 0]
    down = [(FEATURE_LABEL.get(f, f), round(w, 2)) for w, f in reversed(pairs[-top:]) if w < 0]
    return up, down


# ---------------------------------------------------------------- logging decisions
def record(issue, plan, decision, decided_by, actions=None, reason="", source="app"):
    """Log one decision for each recommendation (actions default to all of the plan's)."""
    model, rates = load_model(), type_rates()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows = []
    for action in actions if actions is not None else plan.get("actions") or []:
        raw = action_features(action, plan) if action["action_type"] in ACTION_TYPES else {
            "action_type": action["action_type"], **context(plan)}
        rows.append({"time": now, "branch_id": issue["branch_id"], "issue_id": issue["issue_id"],
                     "decided_by": decided_by, "decision": decision,
                     "action_key": f"{action['action_type']}|{action.get('target', '')}",
                     "action_type": action["action_type"], "title": action.get("title") or action.get("description"),
                     "reason": str(reason or "")[:200], "features": json.dumps(raw),
                     "p_accept": p_accept(raw, model, rates) if action["action_type"] in ACTION_TYPES else None,
                     "source": source})
    if rows:
        store.add_decisions(rows)
    return len(rows)


# ---------------------------------------------------------------- insights
def insights(branch_id):
    """Numbers for the Insights page (one branch)."""
    log = store.decisions_df(branch_id)
    by_type = []
    for action_type in (*ACTION_TYPES, "optimised_plan"):
        rows = log[log["action_type"] == action_type]
        if not len(rows):
            continue
        counts = rows["decision"].value_counts().to_dict()
        taken = counts.get("accepted", 0) + counts.get("chosen", 0)
        decided = taken + counts.get("skipped", 0) + counts.get("rejected", 0) + counts.get("not_chosen", 0)
        by_type.append({"action_type": action_type, "label": ACTION_LABEL[action_type], "taken": int(taken),
                        "decided": int(decided), "rate": round(taken / decided, 3) if decided else None,
                        "skipped": int(counts.get("skipped", 0)), "rejected": int(counts.get("rejected", 0)),
                        "modified": int(counts.get("modified", 0)), "replaced": int(counts.get("replaced", 0))})
    changed = log[log["decision"].isin(["modified", "skipped"])]
    most_changed = (changed.groupby(["action_type", "decision"]).size().reset_index(name="times")
                    .sort_values("times", ascending=False).head(8).to_dict("records")) if len(changed) else []
    plans = log.drop_duplicates(["issue_id", "decision"])
    model = load_model()
    return {"decisions": int(len(log)), "learnable": int(log["decision"].isin(list(LABEL)).sum()),
            "plans_accepted": int(plans[plans["decision"].isin(["accepted", "replaced"])]["issue_id"].nunique()),
            "plans_rejected": int(plans[plans["decision"] == "rejected"]["issue_id"].nunique()),
            "sample_rows": int((log["source"] == "sample").sum()), "by_type": by_type, "most_changed": most_changed,
            "recent": log.head(12).to_dict("records"), "model": model, "drivers": drivers(model)}


def sample_history(branch_id, n=150, seed=7):
    """Demo: n synthetic past decisions (source "sample") with believable habits – backup vehicles for medical
    parcels are nearly always taken, long reroutes are often skipped, notices are almost always fine, plans for
    low-severity problems get rejected more."""
    rng = np.random.default_rng(seed)
    start = datetime.now() - timedelta(days=30)
    rows = []
    for i in range(n):
        action_type = rng.choice(ACTION_TYPES, p=[0.25, 0.3, 0.2, 0.25])
        severity = rng.choice(list(SEVERITY_RANK), p=[0.15, 0.35, 0.3, 0.2])
        raw = {"action_type": str(action_type), "risk": int(rng.integers(0, 4)), "protected": int(rng.integers(1, 5)),
               "saved_min": float(rng.integers(0, 90)), "extra_km": float(rng.uniform(0, 9)),
               "medical": bool(rng.random() < 0.3), "cause": str(rng.choice(DISRUPTION_TYPES)),
               "severity": str(severity), "duration_min": int(rng.choice([30, 60, 120, 180])),
               "rain": bool(rng.random() < 0.3), "affected": int(rng.integers(2, 12))}
        logit = (-0.2 + 1.6 * raw["medical"] * (action_type == "reassign") - 0.35 * raw["extra_km"] / 2
                 + 1.8 * (action_type == "reschedule_notify") + 0.03 * raw["saved_min"]
                 + 0.5 * raw["risk"] - 1.2 * (severity == "low"))
        accepted = rng.random() < 1 / (1 + math.exp(-logit))
        decision = "accepted" if accepted else ("rejected" if severity == "low" and rng.random() < 0.5 else "skipped")
        when = (start + timedelta(hours=12 * i)).strftime("%Y-%m-%d %H:%M:%S")
        rows.append({"time": when, "branch_id": branch_id, "issue_id": None, "decided_by": "sample",
                     "decision": decision, "action_key": f"{action_type}|sample {i}", "action_type": str(action_type),
                     "title": f"{ACTION_LABEL[str(action_type)]} (sample)",
                     "reason": "Not needed" if decision == "rejected" else "", "features": json.dumps(raw),
                     "p_accept": None, "source": "sample"})
    store.add_decisions(rows)
    return len(rows)
