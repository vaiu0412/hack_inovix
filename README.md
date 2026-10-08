# 🌊 Ripple – AI-Powered Disruption-Aware Logistics Planning

> Every disruption creates a ripple. We show how far it spreads — and how to stop it.

**Live demo:** _add your Streamlit Cloud link here after deploying (see "Free public demo link" below)_

## Problem
A single accident, flood or breakdown in a city like Coimbatore quietly breaks dozens of delivery
promises: insulin reaches a hospital late, milk spoils, customers aren't told. Dispatchers find out
too late and react by phone. Ripple turns one free-text report into a clear impact picture and an
explained recovery plan in seconds.

## Workflow
**WHAT CHANGED? → WHAT IS AFFECTED? → WHAT SHOULD WE DO NEXT?**

1. **Report** – type a message in English or Tanglish (*"Avinashi road la accident aachu, full ah block"*)
   or fill a form. Ripple parses it and a human confirms or edits it.
2. **Impact** – finds every vehicle whose route uses the road, cascades the delay to all downstream
   stops, recomputes ETAs and scores each delivery's risk (Critical / High / Medium / Low).
3. **Recovery** – recommends actions with a plain-English *why*: reassign urgent parcels to the
   backup van, reroute vehicles, resequence stops and notify customers (messages auto-drafted).
   One click applies the plan and updates the dashboard.

## Features
- Rule-based parser with Tanglish support; optional LLM (Gemini or Groq) with automatic fallback
- Downstream cascade model on real Coimbatore roads (no live routing needed)
- Weighted risk score: deadline slack, priority (medical > perishable > express > standard),
  cascade position, severity
- Backup-vehicle reassignment, alternate-road reroute with extra km, before/after missed deadlines
- **Several disruptions at once** (e.g. an accident + rain): delays add up, detours avoid every blocked
  road, and each disruption can be removed from the sidebar
- Live OpenStreetMap map with the "ripple", and a dependency graph Disruption → Road → Vehicle → Delivery → Customer
- Fixed simulated clock (09:00) so the demo always makes sense
- **Works fully offline without any API key**

## How to run
```bash
pip install -r requirements.txt
streamlit run app.py
```
Optional LLM (any one) – as an environment variable or in `.streamlit/secrets.toml` (git-ignored):
```bash
set GEMINI_API_KEY=...     # Windows (use export on macOS/Linux)
set GROQ_API_KEY=...
```
If the key is wrong or the network is down, Ripple quietly falls back to its rules.
Tests:
```bash
python -m pytest -q
```
Every module also has a self-test, e.g. `python -m modules.impact`.

## Demo script (2 minutes)
1. **Dashboard** – 6 vehicles, 30 deliveries, 0 disruptions, everything on track.
2. Click **▶ Load demo scenario** – *"Accident near Avinashi Road, road blocked for 2 hours"*.
3. Show the parsed card (accident · Avinashi Road · critical · 120 min) → **Confirm & analyse impact**.
4. **Impact** – 3 vehicles, 9 deliveries, 3 predicted misses; KMCH insulin and FreshMart dairy are Critical.
   Show the ripple map and the dependency graph.
5. **Recovery** – backup van V6 takes the insulin and dairy; V1–V3 reroute via the Peelamedu–Hope College stretch.
   Missed deadlines **3 → 0**. Open a drafted WhatsApp/SMS message.
6. **Apply plan** → back to **Dashboard**: KPIs and map updated.
7. **Two disruptions:** on **Report Disruption** add *"Heavy rain flooding at Trichy Road, 45 mins"* →
   2 active disruptions, 4 vehicles, 14 deliveries. V3 is hit by both; the new plan reroutes it around
   both roads and still brings missed deadlines **3 → 0**. Remove one with ✕ in the sidebar.
8. Bonus: try *"Murugan vandi breakdown aachu near Race Course"* (Tanglish breakdown).

## Free public demo link (Streamlit Community Cloud)
1. Push this repo to GitHub (already done for `vaiu0412/hack_inovix`).
2. Go to <https://share.streamlit.io> and sign in with the GitHub account that owns the repo.
3. Click **Create app** and choose to deploy from a GitHub repo (labels may differ slightly).
4. Repository `vaiu0412/hack_inovix`, branch `main`, main file path `app.py`.
   Optionally pick a custom URL, e.g. `ripple-coimbatore`.
5. In **Advanced settings** choose Python **3.12** (3.10 or newer works). Secrets are optional:
   ```toml
   GEMINI_API_KEY = "your-key"
   ```
   Leave secrets empty to run in rule-based mode – everything still works.
6. Click **Deploy**. The first build takes a few minutes; every push to `main` redeploys automatically.
7. Paste the link at the top of this README.

Free apps go to sleep after a while without visitors – open the link a few minutes before judging.

## Folder structure
```
hack_inovix/
├── app.py                  Streamlit UI (4 pages)
├── data/                   roads.csv, vehicles.csv, deliveries.csv (synthetic, real coordinates)
├── modules/
│   ├── data_loader.py      load CSVs, clock, distance helpers
│   ├── parser.py           WHAT CHANGED?  text -> structured disruption (+ optional LLM)
│   ├── impact.py           WHAT IS AFFECTED?  cascade + new ETAs
│   ├── risk.py             risk score 0-100 + labels
│   ├── recommender.py      WHAT NEXT?  actions, why, messages, before/after
│   ├── graph_viz.py        NetworkX dependency graph (Plotly)
│   └── map_viz.py          Plotly OpenStreetMap map
├── assets/style.css        dark theme
├── tests/test_scenario.py  demo + parser tests
└── requirements.txt
```

## Team module ownership
| Member | Owns |
|---|---|
| Member 1 | `data/`, `data_loader.py`, `parser.py` (what changed) |
| Member 2 | `impact.py`, `risk.py`, `recommender.py` (what is affected / what next) |
| Member 3 | `app.py`, `map_viz.py`, `graph_viz.py`, `assets/style.css` (UI & visuals) |
