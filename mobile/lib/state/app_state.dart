import 'dart:async';
import 'dart:typed_data';

import 'package:flutter/foundation.dart';

import '../api/api_client.dart';
import '../api/endpoints.dart';
import '../api/models.dart';
import '../services/live_feed.dart';
import '../services/location_service.dart';
import '../services/offline_queue.dart';
import '../services/push_service.dart';

/// Everything the screens show, in one place. Screens call methods here; nothing talks to the API directly.
class AppState extends ChangeNotifier {
  AppState({ApiClient? api}) : api = api ?? ApiClient() {
    live = LiveFeed(this.api);
    queue = OfflineQueue(this.api);
    push = PushService(this.api);
    location = LocationService(this.api);
  }

  final ApiClient api;
  late final LiveFeed live;
  late final OfflineQueue queue;
  late final PushService push;
  late final LocationService location;

  final _notices = StreamController<String>.broadcast();
  final List<StreamSubscription<dynamic>> _subscriptions = [];
  final Set<String> _seen = {};
  Timer? _debounce;

  bool booting = true;
  bool signedIn = false;
  bool loading = false;
  Profile? profile;
  List<Delivery> deliveries = [];
  List<Delivery> offers = [];
  List<Message> messages = [];
  List<Incident> incidents = [];

  /// Short one-line messages for a snackbar ("Saved offline – sent when you're back online").
  Stream<String> get notices => _notices.stream;

  int get unread => messages.where((m) => !m.read).length;
  List<Delivery> get open => deliveries.where((d) => !d.done).toList();
  Delivery? get nextStop => open.isEmpty ? null : open.first;
  bool get liveConnected => live.isConnected;
  int get pendingUpdates => queue.pending;

  // ---------------------------------------------------------------- session
  Future<void> boot() async {
    signedIn = await api.resume();
    if (signedIn) await _afterSignIn();
    booting = false;
    notifyListeners();
  }

  Future<void> signIn(String identifier, String password) async {
    await api.signIn(identifier, password);
    signedIn = true;
    await _afterSignIn();
    notifyListeners();
  }

  Future<void> signOut() async {
    for (final s in _subscriptions) {
      await s.cancel();
    }
    _subscriptions.clear();
    await live.stop();
    await location.stop();
    await push.stop();
    await queue.stop();
    await queue.clear();
    await api.signOut(pushToken: push.token);
    signedIn = false;
    profile = null;
    deliveries = [];
    offers = [];
    messages = [];
    incidents = [];
    _seen.clear();
    notifyListeners();
  }

  Future<void> _afterSignIn() async {
    _subscriptions
      ..add(live.changes.listen((_) => _soon()))
      ..add(live.connected.listen((_) => notifyListeners()))
      ..add(queue.size.listen((_) => notifyListeners()))
      ..add(queue.dropped.listen(_notices.add))
      ..add(push.offers.listen((_) => _soon()));
    await refresh();
    live.start();
    await queue.start();
    unawaited(push.start());
    await _locationForDuty();
  }

  // ---------------------------------------------------------------- data
  Future<void> refresh() async {
    loading = true;
    notifyListeners();
    try {
      final results = await Future.wait([api.me(), api.deliveries(), api.offers(), api.messages(), api.incidents()]);
      profile = (results[0] as (Profile, List<Message>)).$1;
      deliveries = results[1] as List<Delivery>;
      offers = results[2] as List<Delivery>;
      messages = results[3] as List<Message>;
      incidents = results[4] as List<Incident>;
      final fresh = offers.map((o) => o.id).where((id) => !_seen.contains(id)).toList();
      if (fresh.isNotEmpty) {
        _seen.addAll(fresh);
        unawaited(api.offersSeen(fresh).catchError((_) {}));
      }
    } on ApiException catch (e) {
      if (e.status == 401) {
        await signOut();
        _notices.add('Signed out – please sign in again');
      } else if (!e.offline) {
        _notices.add(e.message);
      }
    } finally {
      loading = false;
      notifyListeners();
    }
  }

  void _soon() {
    _debounce?.cancel();
    _debounce = Timer(const Duration(milliseconds: 400), refresh);
  }

  Future<void> _locationForDuty() async {
    if (profile?.onDuty ?? false) {
      await location.start();
    } else {
      await location.stop();
    }
  }

  // ---------------------------------------------------------------- actions (queued when offline)
  Future<void> accept(Delivery offer) => _step(offer, 'accepted');

  Future<void> advance(Delivery d) async {
    final next = d.nextStep;
    if (next == null) return;
    await _step(d, next.$1);
  }

  Future<void> decline(Delivery offer, String reason) async {
    _replace(offer.withStatus('unassigned'), removeOffer: true);
    await _queued(Endpoints.decline, {'id': offer.id}, json: {'reason': reason});
  }

  Future<void> _step(Delivery d, String step) async {
    _replace(d.withStatus(step), removeOffer: step == 'accepted');
    await _queued(step == 'delivered' ? Endpoints.delivered : Endpoints.step, {'id': d.id, 'step': step});
  }

  Future<void> _queued(String endpoint, Map<String, String> params, {Map<String, dynamic>? json}) async {
    try {
      final sentNow = await queue.send(endpoint, params, json: json);
      if (!sentNow) _notices.add('Saved offline – sent when you are back online');
      _soon();
    } on ApiException catch (e) {
      _notices.add(e.message);
      await refresh(); // the server said no: show what is really there
    }
  }

  void _replace(Delivery updated, {bool removeOffer = false}) {
    deliveries = [for (final d in deliveries) d.id == updated.id ? updated : d];
    if (removeOffer) offers = offers.where((o) => o.id != updated.id).toList();
    notifyListeners();
  }

  // ---------------------------------------------------------------- online only
  Future<String?> sendProofCode(Delivery d) => api.sendProofCode(d.id);

  Future<void> deliverWithProof(Delivery d, {required Uint8List photo, String? code, Uint8List? signature}) async {
    await api.deliverWithProof(d.id, photo: photo, code: code, signature: signature);
    _replace(d.withStatus('delivered'));
    _soon();
  }

  Future<Incident> report({String text = '', String? quickType, Uint8List? photo, Uint8List? voice}) async {
    final Incident incident;
    if (photo != null) {
      incident = await api.reportPhoto(photo, text: text, quickType: quickType);
    } else if (voice != null) {
      incident = await api.reportVoice(voice, quickType: quickType);
    } else {
      incident = await api.report(text: text, quickType: quickType);
    }
    incidents = [incident, ...incidents];
    notifyListeners();
    return incident;
  }

  Future<void> markMessagesRead() async {
    if (unread == 0) return;
    try {
      await api.messagesRead();
      await refresh();
    } on ApiException {
      // offline: try again next time
    }
  }

  @override
  void dispose() {
    _debounce?.cancel();
    live.stop();
    location.stop();
    super.dispose();
  }
}
