import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:intl/intl.dart';

import '../core/session.dart';
import '../models/models.dart';
import '../widgets/charts.dart';
import '../widgets/common.dart';

class DashboardPage extends StatefulWidget {
  const DashboardPage({
    super.key,
    required this.session,
    required this.onOpenEvents,
    required this.onCreateEvent,
  });

  final SessionController session;
  final VoidCallback onOpenEvents;
  final VoidCallback onCreateEvent;

  @override
  State<DashboardPage> createState() => _DashboardPageState();
}

class _DashboardPageState extends State<DashboardPage> {
  DashboardStats? stats;
  DashboardCharts? charts;
  List<TrainingEvent> events = [];
  // Date labels for the "Eligible attendees by event" chart. Recurring series
  // share a title, so a truncated title renders identical bars; the event date
  // is what tells them apart.
  List<String> complianceChartLabels = [];
  String? error;

  @override
  void initState() {
    super.initState();
    load();
  }

  Future<void> load() async {
    setState(() => error = null);
    try {
      final results = await Future.wait([
        widget.session.api.get('/dashboard'),
        widget.session.api.get('/events'),
        widget.session.api.get('/dashboard/charts'),
      ]);
      if (!mounted) return;
      final allEvents = (results[1] as List)
          .map((item) => TrainingEvent.fromJson(item as Map<String, dynamic>))
          .toList();
      final chartsJson = results[2] as Map<String, dynamic>;
      final dateById = {for (final event in allEvents) event.id: event.eventDate};
      setState(() {
        stats = DashboardStats.fromJson(results[0] as Map<String, dynamic>);
        events = allEvents.take(5).toList();
        charts = DashboardCharts.fromJson(chartsJson);
        complianceChartLabels = [
          for (final point in (chartsJson['events_compliance'] as List? ?? const []))
            _chartLabel(point as Map<String, dynamic>, dateById),
        ];
      });
    } catch (exception) {
      if (mounted) {
        final message = humanizeError(exception);
        setState(() => error = message);
        announceToScreenReader(context, message);
      }
    }
  }

  /// Label a chart bar by the event's date (recurring series share a title, so
  /// dates are the only distinguishing part); falls back to a truncated title.
  static String _chartLabel(Map<String, dynamic> point, Map<int, DateTime> dateById) {
    final date = dateById[point['event_id'] as int?];
    if (date != null) return DateFormat.MMMd().format(date.toLocal());
    final title = point['title'] as String? ?? '';
    return title.length > 14 ? '${title.substring(0, 12)}…' : title;
  }

  void openEvent(TrainingEvent event) => context.go('/events/${event.id}', extra: event);

  @override
  Widget build(BuildContext context) {
    if (error != null) return ErrorPanel(message: error!, onRetry: load);
    if (stats == null) return const LoadingPanel(label: 'Loading dashboard');
    final theme = Theme.of(context);
    final colors = theme.portal;
    final data = stats!;
    final isAdmin = widget.session.user!.isAdmin;
    return SingleChildScrollView(
      padding: pagePadding,
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: maxContentWidth),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              PageHeader(
                title: 'Dashboard',
                subtitle: 'A current view of events, reviews, and certificate delivery.',
                actions: [
                  OutlinedButton.icon(onPressed: widget.onOpenEvents, icon: const Icon(Icons.event_note_outlined), label: const Text('View events')),
                  if (isAdmin)
                    ElevatedButton.icon(onPressed: widget.onCreateEvent, icon: const Icon(Icons.add), label: const Text('Create event')),
                ],
              ),
              const SizedBox(height: Space.xl),
              LayoutBuilder(
                builder: (context, constraints) {
                  final columns = constraints.maxWidth >= 1100 ? 5 : constraints.maxWidth >= 620 ? 2 : 1;
                  final width = (constraints.maxWidth - (columns - 1) * Space.sm) / columns;
                  final cards = [
                    StatCard(label: 'Total events', value: '${data.totalEvents}', icon: Icons.event_available_outlined, color: navy),
                    StatCard(label: 'Upcoming', value: '${data.upcomingEvents}', icon: Icons.calendar_month_outlined, color: teal),
                    StatCard(label: 'Pending review', value: '${data.pendingReviews}', icon: Icons.fact_check_outlined, color: gold),
                    StatCard(label: 'Certificates sent', value: '${data.certificatesSent}', icon: Icons.send_outlined, color: colors.accentAlt),
                    StatCard(label: 'Compliance rate', value: '${data.complianceRate.toStringAsFixed(1)}%', icon: Icons.insights_outlined, color: colors.success),
                  ];
                  return Wrap(spacing: Space.sm, runSpacing: Space.sm, children: cards.map((card) => SizedBox(width: width, child: card)).toList());
                },
              ),
              if (charts != null) ...[
                const SizedBox(height: Space.xl),
                LayoutBuilder(
                  builder: (context, constraints) {
                    final twoUp = constraints.maxWidth >= 900;
                    final width = twoUp ? (constraints.maxWidth - Space.sm) / 2 : constraints.maxWidth;
                    return Wrap(
                      spacing: Space.sm,
                      runSpacing: Space.sm,
                      children: [
                        SizedBox(
                          width: width,
                          child: ChartCard(
                            title: 'Post-test score distribution',
                            child: SimpleBarChart(
                              description: 'Post-test score distribution',
                              labels: charts!.scoreDistribution.map((b) => b.label).toList(),
                              values: charts!.scoreDistribution.map((b) => b.value.toDouble()).toList(),
                              color: navy,
                            ),
                          ),
                        ),
                        SizedBox(
                          width: width,
                          child: ChartCard(
                            title: 'Certificates sent (last 6 months)',
                            child: SimpleBarChart(
                              description: 'Certificates sent in the last 6 months',
                              labels: charts!.monthlyCertificates.map((b) => b.label).toList(),
                              values: charts!.monthlyCertificates.map((b) => b.value.toDouble()).toList(),
                              color: teal,
                            ),
                          ),
                        ),
                        if (charts!.eventsCompliance.isNotEmpty)
                          SizedBox(
                            width: constraints.maxWidth,
                            child: ChartCard(
                              title: 'Eligible attendees by event',
                              child: SimpleBarChart(
                                description: 'Eligible attendees by event',
                                labels: complianceChartLabels.length == charts!.eventsCompliance.length
                                    ? complianceChartLabels
                                    : [
                                        for (final e in charts!.eventsCompliance)
                                          e.title.length > 14 ? '${e.title.substring(0, 12)}…' : e.title,
                                      ],
                                values: charts!.eventsCompliance.map((e) => e.eligible.toDouble()).toList(),
                                color: colors.success,
                              ),
                            ),
                          ),
                      ],
                    );
                  },
                ),
              ],
              const SizedBox(height: Space.xl),
              Card(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Padding(
                      padding: const EdgeInsets.all(Space.lg),
                      child: Row(
                        children: [
                          const Expanded(child: SectionTitle('Recent events')),
                          TextButton(onPressed: widget.onOpenEvents, child: const Text('View all')),
                        ],
                      ),
                    ),
                    divider,
                    if (events.isEmpty)
                      Padding(
                        padding: const EdgeInsets.all(Space.xxl),
                        child: Text(isAdmin
                            ? 'No events yet. Create the first training event.'
                            : 'No events assigned to you yet — your NMEDA administrator will assign your session before the event date.'),
                      )
                    else
                      SingleChildScrollView(
                        scrollDirection: Axis.horizontal,
                        child: DataTable(
                          showCheckboxColumn: false,
                          columns: [
                            const DataColumn(label: Text('Event')),
                            const DataColumn(label: Text('Date')),
                            const DataColumn(label: Text('CEU hours')),
                            const DataColumn(label: Text('Presenter')),
                            const DataColumn(label: Text('Status')),
                            DataColumn(label: Semantics(label: 'Open', child: const Text(''))),
                          ],
                          rows: events
                              .map(
                                (event) => DataRow(
                                  onSelectChanged: (_) => openEvent(event),
                                  cells: [
                                    DataCell(ConstrainedBox(
                                      constraints: const BoxConstraints(minWidth: 260, maxWidth: 360),
                                      child: Text(
                                        event.title,
                                        style: theme.textTheme.bodyMedium
                                            ?.copyWith(fontWeight: FontWeight.w600),
                                      ),
                                    )),
                                    DataCell(Text(formatDate(event.eventDate))),
                                    DataCell(Text(event.ceuHours.toStringAsFixed(1))),
                                    DataCell(Text(event.presenterName ?? 'Not assigned')),
                                    DataCell(_statusBadge(event.status)),
                                    DataCell(IconButton(tooltip: 'Open ${event.title}', onPressed: () => openEvent(event), icon: const Icon(Icons.arrow_forward))),
                                  ],
                                ),
                              )
                              .toList(),
                        ),
                      ),
                  ],
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

