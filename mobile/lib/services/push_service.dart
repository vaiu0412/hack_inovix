import 'dart:async';

import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_messaging/firebase_messaging.dart';

import '../api/api_client.dart';

/// Firebase Cloud Messaging: the server pushes "New order" when an order is offered (escalation level 0).
/// Optional – without android/app/google-services.json Firebase isn't set up and the app relies on the live feed
/// and the in-app ring (Demo mode).
class PushService {
  PushService(this._api);

  final ApiClient _api;
  final _offers = StreamController<String>.broadcast();
  StreamSubscription<String>? _refresh;
  String? token;
  bool available = false;

  /// Delivery ids from offer pushes (tapped or received while the app is open).
  Stream<String> get offers => _offers.stream;

  /// Called once at start-up; false when Firebase isn't configured for this build.
  static Future<bool> initialise() async {
    try {
      await Firebase.initializeApp();
      FirebaseMessaging.onBackgroundMessage(_background);
      return true;
    } catch (_) {
      return false;
    }
  }

  /// After sign-in: ask permission, register this phone with the server, listen for offers.
  Future<void> start() async {
    if (Firebase.apps.isEmpty) return;
    final messaging = FirebaseMessaging.instance;
    final settings = await messaging.requestPermission(alert: true, sound: true, badge: true);
    if (settings.authorizationStatus == AuthorizationStatus.denied) return;
    token = await messaging.getToken();
    if (token == null) return;
    available = true;
    await _register(token!);
    _refresh = messaging.onTokenRefresh.listen((fresh) {
      token = fresh;
      _register(fresh);
    });
    FirebaseMessaging.onMessage.listen(_handle);
    FirebaseMessaging.onMessageOpenedApp.listen(_handle);
    final opened = await messaging.getInitialMessage();
    if (opened != null) _handle(opened);
  }

  Future<void> stop() async {
    await _refresh?.cancel();
    available = false;
  }

  Future<void> _register(String pushToken) async {
    try {
      await _api.registerDevice(pushToken);
    } on ApiException {
      // offline: registered again on the next start
    }
  }

  void _handle(RemoteMessage message) {
    if (message.data['type'] == 'offer' && message.data['delivery_id'] != null) {
      _offers.add(message.data['delivery_id'] as String);
    }
  }
}

/// Runs in the background isolate when a push arrives and the app is closed: the system shows the notification
/// itself; tapping it opens the app on the offer (getInitialMessage).
@pragma('vm:entry-point')
Future<void> _background(RemoteMessage message) async {
  await Firebase.initializeApp();
}
