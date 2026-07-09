import 'package:flutter/material.dart';

import '../core/session.dart';
import '../widgets/common.dart';

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

