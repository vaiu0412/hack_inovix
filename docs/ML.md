# Delay prediction model

Two LightGBM models answer, for every open stop: **how many minutes late will it be** (regressor) and **how likely
is it to miss its deadline** (classifier). Each prediction comes with its top two reasons, e.g. *Heavy rain ·
Avinashi Rd traffic*.

## Data
`ml/generate_history.py` writes 60 days of **synthetic** delivery history for Coimbatore (fixed seed, 24,639
deliveries, 19 % late) to `ml/data/history.csv` (not committed). The plan assumes average city speed on a dry
day; the "real" outcome follows these patterns:

| Pattern | How it is simulated |
|---|---|
| Rush hours | 8–10 and 17–20 add congestion (half at the weekend, a third on Sunday) |
| Avinashi Road | the most congested road, 25 % worse again in rush hour; 100 Feet Rd and Town Hall next |
| Rain | light rain −15 % speed, heavy rain −35 % (riders slow down most) on 30 % of days |
| Vehicle | bikes take 60 % of the rush-hour penalty, trucks 125 % and drive slower |
| Stops before | each earlier stop adds drift, more in traffic |
| Handover | electronics +3 min, medicine +2.5 min, food −1 min; new partners (< 6 months) 30 % slower |
| Incidents | 2–7 % chance of +15–60 min (Avinashi Rd rush hour and heavy rain raise it), plus noise |

## Features
| Feature | Meaning |
|---|---|
| `hour`, `weekday`, `is_weekend` | when the stop is due (planned ETA) |
| `rain_mm` | rain now (Clear 0 / Light rain 2.5 / Heavy rain 12 mm per hour) |
| `distance_km` | from the stop before (or the vehicle) |
| `stops_before` | open stops before this one on the same vehicle |
| `experience_months` | the partner's experience |
| `road_*`, `vehicle_*`, `cat_*` | road (10), vehicle type (4), parcel category (6), one-hot |
| `slack_min` (classifier only) | deadline minus planned ETA |

One function, `modules.predict.encode`, builds these for training and for the app, so they can't drift apart.

## Training and results
`ml/train_delay.py`: split **by date** – the last 12 days are the test set, the 7 days before them stop training
early. LightGBM, 15 leaves, learning rate 0.05, deterministic.

| Test set (12 days, 4,846 deliveries) | Model | Baseline |
|---|---|---|
| Regressor MAE | **3.85 min** (RMSE 7.11) | 4.75 rules · 8.12 "the plan is right" |
| Classifier ROC-AUC | **0.965** (accuracy 0.93 at 50 %) | 0.957 rules |

The classifier's lead over the rules is small because the slack carries most of the signal (66 % of the gain):
anyone can tell a stop with 5 minutes to spare is at risk. The model's value is in the minutes – where rush hour,
rain, stops and the road meet.

What drives the predictions (share of LightGBM gain):

| Regressor | | Classifier | |
|---|---|---|---|
| hour | 28 % | slack | 66 % |
| stops before | 27 % | hour | 10 % |
| distance | 17 % | stops before | 9 % |
| road | 10 % | distance | 6 % |
| vehicle | 5 % | road | 3 % |
| day, rain, category, experience | 13 % | the rest | 6 % |

Mean |SHAP| (TreeSHAP) per group is saved too: `models/delay_model.meta.json`.

## In the app
- **No LightGBM at runtime.** The models are exported to `models/delay_regressor.json` and
  `models/late_classifier.json` (≈ 390 KB) and scored by a small tree evaluator in `modules/predict.py`. Training
  checks the export against LightGBM (max difference 9e-7); `tests/test_predict.py` checks it again.
- **Reasons** = path contributions of each feature group in the classifier's trees (the top two that push the
  risk up), mapped to short labels.
- **No model file → rules.** If the JSON files are missing or broken, a rule-based estimate gives the same outputs
  (source "rules"); the caption on Command Center says which one is active.

Where it is used:

| Place | What it does |
|---|---|
| Command Center → **Likely late** | the riskiest open stops before anyone reports a problem; red *Predicted late 72%* from 50 % |
| Weather switch (same card) | Clear / Light rain / Heavy rain – a demo setting until live weather is connected |
| Impact engine | when it rains, adds the minutes rain costs each hit stop as a "weather" part (no reroute removes it); on a dry day nothing changes, so the demo numbers stay the same |
| Assign Work | each candidate's ETA gets the predicted delay for that partner, road, hour and weather: it counts in "can it make the deadline" and in the score (*· +6 min likely*) |
| Deliveries | *Late risk* column and the badge in the side panel |
| Partner app | *Predicted late* badge on the next stop from 50 % |

## Retrain
```bash
pip install -r requirements-ml.txt
python ml/generate_history.py      # or replace ml/data/history.csv with real history (same columns)
python ml/train_delay.py           # writes models/*.json and prints the metrics
```

## Limitations
- The history is **synthetic**: the model learns the patterns written into the generator, not Coimbatore's real
  traffic. Swap in real delivery logs (same columns) to make it real.
- Weather is set by hand on Command Center for now; live weather comes with the real-world data phase.
- The demo uses a fixed 09:00 clock, so the hour feature comes from each stop's planned ETA.
- Reasons are path contributions, a fast approximation of SHAP – good for "why", not for exact attribution.
- Probabilities are not separately calibrated; use them to rank risk, not as exact chances.
