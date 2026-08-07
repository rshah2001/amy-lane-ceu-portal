// The error paths through ApiClient had no tests at all, which is how a
// FormatException from an HTML error page ended up being what a training
// coordinator saw when the proxy hiccuped.
//
// Every case here is one an audit found reaching the screen: a gateway serving
// HTML, a request that never answers, a validation error arriving as a list, a
// token that expired between page loads.
import 'dart:async';
import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:ceu_compliance_portal/core/api_client.dart';
import 'package:ceu_compliance_portal/core/session.dart';
import 'package:ceu_compliance_portal/widgets/common.dart';

ApiClient _client(
  Future<http.Response> Function(http.Request request) handler, {
  Duration timeout = ApiClient.defaultTimeout,
}) =>
    ApiClient(
      baseUrl: 'https://portal.test/api',
      client: MockClient(handler),
      timeout: timeout,
      transferTimeout: timeout,
    );

http.Response _json(Object body, [int status = 200]) => http.Response(
      jsonEncode(body),
      status,
      headers: {'content-type': 'application/json'},
    );

void main() {
  group('a non-JSON body', () {
    // The reported bug: jsonDecode ran before the status check, so an HTML
    // error page from a proxy surfaced as "FormatException: Unexpected
    // character (at character 1)" — unactionable, and it hid the 502.
    const html = '<!doctype html><html><body><h1>502 Bad Gateway</h1></body></html>';

    test('on a 502 is reported as a server error, not a parse failure', () async {
      final api = _client((_) async => http.Response(html, 502));
      await expectLater(
        api.get('/events'),
        throwsA(isA<ApiException>().having((e) => e.statusCode, 'statusCode', 502)),
      );
    });

    test('on a 504 humanizes into advice a coordinator can act on', () async {
      final api = _client((_) async => http.Response(html, 504));
      try {
        await api.get('/events');
        fail('expected a failure');
      } catch (exception) {
        expect(exception, isA<ApiException>());
        expect(humanizeError(exception), contains('The server had a problem'));
        expect(humanizeError(exception), isNot(contains('FormatException')));
      }
    });

    test('on a 200 is refused rather than handed to the page', () async {
      // A captive portal or CDN maintenance page answering 200 in the API's
      // place. Letting it through means a page casting HTML to List.
      final api = _client((_) async => http.Response(html, 200));
      await expectLater(
        api.get('/events'),
        throwsA(isA<ApiException>()
            .having((e) => e.message, 'message', contains('could not read'))),
      );
    });
  });

  group('error bodies', () {
    test('a string detail is passed through', () async {
      final api = _client((_) async => _json({'detail': 'Event is locked'}, 409));
      await expectLater(
        api.post('/events/1/lock'),
        throwsA(isA<ApiException>()
            .having((e) => e.message, 'message', 'Event is locked')),
      );
    });

    test("FastAPI's validation list is flattened, not stringified", () async {
      // Otherwise the user reads `[{loc: [body, email], msg: field required}]`.
      final api = _client((_) async => _json({
            'detail': [
              {'loc': ['body', 'email'], 'msg': 'field required'},
              {'loc': ['body', 'name'], 'msg': 'too short'},
            ],
          }, 422));
      await expectLater(
        api.post('/users', const {}),
        throwsA(isA<ApiException>()
            .having((e) => e.message, 'message', 'field required. too short')),
      );
    });

    test('a bodyless failure still humanizes into a sentence', () async {
      final api = _client((_) async => http.Response('', 403));
      try {
        await api.delete('/users/2');
        fail('expected a failure');
      } catch (exception) {
        expect(humanizeError(exception), "You don't have permission to do that.");
      }
    });
  });

  group('timeouts', () {
    // Before this there were none anywhere: a request that never answered left
    // the page on its spinner with no error, no Retry, and nothing to do but
    // reload the tab.
    test('a request that never answers gives up', () async {
      final api = _client(
        (_) => Completer<http.Response>().future,
        timeout: const Duration(milliseconds: 20),
      );
      await expectLater(api.get('/events'), throwsA(isA<TimeoutException>()));
    });

    test('a hung POST gives up too', () async {
      final api = _client(
        (_) => Completer<http.Response>().future,
        timeout: const Duration(milliseconds: 20),
      );
      await expectLater(
        api.post('/events/1/certificates/send-all'),
        throwsA(isA<TimeoutException>()),
      );
    });

    test('a hung download gives up', () async {
      final api = _client(
        (_) => Completer<http.Response>().future,
        timeout: const Duration(milliseconds: 20),
      );
      await expectLater(api.download('/reports/annual/2026'), throwsA(isA<TimeoutException>()));
    });

    test('the wording tells the user to check before retrying', () {
      final message = humanizeError(TimeoutException('timed out'));
      expect(message, contains('took too long'));
      // Not "try again": the socket was abandoned, not cancelled, so a send
      // that timed out may have gone out. Pressing Send again double-emails.
      expect(message, contains('reload the page to check'));
    });

    test('a healthy response well inside the budget is unaffected', () async {
      final api = _client(
        (_) async => _json([
          {'id': 1}
        ]),
        timeout: const Duration(seconds: 5),
      );
      expect(await api.get('/events'), [
        {'id': 1}
      ]);
    });
  });

  group('success decoding', () {
    test('an empty 204 body is null, not a parse error', () async {
      final api = _client((_) async => http.Response('', 204));
      expect(await api.delete('/users/2'), isNull);
    });

    test('JSON is decoded', () async {
      final api = _client((_) async => _json({'processed': 3}));
      expect(await api.post('/x'), {'processed': 3});
    });

    test('the auth header travels with the request', () async {
      String? seen;
      final api = _client((request) async {
        seen = request.headers['Authorization'];
        return _json(const <String>[]);
      })
        ..token = 'abc123';
      await api.get('/events');
      expect(seen, 'Bearer abc123');
    });
  });

  group('401 handling', () {
    test('an authenticated rejection hands off to the session', () async {
      var signedOut = false;
      final api = _client((_) async => _json({'detail': 'Not authenticated'}, 401))
        ..token = 'stale'
        ..onUnauthorized = () => signedOut = true;
      await expectLater(api.get('/events'), throwsA(isA<ApiException>()));
      expect(signedOut, isTrue);
    });

    test('a 401 on a public page does not try to sign anyone out', () async {
      // The check-in, post-test, survey and verification pages run with no
      // token; firing onUnauthorized there would be a sign-out of nobody.
      var signedOut = false;
      final api = _client((_) async => _json({'detail': 'Invalid token'}, 401))
        ..onUnauthorized = () => signedOut = true;
      await expectLater(api.get('/public/tests/xyz'), throwsA(isA<ApiException>()));
      expect(signedOut, isFalse);
    });
  });

  group('session restore validates the stored token', () {
    setUp(() {
      TestWidgetsFlutterBinding.ensureInitialized();
      SharedPreferences.setMockInitialValues({
        'access_token': 'stored-token',
        'user': jsonEncode({
          'id': 1,
          'email': 'amy@example.com',
          'full_name': 'Amy',
          'role': 'admin',
        }),
      });
    });

    test('a rejected token signs out instead of painting the admin shell', () async {
      final session = SessionController(
        api: _client((_) async => _json({'detail': 'Not authenticated'}, 401)),
      );
      await session.restore();
      // The old behaviour trusted the stored token outright, so an expired
      // session rendered the whole sidebar and only fell over one page in.
      expect(session.isAuthenticated, isFalse);
      expect(session.user, isNull);
    });

    test('a deactivated account is signed out too', () async {
      final session = SessionController(
        api: _client((_) async => _json({'detail': 'Inactive user'}, 403)),
      );
      await session.restore();
      expect(session.isAuthenticated, isFalse);
    });

    test('the server response is what the session ends up holding', () async {
      // A role changed since last login takes effect on restore rather than
      // handing the user a sidebar full of pages they can no longer open.
      final session = SessionController(
        api: _client((_) async => _json({
              'id': 1,
              'email': 'amy@example.com',
              'full_name': 'Amy Lane',
              'role': 'presenter',
            })),
      );
      await session.restore();
      expect(session.isAuthenticated, isTrue);
      expect(session.user!.role, 'presenter');
      expect(session.user!.isAdmin, isFalse);
    });

    test('an unreachable server keeps the cached session', () async {
      // Signing someone out because their wifi dropped is worse than trusting
      // the cache: the next request will 401 if the token really is dead.
      final session = SessionController(
        api: _client(
          (_) => Completer<http.Response>().future,
          timeout: const Duration(milliseconds: 20),
        ),
      );
      await session.restore();
      expect(session.isAuthenticated, isTrue);
      expect(session.user!.fullName, 'Amy');
    });

    test('a 500 keeps the cached session as well', () async {
      final session = SessionController(
        api: _client((_) async => http.Response('boom', 500)),
      );
      await session.restore();
      expect(session.isAuthenticated, isTrue);
    });

    test('no stored token means no request at all', () async {
      SharedPreferences.setMockInitialValues(const {});
      var called = false;
      final session = SessionController(
        api: _client((_) async {
          called = true;
          return _json(const {});
        }),
      );
      await session.restore();
      expect(called, isFalse);
      expect(session.isAuthenticated, isFalse);
    });
  });
}
