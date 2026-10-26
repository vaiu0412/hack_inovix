import 'dart:async';

import 'package:geolocator/geolocator.dart';

import '../api/api_client.dart';
import '../config.dart';

/// Shares the phone's position every 30 s – only while the partner is on duty, also with the app in the background
/// (Android foreground service with a visible notification, so the partner always knows). Off duty: nothing is sent.
class LocationService {
  LocationService(this._api);

  final ApiClient _api;
  StreamSubscription<Position>? _stream;
  DateTime _lastSent = DateTime.fromMillisecondsSinceEpoch(0);
  String status = 'Location off';

  bool get running => _stream != null;

  /// Asks for permission when needed. Returns a short status line for the screen.
  Future<String> start() async {
    if (running) return status;
    if (!await Geolocator.isLocationServiceEnabled()) return status = 'Turn on location';
    var permission = await Geolocator.checkPermission();
    if (permission == LocationPermission.denied) permission = await Geolocator.requestPermission();
    if (permission == LocationPermission.denied || permission == LocationPermission.deniedForever) {
      return status = 'Location blocked – allow it in Settings';
    }
    final settings = AndroidSettings(
      accuracy: LocationAccuracy.high,
      distanceFilter: 20,
      intervalDuration: locationEvery,
      foregroundNotificationConfig: const ForegroundNotificationConfig(
        notificationTitle: 'DEPORT',
        notificationText: 'Sharing your location while on duty',
        enableWakeLock: true,
      ),
    );
    _stream = Geolocator.getPositionStream(locationSettings: settings).listen(_send, onError: (_) {});
    return status = 'Sharing location every 30 s';
  }

  Future<void> stop() async {
    await _stream?.cancel();
    _stream = null;
    status = 'Location off';
  }

  Future<void> _send(Position p) async {
    final now = DateTime.now();
    if (now.difference(_lastSent) < locationEvery - const Duration(seconds: 2)) return;
    _lastSent = now;
    try {
      await _api.sendLocation(p.latitude, p.longitude, p.accuracy);
    } on ApiException {
      // offline: the next position goes out instead (old positions are not worth queueing)
    }
  }
}
