import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../core/file_download.dart';
import '../core/session.dart';
import '../widgets/common.dart';

class AuditReportsPage extends StatefulWidget {
  const AuditReportsPage({super.key, required this.session});
  final SessionController session;

  @override
  State<AuditReportsPage> createState() => _AuditReportsPageState();
}

class _AuditReportsPageState extends State<AuditReportsPage> {
  List<Map<String, dynamic>>? logs;
  Map<String, dynamic>? insights;
  List<Map<String, dynamic>> columns = [];
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
    try {
      final results = await Future.wait([
        widget.session.api.get('/audit-logs?limit=300'),
        widget.session.api.get('/survey-insights'),
        widget.session.api.get('/reports/columns'),
      ]);
      if (mounted) {
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
      if (mounted) _fail(exception);
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
              if (error != null) ...[
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
                  child: logs == null
                      ? const LoadingPanel(label: 'Loading audit log')
                      : logs!.isEmpty
                          ? const EmptyState(
                              icon: Icons.assessment_outlined,
                              message: 'No audit log entries yet',
                              detail: 'Material actions such as uploads, approvals, and certificate sends are recorded here.',
                            )
                          : SingleChildScrollView(
                          child: SingleChildScrollView(
                            scrollDirection: Axis.horizontal,
                            child: DataTable(
                              columns: const [
                                DataColumn(label: Text('Timestamp')),
                                DataColumn(label: Text('Action')),
                                DataColumn(label: Text('Entity')),
                                DataColumn(label: Text('Event ID')),
                                DataColumn(label: Text('Actor ID')),
                                DataColumn(label: Text('Details')),
                              ],
                              rows: logs!
                                  .map(
                                    (log) => DataRow(
                                      cells: [
                                        DataCell(Text(DateFormat.yMd().add_jm().format(DateTime.parse(log['created_at'] as String).toLocal()))),
                                        DataCell(StatusBadge((log['action'] as String).replaceAll('.', ' ').toUpperCase(), tone: BadgeTone.info)),
                                        DataCell(Text('${log['entity_type']} #${log['entity_id'] ?? '—'}')),
                                        DataCell(Text('${log['event_id'] ?? '—'}')),
                                        DataCell(Text('${log['actor_id'] ?? 'system'}')),
                                        DataCell(ConstrainedBox(
                                          constraints: const BoxConstraints(minWidth: 330, maxWidth: 460),
                                          child: Text(log['details'].toString(), maxLines: 2, overflow: TextOverflow.ellipsis),
                                        )),
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
