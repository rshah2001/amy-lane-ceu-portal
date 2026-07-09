import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../core/api_client.dart';
import '../core/theme.dart';
import '../widgets/common.dart';

class PublicSurveyPage extends StatefulWidget {
  const PublicSurveyPage({
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
  State<PublicSurveyPage> createState() => _PublicSurveyPageState();
}

class _PublicSurveyPageState extends State<PublicSurveyPage> {
  final formKey = GlobalKey<FormState>();
  final name = TextEditingController();
  final email = TextEditingController();
  Map<String, dynamic>? survey;
  final answers = <String, TextEditingController>{};
  String? error;
  bool submitted = false;
  bool saving = false;

  @override
  void initState() {
    super.initState();
    if (widget.prefillName != null) name.text = widget.prefillName!;
    if (widget.prefillEmail != null) email.text = widget.prefillEmail!;
    load();
  }

  Future<void> load() async {
    try {
      final result = await widget.api.get('/public/surveys/${widget.token}') as Map<String, dynamic>;
      for (final question in result['questions'] as List) {
        answers[question['id'] as String] = TextEditingController();
      }
      if (mounted) setState(() => survey = result);
    } catch (exception) {
      if (mounted) setState(() => error = exception.toString());
    }
  }

  Future<void> submit() async {
    if (!formKey.currentState!.validate()) return;
    // Questions are optional — only send what was actually written, but ask
    // for at least one answer so an entirely blank survey isn't recorded.
    final filledAnswers = {
      for (final entry in answers.entries)
        if (entry.value.text.trim().isNotEmpty) entry.key: entry.value.text.trim(),
    };
    if (filledAnswers.isEmpty) {
      setState(() => error = 'Please answer at least one question.');
      return;
    }
    setState(() {
      saving = true;
      error = null;
    });
    try {
      await widget.api.post('/public/surveys/${widget.token}', {
        'full_name': name.text.trim(),
        'email': email.text.trim(),
        'answers': filledAnswers,
      });
      if (mounted) setState(() => submitted = true);
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
        title: const Text('CEU Course Feedback'),
      ),
      body: Center(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(24),
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 720),
            child: error != null && survey == null
                ? ErrorPanel(message: error!, onRetry: load)
                : survey == null
                    ? const LoadingPanel()
                    : submitted
                        ? const Card(
                            child: Padding(
                              padding: EdgeInsets.all(40),
                              child: Column(
                                children: [
                                  Icon(Icons.check_circle, color: Color(0xFF248A52), size: 52),
                                  SizedBox(height: 16),
                                  Text('Thank you', style: TextStyle(fontSize: 26, fontWeight: FontWeight.w700)),
                                  SizedBox(height: 8),
                                  Text('Your feedback has been recorded.'),
                                ],
                              ),
                            ),
                          )
                        : Card(
                            child: Padding(
                              padding: const EdgeInsets.all(26),
                              child: Form(
                                key: formKey,
                                child: Column(
                                  crossAxisAlignment: CrossAxisAlignment.stretch,
                                  children: [
                                    Text(survey!['event_title'] as String, style: const TextStyle(fontSize: 24, fontWeight: FontWeight.w700)),
                                    const SizedBox(height: 5),
                                    Text(
                                      '${DateFormat.yMMMMd().format(DateTime.parse(survey!['event_date'] as String))} • ${survey!['presenter_name'] ?? 'CEU Training'}',
                                      style: const TextStyle(color: Color(0xFF667085)),
                                    ),
                                    const SizedBox(height: 24),
                                    TextFormField(
                                      controller: name,
                                      autofillHints: const [AutofillHints.name],
                                      textCapitalization: TextCapitalization.words,
                                      textInputAction: TextInputAction.next,
                                      decoration: const InputDecoration(labelText: 'Full name'),
                                      validator: (value) => value == null || value.trim().length < 2 ? 'Enter your name' : null,
                                    ),
                                    const SizedBox(height: 14),
                                    TextFormField(
                                      controller: email,
                                      keyboardType: TextInputType.emailAddress,
                                      autofillHints: const [AutofillHints.email],
                                      textInputAction: TextInputAction.next,
                                      decoration: const InputDecoration(labelText: 'Email address'),
                                      validator: emailValidator,
                                    ),
                                    const SizedBox(height: 18),
                                    const Text(
                                      'Answer as many questions as you like — every question is optional.',
                                      style: TextStyle(fontSize: 13, color: Color(0xFF667085)),
                                    ),
                                    for (final question in survey!['questions'] as List) ...[
                                      const SizedBox(height: 18),
                                      TextFormField(
                                        controller: answers[question['id']],
                                        maxLines: 3,
                                        textCapitalization: TextCapitalization.sentences,
                                        decoration: InputDecoration(labelText: question['label'] as String),
                                      ),
                                    ],
                                    if (error != null) ...[
                                      const SizedBox(height: 12),
                                      Text(error!, style: const TextStyle(color: Color(0xFFB42318))),
                                    ],
                                    const SizedBox(height: 24),
                                    ElevatedButton.icon(
                                      onPressed: saving ? null : submit,
                                      icon: const Icon(Icons.send_outlined),
                                      label: Text(saving ? 'Submitting...' : 'Submit feedback'),
                                    ),
                                  ],
                                ),
                              ),
                            ),
                          ),
          ),
        ),
      ),
    );
  }
}
