# Platform: PostgreSQL, migrations, mobile API, live updates, push

The production path. Everything here is optional: with no settings DEPORT still runs on one SQLite file, exactly
as before, and the demo is unchanged.

| Piece | Default (nothing set) | With settings |
|---|---|---|
| **Database** | SQLite file (`DB_PATH`, default `data/deport.db`) | PostgreSQL (`DATABASE_URL`), PostGIS when installed |
| **Schema** | created from `modules/schema.py` on start-up | Alembic migrations (`migrations/`), run on start-up |
| **API auth** | JWT access tokens, secret made once and kept in the database | `JWT_SECRET` |
| **Live updates** | WebSockets `/ws/partner`, `/ws/admin` (API) · the Streamlit screens poll as before | – |
| **Push** | none (in-app ring → call → admin alert still run) | Firebase Cloud Messaging (`FCM_PROJECT_ID`, `FCM_SERVICE_ACCOUNT`) |

## Database (`modules/schema.py`, `modules/db.py`, `modules/store.py`)
- **One schema.** Every table and index is defined once with SQLAlchemy Core in `modules/schema.py`. SQLite files
  are created from it (`CREATE TABLE IF NOT EXISTS`, older files keep being upgraded in place by `store.init_db`);
  PostgreSQL is created and upgraded by Alembic from the same definitions. Tests check that a fresh SQLite file, a
  migrated PostgreSQL database and `schema.py` agree, and CI runs `alembic check` (no drift).
- **One SQL.** The engine keeps its plain SQL with `?` placeholders. On PostgreSQL every statement goes through
  SQLAlchemy (psycopg 3) after a small, cached translation: `?` → `%s`, `INSERT OR IGNORE` → `ON CONFLICT DO
  NOTHING`, `INSERT OR REPLACE` → an upsert on the primary key, `RETURNING <id>` so `lastrowid` works, `PRAGMA`
  skipped. Rows behave like `sqlite3.Row`. Transactions keep their meaning: `store.transaction()` is all-or-nothing on
  both.
- **Turn it on:** `DATABASE_URL=postgresql://user:pass@host:5432/deport` (`postgres://` works too). The first start
  runs `alembic upgrade head` (under an advisory lock, so the app and the API can start together) and loads the demo
  into an empty database. `DATABASE_SCHEMA` puts the tables in another schema (default `public`).
  By hand: `DATABASE_URL=… alembic upgrade head`.
- **PostGIS:** migration `0002` installs the extension when the server offers it and indexes vehicle positions
  (GiST on a geography expression). `store.nearest_vehicles()` then orders by `<->` and measures with
  `ST_Distance` on the spheroid; without PostGIS it uses the same straight-line formula as the rest of the app.
  API: `GET /vehicles/nearest?lat=…&lng=…` (Branch Admin, own branch).
- **Files** (photos, voice notes, proof of delivery) stay on disk next to `DB_PATH` – mount a volume at `/data`.
- **Backups:** SQLite keeps its timestamped copy before a demo reset. On PostgreSQL `backup()` returns nothing –
  use `pg_dump` or your host's snapshots.
- **docker compose:** `docker compose --profile postgres up --build` starts PostGIS 16 next to the app and API; put
  `DATABASE_URL=postgresql://deport:deport@db:5432/deport` in `.env` (change the password with `POSTGRES_PASSWORD`).

## Mobile API (`api/main.py`, `modules/tokens.py`)
- `POST /login` → `{token, access_token, token_type, expires_in, refresh_token, user}`. The access token is a JWT
  (HS256, 60 minutes, never longer than its session) with `sub`, `role`, `branch`, `dp` and `sid` – the hash of a
  server-side session, never the session token itself.
- Every request checks the signature **and** that the session is still valid, so `POST /logout`, deactivating a
  user or switching off a branch stops all of that session's tokens at once.
- `POST /token/refresh {refresh_token}` → a new access token while the session lasts (8 h, or 7 days with
  *remember me*). The app's own session tokens are still accepted as bearer tokens.
- Partner endpoints take the partner and branch from the token only: my deliveries, route, offers, accept / steps /
  decline, delivered (+ proof), report issue (text, voice, **photo**: `POST /me/issues/photo`), location, messages,
  **devices** (`POST/DELETE /me/devices` for push).
- Admin endpoints: KPIs, partners, deliveries, map, issues, escalations, insights (read-only), nearest vehicles, and
  approve / reject a plan. Full list with schemas at `/docs`.

## Live updates (`api/live.py`, `store.emit`)
- Every change worth telling someone about is written to a small **`changes` table in the same transaction** as the
  change itself: offer and escalation steps (for that partner), history events and alerts (for the branch), messages
  to a partner. A rolled-back change is never announced.
- The API has one poller that reads new rows every second and hands each to the open sockets allowed to see it. It
  works across processes (app and API share the database) and on both databases. The table is pruned to the newest
  5 000 rows.
- `ws://host/ws/partner?token=…` – the partner's own offers, escalation steps and messages.
  `ws://host/ws/admin?token=…` – a Branch Admin's branch (a Super Admin sees all).
  Add `&since=<id>` to catch up after being offline. Messages: `{"type": "hello"}`, then
  `{"type": "change", "id", "kind": "offer" | "event" | "message", "time", "branch_id", "dp_id", "data"}`;
  send `ping`, get `{"type": "pong"}`. Close codes: 4401 (no/invalid token, session ended – re-checked every
  minute), 4403 (wrong role).
- The Streamlit screens keep polling the data version (every few seconds) – nothing to set up.

## Push (`services/push.py`)
- Escalation **level 0**: when an order is offered and the partner registered a phone, a high-priority FCM push
  (title *New order*, text *D31: accept or say you can't take it.*) goes out **after the commit**
  (`store.after_commit`), so a rolled-back assignment never rings anyone. The timeline shows *Push sent to 1 phone(s)*.
- A phone token Firebase says is gone is deleted. Without the keys or without a phone nothing is sent and nothing
  is logged; ringing, the call and the admin alert follow as before.
- Setup: Firebase console → Project settings → Service accounts → *Generate new private key*. Set
  `FCM_PROJECT_ID` and `FCM_SERVICE_ACCOUNT` (the JSON, or a path to the file). The service account's OAuth token is
  made with the key (RS256) and cached for an hour.

## Tests
- `pytest -q` runs everything on SQLite (no keys, no network).
- `TEST_DATABASE_URL=postgresql://… pytest -q` runs the same suite on PostgreSQL – each test in its own schema,
  dropped afterwards; the few tests that edit the SQLite file directly are skipped. CI does both (PostGIS 16 service)
  and checks that `alembic upgrade head` works from scratch and matches `schema.py`.
- Locally without Docker, `pip install pgserver` gives a throwaway PostgreSQL for this.

## Limits
- Live updates are polled once a second from the `changes` table (no `LISTEN/NOTIFY` yet) – fine for a city
  branch, not for thousands of sockets per process.
- WebSockets authenticate with the token in the query string (browsers can't set headers on them); use HTTPS/WSS
  so it isn't sent in clear, and keep access tokens short-lived (they are: 60 minutes).
- The Streamlit app itself doesn't use the WebSockets; it keeps polling.
- Push covers new offers only; ringing, the call and the alert still come from the escalation timer.
