# Deploying DEPORT

DEPORT keeps everything that changes – the SQLite database, voice notes and backups – in **one folder: the folder of
`DB_PATH`**. Host it with a **persistent disk** mounted there, or the data resets on every restart.

The Docker image sets `DB_PATH=/data/deport.db`, listens on `$PORT` (default 8501) and has a health check at
`/_stcore/health`. Every key is optional; without keys the app runs in demo mode (rules instead of AI, OTP on screen).

## Docker (any server)
```bash
cp .env.example .env          # optional: add keys
docker compose up --build -d  # http://<server>:8501 ; data in the "deport-data" volume
```
Back up the volume (or copy `/data/deport.db` from the container); *Reset demo data* also saves a copy in
`/data/backups/`.

## Render
1. **New → Web Service** → connect the GitHub repo. Render detects the `Dockerfile` (runtime: Docker).
2. **Instance type:** a paid type (Starter or higher) – persistent disks are not available on the free type.
3. **Advanced → Add Disk:** mount path `/data`, size 1 GB.
4. **Environment:** `DB_PATH=/data/deport.db` (already the image default) plus any keys from `.env.example`.
   Health check path: `/_stcore/health`.
5. Deploy → open `https://<name>.onrender.com` (Super Admin: `/console`).

Notes: a service with a disk runs as one instance and has a short pause on each deploy. For Google sign-in add a
**Secret File** named `secrets.toml` (the `[auth]` section below); the container copies it into place at start.

## Railway
1. **New Project → Deploy from GitHub repo**. Railway builds the `Dockerfile` and sets `PORT` itself.
2. **Add a Volume** to the service with mount path `/data`.
3. **Variables:** `DB_PATH=/data/deport.db` plus any keys from `.env.example`.
4. **Settings → Networking → Generate Domain**, then open it.

Railway has no secret files, so Google sign-in needs another host (or a custom image); every other key works as a
variable.

## Streamlit Community Cloud
Works for demos (it is how the live demo runs) but has **no persistent disk**: data resets when the app sleeps,
restarts or redeploys. Keys go in *App → Settings → Secrets* (same names as `.streamlit/secrets.toml.example`).

## Optional integrations

### OTP by email (SMTP)
Set `SMTP_HOST` (`smtp.gmail.com`), `SMTP_PORT` (`587`), `SMTP_USER`, `SMTP_PASSWORD` and optionally `SMTP_FROM`.
For Gmail use an **app password** (Google Account → Security → 2-Step Verification → App passwords). Without SMTP,
codes are shown on screen labelled DEMO.

### Google sign-in
1. Google Cloud Console → *APIs & Services* → *Credentials* → **Create OAuth client ID** (Web application).
2. Authorised redirect URI: `<app URL>/oauth2callback`.
3. In `secrets.toml`:
   ```toml
   [auth]
   redirect_uri = "https://<app URL>/oauth2callback"
   cookie_secret = "a-long-random-string"
   [auth.google]
   client_id = "...apps.googleusercontent.com"
   client_secret = "..."
   server_metadata_url = "https://accounts.google.com/.well-known/openid-configuration"
   ```
4. Restart – **Continue with Google** appears. Without it the button is hidden.
5. Only emails of active DEPORT accounts get in (Branch Admins can link a partner's email via *Link Google*).

### AI voice call for unaccepted orders
Twilio Voice keys plus `PUBLIC_BASE_URL` (where Twilio reaches the API). Run the API next to the app on the same
database – `docker compose` already does. Setup and testing with ngrok: [`AI_CALL.md`](AI_CALL.md). Without keys
the partner app shows a simulated call.

### AI (voice + understanding)
`GROQ_API_KEY` (free at console.groq.com) or `GEMINI_API_KEY`. Without a key, reports are understood by the
built-in Tamil/English rules and voice uses free Google speech recognition.

### Live data (weather, traffic, GPS)
`OWM_API_KEY` (OpenWeatherMap) and `TOMTOM_API_KEY` (TomTom Traffic Flow), both free tiers. GPS needs no key but the
app must be served over **https** (browsers share location only on https or localhost). See
[`REALTIME.md`](REALTIME.md).

### Learning from decisions
The API retrains the acceptance model once a day by itself. Without the API, run
`python scripts/retrain_acceptance.py` nightly (cron) on the same `DB_PATH` – see [`LEARNING.md`](LEARNING.md).

## Checklist before going live
- `DEMO_MODE` unset (no one-click demo chips).
- Change the demo passwords: Super Admin → *Admins* resets Branch Admin passwords; with SMTP set up everyone can use
  *Forgot password?*.
- Persistent disk mounted at the `DB_PATH` folder; a backup plan for it.
