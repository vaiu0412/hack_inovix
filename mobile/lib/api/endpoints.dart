/// Every API call the app makes, in one place ("METHOD /path"). tests/test_mobile_contract.py (Python) checks each
/// one against the real FastAPI routes, so the app and the server can't drift apart unnoticed.
class Endpoints {
  static const login = 'POST /login';
  static const refresh = 'POST /token/refresh';
  static const logout = 'POST /logout';
  static const me = 'GET /me';
  static const deliveries = 'GET /me/deliveries';
  static const offers = 'GET /me/offers';
  static const offersSeen = 'POST /me/offers/seen';
  static const step = 'POST /me/deliveries/{id}/{step}';
  static const decline = 'POST /me/deliveries/{id}/decline';
  static const delivered = 'POST /me/deliveries/{id}/delivered';
  static const proofCode = 'POST /me/deliveries/{id}/pod/code';
  static const proof = 'POST /me/deliveries/{id}/pod';
  static const issues = 'GET /me/issues';
  static const report = 'POST /me/issues';
  static const reportVoice = 'POST /me/issues/voice';
  static const reportPhoto = 'POST /me/issues/photo';
  static const messages = 'GET /me/messages';
  static const messagesRead = 'POST /me/messages/read';
  static const location = 'POST /me/location';
  static const deviceAdd = 'POST /me/devices';
  static const deviceRemove = 'DELETE /me/devices';
  static const live = 'WS /ws/partner';

  /// "POST /me/deliveries/{id}/{step}" + {'id': 'D07', 'step': 'picked_up'} -> ('POST', '/me/deliveries/D07/picked_up')
  static (String, String) resolve(String endpoint, [Map<String, String> params = const {}]) {
    final space = endpoint.indexOf(' ');
    var path = endpoint.substring(space + 1);
    params.forEach((key, value) => path = path.replaceAll('{$key}', Uri.encodeComponent(value)));
    return (endpoint.substring(0, space), path);
  }
}
