import 'dart:async';
import 'dart:convert';

import 'package:connectivity_plus/connectivity_plus.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../api/api_client.dart';
import '../api/endpoints.dart';

/// Status updates (Accept, Picked up, Start, Delivered, Can't take) made without a connection are kept on the phone,
/// in order, and sent when the network is back – or when the app opens again. The screen updates at once.
/// An update the server refuses (409: already changed, 403: no longer yours, 404) is dropped and reported, never
/// retried forever. Photos and proof of delivery need a connection and are not queued.
class OfflineQueue {
  OfflineQueue(this._api);

  static const _key = 'deport.queue';
  final ApiClient _api;
  final _dropped = StreamController<String>.broadcast();
  final _size = StreamController<int>.broadcast();
  StreamSubscription<List<ConnectivityResult>>? _network;
  bool _flushing = false;
  int pending = 0;

  /// Messages for updates the server refused ("D07: Already delivered").
  Stream<String> get dropped => _dropped.stream;

  /// How many updates are waiting.
  Stream<int> get size => _size.stream;

  Future<void> start() async {
    pending = (await _load()).length;
    _size.add(pending);
    _network = Connectivity().onConnectivityChanged.listen((results) {
      if (results.any((r) => r != ConnectivityResult.none)) flush();
    });
    await flush();
  }

  Future<void> stop() async => _network?.cancel();

  /// Send now if possible; keep it for later if there is no connection. Returns true when it went out now.
  Future<bool> send(String endpoint, Map<String, String> params, {Map<String, dynamic>? json}) async {
    final (method, path) = Endpoints.resolve(endpoint, params);
    if (pending == 0) {
      try {
        await _api.replay(method, path, json);
        return true;
      } on ApiException catch (e) {
        if (!e.offline) rethrow;
      }
    }
    final items = await _load();
    items.add({'method': method, 'path': path, 'json': json, 'at': DateTime.now().toIso8601String()});
    await _save(items);
    return false;
  }

  Future<void> flush() async {
    if (_flushing) return;
    _flushing = true;
    try {
      final items = await _load();
      while (items.isNotEmpty) {
        final item = items.first;
        try {
          await _api.replay(item['method'] as String, item['path'] as String,
              (item['json'] as Map?)?.cast<String, dynamic>());
        } on ApiException catch (e) {
          if (e.offline) break; // still offline: keep the rest, in order
          if (e.status == 401) break; // signed out: the next sign-in flushes
          _dropped.add('${_label(item['path'] as String)}: ${e.message}');
        }
        items.removeAt(0);
        await _save(items);
      }
    } finally {
      _flushing = false;
    }
  }

  Future<void> clear() => _save([]);

  String _label(String path) => path.split('/').where((p) => p.isNotEmpty).skip(2).join(' ');

  Future<List<Map<String, dynamic>>> _load() async {
    final prefs = await SharedPreferences.getInstance();
    final raw = prefs.getString(_key);
    if (raw == null) return [];
    return (jsonDecode(raw) as List).map((e) => (e as Map).cast<String, dynamic>()).toList();
  }

  Future<void> _save(List<Map<String, dynamic>> items) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_key, jsonEncode(items));
    pending = items.length;
    _size.add(pending);
  }
}
