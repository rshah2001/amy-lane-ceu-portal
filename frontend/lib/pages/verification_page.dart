import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:url_launcher/url_launcher.dart';

import '../core/api_client.dart';
import '../widgets/common.dart';

class VerificationPage extends StatefulWidget {
  const VerificationPage({super.key, required this.api, this.initialNumber});
  final ApiClient api;
  final String? initialNumber;

  @override
  State<VerificationPage> createState() => _VerificationPageState();
}

class _VerificationPageState extends State<VerificationPage> {
  final controller = TextEditingController();
  Map<String, dynamic>? result;
  String? error;
  bool loading = false;

  @override
  void initState() {
    super.initState();
    if (widget.initialNumber != null && widget.initialNumber!.trim().isNotEmpty) {
      controller.text = widget.initialNumber!.trim();
      verify();
    }
  }

  @override
  void dispose() {
    controller.dispose();
    super.dispose();
  }

  Future<void> verify() async {
    final number = controller.text.trim();
    if (number.isEmpty) {
      const message = 'Enter a certificate number to verify.';
      setState(() {
        error = message;
        result = null;
      });
      announceToScreenReader(context, message);
      return;
    }
    setState(() {
      loading = true;
      error = null;
      result = null;
    });
    try {
      final response = await widget.api.get('/public/verify/${Uri.encodeComponent(number)}') as Map<String, dynamic>;
      if (mounted) setState(() => result = response);
    } catch (exception) {
      if (mounted) {
        final message = humanizeError(exception);
        setState(() => error = message);
        announceToScreenReader(context, message);
      }
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  void download() {
    final number = result?['certificate_number'] as String?;
    if (number == null) return;
    final url = '${widget.api.baseUrl}/public/verify/${Uri.encodeComponent(number)}/download';
    launchUrl(Uri.parse(url), webOnlyWindowName: '_blank');
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Scaffold(
      appBar: AppBar(
        backgroundColor: navy,
        foregroundColor: Colors.white,
        title: const Text('Verify a CEU Certificate'),
      ),
      body: Center(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(24),
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: maxPublicWidth),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Card(
                  child: Padding(
                    padding: const EdgeInsets.all(Space.xl),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        Heading(
                          child: Text(
                            'Certificate verification',
                            style: theme.textTheme.headlineSmall,
                          ),
                        ),
                        const SizedBox(height: Space.xxs + 2),
                        Text(
                          'Enter the certificate number to confirm it was issued by this program.',
                          style: theme.textTheme.bodyMedium
                              ?.copyWith(color: theme.portal.textSecondary),
                        ),
                        const SizedBox(height: Space.md + 2),
                        TextField(
                          controller: controller,
                          onSubmitted: (_) => verify(),
                          decoration: const InputDecoration(
                            labelText: 'Certificate number',
                            prefixIcon: Icon(Icons.confirmation_number_outlined),
                            hintText: 'e.g. CEU-00002-XXXXXXXXXX',
                          ),
                        ),
                        const SizedBox(height: Space.sm + 2),
                        ElevatedButton.icon(
                          onPressed: loading ? null : verify,
                          icon: loading
                              ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                              : const Icon(Icons.search),
                          label: const Text('Verify'),
                        ),
                      ],
                    ),
                  ),
                ),
                if (error != null) ...[
                  const SizedBox(height: Space.sm + 2),
                  FormErrorText(error!),
                ],
                if (result != null) ...[
                  const SizedBox(height: Space.md),
                  _ResultCard(result: result!, onDownload: download),
                ],
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _ResultCard extends StatelessWidget {
  const _ResultCard({required this.result, required this.onDownload});
  final Map<String, dynamic> result;
  final VoidCallback onDownload;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final colors = theme.portal;
    final valid = result['valid'] == true;
    // Three outcomes, not two. A revoked certificate exists and was really
    // issued — telling its holder "no certificate matches that number" would
    // send them back to a document that is no longer worth anything.
    final revokedAt = DateTime.tryParse(result['revoked_at']?.toString() ?? '');
    final revoked = !valid && result['status'] == 'revoked';
    if (revoked) {
      return Card(
        child: Padding(
          padding: const EdgeInsets.all(Space.xl),
          child: Semantics(
            liveRegion: true,
            container: true,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    ExcludeSemantics(child: Icon(Icons.gpp_bad, color: colors.danger, size: 30)),
                    const SizedBox(width: Space.sm),
                    Heading(
                      child: Text('Certificate revoked', style: theme.textTheme.titleMedium),
                    ),
                    const Spacer(),
                    lifecycleBadge('revoked'),
                  ],
                ),
                const SizedBox(height: Space.sm),
                Text(
                  'This certificate was issued and has since been withdrawn. It no longer '
                  'confirms CEU credit. Contact the issuing organization if you believe this '
                  'is a mistake.',
                  style: theme.textTheme.bodyMedium?.copyWith(color: colors.danger),
                ),
                const SizedBox(height: Space.md),
                if (result['attendee_name'] != null)
                  _row('Issued to', result['attendee_name'].toString()),
                if (result['event_title'] != null)
                  _row('Course', result['event_title'].toString()),
                _row('Certificate #', result['certificate_number']?.toString() ?? '—'),
                if (revokedAt != null)
                  _row('Revoked', DateFormat.yMMMMd().format(revokedAt.toLocal())),
              ],
            ),
          ),
        ),
      );
    }
    if (!valid) {
      return Card(
        child: Padding(
          padding: const EdgeInsets.all(Space.xl),
          // Verifying a certificate replaces the card in place with no
          // navigation, so the outcome has to be spoken.
          child: Semantics(
            liveRegion: true,
            container: true,
            child: Row(
              children: [
                ExcludeSemantics(child: Icon(Icons.cancel, color: colors.danger, size: 34)),
                const SizedBox(width: Space.sm + 2),
                const Expanded(
                  child: Text('No certificate matches that number. Check the number and try again.'),
                ),
              ],
            ),
          ),
        ),
      );
    }
    final date = DateTime.tryParse(result['event_date']?.toString() ?? '');
    final generated = DateTime.tryParse(result['generated_at']?.toString() ?? '');
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(Space.xl),
        child: Semantics(
          liveRegion: true,
          container: true,
          child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                ExcludeSemantics(child: Icon(Icons.verified, color: colors.success, size: 30)),
                const SizedBox(width: Space.sm),
                Heading(
                  child: Text('Valid certificate', style: theme.textTheme.titleMedium),
                ),
                const Spacer(),
                if (result['status'] != null) lifecycleBadge(result['status'] as String),
              ],
            ),
            const SizedBox(height: Space.md),
            _row('Holder', result['attendee_name']?.toString() ?? '—'),
            _row('Course', result['event_title']?.toString() ?? '—'),
            if (date != null) _row('Event date', DateFormat.yMMMMd().format(date)),
            if (result['ceu_hours'] != null) _row('CEU hours', result['ceu_hours'].toString()),
            if (result['course_instructor'] != null) _row('Instructor', result['course_instructor'].toString()),
            _row('Certificate #', result['certificate_number']?.toString() ?? '—'),
            if (generated != null) _row('Issued', DateFormat.yMMMMd().format(generated.toLocal())),
            const SizedBox(height: Space.md),
            OutlinedButton.icon(onPressed: onDownload, icon: const Icon(Icons.download_outlined), label: const Text('Download certificate PDF')),
          ],
          ),
        ),
      ),
    );
  }

  Widget _row(String label, String value) => Builder(
        builder: (context) {
          final theme = Theme.of(context);
          return Padding(
            padding: const EdgeInsets.symmetric(vertical: Space.xxs + 1),
            child: Semantics(
              container: true,
              label: '$label: $value',
              excludeSemantics: true,
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  ConstrainedBox(
                    constraints: const BoxConstraints(minWidth: 120, maxWidth: 180),
                    child: Text(
                      label,
                      style: theme.textTheme.bodyMedium
                          ?.copyWith(color: theme.portal.textSecondary),
                    ),
                  ),
                  Expanded(
                    child: Text(
                      value,
                      style: theme.textTheme.bodyMedium?.copyWith(fontWeight: FontWeight.w600),
                    ),
                  ),
                ],
              ),
            ),
          );
        },
      );
}
