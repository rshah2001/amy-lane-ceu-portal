import 'package:flutter/material.dart';

import '../core/file_download.dart';
import '../core/session.dart';
import '../models/models.dart';
import '../widgets/common.dart';
import '../widgets/portal_table.dart';

class SurveyResponsesPage extends StatefulWidget {
  const SurveyResponsesPage({super.key, required this.session});
  final SessionController session;

  @override
  State<SurveyResponsesPage> createState() => _SurveyResponsesPageState();
}

class _SurveyResponsesPageState extends State<SurveyResponsesPage> with LatestRequest {
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
    // The event dropdown and the search box both reload; two changes in quick
    // succession leave two reads in flight, and the older one landing last
    // shows responses that don't match the filters on screen.
    final request = beginRequest();
    setState(() {
      responses = null;
      error = null;
    });
    try {
      final result = await widget.session.api.get('/survey-responses${_query()}') as List;
      if (request.isCurrent) setState(() => responses = result.cast<Map<String, dynamic>>());
    } catch (exception) {
      if (request.isCurrent) _fail(exception);
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

  /// How many submissions this person has for this event.
  ///
  /// The backend keeps every submission, so the same person can appear more
  /// than once; counting them lets a repeat be flagged as a repeat instead of
  /// reading as an accidental duplicate row.
  Map<String, int> get _submissionCounts {
    final counts = <String, int>{};
    for (final response in responses ?? const <Map<String, dynamic>>[]) {
      final key = _personEventKey(response);
      counts[key] = (counts[key] ?? 0) + 1;
    }
    return counts;
  }

  List<TableColumn<Map<String, dynamic>>> _columns(BuildContext context) {
    final theme = Theme.of(context);
    final counts = _submissionCounts;
    return [
      TableColumn<Map<String, dynamic>>(
        label: 'Respondent',
        width: 220,
        flex: 2,
        sortValue: (response) => response['full_name'] as String?,
        cell: (context, response) {
          final repeats = counts[_personEventKey(response)] ?? 1;
          return Row(
            children: [
              Flexible(
                child: Text(
                  response['full_name'] as String? ?? 'Anonymous',
                  overflow: TextOverflow.ellipsis,
                  style: theme.textTheme.bodyMedium?.copyWith(fontWeight: FontWeight.w600),
                ),
              ),
              if (repeats > 1) ...[
                const SizedBox(width: Space.xs),
                StatusBadge('$repeats SUBMISSIONS', tone: BadgeTone.warning),
              ],
            ],
          );
        },
      ),
      TableColumn<Map<String, dynamic>>(
        label: 'Event',
        width: 220,
        flex: 2,
        sortValue: (response) => response['event_title'] as String?,
        cell: (context, response) => Text(
          '${response['event_title']}',
          overflow: TextOverflow.ellipsis,
        ),
      ),
      TableColumn<Map<String, dynamic>>(
        label: 'Email',
        width: 220,
        flex: 1,
        sortValue: (response) => response['email'] as String?,
        cell: (context, response) => Text(
          response['email'] as String? ?? 'no email',
          overflow: TextOverflow.ellipsis,
          style: theme.textTheme.bodyMedium?.copyWith(
            color: response['email'] == null ? theme.portal.textTertiary : null,
          ),
        ),
      ),
      TableColumn<Map<String, dynamic>>(
        label: 'Business / location',
        width: 200,
        sortValue: (response) => (response['business_location'] as String?)?.trim(),
        cell: (context, response) => Text(
          (response['business_location'] as String?)?.trim().isEmpty ?? true
              ? '—'
              : (response['business_location'] as String).trim(),
          overflow: TextOverflow.ellipsis,
        ),
      ),
      TableColumn<Map<String, dynamic>>(
        label: 'Submitted',
        width: 190,
        // Sorted on the parsed instant rather than the formatted string.
        sortValue: (response) =>
            DateTime.tryParse(response['completed_at']?.toString() ?? ''),
        cell: (context, response) {
          final at = DateTime.tryParse(response['completed_at']?.toString() ?? '');
          return Text(at == null ? '—' : formatDateTime(at));
        },
      ),
    ];
  }

  /// The answer text, revealed under its row.
  Widget _answers(BuildContext context, Map<String, dynamic> response) {
    final theme = Theme.of(context);
    final colors = theme.portal;
    final answers = (response['answers'] as Map?)?.cast<String, dynamic>() ?? {};
    if (answers.isEmpty) {
      return Text(
        'No answer text recorded.',
        style: theme.textTheme.bodyMedium?.copyWith(color: colors.textSecondary),
      );
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
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
              // Only when there is a table to sit above: a failed load is
              // reported inside the table instead, where it comes with a Retry.
              if (error != null && responses != null) ...[
                const SizedBox(height: Space.xs + 2),
                FormErrorText(error!),
              ],
              const SizedBox(height: Space.sm + 2),
              Expanded(
                child: Card(
                  child: PortalTable<Map<String, dynamic>>(
                    caption: 'Survey responses',
                    columns: _columns(context),
                    rows: responses,
                    error: responses == null ? error : null,
                    onRetry: load,
                    loadingLabel: 'Loading survey responses',
                    emptyIcon: Icons.rate_review_outlined,
                    emptyMessage: 'No survey responses match this view',
                    emptyDetail: 'Responses appear here as attendees complete the '
                        'built-in feedback survey.',
                    // Paged. Responses are read one at a time — a row is opened,
                    // its answers are read, it is closed — which is a working
                    // rhythm, not a scan.
                    rowsPerPage: 25,
                    initialSortColumn: 4,
                    // Newest response first: the reason to open this page is
                    // almost always "what came in since I last looked".
                    initialSortAscending: false,
                    rowKey: (response) => response['id'] as Object,
                    rowSemanticLabel: (response) =>
                        response['full_name'] as String? ?? 'Anonymous response',
                    // The answers stay attached to their row rather than moving
                    // to a dialog: reading feedback means comparing one person's
                    // words against the next person's, and a modal breaks that.
                    expansionBuilder: _answers,
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

/// Identity of a submitter within one event, for spotting repeat submissions.
String _personEventKey(Map<String, dynamic> response) {
  final identity = (response['email'] ?? response['full_name'] ?? '').toString().trim().toLowerCase();
  // Anonymous submissions carry no identity; key them by row id so unrelated
  // anonymous responses are never flagged as repeats from one person.
  if (identity.isEmpty) return 'anonymous|${response['id']}';
  return '$identity|${response['event_id'] ?? response['event_title']}';
}
