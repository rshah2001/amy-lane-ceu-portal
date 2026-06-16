import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../models/models.dart';
import 'api_client.dart';

class SessionController extends ChangeNotifier {
  SessionController() {
    api.onUnauthorized = _handleUnauthorized;
  }

  final ApiClient api = ApiClient();
  PortalUser? user;
  String? error;
  bool loading = false;

  bool get isAuthenticated => user != null && api.token != null;

  void _handleUnauthorized() {
    if (user == null && api.token == null) return; // already signed out
    error = 'Your session expired. Please sign in again.';
    logout();
  }

  Future<void> restore() async {
    final preferences = await SharedPreferences.getInstance();
    final token = preferences.getString('access_token');
    final userJson = preferences.getString('user');
    if (token == null || userJson == null) return;
    api.token = token;
    user = PortalUser.fromJson(jsonDecode(userJson) as Map<String, dynamic>);
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
      error = exception.message;
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

