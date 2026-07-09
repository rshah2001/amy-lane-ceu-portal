import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../core/api_client.dart';
import '../core/theme.dart';
import '../widgets/common.dart';

class PublicTestPage extends StatefulWidget {
  const PublicTestPage({
    super.key,
    required this.api,
    required this.token,
    this.prefillName,
    this.prefillEmail,
  });
  final ApiClient api;
  final String token;
  final String? prefillName;
  final String? prefillEmail;

  @override
  State<PublicTestPage> createState() => _PublicTestPageState();
}

class _PublicTestPageState extends State<PublicTestPage> {
  final formKey = GlobalKey<FormState>();
  final name = TextEditingController();
  final email = TextEditingController();
  Map<String, dynamic>? test;
  final selected = <String, int>{};
  String? error;
  bool saving = false;
  Map<String, dynamic>? result;

  @override
  void initState() {
    super.initState();
    if (widget.prefillName != null) name.text = widget.prefillName!;
    if (widget.prefillEmail != null) email.text = widget.prefillEmail!;
    load();
  }

  Future<void> load() async {
    try {
      final data = await widget.api.get('/public/tests/${widget.token}') as Map<String, dynamic>;
      if (mounted) setState(() => test = data);
    } catch (exception) {
      if (mounted) setState(() => error = exception.toString());
    }
  }

  Future<void> submit() async {
    if (!formKey.currentState!.validate()) return;
    final questions = test!['questions'] as List;
    if (selected.length < questions.length) {
      setState(() => error = 'Please answer every question before submitting.');
      return;
    }
    setState(() {
      saving = true;
      error = null;
    });
    try {
      final response = await widget.api.post('/public/tests/${widget.token}', {
        'full_name': name.text.trim(),
        'email': email.text.trim(),
        'answers': selected,
      }) as Map<String, dynamic>;
      if (mounted) setState(() => result = response);
    } catch (exception) {
      if (mounted) setState(() => error = exception.toString());
    } finally {
      if (mounted) setState(() => saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        backgroundColor: navy,
        foregroundColor: Colors.white,
        title: const Text('CEU Post-Test'),
      ),
      body: Center(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(24),
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 720),
            child: error != null && test == null
                ? ErrorPanel(message: error!, onRetry: load)
                : test == null
                    ? const LoadingPanel()
                    : result != null
                        ? _ResultCard(result: result!)
                        : _buildForm(),
          ),
        ),
      ),
    );
  }

  Widget _buildForm() {
    final questions = test!['questions'] as List;
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(26),
        child: Form(
          key: formKey,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text(test!['event_title'] as String, style: const TextStyle(fontSize: 24, fontWeight: FontWeight.w700)),
              const SizedBox(height: 5),
              Text(
                '${DateFormat.yMMMMd().format(DateTime.parse(test!['event_date'] as String))} • ${test!['presenter_name'] ?? 'CEU Training'}',
                style: const TextStyle(color: Color(0xFF667085)),
              ),
              const SizedBox(height: 6),
              const Text('A score of 80% or higher is required to earn your certificate.', style: TextStyle(fontSize: 13, color: Color(0xFF667085))),
              const SizedBox(height: 22),
              TextFormField(
                controller: name,
                decoration: const InputDecoration(labelText: 'Full name'),
                validator: (value) => value == null || value.trim().length < 2 ? 'Enter your name' : null,
              ),
              const SizedBox(height: 14),
              TextFormField(
                controller: email,
                keyboardType: TextInputType.emailAddress,
                decoration: const InputDecoration(labelText: 'Email address'),
                validator: emailValidator,
              ),
              for (var i = 0; i < questions.length; i++) ...[
                const SizedBox(height: 22),
                Text('${i + 1}. ${questions[i]['prompt']}', style: const TextStyle(fontWeight: FontWeight.w600)),
                RadioGroup<int>(
                  groupValue: selected[questions[i]['id']],
                  onChanged: (value) => setState(() => selected[questions[i]['id'] as String] = value!),
                  child: Column(
                    children: [
                      for (var c = 0; c < (questions[i]['choices'] as List).length; c++)
                        RadioListTile<int>(
                          contentPadding: EdgeInsets.zero,
                          dense: true,
                          value: c,
                          title: Text((questions[i]['choices'] as List)[c] as String),
                        ),
                    ],
                  ),
                ),
              ],
              if (error != null) ...[
                const SizedBox(height: 12),
                Text(error!, style: const TextStyle(color: Color(0xFFB42318))),
              ],
              const SizedBox(height: 24),
              ElevatedButton.icon(
                onPressed: saving ? null : submit,
                icon: const Icon(Icons.check_circle_outline),
                label: Text(saving ? 'Submitting...' : 'Submit test'),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _ResultCard extends StatelessWidget {
  const _ResultCard({required this.result});
  final Map<String, dynamic> result;

  @override
  Widget build(BuildContext context) {
    final passed = result['passed'] as bool;
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(40),
        child: Column(
          children: [
            Icon(passed ? Icons.verified : Icons.error_outline, color: passed ? const Color(0xFF248A52) : const Color(0xFFB42318), size: 56),
            const SizedBox(height: 16),
            Text('${result['score']}%', style: const TextStyle(fontSize: 34, fontWeight: FontWeight.w700)),
            const SizedBox(height: 4),
            Text('${result['correct']} of ${result['total']} correct', style: const TextStyle(color: Color(0xFF667085))),
            const SizedBox(height: 12),
            Text(
              passed
                  ? 'You passed. Your certificate will be issued after the organizer reviews the session.'
                  : 'A score of 80% is required. Please contact the organizer if you need to retake the test.',
              textAlign: TextAlign.center,
            ),
          ],
        ),
      ),
    );
  }
}
