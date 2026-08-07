// Revoking a certificate is not deleting one, and the UI has to say so.
//
// An issued certificate inside its seven-year retention window is withdrawn
// rather than destroyed: the record stays, and from then on the number
// verifies publicly as REVOKED. Both halves of that are things a person acts
// on — the admin pressing the button, and whoever is holding the PDF — so
// both are pinned here.
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'package:ceu_compliance_portal/core/api_client.dart';
import 'package:ceu_compliance_portal/core/session.dart';
import 'package:ceu_compliance_portal/models/models.dart';
import 'package:ceu_compliance_portal/pages/compliance_page.dart';
import 'package:ceu_compliance_portal/pages/verification_page.dart';
import 'package:ceu_compliance_portal/widgets/common.dart';

/// Both pages under test are page bodies rather than whole routes, so they get
/// the Scaffold (and with it the ScaffoldMessenger) the shell normally gives
/// them.
Widget _wrap(Widget child) =>
    MaterialApp(theme: buildPortalTheme(), home: Scaffold(body: child));

/// One compliance row as the API sends it.
Map<String, dynamic> _row({
  int id = 1,
  String fullName = 'Alice Nguyen',
  String lifecycleStatus = 'sent',
  String? sentAt = '2026-07-01T12:00:00Z',
  String? revokedAt,
}) =>
    {
      'id': id,
      'attendee_id': id + 100,
      'full_name': fullName,
      'email': 'alice.nguyen@example.com',
      'company': 'Mobility Works',
      'registered': true,
      'attended': true,
      'test_completed': true,
      'test_score': 92.0,
      'survey_completed': true,
      'has_valid_email': true,
      'eligible': true,
      'approved': true,
      'compliance_status': 'approved',
      'lifecycle_status': lifecycleStatus,
      'eligibility_reasons': <String>[],
      'certificate_id': 7,
      'certificate_number': 'CEU-00002-ABCDEFGHIJ',
      'certificate_sent_at': sentAt,
      'certificate_downloaded_at': null,
      'certificate_revoked_at': revokedAt,
    };

final _event = TrainingEvent(
  id: 2,
  title: 'Adaptive Vehicle Safety CEU',
  eventDate: DateTime(2026, 6, 15),
  ceuHours: 2,
  status: 'review',
);

SessionController _adminSession() {
  final session = SessionController();
  session.user = PortalUser(id: 1, email: 'amy@example.com', fullName: 'Amy', role: 'admin');
  session.api.token = 'test-token';
  return session;
}

void main() {
  group('the revoked badge', () {
    testWidgets('reads REVOKED in the danger tone', (tester) async {
      final badge = lifecycleBadge('revoked');
      expect(badge.label, 'REVOKED');
      // Not one of the green delivery states and not a neutral fallback: a
      // withdrawn credential is the one alarming value in that column.
      expect(badge.tone, BadgeTone.danger);
      await tester.pumpWidget(_wrap(Scaffold(body: badge)));
      expect(find.text('REVOKED'), findsOneWidget);
    });

    testWidgets('the delivery states are unchanged', (tester) async {
      expect(lifecycleBadge('sent').tone, BadgeTone.success);
      expect(lifecycleBadge('downloaded').tone, BadgeTone.success);
      expect(lifecycleBadge('generated').tone, BadgeTone.info);
    });
  });

  group('ComplianceRecord', () {
    test('carries the revocation timestamp', () {
      final record = ComplianceRecord.fromJson(_row(revokedAt: '2026-08-07T09:30:00Z'));
      expect(record.certificateRevoked, isTrue);
      expect(record.certificateRevokedAt, DateTime.parse('2026-08-07T09:30:00Z'));
    });

    test('a live certificate is not revoked', () {
      expect(ComplianceRecord.fromJson(_row()).certificateRevoked, isFalse);
    });
  });

  group('public verification', () {
    Future<void> pumpVerification(
      WidgetTester tester,
      Map<String, dynamic> response,
    ) async {
      final client = MockClient((request) async => http.Response(
            jsonEncode(response),
            200,
            headers: {'content-type': 'application/json'},
          ));
      await http.runWithClient(() async {
        await tester.pumpWidget(
          _wrap(VerificationPage(api: ApiClient(), initialNumber: 'CEU-00002-ABCDEFGHIJ')),
        );
        await tester.pumpAndSettle();
      }, () => client);
    }

    testWidgets('a revoked certificate is reported as revoked, not as missing',
        (tester) async {
      await pumpVerification(tester, {
        'valid': false,
        'status': 'revoked',
        'certificate_number': 'CEU-00002-ABCDEFGHIJ',
        'attendee_name': 'Alice Nguyen',
        'event_title': 'Adaptive Vehicle Safety CEU',
        'event_date': '2026-06-15',
        'generated_at': '2026-06-20T10:00:00Z',
        'revoked_at': '2026-08-07T09:30:00Z',
      });
      expect(find.text('Certificate revoked'), findsOneWidget);
      // The failure this guards: "no certificate matches" sends the holder
      // back to a document that is no longer worth anything.
      expect(find.textContaining('No certificate matches'), findsNothing);
      expect(find.text('Valid certificate'), findsNothing);
      expect(find.text('REVOKED'), findsOneWidget);
      expect(find.textContaining('August 7, 2026'), findsOneWidget);
      expect(find.text('Alice Nguyen'), findsOneWidget);
      // Nothing to hand over: the PDF is retained for the record, not for the
      // public.
      expect(find.text('Download certificate PDF'), findsNothing);
    });

    testWidgets('an unknown number still reads as unknown', (tester) async {
      await pumpVerification(tester, {'valid': false});
      expect(find.textContaining('No certificate matches'), findsOneWidget);
      expect(find.text('Certificate revoked'), findsNothing);
    });

    testWidgets('a valid certificate is unchanged', (tester) async {
      await pumpVerification(tester, {
        'valid': true,
        'status': 'sent',
        'certificate_number': 'CEU-00002-ABCDEFGHIJ',
        'attendee_name': 'Alice Nguyen',
        'event_title': 'Adaptive Vehicle Safety CEU',
        'event_date': '2026-06-15',
        'ceu_hours': '2.00',
        'generated_at': '2026-06-20T10:00:00Z',
      });
      expect(find.text('Valid certificate'), findsOneWidget);
      expect(find.text('Certificate revoked'), findsNothing);
      expect(find.text('Download certificate PDF'), findsOneWidget);
    });
  });

  group('the removal flow explains what it actually does', () {
    /// Pumps the compliance page over a mock API and runs [body] inside the
    /// same client zone, so taps that fire requests are captured too.
    Future<void> pumpCompliance(
      WidgetTester tester, {
      required List<Map<String, dynamic>> rows,
      required List<String> requests,
      Map<String, dynamic> removalResult = const {
        'removed': 0,
        'kept_with_issued_certificates': <String>[],
        'revoked': <String>['Alice Nguyen'],
      },
      Future<void> Function(WidgetTester tester)? body,
    }) async {
      final client = MockClient((request) async {
        requests.add('${request.method} ${request.url}');
        final payload = request.method == 'DELETE' ? removalResult : rows;
        return http.Response(
          jsonEncode(payload),
          200,
          headers: {'content-type': 'application/json'},
        );
      });
      // The compliance table is wide (five requirement columns plus actions)
      // and scrolls horizontally; the default 800px surface would leave the
      // row actions off-screen and un-tappable.
      tester.view.physicalSize = const Size(1600, 1200);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.reset);
      await http.runWithClient(() async {
        await tester.pumpWidget(
          _wrap(CompliancePage(session: _adminSession(), event: _event)),
        );
        await tester.pumpAndSettle();
        if (body != null) await body(tester);
      }, () => client);
    }

    testWidgets('an issued certificate is described as revoked, not deleted',
        (tester) async {
      final requests = <String>[];
      await pumpCompliance(
        tester,
        rows: [_row()],
        requests: requests,
        body: (tester) async {
          await tester.tap(find.byIcon(Icons.person_remove_outlined));
          await tester.pumpAndSettle();
        },
      );
      expect(find.text('Remove Alice Nguyen and revoke their certificate?'), findsOneWidget);
      expect(find.textContaining('revoked rather than deleted'), findsOneWidget);
      expect(find.textContaining('kept for seven years'), findsOneWidget);
      expect(find.textContaining('verifies publicly as REVOKED'), findsOneWidget);
      expect(find.textContaining('cannot be undone'), findsOneWidget);
      expect(find.text('Reason (optional)'), findsOneWidget);
    });

    testWidgets('the reason travels with the request', (tester) async {
      final requests = <String>[];
      await pumpCompliance(
        tester,
        rows: [_row()],
        requests: requests,
        body: (tester) async {
          await tester.tap(find.byIcon(Icons.person_remove_outlined));
          await tester.pumpAndSettle();
          await tester.enterText(find.byType(TextField).last, 'Wrong sign-in sheet');
          await tester.tap(find.text('Revoke and remove'));
          await tester.pumpAndSettle();
        },
      );
      final delete = requests.firstWhere((entry) => entry.startsWith('DELETE'));
      expect(delete, contains('include_sent=true'));
      expect(delete, contains('reason=Wrong+sign-in+sheet'));
    });

    testWidgets('the result says revoked, not removed', (tester) async {
      final requests = <String>[];
      await pumpCompliance(
        tester,
        rows: [_row()],
        requests: requests,
        body: (tester) async {
          await tester.tap(find.byIcon(Icons.person_remove_outlined));
          await tester.pumpAndSettle();
          await tester.tap(find.text('Revoke and remove'));
          await tester.pumpAndSettle();
        },
      );
      expect(find.textContaining('certificate is revoked'), findsOneWidget);
    });

    testWidgets('a plain removal is still a plain removal', (tester) async {
      final requests = <String>[];
      await pumpCompliance(
        tester,
        rows: [_row(lifecycleStatus: 'approved', sentAt: null)],
        requests: requests,
        removalResult: const {
          'removed': 1,
          'kept_with_issued_certificates': <String>[],
          'revoked': <String>[],
        },
        body: (tester) async {
          await tester.tap(find.byIcon(Icons.person_remove_outlined));
          await tester.pumpAndSettle();
          expect(find.text('Remove Alice Nguyen from this event?'), findsOneWidget);
          expect(find.text('Reason (optional)'), findsNothing);
          expect(find.textContaining('revoked rather than deleted'), findsNothing);
          await tester.tap(find.text('Remove attendee'));
          await tester.pumpAndSettle();
        },
      );
      expect(find.text('Alice Nguyen removed from this event.'), findsOneWidget);
      expect(
        requests.firstWhere((entry) => entry.startsWith('DELETE')),
        isNot(contains('include_sent')),
      );
    });

    testWidgets('an already-revoked row shows the badge and cannot be removed again',
        (tester) async {
      await pumpCompliance(
        tester,
        rows: [_row(lifecycleStatus: 'revoked', revokedAt: '2026-08-07T09:30:00Z')],
        requests: <String>[],
      );
      expect(find.text('REVOKED'), findsOneWidget);
      // The row is retained for seven years by design, so the action is
      // disabled rather than repeatedly no-op'ing against the server.
      final button = tester.widget<IconButton>(
        find.ancestor(
          of: find.byIcon(Icons.person_remove_outlined),
          matching: find.byType(IconButton),
        ),
      );
      expect(button.onPressed, isNull);
      expect(button.tooltip, contains('kept for seven years'));
    });
  });
}
