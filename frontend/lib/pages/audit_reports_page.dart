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
      if (mounted) setState(() => error = exception.toString());
    }
  }

  Future<void> exportAnnualReport() async {
    if (selectedColumns.isEmpty) {
      setState(() => error = 'Select at least one column to export.');
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
      if (mounted) setState(() => error = exception.toString());
    } finally {
      if (mounted) setState(() => exporting = false);
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
              PageHeader(
                title: 'Audit Reports',
                subtitle: 'Review material actions and export annual completion records.',
                actions: [
                  DropdownButton<int>(
                    value: year,
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
                const SizedBox(height: 10),
                Text(error!, style: const TextStyle(color: Color(0xFFB42318))),
              ],
              const SizedBox(height: 16),
              if (columns.isNotEmpty)
                Card(
                  child: Padding(
                    padding: const EdgeInsets.all(18),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        const Text('Report builder', style: TextStyle(fontSize: 15, fontWeight: FontWeight.w700)),
                        const SizedBox(height: 4),
                        const Text('Pick columns and filters, then export the annual CSV.',
                            style: TextStyle(fontSize: 13, color: Color(0xFF667085))),
                        const SizedBox(height: 12),
                        Wrap(
                          spacing: 8,
                          runSpacing: 8,
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
                        const SizedBox(height: 12),
                        Row(
                          children: [
                            const Text('Eligibility: ', style: TextStyle(color: Color(0xFF667085))),
                            const SizedBox(width: 8),
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
              const SizedBox(height: 16),
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(18),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Builder(
                        builder: (context) {
                          final themes = (insights?['common_themes'] as List?) ?? [];
                          return Wrap(
                            spacing: 12,
                            runSpacing: 12,
                            crossAxisAlignment: WrapCrossAlignment.center,
                            children: [
                              Text(
                                '${insights?['response_count'] ?? 0} survey responses',
                                style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w700),
                              ),
                              for (final theme in themes.take(8))
                                StatusBadge('${theme['theme']} (${theme['mentions']})', tone: BadgeTone.info),
                              if (themes.isEmpty)
                                const Text('Themes will appear as built-in survey responses are collected.'),
                            ],
                          );
                        },
                      ),
                      if (insights?['ai_summary'] != null) ...[
                        const SizedBox(height: 16),
                        const Divider(height: 1),
                        const SizedBox(height: 14),
                        Row(
                          children: const [
                            Icon(Icons.auto_awesome_outlined, size: 18, color: Color(0xFF5F6CAF)),
                            SizedBox(width: 6),
                            Text('AI summary across sessions', style: TextStyle(fontWeight: FontWeight.w700)),
                          ],
                        ),
                        const SizedBox(height: 8),
                        Text('${(insights!['ai_summary'] as Map)['executive_summary']}'),
                        const SizedBox(height: 12),
                        Wrap(
                          spacing: 8,
                          runSpacing: 8,
                          children: [
                            for (final theme in (((insights!['ai_summary'] as Map)['themes'] as List?) ?? []))
                              StatusBadge('${theme['theme']} (${theme['mentions']})', tone: BadgeTone.success),
                          ],
                        ),
                        for (final quote in (((insights!['ai_summary'] as Map)['representative_quotes'] as List?) ?? []))
                          Padding(
                            padding: const EdgeInsets.only(top: 8),
                            child: Text('“$quote”', style: const TextStyle(fontStyle: FontStyle.italic, color: Color(0xFF475467))),
                          ),
                      ],
                    ],
                  ),
                ),
              ),
              const SizedBox(height: 14),
              Expanded(
                child: Card(
                  child: logs == null
                      ? const LoadingPanel()
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
                                        DataCell(SizedBox(width: 330, child: Text(log['details'].toString(), maxLines: 2, overflow: TextOverflow.ellipsis))),
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
