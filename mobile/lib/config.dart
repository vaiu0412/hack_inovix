/// Where the DEPORT API runs. Set at build time:
///   flutter run --dart-define=API_URL=https://api.your-domain.com
/// The default reaches a local `uvicorn api.main:app --host 0.0.0.0` from the Android emulator.
const String apiUrl = String.fromEnvironment('API_URL', defaultValue: 'http://10.0.2.2:8000');

/// ws:// or wss:// for the live feed, from the API URL.
String get wsUrl => apiUrl.replaceFirst(RegExp(r'^http'), 'ws');

/// How often the phone reports its position while on duty (the server ignores points outside Coimbatore).
const Duration locationEvery = Duration(seconds: 30);

/// Reasons a partner can give for "Can't take" (same list as the server's escalation.DECLINE_REASONS).
const List<String> declineReasons = ['Too far', 'Vehicle issue', 'On break', 'Too much work', 'Other'];

/// Quick issue types (same keys as the server's parser).
const Map<String, String> issueTypes = {
  'breakdown': 'Breakdown',
  'accident': 'Accident',
  'traffic': 'Traffic',
  'flood': 'Flood',
  'closure': 'Road closed',
  'protest': 'Protest',
  'customer_unavailable': 'Customer away',
  'requirement_change': 'Order change',
};
