import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../core/session.dart';
import '../models/models.dart';
import '../widgets/common.dart';

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
      if (mounted) setState(() => error = exception.toString());
    }
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
              const PageHeader(title: 'Events', subtitle: 'Create, monitor, and complete continuing education events.'),
              const SizedBox(height: 20),
              Row(
                children: [
                  Expanded(
                    child: TextField(
                      controller: search,
                      onSubmitted: (_) => load(),
                      decoration: const InputDecoration(prefixIcon: Icon(Icons.search), hintText: 'Search events'),
                    ),
                  ),
                  const SizedBox(width: 10),
                  IconButton.filledTonal(tooltip: 'Refresh', onPressed: load, icon: const Icon(Icons.refresh)),
                ],
              ),
              const SizedBox(height: 16),
              Expanded(
                child: Card(
                  child: error != null
                      ? ErrorPanel(message: error!, onRetry: load)
                      : events == null
                          ? const LoadingPanel()
                          : events!.isEmpty
                              ? EmptyState(
                                  icon: Icons.event_note_outlined,
                                  message: search.text.trim().isEmpty ? 'No events yet' : 'No events match this search',
                                  detail: search.text.trim().isEmpty
                                      ? 'Create the first training event to get started.'
                                      : 'Try a different search term.',
                                )
                              : SingleChildScrollView(
                                  child: SingleChildScrollView(
                                    scrollDirection: Axis.horizontal,
                                    child: DataTable(
                                      columns: const [
                                        DataColumn(label: Text('Event')),
                                        DataColumn(label: Text('Date')),
                                        DataColumn(label: Text('Location')),
                                        DataColumn(label: Text('Presenter')),
                                        DataColumn(label: Text('Status')),
                                        DataColumn(label: Text('')),
                                      ],
                                      rows: events!
                                          .map(
                                            (event) => DataRow(
                                              cells: [
                                                DataCell(SizedBox(width: 280, child: Text(event.title, style: const TextStyle(fontWeight: FontWeight.w600)))),
                                                DataCell(Text(DateFormat.yMMMd().format(event.eventDate))),
                                                DataCell(Text(event.location ?? 'Remote / TBD')),
                                                DataCell(Text(event.presenterName ?? 'Not assigned')),
                                                DataCell(StatusBadge(event.status.toUpperCase(), tone: event.status == 'review' ? BadgeTone.warning : BadgeTone.info)),
                                                DataCell(IconButton(tooltip: 'Open event', onPressed: () => widget.onOpen(event), icon: const Icon(Icons.arrow_forward))),
                                              ],
                                            ),
                                          )
                                          .toList(),
                                    ),
                                  ),
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

