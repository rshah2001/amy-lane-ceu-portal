import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:intl/intl.dart';
import 'package:url_launcher/url_launcher.dart';

import '../core/file_download.dart';
import '../core/session.dart';
import '../models/models.dart';
import '../widgets/common.dart';

class EventDetailPage extends StatelessWidget {
  const EventDetailPage({
    super.key,
    required this.session,
    required this.event,
    required this.isAdmin,
    required this.canManageCertificates,
    required this.onNavigate,
  });
  final SessionController session;
  final TrainingEvent event;
  final bool isAdmin;
  final bool canManageCertificates;
  final ValueChanged<String> onNavigate;

  Future<void> downloadSurveyQr(BuildContext context) async {
    final messenger = ScaffoldMessenger.of(context);
    try {
      final bytes = await session.api.download('/events/${event.id}/survey-qr');
      downloadBytes(bytes, '${event.title}-survey-qr.png', 'image/png');
    } catch (exception) {
      messenger.showSnackBar(SnackBar(content: Text('Survey QR download failed. ${humanizeError(exception)}')));
    }
  }

  Future<void> downloadTestQr(BuildContext context) async {
    final messenger = ScaffoldMessenger.of(context);
    try {
      final bytes = await session.api.download('/events/${event.id}/test-qr');
      downloadBytes(bytes, '${event.title}-post-test-qr.png', 'image/png');
    } catch (exception) {
      messenger.showSnackBar(SnackBar(content: Text('Post-test QR download failed. ${humanizeError(exception)}')));
    }
  }

  Future<void> downloadCheckinQr() async {
    final bytes = await session.api.download('/events/${event.id}/checkin-qr');
    downloadBytes(bytes, '${event.title}-checkin-qr.png', 'image/png');
  }

  Future<void> downloadQrSheet(BuildContext context) async {
    final messenger = ScaffoldMessenger.of(context);
    try {
      final bytes = await session.api.download('/events/${event.id}/qr-sheet');
      downloadBytes(bytes, '${event.title}-qr-sheet.pdf', 'application/pdf');
    } catch (exception) {
      messenger.showSnackBar(SnackBar(content: Text('QR sheet download failed. ${humanizeError(exception)}')));
    }
  }

  // Deleting an event permanently removes its uploads, attendee records, and
  // certificates, so the dialog requires typing DELETE before proceeding.
  Future<void> deleteEvent(BuildContext context) async {
    final theme = Theme.of(context);
    final messenger = ScaffoldMessenger.of(context);
    final controller = TextEditingController();
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => StatefulBuilder(
        builder: (dialogContext, setDialogState) => AlertDialog(
          title: Text('Delete "${event.title}"?'),
          content: SizedBox(
            width: 420,
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'This permanently removes the event with all of its uploads, '
                  'attendance records, test and survey results, and issued '
                  'certificates. Certificate verification links stop working. '
                  'This cannot be undone.',
                  style: theme.textTheme.bodyMedium?.copyWith(color: theme.portal.danger),
                ),
                const SizedBox(height: Space.sm + 2),
                TextField(
                  controller: controller,
                  autofocus: true,
                  decoration: const InputDecoration(labelText: 'Type DELETE to confirm'),
                  onChanged: (_) => setDialogState(() {}),
                ),
              ],
            ),
          ),
          actions: [
            TextButton(onPressed: () => Navigator.pop(dialogContext, false), child: const Text('Cancel')),
            ElevatedButton(
              style: ElevatedButton.styleFrom(
                backgroundColor: theme.portal.danger,
                foregroundColor: Colors.white,
              ),
              onPressed: controller.text.trim() == 'DELETE' ? () => Navigator.pop(dialogContext, true) : null,
              child: const Text('Delete event'),
            ),
          ],
        ),
      ),
    );
    if (confirmed != true) return;
    try {
      await session.api.delete('/events/${event.id}');
      messenger.showSnackBar(SnackBar(content: Text('"${event.title}" was deleted.')));
      onNavigate('back');
    } catch (exception) {
      messenger.showSnackBar(SnackBar(content: Text('Delete failed. ${humanizeError(exception)}')));
    }
  }

  Future<void> distribute(BuildContext context) async {
    final messenger = ScaffoldMessenger.of(context);
    // This sends real email, so always confirm first — with the recipient
    // count from the event summary when it can be fetched.
    int? registered;
    try {
      final summary = await session.api.get('/events/${event.id}/summary') as Map<String, dynamic>;
      registered = summary['registered'] as int?;
    } catch (_) {
      registered = null; // still confirm, just without the count
    }
    if (!context.mounted) return;
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('Email links to attendees?'),
        content: SizedBox(
          width: 420,
          child: Text(
            registered == null
                ? 'This emails the post-test and survey links to every registered or checked-in attendee with an email address. Send?'
                : 'This emails the post-test and survey links to the $registered registered/checked-in attendee${registered == 1 ? '' : 's'} with an email address. Send?',
          ),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(dialogContext, false), child: const Text('Cancel')),
          ElevatedButton(onPressed: () => Navigator.pop(dialogContext, true), child: const Text('Send')),
        ],
      ),
    );
    if (confirmed != true) return;
    messenger.showSnackBar(const SnackBar(content: Text('Sending post-test and survey links to registered attendees...')));
    try {
      final result = await session.api.post('/events/${event.id}/distribute') as Map<String, dynamic>;
      if (!context.mounted) return;
      final outcomes = [
        for (final entry in (result['recipients'] as List? ?? const []).cast<Map<String, dynamic>>())
          (
            name: (entry['full_name'] as String?) ?? 'Unknown attendee',
            email: entry['email'] as String?,
            status: (entry['status'] as String?) ?? 'failed',
            reason: entry['reason'] as String?,
            retryable: (entry['retryable'] as bool?) ?? false,
          ),
      ];
      await showBulkResultDialog(
        context,
        title: 'Invitations sent',
        sent: (result['sent'] as num?)?.toInt() ?? 0,
        outcomes: outcomes,
      );
    } catch (exception) {
      messenger.showSnackBar(SnackBar(content: Text('Distribution failed. ${humanizeError(exception)}')));
    }
  }

  bool get hasTest =>
      (event.testMode == 'internal' && event.testToken != null) ||
      (event.testMode == 'external' && event.postTestUrl != null);

  /// Origin the public test/survey pages are served from. The public pages are
  /// part of this same web app, so links share the portal's own address.
  String? get _appOrigin {
    final base = Uri.base;
    return (base.scheme == 'http' || base.scheme == 'https') ? base.origin : null;
  }

  String? get testLink {
    if (event.testMode == 'external') return event.postTestUrl;
    if (event.testToken == null || _appOrigin == null) return null;
    return '$_appOrigin/?test=${event.testToken}';
  }

  String? get checkinLink {
    if (event.checkinToken == null || _appOrigin == null) return null;
    return '$_appOrigin/?checkin=${event.checkinToken}';
  }

  String? get surveyLink {
    if (event.surveyMode == 'external') return event.externalSurveyUrl;
    if (event.surveyToken == null || _appOrigin == null) return null;
    return '$_appOrigin/?survey=${event.surveyToken}';
  }

  @override
  Widget build(BuildContext context) {
    final (statusLabel, statusTone) = eventStatusDisplay(event.status);
    return SingleChildScrollView(
      padding: pagePadding,
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: maxContentWidth),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              PageHeader(
                title: event.title,
                subtitle: '${DateFormat.yMMMMd().format(event.eventDate)}  •  ${event.ceuHours.toStringAsFixed(1)} CEU hours',
                actions: [
                  if (isAdmin) ...[
                    OutlinedButton.icon(
                      onPressed: () => onNavigate('edit'),
                      icon: const Icon(Icons.edit_outlined, size: 18),
                      label: const Text('Edit event'),
                    ),
                    OutlinedButton.icon(
                      onPressed: () => deleteEvent(context),
                      style: OutlinedButton.styleFrom(foregroundColor: Theme.of(context).portal.danger),
                      icon: const Icon(Icons.delete_outline, size: 18),
                      label: const Text('Delete'),
                    ),
                  ],
                  StatusBadge(statusLabel, tone: statusTone),
                ],
              ),
              const SizedBox(height: 22),
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(22),
                  child: Wrap(
                    spacing: 42,
                    runSpacing: 20,
                    children: [
                      _Detail(label: 'Location', value: event.location ?? 'Remote / TBD', icon: Icons.location_on_outlined),
                      _Detail(label: 'Presenter', value: event.presenterName ?? 'Not assigned', icon: Icons.record_voice_over_outlined),
                      if (isAdmin)
                        _Detail(label: 'Portal access', value: event.assignedPresenterName ?? 'No presenter assigned', icon: Icons.lock_person_outlined),
                      _Detail(label: 'Event ID', value: '#${event.id}', icon: Icons.tag),
                      _Detail(label: 'Event type', value: event.eventType.replaceAll('_', ' '), icon: Icons.category_outlined),
                    ],
                  ),
                ),
              ),
              const SizedBox(height: 16),
              _SummaryStrip(
                session: session,
                eventId: event.id,
                onOpenCompliance: () => onNavigate('compliance'),
              ),
              if (event.description != null) ...[
                const SizedBox(height: 16),
                Card(child: Padding(padding: const EdgeInsets.all(22), child: Text(event.description!))),
              ],
              const SizedBox(height: 24),
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(18),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      Wrap(
                        spacing: 10,
                        runSpacing: 10,
                        crossAxisAlignment: WrapCrossAlignment.center,
                        children: [
                          const SectionTitle('Participant links'),
                          Tooltip(
                            message: 'One printable page with the check-in, post-test, and survey QR codes — drop it into the slide deck',
                            child: ElevatedButton.icon(
                              onPressed: () => downloadQrSheet(context),
                              icon: const Icon(Icons.picture_as_pdf_outlined),
                              label: const Text('QR sheet (PDF)'),
                            ),
                          ),
                          if (checkinLink != null)
                            OutlinedButton.icon(
                              onPressed: downloadCheckinQr,
                              icon: const Icon(Icons.how_to_reg_outlined),
                              label: const Text('Download check-in QR'),
                            ),
                          if (hasTest)
                            OutlinedButton.icon(
                              onPressed: () => downloadTestQr(context),
                              icon: const Icon(Icons.qr_code_2),
                              label: Text(event.testMode == 'internal' ? 'Download post-test QR' : 'Download external test QR'),
                            ),
                          OutlinedButton.icon(
                            onPressed: () => downloadSurveyQr(context),
                            icon: const Icon(Icons.qr_code_2),
                            label: Text(event.surveyMode == 'internal' ? 'Download survey QR' : 'Download external survey QR'),
                          ),
                          ElevatedButton.icon(
                            onPressed: () => distribute(context),
                            icon: const Icon(Icons.forward_to_inbox_outlined),
                            label: const Text('Email links to attendees'),
                          ),
                          if (isAdmin)
                            StatusBadge('CERTIFICATE TEMPLATE V${event.certificateTemplateVersion}', tone: BadgeTone.info),
                        ],
                      ),
                      if (checkinLink != null) ...[
                        const SizedBox(height: 14),
                        _LinkRow(label: 'Self check-in link', url: checkinLink!),
                      ],
                      if (testLink != null) ...[
                        const SizedBox(height: 8),
                        _LinkRow(
                          label: event.testMode == 'internal' ? 'Post-test link' : 'External post-test',
                          url: testLink!,
                        ),
                      ],
                      if (surveyLink != null) ...[
                        const SizedBox(height: 8),
                        _LinkRow(
                          label: event.surveyMode == 'internal' ? 'Survey link' : 'External survey',
                          url: surveyLink!,
                        ),
                      ],
                    ],
                  ),
                ),
              ),
              if (isAdmin && event.testMode == 'internal' && event.testQuestions.isNotEmpty) ...[
                const SizedBox(height: 16),
                _QuestionsCard(questions: event.testQuestions),
              ],
              const SizedBox(height: 24),
              const SectionTitle('Workflow'),
              const SizedBox(height: Space.sm),
              LayoutBuilder(
                builder: (context, constraints) {
                  final width = constraints.maxWidth < 700 ? constraints.maxWidth : (constraints.maxWidth - 24) / 3;
                  return Wrap(
                    spacing: 12,
                    runSpacing: 12,
                    children: [
                      _WorkflowCard(
                        width: width,
                        icon: Icons.upload_file_outlined,
                        title: isAdmin ? 'Upload documents' : 'Upload sign-in sheet',
                        text: isAdmin
                            ? 'Add registration, attendance, post-test, and survey files or scans.'
                            : 'Upload the attendance / sign-in sheet for this event.',
                        button: isAdmin ? 'Manage uploads' : 'Upload sign-in sheet',
                        onPressed: () => onNavigate('uploads'),
                      ),
                      if (isAdmin) ...[
                        _WorkflowCard(
                          width: width,
                          icon: Icons.fact_check_outlined,
                          title: 'Compliance review',
                          text: 'Inspect matched attendees and clear eligibility reasons.',
                          button: 'Review attendees',
                          onPressed: () => onNavigate('compliance'),
                        ),
                        _WorkflowCard(
                          width: width,
                          icon: Icons.workspace_premium_outlined,
                          title: 'Certificates',
                          text: 'Generate, send, and resend approved attendee certificates.',
                          button: canManageCertificates ? 'Certificate center' : 'Admin approval required',
                          onPressed: canManageCertificates ? () => onNavigate('certificates') : null,
                        ),
                      ],
                    ],
                  );
                },
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _Detail extends StatelessWidget {
  const _Detail({required this.label, required this.value, required this.icon});
  final String label;
  final String value;
  final IconData icon;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return ConstrainedBox(
      // Min-width, not fixed: at large text scale the label and value need room
      // to grow. The inner Column is Expanded because without it the Row had no
      // flexible child and overflowed horizontally outright — not a clip, a
      // RenderFlex error painted over the content.
      constraints: const BoxConstraints(minWidth: 240, maxWidth: 320),
      child: Semantics(
        container: true,
        label: '$label: $value',
        excludeSemantics: true,
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Icon(icon, color: theme.portal.textSecondary),
            const SizedBox(width: Space.xs + 2),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    label,
                    style: theme.textTheme.labelMedium?.copyWith(
                      color: theme.portal.textSecondary,
                      fontWeight: FontWeight.w400,
                    ),
                  ),
                  const SizedBox(height: 2),
                  Text(
                    value,
                    style: theme.textTheme.bodyMedium?.copyWith(fontWeight: FontWeight.w600),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _WorkflowCard extends StatelessWidget {
  const _WorkflowCard({
    required this.width,
    required this.icon,
    required this.title,
    required this.text,
    required this.button,
    required this.onPressed,
  });

  final double width;
  final IconData icon;
  final String title;
  final String text;
  final String button;
  final VoidCallback? onPressed;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return SizedBox(
      width: width,
      child: Card(
        child: Padding(
          padding: const EdgeInsets.all(Space.lg),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              ExcludeSemantics(
                child: Icon(icon, size: 30, color: theme.colorScheme.primary),
              ),
              const SizedBox(height: Space.md),
              SectionTitle(title, style: theme.textTheme.titleSmall),
              const SizedBox(height: Space.xs),
              // Min-height, not fixed: the cards already sit in a Wrap, so
              // uneven heights are harmless — whereas a hard 60px cap showed one
              // line of a three-line explanation at 200% text scale, and this is
              // the copy that tells a presenter what "Upload sign-in sheet" means.
              ConstrainedBox(
                constraints: const BoxConstraints(minHeight: 60),
                child: Text(
                  text,
                  style: theme.textTheme.bodyMedium?.copyWith(color: theme.portal.textSecondary),
                ),
              ),
              const SizedBox(height: Space.sm + 2),
              SizedBox(width: double.infinity, child: OutlinedButton(onPressed: onPressed, child: Text(button))),
            ],
          ),
        ),
      ),
    );
  }
}

class _LinkRow extends StatelessWidget {
  const _LinkRow({required this.label, required this.url});
  final String label;
  final String url;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: Space.sm, vertical: Space.xxs + 2),
      decoration: BoxDecoration(
        color: theme.portal.surfaceSubtle,
        borderRadius: BorderRadius.circular(Radii.md),
      ),
      child: Row(
        children: [
          ConstrainedBox(
            constraints: const BoxConstraints(minWidth: 140, maxWidth: 200),
            child: Text(
              label,
              style: theme.textTheme.labelMedium?.copyWith(color: theme.portal.textSecondary),
            ),
          ),
          Expanded(
            child: SelectableText(url, maxLines: 1, style: theme.textTheme.bodySmall),
          ),
          IconButton(
            tooltip: 'Copy $label',
            icon: const Icon(Icons.copy_outlined, size: 18),
            onPressed: () async {
              await Clipboard.setData(ClipboardData(text: url));
              if (context.mounted) {
                ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('$label copied to clipboard')));
              }
            },
          ),
          IconButton(
            tooltip: 'Open $label in a new tab',
            icon: const Icon(Icons.open_in_new, size: 18),
            onPressed: () => launchUrl(Uri.parse(url), webOnlyWindowName: '_blank'),
          ),
        ],
      ),
    );
  }
}

class _QuestionsCard extends StatelessWidget {
  const _QuestionsCard({required this.questions});
  final List<Map<String, dynamic>> questions;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final colors = theme.portal;
    return Card(
      child: ExpansionTile(
        shape: const Border(),
        title: Text(
          'Post-test questions (${questions.length})',
          style: theme.textTheme.labelLarge?.copyWith(fontWeight: FontWeight.w700),
        ),
        subtitle: Text(
          'Review what attendees will be asked. Correct answers are marked.',
          style: theme.textTheme.labelMedium?.copyWith(
            color: colors.textSecondary,
            fontWeight: FontWeight.w400,
          ),
        ),
        childrenPadding: const EdgeInsets.fromLTRB(22, 0, 22, 18),
        expandedCrossAxisAlignment: CrossAxisAlignment.start,
        children: [
          for (var i = 0; i < questions.length; i++) ...[
            if (i > 0) const SizedBox(height: Space.sm + 2),
            Text(
              '${i + 1}. ${questions[i]['prompt']}',
              style: theme.textTheme.bodyMedium?.copyWith(fontWeight: FontWeight.w600),
            ),
            const SizedBox(height: Space.xxs),
            for (var c = 0; c < (questions[i]['choices'] as List).length; c++)
              Padding(
                padding: const EdgeInsets.only(left: Space.md, top: 2),
                child: Semantics(
                  // The tick is the only thing marking the right answer, so it
                  // needs to survive being read aloud.
                  label: c == questions[i]['correct_index'] ? 'Correct answer' : 'Answer option',
                  child: Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      ExcludeSemantics(
                        child: Icon(
                          c == questions[i]['correct_index']
                              ? Icons.check_circle
                              : Icons.radio_button_unchecked,
                          size: 16,
                          color: c == questions[i]['correct_index']
                              ? colors.success
                              : colors.textTertiary,
                        ),
                      ),
                      const SizedBox(width: Space.xs),
                      Expanded(child: Text((questions[i]['choices'] as List)[c].toString())),
                    ],
                  ),
                ),
              ),
          ],
        ],
      ),
    );
  }
}

class _SummaryStrip extends StatelessWidget {
  const _SummaryStrip({required this.session, required this.eventId, required this.onOpenCompliance});
  final SessionController session;
  final int eventId;
  final VoidCallback onOpenCompliance;

  bool get isAdmin => session.user!.isAdmin;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final colors = theme.portal;
    return FutureBuilder<dynamic>(
      future: session.api.get('/events/$eventId/summary'),
      builder: (context, snapshot) {
        if (snapshot.hasError) {
          return Card(
            child: Padding(
              padding: const EdgeInsets.all(22),
              child: Semantics(
                liveRegion: true,
                container: true,
                child: Row(
                  children: [
                    ExcludeSemantics(
                      child: Icon(Icons.error_outline, color: colors.danger, size: 20),
                    ),
                    const SizedBox(width: Space.xs + 2),
                    Expanded(
                      child: Text(
                        'Event summary could not be loaded. '
                        '${humanizeError(snapshot.error!)}',
                        style: theme.textTheme.bodySmall?.copyWith(color: colors.textSecondary),
                      ),
                    ),
                  ],
                ),
              ),
            ),
          );
        }
        if (!snapshot.hasData) {
          return const Card(child: Padding(padding: EdgeInsets.all(22), child: LinearProgressIndicator()));
        }
        final s = EventSummary.fromJson(snapshot.data as Map<String, dynamic>);
        // The third element marks figures that answer to the compliance
        // review, so tapping them opens it directly.
        final items = <(String, String, bool)>[
          ('Attendees', '${s.totalAttendees}', false),
          ('Attended', '${s.attended}', false),
          ('Passed test', '${s.testPassed}', false),
          ('Survey done', '${s.surveyCompleted}', false),
          ('Eligible', '${s.eligible}', true),
          ('Approved', '${s.approved}', true),
          ('Certs sent', '${s.certificatesSent}/${s.certificatesGenerated}', true),
          ('Compliance', '${s.complianceRate.toStringAsFixed(0)}%', false),
        ];
        return Card(
          child: Padding(
            padding: const EdgeInsets.all(20),
            child: Wrap(
              spacing: 36,
              runSpacing: 16,
              children: [
                for (final item in items)
                  // Compliance review is admin-only, so only admins get the
                  // tappable shortcut into it.
                  if (item.$3 && isAdmin)
                    Tooltip(
                      message: 'Open compliance review',
                      child: InkWell(
                        borderRadius: BorderRadius.circular(Radii.sm),
                        onTap: onOpenCompliance,
                        child: MinTapTarget(
                          child: Padding(
                            padding: const EdgeInsets.symmetric(
                              horizontal: Space.xs,
                              vertical: Space.xxs,
                            ),
                            child: _SummaryFigure(value: item.$2, label: item.$1),
                          ),
                        ),
                      ),
                    )
                  else
                    _SummaryFigure(value: item.$2, label: item.$1),
              ],
            ),
          ),
        );
      },
    );
  }
}

class _SummaryFigure extends StatelessWidget {
  const _SummaryFigure({required this.value, required this.label});
  final String value;
  final String label;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Semantics(
      container: true,
      label: '$label: $value',
      excludeSemantics: true,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(value, style: theme.textTheme.titleLarge?.copyWith(color: navy)),
          const SizedBox(height: 2),
          Text(
            label,
            style: theme.textTheme.labelMedium?.copyWith(
              color: theme.portal.textSecondary,
              fontWeight: FontWeight.w400,
            ),
          ),
        ],
      ),
    );
  }
}
