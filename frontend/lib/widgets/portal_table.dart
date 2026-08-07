/// The portal's one data table.
///
/// It replaces six hand-rolled `DataTable`s that between them had no sorting, no
/// paging, no virtualization, no pinned header, and three different ideas about
/// what an empty roster should look like. `DataTable` cannot provide the first
/// four: it lays every row out eagerly in a single `RenderTable`, so a 500-person
/// event built 500 rows on every rebuild and the header scrolled away with them.
///
/// So the layout is hand-built out of a `Row` per record instead. That buys the
/// three things the audit asked for:
///
///  * a header that lives *outside* the vertical scroller, so column meaning
///    survives scrolling;
///  * a `ListView.builder` body, so only the visible rows are built;
///  * one implementation of loading / empty / error, so pages stop inventing
///    their own.
///
/// Column widths are resolved once per layout and shared by the header and every
/// row, which is what keeps them lined up without `RenderTable`.
library;

import 'package:flutter/material.dart';

// Also re-exports the design tokens (`Space`, `minTapTarget`, `border`) this
// builds on, and the a11y helpers it announces through.
import 'common.dart';

/// How much vertical room a row gets.
///
/// Enterprise tables are read by scanning down a column, and the denser the
/// table the more of it is in view at once — but cells here hold stacked
/// content (an attendee's name over their email over their eligibility
/// reasons), so density is a floor, never a cap. Rows always grow to fit.
enum TableDensity {
  /// 40 — logs and reference lists, where the row is one line of text.
  compact,

  /// 52 — the default: fits a badge or an icon button without crowding.
  standard,

  /// 64 — rows carrying two or three stacked lines.
  comfortable;

  double get minRowHeight => switch (this) {
        TableDensity.compact => 40,
        TableDensity.standard => 52,
        TableDensity.comfortable => 64,
      };

  double get verticalPadding => switch (this) {
        TableDensity.compact => Space.xxs,
        TableDensity.standard => Space.xs,
        TableDensity.comfortable => Space.xs + 2,
      };
}

/// How the body deals with row count.
enum TablePaging {
  /// A page at a time, with controls. For rosters — a roster is something an
  /// admin works *through*, and "you are on page 2 of 9" is the only honest
  /// answer to "how much is left", which an infinite scroll never gives.
  paginated,

  /// Every row in one lazily-built scroller. For logs — an audit trail is
  /// something you scan and search, and chopping a chronological stream into
  /// pages puts an arbitrary wall in the middle of the thing being read.
  virtualized,
}

/// One column: how it is labelled, how a cell is built, and — if it is
/// sortable — what value to sort on.
class TableColumn<T> {
  const TableColumn({
    required this.label,
    required this.cell,
    this.sortValue,
    this.width = 160,
    this.flex = 0,
    this.numeric = false,
    this.headerIcon,
    this.semanticLabel,
    this.tooltip,
  }) : assert(headerIcon == null || semanticLabel != null,
            'An icon-only header announces as nothing without a semanticLabel.');

  /// Visible header text. Not shown when [headerIcon] is set.
  final String label;

  final Widget Function(BuildContext context, T row) cell;

  /// The value this column sorts on, or null for a column that cannot be
  /// sorted (an actions column). Strings compare case-insensitively; `null`
  /// values always sort last, in both directions, because "not yet sent" is an
  /// absence rather than the earliest date.
  final Object? Function(T row)? sortValue;

  /// Base width in logical pixels. The table never renders a column narrower
  /// than this; below the sum of them it scrolls horizontally instead of
  /// squeezing the content.
  final double width;

  /// Share of any width left over once every column has its [width]. 0 pins the
  /// column to exactly [width] — right for a status badge or a date, wrong for
  /// the free-text column that should absorb a wide screen.
  final int flex;

  /// Right-aligns the cell, for figures that are read by comparing digits.
  final bool numeric;

  /// Renders the header as an icon rather than text, for the four compliance
  /// requirement columns where a word per column would not fit.
  final IconData? headerIcon;

  /// What a screen reader announces for the header. Defaults to [label];
  /// required when [headerIcon] is used.
  final String? semanticLabel;

  /// Hover/long-press explanation of the column, mostly for [headerIcon].
  final String? tooltip;

  String get accessibleLabel => semanticLabel ?? label;
}

class PortalTable<T> extends StatefulWidget {
  const PortalTable({
    super.key,
    required this.columns,
    required this.rows,
    required this.emptyIcon,
    required this.emptyMessage,
    this.emptyDetail,
    this.error,
    this.onRetry,
    this.loadingLabel = 'Loading',
    this.paging = TablePaging.paginated,
    this.rowsPerPage = 25,
    this.density = TableDensity.standard,
    this.initialSortColumn,
    this.initialSortAscending = true,
    this.rowKey,
    this.selectedKeys,
    this.isSelectable,
    this.onSelectChanged,
    this.expansionBuilder,
    this.rowSemanticLabel,
    this.shrinkWrap = false,
    this.caption,
  })  : assert(
          !(shrinkWrap && paging == TablePaging.virtualized),
          'A shrink-wrapped table has no viewport to virtualize against; page it.',
        ),
        // Both features address a row by identity. Without a key, sorting or
        // paging would move a selection — or an open detail panel — onto
        // whoever happens to land at that index next.
        assert(selectedKeys == null || rowKey != null,
            'Selection needs a rowKey to be stable across sorting and paging.'),
        assert(expansionBuilder == null || rowKey != null,
            'Expansion needs a rowKey to stay attached to its row.');

  final List<TableColumn<T>> columns;

  /// The data. `null` means "still loading" — the distinction from an empty
  /// list is the difference between a spinner and "no attendees yet", and every
  /// page used to draw it by hand.
  final List<T>? rows;

  final IconData emptyIcon;
  final String emptyMessage;
  final String? emptyDetail;

  /// A load failure. Takes precedence over [rows]: showing a stale table under
  /// an error banner invites acting on data that is no longer true.
  final String? error;
  final VoidCallback? onRetry;
  final String loadingLabel;

  final TablePaging paging;
  final int rowsPerPage;
  final TableDensity density;

  /// Index into [columns] to sort by on first build.
  final int? initialSortColumn;
  final bool initialSortAscending;

  /// Stable identity for a row — required for selection and for expansion, so
  /// that sorting or paging doesn't move the selection onto a different person.
  final Object Function(T row)? rowKey;

  /// Keys currently selected. Non-null turns the checkbox column on.
  final Set<Object>? selectedKeys;

  /// Rows the user is allowed to select. Unselectable rows show no checkbox
  /// rather than a dead one.
  final bool Function(T row)? isSelectable;

  final void Function(T row, bool selected)? onSelectChanged;

  /// Detail panel revealed under a row when it is expanded. Non-null adds the
  /// disclosure column.
  final Widget Function(BuildContext context, T row)? expansionBuilder;

  /// What a screen reader should read the whole row as, before it reaches the
  /// individual cells. Without it a row is announced as a bare run of values.
  final String? Function(T row)? rowSemanticLabel;

  /// Sizes to the content instead of filling its parent. Only valid with
  /// [TablePaging.paginated], which bounds how many rows can be built.
  final bool shrinkWrap;

  /// Names the table for screen reader users, e.g. "Compliance roster".
  final String? caption;

  @override
  State<PortalTable<T>> createState() => _PortalTableState<T>();
}

class _PortalTableState<T> extends State<PortalTable<T>> {
  final _horizontal = ScrollController();
  final _vertical = ScrollController();
  final _expanded = <Object>{};

  int? _sortColumn;
  late bool _ascending;
  int _page = 0;

  @override
  void initState() {
    super.initState();
    _sortColumn = widget.initialSortColumn;
    _ascending = widget.initialSortAscending;
  }

  @override
  void didUpdateWidget(covariant PortalTable<T> oldWidget) {
    super.didUpdateWidget(oldWidget);
    // A reload that returns fewer rows must not strand the reader on a page
    // that no longer exists — they'd see an empty table over a full dataset.
    final pages = _pageCount(widget.rows?.length ?? 0);
    if (_page >= pages) _page = pages - 1 < 0 ? 0 : pages - 1;

    // Expansion is keyed by row, and a filter change can retire a row while its
    // key is still in the set. Left to accumulate, an afternoon of filtering
    // grows the set without bound and re-expands rows that come back.
    final keyOf = widget.rowKey;
    if (keyOf != null && _expanded.isNotEmpty && widget.rows != oldWidget.rows) {
      final live = widget.rows?.map(keyOf).toSet() ?? const <Object>{};
      _expanded.removeWhere((key) => !live.contains(key));
    }
  }

  @override
  void dispose() {
    _horizontal.dispose();
    _vertical.dispose();
    super.dispose();
  }

  int _pageCount(int rowCount) {
    if (widget.paging != TablePaging.paginated) return 1;
    return rowCount <= 0 ? 1 : ((rowCount - 1) ~/ widget.rowsPerPage) + 1;
  }

  void _sortBy(int index) {
    final column = widget.columns[index];
    setState(() {
      if (_sortColumn == index) {
        _ascending = !_ascending;
      } else {
        _sortColumn = index;
        _ascending = true;
      }
      // Re-sorting reshuffles which rows are on which page; page 1 is the only
      // position that still means the same thing afterwards.
      _page = 0;
    });
    announceToScreenReader(
      context,
      '${column.accessibleLabel}, sorted ${_ascending ? 'ascending' : 'descending'}',
    );
  }

  /// Orders two cell values. `null` sorts last in both directions: a missing
  /// value is not a small one, and burying "no email" at the bottom is what the
  /// reader wants either way.
  static int _compare(Object? a, Object? b) {
    if (a == null && b == null) return 0;
    if (a == null) return 1;
    if (b == null) return -1;
    if (a is bool && b is bool) return (a ? 1 : 0).compareTo(b ? 1 : 0);
    if (a is num && b is num) return a.compareTo(b);
    if (a is DateTime && b is DateTime) return a.compareTo(b);
    return a.toString().toLowerCase().compareTo(b.toString().toLowerCase());
  }

  List<T> _sorted(List<T> rows) {
    final index = _sortColumn;
    if (index == null || index >= widget.columns.length) return rows;
    final sortValue = widget.columns[index].sortValue;
    if (sortValue == null) return rows;
    final sorted = [...rows];
    sorted.sort((a, b) {
      final left = sortValue(a);
      final right = sortValue(b);
      final result = _compare(left, right);
      // The null-last rule is deliberately not inverted by direction, so the
      // sign is applied only once both sides have a value.
      if (left == null || right == null) return result;
      return _ascending ? result : -result;
    });
    return sorted;
  }

  // ───────────────────────────────────────────────────────────────────────────
  // Width resolution
  // ───────────────────────────────────────────────────────────────────────────

  /// Fixed leading columns: the checkbox and the expansion toggle. Both are
  /// pointer targets, and Material sizes a padded `Checkbox`/`IconButton` at 48
  /// square, so the column has to be at least that or the control overflows it.
  static const _controlWidth = 48.0;

  double get _leadingWidth =>
      (widget.selectedKeys != null ? _controlWidth : 0) +
      (widget.expansionBuilder != null ? _controlWidth : 0);

  List<double> _resolveWidths(double available) {
    final base = widget.columns.map((column) => column.width).toList();
    final total = base.fold<double>(_leadingWidth, (sum, width) => sum + width);
    final spare = available - total;
    final totalFlex = widget.columns.fold<int>(0, (sum, column) => sum + column.flex);
    if (spare <= 0 || totalFlex == 0) return base;
    return [
      for (var i = 0; i < base.length; i++)
        base[i] + spare * widget.columns[i].flex / totalFlex,
    ];
  }

  // ───────────────────────────────────────────────────────────────────────────
  // Build
  // ───────────────────────────────────────────────────────────────────────────

  @override
  Widget build(BuildContext context) {
    if (widget.error != null) {
      return ErrorPanel(message: widget.error!, onRetry: widget.onRetry ?? () {});
    }
    if (widget.rows == null) return LoadingPanel(label: widget.loadingLabel);
    if (widget.rows!.isEmpty) {
      return EmptyState(
        icon: widget.emptyIcon,
        message: widget.emptyMessage,
        detail: widget.emptyDetail,
      );
    }

    final sorted = _sorted(widget.rows!);
    final pageCount = _pageCount(sorted.length);
    final page = _page.clamp(0, pageCount - 1);
    final start = widget.paging == TablePaging.paginated ? page * widget.rowsPerPage : 0;
    final end = widget.paging == TablePaging.paginated
        ? (start + widget.rowsPerPage).clamp(0, sorted.length)
        : sorted.length;
    final visible = sorted.sublist(start, end);

    final table = LayoutBuilder(
      builder: (context, constraints) {
        final widths = _resolveWidths(constraints.maxWidth);
        final tableWidth = widths.fold<double>(
          _leadingWidth,
          (sum, width) => sum + width,
        );
        return Scrollbar(
          controller: _horizontal,
          scrollbarOrientation: ScrollbarOrientation.bottom,
          child: SingleChildScrollView(
            controller: _horizontal,
            scrollDirection: Axis.horizontal,
            child: SizedBox(
              // Never narrower than the viewport, so a short table still fills
              // the card instead of stranding its header over empty space.
              width: tableWidth < constraints.maxWidth ? constraints.maxWidth : tableWidth,
              child: Column(
                mainAxisSize: widget.shrinkWrap ? MainAxisSize.min : MainAxisSize.max,
                children: [
                  // Outside the vertical scroller on purpose — this is the
                  // pinned header.
                  _header(context, widths, sorted),
                  divider,
                  // `Expanded` only where there is a bounded height to divide
                  // up; a shrink-wrapped table is laid out inside an unbounded
                  // parent, where any flex child is an assertion.
                  if (widget.shrinkWrap)
                    _body(context, widths, visible)
                  else
                    Expanded(child: _body(context, widths, visible)),
                ],
              ),
            ),
          ),
        );
      },
    );

    return Semantics(
      container: true,
      label: widget.caption,
      explicitChildNodes: true,
      child: Column(
        mainAxisSize: widget.shrinkWrap ? MainAxisSize.min : MainAxisSize.max,
        children: [
          if (widget.shrinkWrap) table else Expanded(child: table),
          if (widget.paging == TablePaging.paginated)
            _PageBar(
              page: page,
              pageCount: pageCount,
              first: start + 1,
              last: end,
              total: sorted.length,
              onChanged: (next) {
                setState(() => _page = next);
                // The rows swap under a reader who cannot see them change.
                announceToScreenReader(context, 'Page ${next + 1} of $pageCount');
                if (_vertical.hasClients) _vertical.jumpTo(0);
              },
            ),
        ],
      ),
    );
  }

  Widget _body(BuildContext context, List<double> widths, List<T> visible) {
    return Scrollbar(
      controller: widget.shrinkWrap ? null : _vertical,
      child: ListView.separated(
        controller: widget.shrinkWrap ? null : _vertical,
        shrinkWrap: widget.shrinkWrap,
        physics: widget.shrinkWrap ? const NeverScrollableScrollPhysics() : null,
        padding: EdgeInsets.zero,
        itemCount: visible.length,
        separatorBuilder: (_, __) => divider,
        itemBuilder: (context, index) => _row(context, widths, visible[index]),
      ),
    );
  }

  // ───────────────────────────────────────────────────────────────────────────
  // Header
  // ───────────────────────────────────────────────────────────────────────────

  Widget _header(BuildContext context, List<double> widths, List<T> allRows) {
    final theme = Theme.of(context);
    final colors = theme.portal;
    return Container(
      color: colors.surfaceSubtle,
      constraints: const BoxConstraints(minHeight: minTapTarget),
      child: Row(
        children: [
          if (widget.selectedKeys != null) _selectAll(context, allRows),
          if (widget.expansionBuilder != null)
            // No control here: "expand everything" would build every detail
            // panel at once, which is exactly what the lazy body avoids.
            const SizedBox(width: _controlWidth),
          for (var i = 0; i < widget.columns.length; i++)
            SizedBox(width: widths[i], child: _headerCell(context, i)),
        ],
      ),
    );
  }

  Widget _headerCell(BuildContext context, int index) {
    final theme = Theme.of(context);
    final colors = theme.portal;
    final column = widget.columns[index];
    final sortable = column.sortValue != null;
    final isSorted = sortable && _sortColumn == index;

    Widget label = column.headerIcon != null
        ? Icon(column.headerIcon, size: 18, color: colors.textSecondary)
        : Text(
            column.label,
            style: theme.textTheme.labelLarge?.copyWith(color: colors.textSecondary),
            overflow: TextOverflow.ellipsis,
          );
    if (column.tooltip != null) {
      label = Tooltip(message: column.tooltip!, child: label);
    }

    final content = Padding(
      padding: EdgeInsets.symmetric(
        horizontal: Space.sm,
        vertical: widget.density.verticalPadding,
      ),
      child: Row(
        mainAxisAlignment:
            column.numeric ? MainAxisAlignment.end : MainAxisAlignment.start,
        children: [
          Flexible(child: label),
          if (isSorted) ...[
            const SizedBox(width: Space.xxs),
            // The direction is shown, not just the fact of sorting: an
            // unlabelled "this column is active" mark leaves the reader to
            // infer the order from the data.
            Icon(
              _ascending ? Icons.arrow_upward : Icons.arrow_downward,
              size: 15,
              color: colors.textPrimary,
            ),
          ],
        ],
      ),
    );

    if (!sortable) {
      return Semantics(
        label: column.accessibleLabel,
        excludeSemantics: true,
        child: content,
      );
    }

    // Announced the way a sortable column has to be — name, then state — and
    // reachable by Tab. `InkWell` activates on Enter and Space when focused,
    // so the sort is not pointer-only.
    return Semantics(
      button: true,
      label: isSorted
          ? '${column.accessibleLabel}, sorted ${_ascending ? 'ascending' : 'descending'}'
          : '${column.accessibleLabel}, not sorted',
      hint: isSorted && _ascending ? 'Sort descending' : 'Sort ascending',
      excludeSemantics: true,
      child: InkWell(
        onTap: () => _sortBy(index),
        child: content,
      ),
    );
  }

  Widget _selectAll(BuildContext context, List<T> allRows) {
    final keyOf = widget.rowKey!;
    final selectable = allRows
        .where((row) => widget.isSelectable?.call(row) ?? true)
        .toList();
    final selected = widget.selectedKeys!;
    final all = selectable.isNotEmpty &&
        selectable.every((row) => selected.contains(keyOf(row)));
    final some = selectable.any((row) => selected.contains(keyOf(row)));
    return SizedBox(
      width: _controlWidth,
      child: Semantics(
        label: all ? 'Deselect all rows' : 'Select all rows',
        child: Checkbox(
          value: all ? true : (some ? null : false),
          tristate: true,
          onChanged: selectable.isEmpty
              ? null
              : (_) {
                  // Acts on every selectable row in the *dataset*, not just the
                  // page in view — an admin who ticks "select all" and then
                  // approves expects the whole filtered roster, and silently
                  // approving 25 of 300 would be the worse surprise.
                  for (final row in selectable) {
                    widget.onSelectChanged?.call(row, !all);
                  }
                  announceToScreenReader(
                    context,
                    all ? 'Selection cleared' : '${selectable.length} rows selected',
                  );
                },
        ),
      ),
    );
  }

  // ───────────────────────────────────────────────────────────────────────────
  // Rows
  // ───────────────────────────────────────────────────────────────────────────

  Widget _row(BuildContext context, List<double> widths, T row) {
    final colors = Theme.of(context).portal;
    final key = widget.rowKey?.call(row);
    final selected = key != null && (widget.selectedKeys?.contains(key) ?? false);
    final isExpanded = key != null && _expanded.contains(key);

    final cells = Row(
      children: [
        if (widget.selectedKeys != null) _rowCheckbox(row, selected),
        if (widget.expansionBuilder != null) _rowDisclosure(row, key, isExpanded),
        for (var i = 0; i < widget.columns.length; i++)
          SizedBox(
            width: widths[i],
            child: Padding(
              padding: EdgeInsets.symmetric(
                horizontal: Space.sm,
                vertical: widget.density.verticalPadding,
              ),
              child: Align(
                alignment: widget.columns[i].numeric
                    ? Alignment.centerRight
                    : Alignment.centerLeft,
                child: widget.columns[i].cell(context, row),
              ),
            ),
          ),
      ],
    );

    return Semantics(
      container: true,
      label: widget.rowSemanticLabel?.call(row),
      child: Container(
        color: selected ? colors.infoSurface : null,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            ConstrainedBox(
              // A floor, not a height. Cells here stack a name over an email
              // over two lines of eligibility reasons, and at 200% text scale a
              // capped row paints overflow stripes straight over the reasons.
              constraints: BoxConstraints(minHeight: widget.density.minRowHeight),
              child: cells,
            ),
            if (isExpanded)
              Padding(
                padding: const EdgeInsets.fromLTRB(
                  _controlWidth,
                  0,
                  Space.md,
                  Space.md,
                ),
                child: widget.expansionBuilder!(context, row),
              ),
          ],
        ),
      ),
    );
  }

  Widget _rowCheckbox(T row, bool selected) {
    final selectable = widget.isSelectable?.call(row) ?? true;
    return SizedBox(
      width: _controlWidth,
      child: selectable
          ? Checkbox(
              value: selected,
              onChanged: (value) => widget.onSelectChanged?.call(row, value ?? false),
            )
          : const SizedBox.shrink(),
    );
  }

  Widget _rowDisclosure(T row, Object? key, bool isExpanded) {
    final label = widget.rowSemanticLabel?.call(row);
    return SizedBox(
      width: _controlWidth,
      child: IconButton(
        // Named per row, because a column of identically-labelled "Expand"
        // buttons tells a screen reader user nothing about which one they are on.
        tooltip: isExpanded
            ? 'Hide details${label == null ? '' : ' for $label'}'
            : 'Show details${label == null ? '' : ' for $label'}',
        icon: Icon(isExpanded ? Icons.expand_less : Icons.expand_more, size: 20),
        onPressed: key == null
            ? null
            : () => setState(
                  () => isExpanded ? _expanded.remove(key) : _expanded.add(key),
                ),
      ),
    );
  }
}

/// "Rows 26–50 of 312", and the controls to move between them.
class _PageBar extends StatelessWidget {
  const _PageBar({
    required this.page,
    required this.pageCount,
    required this.first,
    required this.last,
    required this.total,
    required this.onChanged,
  });

  final int page;
  final int pageCount;
  final int first;
  final int last;
  final int total;
  final ValueChanged<int> onChanged;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final colors = theme.portal;
    final summary = 'Rows $first to $last of $total';
    return Container(
      decoration: const BoxDecoration(border: Border(top: BorderSide(color: border))),
      padding: const EdgeInsets.symmetric(horizontal: Space.sm, vertical: Space.xxs),
      child: Row(
        children: [
          Expanded(
            child: Semantics(
              // A live region: the counts change without anything moving focus,
              // so nothing would otherwise say what the new page holds.
              liveRegion: true,
              child: Text(
                '$summary  ·  page ${page + 1} of $pageCount',
                style: theme.textTheme.labelMedium?.copyWith(
                  color: colors.textSecondary,
                  fontWeight: FontWeight.w400,
                ),
              ),
            ),
          ),
          IconButton(
            tooltip: 'First page',
            onPressed: page == 0 ? null : () => onChanged(0),
            icon: const Icon(Icons.first_page, size: 20),
          ),
          IconButton(
            tooltip: 'Previous page',
            onPressed: page == 0 ? null : () => onChanged(page - 1),
            icon: const Icon(Icons.chevron_left, size: 20),
          ),
          IconButton(
            tooltip: 'Next page',
            onPressed: page >= pageCount - 1 ? null : () => onChanged(page + 1),
            icon: const Icon(Icons.chevron_right, size: 20),
          ),
          IconButton(
            tooltip: 'Last page',
            onPressed: page >= pageCount - 1 ? null : () => onChanged(pageCount - 1),
            icon: const Icon(Icons.last_page, size: 20),
          ),
        ],
      ),
    );
  }
}
