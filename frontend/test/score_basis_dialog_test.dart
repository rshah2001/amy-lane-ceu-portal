// The score-basis correction flow: what happens when the server refuses to
// guess whether a bare 8 is a fail or a pass.
//
// These exist because the flow shipped without them and a prefix-matching bug
// went unnoticed: the server raises the refusal from two places and one of them
// arrives wrapped, which a startsWith match silently missed. The user then got
// a red banner telling them to go edit their spreadsheet — precisely the trip
// this dialog exists to save.
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:ceu_compliance_portal/core/api_client.dart';
import 'package:ceu_compliance_portal/core/theme.dart';
import 'package:ceu_compliance_portal/pages/uploads_page.dart';

const _bareMessage =
    'The score column is ambiguous: every value is between 0 and 10 and none '
    'says "%" or "x/10", so 8 could mean 8% (a fail) or 8/10 (a pass) and '
    'guessing would issue certificates for failed tests. Values found: 8, 9.';

// What the generic handler in uploads.py produces for the second raise site.
const _wrappedMessage = 'Unable to extract rows: $_bareMessage';

void main() {
  group('recognising the refusal', () {
    test('matches the message the server sends unwrapped', () {
      expect(isAmbiguousScoreError(ApiException(_bareMessage, 400)), isTrue);
    });

    test('matches it when a generic handler has prefixed it', () {
      // The bug this whole file exists for.
      expect(isAmbiguousScoreError(ApiException(_wrappedMessage, 400)), isTrue);
    });

    test('matches a server too old to list the values', () {
      const older = 'The score column is ambiguous: every value is between 0 and 10.';
      expect(isAmbiguousScoreError(ApiException(older, 400)), isTrue);
    });

    test('ignores other 400s, so a real error still reads as an error', () {
      expect(
        isAmbiguousScoreError(ApiException('No attendee names could be read', 400)),
        isFalse,
      );
    });

    test('ignores the same words on a non-400', () {
      expect(isAmbiguousScoreError(ApiException(_bareMessage, 500)), isFalse);
    });

    test('ignores things that are not ApiExceptions', () {
      expect(isAmbiguousScoreError(Exception(_bareMessage)), isFalse);
    });
  });

  group('pulling the values out', () {
    test('reads the list the server reported', () {
      expect(scoreSamplesFrom(_bareMessage), ['8', '9']);
    });

    test('reads them through the wrapping prefix too', () {
      expect(scoreSamplesFrom(_wrappedMessage), ['8', '9']);
    });

    test('returns nothing rather than throwing when they are absent', () {
      expect(scoreSamplesFrom('The score column is ambiguous.'), isEmpty);
    });
  });

  group('restating a value under each reading', () {
    test('out of 10 turns a failing-looking 8 into a pass', () {
      expect(scoreBasisPreview('out_of_10', '8'), '8 becomes 80% — a pass');
    });

    test('percent keeps 8 a fail — the case that issued wrong certificates', () {
      expect(scoreBasisPreview('percent', '8'), '8 becomes 8% — a fail');
    });

    test('fractions of 1 read an Excel decimal', () {
      expect(scoreBasisPreview('out_of_1', '0.85'), '0.85 becomes 85% — a pass');
    });

    test('says nothing for a value it cannot restate', () {
      expect(scoreBasisPreview('percent', 'n/a'), '');
    });
  });

  group('the dialog', () {
    Future<void> pump(WidgetTester tester, List<String> samples) => tester.pumpWidget(
          MaterialApp(
            theme: buildPortalTheme(),
            home: Scaffold(body: ScoreBasisDialog(samples: samples)),
          ),
        );

    testWidgets('shows the user their own values', (tester) async {
      await pump(tester, ['8', '9']);
      expect(find.textContaining('scores like 8, 9'), findsOneWidget);
    });

    testWidgets('offers all three readings with worked examples', (tester) async {
      await pump(tester, ['8']);
      expect(find.text('Percentages (0–100)'), findsOneWidget);
      expect(find.text('Out of 10'), findsOneWidget);
      expect(find.text('Fractions of 1'), findsOneWidget);
      // The example is what makes the choice concrete rather than a quiz.
      expect(find.text('8 becomes 80% — a pass'), findsOneWidget);
      expect(find.text('8 becomes 8% — a fail'), findsOneWidget);
    });

    testWidgets('promises no second trip to the file', (tester) async {
      await pump(tester, ['8']);
      expect(find.textContaining('you do not need to open it again'), findsOneWidget);
    });

    testWidgets('still asks when the server listed no values', (tester) async {
      await pump(tester, const []);
      expect(find.textContaining('no "%" or "x/10" on any row'), findsOneWidget);
      expect(find.text('Out of 10'), findsOneWidget);
    });

    testWidgets('pre-selects nothing — choosing for them is the guess we refuse', (tester) async {
      await pump(tester, ['8']);
      // Every option is an equal, unselected button; nothing is marked chosen.
      expect(find.byType(Radio<String>), findsNothing);
      expect(find.byType(OutlinedButton), findsNWidgets(scoreBasisOptions.length));
    });

    testWidgets('returns the chosen basis to the caller', (tester) async {
      String? chosen;
      await tester.pumpWidget(
        MaterialApp(
          theme: buildPortalTheme(),
          home: Builder(
            builder: (context) => Scaffold(
              body: Center(
                child: ElevatedButton(
                  onPressed: () async {
                    chosen = await showDialog<String>(
                      context: context,
                      builder: (_) => const ScoreBasisDialog(samples: ['8']),
                    );
                  },
                  child: const Text('open'),
                ),
              ),
            ),
          ),
        ),
      );
      await tester.tap(find.text('open'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Out of 10'));
      await tester.pumpAndSettle();
      expect(chosen, 'out_of_10');
    });

    testWidgets('cancelling returns nothing, so no basis is sent', (tester) async {
      String? chosen = 'untouched';
      await tester.pumpWidget(
        MaterialApp(
          theme: buildPortalTheme(),
          home: Builder(
            builder: (context) => Scaffold(
              body: Center(
                child: ElevatedButton(
                  onPressed: () async {
                    chosen = await showDialog<String>(
                      context: context,
                      builder: (_) => const ScoreBasisDialog(samples: ['8']),
                    );
                  },
                  child: const Text('open'),
                ),
              ),
            ),
          ),
        ),
      );
      await tester.tap(find.text('open'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Cancel'));
      await tester.pumpAndSettle();
      expect(chosen, isNull);
    });
  });
}
