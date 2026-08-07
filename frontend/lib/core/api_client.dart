import 'dart:async';
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
  /// [client] is for tests. Left null in production so every call goes through
  /// the package-level `http.get`/`http.post` helpers, which honour
  /// `http.runWithClient` — that is how the existing widget tests swap in a
  /// `MockClient` without any page knowing about it.
  ApiClient({
    String? baseUrl,
    http.Client? client,
    this.timeout = defaultTimeout,
    this.transferTimeout = defaultTransferTimeout,
  })  : baseUrl = baseUrl ??
            const String.fromEnvironment(
              'API_BASE_URL',
              defaultValue: 'http://localhost:8000/api',
            ),
        _client = client;

  /// Ceiling on an ordinary JSON request.
  ///
  /// Without one, a request that never answers — a dropped conference-centre
  /// wifi connection, a proxy holding the socket open — leaves the page on its
  /// spinner forever, with no error, no Retry, and nothing the user can do but
  /// reload the tab and lose whatever they had typed. 30s is well past any
  /// healthy response here (the slowest real endpoint is the annual export) and
  /// well short of a person's patience.
  static const defaultTimeout = Duration(seconds: 30);

  /// Ceiling on a file transfer — certificate PDFs, template uploads, the CSV
  /// exports. These are legitimately slow on a bad connection, so they get their
  /// own, longer budget rather than being failed by the request timeout.
  static const defaultTransferTimeout = Duration(minutes: 2);

  final String baseUrl;
  final http.Client? _client;
  final Duration timeout;
  final Duration transferTimeout;
  String? token;

  /// Called when an authenticated request is rejected with 401, so the app can
  /// clear the stale session and return to the login screen.
  void Function()? onUnauthorized;

  Map<String, String> get _headers => {
        'Content-Type': 'application/json',
        if (token != null) 'Authorization': 'Bearer $token',
      };

  Uri _uri(String path) => Uri.parse('$baseUrl$path');

  /// [timeout] can only *tighten* the client-wide budget, never extend past it
  /// — the startup token check wants to give up in 8s, but nothing should be
  /// able to talk the client into waiting longer than it agreed to.
  Future<dynamic> get(String path, {Duration? timeout}) async {
    final limit = timeout == null || timeout > this.timeout ? this.timeout : timeout;
    return _decode(
      await _await(
        _client?.get(_uri(path), headers: _headers) ??
            http.get(_uri(path), headers: _headers),
        limit,
      ),
    );
  }

  Future<dynamic> post(String path, [Map<String, dynamic>? body]) async {
    final payload = jsonEncode(body ?? <String, dynamic>{});
    return _decode(
      await _await(
        _client?.post(_uri(path), headers: _headers, body: payload) ??
            http.post(_uri(path), headers: _headers, body: payload),
        timeout,
      ),
    );
  }

  Future<dynamic> put(String path, [Map<String, dynamic>? body]) async {
    final payload = jsonEncode(body ?? <String, dynamic>{});
    return _decode(
      await _await(
        _client?.put(_uri(path), headers: _headers, body: payload) ??
            http.put(_uri(path), headers: _headers, body: payload),
        timeout,
      ),
    );
  }

  Future<dynamic> patch(String path, [Map<String, dynamic>? body]) async {
    final payload = jsonEncode(body ?? <String, dynamic>{});
    return _decode(
      await _await(
        _client?.patch(_uri(path), headers: _headers, body: payload) ??
            http.patch(_uri(path), headers: _headers, body: payload),
        timeout,
      ),
    );
  }

  Future<dynamic> delete(String path) async {
    return _decode(
      await _await(
        _client?.delete(_uri(path), headers: _headers) ??
            http.delete(_uri(path), headers: _headers),
        timeout,
      ),
    );
  }

  Future<dynamic> uploadFile(
    String path,
    Uint8List bytes,
    String filename, {
    Map<String, String>? fields,
  }) async {
    final request = http.MultipartRequest('POST', _uri(path));
    if (token != null) request.headers['Authorization'] = 'Bearer $token';
    if (fields != null) request.fields.addAll(fields);
    request.files.add(http.MultipartFile.fromBytes('file', bytes, filename: filename));
    final streamed = _client?.send(request) ?? request.send();
    return _decode(
      await _await(streamed.then(http.Response.fromStream), transferTimeout),
    );
  }

  Future<Uint8List> download(String path) async {
    final response = await _await(
      _client?.get(_uri(path), headers: _headers) ??
          http.get(_uri(path), headers: _headers),
      transferTimeout,
    );
    if (response.statusCode < 200 || response.statusCode >= 300) {
      _decode(response);
    }
    return response.bodyBytes;
  }

  /// Applies [limit] to [request] and rethrows the timeout with a message the
  /// UI layer can turn into advice — see `humanizeError`.
  ///
  /// The socket is not aborted, because `package:http` has no portable way to
  /// do that from a browser; the caller simply stops waiting. Callers that
  /// mutate state therefore have to treat a timeout as "unknown outcome", which
  /// is what the humanized wording says.
  Future<http.Response> _await(Future<http.Response> request, Duration limit) {
    return request.timeout(
      limit,
      onTimeout: () => throw TimeoutException('The request timed out.', limit),
    );
  }

  dynamic _decode(http.Response response) {
    // Status first, body second. The old order decoded before checking, so a
    // 502 from a proxy — which answers with an HTML error page, not JSON —
    // surfaced as "FormatException: Unexpected character (at character 1)"
    // instead of "the server had a problem". The status is the fact we can
    // always trust; the body is best-effort.
    if (response.statusCode < 200 || response.statusCode >= 300) {
      // An authenticated request that's rejected means the token is stale —
      // hand off to the session so it can sign out instead of stranding the user.
      if (response.statusCode == 401 && token != null) {
        onUnauthorized?.call();
      }
      final body = _tryDecode(response.body);
      final detail = body is Map<String, dynamic> ? body['detail'] : null;
      throw ApiException(_detailText(detail) ?? '', response.statusCode);
    }
    if (response.body.isEmpty) return null;
    final body = _tryDecode(response.body);
    if (body == null && response.body.trim().isNotEmpty) {
      // A 200 that isn't JSON means something answered in the API's place —
      // a captive-portal login page, a CDN maintenance page. Reported as a
      // server fault rather than as a parser crash.
      throw ApiException('The server sent a response the portal could not read.', 502);
    }
    return body;
  }

  static dynamic _tryDecode(String body) {
    if (body.isEmpty) return null;
    try {
      return jsonDecode(body);
    } on FormatException {
      return null;
    }
  }

  /// FastAPI's `detail` is a string for hand-raised errors but a list of
  /// per-field objects for validation failures, which used to reach the user as
  /// `[{loc: [body, email], msg: field required, ...}]`.
  static String? _detailText(Object? detail) {
    if (detail == null) return null;
    if (detail is String) return detail;
    if (detail is List) {
      final messages = detail
          .map((item) => item is Map ? item['msg']?.toString() : item?.toString())
          .whereType<String>()
          .where((message) => message.isNotEmpty)
          .toList();
      return messages.isEmpty ? null : messages.join('. ');
    }
    return detail.toString();
  }
}
