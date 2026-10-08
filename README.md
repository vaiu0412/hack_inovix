# DEPORT – Disruption-Aware Logistics Decision Support System

> **From Disruption to Decision.**

**Live demo:** <https://ripple-coimbatore.streamlit.app> · built for HackNext'26 (Coimbatore)

| Sign-in | Command Center | Alerts (3 steps) | Partner phone |
|---|---|---|---|
| `docs/screenshots/login.png` | `docs/screenshots/command-center.png` | `docs/screenshots/alerts.png` | `docs/screenshots/partner-today.png` |

*(Screenshot placeholders – add the PNGs to `docs/screenshots/`.)*

## What DEPORT does
1. **Report by voice** – a delivery partner taps *Accident* or says *"Avinashi road la accident, full block,
   rendu mani neram"* (Tamil, English or both). DEPORT finds the place even when misspelled.
2. **See the impact** – the branch admin gets an alert in seconds: which deliveries are hit, which will be
   late, what is critical (the **Ripple Impact** graph and a live map on real roads).
3. **Fix in one click** – the AI plan (backup van, reroute, prioritise, notify) with a 2-line reason per action.
   **Accept plan** updates routes, vehicles, ETAs, the map, KPIs, history and every partner's phone at once.

Demo numbers (2-hour accident on Avinashi Road): **9 deliveries hit → missed deadlines 3 → 0**,
average delay +95 → +17 min, KMCH insulin delivered by the backup van at 10:44 (deadline 11:30).

## Roles
| Role | Pages | Sees |
|---|---|---|
| Super Admin | Overview · Branches · Admins · Audit log | all branches, summary level |
| Branch Admin | Command Center · Live Map · Partners · Deliveries · Alerts · History | own branch only |
| Delivery Partner | Today · Deliveries · Route · Report · History | own data only |

The role comes from the account – everyone signs in on the same page and lands on their own dashboard.
Super Admins sign in only at the unlisted **`/console`** page (not linked anywhere).

## Demo logins
For judges and this README only – never shown in the app.

| Who | Email / ID | Password |
|---|---|---|
| Super Admin (at `/console`) | `superadmin@deport.in` | `Super@123` |
| Branch Admin – East | `east.admin@deport.in` | `Admin@123` |
| Branch Admin – Central / South | `central.admin@deport.in` / `south.admin@deport.in` | `Admin@123` |
| Delivery Partner | `DP101`…`DP106` or `dp102@deport.in` (DP102 = Karthik, DP106 = Lakshmi, backup van) | `Partner@123` |

Also: **Sign in with OTP** (code shown on screen as DEMO when no SMS provider is set) and **Forgot password?**.
*Reset demo* (Super Admin sidebar) restores all accounts and the 09:00 state.

## Demo script (6 steps)
1. **Phone:** sign in as `DP102` → **Report** → tap *Accident*, record or type
   *"avinashi road accident, full block, 2 hours"* → **Check** → *We understood: Accident · Avinashi Road* → **Send**.
2. **Laptop:** sign in as `east.admin@deport.in` → Command Center shows the red banner
   *DP102 · Accident · Avinashi Rd · 9 deliveries hit* and *Critical 3*.
3. **Live Map** → DP102 pulses red on Avinashi Road (red dashed), green alternate route, tap the bike for the panel.
4. **Alerts** → ① what changed (transcript) ② what's affected (Ripple Impact, mini map) ③ what to do → **Accept plan**.
5. Green **Plan applied.** with Before → After (missed 3 → 0); KPIs, map and History update.
6. **Phone:** DP102's Today shows **Route changed** (avoid Avinashi Road); `DP106` now has the KMCH insulin pickup.

## Run it
```bash
pip install -r requirements.txt
streamlit run app.py                 # http://localhost:8501  (Super Admin: http://localhost:8501/console)
python -m pytest -q                  # no internet or keys needed
uvicorn api.main:app --reload        # REST API for a native app, docs at http://localhost:8000/docs
python scripts/build_geometry.py     # optional: refresh the cached real-road shapes from OSRM
```
Optional secrets (AI key, SMS key, Google sign-in): copy `.streamlit/secrets.toml.example` to
`.streamlit/secrets.toml` (git-ignored).

## Google sign-in (OAuth) setup
1. Google Cloud Console → *APIs & Services* → *Credentials* → **Create OAuth client ID** (Web application).
2. Authorised redirect URI: `<app URL>/oauth2callback` (e.g. `http://localhost:8501/oauth2callback`).
3. Fill `[auth]` (`redirect_uri`, `cookie_secret`) and `[auth.google]` (`client_id`, `client_secret`,
   `server_metadata_url`) in `.streamlit/secrets.toml` – see the example file. `Authlib` is in requirements.
4. Restart. *Continue with Google* now uses Streamlit's real OIDC (`st.login`). The Google email must belong to an
   existing, active DEPORT account – accounts are never auto-created. Until configured, the button is disabled.

## How it works
- **Impact → risk → plan:** impact cascade over each vehicle's route, a 0–100 risk score (deadline, priority,
  closeness, severity), then backup van for urgent medical/perishable stops, reroute via the best open road, etc.
- **One transaction:** accepting a plan writes deliveries, routes, messages, the road block, the alert and the
  history in a single SQLite transaction – all or nothing. Every screen reads SQLite (no page copies) and refreshes
  within 4 s when anything changes.
- **Real roads, no network at demo time:** road shapes, vehicle road-snaps and driving legs come from the free
  OSRM server once (`scripts/build_geometry.py`), are committed in `data/route_geometry.json` and loaded into
  SQLite at seed. Basemap: Esri World Street Map (keyless; layers: OpenStreetMap, light grey, satellite).

## Security & data isolation
PBKDF2-SHA256 (200 000 iterations) passwords; session tokens and OTPs stored only as hashes; 5 wrong tries lock an
account for 2 minutes; *Remember me* = 7-day revocable session cookie; audit log of sign-ins and admin actions.
Role, branch and partner ID come only from the validated session. Branch scoping is enforced in the core code
(`modules/store.py`, `partner_scope.py`, `operations.py`), not just the UI – cross-branch writes raise
`PermissionError`, and every page checks the role first.

## Project structure
```
app.py            sign-in first, then role navigation          views/login.py · views/console.py
views/manager/    branch admin pages                            views/partner/ · views/super/
modules/          store (SQLite) · auth · guards · operations · impact · risk · recommender · parser · voice
                  live_map (folium) · geometry (OSRM cache) · ui (design system) · manager_ui · report_ui · login_ui
assets/           style.css · logo.svg · logo_mark.svg · favicon.png
data/             branches, roads, vehicles, deliveries, partners, places (real Coimbatore coordinates), route_geometry.json
tests/            test_demo_flow · test_rbac · test_ui_data · test_app_ui (headless click-through) · API · scenario
```

## Known limits
Routing is simplified to named roads (no live traffic); OTP SMS and Google sign-in need their own keys; the free
Streamlit Cloud disk is reset on redeploy (data created there is lost); CARTO basemaps now need an API key, so the
default basemap is Esri's.
