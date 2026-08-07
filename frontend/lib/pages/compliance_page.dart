import 'package:flutter/material.dart';

import '../core/api_client.dart';
import '../core/session.dart';
import '../models/models.dart';
import '../widgets/common.dart';
import '../widgets/portal_table.dart';

class CompliancePage extends StatefulWidget {
  const CompliancePage({super.key, required this.session, required this.event});
  final SessionController session;
  final TrainingEvent event;

  @override
  State<CompliancePage> createState() => _CompliancePageState();
}

class _CompliancePageState extends State<CompliancePage> with LatestRequest {
  List<ComplianceRecord>? records;
  final selected = <int>{};
  final search = TextEditingController();
  // Lives with the page rather than with the dialog: disposing it as the
  // dialog pops tears the controller out from under a TextField that is still
  // rebuilding through the exit animation.
  final removalReason = TextEditingController();
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
    removalReason.dispose();
    super.dispose();
  }

  /// Whether the attendee is holding a certificate already — emailed to them,
  /// or downloaded by them from the public portal. Either way its number is
  /// live in the verification portal, so removing them revokes a real
  /// credential and needs the explicit override. Mirrors `_already_issued`
  /// on the backend; keep the two in step.
  static bool _certificateReachedHolder(ComplianceRecord record) =>
      record.certificateSentAt != null || record.certificateDownloadedAt != null;

  /// Shows a failure and speaks it. Every bulk action here is destructive or
  /// irreversible, so a silently-rendered red banner is not good enough: a
  /// screen reader user who presses "Remove all" needs to hear why it didn't
  /// happen, not discover it later.
  void _fail(Object exception) {
    if (!mounted) return;
    final message = humanizeError(exception);
    setState(() => error = message);
    announceToScreenReader(context, message);
  }

  Future<void> load() async {
    if (!mounted) return;
    // Both filters reload, so two changes in quick succession leave two reads
    // in flight and the slower one would otherwise repaint the roster to match
    // a filter the admin has already moved off.
    final request = beginRequest();
    setState(() {
      error = null;
      records = null;
    });
    try {
      final params = <String>[];
      if (filter != 'all') params.add('eligibility=${Uri.encodeQueryComponent(filter)}');
      if (search.text.trim().isNotEmpty) params.add('search=${Uri.encodeQueryComponent(search.text.trim())}');
      final result = await widget.session.api.get('/events/${widget.event.id}/compliance${params.isEmpty ? '' : '?${params.join('&')}'}') as List;
      if (request.isCurrent) {
        setState(() {
          records = result.map((item) => ComplianceRecord.fromJson(item as Map<String, dynamic>)).toList();
          selected.removeWhere((id) => !records!.any((record) => record.id == id));
        });
      }
    } catch (exception) {
      if (request.isCurrent) _fail(exception);
    }
  }

  Future<void> approve() async {
    if (selected.isEmpty) return;
    // Approving someone who doesn't meet the requirements is allowed for
    // admins, but only after an explicit, per-name confirmation.
    final ineligible = records!.where((r) => selected.contains(r.id) && !r.eligible).toList();
    if (ineligible.isNotEmpty) {
      final theme = Theme.of(context);
      final confirmed = await showDialog<bool>(
        context: context,
        builder: (context) => AlertDialog(
          title: const Text('Approve without eligibility?'),
          content: SizedBox(
            width: 420,
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text('These attendees do not meet the requirements. Approving them anyway is recorded in the audit log:'),
                const SizedBox(height: Space.xs + 2),
                for (final record in ineligible)
                  Padding(
                    padding: const EdgeInsets.only(bottom: Space.xxs + 2),
                    child: Text(
                      '• ${record.fullName} — ${record.reasons.join(', ')}',
                      style: theme.textTheme.bodySmall?.copyWith(color: theme.portal.danger),
                    ),
                  ),
              ],
            ),
          ),
          actions: [
            TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Cancel')),
            ElevatedButton(onPressed: () => Navigator.pop(context, true), child: const Text('Approve anyway')),
          ],
        ),
      );
      if (confirmed != true) return;
    }
    setState(() => working = true);
    try {
      await widget.session.api.post('/events/${widget.event.id}/compliance/approve', {
        'event_attendee_ids': selected.toList(),
        'approved': true,
        if (ineligible.isNotEmpty) 'override': true,
      });
      selected.clear();
      await load();
    } catch (exception) {
      if (mounted) _fail(exception);
    } finally {
      if (mounted) setState(() => working = false);
    }
  }

  // Sending certificates is real email, so the bulk action confirms with the
  // exact recipient count before anything goes out.
  Future<void> confirmSendAll() async {
    final pending = (records ?? const <ComplianceRecord>[])
        .where((record) => record.certificateNumber != null && record.certificateSentAt == null)
        .length;
    if (pending == 0) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('No generated certificates are waiting to be emailed.')),
      );
      return;
    }
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('Send certificates?'),
        content: Text('Email certificates to $pending attendee${pending == 1 ? '' : 's'}?'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(dialogContext, false), child: const Text('Cancel')),
          ElevatedButton(onPressed: () => Navigator.pop(dialogContext, true), child: const Text('Send')),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    await bulk('send-all', 'Send all');
  }

  // Undo an approval that hasn't produced a sent certificate yet, e.g. after
  // approving the wrong person.
  Future<void> revoke(ComplianceRecord record) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: Text('Revoke approval for ${record.fullName}?'),
        content: const SizedBox(
          width: 420,
          child: Text('They move back into the review queue, and no certificate will be sent until they are approved again.'),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(dialogContext, false), child: const Text('Cancel')),
          ElevatedButton(
            style: ElevatedButton.styleFrom(
              backgroundColor: Theme.of(context).portal.danger,
              foregroundColor: Colors.white,
            ),
            onPressed: () => Navigator.pop(dialogContext, true),
            child: const Text('Revoke approval'),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    setState(() => working = true);
    try {
      await widget.session.api.post('/events/${widget.event.id}/compliance/approve', {
        'event_attendee_ids': [record.id],
        'approved': false,
      });
      await load();
    } catch (exception) {
      if (mounted) _fail(exception);
    } finally {
      if (mounted) setState(() => working = false);
    }
  }

  /// Takes one person off this event's roster — the fix for a name that was
  /// read off the wrong sheet, or that a pre-scoping upload merged in from
  /// another event. Their certificate and this event's test/survey results go
  /// with them; they stay on every other event they attended.
  ///
  /// Unless the certificate already reached them, in which case it is revoked
  /// rather than deleted: the record is kept for seven years under the CEU
  /// retention commitment, and the number publicly verifies as revoked from
  /// then on. The dialog has to say that plainly, because it is permanent and
  /// anyone holding the PDF will see it.
  Future<void> remove(ComplianceRecord record) async {
    final theme = Theme.of(context);
    final alreadyIssued = _certificateReachedHolder(record);
    removalReason.clear();
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: Text(
          alreadyIssued
              ? 'Remove ${record.fullName} and revoke their certificate?'
              : 'Remove ${record.fullName} from this event?',
        ),
        content: SizedBox(
          width: 460,
          child: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  'They come off this event only — other events they attended are unchanged.',
                ),
                const SizedBox(height: Space.xs + 2),
                Text(
                  'Their post-test score and survey response for this event go too. Uploading the '
                  'sign-in sheet again brings the person back, but not those results.',
                  style: theme.textTheme.bodySmall?.copyWith(color: theme.portal.textSecondary),
                ),
                if (alreadyIssued) ...[
                  const SizedBox(height: Space.md),
                  Text(
                    record.certificateSentAt != null
                        ? 'Their certificate was already emailed, so it is revoked rather than deleted.'
                        : 'They already downloaded their certificate, so it is revoked rather than deleted.',
                    style: theme.textTheme.bodyMedium
                        ?.copyWith(color: theme.portal.danger, fontWeight: FontWeight.w600),
                  ),
                  const SizedBox(height: Space.xs),
                  Text(
                    'The certificate record is kept for seven years under our CEU retention '
                    'commitment — it is not deleted. From now on the certificate number verifies '
                    'publicly as REVOKED, which is what anyone holding the PDF will be shown. '
                    'This cannot be undone, and the certificate cannot be re-issued or re-sent.',
                    style: theme.textTheme.bodySmall?.copyWith(color: theme.portal.textSecondary),
                  ),
                  const SizedBox(height: Space.md),
                  TextField(
                    controller: removalReason,
                    maxLength: 500,
                    minLines: 1,
                    maxLines: 3,
                    decoration: const InputDecoration(
                      labelText: 'Reason (optional)',
                      helperText: 'Recorded on the certificate and in the audit log.',
                      hintText: 'e.g. name read off the wrong sign-in sheet',
                    ),
                  ),
                ],
              ],
            ),
          ),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(dialogContext, false), child: const Text('Cancel')),
          ElevatedButton(
            style: ElevatedButton.styleFrom(
              backgroundColor: Theme.of(context).portal.danger,
              foregroundColor: Colors.white,
            ),
            onPressed: () => Navigator.pop(dialogContext, true),
            child: Text(alreadyIssued ? 'Revoke and remove' : 'Remove attendee'),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    final note = removalReason.text.trim();
    final messenger = ScaffoldMessenger.of(context);
    setState(() => working = true);
    try {
      // The dialog already spelled out the consequence, so an explicitly named
      // attendee is removed even when their certificate reached them.
      final query = <String>[
        if (alreadyIssued) 'include_sent=true',
        if (alreadyIssued && note.isNotEmpty) 'reason=${Uri.encodeQueryComponent(note)}',
      ];
      final result = await widget.session.api.delete(
        '/events/${widget.event.id}/compliance/${record.id}'
        '${query.isEmpty ? '' : '?${query.join('&')}'}',
      ) as Map<String, dynamic>;
      if (!mounted) return;
      // Revoked and removed are different outcomes and the admin has to be
      // told which one they got: one destroyed a record, the other kept it.
      final wasRevoked = ((result['revoked'] as List?) ?? const []).isNotEmpty;
      final message = wasRevoked
          ? '${record.fullName} removed. Their certificate is revoked and now verifies '
              'publicly as revoked; the record is kept.'
          : '${record.fullName} removed from this event.';
      messenger.showSnackBar(
        SnackBar(content: Text(message), duration: Duration(seconds: wasRevoked ? 8 : 4)),
      );
      announceToScreenReader(context, message);
      await load();
    } catch (exception) {
      if (!mounted) return;
      _fail(exception);
      // A 409 means the server knows about a delivered certificate this row
      // didn't: reload so the retry shows the red warning and sends the
      // override instead of repeating the identical, always-rejected request.
      if (exception is ApiException && exception.statusCode == 409) await load();
    } finally {
      if (mounted) setState(() => working = false);
    }
  }

  /// Empties the roster. The repair for an event showing the wrong people:
  /// clear it, then upload that event's sign-in sheet again to rebuild it.
  Future<void> removeAll() async {
    final theme = Theme.of(context);
    final messenger = ScaffoldMessenger.of(context);
    // `records` holds a server-filtered view; this clears the WHOLE roster, so
    // every number in the dialog has to come from an unfiltered read. Counting
    // the visible rows would understate how many live certificates the
    // override revokes.
    final List<ComplianceRecord> all;
    setState(() => working = true);
    try {
      final result = await widget.session.api.get('/events/${widget.event.id}/compliance') as List;
      all = result.map((item) => ComplianceRecord.fromJson(item as Map<String, dynamic>)).toList();
    } catch (exception) {
      if (mounted) _fail(exception);
      return;
    } finally {
      if (mounted) setState(() => working = false);
    }
    if (!mounted) return;
    if (all.isEmpty) {
      messenger.showSnackBar(
        const SnackBar(content: Text('There are no attendees on this event to remove.')),
      );
      return;
    }
    // The filters narrow what's on screen, but this clears the whole roster —
    // say so plainly rather than letting the visible count imply otherwise.
    final filtered = filter != 'all' || search.text.trim().isNotEmpty;
    // Already-revoked rows are not offered again: there is nothing left to
    // revoke, and their row is retained whatever the admin ticks.
    final sentCount = all
        .where((record) => _certificateReachedHolder(record) && !record.certificateRevoked)
        .length;
    var includeSent = false;
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => StatefulBuilder(
        builder: (dialogContext, setDialogState) => AlertDialog(
          title: const Text('Remove all attendees?'),
          content: SizedBox(
            width: 460,
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'Every attendee on "${widget.event.title}" is taken off the roster, along with '
                  'their certificates and this event\'s test and survey results. This cannot be undone.',
                ),
                if (filtered) ...[
                  const SizedBox(height: Space.xs + 2),
                  Text(
                    'The whole roster is cleared, not just the rows matching the current filter.',
                    style: theme.textTheme.bodySmall
                        ?.copyWith(color: theme.portal.warning, fontWeight: FontWeight.w600),
                  ),
                ],
                const SizedBox(height: Space.xs + 2),
                Text(
                  'Upload this event\'s sign-in sheet again afterwards to rebuild the roster from the file alone.',
                  style: theme.textTheme.bodySmall?.copyWith(color: theme.portal.textSecondary),
                ),
                if (sentCount > 0) ...[
                  const SizedBox(height: Space.xxs + 2),
                  CheckboxListTile(
                    contentPadding: EdgeInsets.zero,
                    controlAffinity: ListTileControlAffinity.leading,
                    dense: true,
                    value: includeSent,
                    onChanged: (value) => setDialogState(() => includeSent = value ?? false),
                    title: Text(
                      'Also revoke the certificate${sentCount == 1 ? '' : 's'} of the $sentCount '
                      'attendee${sentCount == 1 ? '' : 's'} who already has one',
                      style: theme.textTheme.bodySmall?.copyWith(color: theme.portal.danger),
                    ),
                    subtitle: Text(
                      'Those certificates are revoked, not deleted: the records are kept for seven '
                      'years and the numbers verify publicly as REVOKED from then on. This cannot '
                      'be undone. Left unchecked, they stay on the roster untouched.',
                      style: theme.textTheme.labelMedium?.copyWith(
                        color: theme.portal.textSecondary,
                        fontWeight: FontWeight.w400,
                      ),
                    ),
                  ),
                ],
              ],
            ),
          ),
          actions: [
            TextButton(onPressed: () => Navigator.pop(dialogContext, false), child: const Text('Cancel')),
            ElevatedButton(
              style: ElevatedButton.styleFrom(
              backgroundColor: Theme.of(context).portal.danger,
              foregroundColor: Colors.white,
            ),
              onPressed: () => Navigator.pop(dialogContext, true),
              child: const Text('Remove all'),
            ),
          ],
        ),
      ),
    );
    if (confirmed != true || !mounted) return;
    setState(() => working = true);
    try {
      final result = await widget.session.api.delete(
        '/events/${widget.event.id}/compliance${includeSent ? '?include_sent=true' : ''}',
      ) as Map<String, dynamic>;
      if (!mounted) return;
      final removed = result['removed'] ?? 0;
      final kept = ((result['kept_with_issued_certificates'] as List?) ?? const []).length;
      final revoked = ((result['revoked'] as List?) ?? const []).length;
      // Three outcomes, and they are not interchangeable: removed is gone,
      // revoked is kept-but-withdrawn, kept is untouched.
      final message = '$removed attendee${removed == 1 ? '' : 's'} removed.'
          '${revoked == 0 ? '' : ' $revoked certificate${revoked == 1 ? '' : 's'} revoked — '
              'those records are kept and now verify publicly as revoked.'}'
          '${kept == 0 ? '' : ' $kept kept — they already have their certificates.'}';
      messenger.showSnackBar(SnackBar(
        content: Text(message),
        duration: Duration(seconds: kept == 0 && revoked == 0 ? 4 : 8),
      ));
      announceToScreenReader(context, message);
      selected.clear();
      await load();
    } catch (exception) {
      if (mounted) _fail(exception);
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
      if (mounted) _fail(exception);
    } finally {
      if (mounted) setState(() => working = false);
    }
  }

  /// An icon-only requirement column that still has a name.
  ///
  /// Four words would not fit side by side at this width, but an unnamed glyph
  /// announces as nothing at all — so the icon carries the label in semantics
  /// and in a tooltip. Sortable on the underlying fact, which is how an admin
  /// pulls "everyone still missing the survey" to the top of a 200-row roster.
  TableColumn<ComplianceRecord> _requirementColumn({
    required IconData icon,
    required String label,
    required String tooltip,
    required Object? Function(ComplianceRecord) sortValue,
    required Widget Function(BuildContext, ComplianceRecord) cell,
    double width = 76,
  }) {
    return TableColumn<ComplianceRecord>(
      label: '',
      headerIcon: icon,
      semanticLabel: label,
      tooltip: tooltip,
      width: width,
      sortValue: sortValue,
      cell: cell,
    );
  }

  List<TableColumn<ComplianceRecord>> _columns(BuildContext context, bool isAdmin) {
    final theme = Theme.of(context);
    final colors = theme.portal;
    return [
      TableColumn<ComplianceRecord>(
        label: 'Attendee',
        // The widest column and the only one worth giving a big screen to; the
        // rest are badges and glyphs that gain nothing from extra room.
        width: 240,
        flex: 1,
        sortValue: (record) => record.fullName,
        cell: (context, record) => Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              record.fullName,
              style: theme.textTheme.bodyMedium?.copyWith(fontWeight: FontWeight.w600),
            ),
            Text(
              record.email ?? 'No email',
              overflow: TextOverflow.ellipsis,
              style: theme.textTheme.labelMedium?.copyWith(
                color: colors.textTertiary,
                fontWeight: FontWeight.w400,
              ),
            ),
            if (record.reasons.isNotEmpty)
              Tooltip(
                message: record.reasons.join('\n'),
                child: Text(
                  record.reasons.join(' • '),
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: theme.textTheme.labelSmall?.copyWith(
                    color: colors.danger,
                    fontWeight: FontWeight.w400,
                  ),
                ),
              ),
          ],
        ),
      ),
      _requirementColumn(
        icon: Icons.event_available_outlined,
        label: 'Attended',
        tooltip: 'Attended the session',
        sortValue: (record) => record.attended,
        cell: (context, record) => CheckIcon(record.attended, label: 'Attended'),
      ),
      _requirementColumn(
        icon: Icons.quiz_outlined,
        label: 'Post-test passed',
        tooltip: 'Post-test passed (80% or higher)',
        width: 110,
        // Sorted on the score, not the pass flag: "who is closest to passing"
        // is the question a coordinator chasing retakes actually has.
        sortValue: (record) => record.testScore,
        cell: (context, record) => Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            CheckIcon(
              record.testCompleted && (record.testScore ?? 0) >= 80,
              label: 'Post-test passed',
            ),
            const SizedBox(width: Space.xxs + 1),
            Text(
              record.testScore == null ? '—' : '${record.testScore!.toStringAsFixed(0)}%',
              style: theme.textTheme.labelMedium?.copyWith(fontWeight: FontWeight.w400),
            ),
          ],
        ),
      ),
      _requirementColumn(
        icon: Icons.rate_review_outlined,
        label: 'Survey completed',
        tooltip: 'Survey completed',
        sortValue: (record) => record.surveyCompleted,
        cell: (context, record) =>
            CheckIcon(record.surveyCompleted, label: 'Survey completed'),
      ),
      _requirementColumn(
        icon: Icons.alternate_email,
        label: 'Valid email',
        tooltip: 'Valid email address on file',
        sortValue: (record) => record.validEmail,
        cell: (context, record) => CheckIcon(record.validEmail, label: 'Valid email'),
      ),
      TableColumn<ComplianceRecord>(
        label: 'Status',
        width: 160,
        sortValue: (record) => record.lifecycleStatus,
        cell: (context, record) => lifecycleBadge(record.lifecycleStatus),
      ),
      if (isAdmin)
        TableColumn<ComplianceRecord>(
          label: 'Actions',
          // Wide enough for both 48px icon buttons plus the cell padding: an
          // approved-but-unsent row carries "revoke approval" *and* "remove".
          width: 140,
          cell: (context, record) => Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              if (record.approved && record.certificateSentAt == null)
                IconButton(
                  tooltip: 'Revoke approval for ${record.fullName}',
                  onPressed: working ? null : () => revoke(record),
                  icon: Icon(Icons.undo, size: 18, color: colors.danger),
                ),
              // Already revoked: there is nothing left to remove — the row is
              // retained for seven years by design — so the action says why
              // instead of no-op'ing.
              IconButton(
                tooltip: record.certificateRevoked
                    ? '${record.fullName}\'s certificate is revoked. '
                        'The record is kept for seven years and cannot be removed.'
                    : 'Remove ${record.fullName} from this event',
                onPressed: working || record.certificateRevoked
                    ? null
                    : () => remove(record),
                icon: Icon(
                  Icons.person_remove_outlined,
                  size: 18,
                  color: colors.textSecondary,
                ),
              ),
            ],
          ),
        ),
    ];
  }

  @override
  Widget build(BuildContext context) {
    final isAdmin = widget.session.user!.isAdmin;
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
                  if (isAdmin) ...[
                    ElevatedButton.icon(
                      onPressed: selected.isEmpty || working ? null : approve,
                      icon: const Icon(Icons.verified_outlined),
                      label: Text('Approve selected (${selected.length})'),
                    ),
                    ActionMenu(
                      label: 'Bulk actions',
                      icon: const Icon(Icons.bolt_outlined),
                      enabled: !working,
                      actions: [
                        MenuAction('Approve all eligible', () => bulk('approve-all', 'Approve all eligible')),
                        MenuAction('Generate all approved', () => bulk('generate-all', 'Generate all')),
                        MenuAction('Send all generated', confirmSendAll),
                        null,
                        MenuAction('Remove all attendees', removeAll, destructive: true),
                      ],
                    ),
                  ],
                ],
              ),
              const SizedBox(height: Space.md + 2),
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
                    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [searchField, const SizedBox(height: Space.xs + 2), SingleChildScrollView(scrollDirection: Axis.horizontal, child: filters)]);
                  }
                  return Row(children: [Expanded(child: searchField), const SizedBox(width: Space.sm), filters]);
                },
              ),
              if (error != null) ...[
                const SizedBox(height: Space.xs + 2),
                InlineAlert(message: error!, onRetry: load, onDismiss: () => setState(() => error = null)),
              ],
              const SizedBox(height: Space.sm + 2),
              Expanded(
                child: Card(
                  child: PortalTable<ComplianceRecord>(
                    caption: 'Compliance roster',
                    columns: _columns(context, isAdmin),
                    rows: records,
                    loadingLabel: 'Loading compliance records',
                    emptyIcon: Icons.fact_check_outlined,
                    emptyMessage: 'No attendee records match this view',
                    emptyDetail: 'Upload the registration and attendance files, or '
                        'adjust the search and eligibility filters.',
                    // Paged, not virtualized. A roster is worked through name by
                    // name and then signed off, so "page 3 of 9" is the only
                    // honest answer to how much review is left — a bottomless
                    // scroll never gives one.
                    rowsPerPage: 25,
                    // Rows stack a name over an email over up to two lines of
                    // eligibility reasons, which is what the review is for.
                    density: TableDensity.comfortable,
                    // Alphabetical by default: this is a list people are looked
                    // up in, and the server's order is insertion order.
                    initialSortColumn: 0,
                    rowKey: (record) => record.id,
                    rowSemanticLabel: (record) => record.fullName,
                    // Admins can select ineligible rows too; approving them asks
                    // for an explicit override confirmation.
                    selectedKeys: isAdmin ? selected.cast<Object>() : null,
                    isSelectable: (record) => !record.approved,
                    onSelectChanged: (record, on) => setState(
                      () => on ? selected.add(record.id) : selected.remove(record.id),
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

