import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../core/session.dart';
import 'common.dart';

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

  /// Navigation grouped by what the reader is trying to do.
  ///
  /// An admin saw ten flat destinations in one list, which gives no clue that
  /// "Certificate Center" is where today's work is and "System Health" is not.
  /// The groups are: the work itself, the records you look things up in, and
  /// administration. A presenter has four destinations and no need of
  /// scaffolding, so they see the same flat list they always did — headings
  /// over groups of one would be noise.
  List<_NavGroup> get _navGroups {
    if (!widget.session.user!.isAdmin) {
      return [_NavGroup(null, _presenterItems)];
    }
    return [
      _NavGroup('Workflow', [
        const _NavItem('/dashboard', 'Dashboard', Icons.space_dashboard_outlined),
        const _NavItem('/events', 'Events', Icons.event_note_outlined),
        const _NavItem('/certificates', 'Certificate Center', Icons.workspace_premium_outlined),
        _NavItem('/notifications', 'Notifications', Icons.notifications_outlined, badgeCount: unreadNotifications),
      ]),
      const _NavGroup('Records', [
        _NavItem('/attendees', 'Attendee Search', Icons.person_search_outlined),
        _NavItem('/survey-responses', 'Survey Responses', Icons.rate_review_outlined),
        _NavItem('/reports', 'Audit Reports', Icons.assessment_outlined),
      ]),
      const _NavGroup('Administration', [
        _NavItem('/users', 'Users', Icons.group_outlined),
        _NavItem('/system', 'System Health', Icons.monitor_heart_outlined),
        _NavItem('/settings', 'Settings', Icons.settings_outlined),
      ]),
    ];
  }

  static const _presenterItems = [
    _NavItem('/dashboard', 'Dashboard', Icons.space_dashboard_outlined),
    _NavItem('/events', 'Events', Icons.event_note_outlined),
    _NavItem('/attendees', 'Attendee Search', Icons.person_search_outlined),
    _NavItem('/settings', 'Settings', Icons.settings_outlined),
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

  /// Focus target for "Skip to main content". Anchored on the page content so
  /// the first Tab of a fresh page can jump the ten sidebar destinations
  /// instead of walking them again on every navigation.
  final FocusScopeNode _contentFocus = FocusScopeNode(debugLabel: 'main content');

  @override
  void dispose() {
    _contentFocus.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final compact = MediaQuery.sizeOf(context).width < 920;
    final back = backTarget;
    return Scaffold(
      appBar: compact
          ? AppBar(
              title: Text('CEU Portal', style: Theme.of(context).textTheme.titleMedium),
              actions: [
                IconButton(
                  tooltip: 'Sign out',
                  onPressed: widget.session.logout,
                  icon: const Icon(Icons.logout),
                ),
              ],
            )
          : null,
      drawer: compact
          ? Drawer(
              child: _Navigation(
                groups: _navGroups,
                selected: selectedPath,
                session: widget.session,
              ),
            )
          : null,
      body: Row(
        children: [
          if (!compact)
            SizedBox(
              width: 250,
              child: _Navigation(
                groups: _navGroups,
                selected: selectedPath,
                session: widget.session,
              ),
            ),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                _SkipToContentLink(onSkip: _contentFocus.requestFocus),
                if (back != null)
                  Padding(
                    padding: const EdgeInsets.fromLTRB(18, Space.xs + 2, 18, 0),
                    child: TextButton.icon(
                      onPressed: () => context.go(back.$1),
                      icon: const Icon(Icons.arrow_back, size: 18),
                      label: Text('Back to ${back.$2}', overflow: TextOverflow.ellipsis),
                    ),
                  ),
                Expanded(
                  child: FocusScope(node: _contentFocus, child: widget.child),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

/// A bypass link that stays invisible until it is focused.
///
/// The sidebar sits first in traversal order, so without this a keyboard user
/// tabs through ten destinations, the user chip and the sign-out button before
/// reaching page content — on every single navigation. WCAG 2.4.1 asks for a
/// mechanism to skip repeated blocks; this is it.
class _SkipToContentLink extends StatefulWidget {
  const _SkipToContentLink({required this.onSkip});

  final VoidCallback onSkip;

  @override
  State<_SkipToContentLink> createState() => _SkipToContentLinkState();
}

class _SkipToContentLinkState extends State<_SkipToContentLink> {
  final FocusNode _node = FocusNode(debugLabel: 'skip to content');

  @override
  void initState() {
    super.initState();
    _node.addListener(_onFocusChange);
  }

  void _onFocusChange() {
    if (mounted) setState(() {});
  }

  @override
  void dispose() {
    _node.removeListener(_onFocusChange);
    _node.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    // The button stays in the tree at all times — collapsed and clipped rather
    // than removed — so it is always the first thing Tab reaches, and it
    // reveals itself the moment it takes focus.
    //
    // `heightFactor` rather than a zero-height SizedBox: Align still lays the
    // child out at its natural size and only scales the space it occupies, so
    // the button never gets squeezed into an overflow.
    return ClipRect(
      child: Align(
        alignment: Alignment.topLeft,
        heightFactor: _node.hasFocus ? 1.0 : 0.0,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(18, Space.xs, 18, 0),
          child: TextButton.icon(
            focusNode: _node,
            onPressed: widget.onSkip,
            icon: const Icon(Icons.keyboard_tab, size: 18),
            label: const Text('Skip to main content'),
          ),
        ),
      ),
    );
  }
}

class _Navigation extends StatelessWidget {
  const _Navigation({
    required this.groups,
    required this.selected,
    required this.session,
  });

  final List<_NavGroup> groups;
  final String selected;
  final SessionController session;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final colors = theme.portal;
    return Material(
      color: colors.navSurface,
      child: SafeArea(
        child: Column(
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(Space.lg, 22, Space.lg, 18),
              child: Row(
                children: [
                  const ExcludeSemantics(
                    child: Icon(Icons.workspace_premium_outlined, color: Colors.white, size: 30),
                  ),
                  const SizedBox(width: Space.xs + 2),
                  Expanded(
                    child: Heading(
                      child: Text(
                        'CEU PORTAL',
                        style: theme.textTheme.titleSmall?.copyWith(color: Colors.white),
                      ),
                    ),
                  ),
                ],
              ),
            ),
            Divider(color: colors.navOutline, height: 1),
            Expanded(
              child: Semantics(
                explicitChildNodes: true,
                label: 'Main navigation',
                child: ListView(
                  padding: const EdgeInsets.symmetric(
                    vertical: Space.sm + 2,
                    horizontal: Space.xs + 2,
                  ),
                  children: [
                    for (final group in groups) ...[
                      if (group.label != null)
                        Padding(
                          padding: const EdgeInsets.fromLTRB(Space.sm + 2, Space.md, Space.sm, Space.xxs),
                          // A heading in the semantics tree too, so a screen
                          // reader user can jump between sections rather than
                          // arrowing through all ten destinations.
                          child: Semantics(
                            header: true,
                            child: Text(
                              group.label!.toUpperCase(),
                              style: theme.textTheme.labelSmall?.copyWith(
                                color: colors.onNavMuted,
                                letterSpacing: 0.8,
                                fontWeight: FontWeight.w700,
                              ),
                            ),
                          ),
                        ),
                      for (final item in group.items)
                        Padding(
                          padding: const EdgeInsets.only(bottom: Space.xxs),
                          child: _NavTile(
                            item: item,
                            isSelected: selected == item.path,
                          ),
                        ),
                    ],
                  ],
                ),
              ),
            ),
            Divider(color: colors.navOutline, height: 1),
            Padding(
              padding: const EdgeInsets.all(Space.sm + 2),
              child: Row(
                children: [
                  CircleAvatar(
                    radius: 19,
                    backgroundColor: teal,
                    child: ExcludeSemantics(
                      child: Text(
                        session.user!.fullName.substring(0, 1),
                        style: theme.textTheme.bodyMedium
                            ?.copyWith(color: Colors.white, fontWeight: FontWeight.w700),
                      ),
                    ),
                  ),
                  const SizedBox(width: Space.xs + 2),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          session.user!.fullName,
                          overflow: TextOverflow.ellipsis,
                          style: theme.textTheme.bodySmall
                              ?.copyWith(color: Colors.white, fontWeight: FontWeight.w600),
                        ),
                        Text(
                          session.user!.role == 'admin' ? 'Administrator' : 'Dealer / Presenter',
                          style: theme.textTheme.labelSmall?.copyWith(
                            color: colors.onNavMuted,
                            fontWeight: FontWeight.w400,
                          ),
                        ),
                      ],
                    ),
                  ),
                  IconButton(
                    tooltip: 'Sign out',
                    onPressed: session.logout,
                    icon: const Icon(Icons.logout, color: Colors.white70, size: 20),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// One sidebar destination.
///
/// The current page used to be signalled by a `#294761` tile against the
/// `#17324D` sidebar — **1.44:1**, which is effectively invisible, and colour
/// was the only carrier. Three independent cues now mark it:
///
///  * a 3px left accent bar at **8.02:1** against the sidebar (this is the cue
///    that satisfies WCAG 1.4.11 — a fill light enough to reach 3:1 would drop
///    its own white label under 4.5:1, so the bar does that job instead),
///  * a **bold** label rather than regular weight, and
///  * a lifted tile fill at 2.01:1 with its white label still at 6.53:1.
class _NavTile extends StatelessWidget {
  const _NavTile({required this.item, required this.isSelected});

  final _NavItem item;
  final bool isSelected;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final colors = theme.portal;
    return Stack(
      children: [
        ListTile(
          dense: true,
          selected: isSelected,
          selectedTileColor: colors.navSelected,
          selectedColor: Colors.white,
          contentPadding: const EdgeInsets.only(left: Space.md, right: Space.md),
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(Radii.sm)),
          leading: Icon(
            item.icon,
            color: isSelected ? Colors.white : Colors.white70,
            size: 21,
          ),
          title: Text(
            item.label,
            style: theme.textTheme.labelLarge?.copyWith(
              color: Colors.white,
              fontWeight: isSelected ? FontWeight.w700 : FontWeight.w500,
            ),
          ),
          trailing: item.badgeCount > 0 ? _CountChip(count: item.badgeCount) : null,
          onTap: () {
            context.go(item.path);
            if (Scaffold.maybeOf(context)?.hasDrawer ?? false) Navigator.pop(context);
          },
        ),
        if (isSelected)
          Positioned(
            left: 0,
            top: 6,
            bottom: 6,
            child: ExcludeSemantics(
              child: Container(
                width: 3,
                decoration: BoxDecoration(
                  color: colors.navAccent,
                  borderRadius: BorderRadius.circular(Radii.pill),
                ),
              ),
            ),
          ),
      ],
    );
  }
}

/// Small unread-count chip shown next to a nav destination.
class _CountChip extends StatelessWidget {
  const _CountChip({required this.count});
  final int count;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Semantics(
      // "12" on its own is meaningless in the reading order; this makes the
      // destination announce as "Notifications, 12 unread".
      label: '$count unread',
      excludeSemantics: true,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: Space.xs, vertical: 3),
        decoration: BoxDecoration(
          color: theme.portal.danger,
          borderRadius: BorderRadius.circular(Radii.pill),
        ),
        child: Text(
          count > 99 ? '99+' : '$count',
          style: theme.textTheme.labelSmall?.copyWith(
            color: Colors.white,
            fontWeight: FontWeight.w700,
          ),
        ),
      ),
    );
  }
}

/// A titled run of navigation destinations. A null [label] renders the items
/// with no heading, which is what the presenter's short list wants.
class _NavGroup {
  const _NavGroup(this.label, this.items);
  final String? label;
  final List<_NavItem> items;
}

class _NavItem {
  const _NavItem(this.path, this.label, this.icon, {this.badgeCount = 0});
  final String path;
  final String label;
  final IconData icon;
  final int badgeCount;
}
