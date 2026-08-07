import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter/semantics.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:ceu_compliance_portal/widgets/common.dart';

/// Relative luminance per WCAG 2.1, so the contrast floors these tokens were
/// chosen for are asserted rather than left to a comment that can drift.
double _luminance(Color color) {
  double channel(double value) =>
      value <= 0.03928 ? value / 12.92 : math.pow((value + 0.055) / 1.055, 2.4).toDouble();
  return 0.2126 * channel(color.r) + 0.7152 * channel(color.g) + 0.0722 * channel(color.b);
}

double contrastRatio(Color a, Color b) {
  final la = _luminance(a);
  final lb = _luminance(b);
  final hi = math.max(la, lb);
  final lo = math.min(la, lb);
  return (hi + 0.05) / (lo + 0.05);
}

const _white = Color(0xFFFFFFFF);

Widget _wrap(Widget child, {double textScale = 1.0}) {
  return MaterialApp(
    theme: buildPortalTheme(),
    home: MediaQuery(
      data: MediaQueryData(textScaler: TextScaler.linear(textScale)),
      child: Scaffold(body: child),
    ),
  );
}

void main() {
  group('colour tokens meet their documented contrast floors', () {
    const colors = PortalColors.light;

    test('body and caption text clear AA (4.5:1) on white and on canvas', () {
      final tiers = {
        'textPrimary': colors.textPrimary,
        'textSecondary': colors.textSecondary,
        'textTertiary': colors.textTertiary,
      };
      for (final entry in tiers.entries) {
        expect(contrastRatio(entry.value, _white), greaterThanOrEqualTo(4.5),
            reason: '${entry.key} on white');
        expect(contrastRatio(entry.value, canvas), greaterThanOrEqualTo(4.5),
            reason: '${entry.key} on canvas');
      }
    });

    test('semantic colours clear AA on white and on their own badge surface', () {
      final pairs = <String, (Color, Color)>{
        'success': (colors.success, colors.successSurface),
        'warning': (colors.warning, colors.warningSurface),
        'danger': (colors.danger, colors.dangerSurface),
        'info': (colors.info, colors.infoSurface),
        'neutral': (colors.neutral, colors.neutralSurface),
      };
      for (final entry in pairs.entries) {
        final (foreground, surface) = entry.value;
        expect(contrastRatio(foreground, _white), greaterThanOrEqualTo(4.5),
            reason: '${entry.key} on white');
        expect(contrastRatio(foreground, surface), greaterThanOrEqualTo(4.5),
            reason: '${entry.key} on its badge surface');
      }
    });

    test('gold clears AA on the canvas it sits on (was 2.94:1)', () {
      expect(contrastRatio(gold, canvas), greaterThanOrEqualTo(4.5));
      expect(contrastRatio(gold, _white), greaterThanOrEqualTo(4.5));
    });

    test('outlines clear the 3:1 non-text minimum (was 1.29:1)', () {
      expect(contrastRatio(border, _white), greaterThanOrEqualTo(3.0));
      expect(contrastRatio(border, canvas), greaterThanOrEqualTo(3.0));
    });

    test('the selected-page indicator clears 3:1 against the sidebar', () {
      // The accent bar carries this, not the tile fill: a fill light enough to
      // reach 3:1 against navy would drop its own white label under 4.5:1.
      expect(contrastRatio(colors.navAccent, colors.navSurface), greaterThanOrEqualTo(3.0));
      expect(contrastRatio(_white, colors.navSelected), greaterThanOrEqualTo(4.5));
    });

    test('brand colours that already passed still pass', () {
      expect(contrastRatio(navy, _white), greaterThanOrEqualTo(4.5));
      expect(contrastRatio(_white, navy), greaterThanOrEqualTo(4.5));
      expect(contrastRatio(teal, _white), greaterThanOrEqualTo(4.5));
    });
  });

  group('compliance marks are readable by a screen reader', () {
    testWidgets('a met requirement announces which requirement it is', (tester) async {
      final handle = tester.ensureSemantics();
      await tester.pumpWidget(_wrap(const CheckIcon(true, label: 'Attended')));
      expect(find.bySemanticsLabel('Attended: yes'), findsOneWidget);
      handle.dispose();
    });

    testWidgets('an unmet requirement announces that it is unmet', (tester) async {
      final handle = tester.ensureSemantics();
      await tester.pumpWidget(_wrap(const CheckIcon(false, label: 'Post-test passed')));
      expect(find.bySemanticsLabel('Post-test passed: no'), findsOneWidget);
      handle.dispose();
    });
  });

  testWidgets('page titles are exposed as headings', (tester) async {
    final handle = tester.ensureSemantics();
    await tester.pumpWidget(
      _wrap(const PageHeader(title: 'Compliance Review', subtitle: 'Spring session')),
    );
    expect(
      tester.getSemantics(find.text('Compliance Review')),
      isSemantics(isHeader: true),
    );
    handle.dispose();
  });

  testWidgets('form errors are a live region so they get announced', (tester) async {
    final handle = tester.ensureSemantics();
    await tester.pumpWidget(_wrap(const FormErrorText('Enter a valid email address')));
    expect(
      tester.getSemantics(find.byType(FormErrorText)),
      isSemantics(isLiveRegion: true),
    );
    handle.dispose();
  });

  testWidgets('a small tap target is padded out to the 44px minimum', (tester) async {
    await tester.pumpWidget(_wrap(const MinTapTarget(child: Icon(Icons.close, size: 12))));
    final size = tester.getSize(find.byType(MinTapTarget));
    expect(size.width, greaterThanOrEqualTo(minTapTarget));
    expect(size.height, greaterThanOrEqualTo(minTapTarget));
  });

  group('ActionMenu is keyboard operable', () {
    Widget menu({bool enabled = true, VoidCallback? onApprove}) => _wrap(
          ActionMenu(
            label: 'Bulk actions',
            icon: const Icon(Icons.bolt_outlined),
            enabled: enabled,
            actions: [
              MenuAction('Approve all eligible', onApprove ?? () {}),
              null,
              MenuAction('Remove all attendees', () {}, destructive: true),
            ],
          ),
        );

    testWidgets('exposes exactly one trigger, and it is not a no-op', (tester) async {
      await tester.pumpWidget(menu());
      // The old shape was PopupMenuButton(child: IgnorePointer(OutlinedButton(
      // onPressed: () {}))): two tab stops, the inner one doing nothing at all.
      // There is now a single button and pressing it actually does something —
      // which the Tab/Enter test below exercises end to end.
      expect(find.byType(OutlinedButton), findsOneWidget);
      expect(tester.widget<OutlinedButton>(find.byType(OutlinedButton)).onPressed, isNotNull);
    });

    testWidgets('Tab reaches the trigger and Enter opens the menu', (tester) async {
      var approved = false;
      await tester.pumpWidget(menu(onApprove: () => approved = true));

      await tester.sendKeyEvent(LogicalKeyboardKey.tab);
      await tester.pumpAndSettle();
      expect(tester.binding.focusManager.primaryFocus?.hasPrimaryFocus, isTrue);

      await tester.sendKeyEvent(LogicalKeyboardKey.enter);
      await tester.pumpAndSettle();
      expect(find.text('Approve all eligible'), findsOneWidget,
          reason: 'Enter on the trigger must open the menu');

      await tester.tap(find.text('Approve all eligible'));
      await tester.pumpAndSettle();
      expect(approved, isTrue);
    });

    testWidgets('a disabled menu cannot be activated', (tester) async {
      await tester.pumpWidget(menu(enabled: false));
      expect(tester.widget<OutlinedButton>(find.byType(OutlinedButton)).onPressed, isNull);
    });
  });

  testWidgets('the semantics tree can be forced on, as main() does', (tester) async {
    // main() calls this so the DOM semantics tree exists from the first frame
    // instead of waiting for the user to find the hidden "Enable accessibility"
    // button. Guards the API this depends on.
    final handle = SemanticsBinding.instance.ensureSemantics();
    expect(SemanticsBinding.instance.semanticsEnabled, isTrue);
    handle.dispose();
  });

  group('layout survives 200% text scale', () {
    testWidgets('a stat card does not overflow', (tester) async {
      await tester.pumpWidget(
        _wrap(
          const SizedBox(
            width: 280,
            child: StatCard(
              label: 'Certificates sent',
              value: '1284',
              icon: Icons.send_outlined,
              color: navy,
            ),
          ),
          textScale: 2.0,
        ),
      );
      expect(tester.takeException(), isNull);
    });

    testWidgets('the page header does not overflow', (tester) async {
      await tester.pumpWidget(
        _wrap(
          const PageHeader(
            title: 'Compliance Review',
            subtitle: 'NMEDA CAMS Lunch & Learn — Spring 2026 session',
          ),
          textScale: 2.0,
        ),
      );
      expect(tester.takeException(), isNull);
    });

    testWidgets('an empty state does not overflow', (tester) async {
      await tester.pumpWidget(
        _wrap(
          const EmptyState(
            icon: Icons.fact_check_outlined,
            message: 'No attendee records match this view',
            detail: 'Upload the registration and attendance files, or adjust the filters.',
          ),
          textScale: 2.0,
        ),
      );
      expect(tester.takeException(), isNull);
    });

    testWidgets('a status badge does not overflow', (tester) async {
      await tester.pumpWidget(
        _wrap(const StatusBadge('AWAITING DOCUMENTS', tone: BadgeTone.info), textScale: 2.0),
      );
      expect(tester.takeException(), isNull);
    });
  });

  group('theme', () {
    test('no longer caps data rows below their own content', () {
      expect(buildPortalTheme().dataTableTheme.dataRowMaxHeight, double.infinity);
    });

    test('ships a complete type scale', () {
      final text = buildPortalTheme().textTheme;
      final roles = <String, TextStyle?>{
        'displayLarge': text.displayLarge,
        'displayMedium': text.displayMedium,
        'displaySmall': text.displaySmall,
        'headlineLarge': text.headlineLarge,
        'headlineMedium': text.headlineMedium,
        'headlineSmall': text.headlineSmall,
        'titleLarge': text.titleLarge,
        'titleMedium': text.titleMedium,
        'titleSmall': text.titleSmall,
        'bodyLarge': text.bodyLarge,
        'bodyMedium': text.bodyMedium,
        'bodySmall': text.bodySmall,
        'labelLarge': text.labelLarge,
        'labelMedium': text.labelMedium,
        'labelSmall': text.labelSmall,
      };
      for (final entry in roles.entries) {
        expect(entry.value?.fontSize, isNotNull, reason: '${entry.key} has no size');
      }
      // The scale must descend, or "section heading" stops being one decision.
      expect(text.displayLarge!.fontSize, greaterThan(text.headlineLarge!.fontSize!));
      expect(text.headlineLarge!.fontSize, greaterThan(text.titleLarge!.fontSize!));
      expect(text.titleLarge!.fontSize, greaterThan(text.bodyMedium!.fontSize!));
    });

    test('uses the system font stack rather than Arial or a downloaded font', () {
      final body = buildPortalTheme().textTheme.bodyMedium;
      expect(body?.fontFamily, 'system-ui');
      expect(body?.fontFamilyFallback, contains('-apple-system'));
      expect(body?.fontFamilyFallback, contains('Segoe UI'));
    });

    test('installs the semantic colour extension', () {
      expect(buildPortalTheme().extension<PortalColors>(), isNotNull);
      expect(buildPortalTheme().portal.success, PortalColors.light.success);
    });

    test('pins the component roles that used to leak seed colours', () {
      final scheme = buildPortalTheme().colorScheme;
      // SegmentedButton and FilterChip fill their selected state from these.
      expect(scheme.secondaryContainer, PortalColors.light.infoSurface);
      expect(scheme.onSecondaryContainer, PortalColors.light.info);
      expect(scheme.outline, border);
      expect(buildPortalTheme().segmentedButtonTheme.style, isNotNull);
      expect(buildPortalTheme().chipTheme.selectedColor, PortalColors.light.infoSurface);
    });
  });
}
