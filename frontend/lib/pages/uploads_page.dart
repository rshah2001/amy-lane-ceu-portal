import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';

import '../core/api_client.dart';
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

  /// Shows a failure and speaks it. Uploading is the presenter's only task in
  /// the portal, so a silent failure leaves them with no idea whether the
  /// sign-in sheet landed.
  void _fail(Object exception) {
    if (!mounted) return;
    final message = humanizeError(exception);
    setState(() => error = message);
    announceToScreenReader(context, message);
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
      if (mounted) _fail(exception);
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
      if (!mounted) {
        // fall through to the finally block
      } else if (_isNothingImported(exception)) {
        // A file the parser could make nothing of is now a 400 rather than a
        // 201-with-a-notice, because an import that lands no rows must not be
        // allowed to wipe the results already on the event. For a presenter
        // that is still the same situation as before — their sheet needs
        // another go — so it keeps the dialog that explains what to do, not
        // the generic red banner a 400 would otherwise land in.
        _showNothingImportedDialog((exception as ApiException).message);
      } else {
        _fail(exception);
      }
    } finally {
      if (mounted) setState(() => uploadingType = null);
    }
  }

  /// Role-aware confirmation so nobody is left wondering whether the upload
  /// "took": presenters get told they're done, admins get pointed at review.
  /// File-level parser notices (row 0) — "no attendee names could be read", a
  /// sheet-format mismatch, OCR caveats — are spelled out instead of counted.
  void _showUploadFeedback(String type, Map<String, dynamic> response) {
    final colors = Theme.of(context).portal;
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
              ? Icon(Icons.warning_amber_outlined, color: colors.warning, size: 42)
              : Icon(Icons.check_circle_outline, color: colors.success, size: 42),
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

  /// Is this the backend's "nothing could be imported" refusal?
  ///
  /// Matched on the two server messages rather than on the bare 400, so a
  /// genuinely different bad request (an unsupported file type, an oversized
  /// file) still surfaces as an error instead of being dressed up as a
  /// routine "try again" dialog.
  bool _isNothingImported(Object exception) {
    if (exception is! ApiException || exception.statusCode != 400) return false;
    final message = exception.message;
    return message.startsWith('No attendee names could be read') ||
        message.startsWith('No rows from this file could be imported');
  }

  /// The upload landed nothing, so the event was left untouched. Both roles get
  /// told plainly that nothing changed — the reassurance matters most to a
  /// presenter re-uploading a photographed sign-in sheet, who would otherwise
  /// wonder whether they had just destroyed the roster.
  void _showNothingImportedDialog(String message) {
    final colors = Theme.of(context).portal;
    showDialog<void>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        icon: Icon(Icons.warning_amber_outlined, color: colors.warning, size: 42),
        title: const Text('Nothing was imported'),
        content: Text(
          '$message\n\nNothing already recorded for this event was changed.',
        ),
        actions: [
          FilledButton(
            onPressed: () => Navigator.of(dialogContext).pop(),
            child: const Text('Got it'),
          ),
        ],
      ),
    );
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
                padding: const EdgeInsets.symmetric(vertical: Space.xs),
                child: Text(
                  '$prefix${entry['message']}',
                  style: Theme.of(dialogContext).textTheme.bodySmall,
                ),
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
        style: Theme.of(context).textTheme.bodySmall,
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
      messenger.showSnackBar(SnackBar(content: Text('Could not open $filename. ${humanizeError(exception)}')));
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
    final theme = Theme.of(context);
    final isAdmin = widget.session.user!.isAdmin;
    return SingleChildScrollView(
      padding: pagePadding,
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: maxContentWidth),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              PageHeader(
                title: 'Upload Documents',
                subtitle: widget.event.title,
                actions: [OutlinedButton.icon(onPressed: load, icon: const Icon(Icons.refresh), label: const Text('Refresh'))],
              ),
              const SizedBox(height: Space.md + 2),
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(Space.md),
                  child: Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      ExcludeSemantics(
                        child: Icon(Icons.info_outline, color: theme.portal.info),
                      ),
                      const SizedBox(width: Space.xs + 2),
                      Expanded(
                        child: Text(
                          isAdmin
                              ? 'Upload CSV, XLSX, PDF, DOCX, or image scans. Image OCR is best-effort, so review extracted rows before approving certificates.'
                              : "Upload the signed attendance sheet from your session. A photo (JPG/PNG), scan (PDF), or spreadsheet all work. iPhone tip: HEIC photos aren't supported — share the photo as JPEG or scan to PDF from the Notes app.",
                          style: theme.textTheme.bodyMedium
                              ?.copyWith(color: theme.portal.textSecondary),
                        ),
                      ),
                    ],
                  ),
                ),
              ),
              if (error != null) ...[
                const SizedBox(height: Space.sm),
                InlineAlert(message: error!, onDismiss: () => setState(() => error = null)),
              ],
              const SizedBox(height: Space.md),
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
                const SizedBox(height: Space.sm),
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
    final theme = Theme.of(context);
    final colors = theme.portal;
    final errors = ((upload?['parse_errors'] as List?) ?? const []).cast<Map<String, dynamic>>();
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(18),
        child: LayoutBuilder(
          builder: (context, constraints) {
            final info = Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                ExcludeSemantics(
                  child: Container(
                    width: 44,
                    height: 44,
                    decoration: BoxDecoration(
                      color: colors.infoSurface,
                      borderRadius: BorderRadius.circular(Radii.sm),
                    ),
                    child: Icon(icon, color: colors.info),
                  ),
                ),
                const SizedBox(width: Space.sm + 2),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      SectionTitle(title, style: theme.textTheme.bodyMedium?.copyWith(fontWeight: FontWeight.w700)),
                      const SizedBox(height: 3),
                      Text(
                        description,
                        style: theme.textTheme.bodySmall?.copyWith(color: colors.textSecondary),
                      ),
                      if (formatSelector != null) ...[
                        const SizedBox(height: Space.sm),
                        formatSelector!,
                      ],
                      if (upload != null) ...[
                        const SizedBox(height: Space.xxs + 3),
                        Wrap(
                          crossAxisAlignment: WrapCrossAlignment.center,
                          children: [
                            // Was a bare InkWell around 12px underlined text —
                            // roughly a 190x16 target, and the only route to the
                            // uploaded file. TextButton carries a 48px padded
                            // target and real button semantics for free.
                            TextButton.icon(
                              onPressed: onOpen,
                              icon: const Icon(Icons.file_download_outlined, size: 15),
                              label: Text(
                                '${upload!['original_filename']}',
                                style: theme.textTheme.labelMedium?.copyWith(
                                  color: colors.info,
                                  decoration: TextDecoration.underline,
                                ),
                              ),
                              style: TextButton.styleFrom(
                                foregroundColor: colors.info,
                                padding: const EdgeInsets.symmetric(horizontal: Space.xs),
                                minimumSize: const Size(0, minTapTarget),
                              ),
                            ),
                            Text(
                              '• ${upload!['row_count']} rows • ${formatDateTime(DateTime.parse(upload!['uploaded_at'] as String))}',
                              style: theme.textTheme.labelMedium
                                  ?.copyWith(fontWeight: FontWeight.w400),
                            ),
                          ],
                        ),
                        if (errors.isNotEmpty)
                          // Same fix: this is a presenter's only way to find out
                          // which rows of their sign-in sheet failed to parse,
                          // and they are most likely on a phone.
                          TextButton.icon(
                            onPressed: () => onShowErrors(errors),
                            icon: const Icon(Icons.report_problem_outlined, size: 15),
                            label: Text(
                              '${errors.length} ${errors.length == 1 ? 'row' : 'rows'} could not be read — view details',
                              style: theme.textTheme.labelMedium?.copyWith(
                                color: colors.danger,
                                decoration: TextDecoration.underline,
                              ),
                            ),
                            style: TextButton.styleFrom(
                              foregroundColor: colors.danger,
                              padding: const EdgeInsets.symmetric(horizontal: Space.xs),
                              minimumSize: const Size(0, minTapTarget),
                              alignment: Alignment.centerLeft,
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
                const SizedBox(width: Space.xs + 2),
                OutlinedButton.icon(
                  onPressed: loading ? null : onUpload,
                  icon: loading
                      ? const SizedBox(width: 17, height: 17, child: CircularProgressIndicator(strokeWidth: 2))
                      : const Icon(Icons.upload_file),
                  label: Text(upload == null ? 'Upload file for $title' : 'Replace $title'),
                ),
              ],
            );
            if (constraints.maxWidth < 720) {
              return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [info, const SizedBox(height: Space.sm + 2), Align(alignment: Alignment.centerRight, child: action)]);
            }
            return Row(crossAxisAlignment: CrossAxisAlignment.start, children: [Expanded(child: info), const SizedBox(width: Space.md), action]);
          },
        ),
      ),
    );
  }
}
