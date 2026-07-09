import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

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
    } catch (exception) {
      if (mounted) setState(() => error = exception.toString());
    } finally {
      if (mounted) setState(() => workingId = null);
    }
  }

  Future<void> uploadTemplate() async {
    if (event == null) return;
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
                  OutlinedButton.icon(
                    onPressed: event == null || uploadingTemplate ? null : uploadTemplate,
                    icon: uploadingTemplate
                        ? const SizedBox(width: 17, height: 17, child: CircularProgressIndicator(strokeWidth: 2))
                        : const Icon(Icons.image_outlined),
                    label: Text(uploadingTemplate ? 'Uploading...' : 'Upload template'),
                  ),
                ],
              ),
              const SizedBox(height: 16),
              if (events == null)
                const LoadingPanel()
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
                      DropdownMenuItem(value: candidate.id, child: Text('${candidate.title} (${DateFormat.yMMMd().format(candidate.eventDate)})')),
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
                  Text(error!, style: const TextStyle(color: Color(0xFFB42318))),
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
                                          DataCell(Text(record.certificateSentAt == null ? 'Not sent' : DateFormat.yMd().add_jm().format(record.certificateSentAt!.toLocal()))),
                                          DataCell(
                                            Wrap(
                                              spacing: 8,
                                              children: [
                                                OutlinedButton.icon(
                                                  onPressed: !record.eligible || workingId == record.id
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
