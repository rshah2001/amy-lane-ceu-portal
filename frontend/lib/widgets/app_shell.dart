import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../core/session.dart';
import '../core/theme.dart';

class AppShell extends StatefulWidget {
  const AppShell({
    super.key,
    required this.session,
    required this.location,
    required this.child,
  });

  final SessionController session;
  final String location;
  final Widget child;

  @override
  State<AppShell> createState() => _AppShellState();
}

class _AppShellState extends State<AppShell> {
  int unreadNotifications = 0;

  @override
  void initState() {
    super.initState();
    _refreshUnreadCount();
  }

  @override
  void didUpdateWidget(AppShell oldWidget) {
    super.didUpdateWidget(oldWidget);
    // Refresh on navigation so the badge stays honest without a polling loop.
    if (oldWidget.location != widget.location) _refreshUnreadCount();
  }

  /// Best-effort unread badge for the Notifications nav item (admins only).
  Future<void> _refreshUnreadCount() async {
    if (!widget.session.user!.isAdmin) return;
    try {
      final result = await widget.session.api.get('/notifications/unread-count') as Map<String, dynamic>;
      final count = (result['unread'] as num?)?.toInt() ?? 0;
      if (mounted && count != unreadNotifications) setState(() => unreadNotifications = count);
    } catch (_) {
      // The badge is a hint, never worth an error state.
    }
  }

  List<_NavItem> get _navItems => [
        const _NavItem('/dashboard', 'Dashboard', Icons.space_dashboard_outlined),
        const _NavItem('/events', 'Events', Icons.event_note_outlined),
        const _NavItem('/attendees', 'Attendee Search', Icons.person_search_outlined),
        if (widget.session.user!.isAdmin) ...[
          const _NavItem('/certificates', 'Certificate Center', Icons.workspace_premium_outlined),
          const _NavItem('/survey-responses', 'Survey Responses', Icons.rate_review_outlined),
          _NavItem('/notifications', 'Notifications', Icons.notifications_outlined, badgeCount: unreadNotifications),
          const _NavItem('/reports', 'Audit Reports', Icons.assessment_outlined),
          const _NavItem('/system', 'System Health', Icons.monitor_heart_outlined),
          const _NavItem('/users', 'Users', Icons.group_outlined),
        ],
        const _NavItem('/settings', 'Settings', Icons.settings_outlined),
      ];

  /// Sidebar path this location belongs to, so drill-down pages keep their
  /// section highlighted (e.g. /events/6/uploads highlights Events).
  String get selectedPath {
    // Creating an event is part of the Events workflow (the nav has no
    // dedicated "Create Event" destination).
    if (widget.location == '/create') return '/events';
    for (final prefix in const ['/events', '/attendees', '/certificates', '/survey-responses', '/notifications', '/reports', '/system', '/users', '/settings']) {
      if (widget.location == prefix || widget.location.startsWith('$prefix/')) return prefix;
    }
    return '/dashboard';
  }

  /// Where "Back" leads from a drill-down page, or null on top-level pages
  /// (the URL is the source of truth: /events/6/uploads -> /events/6 -> /events).
  (String, String)? get backTarget {
    final segments = Uri.parse(widget.location).pathSegments;
    if (segments.length >= 3 && segments[0] == 'events') {
      return ('/events/${segments[1]}', 'event');
    }
    if (segments.length == 2 && segments[0] == 'events') {
      return ('/events', 'Events');
    }
    return null;
  }

  @override
  Widget build(BuildContext context) {
    final compact = MediaQuery.sizeOf(context).width < 920;
    final back = backTarget;
    return Scaffold(
      appBar: compact
          ? AppBar(
              title: const Text('CEU Portal', style: TextStyle(fontWeight: FontWeight.w700)),
              backgroundColor: Colors.white,
              surfaceTintColor: Colors.white,
              actions: [
                IconButton(tooltip: 'Sign out', onPressed: widget.session.logout, icon: const Icon(Icons.logout)),
              ],
            )
          : null,
      drawer: compact ? Drawer(child: _Navigation(items: _navItems, selected: selectedPath, session: widget.session)) : null,
      body: Row(
        children: [
          if (!compact)
            SizedBox(
              width: 250,
              child: _Navigation(items: _navItems, selected: selectedPath, session: widget.session),
            ),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                if (back != null)
                  Padding(
                    padding: const EdgeInsets.fromLTRB(18, 10, 18, 0),
                    child: TextButton.icon(
                      onPressed: () => context.go(back.$1),
                      icon: const Icon(Icons.arrow_back, size: 18),
                      label: Text('Back to ${back.$2}', overflow: TextOverflow.ellipsis),
                    ),
                  ),
                Expanded(child: widget.child),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _Navigation extends StatelessWidget {
  const _Navigation({
    required this.items,
    required this.selected,
    required this.session,
  });

  final List<_NavItem> items;
  final String selected;
  final SessionController session;

  @override
  Widget build(BuildContext context) {
    return Material(
      color: navy,
      child: SafeArea(
        child: Column(
          children: [
            const Padding(
              padding: EdgeInsets.fromLTRB(20, 22, 20, 18),
              child: Row(
                children: [
                  Icon(Icons.workspace_premium_outlined, color: Colors.white, size: 30),
                  SizedBox(width: 10),
                  Expanded(child: Text('CEU PORTAL', style: TextStyle(color: Colors.white, fontWeight: FontWeight.w700, fontSize: 16))),
                ],
              ),
            ),
            const Divider(color: Color(0xFF34506A), height: 1),
            Expanded(
              child: ListView(
                padding: const EdgeInsets.symmetric(vertical: 14, horizontal: 10),
                children: [
                  for (final item in items)
                    Padding(
                      padding: const EdgeInsets.only(bottom: 4),
                      child: ListTile(
                        dense: true,
                        selected: selected == item.path,
                        selectedTileColor: const Color(0xFF294761),
                        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(6)),
                        leading: Icon(item.icon, color: Colors.white70, size: 21),
                        title: Text(item.label, style: const TextStyle(color: Colors.white, fontSize: 14)),
                        trailing: item.badgeCount > 0 ? _CountChip(count: item.badgeCount) : null,
                        onTap: () {
                          context.go(item.path);
                          if (Scaffold.maybeOf(context)?.hasDrawer ?? false) Navigator.pop(context);
                        },
                      ),
                    ),
                ],
              ),
            ),
            const Divider(color: Color(0xFF34506A), height: 1),
            Padding(
              padding: const EdgeInsets.all(14),
              child: Row(
                children: [
                  CircleAvatar(
                    radius: 19,
                    backgroundColor: teal,
                    child: Text(session.user!.fullName.substring(0, 1), style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w700)),
                  ),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(session.user!.fullName, overflow: TextOverflow.ellipsis, style: const TextStyle(color: Colors.white, fontSize: 13, fontWeight: FontWeight.w600)),
                        Text(session.user!.role == 'admin' ? 'Administrator' : 'Dealer / Presenter', style: const TextStyle(color: Color(0xFFAAC0D1), fontSize: 11)),
                      ],
                    ),
                  ),
                  IconButton(tooltip: 'Sign out', onPressed: session.logout, icon: const Icon(Icons.logout, color: Colors.white70, size: 20)),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// Small unread-count chip shown next to a nav destination.
class _CountChip extends StatelessWidget {
  const _CountChip({required this.count});
  final int count;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(color: const Color(0xFFB42318), borderRadius: BorderRadius.circular(12)),
      child: Text(
        count > 99 ? '99+' : '$count',
        style: const TextStyle(color: Colors.white, fontSize: 11, fontWeight: FontWeight.w700),
      ),
    );
  }
}

class _NavItem {
  const _NavItem(this.path, this.label, this.icon, {this.badgeCount = 0});
  final String path;
  final String label;
  final IconData icon;
  final int badgeCount;
}
