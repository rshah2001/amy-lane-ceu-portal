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
      messenger.showSnackBar(SnackBar(content: Text('Survey QR download failed: $exception')));
    }
  }

  Future<void> downloadTestQr(BuildContext context) async {
    final messenger = ScaffoldMessenger.of(context);
    try {
      final bytes = await session.api.download('/events/${event.id}/test-qr');
      downloadBytes(bytes, '${event.title}-post-test-qr.png', 'image/png');
    } catch (exception) {
      messenger.showSnackBar(SnackBar(content: Text('Post-test QR download failed: $exception')));
    }
  }

  Future<void> downloadCheckinQr() async {
    final bytes = await session.api.download('/events/${event.id}/checkin-qr');
    downloadBytes(bytes, '${event.title}-checkin-qr.png', 'image/png');
  }

  Future<void> distribute(BuildContext context) async {
    final messenger = ScaffoldMessenger.of(context);
    messenger.showSnackBar(const SnackBar(content: Text('Sending post-test and survey links to registered attendees...')));
    try {
      final result = await session.api.post('/events/${event.id}/distribute') as Map<String, dynamic>;
      final skipped = (result['skipped'] as List).length;
      final failed = (result['failed'] as List).length;
      messenger.showSnackBar(SnackBar(
        content: Text('Sent ${result['sent']} invite(s). Skipped $skipped (no valid email), $failed failed.'),
      ));
    } catch (exception) {
      messenger.showSnackBar(SnackBar(content: Text('Distribution failed: $exception')));
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
    return SingleChildScrollView(
      padding: pagePadding,
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 1100),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              PageHeader(
                title: event.title,
                subtitle: '${DateFormat.yMMMMd().format(event.eventDate)}  •  ${event.ceuHours.toStringAsFixed(1)} CEU hours',
                actions: [
                  if (isAdmin)
                    OutlinedButton.icon(
                      onPressed: () => onNavigate('edit'),
                      icon: const Icon(Icons.edit_outlined, size: 18),
                      label: const Text('Edit event'),
                    ),
                  StatusBadge(event.status.toUpperCase(), tone: BadgeTone.warning),
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
              _SummaryStrip(session: session, eventId: event.id),
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
                          const Text('Participant links', style: TextStyle(fontWeight: FontWeight.w700)),
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
              Text('Workflow', style: Theme.of(context).textTheme.titleLarge?.copyWith(fontWeight: FontWeight.w700)),
              const SizedBox(height: 12),
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
    return SizedBox(
      width: 240,
      child: Row(
        children: [
          Icon(icon, color: Colors.blueGrey),
          const SizedBox(width: 10),
          Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(label, style: const TextStyle(fontSize: 12, color: Color(0xFF667085))),
              const SizedBox(height: 2),
              Text(value, style: const TextStyle(fontWeight: FontWeight.w600)),
            ],
          ),
        ],
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
    return SizedBox(
      width: width,
      child: Card(
        child: Padding(
          padding: const EdgeInsets.all(20),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Icon(icon, size: 30, color: Theme.of(context).colorScheme.primary),
              const SizedBox(height: 16),
              Text(title, style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700)),
              const SizedBox(height: 8),
              SizedBox(height: 60, child: Text(text, style: const TextStyle(color: Color(0xFF667085), height: 1.4))),
              const SizedBox(height: 14),
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
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
      decoration: BoxDecoration(
        color: const Color(0xFFF4F6F8),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Row(
        children: [
          SizedBox(
            width: 140,
            child: Text(label, style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w600, color: Color(0xFF667085))),
          ),
          Expanded(
            child: SelectableText(url, maxLines: 1, style: const TextStyle(fontSize: 13)),
          ),
          IconButton(
            tooltip: 'Copy link',
            icon: const Icon(Icons.copy_outlined, size: 18),
            onPressed: () async {
              await Clipboard.setData(ClipboardData(text: url));
              if (context.mounted) {
                ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('$label copied to clipboard')));
              }
            },
          ),
          IconButton(
            tooltip: 'Open in new tab',
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
    return Card(
      child: ExpansionTile(
        shape: const Border(),
        title: Text('Post-test questions (${questions.length})', style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 14)),
        subtitle: const Text('Review what attendees will be asked. Correct answers are marked.',
            style: TextStyle(fontSize: 12, color: Color(0xFF667085))),
        childrenPadding: const EdgeInsets.fromLTRB(22, 0, 22, 18),
        expandedCrossAxisAlignment: CrossAxisAlignment.start,
        children: [
          for (var i = 0; i < questions.length; i++) ...[
            if (i > 0) const SizedBox(height: 14),
            Text('${i + 1}. ${questions[i]['prompt']}', style: const TextStyle(fontWeight: FontWeight.w600)),
            const SizedBox(height: 4),
            for (var c = 0; c < (questions[i]['choices'] as List).length; c++)
              Padding(
                padding: const EdgeInsets.only(left: 16, top: 2),
                child: Row(
                  children: [
                    Icon(
                      c == questions[i]['correct_index'] ? Icons.check_circle : Icons.radio_button_unchecked,
                      size: 16,
                      color: c == questions[i]['correct_index'] ? const Color(0xFF12805C) : const Color(0xFF98A2B3),
                    ),
                    const SizedBox(width: 8),
                    Expanded(child: Text((questions[i]['choices'] as List)[c].toString())),
                  ],
                ),
              ),
          ],
        ],
      ),
    );
  }
}

class _SummaryStrip extends StatelessWidget {
  const _SummaryStrip({required this.session, required this.eventId});
  final SessionController session;
  final int eventId;

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<dynamic>(
      future: session.api.get('/events/$eventId/summary'),
      builder: (context, snapshot) {
        if (snapshot.hasError) {
          return Card(
            child: Padding(
              padding: const EdgeInsets.all(22),
              child: Row(
                children: [
                  const Icon(Icons.error_outline, color: Color(0xFFB42318), size: 20),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Text(
                      'Event summary could not be loaded: ${snapshot.error}',
                      style: const TextStyle(fontSize: 13, color: Color(0xFF667085)),
                    ),
                  ),
                ],
              ),
            ),
          );
        }
        if (!snapshot.hasData) {
          return const Card(child: Padding(padding: EdgeInsets.all(22), child: LinearProgressIndicator()));
        }
        final s = EventSummary.fromJson(snapshot.data as Map<String, dynamic>);
        final items = <(String, String)>[
          ('Attendees', '${s.totalAttendees}'),
          ('Attended', '${s.attended}'),
          ('Passed test', '${s.testPassed}'),
          ('Survey done', '${s.surveyCompleted}'),
          ('Eligible', '${s.eligible}'),
          ('Approved', '${s.approved}'),
          ('Certs sent', '${s.certificatesSent}/${s.certificatesGenerated}'),
          ('Compliance', '${s.complianceRate.toStringAsFixed(0)}%'),
        ];
        return Card(
          child: Padding(
            padding: const EdgeInsets.all(20),
            child: Wrap(
              spacing: 36,
              runSpacing: 16,
              children: [
                for (final item in items)
                  Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(item.$2, style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w700, color: Color(0xFF17324D))),
                      const SizedBox(height: 2),
                      Text(item.$1, style: const TextStyle(fontSize: 12, color: Color(0xFF667085))),
                    ],
                  ),
              ],
            ),
          ),
        );
      },
    );
  }
}
