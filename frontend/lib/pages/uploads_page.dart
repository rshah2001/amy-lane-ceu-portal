import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../core/session.dart';
import '../models/models.dart';
import '../widgets/common.dart';

class UploadsPage extends StatefulWidget {
  const UploadsPage({super.key, required this.session, required this.event});
  final SessionController session;
  final TrainingEvent event;

  @override
  State<UploadsPage> createState() => _UploadsPageState();
}

class _UploadsPageState extends State<UploadsPage> {
  List<Map<String, dynamic>>? uploads;
  String? error;
  String? uploadingType;

  static const allTypes = [
    ('registration', 'Registration roster', Icons.how_to_reg_outlined, 'Names, emails, company, and license numbers'),
    ('attendance', 'Attendance / sign-in', Icons.fact_check_outlined, 'The final event attendance export'),
    ('post_test', 'Post-test results', Icons.quiz_outlined, 'Attendee identity and numeric score'),
    ('survey', 'Survey results', Icons.rate_review_outlined, 'Attendee identity and completion status'),
  ];

  // Presenters can only submit the attendance / sign-in sheet; admins manage all four.
  List<(String, String, IconData, String)> get types => widget.session.user!.isAdmin
      ? allTypes
      : allTypes.where((t) => t.$1 == 'attendance').toList();

  @override
  void initState() {
    super.initState();
    load();
  }

  Future<void> load() async {
    try {
      final result = await widget.session.api.get('/events/${widget.event.id}/uploads') as List;
      if (mounted) {
        setState(() {
          uploads = result.cast<Map<String, dynamic>>();
          error = null;
        });
      }
    } catch (exception) {
      if (mounted) setState(() => error = exception.toString());
    }
  }

  Future<void> pickAndUpload(String type) async {
    final result = await FilePicker.platform.pickFiles(
      type: FileType.custom,
      allowedExtensions: const ['csv', 'xlsx', 'png', 'jpg', 'jpeg'],
      withData: true,
    );
    final file = result?.files.single;
    if (file?.bytes == null) return;
    setState(() {
      uploadingType = type;
      error = null;
    });
    try {
      await widget.session.api.uploadFile(
        '/events/${widget.event.id}/uploads/$type',
        file!.bytes!,
        file.name,
      );
      await load();
    } catch (exception) {
      if (mounted) setState(() => error = exception.toString());
    } finally {
      if (mounted) setState(() => uploadingType = null);
    }
  }

  Map<String, dynamic>? latestFor(String type) {
    if (uploads == null) return null;
    for (final upload in uploads!) {
      if (upload['file_type'] == type) return upload;
    }
    return null;
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
                title: 'Upload Documents',
                subtitle: widget.event.title,
                actions: [OutlinedButton.icon(onPressed: load, icon: const Icon(Icons.refresh), label: const Text('Refresh'))],
              ),
              const SizedBox(height: 18),
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(16),
                  child: Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Icon(Icons.info_outline, color: Color(0xFF245B85)),
                      const SizedBox(width: 10),
                      Expanded(
                        child: Text(
                          'Upload CSV, XLSX, or image scans. Image OCR is best-effort, so review extracted rows before approving certificates.',
                          style: TextStyle(color: Colors.blueGrey.shade700),
                        ),
                      ),
                    ],
                  ),
                ),
              ),
              if (error != null) ...[
                const SizedBox(height: 12),
                Text(error!, style: const TextStyle(color: Color(0xFFB42318))),
              ],
              const SizedBox(height: 16),
              for (final type in types) ...[
                _UploadRow(
                  title: type.$2,
                  description: type.$4,
                  icon: type.$3,
                  upload: latestFor(type.$1),
                  loading: uploadingType == type.$1,
                  onUpload: () => pickAndUpload(type.$1),
                ),
                const SizedBox(height: 12),
              ],
            ],
          ),
        ),
      ),
    );
  }
}

class _UploadRow extends StatelessWidget {
  const _UploadRow({
    required this.title,
    required this.description,
    required this.icon,
    required this.upload,
    required this.loading,
    required this.onUpload,
  });

  final String title;
  final String description;
  final IconData icon;
  final Map<String, dynamic>? upload;
  final bool loading;
  final VoidCallback onUpload;

  @override
  Widget build(BuildContext context) {
    final errors = (upload?['parse_errors'] as List?) ?? [];
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(18),
        child: LayoutBuilder(
          builder: (context, constraints) {
            final info = Row(
              children: [
                Container(
                  width: 44,
                  height: 44,
                  decoration: BoxDecoration(color: const Color(0xFFE9F2FA), borderRadius: BorderRadius.circular(6)),
                  child: Icon(icon, color: const Color(0xFF245B85)),
                ),
                const SizedBox(width: 14),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(title, style: const TextStyle(fontWeight: FontWeight.w700)),
                      const SizedBox(height: 3),
                      Text(description, style: const TextStyle(color: Color(0xFF667085), fontSize: 13)),
                      if (upload != null) ...[
                        const SizedBox(height: 7),
                        Text(
                          '${upload!['original_filename']} • ${upload!['row_count']} rows • ${DateFormat.yMd().add_jm().format(DateTime.parse(upload!['uploaded_at'] as String).toLocal())}',
                          style: const TextStyle(fontSize: 12),
                        ),
                        if (errors.isNotEmpty)
                          Text('${errors.length} row errors require review', style: const TextStyle(color: Color(0xFFB42318), fontSize: 12)),
                      ],
                    ],
                  ),
                ),
              ],
            );
            final action = Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                StatusBadge(upload == null ? 'NOT UPLOADED' : errors.isEmpty ? 'PROCESSED' : 'CHECK ERRORS', tone: upload == null ? BadgeTone.neutral : errors.isEmpty ? BadgeTone.success : BadgeTone.warning),
                const SizedBox(width: 10),
                OutlinedButton.icon(
                  onPressed: loading ? null : onUpload,
                  icon: loading
                      ? const SizedBox(width: 17, height: 17, child: CircularProgressIndicator(strokeWidth: 2))
                      : const Icon(Icons.upload_file),
                  label: Text(upload == null ? 'Upload file' : 'Replace'),
                ),
              ],
            );
            if (constraints.maxWidth < 720) {
              return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [info, const SizedBox(height: 14), Align(alignment: Alignment.centerRight, child: action)]);
            }
            return Row(children: [Expanded(child: info), const SizedBox(width: 16), action]);
          },
        ),
      ),
    );
  }
}
