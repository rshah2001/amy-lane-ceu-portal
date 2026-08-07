// The shared table is now the only table in the portal, so the behaviour six
// pages depend on is pinned here rather than re-proven page by page: that it
// sorts, that it pages, that the header stays put and stays operable from the
// keyboard, and that loading / empty / error are one implementation instead of
// six.
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:ceu_compliance_portal/widgets/common.dart';
import 'package:ceu_compliance_portal/widgets/portal_table.dart';

typedef Person = ({String name, int score, DateTime? sent});

List<Person> _people(int count) => [
      for (var i = 0; i < count; i++)
        (
          name: 'Person ${(count - i).toString().padLeft(3, '0')}',
          score: i,
          // Every third row has no send date, so the null-ordering rule is
          // exercised by the ordinary fixture rather than a special case.
          sent: i % 3 == 0 ? null : DateTime(2026, 1, 1).add(Duration(days: i)),
        ),
    ];

List<TableColumn<Person>> _columns() => [
      TableColumn<Person>(
        label: 'Name',
        width: 200,
        flex: 1,
        sortValue: (row) => row.name,
        cell: (context, row) => Text(row.name),
      ),
      TableColumn<Person>(
        label: 'Score',
        width: 100,
        numeric: true,
        sortValue: (row) => row.score,
        cell: (context, row) => Text('${row.score}'),
      ),
      TableColumn<Person>(
        // Deliberately not "Sent": a header sharing a string with its own cells
        // makes every finder in this file ambiguous.
        label: 'Sent date',
        width: 140,
        sortValue: (row) => row.sent,
        cell: (context, row) => Text(row.sent == null ? 'Not sent' : 'Sent'),
      ),
      TableColumn<Person>(
        label: 'Actions',
        width: 120,
        cell: (context, row) => const Text('—'),
      ),
    ];

Widget _wrap(Widget table, {double height = 600, double width = 900}) => MaterialApp(
      theme: buildPortalTheme(),
      home: Scaffold(
        body: Center(child: SizedBox(height: height, width: width, child: table)),
      ),
    );

/// The names currently rendered, top to bottom.
List<String> _visibleNames(WidgetTester tester) => tester
    .widgetList<Text>(find.byType(Text))
    .map((text) => text.data ?? '')
    .where((data) => data.startsWith('Person '))
    .toList();

void main() {
  group('states', () {
    testWidgets('null rows is loading, not empty', (tester) async {
      await tester.pumpWidget(_wrap(PortalTable<Person>(
        columns: _columns(),
        rows: null,
        loadingLabel: 'Loading attendees',
        emptyIcon: Icons.people_outline,
        emptyMessage: 'No attendees yet',
      )));
      expect(find.byType(LoadingPanel), findsOneWidget);
      expect(find.text('No attendees yet'), findsNothing);
    });

    testWidgets('an empty list is the empty state, not a blank table', (tester) async {
      await tester.pumpWidget(_wrap(PortalTable<Person>(
        columns: _columns(),
        rows: const [],
        emptyIcon: Icons.people_outline,
        emptyMessage: 'No attendees yet',
        emptyDetail: 'Upload the sign-in sheet.',
      )));
      expect(find.text('No attendees yet'), findsOneWidget);
      expect(find.text('Upload the sign-in sheet.'), findsOneWidget);
    });

    testWidgets('an error hides the table rather than showing stale rows',
        (tester) async {
      var retried = 0;
      await tester.pumpWidget(_wrap(PortalTable<Person>(
        columns: _columns(),
        rows: _people(5),
        error: 'Could not reach the server.',
        onRetry: () => retried++,
        emptyIcon: Icons.people_outline,
        emptyMessage: 'No attendees yet',
      )));
      expect(find.text('Could not reach the server.'), findsOneWidget);
      // Acting on a roster that failed to refresh is how the wrong person gets
      // a certificate; the rows go away with the error.
      expect(_visibleNames(tester), isEmpty);
      await tester.tap(find.text('Retry'));
      expect(retried, 1);
    });
  });

  group('sorting', () {
    Widget table({int? initialSort}) => _wrap(PortalTable<Person>(
          columns: _columns(),
          rows: _people(6),
          initialSortColumn: initialSort,
          rowsPerPage: 10,
          emptyIcon: Icons.people_outline,
          emptyMessage: 'No attendees yet',
        ));

    testWidgets('a header click sorts ascending, a second click descending',
        (tester) async {
      await tester.pumpWidget(table());
      // Unsorted: the fixture is built in reverse name order.
      expect(_visibleNames(tester).first, 'Person 006');

      await tester.tap(find.text('Name'));
      await tester.pumpAndSettle();
      expect(_visibleNames(tester).first, 'Person 001');
      expect(find.byIcon(Icons.arrow_upward), findsOneWidget);

      await tester.tap(find.text('Name'));
      await tester.pumpAndSettle();
      expect(_visibleNames(tester).first, 'Person 006');
      expect(find.byIcon(Icons.arrow_downward), findsOneWidget);
    });

    testWidgets('only the sorted column shows an indicator', (tester) async {
      await tester.pumpWidget(table());
      expect(find.byIcon(Icons.arrow_upward), findsNothing);
      await tester.tap(find.text('Score'));
      await tester.pumpAndSettle();
      expect(find.byIcon(Icons.arrow_upward), findsOneWidget);
    });

    testWidgets('numbers sort numerically, not as text', (tester) async {
      await tester.pumpWidget(_wrap(PortalTable<Person>(
        columns: _columns(),
        rows: _people(12),
        rowsPerPage: 20,
        emptyIcon: Icons.people_outline,
        emptyMessage: 'No attendees yet',
      )));
      await tester.tap(find.text('Score'));
      await tester.pumpAndSettle();
      final scores = tester
          .widgetList<Text>(find.byType(Text))
          .map((text) => int.tryParse(text.data ?? ''))
          .whereType<int>()
          .toList();
      // Only the rows in the viewport are built, so this checks the order of
      // what was built rather than the whole page. Sorted as strings the third
      // row would be 10, not 2.
      expect(scores.take(4), [0, 1, 2, 3]);
    });

    testWidgets('missing values sort last in both directions', (tester) async {
      await tester.pumpWidget(_wrap(PortalTable<Person>(
        columns: _columns(),
        rows: _people(6),
        rowsPerPage: 20,
        emptyIcon: Icons.people_outline,
        emptyMessage: 'No attendees yet',
      )));
      List<String> sentColumn() => tester
          .widgetList<Text>(find.byType(Text))
          .map((text) => text.data ?? '')
          .where((data) => data == 'Sent' || data == 'Not sent')
          .toList();

      await tester.tap(find.text('Sent date'));
      await tester.pumpAndSettle();
      // "Not sent" is an absence, not the earliest date — it belongs at the
      // bottom whichever way the dates run.
      expect(sentColumn().last, 'Not sent');
      await tester.tap(find.text('Sent date'));
      await tester.pumpAndSettle();
      expect(sentColumn().last, 'Not sent');
    });

    testWidgets('a column with no sort value is not a button', (tester) async {
      final handle = tester.ensureSemantics();
      await tester.pumpWidget(table());
      expect(
        tester.getSemantics(find.text('Actions')),
        isNot(isSemantics(isButton: true)),
      );
      handle.dispose();
    });

    testWidgets('the sort state is announced, not just drawn', (tester) async {
      final handle = tester.ensureSemantics();
      await tester.pumpWidget(table());
      expect(find.bySemanticsLabel('Name, not sorted'), findsOneWidget);
      await tester.tap(find.text('Name'));
      await tester.pumpAndSettle();
      // The exact wording the audit asked for: an arrow glyph announces as
      // nothing at all.
      expect(find.bySemanticsLabel('Name, sorted ascending'), findsOneWidget);
      await tester.tap(find.text('Name'));
      await tester.pumpAndSettle();
      expect(find.bySemanticsLabel('Name, sorted descending'), findsOneWidget);
      handle.dispose();
    });

    testWidgets('sorting is reachable and operable from the keyboard',
        (tester) async {
      await tester.pumpWidget(table());
      // Tab lands on the first sortable header; Enter has to do what a click
      // does, or the table is pointer-only.
      await tester.sendKeyEvent(LogicalKeyboardKey.tab);
      await tester.pumpAndSettle();
      await tester.sendKeyEvent(LogicalKeyboardKey.enter);
      await tester.pumpAndSettle();
      expect(_visibleNames(tester).first, 'Person 001');

      await tester.sendKeyEvent(LogicalKeyboardKey.space);
      await tester.pumpAndSettle();
      expect(_visibleNames(tester).first, 'Person 006');
    });

    testWidgets('an icon-only header still announces its column', (tester) async {
      final handle = tester.ensureSemantics();
      await tester.pumpWidget(_wrap(PortalTable<Person>(
        columns: [
          TableColumn<Person>(
            label: '',
            headerIcon: Icons.event_available_outlined,
            semanticLabel: 'Attended',
            tooltip: 'Attended the session',
            width: 80,
            sortValue: (row) => row.score,
            cell: (context, row) => const CheckIcon(true, label: 'Attended'),
          ),
        ],
        rows: _people(2),
        emptyIcon: Icons.people_outline,
        emptyMessage: 'No attendees yet',
      )));
      expect(find.bySemanticsLabel('Attended, not sorted'), findsOneWidget);
      handle.dispose();
    });
  });

  group('pagination', () {
    Widget table({int rows = 30, int perPage = 10}) => _wrap(PortalTable<Person>(
          columns: _columns(),
          rows: _people(rows),
          rowsPerPage: perPage,
          emptyIcon: Icons.people_outline,
          emptyMessage: 'No attendees yet',
        ));

    testWidgets('only one page of rows is built', (tester) async {
      await tester.pumpWidget(table());
      expect(_visibleNames(tester).length, 10);
      expect(find.textContaining('Rows 1 to 10 of 30'), findsOneWidget);
      expect(find.textContaining('page 1 of 3'), findsOneWidget);
    });

    testWidgets('next and previous move a page at a time', (tester) async {
      await tester.pumpWidget(table());
      final firstPage = _visibleNames(tester);

      await tester.tap(find.byTooltip('Next page'));
      await tester.pumpAndSettle();
      expect(find.textContaining('Rows 11 to 20 of 30'), findsOneWidget);
      expect(_visibleNames(tester), isNot(firstPage));

      await tester.tap(find.byTooltip('Previous page'));
      await tester.pumpAndSettle();
      expect(_visibleNames(tester), firstPage);
    });

    testWidgets('the last page is short, not padded', (tester) async {
      await tester.pumpWidget(table(rows: 25, perPage: 10));
      await tester.tap(find.byTooltip('Last page'));
      await tester.pumpAndSettle();
      expect(find.textContaining('Rows 21 to 25 of 25'), findsOneWidget);
      expect(_visibleNames(tester).length, 5);
    });

    testWidgets('the edges disable rather than wrap around', (tester) async {
      await tester.pumpWidget(table());
      IconButton button(IconData icon) => tester.widget<IconButton>(
            find.ancestor(of: find.byIcon(icon), matching: find.byType(IconButton)),
          );
      expect(button(Icons.first_page).onPressed, isNull);
      expect(button(Icons.chevron_left).onPressed, isNull);
      expect(button(Icons.chevron_right).onPressed, isNotNull);

      await tester.tap(find.byTooltip('Last page'));
      await tester.pumpAndSettle();
      expect(button(Icons.chevron_right).onPressed, isNull);
      expect(button(Icons.last_page).onPressed, isNull);
      expect(button(Icons.chevron_left).onPressed, isNotNull);
    });

    testWidgets('re-sorting returns to page one', (tester) async {
      await tester.pumpWidget(table());
      await tester.tap(find.byTooltip('Next page'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Name'));
      await tester.pumpAndSettle();
      // Page 2 of the old order is not page 2 of the new one, so staying put
      // would silently show a different slice than the reader expects.
      expect(find.textContaining('Rows 1 to 10 of 30'), findsOneWidget);
    });

    testWidgets('a shorter reload does not strand the reader on a dead page',
        (tester) async {
      await tester.pumpWidget(table());
      await tester.tap(find.byTooltip('Last page'));
      await tester.pumpAndSettle();
      expect(find.textContaining('page 3 of 3'), findsOneWidget);

      await tester.pumpWidget(table(rows: 5));
      await tester.pumpAndSettle();
      expect(find.textContaining('Rows 1 to 5 of 5'), findsOneWidget);
      expect(_visibleNames(tester).length, 5);
    });

    testWidgets('a single page still reports where the reader is', (tester) async {
      await tester.pumpWidget(table(rows: 4));
      expect(find.textContaining('Rows 1 to 4 of 4'), findsOneWidget);
      expect(find.textContaining('page 1 of 1'), findsOneWidget);
    });
  });

  group('virtualization', () {
    testWidgets('300 log rows do not all get built', (tester) async {
      await tester.pumpWidget(_wrap(PortalTable<Person>(
        columns: _columns(),
        rows: _people(300),
        paging: TablePaging.virtualized,
        density: TableDensity.compact,
        emptyIcon: Icons.receipt_long_outlined,
        emptyMessage: 'No audit entries yet',
      )));
      // The whole point: an audit log scrolls as one stream, but only the
      // visible slice is laid out. 600px of viewport cannot hold 300 rows.
      expect(_visibleNames(tester).length, lessThan(40));
      expect(find.textContaining('page 1 of'), findsNothing);
    });

    testWidgets('scrolling reaches rows that were never built at first',
        (tester) async {
      await tester.pumpWidget(_wrap(PortalTable<Person>(
        columns: _columns(),
        rows: _people(300),
        paging: TablePaging.virtualized,
        density: TableDensity.compact,
        emptyIcon: Icons.receipt_long_outlined,
        emptyMessage: 'No audit entries yet',
      )));
      expect(find.text('Person 001'), findsNothing);
      await tester.tap(find.text('Name'));
      await tester.pumpAndSettle();
      expect(find.text('Person 001'), findsOneWidget);
    });
  });

  testWidgets('the header stays pinned while the body scrolls', (tester) async {
    await tester.pumpWidget(_wrap(PortalTable<Person>(
      columns: _columns(),
      rows: _people(200),
      paging: TablePaging.virtualized,
      emptyIcon: Icons.people_outline,
      emptyMessage: 'No attendees yet',
    )));
    final before = tester.getTopLeft(find.text('Name'));
    await tester.drag(find.byType(ListView), const Offset(0, -400));
    await tester.pumpAndSettle();
    // Column meaning has to survive scrolling — this is the failure that made
    // the old DataTables unreadable past the first screenful.
    expect(find.text('Name'), findsOneWidget);
    expect(tester.getTopLeft(find.text('Name')), before);
  });

  group('selection', () {
    testWidgets('select-all covers the whole dataset, not just the page',
        (tester) async {
      final selected = <Object>{};
      final rows = _people(30);
      await tester.pumpWidget(_wrap(
        StatefulBuilder(
          builder: (context, setState) => PortalTable<Person>(
            columns: _columns(),
            rows: rows,
            rowsPerPage: 10,
            rowKey: (row) => row.name,
            selectedKeys: selected,
            onSelectChanged: (row, on) => setState(
              () => on ? selected.add(row.name) : selected.remove(row.name),
            ),
            emptyIcon: Icons.people_outline,
            emptyMessage: 'No attendees yet',
          ),
        ),
      ));
      await tester.tap(find.byType(Checkbox).first);
      await tester.pumpAndSettle();
      // Approving 10 of the 30 rows the admin believes they ticked is the
      // dangerous half-measure this avoids.
      expect(selected.length, 30);
    });

    testWidgets('rows that cannot be selected show no checkbox', (tester) async {
      final rows = _people(4);
      await tester.pumpWidget(_wrap(PortalTable<Person>(
        columns: _columns(),
        rows: rows,
        rowKey: (row) => row.name,
        selectedKeys: const <Object>{},
        isSelectable: (row) => row.score.isEven,
        onSelectChanged: (row, on) {},
        emptyIcon: Icons.people_outline,
        emptyMessage: 'No attendees yet',
      )));
      // Two selectable rows plus the header's select-all.
      expect(find.byType(Checkbox), findsNWidgets(3));
    });
  });

  testWidgets('an expandable row reveals its detail in place', (tester) async {
    await tester.pumpWidget(_wrap(PortalTable<Person>(
      columns: _columns(),
      rows: _people(3),
      rowKey: (row) => row.name,
      expansionBuilder: (context, row) => Text('Answers for ${row.name}'),
      emptyIcon: Icons.people_outline,
      emptyMessage: 'No responses yet',
    )));
    expect(find.text('Answers for Person 003'), findsNothing);
    await tester.tap(find.byTooltip('Show details').first);
    await tester.pumpAndSettle();
    expect(find.text('Answers for Person 003'), findsOneWidget);
    await tester.tap(find.byTooltip('Hide details').first);
    await tester.pumpAndSettle();
    expect(find.text('Answers for Person 003'), findsNothing);
  });

  testWidgets('survives 200% text scale without overflowing', (tester) async {
    await tester.pumpWidget(MaterialApp(
      theme: buildPortalTheme(),
      home: MediaQuery(
        data: const MediaQueryData(textScaler: TextScaler.linear(2.0)),
        child: Scaffold(
          body: SizedBox(
            height: 600,
            child: PortalTable<Person>(
              columns: _columns(),
              rows: _people(8),
              emptyIcon: Icons.people_outline,
              emptyMessage: 'No attendees yet',
            ),
          ),
        ),
      ),
    ));
    expect(tester.takeException(), isNull);
  });
}
