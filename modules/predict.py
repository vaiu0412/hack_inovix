"""Delay prediction: how late will a delivery be, and how likely is it to miss its deadline? No Streamlit imports.

Two LightGBM models are trained by ml/train_delay.py on 60 days of synthetic history (ml/generate_history.py):
- regressor:  minutes late compared with the planned ETA
- classifier: probability of missing the deadline (it also sees the slack: deadline minus planned ETA)
They are exported to small JSON files in models/ and scored here by a tiny tree evaluator, so the app needs no
LightGBM at runtime. Every prediction comes with its top reasons ("Rain · Peak hour"): the path contributions of
each feature group in the classifier's trees. Without the model files, rule-based estimates are used instead
(same outputs, source "rules").

Used by: the impact engine (extra delay from today's weather on top of the plan), the "Likely late" list (before
anyone reports a problem) and assignment scoring.
"""
import json
import math
from datetime import date
from functools import lru_cache
from pathlib import Path

import pandas as pd

from modules import store
from modules.data_loader import NOW_MIN, haversine_km

MODEL_DIR = Path(__file__).resolve().parent.parent / "models"
REGRESSOR, CLASSIFIER, META = "delay_regressor.json", "late_classifier.json", "delay_model.meta.json"

ROADS = ("R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8", "R9", "R10")
ROAD_SHORT = {"R1": "Avinashi Rd", "R2": "Trichy Rd", "R3": "Mettupalayam Rd", "R4": "Sathy Rd", "R5": "Pollachi Rd",
              "R6": "DB Rd", "R7": "100 Feet Rd", "R8": "Race Course Rd", "R9": "Hope College", "R10": "Town Hall Rd"}
VEHICLES = ("bike", "car", "van", "truck")
CATEGORIES = ("Parcel", "Food", "Medicine", "Groceries", "Documents", "Electronics")
CATEGORY_OF_PRIORITY = {"medical": "Medicine", "perishable": "Food", "express": "Parcel", "standard": "Parcel"}
NUMERIC = ("hour", "weekday", "is_weekend", "rain_mm", "distance_km", "stops_before", "experience_months")
FEATURES = [*NUMERIC, *(f"road_{r}" for r in ROADS), *(f"vehicle_{v}" for v in VEHICLES),
            *(f"cat_{c}" for c in CATEGORIES)]
CLASSIFIER_FEATURES = [*FEATURES, "slack_min"]
WEATHER = {"clear": 0.0, "light_rain": 2.5, "heavy_rain": 12.0}  # mm of rain per hour
WEATHER_LABEL = {"clear": "Clear", "light_rain": "Light rain", "heavy_rain": "Heavy rain"}
PEAK = ((8, 10), (17, 20))
LATE_AT = 0.5  # probability from which a delivery counts as "likely late"


def is_peak(hour):
    """8–10 and 17–20 are Coimbatore's rush hours."""
    return any(start <= hour < end for start, end in PEAK)


def _group(feature):
    for prefix, group in (("road_", "road"), ("vehicle_", "vehicle"), ("cat_", "category")):
        if feature.startswith(prefix):
            return group
    return {"weekday": "day", "is_weekend": "day", "rain_mm": "rain", "distance_km": "distance",
            "stops_before": "stops", "experience_months": "experience", "slack_min": "slack"}.get(feature, feature)


def encode(raw, with_slack=False):
    """Model inputs (a list in FEATURES order) from one raw row: {road_id, hour, weekday, rain_mm, distance_km,
    stops_before, vehicle_type, category, experience_months[, slack_min]}.
    Shared by training and the app, so both always see the same features."""
    weekday = int(raw["weekday"])
    x = [float(raw["hour"]), float(weekday), float(weekday >= 5), float(raw["rain_mm"]), float(raw["distance_km"]),
         float(raw["stops_before"]), float(raw["experience_months"])]
    x += [float(raw["road_id"] == r) for r in ROADS]
    x += [float(raw["vehicle_type"] == v) for v in VEHICLES]
    x += [float(raw["category"] == c) for c in CATEGORIES]
    if with_slack:
        x.append(float(raw["slack_min"]))
    return x


# ---------------------------------------------------------------- the exported models
class Forest:
    """A LightGBM model exported by ml/train_delay.py: each tree as flat lists (feature, threshold, left, right,
    value, default_left; feature -1 = leaf). Scored with plain Python – no LightGBM needed."""

    def __init__(self, spec):
        self.objective = spec["objective"]
        self.features = spec["features"]
        self.trees = spec["trees"]

    def _leaf_path(self, tree, x):
        node, path = 0, [0]
        while tree["f"][node] >= 0:
            value = x[tree["f"][node]]
            go_left = tree["d"][node] if math.isnan(value) else value <= tree["t"][node]
            node = tree["l"][node] if go_left else tree["r"][node]
            path.append(node)
        return path

    def raw(self, x):
        """Sum of the trees (log-odds for the classifier, minutes for the regressor)."""
        return sum(tree["v"][self._leaf_path(tree, x)[-1]] for tree in self.trees)

    def contributions(self, x):
        """(raw score, {feature group: contribution}) – how much each group pushed this prediction up or down."""
        bias, groups = 0.0, {}
        for tree in self.trees:
            path = self._leaf_path(tree, x)
            bias += tree["v"][0]
            for parent, child in zip(path, path[1:]):
                group = _group(self.features[tree["f"][parent]])
                groups[group] = groups.get(group, 0.0) + tree["v"][child] - tree["v"][parent]
        return bias + sum(groups.values()), groups

    def predict(self, x):
        """Minutes (regressor) or probability (classifier)."""
        raw = self.raw(x)
        return 1 / (1 + math.exp(-raw)) if self.objective == "binary" else raw


@lru_cache(maxsize=4)
def _load(name, stamp):
    path = MODEL_DIR / name
    return Forest(json.loads(path.read_text(encoding="utf-8")))


def model(name):
    """The exported model, or None when the file is missing or broken (then rules are used)."""
    path = MODEL_DIR / name
    try:
        return _load(name, path.stat().st_mtime)
    except (OSError, ValueError, KeyError):
        return None


def available():
    """True when both model files load."""
    return model(REGRESSOR) is not None and model(CLASSIFIER) is not None


def metadata():
    """Training facts (date, rows, metrics, feature importance) or {} without a model."""
    try:
        return json.loads((MODEL_DIR / META).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


# ---------------------------------------------------------------- rule-based fallback
def rule_delay(raw):
    """Minutes late from simple rules: rush hour, rain, the road, stops before, distance, vehicle, partner."""
    hour, rain = float(raw["hour"]), float(raw["rain_mm"])
    terms = {"hour": 6.0 if is_peak(hour) else -1.0,
             "road": (5.0 if is_peak(hour) else 2.0) if raw["road_id"] == "R1" else 0.0,
             "rain": 0.0 if rain <= 0 else 4.0 if rain < 7 else 12.0,
             "stops": 1.2 * float(raw["stops_before"]), "distance": 0.4 * float(raw["distance_km"]),
             "vehicle": {"bike": -2.0, "truck": 3.0}.get(raw["vehicle_type"], 0.0) if is_peak(hour) else 0.0,
             "category": 2.0 if raw["category"] in ("Medicine", "Electronics") else 0.0,
             "experience": 3.0 if float(raw["experience_months"]) < 6 else 0.0}
    return sum(terms.values()), terms


# ---------------------------------------------------------------- predictions
def _label(group, raw):
    """Short reason text for a feature group, for this row."""
    hour, rain = float(raw["hour"]), float(raw["rain_mm"])
    return {
        "hour": "Peak hour" if is_peak(hour) else "Time of day",
        "day": "Weekend" if int(raw["weekday"]) >= 5 else "Weekday traffic",
        "rain": "Heavy rain" if rain >= 7 else "Rain" if rain > 0 else "Weather",
        "distance": "Long way",
        "stops": f"{int(raw['stops_before'])} stops before",
        "experience": "New partner" if float(raw["experience_months"]) < 6 else "Partner pace",
        "road": f"{ROAD_SHORT.get(raw['road_id'], raw['road_id'])} traffic",
        "vehicle": f"{str(raw['vehicle_type']).capitalize()} in traffic",
        "category": f"{raw['category']} handover",
        "slack": "Tight deadline",
    }.get(group, group)


def _reasons(groups, raw, top=2):
    pushing = sorted(((v, g) for g, v in groups.items() if v > 0.02), reverse=True)
    return [_label(g, raw) for _, g in pushing[:top]]


def predict_rows(raws):
    """For each raw row: {delay_min, p_late, reasons, source}. Model when available, otherwise rules."""
    regressor, classifier = model(REGRESSOR), model(CLASSIFIER)
    out = []
    for raw in raws:
        if regressor is not None and classifier is not None:
            delay = regressor.predict(encode(raw))
            logit, groups = classifier.contributions(encode(raw, with_slack=True))
            p_late, source = 1 / (1 + math.exp(-logit)), "model"
        else:
            delay, terms = rule_delay(raw)
            groups = dict(terms, slack=max(0.0, delay - float(raw["slack_min"])) / 6)
            p_late, source = 1 / (1 + math.exp(-(delay - float(raw["slack_min"])) / 6)), "rules"
        out.append({"delay_min": round(delay, 1), "p_late": round(p_late, 3), "reasons": _reasons(groups, raw),
                    "source": source})
    return out


def predict_delay(raw):
    """One delivery: {delay_min, p_late, reasons, source}."""
    return predict_rows([raw])[0]


# ---------------------------------------------------------------- live inputs from the app's data
def weather_now():
    """Current weather key: clear, light_rain or heavy_rain (set on Command Center until live weather is wired)."""
    value = store.get_setting("weather_now", "clear")
    return value if value in WEATHER else "clear"


def set_weather(actor, key):
    """Branch or Super Admin sets today's weather for the city (Demo mode)."""
    if not actor or actor.get("role") not in ("branch_admin", "super_admin"):
        raise PermissionError("Admins only")
    if key not in WEATHER:
        raise ValueError(f"Unknown weather {key}")
    store.set_setting("weather_now", key, actor["user_id"])
    store.audit(actor["user_id"], "weather_set", key, {"weather": key}, actor.get("branch_id"))


def live_rows(deliveries, vehicles, rain_mm=None, weekday=None):
    """Raw model inputs for every open delivery on a vehicle: the hour of its ETA, distance from the stop before
    (or the vehicle), stops before it, vehicle type, partner experience, category and slack.
    Returns {delivery_id: raw row}."""
    rain_mm = WEATHER[weather_now()] if rain_mm is None else rain_mm
    weekday = date.today().weekday() if weekday is None else weekday
    vehicles = vehicles.set_index("vehicle_id")
    done = (deliveries["status"].isin(store.ACTIVE_DONE) if "status" in deliveries
            else pd.Series(False, index=deliveries.index))
    open_ = deliveries[deliveries["vehicle_id"].notna() & ~done]
    out = {}
    for vehicle_id, own in open_.groupby("vehicle_id"):
        if vehicle_id not in vehicles.index:
            continue
        v = vehicles.loc[vehicle_id]
        experience = v.get("experience_months", 12)
        if experience is None or (isinstance(experience, float) and math.isnan(experience)):
            experience = 12  # a vehicle without a partner record
        prev = (float(v["current_lat"]), float(v["current_lng"]))
        for i, d in enumerate(own.sort_values(["eta_min", "stop_order"]).to_dict("records")):
            here = (float(d["lat"]), float(d["lng"]))
            category = d.get("category") or CATEGORY_OF_PRIORITY.get(d.get("priority"), "Parcel")
            out[d["delivery_id"]] = {
                "road_id": d.get("road_id"), "hour": max(float(d["eta_min"]), NOW_MIN) / 60, "weekday": weekday,
                "rain_mm": rain_mm, "distance_km": round(haversine_km(*prev, *here), 2), "stops_before": i,
                "vehicle_type": v["type"], "category": category if category in CATEGORIES else "Parcel",
                "experience_months": float(experience), "slack_min": float(d["deadline_min"] - d["eta_min"]),
            }
            prev = here
    return out


def weather_extra(delivery_ids, data):
    """Extra minutes today's weather adds to each delivery on top of its plan (the plan assumes a dry day):
    model delay now minus model delay on a clear day. {} when it is clear."""
    rain = WEATHER[weather_now()]
    if rain <= 0 or not delivery_ids:
        return {}
    rows = live_rows(data["deliveries"], data["vehicles"], rain_mm=rain)
    ids = [i for i in delivery_ids if i in rows]
    wet = predict_rows([rows[i] for i in ids])
    dry = predict_rows([dict(rows[i], rain_mm=0.0) for i in ids])
    return {i: max(0, round(w["delay_min"] - d["delay_min"])) for i, w, d in zip(ids, wet, dry)}


def likely_late(branch_id, threshold=LATE_AT):
    """Open deliveries of a branch most likely to miss their deadline – before anyone reports a problem.
    DataFrame with p_late, delay_min, reasons; highest risk first."""
    data = store.snapshot(branch_id)
    rows = live_rows(data["deliveries"], data["vehicles"])
    if not rows:
        return pd.DataFrame(columns=["delivery_id", "p_late", "delay_min", "reasons", "source"])
    preds = predict_rows(list(rows.values()))
    table = pd.DataFrame([{"delivery_id": i, **p} for i, p in zip(rows, preds)])
    table = table.merge(data["deliveries"], on="delivery_id")
    return table[table["p_late"] >= threshold].sort_values("p_late", ascending=False).reset_index(drop=True)


def for_branch(branch_id):
    """{delivery_id: prediction} for every open delivery of a branch (Deliveries table, partner app)."""
    data = store.snapshot(branch_id)
    rows = live_rows(data["deliveries"], data["vehicles"])
    return dict(zip(rows, predict_rows(list(rows.values()))))


def summary_line():
    """'Model: MAE 4.1 min · AUC 0.86' or 'Rules (no model file)'."""
    meta = metadata()
    if not available() or not meta:
        return "Rules (no model file)"
    metrics = meta.get("metrics", {})
    return f"LightGBM · MAE {metrics.get('mae_min', '?')} min · AUC {metrics.get('roc_auc', '?')}"
