# Product features: photos, tracking, proof, analytics, Tamil

Five features for the people around a delivery – the partner, the customer and the branch – each optional on keys
and each with a Demo mode. With zero keys everything works end to end.

| Feature | With a key | Without (Demo mode) |
|---|---|---|
| **Photo reports** | a vision model reads the photo (Gemini, else Groq vision) and fills in type, severity and a one-line note | the partner taps the type; the photo is still saved and shown to the admin |
| **Tracking link** | `PUBLIC_APP_URL` makes the link point at your hosted app | links point at `http://localhost:8501` |
| **Customer messages** | WhatsApp via Twilio (`TWILIO_WHATSAPP_FROM`) or the WhatsApp Business Cloud API (`WHATSAPP_TOKEN`, `WHATSAPP_PHONE_ID`) | kept as **drafts**; the admin sees them (status *Draft (no provider)*) and can open the newest in the phone's SMS app |
| **Proof of delivery** | the customer's 4-digit code goes out by WhatsApp | the partner's screen shows the code, labelled **DEMO** |
| **Analytics** | – | always on; history charts use the synthetic 60-day history (labelled) |
| **Tamil UI** | – | always on; per-partner choice |

## Photo reports (`services/vision.py`, `modules/issues.py`, `modules/report_ui.py`)
- *Report issue* has a **Photo** section: take one with the camera (`st.camera_input`) or upload one.
- **Check** works with a photo alone. With a vision key the model returns `{type, severity, description}`; the type is
  used when the partner didn't pick one, the severity only ever goes *up*, and the description becomes the alert's
  *Photo* note. Without a key (or if the model can't tell) the partner is asked to tap the type.
- The image is stored under `data/photos/` next to the database (`issues.photo_path`) and shown in the admin's alert
  (step 1) with the note.
- Native app: `POST /me/issues/preview` and `POST /me/issues` keep working; photos are a web-app feature for now.

## Customer tracking link (`modules/track_ui.py`, `views/track.py`)
- Every delivery has a random 12-character **tracking code** (`deliveries.track_code`, made at start-up for old rows).
  The link is `<PUBLIC_APP_URL>/track?code=…` – the Deliveries panel shows it for each order.
- The page needs **no sign-in** and shows **one** delivery: its stage (*Order received → Partner assigned → Picked up
  → On the way → Delivered*), the ETA and promised time, the partner's **first name** and vehicle, and a small map
  with the drop point and – once picked up – where the vehicle is. It refreshes every 30 s.
- It never shows phone numbers, other customers' stops or anything else of the branch. `app.py` routes a `code`
  link before the session is even restored, into a navigation that contains only this page.
- An unknown code shows *This tracking link is not valid.*

## Customer messages (`services/messaging.py`, `modules/operations.py`)
- When an admin applies a plan, the customers whose delivery changes get a message; it now ends with
  *Track: <link>*. Messages are saved first, then sent **after** the database commit (never a network call inside the
  transaction), and each one gets a status: *Sent · WhatsApp*, *Failed · WhatsApp* or *Draft (no provider)*.
- Deliveries → **Customer messages** lists them with the status. In Demo mode the newest draft is shown with
  **Open in SMS** (an `sms:` link with the text filled in) so the admin can send it from a phone.
- Business-initiated WhatsApp messages outside a 24-hour chat need an approved template on the Cloud API; the
  Twilio sandbox works for testing.

## Proof of delivery (`modules/pod.py`, `components/signature/`, `modules/partner_ui.py`)
- **Medical** orders (`assign.PROOF_FOR`) can only be marked Delivered with a **photo** and either the customer's
  **4-digit code** or their **signature**. This is checked in `assign.advance`, so the app, the API and any future
  client all hit the same rule. Other orders: proof is optional.
- **Code:** *Send code* makes a random code, stores only its SHA-256 hash, valid 15 minutes, **5 tries** (every try
  counts, a locked code stays locked). The message log says *Delivery code sent (hidden)* – the code itself is never
  stored in clear text. Without WhatsApp the code is shown on the partner's screen as **DEMO**.
- **Signature:** a small signature pad (plain HTML/JS component, no package) – *Clear* / *Use signature* – sends a PNG.
- Photo and signature are saved under `data/pod/`; the admin's Deliveries panel shows *Proof of delivery* with the
  method, time and both images, and the tracking page says *Delivered at 10:42 · proof recorded*.
- API: `POST /me/deliveries/{id}/pod/code` → `{status, provider, demo_code}`;
  `POST /me/deliveries/{id}/pod` (multipart: `photo`, `signature`, `code`, `note`) → 200, or 409 with the reason.
  `POST /me/deliveries/{id}/delivered` returns 409 for a medical order without proof.

## Analytics (`modules/analytics.py`, `views/manager/analytics.py`, `ml/summarise_history.py`)
Each chart has a *Table view*; history charts carry a **Synthetic history** badge, live ones **Live**.

| Section | Source | What it shows |
|---|---|---|
| Delays by road and hour | history | heatmap of mean minutes late per road × hour of day (worst roads first, one blue hue) |
| On time per day | history | share delivered by the deadline, per day |
| Where disruptions happen | live | heatmap of every disruption of the branch (active or ended), weighted by severity |
| Partner performance | live | delivered, on-time %, open stops, offers answered, mean answer time, declines |
| Prediction accuracy | history | MAE per road and a reliability chart (predicted chance late vs how often it really was) |

- `ml/data/history.csv` is not in git, so `ml/summarise_history.py` writes a small **`models/history_summary.json`**
  (delay by road × hour, SLA per day, test-day accuracy). It scores the test days with the app's **exported** JSON
  models (no LightGBM needed) – its MAE equals the training metric (3.85 min). `ml/train_delay.py` runs it after every
  training.
- **On time** on live data: the app runs on a simulated 09:00 clock, so a delivered stop counts as on time when its
  ETA at delivery was within the promised time (without an ETA, the real delivery time is used).
- **Answer time** = offer *Sent* → the partner's *Accepted* or *Declined* (from the escalation log).

## Tamil + English (`modules/i18n.py`, `i18n/en.json`, `i18n/ta.json`)
- `t("key", **values)` returns the text in the user's language, falling back to English. Both files have the same
  ~160 keys and the same `{placeholders}` (a test checks it).
- Partners switch **English / தமிழ்** in the sidebar; the choice is saved in `user_prefs` (key `lang`) and restored at
  the next sign-in, before the menu is drawn – so the page titles are translated too.
- Fully translated: the partner pages (Today, My deliveries, My route, Report issue, History), the offer overlay,
  the proof form, location messages, statuses and stages. Admin pages stay in English.
- Not translated (yet): texts made by the server at run time – plan reasons, route instructions in messages, and
  what the AI wrote in an alert summary.

## Limits
- Photos are stored as files next to the database; on a host without a persistent disk they disappear on restart
  (same as voice notes – see [`DEPLOY.md`](DEPLOY.md)).
- The tracking code is the only secret of the public page: anyone with the link sees that one delivery. Codes are
  random (`secrets.token_urlsafe`), never listed, and can't be guessed from the delivery ID.
- WhatsApp sending is fire-and-forget: there is no delivery receipt or reply handling yet.
