import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/semantics.dart';
// `intl` also exports a `TextDirection`, which shadows the `dart:ui` one that
// the semantics API expects.
import 'package:intl/intl.dart' hide TextDirection;

import '../core/api_client.dart';
import '../core/theme.dart';

// Everything in the design system travels with the shared widgets, so a page
// needs one import to get both `PageHeader` and the tokens it is built from.
export '../core/theme.dart';
// The stale-response guard is needed by every page that loads a list, which is
// every page that already imports this file.
export 'request_guard.dart';

/// Page padding. Every page in the shell uses this, so the content column
/// starts at the same inset no matter which page you navigated from.
const pagePadding = EdgeInsets.all(Space.xl);

const divider = Divider(height: 1, color: border);

// ─────────────────────────────────────────────────────────────────────────────
// Accessibility primitives
// ─────────────────────────────────────────────────────────────────────────────

/// Marks [child] as a heading.
///
/// Screen reader users navigate a page by jumping heading to heading (the `H`
/// key in NVDA/JAWS, the rotor in VoiceOver). Without this the portal is one
/// flat run of text and reaching the compliance table means arrowing past the
/// entire sidebar and page header every time.
class Heading extends StatelessWidget {
  const Heading({super.key, required this.child, this.level = 1});

  final Widget child;

  /// Kept for call-site intent; Flutter's semantics model has a single
  /// `header` flag rather than levels, so this documents the hierarchy for
  /// readers of the code even though it is not forwarded to the platform.
  final int level;

  @override
  Widget build(BuildContext context) => Semantics(header: true, child: child);
}

/// Speaks [message] immediately, interrupting whatever the screen reader is
/// saying.
///
/// Used for form and request failures. A visually-hidden change to a red `Text`
/// on screen is silent to a screen reader, so a user who presses "Sign in" and
/// fails otherwise hears nothing at all and has no way to know why the page
/// didn't move.
void announceToScreenReader(BuildContext context, String message) {
  if (message.trim().isEmpty) return;
  final view = View.maybeOf(context);
  if (view == null) return;
  SemanticsService.sendAnnouncement(
    view,
    message,
    Directionality.maybeOf(context) ?? TextDirection.ltr,
    assertiveness: Assertiveness.assertive,
  );
}

/// A validated field that [validateAndFocusFirstError] can move focus to.
typedef FormFieldRef = ({GlobalKey<FormFieldState<String>> key, FocusNode focus});

/// Validates [formKey] and, on failure, puts focus on the first field that
/// reported an error, scrolls it into view, and announces the message.
///
/// Flutter's `FormState.validate()` paints the error text and returns false —
/// it does not move focus. On Create Event (a 15-field page) that leaves the
/// caret on the submit button while the actual problem sits 800px up the page,
/// which for a keyboard or screen reader user is a dead end.
///
/// [fields] is in visual order; only the fields worth jumping to need to be
/// listed. Anything not listed still validates, it just falls back to the
/// generic announcement.
bool validateAndFocusFirstError(
  BuildContext context,
  GlobalKey<FormState> formKey,
  List<FormFieldRef> fields,
) {
  if (formKey.currentState?.validate() ?? false) return true;
  for (final field in fields) {
    final state = field.key.currentState;
    if (state != null && state.hasError) {
      field.focus.requestFocus();
      final fieldContext = field.key.currentContext;
      if (fieldContext != null) {
        Scrollable.ensureVisible(
          fieldContext,
          alignment: 0.2,
          duration: const Duration(milliseconds: 200),
        );
      }
      announceToScreenReader(context, state.errorText ?? 'This field needs attention.');
      return false;
    }
  }
  announceToScreenReader(
    context,
    'The form could not be submitted. Please check the highlighted fields.',
  );
  return false;
}

/// Guarantees a pointer target of at least [minTapTarget] square without
/// changing how the child looks.
///
/// The uploads page had two 16px-tall text links — "open the original file" and
/// "N rows could not be read" — which are the only route to parse-error detail
/// for a presenter who just photographed a sign-in sheet on their phone. That
/// is the exact person least able to hit a 16px target.
class MinTapTarget extends StatelessWidget {
  const MinTapTarget({super.key, required this.child, this.alignment = Alignment.centerLeft});

  final Widget child;
  final AlignmentGeometry alignment;

  @override
  Widget build(BuildContext context) {
    return ConstrainedBox(
      constraints: const BoxConstraints(minWidth: minTapTarget, minHeight: minTapTarget),
      // The 1.0 factors keep the box sized to the child; the ConstrainedBox
      // then raises it to the 44px floor only when the child is smaller.
      child: Align(alignment: alignment, widthFactor: 1, heightFactor: 1, child: child),
    );
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Page furniture
// ─────────────────────────────────────────────────────────────────────────────

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
    final theme = Theme.of(context);
    final colors = theme.portal;
    return LayoutBuilder(
      builder: (context, constraints) {
        final heading = Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Heading(child: Text(title, style: theme.textTheme.headlineMedium)),
            const SizedBox(height: Space.xxs),
            Text(
              subtitle,
              style: theme.textTheme.bodyMedium?.copyWith(color: colors.textSecondary),
            ),
          ],
        );
        if (constraints.maxWidth < 680 || actions.isEmpty) {
          return Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              heading,
              if (actions.isNotEmpty) ...[
                const SizedBox(height: Space.md),
                Wrap(spacing: Space.xs, runSpacing: Space.xs, children: actions),
              ],
            ],
          );
        }
        return Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Expanded(child: heading),
            Wrap(spacing: Space.xs, runSpacing: Space.xs, children: actions),
          ],
        );
      },
    );
  }
}

/// A section heading inside a page or card, announced as a heading.
class SectionTitle extends StatelessWidget {
  const SectionTitle(this.text, {super.key, this.style});

  final String text;
  final TextStyle? style;

  @override
  Widget build(BuildContext context) {
    return Heading(
      level: 2,
      child: Text(text, style: style ?? Theme.of(context).textTheme.titleMedium),
    );
  }
}

class StatusBadge extends StatelessWidget {
  const StatusBadge(this.label, {super.key, this.tone = BadgeTone.neutral});

  final String label;
  final BadgeTone tone;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final colors = theme.portal;
    // Every pair below measures 4.5:1 or better; see the ratios recorded on the
    // tokens in theme.dart.
    final (background, foreground) = switch (tone) {
      BadgeTone.success => (colors.successSurface, colors.success),
      BadgeTone.warning => (colors.warningSurface, colors.warning),
      BadgeTone.danger => (colors.dangerSurface, colors.danger),
      BadgeTone.info => (colors.infoSurface, colors.info),
      BadgeTone.neutral => (colors.neutralSurface, colors.neutral),
    };
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 5),
      decoration: BoxDecoration(
        color: background,
        borderRadius: BorderRadius.circular(Radii.pill),
      ),
      child: Text(label, style: theme.textTheme.labelMedium?.copyWith(color: foreground)),
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
    final theme = Theme.of(context);
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(Space.lg),
        child: Semantics(
          // Read as one fact ("Total events: 42") instead of two orphaned
          // fragments in whichever order the traversal happens to reach them.
          container: true,
          label: '$label: $value',
          excludeSemantics: true,
          child: Row(
            children: [
              Container(
                width: 44,
                height: 44,
                decoration: BoxDecoration(
                  color: color.withValues(alpha: 0.12),
                  borderRadius: BorderRadius.circular(Radii.sm),
                ),
                child: Icon(icon, color: color),
              ),
              const SizedBox(width: Space.sm + 2),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(value, style: theme.textTheme.headlineMedium),
                    const SizedBox(height: 2),
                    Text(
                      label,
                      style: theme.textTheme.bodyMedium?.copyWith(
                        color: theme.portal.textSecondary,
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
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
    final theme = Theme.of(context);
    final colors = theme.portal;
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(Space.xxl),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            // Purely decorative — the message right below says the same thing.
            ExcludeSemantics(child: Icon(icon, size: 40, color: colors.textTertiary)),
            const SizedBox(height: Space.sm),
            Text(
              message,
              textAlign: TextAlign.center,
              style: theme.textTheme.bodyMedium?.copyWith(fontWeight: FontWeight.w600),
            ),
            if (detail != null) ...[
              const SizedBox(height: Space.xxs + 2),
              Text(
                detail!,
                textAlign: TextAlign.center,
                style: theme.textTheme.bodySmall?.copyWith(color: colors.textSecondary),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

class LoadingPanel extends StatelessWidget {
  const LoadingPanel({super.key, this.label = 'Loading'});

  final String label;

  @override
  Widget build(BuildContext context) => Center(
        child: Padding(
          padding: const EdgeInsets.all(Space.xxxl),
          // Without a label the spinner is an unnamed progress node; with it a
          // screen reader says what the page is waiting for.
          child: Semantics(
            label: label,
            liveRegion: true,
            child: const CircularProgressIndicator(),
          ),
        ),
      );
}

class ErrorPanel extends StatelessWidget {
  const ErrorPanel({super.key, required this.message, required this.onRetry});

  final String message;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).portal;
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(Space.xxl),
        child: Semantics(
          liveRegion: true,
          container: true,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              ExcludeSemantics(
                child: Icon(Icons.error_outline, color: colors.danger, size: 36),
              ),
              const SizedBox(height: Space.sm),
              Text(message, textAlign: TextAlign.center),
              const SizedBox(height: Space.md),
              OutlinedButton.icon(
                onPressed: onRetry,
                icon: const Icon(Icons.refresh),
                label: const Text('Retry'),
              ),
            ],
          ),
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
  if (exception is TimeoutException) {
    // Deliberately not "try again": the client stopped waiting, it did not
    // cancel the request, so a certificate send that timed out may well have
    // gone out. Telling someone to press Send again would double-email an
    // attendee. Reload first, then decide.
    return 'The server took too long to respond. It may still be working on it — '
        'reload the page to check before trying again.';
  }
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
    // Revoked is a withdrawal, not a stage of delivery: the record is kept for
    // the retention period and the number publicly answers "revoked", so it
    // has to read as the one alarming state in the column.
    'revoked' => BadgeTone.danger,
    'downloaded' || 'delivered' || 'sent' => BadgeTone.success,
    'generated' || 'approved' => BadgeTone.info,
    'eligible' => BadgeTone.warning,
    'pending_attendance' || 'pending_test' || 'pending_survey' => BadgeTone.neutral,
    _ => BadgeTone.neutral,
  };
  return StatusBadge(label, tone: tone);
}

/// A met / not-met requirement mark.
///
/// [label] is not optional on purpose. These four marks — attended, post-test
/// passed, survey completed, valid email — are the facts that decide whether a
/// person gets CEU credit, and as a bare coloured glyph they announced as
/// nothing at all. A screen reader user reviewing the compliance table could
/// not tell an approved attendee from a rejected one.
class CheckIcon extends StatelessWidget {
  const CheckIcon(this.value, {super.key, required this.label});

  final bool value;

  /// What the mark is about, e.g. `'Attended'`. Rendered as "Attended: yes".
  final String label;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).portal;
    return Semantics(
      label: '$label: ${value ? 'yes' : 'no'}',
      excludeSemantics: true,
      child: Icon(
        value ? Icons.check_circle : Icons.cancel,
        color: value ? colors.success : colors.danger,
        size: 20,
      ),
    );
  }
}

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

// ─────────────────────────────────────────────────────────────────────────────
// Errors
// ─────────────────────────────────────────────────────────────────────────────

/// In-form error text.
///
/// Replaces the bare red `Text(error!)` that appeared on 39 pages. Two things
/// were wrong with that: it was invisible to screen readers (no live region, no
/// announcement), and colour was the only thing marking it as an error. This
/// adds both an icon and a live region.
class FormErrorText extends StatelessWidget {
  const FormErrorText(this.message, {super.key});

  final String message;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Semantics(
      liveRegion: true,
      container: true,
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          ExcludeSemantics(
            child: Icon(Icons.error_outline, size: 18, color: theme.portal.danger),
          ),
          const SizedBox(width: Space.xs - 2),
          Expanded(
            child: Text(
              message,
              style: theme.textTheme.bodySmall?.copyWith(color: theme.portal.danger),
            ),
          ),
        ],
      ),
    );
  }
}

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
    final theme = Theme.of(context);
    final colors = theme.portal;
    return Semantics(
      liveRegion: true,
      container: true,
      child: Container(
        margin: const EdgeInsets.only(bottom: Space.sm + 2),
        padding: const EdgeInsets.symmetric(horizontal: Space.md - 2, vertical: Space.xs + 2),
        decoration: BoxDecoration(
          color: colors.dangerSurface,
          borderRadius: BorderRadius.circular(Radii.md),
          border: Border.all(color: colors.dangerOutline),
        ),
        child: Row(
          children: [
            ExcludeSemantics(
              child: Icon(Icons.error_outline, color: colors.danger, size: 20),
            ),
            const SizedBox(width: Space.xs + 2),
            Expanded(
              child: Text(
                _humanize(message),
                style: theme.textTheme.bodySmall?.copyWith(color: colors.danger),
              ),
            ),
            if (onRetry != null) TextButton(onPressed: onRetry, child: const Text('Retry')),
            if (onDismiss != null)
              IconButton(
                onPressed: onDismiss,
                icon: Icon(Icons.close, size: 17, color: colors.danger),
                tooltip: 'Dismiss',
              ),
          ],
        ),
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

// ─────────────────────────────────────────────────────────────────────────────
// Action menu
// ─────────────────────────────────────────────────────────────────────────────

/// One row in an [ActionMenu]. A `null` entry in the list renders a separator.
class MenuAction {
  const MenuAction(this.label, this.onSelected, {this.destructive = false});

  final String label;
  final VoidCallback onSelected;

  /// Renders the label in the danger colour — for "Remove all attendees" and
  /// friends, which revoke live certificates.
  final bool destructive;
}

/// A drop-down of secondary actions behind a real, keyboard-operable button.
///
/// Replaces `PopupMenuButton(child: IgnorePointer(child: OutlinedButton(
/// onPressed: () {})))`. `IgnorePointer` blocks pointers but *not* focus, so
/// tabbing landed on an enabled button labelled "Bulk actions" whose
/// `onPressed` did nothing — and that button is the entry point to Approve all
/// / Generate all / Send all / Remove all attendees. A keyboard user pressed
/// Enter, got silence, and reasonably concluded the feature was broken.
///
/// [MenuAnchor] keeps one focus stop, opens on Enter or Space, walks the items
/// with the arrow keys, and closes on Escape.
class ActionMenu extends StatelessWidget {
  const ActionMenu({
    super.key,
    required this.label,
    required this.icon,
    required this.actions,
    this.enabled = true,
  });

  final String label;
  final Widget icon;
  final List<MenuAction?> actions;
  final bool enabled;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).portal;
    return MenuAnchor(
      menuChildren: [
        for (final action in actions)
          if (action == null)
            const Divider(height: Space.xs, color: border)
          else
            MenuItemButton(
              onPressed: action.onSelected,
              child: Text(
                action.label,
                style: action.destructive ? TextStyle(color: colors.danger) : null,
              ),
            ),
      ],
      builder: (context, controller, child) => OutlinedButton.icon(
        onPressed: enabled
            ? () => controller.isOpen ? controller.close() : controller.open()
            : null,
        icon: icon,
        label: Text(label),
      ),
    );
  }
}

/// One recipient's outcome from a bulk operation (invites, certificate email).
///
/// Mirrors the backend's per-recipient distribution report. `retryable`
/// separates a delivery failure — worth pressing Retry — from a missing email
/// address, which needs the roster corrected first, so the dialog can tell the
/// admin which of the two problems they actually have.
typedef BulkOutcome = ({
  String name,
  String? email,
  String status,
  String? reason,
  bool retryable,
});

/// Shows the itemized result of a bulk operation and returns the recipients the
/// admin asked to retry, or null if they didn't.
///
/// Replaces the snackbar this used to be. "3 failed" that disappears after four
/// seconds, with no names and no way to act, is indistinguishable from silence:
/// the admin knows something went wrong for someone and has no route to finding
/// out who. Successes stay collapsed to a count — it is the problems that need
/// the room.
Future<List<BulkOutcome>?> showBulkResultDialog(
  BuildContext context, {
  required String title,
  required int sent,
  required List<BulkOutcome> outcomes,
}) {
  final problems = outcomes.where((outcome) => outcome.status != 'sent').toList();
  final retryable = problems.where((outcome) => outcome.retryable).toList();
  return showDialog<List<BulkOutcome>>(
    context: context,
    builder: (dialogContext) {
      final theme = Theme.of(dialogContext);
      final colors = theme.portal;
      return AlertDialog(
        title: Text(title),
        content: ConstrainedBox(
          // Bounded so a 200-person event scrolls inside the dialog instead of
          // growing it past the viewport.
          constraints: const BoxConstraints(maxWidth: 520, maxHeight: 420),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                '$sent sent successfully.',
                style: theme.textTheme.bodyMedium?.copyWith(color: colors.success),
              ),
              if (problems.isEmpty)
                Padding(
                  padding: const EdgeInsets.only(top: Space.sm),
                  child: Text('Nothing needed attention.', style: theme.textTheme.bodyMedium),
                )
              else ...[
                const SizedBox(height: Space.md),
                Text(
                  '${problems.length} need${problems.length == 1 ? 's' : ''} attention',
                  style: theme.textTheme.titleSmall,
                ),
                const SizedBox(height: Space.xs),
                Flexible(
                  child: ListView.separated(
                    shrinkWrap: true,
                    itemCount: problems.length,
                    separatorBuilder: (_, __) => divider,
                    itemBuilder: (_, index) {
                      final outcome = problems[index];
                      return Padding(
                        padding: const EdgeInsets.symmetric(vertical: Space.xs),
                        child: Row(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            StatusBadge(
                              outcome.status.toUpperCase(),
                              tone: outcome.status == 'failed' ? BadgeTone.danger : BadgeTone.warning,
                            ),
                            const SizedBox(width: Space.sm),
                            Expanded(
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Text(outcome.name, style: theme.textTheme.bodyMedium),
                                  if (outcome.email != null && outcome.email!.isNotEmpty)
                                    Text(
                                      outcome.email!,
                                      style: theme.textTheme.labelSmall
                                          ?.copyWith(color: colors.textTertiary),
                                    ),
                                  if (outcome.reason != null)
                                    Text(
                                      outcome.reason!,
                                      style: theme.textTheme.labelSmall
                                          ?.copyWith(color: colors.textSecondary),
                                    ),
                                ],
                              ),
                            ),
                          ],
                        ),
                      );
                    },
                  ),
                ),
              ],
            ],
          ),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(dialogContext), child: const Text('Close')),
          if (retryable.isNotEmpty)
            ElevatedButton.icon(
              onPressed: () => Navigator.pop(dialogContext, retryable),
              icon: const Icon(Icons.refresh),
              label: Text('Retry ${retryable.length}'),
            ),
        ],
      );
    },
  );
}
