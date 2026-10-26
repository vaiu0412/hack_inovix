"""Synthetic but realistic delivery history for Coimbatore – 60 days – to train the delay models.

Each row is one delivery: road, time of day, weekday, rain, distance from the previous stop, stops before it,
vehicle type, parcel category and partner experience -> actual minutes late vs the plan, and whether it missed its
deadline. The plan assumes average city speed on a dry day; reality follows these patterns:

- rush hours 8–10 and 17–20 (lighter at the weekend, lightest on Sunday)
- Avinashi Road is the most congested road, worst in rush hour; 100 Feet Road and Town Hall are next
- rain slows everyone (heavy rain much more); riders slow down most in heavy rain
- bikes filter through traffic (smaller rush-hour penalty); trucks and vans are slower in it
- every earlier stop adds drift; electronics and medicine take longer to hand over; new partners are slower
- rare incidents (more likely on Avinashi Road in rush hour and in heavy rain), plus noise

Fixed seed, so the same file is produced every time. Output: ml/data/history.csv (not committed).
Run:  python ml/generate_history.py
"""
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from modules.predict import CATEGORIES, ROADS, VEHICLES  # noqa: E402

OUT = ROOT / "ml" / "data" / "history.csv"
DAYS, START, SEED = 60, date(2026, 8, 1), 2026
ROAD_WEIGHT = dict(zip(ROADS, (18, 10, 9, 8, 8, 9, 12, 8, 8, 10)))
ROAD_TRAFFIC = dict(zip(ROADS, (1.35, 1.12, 1.10, 1.05, 1.05, 1.00, 1.22, 0.95, 1.00, 1.25)))
VEHICLE_WEIGHT = dict(zip(VEHICLES, (45, 15, 30, 10)))
VEHICLE_SPEED = {"bike": 1.0, "car": 1.0, "van": 0.92, "truck": 0.85}
VEHICLE_IN_TRAFFIC = {"bike": 0.6, "car": 1.0, "van": 1.1, "truck": 1.25}  # share of the rush-hour penalty
CATEGORY_WEIGHT = dict(zip(CATEGORIES, (35, 20, 12, 15, 10, 8)))
HANDOVER_EXTRA = {"Parcel": 0.0, "Food": -1.0, "Medicine": 2.5, "Groceries": 1.0, "Documents": 1.0,
                  "Electronics": 3.0}
PLAN_SPEED_KMPH, PLAN_HANDOVER_MIN = 24.0, 4.0


def rush(hour, weekday):
    """Extra congestion share for this time (0 = free-flowing)."""
    if 8 <= hour < 10:
        extra = 0.55
    elif 17 <= hour < 20:
        extra = 0.65
    elif 10 <= hour < 11 or 16 <= hour < 17 or 20 <= hour < 21:
        extra = 0.2
    else:
        extra = -0.1
    if weekday == 6:
        extra *= 0.35
    elif weekday == 5:
        extra *= 0.5
    return extra


def day_weather(rng):
    """(start hour, end hour, mm per hour) of today's rain, or None for a dry day."""
    if rng.random() > 0.3:
        return None
    start = rng.uniform(6, 10) if rng.random() < 0.25 else rng.uniform(13, 19)
    heavy = rng.random() < 0.3
    return start, start + rng.uniform(1, 5), rng.uniform(7, 20) if heavy else rng.uniform(0.8, 5)


def generate(days=DAYS, start=START, seed=SEED, per_day=420):
    """The history as a DataFrame (one row per delivery)."""
    rng = np.random.default_rng(seed)
    partners = [{"id": f"P{i:02d}", "vehicle": rng.choice(VEHICLES, p=_p(VEHICLE_WEIGHT)),
                 "experience": int(rng.integers(1, 73))} for i in range(40)]
    by_vehicle = {v: [p for p in partners if p["vehicle"] == v] for v in VEHICLES}
    hours = np.arange(8, 22)
    hour_weight = np.array([9, 10, 8, 7, 6, 6, 6, 6, 7, 8, 9, 8, 6, 4], dtype=float)
    rows = []
    for offset in range(days):
        day = start + timedelta(days=offset)
        weekday, rain = day.weekday(), day_weather(rng)
        for _ in range(rng.poisson(per_day * (0.8 if weekday == 6 else 1.0))):
            hour = float(rng.choice(hours, p=hour_weight / hour_weight.sum()) + rng.random())
            road = rng.choice(ROADS, p=_p(ROAD_WEIGHT))
            vehicle = rng.choice(VEHICLES, p=_p(VEHICLE_WEIGHT))
            pool = by_vehicle[vehicle] or partners
            partner = pool[rng.integers(len(pool))]
            category = rng.choice(CATEGORIES, p=_p(CATEGORY_WEIGHT))
            stops_before = int(min(rng.geometric(0.22) - 1, 12))
            distance = float(np.clip(rng.lognormal(np.log(2.2 if vehicle == "bike" else 3.0), 0.55), 0.3, 14))
            rain_mm = rain[2] if rain and rain[0] <= hour < rain[1] else 0.0
            delay = _delay(rng, hour, weekday, road, vehicle, category, stops_before, distance, rain_mm,
                           partner["experience"])
            slack = float(rng.uniform(-5, 10) if rng.random() < 0.15 else rng.exponential(35) + 5)
            rows.append({"date": day.isoformat(), "road_id": road, "hour": round(hour, 2), "weekday": weekday,
                         "rain_mm": round(rain_mm, 1), "distance_km": round(distance, 2), "stops_before": stops_before,
                         "vehicle_type": vehicle, "category": category, "experience_months": partner["experience"],
                         "partner_id": partner["id"], "slack_min": round(slack, 1), "delay_min": round(delay, 1),
                         "late": int(delay > slack)})
    return pd.DataFrame(rows)


def _p(weights):
    values = np.array(list(weights.values()), dtype=float)
    return values / values.sum()


def _delay(rng, hour, weekday, road, vehicle, category, stops_before, distance, rain_mm, experience):
    """Actual minus planned minutes for one delivery."""
    congestion = 1 + rush(hour, weekday) * VEHICLE_IN_TRAFFIC[vehicle]
    traffic = ROAD_TRAFFIC[road] * (1.25 if road == "R1" and rush(hour, weekday) > 0.3 else 1.0)
    wet = 1.0 if rain_mm <= 0 else 0.85 if rain_mm < 7 else 0.65 * (0.85 if vehicle == "bike" else 1.0)
    speed = 26 * VEHICLE_SPEED[vehicle] * wet / (congestion * traffic)
    travel = distance / speed * 60
    handover = (PLAN_HANDOVER_MIN + HANDOVER_EXTRA[category]) * (1.3 if experience < 6 else 0.85 if experience > 36
                                                                  else 1.0)
    drift = stops_before * rng.uniform(0.4, 1.4) * congestion
    incident_chance = 0.02 + (0.03 if road == "R1" and rush(hour, weekday) > 0.3 else 0) + (0.02 if rain_mm >= 7 else 0)
    incident = rng.uniform(15, 60) if rng.random() < incident_chance else 0.0
    planned = distance / PLAN_SPEED_KMPH * 60 + PLAN_HANDOVER_MIN
    noise = rng.normal(0, 2 + 0.12 * travel)
    return travel + handover + drift + incident + noise - planned


def main():
    history = generate()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    history.to_csv(OUT, index=False)
    print(f"wrote {OUT.relative_to(ROOT)}: {len(history)} deliveries, {history['date'].nunique()} days, "
          f"late {history['late'].mean():.0%}, mean delay {history['delay_min'].mean():+.1f} min, "
          f"rush-hour delay {history[history['hour'].between(8, 10, inclusive='left')]['delay_min'].mean():+.1f} min, "
          f"rain delay {history[history['rain_mm'] > 0]['delay_min'].mean():+.1f} min")


if __name__ == "__main__":
    main()
