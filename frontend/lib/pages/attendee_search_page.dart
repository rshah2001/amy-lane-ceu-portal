import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../core/session.dart';
import '../models/models.dart';
import '../widgets/common.dart';

class AttendeeSearchPage extends StatefulWidget {
  const AttendeeSearchPage({super.key, required this.session});
  final SessionController session;

  @override
  State<AttendeeSearchPage> createState() => _AttendeeSearchPageState();
}

class _AttendeeSearchPageState extends State<AttendeeSearchPage> {
  final query = TextEditingController();
  List<Map<String, dynamic>>? rows;
  List<TrainingEvent> events = const [];
  String? error;

  /// null means "All events" — this page searches across events by design, so
  /// narrowing to one roster (e.g. checking who a sign-in sheet just added) is
  /// an explicit choice.
  int? eventId;

  @override
  void initState() {
    super.initState();
    loadEvents();
    search();
  }

  @override
  void dispose() {
    query.dispose();
    super.dispose();
  }

  Future<void> loadEvents() async {
    try {
      final result = await widget.session.api.get('/events') as List;
      if (mounted) {
        setState(() {
          events = result.map((item) => TrainingEvent.fromJson(item as Map<String, dynamic>)).toList();
          // A Dropdown asserts if its value has no matching item, so a
          // selection that is no longer in the list falls back to "All events".
          if (eventId != null && !events.any((event) => event.id == eventId)) eventId = null;
        });
      }
    } catch (_) {
      // The event filter is an optional narrowing; the search itself still
      // works without it, so a failure here must not block the page.
    }
  }

  /// Guards against an out-of-order response: flipping the event filter twice
  /// leaves two requests in flight, and without this the slower (older) one
  /// would win and show a roster that doesn't match the dropdown.
  int _requestSeq = 0;

  Future<void> search() async {
    final seq = ++_requestSeq;
    setState(() {
      rows = null;
      error = null;
    });
    try {
      final params = <String>[
        if (query.text.trim().isNotEmpty) 'q=${Uri.encodeQueryComponent(query.text.trim())}',
        if (eventId != null) 'event_id=$eventId',
      ];
      final result = await widget.session.api
          .get('/attendees/search${params.isEmpty ? '' : '?${params.join('&')}'}') as List;
      if (mounted && seq == _requestSeq) {
        setState(() {
          rows = result.cast<Map<String, dynamic>>();
          error = null;
        });
      }
    } catch (exception) {
      if (mounted && seq == _requestSeq) {
        final message = humanizeError(exception);
        setState(() => error = message);
        announceToScreenReader(context, message);
      }
    }
  }

  /// Buckets the flat result rows into one group per event, newest event first,
  /// so each event can be opened to reveal just its attendees.
  List<_EventGroup> _groupByEvent(List<Map<String, dynamic>> rows) {
    final groups = <String, _EventGroup>{};
    for (final row in rows) {
      final title = row['event_title'] as String? ?? 'Unknown event';
      final dateRaw = row['event_date'] as String?;
      final key = '${row['event_id'] ?? title}|$dateRaw';
      groups
          .putIfAbsent(
            key,
            () => _EventGroup(
              title: title,
              date: dateRaw == null ? null : DateTime.tryParse(dateRaw),
            ),
          )
          .rows
          .add(row);
    }
    final sorted = groups.values.toList()
      ..sort((a, b) {
        if (a.date == null || b.date == null) return a.date == null ? 1 : -1;
        return b.date!.compareTo(a.date!);
      });
    return sorted;
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: pagePadding,
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: maxContentWidth),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const PageHeader(title: 'Attendee Search', subtitle: 'Find attendees across events, approvals, and issued certificates.'),
              const SizedBox(height: Space.md),
              LayoutBuilder(
                builder: (context, constraints) {
                  final searchField = TextField(
                    controller: query,
                    onSubmitted: (_) => search(),
                    decoration: const InputDecoration(prefixIcon: Icon(Icons.search), hintText: 'Search name, email, or company'),
                  );
                  final eventFilter = DropdownButtonFormField<int?>(
                    initialValue: eventId,
                    isExpanded: true,
                    decoration: const InputDecoration(
                      prefixIcon: Icon(Icons.event_note_outlined),
                      labelText: 'Event',
                      isDense: true,
                    ),
                    items: [
                      const DropdownMenuItem<int?>(value: null, child: Text('All events')),
                      for (final event in events)
                        DropdownMenuItem<int?>(
                          value: event.id,
                          child: Text(event.title, overflow: TextOverflow.ellipsis),
                        ),
                    ],
                    onChanged: (value) {
                      setState(() => eventId = value);
                      search();
                    },
                  );
                  final searchButton = IconButton.filledTonal(
                    tooltip: 'Search attendees',
                    onPressed: search,
                    icon: const Icon(Icons.search),
                  );
                  if (constraints.maxWidth < 760) {
                    return Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        searchField,
                        const SizedBox(height: Space.xs + 2),
                        Row(children: [Expanded(child: eventFilter), const SizedBox(width: Space.xs + 2), searchButton]),
                      ],
                    );
                  }
                  return Row(
                    children: [
                      Expanded(flex: 3, child: searchField),
                      const SizedBox(width: Space.xs + 2),
                      Expanded(flex: 2, child: eventFilter),
                      const SizedBox(width: Space.xs + 2),
                      searchButton,
                    ],
                  );
                },
              ),
              const SizedBox(height: Space.sm + 2),
              Expanded(
                child: Card(
                  child: error != null
                      ? ErrorPanel(message: error!, onRetry: search)
                      : rows == null
                          ? const LoadingPanel(label: 'Searching attendees')
                          : rows!.isEmpty
                              ? EmptyState(
                                  icon: Icons.person_search_outlined,
                                  message: query.text.trim().isEmpty
                                      ? (eventId == null ? 'No attendees yet' : 'No attendees on this event yet')
                                      : 'No attendees match this search',
                                  detail: query.text.trim().isEmpty
                                      ? 'Attendees appear here once event rosters and attendance sheets are uploaded.'
                                      : 'Try a different name, email, or company — or widen the event filter to all events.',
                                )
                              : _GroupedResults(groups: _groupByEvent(rows!)),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _EventGroup {
  _EventGroup({required this.title, required this.date});
  final String title;
  final DateTime? date;
  final List<Map<String, dynamic>> rows = [];
}

class _GroupedResults extends StatelessWidget {
  const _GroupedResults({required this.groups});
  final List<_EventGroup> groups;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final colors = theme.portal;
    return ListView.separated(
      padding: const EdgeInsets.symmetric(vertical: Space.xxs),
      itemCount: groups.length,
      separatorBuilder: (_, __) => divider,
      itemBuilder: (context, index) {
        final group = groups[index];
        return ExpansionTile(
          shape: const Border(),
          collapsedShape: const Border(),
          initiallyExpanded: groups.length == 1,
          leading: ExcludeSemantics(
            child: Icon(Icons.event_note_outlined, color: colors.info),
          ),
          title: Text(
            group.title,
            style: theme.textTheme.labelLarge?.copyWith(fontWeight: FontWeight.w700),
          ),
          subtitle: Text(
            group.date == null ? 'Date unknown' : DateFormat.yMMMd().format(group.date!),
            style: theme.textTheme.labelMedium?.copyWith(
              color: colors.textSecondary,
              fontWeight: FontWeight.w400,
            ),
          ),
          trailing: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              StatusBadge('${group.rows.length} ATTENDEE${group.rows.length == 1 ? '' : 'S'}', tone: BadgeTone.info),
              const SizedBox(width: Space.xxs + 2),
              ExcludeSemantics(
                child: Icon(Icons.expand_more, size: 20, color: colors.textSecondary),
              ),
            ],
          ),
          childrenPadding: const EdgeInsets.fromLTRB(Space.md, 0, Space.md, Space.sm + 2),
          children: [
            SingleChildScrollView(
              scrollDirection: Axis.horizontal,
              child: DataTable(
                columns: const [
                  DataColumn(label: Text('Attendee')),
                  DataColumn(label: Text('Email')),
                  DataColumn(label: Text('Company')),
                  DataColumn(label: Text('Status')),
                  DataColumn(label: Text('Certificate')),
                ],
                rows: group.rows
                    .map(
                      (row) => DataRow(
                        cells: [
                          DataCell(ConstrainedBox(
                            constraints: const BoxConstraints(minWidth: 190, maxWidth: 280),
                            child: Text(
                              row['full_name'] as String,
                              style: theme.textTheme.bodyMedium
                                  ?.copyWith(fontWeight: FontWeight.w600),
                            ),
                          )),
                          DataCell(Text(row['email'] as String? ?? '')),
                          DataCell(Text(row['company'] as String? ?? '')),
                          DataCell(StatusBadge(row['approved'] == true ? 'APPROVED' : row['eligible'] == true ? 'ELIGIBLE' : 'INELIGIBLE', tone: row['approved'] == true || row['eligible'] == true ? BadgeTone.success : BadgeTone.danger)),
                          DataCell(Text(row['certificate_number'] as String? ?? '')),
                        ],
                      ),
                    )
                    .toList(),
              ),
            ),
          ],
        );
      },
    );
  }
}
