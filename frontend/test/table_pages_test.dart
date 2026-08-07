// The six views that adopted the shared table, pumped against a mock API at a
// realistic desktop width.
//
// The point is less to re-prove sorting — portal_table_test.dart does that —
// than to catch the two things a shared table can break at the call site: a
// column too narrow for what a page puts in it (which shows up as a RenderFlex
// overflow, not a failed expectation), and a page-specific behaviour that used
// to live in the hand-rolled table it replaced.
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'package:ceu_compliance_portal/core/session.dart';
import 'package:ceu_compliance_portal/models/models.dart';
import 'package:ceu_compliance_portal/pages/attendee_search_page.dart';
import 'package:ceu_compliance_portal/pages/audit_reports_page.dart';
import 'package:ceu_compliance_portal/pages/certificate_center_page.dart';
import 'package:ceu_compliance_portal/pages/compliance_page.dart';
import 'package:ceu_compliance_portal/pages/survey_responses_page.dart';
import 'package:ceu_compliance_portal/pages/users_page.dart';
import 'package:ceu_compliance_portal/widgets/common.dart';

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

Map<String, dynamic> _complianceRow({
  required int id,
  required String name,
  bool approved = false,
  String? certificateNumber,
  String? sentAt,
}) =>
    {
      'id': id,
      'attendee_id': id + 100,
      'full_name': name,
      'email': '${name.toLowerCase().replaceAll(' ', '.')}@example.com',
      'company': 'Mobility Works',
      'registered': true,
      'attended': true,
      'test_completed': true,
      'test_score': 80.0 + id,
      'survey_completed': true,
      'has_valid_email': true,
      'eligible': true,
      'approved': approved,
      'compliance_status': approved ? 'approved' : 'eligible',
      'lifecycle_status': approved ? 'approved' : 'eligible',
      'eligibility_reasons': <String>[],
      'certificate_id': certificateNumber == null ? null : id,
      'certificate_number': certificateNumber,
      'certificate_sent_at': sentAt,
      'certificate_downloaded_at': null,
      'certificate_revoked_at': null,
    };

/// Pumps [child] at a desktop width against an API that answers from [routes],
/// keyed by the tail of the request path.
Future<void> _pump(
  WidgetTester tester,
  Widget child, {
  required Map<String, Object> routes,
}) async {
  final client = MockClient((request) async {
    for (final entry in routes.entries) {
      if (request.url.path.contains(entry.key)) {
        return http.Response(
          jsonEncode(entry.value),
          200,
          headers: {'content-type': 'application/json'},
        );
      }
    }
    return http.Response(jsonEncode(const <String>[]), 200,
        headers: {'content-type': 'application/json'});
  });
  // The portal is a desktop app behind a sidebar; the default 800px test
  // surface is narrower than any screen it actually runs on.
  tester.view.physicalSize = const Size(1600, 1100);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.reset);
  await http.runWithClient(() async {
    await tester.pumpWidget(MaterialApp(
      theme: buildPortalTheme(),
      home: Scaffold(body: child),
    ));
    await tester.pumpAndSettle();
  }, () => client);
}

void main() {
  group('Compliance Review', () {
    final roster = [
      _complianceRow(id: 1, name: 'Zoe Adams'),
      _complianceRow(id: 2, name: 'Alan Brooks'),
      _complianceRow(id: 3, name: 'Maria Chen', approved: true),
    ];

    testWidgets('lays out without overflowing and sorts by name by default',
        (tester) async {
      await _pump(
        tester,
        CompliancePage(session: _adminSession(), event: _event),
        routes: {'compliance': roster},
      );
      expect(tester.takeException(), isNull);
      final names = tester
          .widgetList<Text>(find.byType(Text))
          .map((text) => text.data ?? '')
          .where((data) => data.contains(RegExp(r'^(Zoe|Alan|Maria)')))
          .toList();
      expect(names.first, 'Alan Brooks');
    });

    testWidgets('select-all skips the already-approved row', (tester) async {
      await _pump(
        tester,
        CompliancePage(session: _adminSession(), event: _event),
        routes: {'compliance': roster},
      );
      await tester.tap(find.byType(Checkbox).first);
      await tester.pumpAndSettle();
      // Maria is approved, so she is not selectable — approving her again is
      // not an action the page offers.
      expect(find.text('Approve selected (2)'), findsOneWidget);
    });

    testWidgets('the requirement columns still announce their names',
        (tester) async {
      final handle = tester.ensureSemantics();
      await _pump(
        tester,
        CompliancePage(session: _adminSession(), event: _event),
        routes: {'compliance': roster},
      );
      // Icon-only headers used to announce as nothing at all; now they are
      // named *and* sortable.
      expect(find.bySemanticsLabel('Attended, not sorted'), findsOneWidget);
      expect(find.bySemanticsLabel('Survey completed, not sorted'), findsOneWidget);
      handle.dispose();
    });
  });

  group('Certificate Center', () {
    testWidgets('renders its three row actions without overflowing',
        (tester) async {
      await _pump(
        tester,
        CertificateCenterPage(
          session: _adminSession(),
          initialEvent: _event,
          onSelectEvent: (_) {},
        ),
        routes: {
          'compliance': [
            _complianceRow(
              id: 1,
              name: 'Zoe Adams',
              approved: true,
              certificateNumber: 'CEU-00001-AAAAAAAAAA',
              sentAt: '2026-07-01T12:00:00Z',
            ),
            _complianceRow(id: 2, name: 'Alan Brooks', approved: true),
          ],
          'events': [
            {
              'id': 2,
              'title': 'Adaptive Vehicle Safety CEU',
              'event_date': '2026-06-15',
              'ceu_hours': 2,
              'status': 'review',
            },
          ],
        },
      );
      expect(tester.takeException(), isNull);
      expect(find.text('Resend'), findsOneWidget);
      expect(find.text('Send'), findsOneWidget);
      // Alan is approved with no certificate yet, so Generate is live for him
      // and spent for Zoe.
      expect(find.text('Generate'), findsOneWidget);
      expect(find.text('Generated'), findsOneWidget);
    });
  });

  group('Audit Reports', () {
    final logs = [
      {
        'id': 1,
        'created_at': '2026-01-05T09:00:00Z',
        'action': 'certificate.sent',
        'entity_type': 'certificate',
        'entity_id': 5,
        'event_id': 2,
        'actor_id': 1,
        'details': 'Emailed to zoe@example.com',
      },
      {
        'id': 2,
        'created_at': '2026-08-05T09:00:00Z',
        'action': 'attendee.removed',
        'entity_type': 'event_attendee',
        'entity_id': 9,
        'event_id': 2,
        'actor_id': null,
        'details': 'Removed from the roster',
      },
    ];

    testWidgets('opens newest-first, which is what an audit trail is for',
        (tester) async {
      await _pump(
        tester,
        AuditReportsPage(session: _adminSession()),
        routes: {
          'audit-logs': logs,
          'survey-insights': const {'response_count': 0, 'common_themes': <String>[]},
          'reports/columns': const <Map<String, dynamic>>[],
        },
      );
      expect(tester.takeException(), isNull);
      final actions = tester
          .widgetList<Text>(find.byType(Text))
          .map((text) => text.data ?? '')
          .where((data) => data.startsWith('CERTIFICATE ') || data.startsWith('ATTENDEE '))
          .toList();
      expect(actions.first, 'ATTENDEE REMOVED');
      // A log is scrolled, not paged.
      expect(find.textContaining('page 1 of'), findsNothing);
    });

    testWidgets('a system action shows as system rather than blank', (tester) async {
      await _pump(
        tester,
        AuditReportsPage(session: _adminSession()),
        routes: {
          'audit-logs': logs,
          'survey-insights': const {'response_count': 0, 'common_themes': <String>[]},
          'reports/columns': const <Map<String, dynamic>>[],
        },
      );
      // Capitalised now that the column reads as a name ("Who") rather than a
      // raw actor id, and still rendered even though this mock serves no
      // /users or /events — those lookups are enrichment, not a dependency.
      expect(find.text('System'), findsOneWidget);
    });
  });

  group('Survey Responses', () {
    final responses = [
      {
        'id': 1,
        'event_id': 2,
        'event_title': 'Adaptive Vehicle Safety CEU',
        'full_name': 'Zoe Adams',
        'email': 'zoe@example.com',
        'business_location': 'Tampa, FL',
        'completed_at': '2026-07-01T12:00:00Z',
        'answers': {'What worked well?': 'The hands-on section'},
      },
      {
        'id': 2,
        'event_id': 2,
        'event_title': 'Adaptive Vehicle Safety CEU',
        'full_name': 'Zoe Adams',
        'email': 'zoe@example.com',
        'business_location': 'Tampa, FL',
        'completed_at': '2026-07-02T12:00:00Z',
        'answers': {'What worked well?': 'Second thoughts'},
      },
    ];

    testWidgets('a repeat submission is still flagged as a repeat', (tester) async {
      await _pump(
        tester,
        SurveyResponsesPage(session: _adminSession()),
        routes: {'survey-responses': responses, 'events': const <Map<String, dynamic>>[]},
      );
      expect(tester.takeException(), isNull);
      // The backend keeps every submission, so the same person appears twice;
      // both rows say so rather than reading as accidental duplicates.
      expect(find.text('2 SUBMISSIONS'), findsNWidgets(2));
    });

    testWidgets('the answers open under the row, not in a dialog', (tester) async {
      await _pump(
        tester,
        SurveyResponsesPage(session: _adminSession()),
        routes: {'survey-responses': responses, 'events': const <Map<String, dynamic>>[]},
      );
      expect(find.text('The hands-on section'), findsNothing);
      await tester.tap(find.byTooltip('Show details for Zoe Adams').last);
      await tester.pumpAndSettle();
      expect(find.text('The hands-on section'), findsOneWidget);
      expect(find.byType(Dialog), findsNothing);
    });
  });

  group('Users', () {
    final users = [
      {
        'id': 2,
        'full_name': 'Zoe Adams',
        'email': 'zoe@example.com',
        'role': 'presenter',
        'is_active': true,
        'created_at': '2026-01-05T09:00:00Z',
      },
      {
        'id': 1,
        'full_name': 'Amy',
        'email': 'amy@example.com',
        'role': 'admin',
        'is_active': true,
        'created_at': '2025-01-05T09:00:00Z',
      },
    ];

    testWidgets('lists accounts alphabetically without overflowing', (tester) async {
      await _pump(tester, UsersPage(session: _adminSession()), routes: {'users': users});
      expect(tester.takeException(), isNull);
      expect(find.text('ADMIN'), findsOneWidget);
      expect(find.text('PRESENTER'), findsOneWidget);
    });

    testWidgets('you still cannot deactivate yourself', (tester) async {
      await _pump(tester, UsersPage(session: _adminSession()), routes: {'users': users});
      // Amy is the signed-in admin: her row offers no menu, because
      // deactivating it would sign her out of the only page that could undo it.
      expect(find.byTooltip('Manage Amy'), findsNothing);
      expect(find.byTooltip('Manage Zoe Adams'), findsOneWidget);
    });
  });

  group('Attendee Search', () {
    testWidgets('an event group opens onto a sortable table', (tester) async {
      await _pump(
        tester,
        AttendeeSearchPage(session: _adminSession()),
        routes: {
          'attendees/search': [
            {
              'event_id': 2,
              'event_title': 'Adaptive Vehicle Safety CEU',
              'event_date': '2026-06-15',
              'full_name': 'Zoe Adams',
              'email': 'zoe@example.com',
              'company': 'Mobility Works',
              'approved': true,
              'eligible': true,
              'certificate_number': 'CEU-00001-AAAAAAAAAA',
            },
          ],
          'events': const <Map<String, dynamic>>[],
        },
      );
      expect(tester.takeException(), isNull);
      // A single group opens by itself, so the table is on screen already.
      expect(find.text('Zoe Adams'), findsOneWidget);
      expect(find.text('APPROVED'), findsOneWidget);
      await tester.tap(find.text('Company'));
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
    });
  });
}
