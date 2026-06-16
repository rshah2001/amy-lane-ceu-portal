import 'package:flutter/material.dart';

import '../core/session.dart';
import '../core/theme.dart';
import '../widgets/common.dart';

class SystemHealthPage extends StatefulWidget {
  const SystemHealthPage({super.key, required this.session});
  final SessionController session;

  @override
  State<SystemHealthPage> createState() => _SystemHealthPageState();
}

class _SystemHealthPageState extends State<SystemHealthPage> {
  Map<String, dynamic>? health;
  String? error;

  @override
  void initState() {
    super.initState();
    load();
  }

  Future<void> load() async {
    setState(() {
      health = null;
      error = null;
    });
    try {
      final result = await widget.session.api.get('/system/health') as Map<String, dynamic>;
      if (mounted) setState(() => health = result);
    } catch (exception) {
      if (mounted) setState(() => error = exception.toString());
    }
  }

  @override
  Widget build(BuildContext context) {
    if (error != null) return ErrorPanel(message: error!, onRetry: load);
    if (health == null) return const LoadingPanel();
    final h = health!;
    final cards = <Widget>[
      StatCard(label: 'Events created', value: '${h['events_created']}', icon: Icons.event_note_outlined, color: navy),
      StatCard(label: 'Total certificates', value: '${h['total_certificates']}', icon: Icons.workspace_premium_outlined, color: teal),
      StatCard(label: 'Certificates sent', value: '${h['certificates_sent']}', icon: Icons.send_outlined, color: gold),
      StatCard(label: 'Active users', value: '${h['active_users']}', icon: Icons.group_outlined, color: const Color(0xFF5F6CAF)),
      StatCard(label: 'Storage used', value: '${h['storage_human']}', icon: Icons.sd_storage_outlined, color: const Color(0xFF248A52)),
      StatCard(label: 'Email success rate', value: '${h['email_success_rate']}%', icon: Icons.mark_email_read_outlined, color: const Color(0xFF245B85)),
    ];
    return SingleChildScrollView(
      padding: pagePadding,
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: maxContentWidth),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              PageHeader(
                title: 'System Health',
                subtitle: 'Storage, certificate, user, and email delivery metrics.',
                actions: [OutlinedButton.icon(onPressed: load, icon: const Icon(Icons.refresh), label: const Text('Refresh'))],
              ),
              const SizedBox(height: 18),
              LayoutBuilder(
                builder: (context, constraints) {
                  final columns = constraints.maxWidth < 640 ? 1 : constraints.maxWidth < 980 ? 2 : 3;
                  final width = (constraints.maxWidth - (columns - 1) * 14) / columns;
                  return Wrap(
                    spacing: 14,
                    runSpacing: 14,
                    children: [for (final card in cards) SizedBox(width: width, child: card)],
                  );
                },
              ),
              const SizedBox(height: 18),
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(18),
                  child: Row(
                    children: [
                      const Icon(Icons.outgoing_mail, color: Color(0xFF245B85)),
                      const SizedBox(width: 12),
                      Expanded(
                        child: Text(
                          'Email delivery: ${h['emails_sent']} sent, ${h['emails_failed']} failed. '
                          'Success rate reflects certificate emails only.',
                          style: TextStyle(color: Colors.blueGrey.shade700),
                        ),
                      ),
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
