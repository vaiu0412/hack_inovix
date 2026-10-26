import 'package:flutter_secure_storage/flutter_secure_storage.dart';

/// Keeps the refresh token (the server-side session) in the phone's secure storage (Android Keystore).
/// The short-lived access token stays in memory only.
class TokenStore {
  TokenStore([FlutterSecureStorage? storage])
      : _storage = storage ?? const FlutterSecureStorage(aOptions: AndroidOptions(encryptedSharedPreferences: true));

  static const _key = 'deport.refresh_token';
  final FlutterSecureStorage _storage;

  Future<String?> readRefresh() => _storage.read(key: _key);
  Future<void> saveRefresh(String token) => _storage.write(key: _key, value: token);
  Future<void> clear() => _storage.delete(key: _key);
}
