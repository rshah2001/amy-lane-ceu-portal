import 'package:flutter/material.dart';
import 'package:flutter/semantics.dart';
import 'package:go_router/go_router.dart';

import 'core/session.dart';
import 'models/models.dart';
import 'pages/attendee_search_page.dart';
import 'pages/audit_reports_page.dart';
import 'pages/certificate_center_page.dart';
import 'pages/checkin_page.dart';
import 'pages/compliance_page.dart';
import 'pages/create_event_page.dart';
import 'pages/dashboard_page.dart';
import 'pages/event_detail_page.dart';
import 'pages/events_page.dart';
import 'pages/login_page.dart';
import 'pages/notification_center_page.dart';
import 'pages/public_survey_page.dart';
import 'pages/public_test_page.dart';
import 'pages/settings_page.dart';
import 'pages/survey_responses_page.dart';
import 'pages/system_health_page.dart';
import 'pages/uploads_page.dart';
import 'pages/users_page.dart';
import 'pages/verification_page.dart';
import 'widgets/app_shell.dart';
import 'widgets/common.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();

  // Build the accessibility tree from the first frame, unconditionally.
  //
  // This is a CanvasKit build, so Flutter paints into a WebGL canvas that a
  // screen reader sees as one empty graphic. Flutter only starts emitting DOM
  // semantics once something turns them on — normally an off-screen "Enable
  // accessibility" button the user has to find and activate first. Until then
  // VoiceOver and NVDA get a blank page.
  //
  // That placeholder button is not a reasonable ask of anyone, and it is an
  // impossible one for an attendee who has just scanned a QR code on their
  // phone to reach the public check-in, post-test, survey, or certificate
  // verification page — those are the screens NMEDA's own audience lands on.
  //
  // Tradeoff: the semantics tree is now built and maintained for every user
  // rather than on demand, which costs a DOM mirror of the widget tree and some
  // per-frame work. On a form-and-table app of this size that is not a
  // measurable interaction cost, and it is the only way the public pages are
  // usable at all with a screen reader.
  SemanticsBinding.instance.ensureSemantics();

  final session = SessionController();
  await session.restore();
  runApp(CeuPortalApp(session: session));
}

class CeuPortalApp extends StatefulWidget {
  const CeuPortalApp({super.key, required this.session});

  final SessionController session;

  @override
  State<CeuPortalApp> createState() => _CeuPortalAppState();
}

class _CeuPortalAppState extends State<CeuPortalApp> {
  late final GoRouter router = buildRouter(widget.session);

  @override
  Widget build(BuildContext context) {
    // Personalized links from QR codes and invite emails arrive as query
    // parameters on the root URL; they open the public page directly and
    // never touch the authenticated app or its router.
    final params = Uri.base.queryParameters;
    final testToken = params['test'];
    final surveyToken = params['survey'];
    final checkinToken = params['checkin'];
    if (testToken != null || surveyToken != null || checkinToken != null || params.containsKey('verify')) {
      return MaterialApp(
        title: 'CEU Compliance Portal',
        debugShowCheckedModeBanner: false,
        theme: buildPortalTheme(),
        home: testToken != null
            ? PublicTestPage(
                api: widget.session.api,
                token: testToken,
                prefillName: params['name'],
                prefillEmail: params['email'],
              )
            : surveyToken != null
                ? PublicSurveyPage(
                    api: widget.session.api,
                    token: surveyToken,
                    prefillName: params['name'],
                    prefillEmail: params['email'],
                  )
                : checkinToken != null
                    ? CheckinPage(
                        api: widget.session.api,
                        token: checkinToken,
                        prefillName: params['name'],
                        prefillEmail: params['email'],
                      )
                    : VerificationPage(api: widget.session.api, initialNumber: params['verify']),
      );
    }
    return MaterialApp.router(
      title: 'CEU Compliance Portal',
      debugShowCheckedModeBanner: false,
      theme: buildPortalTheme(),
      routerConfig: router,
    );
  }
}

GoRouter buildRouter(SessionController session) {
  return GoRouter(
    initialLocation: '/dashboard',
    refreshListenable: session,
    redirect: (context, state) {
      final loggingIn = state.matchedLocation == '/login';
      // The certificate verification page is public (no sign-in required).
      if (state.matchedLocation == '/verify') return null;
      if (!session.isAuthenticated) {
        if (loggingIn) return null;
        return '/login?from=${Uri.encodeComponent(state.uri.toString())}';
      }
      if (loggingIn) {
        final from = state.uri.queryParameters['from'];
        return (from == null || from.isEmpty) ? '/dashboard' : Uri.decodeComponent(from);
      }
      // Admin-only sections: keep presenters out even via a typed/shared URL.
      const adminOnly = ['/create', '/certificates', '/reports', '/users', '/survey-responses', '/notifications', '/system'];
      if (!session.user!.isAdmin &&
          (adminOnly.any((p) => state.matchedLocation.startsWith(p)) ||
              state.matchedLocation.endsWith('/edit') ||
              state.matchedLocation.endsWith('/compliance'))) {
        return '/dashboard';
      }
      return null;
    },
    // Without this, a mistyped or stale URL — a bookmarked event that has since
    // been deleted, a link forwarded with a truncated path — drops the user on
    // go_router's raw diagnostic page, which shows a Dart exception and offers
    // no way back. Attendees reach this app through printed QR codes, so a
    // wrong URL is a realistic arrival, not just a developer typo.
    errorBuilder: (context, state) => _NotFoundPage(
      location: state.uri.toString(),
      signedIn: session.isAuthenticated,
    ),
    routes: [
      GoRoute(path: '/', redirect: (context, state) => '/dashboard'),
      GoRoute(path: '/login', builder: (context, state) => LoginPage(session: session)),
      GoRoute(
        path: '/verify',
        builder: (context, state) => VerificationPage(
          api: session.api,
          initialNumber: state.uri.queryParameters['n'],
        ),
      ),
      ShellRoute(
        builder: (context, state, child) => AppShell(
          session: session,
          location: state.uri.path,
          child: child,
        ),
        routes: [
          GoRoute(
            path: '/dashboard',
            builder: (context, state) => DashboardPage(
              session: session,
              onOpenEvents: () => context.go('/events'),
              onCreateEvent: () => context.go('/create'),
            ),
          ),
          GoRoute(
            path: '/events',
            builder: (context, state) => EventsPage(
              session: session,
              onOpen: (event) => context.go('/events/${event.id}', extra: event),
            ),
            routes: [
              GoRoute(
                path: ':id',
                builder: (context, state) => _eventScreen(
                  session,
                  state,
                  (context, event) => EventDetailPage(
                    session: session,
                    event: event,
                    isAdmin: session.user!.isAdmin,
                    canManageCertificates: session.user!.isAdmin,
                    onNavigate: (target) {
                      switch (target) {
                        case 'edit':
                          // No extra: the edit screen refetches the event so it
                          // always has the latest test and survey questions.
                          context.go('/events/${event.id}/edit');
                        case 'uploads':
                          context.go('/events/${event.id}/uploads', extra: event);
                        case 'compliance':
                          context.go('/events/${event.id}/compliance', extra: event);
                        case 'certificates':
                          context.go('/certificates', extra: event);
                        default:
                          context.go('/events');
                      }
                    },
                  ),
                ),
                routes: [
                  GoRoute(
                    path: 'edit',
                    builder: (context, state) => _eventScreen(
                      session,
                      state,
                      (context, event) => CreateEventPage(
                        session: session,
                        event: event,
                        onSaved: (updated) => context.go('/events/${updated.id}', extra: updated),
                      ),
                    ),
                  ),
                  GoRoute(
                    path: 'uploads',
                    builder: (context, state) => _eventScreen(
                      session,
                      state,
                      (context, event) => UploadsPage(session: session, event: event),
                    ),
                  ),
                  GoRoute(
                    path: 'compliance',
                    builder: (context, state) => _eventScreen(
                      session,
                      state,
                      (context, event) => CompliancePage(session: session, event: event),
                    ),
                  ),
                ],
              ),
            ],
          ),
          GoRoute(
            path: '/create',
            builder: (context, state) => CreateEventPage(
              session: session,
              onSaved: (event) => context.go('/events/${event.id}', extra: event),
            ),
          ),
          GoRoute(
            path: '/attendees',
            builder: (context, state) => AttendeeSearchPage(session: session),
          ),
          GoRoute(
            path: '/certificates',
            builder: (context, state) => CertificateCenterPage(
              session: session,
              initialEvent: state.extra is TrainingEvent ? state.extra as TrainingEvent : null,
              onSelectEvent: (event) {},
            ),
          ),
          GoRoute(
            path: '/reports',
            builder: (context, state) => AuditReportsPage(session: session),
          ),
          GoRoute(
            path: '/users',
            builder: (context, state) => UsersPage(session: session),
          ),
          GoRoute(
            path: '/survey-responses',
            builder: (context, state) => SurveyResponsesPage(session: session),
          ),
          GoRoute(
            path: '/notifications',
            builder: (context, state) => NotificationCenterPage(session: session),
          ),
          GoRoute(
            path: '/system',
            builder: (context, state) => SystemHealthPage(session: session),
          ),
          GoRoute(
            path: '/settings',
            builder: (context, state) => SettingsPage(session: session),
          ),
        ],
      ),
    ],
  );
}

Widget _eventScreen(
  SessionController session,
  GoRouterState state,
  Widget Function(BuildContext, TrainingEvent) builder,
) {
  final id = int.tryParse(state.pathParameters['id'] ?? '') ?? 0;
  return EventScreen(
    key: ValueKey('event-$id-${state.uri.path}'),
    session: session,
    eventId: id,
    initial: state.extra is TrainingEvent ? state.extra as TrainingEvent : null,
    builder: builder,
  );
}

/// Resolves the event for /events/:id routes. Uses the event passed along
/// with in-app navigation when available, otherwise fetches it by id so the
/// URL keeps working on refresh or when shared.
class EventScreen extends StatefulWidget {
  const EventScreen({
    super.key,
    required this.session,
    required this.eventId,
    required this.builder,
    this.initial,
  });

  final SessionController session;
  final int eventId;
  final TrainingEvent? initial;
  final Widget Function(BuildContext, TrainingEvent) builder;

  @override
  State<EventScreen> createState() => _EventScreenState();
}

class _EventScreenState extends State<EventScreen> {
  TrainingEvent? event;
  Object? error;

  @override
  void initState() {
    super.initState();
    event = widget.initial?.id == widget.eventId ? widget.initial : null;
    if (event == null) _load();
  }

  Future<void> _load() async {
    try {
      final json = await widget.session.api.get('/events/${widget.eventId}');
      if (mounted) setState(() => event = TrainingEvent.fromJson(json as Map<String, dynamic>));
    } catch (exception) {
      if (mounted) setState(() => error = exception);
    }
  }

  @override
  Widget build(BuildContext context) {
    if (event != null) return widget.builder(context, event!);
    if (error != null) {
      final theme = Theme.of(context);
      return Center(
        child: Semantics(
          liveRegion: true,
          container: true,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Text('This event could not be loaded.'),
              const SizedBox(height: Space.xxs + 2),
              Text(
                humanizeError(error!),
                textAlign: TextAlign.center,
                style: theme.textTheme.labelMedium?.copyWith(
                  color: theme.portal.textSecondary,
                  fontWeight: FontWeight.w400,
                ),
              ),
              const SizedBox(height: Space.sm + 2),
              OutlinedButton(
                onPressed: () => context.go('/events'),
                child: const Text('Back to Events'),
              ),
            ],
          ),
        ),
      );
    }
    return const LoadingPanel(label: 'Loading event');
  }
}

/// Shown for any URL the router doesn't recognise.
///
/// Deliberately does not say "you don't have permission" — the router can't
/// tell a deleted event from a typo from a page this role can't see, and
/// guessing wrong is worse than saying plainly that the page isn't there.
/// Where it goes next depends on who is asking: a signed-in user gets the
/// dashboard, while a visitor who scanned a bad QR code has no dashboard to
/// go to and is pointed at sign-in instead.
class _NotFoundPage extends StatelessWidget {
  const _NotFoundPage({required this.location, required this.signedIn});

  final String location;
  final bool signedIn;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final colors = theme.portal;
    return Scaffold(
      body: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: maxFormWidth),
          child: Padding(
            padding: pagePadding,
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                ExcludeSemantics(
                  child: Icon(Icons.explore_off_outlined, size: 48, color: colors.textTertiary),
                ),
                const SizedBox(height: Space.md),
                Heading(child: Text('That page could not be found', style: theme.textTheme.headlineMedium)),
                const SizedBox(height: Space.xs),
                Text(
                  signedIn
                      ? 'The link may be out of date, or the item may have been removed.'
                      : 'The link may be out of date. If you scanned a QR code at an event, '
                          'ask the presenter to check it.',
                  textAlign: TextAlign.center,
                  style: theme.textTheme.bodyMedium?.copyWith(color: colors.textSecondary),
                ),
                const SizedBox(height: Space.sm),
                SelectableText(
                  location,
                  textAlign: TextAlign.center,
                  style: theme.textTheme.labelSmall?.copyWith(color: colors.textTertiary),
                ),
                const SizedBox(height: Space.lg),
                ElevatedButton(
                  onPressed: () => context.go(signedIn ? '/dashboard' : '/login'),
                  child: Text(signedIn ? 'Back to Dashboard' : 'Go to sign in'),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
