# DEPORT – Disruption-Aware Logistics Decision Support

> **From Disruption to Decision.** A delivery partner reports a road problem by voice; the branch admin sees the
> impact in seconds and fixes every affected route in one click.

[![CI](https://github.com/vaiu0412/hack_inovix/actions/workflows/ci.yml/badge.svg)](https://github.com/vaiu0412/hack_inovix/actions/workflows/ci.yml)
· **Live demo:** <https://ripple-coimbatore.streamlit.app> · **Demo video:** _link coming soon_ ·
HackNext'26, Coimbatore (Team Inovix)

| Command Center | Live Map | Alerts – 3 steps | Partner: Report |
|---|---|---|---|
| ![Command Center](docs/screens/02_command_center.jpg) | ![Live map on real roads](docs/screens/03_live_map.jpg) | ![Alerts](docs/screens/04_alerts.jpg) | ![Partner report](docs/screens/07_partner_report.jpg) |

More in [`docs/screens/`](docs/screens/) · slides in [`docs/presentation/`](docs/presentation/)

## Problem
One accident on a main road delays many deliveries at once. Managers find out late, work out the impact by hand
and decide under pressure – so deadlines (even medicines) are missed.

## Solution
1. **Report** – the partner taps *Accident* and says or types it (Tamil, English or both). DEPORT finds the road,
   duration and severity, even when misspelled.
2. **See the impact** – the branch admin gets an alert: which deliveries are hit, which will be late, what is critical.
3. **Fix in one click** – a plan (backup vehicle, reroute, prioritise, notify) with a short reason per action.
   *Accept plan* updates routes, ETAs, the map, history and every partner's phone in one transaction.

Demo scenario (2-hour accident on Avinashi Road, demo data): 9 deliveries hit, missed deadlines 3 → 0.

## Architecture
```mermaid
flowchart LR
    partner["Partner phone"] --> ui
    admin["Branch Admin"] --> ui
    superadmin["Super Admin (/console)"] --> ui
    mobile["Mobile app (planned)"] --> api
    ui["Streamlit UI<br/>app.py · views/ · *_ui.py"] --> engine
    api["FastAPI REST<br/>api/main.py"] --> engine
    subgraph engine["Engine – modules/ (no UI code)"]
        direction LR
        parser["parser + voice"] --> impact --> risk --> recommender --> operations
        assign["assign (work)"]
        auth["auth + RBAC"]
        geometry["geometry (road shapes)"]
        escalation["escalation (offers)"]
    end
    engine --> db[("SQLite<br/>DB_PATH")]
    parser -. "optional key" .-> llm["Groq / Gemini"]
    escalation -. "services/voice_call" .-> twilio["Twilio Voice"]
    twilio -. "webhooks" .-> api
    geometry -. "cached in data/" .-> osrm["OSRM"]
```

## Features
- **Three roles, one sign-in:** Super Admin (branches, admins, audit), Branch Admin (own branch only), Delivery Partner
  (own data only). Checked in the engine, not just hidden buttons.
- **Voice or text reports** with AI understanding (LLM when a key is set, offline Tamil/English rules otherwise).
- **Impact → risk → plan:** cascade over each route, a 0–100 risk score, recommended actions with reasons.
- **Live map** on real road shapes, alerts in 3 steps, KPIs, history, partner phone screens.
- **Delay prediction (LightGBM):** minutes late and chance to miss the deadline for every open stop, with reasons
  (*Heavy rain · Avinashi Rd traffic*) – a proactive *Likely late* list, rain-aware impact, smarter assignment
  ([`docs/ML.md`](docs/ML.md)). MAE 3.85 min, ROC-AUC 0.965 on a date-split test set (synthetic history).
- **Optimised plan (OR-Tools):** next to the rule-based plan, a vehicle-routing re-optimisation of the affected
  branch (time windows, capacities, medical first) with a side-by-side *missed · delay · km* comparison – the admin
  picks which one to apply ([`docs/OPTIMIZER.md`](docs/OPTIMIZER.md)).
- **Learns from decisions:** every recommendation's fate is logged (accepted, skipped, rejected, modified); a
  logistic regression learns what admins take and plans are ranked by *chance taken × impact*; **Insights** shows
  acceptance by action type and what gets changed ([`docs/LEARNING.md`](docs/LEARNING.md)).
- **Real-world data:** partner phones share GPS every 30 s on duty (live position + trail on the map; simulated
  movement in Demo mode); OpenWeatherMap rain feeds the delay model and opens *Weather risk* alerts; TomTom jams
  become suggestions the admin confirms – all into the same impact → plan → approve flow
  ([`docs/REALTIME.md`](docs/REALTIME.md)).
- **Assign Work:** new orders (form or CSV), best partner with a reason, step-by-step delivery flow.
- **For customers and the field** ([`docs/PRODUCT.md`](docs/PRODUCT.md)): photo issue reports (a vision model reads
  them when a key is set); a public **tracking link** per order (`/track?code=…`, no sign-in: stage, ETA, partner's
  first name, mini map); customer updates by **WhatsApp** (or drafts in Demo mode); **proof of delivery** – photo +
  the customer's 4-digit code or a signature, required for medical orders; an **Analytics** page (delays by road ×
  hour, on time per day, disruption heatmap, partner performance, model accuracy); the partner app in **Tamil** or
  English.
- **No missed orders:** every assignment is an offer – Sent → Seen → Ringing (alarm) → AI voice call (Twilio, or a
  simulated call in Demo mode) → red admin alert with the next-best partner and one-click Reassign
  ([`docs/AI_CALL.md`](docs/AI_CALL.md)).
- **Nothing is lost:** drafts, filters and data survive refresh and restarts; reset saves a backup first.
- **Secure sign-in:** hashed passwords and sessions, lockout, OTP by email, optional Google sign-in.

## Tech stack
| Area | Used |
|---|---|
| UI | Streamlit 1.53 (multi-page, dark glass CSS) |
| Backend | Python 3.12+, FastAPI + Uvicorn |
| AI / NLP | Groq or Gemini (optional), rule-based Tamil/English parser, SpeechRecognition, RapidFuzz |
| ML | LightGBM (training only) → exported trees scored in pure Python; synthetic 60-day history |
| Optimisation | Google OR-Tools (VRP with time windows + capacities) |
| Data | SQLite (WAL), pandas |
| Maps & charts | Folium, OSRM shapes (cached), Esri tiles, Plotly, NetworkX |
| Live data | Browser geolocation, OpenWeatherMap, TomTom Traffic Flow (all optional) |
| Customers | WhatsApp (Twilio or Cloud API), Gemini / Groq vision for photos (all optional) |
| Quality & ops | pytest, ruff, GitHub Actions, Docker |

## Run it
```bash
pip install -r requirements.txt
streamlit run app.py                 # http://localhost:8501  (Super Admin: /console)
```
Docker (app + API, data kept in a volume):
```bash
docker compose up --build            # app :8501 · API :8000/docs
```
Tests and lint: `pip install -r requirements-dev.txt`, then `pytest -q` and `ruff check .` (no internet or keys).
REST API: `uvicorn api.main:app --reload` → docs at <http://localhost:8000/docs>.

All keys are optional – see [`.env.example`](.env.example) and
[`.streamlit/secrets.toml.example`](.streamlit/secrets.toml.example). Hosting with a persistent disk:
[`docs/DEPLOY.md`](docs/DEPLOY.md).

## Demo logins
For judges and this README only – never shown in the app.

| Who | Email / ID | Password |
|---|---|---|
| Super Admin (at `/console`) | `superadmin@deport.in` | `Super@123` |
| Branch Admin – East | `east.admin@deport.in` | `Admin@123` |
| Branch Admin – Central / South | `central.admin@deport.in` / `south.admin@deport.in` | `Admin@123` |
| Delivery Partner | `DP101`…`DP106` (DP102 = Karthik, DP106 = Lakshmi, backup van) | `Partner@123` |

## Demo script
1. **Phone:** `DP102` → **Report** → *Accident* + "avinashi road accident, full block, 2 hours" → **Check** → **Send**.
2. **Laptop:** `east.admin@deport.in` → red banner *DP102 · Accident · Avinashi Rd · 9 deliveries hit*.
3. **Live Map** → DP102 pulses red on Avinashi Road; green alternate route.
4. **Alerts** → what changed → what's affected → what to do → **Accept plan** → *Plan applied* (missed 3 → 0).
   *Optional:* switch to **Optimised (OR-Tools)** – also 0 missed, less delay, fewer km – and apply that instead.
5. **Phone:** DP102 sees **Route changed**; DP106 has the KMCH insulin pickup.
6. *Bonus:* **Assign Work** → new order → **Assign best** → partner taps *Accept → Picked up → Start → Delivered*.
7. *Delay model:* Command Center → **Likely late** → switch the weather to *Heavy rain*: risks and reasons update; an
   accident reported in the rain shows more delay than on a dry day.
8. *Escalation:* assign a **medical** order to DP102 and don't answer: full-screen card → alarm at 1 min → call
   (simulated without Twilio keys) at 3 min → red alert with **Reassign to …** at 5 min (times: Super Admin → Overview).
9. *Customer & proof:* Deliveries → select an order → open its **Tracking link** in a private window (no sign-in).
   Sign in as `DP101` → the medical order D06 → **Delivered** asks for a photo + **Send code** (DEMO code on screen)
   or a signature. *Analytics* shows delays by road × hour and partner performance; the partner sidebar switches to
   **தமிழ்**.

## Project structure
```
app.py         sign-in first, then role-based navigation
views/         pages: manager/ · partner/ · super/ · login · console
modules/       engine (store, auth, parser, voice, impact, risk, recommender, operations, assign, escalation, predict, optimizer, learning, tracking, realtime,
               geometry, places, pod, analytics, i18n) + UI helpers (ui, manager_ui, partner_ui, report_ui,
               login_ui, escalation_ui, live_map, track_ui, graph_viz)
services/      optional outside providers with a Demo-mode fallback (voice_call, weather, traffic, vision, messaging)
components/    geolocation (the partner phone's GPS) · signature pad – plain HTML/JS
i18n/          en.json + ta.json (partner app texts)
ml/            synthetic history, LightGBM training, history summary   models/   exported delay models (JSON)
api/           FastAPI REST for a native app + Twilio webhooks + the offer timer
data/          demo data with real Coimbatore coordinates + cached road shapes
tests/         225 tests (flows, RBAC, persistence, assignment, escalation, ML, optimiser, learning, live data,
               product: photos, tracking, proof, analytics, Tamil · API, headless UI)
```

## Roadmap
- [x] Portfolio-ready: lint, docstrings, Docker, CI, deploy guide
- [x] Order accept + escalation (sound → AI voice call → reassign)
- [x] Delay prediction model (proactive "likely late")
- [x] OR-Tools re-optimisation alongside the rule-based plan
- [x] Learning from admin decisions
- [x] Real-world data: live GPS, weather, traffic
- [x] Photo reports, customer tracking link, proof of delivery, analytics, Tamil UI
- [ ] Platform: PostgreSQL/PostGIS, JWT API, WebSockets, push
- [ ] Flutter partner app

## Known limits
Simulated clock (09:00) and demo data; routing uses named roads (no live traffic yet); Google sign-in and SMTP need
your own keys; Streamlit Community Cloud storage is temporary – use a persistent disk ([`docs/DEPLOY.md`](docs/DEPLOY.md)).
