import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../core/api_client.dart';
import '../core/theme.dart';
import '../widgets/common.dart';

class CheckinPage extends StatefulWidget {
  const CheckinPage({
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
  State<CheckinPage> createState() => _CheckinPageState();
}

class _CheckinPageState extends State<CheckinPage> {
  final formKey = GlobalKey<FormState>();
  final name = TextEditingController();
  final email = TextEditingController();
  Map<String, dynamic>? event;
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

  @override
  void dispose() {
    name.dispose();
    email.dispose();
    super.dispose();
  }

  Future<void> load() async {
    try {
      final result = await widget.api.get('/public/checkin/${widget.token}') as Map<String, dynamic>;
      if (mounted) setState(() => event = result);
    } catch (exception) {
      if (mounted) setState(() => error = exception.toString());
    }
  }

  Future<void> submit() async {
    if (!formKey.currentState!.validate()) return;
    setState(() {
      saving = true;
      error = null;
    });
    try {
      await widget.api.post('/public/checkin/${widget.token}', {
        'full_name': name.text.trim(),
        'email': email.text.trim(),
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
        title: const Text('Event Check-In'),
      ),
      body: Center(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(24),
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 560),
            child: error != null
                ? ErrorPanel(message: error!, onRetry: load)
                : event == null
                    ? const LoadingPanel()
                    : submitted
                        ? const Card(
                            child: Padding(
                              padding: EdgeInsets.all(40),
                              child: Column(
                                children: [
                                  Icon(Icons.verified, color: Color(0xFF248A52), size: 52),
                                  SizedBox(height: 16),
                                  Text("You're checked in", style: TextStyle(fontSize: 24, fontWeight: FontWeight.w700)),
                                  SizedBox(height: 8),
                                  Text(
                                    'Your attendance has been recorded. Remember to complete the post-test to earn your certificate.',
                                    textAlign: TextAlign.center,
                                  ),
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
                                    Text(event!['event_title'] as String, style: const TextStyle(fontSize: 24, fontWeight: FontWeight.w700)),
                                    const SizedBox(height: 5),
                                    Text(
                                      '${DateFormat.yMMMMd().format(DateTime.parse(event!['event_date'] as String))}'
                                      '${event!['location'] != null ? ' • ${event!['location']}' : ''}',
                                      style: const TextStyle(color: Color(0xFF667085)),
                                    ),
                                    const SizedBox(height: 20),
                                    const Text('Confirm your attendance for this event.', style: TextStyle(color: Color(0xFF667085))),
                                    const SizedBox(height: 16),
                                    TextFormField(
                                      controller: name,
                                      decoration: const InputDecoration(labelText: 'Full name'),
                                      validator: (v) => v == null || v.trim().length < 2 ? 'Enter your name' : null,
                                    ),
                                    const SizedBox(height: 14),
                                    TextFormField(
                                      controller: email,
                                      keyboardType: TextInputType.emailAddress,
                                      decoration: const InputDecoration(labelText: 'Email address'),
                                      validator: (v) => v == null || !v.contains('@') ? 'Enter a valid email' : null,
                                    ),
                                    if (error != null) ...[
                                      const SizedBox(height: 12),
                                      Text(error!, style: const TextStyle(color: Color(0xFFB42318))),
                                    ],
                                    const SizedBox(height: 22),
                                    ElevatedButton.icon(
                                      onPressed: saving ? null : submit,
                                      icon: const Icon(Icons.how_to_reg),
                                      label: Text(saving ? 'Checking in...' : 'Check in'),
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
