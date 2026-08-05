import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../core/api_client.dart';
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

/// Consistent placeholder for lists and tables that have nothing to show yet.
class EmptyState extends StatelessWidget {
  const EmptyState({super.key, required this.icon, required this.message, this.detail});

  final IconData icon;
  final String message;
  final String? detail;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(icon, size: 40, color: const Color(0xFF98A2B3)),
            const SizedBox(height: 12),
            Text(message, textAlign: TextAlign.center, style: const TextStyle(fontWeight: FontWeight.w600)),
            if (detail != null) ...[
              const SizedBox(height: 6),
              Text(detail!, textAlign: TextAlign.center, style: const TextStyle(fontSize: 13, color: Color(0xFF667085))),
            ],
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

/// Turns any thrown object into something worth showing a training
/// coordinator. [ApiException] already carries a server-authored message, so
/// that is passed through — but its status code is used to add the bit the
/// server can't know: what the reader should do next. Anything else (socket
/// failures, JSON cast errors) stringifies into developer noise like
/// "ClientException with SocketException:", so it is replaced wholesale rather
/// than shown.
String humanizeError(Object exception) {
  if (exception is ApiException) {
    final message = exception.message.trim();
    return switch (exception.statusCode) {
      401 => 'Your session has expired. Please sign in again.',
      403 => message.isEmpty ? "You don't have permission to do that." : message,
      404 => message.isEmpty ? 'That item no longer exists. It may have been deleted.' : message,
      409 => message.isEmpty ? 'That conflicts with something already saved.' : message,
      429 => 'Too many attempts. Please wait a moment and try again.',
      >= 500 => 'The server had a problem completing that. Please try again — '
          'if it keeps happening, contact your administrator.',
      _ => message.isEmpty ? 'Something went wrong. Please try again.' : message,
    };
  }
  return 'Could not reach the server. Check your internet connection and try again.';
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

/// Validator for a required email field.
String? emailValidator(String? value) {
  final text = value?.trim() ?? '';
  if (text.isEmpty) return 'Enter an email address';
  return RegExp(r'^[^@\s]+@[^@\s]+\.[^@\s]+$').hasMatch(text) ? null : 'Enter a valid email address';
}

/// Validator for an optional email field (valid when left blank, but a
/// non-blank value must still look like an email address).
String? optionalEmailValidator(String? value) {
  final text = value?.trim() ?? '';
  if (text.isEmpty) return null;
  return RegExp(r'^[^@\s]+@[^@\s]+\.[^@\s]+$').hasMatch(text) ? null : 'Enter a valid email address';
}

/// Validator for an optional http(s) URL field (valid when left blank).
String? optionalUrlValidator(String? value) {
  final text = value?.trim() ?? '';
  if (text.isEmpty) return null;
  final uri = Uri.tryParse(text);
  final valid = uri != null && (uri.isScheme('http') || uri.isScheme('https')) && uri.host.isNotEmpty;
  return valid ? null : 'Enter a full link starting with http:// or https://';
}

const maxContentWidth = 1480.0;
const pagePadding = EdgeInsets.all(24);
const divider = Divider(height: 1, color: border);


/// One place for date rendering so every page reads the same way.
String formatDate(DateTime value) => DateFormat.yMMMd().format(value.toLocal());

String formatDateTime(DateTime value) {
  final local = value.toLocal();
  return '${DateFormat.yMMMd().format(local)} · ${DateFormat.jm().format(local)}';
}

/// Human wording for the internal event status values. "draft" and "review"
/// are developer jargon; Amy reads these as workflow stages.
(String, BadgeTone) eventStatusDisplay(String status) => switch (status) {
      'draft' => ('AWAITING DOCUMENTS', BadgeTone.info),
      'review' => ('IN REVIEW', BadgeTone.warning),
      'completed' => ('COMPLETED', BadgeTone.success),
      _ => (status.toUpperCase(), BadgeTone.neutral),
    };

/// Dismissible, plain-language error banner: replaces the raw
/// `exception.toString()` strings that used to sit permanently on pages.
class InlineAlert extends StatelessWidget {
  const InlineAlert({
    super.key,
    required this.message,
    this.onRetry,
    this.onDismiss,
  });

  final String message;
  final VoidCallback? onRetry;
  final VoidCallback? onDismiss;

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.only(bottom: 14),
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
      decoration: BoxDecoration(
        color: const Color(0xFFFEECEB),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: const Color(0xFFF4B4AE)),
      ),
      child: Row(
        children: [
          const Icon(Icons.error_outline, color: Color(0xFFB42318), size: 20),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              _humanize(message),
              style: const TextStyle(color: Color(0xFFB42318), fontSize: 13),
            ),
          ),
          if (onRetry != null)
            TextButton(onPressed: onRetry, child: const Text('Retry')),
          if (onDismiss != null)
            IconButton(
              onPressed: onDismiss,
              icon: const Icon(Icons.close, size: 17, color: Color(0xFFB42318)),
              tooltip: 'Dismiss',
            ),
        ],
      ),
    );
  }

  // Strip the exception-class prefixes users can't act on.
  static String _humanize(String raw) {
    var text = raw;
    for (final prefix in ['ApiException: ', 'ClientException: ', 'Exception: ']) {
      if (text.startsWith(prefix)) text = text.substring(prefix.length);
    }
    if (text.contains('Failed to fetch')) {
      return 'Could not reach the server. Check your connection and try again.';
    }
    return text;
  }
}
