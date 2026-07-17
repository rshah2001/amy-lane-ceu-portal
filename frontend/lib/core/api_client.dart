import 'dart:convert';
import 'dart:typed_data';

import 'package:http/http.dart' as http;

class ApiException implements Exception {
  ApiException(this.message, this.statusCode);
  final String message;
  final int statusCode;

  @override
  String toString() => message;
}

class ApiClient {
  ApiClient({String? baseUrl})
      : baseUrl = baseUrl ??
            const String.fromEnvironment(
              'API_BASE_URL',
              defaultValue: 'http://localhost:8000/api',
            );

  final String baseUrl;
  String? token;

  /// Called when an authenticated request is rejected with 401, so the app can
  /// clear the stale session and return to the login screen.
  void Function()? onUnauthorized;

  Map<String, String> get _headers => {
        'Content-Type': 'application/json',
        if (token != null) 'Authorization': 'Bearer $token',
      };

  Future<dynamic> get(String path) async {
    return _decode(await http.get(Uri.parse('$baseUrl$path'), headers: _headers));
  }

  Future<dynamic> post(String path, [Map<String, dynamic>? body]) async {
    return _decode(
      await http.post(
        Uri.parse('$baseUrl$path'),
        headers: _headers,
        body: jsonEncode(body ?? <String, dynamic>{}),
      ),
    );
  }

  Future<dynamic> put(String path, [Map<String, dynamic>? body]) async {
    return _decode(
      await http.put(
        Uri.parse('$baseUrl$path'),
        headers: _headers,
        body: jsonEncode(body ?? <String, dynamic>{}),
      ),
    );
  }

  Future<dynamic> patch(String path, [Map<String, dynamic>? body]) async {
    return _decode(
      await http.patch(
        Uri.parse('$baseUrl$path'),
        headers: _headers,
        body: jsonEncode(body ?? <String, dynamic>{}),
      ),
    );
  }

  Future<dynamic> delete(String path) async {
    return _decode(await http.delete(Uri.parse('$baseUrl$path'), headers: _headers));
  }

  Future<dynamic> uploadFile(
    String path,
    Uint8List bytes,
    String filename, {
    Map<String, String>? fields,
  }) async {
    final request = http.MultipartRequest('POST', Uri.parse('$baseUrl$path'));
    if (token != null) request.headers['Authorization'] = 'Bearer $token';
    if (fields != null) request.fields.addAll(fields);
    request.files.add(http.MultipartFile.fromBytes('file', bytes, filename: filename));
    return _decode(await http.Response.fromStream(await request.send()));
  }

  Future<Uint8List> download(String path) async {
    final response = await http.get(Uri.parse('$baseUrl$path'), headers: _headers);
    if (response.statusCode < 200 || response.statusCode >= 300) {
      _decode(response);
    }
    return response.bodyBytes;
  }

  dynamic _decode(http.Response response) {
    final dynamic body = response.body.isEmpty ? null : jsonDecode(response.body);
    if (response.statusCode < 200 || response.statusCode >= 300) {
      // An authenticated request that's rejected means the token is stale —
      // hand off to the session so it can sign out instead of stranding the user.
      if (response.statusCode == 401 && token != null) {
        onUnauthorized?.call();
      }
      final message = body is Map<String, dynamic>
          ? body['detail']?.toString() ?? 'Request failed'
          : 'Request failed';
      throw ApiException(message, response.statusCode);
    }
    return body;
  }
}
