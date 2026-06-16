import 'package:flutter/material.dart';

import '../core/theme.dart';

class PageHeader extends StatelessWidget {
  const PageHeader({
    super.key,
    required this.title,
    required this.subtitle,
    this.actions = const [],
  });

  final String title;
  final String subtitle;
  final List<Widget> actions;

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        final heading = Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(title, style: Theme.of(context).textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w700)),
            const SizedBox(height: 4),
            Text(subtitle, style: Theme.of(context).textTheme.bodyMedium?.copyWith(color: Colors.blueGrey.shade600)),
          ],
        );
        if (constraints.maxWidth < 680 || actions.isEmpty) {
          return Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              heading,
              if (actions.isNotEmpty) ...[
                const SizedBox(height: 16),
                Wrap(spacing: 8, runSpacing: 8, children: actions),
              ],
            ],
          );
        }
        return Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Expanded(child: heading),
            Wrap(spacing: 8, runSpacing: 8, children: actions),
          ],
        );
      },
    );
  }
}

class StatusBadge extends StatelessWidget {
  const StatusBadge(this.label, {super.key, this.tone = BadgeTone.neutral});

  final String label;
  final BadgeTone tone;

  @override
  Widget build(BuildContext context) {
    final colors = switch (tone) {
      BadgeTone.success => (const Color(0xFFE8F5EE), const Color(0xFF176B3A)),
      BadgeTone.warning => (const Color(0xFFFFF4D6), const Color(0xFF875F00)),
      BadgeTone.danger => (const Color(0xFFFEECEB), const Color(0xFFB42318)),
      BadgeTone.info => (const Color(0xFFE9F2FA), const Color(0xFF245B85)),
      BadgeTone.neutral => (const Color(0xFFF0F2F5), const Color(0xFF475467)),
    };
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 5),
      decoration: BoxDecoration(color: colors.$1, borderRadius: BorderRadius.circular(14)),
      child: Text(
        label,
        style: TextStyle(color: colors.$2, fontWeight: FontWeight.w600, fontSize: 12),
      ),
    );
  }
}

enum BadgeTone { success, warning, danger, info, neutral }

class StatCard extends StatelessWidget {
  const StatCard({
    super.key,
    required this.label,
    required this.value,
    required this.icon,
    required this.color,
  });

  final String label;
  final String value;
  final IconData icon;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(20),
        child: Row(
          children: [
            Container(
              width: 44,
              height: 44,
              decoration: BoxDecoration(color: color.withValues(alpha: 0.12), borderRadius: BorderRadius.circular(6)),
              child: Icon(icon, color: color),
            ),
            const SizedBox(width: 14),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(value, style: Theme.of(context).textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w700)),
                  const SizedBox(height: 2),
                  Text(label, style: TextStyle(color: Colors.blueGrey.shade600)),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class LoadingPanel extends StatelessWidget {
  const LoadingPanel({super.key});

  @override
  Widget build(BuildContext context) => const Center(child: Padding(padding: EdgeInsets.all(48), child: CircularProgressIndicator()));
}

class ErrorPanel extends StatelessWidget {
  const ErrorPanel({super.key, required this.message, required this.onRetry});
  final String message;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.error_outline, color: Color(0xFFB42318), size: 36),
            const SizedBox(height: 12),
            Text(message, textAlign: TextAlign.center),
            const SizedBox(height: 16),
            OutlinedButton.icon(onPressed: onRetry, icon: const Icon(Icons.refresh), label: const Text('Retry')),
          ],
        ),
      ),
    );
  }
}

/// Human label + colour for a certificate lifecycle status string from the API.
StatusBadge lifecycleBadge(String status) {
  final label = status.replaceAll('_', ' ').toUpperCase();
  final tone = switch (status) {
    'downloaded' || 'delivered' || 'sent' => BadgeTone.success,
    'generated' || 'approved' => BadgeTone.info,
    'eligible' => BadgeTone.warning,
    'pending_attendance' || 'pending_test' || 'pending_survey' => BadgeTone.neutral,
    _ => BadgeTone.neutral,
  };
  return StatusBadge(label, tone: tone);
}

Widget checkIcon(bool value) => Icon(
      value ? Icons.check_circle : Icons.cancel,
      color: value ? const Color(0xFF248A52) : const Color(0xFFB42318),
      size: 20,
    );

const maxContentWidth = 1480.0;
const pagePadding = EdgeInsets.all(24);
const divider = Divider(height: 1, color: border);

