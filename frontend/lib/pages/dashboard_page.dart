import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:intl/intl.dart';

import '../core/session.dart';
import '../models/models.dart';
import '../widgets/charts.dart';
import '../widgets/common.dart';
import '../widgets/portal_table.dart';

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
                  // Ordered by what the reader can act on, not by what is
                  // easiest to count. "Pending review" is the only number that
                  // represents work waiting for a person, and it used to sit
                  // third and inert while "Total events" — a figure nobody acts
                  // on — led the page. Anything with somewhere to go is now
                  // clickable, so the number is a route into the work rather
                  // than a read-only fact.
                  // Every role still sees every number — a presenter losing
                  // sight of the compliance figures would be a step backwards.
                  // Only the *link* is role-aware: the Certificate Center is
                  // admin-only, so making those cards tappable for a presenter
                  // would just bounce them off the router's guard.
                  final cards = [
                    _ActionableStat(
                      onTap: isAdmin ? () => context.go('/certificates') : null,
                      hint: 'Opens the Certificate Center',
                      child: StatCard(label: 'Pending review', value: '${data.pendingReviews}', icon: Icons.fact_check_outlined, color: gold),
                    ),
                    _ActionableStat(
                      onTap: widget.onOpenEvents,
                      hint: 'Opens Events',
                      child: StatCard(label: 'Upcoming', value: '${data.upcomingEvents}', icon: Icons.calendar_month_outlined, color: teal),
                    ),
                    _ActionableStat(
                      onTap: isAdmin ? () => context.go('/certificates') : null,
                      hint: 'Opens the Certificate Center',
                      child: StatCard(label: 'Certificates sent', value: '${data.certificatesSent}', icon: Icons.send_outlined, color: colors.accentAlt),
                    ),
                    StatCard(label: 'Compliance rate', value: '${data.complianceRate.toStringAsFixed(1)}%', icon: Icons.insights_outlined, color: colors.success),
                    _ActionableStat(
                      onTap: widget.onOpenEvents,
                      hint: 'Opens Events',
                      child: StatCard(label: 'Total events', value: '${data.totalEvents}', icon: Icons.event_available_outlined, color: navy),
                    ),
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
                              // Plots the rate, not the raw count. Charting
                              // `eligible` alone threw away the denominator, so
                              // a flawless 3-of-3 event drew a shorter bar than
                              // a struggling 10-of-50 and the chart ranked
                              // events by size while appearing to rank them by
                              // compliance. The counts survive in the
                              // description, which is also what a screen reader
                              // gets instead of the bars.
                              title: 'Eligibility rate by event',
                              child: SimpleBarChart(
                                description: 'Eligibility rate by event. '
                                    '${[
                                      for (final e in charts!.eventsCompliance)
                                        '${e.title}: ${e.eligible} of ${e.total} eligible',
                                    ].join('. ')}.',
                                labels: complianceChartLabels.length == charts!.eventsCompliance.length
                                    ? complianceChartLabels
                                    : [
                                        for (final e in charts!.eventsCompliance)
                                          e.title.length > 14 ? '${e.title.substring(0, 12)}…' : e.title,
                                      ],
                                values: [
                                  for (final e in charts!.eventsCompliance)
                                    e.total == 0 ? 0.0 : e.eligible / e.total * 100,
                                ],
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
                      // Virtualized rather than paginated, and shrink-wrapped:
                      // this is a five-row preview inside the page's own
                      // scroller, so paging controls under it would be
                      // furniture for a list that never has a second page.
                      PortalTable<TrainingEvent>(
                        paging: TablePaging.virtualized,
                        shrinkWrap: true,
                        density: TableDensity.compact,
                        columns: [
                          TableColumn<TrainingEvent>(
                            label: 'Event',
                            width: 260,
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
                            width: 120,
                            sortValue: (event) => event.eventDate,
                            cell: (context, event) => Text(formatDate(event.eventDate)),
                          ),
                          TableColumn<TrainingEvent>(
                            label: 'CEU hours',
                            width: 110,
                            numeric: true,
                            sortValue: (event) => event.ceuHours,
                            cell: (context, event) => Text(event.ceuHours.toStringAsFixed(1)),
                          ),
                          TableColumn<TrainingEvent>(
                            label: 'Presenter',
                            width: 160,
                            flex: 1,
                            sortValue: (event) => event.presenterName,
                            cell: (context, event) => Text(event.presenterName ?? 'Not assigned', overflow: TextOverflow.ellipsis),
                          ),
                          TableColumn<TrainingEvent>(
                            label: 'Status',
                            width: 175,
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
                              onPressed: () => openEvent(event),
                              icon: const Icon(Icons.arrow_forward),
                            ),
                          ),
                        ],
                        rows: events,
                        rowKey: (event) => event.id,
                        rowSemanticLabel: (event) =>
                            '${event.title}, ${formatDate(event.eventDate)}, ${eventStatusDisplay(event.status).$1}',
                        emptyIcon: Icons.event_note_outlined,
                        emptyMessage: 'No events yet',
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


/// Makes a [StatCard] a real destination.
///
/// A wrapper rather than a parameter on StatCard because the shared widgets are
/// being reworked in parallel; this keeps the change local. `button: true` with
/// `excludeSemantics: false` keeps the card's own label and value readable while
/// adding the affordance, so a screen reader announces the number *and* that it
/// leads somewhere.
class _ActionableStat extends StatelessWidget {
  const _ActionableStat({required this.child, required this.onTap, required this.hint});

  final Widget child;

  /// Null when this role has nowhere to go, in which case the card renders as
  /// the plain read-only figure it always was — no button semantics, no hover,
  /// nothing promising an action that the router would refuse.
  final VoidCallback? onTap;
  final String hint;

  @override
  Widget build(BuildContext context) {
    if (onTap == null) return child;
    return Semantics(
      button: true,
      hint: hint,
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(8),
        child: child,
      ),
    );
  }
}
