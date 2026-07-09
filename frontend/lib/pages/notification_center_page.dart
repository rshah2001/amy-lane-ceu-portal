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
      if (mounted) setState(() => error = exception.toString());
    }
  }

  Future<void> markAllRead() async {
    setState(() => markingAll = true);
    try {
      await widget.session.api.post('/notifications/read-all');
      await load();
    } catch (exception) {
      if (mounted) setState(() => error = exception.toString());
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
    return Padding(
      padding: pagePadding,
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 900),
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
                const SizedBox(height: 10),
                Text(error!, style: const TextStyle(color: Color(0xFFB42318))),
              ],
              const SizedBox(height: 16),
              Expanded(
                child: Card(
                  child: items == null
                      ? const LoadingPanel()
                      : items!.isEmpty
                          ? const EmptyState(
                              icon: Icons.notifications_none_outlined,
                              message: 'No notifications yet',
                              detail: 'Alerts from presenters and the compliance workflow will appear here.',
                            )
                          : ListView.separated(
                              padding: const EdgeInsets.all(6),
                              itemCount: items!.length,
                              separatorBuilder: (_, __) => divider,
                              itemBuilder: (context, index) {
                                final item = items![index];
                                final unread = item['is_read'] != true;
                                final created = DateTime.tryParse(item['created_at']?.toString() ?? '');
                                return ListTile(
                                  leading: Icon(
                                    unread ? Icons.mark_email_unread_outlined : Icons.mark_email_read_outlined,
                                    color: unread ? const Color(0xFF245B85) : const Color(0xFF98A2B3),
                                  ),
                                  title: Text(
                                    item['title'] as String,
                                    style: TextStyle(fontWeight: unread ? FontWeight.w700 : FontWeight.w500),
                                  ),
                                  subtitle: Column(
                                    crossAxisAlignment: CrossAxisAlignment.start,
                                    children: [
                                      if (item['body'] != null) Text(item['body'] as String),
                                      if (created != null)
                                        Text(DateFormat.yMMMd().add_jm().format(created.toLocal()),
                                            style: const TextStyle(fontSize: 11, color: Color(0xFF98A2B3))),
                                    ],
                                  ),
                                  trailing: item['event_id'] != null ? const Icon(Icons.chevron_right) : null,
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
