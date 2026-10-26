import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:http/http.dart' as http;

import '../config.dart';
import '../services/token_store.dart';
import 'endpoints.dart';
import 'models.dart';

/// A failed call. status 0 = no connection (the offline queue keeps such updates for later).
class ApiException implements Exception {
  ApiException(this.status, this.message);

  final int status;
  final String message;

  bool get offline => status == 0;

  @override
  String toString() => message;
}

/// The DEPORT REST API with JWT access tokens. Sign-in stores the refresh token (the session) securely; an expired
/// access token is refreshed once automatically. The partner and branch always come from the token, never from
/// the app.
class ApiClient {
  ApiClient({http.Client? httpClient, TokenStore? tokens})
      : _http = httpClient ?? http.Client(),
        _tokens = tokens ?? TokenStore();

  final http.Client _http;
  final TokenStore _tokens;
  String? _access;
  Future<void>? _refreshing;

  String? get accessToken => _access;

  /// The signed-in role from the access token ('partner' or 'customer'); read only to pick the screens –
  /// the server checks the token on every call.
  String? get role {
    final parts = (_access ?? '').split('.');
    if (parts.length != 3) return null;
    try {
      final claims = jsonDecode(utf8.decode(base64Url.decode(base64Url.normalize(parts[1])))) as Map<String, dynamic>;
      return claims['role'] as String?;
    } catch (_) {
      return null;
    }
  }

  // ---------------------------------------------------------------- session
  Future<User> signIn(String identifier, String password) async {
    final body = await _call(Endpoints.login,
        json: {'identifier': identifier.trim(), 'password': password, 'remember_me': true}, auth: false);
    _access = body['token'] as String;
    await _tokens.saveRefresh(body['refresh_token'] as String);
    final user = User.fromJson((body['user'] as Map).cast<String, dynamic>());
    if (!user.isPartner) {
      await signOut();
      throw ApiException(403, user.isCustomer ? 'Customers sign in with a code.' : 'Use the web app for admin accounts.');
    }
    return user;
  }

  /// Ask for a 6-digit sign-in code by SMS or email (partners and customers). Returns (message, DEMO code or null).
  Future<(String, String?)> requestCode(String identifier, {String? channel}) async {
    final body = await _call(Endpoints.codeRequest,
        json: {'identifier': identifier.trim(), if (channel != null) 'channel': channel}, auth: false);
    return (body['message'] as String, body['demo_code'] as String?);
  }

  /// Sign in with the code that arrived. Partners and customers only (admins use the web app).
  Future<User> signInWithCode(String identifier, String code) async {
    final body = await _call(Endpoints.codeVerify,
        json: {'identifier': identifier.trim(), 'code': code.trim(), 'remember_me': true}, auth: false);
    _access = body['token'] as String;
    await _tokens.saveRefresh(body['refresh_token'] as String);
    final user = User.fromJson((body['user'] as Map).cast<String, dynamic>());
    if (!user.isPartner && !user.isCustomer) {
      await signOut();
      throw ApiException(403, 'Use the web app for admin accounts.');
    }
    return user;
  }

  /// Back in after a restart: a new access token from the saved session. False when it ended.
  Future<bool> resume() async {
    if (await _tokens.readRefresh() == null) return false;
    try {
      await refreshNow();
      return true;
    } on ApiException catch (e) {
      if (e.status == 401) await _tokens.clear();
      return false;
    }
  }

  /// One refresh at a time, however many calls hit 401 together.
  Future<void> refreshNow() => _refreshing ??= _refresh().whenComplete(() => _refreshing = null);

  Future<void> _refresh() async {
    final refresh = await _tokens.readRefresh();
    if (refresh == null) throw ApiException(401, 'Sign in again');
    final body = await _call(Endpoints.refresh, json: {'refresh_token': refresh}, auth: false);
    _access = body['token'] as String;
  }

  Future<void> signOut({String? pushToken}) async {
    try {
      if (pushToken != null) await _call(Endpoints.deviceRemove, json: {'token': pushToken});
      if (_access != null) await _call(Endpoints.logout);
    } on ApiException {
      // offline or already signed out: forget locally anyway
    }
    _access = null;
    await _tokens.clear();
  }

  // ---------------------------------------------------------------- partner data
  Future<(Profile, List<Message>)> me() async {
    final body = await _call(Endpoints.me);
    return (
      Profile.fromJson((body['profile'] as Map).cast<String, dynamic>()),
      _list(body['unread_messages']).map(Message.fromJson).toList(),
    );
  }

  Future<List<CustomerOrder>> myOrders() async =>
      _list(await _call(Endpoints.myOrders)).map(CustomerOrder.fromJson).toList();

  Future<List<Delivery>> deliveries() async => _list(await _call(Endpoints.deliveries)).map(Delivery.fromJson).toList();
  Future<List<Delivery>> offers() async => _list(await _call(Endpoints.offers)).map(Delivery.fromJson).toList();
  Future<List<Message>> messages() async => _list(await _call(Endpoints.messages)).map(Message.fromJson).toList();
  Future<List<Incident>> incidents() async => _list(await _call(Endpoints.issues)).map(Incident.fromJson).toList();

  Future<void> offersSeen(List<String> ids) => _call(Endpoints.offersSeen, json: {'delivery_ids': ids});
  Future<void> messagesRead() => _call(Endpoints.messagesRead);

  /// accepted | picked_up | in_transit | delivered (non-medical) – also replayed by the offline queue.
  Future<void> step(String deliveryId, String step) => step == 'delivered'
      ? _call(Endpoints.delivered, params: {'id': deliveryId})
      : _call(Endpoints.step, params: {'id': deliveryId, 'step': step});

  Future<void> decline(String deliveryId, String reason) =>
      _call(Endpoints.decline, params: {'id': deliveryId}, json: {'reason': reason});

  /// Sends the customer's code (WhatsApp). Returns the DEMO code when no messaging is set up on the server.
  Future<String?> sendProofCode(String deliveryId) async {
    final body = await _call(Endpoints.proofCode, params: {'id': deliveryId});
    return body['demo_code'] as String?;
  }

  Future<void> deliverWithProof(String deliveryId, {required Uint8List photo, String? code, Uint8List? signature}) =>
      _multipart(Endpoints.proof, params: {'id': deliveryId}, files: {
        'photo': (photo, 'proof.jpg'),
        if (signature != null) 'signature': (signature, 'signature.png'),
      }, fields: {
        if (code != null) 'code': code,
      });

  Future<Incident> report({String text = '', String? quickType}) async =>
      Incident.fromJson(await _call(Endpoints.report, json: {'text': text, 'quick_type': quickType}));

  Future<Incident> reportVoice(Uint8List wav, {String? quickType}) async => Incident.fromJson(await _multipart(
      Endpoints.reportVoice,
      files: {'audio': (wav, 'note.wav')},
      fields: {if (quickType != null) 'quick_type': quickType}));

  Future<Incident> reportPhoto(Uint8List photo, {String text = '', String? quickType}) async =>
      Incident.fromJson(await _multipart(Endpoints.reportPhoto,
          files: {'photo': (photo, 'photo.jpg')}, fields: {'text': text, if (quickType != null) 'quick_type': quickType}));

  Future<bool> sendLocation(double lat, double lng, double? accuracy) async {
    final body = await _call(Endpoints.location, json: {'lat': lat, 'lng': lng, 'accuracy_m': accuracy});
    return body['used'] == true;
  }

  Future<void> registerDevice(String pushToken) =>
      _call(Endpoints.deviceAdd, json: {'token': pushToken, 'platform': Platform.isIOS ? 'ios' : 'android'});

  /// A queued update, replayed as it was recorded (method + path + JSON body).
  Future<void> replay(String method, String path, Map<String, dynamic>? json) => _send(method, path, json: json);

  // ---------------------------------------------------------------- transport
  List<Map<String, dynamic>> _list(Object? value) =>
      (value as List? ?? const []).map((e) => (e as Map).cast<String, dynamic>()).toList();

  Future<dynamic> _call(String endpoint,
      {Map<String, String> params = const {}, Map<String, dynamic>? json, bool auth = true}) {
    final (method, path) = Endpoints.resolve(endpoint, params);
    return _send(method, path, json: json, auth: auth);
  }

  Future<dynamic> _send(String method, String path, {Map<String, dynamic>? json, bool auth = true}) async {
    Future<http.Response> attempt() {
      final request = http.Request(method, Uri.parse('$apiUrl$path'))
        ..headers.addAll({'Accept': 'application/json', if (auth && _access != null) 'Authorization': 'Bearer $_access'});
      if (json != null) {
        request.headers['Content-Type'] = 'application/json';
        request.body = jsonEncode(json);
      }
      return _http.send(request).then(http.Response.fromStream);
    }

    var reply = await _guard(attempt);
    if (reply.statusCode == 401 && auth) {
      await refreshNow();
      reply = await _guard(attempt);
    }
    return _decode(reply);
  }

  Future<dynamic> _multipart(String endpoint,
      {Map<String, String> params = const {},
      required Map<String, (Uint8List, String)> files,
      Map<String, String> fields = const {}}) async {
    final (method, path) = Endpoints.resolve(endpoint, params);
    Future<http.Response> attempt() {
      final request = http.MultipartRequest(method, Uri.parse('$apiUrl$path'))
        ..headers['Authorization'] = 'Bearer $_access'
        ..fields.addAll(fields);
      files.forEach((name, file) => request.files.add(http.MultipartFile.fromBytes(name, file.$1, filename: file.$2)));
      return _http.send(request).then(http.Response.fromStream);
    }

    var reply = await _guard(attempt, timeout: const Duration(seconds: 60));
    if (reply.statusCode == 401) {
      await refreshNow();
      reply = await _guard(attempt, timeout: const Duration(seconds: 60));
    }
    return _decode(reply);
  }

  Future<http.Response> _guard(Future<http.Response> Function() call,
      {Duration timeout = const Duration(seconds: 15)}) async {
    try {
      return await call().timeout(timeout);
    } on SocketException {
      throw ApiException(0, 'No connection');
    } on TimeoutException {
      throw ApiException(0, 'No connection');
    } on http.ClientException {
      throw ApiException(0, 'No connection');
    }
  }

  dynamic _decode(http.Response reply) {
    final text = utf8.decode(reply.bodyBytes);
    final body = text.isEmpty ? null : jsonDecode(text);
    if (reply.statusCode >= 200 && reply.statusCode < 300) return body;
    final detail = body is Map ? body['detail'] : null;
    throw ApiException(reply.statusCode, detail is String ? detail : 'Something went wrong (${reply.statusCode})');
  }
}
