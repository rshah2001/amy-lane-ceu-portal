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
      if (mounted) {
        final message = humanizeError(exception);
        setState(() => error = message);
        announceToScreenReader(context, message);
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    if (error != null) return ErrorPanel(message: error!, onRetry: load);
    if (settings == null) return const LoadingPanel(label: 'Loading settings');
    final colors = Theme.of(context).portal;
    final user = settings!['current_user'] as Map<String, dynamic>;
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
                title: 'Settings',
                subtitle: isAdmin ? 'Account and compliance environment configuration.' : 'Your account.',
              ),
              const SizedBox(height: Space.md + 2),
              Card(
                child: Column(
                  children: [
                    const ListTile(title: SectionTitle('Account')),
                    divider,
                    ListTile(leading: const Icon(Icons.person_outline), title: Text(user['full_name'] as String), subtitle: Text(user['email'] as String), trailing: StatusBadge((user['role'] as String).toUpperCase(), tone: BadgeTone.info)),
                  ],
                ),
              ),
              const SizedBox(height: Space.sm + 2),
              // Ops internals (email delivery, environment, retention) only
              // mean something to admins; presenters just need their account.
              if (isAdmin) ...[
                Card(
                  child: Column(
                    children: [
                      const ListTile(title: SectionTitle('Compliance configuration')),
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
                const SizedBox(height: Space.sm + 2),
                _SurveyTemplateCard(session: widget.session),
                const SizedBox(height: Space.sm + 2),
              ],
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(Space.md + 2),
                  child: Row(
                    children: [
                      ExcludeSemantics(
                        child: Icon(
                          isAdmin ? Icons.shield_outlined : Icons.help_outline,
                          color: colors.success,
                        ),
                      ),
                      const SizedBox(width: Space.sm),
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
      if (mounted) {
        final message = humanizeError(exception);
        setState(() => error = message);
        announceToScreenReader(context, message);
      }
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
      if (mounted) {
        final message = humanizeError(exception);
        setState(() => error = message);
        announceToScreenReader(context, message);
      }
    } finally {
      if (mounted) setState(() => saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Card(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const ListTile(title: SectionTitle('Default survey questions')),
          divider,
          Padding(
            padding: const EdgeInsets.all(Space.md + 2),
            child: questions == null && error == null
                ? const LoadingPanel(label: 'Loading default survey questions')
                : Form(
                    key: formKey,
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        Text(
                          'Every new event starts with these questions; each event keeps its own copy, '
                          'so changes here never affect existing events. Use "Multiple choice" for an '
                          'agree/disagree scale — the standard scale is pre-filled.',
                          style: theme.textTheme.labelMedium?.copyWith(
                            color: theme.portal.textSecondary,
                            fontWeight: FontWeight.w400,
                          ),
                        ),
                        const SizedBox(height: Space.sm),
                        for (var i = 0; i < (questions?.length ?? 0); i++) ...[
                          SurveyQuestionEditor(
                            index: i + 1,
                            draft: questions![i],
                            onRemove: () => setState(() => questions!.removeAt(i).dispose()),
                            onChanged: () => setState(() {}),
                          ),
                          const SizedBox(height: Space.xs + 2),
                        ],
                        if (error != null) ...[
                          FormErrorText(error!),
                          const SizedBox(height: Space.xs + 2),
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
    final theme = Theme.of(context);
    return ListTile(
      leading: ExcludeSemantics(child: Icon(icon)),
      title: Text(label),
      trailing: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 420),
        child: Text(
          value,
          textAlign: TextAlign.right,
          style: theme.textTheme.bodyMedium?.copyWith(fontWeight: FontWeight.w600),
        ),
      ),
    );
  }
}

