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
      if (mounted) _fail(exception);
    }
  }

  void _fail(Object exception) {
    if (!mounted) return;
    final message = humanizeError(exception);
    setState(() => error = message);
    announceToScreenReader(context, message);
  }

  Future<void> export() async {
    setState(() => exporting = true);
    try {
      final bytes = await widget.session.api.download('/survey-responses.csv${_query()}');
      downloadBytes(bytes, 'survey_responses.csv', 'text/csv');
    } catch (exception) {
      if (mounted) _fail(exception);
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
              const SizedBox(height: Space.md),
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
                    return Column(children: [eventDropdown, const SizedBox(height: Space.xs + 2), searchField]);
                  }
                  return Row(children: [Expanded(child: eventDropdown), const SizedBox(width: Space.sm), Expanded(child: searchField)]);
                },
              ),
              if (error != null) ...[
                const SizedBox(height: Space.xs + 2),
                FormErrorText(error!),
              ],
              const SizedBox(height: Space.sm + 2),
              Expanded(
                child: Card(
                  child: responses == null
                      ? const LoadingPanel(label: 'Loading survey responses')
                      : responses!.isEmpty
                          ? const EmptyState(
                              icon: Icons.rate_review_outlined,
                              message: 'No survey responses match this view',
                              detail: 'Responses appear here as attendees complete the built-in feedback survey.',
                            )
                          : Builder(builder: (context) {
                              // The backend keeps every submission, so the same
                              // person can appear more than once; count them so
                              // repeats are visibly flagged instead of looking
                              // like accidental duplicates.
                              final submissionCounts = <String, int>{};
                              for (final response in responses!) {
                                final key = _personEventKey(response);
                                submissionCounts[key] = (submissionCounts[key] ?? 0) + 1;
                              }
                              return ListView.separated(
                                padding: const EdgeInsets.all(Space.xs),
                                itemCount: responses!.length,
                                separatorBuilder: (_, __) => divider,
                                itemBuilder: (context, index) => _ResponseTile(
                                  response: responses![index],
                                  submissionCount: submissionCounts[_personEventKey(responses![index])] ?? 1,
                                ),
                              );
                            }),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// Identity of a submitter within one event, for spotting repeat submissions.
String _personEventKey(Map<String, dynamic> response) {
  final identity = (response['email'] ?? response['full_name'] ?? '').toString().trim().toLowerCase();
  // Anonymous submissions carry no identity; key them by row id so unrelated
  // anonymous responses are never flagged as repeats from one person.
  if (identity.isEmpty) return 'anonymous|${response['id']}';
  return '$identity|${response['event_id'] ?? response['event_title']}';
}

class _ResponseTile extends StatelessWidget {
  const _ResponseTile({required this.response, this.submissionCount = 1});
  final Map<String, dynamic> response;

  /// How many submissions this person has for this event (1 = no repeats).
  final int submissionCount;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final colors = theme.portal;
    final answers = (response['answers'] as Map?)?.cast<String, dynamic>() ?? {};
    final completed = DateTime.tryParse(response['completed_at']?.toString() ?? '')?.toLocal();
    final businessLocation = (response['business_location'] as String?)?.trim() ?? '';
    return ExpansionTile(
      shape: const Border(),
      collapsedShape: const Border(),
      title: Row(
        children: [
          Flexible(
            child: Text(
              response['full_name'] as String? ?? 'Anonymous',
              style: theme.textTheme.bodyMedium?.copyWith(fontWeight: FontWeight.w600),
            ),
          ),
          if (submissionCount > 1) ...[
            const SizedBox(width: Space.xs),
            StatusBadge('$submissionCount SUBMISSIONS', tone: BadgeTone.warning),
          ],
        ],
      ),
      subtitle: Text(
        '${response['event_title']}  ·  ${response['email'] ?? 'no email'}'
        '${businessLocation.isEmpty ? '' : '  ·  $businessLocation'}'
        '${completed == null ? '' : '  ·  ${DateFormat.yMMMd().format(completed)} · ${DateFormat.jm().format(completed)}'}',
        style: theme.textTheme.labelMedium?.copyWith(
          color: colors.textSecondary,
          fontWeight: FontWeight.w400,
        ),
      ),
      childrenPadding: const EdgeInsets.fromLTRB(Space.md + 2, 0, Space.md + 2, Space.sm + 2),
      // Both are needed: without expandedAlignment the answers Column
      // shrink-wraps and floats to the center of the tile.
      expandedAlignment: Alignment.topLeft,
      expandedCrossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (answers.isEmpty)
          Text(
            'No answer text recorded.',
            style: theme.textTheme.bodyMedium?.copyWith(color: colors.textSecondary),
          )
        else
          for (final entry in answers.entries) ...[
            Text(
              entry.key,
              style: theme.textTheme.labelMedium?.copyWith(
                color: colors.textSecondary,
                fontWeight: FontWeight.w700,
              ),
            ),
            const SizedBox(height: 2),
            Text('${entry.value}'),
            const SizedBox(height: Space.xs + 2),
          ],
      ],
    );
  }
}
