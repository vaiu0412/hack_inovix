import 'dart:async';
import 'dart:convert';
import 'dart:math' as math;

import 'package:web_socket_channel/web_socket_channel.dart';

import '../api/api_client.dart';
import '../api/endpoints.dart';
import '../api/models.dart';
import '../config.dart';

/// The partner's live feed (/ws/partner): new offers, escalation steps and messages as they happen.
/// Reconnects by itself (1 s, 2 s, 4 s … up to 30 s) and catches up with `since`, so nothing is missed while the
/// phone was offline. A 4401 close (token expired or session ended) refreshes the token once, then retries.
class LiveFeed {
  LiveFeed(this._api);

  final ApiClient _api;
  final _changes = StreamController<LiveChange>.broadcast();
  final _connected = StreamController<bool>.broadcast();
  WebSocketChannel? _channel;
  StreamSubscription<dynamic>? _subscription;
  Timer? _ping, _retry;
  int _lastId = 0;
  int _attempt = 0;
  bool _running = false;
  bool isConnected = false;

  Stream<LiveChange> get changes => _changes.stream;
  Stream<bool> get connected => _connected.stream;

  void start() {
    if (_running) return;
    _running = true;
    _connect();
  }

  Future<void> stop() async {
    _running = false;
    _retry?.cancel();
    await _close();
  }

  Future<void> _connect() async {
    final token = _api.accessToken;
    if (!_running || token == null) return;
    final (_, path) = Endpoints.resolve(Endpoints.live);
    final since = _lastId > 0 ? '&since=$_lastId' : '';
    final uri = Uri.parse('$wsUrl$path?token=${Uri.encodeQueryComponent(token)}$since');
    try {
      final channel = WebSocketChannel.connect(uri);
      await channel.ready;
      _channel = channel;
      _subscription = channel.stream.listen(_onMessage, onDone: _onClosed, onError: (_) => _onClosed());
      _ping = Timer.periodic(const Duration(seconds: 25), (_) => _channel?.sink.add('ping'));
    } catch (_) {
      _scheduleRetry();
    }
  }

  void _onMessage(dynamic raw) {
    final message = jsonDecode(raw as String) as Map<String, dynamic>;
    switch (message['type']) {
      case 'hello':
        _attempt = 0;
        if (_lastId == 0) _lastId = (message['last_id'] as num?)?.toInt() ?? 0;
        _setConnected(true);
      case 'change':
        final change = LiveChange.fromJson(message);
        if (change.id > _lastId) _lastId = change.id;
        _changes.add(change);
    }
  }

  Future<void> _onClosed() async {
    final code = _channel?.closeCode;
    await _close();
    _setConnected(false);
    if (!_running) return;
    if (code == 4401) {
      try {
        await _api.refreshNow();
      } on ApiException {
        _running = false; // the session ended: the app shows the sign-in screen
        return;
      }
    }
    _scheduleRetry();
  }

  void _scheduleRetry() {
    _retry?.cancel();
    final seconds = const [1, 2, 4, 8, 15, 30][math.min(_attempt, 5)];
    _attempt++;
    _retry = Timer(Duration(seconds: seconds), _connect);
  }

  Future<void> _close() async {
    _ping?.cancel();
    await _subscription?.cancel();
    await _channel?.sink.close();
    _subscription = null;
    _channel = null;
  }

  void _setConnected(bool value) {
    if (value == isConnected) return;
    isConnected = value;
    _connected.add(value);
  }
}
