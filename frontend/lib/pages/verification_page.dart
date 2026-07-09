import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:url_launcher/url_launcher.dart';

import '../core/api_client.dart';
import '../core/theme.dart';
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
      setState(() {
        error = 'Enter a certificate number to verify.';
        result = null;
      });
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
      if (mounted) setState(() => error = exception.toString());
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
            constraints: const BoxConstraints(maxWidth: 640),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Card(
                  child: Padding(
                    padding: const EdgeInsets.all(24),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        const Text('Certificate verification', style: TextStyle(fontSize: 22, fontWeight: FontWeight.w700)),
                        const SizedBox(height: 6),
                        const Text('Enter the certificate number to confirm it was issued by this program.',
                            style: TextStyle(color: Color(0xFF667085))),
                        const SizedBox(height: 18),
                        TextField(
                          controller: controller,
                          onSubmitted: (_) => verify(),
                          decoration: const InputDecoration(
                            labelText: 'Certificate number',
                            prefixIcon: Icon(Icons.confirmation_number_outlined),
                            hintText: 'e.g. CEU-00002-XXXXXXXXXX',
                          ),
                        ),
                        const SizedBox(height: 14),
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
                  const SizedBox(height: 14),
                  Text(error!, style: const TextStyle(color: Color(0xFFB42318))),
                ],
                if (result != null) ...[
                  const SizedBox(height: 16),
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
    final valid = result['valid'] == true;
    if (!valid) {
      return Card(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Row(
            children: const [
              Icon(Icons.cancel, color: Color(0xFFB42318), size: 34),
              SizedBox(width: 14),
              Expanded(child: Text('No certificate matches that number. Check the number and try again.')),
            ],
          ),
        ),
      );
    }
    final date = DateTime.tryParse(result['event_date']?.toString() ?? '');
    final generated = DateTime.tryParse(result['generated_at']?.toString() ?? '');
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                const Icon(Icons.verified, color: Color(0xFF248A52), size: 30),
                const SizedBox(width: 12),
                const Text('Valid certificate', style: TextStyle(fontSize: 18, fontWeight: FontWeight.w700)),
                const Spacer(),
                if (result['status'] != null) lifecycleBadge(result['status'] as String),
              ],
            ),
            const SizedBox(height: 16),
            _row('Holder', result['attendee_name']?.toString() ?? '—'),
            _row('Course', result['event_title']?.toString() ?? '—'),
            if (date != null) _row('Event date', DateFormat.yMMMMd().format(date)),
            if (result['ceu_hours'] != null) _row('CEU hours', result['ceu_hours'].toString()),
            if (result['course_instructor'] != null) _row('Instructor', result['course_instructor'].toString()),
            _row('Certificate #', result['certificate_number']?.toString() ?? '—'),
            if (generated != null) _row('Issued', DateFormat.yMMMMd().format(generated.toLocal())),
            const SizedBox(height: 16),
            OutlinedButton.icon(onPressed: onDownload, icon: const Icon(Icons.download_outlined), label: const Text('Download certificate PDF')),
          ],
        ),
      ),
    );
  }

  Widget _row(String label, String value) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 5),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            SizedBox(width: 120, child: Text(label, style: const TextStyle(color: Color(0xFF667085)))),
            Expanded(child: Text(value, style: const TextStyle(fontWeight: FontWeight.w600))),
          ],
        ),
      );
}
