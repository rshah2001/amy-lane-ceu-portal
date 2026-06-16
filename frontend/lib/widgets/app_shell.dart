import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../core/session.dart';
import '../core/theme.dart';

class AppShell extends StatelessWidget {
  const AppShell({
    super.key,
    required this.session,
    required this.location,
    required this.child,
  });

  final SessionController session;
  final String location;
  final Widget child;

  List<_NavItem> get _navItems => [
        const _NavItem('/dashboard', 'Dashboard', Icons.space_dashboard_outlined),
        const _NavItem('/events', 'Events', Icons.event_note_outlined),
        if (session.user!.isAdmin) const _NavItem('/create', 'Create Event', Icons.add_circle_outline),
        const _NavItem('/attendees', 'Attendee Search', Icons.person_search_outlined),
        if (session.user!.isAdmin) ...[
          const _NavItem('/certificates', 'Certificate Center', Icons.workspace_premium_outlined),
          const _NavItem('/survey-responses', 'Survey Responses', Icons.rate_review_outlined),
          const _NavItem('/notifications', 'Notifications', Icons.notifications_outlined),
          const _NavItem('/reports', 'Audit Reports', Icons.assessment_outlined),
          const _NavItem('/system', 'System Health', Icons.monitor_heart_outlined),
          const _NavItem('/users', 'Users', Icons.group_outlined),
        ],
        const _NavItem('/settings', 'Settings', Icons.settings_outlined),
      ];

  /// Sidebar path this location belongs to, so drill-down pages keep their
  /// section highlighted (e.g. /events/6/uploads highlights Events).
  String get selectedPath {
    if (location == '/create') return '/create';
    for (final prefix in const ['/events', '/attendees', '/certificates', '/survey-responses', '/notifications', '/reports', '/system', '/users', '/settings']) {
      if (location == prefix || location.startsWith('$prefix/')) return prefix;
    }
    return '/dashboard';
  }

  /// Where "Back" leads from a drill-down page, or null on top-level pages
  /// (the URL is the source of truth: /events/6/uploads -> /events/6 -> /events).
  (String, String)? get backTarget {
    final segments = Uri.parse(location).pathSegments;
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
                IconButton(tooltip: 'Sign out', onPressed: session.logout, icon: const Icon(Icons.logout)),
              ],
            )
          : null,
      drawer: compact ? Drawer(child: _Navigation(items: _navItems, selected: selectedPath, session: session)) : null,
      body: Row(
        children: [
          if (!compact)
            SizedBox(
              width: 250,
              child: _Navigation(items: _navItems, selected: selectedPath, session: session),
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
                Expanded(child: child),
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

class _NavItem {
  const _NavItem(this.path, this.label, this.icon);
  final String path;
  final String label;
  final IconData icon;
}
