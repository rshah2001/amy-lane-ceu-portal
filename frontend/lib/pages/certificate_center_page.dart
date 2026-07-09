import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';

import '../core/file_download.dart';
import '../core/session.dart';
import '../models/models.dart';
import '../widgets/common.dart';

class CertificateCenterPage extends StatefulWidget {
  const CertificateCenterPage({
    super.key,
    required this.session,
    required this.initialEvent,
    required this.onSelectEvent,
  });

  final SessionController session;
  final TrainingEvent? initialEvent;
  final ValueChanged<TrainingEvent> onSelectEvent;

  @override
  State<CertificateCenterPage> createState() => _CertificateCenterPageState();
}

class _CertificateCenterPageState extends State<CertificateCenterPage> {
  List<TrainingEvent>? events;
  TrainingEvent? event;
  List<ComplianceRecord>? records;
  String? error;
  int? workingId;
  bool uploadingTemplate = false;
  bool bulkWorking = false;

  @override
  void initState() {
    super.initState();
    event = widget.initialEvent;
    loadEvents();
  }

  Future<void> loadEvents() async {
    try {
      final result = await widget.session.api.get('/events') as List;
      final loaded = result.map((item) => TrainingEvent.fromJson(item as Map<String, dynamic>)).toList();
      if (!mounted) return;
      setState(() {
        events = loaded;
        if (loaded.isEmpty) {
          event = null;
        } else if (event == null) {
          event = loaded.first;
        } else {
          event = loaded.firstWhere(
            (candidate) => candidate.id == event!.id,
            orElse: () => loaded.first,
          );
        }
      });
      if (event != null) await loadRecords();
    } catch (exception) {
      if (mounted) setState(() => error = exception.toString());
    }
  }

  Future<void> loadRecords() async {
    if (event == null) return;
    setState(() {
      records = null;
      error = null;
    });
    try {
      final result = await widget.session.api.get('/events/${event!.id}/compliance') as List;
      if (mounted) {
        setState(() => records = result.map((item) => ComplianceRecord.fromJson(item as Map<String, dynamic>)).toList());
      }
    } catch (exception) {
      if (mounted) setState(() => error = exception.toString());
    }
  }

  Future<void> generate(ComplianceRecord record) async {
    await action(record, '/events/${event!.id}/certificates/${record.id}/generate');
  }

  Future<void> send(ComplianceRecord record) async {
    await action(record, '/events/${event!.id}/certificates/${record.id}/send');
  }

  Future<void> preview(ComplianceRecord record) async {
    if (event == null) return;
    final messenger = ScaffoldMessenger.of(context);
    setState(() => workingId = record.id);
    try {
      final bytes = await widget.session.api.download(
        '/events/${event!.id}/certificates/${record.id}/preview',
      );
      downloadBytes(
        bytes,
        '${record.fullName}-certificate-preview.pdf',
        'application/pdf',
      );
      messenger.showSnackBar(
        const SnackBar(content: Text('Preview downloaded — check your Downloads folder.')),
      );
    } catch (exception) {
      if (mounted) setState(() => error = exception.toString());
    } finally {
      if (mounted) setState(() => workingId = null);
    }
  }

  // The primary admin flow after approvals: one button that generates every
  // missing certificate and emails everything unsent, with a confirmation
  // first and a persistent result dialog after.
  Future<void> generateAndSendAll() async {
    if (event == null || records == null) return;
    final toGenerate = records!.where((record) => record.approved && record.certificateNumber == null).length;
    final toSend = records!.where((record) => record.approved && record.certificateSentAt == null).length;
    if (toGenerate == 0 && toSend == 0) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Every approved attendee already has a certificate that was sent.')),
      );
      return;
    }
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('Generate & send all approved?'),
        content: SizedBox(
          width: 420,
          child: Text(
            'Generate certificates for $toGenerate approved attendee${toGenerate == 1 ? '' : 's'} '
            'and email $toSend of them? Attendees without an email address are skipped.',
          ),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(dialogContext, false), child: const Text('Cancel')),
          ElevatedButton(onPressed: () => Navigator.pop(dialogContext, true), child: const Text('Generate & send')),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    setState(() {
      bulkWorking = true;
      error = null;
    });
    try {
      final generated = await widget.session.api.post('/events/${event!.id}/certificates/generate-all') as Map<String, dynamic>;
      final sent = await widget.session.api.post('/events/${event!.id}/certificates/send-all') as Map<String, dynamic>;
      if (!mounted) return;
      final details = [
        ...((generated['details'] as List?) ?? const []),
        ...((sent['details'] as List?) ?? const []),
      ].cast<String>();
      await showDialog<void>(
        context: context,
        builder: (dialogContext) => AlertDialog(
          title: const Text('Certificates processed'),
          content: SizedBox(
            width: 440,
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('Generated: ${generated['processed']} new, ${generated['skipped']} already existed, ${generated['failed']} failed.'),
                const SizedBox(height: 6),
                Text('Emailed: ${sent['processed']} sent, ${sent['skipped']} skipped (no email address), ${sent['failed']} failed.'),
                if (details.isNotEmpty) ...[
                  const SizedBox(height: 12),
                  for (final line in details)
                    Padding(
                      padding: const EdgeInsets.only(bottom: 4),
                      child: Text('• $line', style: const TextStyle(fontSize: 12, color: Color(0xFFB42318))),
                    ),
                ],
              ],
            ),
          ),
          actions: [
            ElevatedButton(onPressed: () => Navigator.pop(dialogContext), child: const Text('Done')),
          ],
        ),
      );
      await loadRecords();
    } catch (exception) {
      if (mounted) setState(() => error = exception.toString());
    } finally {
      if (mounted) setState(() => bulkWorking = false);
    }
  }

  Future<void> uploadTemplate() async {
    if (event == null) return;
    final proceed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('Upload certificate template'),
        content: const SizedBox(
          width: 420,
          child: Text(
            'PNG or JPG, landscape letter recommended. Replacing the template '
            'only affects future certificates.',
          ),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(dialogContext, false), child: const Text('Cancel')),
          ElevatedButton(onPressed: () => Navigator.pop(dialogContext, true), child: const Text('Choose file')),
        ],
      ),
    );
    if (proceed != true) return;
    final result = await FilePicker.platform.pickFiles(
      type: FileType.custom,
      allowedExtensions: const ['png', 'jpg', 'jpeg'],
      withData: true,
    );
    final file = result?.files.single;
    if (file?.bytes == null) return;
    setState(() {
      uploadingTemplate = true;
      error = null;
    });
    try {
      await widget.session.api.uploadFile(
        '/events/${event!.id}/certificates/template',
        file!.bytes!,
        file.name,
      );
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Certificate template updated for future certificates.')),
        );
      }
      await loadEvents();
    } catch (exception) {
      if (mounted) setState(() => error = exception.toString());
    } finally {
      if (mounted) setState(() => uploadingTemplate = false);
    }
  }

  Future<void> action(ComplianceRecord record, String path) async {
    setState(() => workingId = record.id);
    try {
      await widget.session.api.post(path);
      await loadRecords();
    } catch (exception) {
      if (mounted) setState(() => error = exception.toString());
    } finally {
      if (mounted) setState(() => workingId = null);
    }
  }

  // Admin escape hatch: issue a certificate to anyone by name and email,
  // bypassing the eligibility rules (audited on the backend).
  Future<void> issueManually() async {
    if (event == null) return;
    final formKey = GlobalKey<FormState>();
    final nameController = TextEditingController();
    final emailController = TextEditingController();
    var sendNow = true;
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => StatefulBuilder(
        builder: (context, setDialogState) => AlertDialog(
          title: const Text('Issue a certificate manually'),
          content: SizedBox(
            width: 420,
            child: Form(
              key: formKey,
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    'For "${event!.title}". The recipient does not need to meet the '
                    'eligibility requirements — the manual issue is recorded in the audit log.',
                    style: const TextStyle(fontSize: 13, color: Color(0xFF667085)),
                  ),
                  const SizedBox(height: 14),
                  TextFormField(
                    controller: nameController,
                    autofocus: true,
                    decoration: const InputDecoration(labelText: 'Full name'),
                    validator: (v) => v == null || v.trim().length < 2 ? 'Enter the recipient name' : null,
                  ),
                  const SizedBox(height: 12),
                  TextFormField(
                    controller: emailController,
                    keyboardType: TextInputType.emailAddress,
                    decoration: const InputDecoration(labelText: 'Email address'),
                    validator: emailValidator,
                  ),
                  const SizedBox(height: 6),
                  CheckboxListTile(
                    contentPadding: EdgeInsets.zero,
                    controlAffinity: ListTileControlAffinity.leading,
                    value: sendNow,
                    onChanged: (value) => setDialogState(() => sendNow = value ?? true),
                    title: const Text('Email the certificate now'),
                  ),
                ],
              ),
            ),
          ),
          actions: [
            TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Cancel')),
            ElevatedButton(
              onPressed: () {
                if (formKey.currentState!.validate()) Navigator.pop(context, true);
              },
              child: const Text('Issue certificate'),
            ),
          ],
        ),
      ),
    );
    if (confirmed != true || !mounted) return;
    final messenger = ScaffoldMessenger.of(context);
    setState(() => error = null);
    try {
      await widget.session.api.post('/events/${event!.id}/certificates/issue', {
        'full_name': nameController.text.trim(),
        'email': emailController.text.trim(),
        'send_email': sendNow,
      });
      messenger.showSnackBar(SnackBar(
        content: Text(sendNow
            ? 'Certificate issued and emailed to ${emailController.text.trim()}.'
            : 'Certificate issued for ${nameController.text.trim()}.'),
      ));
      await loadRecords();
    } catch (exception) {
      if (mounted) setState(() => error = exception.toString());
    }
  }

  @override
  Widget build(BuildContext context) {
    final visibleRecords = records?.where((record) => record.approved || record.eligible).toList();
    return Padding(
      padding: pagePadding,
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: maxContentWidth),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              PageHeader(
                title: 'Certificate Center',
                subtitle: 'Preview, generate, send, and preserve issued certificate versions.',
                actions: [
                  // The everyday flow gets the primary slot; the manual-issue
                  // escape hatch and template upload live under "More".
                  ElevatedButton.icon(
                    onPressed: event == null || records == null || bulkWorking ? null : generateAndSendAll,
                    icon: bulkWorking
                        ? const SizedBox(width: 17, height: 17, child: CircularProgressIndicator(strokeWidth: 2))
                        : const Icon(Icons.send_outlined),
                    label: Text(bulkWorking ? 'Working...' : 'Generate & send all approved'),
                  ),
                  PopupMenuButton<String>(
                    enabled: event != null && !uploadingTemplate && !bulkWorking,
                    onSelected: (value) => switch (value) {
                      'issue' => issueManually(),
                      'template' => uploadTemplate(),
                      _ => Future<void>.value(),
                    },
                    itemBuilder: (context) => const [
                      PopupMenuItem(value: 'issue', child: Text('Issue certificate manually')),
                      PopupMenuItem(value: 'template', child: Text('Upload certificate template')),
                    ],
                    child: IgnorePointer(
                      child: OutlinedButton.icon(
                        onPressed: () {},
                        icon: uploadingTemplate
                            ? const SizedBox(width: 17, height: 17, child: CircularProgressIndicator(strokeWidth: 2))
                            : const Icon(Icons.more_horiz),
                        label: Text(uploadingTemplate ? 'Uploading...' : 'More'),
                      ),
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 16),
              if (events == null)
                error != null
                    ? InlineAlert(message: error!, onRetry: loadEvents, onDismiss: () => setState(() => error = null))
                    : const LoadingPanel()
              else if (events!.isEmpty)
                const Expanded(
                  child: EmptyState(
                    icon: Icons.event_busy_outlined,
                    message: 'No events are available',
                    detail: 'Create an event before generating certificates.',
                  ),
                )
              else ...[
                DropdownButtonFormField<int>(
                  initialValue: event?.id,
                  decoration: const InputDecoration(labelText: 'Event', prefixIcon: Icon(Icons.event_note_outlined)),
                  items: [
                    for (final candidate in events!)
                      DropdownMenuItem(value: candidate.id, child: Text('${candidate.title} (${formatDate(candidate.eventDate)})')),
                  ],
                  onChanged: (id) {
                    final next = events!.firstWhere((candidate) => candidate.id == id);
                    widget.onSelectEvent(next);
                    setState(() => event = next);
                    loadRecords();
                  },
                ),
                if (error != null) ...[
                  const SizedBox(height: 10),
                  InlineAlert(message: error!, onRetry: loadRecords, onDismiss: () => setState(() => error = null)),
                ],
                const SizedBox(height: 14),
                Expanded(
                  child: Card(
                    child: visibleRecords == null
                        ? const LoadingPanel()
                        : visibleRecords.isEmpty
                            ? const EmptyState(
                                icon: Icons.workspace_premium_outlined,
                                message: 'No attendees are ready for certificates',
                                detail: 'Attendees appear here once they are eligible or approved in the compliance review.',
                              )
                            : SingleChildScrollView(
                            child: SingleChildScrollView(
                              scrollDirection: Axis.horizontal,
                              child: DataTable(
                                columns: const [
                                  DataColumn(label: Text('Attendee')),
                                  DataColumn(label: Text('Approval')),
                                  DataColumn(label: Text('Certificate')),
                                  DataColumn(label: Text('Sent')),
                                  DataColumn(label: Text('Actions')),
                                ],
                                rows: visibleRecords
                                    .map(
                                      (record) => DataRow(
                                        cells: [
                                          DataCell(SizedBox(width: 230, child: Text(record.fullName, style: const TextStyle(fontWeight: FontWeight.w600)))),
                                          DataCell(StatusBadge(record.approved ? 'APPROVED' : 'AWAITING APPROVAL', tone: record.approved ? BadgeTone.success : BadgeTone.warning)),
                                          DataCell(Text(record.certificateNumber ?? 'Not generated')),
                                          DataCell(Text(record.certificateSentAt == null ? 'Not sent' : formatDateTime(record.certificateSentAt!))),
                                          DataCell(
                                            Wrap(
                                              spacing: 8,
                                              children: [
                                                OutlinedButton.icon(
                                                  // Approved covers manually issued / override-approved
                                                  // attendees, who are never "eligible".
                                                  onPressed: !(record.eligible || record.approved) || workingId == record.id
                                                      ? null
                                                      : () => preview(record),
                                                  icon: const Icon(Icons.visibility_outlined, size: 18),
                                                  label: const Text('Preview'),
                                                ),
                                                OutlinedButton.icon(
                                                  onPressed: !record.approved || record.certificateNumber != null || workingId == record.id
                                                      ? null
                                                      : () => generate(record),
                                                  icon: const Icon(Icons.workspace_premium_outlined, size: 18),
                                                  label: Text(record.certificateNumber == null ? 'Generate' : 'Generated'),
                                                ),
                                                ElevatedButton.icon(
                                                  onPressed: record.certificateNumber == null || workingId == record.id ? null : () => send(record),
                                                  icon: const Icon(Icons.send_outlined, size: 18),
                                                  label: Text(record.certificateSentAt == null ? 'Send' : 'Resend'),
                                                ),
                                              ],
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
            ],
          ),
        ),
      ),
    );
  }
}
