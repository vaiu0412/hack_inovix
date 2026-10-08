# Claude Code prompt – Ripple v2 (role-based, mobile-first)

> Paste everything below the line into Claude Code, opened in the `hack_inovix` folder.
> The team's own words are kept in Appendix A (v2 request) and Appendix B (original v1 prompt).

---

## Think like a hackathon judge first
Judges score roughly: **problem & impact · innovation · technical depth · UX/design · demo ·
feasibility & scale**. Every feature below must earn points on at least one of these:
- **Problem & impact** – show money/time saved: missed deadlines before → after, minutes saved,
  extra km, "critical medical parcels protected". Put these numbers on screen.
- **Innovation** – Tanglish voice notes from the road → AI understands the real problem → a plan a
  human approves. Human-in-the-loop AI, not a black box.
- **Technical depth** – shared live data, fuzzy place matching, cascade model, explainable
  recommendations, REST API ready for a native app, tests.
- **UX/design** – professional, calm, not "AI-generated looking": no emoji spam, no gradient text,
  real icons (`:material/...:`), restrained colours, light **and** dark theme, phone-first.
- **Demo** – two devices live: partner phone reports → manager laptop sees it within 5 s → Accept →
  partner phone updates. Must work with **no internet AI** too (rule-based fallback).
- **Feasibility & scale** – SQLite → Postgres, Streamlit → native app via the same API,
  pluggable LLM (Groq/Gemini), clear limitations listed in the README.

You are a senior Python engineer and an experienced hackathon participant. Upgrade the existing
**Ripple** project (Streamlit app in this repo) into a clear, professional, **mobile-first** product
with two roles: **Manager (admin/operator)** and **Delivery Partner**. Build it phase by phase.
After EACH phase: run the code and tests, fix errors, then make a small git commit with a clear
message. Keep code simple, modular and beginner-readable. Keep the existing modules
(`parser`, `impact`, `risk`, `recommender`) and all existing tests working.

## Goal (one sentence)
A delivery partner reports a problem by voice or text from their phone → AI extracts the real
problem → the manager sees it live on the map with an AI recommendation that "thinks like a senior
dispatcher" → one tap on **Accept** updates every screen (deliveries, ETAs, partners, customers).

## Hard requirements
- **Works with zero API keys** (rule-based fallbacks everywhere). Keys only make it smarter.
- **Mobile-first**: designed for a 390 px wide phone first, then desktop. Touch targets ≥ 44 px,
  no information that is only visible on mouse hover, big readable text, one main action per screen.
- **Shared live data**: the manager (laptop) and partners (phones) must see the same data,
  so use a single SQLite database (`data/ripple.db`) instead of per-session state.
- **Place names must match even when misspelled**: "avinasi rd", "avinashiroad", "Avanashi",
  "100ft road", "R.S.Puram", "townhall", "gandhi puram", Tamil "அவிநாசி சாலை" → correct place/road.
- **Ready for a native mobile app later**: all business logic lives in `modules/` (no Streamlit
  inside), plus a small FastAPI layer (`api/main.py`) that a Flutter/React Native app can call.
- No auth for the hackathon (role picker + optional `?role=partner&id=V1` deep link). Note in the
  README that real auth is needed before production. No Docker, no microservices.

## Stack
Python, Streamlit (UI), SQLite (`sqlite3`), Pandas, Plotly, NetworkX, **folium + streamlit-folium**
(tap-friendly map with popups), **rapidfuzz** (fuzzy matching), `st.audio_input` (voice notes),
optional Groq Whisper / Gemini for speech-to-text and reasoning, optional `SpeechRecognition`
as a no-key online fallback, FastAPI + Uvicorn for the mobile API.

## Structure (new or changed files)
```
hack_inovix/
├── app.py                      entry: st.navigation, role picker, theme
├── pages/
│   ├── manager.py              Manager / admin console
│   └── partner.py              Delivery partner mobile screen
├── modules/
│   ├── store.py                SQLite: seed from CSVs, reset, read/write helpers
│   ├── places.py               fuzzy place + road matching (aliases, areas, landmarks, Tamil)
│   ├── voice.py                speech-to-text chain (Groq → Gemini → SpeechRecognition → manual)
│   ├── issues.py               partner issue → structured disruption (+ confidence)
│   ├── operations.py           analyse issue, AI plan, accept/reject, apply to DB, notifications
│   ├── ui.py                   shared UI components (cards, badges, KPI tiles, empty states)
│   └── (existing) data_loader, parser, impact, risk, recommender, graph_viz, map_viz
├── api/main.py                 FastAPI endpoints for the future mobile app
├── data/places.csv             canonical places with aliases (English + Tamil), lat/lng, road_id
├── data/partners.csv           partner details (phone, shift, languages, rating) per vehicle
├── assets/style.css            clean professional light theme, mobile-first
└── tests/                      existing tests + test_places.py, test_issue_flow.py
```

## Phase 1 – Data + shared store
- `partners.csv`: partner_id, name, phone (dummy), vehicle_id, shift_start, shift_end, languages,
  rating, status (on_duty / on_break / off_duty). One partner per vehicle (6 incl. backup).
- `places.csv`: ~40 real Coimbatore places/landmarks (Gandhipuram, RS Puram, Peelamedu, Hope College,
  PSG Tech, KMCH, Codissia, Lakshmi Mills, Nava India, Saibaba Colony, Ukkadam, Town Hall,
  Singanallur, Ramanathapuram, Sungam, Saravanampatti, Ganapathy, Thudiyalur, Kurichi,
  Sundarapuram, Eachanari, Race Course …) with correct spelling, aliases, Tamil names, road_id.
- Fix any place-name spelling/spacing issues in the existing CSVs.
- `store.py`: create tables (partners, vehicles, roads, deliveries, issues, plans, events,
  messages), seed from CSVs, `reset_demo()`, simple functions (`list_partners`, `get_partner`,
  `deliveries_for`, `add_issue`, `update_delivery`, `add_message`, `log_event` …).
  Delivery status: pending / delivered / failed / reassigned.

## Phase 2 – Fuzzy place matching (fixes the old "exact spelling" problem)
- Normalise text: lowercase, remove punctuation, collapse spaces, also compare without spaces.
- Match against road names, road aliases, place names/aliases and Tamil names with rapidfuzz
  (word-level + partial ratio), with a confidence score and a minimum threshold.
- A place resolves to its road (e.g. "KMCH" → Avinashi Road). Return top-3 suggestions when unsure,
  so the UI can ask "Did you mean …?".
- Upgrade `parser.parse_disruption` to use it. Tests: 15+ misspelled / no-space / Tamil inputs.

## Phase 3 – Voice note → actual problem
- `voice.transcribe(audio_bytes)` chain: Groq Whisper (`GROQ_API_KEY`) → Gemini audio
  (`GEMINI_API_KEY`) → `SpeechRecognition` Google web API (en-IN, then ta-IN) → return None
  so the UI asks the partner to type one line. Never crash; always keep the audio.
- `issues.extract(text, partner)`: uses the parser + fuzzy places; if no place is said, use the
  partner's current location/road; if no vehicle is said, it is the reporting partner's vehicle.
  Output: type, place, road, severity, duration, affected vehicle, confidence, plain summary
  ("Accident on Avinashi Road near PSG Tech, about 2 hours").

## Phase 4 – AI recommendation + apply everywhere
- `operations.analyse(issue)`: build disruption(s) from all open accepted issues, run impact → risk →
  recommender, and write a short human-style dispatcher note ("Insulin for KMCH is the real worry:
  it would be 60 min late. Lakshmi in the backup van is idle 5 km away – send her. Everyone else
  just detours via the Peelamedu stretch."). LLM writes the note if a key exists, else templates.
- `operations.accept(plan)`: update deliveries (vehicle, ETA, status), mark blocked roads, send
  messages to affected partners' inboxes, draft customer SMS, log events. `reject(plan, reason)`.
- Everything is stored in SQLite so every open screen shows the new state.

## Phase 5 – Design system + app shell
- Clean, professional **light and dark** themes (user can switch). Restrained palette, one brand
  colour, risk colours only for status, Inter font, consistent spacing, Material icons + short
  labels. Must not look AI-generated: no emoji spam, no gradient text, no decorative clutter.
- `st.navigation` with top navigation; landing page with two big cards
  "I'm a Manager" / "I'm a Delivery Partner". Remember the choice; `?role=` deep links.
- `ui.py` components: KPI tile, status badge, person card, issue card, empty state, toast.

## Phase 6 – Manager page
- KPI row: partners on duty, deliveries today, delivered, at risk, open issues.
- **Live map** (folium): every partner as a marker coloured by status; **tap a partner** → popup with
  name, phone, vehicle, current area, deliveries pending/done, next stop + ETA, open issue.
  Selecting a partner also opens a detail panel with their stop list. Deliveries coloured by risk,
  blocked roads red, reroutes green, backup vehicle distinct.
- **Team spreadsheet** below the map: all partners with every detail (ID, name, phone, vehicle,
  status, area, assigned / delivered / pending, next stop, ETA, open issues, rating), search,
  filter by status, download CSV.
- **Issues inbox** (auto-refresh every ~5 s with `st.fragment(run_every=...)`): newest first,
  partner, time, voice-note player, transcript, AI-extracted problem + confidence, impact summary,
  AI plan with "why". Buttons: **Accept**, **Edit then accept**, **Reject**. History timeline.
- Keep the old "report a disruption yourself" flow as a "What-if simulator" tab.

## Phase 7 – Delivery partner page (phone first)
- Choose your name once (or deep link). Header: name, vehicle, shift, status toggle.
- **Next stop** card (customer, area, deadline, call button, "Delivered" / "Problem" buttons).
- My stops list with status. Inbox: manager instructions (e.g. "Take Peelamedu stretch",
  "Hand D06 to Lakshmi").
- **Report a problem**: quick chips (Accident, Traffic, Puncture/Breakdown, Rain/Flood, Road blocked,
  Customer not available), a 🎤 voice note (`st.audio_input`), or text. Shows
  "We understood: …" with Edit; **Send to manager** → confirmation + live status of the issue.

## Phase 8 – Tests, polish, docs, deploy
- Tests: fuzzy places, voice fallback (no keys → manual text path), issue → plan → accept updates
  DB, existing scenario tests still pass. Run Streamlit headless and click through both roles.
- Check both pages at 390 px and 1280 px wide.
- README: problem, roles, flow diagram, how to run, API keys (optional), demo script, mobile plan.
- Redeploy to Streamlit Community Cloud.

## Phase 9 – Mobile API (for the future native app)
- `api/main.py` (FastAPI): GET /partners, GET /partners/{id}, GET /partners/{id}/stops,
  POST /issues (text or audio upload), GET /issues, POST /issues/{id}/accept, POST /issues/{id}/reject,
  GET /map (partners + deliveries + blocked roads as JSON). Same `modules/` logic, same SQLite.
- `uvicorn api.main:app --reload`; OpenAPI docs at /docs. Test with FastAPI TestClient.

## Demo script (what judges see)
1. Laptop: Manager page – map of Coimbatore, 5 partners on duty, 30 deliveries, 0 issues.
2. Phone: open the partner link for **Murugan (V1)** → tap 🎤 and say
   "Avinashi road la accident, full block, rendu mani neram aagum".
3. Phone shows "We understood: Accident · Avinashi Road · ~2 hours" → **Send to manager**.
4. Laptop (within 5 s): red issue card, ripple on the map, 9 deliveries at risk, insulin to KMCH critical.
   AI note explains the plan → **Accept**.
5. Murugan's phone shows the detour; **Lakshmi (backup, V6)** sees the new insulin pickup;
   missed deadlines 3 → 0; customer messages drafted. Tap any partner on the map for details.

---

## Appendix A – the team's v2 request (original words)

> im not okay with this app ....i want clear professional app and ui wil be more efficient and ellamey
> user friendly easy observable ha irukanum .....easy to use ha irukanum .........admin page adhuvadhu
> manager page on that visualize map in that endha endha devilery person engha irukaghaa adhaa click
> panna avagha evlo deliveries irukagha something all details abt them and kela ori spreedsheet la evlo
> delivery oerson and their details irukanum .....then delivery persons page on that they complaint abt
> what issues they face and it should have voice note also in that in that it want extract the actual
> problem ......it should so to the admin page the problem should display to operator and it by using ai
> automaticallly think like human and recommend what to do ? and if it is accepted automatically updated
> it in all and everything ......add this all .....in before developed streamlit dashboard exact place
> name correct spelling and space ellam kuduthaa thaan eduthuku so adhu correct pannu .....inum nala user
> friendly easy access ha kudu ....im going to develop this as mobile app of deployment so please mind
> that.....please behave like senior hackathon participate and do all j work and project based on that

Decisions taken with the team: mobile web now + API for a native app later · light and dark theme,
professional, not AI-looking · free Groq key for voice (Whisper) with no-key fallbacks ·
build everything, judged like a senior hackathon judge.

## Appendix B – original v1 prompt (base project, already built)

> RIPPLE – AI-Powered Disruption-Aware Logistics Planning. Workflow: WHAT CHANGED? → WHAT IS AFFECTED? →
> WHAT SHOULD WE DO NEXT? Stack: Python, Streamlit, Pandas, Plotly, NetworkX; optional LLM (Gemini or Groq)
> via env var – must work fully without any API key. Roads are predefined Coimbatore segments with lat/lng
> polylines; each vehicle's route is an ordered list of road_ids; each delivery sits on a road_id with a
> stop_order; fixed simulated clock 09:00. Phases: synthetic data (10 roads, 6 vehicles incl. 1 backup,
> 30 deliveries; Avinashi Rd in exactly 3 routes; 2-hour block affects 8–10 deliveries incl. a critical
> medical and perishable) → rule-based parser with Tanglish → downstream impact cascade → weighted risk
> score (Critical ≥75, High ≥50, Medium ≥25) → recommender (backup reassignment, reroute, resequence,
> notify, plain-English "why", before/after misses) → NetworkX dependency graph + Plotly map → Streamlit UI
> (Dashboard, Report, Impact, Recovery, Apply plan) → tests, README, requirements. Commit after each phase.
