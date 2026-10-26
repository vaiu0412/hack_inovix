"""Summarise the (synthetic) delivery history for the Analytics page -> models/history_summary.json.

- delays by road and hour of day (mean minutes late, deliveries)
- service level per day (share delivered by the deadline)
- prediction accuracy on the test days, scored with the app's exported models: MAE per road and a
  reliability table (predicted chance of being late vs how often it really was)

ml/data/history.csv is not in git, so the small summary is. It uses the exported JSON models (no LightGBM).

Run:  python ml/summarise_history.py        (ml/train_delay.py also runs it after training)
"""
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ml.generate_history import OUT as HISTORY  # noqa: E402
from modules import predict  # noqa: E402

SUMMARY = "history_summary.json"
TEST_DAYS = 12  # the same test days as ml/train_delay.py
BINS = [0, .1, .2, .3, .4, .5, .6, .7, .8, .9, 1.0001]


def summarise(history):
    history = history.assign(hour_of_day=history["hour"].astype(int))
    by_road_hour = (history.groupby(["road_id", "hour_of_day"])["delay_min"].agg(["mean", "size"]).reset_index())
    by_day = history.groupby("date")["late"].agg(["mean", "size"]).reset_index()

    last = date.fromisoformat(history["date"].max())
    test = history[history["date"] >= (last - timedelta(days=TEST_DAYS - 1)).isoformat()]
    regressor, classifier = predict.model(predict.REGRESSOR), predict.model(predict.CLASSIFIER)
    rows = test.to_dict("records")
    test = test.assign(pred_delay=[regressor.predict(predict.encode(r)) for r in rows],
                       p_late=[classifier.predict(predict.encode(r, with_slack=True)) for r in rows])
    test = test.assign(error=(test["pred_delay"] - test["delay_min"]).abs(),
                       bin=pd.cut(test["p_late"], BINS, right=False, labels=False))
    by_road = test.groupby("road_id")["error"].agg(["mean", "size"]).reset_index()
    reliability = test.groupby("bin").agg(predicted=("p_late", "mean"), actual=("late", "mean"),
                                          n=("late", "size")).reset_index()
    return {
        "synthetic": True,
        "source": str(HISTORY.relative_to(ROOT)).replace("\\", "/"),
        "rows": len(history), "days": int(history["date"].nunique()),
        "from": history["date"].min(), "to": history["date"].max(),
        "delay_by_road_hour": [{"road": r.road_id, "hour": int(r.hour_of_day), "delay_min": round(float(r.mean), 2),
                                "n": int(r.size)} for r in by_road_hour.itertuples()],
        "sla_by_day": [{"date": r.date, "on_time": round(1 - float(r.mean), 4), "n": int(r.size)}
                       for r in by_day.itertuples()],
        "accuracy": {
            "test_from": test["date"].min(), "test_to": test["date"].max(), "test_rows": len(test),
            "mae_min": round(float(test["error"].mean()), 2),
            "mae_by_road": [{"road": r.road_id, "mae_min": round(float(r.mean), 2), "n": int(r.size)}
                            for r in by_road.itertuples()],
            "reliability": [{"from": BINS[int(r.bin)], "to": min(BINS[int(r.bin) + 1], 1.0),
                             "predicted": round(float(r.predicted), 3), "actual": round(float(r.actual), 3),
                             "n": int(r.n)} for r in reliability.itertuples()],
            "brier": round(float(np.mean((test["p_late"] - test["late"]) ** 2)), 4),
        },
    }


def main():
    if not predict.available():
        raise SystemExit("No exported models in models/ – run ml/train_delay.py first.")
    summary = summarise(pd.read_csv(HISTORY))
    (predict.MODEL_DIR / SUMMARY).write_text(json.dumps(summary, indent=1), encoding="utf-8")
    acc = summary["accuracy"]
    print(f"summary: {summary['rows']} rows, {summary['days']} days · test MAE {acc['mae_min']} min "
          f"· Brier {acc['brier']} -> models/{SUMMARY}")
    return summary


if __name__ == "__main__":
    main()
