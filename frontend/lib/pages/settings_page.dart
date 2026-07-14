import 'package:flutter/material.dart';

import '../core/session.dart';
import '../widgets/common.dart';
import '../widgets/survey_question_editor.dart';

class SettingsPage extends StatefulWidget {
  const SettingsPage({super.key, required this.session});
  final SessionController session;

  @override
  State<SettingsPage> createState() => _SettingsPageState();
}

class _SettingsPageState extends State<SettingsPage> {
  Map<String, dynamic>? settings;
  String? error;

  @override
  void initState() {
    super.initState();
    load();
  }

  Future<void> load() async {
    try {
      final result = await widget.session.api.get('/settings') as Map<String, dynamic>;
      if (mounted) setState(() => settings = result);
    } catch (exception) {
      if (mounted) setState(() => error = exception.toString());
    }
  }

  @override
  Widget build(BuildContext context) {
    if (error != null) return ErrorPanel(message: error!, onRetry: load);
    if (settings == null) return const LoadingPanel();
    final user = settings!['current_user'] as Map<String, dynamic>;
    final isAdmin = widget.session.user!.isAdmin;
    return SingleChildScrollView(
      padding: pagePadding,
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 900),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              PageHeader(
                title: 'Settings',
                subtitle: isAdmin ? 'Account and compliance environment configuration.' : 'Your account.',
              ),
              const SizedBox(height: 18),
              Card(
                child: Column(
                  children: [
                    const ListTile(title: Text('Account', style: TextStyle(fontWeight: FontWeight.w700))),
                    divider,
                    ListTile(leading: const Icon(Icons.person_outline), title: Text(user['full_name'] as String), subtitle: Text(user['email'] as String), trailing: StatusBadge((user['role'] as String).toUpperCase(), tone: BadgeTone.info)),
                  ],
                ),
              ),
              const SizedBox(height: 14),
              // Ops internals (email delivery, environment, retention) only
              // mean something to admins; presenters just need their account.
              if (isAdmin) ...[
                Card(
                  child: Column(
                    children: [
                      const ListTile(title: Text('Compliance configuration', style: TextStyle(fontWeight: FontWeight.w700))),
                      divider,
                      _SettingRow(icon: Icons.business_outlined, label: 'Certificate issuer', value: settings!['organization'].toString()),
                      divider,
                      _SettingRow(icon: Icons.archive_outlined, label: 'Audit retention', value: '${settings!['retention_years']} years'),
                      divider,
                      _SettingRow(
                        icon: Icons.outgoing_mail,
                        label: 'Email delivery',
                        value: '${settings!['email_delivery_mode']} (${settings!['smtp_configured'] == true ? 'SMTP configured' : 'no SMTP credentials'})',
                      ),
                      divider,
                      _SettingRow(icon: Icons.cloud_outlined, label: 'Environment', value: settings!['environment'].toString()),
                    ],
                  ),
                ),
                const SizedBox(height: 14),
                _SurveyTemplateCard(session: widget.session),
                const SizedBox(height: 14),
              ],
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(18),
                  child: Row(
                    children: [
                      Icon(isAdmin ? Icons.shield_outlined : Icons.help_outline, color: const Color(0xFF176B3A)),
                      const SizedBox(width: 12),
                      Expanded(
                        child: Text(
                          isAdmin
                              ? 'Uploaded files, compliance decisions, certificates, delivery attempts, and audit actions are retained according to the configured policy.'
                              : 'Questions about your account? Contact your NMEDA administrator.',
                        ),
                      ),
                      OutlinedButton.icon(onPressed: widget.session.logout, icon: const Icon(Icons.logout), label: const Text('Sign out')),
                    ],
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// Admin editor for the default survey questions new events start with.
/// Existing events keep their own copy — this only affects events created
/// after saving.
class _SurveyTemplateCard extends StatefulWidget {
  const _SurveyTemplateCard({required this.session});
  final SessionController session;

  @override
  State<_SurveyTemplateCard> createState() => _SurveyTemplateCardState();
}

class _SurveyTemplateCardState extends State<_SurveyTemplateCard> {
  final formKey = GlobalKey<FormState>();
  List<SurveyQuestionDraft>? questions;
  String? error;
  bool saving = false;

  @override
  void initState() {
    super.initState();
    load();
  }

  @override
  void dispose() {
    for (final question in questions ?? const <SurveyQuestionDraft>[]) {
      question.dispose();
    }
    super.dispose();
  }

  Future<void> load() async {
    try {
      final result = await widget.session.api.get('/settings/survey-template') as Map<String, dynamic>;
      if (mounted) {
        setState(() => questions = [
              for (final question in (result['questions'] as List).cast<Map<String, dynamic>>())
                SurveyQuestionDraft.fromJson(question),
            ]);
      }
    } catch (exception) {
      if (mounted) setState(() => error = exception.toString());
    }
  }

  Future<void> save() async {
    if (!formKey.currentState!.validate()) return;
    setState(() {
      saving = true;
      error = null;
    });
    try {
      final result = await widget.session.api.put('/settings/survey-template', {
        'questions': [for (var i = 0; i < questions!.length; i++) questions![i].toJson('s${i + 1}')],
      }) as Map<String, dynamic>;
      if (!mounted) return;
      for (final question in questions!) {
        question.dispose();
      }
      setState(() => questions = [
            for (final question in (result['questions'] as List).cast<Map<String, dynamic>>())
              SurveyQuestionDraft.fromJson(question),
          ]);
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Default survey questions saved — they apply to newly created events.')),
      );
    } catch (exception) {
      if (mounted) setState(() => error = exception.toString());
    } finally {
      if (mounted) setState(() => saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const ListTile(title: Text('Default survey questions', style: TextStyle(fontWeight: FontWeight.w700))),
          divider,
          Padding(
            padding: const EdgeInsets.all(18),
            child: questions == null && error == null
                ? const LoadingPanel()
                : Form(
                    key: formKey,
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        const Text(
                          'Every new event starts with these questions; each event keeps its own copy, '
                          'so changes here never affect existing events. Use "Multiple choice" for an '
                          'agree/disagree scale — the standard scale is pre-filled.',
                          style: TextStyle(fontSize: 12, color: Color(0xFF667085)),
                        ),
                        const SizedBox(height: 12),
                        for (var i = 0; i < (questions?.length ?? 0); i++) ...[
                          SurveyQuestionEditor(
                            index: i + 1,
                            draft: questions![i],
                            onRemove: () => setState(() => questions!.removeAt(i).dispose()),
                            onChanged: () => setState(() {}),
                          ),
                          const SizedBox(height: 10),
                        ],
                        if (error != null) ...[
                          Text(error!, style: const TextStyle(color: Color(0xFFB42318))),
                          const SizedBox(height: 10),
                        ],
                        Row(
                          children: [
                            OutlinedButton.icon(
                              onPressed: () => setState(() => (questions ??= []).add(SurveyQuestionDraft())),
                              icon: const Icon(Icons.add),
                              label: const Text('Add question'),
                            ),
                            const Spacer(),
                            ElevatedButton.icon(
                              onPressed: saving || questions == null ? null : save,
                              icon: const Icon(Icons.save_outlined),
                              label: Text(saving ? 'Saving...' : 'Save defaults'),
                            ),
                          ],
                        ),
                      ],
                    ),
                  ),
          ),
        ],
      ),
    );
  }
}

class _SettingRow extends StatelessWidget {
  const _SettingRow({required this.icon, required this.label, required this.value});
  final IconData icon;
  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return ListTile(
      leading: Icon(icon),
      title: Text(label),
      trailing: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 420),
        child: Text(value, textAlign: TextAlign.right, style: const TextStyle(fontWeight: FontWeight.w600)),
      ),
    );
  }
}

