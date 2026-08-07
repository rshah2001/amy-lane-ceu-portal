import 'dart:async';

import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../core/file_download.dart';
import '../core/session.dart';
import '../widgets/common.dart';
import '../widgets/portal_table.dart';

class AuditReportsPage extends StatefulWidget {
  const AuditReportsPage({super.key, required this.session});
  final SessionController session;

  @override
  State<AuditReportsPage> createState() => _AuditReportsPageState();
}

class _AuditReportsPageState extends State<AuditReportsPage> with LatestRequest {
  List<Map<String, dynamic>>? logs;
  Map<String, dynamic>? insights;
  List<Map<String, dynamic>> columns = [];
  Map<int, String> actorNames = {};
  Map<int, String> eventTitles = {};
  final Set<String> selectedColumns = {};
  String reportEligibility = 'all';
  String? error;
  int year = DateTime.now().year;
  bool exporting = false;

  @override
  void initState() {
    super.initState();
    load();
  }

  Future<void> load() async {
    // Retry can be pressed while the first attempt is still out; without the
    // guard the two sets of results race and the log can end up older than the
    // one it replaced.
    final request = beginRequest();
    try {
      final results = await Future.wait([
        widget.session.api.get('/audit-logs?limit=300'),
        widget.session.api.get('/survey-insights'),
        widget.session.api.get('/reports/columns'),
      ]);
      // Names for the actor and event ids the log stores are an enrichment,
      // never a dependency: the log has to render even if these fail, because
      // an audit trail that won't display because an unrelated endpoint is
      // down is worse than one showing bare ids. Loaded separately from the
      // Future.wait above so a failure here cannot take the page with it.
      unawaited(_loadLabels(request));
      if (request.isCurrent) {
        setState(() {
          logs = (results[0] as List).cast<Map<String, dynamic>>();
          insights = results[1] as Map<String, dynamic>;
          columns = (results[2] as List).cast<Map<String, dynamic>>();
          if (selectedColumns.isEmpty) {
            selectedColumns.addAll(columns.map((c) => c['key'] as String));
          }
          error = null;
        });
      }
    } catch (exception) {
      if (request.isCurrent) _fail(exception);
    }
  }

  /// Best-effort id-to-name lookups for the log table. Silent on failure by
  /// design: the columns fall back to "Event #12" / "User #7", which is what
  /// the page showed before and still identifies the row.
  Future<void> _loadLabels(RequestToken request) async {
    try {
      final results = await Future.wait([
        widget.session.api.get('/users'),
        widget.session.api.get('/events'),
      ]);
      if (!request.isCurrent) return;
      setState(() {
        actorNames = {
          for (final user in (results[0] as List).cast<Map<String, dynamic>>())
            user['id'] as int: (user['full_name'] as String?) ?? user['email'] as String,
        };
        eventTitles = {
          for (final event in (results[1] as List).cast<Map<String, dynamic>>())
            event['id'] as int: event['title'] as String,
        };
      });
    } catch (_) {
      // Deliberately swallowed — see the doc comment.
    }
  }

  void _fail(Object exception) {
    if (!mounted) return;
    final message = humanizeError(exception);
    setState(() => error = message);
    announceToScreenReader(context, message);
  }

  Future<void> exportAnnualReport() async {
    if (selectedColumns.isEmpty) {
      const message = 'Select at least one column to export.';
      setState(() => error = message);
      announceToScreenReader(context, message);
      return;
    }
    setState(() => exporting = true);
    try {
      final params = <String>[
        // preserve the registry order rather than set iteration order
        'columns=${Uri.encodeQueryComponent(columns.map((c) => c['key'] as String).where(selectedColumns.contains).join(','))}',
      ];
      if (reportEligibility != 'all') params.add('eligibility=$reportEligibility');
      final bytes = await widget.session.api.download('/reports/annual/$year?${params.join('&')}');
      downloadBytes(bytes, 'ceu-annual-report-$year.csv', 'text/csv');
    } catch (exception) {
      if (mounted) _fail(exception);
    } finally {
      if (mounted) setState(() => exporting = false);
    }
  }

  /// Reads the log's timestamp, which every column here is ordered against.
  static DateTime? _timestamp(Map<String, dynamic> log) =>
      DateTime.tryParse(log['created_at']?.toString() ?? '');

  List<TableColumn<Map<String, dynamic>>> _columns() => [
        TableColumn<Map<String, dynamic>>(
          label: 'Timestamp',
          width: 180,
          // Sorted on the parsed instant, not the rendered string — "7/9/2026"
          // sorts before "12/1/2025" as text.
          sortValue: _timestamp,
          cell: (context, log) {
            final at = _timestamp(log);
            return Text(at == null ? '—' : DateFormat.yMd().add_jm().format(at.toLocal()));
          },
        ),
        TableColumn<Map<String, dynamic>>(
          label: 'Action',
          width: 230,
          sortValue: (log) => log['action']?.toString(),
          cell: (context, log) => StatusBadge(
            (log['action'] as String).replaceAll('.', ' ').toUpperCase(),
            tone: BadgeTone.info,
          ),
        ),
        TableColumn<Map<String, dynamic>>(
          label: 'Entity',
          width: 170,
          sortValue: (log) => log['entity_type']?.toString(),
          cell: (context, log) => Text('${log['entity_type']} #${log['entity_id'] ?? '—'}'),
        ),
        TableColumn<Map<String, dynamic>>(
          label: 'Event',
          width: 200,
          sortValue: _eventLabel,
          cell: (context, log) => Text(_eventLabel(log), overflow: TextOverflow.ellipsis),
        ),
        TableColumn<Map<String, dynamic>>(
          label: 'Who',
          width: 180,
          sortValue: _actorLabel,
          cell: (context, log) => Text(_actorLabel(log), overflow: TextOverflow.ellipsis),
        ),
        TableColumn<Map<String, dynamic>>(
          label: 'Details',
          width: 330,
          // The one column worth spending a wide screen on.
          flex: 1,
          sortValue: _detailsLabel,
          cell: (context, log) => Text(
            _detailsLabel(log),
            maxLines: 2,
            overflow: TextOverflow.ellipsis,
          ),
        ),
      ];

  /// "Spring Refresher (#12)", or just the id when the event has since been
  /// deleted — which is exactly when an auditor most wants the row.
  String _eventLabel(Map<String, dynamic> log) {
    final id = log['event_id'] as int?;
    if (id == null) return '—';
    final title = eventTitles[id];
    return title == null ? 'Event #$id' : '$title (#$id)';
  }

  /// A person's name, or "System" for the unattended paths (public check-in,
  /// scheduled work) that legitimately have no actor.
  String _actorLabel(Map<String, dynamic> log) {
    final id = log['actor_id'] as int?;
    if (id == null) return 'System';
    return actorNames[id] ?? 'Deleted user #$id';
  }

  /// Renders the details map as prose rather than as a Dart Map literal.
  ///
  /// This column used to print `{attendee_id: 5, full_name: Bob Smith}` —
  /// syntax from the language the portal happens to be written in, in the one
  /// artifact that exists to be read by somebody outside the project.
  String _detailsLabel(Map<String, dynamic> log) {
    final details = log['details'];
    if (details is! Map || details.isEmpty) return '—';
    return details.entries
        .map((entry) => '${_humanizeKey(entry.key.toString())}: ${_formatValue(entry.value)}')
        .join(' · ');
  }

  static String _humanizeKey(String key) {
    final words = key.split('_').where((word) => word.isNotEmpty);
    if (words.isEmpty) return key;
    final first = words.first;
    return [
      first[0].toUpperCase() + first.substring(1),
      ...words.skip(1),
    ].join(' ');
  }

  static String _formatValue(Object? value) {
    if (value == null) return 'none';
    if (value is bool) return value ? 'yes' : 'no';
    if (value is List) return value.isEmpty ? 'none' : value.join(', ');
    if (value is Map) return value.entries.map((e) => '${e.key} ${e.value}').join(', ');
    return value.toString();
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final colors = theme.portal;
    return Padding(
      padding: pagePadding,
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: maxContentWidth),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              PageHeader(
                title: 'Audit Reports',
                subtitle: 'Review material actions and export annual completion records.',
                actions: [
                  DropdownButton<int>(
                    value: year,
                    // Announced as an unnamed combo box without this.
                    hint: const Text('Report year'),
                    items: [for (var value = DateTime.now().year; value >= DateTime.now().year - 7; value--) DropdownMenuItem(value: value, child: Text('$value'))],
                    onChanged: (value) => setState(() => year = value!),
                  ),
                  ElevatedButton.icon(
                    onPressed: exporting ? null : exportAnnualReport,
                    icon: const Icon(Icons.download_outlined),
                    label: Text(exporting ? 'Exporting...' : 'Export annual CSV'),
                  ),
                ],
              ),
              // Only when there is a table to sit above: a failed *load* is
              // reported inside the table instead, where it comes with a Retry.
              if (error != null && logs != null) ...[
                const SizedBox(height: Space.xs + 2),
                FormErrorText(error!),
              ],
              const SizedBox(height: Space.md),
              if (columns.isNotEmpty)
                Card(
                  child: Padding(
                    padding: const EdgeInsets.all(Space.md + 2),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        SectionTitle('Report builder', style: theme.textTheme.titleSmall),
                        const SizedBox(height: Space.xxs),
                        Text(
                          'Pick columns and filters, then export the annual CSV.',
                          style: theme.textTheme.bodySmall?.copyWith(color: colors.textSecondary),
                        ),
                        const SizedBox(height: Space.sm),
                        Wrap(
                          spacing: Space.xs,
                          runSpacing: Space.xs,
                          children: [
                            for (final column in columns)
                              FilterChip(
                                label: Text(column['label'] as String),
                                selected: selectedColumns.contains(column['key']),
                                onSelected: (on) => setState(() {
                                  on ? selectedColumns.add(column['key'] as String) : selectedColumns.remove(column['key']);
                                }),
                              ),
                          ],
                        ),
                        const SizedBox(height: Space.sm),
                        Row(
                          children: [
                            Text(
                              'Eligibility: ',
                              style: theme.textTheme.bodyMedium
                                  ?.copyWith(color: colors.textSecondary),
                            ),
                            const SizedBox(width: Space.xs),
                            SegmentedButton<String>(
                              segments: const [
                                ButtonSegment(value: 'all', label: Text('All')),
                                ButtonSegment(value: 'eligible', label: Text('Eligible')),
                                ButtonSegment(value: 'ineligible', label: Text('Ineligible')),
                              ],
                              selected: {reportEligibility},
                              onSelectionChanged: (v) => setState(() => reportEligibility = v.first),
                            ),
                          ],
                        ),
                      ],
                    ),
                  ),
                ),
              const SizedBox(height: Space.md),
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(Space.md + 2),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Builder(
                        builder: (context) {
                          final themes = (insights?['common_themes'] as List?) ?? [];
                          return Wrap(
                            spacing: Space.sm,
                            runSpacing: Space.sm,
                            crossAxisAlignment: WrapCrossAlignment.center,
                            children: [
                              SectionTitle('${insights?['response_count'] ?? 0} survey responses'),
                              for (final theme in themes.take(8))
                                StatusBadge('${theme['theme']} (${theme['mentions']})', tone: BadgeTone.info),
                              if (themes.isEmpty)
                                const Text('Themes will appear as built-in survey responses are collected.'),
                            ],
                          );
                        },
                      ),
                      if (insights?['ai_summary'] != null) ...[
                        const SizedBox(height: Space.md),
                        const Divider(height: 1),
                        const SizedBox(height: Space.sm + 2),
                        Row(
                          children: [
                            ExcludeSemantics(
                              child: Icon(Icons.auto_awesome_outlined, size: 18, color: colors.accentAlt),
                            ),
                            const SizedBox(width: Space.xxs + 2),
                            const SectionTitle('AI summary across sessions'),
                          ],
                        ),
                        const SizedBox(height: Space.xs),
                        Text('${(insights!['ai_summary'] as Map)['executive_summary']}'),
                        const SizedBox(height: Space.sm),
                        Wrap(
                          spacing: Space.xs,
                          runSpacing: Space.xs,
                          children: [
                            for (final theme in (((insights!['ai_summary'] as Map)['themes'] as List?) ?? []))
                              StatusBadge('${theme['theme']} (${theme['mentions']})', tone: BadgeTone.success),
                          ],
                        ),
                        for (final quote in (((insights!['ai_summary'] as Map)['representative_quotes'] as List?) ?? []))
                          Padding(
                            padding: const EdgeInsets.only(top: Space.xs),
                            child: Text(
                              '“$quote”',
                              style: theme.textTheme.bodyMedium?.copyWith(
                                fontStyle: FontStyle.italic,
                                color: colors.textSecondary,
                              ),
                            ),
                          ),
                      ],
                    ],
                  ),
                ),
              ),
              const SizedBox(height: Space.sm + 2),
              Expanded(
                child: Card(
                  child: PortalTable<Map<String, dynamic>>(
                    caption: 'Audit log',
                    columns: _columns(),
                    rows: logs,
                    error: logs == null ? error : null,
                    onRetry: load,
                    loadingLabel: 'Loading audit log',
                    emptyIcon: Icons.assessment_outlined,
                    emptyMessage: 'No audit log entries yet',
                    emptyDetail: 'Material actions such as uploads, approvals, and '
                        'certificate sends are recorded here.',
                    // Virtualized, not paged. This is a chronological stream
                    // that gets scanned and scrolled rather than worked through
                    // — chopping it into pages puts an arbitrary wall in the
                    // middle of the thing being read. All 300 rows used to be
                    // built eagerly; now only the visible ones are.
                    paging: TablePaging.virtualized,
                    // One line per entry, so more of the trail is in view.
                    density: TableDensity.compact,
                    // Newest first, which is what an audit trail is opened for.
                    initialSortColumn: 0,
                    initialSortAscending: false,
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
