import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';

import '../core/file_download.dart';
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

  /// Optional hint telling the backend what kind of sign-in sheet is being
  /// uploaded, so parsing can pick the right header row. 'other' sends nothing.
  String sheetFormat = 'other';

  static const sheetFormats = [
    ('spreadsheet', 'Spreadsheet (Excel/CSV)'),
    ('word', 'Word document'),
    ('virtual_meeting', 'Virtual meeting export (Zoom/Teams)'),
    ('other', 'Other / not sure'),
  ];

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
      allowedExtensions: const ['csv', 'xlsx', 'pdf', 'docx', 'png', 'jpg', 'jpeg'],
      withData: true,
    );
    final file = result?.files.single;
    if (file?.bytes == null) return;
    setState(() {
      uploadingType = type;
      error = null;
    });
    try {
      final response = await widget.session.api.uploadFile(
        '/events/${widget.event.id}/uploads/$type',
        file!.bytes!,
        file.name,
        // Only the attendance / sign-in sheet has the format picker; leaving
        // it on "Other / not sure" sends no hint, keeping default parsing.
        fields: type == 'attendance' && sheetFormat != 'other'
            ? {'sheet_format': sheetFormat}
            : null,
      ) as Map<String, dynamic>;
      await load();
      if (mounted) _showUploadFeedback(type, response);
    } catch (exception) {
      if (mounted) setState(() => error = exception.toString());
    } finally {
      if (mounted) setState(() => uploadingType = null);
    }
  }

  /// Role-aware confirmation so nobody is left wondering whether the upload
  /// "took": presenters get told they're done, admins get pointed at review.
  /// File-level parser notices (row 0) — "no attendee names could be read", a
  /// sheet-format mismatch, OCR caveats — are spelled out instead of counted.
  void _showUploadFeedback(String type, Map<String, dynamic> response) {
    final rowCount = response['row_count'] ?? 0;
    final parseErrors = ((response['parse_errors'] as List?) ?? const []).cast<Map<String, dynamic>>();
    final fileNotes = [
      for (final entry in parseErrors)
        if (entry['row'] == 0) entry['message'].toString(),
    ];
    final rowErrorCount = parseErrors.length - fileNotes.length;
    final noAttendees = fileNotes.any((note) => note.startsWith('No attendee names'));
    final noteText = fileNotes.isEmpty ? '' : ' ${fileNotes.join(' ')}';
    final errorNote = rowErrorCount == 0
        ? ''
        : ' $rowErrorCount ${rowErrorCount == 1 ? 'row' : 'rows'} could not be read — view details.';
    if (!widget.session.user!.isAdmin) {
      showDialog<void>(
        context: context,
        builder: (dialogContext) => AlertDialog(
          icon: noAttendees
              ? const Icon(Icons.warning_amber_outlined, color: Color(0xFFB54708), size: 42)
              : const Icon(Icons.check_circle_outline, color: Color(0xFF248A52), size: 42),
          title: Text(noAttendees ? 'Sign-in sheet needs attention' : 'Sign-in sheet received'),
          content: Text(
            noAttendees
                ? 'Your file was uploaded, but no attendee names could be read from it. '
                    'Pick the matching sheet format and upload it again, or convert the '
                    'sheet to a spreadsheet (CSV/XLSX) with a "Name" column.$errorNote'
                : 'Sign-in sheet received ($rowCount rows). The compliance team has been '
                    'notified — nothing else is needed from you.$noteText$errorNote',
          ),
          actions: [
            if (parseErrors.isNotEmpty)
              TextButton(
                onPressed: () {
                  Navigator.of(dialogContext).pop();
                  _showParseErrors(parseErrors);
                },
                child: const Text('View details'),
              ),
            FilledButton(onPressed: () => Navigator.of(dialogContext).pop(), child: const Text('Done')),
          ],
        ),
      );
    } else {
      final label = allTypes.firstWhere((t) => t.$1 == type, orElse: () => allTypes[1]).$2;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
        content: Text(
          '$label processed — $rowCount rows.'
          '${noAttendees ? '' : ' Review compliance next.'}$noteText$errorNote',
        ),
        duration: Duration(seconds: fileNotes.isEmpty ? 6 : 10),
        action: parseErrors.isEmpty
            ? null
            : SnackBarAction(label: 'View details', onPressed: () => _showParseErrors(parseErrors)),
      ));
    }
  }

  /// Lists every row the parser could not read, so "N row errors" is
  /// actionable instead of a dead end.
  void _showParseErrors(List<Map<String, dynamic>> parseErrors) {
    showDialog<void>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: Text('${parseErrors.length} ${parseErrors.length == 1 ? 'row' : 'rows'} could not be read'),
        content: SizedBox(
          width: 480,
          child: ListView.separated(
            shrinkWrap: true,
            itemCount: parseErrors.length,
            separatorBuilder: (context, index) => divider,
            itemBuilder: (_, index) {
              final entry = parseErrors[index];
              // Row 0 marks a file-level notice, not a specific row.
              final prefix = entry['row'] == 0 ? '' : 'Row ${entry['row']}: ';
              return Padding(
                padding: const EdgeInsets.symmetric(vertical: 8),
                child: Text('$prefix${entry['message']}', style: const TextStyle(fontSize: 13)),
              );
            },
          ),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.of(dialogContext).pop(), child: const Text('Close')),
        ],
      ),
    );
  }

  /// Sheet-format picker for the attendance / sign-in row: an optional hint
  /// that helps the backend find the attendee table in the uploaded document.
  Widget _formatSelector() {
    return ConstrainedBox(
      constraints: const BoxConstraints(maxWidth: 360),
      child: DropdownButtonFormField<String>(
        initialValue: sheetFormat,
        isDense: true,
        style: const TextStyle(fontSize: 13, color: Color(0xFF344054)),
        decoration: const InputDecoration(
          labelText: 'What kind of sheet is this? (optional)',
          border: OutlineInputBorder(),
          isDense: true,
          contentPadding: EdgeInsets.symmetric(horizontal: 12, vertical: 10),
        ),
        items: [
          for (final format in sheetFormats)
            DropdownMenuItem(value: format.$1, child: Text(format.$2)),
        ],
        onChanged: uploadingType != null
            ? null
            : (value) => setState(() => sheetFormat = value ?? 'other'),
      ),
    );
  }

  /// Downloads the originally uploaded file (e.g. a sign-in sheet) so it can
  /// be reopened after the fact.
  Future<void> openUpload(Map<String, dynamic> upload) async {
    final messenger = ScaffoldMessenger.of(context);
    final filename = upload['original_filename']?.toString() ?? 'upload-${upload['id']}';
    try {
      final bytes = await widget.session.api.download('/events/${widget.event.id}/uploads/${upload['id']}/download');
      downloadBytes(bytes, filename, _contentTypeFor(filename));
    } catch (exception) {
      messenger.showSnackBar(SnackBar(content: Text('Could not open $filename: $exception')));
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
    final isAdmin = widget.session.user!.isAdmin;
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
                          isAdmin
                              ? 'Upload CSV, XLSX, PDF, DOCX, or image scans. Image OCR is best-effort, so review extracted rows before approving certificates.'
                              : "Upload the signed attendance sheet from your session. A photo (JPG/PNG), scan (PDF), or spreadsheet all work. iPhone tip: HEIC photos aren't supported — share the photo as JPEG or scan to PDF from the Notes app.",
                          style: TextStyle(color: Colors.blueGrey.shade700),
                        ),
                      ),
                    ],
                  ),
                ),
              ),
              if (error != null) ...[
                const SizedBox(height: 12),
                InlineAlert(message: error!, onDismiss: () => setState(() => error = null)),
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
                  onOpen: latestFor(type.$1) == null ? null : () => openUpload(latestFor(type.$1)!),
                  onShowErrors: _showParseErrors,
                  formatSelector: type.$1 == 'attendance' ? _formatSelector() : null,
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

/// Content type for re-downloading an original upload, keyed off its extension.
String _contentTypeFor(String filename) {
  final extension = filename.contains('.') ? filename.split('.').last.toLowerCase() : '';
  return switch (extension) {
    'csv' => 'text/csv',
    'xlsx' => 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'pdf' => 'application/pdf',
    'docx' => 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'png' => 'image/png',
    'jpg' || 'jpeg' => 'image/jpeg',
    _ => 'application/octet-stream',
  };
}

class _UploadRow extends StatelessWidget {
  const _UploadRow({
    required this.title,
    required this.description,
    required this.icon,
    required this.upload,
    required this.loading,
    required this.onUpload,
    required this.onOpen,
    required this.onShowErrors,
    this.formatSelector,
  });

  final String title;
  final String description;
  final IconData icon;
  final Map<String, dynamic>? upload;
  final bool loading;
  final VoidCallback onUpload;

  /// Optional sheet-format picker (attendance / sign-in sheet only).
  final Widget? formatSelector;

  /// Downloads the original uploaded file; null while nothing is uploaded.
  final VoidCallback? onOpen;

  /// Opens the row-by-row parse error dialog.
  final void Function(List<Map<String, dynamic>>) onShowErrors;

  @override
  Widget build(BuildContext context) {
    final errors = ((upload?['parse_errors'] as List?) ?? const []).cast<Map<String, dynamic>>();
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
                      if (formatSelector != null) ...[
                        const SizedBox(height: 12),
                        formatSelector!,
                      ],
                      if (upload != null) ...[
                        const SizedBox(height: 7),
                        Wrap(
                          crossAxisAlignment: WrapCrossAlignment.center,
                          children: [
                            Tooltip(
                              message: 'Open the original file',
                              child: InkWell(
                                onTap: onOpen,
                                child: Row(
                                  mainAxisSize: MainAxisSize.min,
                                  children: [
                                    const Icon(Icons.file_download_outlined, size: 15, color: Color(0xFF245B85)),
                                    const SizedBox(width: 3),
                                    Text(
                                      '${upload!['original_filename']}',
                                      style: const TextStyle(
                                        fontSize: 12,
                                        color: Color(0xFF245B85),
                                        fontWeight: FontWeight.w600,
                                        decoration: TextDecoration.underline,
                                      ),
                                    ),
                                  ],
                                ),
                              ),
                            ),
                            Text(
                              '  • ${upload!['row_count']} rows • ${formatDateTime(DateTime.parse(upload!['uploaded_at'] as String))}',
                              style: const TextStyle(fontSize: 12),
                            ),
                          ],
                        ),
                        if (errors.isNotEmpty)
                          Padding(
                            padding: const EdgeInsets.only(top: 4),
                            child: InkWell(
                              onTap: () => onShowErrors(errors),
                              child: Text(
                                '${errors.length} ${errors.length == 1 ? 'row' : 'rows'} could not be read — view details',
                                style: const TextStyle(
                                  color: Color(0xFFB42318),
                                  fontSize: 12,
                                  fontWeight: FontWeight.w600,
                                  decoration: TextDecoration.underline,
                                ),
                              ),
                            ),
                          ),
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
