import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../core/session.dart';
import '../models/models.dart';
import '../widgets/common.dart';
import '../widgets/portal_table.dart';

class EventsPage extends StatefulWidget {
  const EventsPage({super.key, required this.session, required this.onOpen});
  final SessionController session;
  final ValueChanged<TrainingEvent> onOpen;

  @override
  State<EventsPage> createState() => _EventsPageState();
}

class _EventsPageState extends State<EventsPage> {
  final search = TextEditingController();
  List<TrainingEvent>? events;
  String? error;

  @override
  void initState() {
    super.initState();
    load();
  }

  @override
  void dispose() {
    search.dispose();
    super.dispose();
  }

  Future<void> load() async {
    setState(() {
      events = null;
      error = null;
    });
    try {
      final encoded = Uri.encodeQueryComponent(search.text.trim());
      final result = await widget.session.api.get('/events${encoded.isEmpty ? '' : '?search=$encoded'}') as List;
      if (mounted) {
        setState(() => events = result.map((item) => TrainingEvent.fromJson(item as Map<String, dynamic>)).toList());
      }
    } catch (exception) {
      if (mounted) {
        final message = humanizeError(exception);
        setState(() => error = message);
        announceToScreenReader(context, message);
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final isAdmin = widget.session.user!.isAdmin;
    final searching = search.text.trim().isNotEmpty;
    return Padding(
      padding: pagePadding,
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: maxContentWidth),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              PageHeader(
                title: 'Events',
                subtitle: isAdmin
                    ? 'Create, monitor, and complete continuing education events.'
                    : 'Your assigned training sessions.',
                actions: [
                  if (isAdmin)
                    ElevatedButton.icon(
                      onPressed: () => context.go('/create'),
                      icon: const Icon(Icons.add),
                      label: const Text('Create event'),
                    ),
                ],
              ),
              const SizedBox(height: Space.lg),
              Row(
                children: [
                  Expanded(
                    child: TextField(
                      controller: search,
                      onSubmitted: (_) => load(),
                      decoration: const InputDecoration(prefixIcon: Icon(Icons.search), hintText: 'Search events'),
                    ),
                  ),
                  const SizedBox(width: Space.xs + 2),
                  IconButton.filledTonal(tooltip: 'Refresh the event list', onPressed: load, icon: const Icon(Icons.refresh)),
                ],
              ),
              const SizedBox(height: Space.md),
              Expanded(
                child: Card(
                  child: error != null
                      ? ErrorPanel(message: error!, onRetry: load)
                      : events == null
                          ? const LoadingPanel(label: 'Loading events')
                          : events!.isEmpty
                              ? Center(
                                  child: Column(
                                    mainAxisSize: MainAxisSize.min,
                                    children: [
                                      EmptyState(
                                        icon: Icons.event_note_outlined,
                                        message: searching
                                            ? 'No events match this search'
                                            : isAdmin
                                                ? 'No events yet'
                                                : 'No events assigned to you yet',
                                        detail: searching
                                            ? 'Try a different search term.'
                                            : isAdmin
                                                ? 'Create the first training event to get started.'
                                                : 'Your NMEDA administrator will assign your session before the event date.',
                                      ),
                                      if (isAdmin && !searching)
                                        Padding(
                                          padding: const EdgeInsets.only(bottom: Space.xl),
                                          child: ElevatedButton.icon(
                                            onPressed: () => context.go('/create'),
                                            icon: const Icon(Icons.add),
                                            label: const Text('Create event'),
                                          ),
                                        ),
                                    ],
                                  ),
                                )
                              : PortalTable<TrainingEvent>(
                                  columns: [
                                    TableColumn<TrainingEvent>(
                                      label: 'Event',
                                      width: 280,
                                      flex: 2,
                                      sortValue: (event) => event.title,
                                      cell: (context, event) => Text(
                                        event.title,
                                        overflow: TextOverflow.ellipsis,
                                        style: theme.textTheme.bodyMedium?.copyWith(fontWeight: FontWeight.w600),
                                      ),
                                    ),
                                    TableColumn<TrainingEvent>(
                                      label: 'Date',
                                      width: 130,
                                      // Sorts on the DateTime, not its rendered
                                      // text, or "Mar 3" would file under M.
                                      sortValue: (event) => event.eventDate,
                                      cell: (context, event) => Text(formatDate(event.eventDate)),
                                    ),
                                    TableColumn<TrainingEvent>(
                                      label: 'Location',
                                      width: 170,
                                      flex: 1,
                                      sortValue: (event) => event.location,
                                      cell: (context, event) => Text(event.location ?? 'Remote / TBD', overflow: TextOverflow.ellipsis),
                                    ),
                                    TableColumn<TrainingEvent>(
                                      label: 'Presenter',
                                      width: 170,
                                      flex: 1,
                                      sortValue: (event) => event.presenterName,
                                      cell: (context, event) => Text(event.presenterName ?? 'Not assigned', overflow: TextOverflow.ellipsis),
                                    ),
                                    TableColumn<TrainingEvent>(
                                      label: 'Status',
                                      width: 180,
                                      sortValue: (event) => eventStatusDisplay(event.status).$1,
                                      cell: (context, event) => _statusBadge(event.status),
                                    ),
                                    TableColumn<TrainingEvent>(
                                      label: '',
                                      width: 64,
                                      headerIcon: Icons.open_in_new,
                                      semanticLabel: 'Open',
                                      cell: (context, event) => IconButton(
                                        tooltip: 'Open ${event.title}',
                                        onPressed: () => widget.onOpen(event),
                                        icon: const Icon(Icons.arrow_forward),
                                      ),
                                    ),
                                  ],
                                  rows: events!,
                                  // Newest first: the event you just created or
                                  // are about to run is the one you came for.
                                  initialSortColumn: 1,
                                  initialSortAscending: false,
                                  rowKey: (event) => event.id,
                                  rowSemanticLabel: (event) =>
                                      '${event.title}, ${formatDate(event.eventDate)}, ${eventStatusDisplay(event.status).$1}',
                                  emptyIcon: Icons.event_busy_outlined,
                                  emptyMessage: 'No events match',
                                ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

StatusBadge _statusBadge(String status) {
  final (label, tone) = eventStatusDisplay(status);
  return StatusBadge(label, tone: tone);
}
