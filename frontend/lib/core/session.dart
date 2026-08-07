import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../models/models.dart';
import 'api_client.dart';

class SessionController extends ChangeNotifier {
  /// [api] is for tests. Production builds the default client, which routes
  /// through `package:http`'s top-level helpers and so still honours
  /// `http.runWithClient`.
  SessionController({ApiClient? api}) : api = api ?? ApiClient() {
    this.api.onUnauthorized = _handleUnauthorized;
  }

  final ApiClient api;
  PortalUser? user;
  String? error;
  bool loading = false;

  bool get isAuthenticated => user != null && api.token != null;

  void _handleUnauthorized() {
    if (user == null && api.token == null) return; // already signed out
    error = 'Your session expired. Please sign in again.';
    logout();
  }

  /// How long startup is willing to wait for the token check.
  ///
  /// [restore] is awaited before the first frame, so this is a splash screen the
  /// user is staring at — much shorter than the client's own 30s ceiling. A
  /// server that hasn't answered by then is treated as unreachable, not as a
  /// rejection.
  static const _validationTimeout = Duration(seconds: 8);

  Future<void> restore() async {
    final preferences = await SharedPreferences.getInstance();
    final token = preferences.getString('access_token');
    final userJson = preferences.getString('user');
    if (token == null || userJson == null) return;
    api.token = token;
    final cached = PortalUser.fromJson(jsonDecode(userJson) as Map<String, dynamic>);
    // The stored token used to be trusted outright, so a session that had
    // expired, been revoked, or belonged to a since-deactivated account still
    // painted the full admin shell — and only fell over on the first request,
    // one page in, as an unexplained error. Ask the server once, before the
    // first frame, and let it decide.
    try {
      final json = await api.get('/auth/me', timeout: _validationTimeout)
          as Map<String, dynamic>;
      // The response is also the freshest copy of the account: a role changed
      // from admin to presenter since last login takes effect here rather than
      // handing the user a sidebar full of pages they can no longer open.
      user = PortalUser.fromJson(json);
      await preferences.setString('user', jsonEncode(json));
    } on ApiException catch (exception) {
      // 401 already routed through [_handleUnauthorized]; 403 is a live token on
      // a deactivated account. Anything else is the server's problem, not the
      // token's.
      if (exception.statusCode == 401 || exception.statusCode == 403) {
        await logout();
        return;
      }
      user = cached;
    } catch (_) {
      // Offline, or the check timed out. Signing the user out because their
      // wifi dropped would be worse than trusting the cached session: the very
      // next request will 401 if the token really is dead.
      user = cached;
    }
    notifyListeners();
  }

  Future<bool> login(String email, String password) async {
    loading = true;
    error = null;
    notifyListeners();
    try {
      final json = await api.post('/auth/login', {
        'email': email.trim(),
        'password': password,
      }) as Map<String, dynamic>;
      api.token = json['access_token'] as String;
      user = PortalUser.fromJson(json['user'] as Map<String, dynamic>);
      final preferences = await SharedPreferences.getInstance();
      await preferences.setString('access_token', api.token!);
      await preferences.setString('user', jsonEncode(json['user']));
      return true;
    } on ApiException catch (exception) {
      // The login endpoint names the problem ("Incorrect email or password");
      // a proxy failing in front of it does not, and an empty banner tells the
      // user nothing.
      error = exception.message.trim().isEmpty
          ? 'Could not sign in. Please try again in a moment.'
          : exception.message;
      return false;
    } catch (_) {
      // Timeouts and socket failures used to escape login() entirely and land
      // as an unhandled exception, leaving the button stuck on its spinner.
      error = 'Could not reach the server. Check your connection and try again.';
      return false;
    } finally {
      loading = false;
      notifyListeners();
    }
  }

  Future<void> logout() async {
    api.token = null;
    user = null;
    final preferences = await SharedPreferences.getInstance();
    await preferences.remove('access_token');
    await preferences.remove('user');
    notifyListeners();
  }
}

