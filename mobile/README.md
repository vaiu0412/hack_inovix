# DEPORT partner app (Flutter)

The delivery partner's phone app on top of the DEPORT API: today's orders, new-order offers (Accept / Can't take),
status steps, proof of delivery, issue reports by voice, photo or text, inbox, live updates, push and location
sharing while on duty. Dark glass look, same colours as the web app. Architecture: [`../docs/MOBILE.md`](../docs/MOBILE.md).

> **Status:** source code only. It was written without a Flutter SDK on the build machine, so it has **not been
> compiled or run yet** – no APK is included and none is claimed. What *is* checked automatically: every endpoint
> the app calls, every JSON field it reads and the lists it shares with the server (`tests/test_mobile_contract.py`,
> part of the Python suite and CI). Expect to fix small compile issues on the first `flutter analyze`.

## Run it on Android
1. Install **Flutter 3.27+** (includes Dart) and **Android Studio** (Android SDK, an emulator or a phone with USB
   debugging). Check with `flutter doctor`.
2. Generate the Android project around the sources (keeps `lib/`, `test/` and `pubspec.yaml` as they are):
   ```bash
   cd mobile
   flutter create --org in.deport --project-name deport_partner --platforms android .
   ```
3. Open `android/app/src/main/AndroidManifest.xml` and add the permissions from
   [`android_setup/AndroidManifest.additions.xml`](android_setup/AndroidManifest.additions.xml). For a local
   `http://` API also add `android:usesCleartextTraffic="true"` to `<application>` (development only).
4. In `android/app/build.gradle.kts` (or `build.gradle`) set `minSdk = 23` (voice recording needs it).
5. Get the packages and run the tests:
   ```bash
   flutter pub get
   flutter analyze
   flutter test
   ```
6. Start the API on your computer (from the project root), reachable from the phone:
   ```bash
   uvicorn api.main:app --host 0.0.0.0 --port 8000
   ```
7. Run the app. The emulator reaches your computer at `10.0.2.2`; a real phone needs your computer's LAN address:
   ```bash
   flutter run --dart-define=API_URL=http://10.0.2.2:8000
   ```
   Sign in with a partner account (the demo accounts are listed in the main README).
8. Release build against a hosted API (https/wss):
   ```bash
   flutter build apk --release --dart-define=API_URL=https://api.your-domain.com
   ```

## Push notifications (optional)
Without Firebase the app works fully: offers arrive over the live feed and open full-screen; the server's
escalation still rings, calls and alerts the admin. To get a push when an order is offered:
1. Create a Firebase project and add an Android app with package `in.deport.deport_partner`.
2. `dart pub global activate flutterfire_cli` and `flutterfire configure` in `mobile/` – this adds
   `android/app/google-services.json` and the Gradle plugin.
3. On the server set `FCM_PROJECT_ID` and `FCM_SERVICE_ACCOUNT` (see `.env.example`). The app registers the phone
   (`POST /me/devices`) after sign-in.

## What's where
```
lib/main.dart               start-up: Firebase (if configured), sign-in or home
lib/config.dart             API_URL, location interval, decline reasons, issue types
lib/theme.dart              DEPORT dark glass colours
lib/api/                    endpoints.dart (every call), api_client.dart (JWT + refresh), models.dart
lib/services/               live_feed (WebSocket), push_service (FCM), location_service (on duty, background),
                            offline_queue (status updates without network), token_store (secure storage)
lib/state/app_state.dart    everything the screens show; the only place that calls the API
lib/screens/                login, home (tabs), today, deliveries, offer, proof sheet, report, inbox, profile
lib/widgets/common.dart     AppScope, GlassCard, StatusPill, EmptyState
test/                       models + sign-in widget test
android_setup/              manifest permissions to add after `flutter create`
```
