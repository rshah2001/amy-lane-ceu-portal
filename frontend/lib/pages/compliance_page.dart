import 'package:flutter/material.dart';

import '../core/session.dart';
import '../models/models.dart';
import '../widgets/common.dart';

class CompliancePage extends StatefulWidget {
  const CompliancePage({super.key, required this.session, required this.event});
  final SessionController session;
  final TrainingEvent event;

  @override
  State<CompliancePage> createState() => _CompliancePageState();
}

class _CompliancePageState extends State<CompliancePage> {
  List<ComplianceRecord>? records;
  final selected = <int>{};
  final search = TextEditingController();
  String filter = 'all';
  String? error;
  bool working = false;

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
      error = null;
      records = null;
    });
    try {
      final params = <String>[];
      if (filter != 'all') params.add('eligibility=${Uri.encodeQueryComponent(filter)}');
      if (search.text.trim().isNotEmpty) params.add('search=${Uri.encodeQueryComponent(search.text.trim())}');
      final result = await widget.session.api.get('/events/${widget.event.id}/compliance${params.isEmpty ? '' : '?${params.join('&')}'}') as List;
      if (mounted) {
        setState(() {
          records = result.map((item) => ComplianceRecord.fromJson(item as Map<String, dynamic>)).toList();
          selected.removeWhere((id) => !records!.any((record) => record.id == id));
        });
      }
    } catch (exception) {
      if (mounted) setState(() => error = exception.toString());
    }
  }

  Future<void> approve() async {
    if (selected.isEmpty) return;
    setState(() => working = true);
    try {
      await widget.session.api.post('/events/${widget.event.id}/compliance/approve', {
        'event_attendee_ids': selected.toList(),
        'approved': true,
      });
      selected.clear();
      await load();
    } catch (exception) {
      if (mounted) setState(() => error = exception.toString());
    } finally {
      if (mounted) setState(() => working = false);
    }
  }

  Future<void> bulk(String action, String label) async {
    final messenger = ScaffoldMessenger.of(context);
    setState(() => working = true);
    try {
      final result = await widget.session.api.post('/events/${widget.event.id}/certificates/$action') as Map<String, dynamic>;
      messenger.showSnackBar(SnackBar(
        content: Text('$label: ${result['processed']} processed, ${result['skipped']} skipped, ${result['failed']} failed.'),
      ));
      await load();
    } catch (exception) {
      if (mounted) setState(() => error = exception.toString());
    } finally {
      if (mounted) setState(() => working = false);
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
                title: 'Compliance Review',
                subtitle: widget.event.title,
                actions: [
                  if (widget.session.user!.isAdmin) ...[
                    ElevatedButton.icon(
                      onPressed: selected.isEmpty || working ? null : approve,
                      icon: const Icon(Icons.verified_outlined),
                      label: Text('Approve selected (${selected.length})'),
                    ),
                    PopupMenuButton<String>(
                      enabled: !working,
                      onSelected: (value) => switch (value) {
                        'approve-all' => bulk('approve-all', 'Approve all eligible'),
                        'generate-all' => bulk('generate-all', 'Generate all'),
                        'send-all' => bulk('send-all', 'Send all'),
                        _ => Future<void>.value(),
                      },
                      itemBuilder: (context) => const [
                        PopupMenuItem(value: 'approve-all', child: Text('Approve all eligible')),
                        PopupMenuItem(value: 'generate-all', child: Text('Generate all approved')),
                        PopupMenuItem(value: 'send-all', child: Text('Send all generated')),
                      ],
                      child: IgnorePointer(
                        child: OutlinedButton.icon(
                          onPressed: () {},
                          icon: const Icon(Icons.bolt_outlined),
                          label: const Text('Bulk actions'),
                        ),
                      ),
                    ),
                  ],
                ],
              ),
              const SizedBox(height: 18),
              LayoutBuilder(
                builder: (context, constraints) {
                  final searchField = TextField(
                    controller: search,
                    onSubmitted: (_) => load(),
                    decoration: const InputDecoration(prefixIcon: Icon(Icons.search), hintText: 'Search attendee or email'),
                  );
                  final filters = SegmentedButton<String>(
                    segments: const [
                      ButtonSegment(value: 'all', label: Text('All')),
                      ButtonSegment(value: 'eligible', label: Text('Eligible')),
                      ButtonSegment(value: 'ineligible', label: Text('Ineligible')),
                    ],
                    selected: {filter},
                    onSelectionChanged: (value) {
                      setState(() => filter = value.first);
                      load();
                    },
                  );
                  if (constraints.maxWidth < 760) {
                    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [searchField, const SizedBox(height: 10), SingleChildScrollView(scrollDirection: Axis.horizontal, child: filters)]);
                  }
                  return Row(children: [Expanded(child: searchField), const SizedBox(width: 12), filters]);
                },
              ),
              if (error != null) ...[
                const SizedBox(height: 10),
                Text(error!, style: const TextStyle(color: Color(0xFFB42318))),
              ],
              const SizedBox(height: 14),
              Expanded(
                child: Card(
                  child: records == null
                      ? const LoadingPanel()
                      : records!.isEmpty
                          ? const Center(child: Text('No attendee records match this view.'))
                          : SingleChildScrollView(
                              child: SingleChildScrollView(
                                scrollDirection: Axis.horizontal,
                                child: DataTable(
                                  showCheckboxColumn: widget.session.user!.isAdmin,
                                  columns: const [
                                    DataColumn(label: Text('Attendee')),
                                    DataColumn(label: Text('Attendance')),
                                    DataColumn(label: Text('Post-test')),
                                    DataColumn(label: Text('Survey')),
                                    DataColumn(label: Text('Email')),
                                    DataColumn(label: Text('Decision')),
                                    DataColumn(label: Text('Lifecycle')),
                                    DataColumn(label: Text('Reasons')),
                                  ],
                                  rows: records!
                                      .map(
                                        (record) => DataRow(
                                          selected: selected.contains(record.id),
                                          onSelectChanged: !widget.session.user!.isAdmin || !record.eligible || record.approved
                                              ? null
                                              : (value) => setState(() => value == true ? selected.add(record.id) : selected.remove(record.id)),
                                          cells: [
                                            DataCell(
                                              SizedBox(
                                                width: 210,
                                                child: Column(
                                                  mainAxisAlignment: MainAxisAlignment.center,
                                                  crossAxisAlignment: CrossAxisAlignment.start,
                                                  children: [
                                                    Text(record.fullName, style: const TextStyle(fontWeight: FontWeight.w600)),
                                                    Text(record.email ?? 'No email', overflow: TextOverflow.ellipsis, style: const TextStyle(fontSize: 12, color: Color(0xFF667085))),
                                                  ],
                                                ),
                                              ),
                                            ),
                                            DataCell(checkIcon(record.attended)),
                                            DataCell(Row(mainAxisSize: MainAxisSize.min, children: [checkIcon(record.testCompleted && (record.testScore ?? 0) >= 80), const SizedBox(width: 5), Text(record.testScore == null ? '—' : '${record.testScore!.toStringAsFixed(0)}%')])),
                                            DataCell(checkIcon(record.surveyCompleted)),
                                            DataCell(checkIcon(record.validEmail)),
                                            DataCell(StatusBadge(record.approved ? 'APPROVED' : record.eligible ? 'ELIGIBLE' : 'INELIGIBLE', tone: record.approved || record.eligible ? BadgeTone.success : BadgeTone.danger)),
                                            DataCell(lifecycleBadge(record.lifecycleStatus)),
                                            DataCell(
                                              SizedBox(
                                                width: 270,
                                                child: Text(
                                                  record.reasons.isEmpty ? 'All eligibility requirements met' : record.reasons.join(' • '),
                                                  style: TextStyle(fontSize: 12, color: record.reasons.isEmpty ? const Color(0xFF176B3A) : const Color(0xFFB42318)),
                                                ),
                                              ),
                                            ),
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

