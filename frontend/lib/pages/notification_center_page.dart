import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:intl/intl.dart';

import '../core/session.dart';
import '../widgets/common.dart';

class NotificationCenterPage extends StatefulWidget {
  const NotificationCenterPage({super.key, required this.session});
  final SessionController session;

  @override
  State<NotificationCenterPage> createState() => _NotificationCenterPageState();
}

class _NotificationCenterPageState extends State<NotificationCenterPage> {
  List<Map<String, dynamic>>? items;
  String? error;
  bool markingAll = false;

  @override
  void initState() {
    super.initState();
    load();
  }

  Future<void> load() async {
    setState(() {
      items = null;
      error = null;
    });
    try {
      final result = await widget.session.api.get('/notifications?limit=100') as List;
      if (mounted) setState(() => items = result.cast<Map<String, dynamic>>());
    } catch (exception) {
      if (mounted) _fail(exception);
    }
  }

  void _fail(Object exception) {
    if (!mounted) return;
    final message = humanizeError(exception);
    setState(() => error = message);
    announceToScreenReader(context, message);
  }

  Future<void> markAllRead() async {
    setState(() => markingAll = true);
    try {
      await widget.session.api.post('/notifications/read-all');
      await load();
    } catch (exception) {
      if (mounted) _fail(exception);
    } finally {
      if (mounted) setState(() => markingAll = false);
    }
  }

  Future<void> open(Map<String, dynamic> item) async {
    try {
      if (item['is_read'] != true) {
        await widget.session.api.post('/notifications/${item['id']}/read');
      }
    } catch (_) {/* non-fatal */}
    if (!mounted) return;
    final eventId = item['event_id'];
    if (eventId != null) {
      context.go('/events/$eventId');
    } else {
      load();
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final colors = theme.portal;
    return Padding(
      padding: pagePadding,
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: maxContentWidth),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              PageHeader(
                title: 'Notifications',
                subtitle: 'Alerts from presenters and the compliance workflow.',
                actions: [
                  OutlinedButton.icon(onPressed: load, icon: const Icon(Icons.refresh), label: const Text('Refresh')),
                  ElevatedButton.icon(
                    onPressed: items == null || items!.isEmpty || markingAll ? null : markAllRead,
                    icon: const Icon(Icons.done_all),
                    label: Text(markingAll ? 'Marking...' : 'Mark all read'),
                  ),
                ],
              ),
              if (error != null) ...[
                const SizedBox(height: Space.xs + 2),
                FormErrorText(error!),
              ],
              const SizedBox(height: Space.md),
              Expanded(
                child: Card(
                  child: items == null
                      ? const LoadingPanel(label: 'Loading notifications')
                      : items!.isEmpty
                          ? const EmptyState(
                              icon: Icons.notifications_none_outlined,
                              message: 'No notifications yet',
                              detail: 'Alerts from presenters and the compliance workflow will appear here.',
                            )
                          : ListView.separated(
                              padding: const EdgeInsets.all(Space.xxs + 2),
                              itemCount: items!.length,
                              separatorBuilder: (_, __) => divider,
                              itemBuilder: (context, index) {
                                final item = items![index];
                                final unread = item['is_read'] != true;
                                final created = DateTime.tryParse(item['created_at']?.toString() ?? '');
                                return ListTile(
                                  leading: Semantics(
                                    // Read state was carried by icon colour
                                    // alone; the shape differs too, but neither
                                    // is announced.
                                    label: unread ? 'Unread' : 'Read',
                                    excludeSemantics: true,
                                    child: Icon(
                                      unread ? Icons.mark_email_unread_outlined : Icons.mark_email_read_outlined,
                                      color: unread ? colors.info : colors.textTertiary,
                                    ),
                                  ),
                                  title: Text(
                                    item['title'] as String,
                                    style: theme.textTheme.bodyMedium?.copyWith(
                                      fontWeight: unread ? FontWeight.w700 : FontWeight.w500,
                                    ),
                                  ),
                                  subtitle: Column(
                                    crossAxisAlignment: CrossAxisAlignment.start,
                                    children: [
                                      if (item['body'] != null) Text(item['body'] as String),
                                      if (created != null)
                                        Text(
                                          DateFormat.yMMMd().add_jm().format(created.toLocal()),
                                          // 11px timestamps were #98A2B3 at
                                          // 2.58:1 — the worst offender in the
                                          // app, since small text gets no AA
                                          // discount. textTertiary is 4.97:1.
                                          style: theme.textTheme.labelSmall?.copyWith(
                                            color: colors.textTertiary,
                                            fontWeight: FontWeight.w400,
                                          ),
                                        ),
                                    ],
                                  ),
                                  trailing: item['event_id'] != null
                                      ? const ExcludeSemantics(child: Icon(Icons.chevron_right))
                                      : null,
                                  onTap: () => open(item),
                                );
                              },
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
