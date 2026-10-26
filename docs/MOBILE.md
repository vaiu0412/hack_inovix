# Mobile: the Flutter partner app

`mobile/` is a Flutter app for delivery partners. It uses only the public API – REST with JWT, the `/ws/partner`
WebSocket and Firebase push – so it sees exactly what the partner may see, scoped by the server from the token.
How to run it: [`mobile/README.md`](../mobile/README.md).

> Written without a Flutter SDK here: **not compiled or run yet**. Its contract with the API is tested
> (`tests/test_mobile_contract.py`): endpoints and methods, the JSON fields it reads, decline reasons and issue
> types. The Dart unit/widget tests in `mobile/test/` run with `flutter test` once Flutter is installed.

## Architecture
```
 Screens (login, today, orders, offer, proof, report, inbox, profile)
    │  read state, call methods – never the API directly
 AppState (ChangeNotifier, via AppScope)
    ├── ApiClient ──── REST + JWT ───────────────► FastAPI  /login /token/refresh /me/…
    ├── LiveFeed ───── WebSocket ────────────────► /ws/partner?token=…&since=…
    ├── OfflineQueue ─ shared_preferences ───────► replays status updates in order when back online
    ├── PushService ── Firebase Cloud Messaging ─► POST /me/devices; "New order" pushes
    └── LocationService ─ geolocator (foreground service) ─► POST /me/location every 30 s on duty
 TokenStore: refresh token in Android Keystore (flutter_secure_storage); access token in memory only
```

## Flows
- **Sign-in:** `POST /login` (partners: ID + password) or a code (`POST /otp/request` → SMS/email →
  `POST /otp/verify`; partners and customers) → a 60-minute JWT (memory) + the session's refresh token (secure
  storage). A 401 refreshes once (`POST /token/refresh`); a refresh that fails returns to the sign-in screen.
  Admin accounts are refused (web only). Restarting the app resumes the session without a password.
- **Customers:** after code sign-in they get **My orders** (`GET /my/orders`, every 30 s): stage, ETA, partner's
  first name, a progress bar and *Live map* (the public tracking page). No live feed, push, location or queue.
- **New order:** the server offers it (escalation level 0) → `offer` change on the live feed and, with Firebase, a
  push → the app opens the **full-screen offer** once per order and tells the server it was seen
  (`POST /me/offers/seen`, *Sent → Seen* on the admin's timeline). **Accept** or **Can't take** + reason.
- **Work:** each order shows one next step – Accept → Picked up → Start → Delivered. **Medical** orders open the
  proof sheet first: a camera photo + *Send code to customer* (WhatsApp, or the DEMO code on screen in Demo mode) +
  the 4-digit code → `POST /me/deliveries/{id}/pod`.
- **Offline:** steps and Can't take made without a network are saved on the phone and sent in order when the
  network or the app comes back; the screen updates at once and shows *N waiting to send*. The server stays the
  judge: a step it refuses (already changed, reassigned) is dropped with a message, never retried forever. Photos,
  proof and reports need a connection.
- **Live:** the WebSocket reconnects with back-off (1 s → 30 s) and catches up with `since`; changes refresh the lists
  (debounced). The Today screen shows *Live* / *Offline*.
- **Location:** only while the partner's status is *on duty*: every 30 s, also in the background through an Android
  foreground service with a visible notification. Off duty, nothing is sent. The server ignores points outside
  Coimbatore.
- **Reports:** a type tile, text, a voice note (WAV, 16 kHz – what the server's speech recognition reads) or a
  photo → the branch gets an alert with a plan, like a web report.

## Limits
- Not built or run yet (see above).
- English only; the web partner pages have Tamil – porting `i18n/ta.json` is the next step.
- Proof by signature is web-only for now (the API accepts a `signature` file; the app sends photo + code).
- The full-screen offer has no ringtone of its own; with Firebase the system notification sound plays.
- iOS was not set up (Android first: background location and push need extra iOS configuration).
