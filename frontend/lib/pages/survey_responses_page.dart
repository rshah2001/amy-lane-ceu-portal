import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../core/file_download.dart';
import '../core/session.dart';
import '../models/models.dart';
import '../widgets/common.dart';

class SurveyResponsesPage extends StatefulWidget {
  const SurveyResponsesPage({super.key, required this.session});
  final SessionController session;

  @override
  State<SurveyResponsesPage> createState() => _SurveyResponsesPageState();
}

class _SurveyResponsesPageState extends State<SurveyResponsesPage> {
  List<TrainingEvent> events = [];
  List<Map<String, dynamic>>? responses;
  int? eventFilter;
  final search = TextEditingController();
  String? error;
  bool exporting = false;

  @override
  void initState() {
    super.initState();
    init();
  }

  @override
  void dispose() {
    search.dispose();
    super.dispose();
  }

  Future<void> init() async {
    try {
      final result = await widget.session.api.get('/events') as List;
      events = result.map((e) => TrainingEvent.fromJson(e as Map<String, dynamic>)).toList();
    } catch (_) {/* event dropdown is optional */}
    await load();
  }

  String _query() {
    final params = <String>[];
    if (eventFilter != null) params.add('event_id=$eventFilter');
    if (search.text.trim().isNotEmpty) params.add('search=${Uri.encodeQueryComponent(search.text.trim())}');
    return params.isEmpty ? '' : '?${params.join('&')}';
  }

  Future<void> load() async {
    setState(() {
      responses = null;
      error = null;
    });
    try {
      final result = await widget.session.api.get('/survey-responses${_query()}') as List;
      if (mounted) setState(() => responses = result.cast<Map<String, dynamic>>());
    } catch (exception) {
      if (mounted) setState(() => error = exception.toString());
    }
  }

  Future<void> export() async {
    setState(() => exporting = true);
    try {
      final bytes = await widget.session.api.download('/survey-responses.csv${_query()}');
      downloadBytes(bytes, 'survey_responses.csv', 'text/csv');
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
                title: 'Survey Responses',
                subtitle: 'Browse and export submitted feedback survey answers.',
                actions: [
                  ElevatedButton.icon(
                    onPressed: (responses == null || responses!.isEmpty || exporting) ? null : export,
                    icon: const Icon(Icons.download_outlined),
                    label: Text(exporting ? 'Exporting...' : 'Export CSV'),
                  ),
                ],
              ),
              const SizedBox(height: 16),
              LayoutBuilder(
                builder: (context, constraints) {
                  final searchField = TextField(
                    controller: search,
                    onSubmitted: (_) => load(),
                    decoration: const InputDecoration(prefixIcon: Icon(Icons.search), hintText: 'Search attendee or email'),
                  );
                  final eventDropdown = DropdownButtonFormField<int?>(
                    initialValue: eventFilter,
                    decoration: const InputDecoration(labelText: 'Event', prefixIcon: Icon(Icons.event_note_outlined)),
                    items: [
                      const DropdownMenuItem<int?>(value: null, child: Text('All events')),
                      for (final e in events) DropdownMenuItem<int?>(value: e.id, child: Text(e.title)),
                    ],
                    onChanged: (value) {
                      setState(() => eventFilter = value);
                      load();
                    },
                  );
                  if (constraints.maxWidth < 760) {
                    return Column(children: [eventDropdown, const SizedBox(height: 10), searchField]);
                  }
                  return Row(children: [Expanded(child: eventDropdown), const SizedBox(width: 12), Expanded(child: searchField)]);
                },
              ),
              if (error != null) ...[
                const SizedBox(height: 10),
                Text(error!, style: const TextStyle(color: Color(0xFFB42318))),
              ],
              const SizedBox(height: 14),
              Expanded(
                child: Card(
                  child: responses == null
                      ? const LoadingPanel()
                      : responses!.isEmpty
                          ? const Center(child: Text('No survey responses match this view.'))
                          : ListView.separated(
                              padding: const EdgeInsets.all(8),
                              itemCount: responses!.length,
                              separatorBuilder: (_, __) => divider,
                              itemBuilder: (context, index) => _ResponseTile(response: responses![index]),
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

class _ResponseTile extends StatelessWidget {
  const _ResponseTile({required this.response});
  final Map<String, dynamic> response;

  @override
  Widget build(BuildContext context) {
    final answers = (response['answers'] as Map?)?.cast<String, dynamic>() ?? {};
    final completed = DateTime.tryParse(response['completed_at']?.toString() ?? '');
    return ExpansionTile(
      shape: const Border(),
      collapsedShape: const Border(),
      title: Text(response['full_name'] as String, style: const TextStyle(fontWeight: FontWeight.w600)),
      subtitle: Text(
        '${response['event_title']}  ·  ${response['email'] ?? 'no email'}'
        '${completed == null ? '' : '  ·  ${DateFormat.yMMMd().format(completed.toLocal())}'}',
        style: const TextStyle(fontSize: 12, color: Color(0xFF667085)),
      ),
      childrenPadding: const EdgeInsets.fromLTRB(18, 0, 18, 14),
      expandedCrossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (answers.isEmpty)
          const Text('No answer text recorded.', style: TextStyle(color: Color(0xFF667085)))
        else
          for (final entry in answers.entries) ...[
            Text(entry.key, style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: Color(0xFF667085))),
            const SizedBox(height: 2),
            Text('${entry.value}'),
            const SizedBox(height: 10),
          ],
      ],
    );
  }
}
