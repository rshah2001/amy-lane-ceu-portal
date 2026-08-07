// The post-test page has to carry the invite nonce, or the backend check is
// unreachable from the product.
//
// A post-test scored 80% or higher is what directly gates CEU eligibility, and
// the server will only credit the attendee an emailed link was minted for if
// that link's `?k=` reaches it. Everything below is about the URL the page
// actually posts to — the one thing that decides whether a submission is
// attributed by proof or by a typed-in address.
//
// The nonce-less path is pinned just as hard: the printed QR sheet and the
// walk-in check-in hand-off are one shared link for the whole room, and they
// must keep posting exactly as they did.
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'package:ceu_compliance_portal/core/api_client.dart';
import 'package:ceu_compliance_portal/pages/public_test_page.dart';
import 'package:ceu_compliance_portal/widgets/common.dart';

const _token = 'abc123token';

final _test = {
  'event_title': 'Adaptive Vehicle Safety CEU',
  'event_date': '2026-06-15',
  'presenter_name': 'Jordan Miles',
  'questions': [
    {
      'id': 'q1',
      'prompt': '2 + 2?',
      'choices': ['3', '4'],
    },
  ],
};

const _result = {'score': 100.0, 'passed': true, 'correct': 1, 'total': 1};

/// Loads the page over a mock API, fills the form, submits, and hands back
/// every request the page made, in order.
Future<List<http.Request>> submitPostTest(
  WidgetTester tester, {
  String? inviteNonce,
}) async {
  final requests = <http.Request>[];
  final client = MockClient((request) async {
    requests.add(request);
    return http.Response(
      jsonEncode(request.method == 'POST' ? _result : _test),
      200,
      headers: {'content-type': 'application/json'},
    );
  });
  // The form is a name, an email and a question list in one scroll view; the
  // default 800px-tall surface leaves the submit button off-screen.
  tester.view.physicalSize = const Size(1200, 2400);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.reset);
  await http.runWithClient(() async {
    await tester.pumpWidget(
      MaterialApp(
        theme: buildPortalTheme(),
        home: PublicTestPage(api: ApiClient(), token: _token, inviteNonce: inviteNonce),
      ),
    );
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextFormField).first, 'Alice Nguyen');
    await tester.enterText(find.byType(TextFormField).last, 'alice.nguyen@example.com');
    await tester.tap(find.text('4'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Submit test'));
    await tester.pumpAndSettle();
  }, () => client);
  return requests;
}

Uri submittedTo(List<http.Request> requests) =>
    requests.firstWhere((request) => request.method == 'POST').url;

void main() {
  group('an emailed invite link', () {
    testWidgets('carries its nonce on the submission', (tester) async {
      final requests = await submitPostTest(tester, inviteNonce: 'sJ3kQ9vT2mR7pL1xW8bC4a');
      // The whole point: without this parameter the server falls back to
      // crediting whatever address was typed into the form.
      expect(submittedTo(requests).queryParameters['k'], 'sJ3kQ9vT2mR7pL1xW8bC4a');
      expect(submittedTo(requests).path, endsWith('/public/tests/$_token'));
      // And the attempt was really recorded — the page shows its score.
      expect(find.text('100.0%'), findsOneWidget);
    });

    testWidgets('does not put the nonce on the page load', (tester) async {
      final requests = await submitPostTest(tester, inviteNonce: 'sJ3kQ9vT2mR7pL1xW8bC4a');
      // Reading the questions needs no identity, so the secret stays out of
      // that request — and out of one more proxy and server access log.
      final load = requests.firstWhere((request) => request.method == 'GET');
      expect(load.url.queryParameters.containsKey('k'), isFalse);
    });

    testWidgets('percent-encodes a nonce rather than interpolating it raw',
        (tester) async {
      // A link an email client wrapped or a person hand-edited must arrive as a
      // clean value the server can reject on its own length bound, not as a
      // malformed URL or a second query parameter.
      final requests = await submitPostTest(tester, inviteNonce: 'abc&def=ghi jkl');
      expect(submittedTo(requests).queryParameters['k'], 'abc&def=ghi jkl');
      expect(submittedTo(requests).queryParameters.length, 1);
    });
  });

  group('the shared QR link', () {
    testWidgets('posts with no nonce at all', (tester) async {
      final requests = await submitPostTest(tester);
      final url = submittedTo(requests);
      expect(url.queryParameters, isEmpty);
      expect(url.toString(), isNot(contains('k=')));
      expect(find.text('100.0%'), findsOneWidget);
    });

    testWidgets('an empty nonce is the same as none', (tester) async {
      // A link that reached us as `?k=` with nothing after it must post the
      // plain URL, not an empty parameter the server has to interpret.
      final requests = await submitPostTest(tester, inviteNonce: '');
      expect(submittedTo(requests).queryParameters, isEmpty);
    });
  });

  group('the walk-in hand-off', () {
    test('the nonce is optional on the page itself', () {
      // check-in pushes PublicTestPage without one, deliberately: the person
      // may not be on the roster at all. Nothing may require it.
      expect(PublicTestPage(api: ApiClient(), token: _token).inviteNonce, isNull);
    });
  });
}
