import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../core/session.dart';
import '../core/theme.dart';
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
      setState(() {
        stats = DashboardStats.fromJson(results[0] as Map<String, dynamic>);
        events = (results[1] as List)
            .map((item) => TrainingEvent.fromJson(item as Map<String, dynamic>))
            .take(5)
            .toList();
        charts = DashboardCharts.fromJson(results[2] as Map<String, dynamic>);
      });
    } catch (exception) {
      if (mounted) setState(() => error = exception.toString());
    }
  }

  @override
  Widget build(BuildContext context) {
    if (error != null) return ErrorPanel(message: error!, onRetry: load);
    if (stats == null) return const LoadingPanel();
    final data = stats!;
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
                  ElevatedButton.icon(onPressed: widget.onCreateEvent, icon: const Icon(Icons.add), label: const Text('Create event')),
                ],
              ),
              const SizedBox(height: 24),
              LayoutBuilder(
                builder: (context, constraints) {
                  final columns = constraints.maxWidth >= 1100 ? 5 : constraints.maxWidth >= 620 ? 2 : 1;
                  final width = (constraints.maxWidth - (columns - 1) * 12) / columns;
                  final cards = [
                    StatCard(label: 'Total events', value: '${data.totalEvents}', icon: Icons.event_available_outlined, color: navy),
                    StatCard(label: 'Upcoming', value: '${data.upcomingEvents}', icon: Icons.calendar_month_outlined, color: teal),
                    StatCard(label: 'Pending review', value: '${data.pendingReviews}', icon: Icons.fact_check_outlined, color: gold),
                    StatCard(label: 'Certificates sent', value: '${data.certificatesSent}', icon: Icons.send_outlined, color: const Color(0xFF5F6CAF)),
                    StatCard(label: 'Compliance rate', value: '${data.complianceRate.toStringAsFixed(1)}%', icon: Icons.insights_outlined, color: const Color(0xFF248A52)),
                  ];
                  return Wrap(spacing: 12, runSpacing: 12, children: cards.map((card) => SizedBox(width: width, child: card)).toList());
                },
              ),
              if (charts != null) ...[
                const SizedBox(height: 24),
                LayoutBuilder(
                  builder: (context, constraints) {
                    final twoUp = constraints.maxWidth >= 900;
                    final width = twoUp ? (constraints.maxWidth - 12) / 2 : constraints.maxWidth;
                    return Wrap(
                      spacing: 12,
                      runSpacing: 12,
                      children: [
                        SizedBox(
                          width: width,
                          child: ChartCard(
                            title: 'Post-test score distribution',
                            child: SimpleBarChart(
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
                                labels: [
                                  for (final e in charts!.eventsCompliance)
                                    e.title.length > 14 ? '${e.title.substring(0, 12)}…' : e.title,
                                ],
                                values: charts!.eventsCompliance.map((e) => e.eligible.toDouble()).toList(),
                                color: const Color(0xFF248A52),
                              ),
                            ),
                          ),
                      ],
                    );
                  },
                ),
              ],
              const SizedBox(height: 24),
              Card(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Padding(
                      padding: const EdgeInsets.all(20),
                      child: Row(
                        children: [
                          const Expanded(child: Text('Recent events', style: TextStyle(fontSize: 17, fontWeight: FontWeight.w700))),
                          TextButton(onPressed: widget.onOpenEvents, child: const Text('View all')),
                        ],
                      ),
                    ),
                    divider,
                    if (events.isEmpty)
                      const Padding(padding: EdgeInsets.all(32), child: Text('No events yet. Create the first training event.'))
                    else
                      SingleChildScrollView(
                        scrollDirection: Axis.horizontal,
                        child: DataTable(
                          columns: const [
                            DataColumn(label: Text('Event')),
                            DataColumn(label: Text('Date')),
                            DataColumn(label: Text('CEU hours')),
                            DataColumn(label: Text('Presenter')),
                            DataColumn(label: Text('Status')),
                          ],
                          rows: events
                              .map(
                                (event) => DataRow(
                                  cells: [
                                    DataCell(SizedBox(width: 260, child: Text(event.title, style: const TextStyle(fontWeight: FontWeight.w600)))),
                                    DataCell(Text(DateFormat.yMMMd().format(event.eventDate))),
                                    DataCell(Text(event.ceuHours.toStringAsFixed(1))),
                                    DataCell(Text(event.presenterName ?? 'Not assigned')),
                                    DataCell(StatusBadge(event.status.toUpperCase(), tone: event.status == 'review' ? BadgeTone.warning : BadgeTone.info)),
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

